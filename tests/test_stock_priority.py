import unittest

from avito.stock_priority import (
    RegisterLine,
    StockPriorityConfig,
    is_seller_star_source,
    resolve_register_article,
    resolve_register_stock,
)


class TestStockPriority(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = StockPriorityConfig()

    def test_seller_star_source(self):
        self.assertTrue(is_seller_star_source("google"))
        self.assertTrue(is_seller_star_source("p1"))
        self.assertTrue(is_seller_star_source("db:p2"))
        self.assertTrue(is_seller_star_source("db:p3"))
        self.assertTrue(is_seller_star_source("db:p4"))
        self.assertFalse(is_seller_star_source("db:p5"))
        self.assertFalse(is_seller_star_source("db:p6"))

    def test_p2_ufa_and_ushk(self):
        lines = [
            RegisterLine("100", "Tire A", "УШК Менделеева", 3100, 8),
            RegisterLine("100", "Tire A", "Сам МБ Уфа", 3000, 6),
            RegisterLine("100", "Tire A", "Колесо", 2800, 20),
        ]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        assert result is not None
        self.assertEqual(result.priority, "p2")
        self.assertEqual(result.base_price, 2700.0)

    def test_p3_ufa_only(self):
        lines = [
            RegisterLine("100", "Tire A", "Сам МБ Уфа", 3000, 6),
            RegisterLine("100", "Tire A", "Колесо", 2800, 20),
        ]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        assert result is not None
        self.assertEqual(result.priority, "p3")
        self.assertEqual(result.base_price, 2700.0)

    def test_p4_moscow_and_ushk(self):
        lines = [
            RegisterLine("100", "Tire A", "Сам МБ Москва", 3200, 50),
            RegisterLine("100", "Tire A", "УШК Бакалинская", 3100, 10),
        ]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        assert result is not None
        self.assertEqual(result.priority, "p4")
        self.assertEqual(result.base_price, 2880.0)

    def test_p5_ushk_without_moscow_over_40(self):
        lines = [
            RegisterLine("100", "Tire A", "УШК Центральный склад", 3100, 10),
            RegisterLine("100", "Tire A", "Сам МБ Москва", 3200, 20),
        ]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        assert result is not None
        self.assertEqual(result.priority, "p5")
        self.assertEqual(result.base_price, 3100.0)

    def test_p6_cheapest_other_supplier(self):
        lines = [
            RegisterLine("100", "Tire A", "Бринэкс", 2800, 12),
            RegisterLine("100", "Tire A", "Шининвест", 3397, 11),
        ]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        assert result is not None
        self.assertEqual(result.priority, "p6")
        self.assertEqual(result.base_price, 2800.0)

    def test_disallowed_suppliers_ignored(self):
        lines = [
            RegisterLine("100", "Tire A", "Шинсервис", 1000, 20),
            RegisterLine("100", "Tire A", "Римэкс", 1100, 20),
        ]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        self.assertIsNone(result)

    def test_power_ufa_only_other_power_ignored(self):
        lines = [
            RegisterLine("100", "Tire A", "Пауэр Москва", 2000, 12),
            RegisterLine("100", "Tire A", "Пауэр Екб", 1900, 12),
        ]
        self.assertIsNone(resolve_register_article("100", "Tire A", lines, self.cfg))

        lines_ok = [RegisterLine("100", "Tire A", "Пауэр Уфа", 2100, 12)]
        result = resolve_register_article("100", "Tire A", lines_ok, self.cfg)
        assert result is not None
        self.assertEqual(result.supplier, "Пауэр Уфа")

    def test_excluded_suppliers_ignored(self):
        lines = [
            RegisterLine("100", "Tire A", "Колобокс Уфа", 1000, 20),
            RegisterLine("100", "Tire A", "Вектра Уфа", 1100, 20),
        ]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        self.assertIsNone(result)

    def test_min_quantity_four(self):
        lines = [RegisterLine("100", "Tire A", "Бринэкс", 2800, 3)]
        self.assertIsNone(resolve_register_article("100", "Tire A", lines, self.cfg))

    def test_moscow_requires_more_than_40(self):
        lines = [
            RegisterLine("100", "Tire A", "Сам МБ Москва", 3200, 40),
            RegisterLine("100", "Tire A", "УШК Бакалинская", 3100, 10),
        ]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        assert result is not None
        self.assertEqual(result.priority, "p5")

    def test_resolve_register_stock_groups_articles(self):
        lines = [
            RegisterLine("100", "Tire A", "Сам МБ Уфа", 3000, 6),
            RegisterLine("200", "Tire B", "Бринэкс", 2500, 8),
        ]
        out = resolve_register_stock(lines, self.cfg)
        self.assertEqual(len(out), 2)
        self.assertEqual({row.article for row in out}, {"100", "200"})

    def test_ushk_in_stock_flag_when_not_selected_supplier(self):
        lines = [
            RegisterLine("100", "Tire A", "УШК Менделеева", 3100, 8),
            RegisterLine("100", "Tire A", "Бринэкс", 2500, 12),
        ]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        assert result is not None
        self.assertEqual(result.priority, "p5")
        self.assertTrue(result.ushk_in_stock)

    def test_ushk_in_stock_false_without_ushk(self):
        lines = [RegisterLine("100", "Tire A", "Бринэкс", 2500, 12)]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        assert result is not None
        self.assertFalse(result.ushk_in_stock)

    def test_sam_mb_cash_price_ufa_4_plus(self):
        lines = [RegisterLine("100", "Tire A", "Сам МБ Уфа", 3000, 4)]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        assert result is not None
        self.assertTrue(result.sam_mb_cash_price)

    def test_sam_mb_cash_price_moscow_40_plus(self):
        lines = [RegisterLine("100", "Tire A", "Сам МБ Москва", 3200, 40)]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        assert result is not None
        self.assertTrue(result.sam_mb_cash_price)

    def test_sam_mb_cash_price_false_below_threshold(self):
        lines = [
            RegisterLine("100", "Tire A", "Сам МБ Уфа", 3000, 3),
            RegisterLine("100", "Tire A", "Сам МБ Москва", 3200, 39),
            RegisterLine("100", "Tire A", "Бринэкс", 2500, 50),
        ]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        assert result is not None
        self.assertFalse(result.sam_mb_cash_price)


if __name__ == "__main__":
    unittest.main()
