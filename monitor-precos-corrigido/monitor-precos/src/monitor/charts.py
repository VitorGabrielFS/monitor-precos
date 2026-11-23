import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from . import db


def chart_for(conn, product, title, meta, outdir, days=30):
    cutoff = db.iso(db.now() - timedelta(days=days))
    rows = conn.execute("SELECT substr(h.ts,1,10) d, MIN(h.price) p FROM price_history h JOIN offers o ON o.key=h.key "
                        "WHERE o.product=? AND h.ts>=? AND o.trust IN ('oficial','bom') GROUP BY d ORDER BY d",
                        (product, cutoff)).fetchall()
    if len(rows) < 2:
        return None
    os.makedirs(outdir, exist_ok=True)
    xs = [datetime.fromisoformat(r["d"]) for r in rows]
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.plot(xs, [r["p"] for r in rows], marker="o")
    ax.axhline(meta, color="green", linestyle="--", label=f"meta R$ {meta:,.0f}")
    ax.set_title(f"{title}: menor preço por dia"); ax.legend(); ax.grid(alpha=.3)
    fig.autofmt_xdate(); fig.tight_layout()
    path = os.path.join(outdir, f"{product}.png")
    fig.savefig(path, dpi=110); plt.close(fig)
    return path
