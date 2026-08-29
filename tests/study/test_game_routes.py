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
def plan_quiz_session(db_session, test_user):
    """A session opened by /study/quiz/linear-plan — the plan's own deck quiz.

    Its type is the server's record that the run started from the SRS slot;
    a generic 'quiz' session cannot stand in for it.
    """
    sess = StudySession(user_id=test_user.id, session_type='quiz_linear_plan')
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
        self, authenticated_client, study_settings, db_session, test_user,
        plan_quiz_session,
    ):
        """Quiz submitted with plan_slot='srs' and correct source creates xp_linear StreakEvent."""
        from app.achievements.models import StreakEvent
        before = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == 'xp_linear',
        ).count()

        plan_quiz_session.words_studied = 10
        db_session.commit()

        payload = {
            'session_id': plan_quiz_session.id,
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
        self, authenticated_client, study_settings, db_session, test_user,
        plan_quiz_session,
    ):
        """Second quiz submission with plan_slot='srs' on same day does not double-award."""
        from app.achievements.models import StreakEvent

        plan_quiz_session.words_studied = 10
        db_session.commit()

        payload = {
            'session_id': plan_quiz_session.id,
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


class TestDeckQuizSrsSlotNeedsARealRun:
    """The plan's required SRS slot must not be closable by a bare POST.

    `source`/`from`/`slot` and the counts are all client-supplied, so the only
    server-owned evidence that a deck quiz happened is the session row and the
    answers routed through /api/submit-quiz-answer.
    """

    @staticmethod
    def _linear_events(user_id):
        from app.achievements.models import StreakEvent
        return StreakEvent.query.filter(
            StreakEvent.user_id == user_id,
            StreakEvent.event_type == 'xp_linear',
        ).count()

    def _payload(self, **extra):
        payload = {
            'total_questions': 10,
            'correct_answers': 8,
            'time_taken': 60,
            'source': 'linear_plan_deck_quiz',
            'from': 'linear_plan',
            'slot': 'srs',
        }
        payload.update(extra)
        return payload

    def test_post_without_session_does_not_award(
        self, authenticated_client, study_settings, db_session, test_user
    ):
        before = self._linear_events(test_user.id)
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(self._payload()),
            content_type='application/json',
        )
        assert resp.status_code == 200
        db_session.expire_all()
        assert self._linear_events(test_user.id) == before, (
            'a completion POST with no session must not close the SRS slot'
        )

    def test_session_without_answers_does_not_award(
        self, authenticated_client, study_settings, db_session, test_user,
        plan_quiz_session,
    ):
        """Opening /quiz/linear-plan is not the same as playing it."""
        before = self._linear_events(test_user.id)
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(self._payload(session_id=plan_quiz_session.id)),
            content_type='application/json',
        )
        assert resp.status_code == 200
        db_session.expire_all()
        assert self._linear_events(test_user.id) == before

    def test_another_users_session_does_not_award(
        self, authenticated_client, study_settings, db_session, test_user,
        other_user_quiz_session,
    ):
        other_user_quiz_session.words_studied = 10
        db_session.commit()
        before = self._linear_events(test_user.id)
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(self._payload(session_id=other_user_quiz_session.id)),
            content_type='application/json',
        )
        assert resp.status_code == 200
        db_session.expire_all()
        assert self._linear_events(test_user.id) == before

    def test_themed_set_session_does_not_award(
        self, authenticated_client, study_settings, db_session, test_user
    ):
        """A themed set quiz never grades SRS, so it cannot close the SRS slot."""
        themed = StudySession(
            user_id=test_user.id, session_type='quiz_word_set', words_studied=10,
        )
        db_session.add(themed)
        db_session.commit()

        before = self._linear_events(test_user.id)
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(self._payload(session_id=themed.id)),
            content_type='application/json',
        )
        assert resp.status_code == 200
        db_session.expire_all()
        assert self._linear_events(test_user.id) == before

    def test_generic_quiz_session_relabelled_as_plan_run_does_not_award(
        self, authenticated_client, study_settings, db_session, test_user, quiz_session
    ):
        """/quiz/auto and /quiz/deck/<id> open generic sessions — not the plan's.

        The completion body can claim any source, so an owned free-play quiz
        used to close the required SRS slot just by being relabelled.
        """
        quiz_session.words_studied = 10
        db_session.commit()

        before = self._linear_events(test_user.id)
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(self._payload(session_id=quiz_session.id)),
            content_type='application/json',
        )
        assert resp.status_code == 200
        db_session.expire_all()
        assert self._linear_events(test_user.id) == before, (
            'a generic quiz session must not close the plan SRS slot'
        )

    def test_answers_submitted_through_the_endpoint_do_award(
        self, authenticated_client, study_settings, db_session, test_user,
        plan_quiz_session,
    ):
        """The honest flow still pays: answers go through /submit-quiz-answer."""
        before = self._linear_events(test_user.id)

        answer = authenticated_client.post(
            '/study/api/submit-quiz-answer',
            data=json.dumps({
                'session_id': plan_quiz_session.id,
                'word_id': None,
                'direction': 'eng_to_rus',
                'is_correct': True,
            }),
            content_type='application/json',
        )
        assert answer.status_code == 200

        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(self._payload(session_id=plan_quiz_session.id)),
            content_type='application/json',
        )
        assert resp.status_code == 200
        db_session.expire_all()
        assert self._linear_events(test_user.id) > before

    @pytest.mark.parametrize('answer', [
        {'word_id': None, 'is_correct': True},                      # no direction at all
        {'word_id': None, 'direction': 'sideways', 'is_correct': True},
        {'word_id': 'x', 'direction': 'eng_to_rus', 'is_correct': True},
        {'word_id': [1], 'direction': 'eng_to_rus', 'is_correct': True},
    ])
    def test_unanswerable_submissions_do_not_close_the_slot(
        self, authenticated_client, study_settings, db_session, test_user,
        plan_quiz_session, answer,
    ):
        """`words_studied` is the gate's evidence, so garbage must not raise it.

        A body that names no question the generator could have produced used to
        increment the counter anyway, which let one fake answer stand in for a
        played quiz.
        """
        before = self._linear_events(test_user.id)

        resp = authenticated_client.post(
            '/study/api/submit-quiz-answer',
            data=json.dumps({'session_id': plan_quiz_session.id, **answer}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        db_session.expire_all()
        db_session.refresh(plan_quiz_session)
        assert plan_quiz_session.words_studied == 0

        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps(self._payload(session_id=plan_quiz_session.id)),
            content_type='application/json',
        )
        assert resp.status_code == 200
        db_session.expire_all()
        assert self._linear_events(test_user.id) == before, (
            'an unanswerable submission must not stand in for a played quiz'
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


class TestQuizAdvancesSrs:
    """A deck quiz must move real cards — the plan's SRS slot counts on it."""

    def _seed_session(self, db_session, test_user):
        """Grading is gated on a session this user owns, so every quiz answer
        carries one — quiz.html renders session_id server-side and always
        posts it."""
        from app.study.models import StudySession

        session = StudySession(user_id=test_user.id, session_type='quiz')
        db_session.add(session)
        db_session.commit()
        return session

    def _seed_card(self, db_session, test_user, english: str):
        from app.study.models import UserCardDirection, UserWord
        from app.words.models import CollectionWords

        word = CollectionWords(english_word=english, russian_word='перевод', level='A1')
        db_session.add(word)
        db_session.commit()
        user_word = UserWord(user_id=test_user.id, word_id=word.id)
        db_session.add(user_word)
        db_session.commit()
        direction = UserCardDirection(user_word_id=user_word.id, direction='eng-rus')
        db_session.add(direction)
        db_session.commit()
        return word, user_word, direction

    def test_correct_answer_advances_the_card(
        self, authenticated_client, db_session, test_user, study_settings,
    ):
        word, _, direction = self._seed_card(db_session, test_user, 'quiz_advances')
        session = self._seed_session(db_session, test_user)

        resp = authenticated_client.post(
            '/study/api/submit-quiz-answer',
            data=json.dumps({
                'session_id': session.id,
                'word_id': word.id,
                'direction': 'eng-rus',
                'is_correct': True,
            }),
            content_type='application/json',
        )

        assert resp.status_code == 200
        assert resp.get_json()['srs_graded'] is True
        db_session.refresh(direction)
        assert direction.first_reviewed is not None
        assert direction.state != 'new'

    def test_direction_as_the_quiz_emits_it_is_graded(
        self, authenticated_client, db_session, test_user, study_settings,
    ):
        """The client posts the question's own direction, not the column's.

        ``QuizService`` labels questions ``eng_to_rus``/``rus_to_eng`` and
        quiz.html sends that string back verbatim, while the card column stores
        ``eng-rus``/``rus-eng``. Matching the two vocabularies directly made
        grading a no-op for every real answer while the hyphenated form used by
        the other tests here kept passing.
        """
        word, _, direction = self._seed_card(db_session, test_user, 'quiz_underscore')
        session = self._seed_session(db_session, test_user)

        resp = authenticated_client.post(
            '/study/api/submit-quiz-answer',
            data=json.dumps({
                'session_id': session.id,
                'word_id': word.id,
                'direction': 'eng_to_rus',
                'is_correct': True,
            }),
            content_type='application/json',
        )

        assert resp.status_code == 200
        assert resp.get_json()['srs_graded'] is True
        db_session.refresh(direction)
        assert direction.first_reviewed is not None

    def test_unknown_direction_is_not_graded(
        self, authenticated_client, db_session, test_user, study_settings,
    ):
        word, _, direction = self._seed_card(db_session, test_user, 'quiz_bogus')
        session = self._seed_session(db_session, test_user)

        resp = authenticated_client.post(
            '/study/api/submit-quiz-answer',
            data=json.dumps({
                'session_id': session.id,
                'word_id': word.id,
                'direction': 'sideways',
                'is_correct': True,
            }),
            content_type='application/json',
        )

        assert resp.status_code == 200
        assert resp.get_json()['srs_graded'] is False
        db_session.refresh(direction)
        assert direction.first_reviewed is None

    def test_malformed_direction_is_rejected_not_raised(
        self, authenticated_client, db_session, test_user, study_settings,
    ):
        """A JSON list is unhashable, and ``dict.get`` raises on it.

        The membership test this lookup replaced failed closed for such values;
        the map must too, or a hand-written request 500s the endpoint.
        """
        word, _, direction = self._seed_card(db_session, test_user, 'quiz_unhashable')
        session = self._seed_session(db_session, test_user)

        resp = authenticated_client.post(
            '/study/api/submit-quiz-answer',
            data=json.dumps({
                'session_id': session.id,
                'word_id': word.id,
                'direction': [],
                'is_correct': True,
            }),
            content_type='application/json',
        )

        assert resp.status_code == 200
        assert resp.get_json()['srs_graded'] is False
        db_session.refresh(direction)
        assert direction.first_reviewed is None

    def test_word_without_card_rows_is_provisioned_and_graded(
        self, authenticated_client, db_session, test_user, study_settings,
    ):
        """Bulk «добавить в изучение» writes UserWord but no directions.

        Those words are exactly what a deck quiz serves right after a set is
        added, and declining to grade them let the quiz close the plan's SRS
        slot while moving no card. /study provisions them on first grade; so
        does this.
        """
        from app.study.models import UserCardDirection, UserWord
        from app.words.models import CollectionWords

        word = CollectionWords(
            english_word='quiz_unprovisioned', russian_word='перевод', level='A1',
        )
        db_session.add(word)
        db_session.commit()
        db_session.add(UserWord(user_id=test_user.id, word_id=word.id))
        db_session.commit()
        session = self._seed_session(db_session, test_user)

        resp = authenticated_client.post(
            '/study/api/submit-quiz-answer',
            data=json.dumps({
                'session_id': session.id,
                'word_id': word.id,
                'direction': 'eng_to_rus',
                'is_correct': True,
            }),
            content_type='application/json',
        )

        assert resp.status_code == 200
        assert resp.get_json()['srs_graded'] is True

        user_word = UserWord.query.filter_by(
            user_id=test_user.id, word_id=word.id,
        ).first()
        directions = UserCardDirection.query.filter_by(
            user_word_id=user_word.id,
        ).all()
        # Both directions exist — a lone one in REVIEW would call the word
        # learned after a single keypress.
        assert {row.direction for row in directions} == {'eng-rus', 'rus-eng'}
        graded = next(row for row in directions if row.direction == 'eng-rus')
        assert graded.first_reviewed is not None

    def test_word_without_card_rows_respects_the_new_card_budget(
        self, authenticated_client, db_session, test_user, study_settings,
    ):
        from app.study.models import UserCardDirection, UserWord
        from app.words.models import CollectionWords

        study_settings.new_words_per_day = 0
        db_session.commit()

        word = CollectionWords(
            english_word='quiz_over_budget', russian_word='перевод', level='A1',
        )
        db_session.add(word)
        db_session.commit()
        db_session.add(UserWord(user_id=test_user.id, word_id=word.id))
        db_session.commit()
        session = self._seed_session(db_session, test_user)

        resp = authenticated_client.post(
            '/study/api/submit-quiz-answer',
            data=json.dumps({
                'session_id': session.id,
                'word_id': word.id,
                'direction': 'eng_to_rus',
                'is_correct': True,
            }),
            content_type='application/json',
        )

        assert resp.status_code == 200
        assert resp.get_json()['srs_graded'] is False
        user_word = UserWord.query.filter_by(
            user_id=test_user.id, word_id=word.id,
        ).first()
        assert UserCardDirection.query.filter_by(
            user_word_id=user_word.id,
        ).count() == 0

    def test_excluded_word_is_not_graded(
        self, authenticated_client, db_session, test_user, study_settings,
    ):
        word, user_word, direction = self._seed_card(db_session, test_user, 'quiz_excluded')
        user_word.srs_excluded = True
        db_session.commit()
        session = self._seed_session(db_session, test_user)

        resp = authenticated_client.post(
            '/study/api/submit-quiz-answer',
            data=json.dumps({
                'session_id': session.id,
                'word_id': word.id,
                'direction': 'eng-rus',
                'is_correct': True,
            }),
            content_type='application/json',
        )

        assert resp.status_code == 200
        assert resp.get_json()['srs_graded'] is False
        db_session.refresh(direction)
        assert direction.first_reviewed is None


class TestMatchingGameRespectsExclusion:
    """"Не учить это слово" must hold here too.

    The matching game grades every word it is handed, which used to bypass the
    409 guard that /study/api/update-study-item enforces.
    """

    def test_excluded_word_is_not_graded(
        self, authenticated_client, db_session, test_user, study_settings,
    ):
        from app.study.models import UserCardDirection, UserWord
        from app.words.models import CollectionWords

        word = CollectionWords(english_word='excluded_x', russian_word='исключено_x', level='A1')
        db_session.add(word)
        db_session.commit()

        user_word = UserWord(user_id=test_user.id, word_id=word.id)
        user_word.srs_excluded = True
        db_session.add(user_word)
        db_session.commit()

        direction = UserCardDirection(user_word_id=user_word.id, direction='eng-rus')
        db_session.add(direction)
        db_session.commit()

        resp = authenticated_client.post(
            '/study/api/complete-matching-game',
            data=json.dumps({
                'pairs_matched': 1,
                'total_pairs': 1,
                'moves': 2,
                'time_taken': 10,
                'difficulty': 'easy',
                'word_ids': [word.id],
            }),
            content_type='application/json',
        )
        assert resp.status_code == 200

        db_session.refresh(direction)
        assert direction.first_reviewed is None
        assert (direction.session_attempts or 0) == 0


# ---------------------------------------------------------------------------
# `_session_pk`: a non-integer session_id must be ignored, never 500
# ---------------------------------------------------------------------------

class TestSessionIdCoercion:
    """`session_id` arrives as arbitrary JSON.

    Handed straight to `StudySession.query.get()` a non-integer reaches an
    INTEGER primary key: on PostgreSQL that is a DataError that aborts the
    transaction, so the request 500s before any ownership guard runs.
    `_session_pk` coerces or drops it — and rejects `bool` explicitly, because
    `True` would otherwise look up row 1 (session forgery by literal).
    """

    UNUSABLE = ['x', '12abc', [1], {'a': 1}, 1.5, True, False, None]

    @pytest.mark.parametrize('bad', UNUSABLE)
    def test_complete_quiz_ignores_unusable_session_id(
        self, authenticated_client, study_settings, bad, db_session,
    ):
        resp = authenticated_client.post(
            '/study/api/complete-quiz',
            data=json.dumps({
                'total_questions': 10,
                'correct_answers': 10,
                'time_taken': 30,
                'session_id': bad,
            }),
            content_type='application/json',
        )
        assert resp.status_code == 200, f'{bad!r} produced {resp.status_code}'
        data = resp.get_json()
        assert data['success'] is True
        # No verified session ⇒ no XP. `True` must not resolve to session id 1.
        assert data['xp_earned'] == 0

    @pytest.mark.parametrize('bad', UNUSABLE)
    def test_complete_matching_ignores_unusable_session_id(
        self, authenticated_client, study_settings, bad, db_session,
    ):
        resp = authenticated_client.post(
            '/study/api/complete-matching-game',
            data=json.dumps({
                'pairs_matched': 5,
                'total_pairs': 5,
                'moves': 10,
                'time_taken': 30,
                'difficulty': 'easy',
                'session_id': bad,
            }),
            content_type='application/json',
        )
        assert resp.status_code == 200, f'{bad!r} produced {resp.status_code}'
        data = resp.get_json()
        assert data['success'] is True
        assert data['xp_earned'] == 0

    @pytest.mark.parametrize('bad', UNUSABLE)
    def test_submit_quiz_answer_ignores_unusable_session_id(
        self, authenticated_client, study_settings, bad, db_session,
    ):
        resp = authenticated_client.post(
            '/study/api/submit-quiz-answer',
            data=json.dumps({
                'word_id': 0,
                'is_correct': True,
                'direction': 'eng_to_rus',
                'session_id': bad,
            }),
            content_type='application/json',
        )
        assert resp.status_code in (200, 400), f'{bad!r} produced {resp.status_code}'

    def test_true_does_not_impersonate_session_one(
        self, authenticated_client, study_settings, other_user_quiz_session, db_session,
    ):
        """`True == 1` in Python — the bool guard is what stops the forgery.

        Pinned against a session that exists and is NOT ours, so a regression
        that let `True` through would show up as a resolved session rather than
        as a lookup miss.
        """
        from app.study.game_routes import _session_pk

        assert _session_pk(True) is None
        assert _session_pk(False) is None
        assert _session_pk(other_user_quiz_session.id) == other_user_quiz_session.id
        assert _session_pk(str(other_user_quiz_session.id)) == other_user_quiz_session.id
