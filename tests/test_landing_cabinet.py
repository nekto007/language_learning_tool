"""The public hero uses the same available cabinet entry as public navigation."""

from urllib.parse import urlsplit

import pytest
from bs4 import BeautifulSoup
from flask import Flask, g

from app.auth.models import User
from app.modules.models import SystemModule
from app.modules.service import ModuleService
from app.utils.db import db
from tests.api.test_course_receipt_expiry import sign_in

PROFILE_SCENARIOS = ('reader', 'withdrawn', 'globally_inactive', 'registration_defaults')


def seed_modules() -> dict[str, SystemModule]:
    modules = {}
    for code in ('words', 'study', 'books'):
        module = SystemModule.query.filter_by(code=code).one_or_none()
        if module is None:
            module = SystemModule(code=code, name=code)
            db.session.add(module)
        module.is_active = True
        module.is_default = code in ('words', 'study')
        modules[code] = module
    db.session.commit()
    return modules


def configure_profile(user: User, scenario: str) -> None:
    modules = seed_modules()
    user.onboarding_completed = True
    user.onboarding_level = 'A1'
    user.timezone = 'UTC'
    if scenario == 'registration_defaults':
        ModuleService.grant_default_modules_to_user(user.id)
        return
    if scenario in ('reader', 'globally_inactive'):
        ModuleService.grant_module_to_user(user.id, modules['books'].id)
    if scenario == 'withdrawn':
        ModuleService.grant_module_to_user(user.id, modules['study'].id)
    if scenario in ('withdrawn', 'globally_inactive'):
        ModuleService.grant_module_to_user(user.id, modules['words'].id)
    if scenario == 'withdrawn':
        assert ModuleService.revoke_module_from_user(user.id, modules['words'].id)
    if scenario == 'globally_inactive':
        modules['words'].is_active = False
        db.session.commit()


@pytest.mark.parametrize('scenario', PROFILE_SCENARIOS)
def test_home_routes_to_available_cabinet(
    app: Flask, test_user: User, scenario: str, _skip_autouse_module_fixtures: None,
) -> None:
    configure_profile(test_user, scenario)
    client = app.test_client()
    sign_in(client, app, test_user)
    enabled = ModuleService.get_user_enabled_module_codes(test_user.id)
    g.pop('_login_user', None)
    home = client.get('/')
    if scenario == 'registration_defaults':
        assert set(enabled) == {'words', 'study'}
        assert home.status_code == 302 and urlsplit(home.location).path == '/dashboard'
        dashboard = client.get(home.location)
        assert dashboard.status_code == 200
        assert BeautifulSoup(dashboard.data, 'html.parser').select_one('#daily-plan')
    else:
        assert 'words' not in enabled
        assert home.status_code == 200
        page = BeautifulSoup(home.data, 'html.parser')
        direct = page.select_one('.land-hero__direct a')
        menu = page.select('.public-nav__link--primary[href="/profile"]')
        assert direct.get_text(strip=True) == 'Открыть кабинет'
        assert direct['href'] == '/profile'
        assert len(menu) == 2 and all(link['href'] == direct['href'] for link in menu)
        assert client.get(direct['href']).status_code == 200
        assert client.get('/dashboard').status_code == 403
    assert ModuleService.get_user_enabled_module_codes(test_user.id) == enabled
