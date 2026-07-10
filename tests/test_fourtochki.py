import tempfile
import unittest
from pathlib import Path

from avito.fourtochki import (
    FourtochkiCatalog,
    ModelCatalogEntry,
    build_dictionary_index,
    build_model_description_index,
    catalog_query_title,
    collect_model_keys_from_nomenclatures,
    dict_model_key,
    dictionary_fields_to_canonical,
    html_to_avito_description,
    link_descriptions_to_goods,
    load_catalog_json,
    lookup_description_for_nom,
    make_description_table_row,
    match_catalog_key,
    parse_marka_model_xml,
    map_catalog_dictionary_results,
    resolve_canonical_model,
    save_catalog_json,
    strip_size_from_canonical_name,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
XML_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<data>
  <tyre>
    <marka>
      <name>Ikon</name>
      <html>https://example.com/ikon</html>
      <models>
        <model>
          <name>Autograph Ultra 2 SUV</name>
          <html>https://example.com/ikon/suv</html>
        </model>
      </models>
    </marka>
    <marka>
      <name>Nokian Tyres</name>
      <models>
        <model>
          <name>Hakka Black</name>
          <html>https://example.com/nokian/hakka</html>
        </model>
      </models>
    </marka>
  </tyre>
</data>
"""


class TestFourtochki(unittest.TestCase):
    def test_parse_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sample.xml"
            p.write_text(XML_SAMPLE, encoding="utf-8")
            cat = parse_marka_model_xml(p)
            self.assertIn("Ikon Autograph Ultra 2 SUV", cat.models)
            self.assertEqual(cat.models["Nokian Tyres Hakka Black"].url, "https://example.com/nokian/hakka")

    def test_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sample.xml"
            p.write_text(XML_SAMPLE, encoding="utf-8")
            cat = parse_marka_model_xml(p)
            j = Path(tmp) / "cat.json"
            save_catalog_json(cat, j)
            loaded = load_catalog_json(j)
            self.assertEqual(len(loaded.models), 2)

    def test_match_catalog_key(self):
        models = {
            "Ikon Autograph Ultra 2 SUV": ModelCatalogEntry(
                brand="Ikon", model="Autograph Ultra 2 SUV", url="u"
            ),
            "Nokian Tyres Hakka Black": ModelCatalogEntry(
                brand="Nokian Tyres", model="Hakka Black", url="u"
            ),
        }
        nom = "Ikon Autograph Ultra 2 SUV 235/65R17 108H"
        self.assertEqual(match_catalog_key(nom, models), "Ikon Autograph Ultra 2 SUV")
        nom2 = "Nokian Tyres Hakka Black 2 SUV 235/65R17 108H"
        self.assertEqual(match_catalog_key(nom2, models), "Nokian Tyres Hakka Black")

    def test_collect_keys(self):
        cat = FourtochkiCatalog(
            models={
                "Ikon Autograph Ultra 2 SUV": ModelCatalogEntry(
                    brand="Ikon",
                    model="Autograph Ultra 2 SUV",
                    url="https://example.com",
                )
            },
            brands={},
        )
        keys = collect_model_keys_from_nomenclatures(
            ["Ikon Autograph Ultra 2 SUV 235/65R17 108H"],
            cat,
        )
        self.assertEqual(keys["Ikon Autograph Ultra 2"], "Ikon Autograph Ultra 2 SUV")

    def test_html_to_avito(self):
        raw = (FIXTURES / "4tochki_Autograph_Ultra_2_SUV.html").read_text(encoding="utf-8")
        out = html_to_avito_description(raw)
        self.assertIn("<p>", out)
        self.assertIn("<ul>", out)
        self.assertIn("<li>", out)
        self.assertIn("Ikon Autograph Ultra 2 SUV", out)
        self.assertNotIn("<img", out)
        self.assertNotIn("<b>", out)

    def test_dictionary_fields_to_canonical_strips_size(self):
        fields = {
            "brand": "Hankook",
            "model": "Winter i Pike RS2 W429",
            "name": "Hankook Winter i Pike RS2 W429 205/55 R16 91V",
        }
        canon = dictionary_fields_to_canonical(fields)
        self.assertEqual(canon["ключ_модели"], "Hankook Winter i Pike RS2 W429")
        self.assertEqual(canon["имя_каноническое"], "Hankook Winter i Pike RS2 W429")
        self.assertNotIn("205/55", canon["ключ_модели"])

    def test_batch_dictionary_maps_asterisk_catalog_key(self):
        catalog_key = "Hankook Winter i*Pike RS2 W429"
        query = catalog_query_title(catalog_key)
        parsed = {
            query: {
                "brand": "Hankook",
                "model": "Winter i Pike RS2 W429",
                "name": "Hankook Winter i Pike RS2 W429 205/55 R16 91V",
            }
        }
        mapped = map_catalog_dictionary_results([catalog_key], parsed)
        self.assertIn(catalog_key, mapped)
        canon = resolve_canonical_model(
            catalog_key=catalog_key,
            catalog_brand="Hankook",
            catalog_model="Winter i*Pike RS2 W429",
            normalized_catalog=parsed,
        )
        self.assertEqual(canon["словарь_распознан"], "да")
        self.assertEqual(canon["ключ_модели"], "Hankook Winter i Pike RS2 W429")
        self.assertEqual(canon["модель"], "Winter i Pike RS2 W429")

    def test_strip_size_from_name(self):
        self.assertEqual(
            strip_size_from_canonical_name("Attar S01 185/65 R15 92V"),
            "Attar S01",
        )

    def test_resolve_canonical_from_dict(self):
        query = catalog_query_title("Ikon Autograph Ultra 2 SUV")
        parsed = {
            query: {
                "brand": "Ikon",
                "model": "Autograph Ultra 2 SUV",
                "name": "Ikon Autograph Ultra 2 SUV 205/55 R16 91V",
            }
        }
        cat = FourtochkiCatalog(
            models={
                "Ikon Autograph Ultra 2 SUV": ModelCatalogEntry(
                    brand="Ikon", model="Autograph Ultra 2 SUV", url="u"
                )
            },
            brands={},
        )
        dictionary = build_dictionary_index(parsed, catalog=cat)
        canon = resolve_canonical_model(
            catalog_key="Ikon Autograph Ultra 2 SUV",
            catalog_brand="Ikon",
            catalog_model="Autograph Ultra 2 SUV",
            dictionary=dictionary,
        )
        self.assertEqual(canon["словарь_распознан"], "да")
        self.assertEqual(canon["ключ_модели"], "Ikon Autograph Ultra 2 SUV")
        self.assertEqual(canon["имя_каноническое"], "Ikon Autograph Ultra 2 SUV")

    def test_make_table_row_fallback_4tochki(self):
        row = make_description_table_row(
            catalog_key="Unknown X",
            catalog_brand="Unknown",
            catalog_model="X",
            description_html="<p>x</p>",
            dictionary=build_dictionary_index({}),
        )
        self.assertEqual(row["словарь_распознан"], "нет")
        self.assertEqual(row["ключ_модели"], "")

    def test_catalog_query_title(self):
        self.assertTrue(catalog_query_title("Ikon Autograph Ultra 2 SUV").endswith("91V"))

    def test_build_index_via_dictionary(self):
        cat = FourtochkiCatalog(
            models={
                "Ikon Autograph Ultra 2 SUV": ModelCatalogEntry(
                    brand="Ikon",
                    model="Autograph Ultra 2 SUV",
                    url="https://example.com",
                )
            },
            brands={},
        )
        bulk = {
            "models": {
                "Ikon Autograph Ultra 2 SUV": {
                    "description_html": "<p>test</p>",
                    "status": "ok",
                }
            }
        }
        query = catalog_query_title("Ikon Autograph Ultra 2 SUV")
        parsed = {
            query: {
                "brand": "Ikon",
                "model": "Autograph Ultra 2 SUV",
                "name": "Ikon Autograph Ultra 2 SUV 205/55 R16 91V",
            }
        }
        dictionary = build_dictionary_index(parsed, catalog=cat)
        index = build_model_description_index(bulk, dictionary, cat)
        self.assertEqual(index["Ikon Autograph Ultra 2 SUV"], "<p>test</p>")
        self.assertEqual(index[dict_model_key(parsed[query])], "<p>test</p>")
        self.assertNotIn("Ikon Autograph Ultra 2 SUV 205/55 R16 91V", index)

    def test_link_goods_via_dictionary(self):
        cat = FourtochkiCatalog(
            models={
                "Ikon Autograph Ultra 2 SUV": ModelCatalogEntry(
                    brand="Ikon",
                    model="Autograph Ultra 2 SUV",
                    url="https://example.com",
                )
            },
            brands={},
        )
        bulk = {
            "models": {
                "Ikon Autograph Ultra 2 SUV": {
                    "description_html": "<p>suv</p>",
                    "status": "ok",
                }
            }
        }
        nom = "Ikon Autograph Ultra 2 SUV 235/65R17 108H"
        goods_norm = {
            nom: {
                "brand": "Ikon",
                "model": "Autograph Ultra 2 SUV",
                "name": nom,
            }
        }
        dictionary = build_dictionary_index(
            goods_norm,
            catalog=cat,
            goods_nomenclatures=[nom],
        )
        table_rows, report = link_descriptions_to_goods(
            bulk,
            cat,
            [nom],
            dictionary,
        )
        self.assertTrue(report[0]["есть_описание"])
        keys = {r["ключ_модели"] for r in table_rows}
        self.assertIn("Ikon Autograph Ultra 2 SUV", keys)
        self.assertEqual(len(table_rows), 1)

    def test_lookup_catalog_prefix_without_dict(self):
        cat = FourtochkiCatalog(
            models={
                "Nokian Tyres Hakka Black": ModelCatalogEntry(
                    brand="Nokian Tyres",
                    model="Hakka Black",
                    url="u",
                )
            },
            brands={},
        )
        index = {"Nokian Tyres Hakka Black": "<p>x</p>"}
        nom = "Nokian Tyres Hakka Black 2 SUV 235/65R17 108H"
        html, matched_by, cat_key = lookup_description_for_nom(
            nom,
            goods_fields=None,
            model_index=index,
            catalog=cat,
        )
        self.assertEqual(html, "<p>x</p>")
        self.assertEqual(matched_by, "catalog_prefix")

if __name__ == "__main__":
    unittest.main()
