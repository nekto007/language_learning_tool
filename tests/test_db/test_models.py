import pytest
import os
import sqlite3
import tempfile
import sys
from datetime import datetime
from unittest.mock import patch, MagicMock

# Ensure we can import from the project
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import the models to be tested
from src.db.models import Book, Word, PhrasalVerb, DBInitializer


class TestBook:
    def test_book_initialization(self):
        # Test basic initialization
        book = Book(title="Test Book")
        assert book.id is None
        assert book.title == "Test Book"
        assert book.total_words == 0
        assert book.unique_words == 0
        assert book.scrape_date is None

        # Test initialization with all parameters
        scrape_date = datetime.now()
        book = Book(
            title="Complete Book",
            book_id=1,
            total_words=500,
            unique_words=200,
            scrape_date=scrape_date
        )
        assert book.id == 1
        assert book.title == "Complete Book"
        assert book.total_words == 500
        assert book.unique_words == 200
        assert book.scrape_date == scrape_date

    def test_book_from_dict(self):
        # Test creating a Book from a dictionary with minimal data
        data = {'title': 'Minimal Book'}
        book = Book.from_dict(data)
        assert book.id is None
        assert book.title == 'Minimal Book'
        assert book.total_words == 0
        assert book.unique_words == 0
        assert book.scrape_date is None

        # Test creating a Book from a complete dictionary
        scrape_date = datetime.now()
        data = {
            'id': 2,
            'title': 'Complete Dict Book',
            'total_words': 600,
            'unique_words': 250,
            'scrape_date': scrape_date
        }
        book = Book.from_dict(data)
        assert book.id == 2
        assert book.title == 'Complete Dict Book'
        assert book.total_words == 600
        assert book.unique_words == 250
        assert book.scrape_date == scrape_date

    def test_book_to_dict(self):
        # Test converting a minimal Book to a dictionary
        book = Book(title="Minimal Book")
        data = book.to_dict()
        assert 'id' not in data
        assert data['title'] == 'Minimal Book'
        assert data['total_words'] == 0
        assert data['unique_words'] == 0
        assert 'scrape_date' not in data

        # Test converting a complete Book to a dictionary
        scrape_date = datetime.now()
        book = Book(
            title="Complete Book",
            book_id=3,
            total_words=700,
            unique_words=300,
            scrape_date=scrape_date
        )
        data = book.to_dict()
        assert data['id'] == 3
        assert data['title'] == 'Complete Book'
        assert data['total_words'] == 700
        assert data['unique_words'] == 300
        assert data['scrape_date'] == scrape_date


class TestWord:
    def test_word_initialization(self):
        # Test basic initialization
        word = Word(english_word="test")
        assert word.id is None
        assert word.english_word == "test"
        assert word.listening is None
        assert word.russian_word is None
        assert word.sentences is None
        assert word.level is None
        assert word.brown == 0
        assert word.get_download == 0
        assert word.learning_status == Word.STATUS_NEW

        # Test initialization with all parameters
        word = Word(
            english_word="complete",
            listening="[sound:complete.mp3]",
            russian_word="полный",
            sentences="This is a complete test.",
            level="B1",
            brown=1,
            get_download=1,
            learning_status=Word.STATUS_ACTIVE,
            word_id=1
        )
        assert word.id == 1
        assert word.english_word == "complete"
        assert word.listening == "[sound:complete.mp3]"
        assert word.russian_word == "полный"
        assert word.sentences == "This is a complete test."
        assert word.level == "B1"
        assert word.brown == 1
        assert word.get_download == 1
        assert word.learning_status == Word.STATUS_ACTIVE

    def test_word_from_dict(self):
        # Test creating a Word from a dictionary with minimal data
        data = {'english_word': 'minimal'}
        word = Word.from_dict(data)
        assert word.id is None
        assert word.english_word == 'minimal'
        assert word.learning_status == Word.STATUS_NEW
        assert word.brown == 0
        assert word.get_download == 0

        # Test creating a Word from a complete dictionary
        data = {
            'id': 2,
            'english_word': 'full',
            'listening': '[sound:full.mp3]',
            'russian_word': 'полный',
            'sentences': 'A full example.',
            'level': 'B2',
            'brown': 1,
            'get_download': 1,
            'learning_status': Word.STATUS_MASTERED
        }
        word = Word.from_dict(data)
        assert word.id == 2
        assert word.english_word == 'full'
        assert word.listening == '[sound:full.mp3]'
        assert word.russian_word == 'полный'
        assert word.sentences == 'A full example.'
        assert word.level == 'B2'
        assert word.brown == 1
        assert word.get_download == 1
        assert word.learning_status == Word.STATUS_MASTERED

    def test_word_to_dict(self):
        # Test converting a minimal Word to a dictionary
        word = Word(english_word="minimal")
        data = word.to_dict()
        assert 'id' not in data
        assert data['english_word'] == 'minimal'
        assert data['brown'] == 0
        assert data['get_download'] == 0
        assert data['learning_status'] == Word.STATUS_NEW
        assert 'listening' not in data
        assert 'russian_word' not in data
        assert 'sentences' not in data
        assert 'level' not in data

        # Test converting a complete Word to a dictionary
        word = Word(
            english_word="complete",
            listening="[sound:complete.mp3]",
            russian_word="полный",
            sentences="This is a complete test.",
            level="B1",
            brown=1,
            get_download=1,
            learning_status=Word.STATUS_ACTIVE,
            word_id=3
        )
        data = word.to_dict()
        assert data['id'] == 3
        assert data['english_word'] == 'complete'
        assert data['listening'] == '[sound:complete.mp3]'
        assert data['russian_word'] == 'полный'
        assert data['sentences'] == 'This is a complete test.'
        assert data['level'] == 'B1'
        assert data['brown'] == 1
        assert data['get_download'] == 1
        assert data['learning_status'] == Word.STATUS_ACTIVE

    def test_get_status_label(self):
        # Test all status labels
        word = Word(english_word="test")

        word.learning_status = Word.STATUS_NEW
        assert word.get_status_label() == "Новое"

        word.learning_status = Word.STATUS_KNOWN
        assert word.get_status_label() == "Известное"

        word.learning_status = Word.STATUS_QUEUED
        assert word.get_status_label() == "В очереди"

        word.learning_status = Word.STATUS_ACTIVE
        assert word.get_status_label() == "Активное"

        word.learning_status = Word.STATUS_MASTERED
        assert word.get_status_label() == "Изучено"

        # Test unknown status
        word.learning_status = 99
        assert word.get_status_label() == "Неизвестный статус"


class TestPhrasalVerb:
    def test_phrasal_verb_initialization(self):
        # Test basic initialization
        phrasal_verb = PhrasalVerb(phrasal_verb="look up")
        assert phrasal_verb.id is None
        assert phrasal_verb.phrasal_verb == "look up"
        assert phrasal_verb.russian_translate is None
        assert phrasal_verb.using is None
        assert phrasal_verb.sentence is None
        assert phrasal_verb.word_id is None
        assert phrasal_verb.listening is None
        assert phrasal_verb.get_download == 0

        # Test initialization with all parameters
        phrasal_verb = PhrasalVerb(
            phrasal_verb="give up",
            russian_translate="сдаться",
            using="stop trying",
            sentence="Never give up on your dreams.",
            word_id=1,
            listening="[sound:give_up.mp3]",
            get_download=1,
            verb_id=1
        )
        assert phrasal_verb.id == 1
        assert phrasal_verb.phrasal_verb == "give up"
        assert phrasal_verb.russian_translate == "сдаться"
        assert phrasal_verb.using == "stop trying"
        assert phrasal_verb.sentence == "Never give up on your dreams."
        assert phrasal_verb.word_id == 1
        assert phrasal_verb.listening == "[sound:give_up.mp3]"
        assert phrasal_verb.get_download == 1

    def test_phrasal_verb_from_dict(self):
        # Test creating a PhrasalVerb from a dictionary with minimal data
        data = {'phrasal_verb': 'look for'}
        phrasal_verb = PhrasalVerb.from_dict(data)
        assert phrasal_verb.id is None
        assert phrasal_verb.phrasal_verb == 'look for'
        assert phrasal_verb.get_download == 0

        # Test creating a PhrasalVerb from a complete dictionary
        data = {
            'id': 2,
            'phrasal_verb': 'break down',
            'russian_translate': 'сломаться',
            'using': 'stop working',
            'sentence': 'My car broke down yesterday.',
            'word_id': 2,
            'listening': '[sound:break_down.mp3]',
            'get_download': 1
        }
        phrasal_verb = PhrasalVerb.from_dict(data)
        assert phrasal_verb.id == 2
        assert phrasal_verb.phrasal_verb == 'break down'
        assert phrasal_verb.russian_translate == 'сломаться'
        assert phrasal_verb.using == 'stop working'
        assert phrasal_verb.sentence == 'My car broke down yesterday.'
        assert phrasal_verb.word_id == 2
        assert phrasal_verb.listening == '[sound:break_down.mp3]'
        assert phrasal_verb.get_download == 1

    def test_phrasal_verb_to_dict(self):
        # Test converting a minimal PhrasalVerb to a dictionary
        phrasal_verb = PhrasalVerb(phrasal_verb="look for")
        data = phrasal_verb.to_dict()
        assert 'id' not in data
        assert data['phrasal_verb'] == 'look for'
        assert data['get_download'] == 0
        assert 'russian_translate' not in data
        assert 'using' not in data
        assert 'sentence' not in data
        assert 'word_id' not in data
        assert 'listening' not in data

        # Test converting a complete PhrasalVerb to a dictionary
        phrasal_verb = PhrasalVerb(
            phrasal_verb="give up",
            russian_translate="сдаться",
            using="stop trying",
            sentence="Never give up on your dreams.",
            word_id=3,
            listening="[sound:give_up.mp3]",
            get_download=1,
            verb_id=3
        )
        data = phrasal_verb.to_dict()
        assert data['id'] == 3
        assert data['phrasal_verb'] == 'give up'
        assert data['russian_translate'] == 'сдаться'
        assert data['using'] == 'stop trying'
        assert data['sentence'] == 'Never give up on your dreams.'
        assert data['word_id'] == 3
        assert data['listening'] == '[sound:give_up.mp3]'
        assert data['get_download'] == 1


class TestDBInitializer:
    def test_create_tables(self):
        # Create a temporary database file
        fd, temp_db = tempfile.mkstemp(suffix='.db')
        os.close(fd)

        try:
            # Initialize the database
            DBInitializer.create_tables(temp_db)

            # Verify tables were created
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()

            # Check for book table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='book'")
            assert cursor.fetchone() is not None

            # Check for collections_word table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='collections_word'")
            assert cursor.fetchone() is not None

            # Check for word_book_link table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='word_book_link'")
            assert cursor.fetchone() is not None

            # Check for phrasal_verb table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='phrasal_verb'")
            assert cursor.fetchone() is not None

            # Check if schema version was set
            cursor.execute("PRAGMA user_version")
            assert cursor.fetchone()[0] == 1

            conn.close()
        finally:
            # Clean up the temporary file
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_update_schema_if_needed(self):
        # Create a temporary database file
        fd, temp_db = tempfile.mkstemp(suffix='.db')
        os.close(fd)

        try:
            # Create a basic database with version 0
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            cursor.execute("PRAGMA user_version = 0")
            conn.commit()

            # Run the schema update
            DBInitializer.update_schema_if_needed(temp_db)

            # Verify schema was updated
            cursor.execute("PRAGMA user_version")
            assert cursor.fetchone()[0] == 3  # Should be updated to latest version

            # Check if learning_status column exists
            cursor.execute("PRAGMA table_info(collections_word)")
            columns = [column[1] for column in cursor.fetchall()]
            assert "learning_status" in columns

            # Check if book statistics columns exist
            cursor.execute("PRAGMA table_info(book)")
            columns = [column[1] for column in cursor.fetchall()]
            assert "total_words" in columns
            assert "unique_words" in columns
            assert "scrape_date" in columns

            conn.close()
        finally:
            # Clean up the temporary file
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_update_book_stats(self):
        # Create a temporary database file
        fd, temp_db = tempfile.mkstemp(suffix='.db')
        os.close(fd)

        try:
            # Initialize the database
            DBInitializer.create_tables(temp_db)

            # Create a test book and some words
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()

            # Insert a book
            cursor.execute(
                "INSERT INTO book (title, total_words, unique_words) VALUES (?, ?, ?)",
                ("Test Book", 0, 0)
            )
            book_id = cursor.lastrowid

            # Insert some words
            cursor.execute(
                "INSERT INTO collections_word (english_word) VALUES (?)",
                ("word1",)
            )
            word1_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO collections_word (english_word) VALUES (?)",
                ("word2",)
            )
            word2_id = cursor.lastrowid

            # Link words to book
            cursor.execute(
                "INSERT INTO word_book_link (word_id, book_id, frequency) VALUES (?, ?, ?)",
                (word1_id, book_id, 3)
            )

            cursor.execute(
                "INSERT INTO word_book_link (word_id, book_id, frequency) VALUES (?, ?, ?)",
                (word2_id, book_id, 2)
            )

            conn.commit()

            # Update book stats for specific book
            DBInitializer.update_book_stats(temp_db, book_id)

            # Verify book stats were updated
            cursor.execute("SELECT total_words, unique_words FROM book WHERE id = ?", (book_id,))
            total_words, unique_words = cursor.fetchone()
            assert total_words == 5  # 3 + 2
            assert unique_words == 2  # word1 and word2

            conn.close()
        finally:
            # Clean up the temporary file
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_update_book_stats_all_books(self):
        # Create a temporary database file
        fd, temp_db = tempfile.mkstemp(suffix='.db')
        os.close(fd)

        try:
            # Initialize the database
            DBInitializer.create_tables(temp_db)

            # Create test books and words
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()

            # Insert books
            cursor.execute(
                "INSERT INTO book (title, total_words, unique_words) VALUES (?, ?, ?)",
                ("Book 1", 0, 0)
            )
            book1_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO book (title, total_words, unique_words) VALUES (?, ?, ?)",
                ("Book 2", 0, 0)
            )
            book2_id = cursor.lastrowid

            # Insert words
            cursor.execute(
                "INSERT INTO collections_word (english_word) VALUES (?)",
                ("word1",)
            )
            word1_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO collections_word (english_word) VALUES (?)",
                ("word2",)
            )
            word2_id = cursor.lastrowid

            # Link words to books
            cursor.execute(
                "INSERT INTO word_book_link (word_id, book_id, frequency) VALUES (?, ?, ?)",
                (word1_id, book1_id, 3)
            )

            cursor.execute(
                "INSERT INTO word_book_link (word_id, book_id, frequency) VALUES (?, ?, ?)",
                (word2_id, book1_id, 2)
            )

            cursor.execute(
                "INSERT INTO word_book_link (word_id, book_id, frequency) VALUES (?, ?, ?)",
                (word1_id, book2_id, 1)
            )

            conn.commit()

            # Update stats for all books
            DBInitializer.update_book_stats(temp_db)

            # Verify stats for book 1
            cursor.execute("SELECT total_words, unique_words FROM book WHERE id = ?", (book1_id,))
            total_words, unique_words = cursor.fetchone()
            assert total_words == 5  # 3 + 2
            assert unique_words == 2  # word1 and word2

            # Verify stats for book 2
            cursor.execute("SELECT total_words, unique_words FROM book WHERE id = ?", (book2_id,))
            total_words, unique_words = cursor.fetchone()
            assert total_words == 1
            assert unique_words == 1  # Only word1

            conn.close()
        finally:
            # Clean up the temporary file
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_error_handling(self):
        # Test with invalid database path
        with pytest.raises(sqlite3.Error):
            DBInitializer.create_tables("/nonexistent/path/db.sqlite")

        with pytest.raises(sqlite3.Error):
            DBInitializer.update_schema_if_needed("/nonexistent/path/db.sqlite")

        with pytest.raises(sqlite3.Error):
            DBInitializer.update_book_stats("/nonexistent/path/db.sqlite")
