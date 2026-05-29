import unittest

import pandas as pd

from avito.compare import avito_min_by_title


class TestCompareMatch(unittest.TestCase):
    def test_exact_title_key(self):
        df = pd.DataFrame(
            [
                {
                    "title": "Yokohama ES32 205/55 R16",
                    "price_per_tire": 5000,
                    "is_own": False,
                    "price_confidence": "exact",
                },
                {
                    "title": "Yokohama ES32 205/55 R16 ",
                    "price_per_tire": 4800,
                    "is_own": False,
                    "price_confidence": "exact",
                },
                {
                    "title": "Yokohama ES32 205/55 R16",
                    "price_per_tire": 1000,
                    "is_own": True,
                    "price_confidence": "exact",
                },
            ]
        )
        mins = avito_min_by_title(df, exclude_needs_review=True)
        self.assertEqual(mins["Yokohama ES32 205/55 R16"], 4800)

    def test_no_normalize_different_strings(self):
        df = pd.DataFrame(
            [
                {
                    "title": "A",
                    "price_per_tire": 100,
                    "is_own": False,
                    "price_confidence": "exact",
                },
                {
                    "title": "a",
                    "price_per_tire": 200,
                    "is_own": False,
                    "price_confidence": "exact",
                },
            ]
        )
        mins = avito_min_by_title(df, exclude_needs_review=False)
        self.assertEqual(len(mins), 2)


if __name__ == "__main__":
    unittest.main()
