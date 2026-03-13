"""
Settings module for application configuration.
"""
import os
import sys
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.pool import NullPool

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")
IS_TESTING = os.environ.get("TESTING", "").lower() == "true"

# Custom exception for configuration errors
class EnvironmentConfigurationError(Exception):
    """
    Raised when required environment variables are missing

    ARCHITECTURE: Using exceptions instead of sys.exit() allows:
    1. Proper error handling in Flask
    2. Unit testing
    3. Graceful error messages
    4. Flask error handlers to catch and display user-friendly messages
    """
    def __init__(self, missing_required, missing_recommended=None):
        self.missing_required = missing_required
        self.missing_recommended = missing_recommended or []

        message_parts = []
        if missing_required:
            message_parts.append(f"Missing required environment variables: {', '.join(missing_required)}")
        if missing_recommended:
            message_parts.append(f"Missing recommended environment variables: {', '.join(missing_recommended)}")

        super().__init__(" | ".join(message_parts))


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
    """
    Validate that all required environment variables are set

    ARCHITECTURE FIX: Raises exception instead of calling sys.exit()
    This allows Flask to handle the error gracefully and makes the code testable.

    Raises:
        EnvironmentConfigurationError: When required environment variables are missing

    Returns:
        tuple: (missing_required, missing_recommended) - both empty lists if all OK
    """
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

    # ARCHITECTURE FIX: Raise exception instead of sys.exit(1)
    if missing_required:
        error_msg = f"❌ CRITICAL ERROR: Missing required environment variables:\n"
        for var in missing_required:
            error_msg += f"   - {var}\n"
        error_msg += f"💡 Please set these variables before starting the application."
        print(error_msg, file=sys.stderr)
        raise EnvironmentConfigurationError(missing_required, missing_recommended)

    # Warning for missing recommended variables
    if missing_recommended:
        print(f"⚠️  WARNING: Missing recommended environment variables:")
        for var in missing_recommended:
            print(f"   - {var}")
        print(f"💡 Consider setting these for optimal functionality.")

    # Success message
    if not missing_required and not missing_recommended:
        print(f"✅ All environment variables are properly configured.")

    return (missing_required, missing_recommended)


# Validate environment on import
# Will raise EnvironmentConfigurationError if required vars are missing
try:
    validate_environment()
except EnvironmentConfigurationError as e:
    # Re-raise for Flask to handle, but allow imports to work in tests
    if not IS_TESTING:
        raise

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
TEST_DATABASE_URL = os.environ.get("DATABASE_URL")
if IS_TESTING and TEST_DATABASE_URL:
    SQLALCHEMY_DATABASE_URI = TEST_DATABASE_URL
else:
    SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

DEFAULT_SQLALCHEMY_ENGINE_OPTIONS = {
    # Pool size settings
    'pool_size': 10,              # Number of connections to maintain
    'max_overflow': 20,           # Maximum additional connections when pool is full
    'pool_timeout': 30,           # Seconds to wait before giving up on getting a connection
    'pool_recycle': 300,          # Recycle connections after 5 minutes (prevent stale connections)

    # Connection health checks
    'pool_pre_ping': True,        # Test connection before using it

    # Performance
    'echo': False,                # Set to True for SQL query debugging
    'echo_pool': False,           # Set to True for connection pool debugging

    # Additional PostgreSQL optimizations
    'connect_args': {
        'connect_timeout': 10,    # Connection timeout in seconds
        'options': '-c statement_timeout=0',  # No query timeout (needed for long book processing)
        'keepalives': 1,          # Enable TCP keepalive
        'keepalives_idle': 30,    # Seconds before sending keepalive
        'keepalives_interval': 10,  # Seconds between keepalive probes
        'keepalives_count': 5     # Number of failed probes before giving up
    }
}

if SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
    DEFAULT_SQLALCHEMY_ENGINE_OPTIONS = {
        'echo': False,
        'poolclass': NullPool,
        'connect_args': {
            'check_same_thread': False
        }
    }

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
    TESTING = IS_TESTING
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AUDIO_UPLOAD_FOLDER = MEDIA_FOLDER
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload

    # Internationalization
    BABEL_DEFAULT_LOCALE = "en"
    BABEL_DEFAULT_TIMEZONE = "UTC"

    # JWT — must be distinct from SECRET_KEY
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY") or os.urandom(32).hex()

    # Security
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    REMEMBER_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    
    # CSRF Protection
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour

    # Telegram bot
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "llt_englishbot")
    SITE_URL = os.environ.get("SITE_URL", "")

    # Database Connection Pooling
    SQLALCHEMY_ENGINE_OPTIONS = DEFAULT_SQLALCHEMY_ENGINE_OPTIONS



class TestConfig(Config):
    """Тестовая конфигурация - использует отдельную PostgreSQL базу"""
    TESTING = True
    
    # Используем отдельную тестовую базу данных PostgreSQL
    TEST_DB_NAME = f"{DB_NAME}_test"
    SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{TEST_DB_NAME}"
    
    SQLALCHEMY_TRACK_MODIFICATIONS = True
    WTF_CSRF_ENABLED = True
    WTF_CSRF_SECRET_KEY = 'csrf-test-key'
    SECRET_KEY = 'test-secret-key'
    JWT_SECRET_KEY = 'test-jwt-secret-key'
    SERVER_NAME = 'localhost.localdomain'
    
    # Отключаем validation в тестах для быстрой работы
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'echo': False  # Включить True для отладки SQL запросов
    }
