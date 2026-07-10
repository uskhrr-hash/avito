import unittest

from avito.stock_sources import StockRow, merge_rows


class TestStockSources(unittest.TestCase):
    def test_merge_rows_google_priority(self):
        google_rows = [
            StockRow(article="100", name="A", quantity="5", price=6000, source="google"),
        ]
        db_rows = [
            StockRow(article="100", name="A-from-db", quantity="7", price=5800, source="db"),
            StockRow(article="200", name="B", quantity="", price=7000, source="db"),
        ]
        merged = merge_rows(google_rows, db_rows)
        by = {r.article: r for r in merged}
        self.assertEqual(len(merged), 2)
        self.assertEqual(by["100"].price, 6000)
        self.assertEqual(by["100"].name, "A")
        self.assertEqual(by["100"].source, "google")
        self.assertEqual(by["200"].source, "db")


if __name__ == "__main__":
    unittest.main()
