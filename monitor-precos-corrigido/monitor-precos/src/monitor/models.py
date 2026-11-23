from __future__ import annotations
import hashlib
from dataclasses import dataclass, asdict, fields
from typing import Optional

TRUST_OK = ("oficial", "bom")
RISK = {"oficial": 0.0, "bom": 0.02, "verificar": 0.04, "desconhecido": 0.10, "ruim": 0.5}


@dataclass
class Offer:
    store: str
    title: str
    url: str
    price: float
    product: str = ""            # ps5 | gta6
    variant: str = ""
    seller: str = ""
    marketplace: Optional[bool] = None
    original_price: Optional[float] = None
    shipping: Optional[float] = None       # None = desconhecido
    free_shipping: Optional[bool] = None
    inst_n: Optional[int] = None
    inst_amount: Optional[float] = None
    interest_free: Optional[bool] = None   # None = NAO VERIFICADO
    availability: str = "disponivel"       # disponivel | pre_venda
    trust: str = "desconhecido"            # oficial | bom | verificar | desconhecido | ruim
    new_condition: Optional[bool] = None
    item_id: str = ""

    @property
    def key(self) -> str:
        base = f"{self.store}|{self.item_id or self.url.split('?')[0]}"
        return hashlib.sha1(base.encode()).hexdigest()[:16]

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_row(cls, row):
        names = {f.name for f in fields(cls)}
        d = {k: row[k] for k in row.keys() if k in names}
        for b in ("marketplace", "free_shipping", "interest_free"):
            if d.get(b) is not None:
                d[b] = bool(d[b])
        if d.get("new_condition") is not None:
            d["new_condition"] = bool(d["new_condition"])
        return cls(**d)
