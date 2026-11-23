"""Classifica titulos de anuncios: produto, variante, disponibilidade."""
import re
import unicodedata
from datetime import date


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


HARD_BAD = re.compile(r"\b(usad[oa]s?|seminov[oa]s?|vitrine|mostruario|openbox|open box|recondicionad[oa]s?|defeito|sucata|retirada de pecas|ps4|ps3|xbox|nintendo|switch|pc)\b")
GTA = re.compile(r"\b(gta ?(6|vi)|grand theft auto ?(6|vi))\b")
CONSOLE = re.compile(r"\b(console|slim)\b|\b(ps5|playstation ?5) ?(pro|digital)\b")
FOR_CONSOLE = re.compile(r"\b(para|p/|pra|compativel com)\s+(o\s+)?(console|ps5|playstation)")
ACC_START = re.compile(r"^(suporte|capa|case|skin|cabo|carregador|cooler|bolsa|mochila|adesivo|pelicula|headset|fone|controle|dualsense|base|kit de|ssd|hd|cartao|gift|volante|cadeira|rack)\b")
ACC_GTA = re.compile(r"\b(controle|dualsense|camiseta|poster|boneco|action figure|livro|guia|caneca|quadro|miniatura)\b")
PREORDER = re.compile(r"pre[- ]?venda|pre[- ]?order|preorder|reserva\b")
SOLD_OUT = re.compile(r"\b(esgotado|indisponivel|sem estoque)\b")
BUNDLE = re.compile(r"\+|\bbundle\b|\bcombo\b|\bkit\b|\bjogos?\b|astro bot|god of war|spider|\bgta\b|\bfc ?\d|fifa|call of duty|returnal|2 controles")


def classify(title: str, release_date: str | None = None, today: date | None = None):
    """Retorna (product, variant, availability) ou None se nao for alvo."""
    t = norm(title)
    if HARD_BAD.search(t) or SOLD_OUT.search(t):
        return None
    if GTA.search(t) and not re.search(r"\b(console|slim)\b", t):
        if ACC_GTA.search(t):
            return None
        ed = "Ultimate" if re.search(r"\b(ultimate|deluxe|collector)\b", t) else "Standard"
        if re.search(r"codigo|digital|psn|download", t) and not re.search(r"fisic|disco", t):
            fmt = "Digital"
        elif re.search(r"fisic|midia|disco|caixa", t):
            fmt = "Fisica"
        else:
            fmt = "Fisica/Digital?"
        return "gta6", f"{ed} {fmt}", _availability(t, release_date, today)
    if CONSOLE.search(t):
        if FOR_CONSOLE.search(t) or ACC_START.search(t):
            return None
        if not re.search(r"\b(ps5|playstation ?5)\b", t):
            return None
        if re.search(r"\bpro\b", t):
            base = "Pro"
        elif re.search(r"\bdigital\b", t) and not re.search(r"leitor|disco|midia fisica", t):
            base = "Slim Digital"
        elif re.search(r"leitor|disco|midia fisica", t):
            base = "Slim com leitor"
        else:
            base = "Slim"
        if BUNDLE.search(t):
            base += " (bundle)"
        return "ps5", base, "disponivel"
    return None


def _availability(t, release_date, today):
    if PREORDER.search(t):
        return "pre_venda"
    if release_date:
        today = today or date.today()
        if today < date.fromisoformat(str(release_date)):
            return "pre_venda"
    return "disponivel"
