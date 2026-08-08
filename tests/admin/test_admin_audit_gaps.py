"""Regression tests for ADM-002 / ADM-007 / ADM-008 (cross-zone audit 2026-08-08).

ADM-002 — the coverage gate in ``test_audit_log_coverage.py`` filtered on a
hand-written tuple of 15 blueprint prefixes. Six namespaces served under
``/admin`` were outside it, so the scan never ran on them, and seven mutating
routes wrote nothing to ``AdminAuditLog``: the six Telegram-channel operations
(three of which publish to a public channel irreversibly) and the mass-email
``reminders.send_reminders``. The gate now derives its scope from the URL map.

ADM-007 — five of seven exports left no audit trail, including the export of the
audit log itself. A second defect surfaced while fixing it: ``log_admin_action``
only *stages* its row inside a savepoint and documents that the caller must
commit, but these are GET handlers with nothing else to commit — so even the two
exports that did call the helper never persisted the row.

ADM-008 — four live ``ilike`` filters built their pattern from raw input, so `_`
matched any character and `%` any substring.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.admin.test_audit_log_coverage import (
    ADMIN_URL_PREFIX,
    _admin_mutating_rules,
    _is_admin_rule,
)

APP_ROOT = Path(__file__).resolve().parents[2] / 'app'


class TestCoverageGateScope:
    """ADM-002 — the scan must follow the URL map, not a literal list."""

    def test_scope_is_derived_from_the_url_map(self, app):
        endpoints = {rule.endpoint for rule, _ in _admin_mutating_rules(app)}
        namespaces = {endpoint.split('.')[0] for endpoint in endpoints}

        # The five namespaces the literal prefix list silently dropped.
        assert 'telegram_channel_admin' in namespaces
        assert 'reminders' in namespaces
        assert 'feedback_admin' in namespaces
        assert 'word_contrast_admin' in namespaces

    def test_every_scanned_rule_is_actually_under_admin(self, app):
        for rule, _methods in _admin_mutating_rules(app):
            assert str(rule).startswith(ADMIN_URL_PREFIX)

    def test_non_admin_routes_stay_out_of_scope(self, app):
        scanned = {str(rule) for rule, _ in _admin_mutating_rules(app)}
        assert not any(path.startswith('/api/daily-plan') for path in scanned)

    @pytest.mark.parametrize('path,expected', [
        ('/admin', True),
        ('/admin/users', True),
        ('/admin/reminders/send', True),
        ('/administration', False),
        ('/api/admin-ish', False),
    ])
    def test_prefix_match_is_boundary_aware(self, path, expected):
        class _Rule:
            def __init__(self, value):
                self.value = value

            def __str__(self):
                return self.value

        assert _is_admin_rule(_Rule(path)) is expected


class TestTelegramChannelRoutesAreAudited:
    """ADM-002 — the six channel operations, three of them irreversible."""

    ACTIONS = {
        'telegram_channel_skip': 'channel_post.skip',
        'telegram_channel_refill': 'channel_post.refill',
        'telegram_channel_test': 'channel_post.send_test',
        'telegram_channel_publish_now': 'channel_post.publish_now',
        'telegram_channel_resend': 'channel_post.resend',
        'telegram_channel_send_now': 'channel_post.send_now',
    }

    def _functions(self):
        source = (APP_ROOT / 'admin' / 'routes' / 'telegram_channel_routes.py').read_text(
            encoding='utf-8'
        )
        tree = ast.parse(source)
        return {
            node.name: ast.unparse(node)
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }

    @pytest.mark.parametrize('view,action', sorted(ACTIONS.items()))
    def test_view_logs_its_action(self, view, action):
        body = self._functions()[view]
        assert 'log_admin_action(' in body, f'{view} still mutates without an audit row'
        assert action in body

    @pytest.mark.parametrize('view', sorted(ACTIONS))
    def test_the_audit_row_is_committed(self, view):
        """`log_admin_action` only stages — without a commit the row is lost."""
        body = self._functions()[view]
        log_at = body.index('log_admin_action(')
        assert 'db.session.commit()' in body[log_at:], f'{view} never commits its audit row'

    def test_the_publishing_routes_log_before_they_publish(self):
        """An irreversible send must be attributable even if publishing then fails."""
        functions = self._functions()
        for view, call in (
            ('telegram_channel_publish_now', 'publish_due()'),
            ('telegram_channel_test', 'send_test_message('),
            ('telegram_channel_send_now', 'publish_due()'),
        ):
            body = functions[view]
            assert body.index('log_admin_action(') < body.index(call), view


class TestReminderCampaignIsAudited:
    """ADM-002 — mass email had no admin attribution beyond per-user ReminderLog."""

    def test_send_reminders_logs_the_campaign(self):
        source = (APP_ROOT / 'reminders' / 'routes.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        view = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == 'send_reminders'
        )
        body = ast.unparse(view)
        assert 'reminder.send_campaign' in body
        # Before the first send, not merely before the last commit: mail cannot
        # be recalled, so a crash mid-loop must still leave attribution behind.
        assert body.index('log_admin_action(') < body.index('send_email(')
        log_at = body.index('log_admin_action(')
        assert 'db.session.commit()' in body[log_at:body.index('send_email(')], (
            'the audit row is staged but not committed before the first send'
        )


class TestExportsAreAudited:
    """ADM-007 — all seven exports, staged *and* committed."""

    EXPORTS = [
        ('admin/routes/audit_routes.py', 'audit_export_csv', 'audit_log.export_csv'),
        ('admin/routes/dashboard_routes.py', 'content_quality_export', 'content_quality.export_csv'),
        ('admin/routes/word_routes.py', 'export_words', 'word.export'),
        ('admin/curriculum.py', 'export_lesson', 'lesson.export'),
        ('admin/quiz_decks.py', 'quiz_deck_export', 'quiz_deck.export'),
        ('admin/routes/user_routes.py', 'export_users_csv', 'user.export_csv'),
        ('admin/routes/user_routes.py', '_export_stats_csv', 'stats.export_csv'),
    ]

    def _view(self, relative_path: str, name: str) -> str:
        tree = ast.parse((APP_ROOT / relative_path).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return ast.unparse(node)
        raise AssertionError(f'{name} not found in {relative_path}')

    @pytest.mark.parametrize('path,view,action', EXPORTS)
    def test_export_logs_an_action(self, path, view, action):
        body = self._view(path, view)
        assert 'log_admin_action(' in body
        assert action in body

    @pytest.mark.parametrize('path,view,action', EXPORTS)
    def test_export_commits_the_audit_row(self, path, view, action):
        body = self._view(path, view)
        log_at = body.index('log_admin_action(')
        assert 'db.session.commit()' in body[log_at:], (
            f'{view} stages an audit row that never becomes durable'
        )

    def test_action_names_follow_the_convention(self):
        pattern = re.compile(r'^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$')
        for _path, _view, action in self.EXPORTS:
            assert pattern.match(action), action


class TestEscapeLikeOnLiveFilters:
    """ADM-008 — wildcards in admin search input must be matched literally."""

    SITES = [
        'admin/main_routes.py',
        'admin/routes/curriculum_routes.py',
        'admin/quiz_decks.py',
        'admin/book_courses.py',
    ]

    RAW_PATTERN = re.compile(r"ilike\(f'%\{(search|query)\}%'")

    @pytest.mark.parametrize('path', SITES)
    def test_no_unescaped_pattern_remains(self, path):
        source = (APP_ROOT / path).read_text(encoding='utf-8')
        assert not self.RAW_PATTERN.search(source), (
            f'{path} still interpolates raw input into a LIKE pattern'
        )

    @pytest.mark.parametrize('path', SITES)
    def test_escape_character_is_declared(self, path):
        """`escape_like` prefixes with a backslash; without escape='\\\\' it is literal."""
        source = (APP_ROOT / path).read_text(encoding='utf-8')
        for line_no, line in enumerate(source.splitlines(), 1):
            if 'escape_like(' in line and 'ilike(' in line:
                assert "escape='\\\\'" in line, f'{path}:{line_no} escapes without declaring it'

    def test_helper_escapes_all_three_metacharacters(self):
        from app.admin.utils.request_validators import escape_like

        assert escape_like('a_b') == r'a\_b'
        assert escape_like('a%b') == r'a\%b'
        assert escape_like('a\\b') == 'a\\\\b'

    def test_underscore_search_does_not_match_arbitrary_characters(self, app, db_session):
        """The behavioural half: `Present_Simple` must not match `Present Simple`."""
        from sqlalchemy import select

        from app.admin.utils.request_validators import escape_like
        from app.curriculum.models import CEFRLevel, Lessons, Module
        from tests.conftest import unique_level_code

        level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=880)
        db_session.add(level)
        db_session.flush()
        module = Module(
            level_id=level.id, number=1, title='M', description='d',
            raw_content={'module': {'id': 1}},
        )
        db_session.add(module)
        db_session.flush()
        db_session.add(Lessons(
            module_id=module.id, number=1, title='Present Simple', type='grammar', content={},
        ))
        db_session.flush()

        term = 'Present_Simple'
        escaped = db_session.execute(
            select(Lessons.id).where(
                Lessons.module_id == module.id,
                Lessons.title.ilike(f'%{escape_like(term)}%', escape='\\'),
            )
        ).all()
        raw = db_session.execute(
            select(Lessons.id).where(
                Lessons.module_id == module.id,
                Lessons.title.ilike(f'%{term}%'),
            )
        ).all()

        assert escaped == []
        assert len(raw) == 1, 'the raw form is what made the search imprecise'
