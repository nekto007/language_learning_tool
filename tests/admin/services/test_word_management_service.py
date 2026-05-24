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
    """Tests for bulk_update_word_status method.

    Service contract (post-Task-11):
      - flush only (caller commits with the audit-log entry);
      - bulk word lookup via `CollectionWords.query.filter(in_(...))`;
      - active-user list via `db.session.query(User.id).filter(...).all()`;
      - per-user fetch via `db.session.get(User, uid)`.
    """

    @patch('app.admin.services.word_management_service.db')
    @patch('app.admin.services.word_management_service.User')
    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_bulk_update_success(self, mock_words, mock_user, mock_db):
        """Successful path with explicit user_id."""
        word_a = Mock(id=1)
        word_b = Mock(id=2)
        mock_words.query.filter.return_value.all.return_value = [word_a, word_b]

        mock_user_obj = Mock()
        mock_user_obj.set_word_status = Mock()
        mock_db.session.get.return_value = mock_user_obj

        success, updated, total, error = WordManagementService.bulk_update_word_status(
            words=['test', 'word'],
            status='learning',
            user_id=1
        )

        assert success is True
        assert updated == 2  # 2 words × 1 user
        assert total == 2
        assert error is None
        mock_db.session.flush.assert_called_once()
        # Service must NOT commit — caller commits with audit log entry.
        assert mock_db.session.commit.call_count == 0

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
        mock_words.query.filter.side_effect = Exception("Database error")

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
        """Test bulk update for all active users (user_id=None branch)."""
        # db.session.query(User.id).filter(User.active.is_(True)).all() → [(1,), (2,)]
        mock_db.session.query.return_value.filter.return_value.all.return_value = [(1,), (2,)]

        mock_user1 = Mock()
        mock_user1.set_word_status = Mock()
        mock_user2 = Mock()
        mock_user2.set_word_status = Mock()
        mock_db.session.get.side_effect = [mock_user1, mock_user2]

        word = Mock(id=1)
        mock_words.query.filter.return_value.all.return_value = [word]

        success, updated, total, error = WordManagementService.bulk_update_word_status(
            words=['test'],
            status='learning',
            user_id=None
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

    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_parse_with_comments(self, mock_words):
        """Test parsing file with comments"""
        content = "# This is a comment\ntest;тест;Test sentence;Тестовое предложение;A1"

        mock_words.query.filter_by.return_value.first.return_value = Mock()

        existing, missing, errors = WordManagementService.parse_import_file(content)

        assert len(existing) == 1
        assert len(errors) == 0

    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_parse_with_blank_lines(self, mock_words):
        """Test parsing file with blank lines"""
        content = "test;тест;Test sentence;Тестовое предложение;A1\n\n\nhello;привет;Hello;Привет;A1"

        mock_words.query.filter_by.return_value.first.return_value = None

        existing, missing, errors = WordManagementService.parse_import_file(content)

        assert len(missing) == 2
        assert len(errors) == 0

    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_parse_enriched_file(self, mock_words):
        """Test parsing valid import file with vocabulary enrichment fields."""
        content = (
            "pen;ручка, перо;I write with a pen.;Я пишу ручкой.;A1;"
            "stationery;/pen/;writing tool, ballpoint;eraser;high;"
            "from Latin penna, feather"
        )
        mock_words.query.filter_by.return_value.first.return_value = Mock()

        existing, missing, errors = WordManagementService.parse_import_file(content)

        assert len(existing) == 1
        assert len(missing) == 0
        assert len(errors) == 0
        assert existing[0]['topic'] == 'stationery'
        assert existing[0]['ipa_transcription'] == 'pen'
        assert existing[0]['synonyms'] == ['writing tool', 'ballpoint']
        assert existing[0]['antonyms'] == ['eraser']
        assert existing[0]['frequency_band'] == 1
        assert existing[0]['etymology'] == 'from Latin penna, feather'
        assert existing[0]['has_enrichment'] is True

    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_parse_bilingual_topic_enriched_file(self, mock_words):
        """Test parsing 12-column import with topic_ru/topic_en normalization."""
        content = (
            "pen;ручка, перо;I wrote the note with a pen.;Я написал записку ручкой.;A1;"
            "Канцелярия;Stationery;pen;[marker, ballpoint];[pencil];1;"
            "from Old French penne, from Latin penna meaning feather"
        )
        mock_words.query.filter_by.return_value.first.return_value = Mock()

        existing, missing, errors = WordManagementService.parse_import_file(content)

        assert len(existing) == 1
        assert len(missing) == 0
        assert errors == []
        assert existing[0]['topic'] == 'Канцелярия (Stationery)'
        assert existing[0]['topic_ru'] == 'Канцелярия'
        assert existing[0]['topic_en'] == 'Stationery'
        assert existing[0]['ipa_transcription'] == 'pen'
        assert existing[0]['synonyms'] == ['marker', 'ballpoint']
        assert existing[0]['antonyms'] == ['pencil']
        assert existing[0]['frequency_band'] == 1
        assert existing[0]['has_enrichment'] is True

    def test_parse_invalid_frequency_band(self):
        """Invalid enrichment frequency band should be reported as parse error."""
        content = (
            "pen;ручка;I write with a pen.;Я пишу ручкой.;A1;"
            "stationery;pen;writing tool;eraser;very-high;origin"
        )

        existing, missing, errors = WordManagementService.parse_import_file(content)

        assert existing == []
        assert missing == []
        assert len(errors) == 1
        assert 'frequency_band' in errors[0]['error']


class TestTopicResolutionPreview:
    """Tests for topic resolution preview data."""

    @patch('app.admin.services.word_management_service.Topic')
    def test_prepare_topic_resolution_preview_marks_existing_and_candidates(self, mock_topic):
        existing_topic = Mock()
        existing_topic.id = 1
        existing_topic.name = 'Действия (Actions/Verbs)'

        mock_topic.query.order_by.return_value.all.return_value = [existing_topic]

        existing_words = [
            {'topic': 'Действия (Actions/Verbs)'},
            {'topic': 'Действия (Actions)'},
        ]
        missing_words = []

        result = WordManagementService.prepare_topic_resolution_preview(
            existing_words,
            missing_words,
        )

        assert existing_words[0]['topic_status'] == 'existing'
        assert existing_words[0]['topic_existing_id'] == 1
        assert existing_words[1]['topic_status'] == 'needs_resolution'
        assert len(result['topic_candidates']) == 1
        assert result['topic_candidates'][0]['default_action'] == 'map'
        assert result['topic_candidates'][0]['suggestion']['id'] == 1
        assert result['existing_topics'] == [
            {'id': 1, 'name': 'Действия (Actions/Verbs)'}
        ]

    @patch('app.admin.services.word_management_service.Topic')
    def test_prepare_topic_resolution_preview_suggests_broader_transport_topic(self, mock_topic):
        """Short import topic aliases should map to broader existing taxonomy topics."""
        existing_topic = Mock()
        existing_topic.id = 2
        existing_topic.name = 'Транспорт и путешествия (Transportation & Travel)'

        mock_topic.query.order_by.return_value.all.return_value = [existing_topic]

        existing_words = [
            {'topic': 'транспорт (transport)'},
            {'topic': 'путешествия (travel)'},
        ]

        result = WordManagementService.prepare_topic_resolution_preview(
            existing_words,
            [],
        )

        assert len(result['topic_candidates']) == 2
        assert all(
            candidate['default_action'] == 'map'
            for candidate in result['topic_candidates']
        )
        assert all(
            candidate['suggestion']['id'] == 2
            for candidate in result['topic_candidates']
        )

    @patch('app.admin.services.word_management_service.Topic')
    def test_prepare_topic_resolution_preview_suggests_animal_and_health_topics(self, mock_topic):
        """Mixed RU/EN import labels should map through taxonomy aliases."""
        animals_topic = Mock()
        animals_topic.id = 3
        animals_topic.name = 'Животные (Animals)'

        health_topic = Mock()
        health_topic.id = 4
        health_topic.name = 'Тело и здоровье (Body & Health)'

        mock_topic.query.order_by.return_value.all.return_value = [
            animals_topic,
            health_topic,
        ]

        existing_words = [
            {'topic': 'животные (pet care)'},
            {'topic': 'здоровье (self-control)'},
        ]

        result = WordManagementService.prepare_topic_resolution_preview(
            existing_words,
            [],
        )

        candidates_by_topic = {
            candidate['topic']: candidate
            for candidate in result['topic_candidates']
        }

        assert candidates_by_topic['животные (pet care)']['default_action'] == 'map'
        assert candidates_by_topic['животные (pet care)']['suggestion']['id'] == 3
        assert candidates_by_topic['здоровье (self-control)']['default_action'] == 'map'
        assert candidates_by_topic['здоровье (self-control)']['suggestion']['id'] == 4

    @patch('app.admin.services.word_management_service.Topic')
    def test_prepare_topic_resolution_preview_suggests_work_and_action_topics(self, mock_topic):
        """Career/work and noisy action labels should map to existing topics."""
        work_topic = Mock()
        work_topic.id = 5
        work_topic.name = 'Работа (Work)'

        actions_topic = Mock()
        actions_topic.id = 6
        actions_topic.name = 'Действия (Actions/Verbs)'

        mock_topic.query.order_by.return_value.all.return_value = [
            work_topic,
            actions_topic,
        ]

        existing_words = [
            {'topic': 'работа (career)'},
            {'topic': 'действия (effort)'},
            {'topic': 'действия (permission)'},
        ]

        result = WordManagementService.prepare_topic_resolution_preview(
            existing_words,
            [],
        )

        candidates_by_topic = {
            candidate['topic']: candidate
            for candidate in result['topic_candidates']
        }

        assert candidates_by_topic['работа (career)']['default_action'] == 'map'
        assert candidates_by_topic['работа (career)']['suggestion']['id'] == 5
        assert candidates_by_topic['действия (effort)']['default_action'] == 'map'
        assert candidates_by_topic['действия (effort)']['suggestion']['id'] == 6
        assert candidates_by_topic['действия (permission)']['default_action'] == 'map'
        assert candidates_by_topic['действия (permission)']['suggestion']['id'] == 6

    @patch('app.admin.services.word_management_service.Topic')
    def test_prepare_topic_resolution_preview_suggests_emotions_topic(self, mock_topic):
        """Emotional-state labels should map to emotions/personality topic."""
        emotions_topic = Mock()
        emotions_topic.id = 7
        emotions_topic.name = 'Эмоции и личность (Emotions & Personality)'

        mock_topic.query.order_by.return_value.all.return_value = [emotions_topic]

        existing_words = [
            {'topic': 'эмоции (emotional state)'},
        ]

        result = WordManagementService.prepare_topic_resolution_preview(
            existing_words,
            [],
        )

        assert len(result['topic_candidates']) == 1
        assert result['topic_candidates'][0]['default_action'] == 'map'
        assert result['topic_candidates'][0]['suggestion']['id'] == 7


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

    @patch('app.admin.services.word_management_service.Topic')
    @patch('app.admin.services.word_management_service.logger')
    @patch('app.admin.services.word_management_service.db')
    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_import_update_existing_with_enrichment(self, mock_words, mock_db, mock_logger, mock_topic):
        """Test updating existing words with enrichment fields."""
        existing_words = [
            {
                'english_word': 'pen',
                'russian_translate': 'ручка, перо',
                'english_sentence': 'I write with a pen.',
                'russian_sentence': 'Я пишу ручкой.',
                'level': 'A1',
                'line_num': 1,
                'topic': '',
                'ipa_transcription': 'pen',
                'synonyms': ['writing tool', 'ballpoint'],
                'antonyms': ['eraser'],
                'frequency_band': 1,
                'etymology': 'from Latin penna, feather',
                'has_enrichment': True,
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
        assert mock_word.ipa_transcription == 'pen'
        assert mock_word.synonyms == ['writing tool', 'ballpoint']
        assert mock_word.antonyms == ['eraser']
        assert mock_word.frequency_band == 1
        assert mock_word.etymology == 'from Latin penna, feather'

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

    @patch('app.admin.services.word_management_service.logger')
    @patch('app.admin.services.word_management_service.db')
    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_import_duplicate_word_raises_value_error_duplicate_entry(self, mock_words, mock_db, mock_logger):
        """IntegrityError on duplicate english_word is re-raised as ValueError('duplicate_entry')."""
        from sqlalchemy.exc import IntegrityError as SAIntegrityError

        mock_words.query.filter_by.return_value.first.return_value = None
        mock_db.session.add.return_value = None
        mock_db.session.commit.side_effect = SAIntegrityError(
            statement='INSERT', params={}, orig=Exception('unique constraint')
        )
        mock_db.session.rollback.return_value = None

        missing_words = [{'english_word': 'duplicate', 'russian_translate': 'дубликат',
                          'english_sentence': 'Duplicate.', 'russian_sentence': 'Дубликат.',
                          'level': 'A1', 'line_num': 1}]

        with pytest.raises(ValueError) as exc_info:
            WordManagementService.import_translations(
                existing_words=[],
                missing_words=missing_words,
                words_to_add=['1']
            )

        assert str(exc_info.value) == 'duplicate_entry'
        mock_db.session.rollback.assert_called_once()
        mock_logger.warning.assert_called_once()

    @patch('app.admin.services.word_management_service.logger')
    @patch('app.admin.services.word_management_service.db')
    @patch('app.admin.services.word_management_service.CollectionWords')
    def test_import_phrasal_verb_duplicate_raises_value_error(self, mock_words, mock_db, mock_logger):
        """IntegrityError on duplicate phrasal verb is re-raised as ValueError('duplicate_entry')."""
        from sqlalchemy.exc import IntegrityError as SAIntegrityError

        mock_db.session.add.return_value = None
        mock_db.session.commit.side_effect = SAIntegrityError(
            statement='INSERT', params={}, orig=Exception('unique constraint')
        )
        mock_db.session.rollback.return_value = None

        new_verbs = [{'phrasal_verb': 'get up', 'russian_translate': 'вставать',
                      'sentence': 'I get up early.', 'using': 'intransitive'}]

        with pytest.raises(ValueError) as exc_info:
            WordManagementService.import_phrasal_verbs(
                new_verbs=new_verbs,
                existing_verbs=[]
            )

        assert str(exc_info.value) == 'duplicate_entry'
        mock_db.session.rollback.assert_called_once()
        mock_logger.warning.assert_called_once()
