import unittest

from avito.browser import compute_scrape_pause


class TestScrapePause(unittest.TestCase):
    def test_pause_grows_with_page(self):
        p5, _ = compute_scrape_pause(
            5,
            base_sec=7,
            jitter_sec=0,
            step_sec=0.25,
            step_from_page=5,
        )
        p10, _ = compute_scrape_pause(
            10,
            base_sec=7,
            jitter_sec=0,
            step_sec=0.25,
            step_from_page=5,
        )
        self.assertEqual(p5, 7)
        self.assertGreater(p10, p5)

    def test_rest_every_n_pages(self):
        _, note9 = compute_scrape_pause(
            9,
            base_sec=5,
            jitter_sec=0,
            rest_every=8,
            rest_sec=30,
            rest_jitter_sec=0,
        )
        self.assertIn("отдых", note9)
        _, note10 = compute_scrape_pause(
            10,
            base_sec=5,
            jitter_sec=0,
            rest_every=8,
            rest_sec=30,
            rest_jitter_sec=0,
        )
        self.assertEqual(note10, "")


if __name__ == "__main__":
    unittest.main()
