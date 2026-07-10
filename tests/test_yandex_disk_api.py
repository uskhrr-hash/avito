import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from avito.photos import (
    StorePhotos,
    build_store_photo_urls,
    is_avito_hosted_photo_urls,
    yandex_https_urls_from_files,
)
from avito.photos import PhotoNamingSettings
from avito.yandex_disk_api import (
    YandexDiskDownloadUrls,
    disk_resource_path,
    load_yandex_oauth_token,
)


class TestYandexDiskApi(unittest.TestCase):
    def test_disk_resource_path(self):
        self.assertEqual(
            disk_resource_path("Авито", "md100-1.jpg"),
            "disk:/Авито/md100-1.jpg",
        )

    def test_load_token_from_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secrets.local.yaml"
            path.write_text(
                "yandex_disk:\n  oauth_token: test-token-123\n",
                encoding="utf-8",
            )
            self.assertEqual(load_yandex_oauth_token(path), "test-token-123")

    def test_is_avito_hosted(self):
        url = (
            "http://avito.ru/autoload/1/items-to-feed/images?"
            "imageSlug=abc123"
        )
        self.assertTrue(is_avito_hosted_photo_urls(url))
        self.assertFalse(is_avito_hosted_photo_urls("yandex_disk://Авито/x.jpg"))

    @patch("avito.yandex_disk_api.requests.request")
    def test_https_urls_from_files(self, mock_request):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "href": "https://downloader.disk.yandex.ru/disk/abc.jpg"
        }
        mock_request.return_value = response

        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "md100-1.jpg"
            f.write_bytes(b"x")
            downloader = YandexDiskDownloadUrls("token")
            urls = yandex_https_urls_from_files(
                [f],
                yandex_disk_root="Авито",
                article="100",
                layout="flat",
                downloader=downloader,
            )
            self.assertIn("https://downloader.disk.yandex.ru", urls)
            self.assertNotIn("yandex_disk://", urls)

    @patch("avito.yandex_disk_api.requests.request")
    def test_build_store_photo_urls_yandex_https(self, mock_request):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"href": "https://downloader.disk.yandex.ru/x"}
        mock_request.return_value = response

        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "md200-1.jpg"
            f.write_bytes(b"x")
            cfg = PhotoNamingSettings(
                yandex_disk_root="Авито",
                image_count=0,
                image_ext="jpg",
            )
            downloader = YandexDiskDownloadUrls("token")
            out = build_store_photo_urls(
                StorePhotos("md", (f,)),
                cfg,
                article="200",
                layout="flat",
                image_mode="yandex_https",
                downloader=downloader,
            )
            self.assertTrue(out.startswith("https://"))


if __name__ == "__main__":
    unittest.main()
