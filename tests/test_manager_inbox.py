import tempfile
import unittest
from pathlib import Path

from avito.manager_inbox import import_manager_inbox, parse_inbox_filename
from avito.photos import discover_photos_for_stores


class TestManagerInbox(unittest.TestCase):
    def test_parse_filename(self):
        parsed = parse_inbox_filename("124889.jpg")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.article, "124889")
        self.assertIsNone(parsed.store_prefix)

    def test_parse_prefixed_filename(self):
        parsed = parse_inbox_filename("md124889-2.JPG", ("md", "sc"))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.article, "124889")
        self.assertEqual(parsed.store_prefix, "md")

    def test_import_from_store_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "входящие"
            (inbox / "md").mkdir(parents=True)
            target = root / "Авито"
            target.mkdir()
            (inbox / "md" / "124889.jpg").write_bytes(b"x")
            stats = import_manager_inbox(inbox, target, store_prefixes=("md",))
            self.assertEqual(stats.imported, 1)
            self.assertTrue((target / "md124889.jpg").is_file())
            self.assertEqual(stats.by_store.get("md"), 1)

    def test_import_store_subdir_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "входящие"
            (inbox / "md").mkdir(parents=True)
            target = root / "Авито"
            target.mkdir()
            (inbox / "md" / "124889.jpg").write_bytes(b"x")
            stats = import_manager_inbox(
                inbox,
                target,
                store_prefixes=("md",),
                photo_layout="store_subdir",
                prefix_in_filename=False,
            )
            self.assertEqual(stats.imported, 1)
            self.assertTrue((target / "md" / "124889.jpg").is_file())

    def test_discover_store_subdir_unprefixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sub = folder / "md"
            sub.mkdir()
            (sub / "165309-1.jpg").write_bytes(b"x")
            (sub / "165309-2.jpg").write_bytes(b"y")
            found = discover_photos_for_stores(
                folder,
                "165309",
                ("md",),
                layout="store_subdir",
                prefix_in_filename=False,
            )
            self.assertEqual(len(found), 1)
            self.assertEqual(len(found[0].files), 2)
            self.assertEqual(found[0].files[0].name, "165309-1.jpg")

    def test_discover_store_subdir_legacy_prefixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sub = folder / "md"
            sub.mkdir()
            (sub / "md165309-1.jpg").write_bytes(b"x")
            found = discover_photos_for_stores(
                folder,
                "165309",
                ("md",),
                layout="store_subdir",
                prefix_in_filename=False,
            )
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].files[0].name, "md165309-1.jpg")

    def test_prefixed_photo_sets_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "md100-1.jpg").write_bytes(b"x")
            found = discover_photos_for_stores(
                folder,
                "100",
                ("md",),
                legacy_unprefixed_prefix="md",
                article_first=False,
            )
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].prefix, "md")
            self.assertEqual(found[0].files[0].name, "md100-1.jpg")


if __name__ == "__main__":
    unittest.main()
