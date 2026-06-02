# tests/admin/routes/test_grammar_lab_routes.py
"""Tests for admin grammar lab routes — duplicate detection (Task 22) and
cascade-deletion guarantees (Task 13 of 2026-05-24 admin audit)."""
import inspect
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
            content={'source': 'json_import', 'question': 'Old', 'correct_answer': 'test'},
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


class TestImportFromModules:
    """Tests for importing Grammar Lab topics/exercises from curriculum modules."""

    def _module_with_grammar(self, db_session):
        from app.curriculum.models import CEFRLevel, Lessons, Module

        level = CEFRLevel(code='A1', name='Beginner', order=1)
        db_session.add(level)
        db_session.flush()

        module = Module(
            level_id=level.id,
            number=7,
            title='Grammar Import Module',
            description='Module with grammar lesson exercises',
        )
        db_session.add(module)
        db_session.flush()

        lesson = Lessons(
            module_id=module.id,
            number=1,
            order=1,
            title='Present Simple',
            type='grammar',
            content={
                'grammar_explanation': {
                    'title': 'Present Simple',
                    'introduction': 'Basic present forms.',
                    'sections': [],
                },
                'exercises': [
                    {
                        'type': 'fill_in_blank',
                        'prompt': 'I ___ here every day.',
                        'answer': ['work'],
                        'explanation': 'Use present simple for routines.',
                    },
                    {
                        'type': 'match',
                        'pairs': [{'left': 'I work', 'right': 'я работаю'}],
                    },
                ],
            },
        )
        db_session.add(lesson)
        db_session.commit()
        return module

    def test_import_from_modules_uses_grammar_lesson_exercises(
        self, admin_client, mock_admin_user, db_session,
    ):
        from app.grammar_lab.models import GrammarExercise, GrammarTopic

        module = self._module_with_grammar(db_session)

        response = admin_client.post(
            '/admin/grammar-lab/import-from-modules',
            follow_redirects=False,
        )

        assert response.status_code == 302
        topic = GrammarTopic.query.filter_by(slug=f'a1-{module.number}').one()
        exercises = GrammarExercise.query.filter_by(topic_id=topic.id).order_by(
            GrammarExercise.order
        ).all()
        assert topic.title == 'Present Simple'
        assert len(exercises) == 2
        assert exercises[0].exercise_type == 'fill_blank'
        assert exercises[0].content['correct_answer'] == 'work'
        assert exercises[1].exercise_type == 'matching'


class TestGrammarRoutesStructure:
    """Module-level structure smoke checks (Task 13)."""

    def test_module_has_region_markers_for_all_domains(self):
        from app.admin.routes import grammar_lab_routes

        source = inspect.getsource(grammar_lab_routes)
        for marker in (
            '# region TOPICS',
            '# endregion TOPICS',
            '# region EXERCISES',
            '# endregion EXERCISES',
            '# region IMPORT',
            '# endregion IMPORT',
            '# region API',
            '# endregion API',
        ):
            assert marker in source, f'missing region marker: {marker}'


class TestExerciseDeletionCascade:
    """Deleting a GrammarExercise must cascade to dependent SRS/attempt rows.

    Guaranteed by ``ondelete='CASCADE'`` on
    ``user_grammar_exercises.exercise_id`` and ``grammar_attempts.exercise_id``
    plus migration ``20260425_grammar_exercise_cascade`` for legacy DBs.
    """

    def _make_topic(self, db_session, slug: str):
        from app.grammar_lab.models import GrammarTopic

        topic = GrammarTopic(
            slug=slug,
            title='Cascade Topic',
            title_ru='Каскад',
            level='A1',
            order=1,
            content={},
        )
        db_session.add(topic)
        db_session.commit()
        return topic

    def _make_exercise(self, db_session, topic):
        from app.grammar_lab.models import GrammarExercise

        exercise = GrammarExercise(
            topic_id=topic.id,
            exercise_type='fill_blank',
            content={'question': 'Q?', 'correct_answer': 'a'},
            difficulty=1,
            order=1,
        )
        db_session.add(exercise)
        db_session.commit()
        return exercise

    @pytest.mark.smoke
    def test_delete_exercise_cascades_to_user_progress_and_attempts(
        self, admin_client, mock_admin_user, db_session, admin_user,
    ):
        from app.grammar_lab.models import (
            GrammarAttempt,
            GrammarExercise,
            UserGrammarExercise,
        )

        topic = self._make_topic(db_session, slug='cascade-1')
        exercise = self._make_exercise(db_session, topic)
        exercise_id = exercise.id

        UserGrammarExercise.get_or_create(admin_user.id, exercise.id)
        attempt = GrammarAttempt(
            user_id=admin_user.id,
            exercise_id=exercise.id,
            is_correct=True,
            user_answer='a',
            source='topic_practice',
        )
        db_session.add(attempt)
        db_session.commit()

        assert UserGrammarExercise.query.filter_by(exercise_id=exercise_id).count() == 1
        assert GrammarAttempt.query.filter_by(exercise_id=exercise_id).count() == 1

        response = admin_client.post(
            f'/admin/grammar-lab/exercises/{exercise_id}/delete',
            follow_redirects=False,
        )

        assert response.status_code == 302
        db_session.expire_all()
        assert GrammarExercise.query.get(exercise_id) is None
        assert UserGrammarExercise.query.filter_by(exercise_id=exercise_id).count() == 0
        assert GrammarAttempt.query.filter_by(exercise_id=exercise_id).count() == 0

    def test_delete_topic_cascades_to_exercises_and_their_children(
        self, admin_client, mock_admin_user, db_session, admin_user,
    ):
        from app.grammar_lab.models import (
            GrammarAttempt,
            GrammarExercise,
            GrammarTopic,
            UserGrammarExercise,
            UserGrammarTopicStatus,
        )

        topic = self._make_topic(db_session, slug='cascade-2')
        exercise = self._make_exercise(db_session, topic)
        topic_id = topic.id
        exercise_id = exercise.id

        UserGrammarExercise.get_or_create(admin_user.id, exercise.id)
        db_session.add(GrammarAttempt(
            user_id=admin_user.id,
            exercise_id=exercise.id,
            is_correct=False,
            user_answer='wrong',
            source='topic_practice',
        ))
        db_session.add(UserGrammarTopicStatus(
            user_id=admin_user.id,
            topic_id=topic.id,
            status='theory_completed',
            theory_completed=True,
        ))
        db_session.commit()

        response = admin_client.post(
            f'/admin/grammar-lab/topics/{topic_id}/delete',
            follow_redirects=False,
        )

        assert response.status_code == 302
        db_session.expire_all()
        assert GrammarTopic.query.get(topic_id) is None
        assert GrammarExercise.query.filter_by(topic_id=topic_id).count() == 0
        assert UserGrammarExercise.query.filter_by(exercise_id=exercise_id).count() == 0
        assert GrammarAttempt.query.filter_by(exercise_id=exercise_id).count() == 0
        assert UserGrammarTopicStatus.query.filter_by(topic_id=topic_id).count() == 0


class TestEditExerciseValidation:
    """edit_exercise must return 400 on invalid content and reject out-of-range difficulty."""

    def _setup(self, db_session):
        from app.grammar_lab.models import GrammarTopic, GrammarExercise

        topic = GrammarTopic(
            slug='edit-val-topic',
            title='Edit Val Topic',
            title_ru='Редактирование',
            level='A1',
            order=1,
            content={},
        )
        db_session.add(topic)
        db_session.commit()

        exercise = GrammarExercise(
            topic_id=topic.id,
            exercise_type='fill_blank',
            content={'question': 'Q', 'correct_answer': 'a'},
            difficulty=1,
            order=1,
        )
        db_session.add(exercise)
        db_session.commit()
        return topic, exercise

    def test_edit_exercise_invalid_content_returns_400(
        self, admin_client, mock_admin_user, db_session,
    ):
        """edit_exercise must return 400 (not 500) when content fails validation."""
        _topic, exercise = self._setup(db_session)

        response = admin_client.post(
            f'/admin/grammar-lab/exercises/{exercise.id}/edit',
            data={
                'exercise_type': 'fill_blank',
                'content': json.dumps({'question': 'No answer field'}),
                'difficulty': '1',
                'order': '1',
            },
        )

        assert response.status_code == 400

    def test_edit_exercise_difficulty_above_3_returns_400(
        self, admin_client, mock_admin_user, db_session,
    ):
        _topic, exercise = self._setup(db_session)

        response = admin_client.post(
            f'/admin/grammar-lab/exercises/{exercise.id}/edit',
            data={
                'exercise_type': 'fill_blank',
                'content': json.dumps({'question': 'Q', 'correct_answer': 'a'}),
                'difficulty': '5',
                'order': '1',
            },
        )

        assert response.status_code == 400

    def test_edit_exercise_difficulty_below_1_returns_400(
        self, admin_client, mock_admin_user, db_session,
    ):
        _topic, exercise = self._setup(db_session)

        response = admin_client.post(
            f'/admin/grammar-lab/exercises/{exercise.id}/edit',
            data={
                'exercise_type': 'fill_blank',
                'content': json.dumps({'question': 'Q', 'correct_answer': 'a'}),
                'difficulty': '0',
                'order': '1',
            },
        )

        assert response.status_code == 400

    def test_create_exercise_difficulty_out_of_range_returns_400(
        self, admin_client, mock_admin_user, db_session,
    ):
        from app.grammar_lab.models import GrammarTopic

        topic = GrammarTopic(
            slug='create-diff-topic',
            title='Topic',
            title_ru='Тема',
            level='A1',
            order=1,
            content={},
        )
        db_session.add(topic)
        db_session.commit()

        response = admin_client.post(
            f'/admin/grammar-lab/topics/{topic.id}/exercises/create',
            data={
                'exercise_type': 'fill_blank',
                'content': json.dumps({'question': 'Q', 'correct_answer': 'a'}),
                'difficulty': '10',
                'order': '1',
            },
        )

        assert response.status_code == 400


class TestImportExercisesJsonValidation:
    """JSON import must skip exercises with invalid content and clamp difficulty."""

    def _topic(self, db_session, slug: str):
        from app.grammar_lab.models import GrammarTopic

        topic = GrammarTopic(
            slug=slug,
            title=f'Topic {slug}',
            title_ru=f'Тема {slug}',
            level='A1',
            order=1,
            content={},
        )
        db_session.add(topic)
        db_session.commit()
        return topic

    def _file(self, payload: dict, filename: str):
        raw = json.dumps(payload).encode('utf-8')
        return (io.BytesIO(raw), filename)

    def test_import_skips_exercises_with_invalid_content(
        self, admin_client, mock_admin_user, db_session,
    ):
        """Exercises missing required keys are skipped (not imported), no 500."""
        from app.grammar_lab.models import GrammarExercise

        # Slug must match _candidate_topic_slugs output: f"{level}-{module_id}"
        topic = self._topic(db_session, 'a1-501')

        payload = {
            'module_id': 501,
            'grammar_topic_slug': 'a1-501',
            'level': 'A1',
            'sessions': [{
                'exercises': [
                    {
                        'exercise_type': 'fill_blank',
                        'content': {'question': 'Missing correct_answer'},
                        'order': 1,
                        'difficulty': 1,
                    },
                    {
                        'exercise_type': 'fill_blank',
                        'content': {'question': 'Valid', 'correct_answer': 'ok'},
                        'order': 2,
                        'difficulty': 1,
                    },
                ],
            }],
        }
        response = admin_client.post(
            '/admin/grammar-lab/import-exercises-json',
            data={'json_files': [self._file(payload, 'a1-501.json')]},
            content_type='multipart/form-data',
            follow_redirects=False,
        )

        assert response.status_code == 302
        exercises = GrammarExercise.query.filter_by(topic_id=topic.id).all()
        assert len(exercises) == 1
        assert exercises[0].content['correct_answer'] == 'ok'

    def test_import_clamps_difficulty_out_of_range(
        self, admin_client, mock_admin_user, db_session,
    ):
        """Difficulty values outside 1-3 are clamped."""
        from app.grammar_lab.models import GrammarExercise

        # Slug must match _candidate_topic_slugs output: f"{level}-{module_id}"
        topic = self._topic(db_session, 'a1-502')

        payload = {
            'module_id': 502,
            'grammar_topic_slug': 'a1-502',
            'level': 'A1',
            'sessions': [{
                'exercises': [
                    {
                        'exercise_type': 'fill_blank',
                        'content': {'question': 'Q high', 'correct_answer': 'a'},
                        'order': 1,
                        'difficulty': 99,
                    },
                    {
                        'exercise_type': 'fill_blank',
                        'content': {'question': 'Q low', 'correct_answer': 'b'},
                        'order': 2,
                        'difficulty': -5,
                    },
                ],
            }],
        }
        response = admin_client.post(
            '/admin/grammar-lab/import-exercises-json',
            data={'json_files': [self._file(payload, 'a1-502.json')]},
            content_type='multipart/form-data',
            follow_redirects=False,
        )

        assert response.status_code == 302
        exercises = GrammarExercise.query.filter_by(topic_id=topic.id).all()
        assert len(exercises) == 2
        for ex in exercises:
            assert 1 <= ex.difficulty <= 3


class TestBulkDeleteCascade:
    """Bulk-delete in import (synchronize_session=False) must cascade to UserGrammarExercise."""

    def test_import_bulk_delete_cascades_to_user_grammar_exercise(
        self, admin_client, mock_admin_user, db_session, admin_user,
    ):
        """When JSON import wipes old json_import exercises, UserGrammarExercise rows must disappear too."""
        from app.grammar_lab.models import (
            GrammarExercise,
            GrammarTopic,
            UserGrammarExercise,
        )

        # Slug must match _candidate_topic_slugs output: f"{level}-{module_id}"
        topic = GrammarTopic(
            slug='a1-503',
            title='Bulk',
            title_ru='Массово',
            level='A1',
            order=1,
            content={},
        )
        db_session.add(topic)
        db_session.commit()

        old_exercise = GrammarExercise(
            topic_id=topic.id,
            exercise_type='fill_blank',
            content={'source': 'json_import', 'question': 'Old', 'correct_answer': 'x'},
            difficulty=1,
            order=1,
        )
        db_session.add(old_exercise)
        db_session.commit()
        old_id = old_exercise.id

        UserGrammarExercise.get_or_create(admin_user.id, old_id)
        db_session.commit()

        assert UserGrammarExercise.query.filter_by(exercise_id=old_id).count() == 1

        payload = {
            'module_id': 503,
            'grammar_topic_slug': 'a1-503',
            'level': 'A1',
            'sessions': [{
                'exercises': [{
                    'exercise_type': 'fill_blank',
                    'content': {'question': 'New', 'correct_answer': 'y'},
                    'order': 1,
                    'difficulty': 1,
                }],
            }],
        }
        raw = json.dumps(payload).encode('utf-8')
        response = admin_client.post(
            '/admin/grammar-lab/import-exercises-json',
            data={'json_files': [(io.BytesIO(raw), 'a1-503.json')]},
            content_type='multipart/form-data',
            follow_redirects=False,
        )

        assert response.status_code == 302
        db_session.expire_all()
        assert GrammarExercise.query.filter_by(id=old_id).count() == 0
        assert UserGrammarExercise.query.filter_by(exercise_id=old_id).count() == 0
        assert GrammarExercise.query.filter_by(topic_id=topic.id).count() == 1
