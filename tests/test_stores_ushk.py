import unittest

from avito.stores import load_stores


class TestStoresUshk(unittest.TestCase):
    def test_ushk_supplier_loaded(self):
        from pathlib import Path

        stores = load_stores(Path(__file__).resolve().parents[1] / "stores.yaml")
        md = stores.get("md")
        pg = stores.get("pg")
        self.assertIsNotNone(md)
        self.assertIsNotNone(pg)
        assert md is not None and pg is not None
        self.assertEqual(md.ushk_supplier, "УШК Менделеева")
        self.assertEqual(pg.ushk_supplier, "УШК Пугачева")


if __name__ == "__main__":
    unittest.main()
