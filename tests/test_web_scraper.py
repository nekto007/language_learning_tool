"""
Tests for app/web/scraper.py

Tests WebScraper class: fetch_content (with retries, timeouts, errors),
extract_words, and process_multiple_pages.
All HTTP requests and time.sleep are mocked.
"""
import time
from unittest.mock import MagicMock, patch, call

import pytest
import requests
from requests.exceptions import ConnectionError, HTTPError, Timeout, RequestException

from app.web.scraper import WebScraper


@pytest.fixture
def scraper():
    with patch("app.web.scraper.USER_AGENT", "TestAgent/1.0"),          patch("app.web.scraper.REQUEST_TIMEOUT", 5),          patch("app.web.scraper.MAX_RETRIES", 3):
        return WebScraper(user_agent="TestAgent/1.0", timeout=5)


class TestWebScraperInit:

    def test_default_init(self):
        s = WebScraper(user_agent="Agent/1", timeout=10)
        assert s.headers == {"User-Agent": "Agent/1"}
        assert s.timeout == 10

    def test_custom_init(self):
        s = WebScraper(user_agent="Custom/2.0", timeout=30)
        assert s.headers == {"User-Agent": "Custom/2.0"}
        assert s.timeout == 30


class TestFetchContent:

    @patch("app.web.scraper.time.sleep")
    @patch("app.web.scraper.requests.get")
    def test_successful_fetch(self, mock_get, mock_sleep, scraper):
        mock_response = MagicMock()
        mock_response.text = "<html><body>Hello</body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        result = scraper.fetch_content("https://example.com", retries=3)
        assert result == "<html><body>Hello</body></html>"
        mock_get.assert_called_once_with(
            "https://example.com",
            headers={"User-Agent": "TestAgent/1.0"},
            timeout=5,
        )
        mock_sleep.assert_not_called()

    @patch("app.web.scraper.time.sleep")
    @patch("app.web.scraper.requests.get")
    def test_retry_on_connection_error(self, mock_get, mock_sleep, scraper):
        mock_response = MagicMock()
        mock_response.text = "success"
        mock_response.raise_for_status = MagicMock()
        mock_get.side_effect = [
            ConnectionError("Connection refused"),
            mock_response,
        ]
        result = scraper.fetch_content("https://example.com", retries=3)
        assert result == "success"
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once_with(1)

    @patch("app.web.scraper.time.sleep")
    @patch("app.web.scraper.requests.get")
    def test_all_retries_exhausted(self, mock_get, mock_sleep, scraper):
        mock_get.side_effect = Timeout("Timed out")
        result = scraper.fetch_content("https://example.com", retries=3)
        assert result is None
        assert mock_get.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("app.web.scraper.time.sleep")
    @patch("app.web.scraper.requests.get")
    def test_exponential_backoff(self, mock_get, mock_sleep, scraper):
        mock_get.side_effect = RequestException("Error")
        scraper.fetch_content("https://example.com", retries=4)
        expected_sleeps = [call(1), call(2), call(4)]
        assert mock_sleep.call_args_list == expected_sleeps

    @patch("app.web.scraper.time.sleep")
    @patch("app.web.scraper.requests.get")
    def test_http_error_triggers_retry(self, mock_get, mock_sleep, scraper):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = HTTPError("500 Server Error")
        mock_get.return_value = mock_response
        result = scraper.fetch_content("https://example.com", retries=2)
        assert result is None
        assert mock_get.call_count == 2

    @patch("app.web.scraper.time.sleep")
    @patch("app.web.scraper.requests.get")
    def test_single_retry(self, mock_get, mock_sleep, scraper):
        mock_get.side_effect = ConnectionError("fail")
        result = scraper.fetch_content("https://example.com", retries=1)
        assert result is None
        assert mock_get.call_count == 1
        mock_sleep.assert_not_called()

    @patch("app.web.scraper.time.sleep")
    @patch("app.web.scraper.requests.get")
    def test_fetch_returns_html_text(self, mock_get, mock_sleep, scraper):
        mock_response = MagicMock()
        mock_response.text = "<html>Content with unicode</html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        result = scraper.fetch_content("https://example.com/page")
        assert "unicode" in result


class TestExtractWords:

    @patch("app.web.scraper.process_html_content")
    @patch.object(WebScraper, "fetch_content")
    def test_extract_words_success(self, mock_fetch, mock_process, scraper):
        mock_fetch.return_value = "<html><body>Hello world</body></html>"
        mock_process.return_value = ["hello", "world"]
        words = scraper.extract_words("https://example.com")
        assert words == ["hello", "world"]
        mock_fetch.assert_called_once_with("https://example.com")
        mock_process.assert_called_once_with(
            "<html><body>Hello world</body></html>", None
        )

    @patch("app.web.scraper.process_html_content")
    @patch.object(WebScraper, "fetch_content")
    def test_extract_words_with_selector(self, mock_fetch, mock_process, scraper):
        mock_fetch.return_value = '<html><div class="content">Text</div></html>'
        mock_process.return_value = ["text"]
        words = scraper.extract_words("https://example.com", selector=".content")
        mock_process.assert_called_once_with(
            '<html><div class="content">Text</div></html>', '.content'
        )
        assert words == ["text"]

    @patch.object(WebScraper, "fetch_content")
    def test_extract_words_fetch_failure(self, mock_fetch, scraper):
        mock_fetch.return_value = None
        words = scraper.extract_words("https://example.com")
        assert words == []

    @patch("app.web.scraper.process_html_content")
    @patch.object(WebScraper, "fetch_content")
    def test_extract_words_empty_result(self, mock_fetch, mock_process, scraper):
        mock_fetch.return_value = "<html></html>"
        mock_process.return_value = []
        words = scraper.extract_words("https://example.com")
        assert words == []


class TestProcessMultiplePages:

    @patch("app.web.scraper.time.sleep")
    @patch.object(WebScraper, "extract_words")
    def test_process_multiple_pages_basic(self, mock_extract, mock_sleep, scraper):
        mock_extract.side_effect = [
            ["hello", "world"],
            ["foo", "bar"],
            ["baz"],
        ]
        words = scraper.process_multiple_pages("https://example.com/page", 3)
        assert words == ["hello", "world", "foo", "bar", "baz"]
        assert mock_extract.call_count == 3
        mock_extract.assert_any_call("https://example.com/page-1.html")
        mock_extract.assert_any_call("https://example.com/page-2.html")
        mock_extract.assert_any_call("https://example.com/page-3.html")

    @patch("app.web.scraper.time.sleep")
    @patch.object(WebScraper, "extract_words")
    def test_process_multiple_pages_url_format(self, mock_extract, mock_sleep, scraper):
        mock_extract.return_value = []
        scraper.process_multiple_pages("https://site.com/words", 2)
        mock_extract.assert_any_call("https://site.com/words-1.html")
        mock_extract.assert_any_call("https://site.com/words-2.html")

    @patch("app.web.scraper.time.sleep")
    @patch.object(WebScraper, "extract_words")
    def test_process_multiple_pages_pauses_between_requests(self, mock_extract, mock_sleep, scraper):
        mock_extract.return_value = []
        scraper.process_multiple_pages("https://example.com/page", 3)
        assert mock_sleep.call_count == 3
        mock_sleep.assert_called_with(1)

    @patch("app.web.scraper.time.sleep")
    @patch.object(WebScraper, "extract_words")
    def test_process_zero_pages(self, mock_extract, mock_sleep, scraper):
        words = scraper.process_multiple_pages("https://example.com/page", 0)
        assert words == []
        mock_extract.assert_not_called()

    @patch("app.web.scraper.time.sleep")
    @patch.object(WebScraper, "extract_words")
    def test_process_single_page(self, mock_extract, mock_sleep, scraper):
        mock_extract.return_value = ["word1", "word2"]
        words = scraper.process_multiple_pages("https://example.com/page", 1)
        assert words == ["word1", "word2"]
        mock_extract.assert_called_once_with("https://example.com/page-1.html")

    @patch("app.web.scraper.time.sleep")
    @patch.object(WebScraper, "extract_words")
    def test_process_handles_empty_pages(self, mock_extract, mock_sleep, scraper):
        mock_extract.side_effect = [
            ["word1"],
            [],
            ["word2"],
        ]
        words = scraper.process_multiple_pages("https://example.com/page", 3)
        assert words == ["word1", "word2"]

    @patch("app.web.scraper.time.sleep")
    @patch.object(WebScraper, "extract_words")
    def test_process_preserves_duplicates(self, mock_extract, mock_sleep, scraper):
        mock_extract.side_effect = [
            ["hello", "world"],
            ["hello", "test"],
        ]
        words = scraper.process_multiple_pages("https://example.com/page", 2)
        assert words == ["hello", "world", "hello", "test"]
