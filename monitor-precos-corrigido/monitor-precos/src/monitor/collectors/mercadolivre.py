"""Mercado Livre via API oficial. Sem credenciais a API de busca costuma recusar (403);
com um app gratuito (ML_CLIENT_ID/ML_CLIENT_SECRET) funciona sem cartao."""
import os
import logging
import requests
from ..models import Offer
from .base import get, Blocked

API = "https://api.mercadolibre.com"
log = logging.getLogger("monitor")


class MercadoLivre:
    name = "Mercado Livre"

    def __init__(self, session=None):
        self.s = session or requests.Session()
        self.token = None
        self._seller_cache = {}

    def _auth(self):
        cid, sec = os.environ.get("ML_CLIENT_ID"), os.environ.get("ML_CLIENT_SECRET")
        if not (cid and sec):
            return
        r = self.s.post(f"{API}/oauth/token", data={"grant_type": "client_credentials",
                        "client_id": cid, "client_secret": sec}, timeout=20)
        if r.ok:
            self.token = r.json().get("access_token")
        else:
            log.warning("ML: falha ao obter token (%s)", r.status_code)

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def collect(self, queries):
        self._auth()
        out = []
        for q in queries:
            r = get(f"{API}/sites/MLB/search", session=self.s,
                    params={"q": q, "condition": "new", "limit": 50}, headers=self._h())
            if r.status_code in (401, 403):
                raise Blocked("Mercado Livre recusou a busca (HTTP %s). Configure ML_CLIENT_ID/ML_CLIENT_SECRET." % r.status_code)
            r.raise_for_status()
            out += self.parse(r.json())
        return out

    def seller_trust(self, seller_id, rep=None):
        if rep is None:
            if seller_id in self._seller_cache:
                return self._seller_cache[seller_id]
            try:
                r = get(f"{API}/users/{seller_id}", session=self.s, headers=self._h())
                rep = r.json().get("seller_reputation") if r.ok else None
            except Exception:
                rep = None
        trust = "desconhecido"
        if rep:
            level = (rep.get("level_id") or "")
            power = rep.get("power_seller_status")
            if level.endswith("green") or power in ("platinum", "gold", "silver"):
                trust = "bom"
            elif level and (level.endswith("orange") or level.endswith("red") or level.endswith("yellow")):
                trust = "ruim"
        self._seller_cache[seller_id] = trust
        return trust

    def parse(self, data):
        offers = []
        for r in data.get("results", []):
            price = r.get("price")
            if not price or r.get("condition") not in (None, "new"):
                continue
            inst = r.get("installments") or {}
            n, amt, rate = inst.get("quantity"), inst.get("amount"), inst.get("rate")
            free = None
            if n and amt and rate is not None:
                try:
                    rate_zero = float(rate) == 0.0
                    total_installments = float(n) * float(amt)
                    matches_price = abs(total_installments - float(price)) <= max(2.0, float(price) * 0.01)
                    free = bool(rate_zero and matches_price)
                except (TypeError, ValueError):
                    free = None
            ship = r.get("shipping") or {}
            seller = r.get("seller") or {}
            official = bool(r.get("official_store_id"))
            trust = "oficial" if official else self.seller_trust(seller.get("id"), seller.get("seller_reputation")) \
                if seller.get("id") else "desconhecido"
            offers.append(Offer(
                store="Mercado Livre", title=r.get("title", ""), url=r.get("permalink", ""),
                price=float(price), item_id=str(r.get("id", "")),
                seller=str(seller.get("nickname") or seller.get("id") or ""),
                marketplace=True, original_price=r.get("original_price"),
                shipping=0.0 if ship.get("free_shipping") else None,
                free_shipping=True if ship.get("free_shipping") else None,
                inst_n=n, inst_amount=amt, interest_free=free, trust=trust,
                new_condition=(r.get("condition") == "new")))
        return offers
