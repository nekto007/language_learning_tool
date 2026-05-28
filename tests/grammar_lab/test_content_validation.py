"""Tests for GrammarExercise content schema validation + ON DELETE CASCADE."""

import json
import pytest

from app.grammar_lab.content_validator import validate_exercise_content
from app.grammar_lab.models import (
    GrammarAttempt,
    GrammarExercise,
    GrammarTopic,
    UserGrammarExercise,
)
from app.utils.db import db


@pytest.fixture
def topic(app, db_session):
    t = GrammarTopic(
        slug='cascade-test', title='Cascade', title_ru='Каскад',
        level='A1', order=1, content={},
    )
    db_session.add(t)
    db_session.flush()
    return t


class TestValidateExerciseContent:
    def test_valid_fill_blank(self):
        validate_exercise_content('fill_blank', {'correct_answer': 'am'})

    def test_missing_correct_answer_raises(self):
        with pytest.raises(ValueError, match='correct_answer'):
            validate_exercise_content('fill_blank', {'question': 'I ___ here.'})

    def test_multiple_choice_requires_options(self):
        with pytest.raises(ValueError, match='options'):
            validate_exercise_content('multiple_choice', {'correct_answer': 0})

    def test_matching_requires_pairs(self):
        with pytest.raises(ValueError, match='pairs'):
            validate_exercise_content('matching', {'explanation': '...'})

    def test_true_false_accepts_boolean_false(self):
        validate_exercise_content('true_false', {'correct_answer': False})

    def test_unknown_type_passes(self):
        validate_exercise_content('mystery_new_type', {})

    def test_non_mapping_raises(self):
        with pytest.raises(ValueError, match='must be a mapping'):
            validate_exercise_content('fill_blank', None)

    # All 8 supported types — valid payloads
    def test_valid_reorder(self):
        validate_exercise_content('reorder', {'correct_answer': 'She is tall'})

    def test_valid_transformation(self):
        validate_exercise_content('transformation', {'correct_answer': 'He has been'})

    def test_valid_error_correction(self):
        validate_exercise_content('error_correction', {'correct_answer': 'I am going'})

    def test_valid_translation(self):
        validate_exercise_content('translation', {'correct_answer': 'Hello world'})

    def test_valid_true_false(self):
        validate_exercise_content('true_false', {'correct_answer': True})

    def test_valid_multiple_choice(self):
        validate_exercise_content('multiple_choice', {'correct_answer': 1, 'options': ['a', 'b']})

    def test_valid_matching(self):
        validate_exercise_content('matching', {'pairs': [['a', 'b']]})

    # All 8 supported types — invalid payloads raise ValueError
    def test_reorder_missing_correct_answer_raises(self):
        with pytest.raises(ValueError, match='correct_answer'):
            validate_exercise_content('reorder', {'words': ['She', 'is', 'tall']})

    def test_transformation_missing_correct_answer_raises(self):
        with pytest.raises(ValueError, match='correct_answer'):
            validate_exercise_content('transformation', {'original': 'Go'})

    def test_error_correction_missing_correct_answer_raises(self):
        with pytest.raises(ValueError, match='correct_answer'):
            validate_exercise_content('error_correction', {'sentence': 'I is here'})

    def test_translation_missing_correct_answer_raises(self):
        with pytest.raises(ValueError, match='correct_answer'):
            validate_exercise_content('translation', {'sentence': 'Привет'})

    def test_true_false_missing_correct_answer_raises(self):
        with pytest.raises(ValueError, match='correct_answer'):
            validate_exercise_content('true_false', {'statement': 'Cats can fly'})

    def test_empty_correct_answer_string_raises(self):
        with pytest.raises(ValueError, match='correct_answer'):
            validate_exercise_content('fill_blank', {'correct_answer': ''})

    def test_empty_list_pairs_raises(self):
        with pytest.raises(ValueError, match='pairs'):
            validate_exercise_content('matching', {'pairs': []})

    def test_non_mapping_list_raises(self):
        with pytest.raises(ValueError, match='must be a mapping'):
            validate_exercise_content('fill_blank', ['wrong', 'type'])


class TestAdminCreateExerciseValidation:
    """Admin create_exercise route returns 400 (not 500) for invalid exercise content."""

    def test_invalid_content_returns_400_not_500(self, app, client, db_session, admin_user, topic):
        resp = client.post(
            f'/admin/grammar-lab/topics/{topic.id}/exercises/create',
            data={
                'exercise_type': 'fill_blank',
                'content': json.dumps({'question': 'missing answer'}),
                'order': '0',
                'difficulty': '1',
            },
            follow_redirects=False,
        )
        assert resp.status_code == 400, (
            f"Expected 400 for invalid content, got {resp.status_code}"
        )

    def test_invalid_json_content_not_500(self, app, client, db_session, admin_user, topic):
        resp = client.post(
            f'/admin/grammar-lab/topics/{topic.id}/exercises/create',
            data={
                'exercise_type': 'fill_blank',
                'content': 'NOT_VALID_JSON{{{',
                'order': '0',
                'difficulty': '1',
            },
            follow_redirects=False,
        )
        assert resp.status_code != 500, (
            f"Expected non-500 for invalid JSON content, got {resp.status_code}"
        )


class TestApiSubmitAnswerNonexistentExercise:
    """Grammar lab API returns 404 for non-existent exercise; no GrammarAttempt created."""

    def test_submit_nonexistent_exercise_returns_404(self, app, client, db_session, test_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        resp = client.post(
            '/grammar-lab/api/exercise/999999/submit',
            json={'answer': 'test'},
            content_type='application/json',
        )
        assert resp.status_code == 404, (
            f"Expected 404 for nonexistent exercise, got {resp.status_code}"
        )

    def test_submit_nonexistent_exercise_no_attempt_created(self, app, db_session, test_user):
        from app.grammar_lab.services.grammar_lab_service import GrammarLabService
        service = GrammarLabService()

        before_count = db_session.query(GrammarAttempt).filter_by(
            user_id=test_user.id
        ).count()

        result = service.submit_answer(
            exercise_id=999999,
            user_id=test_user.id,
            answer='test',
        )

        after_count = db_session.query(GrammarAttempt).filter_by(
            user_id=test_user.id
        ).count()

        assert result.get('error') == 'Exercise not found'
        assert after_count == before_count, "No GrammarAttempt should be created for nonexistent exercise"


class TestGrammarExerciseInitValidation:
    def test_valid_construction(self, topic):
        ex = GrammarExercise(
            topic_id=topic.id,
            exercise_type='fill_blank',
            content={'correct_answer': 'am'},
        )
        assert ex.exercise_type == 'fill_blank'

    def test_invalid_construction_raises(self, topic):
        with pytest.raises(ValueError):
            GrammarExercise(
                topic_id=topic.id,
                exercise_type='fill_blank',
                content={'question': 'no answer'},
            )

    def test_exercise_loaded_from_db_skips_validation(self, topic, db_session):
        ex = GrammarExercise(
            topic_id=topic.id,
            exercise_type='fill_blank',
            content={'correct_answer': 'am'},
        )
        db_session.add(ex)
        db_session.flush()
        ex_id = ex.id
        db_session.expire_all()
        loaded = db_session.get(GrammarExercise, ex_id)
        assert loaded.exercise_type == 'fill_blank'


class TestCascadeDelete:
    """Cascade is wired at the model level (SQLite respects ondelete=CASCADE
    when foreign_keys pragma is enabled, which the test conftest enables)."""

    def test_delete_exercise_cascades_attempts_and_progress(
        self, app, db_session, topic, test_user
    ):
        ex = GrammarExercise(
            topic_id=topic.id,
            exercise_type='fill_blank',
            content={'correct_answer': 'am'},
        )
        db_session.add(ex)
        db_session.flush()

        attempt = GrammarAttempt(
            user_id=test_user.id,
            exercise_id=ex.id,
            is_correct=True,
            user_answer='am',
        )
        progress = UserGrammarExercise(user_id=test_user.id, exercise_id=ex.id)
        db_session.add_all([attempt, progress])
        db_session.flush()
        ex_id = ex.id

        # Trigger DB-level ON DELETE CASCADE via raw DELETE (skipping ORM
        # which would otherwise null FKs on un-cascaded backrefs).
        db_session.expire_all()
        db_session.execute(
            db.text("DELETE FROM grammar_exercises WHERE id = :id"),
            {'id': ex_id},
        )
        db_session.flush()

        assert db_session.query(GrammarAttempt).filter_by(exercise_id=ex_id).count() == 0
        assert db_session.query(UserGrammarExercise).filter_by(exercise_id=ex_id).count() == 0
