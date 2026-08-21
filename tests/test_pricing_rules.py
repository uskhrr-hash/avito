import unittest

from avito.pricing import fixed_price_recommendation, recommend_price, round_price_to_tens


class TestPricingRules(unittest.TestCase):
    def test_markup(self):
        r = recommend_price(4000)
        self.assertEqual(r.recommended_price, 4600)
        self.assertEqual(r.price_rule, "markup_x1.15")

    def test_custom_multiplier(self):
        r = recommend_price(4000, no_avito_multiplier=1.2)
        self.assertEqual(r.recommended_price, 4800)
        self.assertEqual(r.price_rule, "markup_x1.2")

    def test_round_to_tens(self):
        self.assertEqual(round_price_to_tens(4604), 4600)
        self.assertEqual(round_price_to_tens(4605), 4600)
        self.assertEqual(round_price_to_tens(4606), 4610)

    def test_manual_price(self):
        r = fixed_price_recommendation(5437, 4000)
        self.assertEqual(r.recommended_price, 5440)
        self.assertEqual(r.price_rule, "manual")


if __name__ == "__main__":
    unittest.main()
