import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base directory and path setup
BASE_DIR = Path(__file__).resolve().parent.parent
DB_FILE = 'instance/words.db'

# Media folder for audio files
MEDIA_FOLDER = os.environ.get("MEDIA_FOLDER", os.path.join("app", "static", "audio"))

# Database tables
COLLECTIONS_TABLE = "collection_words"
PHRASAL_VERB_TABLE = "phrasal_verb"

# Translation files
TRANSLATE_FILE = os.environ.get(
    "TRANSLATE_FILE",
    os.path.join(BASE_DIR, os.environ.get("TRANSLATE_FILE", "translate_gpt.txt"))
)
PHRASAL_VERB_FILE = os.environ.get(
    "PHRASAL_VERB_FILE",
    os.path.join(BASE_DIR, os.environ.get("PHRASAL_VERB_FILE", "phrasal_verb.txt"))
)

# Web scraping settings
USER_AGENT = os.environ.get(
    "USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36"
)
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", 10))  # seconds

# Limits and thresholds
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", 3))
MAX_PAGES = int(os.environ.get("MAX_PAGES", 1000))


class Config:
    # Security settings
    SECRET_KEY = os.environ.get('SECRET_KEY')

    # Database settings
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Cookie settings
    REMEMBER_COOKIE_DURATION = timedelta(days=int(os.environ.get('REMEMBER_COOKIE_DAYS', 30)))
    REMEMBER_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
    SESSION_COOKIE_HTTPONLY = True

    # File upload settings
    AUDIO_UPLOAD_FOLDER = os.path.join('app', 'static', 'audio')
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))  # Default 16MB