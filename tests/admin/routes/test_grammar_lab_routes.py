# tests/admin/routes/test_grammar_lab_routes.py
"""Tests for admin grammar lab routes — duplicate detection (Task 22)."""
import io
import json

import pytest
from unittest.mock import patch
from sqlalchemy.exc import IntegrityError


class TestCreateTopicDuplicateSlug:
    """Tests for duplicate slug detection in create_topic route."""

    @pytest.mark.smoke
    @patch('app.admin.routes.grammar_lab_routes.db')
    def test_create_topic_duplicate_slug_returns_error_flash(self, mock_db, admin_client, mock_admin_user):
        """Duplicate slug triggers IntegrityError which flashes an error message."""
        mock_db.session.add.return_value = None
        mock_db.session.commit.side_effect = IntegrityError(
            statement='INSERT INTO grammar_topics', params={}, orig=Exception('unique constraint')
        )
        mock_db.session.rollback.return_value = None

        response = admin_client.post(
            '/admin/grammar-lab/topics/create',
            data={
                'slug': 'a1-1',
                'title': 'Present Simple',
                'title_ru': 'Настоящее простое',
                'level': 'A1',
                'order': '1',
                'estimated_time': '15',
                'difficulty': '1',
                'content': '{}'
            },
            follow_redirects=True
        )

        assert response.status_code == 200
        assert b'slug' in response.data or b'taken' in response.data or b'Error' in response.data

    @patch('app.admin.routes.grammar_lab_routes.db')
    def test_create_topic_rollback_called_on_integrity_error(self, mock_db, admin_client, mock_admin_user):
        """Ensure rollback is called on IntegrityError so session stays clean."""
        mock_db.session.add.return_value = None
        mock_db.session.commit.side_effect = IntegrityError(
            statement='INSERT', params={}, orig=Exception('unique constraint')
        )
        mock_db.session.rollback.return_value = None

        admin_client.post(
            '/admin/grammar-lab/topics/create',
            data={
                'slug': 'a1-1',
                'title': 'Test',
                'title_ru': 'Тест',
                'level': 'A1',
                'order': '1',
                'estimated_time': '15',
                'difficulty': '1',
                'content': '{}'
            },
            follow_redirects=True
        )

        mock_db.session.rollback.assert_called_once()


class TestImportExercisesJson:
    """Tests for uploading generated Grammar Lab exercise JSON files."""

    def _topic(self, db_session, *, slug: str, module_id: int, level: str = 'A1'):
        from app.grammar_lab.models import GrammarTopic

        topic = GrammarTopic(
            slug=slug,
            title=f'Topic {module_id}',
            title_ru=f'Тема {module_id}',
            level=level,
            order=module_id,
            content={},
        )
        db_session.add(topic)
        db_session.commit()
        return topic

    def _payload(self, *, module_id: int, level: str = 'A1', question: str = 'Question'):
        return {
            'module_id': module_id,
            'grammar_topic_slug': f'topic-{module_id}',
            'grammar_topic': f'Topic {module_id}',
            'level': level,
            'sessions': [{
                'exercises': [{
                    'exercise_type': 'fill_blank',
                    'content': {'question': question, 'correct_answer': 'ok'},
                    'order': 1,
                    'difficulty': 1,
                }],
            }],
        }

    def _file(self, payload: dict, filename: str):
        raw = json.dumps(payload).encode('utf-8')
        return (io.BytesIO(raw), filename)

    def test_upload_form_allows_multiple_files(self, admin_client, mock_admin_user):
        response = admin_client.get('/admin/grammar-lab/import-exercises-json')

        assert response.status_code == 200
        assert b'name="json_files"' in response.data
        assert b'multiple' in response.data

    def test_imports_multiple_json_files(
        self, admin_client, mock_admin_user, db_session,
    ):
        from app.grammar_lab.models import GrammarExercise

        topic_1 = self._topic(db_session, slug='a1-1', module_id=1)
        topic_2 = self._topic(db_session, slug='a1-2', module_id=2)

        response = admin_client.post(
            '/admin/grammar-lab/import-exercises-json',
            data={
                'json_files': [
                    self._file(self._payload(module_id=1, question='Q1'), 'a1-1.json'),
                    self._file(self._payload(module_id=2, question='Q2'), 'a1-2.json'),
                ],
            },
            content_type='multipart/form-data',
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert GrammarExercise.query.filter_by(topic_id=topic_1.id).count() == 1
        assert GrammarExercise.query.filter_by(topic_id=topic_2.id).count() == 1

    def test_legacy_single_file_field_still_imports(
        self, admin_client, mock_admin_user, db_session,
    ):
        from app.grammar_lab.models import GrammarExercise

        topic = self._topic(db_session, slug='a1-3', module_id=3)

        response = admin_client.post(
            '/admin/grammar-lab/import-exercises-json',
            data={
                'json_file': self._file(
                    self._payload(module_id=3, question='Legacy'),
                    'a1-3.json',
                ),
            },
            content_type='multipart/form-data',
            follow_redirects=False,
        )

        assert response.status_code == 302
        exercise = GrammarExercise.query.filter_by(topic_id=topic.id).one()
        assert exercise.content['question'] == 'Legacy'

    def test_import_uses_generated_filename_when_payload_module_id_is_database_id(
        self, admin_client, mock_admin_user, db_session,
    ):
        from app.grammar_lab.models import GrammarExercise

        topic = self._topic(db_session, slug='a2-12', module_id=12, level='A2')

        response = admin_client.post(
            '/admin/grammar-lab/import-exercises-json',
            data={
                'json_files': [
                    self._file(
                        self._payload(module_id=27, level='A2', question='Too enough'),
                        'grammar_extra_A2_12.json',
                    ),
                ],
            },
            content_type='multipart/form-data',
            follow_redirects=False,
        )

        assert response.status_code == 302
        exercise = GrammarExercise.query.filter_by(topic_id=topic.id).one()
        assert exercise.content['question'] == 'Too enough'

    def test_same_topic_multiple_files_delete_old_once_and_append_batch(
        self, admin_client, mock_admin_user, db_session,
    ):
        from app.grammar_lab.models import GrammarExercise

        topic = self._topic(db_session, slug='a1-4', module_id=4)
        old_exercise = GrammarExercise(
            topic_id=topic.id,
            exercise_type='fill_blank',
            content={'source': 'json_import', 'question': 'Old'},
            difficulty=1,
            order=1,
        )
        db_session.add(old_exercise)
        db_session.commit()

        response = admin_client.post(
            '/admin/grammar-lab/import-exercises-json',
            data={
                'json_files': [
                    self._file(self._payload(module_id=4, question='New 1'), 'a1-4-a.json'),
                    self._file(self._payload(module_id=4, question='New 2'), 'a1-4-b.json'),
                ],
            },
            content_type='multipart/form-data',
            follow_redirects=False,
        )

        assert response.status_code == 302
        questions = {
            ex.content['question']
            for ex in GrammarExercise.query.filter_by(topic_id=topic.id).all()
        }
        assert questions == {'New 1', 'New 2'}
