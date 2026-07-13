import unittest
from unittest.mock import MagicMock, patch

from avito.avito_api import (
    AvitoApiClient,
    AvitoApiConfig,
    DEFAULT_AUTOLOAD_SCHEDULE,
    fetch_token,
    load_avito_api_config,
    update_autoload_profile,
    update_stocks,
)


class TestAvitoApi(unittest.TestCase):
    def test_load_config_from_secrets(self):
        cfg = load_avito_api_config(
            {"avito": {"client_id": "id", "client_secret": "secret"}}
        )
        self.assertEqual(cfg.client_id, "id")
        self.assertEqual(cfg.client_secret, "secret")

    def test_load_config_missing(self):
        with self.assertRaises(ValueError):
            load_avito_api_config({})

    @patch("avito.avito_api.requests.post")
    def test_fetch_token(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"access_token": "tok123", "expires_in": 3600, "token_type": "Bearer"},
        )
        tok = fetch_token(AvitoApiConfig(client_id="a", client_secret="b"))
        self.assertEqual(tok.access_token, "tok123")
        self.assertTrue(tok.valid)

    @patch("avito.avito_api.fetch_token")
    @patch("avito.avito_api.requests.request")
    def test_client_request(self, mock_req, mock_token):
        mock_token.return_value = __import__(
            "avito.avito_api", fromlist=["AvitoToken"]
        ).AvitoToken(access_token="t", expires_at=1e12)
        mock_req.return_value = MagicMock(status_code=200, content=b'{"ok":true}', json=lambda: {"ok": True})
        client = AvitoApiClient(AvitoApiConfig(client_id="a", client_secret="b"))
        self.assertEqual(client.request("GET", "/autoload/v2/profile"), {"ok": True})

    @patch("avito.avito_api.fetch_token")
    @patch("avito.avito_api.requests.request")
    def test_update_profile_includes_schedule(self, mock_req, mock_token):
        mock_token.return_value = __import__(
            "avito.avito_api", fromlist=["AvitoToken"]
        ).AvitoToken(access_token="t", expires_at=1e12)
        mock_req.return_value = MagicMock(status_code=200, content=b"{}", json=lambda: {})
        client = AvitoApiClient(AvitoApiConfig(client_id="a", client_secret="b"))
        update_autoload_profile(
            client,
            feed_name="main",
            feed_url="https://example.com/feed.xlsx",
            report_email="test@example.com",
        )
        body = mock_req.call_args.kwargs["json"]
        self.assertEqual(body["report_email"], "test@example.com")
        self.assertEqual(body["schedule"], DEFAULT_AUTOLOAD_SCHEDULE)
        self.assertEqual(body["feeds_data"][0]["feed_url"], "https://example.com/feed.xlsx")

    def test_update_profile_requires_email(self):
        client = AvitoApiClient(AvitoApiConfig(client_id="a", client_secret="b"))
        with self.assertRaises(ValueError):
            update_autoload_profile(
                client,
                feed_name="main",
                feed_url="https://example.com/feed.xlsx",
                report_email="",
            )

    @patch("avito.avito_api.fetch_token")
    @patch("avito.avito_api.requests.request")
    def test_update_stocks(self, mock_req, mock_token):
        mock_token.return_value = __import__(
            "avito.avito_api", fromlist=["AvitoToken"]
        ).AvitoToken(access_token="t", expires_at=1e12)
        mock_req.return_value = MagicMock(
            status_code=200,
            content=b'{"stocks":[{"success":true}]}',
            json=lambda: {"stocks": [{"success": True}]},
        )
        client = AvitoApiClient(AvitoApiConfig(client_id="a", client_secret="b"))
        result = update_stocks(
            client,
            [{"item_id": 1, "quantity": 5, "external_id": "md_1"}],
        )
        self.assertEqual(result, [{"success": True}])
        self.assertEqual(mock_req.call_args.kwargs["json"]["stocks"][0]["quantity"], 5)


if __name__ == "__main__":
    unittest.main()
