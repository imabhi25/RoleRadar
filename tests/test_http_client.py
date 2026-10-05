"""
Unit tests for hardened HTTP client using mocks and deterministic fixtures.
"""

import unittest
from unittest.mock import MagicMock, patch
import requests

from ingestion.http_client import (
    DEFAULT_USER_AGENT,
    HardenedHttpClient,
    IngestionFetchError,
    sanitize_url_for_logging,
)


class TestHardenedHttpClient(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock(spec=requests.Session)
        self.mock_session.headers = {}
        self.client = HardenedHttpClient(session=self.mock_session)

    def test_user_agent_header_set(self):
        self.assertEqual(
            self.mock_session.headers.get("User-Agent"), DEFAULT_USER_AGENT
        )

    def test_successful_get_and_json(self):
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"jobs": [{"id": 1, "title": "SWE"}]}
        self.mock_session.get.return_value = mock_response

        data = self.client.get_json("https://api.test.com/jobs")
        self.assertEqual(data, {"jobs": [{"id": 1, "title": "SWE"}]})
        self.mock_session.get.assert_called_once()

    def test_unrecoverable_http_error_raises_fetch_error(self):
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        self.mock_session.get.return_value = mock_response

        with self.assertRaises(IngestionFetchError) as ctx:
            self.client.get("https://api.test.com/missing")
        self.assertIn("404", str(ctx.exception))

    def test_invalid_json_raises_fetch_error(self):
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON string")
        self.mock_session.get.return_value = mock_response

        with self.assertRaises(IngestionFetchError) as ctx:
            self.client.get_json("https://api.test.com/bad_json")
        self.assertIn("Invalid JSON", str(ctx.exception))

    def test_network_exception_raises_fetch_error(self):
        self.mock_session.get.side_effect = requests.exceptions.Timeout("Connection timed out")

        with self.assertRaises(IngestionFetchError) as ctx:
            self.client.get("https://api.test.com/timeout")
        self.assertIn("Network error", str(ctx.exception))

    def test_url_sanitization_for_logging(self):
        secret_url = "https://boards-api.greenhouse.io/v1/jobs?token=secret123&api_key=mykey&page=1"
        sanitized = sanitize_url_for_logging(secret_url)
        self.assertNotIn("secret123", sanitized)
        self.assertNotIn("mykey", sanitized)
        self.assertIn("[REDACTED]", sanitized)
        self.assertIn("page=1", sanitized)

    def test_default_session_retry_configuration(self):
        with HardenedHttpClient() as client:
            for url in ["https://api.test.com", "http://api.test.com"]:
                adapter = client.session.get_adapter(url)
                self.assertIsNotNone(adapter.max_retries)
                retry = adapter.max_retries
                self.assertEqual(retry.total, 3)
                self.assertEqual(retry.backoff_factor, 1.0)
                self.assertIn(429, retry.status_forcelist)
                self.assertIn(500, retry.status_forcelist)
                self.assertIn(502, retry.status_forcelist)
                self.assertIn(503, retry.status_forcelist)
                self.assertIn(504, retry.status_forcelist)
                self.assertTrue(retry.respect_retry_after_header)
                allowed = getattr(retry, "allowed_methods", None) or getattr(retry, "method_whitelist", None)
                self.assertIsNotNone(allowed)
                self.assertIn("GET", allowed)

    def test_transient_500_error_raises_fetch_error_after_retries(self):
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        self.mock_session.get.return_value = mock_response

        with self.assertRaises(IngestionFetchError) as ctx:
            self.client.get("https://api.test.com/server-error")
        self.assertIn("500", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
