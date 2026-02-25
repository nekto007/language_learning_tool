"""
Tests for DatabaseRepository (app/repository.py)
"""
import pytest
from unittest.mock import MagicMock, patch, mock_open, call
import psycopg2


class MockWord:
    """Mock Word object for testing"""
    def __init__(self, english_word, listening=None, russian_word=None,
                 sentences=None, level=None, brown=None, get_download=0):
        self.english_word = english_word
        self.listening = listening
        self.russian_word = russian_word
        self.sentences = sentences
        self.level = level
        self.brown = brown
        self.get_download = get_download


class MockBook:
    """Mock Book object for testing"""
    def __init__(self, title, id=None):
        self.title = title
        self.id = id


class TestDatabaseRepositoryInit:
    """Tests for DatabaseRepository initialization"""

    def test_init_with_custom_config(self):
        """Test initialization with custom config"""
        from app.repository import DatabaseRepository

        custom_config = {'host': 'custom-host', 'database': 'custom-db'}
        repo = DatabaseRepository(custom_config)

        assert repo.db_config == custom_config

    @patch('app.repository.DB_CONFIG', {'host': 'default', 'database': 'default-db'})
    def test_init_with_default_config(self):
        """Test initialization with default config"""
        from app.repository import DatabaseRepository

        repo = DatabaseRepository()
        assert 'host' in repo.db_config


class TestDatabaseRepositoryGetConnection:
    """Tests for get_connection method"""

    @patch('app.repository.psycopg2.connect')
    def test_get_connection_success(self, mock_connect):
        """Test successful connection"""
        from app.repository import DatabaseRepository

        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        conn = repo.get_connection()

        mock_connect.assert_called_once_with(host='test')
        assert conn == mock_conn


class TestDatabaseRepositoryExecuteQuery:
    """Tests for execute_query method"""

    @patch('app.repository.psycopg2.connect')
    def test_execute_query_without_fetch(self, mock_connect):
        """Test execute query without returning results"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.execute_query("INSERT INTO test VALUES (%s)", (1,))

        assert result is None
        mock_cursor.execute.assert_called_once_with("INSERT INTO test VALUES (%s)", (1,))

    @patch('app.repository.psycopg2.connect')
    def test_execute_query_with_fetch(self, mock_connect):
        """Test execute query with returning results"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1, 'test'), (2, 'test2')]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.execute_query("SELECT * FROM test", fetch=True)

        assert result == [(1, 'test'), (2, 'test2')]

    @patch('app.repository.psycopg2.connect')
    def test_execute_query_db_error(self, mock_connect):
        """Test execute query with database error"""
        from app.repository import DatabaseRepository

        mock_connect.side_effect = psycopg2.Error("Connection failed")

        repo = DatabaseRepository({'host': 'test'})

        with pytest.raises(psycopg2.Error):
            repo.execute_query("SELECT 1")


class TestDatabaseRepositoryInsertOrUpdateBook:
    """Tests for insert_or_update_book method"""

    @patch('app.repository.psycopg2.connect')
    def test_insert_new_book(self, mock_connect):
        """Test inserting a new book"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (42,)  # New book ID

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        book = MockBook(title="Test Book")
        result = repo.insert_or_update_book(book)

        assert result == 42

    @patch('app.repository.psycopg2.connect')
    def test_insert_existing_book(self, mock_connect):
        """Test inserting an existing book (returns existing ID)"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        # First fetchone returns None (no insert), second returns existing ID
        mock_cursor.fetchone.side_effect = [None, (99,)]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        book = MockBook(title="Existing Book")
        result = repo.insert_or_update_book(book)

        assert result == 99

    @patch('app.repository.psycopg2.connect')
    def test_insert_book_error(self, mock_connect):
        """Test inserting book with error"""
        from app.repository import DatabaseRepository

        mock_connect.side_effect = psycopg2.Error("Database error")

        repo = DatabaseRepository({'host': 'test'})
        book = MockBook(title="Test Book")
        result = repo.insert_or_update_book(book)

        assert result == 0


class TestDatabaseRepositoryBulkInsertOrUpdateWords:
    """Tests for bulk_insert_or_update_words method"""

    def test_bulk_insert_empty_batch(self):
        """Test with empty batch"""
        from app.repository import DatabaseRepository

        repo = DatabaseRepository({'host': 'test'})
        result = repo.bulk_insert_or_update_words([])

        assert result == {}

    @patch('app.repository.psycopg2.connect')
    def test_bulk_insert_new_words(self, mock_connect):
        """Test bulk inserting new words"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        # First query: check existing words - returns empty
        mock_cursor.fetchall.return_value = []
        # For each insert, return ID and english_word
        mock_cursor.fetchone.side_effect = [(1, 'hello'), (2, 'world')]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        words = [
            MockWord('hello', russian_word='привет'),
            MockWord('world', russian_word='мир')
        ]
        result = repo.bulk_insert_or_update_words(words)

        assert 'hello' in result
        assert 'world' in result
        assert result['hello'] == 1
        assert result['world'] == 2

    @patch('app.repository.psycopg2.connect')
    def test_bulk_insert_existing_words(self, mock_connect):
        """Test bulk updating existing words"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        # First query: check existing words - returns existing IDs
        mock_cursor.fetchall.return_value = [(10, 'hello'), (20, 'world')]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        words = [
            MockWord('hello', russian_word='привет'),
            MockWord('world', russian_word='мир')
        ]
        result = repo.bulk_insert_or_update_words(words)

        assert result == {'hello': 10, 'world': 20}
        # Verify update was called
        mock_cursor.executemany.assert_called_once()

    @patch('app.repository.psycopg2.connect')
    def test_bulk_insert_error(self, mock_connect):
        """Test bulk insert with error"""
        from app.repository import DatabaseRepository

        mock_connect.side_effect = psycopg2.Error("Database error")

        repo = DatabaseRepository({'host': 'test'})
        words = [MockWord('test')]
        result = repo.bulk_insert_or_update_words(words)

        # Should return partial results (empty in this case)
        assert isinstance(result, dict)


class TestDatabaseRepositoryBulkLinkWordsToBook:
    """Tests for bulk_link_words_to_book method"""

    def test_bulk_link_empty_data(self):
        """Test with empty data"""
        from app.repository import DatabaseRepository

        repo = DatabaseRepository({'host': 'test'})
        # Should not raise
        repo.bulk_link_words_to_book([])

    @patch('app.repository.psycopg2.connect')
    def test_bulk_link_success(self, mock_connect):
        """Test successful bulk linking"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        link_data = [(1, 10, 5), (2, 10, 3)]  # (word_id, book_id, frequency)
        repo.bulk_link_words_to_book(link_data)

        mock_cursor.executemany.assert_called_once()


class TestDatabaseRepositoryClearBookWordLinks:
    """Tests for clear_book_word_links method"""

    @patch('app.repository.psycopg2.connect')
    def test_clear_links_success(self, mock_connect):
        """Test successful clearing of links"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 5

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        repo.clear_book_word_links(10)

        mock_cursor.execute.assert_called_once_with(
            "DELETE FROM word_book_link WHERE book_id = %s",
            (10,)
        )


class TestDatabaseRepositoryInsertOrUpdateWord:
    """Tests for insert_or_update_word method"""

    @patch('app.repository.psycopg2.connect')
    def test_insert_new_word(self, mock_connect):
        """Test inserting a new word"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        # First query returns None (word doesn't exist)
        # Second query returns new ID
        mock_cursor.fetchone.side_effect = [None, (42,)]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        word = MockWord('test', russian_word='тест')
        result = repo.insert_or_update_word(word)

        assert result == 42

    @patch('app.repository.psycopg2.connect')
    def test_update_existing_word(self, mock_connect):
        """Test updating existing word"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        # Word exists with ID 10
        mock_cursor.fetchone.return_value = (10,)

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        word = MockWord('test', russian_word='тест обновлен')
        result = repo.insert_or_update_word(word)

        assert result == 10

    @patch('app.repository.psycopg2.connect')
    def test_insert_word_error(self, mock_connect):
        """Test word insertion with error"""
        from app.repository import DatabaseRepository

        mock_connect.side_effect = psycopg2.Error("Database error")

        repo = DatabaseRepository({'host': 'test'})
        word = MockWord('test')
        result = repo.insert_or_update_word(word)

        assert result == 0


class TestDatabaseRepositoryLinkWordToBook:
    """Tests for link_word_to_book method"""

    @patch.object(__import__('app.repository', fromlist=['DatabaseRepository']).DatabaseRepository, 'execute_query')
    def test_link_word_success(self, mock_execute):
        """Test successful word-book linking"""
        from app.repository import DatabaseRepository

        repo = DatabaseRepository({'host': 'test'})
        repo.link_word_to_book(1, 10, 5)

        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        assert (1, 10, 5, 5) == call_args[0][1]


class TestDatabaseRepositoryInsertOrUpdatePhrasalVerb:
    """Tests for insert_or_update_phrasal_verb method"""

    @patch('app.repository.psycopg2.connect')
    def test_insert_new_phrasal_verb(self, mock_connect):
        """Test inserting new phrasal verb"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [None, (100,)]  # Not exists, then new ID

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.insert_or_update_phrasal_verb(
            'give up', 'сдаваться', 'to stop trying', 'I will never give up.'
        )

        assert result == 100

    @patch('app.repository.psycopg2.connect')
    def test_update_existing_phrasal_verb(self, mock_connect):
        """Test updating existing phrasal verb"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (50,)  # Exists with ID 50

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.insert_or_update_phrasal_verb(
            'give up', 'сдаваться', 'to stop trying', 'Updated sentence'
        )

        assert result == 50


class TestDatabaseRepositoryGetWordByEnglish:
    """Tests for get_word_by_english method"""

    @patch('app.repository.psycopg2.connect')
    @patch('app.repository.Word')
    def test_get_word_found(self, mock_word_class, mock_connect):
        """Test getting existing word"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'id': 1, 'english_word': 'test'}

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        mock_word = MagicMock()
        mock_word_class.from_dict.return_value = mock_word

        repo = DatabaseRepository({'host': 'test'})
        result = repo.get_word_by_english('test')

        assert result == mock_word
        mock_word_class.from_dict.assert_called_once()

    @patch('app.repository.psycopg2.connect')
    def test_get_word_not_found(self, mock_connect):
        """Test getting non-existent word"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.get_word_by_english('nonexistent')

        assert result is None


class TestDatabaseRepositoryGetWordsByFilter:
    """Tests for get_words_by_filter method"""

    @patch('app.repository.psycopg2.connect')
    @patch('app.repository.Word')
    def test_get_words_with_filters(self, mock_word_class, mock_connect):
        """Test getting words with filters"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {'id': 1, 'english_word': 'test1'},
            {'id': 2, 'english_word': 'test2'}
        ]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        mock_word_class.from_dict.return_value = MagicMock()

        repo = DatabaseRepository({'host': 'test'})
        result = repo.get_words_by_filter(level='A1')

        assert len(result) == 2

    @patch('app.repository.psycopg2.connect')
    def test_get_words_no_results(self, mock_connect):
        """Test getting words with no results"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.get_words_by_filter(level='C2')

        assert result == []


class TestDatabaseRepositoryGetWordsByBook:
    """Tests for get_words_by_book method"""

    @patch('app.repository.psycopg2.connect')
    def test_get_words_by_book_success(self, mock_connect):
        """Test getting words by book ID"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {'id': 1, 'english_word': 'word1', 'frequency': 10},
            {'id': 2, 'english_word': 'word2', 'frequency': 5}
        ]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.get_words_by_book(10)

        assert len(result) == 2
        assert result[0]['frequency'] == 10

    @patch('app.repository.psycopg2.connect')
    def test_get_words_by_book_empty(self, mock_connect):
        """Test getting words for book with no words"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.get_words_by_book(999)

        assert result == []


class TestDatabaseRepositoryUpdateDownloadStatus:
    """Tests for update_download_status method"""

    @patch('app.repository.os.path.isfile')
    @patch.object(__import__('app.repository', fromlist=['DatabaseRepository']).DatabaseRepository, 'execute_query')
    @patch.object(__import__('app.repository', fromlist=['DatabaseRepository']).DatabaseRepository, 'get_connection')
    def test_update_download_status_with_files(self, mock_get_conn, mock_execute, mock_isfile):
        """Test updating download status when files exist"""
        from app.repository import DatabaseRepository

        # Query selects (column_name, listening) so tuples need 2 elements
        mock_execute.return_value = [('hello', None), ('world', None)]
        mock_isfile.side_effect = [True, False]  # hello exists, world doesn't

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_get_conn.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.update_download_status('collection_words', 'english_word', '/media')

        assert result == 1  # Only 'hello' was updated

    @patch.object(__import__('app.repository', fromlist=['DatabaseRepository']).DatabaseRepository, 'execute_query')
    def test_update_download_status_no_words(self, mock_execute):
        """Test updating when no words need downloading"""
        from app.repository import DatabaseRepository

        mock_execute.return_value = None

        repo = DatabaseRepository({'host': 'test'})
        result = repo.update_download_status('collection_words', 'english_word', '/media')

        assert result == 0


class TestDatabaseRepositoryProcessTranslateFile:
    """Tests for process_translate_file method"""

    @patch('app.repository.os.path.exists')
    def test_process_translate_file_not_found(self, mock_exists):
        """Test processing non-existent file"""
        from app.repository import DatabaseRepository

        mock_exists.return_value = False

        repo = DatabaseRepository({'host': 'test'})
        result = repo.process_translate_file('/nonexistent/file.txt')

        assert result == 0

    @patch('app.repository.os.path.exists')
    @patch('builtins.open', mock_open(read_data='hello;привет;Hello world;Привет мир;A1\n'))
    @patch('app.repository.psycopg2.connect')
    def test_process_translate_file_success(self, mock_connect, mock_exists):
        """Test processing valid translate file"""
        from app.repository import DatabaseRepository

        mock_exists.return_value = True

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.process_translate_file('/path/to/file.txt')

        assert result == 1
        mock_cursor.execute.assert_called()


class TestDatabaseRepositoryProcessPhrasalVerbFile:
    """Tests for process_phrasal_verb_file method"""

    @patch('app.repository.os.path.exists')
    def test_process_phrasal_verb_file_not_found(self, mock_exists):
        """Test processing non-existent file"""
        from app.repository import DatabaseRepository

        mock_exists.return_value = False

        repo = DatabaseRepository({'host': 'test'})
        result = repo.process_phrasal_verb_file('/nonexistent/file.txt')

        assert result == 0


class TestDatabaseRepositoryUpdateWordStatus:
    """Tests for update_word_status and related methods"""

    @patch.object(__import__('app.repository', fromlist=['DatabaseRepository']).DatabaseRepository, 'execute_query')
    def test_update_word_status_success(self, mock_execute):
        """Test successful word status update"""
        from app.repository import DatabaseRepository

        repo = DatabaseRepository({'host': 'test'})
        result = repo.update_word_status(1, 2)

        assert result is True
        mock_execute.assert_called_once()

    @patch.object(__import__('app.repository', fromlist=['DatabaseRepository']).DatabaseRepository, 'execute_query')
    def test_update_word_status_error(self, mock_execute):
        """Test word status update with error"""
        from app.repository import DatabaseRepository

        mock_execute.side_effect = psycopg2.Error("Database error")

        repo = DatabaseRepository({'host': 'test'})
        result = repo.update_word_status(1, 2)

        assert result is False

    @patch.object(__import__('app.repository', fromlist=['DatabaseRepository']).DatabaseRepository, 'execute_query')
    def test_update_word_status_by_english(self, mock_execute):
        """Test word status update by english word"""
        from app.repository import DatabaseRepository

        repo = DatabaseRepository({'host': 'test'})
        result = repo.update_word_status_by_english('test', 1)

        assert result is True


class TestDatabaseRepositoryGetWordsByStatus:
    """Tests for get_words_by_status method"""

    @patch('app.repository.psycopg2.connect')
    @patch('app.repository.Word')
    def test_get_words_by_status_success(self, mock_word_class, mock_connect):
        """Test getting words by status"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {'id': 1, 'english_word': 'test', 'learning_status': 1}
        ]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        mock_word_class.from_dict.return_value = MagicMock()

        repo = DatabaseRepository({'host': 'test'})
        result = repo.get_words_by_status(1)

        assert len(result) == 1

    @patch('app.repository.psycopg2.connect')
    def test_get_words_by_status_empty(self, mock_connect):
        """Test getting words by status with no results"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.get_words_by_status(99)

        assert result == []


class TestDatabaseRepositoryBatchUpdateWordStatus:
    """Tests for batch_update_word_status method"""

    def test_batch_update_empty_list(self):
        """Test batch update with empty list"""
        from app.repository import DatabaseRepository

        repo = DatabaseRepository({'host': 'test'})
        result = repo.batch_update_word_status([], 1)

        assert result == 0

    @patch('app.repository.psycopg2.connect')
    def test_batch_update_success(self, mock_connect):
        """Test successful batch update"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.batch_update_word_status(['hello', 'world'], 2)

        assert result == 2  # 2 words, each with rowcount=1


class TestDatabaseRepositoryUpdateBookStats:
    """Tests for update_book_stats method"""

    @patch.object(__import__('app.repository', fromlist=['DatabaseRepository']).DatabaseRepository, 'execute_query')
    def test_update_book_stats_success(self, mock_execute):
        """Test successful book stats update"""
        from app.repository import DatabaseRepository

        repo = DatabaseRepository({'host': 'test'})
        result = repo.update_book_stats(1, 1000, 500)

        assert result is True

    @patch.object(__import__('app.repository', fromlist=['DatabaseRepository']).DatabaseRepository, 'execute_query')
    def test_update_book_stats_error(self, mock_execute):
        """Test book stats update with error"""
        from app.repository import DatabaseRepository

        mock_execute.side_effect = Exception("Database error")

        repo = DatabaseRepository({'host': 'test'})
        result = repo.update_book_stats(1, 1000, 500)

        assert result is False


class TestDatabaseRepositoryGetBookById:
    """Tests for get_book_by_id method"""

    @patch('app.repository.psycopg2.connect')
    @patch('app.repository.Book')
    def test_get_book_found(self, mock_book_class, mock_connect):
        """Test getting existing book"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'id': 1, 'title': 'Test Book'}

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        mock_book = MagicMock()
        mock_book_class.from_dict.return_value = mock_book

        repo = DatabaseRepository({'host': 'test'})
        result = repo.get_book_by_id(1)

        assert result == mock_book

    @patch('app.repository.psycopg2.connect')
    def test_get_book_not_found(self, mock_connect):
        """Test getting non-existent book"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.get_book_by_id(999)

        assert result is None


class TestDatabaseRepositoryGetBooksWithStats:
    """Tests for get_books_with_stats method"""

    @patch('app.repository.psycopg2.connect')
    def test_get_books_with_stats_success(self, mock_connect):
        """Test getting books with stats"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {'id': 1, 'title': 'Book 1', 'words_total': 1000},
            {'id': 2, 'title': 'Book 2', 'words_total': 500}
        ]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.get_books_with_stats()

        assert len(result) == 2

    @patch('app.repository.psycopg2.connect')
    def test_get_books_with_stats_empty(self, mock_connect):
        """Test getting books when none exist"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        result = repo.get_books_with_stats()

        assert result == []


class TestDatabaseRepositoryUpdateSchemaIfNeeded:
    """Tests for update_schema_if_needed method"""

    @patch('app.repository.psycopg2.connect')
    def test_update_schema_column_exists(self, mock_connect):
        """Test schema update when column already exists"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ('learning_status',)  # Column exists

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        repo.update_schema_if_needed()

        # Should only call the check query, not alter table
        assert mock_cursor.execute.call_count == 1

    @patch('app.repository.psycopg2.connect')
    def test_update_schema_column_missing(self, mock_connect):
        """Test schema update when column is missing"""
        from app.repository import DatabaseRepository

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # Column doesn't exist

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_connect.return_value = mock_conn

        repo = DatabaseRepository({'host': 'test'})
        repo.update_schema_if_needed()

        # Should call check query + ALTER TABLE + CREATE INDEX
        assert mock_cursor.execute.call_count == 3


class TestDatabaseRepositoryProcessBatchFromOriginalFormat:
    """Tests for process_batch_from_original_format method"""

    @patch.object(__import__('app.repository', fromlist=['DatabaseRepository']).DatabaseRepository, 'bulk_insert_or_update_words')
    @patch.object(__import__('app.repository', fromlist=['DatabaseRepository']).DatabaseRepository, 'bulk_link_words_to_book')
    def test_process_batch_success(self, mock_bulk_link, mock_bulk_insert):
        """Test processing batch of word data"""
        from app.repository import DatabaseRepository

        mock_bulk_insert.return_value = {'hello': 1, 'world': 2}

        repo = DatabaseRepository({'host': 'test'})
        word_data = [
            ('hello', '[sound:hello.mp3]', 500, 10),
            ('world', '[sound:world.mp3]', 400, 5)
        ]
        result = repo.process_batch_from_original_format(word_data, 1)

        assert result == 2
        mock_bulk_insert.assert_called_once()
        mock_bulk_link.assert_called_once()

    @patch.object(__import__('app.repository', fromlist=['DatabaseRepository']).DatabaseRepository, 'bulk_insert_or_update_words')
    @patch.object(__import__('app.repository', fromlist=['DatabaseRepository']).DatabaseRepository, 'bulk_link_words_to_book')
    def test_process_batch_with_batching(self, mock_bulk_link, mock_bulk_insert):
        """Test processing large batch that requires multiple batches"""
        from app.repository import DatabaseRepository

        # Each call returns word IDs
        mock_bulk_insert.side_effect = [
            {'word1': 1, 'word2': 2},
            {'word3': 3}
        ]

        repo = DatabaseRepository({'host': 'test'})

        # Create word data larger than batch_size
        word_data = [(f'word{i}', f'[sound:word{i}.mp3]', 100, 1) for i in range(1, 4)]

        result = repo.process_batch_from_original_format(word_data, 1, batch_size=2)

        # Should have processed 3 words
        assert mock_bulk_insert.call_count == 2
        assert mock_bulk_link.call_count == 2
