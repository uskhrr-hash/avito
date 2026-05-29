import unittest

from avito.photos import PhotoNamingSettings, photo_filenames, yandex_disk_urls


class TestPhotos(unittest.TestCase):
    def test_flat_one(self):
        cfg = PhotoNamingSettings("Авито", 1, "jpg", "flat")
        self.assertEqual(photo_filenames("58971", cfg), ["58971.jpg"])

    def test_flat_many(self):
        cfg = PhotoNamingSettings("Авито", 3, "jpg", "flat")
        self.assertEqual(
            photo_filenames("58971", cfg),
            ["58971.jpg", "58971-2.jpg", "58971-3.jpg"],
        )

    def test_flat_four(self):
        cfg = PhotoNamingSettings("Авито", 4, "webp", "flat")
        self.assertEqual(
            photo_filenames("165935", cfg),
            ["165935.webp", "165935-2.webp", "165935-3.webp", "165935-4.webp"],
        )

    def test_folder(self):
        cfg = PhotoNamingSettings("Авито", 2, "jpg", "folder")
        self.assertEqual(photo_filenames("58971", cfg), ["58971/1.jpg", "58971/2.jpg"])

    def test_urls(self):
        cfg = PhotoNamingSettings("Авито", 2, "jpg", "flat")
        u = yandex_disk_urls("58971", cfg)
        self.assertIn("yandex_disk://Авито/58971.jpg", u)
        self.assertIn("58971-2.jpg", u)


if __name__ == "__main__":
    unittest.main()
