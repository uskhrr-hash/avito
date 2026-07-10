import unittest

from avito.pricing import fixed_price_recommendation, recommend_price, round_price_to_tens


class TestPricingRules(unittest.TestCase):
    def test_no_avito(self):
        r = recommend_price(4000, None, seed="x", date_key="2026-05-29")
        self.assertEqual(r.recommended_price, 4600)
        self.assertEqual(r.price_rule, "no_avito_x1.15")

    def test_avito_minus_without_floor(self):
        r = recommend_price(4000, 5000, seed="x", date_key="2026-05-29")
        self.assertGreaterEqual(r.recommended_price, 4400)
        self.assertIn("avito_minus_", r.price_rule)

    def test_floor_when_discount_too_low(self):
        # avito 4500, 3% -> 4365 < floor 4400
        r = recommend_price(
            4000,
            4500,
            seed="force3",
            date_key="2026-05-29",
            discounts=(0.03,),
        )
        self.assertEqual(r.recommended_price, 4400)
        self.assertIn("floor", r.price_rule)

    def test_stable_seed(self):
        a = recommend_price(1000, 2000, seed="same", date_key="d1")
        b = recommend_price(1000, 2000, seed="same", date_key="d1")
        self.assertEqual(a.recommended_price, b.recommended_price)

    def test_round_to_tens(self):
        self.assertEqual(round_price_to_tens(4604), 4600)
        self.assertEqual(round_price_to_tens(4605), 4600)
        self.assertEqual(round_price_to_tens(4606), 4610)

    def test_fixed_google_price(self):
        r = fixed_price_recommendation(5437, 4000, 5000)
        self.assertEqual(r.recommended_price, 5440)
        self.assertEqual(r.price_rule, "fixed_google")


if __name__ == "__main__":
    unittest.main()
