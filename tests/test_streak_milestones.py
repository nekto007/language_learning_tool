"""Tests for streak milestone rewards."""
import pytest
import uuid
from datetime import date
from app.auth.models import User


@pytest.fixture
def milestone_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(username=f'streak_{suffix}', email=f'streak_{suffix}@test.com', active=True)
    user.set_password('test')
    db_session.add(user)
    db_session.commit()
    return user


class TestCheckStreakMilestone:
    """Test milestone detection and reward logic."""

    def test_milestone_at_day_7(self, milestone_user, db_session):
        from app.achievements.streak_service import check_streak_milestone
        result = check_streak_milestone(milestone_user.id, 7)
        db_session.commit()
        assert result is not None
        assert result['streak'] == 7
        assert result['reward'] == 5

    def test_milestone_at_day_30(self, milestone_user, db_session):
        from app.achievements.streak_service import check_streak_milestone
        result = check_streak_milestone(milestone_user.id, 30)
        db_session.commit()
        assert result is not None
        assert result['reward'] == 20

    def test_no_milestone_at_day_5(self, milestone_user, db_session):
        from app.achievements.streak_service import check_streak_milestone
        result = check_streak_milestone(milestone_user.id, 5)
        assert result is None

    def test_milestone_not_awarded_twice(self, milestone_user, db_session):
        from app.achievements.streak_service import check_streak_milestone
        result1 = check_streak_milestone(milestone_user.id, 14)
        db_session.commit()
        result2 = check_streak_milestone(milestone_user.id, 14)
        assert result1 is not None
        assert result2 is None

    def test_milestone_awards_coins(self, milestone_user, db_session):
        from app.achievements.streak_service import check_streak_milestone, get_or_create_coins
        coins_before = get_or_create_coins(milestone_user.id).balance
        check_streak_milestone(milestone_user.id, 100)
        db_session.commit()
        coins_after = get_or_create_coins(milestone_user.id).balance
        assert coins_after - coins_before == 100


class TestGetMilestoneHistory:
    """Test milestone history retrieval."""

    def test_empty_history(self, milestone_user):
        from app.achievements.streak_service import get_milestone_history
        history = get_milestone_history(milestone_user.id)
        assert isinstance(history, list)

    def test_history_after_milestone(self, milestone_user, db_session):
        from app.achievements.streak_service import check_streak_milestone, get_milestone_history
        check_streak_milestone(milestone_user.id, 60)
        db_session.commit()
        history = get_milestone_history(milestone_user.id)
        streaks = [h['streak'] for h in history]
        assert 60 in streaks
