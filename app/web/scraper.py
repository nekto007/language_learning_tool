"""
Module for scraping web pages and extracting text content.
"""
import logging
import time
from typing import List, Optional

import requests
from requests.exceptions import RequestException

from app.nlp.processor import process_html_content
from config.settings import MAX_RETRIES, REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)


class WebScraper:
    """Class for scraping web pages."""

    def __init__(self, user_agent: str = USER_AGENT, timeout: int = REQUEST_TIMEOUT):
        """
        Initializes the scraper.

        Args:
            user_agent (str, optional): User-Agent for HTTP requests.
            timeout (int, optional): Request timeout in seconds.
        """
        self.headers = {"User-Agent": user_agent}
        self.timeout = timeout

    def fetch_content(self, url: str, retries: int = MAX_RETRIES) -> Optional[str]:
        """
        Fetches web page content.

        Args:
            url (str): Web page URL.
            retries (int, optional): Number of retry attempts.

        Returns:
            Optional[str]: HTML content of the page or None in case of error.
        """
        for attempt in range(retries):
            try:
                logger.info(f"Fetching URL: {url} (attempt {attempt + 1}/{retries})")
                response = requests.get(
                    url, headers=self.headers, timeout=self.timeout
                )
                response.raise_for_status()  # Check for HTTP errors
                return response.text
            except RequestException as e:
                logger.warning(f"Attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    # Exponential delay between attempts
                    delay = 2 ** attempt
                    logger.info(f"Retrying in {delay} seconds")
                    time.sleep(delay)
                else:
                    logger.error(f"Failed to fetch {url} after {retries} attempts")

        return None

    def extract_words(self, url: str, selector: str = None) -> List[str]:
        """
        Extracts words from a web page.

        Args:
            url (str): Web page URL.
            selector (str, optional): CSS selector for text extraction.

        Returns:
            List[str]: List of processed words.
        """
        html_content = self.fetch_content(url)

        if not html_content:
            logger.error(f"Could not fetch content from {url}")
            return []

        return process_html_content(html_content, selector)

    def process_multiple_pages(self, base_url: str, num_pages: int) -> List[str]:
        """
        Processes multiple pages and collects words.

        Args:
            base_url (str): Base URL of the pages.
            num_pages (int): Number of pages.

        Returns:
            List[str]: Combined list of words from all pages.
        """
        all_words = []

        for page in range(1, num_pages + 1):
            page_url = f"{base_url}-{page}.html"
            logger.info(f"Processing page {page}/{num_pages}: {page_url}")

            words = self.extract_words(page_url)
            all_words.extend(words)

            logger.info(f"Extracted {len(words)} words from page {page}")

            # Small pause between requests
            time.sleep(1)

        return all_words
