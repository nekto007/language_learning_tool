"""DP-001 (второй механизм): порядок починок серии внутри `process_streak_on_activity`.

У пропущенного дня три способа быть закрытым, и они не равноценны по цене:

- бесплатная починка за выполненный план (`apply_free_repair`);
- бесплатный авто-хилер (`auto_heal_streak_on_activity`, окно `max_days=3`);
- **расходуемый** щит (`apply_shield_repair`), который зарабатывается раз в 7 дней серии.

До ремедиации щит стоял ПЕРВЫМ и гейтился только `real_activity`. Он писал
`StreakEvent('shield_repair')`, а `has_repair_for_date` считает это событие
починкой — значит `find_auto_heal_date` ту же дату больше не видел, и бесплатный
хилер до неё не доходил. Дырка на offset 1–3 закрывалась платным ресурсом там,
где бесплатный сработал бы сам.

Фикс — порядок: бесплатные механизмы вперёд, щит последним, на том, до чего они
не дотянулись (offset 4–7, куда авто-хилер с `max_days=3` не достаёт).
"""
from datetime import datetime
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from app.achievements.models import StreakEvent

MOSCOW = 'Europe/Moscow'  # UTC+3, без DST


@pytest.fixture()
def shielded_user(db_session, test_user):
    """Юзер в фиксированной зоне с активным щитом."""
    test_user.timezone = MOSCOW
    test_user.streak_shield_active = True
    db_session.flush()
    return test_user


def _log_activity(db_session, user_id, created_at_utc_naive):
    """Активность 7-го источника (`xp_linear`) — naive UTC, как в колонке."""
    db_session.add(StreakEvent(
        user_id=user_id,
        event_type='xp_linear',
        coins_delta=0,
        event_date=created_at_utc_naive.date(),
        created_at=created_at_utc_naive,
        details={'source': 'test'},
    ))
    db_session.flush()


def _seed_study_days(db_session, user_id, days):
    """Активность в 12:00 МСК (09:00 UTC) в каждый из перечисленных учебных дней."""
    for day in days:
        _log_activity(db_session, user_id, datetime(2026, 8, day, 9, 0))


def _repairs(user_id, event_type):
    return StreakEvent.query.filter_by(
        user_id=user_id, event_type=event_type,
    ).all()


def _run(user, steps_done=0, steps_total=1):
    """Прогон с реальными хелперами починки; глушим только milestone-награды.

    `check_streak_milestone` на серии 7 выдаёт новый щит — он бы замаскировал
    факт списания старого.
    """
    from app.achievements import streak_service

    with patch.object(streak_service, 'check_streak_milestone', return_value=None):
        return streak_service.process_streak_on_activity(
            user.id, steps_done=steps_done, steps_total=steps_total, tz=MOSCOW,
        )


# ---------------------------------------------------------------------------
# 1. Дырка в окне авто-хилера закрывается бесплатно, щит остаётся
# ---------------------------------------------------------------------------

class TestFreeHealerGoesFirst:

    @freeze_time('2026-08-20 07:00:00')  # 10:00 20 августа по Москве
    def test_gap_at_offset_one_does_not_consume_shield(self, db_session, shielded_user):
        """Дырка на offset 1 при активном щите: чинит авто-хилер, щит цел."""
        # Учебные дни 17, 18 и 20 августа заняты, 19-е пусто — дырка на offset 1.
        _seed_study_days(db_session, shielded_user.id, [17, 18, 20])

        result = _run(shielded_user)

        assert result['streak_repaired'] is True
        assert shielded_user.streak_shield_active is True, \
            'щит списан там, где бесплатный авто-хилер справился бы сам'
        assert _repairs(shielded_user.id, 'shield_repair') == []
        free = _repairs(shielded_user.id, 'free_repair')
        assert [ev.event_date for ev in free] == [datetime(2026, 8, 19).date()]

    @freeze_time('2026-08-20 07:00:00')
    def test_gap_at_offset_three_does_not_consume_shield(self, db_session, shielded_user):
        """Дальняя граница окна авто-хилера (offset 3) — тоже бесплатно."""
        # 16, 18, 19, 20 заняты; 17-е (offset 3) пусто.
        _seed_study_days(db_session, shielded_user.id, [16, 18, 19, 20])

        _run(shielded_user)

        assert shielded_user.streak_shield_active is True
        assert _repairs(shielded_user.id, 'shield_repair') == []
        assert [ev.event_date for ev in _repairs(shielded_user.id, 'free_repair')] == \
            [datetime(2026, 8, 17).date()]

    @freeze_time('2026-08-20 07:00:00')
    def test_free_plan_repair_also_wins_over_shield(self, db_session, shielded_user):
        """Выполненный план чинит дырку бесплатно — щит не трогается."""
        _seed_study_days(db_session, shielded_user.id, [17, 18, 20])

        _run(shielded_user, steps_done=4, steps_total=4)

        assert shielded_user.streak_shield_active is True
        assert _repairs(shielded_user.id, 'shield_repair') == []
        assert len(_repairs(shielded_user.id, 'free_repair')) == 1


# ---------------------------------------------------------------------------
# 2. Щит остаётся достижимым там, куда авто-хилер не дотягивается
# ---------------------------------------------------------------------------

class TestShieldStillReachable:

    @freeze_time('2026-08-20 07:00:00')
    def test_gap_beyond_auto_heal_window_consumes_shield(self, db_session, shielded_user):
        """Страж от «починили, отключив щит»: offset 5 — вне окна `max_days=3`."""
        # 14, 16..20 заняты; 15-е (offset 5) пусто — авто-хилер туда не достаёт.
        _seed_study_days(db_session, shielded_user.id, [14, 16, 17, 18, 19, 20])

        result = _run(shielded_user)

        assert result['streak_repaired'] is True
        assert shielded_user.streak_shield_active is False
        assert [ev.event_date for ev in _repairs(shielded_user.id, 'shield_repair')] == \
            [datetime(2026, 8, 15).date()]

    @freeze_time('2026-08-20 07:00:00')
    def test_gap_at_offset_seven_consumes_shield(self, db_session, shielded_user):
        """Верхняя граница окна `find_missed_date` (max_days=7) — щит работает."""
        # 12, 14..20 заняты; 13-е (offset 7) пусто.
        _seed_study_days(db_session, shielded_user.id, [12, 14, 15, 16, 17, 18, 19, 20])

        _run(shielded_user)

        assert shielded_user.streak_shield_active is False
        assert [ev.event_date for ev in _repairs(shielded_user.id, 'shield_repair')] == \
            [datetime(2026, 8, 13).date()]

    @freeze_time('2026-08-20 07:00:00')
    def test_no_gap_leaves_shield_untouched(self, db_session, shielded_user):
        """Без дырки щит не расходуется вовсе."""
        _seed_study_days(db_session, shielded_user.id, [17, 18, 19, 20])

        _run(shielded_user)

        assert shielded_user.streak_shield_active is True
        assert _repairs(shielded_user.id, 'shield_repair') == []
