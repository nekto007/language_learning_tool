"""maybe_award_linear_perfect_day считает бонус по UNIFIED-плану.

Regression: раньше бонус собирал legacy linear-план (get_linear_plan),
чьи слоты расходились с required unified-плана — бонус был недостижим
для части конфигураций или выдавался без закрытия видимого плана.
"""
from datetime import date
from unittest.mock import patch

import pytest

from app.daily_plan.linear.xp import maybe_award_linear_perfect_day
from app.utils.db import db as real_db


def _unified_plan(required, *, mode='unified', graduated=False, user_id=1):
    return {
        '_plan_meta': {
            'effective_mode': mode,
            'graduated': graduated,
            'user_id': user_id,
        },
        'required': required,
        'optional': [],
    }


def _item(item_id, completed=False):
    return {'id': item_id, 'kind': item_id.split(':')[0], 'completed': completed}


class TestPerfectDayUsesUnifiedPlan:
    def test_award_when_all_unified_required_completed(self, db_session, test_user):
        plan = _unified_plan(
            [_item('curriculum:lesson:1'), _item('srs:global')],
            user_id=test_user.id,
        )
        completion = {'curriculum:lesson:1': True, 'srs:global': True}

        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value={},
        ), patch(
            'app.achievements.streak_service.compute_plan_steps',
            return_value=(completion, 2, 2, 2),
        ), patch(
            'app.daily_plan.linear.xp.award_perfect_day_xp_idempotent',
        ) as mock_award:
            maybe_award_linear_perfect_day(
                test_user.id, for_date=date(2026, 6, 11), db_session=real_db,
            )

        mock_award.assert_called_once()
        # is_linear picks PERFECT_DAY_BONUS_XP_LINEAR (25) over the legacy
        # mission bonus (50) — a flipped flag doubles every award silently.
        assert mock_award.call_args.kwargs['is_linear'] is True
        assert mock_award.call_args.args[1] == date(2026, 6, 11)

    def test_no_award_when_unified_required_incomplete(self, db_session, test_user):
        plan = _unified_plan(
            [_item('curriculum:lesson:1'), _item('srs:global')],
            user_id=test_user.id,
        )
        completion = {'curriculum:lesson:1': True, 'srs:global': False}

        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value={},
        ), patch(
            'app.achievements.streak_service.compute_plan_steps',
            return_value=(completion, 1, 1, 2),
        ), patch(
            'app.daily_plan.linear.xp.award_perfect_day_xp_idempotent',
        ) as mock_award:
            result = maybe_award_linear_perfect_day(
                test_user.id, for_date=date(2026, 6, 11), db_session=real_db,
            )

        assert result is None
        mock_award.assert_not_called()

    def test_no_award_when_plan_paused(self, db_session, test_user):
        # graduated=True so the empty-required admission rule ADMITS this plan:
        # the paused guard has to be the thing that rejects it, otherwise the
        # test passes with `effective_mode == 'paused'` no longer checked.
        plan = _unified_plan([], mode='paused', graduated=True, user_id=test_user.id)

        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value={},
        ), patch(
            'app.daily_plan.linear.xp.award_perfect_day_xp_idempotent',
        ) as mock_award:
            result = maybe_award_linear_perfect_day(
                test_user.id, for_date=date(2026, 6, 11), db_session=real_db,
            )

        assert result is None
        mock_award.assert_not_called()


class TestPerfectDayAdmissionRules:
    """Пустой required без graduated/blocked — не «идеальный день»."""

    def test_no_award_when_required_empty_and_not_graduated(self, db_session, test_user):
        plan = _unified_plan([], graduated=False, user_id=test_user.id)

        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value={},
        ), patch(
            'app.daily_plan.linear.xp.award_perfect_day_xp_idempotent',
        ) as mock_award:
            result = maybe_award_linear_perfect_day(
                test_user.id, for_date=date(2026, 6, 11), db_session=real_db,
            )

        assert result is None
        mock_award.assert_not_called()

    def test_award_when_required_empty_but_graduated(self, db_session, test_user):
        plan = _unified_plan([], graduated=True, user_id=test_user.id)

        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value={},
        ), patch(
            'app.achievements.streak_service.compute_plan_steps',
            return_value=({}, 0, 0, 0),
        ), patch(
            'app.daily_plan.service.compute_day_secured_from_activity', return_value=True,
        ), patch(
            'app.daily_plan.linear.xp.award_perfect_day_xp_idempotent',
        ) as mock_award:
            maybe_award_linear_perfect_day(
                test_user.id, for_date=date(2026, 6, 11), db_session=real_db,
            )

        mock_award.assert_called_once()


class TestPerfectDayIdempotentIsRaceSafe:
    """DP-051: голый check-then-insert под двумя новыми вызывателями.

    Проигравший гонку получает None, а не IntegrityError, и не оставляет
    начисленный XP без строки-маркера.
    """

    def _stats(self, db_session, user_id):
        from app.achievements.models import UserStatistics

        stats = UserStatistics.query.filter_by(user_id=user_id).first()
        if stats is None:
            stats = UserStatistics(user_id=user_id)
            db_session.add(stats)
            db_session.commit()
        return stats

    def test_lost_race_returns_none_without_crediting_xp(self, db_session, test_user):
        from app.achievements.models import StreakEvent
        from app.achievements.xp_service import award_perfect_day_xp_idempotent

        when = date(2026, 6, 11)
        stats = self._stats(db_session, test_user.id)
        stats.total_xp = 100
        db_session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_perfect_day',
            event_date=when,
            coins_delta=0,
            details={'xp': 25},
        ))
        db_session.commit()

        # Конкурент успел вставить строку после нашей проверки — ровно та
        # гонка, которую голый check-then-insert проигрывал исключением.
        with patch(
            'app.achievements.xp_service._perfect_day_already_awarded',
            return_value=False,
        ):
            result = award_perfect_day_xp_idempotent(
                test_user.id, when, is_linear=True,
            )

        assert result is None
        db_session.flush()
        rows = StreakEvent.query.filter_by(
            user_id=test_user.id, event_type='xp_perfect_day', event_date=when,
        ).all()
        assert len(rows) == 1
        assert int(stats.total_xp or 0) == 100

    def test_second_call_same_day_is_a_no_op(self, db_session, test_user):
        from app.achievements.models import StreakEvent
        from app.achievements.xp_service import award_perfect_day_xp_idempotent

        when = date(2026, 6, 11)
        self._stats(db_session, test_user.id)

        first = award_perfect_day_xp_idempotent(test_user.id, when, is_linear=True)
        db_session.commit()
        second = award_perfect_day_xp_idempotent(test_user.id, when, is_linear=True)
        db_session.commit()

        assert first is not None
        assert second is None
        rows = StreakEvent.query.filter_by(
            user_id=test_user.id, event_type='xp_perfect_day', event_date=when,
        ).all()
        assert len(rows) == 1
        # details заполняются после claim'а — маркер не должен остаться пустым
        assert rows[0].details.get('xp') == first.xp_awarded
        assert rows[0].details.get('consecutive_days') == 1


class TestPerfectDaySweeperOnSecuredDay:
    """DP-035: день, закрытый мимо слот-обработчиков, всё равно платит бонус.

    Бонус жил только внутри slot-хендлеров: standalone grammar-lab, book-SRS
    и игры закрывали день, ни разу не пройдя мимо начисляющего call-site, —
    30 из 72 закрытых дней прода остались без `xp_perfect_day`.
    """

    def _summary(self):
        return {
            'lessons_count': 0,
            'lesson_types': [],
            'words_reviewed': 0,
            'srs_words_reviewed': 0,
            'grammar_exercises': 0,
            'grammar_correct': 0,
            'books_read': [],
            'book_course_lessons_today': 0,
        }

    def _patches(self, plan, completion):
        summary = self._summary()
        return [
            patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan),
            patch('app.telegram.queries.get_daily_summary', return_value=summary),
            patch('app.telegram.queries.get_yesterday_summary', return_value=summary),
            patch(
                'app.achievements.streak_service.compute_plan_steps',
                return_value=(completion, 1, 1, 1),
            ),
        ]

    def _events(self, user_id):
        from app.achievements.models import StreakEvent

        return StreakEvent.query.filter_by(
            user_id=user_id, event_type='xp_perfect_day',
        ).all()

    def test_daily_status_awards_bonus_without_any_slot_handler(
        self, authenticated_client, db_session, test_user,
    ):
        plan = _unified_plan(
            [_item('curriculum:lesson:1', completed=True)], user_id=test_user.id,
        )
        completion = {'curriculum:lesson:1': True}

        p = self._patches(plan, completion)
        with p[0], p[1], p[2], p[3]:
            response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        assert response.get_json()['day_secured'] is True
        events = self._events(test_user.id)
        assert len(events) == 1
        assert events[0].details.get('xp') >= 25

    def test_two_consecutive_calls_award_once(
        self, authenticated_client, db_session, test_user,
    ):
        from app.achievements.models import UserStatistics

        plan = _unified_plan(
            [_item('curriculum:lesson:1', completed=True)], user_id=test_user.id,
        )
        completion = {'curriculum:lesson:1': True}

        p = self._patches(plan, completion)
        with p[0], p[1], p[2], p[3]:
            assert authenticated_client.get('/api/daily-status').status_code == 200
            xp_after_first = int(
                (UserStatistics.query.filter_by(user_id=test_user.id).first()
                 or UserStatistics(user_id=test_user.id)).total_xp or 0
            )
            assert authenticated_client.get('/api/daily-status').status_code == 200

        events = self._events(test_user.id)
        assert len(events) == 1
        xp_after_second = int(
            UserStatistics.query.filter_by(user_id=test_user.id).first().total_xp or 0
        )
        assert xp_after_second == xp_after_first

    def test_no_bonus_when_day_not_secured(
        self, authenticated_client, db_session, test_user,
    ):
        plan = _unified_plan(
            [_item('curriculum:lesson:1'), _item('srs:global')], user_id=test_user.id,
        )
        completion = {'curriculum:lesson:1': True, 'srs:global': False}

        p = self._patches(plan, completion)
        with p[0], p[1], p[2], p[3]:
            response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        assert response.get_json()['day_secured'] is False
        assert self._events(test_user.id) == []

    def test_no_bonus_on_paused_day(
        self, authenticated_client, db_session, test_user,
    ):
        plan = _unified_plan([], mode='paused', user_id=test_user.id)
        plan['day_secured'] = True

        p = self._patches(plan, {})
        with p[0], p[1], p[2], p[3]:
            response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        assert self._events(test_user.id) == []

    def test_no_bonus_when_required_empty_and_not_graduated(
        self, authenticated_client, db_session, test_user,
    ):
        plan = _unified_plan([], graduated=False, user_id=test_user.id)

        p = self._patches(plan, {})
        with p[0], p[1], p[2], p[3]:
            response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        assert response.get_json()['day_secured'] is False
        assert self._events(test_user.id) == []


class TestPerfectDaySweeperOnDashboard:
    """Второй писатель `secured_at` — дашборд — тоже подметает бонус.

    Юзер, закрывший день без единого захода в `/api/daily-status`, получает
    бонус на первом же рендере дашборда.
    """

    def _enable_words_module(self, db_session, user_id):
        from app.modules.models import SystemModule, UserModule

        module = SystemModule.query.filter_by(code='words').first()
        if module is None:
            module = SystemModule(code='words', name='Words')
            db_session.add(module)
            db_session.commit()
        if not UserModule.query.filter_by(
            user_id=user_id, module_id=module.id,
        ).first():
            db_session.add(UserModule(
                user_id=user_id, module_id=module.id, is_enabled=True,
            ))
            db_session.commit()

    def test_dashboard_awards_bonus_on_secured_day(
        self, authenticated_client, db_session, test_user,
    ):
        from app.achievements.models import StreakEvent

        self._enable_words_module(db_session, test_user.id)
        plan = _unified_plan(
            [_item('curriculum:lesson:1', completed=True)], user_id=test_user.id,
        )
        completion = {'curriculum:lesson:1': True}

        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value={},
        ), patch(
            'app.achievements.streak_service.compute_plan_steps',
            return_value=(completion, 1, 1, 1),
        ):
            response = authenticated_client.get('/dashboard')

        assert response.status_code == 200
        events = StreakEvent.query.filter_by(
            user_id=test_user.id, event_type='xp_perfect_day',
        ).all()
        assert len(events) == 1
        assert events[0].details.get('xp') >= 25


class TestSecuredWritersCarryTheSameSweepers:
    """Оба писателя `secured_at` несут ОДИН набор подметальщиков.

    Контракт зоны: `daily_status` и `_render_unified_dashboard` обязаны нести
    `record_plan_completion`, `emit_daily_plan_completed`, `emit_minimum_completed`,
    `check_immersion_achievement`, `maybe_award_linear_perfect_day` и
    `check_plan_streak_milestone_notification`. Часть из них жила только в
    `/api/daily-status`, а этот эндпоинт фронт вообще не зовёт (grep по
    `app/templates` + `app/static` — ноль вызовов), поэтому веб-юзер не получал
    ни майлстоун «план дня выполнен», ни всё семейство ачивок иммерсии, ни
    уведомления о майлстоунах серии.
    """

    def _enable_words_module(self, db_session, user_id):
        from app.modules.models import SystemModule, UserModule

        module = SystemModule.query.filter_by(code='words').first()
        if module is None:
            module = SystemModule(code='words', name='Words')
            db_session.add(module)
            db_session.commit()
        if not UserModule.query.filter_by(
            user_id=user_id, module_id=module.id,
        ).first():
            db_session.add(UserModule(
                user_id=user_id, module_id=module.id, is_enabled=True,
            ))
            db_session.commit()

    def _drive_dashboard(self, client, test_user, calls):
        plan = _unified_plan(
            [_item('curriculum:lesson:1', completed=True)], user_id=test_user.id,
        )
        completion = {'curriculum:lesson:1': True}

        def _spy_immersion(user_id, target_date, db_session_arg=None, tz='UTC'):
            calls['immersion'] = {'target_date': target_date, 'tz': tz}
            return []

        def _spy_milestone(user_id, plan_date, db_arg):
            calls['milestone'] = {'plan_date': plan_date}
            return True

        def _spy_streak_milestone(user_id, current_streak, plan_date):
            calls['streak_milestone'] = {
                'streak': current_streak, 'plan_date': plan_date,
            }

        with patch(
            'app.notifications.services.check_plan_streak_milestone_notification',
            side_effect=_spy_streak_milestone,
        ), patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value={},
        ), patch(
            'app.achievements.streak_service.compute_plan_steps',
            return_value=(completion, 1, 1, 1),
        ), patch(
            'app.achievements.services.check_immersion_achievement',
            side_effect=_spy_immersion,
        ), patch(
            'app.daily_plan.milestones.emit_daily_plan_completed',
            side_effect=_spy_milestone,
        ):
            return client.get('/dashboard')

    def test_dashboard_emits_the_day_completed_milestone(
        self, authenticated_client, db_session, test_user,
    ):
        from app.utils.time_utils import get_user_local_date

        self._enable_words_module(db_session, test_user.id)
        calls: dict = {}
        response = self._drive_dashboard(authenticated_client, test_user, calls)

        assert response.status_code == 200
        assert 'milestone' in calls, 'дашборд не позвал emit_daily_plan_completed'
        assert calls['milestone']['plan_date'] == get_user_local_date(
            test_user.id, real_db,
        )

    def test_dashboard_checks_immersion_with_the_profile_timezone(
        self, authenticated_client, db_session, test_user,
    ):
        from app.utils.time_utils import get_user_local_date

        test_user.timezone = 'Europe/Moscow'
        db_session.commit()
        self._enable_words_module(db_session, test_user.id)
        calls: dict = {}
        response = self._drive_dashboard(authenticated_client, test_user, calls)

        assert response.status_code == 200
        assert 'immersion' in calls, 'дашборд не позвал check_immersion_achievement'
        # Зона обязана быть той, из которой выведена дата, иначе окно уедет.
        assert calls['immersion']['tz'] == 'Europe/Moscow'
        assert calls['immersion']['target_date'] == get_user_local_date(
            test_user.id, real_db,
        )

    def test_dashboard_calls_plan_streak_milestone_notification(
        self, authenticated_client, db_session, test_user,
    ):
        """Шестой подметальщик закрытого дня жил только на `/api/daily-status`.

        Тот же класс, что `DP-035`: эндпоинт, который фронт не зовёт, — значит
        майлстоуны серии были недостижимы для веб-юзера. На дашборде вызов идёт
        ПОСЛЕ `process_streak_on_activity`, потому что ему нужен посчитанный
        streak, и получает ту же учебную дату, под которой записан `secured_at`.
        """
        from app.utils.time_utils import get_user_local_date

        self._enable_words_module(db_session, test_user.id)
        calls: dict = {}
        response = self._drive_dashboard(authenticated_client, test_user, calls)

        assert response.status_code == 200
        assert 'streak_milestone' in calls, (
            'дашборд не позвал check_plan_streak_milestone_notification'
        )
        assert calls['streak_milestone']['plan_date'] == get_user_local_date(
            test_user.id, real_db,
        )

    def test_milestone_notification_is_not_repeated_on_every_render(
        self, authenticated_client, db_session, test_user,
    ):
        """Дедуп майлстоуна держится на строке `minimum_completed`.

        Она пишется вторым вызовом; без неё уведомление создавалось бы заново
        на КАЖДОМ рендере дашборда.
        """
        from app.daily_plan.milestones import (
            NOTIFICATION_TYPE as MILESTONE_NOTIFICATION_TYPE,
        )
        from app.notifications.models import Notification

        self._enable_words_module(db_session, test_user.id)
        plan = _unified_plan(
            [_item('curriculum:lesson:1', completed=True)], user_id=test_user.id,
        )
        completion = {'curriculum:lesson:1': True}

        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value={},
        ), patch(
            'app.achievements.streak_service.compute_plan_steps',
            return_value=(completion, 1, 1, 1),
        ):
            def _milestones() -> int:
                # Filtered by type: an unfiltered count sweeps up rank_up /
                # level_up / plan_streak_milestone rows, and `second == first`
                # then holds even when the milestone is never created at all.
                return Notification.query.filter_by(
                    user_id=test_user.id, type=MILESTONE_NOTIFICATION_TYPE,
                ).count()

            assert authenticated_client.get('/dashboard').status_code == 200
            first = _milestones()
            assert authenticated_client.get('/dashboard').status_code == 200
            second = _milestones()

        assert first == 1, 'майлстоун вообще не создался — дедуп нечему держать'
        assert second == 1


class TestPerfectDayClaimIsReleasedOnFailure:
    """Claim-first не имеет права сжечь день, если начисление упало.

    Маркер `xp_perfect_day` И ЕСТЬ ключ идемпотентности, а оба подметальщика
    глотают исключение и всё равно коммитят. Строка, оставшаяся без XP,
    заблокировала бы бонус за этот день навсегда.
    """

    def test_failed_award_removes_the_claim(self, db_session, test_user):
        from app.achievements.models import StreakEvent
        from app.achievements.xp_service import award_perfect_day_xp_idempotent

        for_date = date(2026, 5, 20)

        with patch(
            'app.achievements.xp_service.award_xp',
            side_effect=RuntimeError('boom'),
        ):
            try:
                award_perfect_day_xp_idempotent(
                    test_user.id, for_date, is_linear=True,
                )
            except RuntimeError:
                pass
            else:
                raise AssertionError('исключение обязано дойти до вызывающего')

        assert StreakEvent.query.filter_by(
            user_id=test_user.id,
            event_type='xp_perfect_day',
            event_date=for_date,
        ).count() == 0

    def test_retry_after_a_failed_award_still_pays(self, db_session, test_user):
        from app.achievements.models import StreakEvent
        from app.achievements.xp_service import award_perfect_day_xp_idempotent

        for_date = date(2026, 5, 21)

        with patch(
            'app.achievements.xp_service.award_xp',
            side_effect=RuntimeError('boom'),
        ):
            with pytest.raises(RuntimeError):
                award_perfect_day_xp_idempotent(
                    test_user.id, for_date, is_linear=True,
                )

        result = award_perfect_day_xp_idempotent(
            test_user.id, for_date, is_linear=True,
        )
        assert result is not None
        assert result.xp_awarded > 0
        marker = StreakEvent.query.filter_by(
            user_id=test_user.id,
            event_type='xp_perfect_day',
            event_date=for_date,
        ).one()
        assert marker.details.get('xp') == result.xp_awarded
