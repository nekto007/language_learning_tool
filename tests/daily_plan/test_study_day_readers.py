"""Кластер границы суток, читатели дат: DP-008/010/012/013/022/026.

Writers уже пишут на учебном дне (граница 02:00, ``LEARNING_DAY_START_HOUR``):
XP-события, `DailyStudyMinutes`, `DailyPlanLog.plan_date`, кохорта гонки.
Читатели же брали календарную дату — часть от клиентского `?tz=`, часть от
собственного pytz-стека. В окне 00:00-02:00 локального времени это ровно
сутки расхождения: строка записана под вчера, читатель спрашивает про сегодня
и не находит ничего.

Каждый класс ниже краснеет при откате своей находки.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from app.utils.db import db as app_db

# UTC как таймзона юзера: локальное время == UTC, поэтому freeze_time на
# 00:30 даёт ровно то окно 00:00-02:00, ради которого всё это и пишется.
NIGHT = '2026-09-15 00:30:00'          # календарная дата 15-е
STUDY_DAY = date(2026, 9, 14)          # учебный день — ещё 14-е
CALENDAR_DAY = date(2026, 9, 15)


@pytest.fixture()
def utc_user(db_session, test_user):
    test_user.timezone = 'UTC'
    db_session.commit()
    return test_user


def _enable_words_module(db_session, user_id):
    from app.modules.models import SystemModule, UserModule

    module = SystemModule.query.filter_by(code='words').first()
    if module is None:
        module = SystemModule(code='words', name='Words')
        db_session.add(module)
        db_session.commit()
    if not UserModule.query.filter_by(user_id=user_id, module_id=module.id).first():
        db_session.add(UserModule(user_id=user_id, module_id=module.id, is_enabled=True))
        db_session.commit()


# ── DP-008: «XP сегодня» на дашборде ─────────────────────────────────────────

class TestDashboardXpTodayIsStudyDay:
    """Виджет «XP сегодня» ищет события под учебной датой, а не календарной.

    Записи XP ключуются `get_user_local_date` (учебный день). Виджет брал
    `datetime.now(tz).date()` от клиентского `tz`, поэтому XP, заработанный
    в 00:30, искался под завтрашней датой и не находился НИКОГДА: до 02:00
    его нет под календарным «сегодня», а после 02:00 виджет уже спрашивает
    про следующий день.
    """

    def _award(self, db_session, user_id, event_date, xp):
        from app.achievements.models import StreakEvent

        db_session.add(StreakEvent(
            user_id=user_id,
            event_type='xp_linear',
            event_date=event_date,
            coins_delta=0,
            details={'source': 'linear_srs_global', 'xp': xp},
        ))
        db_session.commit()

    def test_xp_written_on_study_day_is_visible_at_00_30(self, app, db_session, utc_user):
        from app.achievements.xp_service import get_today_xp
        from app.utils.time_utils import get_user_local_date

        self._award(db_session, utc_user.id, STUDY_DAY, 20)

        with app.test_request_context(), freeze_time(NIGHT):
            local_date = get_user_local_date(utc_user.id, app_db)
            assert local_date == STUDY_DAY
            assert get_today_xp(utc_user.id, local_date) == 20

    def test_calendar_date_would_miss_it(self, app, db_session, utc_user):
        """Явно фиксируем цену отката: календарная дата даёт 0."""
        from app.achievements.xp_service import get_today_xp

        self._award(db_session, utc_user.id, STUDY_DAY, 20)

        with app.test_request_context(), freeze_time(NIGHT):
            assert get_today_xp(utc_user.id, CALENDAR_DAY) == 0

    def test_dashboard_renders_study_day_xp(self, authenticated_client, db_session, test_user):
        from app.achievements.xp_service import get_today_xp

        test_user.timezone = 'UTC'
        db_session.commit()
        _enable_words_module(db_session, test_user.id)
        self._award(db_session, test_user.id, STUDY_DAY, 33)

        seen: list = []
        real_get_today_xp = get_today_xp

        def _spy(user_id, for_date=None):
            seen.append(for_date)
            return real_get_today_xp(user_id, for_date)

        with freeze_time(NIGHT), patch(
            'app.achievements.xp_service.get_today_xp', side_effect=_spy,
        ), patch(
            'app.achievements.streak_service.compute_plan_steps',
            return_value=({}, 0, 0, 0),
        ):
            response = authenticated_client.get('/dashboard')

        assert response.status_code == 200
        assert seen, 'виджет XP не был вызван — тест потерял точку наблюдения'
        assert seen[0] == STUDY_DAY


# ── DP-010: minutes_studied_today ────────────────────────────────────────────

class TestStudyMinutesReadOnStudyDay:
    """Читатель `DailyStudyMinutes` берёт ту же дату, что писатель.

    Писатель — `award_linear_slot_xp_idempotent` → `add_study_minutes(when=…)`,
    где `when` = учебный день. Читатель `_compute_study_minutes` брал
    календарную дату, и минуты, начисленные в 00:00-02:00, не показывались
    никогда: строка навсегда осталась под вчерашней датой.
    """

    def test_minutes_written_by_the_awarder_are_read_back(self, app, db_session, utc_user):
        from app.api.daily_plan import _compute_study_minutes
        from app.curriculum.models import add_study_minutes
        from app.utils.time_utils import get_user_local_date

        with app.test_request_context(), freeze_time(NIGHT):
            # Пишем ровно так, как пишет XP-хелпер: по учебной дате.
            when = get_user_local_date(utc_user.id, app_db)
            add_study_minutes(utc_user.id, when, 12, app_db)
            db_session.commit()

            assert when == STUDY_DAY
            assert _compute_study_minutes(utc_user, 'UTC') == 12

    def test_row_under_calendar_date_is_not_read(self, app, db_session, utc_user):
        """Строка под календарной датой читателю не видна — базис один."""
        from app.api.daily_plan import _compute_study_minutes
        from app.curriculum.models import add_study_minutes

        with app.test_request_context(), freeze_time(NIGHT):
            add_study_minutes(utc_user.id, CALENDAR_DAY, 40, app_db)
            db_session.commit()

            assert _compute_study_minutes(utc_user, 'UTC') == 0

    def test_client_tz_cannot_shift_the_lookup(self, app, db_session, utc_user):
        from app.api.daily_plan import _compute_study_minutes
        from app.curriculum.models import add_study_minutes

        with app.test_request_context(), freeze_time(NIGHT):
            add_study_minutes(utc_user.id, STUDY_DAY, 7, app_db)
            db_session.commit()

            # Клиент врёт про зону — дата дедупа не двигается.
            assert _compute_study_minutes(utc_user, 'Pacific/Kiritimati') == 7


# ── DP-012: дата кохорты гонки ───────────────────────────────────────────────

class TestRaceCohortDateSingleBasis:
    """Дашборд и `/api/daily-race` резолвят одну и ту же кохорту.

    `get_or_create_race` ищет строку по точному `race_date`; два разных
    базиса дня давали две кохорты за один реальный день.
    """

    def test_widget_and_api_agree_at_00_30(self, app, db_session, utc_user):
        from app.utils.time_utils import get_user_local_date

        seen: list = []

        def _capture(user_id, race_date, **kwargs):
            seen.append(race_date)
            return None  # виджет/роут просто выйдут раньше

        with app.test_request_context(), freeze_time(NIGHT):
            api_date = get_user_local_date(utc_user.id, app_db)

            with patch(
                'app.achievements.daily_race.get_race_standings', side_effect=_capture,
            ), patch(
                'app.admin.site_settings.get_site_setting', return_value='true',
            ):
                from app.words.routes import _build_daily_race_widget
                _build_daily_race_widget(utc_user.id, 'UTC')

        assert seen == [api_date] == [STUDY_DAY]

    def test_client_tz_does_not_move_the_widget_cohort(self, app, db_session, utc_user):
        seen: list = []

        def _capture(user_id, race_date, **kwargs):
            seen.append(race_date)
            return None

        with app.test_request_context(), freeze_time(NIGHT):
            with patch(
                'app.achievements.daily_race.get_race_standings', side_effect=_capture,
            ), patch(
                'app.admin.site_settings.get_site_setting', return_value='true',
            ):
                from app.words.routes import _build_daily_race_widget
                _build_daily_race_widget(utc_user.id, 'Pacific/Kiritimati')

        assert seen == [STUDY_DAY]


# ── DP-026: граница учебной недели ───────────────────────────────────────────

class TestWeeklyGoalWeekStartsOnStudyMonday:
    """`weekly_lessons` считает неделю от учебного понедельника.

    `daily_words` всегда считался от 02:00 (`count_new_cards_today`).
    Неделя же начиналась в календарную полночь, поэтому в понедельник
    00:30 счётчик недели уже обнулялся, а дневной ещё показывал воскресный
    учебный день — два поля одного объекта `goal_progress` отчитывались
    про разные недели.
    """

    MONDAY_NIGHT = '2026-09-14 00:30:00'   # понедельник по календарю
    SUNDAY_STUDY_DAY = date(2026, 9, 13)   # учебный день — ещё воскресенье

    def _extra_lesson(self, db_session, module_id, number):
        """LessonProgress уникален по (user, lesson) — на второй урок нужен свой."""
        from app.curriculum.models import Lessons

        lesson = Lessons(
            module_id=module_id, number=number, title=f'Week lesson {number}',
            type='quiz', order=number, content={'questions': []},
        )
        db_session.add(lesson)
        db_session.commit()
        return lesson

    def _complete_lesson(self, db_session, user_id, lesson_id, completed_at):
        from app.curriculum.models import LessonProgress

        row = LessonProgress(
            user_id=user_id, lesson_id=lesson_id,
            status='completed', score=100.0, completed_at=completed_at,
        )
        db_session.add(row)
        db_session.commit()
        return row

    def test_sunday_night_lesson_still_counts_for_the_old_week(
        self, app, db_session, utc_user, test_lesson_quiz,
    ):
        from app.api.daily_plan import _compute_goal_progress

        # 21:00 воскресенья — бесспорно прошлая неделя по любому базису.
        self._complete_lesson(
            db_session, utc_user.id, test_lesson_quiz.id,
            datetime(2026, 9, 13, 21, 0, 0),
        )

        with app.test_request_context(), freeze_time(self.MONDAY_NIGHT):
            result = _compute_goal_progress(utc_user, 'UTC')

        # Учебная неделя ещё не сменилась (учебный день = воскресенье),
        # поэтому воскресный урок в счётчике остаётся.
        assert result['goal_progress']['weekly_lessons']['actual'] == 1

    def test_midweek_lesson_is_not_dropped_by_a_premature_week_reset(
        self, app, db_session, utc_user, test_lesson_quiz, test_module,
    ):
        """Учебная неделя в 00:30 понедельника ещё прошлая — среда в счёте.

        Календарная граница сбрасывала неделю уже в 00:00 понедельника, и
        всё, сделанное со вторника по воскресенье, исчезало из счётчика на
        два часа раньше срока.
        """
        from app.api.daily_plan import _compute_goal_progress

        # Среда прошедшей учебной недели + урок в 00:30 понедельника,
        # который по учебному дню всё ещё воскресенье той же недели.
        night_lesson = self._extra_lesson(db_session, test_module.id, 91)
        self._complete_lesson(
            db_session, utc_user.id, test_lesson_quiz.id,
            datetime(2026, 9, 9, 12, 0, 0),
        )
        self._complete_lesson(
            db_session, utc_user.id, night_lesson.id,
            datetime(2026, 9, 14, 0, 30, 0),
        )

        with app.test_request_context(), freeze_time(self.MONDAY_NIGHT):
            result = _compute_goal_progress(utc_user, 'UTC')

        assert result['goal_progress']['weekly_lessons']['actual'] == 2

    def test_new_week_starts_at_02_00_not_at_midnight(
        self, app, db_session, utc_user, test_lesson_quiz,
    ):
        """Урок в 01:00 понедельника принадлежит ПРОШЛОЙ учебной неделе.

        Зеркало предыдущего теста: смотрим уже из новой недели (полдень
        понедельника). Календарный якорь 00:00 затянул бы ночной урок в
        новый счётчик, хотя учебный день у него ещё воскресный.
        """
        from app.api.daily_plan import _compute_goal_progress

        self._complete_lesson(
            db_session, utc_user.id, test_lesson_quiz.id,
            datetime(2026, 9, 14, 1, 0, 0),
        )

        with app.test_request_context(), freeze_time('2026-09-14 12:00:00'):
            result = _compute_goal_progress(utc_user, 'UTC')

        assert result['goal_progress']['weekly_lessons']['actual'] == 0


# ── DP-013: контракт tz ↔ target_date на call-site immersion ─────────────────

class TestImmersionTzMatchesTargetDate:
    """`check_immersion_achievement` получает зону, из которой выведён `today`.

    Докстринг требует: `tz` MUST be the zone `target_date` was derived from.
    `today` берётся из `User.timezone`, а `tz` приходил из query-параметра —
    клиент мог сдвинуть окно на разницу поясов и получить/потерять бейдж
    за активность соседних суток.
    """

    def test_call_site_passes_user_timezone_not_query_param(
        self, authenticated_client, db_session, test_user,
    ):
        test_user.timezone = 'Europe/Moscow'
        db_session.commit()

        plan = {
            '_plan_meta': {
                'effective_mode': 'unified', 'graduated': False, 'user_id': test_user.id,
            },
            'required': [{'id': 'curriculum:lesson:1', 'kind': 'curriculum', 'completed': True}],
            'optional': [],
        }
        completion = {'curriculum:lesson:1': True}
        captured: dict = {}

        def _spy(user_id, target_date, db_session_arg=None, tz='UTC'):
            captured['target_date'] = target_date
            captured['tz'] = tz
            return []

        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value={},
        ), patch(
            'app.telegram.queries.get_yesterday_summary', return_value={},
        ), patch(
            'app.achievements.streak_service.compute_plan_steps',
            return_value=(completion, 1, 1, 1),
        ), patch(
            'app.achievements.services.check_immersion_achievement', side_effect=_spy,
        ):
            response = authenticated_client.get('/api/daily-status?tz=Pacific/Kiritimati')

        assert response.status_code == 200
        assert captured, 'immersion-проверка не вызвана — день не закрылся'
        # Клиент прислал Kiritimati; в хелпер обязана уехать зона профиля,
        # потому что именно из неё выведён target_date.
        assert captured['tz'] == 'Europe/Moscow'

    def test_target_date_and_tz_come_from_one_source(self, app, db_session, utc_user):
        """Инвариант, а не совпадение: обе величины читают User.timezone."""
        from app.utils.time_utils import get_user_local_date, get_user_timezone_name

        utc_user.timezone = 'Asia/Kolkata'
        db_session.commit()

        with app.test_request_context(), freeze_time(NIGHT):
            tz_name = get_user_timezone_name(utc_user.id, app_db)
            today = get_user_local_date(utc_user.id, app_db)

        assert tz_name == 'Asia/Kolkata'
        # 00:30 UTC = 06:00 Kolkata → учебный день уже наступил.
        assert today == CALENDAR_DAY


# ── DP-022: одна реализация «вчера не закрыто» ───────────────────────────────

class TestUnsecuredYesterdaySingleImplementation:
    """Оба эндпоинта отвечают на «вчера не закрыто?» одним предикатом.

    `_get_recovery_suggestion` (`/api/daily-status`) считал «вчера» pytz-полночью,
    `_check_recovery` (`/api/daily-plan/continuation`) — учебным днём. В окне
    00:00-02:00 они запрашивали `DailyPlanLog` за разные даты, хотя сам
    `plan_date` пишется на учебном базисе.
    """

    def _unsecured_log(self, db_session, user_id, plan_date):
        from app.daily_plan.models import DailyPlanLog

        row = DailyPlanLog(user_id=user_id, plan_date=plan_date, secured_at=None)
        db_session.add(row)
        db_session.commit()
        return row

    def test_both_readers_see_the_same_unsecured_day(self, app, db_session, utc_user):
        from app.api.daily_plan import _get_recovery_suggestion
        from app.daily_plan.next_step import _check_recovery

        # «Вчера» относительно учебного дня 14-го — это 13-е.
        self._unsecured_log(db_session, utc_user.id, STUDY_DAY - timedelta(days=1))

        with app.test_request_context(), freeze_time(NIGHT):
            api_suggestion = _get_recovery_suggestion(utc_user.id, 'UTC')
            next_step = _check_recovery(utc_user.id, app_db)

        assert api_suggestion is not None
        assert next_step is not None
        assert api_suggestion['missed_date'] == next_step.data['missed_date']
        assert api_suggestion['missed_date'] == (STUDY_DAY - timedelta(days=1)).isoformat()

    def test_both_readers_stay_silent_on_a_secured_day(self, app, db_session, utc_user):
        from app.api.daily_plan import _get_recovery_suggestion
        from app.daily_plan.models import DailyPlanLog
        from app.daily_plan.next_step import _check_recovery

        db_session.add(DailyPlanLog(
            user_id=utc_user.id,
            plan_date=STUDY_DAY - timedelta(days=1),
            secured_at=datetime.now(UTC).replace(tzinfo=None),
        ))
        db_session.commit()

        with app.test_request_context(), freeze_time(NIGHT):
            assert _get_recovery_suggestion(utc_user.id, 'UTC') is None
            assert _check_recovery(utc_user.id, app_db) is None

    def test_client_tz_cannot_move_the_api_reader(self, app, db_session, utc_user):
        from app.api.daily_plan import _get_recovery_suggestion

        self._unsecured_log(db_session, utc_user.id, STUDY_DAY - timedelta(days=1))

        with app.test_request_context(), freeze_time(NIGHT):
            suggestion = _get_recovery_suggestion(utc_user.id, 'Pacific/Kiritimati')

        assert suggestion is not None
        assert suggestion['missed_date'] == (STUDY_DAY - timedelta(days=1)).isoformat()


# ── Сквозной страж: три поверхности, одна «сегодняшняя» дата ────────────────

class TestOneTodayAcrossSurfaces:
    """Дашборд, `/api/daily-status` и `/api/daily-plan` в 00:30 согласны о дате.

    Общий страж кластера: любая будущая правка, вернувшая календарную полночь
    в один из трёх путей, разведёт этот набор.
    """

    def _collect(self, authenticated_client, url: str) -> set:
        """Возвращает все даты, которые путь вывел через `get_user_local_date`."""
        from app.utils import time_utils

        seen: set = set()
        real = time_utils.get_user_local_date

        def _spy(user_id, db_session=None):
            value = real(user_id, db_session)
            seen.add(value)
            return value

        plan = {
            '_plan_meta': {'effective_mode': 'unified', 'graduated': False, 'user_id': 1},
            'required': [],
            'optional': [],
        }

        with freeze_time(NIGHT), patch.object(
            time_utils, 'get_user_local_date', side_effect=_spy,
        ), patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value={},
        ), patch(
            'app.telegram.queries.get_yesterday_summary', return_value={},
        ), patch(
            'app.achievements.streak_service.compute_plan_steps',
            return_value=({}, 0, 0, 0),
        ):
            response = authenticated_client.get(url)

        assert response.status_code == 200, url
        return seen

    def test_all_three_surfaces_resolve_the_same_study_day(
        self, authenticated_client, db_session, test_user,
    ):
        test_user.timezone = 'UTC'
        db_session.commit()
        _enable_words_module(db_session, test_user.id)

        dashboard = self._collect(authenticated_client, '/dashboard')
        status = self._collect(authenticated_client, '/api/daily-status?tz=Pacific/Kiritimati')
        plan = self._collect(authenticated_client, '/api/daily-plan?tz=Pacific/Kiritimati')

        for surface, dates in (
            ('dashboard', dashboard), ('daily-status', status), ('daily-plan', plan),
        ):
            # Пустое множество = путь перестал спрашивать канонический резолвер:
            # страж без наблюдений бесполезен, поэтому это тоже провал.
            assert dates, f'{surface} не вывел ни одной даты — страж ослеп'
            assert dates == {STUDY_DAY}, f'{surface} вывел чужую дату: {dates}'
