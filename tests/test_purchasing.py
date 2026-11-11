import unittest

from stock.db import connect
from stock.purchasing import PurchasingService
from stock.service import StockError


class TestPurchasing(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.po = PurchasingService(self.conn)
        self.sup = self.po.add_supplier("Acme", "a@acme.example", 3)["id"]
        self.po.stock.add_product("P1", "Produit 1", 10.0, quantity=2, min_stock=5, supplier_id=self.sup)
        self.po.stock.add_product("P2", "Produit 2", 20.0, quantity=50, min_stock=5, supplier_id=self.sup)
        self.po.stock.add_product("P3", "Sans fournisseur", 5.0, quantity=0, min_stock=3)

    def new_order(self):
        o = self.po.create_order(self.sup)
        self.po.add_line(o["id"], "P1", 10, 8.0)
        return o["id"]

    def test_supplier_unique(self):
        with self.assertRaises(StockError):
            self.po.add_supplier("Acme")

    def test_full_lifecycle_updates_stock(self):
        oid = self.new_order()
        self.assertEqual(self.po.order_total(oid), 80.0)
        self.assertEqual(self.po.send_order(oid)["status"], "sent")
        self.assertEqual(self.po.receive_order(oid)["status"], "received")
        self.assertEqual(self.po.stock.get("P1")["quantity"], 12)
        reasons = [m["reason"] for m in self.po.stock.history("P1")]
        self.assertIn(f"Réception commande #{oid}", reasons)

    def test_cannot_receive_draft(self):
        with self.assertRaises(StockError):
            self.po.receive_order(self.new_order())

    def test_cannot_send_empty_order(self):
        o = self.po.create_order(self.sup)
        with self.assertRaises(StockError):
            self.po.send_order(o["id"])

    def test_cannot_edit_after_send(self):
        oid = self.new_order()
        self.po.send_order(oid)
        with self.assertRaises(StockError):
            self.po.add_line(oid, "P2", 1)

    def test_cancel_rules(self):
        oid = self.new_order()
        self.po.cancel_order(oid)
        with self.assertRaises(StockError):
            self.po.send_order(oid)
        with self.assertRaises(StockError):
            self.po.cancel_order(oid)

    def test_no_double_receive(self):
        oid = self.new_order()
        self.po.send_order(oid)
        self.po.receive_order(oid)
        with self.assertRaises(StockError):
            self.po.receive_order(oid)
        self.assertEqual(self.po.stock.get("P1")["quantity"], 12)

    def test_duplicate_line_rejected(self):
        oid = self.new_order()
        with self.assertRaises(StockError):
            self.po.add_line(oid, "P1", 3)

    def test_suggestions(self):
        sug = {s["sku"]: s for s in self.po.suggest_reorder()}
        self.assertEqual(set(sug), {"P1", "P3"})
        self.assertEqual(sug["P1"]["suggested"], 8)   # 2*5 - 2
        self.assertEqual(sug["P3"]["suggested"], 6)   # 2*3 - 0

    def test_orders_from_suggestions(self):
        created, without = self.po.create_orders_from_suggestions()
        self.assertEqual(len(created), 1)
        self.assertEqual(without, ["P3"])
        self.assertEqual(self.po.order_lines(created[0])[0]["quantity"], 8)
        # relancer ne crée pas de doublon
        again, _ = self.po.create_orders_from_suggestions()
        self.assertEqual(again, created)
        self.assertEqual(len(self.po.list_orders()), 1)

    def test_cannot_delete_product_in_order(self):
        self.new_order()
        with self.assertRaises(StockError):
            self.po.stock.delete_product("P1")

    def test_atomic_receive_rolls_back(self):
        oid = self.new_order()
        self.po.add_line(oid, "P2", 5, 1.0)
        self.po.send_order(oid)
        # Panne simulée : l'écriture du 2e mouvement (quantité 5) échoue
        self.conn.execute(
            "CREATE TRIGGER fail_on_5 BEFORE INSERT ON movements WHEN NEW.delta = 5 "
            "BEGIN SELECT RAISE(ABORT, 'panne simulée'); END")
        with self.assertRaises(Exception):
            self.po.receive_order(oid)
        # tout ou rien : ni stock modifié, ni statut changé
        self.assertEqual(self.po.get_order(oid)["status"], "sent")
        self.assertEqual(self.po.stock.get("P1")["quantity"], 2)
        self.assertEqual(self.po.stock.get("P2")["quantity"], 50)


if __name__ == "__main__":
    unittest.main()
