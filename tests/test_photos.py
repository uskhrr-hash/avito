import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from avito.photos import (
    StorePhotos,
    discover_model_photos,
    discover_photos_for_stores,
    discover_prefixed_photos,
    model_photo_label,
    newest_file_mtime,
    prefixed_stem_variants,
    resolve_listing_photo_sets,
    select_store_when_conflict,
    yandex_disk_urls_from_files,
)
from avito.stores import Store, StoresConfig


def _stores(*prefixes: str) -> StoresConfig:
    return StoresConfig(
        stores=tuple(
            Store(prefix=p, label=p, fields={}) for p in prefixes
        ),
        legacy_unprefixed_store=None,
    )


class TestPhotos(unittest.TestCase):
    def test_prefixed_stems(self):
        self.assertIn("md103926", prefixed_stem_variants("md", "103926", 1))
        self.assertIn("md103926-1", prefixed_stem_variants("md", "103926", 1))
        self.assertEqual(prefixed_stem_variants("md", "103926", 2), ["md103926-2"])

    def test_discover_md_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "md103926-1.jpg").write_bytes(b"x")
            found = discover_prefixed_photos(folder, "md", "103926")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].name, "md103926-1.jpg")

    def test_discover_md_prefix_store_subdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sub = folder / "md"
            sub.mkdir()
            (sub / "103926-1.jpg").write_bytes(b"x")
            found = discover_prefixed_photos(
                folder,
                "md",
                "103926",
                layout="store_subdir",
                prefix_in_filename=False,
            )
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].name, "103926-1.jpg")

    def test_yandex_urls_store_subdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sub = folder / "md"
            sub.mkdir()
            f = sub / "md165309-5.jpg"
            f.write_bytes(b"x")
            u = yandex_disk_urls_from_files(
                [f],
                yandex_disk_root="Авито",
                article="165309",
                layout="store_subdir",
                store_prefix="md",
            )
            self.assertIn("yandex_disk://Авито/md/md165309-5.jpg", u)

    def test_discover_multi_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "md100.jpg").write_bytes(b"x")
            (folder / "sc100.jpg").write_bytes(b"x")
            result = discover_photos_for_stores(
                folder, "100", ("md", "sc"), legacy_unprefixed_prefix=None
            )
            self.assertEqual(len(result), 2)
            prefixes = {r.prefix for r in result}
            self.assertEqual(prefixes, {"md", "sc"})

    def test_conflict_same_day_earlier_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            early = folder / "md100.jpg"
            late = folder / "sc100.jpg"
            early.write_bytes(b"x")
            time.sleep(0.05)
            late.write_bytes(b"x")
            # same day guaranteed
            cands = [
                StorePhotos("md", (early,)),
                StorePhotos("sc", (late,)),
            ]
            winner = select_store_when_conflict(cands)
            self.assertEqual(winner.prefix, "md")

    def test_conflict_uses_newest_file_not_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            now = datetime.now()
            md_old = folder / "md100-1.jpg"
            md_new = folder / "md100-2.jpg"
            sc_one = folder / "sc100-1.jpg"
            md_old.write_bytes(b"a")
            md_new.write_bytes(b"b")
            sc_one.write_bytes(b"c")
            noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
            md_old_ts = (noon - timedelta(hours=2)).timestamp()
            sc_ts = noon.timestamp()
            md_new_ts = (noon + timedelta(hours=2)).timestamp()
            os.utime(md_old, (md_old_ts, md_old_ts))
            os.utime(sc_one, (sc_ts, sc_ts))
            os.utime(md_new, (md_new_ts, md_new_ts))
            self.assertEqual(newest_file_mtime((md_old, md_new)), md_new_ts)
            cands = [
                StorePhotos("md", (md_old, md_new)),
                StorePhotos("sc", (sc_one,)),
            ]
            winner = select_store_when_conflict(cands)
            # один день: sc в полдень раньше, чем md100-2 в 14:00
            self.assertEqual(winner.prefix, "sc")

    def test_conflict_different_days_newer_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            old = folder / "md100.jpg"
            new = folder / "sc100.jpg"
            now = datetime.now()
            old.write_bytes(b"x")
            new.write_bytes(b"y")
            old_ts = (now - timedelta(days=5)).timestamp()
            new_ts = now.timestamp()
            os.utime(old, (old_ts, old_ts))
            os.utime(new, (new_ts, new_ts))
            cands = [
                StorePhotos("md", (old,)),
                StorePhotos("sc", (new,)),
            ]
            winner = select_store_when_conflict(cands)
            self.assertEqual(winner.prefix, "sc")

    def test_model_photo_label(self):
        self.assertEqual(model_photo_label("Formula", "Energy"), "Formula Energy")
        self.assertEqual(model_photo_label("Nokian", ""), "Nokian")

    def test_discover_model_photos(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "Formula Energy.jpg").write_bytes(b"x")
            (folder / "Formula Energy-2.jpg").write_bytes(b"y")
            found = discover_model_photos(folder, "Formula", "Energy")
            self.assertEqual(len(found), 2)
            self.assertEqual(found[0].name, "Formula Energy.jpg")

    def test_resolve_model_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "Formula Energy-1.jpg").write_bytes(b"x")
            resolved = resolve_listing_photo_sets(
                folder,
                "99999",
                ("md",),
                brand="Formula",
                model="Energy",
                model_fallback=True,
                legacy_unprefixed_prefix="md",
            )
            self.assertEqual(resolved.source, "model")
            self.assertEqual(len(resolved.store_sets), 1)
            self.assertEqual(resolved.store_sets[0].files[0].name, "Formula Energy-1.jpg")

    def test_resolve_prefers_article_over_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "md100-1.jpg").write_bytes(b"a")
            (folder / "Formula Energy.jpg").write_bytes(b"b")
            resolved = resolve_listing_photo_sets(
                folder,
                "100",
                ("md",),
                brand="Formula",
                model="Energy",
                model_fallback=True,
                legacy_unprefixed_prefix="md",
            )
            self.assertEqual(resolved.source, "article")
            self.assertEqual(resolved.store_sets[0].files[0].name, "md100-1.jpg")

    def test_urls_use_jpg_for_webp_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "md58971-2.webp"
            f.write_bytes(b"x")
            u = yandex_disk_urls_from_files(
                [f], yandex_disk_root="Авито", article="58971", layout="flat"
            )
            self.assertIn("md58971-2.jpg", u)
            self.assertNotIn(".webp", u)

    def test_discover_heic_returns_jpg_path(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            heic = folder / "md12044-1.webp"
            Image.new("RGB", (4, 4)).save(heic, format="WEBP")
            found = discover_prefixed_photos(folder, "md", "12044")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].suffix.lower(), ".jpg")
            self.assertTrue(found[0].is_file())


if __name__ == "__main__":
    unittest.main()
