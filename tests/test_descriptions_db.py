import unittest
from unittest.mock import MagicMock, patch

from avito.description_generator import (
    ModelGenInput,
    build_system_prompt,
    build_user_prompt,
    normalize_llm_html,
)
from avito.descriptions_db import html_to_plain, prompt_hash


class TestDescriptionGenerator(unittest.TestCase):
    def test_normalize_strips_fence(self):
        raw = "```html\n<p>Тест</p>\n```"
        self.assertEqual(normalize_llm_html(raw), "<p>Тест</p>")

    def test_plain_text_wrapped(self):
        self.assertTrue(normalize_llm_html("Просто текст").startswith("<p>"))

    def test_build_prompt_includes_facts(self):
        p = build_user_prompt(
            ModelGenInput(
                model_key="Yokohama G015",
                brand="Yokohama",
                model="G015",
                source_facts="<p>Сцепление</p>",
            )
        )
        self.assertIn("Yokohama G015", p)
        self.assertIn("Сцепление", p)

    def test_html_to_plain(self):
        self.assertEqual(html_to_plain("<p>A <strong>B</strong></p>"), "A B")

    def test_prompt_hash_stable(self):
        self.assertEqual(prompt_hash("x"), prompt_hash("x"))


class TestResolveModelDescriptions(unittest.TestCase):
    def test_disabled_uses_xlsx_only(self):
        from pathlib import Path
        import tempfile

        from avito.model_descriptions import resolve_model_descriptions, save_model_descriptions_table
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "m.xlsx"
            save_model_descriptions_table(
                p,
                pd.DataFrame(
                    [
                        {
                            "бренд": "A",
                            "модель": "B",
                            "ключ_модели": "A B",
                            "имя_каноническое": "",
                            "словарь_распознан": "",
                            "каталог_4tochki": "",
                            "описание_html": "<p>x</p>",
                            "источник": "test",
                            "обновлено": "",
                        }
                    ]
                ),
            )
            d = resolve_model_descriptions(
                xlsx_path=p,
                descriptions_db_enabled=False,
            )
            self.assertEqual(d.get("A B"), "<p>x</p>")


class TestDeepSeekClient(unittest.TestCase):
    @patch("avito.deepseek_client.requests.post")
    def test_chat_completion(self, mock_post):
        from avito.deepseek_client import ChatResult, DeepSeekConfig, chat_completion

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "choices": [{"message": {"content": "<p>OK</p>"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
        cfg = DeepSeekConfig(api_key="test")
        r = chat_completion(cfg, system="s", user="u")
        self.assertIsInstance(r, ChatResult)
        self.assertIn("OK", r.content)


if __name__ == "__main__":
    unittest.main()
