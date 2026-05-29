import unittest

from avito.price import parse_price


class TestParsePrice(unittest.TestCase):
    def test_per_one(self):
        r = parse_price("5 400 ₽ за 1 шт.")
        self.assertEqual(r.price_rub, 5400)
        self.assertEqual(r.price_unit_count, 1)
        self.assertEqual(r.price_per_tire, 5400.0)
        self.assertEqual(r.price_confidence, "exact")

    def test_per_four(self):
        r = parse_price("20 000 ₽ за 4 шт.")
        self.assertEqual(r.price_per_tire, 5000.0)
        self.assertEqual(r.price_unit_count, 4)

    def test_per_two(self):
        r = parse_price("5 000 ₽ за 2 шт.")
        self.assertEqual(r.price_per_tire, 2500.0)

    def test_kit_without_count(self):
        r = parse_price(
            "17 400 ₽",
            extra_text="Продаётся комплектом, цена за наличку",
        )
        self.assertEqual(r.price_confidence, "needs_review")
        self.assertIsNone(r.price_per_tire)

    def test_inferred_single(self):
        r = parse_price("7 950 ₽")
        self.assertEqual(r.price_confidence, "inferred")
        self.assertEqual(r.price_per_tire, 7950.0)


if __name__ == "__main__":
    unittest.main()
