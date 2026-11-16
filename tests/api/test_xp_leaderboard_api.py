"""Read-only global XP API: source parity, projection, rank and real JWT guards."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from flask_login import LoginManager, UserMixin


class RankingUser(UserMixin):
    id = 7
    username = 'learner'
    active = True

    @property
    def is_active(self):
        return self.active

    def has_auth_version(self, version):
        return version == 1


@pytest.fixture
def xp_context(monkeypatch):
    from app.api import decorators
    from app.api.daily_plan import api_daily_plan
    from app.study.services.stats_service import StatsService
    import app.achievements.models as models

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='local-xp-test-session-key',
                      JWT_SECRET_KEY='local-xp-test-signing-key-32-characters')
    JWTManager(app)
    login = LoginManager(app)
    user = RankingUser()
    login.user_loader(lambda identity: user if identity == '7' else None)
    monkeypatch.setattr(decorators, 'db_get_user', lambda identity: user if identity == 7 else None)
    leaders = Mock(return_value=[
        {'id': 1, 'username': 'First learner', 'total_xp': 2000, 'level': 8, 'email': 'never-return@example.test'},
        {'id': 7, 'username': 'learner', 'total_xp': 1000, 'level': 6},
    ])
    rank = Mock(return_value=102)
    monkeypatch.setattr(StatsService, 'get_xp_leaderboard', leaders)
    monkeypatch.setattr(StatsService, 'get_user_xp_rank', rank)
    query = Mock()
    query.filter_by.return_value.first.return_value = SimpleNamespace(total_xp=500)
    monkeypatch.setattr(models, 'UserStatistics', SimpleNamespace(query=query))
    app.register_blueprint(api_daily_plan, url_prefix='/api')
    with app.app_context():
        token = create_access_token(identity='7', additional_claims={'auth_version': 1})
    return SimpleNamespace(app=app, client=app.test_client(), user=user, leaders=leaders,
                           rank=rank, query=query, headers={'Authorization': f'Bearer {token}'})


def test_xp_leaderboard_uses_dashboard_source_and_returns_only_public_fields(xp_context):
    c = xp_context
    result = c.client.get('/api/xp-leaderboard', headers=c.headers)
    assert result.status_code == 200
    data = result.get_json()
    assert data['success'] is True
    c.leaders.assert_called_once_with(limit=100)
    assert [(x['username'], x['total_xp'], x['level']) for x in data['entries']] == [
        ('First learner', 2000, 8), ('learner', 1000, 6)]
    assert data['me']['id'] == 7
    assert data['me']['rank'] == 2
    assert data['entries'][1]['is_me'] is True
    assert set(data['entries'][0]) == {'id', 'username', 'total_xp', 'level', 'rank', 'is_me'}
    assert result.headers['Cache-Control'] == 'private, no-store'
    assert 'Set-Cookie' not in result.headers
    c.query.filter_by.assert_not_called()


def test_xp_leaderboard_requires_authentication(xp_context):
    assert xp_context.client.get('/api/xp-leaderboard').status_code == 401
    xp_context.leaders.assert_not_called()


def test_xp_leaderboard_rejects_bad_bearer(xp_context):
    result = xp_context.client.get('/api/xp-leaderboard', headers={'Authorization': 'Bearer invalid'})
    assert result.status_code == 401
    xp_context.leaders.assert_not_called()


def test_xp_leaderboard_rejects_inactive_account(xp_context):
    xp_context.user.active = False
    result = xp_context.client.get('/api/xp-leaderboard', headers=xp_context.headers)
    assert result.status_code == 403
    xp_context.leaders.assert_not_called()


def test_xp_leaderboard_rejects_revoked_auth_version(xp_context):
    c = xp_context
    with c.app.app_context():
        stale = create_access_token(identity='7', additional_claims={'auth_version': 0})
    assert c.client.get('/api/xp-leaderboard', headers={'Authorization': f'Bearer {stale}'}).status_code == 401
    c.leaders.assert_not_called()


def test_xp_leaderboard_preserves_browser_session_auth(xp_context):
    c = xp_context
    with c.client.session_transaction() as session:
        session['_user_id'] = '7'
        session['_fresh'] = True
    assert c.client.get('/api/xp-leaderboard').status_code == 200


def test_xp_leaderboard_ties_share_rank(xp_context):
    c = xp_context
    c.leaders.return_value = [
        {'id': 1, 'username': 'a', 'total_xp': 2000, 'level': 8},
        {'id': 2, 'username': 'b', 'total_xp': 2000, 'level': 8},
        {'id': 7, 'username': 'learner', 'total_xp': 1000, 'level': 6},
    ]
    data = c.client.get('/api/xp-leaderboard', headers=c.headers).get_json()
    assert [x['rank'] for x in data['entries']] == [1, 1, 3]
    assert data['me']['rank'] == 3


def test_xp_leaderboard_returns_own_place_outside_top_100(xp_context):
    c = xp_context
    c.leaders.return_value = [{'id': 1, 'username': 'a', 'total_xp': 2000, 'level': 8}]
    data = c.client.get('/api/xp-leaderboard?user_id=1', headers=c.headers).get_json()
    assert data['me']['id'] == 7
    assert data['me']['username'] == 'learner'
    assert data['me']['total_xp'] == 500
    assert data['me']['rank'] == 102
    c.rank.assert_called_once_with(7)
    c.query.filter_by.assert_called_once_with(user_id=7)


def test_xp_leaderboard_handles_new_account_without_statistics(xp_context):
    c = xp_context
    c.leaders.return_value = []
    c.query.filter_by.return_value.first.return_value = None
    c.rank.return_value = None
    data = c.client.get('/api/xp-leaderboard', headers=c.headers).get_json()
    assert data['entries'] == []
    assert data['me']['total_xp'] == 0
    assert data['me']['level'] == 1
    assert data['me']['rank'] is None


def test_xp_leaderboard_is_read_only(xp_context):
    assert xp_context.client.post('/api/xp-leaderboard', headers=xp_context.headers).status_code == 405
    xp_context.leaders.assert_not_called()
