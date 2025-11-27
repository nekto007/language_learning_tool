# tests/admin/services/test_word_management_service.py

"""
Unit tests for WordManagementService
Tests word statistics, bulk operations, and import/export functionality
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from app.admin.services.word_management_service import WordManagementService


class TestGetWordStatistics:
    """Tests for get_word_statistics method"""

    @patch('app.admin.services.word_management_service.db')
    @patch('app.admin.services.word_management_service.CollectionWords')
    @patch('app.admin.services.word_management_service.UserWord')
    def test_get_word_statistics_success(self, mock_user_word, mock_collection_words, mock_db):
        """Test successful word statistics retrieval"""
        # Mock total words count
        mock_collection_words.query.count.return_value = 100

        # Mock status stats
        mock_status_stats = [
            ('new', 30),
            ('learning', 50),
            ('mastered', 20)
        ]
        mock_db.session.query.return_value.group_by.return_value.all.return_value = mock_status_stats

        # Mock recent words
        mock_word = Mock()
        mock_word.english_word = 'test'
        mock_collection_words.query.order_by.return_value.limit.return_value.all.return_value = [mock_word]

        # Mock words without translation
        mock_collection_words.query.filter.return_value.count.return_value = 5

        result = WordManagementService.get_word_statistics()

        assert result['words_total'] == 100
        assert result['status_stats'] == mock_status_stats
        assert len(result['recent_words']) == 1
        assert result['words_without_translation'] == 5

    @patch('app.admin.services.word_management_service.logger')
    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_get_word_statistics_error(self, mock_collection_words, mock_logger):
        """Test error handling in get_word_statistics"""
        mock_collection_words.query.count.side_effect = Exception("Database error")

        result = WordManagementService.get_word_statistics()

        assert 'error' in result
        assert result['error'] == "Database error"
        mock_logger.error.assert_called_once()

    @patch('app.admin.services.word_management_service.db')
    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_get_word_statistics_empty_db(self, mock_collection_words, mock_db):
        """Test statistics with empty database"""
        mock_collection_words.query.count.return_value = 0
        mock_db.session.query.return_value.group_by.return_value.all.return_value = []
        mock_collection_words.query.order_by.return_value.limit.return_value.all.return_value = []
        mock_collection_words.query.filter.return_value.count.return_value = 0

        result = WordManagementService.get_word_statistics()

        assert result['words_total'] == 0
        assert result['status_stats'] == []
        assert result['recent_words'] == []
        assert result['words_without_translation'] == 0


class TestGetDetailedStatistics:
    """Tests for get_detailed_statistics method"""

    @patch('app.admin.services.word_management_service.db')
    @patch('app.admin.services.word_management_service.User')
    @patch('app.admin.services.word_management_service.Book')
    def test_get_detailed_statistics_success(self, mock_book, mock_user, mock_db):
        """Test successful detailed statistics retrieval"""
        # Mock status stats
        mock_status = [('new', 10, 5)]
        # Mock level stats
        mock_level = [('A1', 20)]
        # Mock top users
        mock_users = [('user1', 100)]
        # Mock book stats
        mock_books = [('Book1', 5000, 2000)]

        # Setup query chain mocks
        mock_query = Mock()
        mock_query.group_by.return_value.all.return_value = mock_status

        mock_level_query = Mock()
        mock_level_query.group_by.return_value.all.return_value = mock_level

        mock_user_query = Mock()
        mock_user_query.join.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value = mock_users

        mock_book_query = Mock()
        mock_book_query.order_by.return_value.limit.return_value.all.return_value = mock_books

        mock_db.session.query.side_effect = [mock_query, mock_level_query, mock_user_query, mock_book_query]

        result = WordManagementService.get_detailed_statistics()

        assert result['status_stats'] == mock_status
        assert result['level_stats'] == mock_level
        assert result['top_users'] == mock_users
        assert result['book_stats'] == mock_books

    @patch('app.admin.services.word_management_service.logger')
    @patch('app.admin.services.word_management_service.db')
    def test_get_detailed_statistics_error(self, mock_db, mock_logger):
        """Test error handling in get_detailed_statistics"""
        mock_db.session.query.side_effect = Exception("Query failed")

        result = WordManagementService.get_detailed_statistics()

        assert 'error' in result
        mock_logger.error.assert_called_once()


class TestBulkUpdateWordStatus:
    """Tests for bulk_update_word_status method"""

    @patch('app.admin.services.word_management_service.db')
    @patch('app.admin.services.word_management_service.User')
    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_bulk_update_success(self, mock_words, mock_user, mock_db):
        """Test successful bulk status update"""
        # Mock word lookup
        mock_word = Mock()
        mock_word.id = 1
        mock_words.query.filter_by.return_value.first.return_value = mock_word

        # Mock user
        mock_user_obj = Mock()
        mock_user_obj.set_word_status = Mock()
        mock_user.query.get.return_value = mock_user_obj

        success, updated, total, error = WordManagementService.bulk_update_word_status(
            words=['test', 'word'],
            status='learning',
            user_id=1
        )

        assert success is True
        assert updated == 2
        assert total == 2
        assert error is None
        mock_db.session.commit.assert_called_once()

    @patch('app.admin.services.word_management_service.User')
    def test_bulk_update_empty_words(self, mock_user):
        """Test bulk update with empty words list"""
        success, updated, total, error = WordManagementService.bulk_update_word_status(
            words=[],
            status='learning'
        )

        assert success is False
        assert updated == 0
        assert total == 0
        assert 'Требуются words и status' in error

    @patch('app.admin.services.word_management_service.User')
    def test_bulk_update_no_status(self, mock_user):
        """Test bulk update without status"""
        success, updated, total, error = WordManagementService.bulk_update_word_status(
            words=['test'],
            status=None
        )

        assert success is False
        assert 'Требуются words и status' in error

    @patch('app.admin.services.word_management_service.logger')
    @patch('app.admin.services.word_management_service.db')
    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_bulk_update_error_rollback(self, mock_words, mock_db, mock_logger):
        """Test bulk update error handling and rollback"""
        mock_words.query.filter_by.side_effect = Exception("Database error")

        success, updated, total, error = WordManagementService.bulk_update_word_status(
            words=['test'],
            status='learning',
            user_id=1
        )

        assert success is False
        assert updated == 0
        assert error == "Database error"
        mock_db.session.rollback.assert_called_once()
        mock_logger.error.assert_called_once()

    @patch('app.admin.services.word_management_service.db')
    @patch('app.admin.services.word_management_service.User')
    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_bulk_update_all_active_users(self, mock_words, mock_user, mock_db):
        """Test bulk update for all active users"""
        # Mock active users
        mock_user1 = Mock()
        mock_user1.id = 1
        mock_user1.set_word_status = Mock()

        mock_user2 = Mock()
        mock_user2.id = 2
        mock_user2.set_word_status = Mock()

        mock_user.query.filter_by.return_value.all.return_value = [mock_user1, mock_user2]
        mock_user.query.get.side_effect = [mock_user1, mock_user2]

        # Mock word
        mock_word = Mock()
        mock_word.id = 1
        mock_words.query.filter_by.return_value.first.return_value = mock_word

        success, updated, total, error = WordManagementService.bulk_update_word_status(
            words=['test'],
            status='learning',
            user_id=None  # All active users
        )

        assert success is True
        assert updated == 2  # 1 word × 2 users
        assert total == 2


class TestGetWordsForExport:
    """Tests for get_words_for_export method"""

    @patch('app.admin.services.word_management_service.db')
    def test_export_all_words(self, mock_db):
        """Test export all words without filters"""
        mock_word = ('test', 'тест', 'A1')
        mock_query = Mock()
        mock_query.all.return_value = [mock_word]
        mock_db.session.query.return_value = mock_query

        result = WordManagementService.get_words_for_export()

        assert len(result) == 1
        assert result[0] == mock_word

    @patch('app.admin.services.word_management_service.db')
    def test_export_by_status_and_user(self, mock_db):
        """Test export with status and user filter"""
        mock_word = ('test', 'тест', 'A1', 'learning')
        mock_query = Mock()
        mock_query.join.return_value.filter.return_value.all.return_value = [mock_word]
        mock_db.session.query.return_value = mock_query

        result = WordManagementService.get_words_for_export(status='learning', user_id=1)

        assert len(result) == 1

    @patch('app.admin.services.word_management_service.db')
    def test_export_by_status_only(self, mock_db):
        """Test export with status filter only"""
        mock_word = ('test', 'тест', 'A1', 'mastered')
        mock_query = Mock()
        mock_query.join.return_value.filter.return_value.distinct.return_value.all.return_value = [mock_word]
        mock_db.session.query.return_value = mock_query

        result = WordManagementService.get_words_for_export(status='mastered')

        assert len(result) == 1

    @patch('app.admin.services.word_management_service.logger')
    @patch('app.admin.services.word_management_service.db')
    def test_export_error(self, mock_db, mock_logger):
        """Test export error handling"""
        mock_db.session.query.side_effect = Exception("Query error")

        result = WordManagementService.get_words_for_export()

        assert result == []
        mock_logger.error.assert_called_once()


class TestParseImportFile:
    """Tests for parse_import_file method"""

    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_parse_valid_file(self, mock_words):
        """Test parsing valid import file"""
        content = "test;тест;Test sentence;Тестовое предложение;A1\nhello;привет;Hello world;Привет мир;A2"

        # First word exists
        mock_word1 = Mock()
        # Second word doesn't exist
        mock_words.query.filter_by.return_value.first.side_effect = [mock_word1, None]

        existing, missing, errors = WordManagementService.parse_import_file(content)

        assert len(existing) == 1
        assert len(missing) == 1
        assert len(errors) == 0
        assert existing[0]['english_word'] == 'test'
        assert missing[0]['english_word'] == 'hello'

    def test_parse_invalid_format(self):
        """Test parsing file with invalid format"""
        content = "invalid line without semicolons"

        existing, missing, errors = WordManagementService.parse_import_file(content)

        assert len(existing) == 0
        assert len(missing) == 0
        assert len(errors) == 1
        assert 'неверный формат' in errors[0]['error']

    def test_parse_empty_file(self):
        """Test parsing empty file"""
        content = ""

        existing, missing, errors = WordManagementService.parse_import_file(content)

        assert len(existing) == 0
        assert len(missing) == 0
        assert len(errors) == 0

    def test_parse_with_comments(self):
        """Test parsing file with comments"""
        content = "# This is a comment\ntest;тест;Test sentence;Тестовое предложение;A1"

        with patch('app.admin.services.word_management_service.CollectionWords.query') as mock_query:
            mock_query.filter_by.return_value.first.return_value = Mock()

            existing, missing, errors = WordManagementService.parse_import_file(content)

            assert len(existing) == 1
            assert len(errors) == 0

    def test_parse_with_blank_lines(self):
        """Test parsing file with blank lines"""
        content = "test;тест;Test sentence;Тестовое предложение;A1\n\n\nhello;привет;Hello;Привет;A1"

        with patch('app.admin.services.word_management_service.CollectionWords.query') as mock_query:
            mock_query.filter_by.return_value.first.return_value = None

            existing, missing, errors = WordManagementService.parse_import_file(content)

            assert len(missing) == 2
            assert len(errors) == 0


class TestImportTranslations:
    """Tests for import_translations method"""

    @patch('app.admin.services.word_management_service.logger')
    @patch('app.admin.services.word_management_service.db')
    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_import_update_existing(self, mock_words, mock_db, mock_logger):
        """Test updating existing words"""
        existing_words = [
            {
                'english_word': 'test',
                'russian_translate': 'тест',
                'english_sentence': 'Test sentence',
                'russian_sentence': 'Тестовое предложение',
                'level': 'A1',
                'line_num': 1
            }
        ]

        mock_word = Mock()
        mock_words.query.filter_by.return_value.first.return_value = mock_word

        updated, added = WordManagementService.import_translations(
            existing_words=existing_words,
            missing_words=[],
            words_to_add=[]
        )

        assert updated == 1
        assert added == 0
        assert mock_word.russian_word == 'тест'
        mock_db.session.commit.assert_called_once()

    @patch('app.admin.services.word_management_service.logger')
    @patch('app.admin.services.word_management_service.db')
    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_import_add_new_words(self, mock_words, mock_db, mock_logger):
        """Test adding new words"""
        missing_words = [
            {
                'english_word': 'new',
                'russian_translate': 'новый',
                'english_sentence': 'New word',
                'russian_sentence': 'Новое слово',
                'level': 'B1',
                'line_num': 1
            }
        ]

        mock_words.query.filter_by.return_value.first.return_value = None

        updated, added = WordManagementService.import_translations(
            existing_words=[],
            missing_words=missing_words,
            words_to_add=['1']
        )

        assert updated == 0
        assert added == 1
        mock_db.session.add.assert_called_once()
        mock_db.session.commit.assert_called_once()

    @patch('app.admin.services.word_management_service.logger')
    @patch('app.admin.services.word_management_service.db')
    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_import_mixed_update_and_add(self, mock_words, mock_db, mock_logger):
        """Test both updating existing and adding new words"""
        existing_words = [{'english_word': 'test', 'russian_translate': 'тест',
                          'english_sentence': 'Test', 'russian_sentence': 'Тест',
                          'level': 'A1', 'line_num': 1}]
        missing_words = [{'english_word': 'new', 'russian_translate': 'новый',
                         'english_sentence': 'New', 'russian_sentence': 'Новый',
                         'level': 'A1', 'line_num': 2}]

        mock_word = Mock()
        mock_words.query.filter_by.return_value.first.return_value = mock_word

        updated, added = WordManagementService.import_translations(
            existing_words=existing_words,
            missing_words=missing_words,
            words_to_add=['2']
        )

        assert updated == 1
        assert added == 1

    @patch('app.admin.services.word_management_service.logger')
    @patch('app.admin.services.word_management_service.db')
    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_import_error_rollback(self, mock_words, mock_db, mock_logger):
        """Test error handling and rollback during import"""
        existing_words = [{'english_word': 'test', 'russian_translate': 'тест',
                          'english_sentence': 'Test', 'russian_sentence': 'Тест',
                          'level': 'A1', 'line_num': 1}]

        mock_words.query.filter_by.side_effect = Exception("Database error")

        with pytest.raises(Exception):
            WordManagementService.import_translations(
                existing_words=existing_words,
                missing_words=[],
                words_to_add=[]
            )

        mock_db.session.rollback.assert_called_once()
        mock_logger.error.assert_called_once()
