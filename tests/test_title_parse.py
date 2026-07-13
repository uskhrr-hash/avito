import unittest

from avito.description_generator import ModelGenInput, build_user_prompt
from avito.title_parse import parse_title_fields, build_multi_name_from_title


class TestTitleParse(unittest.TestCase):
    def test_yokohama_geolandar_g015(self):
        t = "Yokohama Geolandar G015 245/70 R16 111H"
        f = parse_title_fields(t)
        self.assertEqual(f["brand"], "Yokohama")
        self.assertEqual(f["model"], "Geolandar G015")
        self.assertEqual(f["width"], "245")
        self.assertEqual(f["profile"], "70")
        self.assertEqual(f["diameter"], "16")

    def test_formula_energy(self):
        t = "Formula Energy 205/55 R16"
        f = parse_title_fields(t)
        self.assertEqual(f["brand"], "Formula")
        self.assertEqual(f["model"], "Energy")

    def test_compact_size_without_spaces(self):
        t = "Nokian Hakkapeliitta 205/55R16 91H"
        f = parse_title_fields(t)
        self.assertEqual(f["brand"], "Nokian")
        self.assertIn("Hakkapeliitta", f["model"])
        self.assertEqual(f["width"], "205")

    def test_multi_name_from_size(self):
        self.assertEqual(
            build_multi_name_from_title("Kumho Ecowing ES31 195/65 R15 91H"),
            "19565R15",
        )
        self.assertEqual(
            build_multi_name_from_title("Yokohama Geolandar G015 245/70 R16 111H"),
            "24570R16",
        )
        self.assertEqual(build_multi_name_from_title("No size here"), "")

    def test_winter_english_in_name(self):
        from avito.title_parse import infer_season_from_text

        self.assertEqual(
            infer_season_from_text("Hankook Winter i*Pike RS2 W429 205/55 R16"),
            "Зимние",
        )
        self.assertEqual(
            infer_season_from_text("Cordiant Snow Cross 205/55 R16"),
            "Зимние",
        )
        self.assertEqual(
            infer_season_from_text("Michelin X-Ice Snow 205/55 R16"),
            "Зимние",
        )
        self.assertEqual(
            parse_title_fields("Kumho Ecowing ES31 195/65 R15 91H")["season"],
            "Летние",
        )
        self.assertEqual(
            infer_season_from_text("зимняя шипованная резина"),
            "Зимние",
        )

    def test_prompt_requires_season(self):
        p = build_user_prompt(
            ModelGenInput(
                model_key="Hankook Winter i*Pike RS2 W429",
                brand="Hankook",
                model="Winter i*Pike RS2 W429",
            )
        )
        self.assertIn("обязательно соблюдать", p)
        self.assertIn("Зимние", p)


if __name__ == "__main__":
    unittest.main()
