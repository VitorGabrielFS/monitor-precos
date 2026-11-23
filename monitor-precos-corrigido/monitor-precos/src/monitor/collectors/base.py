import logging
import time
import requests

log = logging.getLogger("monitor")
UA = "Mozilla/5.0 (compatible; PriceMonitorBot/1.0; uso pessoal; sem contornar protecoes)"
BLOCK_MARKERS = ("captcha", "robot check", "unusual traffic", "are you a human", "acesso negado", "access denied")


class Blocked(Exception):
    """A loja bloqueou/protegeu a pagina. Nao tentamos contornar: apenas registramos."""


def get(url, session=None, params=None, headers=None, timeout=20, retries=2):
    s = session or requests
    h = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"}
    h.update(headers or {})
    last = None
    for i in range(retries + 1):
        try:
            r = s.get(url, params=params, headers=h, timeout=timeout)
            if r.status_code in (429, 503) and i < retries:
                time.sleep(2 * (i + 1))
                continue
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(1 + i)
    raise last or RuntimeError("falha de rede")


def parse_brl(v):
    """'1.299,90' | 1299.9 | 'R$ 1.299,90' -> float"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("R$", "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None
