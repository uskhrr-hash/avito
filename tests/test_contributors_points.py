"""Тесты баллов, contributors pool и split md/pg."""
from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from avito.photo_upload import db as photo_db
from avito.photo_upload.service import next_photo_index, save_upload_batch
from avito.photos import (
    assign_store_for_contributor_article,
    discover_photos_for_stores,
    resolve_listing_photo_sets,
)


class TestContributorAssign(unittest.TestCase):
    def test_assign_stable_split(self):
        prefixes = ("md", "pg")
        a = assign_store_for_contributor_article("122062", prefixes)
        b = assign_store_for_contributor_article("122062", prefixes)
        self.assertEqual(a, b)
        self.assertIn(a, prefixes)

    def test_discover_contributors_fallback(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            root = Path(tmp_name)
            pool = root / "contributors"
            pool.mkdir()
            f = pool / "555001.jpg"
            img = Image.new("RGB", (40, 40), color=(10, 20, 30))
            buf = BytesIO()
            img.save(buf, format="JPEG")
            f.write_bytes(buf.getvalue())

            found = discover_photos_for_stores(
                root,
                "555001",
                ("md", "pg"),
                layout="store_subdir",
                prefix_in_filename=False,
                contributors_prefix="contributors",
            )
            self.assertEqual(len(found), 1)
            self.assertIn(found[0].prefix, ("md", "pg"))
            self.assertTrue(found[0].files)

    def test_store_photos_beat_contributors(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            root = Path(tmp_name)
            (root / "md").mkdir()
            (root / "contributors").mkdir()
            for folder in ("md", "contributors"):
                img = Image.new("RGB", (40, 40), color=(10, 20, 30))
                buf = BytesIO()
                img.save(buf, format="JPEG")
                (root / folder / "555002.jpg").write_bytes(buf.getvalue())

            found = discover_photos_for_stores(
                root,
                "555002",
                ("md", "pg"),
                layout="store_subdir",
                prefix_in_filename=False,
                contributors_prefix="contributors",
            )
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].prefix, "md")


class TestPointsDb(unittest.TestCase):
    def test_points_on_new_photo_only(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_name:
            from tests.test_photo_upload import TestPhotoUploadService

            helper = TestPhotoUploadService()
            runtime = helper._runtime(Path(tmp_name))
            with runtime.db() as conn:
                user = photo_db.create_user(
                    conn,
                    login="worker1",
                    password="secret",
                    role=photo_db.ROLE_CONTRIBUTOR,
                    display_name="Worker",
                )
            img = Image.new("RGB", (80, 60), color=(40, 50, 60))
            buf = BytesIO()
            img.save(buf, format="JPEG")
            data = buf.getvalue()

            r1 = save_upload_batch(
                runtime,
                store_prefix=runtime.contributors_prefix,
                article="777001",
                items=[(1, data), (2, data)],
                max_index=10,
                contributor_user_id=user.id,
            )
            self.assertEqual(r1.points_awarded, 20)
            self.assertEqual(r1.balance, 20)

            r2 = save_upload_batch(
                runtime,
                store_prefix=runtime.contributors_prefix,
                article="777001",
                items=[(1, data)],
                max_index=10,
                contributor_user_id=user.id,
            )
            self.assertEqual(r2.points_awarded, 0)
            self.assertEqual(r2.balance, 20)

            self.assertEqual(
                next_photo_index(
                    runtime,
                    store_prefix=runtime.contributors_prefix,
                    article="777001",
                    max_index=10,
                ),
                3,
            )

            with runtime.db() as conn:
                bal = photo_db.deduct_points(
                    conn,
                    user_id=user.id,
                    amount=15,
                    reason="тест",
                    admin_id=user.id,
                )
            self.assertEqual(bal, 5)

    def test_max_10_raises(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_name:
            from tests.test_photo_upload import TestPhotoUploadService

            helper = TestPhotoUploadService()
            runtime = helper._runtime(Path(tmp_name))
            prefix = runtime.contributors_prefix
            for i in range(1, 11):
                target = runtime.photos_dir / prefix / (
                    "888001.jpg" if i == 1 else f"888001-{i}.jpg"
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"x")
            with self.assertRaises(ValueError):
                next_photo_index(
                    runtime,
                    store_prefix=prefix,
                    article="888001",
                    max_index=10,
                )


class TestResolveContributors(unittest.TestCase):
    def test_resolve_uses_contributors(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            root = Path(tmp_name)
            pool = root / "contributors"
            pool.mkdir()
            img = Image.new("RGB", (40, 40), color=(1, 2, 3))
            buf = BytesIO()
            img.save(buf, format="JPEG")
            (pool / "666001.jpg").write_bytes(buf.getvalue())

            resolved = resolve_listing_photo_sets(
                root,
                "666001",
                ("md", "pg"),
                layout="store_subdir",
                prefix_in_filename=False,
                contributors_prefix="contributors",
            )
            self.assertEqual(len(resolved.store_sets), 1)
            self.assertEqual(resolved.source, "article")


if __name__ == "__main__":
    unittest.main()
