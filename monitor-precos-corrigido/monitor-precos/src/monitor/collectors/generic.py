"""Coletor best-effort de dados estruturados publicamente expostos nas lojas.
Nao contorna bloqueios; robots.txt e tratado de forma conservadora."""
import json
import re
import logging
from urllib import robotparser
from urllib.parse import quote, urlparse, urljoin
import requests
from ..models import Offer
from .base import get, Blocked, BLOCK_MARKERS, parse_brl, UA

log = logging.getLogger("monitor")
INST_RE = re.compile(r"(\d{1,2})\s*x\s*(?:de\s*)?R?\$?\s*([\d\.]+,\d{2})\s*(sem juros|com juros)", re.I)

class Generic:
    def __init__(self, store, session=None, respect_robots=True):
        self.cfg = store
        self.name = store["nome"]
        self.s = session or requests.Session()
        self.respect_robots = respect_robots
        self._robots = {}

    def _allowed(self, url):
        if not self.respect_robots:
            return True
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self._robots:
            try:
                r = get(f"{origin}/robots.txt", session=self.s, retries=0, timeout=10)
                if r.status_code in (404, 410):
                    self._robots[origin] = True
                elif r.status_code >= 400:
                    self._robots[origin] = False
                else:
                    rp = robotparser.RobotFileParser()
                    rp.parse(r.text.splitlines())
                    self._robots[origin] = rp
            except Exception:
                self._robots[origin] = False
        rule = self._robots[origin]
        if rule is True:
            return True
        if rule is False:
            return False
        return rule.can_fetch(UA, url)

    def collect(self, queries):
        out = []
        for q in queries:
            url = self.cfg["url"].format(q=quote(q).replace("%20", self.cfg.get("sep", "+")))
            if not self._allowed(url):
                raise Blocked("robots.txt nao permite a busca automatizada ou nao foi possivel confirmar permissao")
            r = get(url, session=self.s)
            if r.status_code in (401, 403, 429) or any(m in r.text[:5000].lower() for m in BLOCK_MARKERS):
                raise Blocked(f"protecao anti-bot (HTTP {r.status_code}); nao contornamos")
            r.raise_for_status()
            out += self.parse(r.text, url)
        return out

    def parse(self, html, base_url=""):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        blobs = []
        for sc in soup.find_all("script"):
            if sc.get("type") == "application/ld+json" or sc.get("id") == "__NEXT_DATA__":
                try:
                    blobs.append(json.loads(sc.string or sc.get_text() or ""))
                except (ValueError, TypeError):
                    continue
        seen, offers = set(), []
        for blob in blobs:
            for d in _walk(blob):
                for offer in self._to_offers(d, base_url):
                    if offer.key not in seen:
                        seen.add(offer.key)
                        offers.append(offer)
        return offers

    def _to_offers(self, d, base_url):
        title = d.get("name") or d.get("title")
        if not isinstance(title, str):
            return []
        raw_offers = d.get("offers")
        offer_list = raw_offers if isinstance(raw_offers, list) else [raw_offers or {}]
        results = []
        for offer in offer_list:
            if not isinstance(offer, dict):
                continue
            price = None
            for value in (offer.get("price"), offer.get("lowPrice"), d.get("price"), d.get("lowPrice"),
                          d.get("sellingPrice"), d.get("salePrice"), d.get("bestPrice")):
                price = parse_brl(value)
                if price and price > 0:
                    break
            url = offer.get("url") or d.get("url") or d.get("link") or ""
            if not price or not url:
                continue
            url = urljoin(base_url, url)
            if urlparse(url).scheme not in ("http", "https"):
                continue
            avail = str(offer.get("availability", d.get("availability", ""))).lower()
            if "outofstock" in avail or "soldout" in avail:
                continue
            text = json.dumps(d, ensure_ascii=False) + " " + json.dumps(offer, ensure_ascii=False)
            n = amt = free = None
            m = INST_RE.search(text)
            if m:
                n, amt = int(m.group(1)), parse_brl(m.group(2))
                flag = m.group(3).lower()
                if flag == "sem juros" and n >= 2 and amt:
                    free = abs(n * amt - price) <= max(2.0, price * 0.01)
                elif flag == "com juros":
                    free = False
            seller = ""
            seller_data = offer.get("seller") or d.get("seller")
            if isinstance(seller_data, dict):
                seller = seller_data.get("name", "")
            elif isinstance(seller_data, str):
                seller = seller_data
            if seller:
                first_party = _same(seller, self.name)
                marketplace, trust = (not first_party), ("oficial" if first_party else "desconhecido")
            elif self.cfg.get("assume_first_party_if_missing", False):
                # Somente lojas configuradas como varejo direto, nao marketplaces.
                seller, marketplace, trust = self.name, False, "oficial"
            else:
                marketplace, trust = None, "verificar"
            condition = offer.get("itemCondition") or d.get("itemCondition") or d.get("condition")
            condition_text = str(condition or "").lower()
            if "newcondition" in condition_text or condition_text in ("new", "novo", "nova"):
                is_new = True
            elif any(x in condition_text for x in ("usedcondition", "refurbishedcondition", "used", "usado", "recondicionado")):
                is_new = False
            elif self.cfg.get("assume_new_if_missing", False):
                title_l = title.lower()
                is_new = not any(flag in title_l for flag in ("openbox", "open box", "usado", "seminovo", "recondicionado", "vitrine", "mostruario"))
            else:
                is_new = None
            results.append(Offer(store=self.name, title=title, url=url, price=price, seller=seller,
                                 marketplace=marketplace, inst_n=n, inst_amount=amt, interest_free=free,
                                 trust=trust, new_condition=is_new,
                                 availability="pre_venda" if "preorder" in avail or "presale" in avail else "disponivel"))
        return results

def _same(a, b):
    n = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    aa, bb = n(a), n(b)
    return bool(aa and bb and (bb in aa or aa in bb))

def _walk(o):
    if isinstance(o, dict):
        if ("name" in o or "title" in o) and any(k in o for k in ("price", "lowPrice", "sellingPrice", "salePrice", "offers", "bestPrice")):
            yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)
