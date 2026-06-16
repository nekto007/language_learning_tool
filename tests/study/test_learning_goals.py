"""Tests for Task 63: Learning goals settings page.

Covers:
- default values on the User model
- setting daily_word_goal / weekly_lesson_goal on the User model
"""
from __future__ import annotations

from app.auth.models import User


class TestLearningGoalsModel:
    def test_default_daily_word_goal(self, test_user):
        assert test_user.daily_word_goal == 10

    def test_default_weekly_lesson_goal(self, test_user):
        assert test_user.weekly_lesson_goal == 5

    def test_set_daily_word_goal(self, db_session, test_user):
        test_user.daily_word_goal = 15
        db_session.commit()
        refreshed = db_session.get(User, test_user.id)
        assert refreshed.daily_word_goal == 15

    def test_set_weekly_lesson_goal(self, db_session, test_user):
        test_user.weekly_lesson_goal = 7
        db_session.commit()
        refreshed = db_session.get(User, test_user.id)
        assert refreshed.weekly_lesson_goal == 7
