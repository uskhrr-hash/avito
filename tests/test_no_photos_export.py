import tempfile
import unittest
from pathlib import Path

import pandas as pd

from avito.no_photos_export import export_no_photos_excel


class TestNoPhotosExport(unittest.TestCase):
    def test_writes_excel(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            out = export_no_photos_excel(
                folder,
                "no_photos.xlsx",
                [{"артикул": "1", "номенклатура": "Tire", "проблема": "нет"}],
            )
            self.assertTrue(out.is_file())
            df = pd.read_excel(out, sheet_name="без фото")
            self.assertEqual(len(df), 1)
            self.assertEqual(str(df.iloc[0]["артикул"]), "1")


if __name__ == "__main__":
    unittest.main()
