import tempfile
import unittest
from pathlib import Path

import pandas as pd

from avito.model_descriptions import (
    load_model_descriptions,
    lookup_model_description,
    merge_model_descriptions_table,
    model_key,
    save_model_descriptions_table,
)


class TestModelDescriptions(unittest.TestCase):
    def test_model_key(self):
        self.assertEqual(model_key("Ikon", "Autograph Ultra 2 SUV"), "Ikon Autograph Ultra 2 SUV")

    def test_lookup_by_prefix(self):
        descs = {"Ikon Autograph Ultra 2 SUV": "<p>x</p>"}
        got = lookup_model_description(
            descs,
            nomenclature="Ikon Autograph Ultra 2 SUV 235/65R17",
            brand="Ikon",
            model="Autograph Ultra 2",
        )
        self.assertEqual(got, "<p>x</p>")

    def test_load_from_excel(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "model_descriptions.xlsx"
            df = pd.DataFrame(
                [
                    {
                        "бренд": "Ikon",
                        "модель": "Autograph",
                        "ключ_модели": "Ikon Autograph",
                        "имя_каноническое": "Ikon Autograph",
                        "словарь_распознан": "да",
                        "каталог_4tochki": "",
                        "описание_html": "<p>text</p>",
                        "источник": "test",
                        "обновлено": "",
                    }
                ]
            )
            save_model_descriptions_table(p, df)
            d = load_model_descriptions(p)
            self.assertIn("Ikon Autograph", d)
            self.assertEqual(d["Ikon Autograph"], "<p>text</p>")

    def test_merge_rekeys_by_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "model_descriptions.xlsx"
            merge_model_descriptions_table(
                p,
                [
                    {
                        "бренд": "Hankook",
                        "модель": "Winter i*Pike RS2 W429",
                        "ключ_модели": "Hankook Winter i*Pike RS2 W429",
                        "имя_каноническое": "",
                        "словарь_распознан": "нет",
                        "каталог_4tochki": "Hankook Winter i*Pike RS2 W429",
                        "описание_html": "<p>old</p>",
                        "источник": "4tochki",
                    }
                ],
                overwrite=True,
            )
            merge_model_descriptions_table(
                p,
                [
                    {
                        "бренд": "Hankook",
                        "модель": "Winter i Pike RS2 W429",
                        "ключ_модели": "Hankook Winter i Pike RS2 W429",
                        "имя_каноническое": "Hankook Winter i Pike RS2 W429",
                        "словарь_распознан": "да",
                        "каталог_4tochki": "Hankook Winter i*Pike RS2 W429",
                        "описание_html": "<p>new</p>",
                        "источник": "4tochki",
                    }
                ],
                overwrite=True,
            )
            d = load_model_descriptions(p)
            self.assertEqual(len(d), 1)
            self.assertIn("Hankook Winter i Pike RS2 W429", d)

    def test_dedupe_removes_legacy_when_canonical_already_in_table(self):
        """Две строки в файле (4tochki-ключ + канон) → остаётся канон."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "model_descriptions.xlsx"
            df = pd.DataFrame(
                [
                    {
                        "бренд": "Hankook",
                        "модель": "Winter i*Pike RS2 W429",
                        "ключ_модели": "Hankook Winter i*Pike RS2 W429",
                        "имя_каноническое": "",
                        "словарь_распознан": "",
                        "каталог_4tochki": "Hankook Winter i*Pike RS2 W429",
                        "описание_html": "<p>old</p>",
                        "источник": "4tochki",
                        "обновлено": "",
                    },
                    {
                        "бренд": "Hankook",
                        "модель": "Winter i Pike RS2 W429",
                        "ключ_модели": "Hankook Winter i Pike RS2 W429",
                        "имя_каноническое": "Hankook Winter i Pike RS2 W429",
                        "словарь_распознан": "да",
                        "каталог_4tochki": "Hankook Winter i*Pike RS2 W429",
                        "описание_html": "<p>new</p>",
                        "источник": "4tochki",
                        "обновлено": "",
                    },
                ]
            )
            save_model_descriptions_table(p, df)
            merge_model_descriptions_table(p, [], overwrite=False)
            d = load_model_descriptions(p)
            self.assertEqual(len(d), 1)
            self.assertIn("Hankook Winter i Pike RS2 W429", d)
            self.assertEqual(d["Hankook Winter i Pike RS2 W429"], "<p>new</p>")

    def test_merge_table_dedupe_by_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "model_descriptions.xlsx"
            rows = [
                {
                    "бренд": "Attar",
                    "модель": "S01",
                    "ключ_модели": "Attar S01",
                    "имя_каноническое": "Attar S01",
                    "словарь_распознан": "да",
                    "каталог_4tochki": "Attar S01",
                    "описание_html": "<p>one</p>",
                    "источник": "4tochki",
                },
                {
                    "бренд": "Attar",
                    "модель": "S01",
                    "ключ_модели": "Attar S01",
                    "каталог_4tochki": "Attar S01",
                    "описание_html": "<p>dup</p>",
                    "источник": "4tochki",
                },
            ]
            stats = merge_model_descriptions_table(p, rows, overwrite=True)
            self.assertEqual(stats["added"], 1)
            d = load_model_descriptions(p)
            self.assertEqual(len(d), 1)


if __name__ == "__main__":
    unittest.main()
