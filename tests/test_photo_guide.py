import unittest

from avito.photo_upload.guide import render_guide_html


class TestPhotoGuide(unittest.TestCase):
    def test_render_guide_contains_four_sections(self):
        html = render_guide_html(base="/photo/")
        self.assertIn("Стопка шин", html)
        self.assertIn("Протектор крупно", html)
        self.assertIn("Страна производства", html)
        self.assertIn("Год выпуска", html)
        self.assertIn('class="guide-svg"', html)
        self.assertIn("артикул-4.jpg", html)


if __name__ == "__main__":
    unittest.main()
