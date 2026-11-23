import json
from datetime import date
import pytest
from monitor import db, analyzer, report
from monitor.classify import classify
from monitor.config import load
from monitor.models import Offer
from monitor.collectors.mercadolivre import MercadoLivre
from monitor.collectors.generic import Generic
from monitor.telegram_bot import Telegram, handle_commands
from monitor import main

CFG = load()


# ---------- classificador ----------
@pytest.mark.parametrize("title,expected", [
    ("Console PlayStation 5 Slim Digital 1TB Sony", ("ps5", "Slim Digital")),
    ("Console PS5 Slim com Leitor de Disco 1TB", ("ps5", "Slim com leitor")),
    ("Playstation 5 Pro 2TB", ("ps5", "Pro")),
    ("Console PS5 Slim + Astro Bot", ("ps5", "Slim (bundle)")),
    ("Controle DualSense PS5 Branco", None),
    ("Suporte Vertical para Console PS5 Slim", None),
    ("Console PS5 Slim Usado", None),
    ("Jogo FIFA 25 PS5", None),
    ("Console Xbox Series X", None),
])
def test_classify_ps5(title, expected):
    r = classify(title)
    assert (r[:2] if r else None) == expected


def test_classify_gta():
    assert classify("GTA 6 PS5 Mídia Física", "2026-11-19", date(2026, 11, 23))[:3] == ("gta6", "Standard Fisica", "disponivel")
    assert classify("Grand Theft Auto VI Ultimate PS5 Código Digital")[1] == "Ultimate Digital"
    assert classify("GTA 6 PS5 Pré-venda", "2026-11-19", date(2026, 11, 23))[2] == "pre_venda"
    assert classify("GTA 6 PS5", "2026-11-19", date(2026, 11, 1))[2] == "pre_venda"
    assert classify("GTA 6 Xbox Series") is None
    assert classify("Camiseta GTA 6") is None


# ---------- Mercado Livre ----------
ML = {"results": [
    {"id": "MLB1", "title": "Console PlayStation 5 Slim Digital", "price": 4200, "condition": "new",
     "permalink": "https://produto.mercadolivre.com.br/MLB-1", "official_store_id": 7,
     "installments": {"quantity": 10, "amount": 420, "rate": 0}, "shipping": {"free_shipping": True},
     "seller": {"id": 1, "nickname": "SONY"}},
    {"id": "MLB2", "title": "Console PS5 Slim Leitor", "price": 4300, "condition": "new",
     "permalink": "https://produto.mercadolivre.com.br/MLB-2",
     "installments": {"quantity": 12, "amount": 400, "rate": 0.2}, "shipping": {"free_shipping": False},
     "seller": {"id": 2, "nickname": "LOJA", "seller_reputation": {"level_id": "5_green", "power_seller_status": "gold"}}},
]}


def test_ml_parse():
    o = MercadoLivre().parse(ML)
    assert o[0].trust == "oficial" and o[0].interest_free is True and o[0].shipping == 0.0
    assert o[1].interest_free is False and o[1].trust == "bom" and o[1].shipping is None


# ---------- generico ----------
HTML = """<html><script type="application/ld+json">
{"@type":"ItemList","itemListElement":[
 {"@type":"Product","name":"Console PlayStation 5 Slim Digital","url":"/p/ps5-digital",
  "offers":{"@type":"Offer","price":"4.199,90","availability":"https://schema.org/InStock",
            "seller":{"name":"Magazine Luiza"},"description":"10x de R$ 419,99 sem juros"}},
 {"@type":"Product","name":"Console PS5 Pro","url":"/p/pro","offers":{"price":"6999.00","availability":"OutOfStock"}}]}
</script></html>"""


def test_generic_parse():
    g = Generic({"nome": "Magazine Luiza", "url": "x"})
    offers = g.parse(HTML, "https://www.magazineluiza.com.br/busca/x/")
    assert len(offers) == 1
    o = offers[0]
    assert o.price == 4199.90 and o.url.startswith("https://www.magazineluiza.com.br/p/")
    assert o.inst_n == 10 and o.interest_free is True and o.trust == "oficial" and o.marketplace is False


def test_generic_blocked(monkeypatch):
    from monitor.collectors import generic
    from monitor.collectors.base import Blocked

    class R:
        status_code = 200
        text = "Please solve the CAPTCHA"
    monkeypatch.setattr(generic, "get", lambda *a, **k: R())
    g = Generic({"nome": "X", "url": "https://x.com/{q}", "sep": "+"}, respect_robots=False)
    with pytest.raises(Blocked):
        g.collect(["ps5"])


# ---------- analisador ----------
def O(store, prod, var, price, n=None, free=None, ship=0.0, trust="oficial", av="disponivel", url=None):
    return Offer(store=store, title=var, url=url or f"https://{store}/{prod}/{price}", price=price, product=prod,
                 variant=var, shipping=ship, inst_n=n, inst_amount=(price / n if n else None),
                 interest_free=free, trust=trust, availability=av, new_condition=True)


def test_budget_never_exceeded():
    offers = [O("A", "ps5", "Slim Digital", 4300, 10, True), O("B", "gta6", "Standard Fisica", 440, 10, True)]
    a = analyzer.analyze(offers, CFG)
    assert len(a.combos_ok) == 1
    c = a.combos_ok[0]
    assert round(c.monthly, 2) == 474.0 and c.monthly <= 500
    # parcelas menores (6x) estouram 500 => nao recomendado
    a2 = analyzer.analyze([O("A", "ps5", "Slim Digital", 4300, 6, True), O("B", "gta6", "Standard Fisica", 440, 6, True)], CFG)
    assert a2.combos_ok == []


def test_unverified_installments_not_recommended():
    offers = [O("A", "ps5", "Slim Digital", 4000, None, None), O("B", "gta6", "Standard Fisica", 440, 10, True)]
    a = analyzer.analyze(offers, CFG)
    assert a.combos_ok == [] and len(a.combos_unverified) == 1
    assert "NÃO VERIFICADO" in report.parcel_txt(a.ps5[0])


def test_screen_filters():
    offers = [O("A", "ps5", "Slim", 1500, 10, True),                    # preco baixo nao e descartado por piso arbitrario
              O("B", "ps5", "Slim", 4000, 10, True, trust="desconhecido"),  # vendedor sem reputacao
              O("C", "ps5", "Slim", 4100, 10, True),
              O("C", "ps5", "Slim", 4100, 10, True, url="https://C/outra-url")]  # duplicado
    ok, rej = analyzer.screen(offers, CFG)
    assert [o.store for o in ok] == ["A", "C"]
    assert rej["duplicado"] == 1 and rej["vendedor nao confiavel/verificado"] == 1


def test_unknown_shipping_is_estimated():
    p = analyzer.make_plan(O("A", "ps5", "Slim", 4000, 10, True, ship=None), CFG)
    assert p.shipping == 40 and not p.shipping_known and round(p.parcela, 2) == 404.0


# ---------- banco ----------
def test_db_history(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    o = O("A", "ps5", "Slim Digital", 4300, 10, True)
    r1 = db.upsert_offer(conn, o)
    db.upsert_offer(conn, o)  # sem mudanca: nao duplica historico
    o2 = O("A", "ps5", "Slim Digital", 4200, 10, True, url=o.url)
    r3 = db.upsert_offer(conn, o2)
    assert r1["is_new"] and r3["price_changed"]
    assert conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 2
    assert conn.execute("SELECT min_price FROM offers").fetchone()[0] == 4200


# ---------- Telegram + notificacoes ----------
class FakeTG(Telegram):
    def __init__(self, updates=None):
        super().__init__("tok", "123")
        self.sent, self._u = [], updates or []

    def send(self, text):
        self.sent.append(text); return True

    def send_photo(self, *a, **k):
        self.sent.append("[foto]")

    def updates(self, offset=None):
        return [u for u in self._u if not offset or u["update_id"] >= offset]


def test_notify_dedupe(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    for o in (O("A", "ps5", "Slim Digital", 4300, 10, True), O("B", "gta6", "Standard Fisica", 429, 10, True)):
        db.upsert_offer(conn, o)
    tg = FakeTG()
    a = analyzer.analyze(db.active_offers(conn, 6), CFG)
    assert main.notify(conn, CFG, tg, a) == 3          # ps5 + gta6 + combo
    assert main.notify(conn, CFG, tg, a) == 0          # repetir nao duplica
    db.upsert_offer(conn, O("A", "ps5", "Slim Digital", 4100, 10, True))
    a = analyzer.analyze(db.active_offers(conn, 6), CFG)
    assert main.notify(conn, CFG, tg, a) == 2          # queda >2%: oferta + combo
    assert any("abaixo da meta" in m for m in tg.sent)


def test_above_target_no_alert(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.upsert_offer(conn, O("A", "gta6", "Standard Fisica", 449.90, 10, True))
    a = analyzer.analyze(db.active_offers(conn, 6), CFG)
    assert main.notify(conn, CFG, FakeTG(), a) == 0


def test_commands(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.upsert_offer(conn, O("A", "ps5", "Slim Digital", 4300, 10, True))
    msg = lambda i, t, chat=123: {"update_id": i, "message": {"chat": {"id": chat}, "text": t}}
    tg = FakeTG([msg(1, "/start"), msg(2, "/ajuda"), msg(3, "/status"), msg(4, "/precos"), msg(5, "/precos", chat=999)])
    b = {"status": lambda: main.status_text(conn, CFG),
         "precos": lambda: report.precos_msg(analyzer.analyze(db.active_offers(conn, 6), CFG), CFG)}
    assert handle_commands(conn, tg, CFG, b) == 4      # chat 999 ignorado
    assert len(tg.sent) == 4 and "PS5" in tg.sent[3]
    assert handle_commands(conn, tg, CFG, b) == 0      # offset salvo: nao reprocessa


def test_full_run_with_fake_collector(tmp_path):
    class Fake:
        name = "Fake"
        def collect(self, q):
            return [Offer(store="Fake", title="Console PlayStation 5 Slim Digital", url="https://f/1", price=4200,
                          shipping=0.0, new_condition=True, inst_n=10, inst_amount=420, interest_free=True, trust="oficial"),
                    Offer(store="Fake", title="GTA 6 PS5 Mídia Física", url="https://f/2", price=419,
                          shipping=0.0, new_condition=True, inst_n=10, inst_amount=41.9, interest_free=True, trust="oficial"),
                    Offer(store="Fake", title="Controle DualSense", url="https://f/3", price=300, new_condition=True)]
    tg = FakeTG()
    a = main.run_once(collectors=[Fake()], cfg=CFG, db_path=tmp_path / "r.db", tg=tg)
    assert len(a.ps5) == 1 and len(a.gta6) == 1 and len(a.combos_ok) == 1
    assert a.combos_ok[0].monthly <= 500 and len(tg.sent) == 3


def test_ml_missing_interest_rate_is_not_verified():
    data = {"results": [{"id": "MLB3", "title": "Console PlayStation 5 Slim", "price": 4000,
        "condition": "new", "permalink": "https://produto.mercadolivre.com.br/MLB-3",
        "installments": {"quantity": 10, "amount": 400}, "shipping": {"free_shipping": True},
        "official_store_id": 1, "seller": {"id": 3, "nickname": "OFICIAL"}}]}
    assert MercadoLivre().parse(data)[0].interest_free is None


def test_inconsistent_installments_are_not_verified():
    offer = O("A", "ps5", "Slim", 4000, 12, True)
    offer.inst_amount = 100
    plan = analyzer.make_plan(offer, CFG)
    assert plan.verified is False and plan.n == 1


def test_unknown_seller_and_unknown_condition_rejected():
    unknown_seller = O("A", "ps5", "Slim", 4000, 10, True, trust="verificar")
    unknown_condition = O("B", "ps5", "Slim", 4100, 10, True)
    unknown_condition.new_condition = None
    ok, rejected = analyzer.screen([unknown_seller, unknown_condition], CFG)
    assert ok == []
    assert rejected["vendedor nao confiavel/verificado"] == 1
    assert rejected["condicao nova nao confirmada"] == 1


def test_unknown_shipping_combo_not_confirmed():
    ps5 = O("A", "ps5", "Slim", 4300, 12, True, ship=None)
    gta = O("B", "gta6", "Standard", 440, 12, True, ship=0.0)
    analysis = analyzer.analyze([ps5, gta], CFG)
    assert analysis.combos_ok == []
    assert len(analysis.combos_unverified) == 1


def test_generic_installments_need_exact_sum_and_condition():
    html = '<script type="application/ld+json">{"@type":"Product","name":"Console PlayStation 5 Slim","url":"/p/1","itemCondition":"https://schema.org/NewCondition","offers":{"price":"4000.00","url":"/p/1","seller":{"name":"Loja X"},"description":"12x de R$ 100,00 sem juros"}}</script>'
    offer = Generic({"nome":"Loja X", "url":"x"}).parse(html, "https://loja.com")[0]
    assert offer.interest_free is False
    assert offer.new_condition is True


def test_generic_direct_store_can_assume_new_catalog():
    html = '<script type="application/ld+json">{"@type":"Product","name":"Console PlayStation 5 Slim Digital","url":"/p/1","offers":{"price":"4200.00","url":"/p/1"}}</script>'
    cfg = {"nome":"Pichau", "url":"x", "assume_first_party_if_missing":True, "assume_new_if_missing":True}
    offer = Generic(cfg).parse(html, "https://www.pichau.com.br")[0]
    assert offer.trust == "oficial" and offer.new_condition is True


def test_unknown_shipping_estimate_is_included_in_meta_alert(tmp_path):
    conn = db.connect(tmp_path / "freight.db")
    offer = O("A", "ps5", "Slim", 4320, 12, True, ship=None)
    db.upsert_offer(conn, offer)
    analysis = analyzer.analyze(db.active_offers(conn, 6), CFG)
    tg = FakeTG()
    assert main.notify(conn, CFG, tg, analysis) == 0  # 4320 + frete estimado 40 ultrapassa 4350


def test_extreme_outlier_price_is_flagged_only_with_comparison_set():
    offers = [O("A", "ps5", "Slim", 4200, 12, True), O("B", "ps5", "Slim", 4100, 12, True),
              O("C", "ps5", "Slim", 4300, 12, True), O("D", "ps5", "Slim", 4150, 12, True),
              O("E", "ps5", "Slim", 4250, 12, True), O("F", "ps5", "Slim", 500, 12, True)]
    ok, rejected = analyzer.screen(offers, CFG)
    assert len(ok) == 5
    assert rejected["preco extremamente abaixo da referencia"] == 1
