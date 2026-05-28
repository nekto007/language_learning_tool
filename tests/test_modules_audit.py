"""
Task 75 audit: modules — feature gates and activation
Tests for @module_required decorator, direct URL blocking, duplicate activation,
and settings page correctness for users without active modules.
"""
import uuid
import pytest
from unittest.mock import patch, MagicMock

from app.modules.models import SystemModule, UserModule
from app.modules.service import ModuleService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_code(prefix: str = "mod") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _make_module(db_session, code=None, *, is_active=True, is_default=False):
    mod = SystemModule(
        code=code or _unique_code(),
        name=f"Test {code or 'module'}",
        is_active=is_active,
        is_default=is_default,
        order=99,
    )
    db_session.add(mod)
    db_session.flush()
    return mod


def _grant(db_session, user_id, module_id, *, is_enabled=True):
    um = UserModule(user_id=user_id, module_id=module_id, is_enabled=is_enabled)
    db_session.add(um)
    db_session.flush()
    return um


# ---------------------------------------------------------------------------
# Feature gate: is_module_enabled_for_user
# ---------------------------------------------------------------------------

class TestFeatureGate:
    """is_module_enabled_for_user is the gate used by @module_required."""

    @pytest.mark.smoke
    def test_returns_true_when_active_and_enabled(self, app, db_session, test_user):
        with app.app_context():
            mod = _make_module(db_session, is_active=True)
            _grant(db_session, test_user.id, mod.id, is_enabled=True)
            db_session.commit()

            assert ModuleService.is_module_enabled_for_user(test_user.id, mod.code) is True

    @pytest.mark.smoke
    def test_returns_false_when_system_module_inactive(self, app, db_session, test_user):
        """Deactivated SystemModule must be blocked even if UserModule.is_enabled=True."""
        with app.app_context():
            mod = _make_module(db_session, is_active=False)
            _grant(db_session, test_user.id, mod.id, is_enabled=True)
            db_session.commit()

            assert ModuleService.is_module_enabled_for_user(test_user.id, mod.code) is False

    def test_returns_false_when_user_module_disabled(self, app, db_session, test_user):
        """Disabled UserModule must block access even if SystemModule.is_active=True."""
        with app.app_context():
            mod = _make_module(db_session, is_active=True)
            _grant(db_session, test_user.id, mod.id, is_enabled=False)
            db_session.commit()

            assert ModuleService.is_module_enabled_for_user(test_user.id, mod.code) is False

    def test_returns_false_when_no_user_module_row(self, app, db_session, test_user):
        with app.app_context():
            mod = _make_module(db_session, is_active=True)
            db_session.commit()

            assert ModuleService.is_module_enabled_for_user(test_user.id, mod.code) is False

    def test_returns_false_for_nonexistent_module_code(self, app, db_session, test_user):
        with app.app_context():
            assert ModuleService.is_module_enabled_for_user(test_user.id, "does_not_exist_xyz") is False


class TestModuleRequiredDecorator:
    """Unit tests for @module_required decorator via mock service calls."""

    def test_decorator_calls_is_module_enabled_for_user(self):
        """@module_required must delegate access check to ModuleService."""
        from app.modules.decorators import module_required
        from flask import Flask

        test_app = Flask(__name__)

        with patch("app.modules.decorators.current_user") as mock_user, \
             patch("app.modules.decorators.ModuleService.is_module_enabled_for_user") as mock_svc:
            mock_user.is_authenticated = True
            mock_user.id = 42
            mock_svc.return_value = True

            @module_required("curriculum")
            def view():
                return "OK"

            with test_app.test_request_context("/test"):
                view()

            mock_svc.assert_called_once_with(42, "curriculum")

    def test_decorator_aborts_403_when_module_disabled(self):
        """@module_required must abort with 403 when module is not enabled."""
        from app.modules.decorators import module_required
        from flask import Flask, abort
        import werkzeug.exceptions

        test_app = Flask(__name__)

        with patch("app.modules.decorators.current_user") as mock_user, \
             patch("app.modules.decorators.ModuleService.is_module_enabled_for_user") as mock_svc, \
             patch("app.modules.decorators.flash"):
            mock_user.is_authenticated = True
            mock_user.id = 1
            mock_svc.return_value = False  # module not enabled

            @module_required("some_module")
            def view():
                return "OK"

            with test_app.test_request_context("/test"):
                with pytest.raises(werkzeug.exceptions.Forbidden):
                    view()

    def test_decorator_allows_access_when_module_enabled(self):
        """@module_required must allow access when module is enabled."""
        from app.modules.decorators import module_required
        from flask import Flask

        test_app = Flask(__name__)

        with patch("app.modules.decorators.current_user") as mock_user, \
             patch("app.modules.decorators.ModuleService.is_module_enabled_for_user") as mock_svc:
            mock_user.is_authenticated = True
            mock_user.id = 1
            mock_svc.return_value = True

            @module_required("some_module")
            def view():
                return "OK"

            with test_app.test_request_context("/test"):
                result = view()

            assert result == "OK"

    def test_decorator_redirects_unauthenticated_user(self):
        """@module_required must redirect unauthenticated users to login."""
        from app.modules.decorators import module_required
        from flask import Flask

        test_app = Flask(__name__)

        with patch("app.modules.decorators.current_user") as mock_user, \
             patch("app.modules.decorators.redirect") as mock_redirect, \
             patch("app.modules.decorators.url_for") as mock_url_for, \
             patch("app.modules.decorators.flash"):
            mock_user.is_authenticated = False
            mock_url_for.return_value = "/auth/login"
            mock_redirect.return_value = "redirect_resp"

            @module_required("curriculum")
            def view():
                return "OK"

            with test_app.test_request_context("/protected"):
                result = view()

            assert result == "redirect_resp"
            mock_redirect.assert_called_once()

    def test_inactive_module_returns_false_before_decorator_aborts(
        self, app, db_session, test_user
    ):
        """Integration: inactive module triggers is_module_enabled_for_user=False,
        which is what the decorator uses to abort 403."""
        with app.app_context():
            mod = _make_module(db_session, is_active=False)
            _grant(db_session, test_user.id, mod.id, is_enabled=True)
            db_session.commit()
            code = mod.code

        # Verify service returns False — this is what @module_required checks
        with app.app_context():
            result = ModuleService.is_module_enabled_for_user(test_user.id, code)
        assert result is False


# ---------------------------------------------------------------------------
# Duplicate activation prevention
# ---------------------------------------------------------------------------

class TestModuleActivationIdempotency:
    """grant_module_to_user must not create duplicate UserModule rows."""

    @pytest.mark.smoke
    def test_grant_twice_creates_one_row(self, app, db_session, test_user):
        with app.app_context():
            mod = _make_module(db_session)
            db_session.commit()

            ModuleService.grant_module_to_user(test_user.id, mod.id)
            ModuleService.grant_module_to_user(test_user.id, mod.id)

            count = UserModule.query.filter_by(
                user_id=test_user.id, module_id=mod.id
            ).count()
            assert count == 1

    def test_grant_after_revoke_updates_row(self, app, db_session, test_user):
        """Re-granting a revoked module updates is_enabled instead of creating new row."""
        with app.app_context():
            mod = _make_module(db_session)
            db_session.commit()

            ModuleService.grant_module_to_user(test_user.id, mod.id)
            ModuleService.revoke_module_from_user(test_user.id, mod.id)

            um = UserModule.query.filter_by(
                user_id=test_user.id, module_id=mod.id
            ).one()
            assert um.is_enabled is False

            ModuleService.grant_module_to_user(test_user.id, mod.id)

            count = UserModule.query.filter_by(
                user_id=test_user.id, module_id=mod.id
            ).count()
            assert count == 1

            um = UserModule.query.filter_by(
                user_id=test_user.id, module_id=mod.id
            ).one()
            assert um.is_enabled is True

    def test_toggle_twice_returns_to_original_state(self, app, db_session, test_user):
        with app.app_context():
            mod = _make_module(db_session)
            db_session.commit()

            ModuleService.grant_module_to_user(test_user.id, mod.id)

            state1 = ModuleService.toggle_module_for_user(test_user.id, mod.id)
            state2 = ModuleService.toggle_module_for_user(test_user.id, mod.id)

            assert state1 is False
            assert state2 is True

            count = UserModule.query.filter_by(
                user_id=test_user.id, module_id=mod.id
            ).count()
            assert count == 1

    def test_grant_default_modules_no_duplicate(self, app, db_session, test_user):
        """grant_default_modules_to_user is idempotent — second call must not add rows."""
        with app.app_context():
            default_mod = _make_module(db_session, is_default=True, is_active=True)
            db_session.commit()

            ModuleService.grant_default_modules_to_user(test_user.id)
            before_count = UserModule.query.filter_by(
                user_id=test_user.id, module_id=default_mod.id
            ).count()

            ModuleService.grant_default_modules_to_user(test_user.id)
            after_count = UserModule.query.filter_by(
                user_id=test_user.id, module_id=default_mod.id
            ).count()

            assert before_count == 1
            assert after_count == 1


# ---------------------------------------------------------------------------
# Settings page with no active modules
# ---------------------------------------------------------------------------

class TestModulesSettingsPage:
    """Modules settings page must render correctly regardless of user's module state."""

    @pytest.mark.smoke
    def test_settings_page_renders_with_no_enabled_modules(
        self, authenticated_client
    ):
        """Page must return 200 and not crash when user has zero enabled modules."""
        response = authenticated_client.get("/modules/settings")
        assert response.status_code == 200

    def test_settings_page_renders_with_all_modules_disabled(
        self, app, db_session, test_user, authenticated_client
    ):
        """User has UserModule rows but all is_enabled=False — page must not crash."""
        with app.app_context():
            mod = _make_module(db_session, is_active=True)
            _grant(db_session, test_user.id, mod.id, is_enabled=False)
            db_session.commit()

        response = authenticated_client.get("/modules/settings")
        assert response.status_code == 200

    def test_settings_page_unauthenticated_redirects(self, client):
        response = client.get("/modules/settings")
        assert response.status_code == 302

    def test_settings_page_renders_with_enabled_modules(
        self, app, db_session, test_user, authenticated_client
    ):
        with app.app_context():
            mod = _make_module(db_session, is_active=True)
            _grant(db_session, test_user.id, mod.id, is_enabled=True)
            db_session.commit()

        response = authenticated_client.get("/modules/settings")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# get_user_modules filters inactive system modules
# ---------------------------------------------------------------------------

class TestGetUserModulesFiltering:
    """get_user_modules(enabled_only=True) must exclude globally inactive modules."""

    def test_inactive_system_module_excluded_from_enabled_list(
        self, app, db_session, test_user
    ):
        with app.app_context():
            active_mod = _make_module(db_session, is_active=True)
            inactive_mod = _make_module(db_session, is_active=False)
            _grant(db_session, test_user.id, active_mod.id, is_enabled=True)
            _grant(db_session, test_user.id, inactive_mod.id, is_enabled=True)
            db_session.commit()

            modules = ModuleService.get_user_modules(test_user.id, enabled_only=True)
            codes = [m.code for m in modules]

            assert active_mod.code in codes
            assert inactive_mod.code not in codes

    def test_inactive_system_module_appears_in_full_list(
        self, app, db_session, test_user
    ):
        """When enabled_only=False, inactive modules should still appear (for admin settings)."""
        with app.app_context():
            inactive_mod = _make_module(db_session, is_active=False)
            _grant(db_session, test_user.id, inactive_mod.id, is_enabled=True)
            db_session.commit()

            modules = ModuleService.get_user_modules(test_user.id, enabled_only=False)
            codes = [m.code for m in modules]

            assert inactive_mod.code in codes

    def test_api_user_modules_excludes_inactive_system_modules(
        self, app, db_session, test_user, authenticated_client
    ):
        """GET /api/modules/user must not return globally deactivated modules."""
        with app.app_context():
            inactive_mod = _make_module(db_session, is_active=False)
            _grant(db_session, test_user.id, inactive_mod.id, is_enabled=True)
            db_session.commit()
            inactive_code = inactive_mod.code

        response = authenticated_client.get("/api/modules/user")
        assert response.status_code == 200
        data = response.get_json()
        returned_codes = [m["code"] for m in data["modules"]]
        assert inactive_code not in returned_codes

    def test_api_user_modules_empty_for_user_with_no_grants(
        self, authenticated_client
    ):
        """Users with no module grants receive empty list without error."""
        response = authenticated_client.get("/api/modules/user")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert isinstance(data["modules"], list)


# ---------------------------------------------------------------------------
# admin_or_module_owner gate
# ---------------------------------------------------------------------------

class TestAdminOrModuleOwnerGate:
    """admin_or_module_owner must allow admins and block users without the module."""

    def test_non_admin_without_module_gets_403_via_service(
        self, app, db_session, test_user
    ):
        """Non-admin user without any UserModule row: service returns False."""
        with app.app_context():
            mod = _make_module(db_session, is_active=True)
            db_session.commit()

            result = ModuleService.is_module_enabled_for_user(test_user.id, mod.code)
        assert result is False

    def test_admin_bypasses_module_check_in_decorator(self):
        """admin_or_module_owner must not call service for admin users."""
        from app.modules.decorators import admin_or_module_owner
        from flask import Flask

        test_app = Flask(__name__)

        with patch("app.modules.decorators.current_user") as mock_user, \
             patch("app.modules.decorators.ModuleService.is_module_enabled_for_user") as mock_svc:
            mock_user.is_authenticated = True
            mock_user.is_admin = True

            @admin_or_module_owner("some_module")
            def view():
                return "OK"

            with test_app.test_request_context("/test"):
                result = view()

            assert result == "OK"
            mock_svc.assert_not_called()

    def test_non_admin_with_enabled_module_gets_access(self):
        """Non-admin user with enabled module should get access."""
        from app.modules.decorators import admin_or_module_owner
        from flask import Flask

        test_app = Flask(__name__)

        with patch("app.modules.decorators.current_user") as mock_user, \
             patch("app.modules.decorators.ModuleService.is_module_enabled_for_user") as mock_svc:
            mock_user.is_authenticated = True
            mock_user.is_admin = False
            mock_user.id = 1
            mock_svc.return_value = True

            @admin_or_module_owner("curriculum")
            def view():
                return "OK"

            with test_app.test_request_context("/test"):
                result = view()

            assert result == "OK"

    def test_non_admin_without_module_aborts_403_in_decorator(self):
        """admin_or_module_owner must abort 403 for non-admin without module."""
        from app.modules.decorators import admin_or_module_owner
        from flask import Flask
        import werkzeug.exceptions

        test_app = Flask(__name__)

        with patch("app.modules.decorators.current_user") as mock_user, \
             patch("app.modules.decorators.ModuleService.is_module_enabled_for_user") as mock_svc, \
             patch("app.modules.decorators.flash"):
            mock_user.is_authenticated = True
            mock_user.is_admin = False
            mock_user.id = 1
            mock_svc.return_value = False

            @admin_or_module_owner("curriculum")
            def view():
                return "OK"

            with test_app.test_request_context("/test"):
                with pytest.raises(werkzeug.exceptions.Forbidden):
                    view()
