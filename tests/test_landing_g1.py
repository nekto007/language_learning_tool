"""The guest hero offers two clear routes and keeps account access available."""
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from bs4 import BeautifulSoup

pytestmark = pytest.mark.smoke


def test_hero_prioritises_direct_test_with_an_unhurried_demo_alternative(client: Any) -> None:
    page = BeautifulSoup(client.get('/').data, 'html.parser')
    hero = page.select_one('.land-hero')
    primary = hero.select_one('.land-btn--primary')
    assert primary.get_text(strip=True) == 'Проверить уровень'
    parsed = urlparse(primary['href'])
    assert parsed.path == '/placement' and parse_qs(parsed.query) == {'start': ['1']}
    conditions = hero.select_one('#' + primary['aria-describedby'])
    assert conditions.get_text(strip=True) == '10 вопросов · около 2 минут · результат сразу · без регистрации'
    secondary = hero.select_one('.land-btn--secondary')
    assert secondary.get_text(strip=True) == 'Попробовать одно задание'
    assert secondary['href'] == '#try-english'
    assert len(hero.select('.land-hero__actions a')) == 2
    assert len(hero.select_one('.land-hero__desc').get_text(' ', strip=True)) < 200


def test_login_and_direct_signup_are_not_replaced_by_the_placement_test(client: Any) -> None:
    page = BeautifulSoup(client.get('/').data, 'html.parser')
    login = page.select_one('.public-header a[href="/login"]')
    assert login and login.get_text(strip=True) in ('Вход', 'Войти')
    direct = page.select_one('.land-hero__direct a')
    assert urlparse(direct['href']).path == '/register'
    assert direct.get_text(strip=True) == 'Зарегистрироваться'


def test_demo_retains_feedback_and_a_specific_a1_course_destination(client: Any) -> None:
    page = BeautifulSoup(client.get('/').data, 'html.parser')
    demo = page.select_one('#landing-preview')
    assert demo.find_parent('form') is None
    assert demo.select_one('#preview-feedback')['aria-live'] == 'polite'
    assert len(demo.select('input[name="preview-answer"]')) == 3
    assert demo['data-correct'] in [field['value'] for field in demo.select('input')]
    assert demo['data-explanation']
    target = demo.select_one('#preview-register')
    assert target.get_text(strip=True) == 'Начать курс A1'
    assert parse_qs(urlparse(target['href']).query) == {'level': ['A1'], 'entry': ['preview']}


def test_first_week_is_suitable_for_a_recommended_or_self_selected_level(client: Any) -> None:
    page = BeautifulSoup(client.get('/').data, 'html.parser')
    week = page.select_one('.land-start').get_text(' ', strip=True)
    assert 'рекомендованного уровня' in week
    assert 'свой уровень' in week
    assert 'выберите A1' not in week and 'Знакомство и приветствия' not in week


def test_login_is_reachable_outside_the_mobile_menu(client: Any) -> None:
    page = BeautifulSoup(client.get('/').data, 'html.parser')
    desktop_login = page.select_one('.public-nav-desktop a[href="/login"]')
    assert desktop_login and desktop_login.find_parent('details') is None
    mobile = page.select_one('details.public-nav-collapse')
    assert mobile and not mobile.has_attr('open')
    assert mobile.select_one('summary').get_text(' ', strip=True) == 'Меню'
    mobile_login = page.select_one('.public-nav-mobile > a[href="/login"]')
    assert mobile_login and mobile_login.get_text(strip=True) == 'Вход'
    assert mobile.select_one('a[href="/login"]') is None
    assert {a['href'] for a in page.select('.public-nav-desktop a')} == {
        a['href'] for a in page.select('.public-nav-mobile a')}
