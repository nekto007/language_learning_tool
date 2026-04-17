"""Unit tests for the daily plan rank/title system."""
from app.achievements.ranks import (
    RANK_THRESHOLDS,
    RankInfo,
    get_rank_code,
    get_rank_name,
    get_user_rank,
    is_rank_up,
)


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
