"""DP-001 (фундамент): единый учебный день во всех окнах активности.

Учебный день начинается в 02:00 локального времени (``LEARNING_DAY_START_HOUR``)
— это осознанное решение владельца, и ``get_user_local_date`` уже так работает.
До ремедиации ``_user_day_boundaries`` (app/telegram/queries.py) строил окно от
календарной полуночи, поэтому активность в 00:00–02:00 попадала в один день по
дедуп-ключам XP и в другой — по окнам активности streak/телеграма. Практическое
следствие: юзер, занимавшийся в 01:00, объявлялся пропустившим предыдущий день,
и починка серии тратилась не на ту дату.

Тесты фиксируют один базис для обоих семейств хелперов.
"""
from datetime import UTC
from datetime import date as date_cls
from datetime import datetime, timedelta
from itertools import pairwise
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from app.achievements.models import StreakEvent
from app.achievements.streak_service import find_missed_date
from app.telegram.queries import _user_day_boundaries, has_activity_today
from app.utils.time_utils import (
    LEARNING_DAY_START_HOUR,
    day_to_naive_utc,
    get_user_local_date,
    get_user_local_day_bounds,
    study_day_bounds_utc,
    study_day_start_utc,
)

MOSCOW = 'Europe/Moscow'  # UTC+3, без DST — локальное = UTC+3 круглый год


@pytest.fixture()
def moscow_user(db_session, test_user):
    test_user.timezone = MOSCOW
    db_session.flush()
    return test_user


def _log_activity(db_session, user_id, created_at_utc_naive):
    """Пишем активность 7-го источника (`xp_linear`) — naive UTC, как в колонке."""
    db_session.add(StreakEvent(
        user_id=user_id,
        event_type='xp_linear',
        coins_delta=0,
        event_date=created_at_utc_naive.date(),
        created_at=created_at_utc_naive,
        details={'source': 'test'},
    ))
    db_session.flush()


# ---------------------------------------------------------------------------
# 1. Канонический хелпер окна учебного дня
# ---------------------------------------------------------------------------

class TestStudyDayBoundsUtc:

    @freeze_time('2026-08-19 22:30:00')  # 01:30 20 августа по Москве
    def test_window_before_two_am_belongs_to_previous_day(self):
        start, end = study_day_bounds_utc(MOSCOW)
        # Учебный день = 19 августа: 02:00 19-го … 02:00 20-го по Москве.
        assert start == datetime(2026, 8, 18, 23, 0, tzinfo=UTC)
        assert end == datetime(2026, 8, 19, 23, 0, tzinfo=UTC)

    @freeze_time('2026-08-19 22:30:00')
    def test_now_is_inside_its_own_window(self):
        start, end = study_day_bounds_utc(MOSCOW)
        assert start <= datetime.now(UTC) < end

    @freeze_time('2026-08-20 07:00:00')  # 10:00 по Москве
    def test_offset_days_walks_back_whole_study_days(self):
        today_start, today_end = study_day_bounds_utc(MOSCOW)
        y_start, y_end = study_day_bounds_utc(MOSCOW, offset_days=-1)
        assert y_end == today_start
        assert today_end - today_start == timedelta(days=1)
        assert y_start == datetime(2026, 8, 18, 23, 0, tzinfo=UTC)

    @freeze_time('2026-08-20 07:00:00')
    def test_windows_are_contiguous_no_gap_no_overlap(self):
        bounds = [study_day_bounds_utc(MOSCOW, offset_days=-o) for o in range(0, 5)]
        for newer, older in pairwise(bounds):
            assert older[1] == newer[0]

    @freeze_time('2026-08-19 22:30:00')
    def test_anchor_is_learning_day_start_hour(self):
        import pytz
        start, _ = study_day_bounds_utc(MOSCOW)
        assert start.astimezone(pytz.timezone(MOSCOW)).hour == LEARNING_DAY_START_HOUR

    def test_unknown_timezone_falls_back_to_default_not_utc(self):
        """Политика фолбэка сохранена дословно от `_user_day_boundaries`.

        Неизвестная зона → DEFAULT_TIMEZONE, а НЕ UTC (расхождение pytz/ZoneInfo
        в `_get_user_timezone` — DP-082 — в эту фазу сознательно не чинится).
        """
        from config.settings import DEFAULT_TIMEZONE
        assert study_day_bounds_utc('Mars/Olympus') == study_day_bounds_utc(DEFAULT_TIMEZONE)

    @freeze_time('2026-08-19 22:30:00')
    def test_agrees_with_get_user_local_day_bounds(self, moscow_user, db_session):
        """Новый хелпер обязан описывать ТЕ ЖЕ сутки, что уже существующие."""
        start, end = study_day_bounds_utc(MOSCOW)
        legacy_start, legacy_end = get_user_local_day_bounds(moscow_user.id, db_session)
        assert start.replace(tzinfo=None) == legacy_start
        assert end.replace(tzinfo=None) == legacy_end
        assert start.replace(tzinfo=None) == day_to_naive_utc(moscow_user.id, db_session)

    @pytest.mark.parametrize('tz_name, transition_day', [
        # Осенний перевод: 03:00 → 02:00, поэтому 02:00 локального — час,
        # который случается ДВАЖДЫ. pytz `localize` по умолчанию (is_dst=False)
        # берёт второе вхождение, ZoneInfo (fold=0) — первое, и два семейства
        # хелперов расходились на час раз в год ровно в тот момент, ради
        # согласования которого вся фаза и делалась.
        ('Europe/Berlin', date_cls(2026, 10, 25)),
        ('Europe/Kyiv', date_cls(2026, 10, 25)),
        # Весенний перевод: 02:00 локального не существует вовсе.
        ('Europe/Berlin', date_cls(2026, 3, 29)),
        # Зона с переводом не в 03:00 — контроль, что общий случай не сломан.
        ('America/New_York', date_cls(2026, 11, 1)),
        ('America/New_York', date_cls(2026, 3, 8)),
    ])
    def test_dst_transition_days_agree_with_zoneinfo_basis(self, tz_name, transition_day):
        """`study_day_start_utc` обязан совпадать с базисом `day_to_naive_utc`.

        `day_to_naive_utc` (SRS-счётчики, дедуп XP) строит 02:00 через ZoneInfo;
        если оконный хелпер решает ту же дату иначе, активность одного часа
        уезжает в разные учебные дни у разных потребителей.
        """
        from zoneinfo import ZoneInfo

        expected = datetime(
            transition_day.year, transition_day.month, transition_day.day,
            LEARNING_DAY_START_HOUR, tzinfo=ZoneInfo(tz_name),
        ).astimezone(UTC)
        assert study_day_start_utc(tz_name, transition_day) == expected

    def test_start_and_bounds_share_one_anchor_on_a_dst_day(self):
        """Окно, построенное «от сейчас», и окно от сохранённой даты — одно и то же."""
        with freeze_time('2026-10-25 09:00:00'):
            start, _end = study_day_bounds_utc('Europe/Berlin')
        assert start == study_day_start_utc('Europe/Berlin', date_cls(2026, 10, 25))


# ---------------------------------------------------------------------------
# 2. Телеграм-обёртка `_user_day_boundaries` на том же базисе
# ---------------------------------------------------------------------------

class TestUserDayBoundariesBasis:

    @freeze_time('2026-08-19 22:30:00')  # 01:30 20 августа по Москве
    def test_boundaries_use_study_day_not_calendar_midnight(self):
        start, end = _user_day_boundaries(MOSCOW)
        assert start == datetime(2026, 8, 18, 23, 0, tzinfo=UTC)
        assert end == datetime(2026, 8, 19, 23, 0, tzinfo=UTC)

    @freeze_time('2026-08-19 22:30:00')
    def test_matches_canonical_helper_for_every_offset(self):
        for offset in (0, -1, -2, -7):
            assert _user_day_boundaries(MOSCOW, offset_days=offset) == \
                study_day_bounds_utc(MOSCOW, offset_days=offset)

    def test_unknown_timezone_still_falls_back_to_default_tz(self):
        from app.telegram.queries import DEFAULT_TZ
        assert _user_day_boundaries('Not/AZone') == _user_day_boundaries(DEFAULT_TZ)

    @freeze_time('2026-08-19 22:30:00')
    def test_local_date_and_activity_window_agree(self, moscow_user, db_session):
        """Один и тот же момент — одна и та же «сегодняшняя» дата в обоих семействах."""
        start, _ = _user_day_boundaries(MOSCOW)
        import pytz
        assert start.astimezone(pytz.timezone(MOSCOW)).date() == \
            get_user_local_date(moscow_user.id, db_session)

    @freeze_time('2026-08-19 22:30:00')  # 01:30 20 августа по Москве
    def test_late_evening_activity_counts_as_today_after_midnight(
            self, moscow_user, db_session):
        """Занятие в 23:00 — всё ещё «сегодня» в 01:30 следующей календарной даты."""
        _log_activity(db_session, moscow_user.id, datetime(2026, 8, 19, 20, 0))  # 23:00 МСК
        assert has_activity_today(moscow_user.id, tz=MOSCOW) is True


# ---------------------------------------------------------------------------
# 3. Починка серии не должна объявлять ночную сессию пропуском
# ---------------------------------------------------------------------------

class TestFindMissedDateStudyDayBasis:

    @freeze_time('2026-08-20 07:00:00')  # 10:00 20 августа по Москве
    def test_one_am_session_is_not_a_missed_day(self, moscow_user, db_session):
        """DP-001: занятие в 01:00 20-го — это учебный день 19-го, не пропуск.

        До фикса окно 19-го строилось от календарной полуночи, сессия в него не
        попадала, и `find_missed_date` возвращал 19 августа — починка (щит или
        бесплатная) тратилась на день, в который юзер занимался.
        """
        # Якорь серии: 18 августа, 12:00 МСК.
        _log_activity(db_session, moscow_user.id, datetime(2026, 8, 18, 9, 0))
        # Ночная сессия: 01:00 20 августа МСК = 22:00 19 августа UTC.
        _log_activity(db_session, moscow_user.id, datetime(2026, 8, 19, 22, 0))

        assert find_missed_date(moscow_user.id, tz=MOSCOW) is None

    @freeze_time('2026-08-20 07:00:00')
    def test_real_gap_is_still_detected(self, moscow_user, db_session):
        """Страж от «починили, отключив детектор»: настоящая дырка видна."""
        _log_activity(db_session, moscow_user.id, datetime(2026, 8, 18, 9, 0))  # 18-е
        _log_activity(db_session, moscow_user.id, datetime(2026, 8, 20, 6, 0))  # 20-е
        assert find_missed_date(moscow_user.id, tz=MOSCOW) == \
            datetime(2026, 8, 19).date()

    @freeze_time('2026-08-19 22:30:00')  # 01:30 20 августа по Москве, учебный день 19-го
    def test_returned_date_is_the_study_day_date(self, moscow_user, db_session):
        """Возвращаемая дата обязана описывать ТО ЖЕ окно, в котором найдена дырка.

        `check_date` считался как `datetime.now(tz).date() - offset`, то есть по
        календарю: между 00:00 и 02:00 он уезжал на день вперёд относительно
        собственного окна, и починка писалась в `streak_events` под чужой датой.
        """
        # Якорь серии — учебный день 17 августа (12:00 МСК).
        _log_activity(db_session, moscow_user.id, datetime(2026, 8, 17, 9, 0))
        # Учебный день 18 августа пуст — это и есть дырка.
        missed = find_missed_date(moscow_user.id, tz=MOSCOW)
        assert missed == datetime(2026, 8, 18).date()
        start, _end = _user_day_boundaries(MOSCOW, offset_days=-1)
        import pytz
        assert start.astimezone(pytz.timezone(MOSCOW)).date() == missed


# ---------------------------------------------------------------------------
# 4. Один базис внутри process_streak_on_activity
# ---------------------------------------------------------------------------

class TestProcessStreakSingleBasis:

    def test_repair_lookups_use_user_timezone_not_client_tz(self, db_session, test_user):
        """DP-001 (второй базис): выбор чинимой даты не зависит от клиентского ?tz=.

        `real_activity` уже читал User.timezone, а `find_missed_date` /
        `get_streak_status` / `auto_heal_streak_on_activity` получали клиентский
        параметр — три разных дня в одном вызове.
        """
        from app.achievements import streak_service

        test_user.timezone = 'Asia/Tokyo'
        db_session.flush()

        seen: dict[str, str] = {}

        def _capture(name):
            def _inner(user_id, tz=None, **kwargs):
                seen[name] = tz
                return None if name != 'auto_heal' else 0
            return _inner

        def _status(user_id, tz=None, steps_total=4):
            seen['status'] = tz
            return {
                'streak': 5, 'coins_balance': 0, 'has_activity_today': True,
                'can_repair': False, 'missed_date': None, 'repair_cost': None,
                'required_steps': 1, 'steps_total': steps_total,
            }

        with patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch.object(streak_service, 'find_missed_date', _capture('missed')), \
             patch.object(streak_service, 'auto_heal_streak_on_activity', _capture('auto_heal')), \
             patch.object(streak_service, 'get_streak_status', _status), \
             patch.object(streak_service, 'check_streak_milestone', return_value=None):
            streak_service.process_streak_on_activity(
                test_user.id, steps_done=1, steps_total=1, tz='Pacific/Kiritimati',
            )

        assert seen['missed'] == 'Asia/Tokyo'
        assert seen['auto_heal'] == 'Asia/Tokyo'
        assert seen['status'] == 'Asia/Tokyo'
