import os
import tempfile
import unittest

from stock.db import connect
from stock.service import StockError, StockService


class TestStockService(unittest.TestCase):
    def setUp(self):
        self.svc = StockService(connect(":memory:"))
        self.svc.add_product("abc-1", "Produit", 10.0, quantity=10, min_stock=3)

    def test_sku_normalized(self):
        self.assertEqual(self.svc.get("ABC-1")["name"], "Produit")

    def test_duplicate_rejected(self):
        with self.assertRaises(StockError):
            self.svc.add_product("ABC-1", "Autre", 1.0)

    def test_invalid_price(self):
        with self.assertRaises(StockError):
            self.svc.add_product("X", "Nom", -1.0)

    def test_entry_and_exit(self):
        self.assertEqual(self.svc.move_stock("ABC-1", 5)["quantity"], 15)
        self.assertEqual(self.svc.move_stock("ABC-1", -12)["quantity"], 3)

    def test_insufficient_stock(self):
        with self.assertRaises(StockError):
            self.svc.move_stock("ABC-1", -11)
        self.assertEqual(self.svc.get("ABC-1")["quantity"], 10)

    def test_zero_movement_rejected(self):
        with self.assertRaises(StockError):
            self.svc.move_stock("ABC-1", 0)

    def test_unknown_product(self):
        with self.assertRaises(StockError):
            self.svc.get("NOPE")

    def test_low_stock(self):
        self.assertEqual(self.svc.low_stock(), [])
        self.svc.move_stock("ABC-1", -8, "Vente")
        self.assertEqual([p["sku"] for p in self.svc.low_stock()], ["ABC-1"])

    def test_total_value(self):
        self.assertEqual(self.svc.total_value(), 100.0)

    def test_history(self):
        self.svc.move_stock("ABC-1", -2, "Vente")
        h = self.svc.history("ABC-1")
        self.assertEqual([m["delta"] for m in h], [-2, 10])

    def test_delete_cascades(self):
        self.svc.delete_product("ABC-1")
        self.assertEqual(self.svc.list_products(), [])

    def test_export(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")
            self.assertEqual(self.svc.export_csv(path), 1)
            with open(path, encoding="utf-8") as f:
                self.assertIn("ABC-1", f.read())


if __name__ == "__main__":
    unittest.main()
