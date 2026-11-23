"""Formatacao das mensagens (HTML do Telegram)."""
from html import escape


def brl(v):
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tag(p):
    o = p.offer
    t = []
    if o.availability == "pre_venda":
        t.append("⏳ PRÉ-VENDA")
    if o.marketplace:
        t.append("marketplace/" + (o.seller or "vendedor")[:25])
    if o.trust == "verificar":
        t.append("vendedor não verificado: confira se é vendido/entregue pela loja")
    if not p.shipping_known:
        t.append(f"frete não verificado (estimado {brl(p.shipping)})")
    return t


def parcel_txt(p):
    if p.verified:
        base = f"{p.n}x de {brl(p.offer.inst_amount)} sem juros no produto ✅"
        if p.shipping:
            base += f"; parcela estimada com frete: {brl(p.parcela)}"
        elif not p.shipping_known:
            base += f"; total estimado com frete: {brl(p.parcela)}/mês"
        return base
    return "parcelamento sem juros NÃO VERIFICADO"


def offer_line(p):
    o = p.offer
    s = f"<b>{escape(o.store)}</b> – {escape(o.variant)}: <b>{brl(o.price)}</b> + frete {brl(p.shipping)}"
    s += f"\n   {parcel_txt(p)}"
    tags = _tag(p)
    if tags:
        s += "\n   ⚠️ " + "; ".join(escape(t) for t in tags)
    return s + f'\n   <a href="{escape(o.url, quote=True)}">abrir oferta</a>'


def offer_alert(p, name, meta, new_min=False):
    head = f"🔔 <b>{escape(name)}</b> abaixo da meta ({brl(meta)})"
    if new_min:
        head += " – 🔥 menor preço já visto"
    return head + "\n" + offer_line(p)


def combo_text(c, title="Combinação"):
    return (f"<b>{title}</b>: {brl(c.total)} no total | parcela mensal estimada <b>{brl(c.monthly)}</b>\n"
            f"• PS5: {offer_line(c.ps5)}\n• GTA 6: {offer_line(c.gta)}"
            + ("\n(mesma loja: frete conjunto não verificado)" if c.same_store else ""))


def precos_msg(a, cfg):
    lines = []
    for key, p in (("ps5", "PS5"), ("gta6", "GTA 6")):
        plans = getattr(a, key)
        meta = cfg["produtos"][key]["meta"]
        lines.append(f"<b>{p}</b> (meta &lt; {brl(meta)})")
        if not plans:
            lines.append("  nenhuma oferta confiável encontrada")
        for pl in plans[:3]:
            lines.append(offer_line(pl))
        lines.append("")
    names = {"total": "Menor preço total", "parcela": "Menor parcela", "custo_beneficio": "Melhor custo-benefício"}
    if a.combos_ok:
        seen = set()
        for k, nm in names.items():
            c = a.rank(k, 1)[0]
            if id(c) in seen and k != "total":
                lines.append(f"<b>{nm}</b>: mesma combinação acima")
                continue
            seen.add(id(c))
            lines.append(combo_text(c, nm))
    else:
        lines.append(f"Nenhuma combinação com parcelas sem juros VERIFICADAS dentro de {brl(cfg['orcamento_mensal_max'])}/mês.")
    return "\n".join(lines)[:3900]
