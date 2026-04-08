"""
Pytest configuration and fixtures for language learning tool tests
"""
# ==================== PERFORMANCE: Fast password hashing ====================
# Monkey-patch BEFORE any app imports to use 1-iteration PBKDF2 (~3000x faster)
import werkzeug.security
_original_generate_password_hash = werkzeug.security.generate_password_hash


def _fast_generate_password_hash(password: str, method: str = 'pbkdf2:sha256:1',
                                  salt_length: int = 16) -> str:
    return _original_generate_password_hash(password, method='pbkdf2:sha256:1',
                                             salt_length=salt_length)


werkzeug.security.generate_password_hash = _fast_generate_password_hash
# ============================================================================

import pytest
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from pathlib import Path
from dotenv import load_dotenv

# Load test environment variables before importing the application
test_env_path = Path(__file__).parent.parent / '.env.test'
if test_env_path.exists():
    load_dotenv(test_env_path, override=True)

# Ensure required environment variables are populated for config validation
DEFAULT_ENV_VARS = {
    'POSTGRES_USER': 'test_user',
    'POSTGRES_PASSWORD': 'test_password',
    'POSTGRES_DB': 'test_db',
    'SECRET_KEY': 'test-secret-key',
    'FLASK_ENV': 'testing',
    'FLASK_APP': 'app',
    'DATABASE_URL': os.environ.get('DATABASE_URL', 'sqlite:///test.db')
}
for key, value in DEFAULT_ENV_VARS.items():
    os.environ.setdefault(key, value)

# Flag testing mode early so config can relax requirements
os.environ.setdefault('TESTING', 'true')
os.environ.setdefault('SQLALCHEMY_DATABASE_URI', os.environ['DATABASE_URL'])

from app import create_app
from app.utils.db import db
from app.auth.models import User
from app.curriculum.models import (
    CEFRLevel, Module, Lessons, LessonProgress
)


def _ensure_worker_db(base_db_url: str, db_name: str) -> None:
    """Create a per-worker test database if it doesn't exist."""
    from sqlalchemy import create_engine, text
    # Connect to 'postgres' database to create new databases
    admin_url = base_db_url.rsplit('/', 1)[0] + '/postgres'
    engine = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    with engine.connect() as conn:
        result = conn.execute(text(
            f"SELECT 1 FROM pg_database WHERE datname = :name"
        ), {'name': db_name})
        if not result.fetchone():
            # Use identifier quoting for safety
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    engine.dispose()


@pytest.fixture(scope='session')
def app(worker_id):
    """Create application for testing.

    Supports pytest-xdist: each worker gets its own database for safe parallelism.
    worker_id is 'master' when running without xdist, 'gw0', 'gw1', etc. with xdist.
    """
    import os
    from dotenv import load_dotenv

    # Load test environment variables from .env.test
    test_env_path = Path(__file__).parent.parent / '.env.test'
    if test_env_path.exists():
        load_dotenv(test_env_path, override=True)

    # Store original env vars to restore later
    original_db_url = os.environ.get('DATABASE_URL')

    # Set test environment variables (will be picked up by Config)
    os.environ['TESTING'] = 'True'
    base_db_url = os.environ.get('DATABASE_URL')
    if not base_db_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Set it in .env.test or export it before running tests."
        )

    # Per-worker database for pytest-xdist parallel execution
    if worker_id != 'master':
        url_base = base_db_url.rsplit('/', 1)[0]
        db_name = f'learn_db_test_{worker_id}'
        _ensure_worker_db(base_db_url, db_name)
        base_db_url = f'{url_base}/{db_name}'

    os.environ['DATABASE_URL'] = base_db_url
    os.environ['SQLALCHEMY_DATABASE_URI'] = base_db_url

    # Create test configuration class
    from config.settings import Config

    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = base_db_url
        WTF_CSRF_ENABLED = False
        SERVER_NAME = 'localhost'
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        RATELIMIT_ENABLED = False  # Disable rate limiting in tests

    test_app = create_app(config_class=TestConfig)

    # VERIFY we're using test database, not production!
    db_uri = test_app.config.get('SQLALCHEMY_DATABASE_URI', '')

    def _is_safe_test_db(uri: str) -> bool:
        if uri.startswith('sqlite:'):
            return True
        return '_test' in uri

    if not _is_safe_test_db(db_uri):
        raise RuntimeError(
            "CRITICAL: Test database must be isolated from production!\n"
            f"Database URI: {db_uri}\n"
            "Expected URI to use SQLite or include '_test' suffix.\n"
            "This protection prevented potential data loss!"
        )

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()

    # Restore original environment
    if original_db_url:
        os.environ['DATABASE_URL'] = original_db_url
    else:
        os.environ.pop('DATABASE_URL', None)


@pytest.fixture(scope='function')
def client(app):
    """Create test client"""
    return app.test_client()


@pytest.fixture(scope='function')
def db_session(app):
    """Create database session for tests with cleanup.

    Uses DELETE in FK-safe order for cleanup.
    Each worker has its own database when running with pytest-xdist.
    """
    with app.app_context():
        db.session.rollback()

        from app.curriculum.models import LessonProgress, Lessons, Module, CEFRLevel
        from app.auth.models import User

        try:
            LessonProgress.query.delete()
            Lessons.query.delete()
            Module.query.delete()
            CEFRLevel.query.delete()
            User.query.delete()
            db.session.commit()
        except Exception:
            db.session.rollback()

        yield db.session

        db.session.rollback()
        db.session.remove()


@pytest.fixture(scope='function')
def test_user(db_session):
    """Create test user"""
    username = f'testuser_{uuid.uuid4().hex[:8]}'
    user = User(
        username=username,
        email=f'{username}@example.com',
        active=True,
        onboarding_completed=True
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def admin_user(app, db_session, client):
    """Create admin user and login using Flask-Login"""
    from flask_login import login_user

    username = f'admin_{uuid.uuid4().hex[:8]}'
    password = 'adminpass123'
    user = User(
        username=username,
        email=f'{username}@example.com',
        is_admin=True
    )
    user.set_password(password)
    user.active = True  # Set active field, not is_active property
    db_session.add(user)
    db_session.commit()

    # Login the admin user using Flask-Login directly
    with app.test_request_context():
        login_user(user)
        # Set the user ID in the session for the test client
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

    yield user

    # Cleanup
    try:
        db_session.delete(user)
        db_session.commit()
    except:
        db_session.rollback()


@pytest.fixture(scope='function')
def test_level(db_session):
    """Create test CEFR level with unique code.

    Uses uuid prefix for code to avoid collisions.
    db_session TRUNCATE ensures clean table at start.
    """
    code = uuid.uuid4().hex[:2].upper()

    level = CEFRLevel(
        code=code,
        name='Beginner',
        description='Beginner level',
        order=1
    )
    db_session.add(level)
    db_session.commit()
    return level


@pytest.fixture(scope='function')
def test_module(db_session, test_level):
    """Create test module"""
    module = Module(
        level_id=test_level.id,
        number=1,
        title='Test Module',
        description='Test module description',
        raw_content={'module': {'id': 1, 'title': 'Test', 'lessons': []}},
        min_score_required=70,
        allow_skip_test=False,
        input_mode='mixed'
    )
    db_session.add(module)
    db_session.commit()
    return module


@pytest.fixture(scope='function')
def test_lesson_vocabulary(db_session, test_module):
    """Create vocabulary lesson"""
    lesson = Lessons(
        module_id=test_module.id,
        number=1,
        title='Test Vocabulary',
        type='vocabulary',
        order=0,
        content={'vocabulary': [{'word': 'test', 'translation': 'тест'}]}
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


@pytest.fixture(scope='function')
def test_lesson_quiz(db_session, test_module):
    """Create quiz lesson"""
    lesson = Lessons(
        module_id=test_module.id,
        number=2,
        title='Test Quiz',
        type='quiz',
        order=1,
        content={'questions': [{'type': 'multiple_choice', 'question': 'Test?'}]}
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


@pytest.fixture(scope='function')
def test_lesson_progress(db_session, test_user, test_lesson_vocabulary):
    """Create lesson progress"""
    progress = LessonProgress(
        user_id=test_user.id,
        lesson_id=test_lesson_vocabulary.id,
        status='in_progress',
        score=0.0
    )
    db_session.add(progress)
    db_session.commit()
    return progress


@pytest.fixture(scope='function')
def authenticated_client(app, client, test_user, grant_study_module):
    """Create authenticated test client with proper Flask-Login support.

    Uses actual Flask-Login login mechanism to ensure session persistence
    across all request types (GET, POST, etc.).

    Depends on grant_study_module to ensure study module access is granted
    before any requests are made. This fixes 403 Forbidden errors in view tests
    with @module_required('study') decorator.
    """
    from flask_login import login_user

    # Perform actual login to set up session correctly
    with app.test_request_context():
        login_user(test_user)
        # Get the session data that was set by login_user
        with client.session_transaction() as session:
            session['_user_id'] = str(test_user.id)
            session['_fresh'] = True
            session['user_id'] = test_user.id

    # Attach test_user to client for easy access in tests
    client.application.test_user = test_user
    return client


@pytest.fixture(scope='function')
def auth_headers(test_user):
    """Create authentication headers for API requests

    Returns empty dict since the routes use @login_required (session-based auth)
    not JWT tokens. Tests should use authenticated_client with these headers.
    """
    # For session-based authentication, no special headers needed
    # The session is already set by authenticated_client
    return {}


@pytest.fixture(scope='function')
def admin_client(app, client, admin_user):
    """Create admin test client with proper Flask-Login support"""
    from flask_login import login_user

    # Use app context to login user
    with app.test_request_context():
        login_user(admin_user)
        # Store user_id in session for persistence
        with client.session_transaction() as session:
            session['user_id'] = admin_user.id
            session['_fresh'] = True

    # Attach admin_user to client for easy access in tests
    client.application.admin_user = admin_user
    return client


@pytest.fixture(scope='session')
def sample_module_json():
    """Sample module JSON structure"""
    return {
        "module": {
            "id": 1,
            "title": "Тестовый модуль",
            "title_en": "Test Module",
            "level": "A1",
            "input_mode": "mixed",
            "description": "Test description",
            "lessons": [
                {
                    "id": 1,
                    "type": "vocabulary",
                    "title": "Vocabulary Lesson",
                    "order": 0,
                    "content": {
                        "vocabulary": [
                            {
                                "word": "hello",
                                "translation": "привет",
                                "pronunciation": "həˈloʊ",
                                "example": "Hello, how are you?",
                                "example_translation": "Привет, как дела?"
                            }
                        ]
                    }
                },
                {
                    "id": 2,
                    "type": "quiz",
                    "title": "Quiz Lesson",
                    "order": 1,
                    "questions": [
                        {
                            "type": "multiple_choice",
                            "question": "What is 'hello' in Russian?",
                            "options": ["привет", "пока", "здравствуй", "добрый"],
                            "correct": 0
                        }
                    ]
                }
            ]
        }
    }


@pytest.fixture(scope='session')
def json_module_files():
    """Get list of all module JSON files"""
    module_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'module_completed'
    )
    if not os.path.exists(module_dir):
        return []

    return [
        os.path.join(module_dir, f)
        for f in os.listdir(module_dir)
        if f.endswith('.json') and f.startswith('module_')
    ]


@pytest.fixture(scope='function')
def test_book(db_session):
    """Create test book"""
    from app.books.models import Book
    book = Book(
        title='Test Book',
        author='Test Author',
        level='A1',
        chapters_cnt=1
    )
    db_session.add(book)
    db_session.commit()
    return book


@pytest.fixture(scope='function')
def test_chapter(db_session, test_book):
    """Create test chapter"""
    from app.books.models import Chapter
    chapter = Chapter(
        book_id=test_book.id,
        chap_num=1,
        title='Test Chapter',
        words=100,
        text_raw='Test paragraph 1. Test paragraph 2.'
    )
    db_session.add(chapter)
    db_session.commit()
    return chapter


@pytest.fixture(scope='function')
def test_word(db_session):
    """Create test word"""
    from app.words.models import CollectionWords
    import uuid

    # Create unique word to avoid conflicts
    unique_suffix = str(uuid.uuid4())[:8]
    word = CollectionWords(
        english_word=f'test_{unique_suffix}',
        russian_word='тест',
        level='A1'
    )
    db_session.add(word)
    db_session.commit()
    return word


# ==================== STUDY MODULE FIXTURES ====================

@pytest.fixture(scope='function')
def test_words_list(db_session):
    """Create a list of test words for study"""
    from app.words.models import CollectionWords
    import uuid

    words = []
    word_pairs = [
        ('hello', 'привет', 'Hello, how are you?', 'Привет, как дела?'),
        ('book', 'книга', 'I read a book.', 'Я читаю книгу.'),
        ('water', 'вода', 'I drink water.', 'Я пью воду.'),
        ('cat', 'кот', 'I have a cat.', 'У меня есть кот.'),
        ('dog', 'собака', 'I have a dog.', 'У меня есть собака.'),
        ('house', 'дом', 'This is my house.', 'Это мой дом.'),
        ('car', 'машина', 'I have a car.', 'У меня есть машина.'),
        ('friend', 'друг', 'He is my friend.', 'Он мой друг.'),
        ('food', 'еда', 'I like food.', 'Мне нравится еда.'),
        ('city', 'город', 'I live in a city.', 'Я живу в городе.'),
    ]

    unique_suffix = str(uuid.uuid4())[:8]
    for eng, rus, example_en, example_ru in word_pairs:
        word = CollectionWords(
            english_word=f'{eng}_{unique_suffix}',
            russian_word=rus,
            level='A1',
            sentences=f'{example_en}|{example_ru}'
        )
        db_session.add(word)
        words.append(word)

    db_session.commit()
    return words


@pytest.fixture(scope='function')
def study_settings(db_session, test_user):
    """Create study settings for test user"""
    from app.study.models import StudySettings

    settings = StudySettings(
        user_id=test_user.id,
        new_words_per_day=5,
        reviews_per_day=20,
        include_translations=True,
        include_examples=True,
        include_audio=True,
        show_hint_time=10
    )
    db_session.add(settings)
    db_session.commit()
    return settings


@pytest.fixture(scope='function')
def user_words(db_session, test_user, test_words_list):
    """Create user words with various statuses"""
    from app.study.models import UserWord

    user_words_list = []
    statuses = ['new', 'new', 'learning', 'learning', 'review', 'review', 'mastered', 'mastered', 'new', 'learning']

    for word, status in zip(test_words_list, statuses):
        user_word = UserWord(user_id=test_user.id, word_id=word.id)
        user_word.status = status
        db_session.add(user_word)
        user_words_list.append(user_word)

    db_session.commit()
    return user_words_list


@pytest.fixture(scope='function')
def user_card_directions(db_session, user_words):
    """Create card directions for user words"""
    from app.study.models import UserCardDirection
    from app.srs.constants import CardState
    from datetime import datetime, timedelta, timezone

    directions_list = []

    for i, user_word in enumerate(user_words):
        # Create eng-rus direction
        eng_rus = UserCardDirection(
            user_word_id=user_word.id,
            direction='eng-rus'
        )
        # Vary the review dates and states
        if i % 3 == 0:  # Due for review (already studied)
            eng_rus.next_review = datetime.now(timezone.utc) - timedelta(days=1)
            eng_rus.state = CardState.REVIEW.value
            eng_rus.repetitions = 3
            eng_rus.interval = 7
        elif i % 3 == 1:  # Review soon (already studied)
            eng_rus.next_review = datetime.now(timezone.utc) + timedelta(hours=6)
            eng_rus.state = CardState.REVIEW.value
            eng_rus.repetitions = 2
            eng_rus.interval = 3
        else:  # New card
            eng_rus.next_review = datetime.now(timezone.utc) + timedelta(days=3)
            eng_rus.state = CardState.NEW.value
            eng_rus.repetitions = 0

        db_session.add(eng_rus)
        directions_list.append(eng_rus)

        # Create rus-eng direction (due for review)
        rus_eng = UserCardDirection(
            user_word_id=user_word.id,
            direction='rus-eng'
        )
        rus_eng.next_review = datetime.now(timezone.utc) - timedelta(hours=1)
        rus_eng.state = CardState.REVIEW.value
        rus_eng.repetitions = 1
        rus_eng.interval = 1
        db_session.add(rus_eng)
        directions_list.append(rus_eng)

    db_session.commit()
    return directions_list


@pytest.fixture(scope='function')
def study_session(db_session, test_user):
    """Create a study session"""
    from app.study.models import StudySession

    session = StudySession(
        user_id=test_user.id,
        session_type='cards',
        words_studied=5,
        correct_answers=4,
        incorrect_answers=1
    )
    db_session.add(session)
    db_session.commit()
    return session


@pytest.fixture(scope='function')
def quiz_deck(db_session, test_user):
    """Create a quiz deck"""
    from app.study.models import QuizDeck

    deck = QuizDeck(
        title='Test Quiz Deck',
        description='A test quiz deck',
        user_id=test_user.id,
        is_public=False
    )
    db_session.add(deck)
    db_session.commit()
    return deck


@pytest.fixture(scope='function')
def public_quiz_deck(db_session, test_user):
    """Create a public quiz deck with share code"""
    from app.study.models import QuizDeck

    deck = QuizDeck(
        title='Public Quiz Deck',
        description='A public quiz deck',
        user_id=test_user.id,
        is_public=True
    )
    deck.generate_share_code()
    db_session.add(deck)
    db_session.commit()
    return deck


@pytest.fixture(scope='function')
def quiz_deck_with_words(db_session, test_user, test_words_list):
    """Create a quiz deck with words"""
    from app.study.models import QuizDeck, QuizDeckWord

    deck = QuizDeck(
        title='Deck with Words',
        description='A deck with test words',
        user_id=test_user.id,
        is_public=False
    )
    db_session.add(deck)
    db_session.flush()

    for i, word in enumerate(test_words_list[:5]):  # Add first 5 words
        deck_word = QuizDeckWord(
            deck_id=deck.id,
            word_id=word.id,
            order_index=i
        )
        db_session.add(deck_word)

    db_session.commit()
    return deck


@pytest.fixture(scope='function')
def quiz_deck_custom_words(db_session, test_user):
    """Create a quiz deck with custom words (no word_id)"""
    from app.study.models import QuizDeck, QuizDeckWord

    deck = QuizDeck(
        title='Custom Words Deck',
        description='Deck with custom words',
        user_id=test_user.id,
        is_public=False
    )
    db_session.add(deck)
    db_session.flush()

    # Add custom words without word_id
    custom_words = [
        ('custom1', 'кастом1', 'Example sentence 1|Пример 1'),
        ('custom2', 'кастом2', 'Example sentence 2|Пример 2'),
    ]

    for i, (eng, rus, sentences) in enumerate(custom_words):
        deck_word = QuizDeckWord(
            deck_id=deck.id,
            word_id=None,  # Custom word
            custom_english=eng,
            custom_russian=rus,
            custom_sentences=sentences,
            order_index=i
        )
        db_session.add(deck_word)

    db_session.commit()
    return deck


@pytest.fixture(scope='function')
def second_user(db_session):
    """Create a second test user"""
    username = f'testuser2_{uuid.uuid4().hex[:8]}'
    second_user = User(
        username=username,
        email=f'{username}@example.com',
        active=True
    )
    second_user.set_password('testpass123')
    db_session.add(second_user)
    db_session.commit()
    return second_user


@pytest.fixture(scope='function')
def user_xp(db_session, test_user):
    """Create user XP record"""
    from app.study.models import UserXP

    xp = UserXP(
        user_id=test_user.id,
        total_xp=250  # Level 2
    )
    db_session.add(xp)
    db_session.commit()
    return xp


@pytest.fixture(scope='function')
def achievements(db_session):
    """Create test achievements"""
    from app.study.models import Achievement

    # Define test achievements data
    achievements_data = [
        {
            'code': 'first_quiz',
            'name': 'Первый квиз',
            'description': 'Пройдите свой первый квиз',
            'icon': '🎯',
            'xp_reward': 10,
            'category': 'quiz'
        },
        {
            'code': 'perfect_score',
            'name': 'Идеальный результат',
            'description': 'Получите 100% в квизе',
            'icon': '💯',
            'xp_reward': 25,
            'category': 'quiz'
        },
        {
            'code': 'first_study',
            'name': 'Первая учеба',
            'description': 'Завершите первую сессию',
            'icon': '📚',
            'xp_reward': 5,
            'category': 'study'
        },
    ]

    achievements_list = []
    for data in achievements_data:
        # Get or create achievement to avoid duplicates
        achievement = Achievement.query.filter_by(code=data['code']).first()
        if not achievement:
            achievement = Achievement(**data)
            db_session.add(achievement)
        achievements_list.append(achievement)

    db_session.commit()
    return achievements_list


@pytest.fixture(scope='function')
def game_score(db_session, test_user):
    """Create a game score"""
    from app.study.models import GameScore

    score = GameScore(
        user_id=test_user.id,
        game_type='matching',
        difficulty='medium',
        score=850,
        time_taken=45,
        pairs_matched=8,
        total_pairs=8,
        moves=16
    )
    db_session.add(score)
    db_session.commit()
    return score


@pytest.fixture(scope='function')
def collection_and_topic(db_session):
    """Create a collection and topic for testing"""
    from app.words.models import Collection, Topic
    import uuid

    unique_id = uuid.uuid4().hex[:8]

    topic = Topic(
        name=f'Test Topic {unique_id}',
        description='A test topic'
    )
    db_session.add(topic)
    db_session.flush()

    collection = Collection(
        name=f'Test Collection {unique_id}',
        description='A test collection'
    )
    db_session.add(collection)
    db_session.commit()

    return {'collection': collection, 'topic': topic}


# ==================== AUTO-FIXTURES FOR TEST ENVIRONMENT ====================

@pytest.fixture
def _skip_autouse_module_fixtures():
    """Marker fixture to skip autouse module fixtures in tests that manage modules manually"""
    pass


@pytest.fixture(autouse=True)
def enable_study_module_for_user(request):
    """
    Automatically enable the 'study' module for test users.
    Uses lazy dependency resolution to avoid creating db_session/test_user
    for tests that don't need them (pure unit tests, etc.).
    """
    # Skip if test doesn't use authenticated_client or test_user
    if '_skip_autouse_module_fixtures' in request.fixturenames:
        yield None
        return
    if 'authenticated_client' not in request.fixturenames and 'test_user' not in request.fixturenames:
        yield None
        return

    # Lazily resolve db_session only when needed
    db_session = request.getfixturevalue('db_session')

    from app.modules.models import SystemModule

    study_module = SystemModule.query.filter_by(code='study').first()
    if not study_module:
        study_module = SystemModule(
            code='study',
            name='Повторение',
            description='Система интервального повторения слов',
            icon='brain',
            is_active=True,
            is_default=True,
            order=3
        )
        db_session.add(study_module)
        db_session.commit()

    yield study_module


@pytest.fixture(autouse=True)
def grant_study_module(request):
    """
    Grant study module access to test_user after they're created.
    Uses lazy dependency resolution to avoid triggering expensive fixtures
    (db_session, test_user) for tests that don't need them.
    """
    if '_skip_autouse_module_fixtures' in request.fixturenames:
        return
    if 'authenticated_client' not in request.fixturenames and 'test_user' not in request.fixturenames:
        return

    # Lazily resolve dependencies only when this test actually needs them
    enable_study_module_for_user = request.getfixturevalue('enable_study_module_for_user')
    if enable_study_module_for_user is None:
        return

    db_session = request.getfixturevalue('db_session')
    test_user = request.getfixturevalue('test_user')

    from app.modules.models import UserModule, SystemModule

    study_module = SystemModule.query.filter_by(code='study').first()
    if not study_module:
        return

    existing = UserModule.query.filter_by(
        user_id=test_user.id,
        module_id=study_module.id
    ).first()

    if not existing:
        user_module = UserModule(
            user_id=test_user.id,
            module_id=study_module.id,
            is_enabled=True,
            granted_by_admin=True
        )
        db_session.add(user_module)
        db_session.commit()


@pytest.fixture(autouse=True)
def clear_flask_cache(request):
    """
    Clear Flask cache and reset DB session before each test to prevent
    cache pollution and PendingRollbackError from leaking between tests.
    Only runs for tests that use the app fixture.
    """
    if 'app' not in request.fixturenames and 'client' not in request.fixturenames \
            and 'authenticated_client' not in request.fixturenames:
        return

    app = request.getfixturevalue('app')

    # Roll back any pending transaction left by a previous test.
    # Tests that don't use the db_session fixture (which does its own
    # rollback) would otherwise hit PendingRollbackError when their
    # client.get() triggers DB queries in middleware/before_request hooks.
    # We do this outside with app.app_context() to affect the session-scoped
    # app context that is already active.
    try:
        db.session.rollback()
    except Exception:
        pass

    with app.app_context():
        try:
            from app.curriculum.cache import cache
            if hasattr(cache, 'clear'):
                cache.clear()
        except (KeyError, RuntimeError):
            pass
