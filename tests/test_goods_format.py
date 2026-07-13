import tempfile
import unittest
from pathlib import Path

import pandas as pd

from avito.compare import load_stock
from avito.config import CompareSettings
from avito.stock_sources import is_legacy_goods_format, write_goods_xlsx, StockRow


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


class TestGoodsFormat(unittest.TestCase):
    def test_legacy_five_columns_rejected(self):
        self.assertTrue(is_legacy_goods_format(pd.DataFrame([[1, 2, 3, 4, 5]])))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "goods.xlsx"
            pd.DataFrame([[1, "A", 4, 5000, "google"]]).to_excel(
                p, index=False, header=False
            )
            with self.assertRaises(ValueError):
                load_stock(p, _cfg())

    def test_six_columns_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "goods.xlsx"
            write_goods_xlsx(
                p,
                [
                    StockRow(
                        article="1",
                        name="Tire 205/55 R16",
                        quantity="4",
                        price=4000,
                        source="google",
                        avito_price=5500,
                        ushk_in_stock=True,
                    )
                ],
            )
            rows = load_stock(p, _cfg())
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].avito_price, 5500)
            self.assertTrue(rows[0].ushk_in_stock)


if __name__ == "__main__":
    unittest.main()
