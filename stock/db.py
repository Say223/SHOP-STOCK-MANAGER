"""Couche d'accès aux données (SQLite)."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS suppliers (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    email     TEXT NOT NULL DEFAULT '',
    lead_days INTEGER NOT NULL DEFAULT 7 CHECK (lead_days >= 0)
);
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    price       REAL NOT NULL CHECK (price >= 0),
    quantity    INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    min_stock   INTEGER NOT NULL DEFAULT 5 CHECK (min_stock >= 0),
    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS movements (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    delta      INTEGER NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    status      TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'sent', 'received', 'cancelled')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS purchase_order_lines (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id      INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    unit_cost  REAL NOT NULL CHECK (unit_cost >= 0),
    UNIQUE (po_id, product_id)
);
"""


def _migrate(conn):
    """Anciennes bases (sans fournisseurs) : ajoute la colonne manquante."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
    if "supplier_id" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id)")
        conn.commit()


def connect(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Les tables de l'ancienne version peuvent exister : on crée d'abord celles qui manquent
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn
