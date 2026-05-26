"""Regression tests for Task 3 admin findings (CSRF tokens + audit logging)."""
import re
import uuid
from pathlib import Path

import pytest

from app.admin.audit import AdminAuditLog
from app.auth.models import User
from app.utils.db import db


CSRF_INPUT_MARKER = 'name="csrf_token"'
ADMIN_TEMPLATE_DIR = Path('app/templates/admin')

_FORM_POST_RE = re.compile(r'<form\b[^>]*method=["\']post["\'][^>]*>', re.IGNORECASE | re.DOTALL)
_CSRF_MARKER_RE = re.compile(
    r'csrf_token\s*\(\s*\)|form\.hidden_tag\s*\(\s*\)|form\.csrf_token|name=["\']csrf_token["\']'
)
_METHOD_RE = re.compile(r"method\s*:\s*['\"](POST|PUT|DELETE|PATCH)['\"]", re.IGNORECASE)
_CSRF_HEADER_RE = re.compile(r"X-CSRFToken", re.IGNORECASE)
_CSRF_BODY_RE = re.compile(r"['\"]csrf_token['\"]")


def _all_admin_templates():
    return sorted(p for p in ADMIN_TEMPLATE_DIR.rglob('*.html'))


def _extract_fetch_call(text: str, start: int) -> str:
    """Return the substring of a fetch(...) call starting at ``start``."""
    i = start + len('fetch(')
    depth = 1
    while i < len(text) and depth > 0:
        c = text[i]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return text[start:i]


def _iter_post_forms_without_csrf(text: str):
    """Yield form-opening tags that have method=post but lack a CSRF marker before </form>."""
    for m in _FORM_POST_RE.finditer(text):
        end = text.find('</form>', m.end())
        if end == -1:
            end = len(text)
        block = text[m.start():end]
        if not _CSRF_MARKER_RE.search(block):
            yield m.group(0)


def _iter_unsafe_fetch_calls(text: str):
    """Yield fetch(...) call substrings using POST/PUT/DELETE/PATCH without CSRF protection."""
    pos = 0
    while True:
        idx = text.find('fetch(', pos)
        if idx == -1:
            break
        block = _extract_fetch_call(text, idx)
        pos = idx + 1
        m = _METHOD_RE.search(block)
        if not m:
            continue
        # CSRF can be in the fetch block (header or appended body field)
        if _CSRF_HEADER_RE.search(block) or _CSRF_BODY_RE.search(block):
            continue
        # FormData(<form>) — passed directly into fetch — carries csrf_token from
        # the form's own hidden input; template-level form scan catches any form
        # that doesn't.
        if re.search(r"new\s+FormData\s*\(\s*[a-zA-Z_$][\w$.]*\s*\)", block):
            continue
        # ...or appended to the surrounding scope before the call
        # (e.g. formData.append('csrf_token', ...) on the preceding line).
        ctx = text[max(0, idx - 1500):idx]
        if _CSRF_BODY_RE.search(ctx):
            continue
        if re.search(r"new\s+FormData\s*\(\s*[a-zA-Z_$][\w$.]*\s*\)", ctx):
            continue
        yield block.replace('\n', ' ')[:200]


@pytest.mark.smoke
def test_curriculum_edit_templates_carry_csrf_token():
    """Admin curriculum edit templates must include the csrf_token hidden input."""
    template_paths = [
        'app/templates/admin/curriculum/edit_text.html',
        'app/templates/admin/curriculum/edit_quiz.html',
        'app/templates/admin/curriculum/edit_matching.html',
        'app/templates/admin/curriculum/edit_grammar.html',
        'app/templates/admin/curriculum/user_progress.html',
        'app/templates/admin/curriculum/progress_details.html',
        'app/templates/admin/curriculum/edit_module.html',
        'app/templates/admin/curriculum/edit_level.html',
    ]
    for path in template_paths:
        with open(path, encoding='utf-8') as fh:
            contents = fh.read()
        assert 'csrf_token()' in contents, f'csrf_token() missing from {path}'
        assert CSRF_INPUT_MARKER in contents, f'csrf hidden input missing from {path}'


def _make_admin(db_session):
    suffix = uuid.uuid4().hex[:8]
    admin = User(
        username=f'audit_admin_{suffix}',
        email=f'audit_admin_{suffix}@example.com',
        is_admin=True,
        active=True,
    )
    admin.set_password('pass1234')
    db_session.add(admin)
    db_session.flush()
    return admin


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _make_target_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    target = User(
        username=f'audit_target_{suffix}',
        email=f'audit_target_{suffix}@example.com',
        active=True,
    )
    target.set_password('pass1234')
    db_session.add(target)
    db_session.flush()
    return target


class TestUserToggleAuditLog:
    """toggle_user_status / toggle_admin_status / toggle_mission_plan must audit-log."""

    def test_toggle_user_status_logs_action(self, app, client, db_session):
        admin = _make_admin(db_session)
        target = _make_target_user(db_session)
        db_session.commit()
        _login(client, admin)

        response = client.post(f'/admin/users/{target.id}/toggle_status', follow_redirects=False)
        assert response.status_code in (302, 303)

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin.id,
            target_type='user',
            target_id=target.id,
        ).order_by(AdminAuditLog.id.desc()).first()
        assert entry is not None
        assert entry.action in ('user.activate', 'user.deactivate')

    def test_toggle_admin_status_logs_action(self, app, client, db_session):
        admin = _make_admin(db_session)
        target = _make_target_user(db_session)
        db_session.commit()
        _login(client, admin)

        response = client.post(f'/admin/users/{target.id}/toggle_admin', follow_redirects=False)
        assert response.status_code in (302, 303)

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin.id,
            target_type='user',
            target_id=target.id,
        ).order_by(AdminAuditLog.id.desc()).first()
        assert entry is not None
        assert entry.action in ('user.grant_admin', 'user.revoke_admin')

    @pytest.mark.skip(reason="toggle_mission_plan route removed in unified-plan refactor")
    def test_toggle_mission_plan_logs_action(self, app, client, db_session):
        pass


class TestCurriculumDeleteAuditLog:
    """delete_level / delete_module / delete_lesson / progress reset/delete must audit-log."""

    def test_delete_lesson_logs_action(self, app, client, db_session, test_lesson_vocabulary):
        admin = _make_admin(db_session)
        db_session.commit()
        _login(client, admin)
        lesson_id = test_lesson_vocabulary.id

        response = client.post(
            f'/admin/curriculum/lessons/{lesson_id}/delete', follow_redirects=False
        )
        assert response.status_code in (302, 303)

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin.id,
            action='curriculum.lesson.delete',
            target_type='lesson',
            target_id=lesson_id,
        ).first()
        assert entry is not None

    def test_reset_progress_logs_action(self, app, client, db_session, test_lesson_progress):
        admin = _make_admin(db_session)
        db_session.commit()
        _login(client, admin)
        progress_id = test_lesson_progress.id

        response = client.post(
            f'/admin/curriculum/progress/{progress_id}/reset', follow_redirects=False
        )
        assert response.status_code in (302, 303)

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin.id,
            action='curriculum.progress.reset',
            target_type='lesson_progress',
            target_id=progress_id,
        ).first()
        assert entry is not None

    def test_delete_progress_logs_action(self, app, client, db_session, test_lesson_progress):
        admin = _make_admin(db_session)
        db_session.commit()
        _login(client, admin)
        progress_id = test_lesson_progress.id

        response = client.post(
            f'/admin/curriculum/progress/{progress_id}/delete', follow_redirects=False
        )
        assert response.status_code in (302, 303)

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin.id,
            action='curriculum.progress.delete',
            target_type='lesson_progress',
            target_id=progress_id,
        ).first()
        assert entry is not None


class TestAdminTemplateCsrfCoverage:
    """Static-analysis sweep: every admin template must protect its mutating UI with CSRF."""

    @pytest.mark.smoke
    @pytest.mark.parametrize('template', _all_admin_templates(), ids=lambda p: str(p))
    def test_post_forms_have_csrf_token(self, template):
        text = template.read_text(encoding='utf-8', errors='replace')
        offenders = list(_iter_post_forms_without_csrf(text))
        assert not offenders, (
            f'{template}: {len(offenders)} POST form(s) without csrf protection. '
            f'Add `<input type="hidden" name="csrf_token" value="{{{{ csrf_token() }}}}">` '
            f'or use Flask-WTF `{{{{ form.hidden_tag() }}}}`.\n'
            f'Offending opening tag(s): {offenders!r}'
        )

    @pytest.mark.parametrize('template', _all_admin_templates(), ids=lambda p: str(p))
    def test_ajax_mutating_calls_carry_csrf(self, template):
        text = template.read_text(encoding='utf-8', errors='replace')
        offenders = list(_iter_unsafe_fetch_calls(text))
        assert not offenders, (
            f'{template}: AJAX fetch() call(s) using POST/PUT/DELETE/PATCH without CSRF. '
            f"Send the token via `headers: {{'X-CSRFToken': ...}}` "
            f"or append it to FormData under name='csrf_token'.\n"
            f'Offending call(s): {offenders!r}'
        )


class TestAdminRoutesNoCsrfExempt:
    """Admin blueprints must never disable CSRF via @csrf.exempt."""

    @pytest.mark.smoke
    def test_no_csrf_exempt_in_admin_modules(self):
        admin_root = Path('app/admin')
        offenders = []
        for py in admin_root.rglob('*.py'):
            text = py.read_text(encoding='utf-8', errors='replace')
            # Strip comments to avoid matching the documentation in decorators.py
            cleaned = re.sub(r'#.*', '', text)
            if 'csrf.exempt' in cleaned or '@csrf_exempt' in cleaned:
                offenders.append(str(py))
        assert not offenders, (
            f'Admin modules must not use @csrf.exempt; offenders: {offenders}'
        )
