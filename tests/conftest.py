"""
Pytest configuration and fixtures for language learning tool tests
"""
import pytest
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from pathlib import Path
from app import create_app
from app.utils.db import db
from app.auth.models import User
from app.curriculum.models import (
    CEFRLevel, Module, Lessons, LessonProgress
)


@pytest.fixture(scope='session')
def app():
    """Create application for testing"""
    # CRITICAL SECURITY FIX: Load .env.test BEFORE importing config
    # This prevents tests from accidentally using production database
    import os
    from dotenv import load_dotenv

    # Load test environment variables from .env.test
    test_env_path = Path(__file__).parent.parent / '.env.test'
    if test_env_path.exists():
        load_dotenv(test_env_path, override=True)
        print(f"✅ Loaded test environment from {test_env_path}")
    else:
        print(f"⚠️  Warning: .env.test not found at {test_env_path}")

    # Store original env vars to restore later
    original_db_url = os.environ.get('DATABASE_URL')

    # Set test environment variables (will be picked up by Config)
    os.environ['TESTING'] = 'True'
    os.environ['DATABASE_URL'] = os.environ.get('DATABASE_URL', 'postgresql://igor_adm:Shnir!9844891@127.0.0.1:5432/learn_db_test')
    os.environ['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')

    # Create test configuration class
    from config.settings import Config

    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = os.environ['DATABASE_URL']
        WTF_CSRF_ENABLED = False
        SERVER_NAME = 'localhost'
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        RATELIMIT_ENABLED = False  # Disable rate limiting in tests

    # Создаем приложение с тестовой конфигурацией
    test_app = create_app(config_class=TestConfig)

    # VERIFY we're using test database, not production!
    db_uri = test_app.config.get('SQLALCHEMY_DATABASE_URI', '')

    # CRITICAL CHECK: Database name MUST contain '_test' suffix
    if '_test' not in db_uri:
        raise RuntimeError(
            f"CRITICAL: Test database must have '_test' suffix!\n"
            f"Database URI: {db_uri}\n"
            f"Expected: learn_db_test\n"
            f"This protection prevented potential data loss!"
        )

    with test_app.app_context():
        # Создаем все таблицы
        db.create_all()
        yield test_app
        # Очистка после всех тестов - ONLY safe for in-memory DB!
        db.session.remove()
        db.drop_all()

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
    """Create database session for tests"""
    with app.app_context():
        # Clean up before test - delete all data to prevent duplicates
        db.session.rollback()

        # Delete data from tables in correct order (respecting foreign keys)
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

        # Clean up after test
        db.session.rollback()
        db.session.remove()


@pytest.fixture(scope='function')
def test_user(db_session):
    """Create test user"""
    username = f'testuser_{uuid.uuid4().hex[:8]}'
    user = User(
        username=username,
        email=f'{username}@example.com',
        active=True
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def admin_user(db_session):
    """Create admin user"""
    username = f'admin_{uuid.uuid4().hex[:8]}'
    user = User(
        username=username,
        email=f'{username}@example.com',
        is_admin=True
    )
    user.set_password('adminpass123')
    user.active = True  # Set active field, not is_active property
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope='function')
def test_level(db_session):
    """Create test CEFR level"""
    level = CEFRLevel(
        code='A1',
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
def authenticated_client(app, client, test_user):
    """Create authenticated test client with proper Flask-Login support

    Uses actual Flask-Login login mechanism to ensure session persistence
    across all request types (GET, POST, etc.)
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
    from datetime import datetime, timedelta, timezone

    directions_list = []

    for i, user_word in enumerate(user_words):
        # Create eng-rus direction
        eng_rus = UserCardDirection(
            user_word_id=user_word.id,
            direction='eng-rus'
        )
        # Vary the review dates
        if i % 3 == 0:  # Due for review
            eng_rus.next_review = datetime.now(timezone.utc) - timedelta(days=1)
        elif i % 3 == 1:  # Review soon
            eng_rus.next_review = datetime.now(timezone.utc) + timedelta(hours=6)
        else:  # Not due yet
            eng_rus.next_review = datetime.now(timezone.utc) + timedelta(days=3)

        db_session.add(eng_rus)
        directions_list.append(eng_rus)

        # Create rus-eng direction
        rus_eng = UserCardDirection(
            user_word_id=user_word.id,
            direction='rus-eng'
        )
        rus_eng.next_review = datetime.now(timezone.utc) - timedelta(hours=1)
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
    second_user = User(
        username='testuser2',
        email='test2@example.com',
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

@pytest.fixture(autouse=True)
def enable_study_module_for_user(app, request):
    """
    Automatically enable the 'study' module for test users.
    This allows tests to access @module_required('study') routes.

    Only runs for test functions that use authenticated_client or test_user.
    """
    # Check if this test uses authenticated_client or test_user fixtures
    if 'authenticated_client' not in request.fixturenames and 'test_user' not in request.fixturenames:
        return

    with app.app_context():
        from app.modules.models import SystemModule, UserModule

        # Get or create the study module
        study_module = SystemModule.query.filter_by(code='study').first()
        if not study_module:
            # Module should be seeded, but create if missing
            study_module = SystemModule(
                code='study',
                name='Повторение',
                description='Система интервального повторения слов',
                icon='brain',
                is_active=True,
                is_default=True,
                order=3
            )
            db.session.add(study_module)
            db.session.commit()

        # Enable module for test_user if they exist
        # We need to defer this until test_user is created
        # This will be called by the grant_module fixture below
        yield study_module


@pytest.fixture(autouse=True)
def grant_study_module(app, test_user, enable_study_module_for_user, request):
    """
    Grant study module access to test_user after they're created.
    """
    # Only run if test uses authenticated_client or test_user
    if 'authenticated_client' not in request.fixturenames and 'test_user' not in request.fixturenames:
        return

    with app.app_context():
        from app.modules.models import UserModule

        # Check if user already has the module
        existing = UserModule.query.filter_by(
            user_id=test_user.id,
            module_id=enable_study_module_for_user.id
        ).first()

        if not existing:
            user_module = UserModule(
                user_id=test_user.id,
                module_id=enable_study_module_for_user.id,
                is_enabled=True,
                granted_by_admin=True
            )
            db.session.add(user_module)
            db.session.commit()


@pytest.fixture(autouse=True)
def clear_flask_cache(app):
    """
    Clear Flask cache before each test to prevent cache pollution.
    Important for leaderboard and achievements caching tests.
    """
    with app.app_context():
        try:
            from app.utils.cache import cache
            if hasattr(cache, 'clear'):
                cache.clear()
        except (KeyError, RuntimeError):
            # Cache not properly initialized, skip clearing
            pass