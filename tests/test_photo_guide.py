import unittest

from avito.photo_upload.guide import render_guide_html
from avito.photo_upload.overlays import (
    EXAMPLE_FILES,
    ghost_image_for_shot,
    overlay_svg_for_shot,
    shot_label,
)


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
        self.assertEqual(ghost_image_for_shot(1), "")
        self.assertEqual(ghost_image_for_shot(2), "")
        stack_svg = overlay_svg_for_shot(1, camera=True)
        self.assertIn("guide-svg", stack_svg)
        self.assertIn("3 лежат + 1 стоит", stack_svg)
        tread_svg = overlay_svg_for_shot(2, camera=True)
        self.assertIn("Протектор крупно", tread_svg)
        svg = overlay_svg_for_shot(4, camera=True)
        self.assertIn("guide-svg", svg)


if __name__ == "__main__":
    unittest.main()
