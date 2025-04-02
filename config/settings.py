"""
Settings module for application configuration.
"""
import os
from pathlib import Path

# Path to the project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Database settings
DB_USER = os.environ.get("POSTGRES_USER")
DB_PASSWORD = os.environ.get("POSTGRES_PASSWORD")
DB_NAME = os.environ.get("POSTGRES_DB")
DB_HOST = os.environ.get("POSTGRES_HOST", "db")
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")

# PostgreSQL connection config
DB_CONFIG = {
    "host": DB_HOST,
    "port": DB_PORT,
    "user": DB_USER,
    "password": DB_PASSWORD,
    "dbname": DB_NAME
}

# SQLAlchemy database URI for Flask
SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Media folder for audio files
MEDIA_FOLDER = os.path.join(BASE_DIR, "app", "static", "audio")

# File paths
TRANSLATE_FILE = os.path.join(BASE_DIR, "data", "translate.txt")
PHRASAL_VERB_FILE = os.path.join(BASE_DIR, "data", "phrasal_verbs.txt")

# Table names
COLLECTIONS_TABLE = "collection_words"
PHRASAL_VERB_TABLE = "phrasal_verb"

# Web scraper settings
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
REQUEST_TIMEOUT = os.environ.get("REQUEST_TIMEOUT", 10)
MAX_RETRIES = os.environ.get("MAX_RETRIES", 3)
MAX_PAGES = os.environ.get("MAX_PAGES", 100)


# Flask Config class
class Config:
    """Flask application configuration."""
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AUDIO_UPLOAD_FOLDER = MEDIA_FOLDER
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload

    # Internationalization
    BABEL_DEFAULT_LOCALE = "en"
    BABEL_DEFAULT_TIMEZONE = "UTC"

    # Security
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"
    REMEMBER_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"