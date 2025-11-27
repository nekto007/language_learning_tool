"""
Comprehensive tests for CurriculumImportService
Tests for curriculum import, processing, and database operations
"""
import pytest
from datetime import datetime, timedelta, UTC
from unittest.mock import patch, MagicMock, Mock

from app.admin.services.curriculum_import_service import CurriculumImportService


class TestGetLevelName:
    """Tests for get_level_name method"""

    def test_get_level_name_a0(self):
        """Test level name for A0"""
        assert CurriculumImportService.get_level_name('A0') == 'Pre-Beginner'

    def test_get_level_name_a1(self):
        """Test level name for A1"""
        assert CurriculumImportService.get_level_name('A1') == 'Beginner'

    def test_get_level_name_a2(self):
        """Test level name for A2"""
        assert CurriculumImportService.get_level_name('A2') == 'Elementary'

    def test_get_level_name_b1(self):
        """Test level name for B1"""
        assert CurriculumImportService.get_level_name('B1') == 'Intermediate'

    def test_get_level_name_b2(self):
        """Test level name for B2"""
        assert CurriculumImportService.get_level_name('B2') == 'Upper Intermediate'

    def test_get_level_name_c1(self):
        """Test level name for C1"""
        assert CurriculumImportService.get_level_name('C1') == 'Advanced'

    def test_get_level_name_c2(self):
        """Test level name for C2"""
        assert CurriculumImportService.get_level_name('C2') == 'Proficiency'

    def test_get_level_name_unknown(self):
        """Test level name for unknown level"""
        assert CurriculumImportService.get_level_name('X1') == 'Level X1'


class TestGetLevelOrder:
    """Tests for get_level_order method"""

    def test_get_level_order_a0(self):
        """Test order for A0"""
        assert CurriculumImportService.get_level_order('A0') == 0

    def test_get_level_order_a1(self):
        """Test order for A1"""
        assert CurriculumImportService.get_level_order('A1') == 1

    def test_get_level_order_a2(self):
        """Test order for A2"""
        assert CurriculumImportService.get_level_order('A2') == 2

    def test_get_level_order_b1(self):
        """Test order for B1"""
        assert CurriculumImportService.get_level_order('B1') == 3

    def test_get_level_order_b2(self):
        """Test order for B2"""
        assert CurriculumImportService.get_level_order('B2') == 4

    def test_get_level_order_c1(self):
        """Test order for C1"""
        assert CurriculumImportService.get_level_order('C1') == 5

    def test_get_level_order_c2(self):
        """Test order for C2"""
        assert CurriculumImportService.get_level_order('C2') == 6

    def test_get_level_order_unknown(self):
        """Test order for unknown level"""
        assert CurriculumImportService.get_level_order('X1') == 99


class TestProcessVocabulary:
    """Tests for process_vocabulary method"""

    @patch('app.admin.services.curriculum_import_service.db')
    @patch('app.admin.services.curriculum_import_service.CollectionWordLink')
    @patch('app.admin.services.curriculum_import_service.CollectionWords')
    def test_process_vocabulary_new_word(self, mock_words, mock_links, mock_db):
        """Test processing vocabulary with new word"""
        # Setup
        mock_collection = MagicMock()
        mock_collection.id = 1

        mock_words.query.filter_by.return_value.first.return_value = None
        mock_links.query.filter_by.return_value.first.return_value = None

        vocabulary_data = [
            {'word': 'test', 'translation': 'тест', 'frequency_rank': 100}
        ]

        # Execute
        CurriculumImportService.process_vocabulary(vocabulary_data, mock_collection, 'A1')

        # Assert
        mock_db.session.add.assert_called()
        mock_db.session.flush.assert_called()

    @patch('app.admin.services.curriculum_import_service.db')
    @patch('app.admin.services.curriculum_import_service.CollectionWordLink')
    @patch('app.admin.services.curriculum_import_service.CollectionWords')
    def test_process_vocabulary_existing_word(self, mock_words, mock_links, mock_db):
        """Test processing vocabulary with existing word"""
        # Setup
        mock_collection = MagicMock()
        mock_collection.id = 1

        mock_existing_word = MagicMock()
        mock_existing_word.id = 10
        mock_words.query.filter_by.return_value.first.return_value = mock_existing_word
        mock_links.query.filter_by.return_value.first.return_value = None

        vocabulary_data = [
            {'word': 'test', 'translation': 'новый перевод', 'frequency_rank': 50}
        ]

        # Execute
        CurriculumImportService.process_vocabulary(vocabulary_data, mock_collection, 'A1')

        # Assert - word updated
        assert mock_existing_word.russian_word == 'новый перевод'
        assert mock_existing_word.frequency_rank == 50


class TestProcessGrammar:
    """Tests for process_grammar method"""

    def test_process_grammar_fill_in_blank(self):
        """Test processing fill_in_blank exercise"""
        grammar_data = {
            'rule': 'Present Simple',
            'description': 'Use present simple for facts',
            'examples': ['I eat', 'He eats'],
            'exercises': [
                {
                    'type': 'fill_in_blank',
                    'prompt': 'Complete the sentence',
                    'correct_answer': ['is'],
                    'alternative_answers': ['are'],
                    'explanation': 'Use is for singular'
                }
            ]
        }

        result = CurriculumImportService.process_grammar(grammar_data)

        assert result['rule'] == 'Present Simple'
        assert result['description'] == 'Use present simple for facts'
        assert len(result['examples']) == 2
        assert len(result['exercises']) == 1
        assert result['exercises'][0]['type'] == 'fill_in_blank'
        assert result['exercises'][0]['answer'] == ['is']
        assert result['exercises'][0]['alternative_answers'] == ['are']

    def test_process_grammar_multiple_choice(self):
        """Test processing multiple_choice exercise"""
        grammar_data = {
            'rule': 'Test',
            'exercises': [
                {
                    'type': 'multiple_choice',
                    'question': 'Choose correct',
                    'options': ['a', 'b', 'c'],
                    'correct_index': 1,
                    'explanation': 'B is correct'
                }
            ]
        }

        result = CurriculumImportService.process_grammar(grammar_data)

        assert result['exercises'][0]['type'] == 'multiple_choice'
        assert result['exercises'][0]['question'] == 'Choose correct'
        assert result['exercises'][0]['options'] == ['a', 'b', 'c']
        assert result['exercises'][0]['answer'] == 1

    def test_process_grammar_true_false(self):
        """Test processing true_false exercise"""
        grammar_data = {
            'exercises': [
                {
                    'type': 'true_false',
                    'question': 'Is this true?',
                    'correct_answer': True
                }
            ]
        }

        result = CurriculumImportService.process_grammar(grammar_data)

        assert result['exercises'][0]['type'] == 'true_false'
        assert result['exercises'][0]['answer'] is True

    def test_process_grammar_match(self):
        """Test processing match exercise"""
        grammar_data = {
            'exercises': [
                {
                    'type': 'match',
                    'pairs': [['word1', 'trans1'], ['word2', 'trans2']]
                }
            ]
        }

        result = CurriculumImportService.process_grammar(grammar_data)

        assert result['exercises'][0]['type'] == 'match'
        assert len(result['exercises'][0]['pairs']) == 2

    def test_process_grammar_reorder(self):
        """Test processing reorder exercise"""
        grammar_data = {
            'exercises': [
                {
                    'type': 'reorder',
                    'words': ['word3', 'word1', 'word2'],
                    'correct_answer': 'word1 word2 word3'
                }
            ]
        }

        result = CurriculumImportService.process_grammar(grammar_data)

        assert result['exercises'][0]['type'] == 'reorder'
        assert result['exercises'][0]['words'] == ['word3', 'word1', 'word2']
        assert result['exercises'][0]['answer'] == 'word1 word2 word3'

    def test_process_grammar_translation(self):
        """Test processing translation exercise"""
        grammar_data = {
            'exercises': [
                {
                    'type': 'translation',
                    'prompt': 'Translate',
                    'correct_answer': 'correct translation',
                    'alternative_answers': ['alt 1', 'alt 2']
                }
            ]
        }

        result = CurriculumImportService.process_grammar(grammar_data)

        assert result['exercises'][0]['type'] == 'translation'
        assert result['exercises'][0]['answer'] == 'correct translation'
        assert len(result['exercises'][0]['alternative_answers']) == 2

    def test_process_grammar_empty_exercises(self):
        """Test processing grammar with no exercises"""
        grammar_data = {
            'rule': 'Test Rule',
            'description': 'Test Desc'
        }

        result = CurriculumImportService.process_grammar(grammar_data)

        assert result['rule'] == 'Test Rule'
        assert result['description'] == 'Test Desc'
        assert result['exercises'] == []


class TestImportCurriculumData:
    """Tests for import_curriculum_data method"""

    @patch('app.admin.services.curriculum_import_service.current_user')
    @patch('app.admin.services.curriculum_import_service.db')
    @patch('app.admin.services.curriculum_import_service.Lessons')
    @patch('app.admin.services.curriculum_import_service.Module')
    @patch('app.admin.services.curriculum_import_service.CEFRLevel')
    def test_import_curriculum_data_missing_level(self, mock_level, mock_module, mock_lessons, mock_db, mock_user):
        """Test import fails with missing level"""
        data = {'module': 1}  # Missing 'level'

        with pytest.raises(ValueError) as exc_info:
            CurriculumImportService.import_curriculum_data(data)

        assert "обязательные поля" in str(exc_info.value)

    @patch('app.admin.services.curriculum_import_service.current_user')
    @patch('app.admin.services.curriculum_import_service.db')
    @patch('app.admin.services.curriculum_import_service.CollectionWordLink')
    @patch('app.admin.services.curriculum_import_service.Collection')
    @patch('app.admin.services.curriculum_import_service.Lessons')
    @patch('app.admin.services.curriculum_import_service.Module')
    @patch('app.admin.services.curriculum_import_service.CEFRLevel')
    def test_import_curriculum_data_creates_new_level(self, mock_level_cls, mock_module_cls, mock_lessons_cls,
                                                       mock_collection_cls, mock_link_cls, mock_db, mock_user):
        """Test import creates new level"""
        # Setup
        mock_user.id = 1
        mock_level_cls.query.filter_by.return_value.first.return_value = None
        mock_module_cls.query.filter_by.return_value.first.return_value = None

        # Create mock instances
        mock_level = MagicMock()
        mock_level.id = 1
        mock_level.code = 'A1'

        mock_module = MagicMock()
        mock_module.id = 10
        mock_module.number = 1
        mock_module.title = 'Test Module'

        mock_lesson = MagicMock()
        mock_lesson.id = 100

        # Set return values
        mock_level_cls.return_value = mock_level
        mock_module_cls.return_value = mock_module
        mock_lessons_cls.query.filter_by.return_value.first.return_value = None
        mock_lessons_cls.return_value = mock_lesson
        mock_lessons_cls.query.filter_by.return_value.order_by.return_value.first.return_value = mock_lesson

        data = {
            'level': 'A1',
            'module': 1,
            'title': 'Test Module',
            'description': 'Test',
            'lessons': [
                {
                    'lesson_number': 1,
                    'lesson_type': 'text',
                    'title': 'Intro',
                    'content': {'text': 'Hello'}
                }
            ]
        }

        # Execute
        result = CurriculumImportService.import_curriculum_data(data)

        # Assert
        assert result['level_id'] == 1
        assert result['module_id'] == 10
        assert result['lesson_id'] == 100
        mock_db.session.add.assert_called()
        mock_db.session.commit.assert_called_once()

    @patch('app.admin.services.curriculum_import_service.current_user')
    @patch('app.admin.services.curriculum_import_service.db')
    @patch('app.admin.services.curriculum_import_service.CollectionWordLink')
    @patch('app.admin.services.curriculum_import_service.Collection')
    @patch('app.admin.services.curriculum_import_service.CollectionWords')
    @patch('app.admin.services.curriculum_import_service.Lessons')
    @patch('app.admin.services.curriculum_import_service.Module')
    @patch('app.admin.services.curriculum_import_service.CEFRLevel')
    def test_import_curriculum_data_vocabulary_lesson(self, mock_level_cls, mock_module_cls, mock_lessons_cls,
                                                       mock_words_cls, mock_collection_cls, mock_link_cls,
                                                       mock_db, mock_user):
        """Test import with vocabulary lesson"""
        # Setup
        mock_user.id = 1

        mock_level = MagicMock()
        mock_level.id = 1
        mock_level_cls.query.filter_by.return_value.first.return_value = mock_level

        mock_module = MagicMock()
        mock_module.id = 10
        mock_module.title = 'Module 1'
        mock_module_cls.query.filter_by.return_value.first.return_value = mock_module

        mock_lesson = MagicMock()
        mock_lesson.id = 100
        mock_lessons_cls.query.filter_by.return_value.first.return_value = None
        mock_lessons_cls.return_value = mock_lesson
        mock_lessons_cls.query.filter_by.return_value.order_by.return_value.first.return_value = mock_lesson

        mock_collection = MagicMock()
        mock_collection.id = 50
        mock_collection_cls.query.filter_by.return_value.first.return_value = None
        mock_collection_cls.return_value = mock_collection

        mock_words_cls.query.filter_by.return_value.first.return_value = None
        mock_link_cls.query.filter_by.return_value.first.return_value = None
        mock_link_cls.query.filter_by.return_value.delete.return_value = None

        data = {
            'level': 'A1',
            'module': 1,
            'title': 'Module 1',
            'lessons': [
                {
                    'lesson_number': 1,
                    'lesson_type': 'vocabulary',
                    'title': 'Vocab',
                    'words': [
                        {'word': 'hello', 'translation': 'привет', 'frequency_rank': 10}
                    ]
                }
            ]
        }

        # Execute
        result = CurriculumImportService.import_curriculum_data(data)

        # Assert
        assert result['level_id'] == 1
        mock_collection_cls.assert_called_once()


class TestGetWordStatusStatistics:
    """Tests for get_word_status_statistics method"""

    @patch('app.admin.services.curriculum_import_service.db')
    @patch('app.admin.services.curriculum_import_service.UserWord')
    def test_get_word_status_statistics_success(self, mock_user_word, mock_db):
        """Test successful statistics retrieval"""
        # Setup
        mock_stat = MagicMock()
        mock_stat.status = 'learning'
        mock_stat.count = 50
        mock_stat.users = 5

        mock_session = MagicMock()
        mock_session.query.return_value.group_by.return_value.all.return_value = [mock_stat]
        mock_db.session = mock_session

        mock_user_word.query.count.return_value = 100

        # Configure scalar returns
        mock_session.query.return_value.scalar.side_effect = [75, 10]

        # Execute
        result = CurriculumImportService.get_word_status_statistics()

        # Assert
        assert 'status_breakdown' in result
        assert 'totals' in result
        assert result['totals']['total_user_words'] == 100
        assert result['totals']['unique_words_tracked'] == 75
        assert result['totals']['users_with_words'] == 10
        assert len(result['status_breakdown']) == 1
        assert result['status_breakdown'][0]['status'] == 'learning'
        assert result['status_breakdown'][0]['percentage'] == 50.0

    @patch('app.admin.services.curriculum_import_service.db')
    @patch('app.admin.services.curriculum_import_service.UserWord')
    def test_get_word_status_statistics_error(self, mock_user_word, mock_db):
        """Test error handling in statistics"""
        mock_db.session.query.side_effect = Exception("DB Error")

        result = CurriculumImportService.get_word_status_statistics()

        assert 'error' in result
        assert 'DB Error' in result['error']


class TestGetRecentDbOperations:
    """Tests for get_recent_db_operations method"""

    @patch('app.admin.services.curriculum_import_service.User')
    @patch('app.admin.services.curriculum_import_service.Lessons')
    def test_get_recent_db_operations_success(self, mock_lessons, mock_user):
        """Test successful retrieval of recent operations"""
        # Setup mock lessons
        mock_lesson = MagicMock()
        mock_lesson.title = 'Test Lesson'
        mock_lesson.type = 'grammar'
        mock_lesson.created_at = datetime(2025, 11, 20, 10, 0, 0)

        mock_lessons.query.order_by.return_value.limit.return_value.all.return_value = [mock_lesson]

        # Setup mock users - configure User.created_at as a real attribute for datetime comparison
        mock_user_obj = MagicMock()
        mock_user_obj.username = 'testuser'
        mock_user_obj.created_at = datetime(2025, 11, 23, 15, 30, 0)

        # Mock User.created_at as a column to support >= comparison
        mock_created_at_col = MagicMock()
        mock_created_at_col.__ge__ = MagicMock(return_value=True)
        type(mock_user).created_at = mock_created_at_col

        mock_query = MagicMock()
        mock_query.order_by.return_value.limit.return_value.all.return_value = [mock_user_obj]
        mock_user.query.filter.return_value = mock_query

        # Execute
        result = CurriculumImportService.get_recent_db_operations()

        # Assert
        assert 'recent_lessons' in result
        assert 'recent_users' in result
        assert len(result['recent_lessons']) == 1
        assert result['recent_lessons'][0]['title'] == 'Test Lesson'
        assert result['recent_lessons'][0]['type'] == 'grammar'
        assert len(result['recent_users']) == 1
        assert result['recent_users'][0]['username'] == 'testuser'

    @patch('app.admin.services.curriculum_import_service.Lessons')
    def test_get_recent_db_operations_error(self, mock_lessons):
        """Test error handling"""
        mock_lessons.query.order_by.side_effect = Exception("Query failed")

        result = CurriculumImportService.get_recent_db_operations()

        assert 'error' in result
        assert 'Query failed' in result['error']


class TestTestDatabaseConnection:
    """Tests for test_database_connection method"""

    @patch('config.settings.DB_CONFIG', {'host': 'localhost'})
    @patch('app.repository.DatabaseRepository')
    def test_database_connection_success(self, mock_repo_cls):
        """Test successful database connection"""
        # Setup
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ('PostgreSQL 14.1',),
            (25,),
            ('50 MB',)
        ]

        mock_conn = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)

        mock_repo = MagicMock()
        mock_repo.get_connection.return_value = mock_conn
        mock_repo_cls.return_value = mock_repo

        # Execute
        result = CurriculumImportService.test_database_connection()

        # Assert
        assert result['status'] == 'success'
        assert 'PostgreSQL' in result['version']
        assert result['table_count'] == 25
        assert result['database_size'] == '50 MB'

    @patch('config.settings.DB_CONFIG', {'host': 'localhost'})
    @patch('app.repository.DatabaseRepository')
    def test_database_connection_error(self, mock_repo_cls):
        """Test database connection error"""
        mock_repo_cls.side_effect = Exception("Connection failed")

        result = CurriculumImportService.test_database_connection()

        assert result['status'] == 'error'
        assert 'Connection failed' in result['message']
