import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from avito.manager_inbox import photo_relative_path, photo_target_path
from avito.photo_upload.service import (
    next_photo_index,
    pending_photo_meta,
    save_uploaded_photo,
    validate_article,
)
from avito.photo_upload.settings import load_photo_upload_runtime


class TestPhotoUploadPaths(unittest.TestCase):
    def test_relative_path_store_subdir(self):
        rel = photo_relative_path(
            "124889",
            1,
            store_prefix="md",
            photo_layout="store_subdir",
            prefix_in_filename=False,
        )
        self.assertEqual(rel, "md/124889.jpg")

    def test_relative_path_second_photo(self):
        rel = photo_relative_path(
            "124889",
            2,
            store_prefix="md",
            photo_layout="store_subdir",
            prefix_in_filename=False,
        )
        self.assertEqual(rel, "md/124889-2.jpg")

    def test_validate_article(self):
        self.assertEqual(validate_article("124889"), "124889")
        with self.assertRaises(ValueError):
            validate_article("abc")


class TestPhotoUploadService(unittest.TestCase):
    def _runtime(self, tmp: Path):
        config = tmp / "config.yaml"
        secrets = tmp / "secrets.local.yaml"
        stores = tmp / "stores.yaml"
        stock = tmp / "input" / "goods.xlsx"
        photos = tmp / "photos"
        output = tmp / "output"
        photos.mkdir(parents=True)
        output.mkdir(parents=True)
        stock.parent.mkdir(parents=True)

        stores.write_text(
            """
stores:
  - prefix: md
    label: Test MD
    ushk_supplier: УШК Менделеева
  - prefix: pg
    label: Test PG
    ushk_supplier: УШК Пугачева
legacy_unprefixed_store: md
""".strip(),
            encoding="utf-8",
        )
        config.write_text(
            f"""
stores_file: stores.yaml
stock_sources:
  secrets_file: secrets.local.yaml
compare:
  stock_file: input/goods.xlsx
  stock_has_header: false
  stock_indexes:
    article: 0
    nomenclature: 1
    quantity: 2
    price: 3
autoload:
  photos_local_dir: {photos.as_posix()}
  photo_layout: store_subdir
  photo_store_prefix_in_filename: false
  jpeg_quality: 85
  jpeg_max_dimension: 1600
photo_upload:
  enabled: true
""".strip(),
            encoding="utf-8",
        )
        secrets.write_text(
            """
photo_upload:
  session_secret: test-secret
  stores:
    md: pass-md
    pg: pass-pg
  admin:
    login: admin
    password: admin-pass
    display_name: Админ
""".strip(),
            encoding="utf-8",
        )

        import pandas as pd

        pd.DataFrame(
            [
                ["124889", "Test Tire 205/55 R16", "4", "5000"],
                ["103918", "Another Tire", "2", "4000"],
            ]
        ).to_excel(stock, index=False, header=False)

        (output / "autoload_no_photos_2026-07-10.csv").write_text(
            "артикул,номенклатура,магазины,проблема\n"
            "124889,Test Tire 205/55 R16,md,нет фото\n"
            "103918,Another Tire,md,нет фото\n"
            "999999,Other,pg,нет фото\n",
            encoding="utf-8",
        )
        return load_photo_upload_runtime(config_path=config, project_root=tmp)

    def test_runtime_load(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            runtime = self._runtime(Path(tmp_name))
            self.assertEqual(len(runtime.stores), 2)
            self.assertTrue(runtime.photos_dir.is_dir())

    def test_no_photos_queue_filters_store(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            runtime = self._runtime(Path(tmp_name))
            from avito.photo_upload.service import load_no_photos_queue_info

            result = load_no_photos_queue_info(runtime, store_prefix="md")
            self.assertEqual(len(result.items), 2)
            self.assertEqual(result.items[0].article, "124889")

    def test_no_photos_queue_in_store_filter(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            runtime = self._runtime(Path(tmp_name))
            from avito.photo_upload.service import load_no_photos_queue_info

            result = load_no_photos_queue_info(
                runtime,
                store_prefix="md",
                in_store_only=True,
                in_store_articles=frozenset({"103918"}),
            )
            self.assertEqual(len(result.items), 1)
            self.assertEqual(result.items[0].article, "103918")

    def test_no_photos_queue_ushk_override_no_prefix(self):
        """Сотрудник: все магазины в CSV + фильтр по своему УШК."""
        with tempfile.TemporaryDirectory() as tmp_name:
            runtime = self._runtime(Path(tmp_name))
            from avito.photo_upload.service import load_no_photos_queue_info

            result = load_no_photos_queue_info(
                runtime,
                store_prefix="",
                in_store_only=True,
                ushk_supplier="УШК Тест",
                in_store_articles=frozenset({"999999", "124889"}),
            )
            self.assertEqual({r.article for r in result.items}, {"999999", "124889"})

    def test_contributor_ushk_in_db(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            runtime = self._runtime(Path(tmp_name))
            from avito.photo_upload import db as photo_db

            conn = runtime.db()
            try:
                user = photo_db.create_user(
                    conn,
                    login="ivan",
                    password="secret1",
                    role=photo_db.ROLE_CONTRIBUTOR,
                    display_name="Иван",
                    ushk_supplier="УШК Сипайлово",
                )
                self.assertEqual(user.ushk_supplier, "УШК Сипайлово")
                updated = photo_db.set_user_ushk_supplier(
                    conn, user.id, "УШК Проспект Октября"
                )
                self.assertEqual(updated.ushk_supplier, "УШК Проспект Октября")
                again = photo_db.get_user_by_id(conn, user.id)
                self.assertEqual(again.ushk_supplier, "УШК Проспект Октября")
            finally:
                conn.close()

    def test_next_photo_index(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            root = Path(tmp_name)
            runtime = self._runtime(root)
            self.assertEqual(
                next_photo_index(runtime, store_prefix="md", article="124889"),
                1,
            )
            target = photo_target_path(
                runtime.photos_dir,
                "124889",
                1,
                store_prefix="md",
                photo_layout="store_subdir",
                prefix_in_filename=False,
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
            self.assertEqual(
                next_photo_index(runtime, store_prefix="md", article="124889"),
                2,
            )

    def test_pending_photo_meta(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            runtime = self._runtime(Path(tmp_name))
            meta = pending_photo_meta(
                runtime,
                store_prefix="md",
                article="124889",
                index=2,
            )
            self.assertEqual(meta.relative_path, "md/124889-2.jpg")

    def test_save_uploaded_photo(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            runtime = self._runtime(Path(tmp_name))
            image = Image.new("RGB", (120, 80), color=(200, 10, 10))
            buf = BytesIO()
            image.save(buf, format="JPEG")
            rel, was_new = save_uploaded_photo(
                runtime,
                store_prefix="md",
                article="124889",
                index=1,
                data=buf.getvalue(),
            )
            self.assertEqual(rel, "md/124889.jpg")
            self.assertTrue(was_new)
            saved = runtime.photos_dir / "md" / "124889.jpg"
            self.assertTrue(saved.is_file())
            rel2, was_new2 = save_uploaded_photo(
                runtime,
                store_prefix="md",
                article="124889",
                index=1,
                data=buf.getvalue(),
            )
            self.assertEqual(rel2, "md/124889.jpg")
            self.assertFalse(was_new2)


class TestServerHttpsUrls(unittest.TestCase):
    def test_server_https_urls_from_files(self):
        from avito.photos import PhotoNamingSettings, server_https_urls_from_files

        with tempfile.TemporaryDirectory() as tmp_name:
            f = Path(tmp_name) / "124889.jpg"
            f.write_bytes(b"x")
            cfg = PhotoNamingSettings(
                yandex_disk_root="Авито",
                image_count=0,
                image_ext="jpg",
                photos_public_base_url="https://avito.shinaufa.ru/photos",
            )
            out = server_https_urls_from_files(
                [f],
                photos_public_base_url=cfg.photos_public_base_url,
                article="124889",
                layout="store_subdir",
                store_prefix="md",
            )
            self.assertEqual(
                out,
                "https://avito.shinaufa.ru/photos/md/124889.jpg",
            )


if __name__ == "__main__":
    unittest.main()
