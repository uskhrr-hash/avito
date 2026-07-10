import unittest

from avito.compare import StockRow, build_posting_rows
from avito.config import CompareSettings
from pathlib import Path


def _cfg() -> CompareSettings:
    return CompareSettings(
        stock_file=Path("input/goods.xlsx"),
        stock_has_header=False,
        stock_indexes={"article": 0, "nomenclature": 1, "quantity": 2, "price": 3, "avito_price": 4},
        article_column="Артикул",
        nomenclature_column="Номенклатура",
        incoming_price_column="Цена",
        quantity_column="Количество",
        own_seller_names=[],
        exclude_needs_review=True,
        no_avito_multiplier=1.15,
        floor_multiplier=1.1,
        avito_discounts=(0.01, 0.02, 0.03),
        stock_only=True,
    )


class TestComparePricing(unittest.TestCase):
    def test_base_price_multiplied_for_avito(self):
        stock = [
            StockRow(
                article="1",
                nomenclature="Test Tire 205/55 R16 91V",
                incoming=4000,
                quantity="4",
                avito_price=5500,
            )
        ]
        posting, _, _ = build_posting_rows(stock, {}, _cfg(), "2026-06-10")
        self.assertEqual(posting[0]["recommended_price"], 4600)
        self.assertEqual(posting[0]["price_rule"], "no_avito_x1.15")
        self.assertEqual(posting[0]["цена_avito_фикс"], 5500)

    def test_calculated_when_fixed_empty(self):
        stock = [
            StockRow(
                article="2",
                nomenclature="Other 205/55 R16 91V",
                incoming=4000,
                quantity="4",
                avito_price=None,
            )
        ]
        posting, _, _ = build_posting_rows(stock, {}, _cfg(), "2026-06-10")
        self.assertEqual(posting[0]["recommended_price"], 4600)
        self.assertEqual(posting[0]["price_rule"], "no_avito_x1.15")
        self.assertEqual(posting[0]["цена_avito_фикс"], "")


if __name__ == "__main__":
    unittest.main()
