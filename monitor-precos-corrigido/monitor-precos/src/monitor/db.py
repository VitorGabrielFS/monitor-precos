import os
import sqlite3
from datetime import datetime, timezone, timedelta
from .models import Offer

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers(
 key TEXT PRIMARY KEY, product TEXT, variant TEXT, title TEXT, store TEXT, seller TEXT,
 marketplace INTEGER, url TEXT, item_id TEXT, price REAL, original_price REAL, shipping REAL,
 free_shipping INTEGER, inst_n INTEGER, inst_amount REAL, interest_free INTEGER,
 availability TEXT, trust TEXT, new_condition INTEGER, first_seen TEXT, last_seen TEXT, min_price REAL);
CREATE TABLE IF NOT EXISTS price_history(
 id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, ts TEXT, price REAL, shipping REAL,
 inst_n INTEGER, inst_amount REAL, interest_free INTEGER, availability TEXT);
CREATE INDEX IF NOT EXISTS ix_hist_key ON price_history(key, ts);
CREATE TABLE IF NOT EXISTS notifications(
 id INTEGER PRIMARY KEY AUTOINCREMENT, dedupe_key TEXT, ts TEXT, price REAL);
CREATE INDEX IF NOT EXISTS ix_notif ON notifications(dedupe_key, ts);
CREATE TABLE IF NOT EXISTS runs(
 id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, store TEXT, status TEXT, n_offers INTEGER, msg TEXT);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt=None) -> str:
    return (dt or now()).isoformat(timespec="seconds")


def connect(path):
    os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _b(v):
    return None if v is None else int(v)


def upsert_offer(conn, o: Offer) -> dict:
    ts = iso()
    row = conn.execute("SELECT * FROM offers WHERE key=?", (o.key,)).fetchone()
    prev_min = conn.execute("SELECT MIN(min_price) FROM offers WHERE product=? AND variant=?",
                            (o.product, o.variant)).fetchone()[0]
    vals = (o.product, o.variant, o.title, o.store, o.seller, _b(o.marketplace), o.url, o.item_id,
            o.price, o.original_price, o.shipping, _b(o.free_shipping), o.inst_n, o.inst_amount,
            _b(o.interest_free), o.availability, o.trust, _b(o.new_condition))
    if row is None:
        conn.execute("INSERT INTO offers(product,variant,title,store,seller,marketplace,url,item_id,price,"
                     "original_price,shipping,free_shipping,inst_n,inst_amount,interest_free,availability,"
                     "trust,new_condition,key,first_seen,last_seen,min_price) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     vals + (o.key, ts, ts, o.price))
    else:
        conn.execute("UPDATE offers SET product=?,variant=?,title=?,store=?,seller=?,marketplace=?,url=?,"
                     "item_id=?,price=?,original_price=?,shipping=?,free_shipping=?,inst_n=?,inst_amount=?,"
                     "interest_free=?,availability=?,trust=?,new_condition=?,last_seen=?,min_price=? WHERE key=?",
                     vals + (ts, min(row["min_price"] or o.price, o.price), o.key))
    last = conn.execute("SELECT * FROM price_history WHERE key=? ORDER BY id DESC LIMIT 1", (o.key,)).fetchone()
    changed = (last is None or last["price"] != o.price or last["shipping"] != o.shipping
               or last["inst_n"] != o.inst_n or last["availability"] != o.availability)
    old = last is not None and datetime.fromisoformat(last["ts"]) < now() - timedelta(hours=12)
    if changed or old:
        conn.execute("INSERT INTO price_history(key,ts,price,shipping,inst_n,inst_amount,interest_free,availability)"
                     " VALUES(?,?,?,?,?,?,?,?)",
                     (o.key, ts, o.price, o.shipping, o.inst_n, o.inst_amount, _b(o.interest_free), o.availability))
    conn.commit()
    return {"is_new": row is None, "prev_min": prev_min,
            "price_changed": row is not None and row["price"] != o.price}


def active_offers(conn, hours):
    cutoff = iso(now() - timedelta(hours=hours))
    rows = conn.execute("SELECT * FROM offers WHERE last_seen>=?", (cutoff,)).fetchall()
    return [Offer.from_row(r) for r in rows]


def log_run(conn, store, status, n, msg=""):
    conn.execute("INSERT INTO runs(ts,store,status,n_offers,msg) VALUES(?,?,?,?,?)",
                 (iso(), store, status, n, msg[:300]))
    conn.commit()


def get_meta(conn, k, default=None):
    r = conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def set_meta(conn, k, v):
    conn.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
    conn.commit()


def last_notification(conn, dedupe_key):
    return conn.execute("SELECT * FROM notifications WHERE dedupe_key=? ORDER BY id DESC LIMIT 1",
                        (dedupe_key,)).fetchone()


def add_notification(conn, dedupe_key, price):
    conn.execute("INSERT INTO notifications(dedupe_key,ts,price) VALUES(?,?,?)", (dedupe_key, iso(), price))
    conn.commit()
