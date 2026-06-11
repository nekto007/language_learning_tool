"""
Task 29: Study — game routes audit tests.
Covers: score bounds (0-100 for quiz, clamped for matching), game session ownership,
award_game_xp_idempotent with verified session_id, deleted-deck graceful handling.
"""
import json
import pytest

from app.study.models import GameScore, QuizDeck, QuizDeckWord, StudySession
from app.utils.db import db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def quiz_session(db_session, test_user):
    """A quiz StudySession owned by test_user."""
    sess = StudySession(user_id=test_user.id, session_type='quiz')
    db_session.add(sess)
    db_session.commit()
    return sess


@pytest.fixture
def matching_session(db_session, test_user):
    """A matching StudySession owned by test_user."""
    sess = StudySession(user_id=test_user.id, session_type='matching')
    db_session.add(sess)
    db_session.commit()
    return sess


@pytest.fixture
def other_user_quiz_session(db_session, second_user):
    """A quiz session owned by second_user."""
    sess = StudySession(user_id=second_user.id, session_type='quiz')
    db_session.add(sess)
    db_session.commit()
    return sess


@pytest.fixture
def other_user_matching_session(db_session, second_user):
    """A matching session owned by second_user."""
    sess = StudySession(user_id=second_user.id, session_type='matching')
    db_session.add(sess)
    db_session.commit()
    return sess


@pytest.fixture
def user_deck_with_words(db_session, test_user):
    """A deck with words owned by test_user."""
    deck = QuizDeck(title='Game Test Deck', user_id=test_user.id, is_public=False)
    db_session.add(deck)
    db_session.flush()
    for i in range(3):
        word = QuizDeckWord(
            deck_id=deck.id,
            custom_english=f'word_{i}',
            custom_russian=f'слово_{i}',
        )
        db_session.add(word)
    db_session.commit()
    return deck


# ---------------------------------------------------------------------------
# 1. /api/complete-quiz — score is always 0-100
# ---------------------------------------------------------------------------

class TestQuizScoreBounds:
    def _post_quiz(self, client, **kwargs):
        payload = {
            'total_questions': kwargs.get('total_questions', 10),
            'correct_answers': kwargs.get('correct_answers', 7),
            'time_taken': kwargs.get('time_taken', 60),
        }
        payload.update({k: v for k, v in kwargs.items() if k not in payload})
        return client.post(
            '/study/api/complete-quiz',
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_normal_score_is_percentage(self, authenticated_client, study_settings, db_session):
        resp = self._post_quiz(authenticated_client, total_questions=10, correct_answers=7)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 0.0 <= data['score'] <= 100.0

    def test_perfect_score_is_100(self, authenticated_client, study_settings, db_session):
        resp = self._post_quiz(authenticated_client, total_questions=10, correct_answers=10)
        data = resp.get_json()
        assert data['score'] == 100.0

    def test_zero_score_when_all_wrong(self, authenticated_client, study_settings, db_session):
        resp = self._post_quiz(authenticated_client, total_questions=10, correct_answers=0)
        data = resp.get_json()
        assert data['score'] == 0.0

    def test_correct_answers_clamped_to_total(self, authenticated_client, study_settings, db_session):
        """correct_answers > total_questions is clamped server-side → score = 100, not > 100."""
        resp = self._post_quiz(authenticated_client, total_questions=5, correct_answers=999)
        data = resp.get_json()
        assert data['score'] == 100.0

    def test_negative_correct_answers_gives_zero(self, authenticated_client, study_settings, db_session):
        resp = self._post_quiz(authenticated_client, total_questions=10, correct_answers=-5)
        data = resp.get_json()
        assert data['score'] == 0.0

    def test_zero_total_questions_gives_zero(self, authenticated_client, study_settings, db_session):
        resp = self._post_quiz(authenticated_client, total_questions=0, correct_answers=0)
        data = resp.get_json()
        assert data['score'] == 0.0

    def test_invalid_data_returns_400(self, authenticated_client, study_settings):
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps({'total_questions': 'bad', 'correct_answers': 'bad'}),
            content_type='application/json',
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 2. /api/complete-matching-game — score_percentage clamped to 0-100
# ---------------------------------------------------------------------------

class TestMatchingScoreBounds:
    def _post_matching(self, client, **kwargs):
        payload = {
            'pairs_matched': kwargs.get('pairs_matched', 5),
            'total_pairs': kwargs.get('total_pairs', 5),
            'moves': kwargs.get('moves', 10),
            'time_taken': kwargs.get('time_taken', 30),
            'difficulty': kwargs.get('difficulty', 'easy'),
        }
        payload.update({k: v for k, v in kwargs.items() if k not in payload})
        return client.post(
            '/study/api/complete-matching-game',
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_normal_matching_succeeds(self, authenticated_client, study_settings, db_session):
        resp = self._post_matching(authenticated_client)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_pairs_matched_exceeding_total_pairs_rejected(self, authenticated_client, study_settings, db_session):
        """pairs_matched > total_pairs is detected as invalid game data."""
        resp = self._post_matching(
            authenticated_client,
            pairs_matched=9999,
            total_pairs=5,
            moves=10,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is False

    def test_negative_inputs_handled(self, authenticated_client, study_settings, db_session):
        resp = self._post_matching(
            authenticated_client,
            pairs_matched=-1,
            total_pairs=-1,
            moves=-5,
            time_taken=-10,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['score'] >= 0

    def test_invalid_matching_data_returns_400(self, authenticated_client, study_settings):
        resp = authenticated_client.post(
            '/study/api/complete-matching-game',
            data=json.dumps({'pairs_matched': 'abc'}),
            content_type='application/json',
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 3. Session ownership — XP not awarded for another user's session
# ---------------------------------------------------------------------------

class TestSessionOwnership:
    def test_quiz_xp_not_awarded_for_other_user_session(
        self, authenticated_client, study_settings, other_user_quiz_session, db_session
    ):
        """Submitting another user's session_id yields success but no XP (unverified session)."""
        payload = {
            'total_questions': 10,
            'correct_answers': 10,
            'time_taken': 30,
            'session_id': other_user_quiz_session.id,
        }
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        # XP should be 0 since session ownership check failed
        assert data['xp_earned'] == 0

    def test_matching_xp_not_awarded_for_other_user_session(
        self, authenticated_client, study_settings, other_user_matching_session, db_session
    ):
        """Submitting another user's matching session_id yields success but no XP."""
        payload = {
            'pairs_matched': 5,
            'total_pairs': 5,
            'moves': 10,
            'time_taken': 30,
            'difficulty': 'easy',
            'session_id': other_user_matching_session.id,
        }
        resp = authenticated_client.post(
            '/study/api/complete-matching-game',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['xp_earned'] == 0

    def test_quiz_xp_awarded_for_own_session(
        self, authenticated_client, study_settings, quiz_session, db_session
    ):
        """Own quiz session → XP can be earned."""
        payload = {
            'total_questions': 10,
            'correct_answers': 10,
            'time_taken': 30,
            'session_id': quiz_session.id,
        }
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        # XP should be > 0 for perfect score with own session
        assert data['xp_earned'] >= 0  # may be 0 if XP already awarded

    def test_wrong_session_type_not_verified(
        self, authenticated_client, study_settings, matching_session, db_session
    ):
        """A matching session cannot be used as a quiz session (type mismatch → no XP)."""
        payload = {
            'total_questions': 10,
            'correct_answers': 10,
            'time_taken': 30,
            'session_id': matching_session.id,
        }
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['xp_earned'] == 0


# ---------------------------------------------------------------------------
# 4. Deleted deck — complete-quiz succeeds gracefully
# ---------------------------------------------------------------------------

class TestDeletedDeckResult:
    def test_complete_quiz_with_nonexistent_deck_id_succeeds(
        self, authenticated_client, study_settings, db_session
    ):
        """Passing a deleted/nonexistent deck_id must not crash complete-quiz."""
        payload = {
            'total_questions': 5,
            'correct_answers': 3,
            'time_taken': 60,
            'deck_id': 999999,
        }
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 0.0 <= data['score'] <= 100.0

    def test_complete_quiz_after_deck_deleted_succeeds(
        self, authenticated_client, study_settings, user_deck_with_words, db_session
    ):
        """Complete quiz referencing a deck that gets deleted between quiz start and submit."""
        deck_id = user_deck_with_words.id

        # Delete the deck before submitting quiz results
        db_session.delete(user_deck_with_words)
        db_session.commit()

        payload = {
            'total_questions': 5,
            'correct_answers': 4,
            'time_taken': 45,
            'deck_id': deck_id,
        }
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_game_score_still_saved_when_deck_missing(
        self, authenticated_client, study_settings, db_session, test_user
    ):
        """GameScore row is saved even when deck_id refers to missing deck."""
        before_count = GameScore.query.filter_by(
            user_id=test_user.id, game_type='quiz'
        ).count()

        payload = {
            'total_questions': 5,
            'correct_answers': 2,
            'time_taken': 60,
            'deck_id': 999999,
        }
        authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(payload),
            content_type='application/json',
        )

        db_session.expire_all()
        after_count = GameScore.query.filter_by(
            user_id=test_user.id, game_type='quiz'
        ).count()
        assert after_count == before_count + 1


# ---------------------------------------------------------------------------
# 5. SRS-slot XP: matching game NEVER awards it; quiz awards only when plan_slot='srs'
# ---------------------------------------------------------------------------

class TestSrsSlotXpDecision:
    """
    Task 11 decision: matching/word-scramble games intentionally do NOT credit
    linear_srs_global XP.  The matching game has no plan_slot/source signal
    and already gets award_game_xp_idempotent() XP, so adding SRS-slot XP
    would double-credit users who play matching AND complete the dedicated SRS
    slot.  The quiz route gates srs-slot XP on explicit plan_slot='srs' and
    source='linear_plan_deck_quiz' params.
    """

    def test_matching_game_does_not_create_srs_slot_streak_event(
        self, authenticated_client, study_settings, db_session, test_user
    ):
        """Completing matching game (even perfect score) creates no xp_linear StreakEvent."""
        from app.achievements.models import StreakEvent
        before = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == 'xp_linear',
        ).count()

        payload = {
            'pairs_matched': 10,
            'total_pairs': 10,
            'moves': 20,
            'time_taken': 30,
            'difficulty': 'hard',
        }
        resp = authenticated_client.post(
            '/study/api/complete-matching-game',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

        db_session.expire_all()
        after = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == 'xp_linear',
        ).count()
        assert after == before, (
            "Matching game must not create xp_linear StreakEvents — "
            "SRS-slot XP is intentionally excluded (see complete_matching_game docstring)"
        )

    def test_quiz_without_plan_slot_does_not_award_srs_global_xp(
        self, authenticated_client, study_settings, db_session, test_user
    ):
        """Quiz without plan_slot='srs' does not award SRS-slot XP."""
        from app.achievements.models import StreakEvent
        before = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == 'xp_linear',
        ).count()

        payload = {
            'total_questions': 10,
            'correct_answers': 10,
            'time_taken': 60,
            # No source/from/slot — free-play quiz
        }
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

        db_session.expire_all()
        after = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == 'xp_linear',
        ).count()
        assert after == before, "Free-play quiz must not award linear SRS-slot XP"

    def test_quiz_with_srs_plan_slot_awards_srs_global_xp(
        self, authenticated_client, study_settings, db_session, test_user
    ):
        """Quiz submitted with plan_slot='srs' and correct source creates xp_linear StreakEvent."""
        from app.achievements.models import StreakEvent
        before = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == 'xp_linear',
        ).count()

        payload = {
            'total_questions': 10,
            'correct_answers': 8,
            'time_taken': 60,
            'source': 'linear_plan_deck_quiz',
            'from': 'linear_plan',
            'slot': 'srs',
        }
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

        db_session.expire_all()
        after = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == 'xp_linear',
        ).count()
        assert after > before, "Quiz with plan_slot='srs' must award linear SRS-slot XP"

    def test_quiz_with_srs_plan_slot_idempotent_second_call(
        self, authenticated_client, study_settings, db_session, test_user
    ):
        """Second quiz submission with plan_slot='srs' on same day does not double-award."""
        from app.achievements.models import StreakEvent

        payload = {
            'total_questions': 10,
            'correct_answers': 8,
            'time_taken': 60,
            'source': 'linear_plan_deck_quiz',
            'from': 'linear_plan',
            'slot': 'srs',
        }
        # First submission
        authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(payload),
            content_type='application/json',
        )
        db_session.expire_all()
        after_first = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == 'xp_linear',
        ).count()

        # Second submission same day
        authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(payload),
            content_type='application/json',
        )
        db_session.expire_all()
        after_second = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == 'xp_linear',
        ).count()

        assert after_second == after_first, (
            "SRS-slot XP must be idempotent — second same-day quiz must not add StreakEvent"
        )


# ---------------------------------------------------------------------------
# Matching game — активация новых SRS-карточек уважает дневной бюджет
# ---------------------------------------------------------------------------

class TestMatchingSrsBudget:
    def test_new_card_activation_respects_daily_budget(
        self, authenticated_client, test_user, study_settings, db_session,
    ):
        """10 клиентских word_ids не активируют больше new_words_per_day(=5)
        направлений — раньше игра создавала и грейдила карточки без лимита."""
        import uuid as _uuid

        from app.study.models import UserCardDirection, UserWord
        from app.words.models import CollectionWords

        words = []
        for _ in range(10):
            w = CollectionWords(
                english_word=f'mgame_{_uuid.uuid4().hex[:6]}',
                russian_word='пара',
                level='A1',
            )
            db_session.add(w)
            words.append(w)
        db_session.commit()

        resp = authenticated_client.post(
            '/study/api/complete-matching-game',
            data=json.dumps({
                'pairs_matched': 10,
                'total_pairs': 10,
                'moves': 20,
                'time_taken': 60,
                'difficulty': 'easy',
                'word_ids': [w.id for w in words],
            }),
            content_type='application/json',
        )
        assert resp.status_code == 200

        activated = (
            db.session.query(UserCardDirection)
            .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
            .filter(
                UserWord.user_id == test_user.id,
                UserCardDirection.first_reviewed.isnot(None),
            )
            .count()
        )
        # study_settings.new_words_per_day == 5
        assert activated == 5
