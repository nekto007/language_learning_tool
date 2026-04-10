"""
Tests for study stats chart data aggregation (Task 11).
Covers: StatsService.get_accuracy_trend, get_mastered_over_time, get_study_heatmap,
        /study/stats route with chart data, /study/ most_urgent_deck, session summary streak.
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from freezegun import freeze_time

from app.study.models import (
    StudySession, UserWord, UserCardDirection, QuizDeck, QuizDeckWord, StudySettings
)
from app.study.services.stats_service import StatsService
from app.utils.db import db


@pytest.fixture
def study_sessions(db_session, test_user):
    """Create study sessions across multiple days with varying accuracy."""
    sessions = []
    base = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
    data = [
        # (day_offset, correct, incorrect, words_studied, hour)
        (0, 8, 2, 10, 10),
        (0, 6, 4, 10, 14),
        (1, 9, 1, 10, 9),
        (3, 7, 3, 10, 11),
        (5, 10, 0, 10, 16),
        (7, 5, 5, 10, 8),   # Monday morning
    ]
    for day_off, correct, incorrect, words, hour in data:
        s = StudySession(
            user_id=test_user.id,
            session_type='cards',
            start_time=base + timedelta(days=day_off, hours=hour - 10),
            end_time=base + timedelta(days=day_off, hours=hour - 10, minutes=15),
            words_studied=words,
            correct_answers=correct,
            incorrect_answers=incorrect,
        )
        db_session.add(s)
        sessions.append(s)
    db_session.commit()
    return sessions


@pytest.fixture
def mastered_cards(db_session, test_user, test_words_list):
    """Create UserWord + UserCardDirection in mastered state."""
    cards = []
    base = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
    for i, word in enumerate(test_words_list[:5]):
        uw = UserWord(user_id=test_user.id, word_id=word.id)
        uw.status = 'review'
        db_session.add(uw)
        db_session.flush()
        ucd = UserCardDirection(
            user_word_id=uw.id,
            direction='eng-rus',
        )
        ucd.state = 'review'
        ucd.interval = UserWord.MASTERED_THRESHOLD_DAYS + 1
        ucd.last_reviewed = base + timedelta(days=i)
        ucd.first_reviewed = base - timedelta(days=30)
        db_session.add(ucd)
        cards.append(ucd)
    db_session.commit()
    return cards


class TestAccuracyTrend:
    """Tests for StatsService.get_accuracy_trend"""

    @freeze_time("2026-04-10 12:00:00")
    def test_returns_daily_accuracy(self, app, db_session, test_user, study_sessions):
        result = StatsService.get_accuracy_trend(test_user.id)
        assert len(result) > 0
        for entry in result:
            assert 'date' in entry
            assert 'accuracy' in entry
            assert 0 <= entry['accuracy'] <= 100

    @freeze_time("2026-04-10 12:00:00")
    def test_aggregates_multiple_sessions_per_day(self, app, db_session, test_user, study_sessions):
        result = StatsService.get_accuracy_trend(test_user.id)
        # Day 0 (2026-04-01) has 2 sessions: 8+6=14 correct, 2+4=6 incorrect, total=20
        day1 = next((d for d in result if d['date'] == '2026-04-01'), None)
        assert day1 is not None
        assert day1['accuracy'] == 70  # 14/20 * 100
        assert day1['total'] == 20

    @freeze_time("2026-04-10 12:00:00")
    def test_empty_for_no_sessions(self, app, db_session, test_user):
        result = StatsService.get_accuracy_trend(test_user.id)
        assert result == []

    @freeze_time("2026-04-10 12:00:00")
    def test_sorted_by_date(self, app, db_session, test_user, study_sessions):
        result = StatsService.get_accuracy_trend(test_user.id)
        dates = [entry['date'] for entry in result]
        assert dates == sorted(dates)


class TestMasteredOverTime:
    """Tests for StatsService.get_mastered_over_time"""

    @freeze_time("2026-04-10 12:00:00")
    def test_returns_mastered_counts(self, app, db_session, test_user, mastered_cards):
        result = StatsService.get_mastered_over_time(test_user.id)
        assert len(result) > 0
        total_mastered = sum(d['count'] for d in result)
        assert total_mastered == 5  # 5 mastered cards

    @freeze_time("2026-04-10 12:00:00")
    def test_empty_when_no_mastered(self, app, db_session, test_user):
        result = StatsService.get_mastered_over_time(test_user.id)
        assert result == []

    @freeze_time("2026-04-10 12:00:00")
    def test_sorted_by_date(self, app, db_session, test_user, mastered_cards):
        result = StatsService.get_mastered_over_time(test_user.id)
        dates = [entry['date'] for entry in result]
        assert dates == sorted(dates)


class TestStudyHeatmap:
    """Tests for StatsService.get_study_heatmap"""

    @freeze_time("2026-04-10 12:00:00")
    def test_returns_heatmap_structure(self, app, db_session, test_user, study_sessions):
        result = StatsService.get_study_heatmap(test_user.id)
        assert 'day_names' in result
        assert 'data' in result
        assert len(result['day_names']) == 7

    @freeze_time("2026-04-10 12:00:00")
    def test_data_points_have_correct_format(self, app, db_session, test_user, study_sessions):
        result = StatsService.get_study_heatmap(test_user.id)
        for point in result['data']:
            assert 'x' in point  # hour
            assert 'y' in point  # day of week
            assert 'v' in point  # count
            assert 0 <= point['x'] <= 23
            assert 0 <= point['y'] <= 6
            assert point['v'] > 0

    @freeze_time("2026-04-10 12:00:00")
    def test_empty_when_no_sessions(self, app, db_session, test_user):
        result = StatsService.get_study_heatmap(test_user.id)
        assert result['data'] == []


class TestStatsRoute:
    """Test /study/stats route includes chart data."""

    def test_stats_page_renders(self, authenticated_client, study_settings):
        response = authenticated_client.get('/study/stats')
        assert response.status_code == 200

    def test_stats_page_with_sessions(self, authenticated_client, study_settings, study_sessions):
        response = authenticated_client.get('/study/stats')
        assert response.status_code == 200
        # Chart.js should be included
        assert b'chart.js' in response.data


class TestStudyNowButton:
    """Test most_urgent_deck computation on /study/ index."""

    def test_most_urgent_deck_shown(self, authenticated_client, db_session, test_user,
                                     study_settings, test_words_list):
        """When a deck has due cards, Study Now button appears."""
        deck = QuizDeck(user_id=test_user.id, title='Urgent Deck')
        db_session.add(deck)
        db_session.flush()

        # Add words to deck and create user words with learning state
        for word in test_words_list[:3]:
            dw = QuizDeckWord(deck_id=deck.id, word_id=word.id)
            db_session.add(dw)
            uw = UserWord(user_id=test_user.id, word_id=word.id)
            uw.status = 'learning'
            db_session.add(uw)
            db_session.flush()
            ucd = UserCardDirection(
                user_word_id=uw.id,
                direction='eng-rus',
            )
            ucd.state = 'learning'
            ucd.next_review = datetime.now(timezone.utc) - timedelta(hours=1)
            db_session.add(ucd)
        db_session.commit()

        response = authenticated_client.get('/study/')
        assert response.status_code == 200
        assert 'Пора повторять'.encode() in response.data

    def test_no_urgent_deck_when_all_mastered(self, authenticated_client, study_settings):
        """When no decks have due cards, Study Now block is absent."""
        response = authenticated_client.get('/study/')
        assert response.status_code == 200
        assert 'Пора повторять'.encode() not in response.data


class TestAutoDeckBadge:
    """Test auto-deck visual distinction."""

    def test_auto_deck_shows_badge(self, authenticated_client, db_session, test_user,
                                    study_settings):
        """Auto-generated deck shows 'авто' badge."""
        deck = QuizDeck(user_id=test_user.id, title='Топик: Animals')
        db_session.add(deck)
        db_session.commit()

        response = authenticated_client.get('/study/')
        assert response.status_code == 200
        html = response.data.decode()
        assert '>авто</span>' in html

    def test_custom_deck_no_auto_badge(self, authenticated_client, db_session, test_user,
                                        study_settings):
        """Custom deck does not show 'авто' badge."""
        deck = QuizDeck(user_id=test_user.id, title='My Custom Deck')
        db_session.add(deck)
        db_session.commit()

        response = authenticated_client.get('/study/')
        assert response.status_code == 200
        html = response.data.decode()
        assert '>авто</span>' not in html


class TestSessionSummaryStreak:
    """Test that complete-session API returns streak data."""

    def test_complete_session_returns_streak(self, authenticated_client, db_session, test_user):
        """Complete session response includes streak count."""
        from app.achievements.models import UserStatistics

        # Create UserStatistics with streak
        stats = UserStatistics(user_id=test_user.id, current_streak_days=5)
        db_session.add(stats)

        # Create a study session
        session = StudySession(
            user_id=test_user.id,
            session_type='cards',
            start_time=datetime.now(timezone.utc),
            words_studied=10,
            correct_answers=8,
            incorrect_answers=2,
        )
        db_session.add(session)
        db_session.commit()

        response = authenticated_client.post(
            '/study/api/complete-session',
            json={'session_id': session.id},
            content_type='application/json',
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['streak'] == 5

    def test_complete_session_zero_streak(self, authenticated_client, db_session, test_user):
        """Complete session with no UserStatistics returns 0 streak."""
        session = StudySession(
            user_id=test_user.id,
            session_type='cards',
            start_time=datetime.now(timezone.utc),
            words_studied=5,
            correct_answers=3,
            incorrect_answers=2,
        )
        db_session.add(session)
        db_session.commit()

        response = authenticated_client.post(
            '/study/api/complete-session',
            json={'session_id': session.id},
            content_type='application/json',
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['streak'] == 0
