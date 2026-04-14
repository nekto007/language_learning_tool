from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.daily_plan.repair_pressure import (
    FAILURE_CLUSTER_HARD,
    FAILURE_CLUSTER_SOFT,
    GRAMMAR_WEAK_HARD,
    GRAMMAR_WEAK_SOFT,
    OVERDUE_SRS_HARD,
    OVERDUE_SRS_SOFT,
    REPAIR_THRESHOLD,
    WEIGHT_FAILURES,
    WEIGHT_GRAMMAR,
    WEIGHT_OVERDUE,
    RepairBreakdown,
    _normalize,
    calculate_repair_pressure,
)


class TestNormalize:
    def test_zero_value(self):
        assert _normalize(0, 10, 50) == 0.0

    def test_negative_value(self):
        assert _normalize(-5, 10, 50) == 0.0

    def test_at_soft_threshold(self):
        assert _normalize(10, 10, 50) == 0.5

    def test_at_hard_threshold(self):
        assert _normalize(50, 10, 50) == 1.0

    def test_above_hard_threshold(self):
        assert _normalize(100, 10, 50) == 1.0

    def test_below_soft_threshold(self):
        result = _normalize(5, 10, 50)
        assert 0.0 < result < 0.5
        assert result == pytest.approx(5 / 10 * 0.5)

    def test_between_soft_and_hard(self):
        result = _normalize(30, 10, 50)
        assert 0.5 < result < 1.0
        expected = 0.5 + (30 - 10) / (50 - 10) * 0.5
        assert result == pytest.approx(expected)

    def test_value_one(self):
        result = _normalize(1, 15, 50)
        assert result == pytest.approx(1 / 15 * 0.5)


class TestRepairBreakdown:
    def test_dataclass_fields(self):
        bd = RepairBreakdown(
            overdue_srs_count=10,
            overdue_srs_score=0.5,
            grammar_weak_count=3,
            grammar_weak_score=0.3,
            failure_cluster_count=2,
            failure_cluster_score=0.1,
            total_score=0.35,
        )
        assert bd.overdue_srs_count == 10
        assert bd.total_score == 0.35


class TestCalculateRepairPressure:
    @patch("app.daily_plan.repair_pressure._count_failure_clusters", return_value=0)
    @patch("app.daily_plan.repair_pressure._count_grammar_weak_points", return_value=0)
    @patch("app.daily_plan.repair_pressure._count_overdue_srs", return_value=0)
    def test_no_pressure(self, mock_overdue, mock_weak, mock_failures, app):
        with app.app_context():
            result = calculate_repair_pressure(user_id=1)

        assert result.total_score == 0.0
        assert result.overdue_srs_count == 0
        assert result.grammar_weak_count == 0
        assert result.failure_cluster_count == 0

    @patch("app.daily_plan.repair_pressure._count_failure_clusters", return_value=0)
    @patch("app.daily_plan.repair_pressure._count_grammar_weak_points", return_value=0)
    @patch("app.daily_plan.repair_pressure._count_overdue_srs", return_value=5)
    def test_low_overdue_only(self, mock_overdue, mock_weak, mock_failures, app):
        with app.app_context():
            result = calculate_repair_pressure(user_id=1)

        assert result.total_score < REPAIR_THRESHOLD
        assert result.overdue_srs_count == 5
        assert result.overdue_srs_score > 0.0

    @patch("app.daily_plan.repair_pressure._count_failure_clusters", return_value=0)
    @patch("app.daily_plan.repair_pressure._count_grammar_weak_points", return_value=0)
    @patch("app.daily_plan.repair_pressure._count_overdue_srs")
    def test_high_overdue_triggers_repair(self, mock_overdue, mock_weak, mock_failures, app):
        mock_overdue.return_value = OVERDUE_SRS_HARD
        with app.app_context():
            result = calculate_repair_pressure(user_id=1)

        assert result.overdue_srs_score == 1.0
        assert result.total_score == pytest.approx(WEIGHT_OVERDUE)
        assert result.total_score < REPAIR_THRESHOLD

    @patch("app.daily_plan.repair_pressure._count_failure_clusters")
    @patch("app.daily_plan.repair_pressure._count_grammar_weak_points")
    @patch("app.daily_plan.repair_pressure._count_overdue_srs")
    def test_all_signals_high_triggers_repair(self, mock_overdue, mock_weak, mock_failures, app):
        mock_overdue.return_value = OVERDUE_SRS_HARD
        mock_weak.return_value = GRAMMAR_WEAK_HARD
        mock_failures.return_value = FAILURE_CLUSTER_HARD
        with app.app_context():
            result = calculate_repair_pressure(user_id=1)

        assert result.total_score == 1.0
        assert result.total_score >= REPAIR_THRESHOLD

    @patch("app.daily_plan.repair_pressure._count_failure_clusters")
    @patch("app.daily_plan.repair_pressure._count_grammar_weak_points")
    @patch("app.daily_plan.repair_pressure._count_overdue_srs")
    def test_moderate_pressure_below_threshold(self, mock_overdue, mock_weak, mock_failures, app):
        mock_overdue.return_value = OVERDUE_SRS_SOFT
        mock_weak.return_value = 1
        mock_failures.return_value = 2
        with app.app_context():
            result = calculate_repair_pressure(user_id=1)

        assert result.total_score > 0.0
        assert result.total_score < REPAIR_THRESHOLD

    @patch("app.daily_plan.repair_pressure._count_failure_clusters")
    @patch("app.daily_plan.repair_pressure._count_grammar_weak_points")
    @patch("app.daily_plan.repair_pressure._count_overdue_srs")
    def test_combined_moderate_signals_can_trigger(self, mock_overdue, mock_weak, mock_failures, app):
        mock_overdue.return_value = OVERDUE_SRS_HARD
        mock_weak.return_value = GRAMMAR_WEAK_HARD
        mock_failures.return_value = 0
        with app.app_context():
            result = calculate_repair_pressure(user_id=1)

        expected = WEIGHT_OVERDUE * 1.0 + WEIGHT_GRAMMAR * 1.0
        assert result.total_score == pytest.approx(expected, abs=0.01)
        assert result.total_score >= REPAIR_THRESHOLD

    @patch("app.daily_plan.repair_pressure._count_failure_clusters", return_value=0)
    @patch("app.daily_plan.repair_pressure._count_grammar_weak_points")
    @patch("app.daily_plan.repair_pressure._count_overdue_srs", return_value=0)
    def test_grammar_only_high(self, mock_overdue, mock_weak, mock_failures, app):
        mock_weak.return_value = GRAMMAR_WEAK_HARD
        with app.app_context():
            result = calculate_repair_pressure(user_id=1)

        assert result.grammar_weak_score == 1.0
        assert result.total_score == pytest.approx(WEIGHT_GRAMMAR)

    @patch("app.daily_plan.repair_pressure._count_failure_clusters")
    @patch("app.daily_plan.repair_pressure._count_grammar_weak_points", return_value=0)
    @patch("app.daily_plan.repair_pressure._count_overdue_srs", return_value=0)
    def test_failures_only_high(self, mock_overdue, mock_weak, mock_failures, app):
        mock_failures.return_value = FAILURE_CLUSTER_HARD
        with app.app_context():
            result = calculate_repair_pressure(user_id=1)

        assert result.failure_cluster_score == 1.0
        assert result.total_score == pytest.approx(WEIGHT_FAILURES)

    @patch("app.daily_plan.repair_pressure._count_failure_clusters")
    @patch("app.daily_plan.repair_pressure._count_grammar_weak_points")
    @patch("app.daily_plan.repair_pressure._count_overdue_srs")
    def test_score_capped_at_one(self, mock_overdue, mock_weak, mock_failures, app):
        mock_overdue.return_value = 999
        mock_weak.return_value = 999
        mock_failures.return_value = 999
        with app.app_context():
            result = calculate_repair_pressure(user_id=1)

        assert result.total_score <= 1.0

    @patch("app.daily_plan.repair_pressure._count_failure_clusters", return_value=0)
    @patch("app.daily_plan.repair_pressure._count_grammar_weak_points", return_value=0)
    @patch("app.daily_plan.repair_pressure._count_overdue_srs", return_value=0)
    def test_tz_parameter_accepted(self, mock_overdue, mock_weak, mock_failures, app):
        with app.app_context():
            result = calculate_repair_pressure(user_id=1, tz="Europe/Moscow")

        assert result.total_score == 0.0

    def test_weights_sum_to_one(self):
        total = WEIGHT_OVERDUE + WEIGHT_GRAMMAR + WEIGHT_FAILURES
        assert total == pytest.approx(1.0)

    def test_repair_threshold_in_range(self):
        assert 0.0 < REPAIR_THRESHOLD < 1.0


class TestCalculateRepairPressureWithDB:
    def test_no_data_returns_zero(self, app, db_session, test_user):
        result = calculate_repair_pressure(user_id=test_user.id)
        assert result.total_score == 0.0
        assert result.overdue_srs_count == 0
        assert result.grammar_weak_count == 0
        assert result.failure_cluster_count == 0

    def test_overdue_cards_counted(self, app, db_session, test_user):
        from app.study.models import UserWord, UserCardDirection
        from app.words.models import CollectionWords
        import uuid

        past = datetime.now(timezone.utc) - timedelta(days=2)
        for i in range(20):
            word = CollectionWords(english_word=f"repair_test_{uuid.uuid4().hex[:8]}")
            db_session.add(word)
            db_session.flush()
            uw = UserWord(user_id=test_user.id, word_id=word.id)
            db_session.add(uw)
            db_session.flush()
            card = UserCardDirection(user_word_id=uw.id, direction="eng-rus")
            card.state = "review"
            card.next_review = past
            db_session.add(card)
        db_session.flush()

        result = calculate_repair_pressure(user_id=test_user.id)
        assert result.overdue_srs_count == 20
        assert result.overdue_srs_score > 0.0

    def test_grammar_relearning_counted(self, app, db_session, test_user):
        from app.grammar_lab.models import GrammarTopic, GrammarExercise, UserGrammarExercise
        import uuid

        slug = uuid.uuid4().hex[:8]
        topic = GrammarTopic(
            title=f"Test Topic {slug}",
            title_ru=f"Тестовая тема {slug}",
            slug=slug,
            level="A1",
            order=1,
        )
        db_session.add(topic)
        db_session.flush()

        for i in range(5):
            ex = GrammarExercise(
                topic_id=topic.id,
                exercise_type="fill_blank",
                content={"question": f"test {i}", "correct_answer": f"answer {i}"},
            )
            db_session.add(ex)
            db_session.flush()
            uge = UserGrammarExercise(user_id=test_user.id, exercise_id=ex.id)
            uge.state = "relearning"
            uge.next_review = datetime.now(timezone.utc) - timedelta(hours=1)
            db_session.add(uge)
        db_session.flush()

        result = calculate_repair_pressure(user_id=test_user.id)
        assert result.grammar_weak_count == 5
        assert result.grammar_weak_score > 0.0

    def test_recent_failures_counted(self, app, db_session, test_user):
        from app.grammar_lab.models import GrammarTopic, GrammarExercise, GrammarAttempt
        import uuid

        slug = uuid.uuid4().hex[:8]
        topic = GrammarTopic(
            title=f"Test Topic {slug}",
            title_ru=f"Тестовая тема {slug}",
            slug=slug,
            level="A1",
            order=1,
        )
        db_session.add(topic)
        db_session.flush()

        ex = GrammarExercise(
            topic_id=topic.id,
            exercise_type="fill_blank",
            content={"question": "test", "correct_answer": "answer"},
        )
        db_session.add(ex)
        db_session.flush()

        recent = datetime.now(timezone.utc) - timedelta(hours=12)
        for i in range(8):
            attempt = GrammarAttempt(
                user_id=test_user.id,
                exercise_id=ex.id,
                is_correct=False,
                user_answer=f"wrong {i}",
            )
            attempt.created_at = recent
            db_session.add(attempt)
        db_session.flush()

        result = calculate_repair_pressure(user_id=test_user.id)
        assert result.failure_cluster_count == 8
        assert result.failure_cluster_score > 0.0

    def test_old_failures_not_counted(self, app, db_session, test_user):
        from app.grammar_lab.models import GrammarTopic, GrammarExercise, GrammarAttempt
        import uuid

        slug = uuid.uuid4().hex[:8]
        topic = GrammarTopic(
            title=f"Test Topic {slug}",
            title_ru=f"Тестовая тема {slug}",
            slug=slug,
            level="A1",
            order=1,
        )
        db_session.add(topic)
        db_session.flush()

        ex = GrammarExercise(
            topic_id=topic.id,
            exercise_type="fill_blank",
            content={"question": "test", "correct_answer": "answer"},
        )
        db_session.add(ex)
        db_session.flush()

        old = datetime.now(timezone.utc) - timedelta(days=10)
        for i in range(10):
            attempt = GrammarAttempt(
                user_id=test_user.id,
                exercise_id=ex.id,
                is_correct=False,
                user_answer=f"wrong {i}",
            )
            attempt.created_at = old
            db_session.add(attempt)
        db_session.flush()

        result = calculate_repair_pressure(user_id=test_user.id)
        assert result.failure_cluster_count == 0
