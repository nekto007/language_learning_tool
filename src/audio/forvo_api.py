"""
Module for working with the Forvo API.
Allows direct downloading of pronunciation audio files.
"""
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

import requests

from config.settings import MEDIA_FOLDER

logger = logging.getLogger(__name__)


class ForvoAPIClient:
    """Client for working with the Forvo API."""

    # Forvo API base URL
    BASE_URL = "https://apifree.forvo.com"

    def __init__(
            self,
            api_key: str,
            language: str = "en",
            format: str = "mp3",
            max_requests_per_minute: int = 60,  # Common limit for free plans
            media_folder: str = MEDIA_FOLDER,
    ):
        """
        Initializes the Forvo API client.

        Args:
            api_key (str): Forvo API key.
            language (str, optional): Language code for pronunciations. Defaults to "en".
            format (str, optional): Audio file format (mp3 or ogg). Defaults to "mp3".
            max_requests_per_minute (int, optional): Maximum number of requests per minute.
                Defaults to 60.
            media_folder (str, optional): Folder for saving audio files.
                Defaults to settings.
        """
        self.api_key = api_key
        self.language = language
        self.format = format
        self.max_requests_per_minute = max_requests_per_minute
        self.media_folder = media_folder

        # For tracking request limits
        self.request_timestamps = []

    def _check_rate_limit(self) -> None:
        """
        Checks request limits and waits if necessary.
        Prevents exceeding the API request limit.
        """
        now = time.time()
        # Remove old requests (older than one minute)
        self.request_timestamps = [ts for ts in self.request_timestamps if now - ts < 60]

        if len(self.request_timestamps) >= self.max_requests_per_minute:
            # Need to wait until a new slot becomes available
            oldest_ts = min(self.request_timestamps)
            wait_time = 60 - (now - oldest_ts)
            if wait_time > 0:
                logger.info(f"Rate limit reached, waiting {wait_time:.2f} seconds")
                time.sleep(wait_time)
                # Update timestamp after sleep
                now = time.time()

        # Add current time to request history
        self.request_timestamps.append(now)

    def get_pronunciation_data(self, word: str) -> List[Dict]:
        """
        Gets data about pronunciations of a word.

        Args:
            word (str): Word to search pronunciations for.

        Returns:
            List[Dict]: List of dictionaries with pronunciation information.

        Raises:
            Exception: If an error occurs during the API request.
        """
        self._check_rate_limit()

        # Prepare request parameters
        encoded_word = urllib.parse.quote(word)
        url = f"{self.BASE_URL}/key/{self.api_key}/format/json/action/word-pronunciations/word/{encoded_word}/language/{self.language}"

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()

            if "items" in data:
                return data["items"]
            else:
                logger.warning(f"No pronunciations found for word: {word}")
                return []

        except Exception as e:
            logger.error(f"Error getting pronunciation data for word '{word}': {e}")
            return []

    def download_pronunciation(self, word: str, save_path: Optional[str] = None) -> Optional[str]:
        """
        Downloads pronunciation for a word.

        Args:
            word (str): Word to download pronunciation for.
            save_path (Optional[str], optional): Path to save the file.
                If not specified, uses standard name in media_folder.

        Returns:
            Optional[str]: Path to the downloaded file or None in case of error.
        """
        # Get pronunciation data
        pronunciations = self.get_pronunciation_data(word)

        if not pronunciations:
            logger.warning(f"No pronunciations available for word: {word}")
            return None

        # Take the first pronunciation (with highest rating)
        pronunciation = pronunciations[0]

        # If path not specified, create standard filename
        if not save_path:
            word_modified = word.replace(" ", "_").lower()
            save_path = os.path.join(self.media_folder, f"pronunciation_en_{word_modified}.mp3")

        # Create directory if necessary
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        # Download audio file
        try:
            self._check_rate_limit()

            # Get download URL
            download_url = pronunciation["pathmp3" if self.format == "mp3" else "pathogg"]

            # Download file
            urllib.request.urlretrieve(download_url, save_path)

            logger.info(f"Successfully downloaded pronunciation for '{word}' to {save_path}")
            return save_path

        except Exception as e:
            logger.error(f"Error downloading pronunciation for word '{word}': {e}")
            return None

    def download_pronunciations_batch(self, words: List[str]) -> Dict[str, str]:
        """
        Downloads pronunciations for a list of words.

        Args:
            words (List[str]): List of words to download pronunciations for.

        Returns:
            Dict[str, str]: Dictionary {word: file_path} for successful downloads.
        """
        results = {}
        total = len(words)

        logger.info(f"Starting batch download for {total} words")

        for i, word in enumerate(words, 1):
            logger.info(f"Processing word {i}/{total}: {word}")

            # Skip empty words
            if not word.strip():
                continue

            # Download pronunciation
            file_path = self.download_pronunciation(word)

            if file_path:
                results[word] = file_path

        logger.info(f"Batch download completed. Successfully downloaded {len(results)}/{total} pronunciations")
        return results

    def get_file_path(self, word: str) -> str:
        """
        Gets the standard path to a pronunciation file.

        Args:
            word (str): Word.

        Returns:
            str: Path to pronunciation file.
        """
        word_modified = word.replace(" ", "_").lower()
        return os.path.join(self.media_folder, f"pronunciation_en_{word_modified}.mp3")

    def check_file_exists(self, word: str) -> bool:
        """
        Checks if a pronunciation file exists for a word.

        Args:
            word (str): Word.

        Returns:
            bool: True if the file exists, otherwise False.
        """
        file_path = self.get_file_path(word)
        return os.path.exists(file_path)

    def filter_missing_pronunciations(self, words: List[str]) -> List[str]:
        """
        Filters a list of words, keeping only those for which pronunciation files don't exist.

        Args:
            words (List[str]): List of words to check.

        Returns:
            List[str]: List of words without pronunciation files.
        """
        return [word for word in words if not self.check_file_exists(word)]


if __name__ == "__main__":
    import sys
    import argparse

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Download pronunciations using Forvo API")

    parser.add_argument("--api-key", required=True, help="Forvo API key")
    parser.add_argument("--word", help="Single word to download")
    parser.add_argument("--file", help="File with words (one per line)")
    parser.add_argument("--language", default="en", help="Language code (default: en)")
    parser.add_argument("--format", choices=["mp3", "ogg"], default="mp3", help="Audio format")
    parser.add_argument("--output-dir", help="Output directory for audio files")

    args = parser.parse_args()

    # Create API client
    client = ForvoAPIClient(
        api_key=args.api_key,
        language=args.language,
        format=args.format,
        media_folder=args.output_dir or MEDIA_FOLDER,
    )

    if args.word:
        # Download single word
        file_path = client.download_pronunciation(args.word)
        if file_path:
            print(f"Successfully downloaded pronunciation for '{args.word}' to {file_path}")
        else:
            print(f"Failed to download pronunciation for '{args.word}'")
            sys.exit(1)

    elif args.file:
        # Download words from file
        if not os.path.exists(args.file):
            print(f"File not found: {args.file}")
            sys.exit(1)

        with open(args.file, "r", encoding="utf-8") as file:
            words = [line.strip() for line in file if line.strip()]

        if not words:
            print("No words found in the file")
            sys.exit(1)

        results = client.download_pronunciations_batch(words)

        print(f"Downloaded {len(results)}/{len(words)} pronunciations")

        # Output failed words
        failed_words = set(words) - set(results.keys())
        if failed_words:
            print("Failed to download pronunciations for the following words:")
            for word in failed_words:
                print(f"  - {word}")

    else:
        parser.print_help()
        sys.exit(1)
