import tempfile
import unittest
from pathlib import Path

from avito.photo_convert import (
    compress_image_in_place,
    convert_folder_to_jpeg,
    convert_image_to_jpeg,
    jpeg_output_path,
    needs_jpeg_compression,
    needs_jpeg_conversion,
    normalize_yandex_photo_urls,
)
from avito.photos import discover_prefixed_photos


class TestPhotoConvert(unittest.TestCase):
    def test_needs_conversion(self):
        self.assertTrue(needs_jpeg_conversion(Path("a.HEIC")))
        self.assertTrue(needs_jpeg_conversion(Path("a.heif")))
        self.assertTrue(needs_jpeg_conversion(Path("a.webp")))
        self.assertFalse(needs_jpeg_conversion(Path("a.jpg")))

    def test_webp_to_jpeg(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            src = folder / "md100-1.webp"
            dst = jpeg_output_path(src)
            Image.new("RGB", (4, 4), color=(120, 80, 40)).save(src, format="WEBP")
            convert_image_to_jpeg(src, dst, quality=90)
            self.assertTrue(dst.is_file())
            with Image.open(dst) as img:
                self.assertEqual(img.format, "JPEG")

    def test_folder_prefers_jpg_after_convert(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            heic_like = folder / "md103926-1.webp"
            Image.new("RGB", (8, 8), color=(10, 20, 30)).save(
                heic_like, format="WEBP"
            )
            conv = convert_folder_to_jpeg(folder)
            self.assertEqual(conv.converted, 1)
            found = discover_prefixed_photos(folder, "md", "103926")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].suffix.lower(), ".jpg")

    def test_normalize_yandex_urls(self):
        raw = (
            "yandex_disk://Авито/md12044-1.heic | "
            "yandex_disk://Авито/md12044-2.HEIC | "
            "yandex_disk://Авито/md12044-3.webp"
        )
        out = normalize_yandex_photo_urls(raw)
        self.assertIn("md12044-1.jpg", out)
        self.assertIn("md12044-2.jpg", out)
        self.assertIn("md12044-3.jpg", out)
        self.assertNotIn(".heic", out.lower())
        self.assertNotIn(".webp", out.lower())

    def test_compress_large_jpeg(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "md100-1.jpg"
            Image.new("RGB", (3000, 2000), color=(40, 80, 120)).save(
                path, format="JPEG", quality=95
            )
            before = path.stat().st_size
            self.assertTrue(
                needs_jpeg_compression(path, min_bytes=10_000, max_dimension=1920)
            )
            self.assertTrue(
                compress_image_in_place(
                    path, quality=80, max_dimension=1920, min_bytes=10_000
                )
            )
            after = path.stat().st_size
            with Image.open(path) as img:
                self.assertLessEqual(max(img.size), 1920)
            self.assertLess(after, before)

    def test_skip_small_jpeg(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "md100-1.jpg"
            Image.new("RGB", (800, 600), color=(10, 10, 10)).save(
                path, format="JPEG", quality=85
            )
            self.assertFalse(
                needs_jpeg_compression(path, min_bytes=400_000, max_dimension=1920)
            )
            self.assertFalse(
                compress_image_in_place(
                    path, quality=80, max_dimension=1920, min_bytes=400_000
                )
            )

    def test_skip_when_jpg_newer(self):
        from PIL import Image
        import os
        import time

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            src = folder / "md100.webp"
            dst = folder / "md100.jpg"
            Image.new("RGB", (4, 4)).save(src, format="WEBP")
            Image.new("RGB", (4, 4)).save(dst, format="JPEG")
            time.sleep(0.05)
            os.utime(dst, (dst.stat().st_mtime + 10,) * 2)
            conv = convert_folder_to_jpeg(folder)
            self.assertEqual(conv.skipped, 1)
            self.assertEqual(conv.converted, 0)


if __name__ == "__main__":
    unittest.main()
