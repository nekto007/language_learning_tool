"""A rendered public example must retain its level through signup and study entry."""
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup
from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.welcome_email import WelcomeEmail
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.landing.previews import PREVIEWS
from app.onboarding.study_start import get_first_study_url


def registration():
    name = f'entry_{uuid4().hex[:10]}'
    return dict(username=name, email=f'{name}@example.com', password='Xk9$mP2vL!qw', password2='Xk9$mP2vL!qw')


@pytest.mark.parametrize('preview', PREVIEWS, ids=[p['id'] for p in PREVIEWS])
def test_each_variant_renders_its_choices_and_a1_signup(client, db_session, preview):
    with patch('app.landing.routes.pick_preview', return_value=preview):
        response = client.get('/')
    assert response.status_code == 200
    page = BeautifulSoup(response.data, 'html.parser')
    card = page.select_one('#landing-preview')
    assert card['data-preview-id'] == preview['id']
    assert card.select_one('legend').text == preview['prompt']
    assert [item['value'] for item in card.select('input[type="radio"]')] == list(preview['options'])
    assert card['data-correct'] in preview['options']
    assert len(set(preview['options'])) == 3
    assert preview['explanation'] in card.select_one('noscript').text
    target = parse_qs(urlparse(card.select_one('#preview-register')['href']).query)
    assert target == {'level': ['A1'], 'entry': ['preview']}


def test_failed_signup_keeps_preview_intent_and_level(client, db_session):
    response = client.post('/register?level=A1&entry=preview', data={'username': 'abc'})
    assert response.status_code == 200
    page = BeautifulSoup(response.data, 'html.parser')
    params = parse_qs(urlparse(page.select_one('form')['action']).query)
    assert params['level'] == ['A1']
    assert params['entry'] == ['preview']


def test_password_mismatch_uses_russian_message_and_preview_signup_can_retry(
    client: FlaskClient, db_session: Session,
) -> None:
    path = '/register?level=A1&entry=preview'
    data = registration()
    russian = {'Accept-Language': 'ru-RU,ru;q=0.9'}
    rejected = client.post(path, data={**data, 'password2': data['password2'] + 'X'}, headers=russian)
    assert rejected.status_code == 200
    error = BeautifulSoup(rejected.data, 'html.parser').select_one('#password2-errors')
    assert error.get_text(strip=True) == 'Пароли не совпадают'
    assert User.query.filter_by(username=data['username']).count() == 0
    action = error.find_parent('form')['action']
    params = parse_qs(urlparse(action).query)
    assert params['level'] == ['A1'] and params['entry'] == ['preview']

    accepted = client.post(action, data=data, headers=russian)
    assert accepted.status_code == 302 and accepted.location.endswith('/onboarding')
    learner = User.query.filter_by(username=data['username']).one()
    assert learner.onboarding_level == 'A1'
    assert learner.acquisition_meta['entry_point'] == 'landing_preview'


@pytest.mark.parametrize('path, expected_subtitle', [
    ('/register?level=A1&entry=preview',
     'Создайте аккаунт, чтобы начать курс A1 и сохранять результаты будущих занятий. '
     'Уровень можно изменить после регистрации.'),
    ('/register?level=C1', 'Создайте аккаунт для начала обучения'),
    ('/register', 'Создайте аккаунт для начала обучения'),
], ids=['demo', 'placement', 'direct'])
def test_signup_subtitle_matches_the_entry(
    client: FlaskClient, db_session: Session, path: str, expected_subtitle: str,
) -> None:
    response = client.get(path)
    assert response.status_code == 200
    page = BeautifulSoup(response.data, 'html.parser')
    assert page.select_one('.auth-card__subtitle').get_text(strip=True) == expected_subtitle


def test_expired_form_csrf_without_referrer_returns_to_a_real_page(client, db_session, app, monkeypatch):
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    response = client.post('/register?level=A1&entry=preview', data=registration())
    assert response.status_code == 302
    target = urlparse(response.headers['Location'])
    assert target.path == '/register'
    assert parse_qs(target.query) == {'level': ['A1'], 'entry': ['preview']}


def test_preview_signup_never_calls_smtp_and_offers_direct_entry(client, db_session):
    client.get('/')
    data = registration()
    with patch('app.auth.routes.email_sender.send_email', side_effect=AssertionError('SMTP in request')) as send:
        response = client.post('/register?level=A1&entry=preview', data=data)
    assert response.status_code == 302
    send.assert_not_called()
    user = User.query.filter_by(email=data['email']).one()
    assert user.onboarding_level == 'A1'
    assert user.onboarding_completed is False
    assert user.acquisition_meta['entry_point'] == 'landing_preview'
    assert WelcomeEmail.query.filter_by(user_id=user.id).one().status == 'pending'
    page = BeautifulSoup(client.get('/onboarding').data, 'html.parser')
    quick = page.select_one('#quick-start')
    assert quick
    assert quick.select_one('input[name="level"]')['value'] == 'A1'
    assert quick.select_one('input[name="start_first_lesson"]')['value'] == '1'
    change_page = BeautifulSoup(client.get(quick.select_one('a')['href']).data, 'html.parser')
    assert change_page.select_one('#step1')
    assert change_page.select_one('.onboarding-page')['data-initial-level'] == 'A1'

    with patch('app.onboarding.study_start.get_first_study_url', return_value='/curriculum/lesson/42?from=linear_plan&slot=frozen'):
        response = client.post('/onboarding/complete', data={'level': 'B2', 'focus': 'grammar', 'start_first_lesson': '1'})
    assert response.headers['Location'] == '/curriculum/lesson/42?from=linear_plan&slot=frozen'
    db_session.refresh(user)
    assert user.onboarding_level == 'B2'
    assert user.onboarding_focus == 'grammar'
    assert user.onboarding_completed is True


@pytest.mark.parametrize('level, expected', [('', ''), ('fake', ''), ('a1', 'A1'), ('B2', 'B2')])
def test_other_signup_paths_keep_their_level_choice(client, db_session, level, expected):
    data = registration()
    response = client.post('/register', query_string={'level': level}, data=data)
    assert response.status_code == 302
    user = User.query.filter_by(email=data['email']).one()
    assert (user.onboarding_level or '') == expected
    page = BeautifulSoup(client.get('/onboarding').data, 'html.parser')
    assert bool(page.select_one('#quick-start')) == bool(expected)
    assert bool(page.select_one('#step1')) == (not bool(expected))


def test_quick_start_falls_back_when_no_lesson_is_available(client, db_session):
    data = registration()
    client.post('/register?level=A1&entry=preview', data=data)
    with patch('app.onboarding.study_start.get_first_study_url', return_value=None):
        response = client.post('/onboarding/complete', data={'level': 'A1', 'focus': 'all', 'start_first_lesson': '1'})
    assert response.status_code == 302
    assert 'curriculum/lesson' not in response.headers['Location']
    assert User.query.filter_by(email=data['email']).one().onboarding_completed


def test_explicit_safe_next_takes_priority_over_quick_start(client, db_session):
    client.post('/register?level=A1&entry=preview', data=registration())
    with patch('app.onboarding.study_start.get_first_study_url') as select:
        response = client.post('/onboarding/complete', data={
            'level': 'A1', 'start_first_lesson': '1', 'next': '/study/achievements',
        })
    select.assert_not_called()
    assert response.headers['Location'] == '/study/achievements'


def test_topic_destination_survives_level_test_detour_and_native_level_form(
        client: FlaskClient, db_session: Session) -> None:
    target = '/grammar-lab/practice/topic/4'
    response = client.post('/register', query_string={'next': target}, data=registration())
    wizard = BeautifulSoup(client.get(response.location).data, 'html.parser')
    test_link = wizard.select_one('.onboarding-placement__start')['href']
    placement = BeautifulSoup(client.get(test_link).data, 'html.parser')
    placement_root = placement.select_one('#placement-root')
    assert placement_root['data-continue-after-apply'] == 'true'
    assert parse_qs(urlparse(placement_root['data-learn-return']).query)['next'] == [target]
    back = placement.select_one('#placement-return')['href']
    assert parse_qs(urlparse(back).query)['next'] == [target]
    wizard = BeautifulSoup(client.get(back).data, 'html.parser')
    form = wizard.select_one('form.onboarding-levels')
    assert form.select_one('button[name=level][value=A2]') is not None
    data = {field['name']: field['value'] for field in form.select('input[type=hidden]')}
    response = client.post(form['action'], data={**data, 'level': 'A2'})
    assert response.location == target


def test_quick_entry_keeps_the_existing_plan_url_and_saved_progress(db_session, test_user):
    level = CEFRLevel(code=f'Q{uuid4().hex[:1]}', name='Quick entry', order=100)
    db_session.add(level)
    db_session.flush()
    module = Module(level_id=level.id, number=1, title='Quick entry')
    db_session.add(module)
    db_session.flush()
    lesson = Lessons(module_id=module.id, number=1, order=1, title='Existing lesson', type='vocabulary', content={})
    db_session.add(lesson)
    db_session.flush()
    progress = LessonProgress(user_id=test_user.id, lesson_id=lesson.id, status='in_progress', data={'answers': ['saved']})
    db_session.add(progress)
    db_session.commit()
    url = f'/curriculum/lesson/{lesson.id}?from=linear_plan&slot=original&resume=1'
    plan = {'required': [dict(id=f'curriculum:{lesson.id}', kind='curriculum', url=url,
                             data={'lesson_id': lesson.id})], 'optional': []}
    with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan):
        assert get_first_study_url(test_user) == url
    db_session.refresh(progress)
    assert progress.status == 'in_progress'
    assert progress.data == {'answers': ['saved']}
