"""The weekly overview renders the real current study day without crediting activity."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
from sqlalchemy.orm import scoped_session

from app.achievements.models import StreakEvent, UserStatistics
from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonAttempt, LessonProgress, Lessons, Module
from app.daily_plan.models import DailyPlanLog
from app.modules.models import SystemModule, UserModule
from app.study.models import StudySession
from app.utils.db import db
from app.utils.time_utils import get_user_local_date
from tests.api.test_course_receipt_expiry import sign_in


def seed_scenario(user: User, scenario: str) -> None:
    user.onboarding_level = 'A1'
    user.plan_difficulty = 'normal'
    user.timezone = 'UTC'
    today = get_user_local_date(user.id, db)
    for code in ('study', 'words'):
        module = SystemModule.query.filter_by(code=code).one_or_none()
        if module is None:
            module = SystemModule(code=code, name=code, is_active=True)
            db.session.add(module)
            db.session.flush()
        grant = UserModule.query.filter_by(module_id=module.id, user_id=user.id).one_or_none()
        if grant is None:
            db.session.add(UserModule(user_id=user.id, module_id=module.id, is_enabled=True))
        else:
            grant.is_enabled = True

    db.session.add(DailyPlanLog(user_id=user.id, plan_date=today - timedelta(days=2), mission_type='progress',
                               plan_json={'synthetic_history': True}))
    if scenario == 'paused':
        user.plan_paused_until = today + timedelta(days=3)
    elif scenario == 'partial':
        level = CEFRLevel.query.filter_by(code='A1').one_or_none()
        if level is None:
            level = CEFRLevel(code='A1', name='Synthetic A1', order=1)
            db.session.add(level)
            db.session.flush()
        module = Module(level_id=level.id, number=1, title='Synthetic module')
        db.session.add(module)
        db.session.flush()
        for number in (1, 2, 3):
            lesson = Lessons(module_id=module.id, number=number, order=number, type='vocabulary',
                             title=f'Synthetic vocabulary {number}',
                             content={'words': [{'word': 'tree', 'translation': 'дерево'}]})
            db.session.add(lesson)
            db.session.flush()
            if number == 1:
                db.session.add(LessonProgress(
                    user_id=user.id, lesson_id=lesson.id, status='completed', score=100,
                    completed_at=datetime.now(UTC).replace(tzinfo=None),
                ))
    db.session.commit()


def stored_state(user_id: int) -> tuple:
    db.session.expire_all()
    logs = DailyPlanLog.query.filter_by(user_id=user_id).order_by(DailyPlanLog.plan_date)
    stats = UserStatistics.query.filter_by(user_id=user_id).one_or_none()
    return (
        [(log.plan_date, log.secured_at, log.plan_json) for log in logs],
        LessonAttempt.query.filter_by(user_id=user_id).count(),
        LessonProgress.query.filter_by(user_id=user_id, status='completed').count(),
        StudySession.query.filter_by(user_id=user_id).count(),
        StreakEvent.query.filter_by(user_id=user_id).count(),
        stats.total_xp if stats else 0,
    )


def page(client: FlaskClient, path: str) -> BeautifulSoup:
    g.pop('_login_user', None)
    response = client.get(path)
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


@pytest.mark.parametrize(('scenario', 'state'), [('paused', 'paused'), ('partial', 'active'), ('empty', 'empty')])
def test_weekly_matches_today_and_does_not_record_new_credit(
    app: Flask, test_user: User, db_session: scoped_session, scenario: str, state: str,
) -> None:
    seed_scenario(test_user, scenario)
    client = app.test_client()
    sign_in(client, app, test_user)
    before = stored_state(test_user.id)
    weekly = page(client, '/study/weekly')
    after_weekly = stored_state(test_user.id)
    today_date = get_user_local_date(test_user.id, db)
    assert after_weekly[1:] == before[1:]
    assert [log for log in after_weekly[0] if log[0] < today_date] == before[0]
    assert all(log[1] is None for log in after_weekly[0])
    if scenario == 'paused':
        assert after_weekly == before
    else:
        assert any(log[0] == today_date for log in after_weekly[0])
    dashboard = page(client, '/dashboard')
    after_dashboard = stored_state(test_user.id)
    weekly_again = page(client, '/study/weekly')
    assert stored_state(test_user.id) == after_dashboard

    today = weekly.select_one('[data-status=current]')
    assert today['data-plan-state'] == state
    assert weekly_again.select_one('[data-status=current]').get_text(' ', strip=True) == today.get_text(' ', strip=True)
    assert len(weekly.select('[data-status=past]')) == len(weekly.select('[data-status=future]')) == 3
    assert len(weekly.select('[data-status=past] .weekly-plan__past-label')) == 1
    for forecast in weekly.select('[data-status=future]'):
        assert 'Прогноз' in forecast.get_text()
        assert len(forecast.select('.weekly-plan__slot-icon')) == 3
        assert '40' in forecast.select_one('.weekly-plan__time').get_text()

    dashboard_items = dashboard.select('[data-section=required] [data-item-id]')
    if scenario == 'partial':
        expected = [(item['data-item-id'], item['data-item-kind'],
                     'completed' if item['data-state'] == 'done' else item['data-state'])
                    for item in dashboard_items]
        observed = [(item['data-item-id'], item['data-item-kind'], item['data-item-state'])
                    for item in today.select('[data-item-id]')]
        assert observed == expected
        assert any(item[2] == 'completed' for item in observed) and any(item[2] != 'completed' for item in observed)
        progress = dashboard.select_one('.today-header__progress')
        assert today.select_one('.weekly-plan__progress').text.strip() == (
            f'{progress["aria-valuenow"]} / {progress["aria-valuemax"]} выполнено')
        dashboard_minutes = re.search(r'(\d+)\s+мин', dashboard.select_one('.today-header__description').text)[1]
        assert re.search(r'(\d+)\s+мин', today.select_one('.weekly-plan__time').text)[1] == dashboard_minutes
        assert today.select_one('.weekly-plan__cta')['href'] == '/dashboard'
    else:
        assert not dashboard_items and not today.select('[data-item-id]')
        assert not today.select_one('.weekly-plan__progress + .weekly-plan__time a')
        if scenario == 'paused':
            assert 'План на паузе' in today.text and 'План на паузе' in dashboard.text
            assert today.select_one('time')['datetime'] == dashboard.select_one('.daily-plan__empty time')['datetime']
            assert not today.select_one('.weekly-plan__cta')
        else:
            assert 'Нет обязательных заданий' in today.text
            assert not today.select_one('.weekly-plan__time')


def test_weekly_labels_existing_plan_fallback_as_load_error(
    app: Flask, test_user: User, db_session: scoped_session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.daily_plan import plan

    seed_scenario(test_user, 'empty')
    client = app.test_client()
    sign_in(client, app, test_user)

    def broken(_user_id: int) -> dict:
        raise RuntimeError('synthetic plan failure')

    monkeypatch.setattr(plan, 'get_daily_plan', broken)
    before = stored_state(test_user.id)
    result = page(client, '/study/weekly')
    today = result.select_one('[data-status=current]')
    assert today['data-plan-state'] == 'unavailable'
    assert 'Не удалось загрузить план' in today.text  # noqa: RUF001 -- Russian UI copy.
    assert 'Нет обязательных заданий' not in today.text
    assert today.select_one('.weekly-plan__cta')['href'] == '/study/weekly'
    assert not today.select('[data-item-id], .weekly-plan__time')
    assert stored_state(test_user.id) == before
