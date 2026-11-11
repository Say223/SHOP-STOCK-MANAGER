"""Logique métier de la gestion de stock."""
import csv
import sqlite3


class StockError(Exception):
    """Erreur métier (produit inconnu, stock insuffisant, données invalides...)."""


class StockService:
    def __init__(self, conn):
        self.conn = conn

    # ------------------------------------------------------------------ produits
    def add_product(self, sku, name, price, quantity=0, min_stock=5, supplier_id=None):
        sku = sku.strip().upper()
        if not sku or not name.strip():
            raise StockError("La référence et le nom sont obligatoires.")
        if price < 0 or quantity < 0 or min_stock < 0:
            raise StockError("Prix, quantité et seuil doivent être positifs.")
        if supplier_id is not None and self.conn.execute(
                "SELECT 1 FROM suppliers WHERE id = ?", (supplier_id,)).fetchone() is None:
            raise StockError(f"Fournisseur introuvable : {supplier_id}")
        try:
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO products (sku, name, price, quantity, min_stock, supplier_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (sku, name.strip(), price, quantity, min_stock, supplier_id),
                )
                if quantity:
                    self.conn.execute(
                        "INSERT INTO movements (product_id, delta, reason) VALUES (?, ?, ?)",
                        (cur.lastrowid, quantity, "Stock initial"),
                    )
        except sqlite3.IntegrityError:
            raise StockError(f"La référence {sku} existe déjà.")
        return self.get(sku)

    def get(self, sku):
        row = self.conn.execute("SELECT * FROM products WHERE sku = ?", (sku.strip().upper(),)).fetchone()
        if row is None:
            raise StockError(f"Produit introuvable : {sku}")
        return row

    def list_products(self):
        return self.conn.execute("SELECT * FROM products ORDER BY sku").fetchall()

    def set_supplier(self, sku, supplier_id):
        product = self.get(sku)
        if self.conn.execute("SELECT 1 FROM suppliers WHERE id = ?", (supplier_id,)).fetchone() is None:
            raise StockError(f"Fournisseur introuvable : {supplier_id}")
        with self.conn:
            self.conn.execute("UPDATE products SET supplier_id = ? WHERE id = ?", (supplier_id, product["id"]))

    # ------------------------------------------------------------------ mouvements
    def apply_movement(self, product, delta, reason=""):
        """Écrit le mouvement SANS valider la transaction (l'appelant gère le commit).

        Permet d'enchaîner plusieurs mouvements de façon atomique (ex. réception d'une commande fournisseur).
        """
        new_qty = product["quantity"] + delta
        if new_qty < 0:
            raise StockError(
                f"Stock insuffisant pour {product['sku']} : {product['quantity']} disponible(s), {-delta} demandé(s)."
            )
        self.conn.execute("UPDATE products SET quantity = ? WHERE id = ?", (new_qty, product["id"]))
        self.conn.execute(
            "INSERT INTO movements (product_id, delta, reason) VALUES (?, ?, ?)",
            (product["id"], delta, reason),
        )

    def move_stock(self, sku, delta, reason=""):
        """Entrée (delta > 0) ou sortie (delta < 0) de stock, avec historisation."""
        if delta == 0:
            raise StockError("La quantité ne peut pas être nulle.")
        product = self.get(sku)
        with self.conn:
            self.apply_movement(product, delta, reason)
        return self.get(sku)

    # ------------------------------------------------------------------ indicateurs
    def low_stock(self):
        return self.conn.execute(
            "SELECT * FROM products WHERE quantity <= min_stock ORDER BY quantity, sku"
        ).fetchall()

    def total_value(self):
        row = self.conn.execute("SELECT COALESCE(SUM(price * quantity), 0) AS v FROM products").fetchone()
        return row["v"]

    def history(self, sku, limit=20):
        product = self.get(sku)
        return self.conn.execute(
            "SELECT * FROM movements WHERE product_id = ? ORDER BY id DESC LIMIT ?",
            (product["id"], limit),
        ).fetchall()

    def recent_movements(self, limit=10):
        """Derniers mouvements tous produits confondus (pour le rapport)."""
        return self.conn.execute(
            """SELECT m.*, p.sku, p.name FROM movements m
               JOIN products p ON p.id = m.product_id
               ORDER BY m.id DESC LIMIT ?""", (limit,)).fetchall()

    def delete_product(self, sku):
        product = self.get(sku)
        in_orders = self.conn.execute(
            "SELECT 1 FROM purchase_order_lines WHERE product_id = ?", (product["id"],)).fetchone()
        if in_orders:
            raise StockError(f"{product['sku']} figure dans des commandes fournisseur : suppression impossible.")
        with self.conn:
            self.conn.execute("DELETE FROM products WHERE id = ?", (product["id"],))

    def export_csv(self, path):
        rows = self.list_products()
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["sku", "name", "price", "quantity", "min_stock", "stock_value"])
            for r in rows:
                writer.writerow([r["sku"], r["name"], r["price"], r["quantity"], r["min_stock"],
                                 round(r["price"] * r["quantity"], 2)])
        return len(rows)
