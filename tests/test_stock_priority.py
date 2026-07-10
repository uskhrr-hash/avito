import unittest

from avito.stock_priority import (
    RegisterLine,
    StockPriorityConfig,
    resolve_register_article,
    resolve_register_stock,
)


class TestStockPriority(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = StockPriorityConfig()

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
            RegisterLine("100", "Tire A", "Колесо", 2800, 12),
            RegisterLine("100", "Tire A", "63 шинный", 3397, 11),
        ]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        assert result is not None
        self.assertEqual(result.priority, "p6")
        self.assertEqual(result.base_price, 2800.0)

    def test_excluded_suppliers_ignored(self):
        lines = [
            RegisterLine("100", "Tire A", "Колобокс Уфа", 1000, 20),
            RegisterLine("100", "Tire A", "Вектра Уфа", 1100, 20),
        ]
        result = resolve_register_article("100", "Tire A", lines, self.cfg)
        self.assertIsNone(result)

    def test_min_quantity_four(self):
        lines = [RegisterLine("100", "Tire A", "Колесо", 2800, 3)]
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
            RegisterLine("200", "Tire B", "Колесо", 2500, 8),
        ]
        out = resolve_register_stock(lines, self.cfg)
        self.assertEqual(len(out), 2)
        self.assertEqual({row.article for row in out}, {"100", "200"})


if __name__ == "__main__":
    unittest.main()
