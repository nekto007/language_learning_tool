"""Tests for GrammarExercise content schema validation + ON DELETE CASCADE."""

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
