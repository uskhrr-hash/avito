import unittest

from avito.photo_upload.guide import render_guide_html
from avito.photo_upload.overlays import overlay_svg_for_shot, shot_label


class TestPhotoGuide(unittest.TestCase):
    def test_render_guide_contains_examples(self):
        html = render_guide_html(base="/photo/")
        self.assertIn("guide-example", html)
        self.assertIn("static/guide/examples/01-stack.jpg", html)
        self.assertIn("static/guide/examples/04-dot.jpg", html)
        self.assertIn("контур появится поверх камеры", html)

    def test_shot_labels_and_overlays(self):
        meta = shot_label(3)
        self.assertIn("Страна", meta["title"])
        svg = overlay_svg_for_shot(4, camera=True)
        self.assertIn("guide-svg", svg)
        self.assertIn("opacity:0.92", svg)


if __name__ == "__main__":
    unittest.main()
