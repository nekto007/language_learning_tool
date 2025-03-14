"""
Module for managing pronunciation audio files.
"""
import logging
import os
from typing import Dict, List, Set

from config.settings import MEDIA_FOLDER

logger = logging.getLogger(__name__)


class AudioManager:
    """Class for managing audio files."""

    def __init__(self, media_folder: str = MEDIA_FOLDER):
        """
        Initializes the audio file manager.

        Args:
            media_folder (str, optional): Path to the media files folder.
        """
        self.media_folder = media_folder

    def get_file_path(self, word: str) -> str:
        """
        Gets the full path to an audio file.

        Args:
            word (str): Word or phrase.

        Returns:
            str: Full path to the audio file.
        """
        word_modified = word.replace(" ", "_").lower()
        return os.path.join(self.media_folder, f"pronunciation_en_{word_modified}.mp3")

    @staticmethod
    def get_download_path(word: str) -> str:
        """
        Gets the path for downloading an audio file.

        Args:
            word (str): Word or phrase.

        Returns:
            str: URL for downloading the audio file.
        """
        return f"https://forvo.com/word/{word}/#en"

    def file_exists(self, word: str) -> bool:
        """
        Checks if an audio file exists in the media folder.

        Args:
            word (str): Word or phrase.

        Returns:
            bool: True if the file exists, otherwise False.
        """
        file_path = self.get_file_path(word)
        return os.path.isfile(file_path)

    def get_existing_audio_files(self) -> Set[str]:
        """
        Gets a set of words for which audio files already exist.

        Returns:
            Set[str]: Set of words.
        """
        existing_files = set()

        try:
            for filename in os.listdir(self.media_folder):
                if filename.startswith("pronunciation_en_") and filename.endswith(".mp3"):
                    # Extract the word from the filename
                    word = filename[len("pronunciation_en_"):-4]
                    # Replace '_' with spaces (if necessary)
                    word = word.replace("_", " ")
                    existing_files.add(word)
        except FileNotFoundError:
            logger.error(f"Media folder not found: {self.media_folder}")
        except PermissionError:
            logger.error(f"Permission denied for media folder: {self.media_folder}")

        return existing_files

    def get_missing_audio_files(self, words: List[str]) -> List[str]:
        """
        Gets a list of words for which audio files are missing.

        Args:
            words (List[str]): List of words to check.

        Returns:
            List[str]: List of words without audio files.
        """
        existing_files = self.get_existing_audio_files()
        return [word for word in words if word.lower() not in existing_files]

    def generate_download_links(self, words: List[str]) -> Dict[str, str]:
        """
        Generates a dictionary of links for downloading audio files.

        Args:
            words (List[str]): List of words to generate links for.

        Returns:
            Dict[str, str]: Dictionary {word: URL}.
        """
        return {word: self.get_download_path(word) for word in words}

    @staticmethod
    def update_anki_field_format(word: str) -> str:
        """
        Formats a field for Anki.

        Args:
            word (str): Word or phrase.

        Returns:
            str: Formatted field for Anki.
        """
        word_modified = word.replace(" ", "_").lower()
        return f"[sound:pronunciation_en_{word_modified}.mp3]"
