"""
Tests for grammar lab services:
- app/grammar_lab/services/grader.py (GrammarExerciseGrader)
- app/grammar_lab/services/grammar_srs.py (GrammarSRS)
- app/grammar_lab/services/grammar_lab_service.py (GrammarLabService)
"""
import pytest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.grammar_lab.models import (
    GrammarTopic, GrammarExercise, UserGrammarTopicStatus,
    UserGrammarExercise, GrammarAttempt
)
from app.grammar_lab.services.grader import GrammarExerciseGrader
from app.grammar_lab.services.grammar_srs import GrammarSRS
from app.grammar_lab.services.grammar_lab_service import GrammarLabService, GRAMMAR_XP
from app.srs.constants import CardState, RATING_KNOW, RATING_DONT_KNOW
from app.utils.db import db


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def grammar_topic(db_session):
    """Create a grammar topic with unique slug."""
    unique = uuid.uuid4().hex[:8]
    topic = GrammarTopic(
        slug=f'test-present-simple-{unique}',
        title='Present Simple',
        title_ru='Простое настоящее',
        level='A1',
        order=1,
        content={'introduction': 'Test intro', 'sections': []},
        estimated_time=15,
        difficulty=1
    )
    db_session.add(topic)
    db_session.commit()
    return topic


@pytest.fixture
def grammar_exercises(db_session, grammar_topic):
    """Create grammar exercises for the topic."""
    exercises = []
    exercise_data = [
        ('fill_blank', {'question': 'I ___ a student.', 'correct_answer': 'am',
                        'alternatives': ["I'm"], 'explanation': 'Use am with I'}),
        ('multiple_choice', {'question': 'Choose correct:', 'correct_answer': 0,
                             'options': ['am', 'is', 'are'], 'explanation': 'I am'}),
        ('reorder', {'words': ['I', 'am', 'happy'], 'correct_answer': 'I am happy',
                     'explanation': 'SVO order'}),
        ('error_correction', {'question': 'He am happy', 'correct_answer': 'is',
                              'full_correct': 'He is happy', 'alternatives': [],
                              'explanation': 'He takes is'}),
        ('transformation', {'question': 'Transform to negative', 'correct_answer': 'I am not happy',
                            'alternatives': ["I'm not happy"], 'explanation': 'Add not'}),
        ('translation', {'question': 'Translate', 'sentence': 'Я счастлив',
                         'correct_answer': 'I am happy', 'alternatives': ["I'm happy"],
                         'explanation': 'Direct translation'}),
        ('matching', {'pairs': [{'left': 'I', 'right': 'am'}, {'left': 'He', 'right': 'is'}],
                      'explanation': 'Match pronouns with be'}),
        ('true_false', {'question': '"I am" is correct', 'correct_answer': True,
                        'explanation': 'Yes, I am is correct'}),
    ]
    for ex_type, content in exercise_data:
        ex = GrammarExercise(
            topic_id=grammar_topic.id,
            exercise_type=ex_type,
            content=content,
            difficulty=1,
            order=len(exercises)
        )
        db_session.add(ex)
        exercises.append(ex)
    db_session.commit()
    return exercises


@pytest.fixture
def grader():
    return GrammarExerciseGrader()


# ============================================================
# GrammarExerciseGrader Tests
# ============================================================

class TestGraderNormalizeAnswer:
    def test_basic(self, grader):
        assert grader._normalize_answer('  Hello  World  ') == 'hello world'

    def test_punctuation_removal(self, grader):
        assert grader._normalize_answer('Hello!') == 'hello'
        assert grader._normalize_answer('Hello...') == 'hello'

    def test_spaces_before_punctuation(self, grader):
        assert grader._normalize_answer('Hello , world !') == 'hello, world'

    def test_none(self, grader):
        assert grader._normalize_answer(None) == ''

    def test_empty(self, grader):
        assert grader._normalize_answer('') == ''


class TestGraderFillBlank:
    def test_correct_answer(self, grader, grammar_exercises):
        ex = grammar_exercises[0]  # fill_blank
        result = grader.grade(ex, 'am')
        assert result['is_correct'] is True

    def test_alternative_answer(self, grader, grammar_exercises):
        ex = grammar_exercises[0]
        result = grader.grade(ex, "I'm")
        assert result['is_correct'] is True

    def test_wrong_answer(self, grader, grammar_exercises):
        ex = grammar_exercises[0]
        result = grader.grade(ex, 'is')
        assert result['is_correct'] is False

    def test_case_insensitive(self, grader, grammar_exercises):
        ex = grammar_exercises[0]
        result = grader.grade(ex, 'AM')
        assert result['is_correct'] is True

    def test_returns_explanation(self, grader, grammar_exercises):
        ex = grammar_exercises[0]
        result = grader.grade(ex, 'am')
        assert 'explanation' in result

    def test_full_sentence_accepted(self, grader, grammar_exercises):
        """User types full sentence 'I am a student' instead of just 'am'"""
        ex = grammar_exercises[0]  # question: 'I ___ a student.', correct: 'am'
        result = grader.grade(ex, 'I am a student')
        assert result['is_correct'] is True

    def test_full_sentence_wrong_answer(self, grader, grammar_exercises):
        """Full sentence with wrong word in blank should fail"""
        ex = grammar_exercises[0]
        result = grader.grade(ex, 'I is a student')
        assert result['is_correct'] is False


class TestGraderMultipleChoice:
    def test_correct_index(self, grader, grammar_exercises):
        ex = grammar_exercises[1]  # multiple_choice, correct=0
        result = grader.grade(ex, 0)
        assert result['is_correct'] is True

    def test_wrong_index(self, grader, grammar_exercises):
        ex = grammar_exercises[1]
        result = grader.grade(ex, 2)
        assert result['is_correct'] is False

    def test_string_answer(self, grader, grammar_exercises):
        ex = grammar_exercises[1]
        result = grader.grade(ex, 'am')
        assert result['is_correct'] is True

    def test_wrong_string(self, grader, grammar_exercises):
        ex = grammar_exercises[1]
        result = grader.grade(ex, 'are')
        assert result['is_correct'] is False

    def test_string_correct_answer_value(self, db_session, grammar_topic, grader):
        """Test when correct_answer is a string (not index)."""
        ex = GrammarExercise(
            topic_id=grammar_topic.id, exercise_type='multiple_choice',
            content={'question': 'Q?', 'correct_answer': 'is',
                     'options': ['am', 'is', 'are'], 'explanation': ''},
            difficulty=1
        )
        db_session.add(ex)
        db_session.commit()
        result = grader.grade(ex, 1)  # index of 'is'
        assert result['is_correct'] is True


class TestGraderReorder:
    def test_correct_string(self, grader, grammar_exercises):
        ex = grammar_exercises[2]  # reorder
        result = grader.grade(ex, 'I am happy')
        assert result['is_correct'] is True

    def test_wrong_string(self, grader, grammar_exercises):
        ex = grammar_exercises[2]
        result = grader.grade(ex, 'happy am I')
        assert result['is_correct'] is False

    def test_correct_indices(self, grader, grammar_exercises):
        ex = grammar_exercises[2]
        result = grader.grade(ex, [0, 1, 2])  # I, am, happy
        assert result['is_correct'] is True

    def test_wrong_indices(self, grader, grammar_exercises):
        ex = grammar_exercises[2]
        result = grader.grade(ex, [2, 1, 0])
        assert result['is_correct'] is False

    def test_invalid_indices(self, grader, grammar_exercises):
        ex = grammar_exercises[2]
        result = grader.grade(ex, [99])
        assert result['is_correct'] is False


class TestGraderErrorCorrection:
    def test_correct_word(self, grader, grammar_exercises):
        ex = grammar_exercises[3]  # error_correction, correct='is'
        result = grader.grade(ex, 'is')
        assert result['is_correct'] is True

    def test_full_correct_sentence(self, grader, grammar_exercises):
        ex = grammar_exercises[3]
        result = grader.grade(ex, 'He is happy')
        assert result['is_correct'] is True

    def test_wrong_answer(self, grader, grammar_exercises):
        ex = grammar_exercises[3]
        result = grader.grade(ex, 'are')
        assert result['is_correct'] is False


class TestGraderTransformation:
    def test_correct(self, grader, grammar_exercises):
        ex = grammar_exercises[4]  # transformation
        result = grader.grade(ex, 'I am not happy')
        assert result['is_correct'] is True

    def test_alternative(self, grader, grammar_exercises):
        ex = grammar_exercises[4]
        result = grader.grade(ex, "I'm not happy")
        assert result['is_correct'] is True

    def test_wrong(self, grader, grammar_exercises):
        ex = grammar_exercises[4]
        result = grader.grade(ex, 'I happy not')
        assert result['is_correct'] is False


class TestGraderTranslation:
    def test_correct(self, grader, grammar_exercises):
        ex = grammar_exercises[5]  # translation
        result = grader.grade(ex, 'I am happy')
        assert result['is_correct'] is True

    def test_alternative(self, grader, grammar_exercises):
        ex = grammar_exercises[5]
        result = grader.grade(ex, "I'm happy")
        assert result['is_correct'] is True

    def test_wrong(self, grader, grammar_exercises):
        ex = grammar_exercises[5]
        result = grader.grade(ex, 'He is happy')
        assert result['is_correct'] is False

    def test_returns_key_grammar(self, grader, db_session, grammar_topic):
        ex = GrammarExercise(
            topic_id=grammar_topic.id, exercise_type='translation',
            content={'correct_answer': 'test', 'key_grammar': 'subject-verb agreement',
                     'explanation': ''},
            difficulty=1
        )
        db_session.add(ex)
        db_session.commit()
        result = grader.grade(ex, 'test')
        assert result.get('key_grammar') == 'subject-verb agreement'


class TestGraderMatching:
    def test_correct_dict(self, grader, grammar_exercises):
        ex = grammar_exercises[6]  # matching, 2 pairs
        result = grader.grade(ex, {'0': '0', '1': '1'})
        assert result['is_correct'] is True

    def test_wrong_dict(self, grader, grammar_exercises):
        ex = grammar_exercises[6]
        result = grader.grade(ex, {'0': '1', '1': '0'})
        assert result['is_correct'] is False

    def test_correct_list(self, grader, grammar_exercises):
        ex = grammar_exercises[6]
        result = grader.grade(ex, [[0, 0], [1, 1]])
        assert result['is_correct'] is True

    def test_empty_answer(self, grader, grammar_exercises):
        ex = grammar_exercises[6]
        result = grader.grade(ex, None)
        assert result['is_correct'] is False

    def test_empty_list(self, grader, grammar_exercises):
        ex = grammar_exercises[6]
        result = grader.grade(ex, [])
        assert result['is_correct'] is False


class TestGraderTrueFalse:
    def test_correct_true(self, grader, grammar_exercises):
        ex = grammar_exercises[7]  # true_false, correct=True
        result = grader.grade(ex, True)
        assert result['is_correct'] is True

    def test_correct_string_true(self, grader, grammar_exercises):
        ex = grammar_exercises[7]
        result = grader.grade(ex, 'true')
        assert result['is_correct'] is True

    def test_correct_string_yes(self, grader, grammar_exercises):
        ex = grammar_exercises[7]
        result = grader.grade(ex, 'yes')
        assert result['is_correct'] is True

    def test_wrong(self, grader, grammar_exercises):
        ex = grammar_exercises[7]
        result = grader.grade(ex, False)
        assert result['is_correct'] is False

    def test_string_false_correct(self, db_session, grammar_topic, grader):
        ex = GrammarExercise(
            topic_id=grammar_topic.id, exercise_type='true_false',
            content={'question': 'Q?', 'correct_answer': 'false', 'explanation': ''},
            difficulty=1
        )
        db_session.add(ex)
        db_session.commit()
        result = grader.grade(ex, 'false')
        assert result['is_correct'] is True


class TestGraderUnknownType:
    def test_unknown_type(self, grader, db_session, grammar_topic):
        ex = GrammarExercise(
            topic_id=grammar_topic.id, exercise_type='unknown_type',
            content={}, difficulty=1
        )
        db_session.add(ex)
        db_session.commit()
        result = grader.grade(ex, 'answer')
        assert result['is_correct'] is False
        assert 'error' in result


class TestGraderExceptionHandling:
    def test_grader_handles_exception(self, grader, db_session, grammar_topic):
        """Grader should catch exceptions and return error dict."""
        ex = GrammarExercise(
            topic_id=grammar_topic.id, exercise_type='fill_blank',
            content=None,  # Will cause AttributeError in _grade_fill_blank
            difficulty=1
        )
        db_session.add(ex)
        db_session.commit()
        result = grader.grade(ex, 'test')
        assert result['is_correct'] is False
        assert 'error' in result


# ============================================================
# GrammarSRS Tests
# ============================================================

class TestGrammarSRSGetOrCreateTopicStatus:
    def test_creates_new(self, app, db_session, test_user, grammar_topic):
        srs = GrammarSRS()
        status = srs.get_or_create_topic_status(test_user.id, grammar_topic.id)
        assert status is not None
        assert status.user_id == test_user.id
        assert status.topic_id == grammar_topic.id
        assert status.theory_completed is False

    def test_returns_existing(self, app, db_session, test_user, grammar_topic):
        srs = GrammarSRS()
        status1 = srs.get_or_create_topic_status(test_user.id, grammar_topic.id)
        db_session.commit()
        status2 = srs.get_or_create_topic_status(test_user.id, grammar_topic.id)
        assert status1.id == status2.id


class TestGrammarSRSCompleteTheory:
    def test_complete(self, app, db_session, test_user, grammar_topic):
        srs = GrammarSRS()
        status = srs.complete_theory(test_user.id, grammar_topic.id)
        assert status.theory_completed is True
        assert status.theory_completed_at is not None

    def test_idempotent(self, app, db_session, test_user, grammar_topic):
        srs = GrammarSRS()
        status1 = srs.complete_theory(test_user.id, grammar_topic.id)
        ts1 = status1.theory_completed_at
        status2 = srs.complete_theory(test_user.id, grammar_topic.id)
        assert status2.theory_completed_at == ts1  # Not updated again


class TestGrammarSRSAddXP:
    def test_add_xp(self, app, db_session, test_user, grammar_topic):
        srs = GrammarSRS()
        srs.add_xp(test_user.id, grammar_topic.id, 20)
        status = UserGrammarTopicStatus.query.filter_by(
            user_id=test_user.id, topic_id=grammar_topic.id
        ).first()
        assert status.xp_earned == 20

    def test_accumulates(self, app, db_session, test_user, grammar_topic):
        srs = GrammarSRS()
        srs.add_xp(test_user.id, grammar_topic.id, 10)
        srs.add_xp(test_user.id, grammar_topic.id, 15)
        status = UserGrammarTopicStatus.query.filter_by(
            user_id=test_user.id, topic_id=grammar_topic.id
        ).first()
        assert status.xp_earned == 25


class TestSRSStatsServiceTopicStats:
    """Tests for SRSStatsService.get_grammar_stats (moved from GrammarSRS)."""

    def test_empty_topic(self, app, db_session, test_user, grammar_topic):
        from app.srs.stats_service import srs_stats_service
        stats = srs_stats_service.get_grammar_stats(test_user.id, topic_id=grammar_topic.id)
        assert stats['total'] == 0
        assert stats['accuracy'] == 0

    def test_with_exercises(self, app, db_session, test_user, grammar_topic, grammar_exercises):
        from app.srs.stats_service import srs_stats_service
        stats = srs_stats_service.get_grammar_stats(test_user.id, topic_id=grammar_topic.id)
        assert stats['total'] == len(grammar_exercises)
        assert stats['new_count'] == len(grammar_exercises)

    def test_with_progress(self, app, db_session, test_user, grammar_topic, grammar_exercises):
        from app.srs.stats_service import srs_stats_service
        progress = UserGrammarExercise(
            user_id=test_user.id, exercise_id=grammar_exercises[0].id
        )
        progress.state = CardState.LEARNING.value
        progress.correct_count = 3
        progress.incorrect_count = 1
        db_session.add(progress)
        db_session.commit()

        stats = srs_stats_service.get_grammar_stats(test_user.id, topic_id=grammar_topic.id)
        assert stats['learning_count'] == 1
        assert stats['new_count'] == len(grammar_exercises) - 1
        assert stats['accuracy'] == 75.0

    def test_mastered_count(self, app, db_session, test_user, grammar_topic, grammar_exercises):
        from app.srs.stats_service import srs_stats_service
        progress = UserGrammarExercise(
            user_id=test_user.id, exercise_id=grammar_exercises[0].id
        )
        progress.state = CardState.REVIEW.value
        progress.interval = 200  # >= 180 = mastered
        db_session.add(progress)
        db_session.commit()

        stats = srs_stats_service.get_grammar_stats(test_user.id, topic_id=grammar_topic.id)
        assert stats['mastered_count'] == 1


class TestSRSStatsServiceUserStats:
    """Tests for SRSStatsService.get_grammar_user_stats (moved from GrammarSRS)."""

    def test_empty(self, app, db_session, test_user):
        from app.srs.stats_service import srs_stats_service
        stats = srs_stats_service.get_grammar_user_stats(test_user.id)
        assert stats['total_topics'] >= 0
        assert stats['topics_started'] == 0
        assert stats['total_xp'] == 0
        assert stats['accuracy'] == 0

    def test_with_data(self, app, db_session, test_user, grammar_topic, grammar_exercises):
        from app.srs.stats_service import srs_stats_service
        srs = GrammarSRS()
        srs.complete_theory(test_user.id, grammar_topic.id)
        srs.add_xp(test_user.id, grammar_topic.id, 50)

        progress = UserGrammarExercise(
            user_id=test_user.id, exercise_id=grammar_exercises[0].id
        )
        progress.state = CardState.REVIEW.value
        progress.interval = 30
        progress.correct_count = 5
        progress.incorrect_count = 2
        db_session.add(progress)
        db_session.commit()

        stats = srs_stats_service.get_grammar_user_stats(test_user.id)
        assert stats['total_xp'] == 50
        assert stats['theory_completed'] == 1
        assert stats['topics_started'] >= 1
        assert stats['total_attempts'] == 7
        assert stats['accuracy'] == pytest.approx(71.4, abs=0.1)


# ============================================================
# GrammarLabService Tests
# ============================================================

class TestGrammarLabServiceGetTopicsByLevel:
    def test_no_filter(self, app, db_session, grammar_topic):
        service = GrammarLabService()
        topics = service.get_topics_by_level()
        assert len(topics) >= 1
        found = next((t for t in topics if t['slug'] == grammar_topic.slug), None)
        assert found is not None

    def test_filter_by_level(self, app, db_session, grammar_topic):
        service = GrammarLabService()
        topics = service.get_topics_by_level(level='A1')
        assert all(t['level'] == 'A1' for t in topics)

    def test_with_user_progress(self, app, db_session, test_user, grammar_topic, grammar_exercises):
        service = GrammarLabService()
        topics = service.get_topics_by_level(user_id=test_user.id)
        found = next((t for t in topics if t['slug'] == grammar_topic.slug), None)
        assert found is not None
        assert 'srs_stats' in found

    def test_without_user(self, app, db_session, grammar_topic):
        service = GrammarLabService()
        topics = service.get_topics_by_level()
        found = next((t for t in topics if t['slug'] == grammar_topic.slug), None)
        assert found['status'] is None
        assert found['srs_stats'] is None


class TestGrammarLabServiceGetLevelsSummary:
    def test_returns_all_levels(self, app, db_session):
        service = GrammarLabService()
        levels = service.get_levels_summary()
        assert len(levels) == 6
        level_names = [lv['level'] for lv in levels]
        assert level_names == ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']

    def test_with_user(self, app, db_session, test_user, grammar_topic, grammar_exercises):
        service = GrammarLabService()
        levels = service.get_levels_summary(user_id=test_user.id)
        a1 = next(lv for lv in levels if lv['level'] == 'A1')
        assert a1['topic_count'] >= 1
        assert a1['exercises_total'] >= len(grammar_exercises)


class TestGrammarLabServiceGetTopicDetail:
    def test_existing(self, app, db_session, grammar_topic, grammar_exercises):
        service = GrammarLabService()
        detail = service.get_topic_detail(grammar_topic.id)
        assert detail is not None
        assert detail['slug'] == grammar_topic.slug
        assert 'content' in detail
        assert len(detail['exercises']) == len(grammar_exercises)

    def test_nonexistent(self, app, db_session):
        service = GrammarLabService()
        assert service.get_topic_detail(999999) is None

    def test_with_user(self, app, db_session, test_user, grammar_topic, grammar_exercises):
        service = GrammarLabService()
        detail = service.get_topic_detail(grammar_topic.id, user_id=test_user.id)
        assert 'srs_stats' in detail
        assert 'status' in detail


class TestGrammarLabServiceCompleteTheory:
    def test_first_time(self, app, db_session, test_user, grammar_topic):
        service = GrammarLabService()
        result = service.complete_theory(grammar_topic.id, test_user.id)
        assert result['xp_earned'] == GRAMMAR_XP['theory_completed']
        assert result['status']['theory_completed'] is True

    def test_already_completed(self, app, db_session, test_user, grammar_topic):
        service = GrammarLabService()
        service.complete_theory(grammar_topic.id, test_user.id)
        result = service.complete_theory(grammar_topic.id, test_user.id)
        assert result['xp_earned'] == 0  # No XP on repeat


class TestGrammarLabServiceSubmitAnswer:
    @patch('app.grammar_lab.services.grammar_lab_service._get_unified_srs_service')
    def test_correct_answer(self, mock_srs_fn, app, db_session, test_user,
                            grammar_topic, grammar_exercises):
        mock_srs = MagicMock()
        mock_srs.grade_grammar_exercise.return_value = {
            'success': True, 'state': CardState.LEARNING.value, 'interval': 0
        }
        mock_srs_fn.return_value = mock_srs

        service = GrammarLabService()
        ex = grammar_exercises[0]  # fill_blank, correct='am'
        result = service.submit_answer(ex.id, test_user.id, 'am', session_id='test-session')
        assert result['is_correct'] is True
        assert result['xp_earned'] >= GRAMMAR_XP['exercise_correct']

    @patch('app.grammar_lab.services.grammar_lab_service._get_unified_srs_service')
    def test_wrong_answer(self, mock_srs_fn, app, db_session, test_user,
                          grammar_topic, grammar_exercises):
        mock_srs = MagicMock()
        mock_srs.grade_grammar_exercise.return_value = {
            'success': True, 'state': CardState.LEARNING.value, 'interval': 0
        }
        mock_srs_fn.return_value = mock_srs

        service = GrammarLabService()
        ex = grammar_exercises[0]
        result = service.submit_answer(ex.id, test_user.id, 'is')
        assert result['is_correct'] is False
        assert result['xp_earned'] == 0

    @patch('app.grammar_lab.services.grammar_lab_service._get_unified_srs_service')
    def test_nonexistent_exercise(self, mock_srs_fn, app, db_session, test_user):
        service = GrammarLabService()
        result = service.submit_answer(999999, test_user.id, 'answer')
        assert 'error' in result

    @patch('app.grammar_lab.services.grammar_lab_service._get_unified_srs_service')
    def test_mastery_bonus(self, mock_srs_fn, app, db_session, test_user,
                           grammar_topic, grammar_exercises):
        mock_srs = MagicMock()
        mock_srs.grade_grammar_exercise.return_value = {
            'success': True, 'state': CardState.REVIEW.value, 'interval': 200
        }
        mock_srs_fn.return_value = mock_srs

        service = GrammarLabService()
        ex = grammar_exercises[0]
        result = service.submit_answer(ex.id, test_user.id, 'am')
        assert result['xp_earned'] == GRAMMAR_XP['exercise_correct'] + GRAMMAR_XP['exercise_mastered']

    @patch('app.grammar_lab.services.grammar_lab_service._get_unified_srs_service')
    def test_records_attempt(self, mock_srs_fn, app, db_session, test_user,
                             grammar_topic, grammar_exercises):
        mock_srs = MagicMock()
        mock_srs.grade_grammar_exercise.return_value = {
            'success': True, 'state': 'learning', 'interval': 0
        }
        mock_srs_fn.return_value = mock_srs

        service = GrammarLabService()
        ex = grammar_exercises[0]
        service.submit_answer(ex.id, test_user.id, 'am', session_id='sess1', time_spent=5)

        attempt = GrammarAttempt.query.filter_by(
            user_id=test_user.id, exercise_id=ex.id
        ).first()
        assert attempt is not None
        assert attempt.is_correct is True
        assert attempt.session_id == 'sess1'
        assert attempt.time_spent == 5


class TestGrammarLabServiceStartTopicPractice:
    @patch('app.grammar_lab.services.grammar_lab_service._get_unified_srs_service')
    def test_success(self, mock_srs_fn, app, db_session, test_user,
                     grammar_topic, grammar_exercises):
        mock_srs = MagicMock()
        mock_srs.get_or_create_grammar_exercise_progress.return_value = None
        mock_srs.reset_grammar_session_attempts.return_value = None
        mock_srs_fn.return_value = mock_srs

        service = GrammarLabService()
        result = service.start_topic_practice(grammar_topic.id, test_user.id)
        assert 'session_id' in result
        assert 'exercises' in result
        assert result['total_exercises'] > 0
        assert result['topic']['slug'] == grammar_topic.slug

    @patch('app.grammar_lab.services.grammar_lab_service._get_unified_srs_service')
    def test_nonexistent_topic(self, mock_srs_fn, app, db_session, test_user):
        service = GrammarLabService()
        result = service.start_topic_practice(999999, test_user.id)
        assert 'error' in result

    @patch('app.grammar_lab.services.grammar_lab_service._get_unified_srs_service')
    def test_max_exercises_limit(self, mock_srs_fn, app, db_session, test_user,
                                 grammar_topic, grammar_exercises):
        mock_srs = MagicMock()
        mock_srs.get_or_create_grammar_exercise_progress.return_value = None
        mock_srs.reset_grammar_session_attempts.return_value = None
        mock_srs_fn.return_value = mock_srs

        service = GrammarLabService()
        result = service.start_topic_practice(grammar_topic.id, test_user.id, max_exercises=2)
        assert result['total_exercises'] <= 2


class TestGrammarLabServiceGetUserStats:
    def test_returns_stats(self, app, db_session, test_user):
        service = GrammarLabService()
        stats = service.get_user_stats(test_user.id)
        assert 'total_topics' in stats
        assert 'by_level' in stats


class TestGrammarLabServiceGetPracticeSession:
    @patch('app.grammar_lab.services.grammar_lab_service._get_unified_srs_service')
    def test_empty(self, mock_srs_fn, app, db_session, test_user):
        mock_srs = MagicMock()
        mock_srs.get_or_create_grammar_exercise_progress.return_value = None
        mock_srs_fn.return_value = mock_srs

        service = GrammarLabService()
        # With non-existent topic IDs
        result = service.get_practice_session(test_user.id, topic_ids=[999999])
        assert result['total_exercises'] == 0

    @patch('app.grammar_lab.services.grammar_lab_service._get_unified_srs_service')
    def test_with_exercises(self, mock_srs_fn, app, db_session, test_user,
                            grammar_topic, grammar_exercises):
        mock_srs = MagicMock()
        mock_srs.get_or_create_grammar_exercise_progress.return_value = None
        mock_srs_fn.return_value = mock_srs

        service = GrammarLabService()
        result = service.get_practice_session(
            test_user.id, topic_ids=[grammar_topic.id], count=3
        )
        assert result['total_exercises'] <= 3
        assert 'session_id' in result
        assert 'stats' in result


class TestGrammarLabServiceGetRecommendations:
    def test_empty(self, app, db_session, test_user):
        service = GrammarLabService()
        recs = service.get_recommendations(test_user.id)
        # Should return new topics if any exist
        assert isinstance(recs, list)

    def test_with_topic(self, app, db_session, test_user, grammar_topic, grammar_exercises):
        service = GrammarLabService()
        recs = service.get_recommendations(test_user.id)
        assert len(recs) >= 1


# ============================================================
# Model Tests
# ============================================================

class TestUserGrammarExerciseModel:
    def test_create(self, db_session, test_user, grammar_exercises):
        progress = UserGrammarExercise(
            user_id=test_user.id, exercise_id=grammar_exercises[0].id
        )
        db_session.add(progress)
        db_session.commit()
        assert progress.state == 'new'
        assert progress.ease_factor == 2.5
        assert progress.interval == 0

    def test_is_due(self, db_session, test_user, grammar_exercises):
        progress = UserGrammarExercise(
            user_id=test_user.id, exercise_id=grammar_exercises[0].id
        )
        progress.next_review = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.add(progress)
        db_session.commit()
        assert progress.is_due is True

    def test_not_due(self, db_session, test_user, grammar_exercises):
        progress = UserGrammarExercise(
            user_id=test_user.id, exercise_id=grammar_exercises[0].id
        )
        progress.state = 'review'
        progress.next_review = datetime.now(timezone.utc) + timedelta(days=1)
        db_session.add(progress)
        db_session.commit()
        assert progress.is_due is False

    def test_is_buried(self, db_session, test_user, grammar_exercises):
        progress = UserGrammarExercise(
            user_id=test_user.id, exercise_id=grammar_exercises[0].id
        )
        progress.bury(hours=24)
        db_session.add(progress)
        db_session.commit()
        assert progress.is_buried is True

    def test_unbury(self, db_session, test_user, grammar_exercises):
        progress = UserGrammarExercise(
            user_id=test_user.id, exercise_id=grammar_exercises[0].id
        )
        progress.bury()
        progress.unbury()
        db_session.add(progress)
        db_session.commit()
        assert progress.is_buried is False

    def test_is_mature(self, db_session, test_user, grammar_exercises):
        progress = UserGrammarExercise(
            user_id=test_user.id, exercise_id=grammar_exercises[0].id
        )
        progress.state = 'review'
        progress.interval = 25
        assert progress.is_mature is True

    def test_is_mastered(self, db_session, test_user, grammar_exercises):
        progress = UserGrammarExercise(
            user_id=test_user.id, exercise_id=grammar_exercises[0].id
        )
        progress.state = 'review'
        progress.interval = 200
        assert progress.is_mastered is True

    def test_accuracy(self, db_session, test_user, grammar_exercises):
        progress = UserGrammarExercise(
            user_id=test_user.id, exercise_id=grammar_exercises[0].id
        )
        progress.correct_count = 7
        progress.incorrect_count = 3
        assert progress.accuracy == 70.0

    def test_accuracy_zero(self, db_session, test_user, grammar_exercises):
        progress = UserGrammarExercise(
            user_id=test_user.id, exercise_id=grammar_exercises[0].id
        )
        assert progress.accuracy == 0.0

    def test_get_or_create(self, db_session, test_user, grammar_exercises):
        p1 = UserGrammarExercise.get_or_create(test_user.id, grammar_exercises[0].id)
        db_session.commit()
        p2 = UserGrammarExercise.get_or_create(test_user.id, grammar_exercises[0].id)
        assert p1.id == p2.id

    def test_to_dict(self, db_session, test_user, grammar_exercises):
        progress = UserGrammarExercise(
            user_id=test_user.id, exercise_id=grammar_exercises[0].id
        )
        db_session.add(progress)
        db_session.commit()
        d = progress.to_dict()
        assert 'state' in d
        assert 'ease_factor' in d
        assert 'is_due' in d
        assert 'accuracy' in d


class TestUserGrammarTopicStatusModel:
    def test_get_or_create(self, db_session, test_user, grammar_topic):
        s1 = UserGrammarTopicStatus.get_or_create(test_user.id, grammar_topic.id)
        db_session.commit()
        s2 = UserGrammarTopicStatus.get_or_create(test_user.id, grammar_topic.id)
        assert s1.id == s2.id

    def test_add_xp(self, db_session, test_user, grammar_topic):
        status = UserGrammarTopicStatus.get_or_create(test_user.id, grammar_topic.id)
        status.add_xp(10)
        status.add_xp(20)
        assert status.xp_earned == 30

    def test_to_dict(self, db_session, test_user, grammar_topic):
        status = UserGrammarTopicStatus.get_or_create(test_user.id, grammar_topic.id)
        db_session.commit()
        d = status.to_dict()
        assert d['theory_completed'] is False
        assert d['xp_earned'] == 0


class TestGrammarTopicModel:
    def test_to_dict(self, db_session, grammar_topic, grammar_exercises):
        d = grammar_topic.to_dict()
        assert d['slug'] == grammar_topic.slug
        assert d['exercise_count'] == len(grammar_exercises)
        assert 'content' not in d

    def test_to_dict_with_content(self, db_session, grammar_topic):
        d = grammar_topic.to_dict(include_content=True)
        assert 'content' in d
        assert d['content']['introduction'] == 'Test intro'


class TestGrammarExerciseModel:
    def test_to_dict_hides_answer(self, db_session, grammar_exercises):
        d = grammar_exercises[0].to_dict(hide_answer=True)
        assert 'correct_answer' not in d

    def test_to_dict_shows_answer(self, db_session, grammar_exercises):
        d = grammar_exercises[0].to_dict(hide_answer=False)
        assert 'correct_answer' in d

    def test_reorder_has_words(self, db_session, grammar_exercises):
        reorder = grammar_exercises[2]
        d = reorder.to_dict()
        assert 'words' in d

    def test_matching_has_pairs(self, db_session, grammar_exercises):
        matching = grammar_exercises[6]
        d = matching.to_dict()
        assert 'pairs' in d

    def test_translation_has_sentence(self, db_session, grammar_exercises):
        translation = grammar_exercises[5]
        d = translation.to_dict()
        assert 'sentence' in d