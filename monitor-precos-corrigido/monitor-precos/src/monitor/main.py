import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from . import db, analyzer, report, charts
from .classify import classify
from .config import load, DB_PATH, ROOT
from .collectors.base import Blocked
from .collectors.generic import Generic
from .collectors.mercadolivre import MercadoLivre
from .telegram_bot import Telegram, handle_commands

log = logging.getLogger("monitor")


def collect_all(conn, cfg, collectors=None):
    """Roda cada loja isolada: erro/bloqueio em uma nao afeta as outras."""
    queries = {k: v["consultas"] for k, v in cfg["produtos"].items()}
    allq = [q for qs in queries.values() for q in qs]
    if collectors is None:
        collectors = []
        for st in cfg["lojas"]:
            if not st.get("ativo", True):
                continue
            collectors.append(MercadoLivre() if st["tipo"] == "ml"
                              else Generic(st, respect_robots=cfg.get("respeitar_robots_txt", True)))
    total = 0
    successful = 0
    attempted = 0
    for c in collectors:
        attempted += 1
        try:
            raw = c.collect(allq)
            n = 0
            for o in raw:
                res = classify(o.title, cfg["produtos"]["gta6"].get("data_lancamento"))
                if not res:
                    continue
                o.product, o.variant, av = res
                if av == "pre_venda":
                    o.availability = "pre_venda"
                db.upsert_offer(conn, o)
                n += 1
            db.log_run(conn, c.name, "ok", n)
            successful += 1
            log.info("%s: %d ofertas relevantes", c.name, n)
            total += n
        except Blocked as e:
            db.log_run(conn, c.name, "bloqueada", 0, str(e))
            log.warning("%s: %s", c.name, e)
        except Exception as e:
            db.log_run(conn, c.name, "erro", 0, repr(e))
            log.exception("%s: erro", c.name)
    db.set_meta(conn, "last_collection_success_count", successful)
    db.set_meta(conn, "last_collection_attempt_count", attempted)
    return total


def notify(conn, cfg, tg, a):
    sent = 0
    drop = 1 - cfg.get("renotificar_queda_minima_pct", 2) / 100
    max_alerts = max(1, int(cfg.get("max_alertas_por_produto", 2)))
    def should(dk, price):
        last = db.last_notification(conn, dk)
        return last is None or price <= last["price"] * drop
    for key in ("ps5", "gta6"):
        meta = cfg["produtos"][key]["meta"]
        candidates = [p for p in getattr(a, key) if p.total < meta]
        candidates.sort(key=lambda p: (p.total, p.parcela, p.risk))
        count = 0
        for p in candidates:
            if count >= max_alerts:
                break
            price_final = p.total  # inclui frete estimado se nao houver valor confirmado
            if should("offer:" + p.offer.key, price_final):
                row = conn.execute("SELECT MIN(price) m FROM price_history WHERE key IN "
                                   "(SELECT key FROM offers WHERE product=? AND variant=?) AND key<>?",
                                   (key, p.offer.variant, p.offer.key)).fetchone()
                new_min = row["m"] is None or p.offer.price < row["m"]
                tg.send(report.offer_alert(p, cfg["produtos"][key]["nome"], meta, new_min))
                db.add_notification(conn, "offer:" + p.offer.key, price_final)
                sent += 1
                count += 1
    ok = [c for c in a.combos_ok
          if c.ps5.total < cfg["produtos"]["ps5"]["meta"] and c.gta.total < cfg["produtos"]["gta6"]["meta"]]
    if ok:
        best = min(ok, key=lambda c: c.score)
        dk = f"combo:{best.ps5.offer.key}:{best.gta.offer.key}"
        if should(dk, best.total):
            tg.send("🎯 " + report.combo_text(best, "Melhor combinação dentro das metas e do orçamento"))
            db.add_notification(conn, dk, best.total)
            sent += 1
    return sent

def status_text(conn, cfg):
    last = conn.execute("SELECT MAX(ts) t FROM runs").fetchone()["t"]
    rows = conn.execute("SELECT r.store,r.status,r.n_offers,r.msg FROM runs r JOIN "
                        "(SELECT store, MAX(id) mid FROM runs GROUP BY store) m ON r.id=m.mid ORDER BY r.store").fetchall()
    n = len(db.active_offers(conn, cfg["validade_ofertas_horas"]))
    successes = int(db.get_meta(conn, "last_collection_success_count", 0) or 0)
    attempts = int(db.get_meta(conn, "last_collection_attempt_count", 0) or 0)
    lines = [f"<b>Status</b>\nÚltima execução: {last or 'nunca'} (UTC)\nOfertas ativas: {n}\nLojas com coleta concluída: {successes}/{attempts}"]
    icons = {"ok": "✅", "bloqueada": "🚫", "erro": "❌"}
    for r in rows:
        lines.append(f"{icons.get(r['status'], '•')} {r['store']}: {r['status']} ({r['n_offers']})"
                     + (f" – {r['msg'][:70]}" if r["status"] != "ok" else ""))
    for key in ("ps5", "gta6"):
        m = conn.execute("SELECT MIN(min_price) m FROM offers WHERE product=? AND trust IN ('oficial','bom')",
                         (key,)).fetchone()["m"]
        lines.append(f"Menor preço observado {cfg['produtos'][key]['nome']}: {report.brl(m) if m else '—'}")
    return "\n".join(lines)


def run_once(dry_run=False, collectors=None, cfg=None, db_path=None, tg=None):
    cfg = cfg or load()
    conn = db.connect(db_path or DB_PATH)
    tg = tg or Telegram()
    if dry_run:
        tg.token = ""  # nao envia nada
    current = lambda: analyzer.analyze(db.active_offers(conn, cfg["validade_ofertas_horas"]), cfg)
    builders = {
        "status": lambda: status_text(conn, cfg),
        "precos": lambda: report.precos_msg(current(), cfg),
        "charts": lambda: [p for p in (charts.chart_for(conn, k, cfg["produtos"][k]["nome"], cfg["produtos"][k]["meta"],
                                                         str(ROOT / "data" / "charts")) for k in ("ps5", "gta6")) if p],
    }
    try:
        handle_commands(conn, tg, cfg, builders)
    except Exception:
        log.exception("falha ao processar comandos do Telegram")
    collect_all(conn, cfg, collectors)
    a = current()
    sent = notify(conn, cfg, tg, a)
    log.info("Resumo: PS5=%d GTA6=%d combos_ok=%d rejeitados=%s notificacoes=%d", len(a.ps5), len(a.gta6),
             len(a.combos_ok), a.rejected, sent)
    return a


def cli(argv=None):
    ap = argparse.ArgumentParser(prog="monitor")
    ap.add_argument("comando", choices=["run"], help="executa uma rodada de coleta+analise+alertas")
    ap.add_argument("--dry-run", action="store_true", help="nao envia mensagens ao Telegram")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
        log.warning("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID ausentes: rodando sem enviar mensagens.")
    run_once(dry_run=args.dry_run)
    conn = db.connect(DB_PATH)
    successful = int(db.get_meta(conn, "last_collection_success_count", 0) or 0)
    attempted = int(db.get_meta(conn, "last_collection_attempt_count", 0) or 0)
    if attempted and successful == 0:
        log.error("Nenhuma loja conseguiu concluir a coleta; execucao marcada como falha.")
        return 2
    return 0
