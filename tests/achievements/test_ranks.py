"""Unit tests for the daily plan rank/title system."""
import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.achievements.models import StreakEvent, UserStatistics
from app.achievements.ranks import (
    RANK_THRESHOLDS,
    RankInfo,
    RankUp,
    check_rank_up,
    get_rank_code,
    get_rank_name,
    get_user_rank,
    is_rank_up,
    record_plan_completion,
)
from app.auth.models import User
from app.notifications.models import Notification


class TestRankThresholds:
    """RANK_THRESHOLDS list invariants."""

    def test_starts_at_zero(self):
        assert RANK_THRESHOLDS[0][0] == 0

    def test_thresholds_strictly_increasing(self):
        thresholds = [t for t, _, _ in RANK_THRESHOLDS]
        for prev, nxt in zip(thresholds, thresholds[1:]):
            assert nxt > prev

    def test_codes_unique(self):
        codes = [c for _, c, _ in RANK_THRESHOLDS]
        assert len(codes) == len(set(codes))

    def test_seven_ranks_defined(self):
        assert len(RANK_THRESHOLDS) == 7
        names = {n for _, _, n in RANK_THRESHOLDS}
        assert names == {
            'Novice', 'Explorer', 'Student', 'Expert',
            'Master', 'Legend', 'Grandmaster',
        }


class TestGetUserRankBoundaries:
    """Rank boundaries for the documented thresholds."""

    def test_zero_plans_is_novice(self):
        info = get_user_rank(0)
        assert info.code == 'novice'
        assert info.name == 'Novice'
        assert info.threshold == 0
        assert info.next_threshold == 7

    def test_one_below_first_threshold_still_novice(self):
        assert get_user_rank(6).code == 'novice'

    def test_exact_first_threshold_promotes_to_explorer(self):
        info = get_user_rank(7)
        assert info.code == 'explorer'
        assert info.threshold == 7
        assert info.plans_to_next == 14  # 21 - 7

    def test_exact_student_threshold(self):
        info = get_user_rank(21)
        assert info.code == 'student'
        assert info.next_code == 'expert'
        assert info.next_threshold == 50

    def test_between_thresholds_keeps_lower_rank(self):
        # 49 is just below the expert threshold (50) -> still student
        assert get_user_rank(49).code == 'student'

    def test_exact_expert_threshold(self):
        assert get_user_rank(50).code == 'expert'

    def test_exact_master_threshold(self):
        assert get_user_rank(100).code == 'master'

    def test_exact_legend_threshold(self):
        assert get_user_rank(200).code == 'legend'

    def test_exact_grandmaster_threshold(self):
        info = get_user_rank(365)
        assert info.code == 'grandmaster'
        assert info.next_code is None
        assert info.next_threshold is None
        assert info.plans_to_next is None
        assert info.progress_percent == 100.0

    def test_far_above_grandmaster_stays_grandmaster(self):
        info = get_user_rank(10_000)
        assert info.code == 'grandmaster'
        assert info.next_code is None


class TestProgressPercent:
    """Progress percent reflects how far inside the current rank band the user is."""

    def test_progress_at_band_start_is_zero(self):
        info = get_user_rank(7)  # exactly at explorer start
        assert info.progress_percent == 0.0

    def test_progress_at_band_midpoint(self):
        # explorer band: [7, 21), span = 14, halfway = 14
        info = get_user_rank(14)
        # within = 7, span = 14 -> 50%
        assert info.progress_percent == 50.0

    def test_progress_at_band_end(self):
        # one short of student threshold: 21-1 = 20 within explorer band [7,21)
        info = get_user_rank(20)
        # within = 13, span = 14 -> ~92.9%
        assert 92.0 <= info.progress_percent <= 93.5

    def test_progress_for_grandmaster_is_full(self):
        assert get_user_rank(365).progress_percent == 100.0


class TestNegativeAndNoneInputs:
    """Defensive normalization of bad inputs."""

    def test_negative_input_normalized_to_novice(self):
        info = get_user_rank(-5)
        assert info.code == 'novice'
        assert info.plans_completed == 0

    def test_none_input_normalized_to_novice(self):
        info = get_user_rank(None)  # type: ignore[arg-type]
        assert info.code == 'novice'
        assert info.plans_completed == 0


class TestHelpers:
    """Helpers around rank lookup."""

    def test_get_rank_code(self):
        assert get_rank_code(0) == 'novice'
        assert get_rank_code(7) == 'explorer'
        assert get_rank_code(365) == 'grandmaster'

    def test_get_rank_name(self):
        assert get_rank_name(0) == 'Novice'
        assert get_rank_name(50) == 'Expert'

    def test_is_rank_up_detects_promotion(self):
        assert is_rank_up(6, 7) is True

    def test_is_rank_up_within_band_false(self):
        assert is_rank_up(7, 8) is False

    def test_is_rank_up_no_change_false(self):
        assert is_rank_up(50, 50) is False

    def test_is_rank_up_negative_delta_false(self):
        assert is_rank_up(50, 21) is False

    def test_get_user_rank_returns_dataclass(self):
        info = get_user_rank(0)
        assert isinstance(info, RankInfo)


# ---------------------------------------------------------------------------
# Fixtures for progression tests
# ---------------------------------------------------------------------------


@pytest.fixture
def rank_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'rank_{suffix}',
        email=f'rank_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


class TestRecordPlanCompletion:
    """record_plan_completion increments counter, idempotent per day, detects rank-up."""

    def test_first_completion_creates_stats_and_marker(self, db_session, rank_user):
        today = date.today()
        result = record_plan_completion(rank_user.id, for_date=today)
        db_session.flush()

        stats = UserStatistics.query.filter_by(user_id=rank_user.id).one()
        assert stats.plans_completed_total == 1
        assert stats.current_rank == 'novice'
        assert result is None  # within novice band (0 → 1, still novice)

        marker = StreakEvent.query.filter_by(
            user_id=rank_user.id,
            event_type='plan_completed',
            event_date=today,
        ).one()
        assert marker.details['plans_completed_total'] == 1

    def test_second_call_same_date_idempotent(self, db_session, rank_user):
        today = date.today()
        record_plan_completion(rank_user.id, for_date=today)
        db_session.flush()
        result = record_plan_completion(rank_user.id, for_date=today)
        db_session.flush()

        assert result is None
        stats = UserStatistics.query.filter_by(user_id=rank_user.id).one()
        assert stats.plans_completed_total == 1
        markers = StreakEvent.query.filter_by(
            user_id=rank_user.id,
            event_type='plan_completed',
            event_date=today,
        ).count()
        assert markers == 1

    def test_consecutive_days_increment(self, db_session, rank_user):
        d1 = date.today() - timedelta(days=1)
        d2 = date.today()
        record_plan_completion(rank_user.id, for_date=d1)
        db_session.flush()
        record_plan_completion(rank_user.id, for_date=d2)
        db_session.flush()

        stats = UserStatistics.query.filter_by(user_id=rank_user.id).one()
        assert stats.plans_completed_total == 2

    def test_crossing_threshold_returns_rank_up(self, db_session, rank_user):
        """6 completions keep novice; the 7th promotes to explorer."""
        stats = UserStatistics(user_id=rank_user.id, plans_completed_total=6,
                               current_rank='novice')
        db_session.add(stats)
        db_session.flush()

        today = date.today()
        result = record_plan_completion(rank_user.id, for_date=today)
        db_session.flush()

        assert isinstance(result, RankUp)
        assert result.previous_code == 'novice'
        assert result.new_code == 'explorer'
        assert result.plans_completed == 7

        stats = UserStatistics.query.filter_by(user_id=rank_user.id).one()
        assert stats.plans_completed_total == 7
        assert stats.current_rank == 'explorer'

    def test_within_band_no_rank_up(self, db_session, rank_user):
        stats = UserStatistics(user_id=rank_user.id, plans_completed_total=10,
                               current_rank='explorer')
        db_session.add(stats)
        db_session.flush()

        result = record_plan_completion(rank_user.id, for_date=date.today())
        db_session.flush()

        assert result is None
        stats = UserStatistics.query.filter_by(user_id=rank_user.id).one()
        assert stats.plans_completed_total == 11
        assert stats.current_rank == 'explorer'

    def test_grandmaster_threshold_reached(self, db_session, rank_user):
        stats = UserStatistics(user_id=rank_user.id, plans_completed_total=364,
                               current_rank='legend')
        db_session.add(stats)
        db_session.flush()

        result = record_plan_completion(rank_user.id, for_date=date.today())
        db_session.flush()

        assert isinstance(result, RankUp)
        assert result.previous_code == 'legend'
        assert result.new_code == 'grandmaster'


class TestCheckRankUp:
    """check_rank_up detects drift between stored rank and counter."""

    def test_no_stats_returns_none(self, db_session, rank_user):
        assert check_rank_up(rank_user.id) is None

    def test_in_sync_returns_none(self, db_session, rank_user):
        stats = UserStatistics(user_id=rank_user.id, plans_completed_total=25,
                               current_rank='student')
        db_session.add(stats)
        db_session.flush()
        assert check_rank_up(rank_user.id) is None

    def test_stored_rank_stale_returns_rank_up(self, db_session, rank_user):
        """If someone bumped the counter without updating current_rank, detect it."""
        stats = UserStatistics(user_id=rank_user.id, plans_completed_total=50,
                               current_rank='explorer')
        db_session.add(stats)
        db_session.flush()

        result = check_rank_up(rank_user.id)
        assert isinstance(result, RankUp)
        assert result.previous_code == 'explorer'
        assert result.new_code == 'expert'


class TestNotifyRankUp:
    """Rank-up notification is routed through create_notification."""

    def test_notify_rank_up_creates_notification(self, db_session, rank_user):
        from app.notifications.services import notify_rank_up

        notif = notify_rank_up(rank_user.id, 'Explorer')
        db_session.flush()

        assert notif is not None
        assert notif.type == 'rank_up'
        assert 'Explorer' in notif.title
        stored = Notification.query.filter_by(user_id=rank_user.id,
                                              type='rank_up').one()
        assert stored.id == notif.id

    def test_notify_rank_up_respects_preference(self, db_session, rank_user):
        from app.notifications.services import notify_rank_up

        rank_user.notify_in_app_achievements = False
        db_session.flush()

        notif = notify_rank_up(rank_user.id, 'Explorer')
        assert notif is None


class TestStreakServiceIntegration:
    """process_streak_on_activity triggers record_plan_completion on full plans."""

    def test_full_plan_triggers_rank_record(self, db_session, rank_user):
        from app.achievements.streak_service import process_streak_on_activity

        stats = UserStatistics(user_id=rank_user.id, plans_completed_total=6,
                               current_rank='novice')
        db_session.add(stats)
        db_session.flush()

        with patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.achievements.streak_service.get_streak_status', return_value={
                 'streak': 5, 'coins_balance': 0, 'has_activity_today': True,
                 'can_repair': False, 'missed_date': None, 'repair_cost': None,
                 'required_steps': 1, 'steps_total': 4,
             }), \
             patch('app.achievements.streak_service.find_missed_date', return_value=None), \
             patch('app.achievements.streak_service.check_streak_milestone',
                   return_value=None):
            result = process_streak_on_activity(
                rank_user.id, steps_done=4, steps_total=4, tz='UTC',
            )

        assert result['rank_up'] is not None
        assert result['rank_up']['new_code'] == 'explorer'

        refreshed = UserStatistics.query.filter_by(user_id=rank_user.id).one()
        assert refreshed.plans_completed_total == 7
        assert refreshed.current_rank == 'explorer'

        notif = Notification.query.filter_by(user_id=rank_user.id,
                                             type='rank_up').first()
        assert notif is not None
        assert 'Explorer' in notif.title

    def test_partial_plan_does_not_record(self, db_session, rank_user):
        from app.achievements.streak_service import process_streak_on_activity

        with patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.achievements.streak_service.get_streak_status', return_value={
                 'streak': 5, 'coins_balance': 0, 'has_activity_today': True,
                 'can_repair': False, 'missed_date': None, 'repair_cost': None,
                 'required_steps': 1, 'steps_total': 4,
             }), \
             patch('app.achievements.streak_service.find_missed_date', return_value=None), \
             patch('app.achievements.streak_service.check_streak_milestone',
                   return_value=None):
            result = process_streak_on_activity(
                rank_user.id, steps_done=2, steps_total=4, tz='UTC',
            )

        assert result['rank_up'] is None
        stats = UserStatistics.query.filter_by(user_id=rank_user.id).first()
        # May or may not exist, but if it does, should be 0
        if stats:
            assert (stats.plans_completed_total or 0) == 0

    def test_zero_steps_does_not_record(self, db_session, rank_user):
        from app.achievements.streak_service import process_streak_on_activity

        with patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.achievements.streak_service.get_streak_status', return_value={
                 'streak': 0, 'coins_balance': 0, 'has_activity_today': False,
                 'can_repair': False, 'missed_date': None, 'repair_cost': None,
                 'required_steps': 1, 'steps_total': 0,
             }), \
             patch('app.achievements.streak_service.find_missed_date', return_value=None), \
             patch('app.achievements.streak_service.check_streak_milestone',
                   return_value=None):
            result = process_streak_on_activity(
                rank_user.id, steps_done=0, steps_total=0, tz='UTC',
            )

        assert result['rank_up'] is None
