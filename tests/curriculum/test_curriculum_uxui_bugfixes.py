"""Regression tests for UX/UI bug fixes from the 2026-06-02 curriculum audit.

Covers:
- PASSING_SCORE_DEFAULT is 70, not 100, for sentence_correction
- pronunciation finish=True without attempts returns 400
- _curriculum_done_today excludes score-based lessons with score < 70
- XP savepoint rollback: lesson stays completed when XP award raises
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.curriculum.constants import PASSING_SCORE_DEFAULT
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from tests.conftest import unique_level_code


def _make_lesson(db_session, lesson_type: str, content: dict | None = None) -> Lessons:
    level = CEFRLevel(code=unique_level_code(), name='Level', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='Module',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    if content is None:
        if lesson_type == 'sentence_correction':
            content = {
                'incorrect_sentence': 'She go to school.',
                'correct_sentence': 'She goes to school.',
                'error_type': 'verb',
                'explanation': 'Use goes.',
            }
        elif lesson_type == 'pronunciation':
            content = {'items': [{'word': 'hello'}, {'word': 'world'}]}
        else:
            content = {}
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Test Lesson',
        type=lesson_type,
        content=content,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


# ---------------------------------------------------------------------------
# 1. PASSING_SCORE_DEFAULT
# ---------------------------------------------------------------------------


class TestPassingScoreDefault:
    def test_constant_is_70(self):
        assert PASSING_SCORE_DEFAULT == 70

    def test_multi_item_75_percent_passes(self, app, db_session, test_user, client):
        """Multi-item sentence_correction: 3/4 correct (75%) passes the 70% threshold."""
        content = {
            'items': [
                {'incorrect_sentence': 'A', 'correct_sentence': 'A_correct'},
                {'incorrect_sentence': 'B', 'correct_sentence': 'B_correct'},
                {'incorrect_sentence': 'C', 'correct_sentence': 'C_correct'},
                {'incorrect_sentence': 'D', 'correct_sentence': 'D_correct'},
            ]
        }
        lesson = _make_lesson(db_session, 'sentence_correction', content)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/sentence-correction')
        resp = client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={
                'lesson_type': 'sentence_correction',
                'answers': ['A_correct', 'B_correct', 'C_correct', 'wrong'],
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert float(data.get('score', 0)) >= PASSING_SCORE_DEFAULT
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == 'completed'

    def test_single_item_correct_marks_completed(self, app, db_session, test_user, client):
        """Single-item correct answer still marks lesson completed (regression)."""
        lesson = _make_lesson(db_session, 'sentence_correction')
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/sentence-correction')
        resp = client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={'lesson_type': 'sentence_correction', 'user_answer': 'She goes to school.'},
        )
        assert resp.status_code == 200
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == 'completed'


# ---------------------------------------------------------------------------
# 2. Pronunciation requires attempt before finish
# ---------------------------------------------------------------------------


class TestPronunciationRequiresAttempt:
    def test_finish_without_attempts_returns_400(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, 'pronunciation')
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/pronunciation')
        resp = client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={'lesson_type': 'pronunciation', 'finish': True},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data.get('success') is False
        assert data.get('error') == 'requires_attempt'

    def test_finish_after_item_attempt_succeeds(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, 'pronunciation')
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/pronunciation')
        client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={
                'lesson_type': 'pronunciation',
                'item_index': 0,
                'recognized_text': 'hello',
                'target_word': 'hello',
            },
        )
        resp = client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={'lesson_type': 'pronunciation', 'finish': True},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('success') is True
        assert data.get('completed') is True

    def test_finish_after_self_assessed_attempt_succeeds(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, 'pronunciation')
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/pronunciation')
        # item_index is required so the server resolves the correct word
        client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={
                'lesson_type': 'pronunciation',
                'item_index': 0,
                'self_assessed': True,
            },
        )
        resp = client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={'lesson_type': 'pronunciation', 'finish': True},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('success') is True


# ---------------------------------------------------------------------------
# 3. _curriculum_done_today checks passing score
# ---------------------------------------------------------------------------


class TestCurriculumDoneTodayScoreCheck:
    def test_score_based_lesson_below_threshold_not_counted(
        self, app, db_session, test_user
    ):
        """A score-based lesson completed with score < 70 must NOT count as done today."""
        from app.daily_plan.items.curriculum import _curriculum_done_today
        from app.utils.db import db as flask_db

        lesson = _make_lesson(db_session, 'translation', {})
        progress = LessonProgress(
            user_id=test_user.id,
            lesson_id=lesson.id,
            status='completed',
            score=50.0,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db_session.add(progress)
        db_session.commit()

        result = _curriculum_done_today(test_user.id, flask_db)
        assert result is False

    def test_score_based_lesson_at_threshold_is_counted(
        self, app, db_session, test_user
    ):
        """A score-based lesson completed with score >= 70 counts as done today."""
        from app.daily_plan.items.curriculum import _curriculum_done_today
        from app.utils.db import db as flask_db

        lesson = _make_lesson(db_session, 'translation', {})
        progress = LessonProgress(
            user_id=test_user.id,
            lesson_id=lesson.id,
            status='completed',
            score=70.0,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db_session.add(progress)
        db_session.commit()

        result = _curriculum_done_today(test_user.id, flask_db)
        assert result is True

    def test_non_score_based_lesson_counts_without_score(
        self, app, db_session, test_user
    ):
        """Activity-based lesson (vocabulary) counts as done even with score=None."""
        from app.daily_plan.items.curriculum import _curriculum_done_today
        from app.utils.db import db as flask_db

        lesson = _make_lesson(db_session, 'vocabulary', {'words': []})
        progress = LessonProgress(
            user_id=test_user.id,
            lesson_id=lesson.id,
            status='completed',
            score=None,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db_session.add(progress)
        db_session.commit()

        result = _curriculum_done_today(test_user.id, flask_db)
        assert result is True

    def test_not_completed_status_not_counted(self, app, db_session, test_user):
        """A lesson in_progress with passing score still must not count as done."""
        from app.daily_plan.items.curriculum import _curriculum_done_today
        from app.utils.db import db as flask_db

        lesson = _make_lesson(db_session, 'translation', {})
        progress = LessonProgress(
            user_id=test_user.id,
            lesson_id=lesson.id,
            status='in_progress',
            score=90.0,
            started_at=datetime.now(timezone.utc),
            completed_at=None,
        )
        db_session.add(progress)
        db_session.commit()

        result = _curriculum_done_today(test_user.id, flask_db)
        assert result is False


# ---------------------------------------------------------------------------
# 4. XP savepoint rollback
# ---------------------------------------------------------------------------


class TestXPSavepointRollback:
    def test_lesson_stays_completed_when_xp_fails(
        self, app, db_session, test_user, client
    ):
        """LessonProgress must remain completed even when XP award raises."""
        lesson = _make_lesson(db_session, 'vocabulary', {'words': []})
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/vocabulary')

        with patch(
            'app.daily_plan.linear.xp.maybe_award_curriculum_xp',
            side_effect=RuntimeError('XP service down'),
        ):
            resp = client.post(
                f'/curriculum/api/lesson/{lesson.id}/progress',
                json={'status': 'completed', 'score': 85},
            )

        assert resp.status_code == 200

        db_session.expire_all()
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == 'completed'

    def test_no_xp_event_created_when_xp_fails(
        self, app, db_session, test_user, client
    ):
        """No StreakEvent (XP record) should exist after a failed XP award."""
        from app.achievements.models import StreakEvent
        from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE

        lesson = _make_lesson(db_session, 'vocabulary', {'words': []})
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/vocabulary')

        with patch(
            'app.daily_plan.linear.xp.maybe_award_curriculum_xp',
            side_effect=RuntimeError('XP service down'),
        ):
            client.post(
                f'/curriculum/api/lesson/{lesson.id}/progress',
                json={'status': 'completed', 'score': 85},
            )

        db_session.expire_all()
        xp_events = db_session.query(StreakEvent).filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
        ).all()
        assert len(xp_events) == 0

    def test_route_returns_200_when_xp_fails(
        self, app, db_session, test_user, client
    ):
        """XP failure must not propagate as HTTP 500 to the client."""
        lesson = _make_lesson(db_session, 'vocabulary', {'words': []})
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/vocabulary')

        with patch(
            'app.daily_plan.linear.xp.maybe_award_curriculum_xp',
            side_effect=RuntimeError('XP service down'),
        ):
            resp = client.post(
                f'/curriculum/api/lesson/{lesson.id}/progress',
                json={'status': 'completed', 'score': 85},
            )

        assert resp.status_code == 200
