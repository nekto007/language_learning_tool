"""
Helper functions for the project.
"""
import logging
import os
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None) -> None:
    """
    Sets up logging.

    Args:
        log_level (str, optional): Logging level. Defaults to "INFO".
        log_file (Optional[str], optional): Path to log file. Defaults to None.
    """
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {log_level}")

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    handlers = []

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    handlers.append(console_handler)

    # File handler (if file specified)
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(logging.Formatter(log_format, date_format))
            handlers.append(file_handler)
        except (IOError, PermissionError) as e:
            print(f"Warning: Could not set up log file: {e}")

    # Configure root logger
    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        datefmt=date_format,
        handlers=handlers,
    )


def ensure_directory_exists(directory_path: str) -> bool:
    """
    Checks if a directory exists and creates it if necessary.

    Args:
        directory_path (str): Path to the directory.

    Returns:
        bool: True if the directory exists or was created, otherwise False.
    """
    if not os.path.exists(directory_path):
        try:
            os.makedirs(directory_path)
            logger.info(f"Created directory: {directory_path}")
            return True
        except (IOError, PermissionError) as e:
            logger.error(f"Failed to create directory {directory_path}: {e}")
            return False
    return True


def count_word_frequency(words: List[str]) -> Dict[str, int]:
    """
    Counts the frequency of words in a list.

    Args:
        words (List[str]): List of words.

    Returns:
        Dict[str, int]: Dictionary {word: frequency}.
    """
    return dict(Counter(words))


def create_backup(file_path: str) -> Optional[str]:
    """
    Creates a backup of a file.

    Args:
        file_path (str): Path to the file.

    Returns:
        Optional[str]: Path to the backup or None in case of error.
    """
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return None

    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{file_path}.{timestamp}.bak"

        with open(file_path, "rb") as src_file, open(backup_path, "wb") as dst_file:
            dst_file.write(src_file.read())

        logger.info(f"Created backup: {backup_path}")
        return backup_path
    except (IOError, PermissionError) as e:
        logger.error(f"Failed to create backup for {file_path}: {e}")
        return None


def load_text_file(file_path: str, encoding: str = "utf-8") -> Optional[List[str]]:
    """
    Loads a text file and returns its lines.

    Args:
        file_path (str): Path to the file.
        encoding (str, optional): File encoding. Defaults to "utf-8".

    Returns:
        Optional[List[str]]: List of lines or None in case of error.
    """
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return None

    try:
        with open(file_path, "r", encoding=encoding) as file:
            return [line.strip() for line in file]
    except Exception as e:
        logger.error(f"Failed to load file {file_path}: {e}")
        return None


def save_text_file(content: List[str], file_path: str, encoding: str = "utf-8") -> bool:
    """
    Saves a list of strings to a text file.

    Args:
        content (List[str]): List of strings to save.
        file_path (str): Path to the file.
        encoding (str, optional): File encoding. Defaults to "utf-8".

    Returns:
        bool: True on success, otherwise False.
    """
    try:
        # Create directory if necessary
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

        with open(file_path, "w", encoding=encoding) as file:
            for line in content:
                file.write(f"{line}\n")

        logger.info(f"Saved file: {file_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save file {file_path}: {e}")
        return False


def parse_csv_line(line: str, delimiter: str = ";") -> List[str]:
    """
    Parses a CSV line.

    Args:
        line (str): CSV line.
        delimiter (str, optional): Delimiter. Defaults to ";".

    Returns:
        List[str]: List of values.
    """
    return [value.strip() for value in line.split(delimiter)]
