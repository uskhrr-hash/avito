import unittest

import pandas as pd

from avito.compare import _apply_match_keys, avito_min_by_title


class TestCompareMatch(unittest.TestCase):
    def test_canonical_key_only_when_recognized(self):
        df = _apply_match_keys(
            pd.DataFrame(
                [
                    {
                        "title": "Raw Avito Title",
                        "name_canonical": "Brand Model 205/55 R16 91V",
                        "dict_recognized": True,
                    },
                    {
                        "title": "Unknown Tyres 205/55 R16",
                        "name_canonical": "",
                        "dict_recognized": False,
                    },
                ]
            )
        )
        self.assertEqual(df.iloc[0]["match_key"], "Brand Model 205/55 R16 91V")
        self.assertEqual(df.iloc[1]["match_key"], "")

    def test_min_by_canonical_groups_listings(self):
        df = _apply_match_keys(
            pd.DataFrame(
                [
                    {
                        "title": "A long avito title 1",
                        "name_canonical": "Yokohama ES32 205/55 R16 91V",
                        "dict_recognized": True,
                        "price_per_tire": 5000,
                        "is_own": False,
                        "price_confidence": "exact",
                    },
                    {
                        "title": "Another avito title 2",
                        "name_canonical": "Yokohama ES32 205/55 R16 91V",
                        "dict_recognized": True,
                        "price_per_tire": 4700,
                        "is_own": False,
                        "price_confidence": "exact",
                    },
                ]
            )
        )
        mins = avito_min_by_title(df, exclude_needs_review=True)
        self.assertEqual(mins["Yokohama ES32 205/55 R16 91V"], 4700)

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
