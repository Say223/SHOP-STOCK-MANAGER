import os
import tempfile
import unittest

from stock.cli import main
from stock.db import connect
from stock.purchasing import PurchasingService
from stock.report import build_report


class TestReport(unittest.TestCase):
    def setUp(self):
        self.po = PurchasingService(connect(":memory:"))

    def test_empty_database(self):
        html = build_report(self.po.stock, self.po)
        self.assertIn("Aucun produit.", html)
        self.assertIn("Aucune commande.", html)

    def test_demo_data_shows_alerts_and_orders(self):
        self.po.seed_demo()
        self.po.create_orders_from_suggestions()
        html = build_report(self.po.stock, self.po)
        self.assertIn("Souris sans fil", html)
        self.assertIn("#dc2626", html)          # barre rouge : produit sous le seuil
        self.assertIn("Brouillon", html)
        self.assertIn("TechDistrib", html)

    def test_html_is_escaped(self):
        self.po.stock.add_product("X1", "<script>alert(1)</script>", 1.0, quantity=1, min_stock=1)
        html = build_report(self.po.stock, self.po)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_cli_report_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            db, out = os.path.join(d, "t.db"), os.path.join(d, "sous-dossier", "r.html")
            self.assertEqual(main(["--db", db, "demo"]), 0)
            self.assertEqual(main(["--db", db, "report", "--output", out]), 0)
            with open(out, encoding="utf-8") as f:
                self.assertIn("Rapport de stock", f.read())


if __name__ == "__main__":
    unittest.main()
