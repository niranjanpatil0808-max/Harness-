import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from kintsugi.cli import main

SHOP = Path(__file__).parent / "fixtures" / "shop"


class TestCli(unittest.TestCase):
    def test_graph_command(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["graph", str(SHOP)]), 0)
        self.assertIn("pricing.order_total --references--> tax.TAX_RATE", out.getvalue())

    def test_fix_with_mock_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            code = main(["fix", str(SHOP), "--mock", "--retries", "0", "--memory", f"{tmp}/l.json"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
