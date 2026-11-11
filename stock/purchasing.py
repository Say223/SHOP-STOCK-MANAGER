"""Processus de réapprovisionnement : fournisseurs et commandes d'achat.

Cycle de vie d'une commande :  draft --> sent --> received
                                  \\        \\
                                   '--------'--> cancelled
La réception d'une commande alimente automatiquement le stock (traçabilité dans l'historique).
"""
import sqlite3

from .service import StockError, StockService

# Transitions autorisées (règle de gestion RG-05)
TRANSITIONS = {
    "draft": {"sent", "cancelled"},
    "sent": {"received", "cancelled"},
    "received": set(),
    "cancelled": set(),
}
TARGET_FACTOR = 2  # on recommande de remonter le stock à 2 x le seuil d'alerte (RG-07)


class PurchasingService:
    def __init__(self, conn):
        self.conn = conn
        self.stock = StockService(conn)

    # ------------------------------------------------------------------ fournisseurs
    def add_supplier(self, name, email="", lead_days=7):
        name = name.strip()
        if not name:
            raise StockError("Le nom du fournisseur est obligatoire.")
        if lead_days < 0:
            raise StockError("Le délai de livraison doit être positif.")
        try:
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO suppliers (name, email, lead_days) VALUES (?, ?, ?)", (name, email, lead_days))
        except sqlite3.IntegrityError:
            raise StockError(f"Le fournisseur « {name} » existe déjà.")
        return self.get_supplier(cur.lastrowid)

    def get_supplier(self, supplier_id):
        row = self.conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if row is None:
            raise StockError(f"Fournisseur introuvable : {supplier_id}")
        return row

    def list_suppliers(self):
        return self.conn.execute("SELECT * FROM suppliers ORDER BY name").fetchall()

    # ------------------------------------------------------------------ commandes
    def create_order(self, supplier_id):
        self.get_supplier(supplier_id)
        with self.conn:
            cur = self.conn.execute("INSERT INTO purchase_orders (supplier_id) VALUES (?)", (supplier_id,))
        return self.get_order(cur.lastrowid)

    def get_order(self, po_id):
        row = self.conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
        if row is None:
            raise StockError(f"Commande introuvable : {po_id}")
        return row

    def order_lines(self, po_id):
        return self.conn.execute(
            """SELECT l.*, p.sku, p.name FROM purchase_order_lines l
               JOIN products p ON p.id = l.product_id WHERE l.po_id = ? ORDER BY p.sku""", (po_id,)).fetchall()

    def order_total(self, po_id):
        row = self.conn.execute(
            "SELECT COALESCE(SUM(quantity * unit_cost), 0) AS t FROM purchase_order_lines WHERE po_id = ?",
            (po_id,)).fetchone()
        return row["t"]

    def list_orders(self, status=None):
        if status:
            return self.conn.execute("SELECT * FROM purchase_orders WHERE status = ? ORDER BY id", (status,)).fetchall()
        return self.conn.execute("SELECT * FROM purchase_orders ORDER BY id").fetchall()

    def add_line(self, po_id, sku, quantity, unit_cost=None):
        order = self.get_order(po_id)
        if order["status"] != "draft":
            raise StockError("Seule une commande en brouillon peut être modifiée.")  # RG-04
        if quantity <= 0:
            raise StockError("La quantité commandée doit être strictement positive.")
        product = self.stock.get(sku)
        if unit_cost is None:
            unit_cost = product["price"]
        if unit_cost < 0:
            raise StockError("Le coût unitaire doit être positif.")
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO purchase_order_lines (po_id, product_id, quantity, unit_cost) VALUES (?, ?, ?, ?)",
                    (po_id, product["id"], quantity, unit_cost))
        except sqlite3.IntegrityError:
            raise StockError(f"{product['sku']} figure déjà dans la commande {po_id}.")

    def _transition(self, po_id, new_status):
        order = self.get_order(po_id)
        if new_status not in TRANSITIONS[order["status"]]:
            raise StockError(
                f"Transition impossible : la commande {po_id} est « {order['status']} » (vers « {new_status} »).")
        return order

    def send_order(self, po_id):
        self._transition(po_id, "sent")
        if not self.order_lines(po_id):
            raise StockError("Impossible d'envoyer une commande vide.")  # RG-03
        with self.conn:
            self.conn.execute(
                "UPDATE purchase_orders SET status = 'sent', updated_at = datetime('now','localtime') WHERE id = ?",
                (po_id,))
        return self.get_order(po_id)

    def cancel_order(self, po_id):
        self._transition(po_id, "cancelled")
        with self.conn:
            self.conn.execute(
                "UPDATE purchase_orders SET status = 'cancelled', updated_at = datetime('now','localtime') WHERE id = ?",
                (po_id,))
        return self.get_order(po_id)

    def receive_order(self, po_id):
        """Réception : toutes les lignes entrent en stock dans UNE transaction (tout ou rien)."""
        self._transition(po_id, "received")
        lines = self.order_lines(po_id)
        with self.conn:
            for line in lines:
                product = self.conn.execute("SELECT * FROM products WHERE id = ?", (line["product_id"],)).fetchone()
                self.stock.apply_movement(product, line["quantity"], f"Réception commande #{po_id}")
            self.conn.execute(
                "UPDATE purchase_orders SET status = 'received', updated_at = datetime('now','localtime') WHERE id = ?",
                (po_id,))
        return self.get_order(po_id)

    # ------------------------------------------------------------------ aide à la décision
    def suggest_reorder(self):
        """Propose des quantités à commander pour les produits sous le seuil (RG-07).

        Retourne une liste de dicts : sku, name, quantity (actuelle), suggested, supplier_id.
        """
        result = []
        for p in self.stock.low_stock():
            suggested = max(p["min_stock"] * TARGET_FACTOR - p["quantity"], 1)
            result.append({"sku": p["sku"], "name": p["name"], "quantity": p["quantity"],
                           "suggested": suggested, "supplier_id": p["supplier_id"], "price": p["price"]})
        return result

    def create_orders_from_suggestions(self):
        """Crée un brouillon par fournisseur à partir des suggestions. Retourne (ids créés, SKU sans fournisseur)."""
        by_supplier, without = {}, []
        for s in self.suggest_reorder():
            if s["supplier_id"] is None:
                without.append(s["sku"])
            else:
                by_supplier.setdefault(s["supplier_id"], []).append(s)
        created = []
        for supplier_id, items in by_supplier.items():
            # On évite de dupliquer : un seul brouillon ouvert par fournisseur (RG-06)
            existing = self.conn.execute(
                "SELECT id FROM purchase_orders WHERE supplier_id = ? AND status = 'draft'", (supplier_id,)).fetchone()
            po_id = existing["id"] if existing else self.create_order(supplier_id)["id"]
            for s in items:
                try:
                    self.add_line(po_id, s["sku"], s["suggested"], s["price"])
                except StockError:
                    pass  # ligne déjà présente dans le brouillon
            created.append(po_id)
        return created, without

    def seed_demo(self):
        """Données de démonstration : fournisseurs + produits + un brouillon de réapprovisionnement."""
        created = 0
        suppliers = {}
        for name, email, lead in [("TechDistrib", "contact@techdistrib.example", 5),
                                  ("AudioPro", "ventes@audiopro.example", 10)]:
            try:
                suppliers[name] = self.add_supplier(name, email, lead)["id"]
            except StockError:
                suppliers[name] = self.conn.execute("SELECT id FROM suppliers WHERE name = ?", (name,)).fetchone()["id"]
        demo = [
            ("LAP-001", "Laptop Pro 14", 1199.0, 12, 5, "TechDistrib"),
            ("MOU-002", "Souris sans fil", 39.0, 3, 10, "TechDistrib"),
            ("KEY-003", "Clavier mécanique", 89.0, 25, 8, "TechDistrib"),
            ("SCR-004", "Écran 27 pouces", 249.0, 4, 5, "TechDistrib"),
            ("HDP-005", "Casque audio", 129.0, 2, 6, "AudioPro"),
            ("CAB-006", "Câble USB-C", 9.9, 120, 30, None),
        ]
        for sku, name, price, qty, mini, sup in demo:
            try:
                self.stock.add_product(sku, name, price, qty, mini, suppliers.get(sup))
                created += 1
            except StockError:
                pass
        return created
