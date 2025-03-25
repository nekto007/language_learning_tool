"""
Application configuration file.
Contains main settings and parameters.
"""
import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
DB_FILE = os.environ.get("DB_FILE", os.path.join(BASE_DIR, "words.db"))

# Media files folder
MEDIA_FOLDER = os.environ.get(
    "MEDIA_FOLDER",
    os.path.expanduser("static/media/")
)

# Database tables
COLLECTIONS_TABLE = "collection_words"
PHRASAL_VERB_TABLE = "phrasal_verb"

# Translation files
TRANSLATE_FILE = os.environ.get("TRANSLATE_FILE", os.path.join(BASE_DIR, "translate_gpt.txt"))
PHRASAL_VERB_FILE = os.environ.get("PHRASAL_VERB_FILE", os.path.join(BASE_DIR, "phrasal_verb.txt"))

# Web scraping settings
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/39.0.2171.95 Safari/537.36")
REQUEST_TIMEOUT = 10  # seconds

# Limits and thresholds
MAX_RETRIES = 3
MAX_PAGES = 1000
