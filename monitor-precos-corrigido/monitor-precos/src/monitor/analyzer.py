"""Filtros de confianca + analise financeira (parcelas sem juros, combinacoes, rankings)."""
from dataclasses import dataclass, field
from statistics import median
from .models import Offer, TRUST_OK, RISK


@dataclass
class Plan:
    offer: Offer
    shipping: float
    shipping_known: bool
    total: float          # preco + frete (a vista / custo total sem juros)
    n: int                # numero de parcelas VERIFICADAS sem juros (1 = nao verificado)
    parcela: float
    verified: bool
    risk: float

    @property
    def score(self):      # custo ajustado por risco (menor = melhor)
        return self.total * (1 + self.risk)


@dataclass
class Combo:
    ps5: Plan
    gta: Plan
    monthly: float
    total: float
    score: float
    same_store: bool
    feasible: bool


@dataclass
class Analysis:
    ps5: list = field(default_factory=list)
    gta6: list = field(default_factory=list)
    rejected: dict = field(default_factory=dict)
    combos_ok: list = field(default_factory=list)
    combos_unverified: list = field(default_factory=list)

    def rank(self, key, n=3):
        keys = {"total": lambda c: c.total, "parcela": lambda c: c.monthly, "custo_beneficio": lambda c: c.score}
        return sorted(self.combos_ok, key=keys[key])[:n]


def screen(offers, cfg):
    """Remove duplicados, usados/desconhecidos e vendedores sem reputacao confirmada.
    Precos baixos nao sao descartados por piso fixo: podem ser promocoes reais."""
    rejected, ok, seen = {}, [], set()
    def rej(reason):
        rejected[reason] = rejected.get(reason, 0) + 1
    medians = {}
    for product in ("ps5", "gta6"):
        variants = {o.variant for o in offers if o.product == product}
        for variant in variants:
            prices = [o.price for o in offers if o.product == product and o.variant == variant and o.price > 0]
            if len(prices) >= 5:
                medians[(product, variant)] = median(prices)
    suspicious_ratio = float(cfg.get("preco_suspeito_ratio", 0.25))
    for o in sorted(offers, key=lambda x: x.price):
        sig = (o.store, o.seller, round(o.price, 2), o.variant)
        if o.key in seen or sig in seen:
            rej("duplicado"); continue
        seen.add(o.key); seen.add(sig)
        if o.price <= 0:
            rej("preco invalido"); continue
        reference = medians.get((o.product, o.variant))
        if reference and o.price < reference * suspicious_ratio:
            rej("preco extremamente abaixo da referencia"); continue
        if o.new_condition is not True:
            rej("condicao nova nao confirmada"); continue
        if o.trust not in TRUST_OK:
            rej("vendedor nao confiavel/verificado"); continue
        ok.append(o)
    return ok, rejected


def _installments_verified(o: Offer, cfg) -> bool:
    if o.interest_free is not True or not o.inst_n or not o.inst_amount:
        return False
    if o.inst_n < 2 or o.inst_n > int(cfg.get("parcelas_max", 12)) or o.inst_amount <= 0:
        return False
    return abs(o.inst_n * o.inst_amount - o.price) <= max(2.0, o.price * 0.01)


def make_plan(o: Offer, cfg) -> Plan:
    if o.shipping is not None:
        ship, known = max(0.0, float(o.shipping)), True
    elif o.free_shipping is True:
        ship, known = 0.0, True
    else:
        ship, known = float(cfg.get("frete_estimado_se_desconhecido", 0)), False
    total = o.price + ship
    verified = _installments_verified(o, cfg)
    n = min(o.inst_n, cfg.get("parcelas_max", 12)) if verified else 1
    return Plan(o, ship, known, total, n, total / n, verified, RISK.get(o.trust, 0.1))

def analyze(offers, cfg) -> Analysis:
    ok, rejected = screen(offers, cfg)
    a = Analysis(rejected=rejected)
    plans = [make_plan(o, cfg) for o in ok]
    a.ps5 = sorted([p for p in plans if p.offer.product == "ps5"], key=lambda p: p.total)
    a.gta6 = sorted([p for p in plans if p.offer.product == "gta6"], key=lambda p: p.total)
    k = cfg.get("top_k_combinacoes", 15)

    def pool(ps):
        by_total = ps[:k]
        by_parc = sorted([p for p in ps if p.verified], key=lambda p: p.parcela)[:k]
        return {id(p): p for p in by_total + by_parc}.values()

    budget = cfg["orcamento_mensal_max"]
    for x in pool(a.ps5):
        for y in pool(a.gta6):
            monthly, total = x.parcela + y.parcela, x.total + y.total
            verified = x.verified and y.verified
            c = Combo(x, y, monthly, total, x.score + y.score,
                      x.offer.store == y.offer.store, verified and x.shipping_known and y.shipping_known and monthly <= budget)
            if c.feasible:
                a.combos_ok.append(c)
            else:
                a.combos_unverified.append(c)
    return a
