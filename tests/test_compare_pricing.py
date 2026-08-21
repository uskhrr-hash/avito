import unittest
from pathlib import Path

from avito.compare import StockRow, build_posting_rows
from avito.config import CompareSettings


def _cfg() -> CompareSettings:
    return CompareSettings(
        stock_file=Path("input/goods.xlsx"),
        stock_has_header=False,
        stock_indexes={
            "article": 0,
            "nomenclature": 1,
            "quantity": 2,
            "price": 3,
            "avito_price": 4,
        },
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
        self.assertEqual(posting[0]["price_rule"], "markup_x1.15")
        self.assertEqual(posting[0]["цена_avito_фикс"], 5500)

    def test_manual_price_overrides_markup(self):
        stock = [
            StockRow(
                article="10937",
                nomenclature="Manual Tire 205/55 R16 91V",
                incoming=3163,
                quantity="4",
            )
        ]
        posting, _, _ = build_posting_rows(
            stock,
            {},
            _cfg(),
            "2026-06-10",
            manual_prices={"10937": 3200},
        )
        self.assertEqual(posting[0]["recommended_price"], 3200)
        self.assertEqual(posting[0]["price_rule"], "manual")


if __name__ == "__main__":
    unittest.main()
