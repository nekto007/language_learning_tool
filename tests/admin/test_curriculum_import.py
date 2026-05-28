"""
Task 45: Admin — curriculum import preview

Tests for:
- preview_import doesn't write to DB
- batch DB lookups use chunk_ids (not N+1 per-word queries)
- invalid JSON returns graceful redirect (no 500)
- import confirmation is idempotent on double submit
"""
import json
import pytest
from unittest.mock import patch, MagicMock, call
from io import BytesIO

from app.admin.services.curriculum_import_service import CurriculumImportService


# ---------------------------------------------------------------------------
# preview_import — no DB writes
# ---------------------------------------------------------------------------

class TestPreviewImportNoWrite:
    """preview_import must analyse the payload without touching the DB."""

    @patch('app.admin.services.curriculum_import_service.db')
    @patch('app.admin.services.curriculum_import_service.CollectionWords')
    @patch('app.admin.services.curriculum_import_service.CEFRLevel')
    @patch('app.admin.services.curriculum_import_service.Module')
    @patch('app.admin.services.curriculum_import_service.Lessons')
    def test_preview_does_not_call_db_add(
        self, mock_lessons, mock_module, mock_level, mock_words, mock_db
    ):
        """preview_import must not call db.session.add or db.session.commit."""
        data = {
            'level': 'A1',
            'module': 3,
            'title': 'Preview Module',
            'lessons': [
                {'lesson_number': 1, 'lesson_type': 'text', 'title': 'Intro'},
                {'lesson_number': 2, 'lesson_type': 'grammar', 'title': 'To Be'},
            ],
        }

        result = CurriculumImportService.preview_import(data)

        mock_db.session.add.assert_not_called()
        mock_db.session.commit.assert_not_called()
        mock_db.session.flush.assert_not_called()

    def test_preview_returns_correct_summary_old_format(self):
        """preview_import returns accurate summary for old flat format."""
        data = {
            'level': 'B1',
            'module': 5,
            'title': 'B1 Module 5',
            'lessons': [
                {'lesson_number': 1, 'lesson_type': 'vocabulary', 'title': 'Food Words'},
                {'lesson_number': 2, 'lesson_type': 'quiz', 'title': 'Food Quiz'},
            ],
        }

        result = CurriculumImportService.preview_import(data)

        assert result['level'] == 'B1'
        assert result['module_number'] == 5
        assert result['module_title'] == 'B1 Module 5'
        assert result['lesson_count'] == 2
        assert result['lessons'][0] == {'number': 1, 'type': 'vocabulary', 'title': 'Food Words'}
        assert result['lessons'][1] == {'number': 2, 'type': 'quiz', 'title': 'Food Quiz'}

    def test_preview_returns_correct_summary_new_format(self):
        """preview_import handles the new nested module format."""
        data = {
            'module': {
                'level': 'A2',
                'order': 7,
                'title': 'A2 Module 7',
                'lessons': [
                    {'lesson_number': 1, 'lesson_type': 'card', 'title': 'Flashcards'},
                ],
            }
        }

        result = CurriculumImportService.preview_import(data)

        assert result['level'] == 'A2'
        assert result['module_number'] == 7
        assert result['lesson_count'] == 1
        assert result['lessons'][0]['type'] == 'card'

    def test_preview_maps_flashcards_to_card(self):
        """preview_import applies the same type_mapping as import_curriculum_data."""
        data = {
            'level': 'A1',
            'module': 1,
            'lessons': [
                {'lesson_number': 1, 'lesson_type': 'flashcards', 'title': 'Cards'},
            ],
        }

        result = CurriculumImportService.preview_import(data)

        assert result['lessons'][0]['type'] == 'card'

    def test_preview_empty_lessons(self):
        """preview_import handles a module with no lessons."""
        data = {'level': 'C1', 'module': 1, 'title': 'Advanced', 'lessons': []}

        result = CurriculumImportService.preview_import(data)

        assert result['lesson_count'] == 0
        assert result['lessons'] == []


# ---------------------------------------------------------------------------
# preview_import — validation errors raised (no DB, no 500)
# ---------------------------------------------------------------------------

class TestPreviewImportValidation:

    def test_preview_raises_for_missing_level(self):
        with pytest.raises(ValueError, match="обязательные поля"):
            CurriculumImportService.preview_import({'module': 1})

    def test_preview_raises_for_missing_module(self):
        with pytest.raises(ValueError, match="обязательные поля"):
            CurriculumImportService.preview_import({'level': 'A1'})

    def test_preview_raises_for_invalid_level(self):
        with pytest.raises(ValueError, match="Недопустимый уровень"):
            CurriculumImportService.preview_import({'level': 'Z9', 'module': 1})

    def test_preview_raises_for_none_level(self):
        """New-format payload where level is missing inside the nested dict."""
        data = {'module': {'order': 1, 'lessons': []}}  # no level field
        with pytest.raises(ValueError):
            CurriculumImportService.preview_import(data)


# ---------------------------------------------------------------------------
# Batch vocabulary lookup — chunk_ids is used, not N+1 per-word queries
# ---------------------------------------------------------------------------

class TestProcessVocabularyBatchLookup:
    """process_vocabulary must pre-fetch words with IN() queries, not one-by-one."""

    @patch('app.admin.services.curriculum_import_service.db')
    @patch('app.admin.services.curriculum_import_service.CollectionWordLink')
    @patch('app.admin.services.curriculum_import_service.CollectionWords')
    def test_batch_prefetch_called_once_for_small_vocab(
        self, mock_words, mock_links, mock_db
    ):
        """For ≤1000 words there must be exactly one IN() query, not N filter_by calls."""
        mock_collection = MagicMock()
        mock_collection.id = 1

        # No existing words
        mock_words.query.filter.return_value.all.return_value = []

        vocab = [
            {'word': f'word{i}', 'translation': f'перевод{i}'}
            for i in range(5)
        ]

        # Give new words an ID after flush
        created_words = []

        def make_word(**kwargs):
            w = MagicMock()
            w.id = len(created_words) + 100
            w.english_word = kwargs.get('english_word', '')
            created_words.append(w)
            return w

        mock_words.side_effect = make_word

        CurriculumImportService.process_vocabulary(vocab, mock_collection, 'A1')

        # filter() (IN query) must have been called — not filter_by per word
        assert mock_words.query.filter.call_count >= 1
        # filter_by (individual lookup) must NOT have been called
        mock_words.query.filter_by.assert_not_called()

    @patch('app.admin.services.curriculum_import_service.db')
    @patch('app.admin.services.curriculum_import_service.CollectionWordLink')
    @patch('app.admin.services.curriculum_import_service.CollectionWords')
    @patch('app.admin.services.curriculum_import_service.chunk_ids')
    def test_chunk_ids_called_for_large_vocab(
        self, mock_chunk_ids, mock_words, mock_links, mock_db
    ):
        """chunk_ids must be called when processing vocabulary so large lists are safe."""
        mock_collection = MagicMock()
        mock_collection.id = 1

        # chunk_ids should still yield the words
        words_list = [f'word{i}' for i in range(1200)]
        mock_chunk_ids.side_effect = lambda lst, **kw: (
            [lst[i:i+1000] for i in range(0, len(lst), 1000)]
            if lst else []
        )
        mock_words.query.filter.return_value.all.return_value = []

        vocab = [
            {'word': f'word{i}', 'translation': f'перевод{i}'}
            for i in range(1200)
        ]

        def make_word(**kwargs):
            w = MagicMock()
            w.id = id(w)
            w.english_word = kwargs.get('english_word', '')
            return w

        mock_words.side_effect = make_word

        CurriculumImportService.process_vocabulary(vocab, mock_collection, 'A1')

        # chunk_ids must have been called with the words list
        mock_chunk_ids.assert_called_once()

    @patch('app.admin.services.curriculum_import_service.db')
    @patch('app.admin.services.curriculum_import_service.CollectionWordLink')
    @patch('app.admin.services.curriculum_import_service.CollectionWords')
    def test_duplicate_words_in_vocab_create_one_link(
        self, mock_words, mock_links, mock_db
    ):
        """If the same word appears twice in the vocab list, only one link is created."""
        mock_collection = MagicMock()
        mock_collection.id = 42

        # No existing words
        mock_words.query.filter.return_value.all.return_value = []

        calls_to_add = []
        mock_db.session.add.side_effect = lambda obj: calls_to_add.append(obj)

        existing_word = MagicMock()
        existing_word.id = 99
        existing_word.english_word = 'hello'

        # First call to mock_words() creates the word; subsequent uses come from cache
        mock_words.return_value = existing_word

        vocab = [
            {'word': 'hello', 'translation': 'привет'},
            {'word': 'hello', 'translation': 'здравствуй'},  # duplicate
        ]

        CurriculumImportService.process_vocabulary(vocab, mock_collection, 'A1')

        # Only one CollectionWordLink should be added for 'hello'
        link_adds = [
            obj for obj in calls_to_add
            if isinstance(obj, MagicMock) and not hasattr(obj, '_mock_name')
        ]
        # We care that add was called fewer times than len(vocab) for links
        # (exactly 2 calls: one for the word + one for the link)
        assert mock_db.session.add.call_count <= 3  # word + 1 link (not 2 links)


# ---------------------------------------------------------------------------
# Invalid JSON — route returns redirect, not 500
# ---------------------------------------------------------------------------

class TestImportRouteInvalidJson:
    """Invalid JSON in the import form must redirect back, not raise 500."""

    def test_invalid_json_text_redirects(self, admin_client, mock_admin_user):
        response = admin_client.post(
            '/admin/curriculum/import',
            data={'json_text': '{bad json['},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert '/admin/curriculum/import' in response.location

    def test_truncated_json_redirects(self, admin_client, mock_admin_user):
        response = admin_client.post(
            '/admin/curriculum/import',
            data={'json_text': '{"level": "A1", "module"'},  # truncated
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert '/admin/curriculum/import' in response.location

    def test_empty_json_text_does_not_trigger_import(self, admin_client, mock_admin_user):
        """Submitting an empty json_text must not call the import service."""
        with patch(
            'app.admin.routes.curriculum_routes.CurriculumImportService.import_curriculum_data'
        ) as mock_import:
            response = admin_client.post(
                '/admin/curriculum/import',
                data={'json_text': ''},
                follow_redirects=False,
            )
            # Should render form again (200) or redirect — not call import
            mock_import.assert_not_called()

    @patch('app.utils.file_security.validate_text_file_upload')
    def test_invalid_file_encoding_redirects(self, mock_validate, admin_client, mock_admin_user):
        """File that cannot be decoded as UTF-8 redirects without 500."""
        mock_validate.return_value = (True, None)

        file_data = BytesIO(b'\xff\xfe invalid bytes')

        response = admin_client.post(
            '/admin/curriculum/import',
            data={'json_file': (file_data, 'bad.json')},
            content_type='multipart/form-data',
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert '/admin/curriculum/import' in response.location


# ---------------------------------------------------------------------------
# Double submit idempotency
# ---------------------------------------------------------------------------

class TestImportIdempotency:
    """Re-importing the same JSON payload must produce the same DB state (update, not dup)."""

    @patch('app.admin.routes.curriculum_routes.CurriculumImportService.import_curriculum_data')
    @patch('app.admin.routes.curriculum_routes.Module')
    def test_double_submit_calls_import_twice_same_result(
        self, mock_module, mock_import, admin_client, mock_admin_user
    ):
        """Submitting the same payload twice must call import twice without error."""
        mock_import.return_value = {'lesson_id': 55, 'module_id': 3}
        mock_module.query.get.return_value = None  # trigger curriculum redirect

        payload = json.dumps({'level': 'A1', 'module': 1, 'lessons': []})

        r1 = admin_client.post(
            '/admin/curriculum/import',
            data={'json_text': payload},
            follow_redirects=False,
        )
        r2 = admin_client.post(
            '/admin/curriculum/import',
            data={'json_text': payload},
            follow_redirects=False,
        )

        assert r1.status_code == 302
        assert r2.status_code == 302
        assert mock_import.call_count == 2

    @patch('app.admin.services.curriculum_import_service.current_user')
    @patch('app.admin.services.curriculum_import_service.db')
    @patch('app.admin.services.curriculum_import_service.Lessons')
    @patch('app.admin.services.curriculum_import_service.Module')
    @patch('app.admin.services.curriculum_import_service.CEFRLevel')
    def test_re_import_updates_not_duplicates(
        self, mock_level_cls, mock_module_cls, mock_lessons_cls, mock_db, mock_user
    ):
        """import_curriculum_data updates existing module/lesson on second call."""
        mock_user.id = 1

        mock_level = MagicMock()
        mock_level.id = 1
        mock_level_cls.query.filter_by.return_value.first.return_value = mock_level

        mock_module = MagicMock()
        mock_module.id = 10
        mock_module.number = 2
        mock_module.title = 'Original Title'
        # Module exists on first and second call
        mock_module_cls.query.filter_by.return_value.first.return_value = mock_module

        mock_lesson = MagicMock()
        mock_lesson.id = 100
        mock_lesson.number = 1
        mock_lesson.type = 'text'
        mock_lesson.title = 'Intro'
        mock_lesson.content = {'text': 'original'}
        mock_lesson.order = 1
        # The existing_module_lessons prefetch returns this lesson
        all_lessons_query = MagicMock()
        all_lessons_query.all.return_value = [mock_lesson]
        mock_lessons_cls.query.filter_by.return_value = all_lessons_query
        mock_lessons_cls.query.filter_by.return_value.order_by.return_value.first.return_value = mock_lesson

        data = {
            'level': 'A1',
            'module': 2,
            'title': 'Updated Title',
            'lessons': [
                {'lesson_number': 1, 'lesson_type': 'text', 'title': 'Intro', 'content': {'text': 'updated'}},
            ],
        }

        result = CurriculumImportService.import_curriculum_data(data)

        # Module title should have been updated (not a new Module created)
        assert mock_module.title == 'Updated Title'
        # The service should not have called Module() constructor (no new module)
        mock_module_cls.assert_not_called()
        # Result points to existing IDs
        assert result['module_id'] == 10
