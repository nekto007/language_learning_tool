"""Кластер A-1 фазы 2: XP и закрытие дня за работу, которой не было.

Три находки реестра `docs/audit/2026-08-26-daily-plan-audit.md`:

* ``DP-087`` — пустой POST на ``/api/daily-plan/error-review/complete`` платил
  ``linear_error_review`` (10 XP) и у graduated/заблокированного пользователя
  закрывал день: доказательства работы обработчик не требовал вовсе.
* ``DP-042`` — required-слот ``srs:deck_quiz`` читал общий ключ
  ``linear_srs_global``, который пишет и обычная ``/study``-сессия, и
  корректирующая fallback-ветка ``is_srs_slot_completed_today``. У квиза
  должен быть собственный сигнал завершения.
* ``DP-050`` — XP за grammar-урок гейтился липким ``status == 'completed'``:
  проваленная пересдача уже сданного урока статус не понижает, поэтому
  платила как сданная.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.achievements.models import StreakEvent
from app.auth.models import User
from app.curriculum.models import LessonProgress, Lessons
from app.daily_plan.linear.models import QuizErrorLog
from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE
from app.utils.time_utils import get_user_local_date


# ── helpers ──────────────────────────────────────────────────────────────────


def _error_row(db_session, user_id: int, lesson_id: int, *, resolved_at=None) -> QuizErrorLog:
    row = QuizErrorLog(
        user_id=user_id,
        lesson_id=lesson_id,
        question_payload={'question': 'q', 'correct_answer': 'a'},
        answered_wrong_at=datetime.now(timezone.utc) - timedelta(days=1),
        resolved_at=resolved_at,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _linear_events(db_session, user_id: int, source: str) -> list[StreakEvent]:
    return (
        db_session.query(StreakEvent)
        .filter(
            StreakEvent.user_id == user_id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
            StreakEvent.details['source'].astext == source,
        )
        .all()
    )


def _grammar_lesson(db_session, module, exercises) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=7,
        title='Grammar with exercises',
        type='grammar',
        order=7,
        content={
            'title': 'Present Simple',
            'content': 'Rule body',
            'exercises': exercises,
        },
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


# ── DP-087 ───────────────────────────────────────────────────────────────────


class TestErrorReviewRequiresProofOfWork:
    """`/error-review/complete` без разобранных ошибок не платит и не закрывает день."""

    def test_empty_body_returns_400_and_awards_nothing(
        self, db_session, authenticated_client, test_user
    ):
        resp = authenticated_client.post(
            '/api/daily-plan/error-review/complete', json={}
        )

        assert resp.status_code == 400
        body = resp.get_json()
        assert body['success'] is False
        assert body['status'] == 400
        assert _linear_events(db_session, test_user.id, 'linear_error_review') == []

    def test_empty_list_returns_400_and_awards_nothing(
        self, db_session, authenticated_client, test_user
    ):
        resp = authenticated_client.post(
            '/api/daily-plan/error-review/complete', json={'error_ids': []}
        )

        assert resp.status_code == 400
        assert _linear_events(db_session, test_user.id, 'linear_error_review') == []

    def test_foreign_ids_return_400_and_awards_nothing(
        self, db_session, authenticated_client, test_user, second_user,
        test_lesson_quiz,
    ):
        foreign = _error_row(db_session, second_user.id, test_lesson_quiz.id)

        resp = authenticated_client.post(
            '/api/daily-plan/error-review/complete',
            json={'error_ids': [foreign.id]},
        )

        assert resp.status_code == 400
        assert _linear_events(db_session, test_user.id, 'linear_error_review') == []
        db_session.refresh(foreign)
        assert foreign.resolved_at is None

    def test_stale_resolved_row_does_not_pay_again(
        self, db_session, authenticated_client, test_user, test_lesson_quiz,
    ):
        """Ошибка, разобранная неделю назад, не закрывает СЕГОДНЯШНИЙ слот."""
        stale = _error_row(
            db_session, test_user.id, test_lesson_quiz.id,
            resolved_at=datetime.now(timezone.utc) - timedelta(days=7),
        )

        resp = authenticated_client.post(
            '/api/daily-plan/error-review/complete',
            json={'error_ids': [stale.id]},
        )

        assert resp.status_code == 400
        assert _linear_events(db_session, test_user.id, 'linear_error_review') == []

    def test_real_work_still_awards(
        self, db_session, authenticated_client, test_user, test_lesson_quiz,
    ):
        """Регресс-страж: настоящий разбор ошибок платит как раньше."""
        row = _error_row(db_session, test_user.id, test_lesson_quiz.id)

        resp = authenticated_client.post(
            '/api/daily-plan/error-review/complete',
            json={'error_ids': [row.id]},
        )

        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['success'] is True
        assert payload['resolved_count'] == 1
        assert len(_linear_events(db_session, test_user.id, 'linear_error_review')) == 1

    def test_repeat_post_same_day_is_accepted(
        self, db_session, authenticated_client, test_user, test_lesson_quiz,
    ):
        """Повторная отправка тех же id в тот же день — не ошибка (ретрай клиента)."""
        row = _error_row(db_session, test_user.id, test_lesson_quiz.id)

        first = authenticated_client.post(
            '/api/daily-plan/error-review/complete', json={'error_ids': [row.id]},
        )
        second = authenticated_client.post(
            '/api/daily-plan/error-review/complete', json={'error_ids': [row.id]},
        )

        assert first.status_code == 200
        assert second.status_code == 200
        # XP идемпотентен per (user, date, source) — второй раз не доплачивает.
        assert len(_linear_events(db_session, test_user.id, 'linear_error_review')) == 1


# ── DP-042 ───────────────────────────────────────────────────────────────────


class TestDeckQuizHasOwnCompletionSignal:
    """`srs:deck_quiz` закрывается только собственным сигналом квиза."""

    def _srs_global_event(self, db_session, user_id: int) -> None:
        db_session.add(StreakEvent(
            user_id=user_id,
            event_type=LINEAR_XP_EVENT_TYPE,
            event_date=get_user_local_date(user_id, db_session),
            details={'source': 'linear_srs_global', 'xp': 8},
        ))
        db_session.commit()

    def test_plain_srs_session_does_not_close_deck_quiz(
        self, app, db_session, test_user
    ):
        from app.daily_plan.linear.xp import is_deck_quiz_completed_today
        from app.daily_plan.snapshot import _is_item_completed
        from app.utils.db import db as real_db

        self._srs_global_event(db_session, test_user.id)

        with app.test_request_context():
            assert is_deck_quiz_completed_today(test_user.id, real_db) is False
            assert _is_item_completed(
                test_user.id, {'id': 'srs:deck_quiz', 'kind': 'srs'}, real_db,
            ) is False

    def test_deck_quiz_signal_closes_the_slot(self, app, db_session, test_user):
        from app.daily_plan.linear.xp import (
            is_deck_quiz_completed_today,
            record_deck_quiz_completion,
        )
        from app.daily_plan.snapshot import _is_item_completed
        from app.utils.db import db as real_db

        with app.test_request_context():
            record_deck_quiz_completion(test_user.id, db_session=real_db)
            real_db.session.commit()

            assert is_deck_quiz_completed_today(test_user.id, real_db) is True
            assert _is_item_completed(
                test_user.id, {'id': 'srs:deck_quiz', 'kind': 'srs'}, real_db,
            ) is True

    def test_record_is_idempotent_per_day(self, app, db_session, test_user):
        from app.daily_plan.linear.xp import (
            DECK_QUIZ_EVENT_TYPE,
            record_deck_quiz_completion,
        )
        from app.daily_plan.models import DailyPlanEvent
        from app.utils.db import db as real_db

        with app.test_request_context():
            record_deck_quiz_completion(test_user.id, db_session=real_db)
            record_deck_quiz_completion(test_user.id, db_session=real_db)
            real_db.session.commit()

        rows = (
            db_session.query(DailyPlanEvent)
            .filter_by(user_id=test_user.id, event_type=DECK_QUIZ_EVENT_TYPE)
            .all()
        )
        assert len(rows) == 1

    def test_builder_reports_pending_when_only_srs_global_exists(
        self, app, db_session, test_user, study_settings
    ):
        """Билдер пункта плана читает тот же сигнал, что и снапшот."""
        from unittest.mock import patch

        from app.daily_plan.items.srs import _build_deck_quiz_plan_item
        from app.utils.db import db as real_db

        self._srs_global_event(db_session, test_user.id)

        with app.test_request_context(), patch(
            'app.daily_plan.linear.slots.srs_slot._count_user_deck_quiz_words',
            return_value=12,
        ):
            item = _build_deck_quiz_plan_item(test_user.id, real_db)

        assert item is not None
        assert item.completed is False


# ── DP-050 ───────────────────────────────────────────────────────────────────


class TestGrammarRetakeXpGate:
    """Проваленная пересдача grammar-урока XP не платит."""

    EXERCISES = [
        {
            'type': 'fill_in_blank',
            'question': 'She ___ to school every day.',
            'text': 'She ___ to school every day.',
            'answer': 'goes',
            'correct_answer': 'goes',
        },
    ]

    @pytest.mark.parametrize(
        'url_template',
        [
            '/learn/{lesson_id}/',
            '/curriculum/lesson/{lesson_id}/grammar',
        ],
    )
    def test_failed_retake_of_completed_lesson_awards_nothing(
        self, db_session, authenticated_client, test_user, test_module, url_template
    ):
        lesson = _grammar_lesson(db_session, test_module, self.EXERCISES)
        db_session.add(LessonProgress(
            user_id=test_user.id,
            lesson_id=lesson.id,
            status='completed',
            score=100.0,
            best_score=100.0,
            last_score=100.0,
            started_at=datetime.now(timezone.utc) - timedelta(days=3),
            completed_at=datetime.now(timezone.utc) - timedelta(days=3),
            last_activity=datetime.now(timezone.utc) - timedelta(days=3),
        ))
        db_session.commit()

        resp = authenticated_client.post(
            url_template.format(lesson_id=lesson.id),
            data={'answer_0': 'went'},  # неверно → score 0
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

        assert resp.status_code == 200
        # Статус остаётся 'completed' (липкий, by design) …
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id,
        ).first()
        assert progress.status == 'completed'
        # … но XP за проваленную попытку не платится.
        assert _linear_events(db_session, test_user.id, 'linear_curriculum_grammar') == []

    @pytest.mark.parametrize(
        'url_template',
        [
            '/learn/{lesson_id}/',
            '/curriculum/lesson/{lesson_id}/grammar',
        ],
    )
    def test_passing_submission_still_awards(
        self, db_session, authenticated_client, test_user, test_module, url_template
    ):
        lesson = _grammar_lesson(db_session, test_module, self.EXERCISES)

        resp = authenticated_client.post(
            url_template.format(lesson_id=lesson.id),
            data={'answer_0': 'goes'},
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

        assert resp.status_code == 200
        assert len(
            _linear_events(db_session, test_user.id, 'linear_curriculum_grammar')
        ) == 1
