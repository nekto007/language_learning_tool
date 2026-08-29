"""Часовой генератор снапшотов бьётся с границей учебного дня.

Джоба пре-генерирует снапшот «сегодня» для каждого активного юзера. Она
срабатывала на календарной полуночи, то есть за ДВА ЧАСА до того, как
предыдущий учебный день закрывался: решение о переносе (`rolled_over_from`)
для дня D принималось, пока день D-1 ещё шёл, и работа, сделанная между
00:00 и 02:00, повлиять на него не могла. Запрос-путь
(`get_daily_plan` → `get_user_local_date`) всегда жил на учебном дне.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from freezegun import freeze_time

from app.telegram.scheduler import _generate_daily_plans_hourly


MOSCOW = 'Europe/Moscow'  # UTC+3, без DST


def _run_at(app, frozen_utc: str) -> list:
    """Прогнать джобу в замороженный момент, вернуть аргументы резолвера."""
    seen: list = []

    def _spy(user_id, plan_date, db_arg):
        seen.append((user_id, plan_date))
        return {'items': []}

    with freeze_time(frozen_utc), patch(
        'app.daily_plan.snapshot.resolve_snapshot_for_today', side_effect=_spy,
    ):
        _generate_daily_plans_hourly(app)
    return seen


class TestGenerationFiresAtTheStudyDayBoundary:

    def test_calendar_midnight_does_not_trigger(self, app, db_session, test_user):
        test_user.timezone = MOSCOW
        test_user.active = True
        db_session.commit()

        # 21:10 UTC = 00:10 по Москве — календарная полночь, учебный день ещё вчера.
        seen = _run_at(app, '2026-09-14 21:10:00')
        assert [row for row in seen if row[0] == test_user.id] == []

    def test_study_day_start_triggers_with_the_new_days_date(
        self, app, db_session, test_user,
    ):
        test_user.timezone = MOSCOW
        test_user.active = True
        db_session.commit()

        # 23:10 UTC 14-го = 02:10 по Москве 15-го — учебный день только что сменился.
        seen = _run_at(app, '2026-09-14 23:10:00')

        assert (test_user.id, date(2026, 9, 15)) in seen

    def test_inactive_user_is_skipped(self, app, db_session, test_user):
        test_user.timezone = MOSCOW
        test_user.active = False
        db_session.commit()

        seen = _run_at(app, '2026-09-14 23:10:00')
        assert [row for row in seen if row[0] == test_user.id] == []
