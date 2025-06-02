"""
Settings module for application configuration.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Path to the project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Critical environment variables validation
REQUIRED_ENV_VARS = [
    'POSTGRES_USER',
    'POSTGRES_PASSWORD', 
    'POSTGRES_DB',
    'SECRET_KEY'
]

# Optional but recommended environment variables
RECOMMENDED_ENV_VARS = [
    'FLASK_ENV',
    'FLASK_APP'
]

def validate_environment():
    """Validate that all required environment variables are set."""
    missing_required = []
    missing_recommended = []
    
    # Check required variables
    for var in REQUIRED_ENV_VARS:
        if not os.environ.get(var):
            missing_required.append(var)
    
    # Check recommended variables
    for var in RECOMMENDED_ENV_VARS:
        if not os.environ.get(var):
            missing_recommended.append(var)
    
    # Critical error for missing required variables
    if missing_required:
        print(f"❌ CRITICAL ERROR: Missing required environment variables:")
        for var in missing_required:
            print(f"   - {var}")
        print(f"💡 Please set these variables before starting the application.")
        sys.exit(1)
    
    # Warning for missing recommended variables
    if missing_recommended:
        print(f"⚠️  WARNING: Missing recommended environment variables:")
        for var in missing_recommended:
            print(f"   - {var}")
        print(f"💡 Consider setting these for optimal functionality.")
    
    # Success message
    if not missing_required and not missing_recommended:
        print(f"✅ All environment variables are properly configured.")

# Validate environment on import
validate_environment()

# Database settings - now guaranteed to exist
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
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", 10))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", 3))
MAX_PAGES = int(os.environ.get("MAX_PAGES", 100))
# Максимальное время обработки книги (в секундах)
MAX_PROCESSING_TIME = 300  # 5 минут

# Максимальное количество одновременных задач обработки
MAX_CONCURRENT_PROCESSING = 2

# Интервал очистки старых записей о статусе (в секундах)
STATUS_CLEANUP_INTERVAL = 3600  # 1 час

# Максимальный возраст записи о статусе до удаления (в секундах)
MAX_STATUS_AGE = 86400  # 24 часа

# Максимальный размер книги для асинхронной обработки (в символах)
# Книги меньшего размера обрабатываются синхронно
MAX_SYNC_PROCESSING_SIZE = 50000  # ~50 KB

# Таймаут для блокирующих операций при синхронной обработке (в секундах)
SYNC_PROCESSING_TIMEOUT = 30

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



class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = True
    WTF_CSRF_ENABLED = True
    WTF_CSRF_SECRET_KEY = 'csrf-test-key'
    SECRET_KEY = 'test-secret-key'
    SERVER_NAME = 'localhost.localdomain'
