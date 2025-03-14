"""
Module for automating pronunciation downloads from Forvo.
Opens links in Safari browser to download audio files.
"""
import logging
import os
import platform
import subprocess
import time
import webbrowser
from typing import List

logger = logging.getLogger(__name__)


class ForvoDownloader:
    """Class for downloading pronunciations from Forvo through a browser."""

    def __init__(
            self,
            browser_name: str = "safari",
            delay: float = 3.0,
            max_urls: int = 100,
    ):
        """
        Initializes the pronunciation downloader.

        Args:
            browser_name (str, optional): Browser name to use.
                Supported: 'safari', 'chrome', 'firefox'. Defaults to "safari".
            delay (float, optional): Delay between opening links (in seconds).
                Defaults to 3.0.
            max_urls (int, optional): Maximum number of URLs to open in one session.
                Defaults to 100.
        """
        self.browser_name = browser_name.lower()
        self.delay = delay
        self.max_urls = max_urls

        # Register browser
        self._register_browser()

    def _register_browser(self) -> None:
        """
        Registers the browser in the webbrowser module.

        Raises:
            ValueError: If an unsupported browser or system is specified.
        """
        try:
            system = platform.system()

            if system == "Darwin":  # macOS
                if self.browser_name == "safari":
                    safari_path = '/Applications/Safari.app/Contents/MacOS/Safari'
                    if os.path.exists(safari_path):
                        webbrowser.register('safari', None, webbrowser.BackgroundBrowser(safari_path), preferred=True)
                        logger.info("Safari registered successfully")
                    else:
                        raise ValueError(f"Safari not found at {safari_path}")

                elif self.browser_name == "chrome":
                    chrome_path = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
                    if os.path.exists(chrome_path):
                        webbrowser.register('chrome', None, webbrowser.BackgroundBrowser(chrome_path))
                        logger.info("Chrome registered successfully")
                    else:
                        raise ValueError(f"Chrome not found at {chrome_path}")

                elif self.browser_name == "firefox":
                    firefox_path = '/Applications/Firefox.app/Contents/MacOS/firefox'
                    if os.path.exists(firefox_path):
                        webbrowser.register('firefox', None, webbrowser.BackgroundBrowser(firefox_path))
                        logger.info("Firefox registered successfully")
                    else:
                        raise ValueError(f"Firefox not found at {firefox_path}")

                else:
                    raise ValueError(f"Unsupported browser: {self.browser_name}")

            elif system == "Windows":
                # For Windows, use standard handlers
                logger.info(f"Using default browser handler for {self.browser_name} on Windows")

            elif system == "Linux":
                # For Linux, use standard handlers
                logger.info(f"Using default browser handler for {self.browser_name} on Linux")

            else:
                raise ValueError(f"Unsupported system: {system}")

        except Exception as e:
            logger.error(f"Error registering browser: {e}")
            raise

    @staticmethod
    def _open_url_in_safari(url: str) -> None:
        """
        Opens URL in a new Safari tab using AppleScript.

        Args:
            url (str): URL to open.
        """
        applescript_command = f"""
        tell application "Safari"
            activate
            tell window 1
                set newTab to make new tab with properties {{URL: "{url}"}}
            end tell
        end tell
        """
        try:
            subprocess.run(["osascript", "-e", applescript_command], check=True)
            logger.debug(f"Opened URL in Safari: {url}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error opening URL in Safari: {e}")

    def _open_url_in_browser(self, url: str) -> None:
        """
        Opens URL in browser depending on operating system and settings.

        Args:
            url (str): URL to open.
        """
        system = platform.system()

        try:
            if system == "Darwin" and self.browser_name == "safari":
                # For Safari on macOS, use AppleScript for better control
                self._open_url_in_safari(url)
            else:
                # For other browsers and systems, use webbrowser
                if not webbrowser.open_new_tab(url):
                    logger.warning(f"Failed to open URL: {url}")
                    return
                logger.debug(f"Opened URL in browser: {url}")
        except Exception as e:
            logger.error(f"Error opening URL {url}: {e}")

    def download_from_urls(self, urls: List[str]) -> int:
        """
        Opens a list of URLs in the browser to download pronunciations.

        Args:
            urls (List[str]): List of URLs to open.

        Returns:
            int: Number of successfully opened URLs.
        """
        # Limit the number of URLs for safety
        urls = urls[:self.max_urls]

        opened_count = 0
        logger.info(f"Starting to open {len(urls)} URLs with {self.delay}s delay")

        try:
            for url in urls:
                if not url.strip():
                    continue

                self._open_url_in_browser(url)
                opened_count += 1

                # Pause between requests
                if opened_count < len(urls):
                    logger.debug(f"Waiting {self.delay}s before next URL...")
                    time.sleep(self.delay)

            logger.info(f"Successfully opened {opened_count} URLs")
        except KeyboardInterrupt:
            logger.info(f"Process interrupted. Opened {opened_count} URLs")
        except Exception as e:
            logger.error(f"Error in download process: {e}")

        return opened_count

    def download_from_file(self, file_path: str) -> int:
        """
        Opens URLs from a file in the browser to download pronunciations.

        Args:
            file_path (str): Path to file with URLs (one URL per line).

        Returns:
            int: Number of successfully opened URLs.
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return 0

        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                urls = [line.strip() for line in file if line.strip()]

            return self.download_from_urls(urls)

        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            return 0

    @staticmethod
    def generate_urls_for_words(words: List[str]) -> List[str]:
        """
        Generates Forvo URLs based on a list of words.

        Args:
            words (List[str]): List of words to generate URLs for.

        Returns:
            List[str]: List of Forvo URLs.
        """
        return [f"https://forvo.com/word/{word.strip()}/#en" for word in words if word.strip()]

    def download_from_words_file(self, file_path: str) -> int:
        """
        Downloads pronunciations for words from a file.

        Args:
            file_path (str): Path to file with words (one word per line).

        Returns:
            int: Number of successfully opened URLs.
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return 0

        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                words = [line.strip() for line in file if line.strip()]

            urls = self.generate_urls_for_words(words)
            return self.download_from_urls(urls)

        except Exception as e:
            logger.error(f"Error processing words file {file_path}: {e}")
            return 0

    @staticmethod
    def save_urls_to_file(urls: List[str], output_file: str) -> bool:
        """
        Saves a list of URLs to a file.

        Args:
            urls (List[str]): List of URLs to save.
            output_file (str): Path to output file.

        Returns:
            bool: True on success, otherwise False.
        """
        try:
            directory = os.path.dirname(output_file)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)

            with open(output_file, 'w', encoding='utf-8') as file:
                for url in urls:
                    file.write(f"{url}\n")

            logger.info(f"URLs saved to file: {output_file}")
            return True

        except Exception as e:
            logger.error(f"Error saving URLs to file {output_file}: {e}")
            return False
