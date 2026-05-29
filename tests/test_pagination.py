import unittest

from avito.pagination import page_url, should_continue_pagination


class TestPagination(unittest.TestCase):
    def test_page_url_first(self):
        base = "https://www.avito.ru/ufa/shiny?f=abc&localPriority=1"
        self.assertEqual(page_url(base, 1), base)
        self.assertNotIn("p=", page_url(base, 1))

    def test_page_url_second(self):
        base = "https://www.avito.ru/ufa/shiny?f=abc"
        self.assertIn("p=2", page_url(base, 2))
        self.assertNotIn("p=1", page_url(base, 2))

    def test_page_url_replaces_p(self):
        base = "https://www.avito.ru/ufa/shiny?p=3&f=abc"
        u = page_url(base, 2)
        self.assertIn("p=2", u)
        self.assertNotIn("p=3", u)

    def test_should_continue_full_page_without_button(self):
        self.assertTrue(
            should_continue_pagination(
                batch_size=50,
                new_unique=50,
                page_num=1,
                ui_has_next=False,
            )
        )

    def test_should_stop_empty(self):
        self.assertFalse(
            should_continue_pagination(
                batch_size=0,
                new_unique=0,
                page_num=2,
                ui_has_next=True,
            )
        )

    def test_should_stop_no_new_ids(self):
        self.assertFalse(
            should_continue_pagination(
                batch_size=50,
                new_unique=0,
                page_num=2,
                ui_has_next=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
