import contextlib
import io
import os
import tempfile
import unittest

from stock.cli import main


class TestCli(unittest.TestCase):
    def run_cli(self, db, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--db", db, *args])
        return code, out.getvalue(), err.getvalue()

    def test_full_scenario(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "t.db")
            self.assertEqual(self.run_cli(db, "add", "A1", "Stylo", "1.5", "--qty", "10")[0], 0)
            self.assertEqual(self.run_cli(db, "out", "A1", "4")[0], 0)
            code, out, _ = self.run_cli(db, "list")
            self.assertIn("Stylo", out)
            code, out, _ = self.run_cli(db, "value")
            self.assertIn("9.00", out)

    def test_reorder_workflow(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "t.db")
            self.assertEqual(self.run_cli(db, "demo")[0], 0)
            code, out, _ = self.run_cli(db, "reorder")
            self.assertIn("MOU-002", out)
            code, out, _ = self.run_cli(db, "reorder-create")
            self.assertIn("Brouillons", out)
            self.assertEqual(self.run_cli(db, "po-send", "1")[0], 0)
            self.assertEqual(self.run_cli(db, "po-receive", "1")[0], 0)
            code, out, _ = self.run_cli(db, "po-list", "--status", "received")
            self.assertIn("reçue", out)
            code, out, _ = self.run_cli(db, "low")
            self.assertNotIn("HDP-005", out)   # le brouillon n°1 (AudioPro) a été reçu

    def test_invalid_transition_returns_code_1(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "t.db")
            self.run_cli(db, "demo")
            self.run_cli(db, "reorder-create")
            code, _, err = self.run_cli(db, "po-receive", "1")
            self.assertEqual(code, 1)
            self.assertIn("Transition impossible", err)

    def test_error_returns_code_1(self):
        with tempfile.TemporaryDirectory() as d:
            code, _, err = self.run_cli(os.path.join(d, "t.db"), "out", "NOPE", "1")
            self.assertEqual(code, 1)
            self.assertIn("introuvable", err)


if __name__ == "__main__":
    unittest.main()
