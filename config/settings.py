"""
Settings module for application configuration.

No side effects at import time: validation runs inside create_app().
"""
import logging
import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")
IS_TESTING = os.environ.get("TESTING", "").lower() == "true"


class EnvironmentConfigurationError(Exception):
    """Raised when required environment variables are missing."""
    def __init__(self, missing_required, missing_recommended=None):
        self.missing_required = missing_required
        self.missing_recommended = missing_recommended or []

        message_parts = []
        if missing_required:
            message_parts.append(f"Missing required environment variables: {', '.join(missing_required)}")
        if missing_recommended:
            message_parts.append(f"Missing recommended environment variables: {', '.join(missing_recommended)}")

        super().__init__(" | ".join(message_parts))


REQUIRED_ENV_VARS = [
    'POSTGRES_USER',
    'POSTGRES_PASSWORD',
    'POSTGRES_DB',
    'SECRET_KEY'
]

RECOMMENDED_ENV_VARS = [
    'FLASK_ENV',
    'FLASK_APP'
]


def validate_environment():
    """
    Validate required/recommended environment variables.

    Called by create_app() after config load, before extensions init.
    Not called at import time.

    Raises:
        EnvironmentConfigurationError: When required vars are missing (non-TESTING only).
    Returns:
        tuple: (missing_required, missing_recommended)
    """
    missing_required = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
    missing_recommended = [v for v in RECOMMENDED_ENV_VARS if not os.environ.get(v)]

    if missing_required:
        logger.error("Missing required environment variables: %s", ", ".join(missing_required))
        raise EnvironmentConfigurationError(missing_required, missing_recommended)

    if missing_recommended:
        logger.warning("Missing recommended environment variables: %s", ", ".join(missing_recommended))

    return (missing_required, missing_recommended)

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

# =============================================================================
# Timezone defaults
# =============================================================================

# Default application timezone — used as fallback when user has none set.
# Configurable via DEFAULT_TIMEZONE environment variable.
DEFAULT_TIMEZONE: str = os.getenv('DEFAULT_TIMEZONE', 'Europe/Moscow')

# =============================================================================
# Performance monitoring thresholds
# =============================================================================

# Queries exceeding this threshold (milliseconds) are logged as slow queries.
# Configurable via SLOW_QUERY_MS environment variable.
SLOW_QUERY_MS: int = int(os.getenv('SLOW_QUERY_MS', 100))

# =============================================================================
# Domain thresholds — named constants for values used across multiple modules.
# Import from here instead of hardcoding literals.
# =============================================================================

# Minimum score (0–100) a user must achieve to pass a lesson or module
PASSING_SCORE_PERCENT: int = 70


class Config:
    """
    Flask application configuration (production defaults).

    Security-sensitive settings:
    - SECRET_KEY: from env, required in production (validated by validate_environment)
    - JWT_SECRET_KEY: from env, random fallback in dev only; None in production forces explicit config
    - SESSION_COOKIE_SECURE / REMEMBER_COOKIE_SECURE: True except FLASK_ENV=development
    - DB URI: built from POSTGRES_* env vars (required)
    """
    TESTING = IS_TESTING
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AUDIO_UPLOAD_FOLDER = MEDIA_FOLDER
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    BABEL_DEFAULT_LOCALE = "en"
    BABEL_DEFAULT_TIMEZONE = "UTC"

    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY") or (
        os.urandom(32).hex() if os.environ.get("FLASK_ENV") != "production"
        else None
    )

    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV") != "development"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    REMEMBER_COOKIE_SECURE = os.environ.get("FLASK_ENV") != "development"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = timedelta(days=30)

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "llt_englishbot")
    SITE_URL = os.environ.get("SITE_URL", "")

    GOOGLE_SITE_VERIFICATION = os.environ.get("GOOGLE_SITE_VERIFICATION", "")
    GOOGLE_ANALYTICS_ID = os.environ.get("GOOGLE_ANALYTICS_ID", "")

    SQLALCHEMY_ENGINE_OPTIONS = DEFAULT_SQLALCHEMY_ENGINE_OPTIONS
    SLOW_QUERY_MS: int = SLOW_QUERY_MS
    DEFAULT_TIMEZONE: str = DEFAULT_TIMEZONE


class TestConfig(Config):
    """
    Test configuration - uses a separate PostgreSQL database.

    Hardcoded secrets are intentional: tests must not depend on env vars
    for SECRET_KEY/JWT_SECRET_KEY.
    """
    TESTING = True
    TEST_DB_NAME = f"{DB_NAME}_test"
    SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{TEST_DB_NAME}"

    SQLALCHEMY_TRACK_MODIFICATIONS = True
    WTF_CSRF_ENABLED = True
    WTF_CSRF_SECRET_KEY = 'csrf-test-key'
    SECRET_KEY = 'test-secret-key'
    JWT_SECRET_KEY = 'test-jwt-secret-key'
    SERVER_NAME = 'localhost.localdomain'

    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False

    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'echo': False,
    }
