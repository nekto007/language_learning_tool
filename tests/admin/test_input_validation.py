"""Tests for admin input/query-parameter validation (Task 5).

Verifies that admin routes reject malformed query strings with HTTP 400
instead of silently coercing to defaults or returning empty results.
Covers the helpers in `app/admin/utils/request_validators.py` and their
integration with `user_admin` and `word_admin` blueprints.
"""
from enum import Enum

import pytest

from app.admin.utils.request_validators import (
    get_choice_arg,
    get_enum_arg,
    get_int_arg,
)
from app.utils.validators import WordStatus


class _Color(str, Enum):
    RED = 'red'
    BLUE = 'blue'


class TestRequestValidatorHelpers:
    """Unit tests for the standalone helper functions."""

    def test_get_int_arg_returns_default_when_missing(self, app):
        with app.test_request_context('/'):
            assert get_int_arg('page', default=1) == 1

    def test_get_int_arg_parses_valid_int(self, app):
        with app.test_request_context('/?page=5'):
            assert get_int_arg('page', default=1) == 5

    def test_get_int_arg_rejects_non_integer(self, app):
        from werkzeug.exceptions import BadRequest

        with app.test_request_context('/?page=abc'):
            with pytest.raises(BadRequest):
                get_int_arg('page', default=1)

    def test_get_int_arg_rejects_below_min(self, app):
        from werkzeug.exceptions import BadRequest

        with app.test_request_context('/?page=0'):
            with pytest.raises(BadRequest):
                get_int_arg('page', default=1, min_val=1)

    def test_get_int_arg_rejects_above_max(self, app):
        from werkzeug.exceptions import BadRequest

        with app.test_request_context('/?per_page=10000'):
            with pytest.raises(BadRequest):
                get_int_arg('per_page', default=20, max_val=100)

    def test_get_enum_arg_accepts_valid_value(self, app):
        with app.test_request_context('/?color=red'):
            assert get_enum_arg('color', _Color) == 'red'

    def test_get_enum_arg_returns_default_when_missing(self, app):
        with app.test_request_context('/'):
            assert get_enum_arg('color', _Color, default='red') == 'red'

    def test_get_enum_arg_rejects_invalid_value(self, app):
        from werkzeug.exceptions import BadRequest

        with app.test_request_context('/?color=purple'):
            with pytest.raises(BadRequest):
                get_enum_arg('color', _Color)

    def test_get_choice_arg_accepts_value_in_choices(self, app):
        with app.test_request_context('/?format=csv'):
            assert get_choice_arg('format', ('json', 'csv', 'txt')) == 'csv'

    def test_get_choice_arg_rejects_value_outside_choices(self, app):
        from werkzeug.exceptions import BadRequest

        with app.test_request_context('/?format=xlsx'):
            with pytest.raises(BadRequest):
                get_choice_arg('format', ('json', 'csv', 'txt'))

    def test_word_status_enum_covers_canonical_statuses(self):
        # Sanity check: enum values match what UserWord.status stores.
        assert {m.value for m in WordStatus} >= {'new', 'learning', 'review'}


class TestAdminUserListValidation:
    """Integration: /admin/users rejects malformed pagination params."""

    def test_valid_page_renders_200(self, admin_client):
        response = admin_client.get('/admin/users?page=1&per_page=20')
        assert response.status_code == 200

    def test_invalid_page_returns_400(self, admin_client):
        response = admin_client.get('/admin/users?page=abc')
        assert response.status_code == 400

    def test_invalid_per_page_returns_400(self, admin_client):
        response = admin_client.get('/admin/users?per_page=not-a-number')
        assert response.status_code == 400

    def test_page_zero_returns_400(self, admin_client):
        response = admin_client.get('/admin/users?page=0')
        assert response.status_code == 400

    def test_negative_page_returns_400(self, admin_client):
        response = admin_client.get('/admin/users?page=-3')
        assert response.status_code == 400

    def test_per_page_above_cap_is_clamped_to_200(self, admin_client):
        # per_page=500 is clamped silently (preserves existing behavior).
        response = admin_client.get('/admin/users?per_page=500')
        assert response.status_code == 200


class TestAdminWordExportValidation:
    """Integration: /admin/words/export rejects bad enum/choice values."""

    def test_valid_json_export(self, admin_client):
        response = admin_client.get('/admin/words/export?format=json')
        assert response.status_code == 200

    def test_invalid_format_returns_400(self, admin_client):
        response = admin_client.get('/admin/words/export?format=xlsx')
        assert response.status_code == 400

    def test_invalid_status_returns_400(self, admin_client):
        response = admin_client.get(
            '/admin/words/export?format=json&status=not_a_status'
        )
        assert response.status_code == 400

    def test_valid_status_filter(self, admin_client):
        response = admin_client.get(
            '/admin/words/export?format=json&status=learning'
        )
        assert response.status_code == 200

    def test_invalid_user_id_returns_400(self, admin_client):
        response = admin_client.get(
            '/admin/words/export?format=json&user_id=abc'
        )
        assert response.status_code == 400

    def test_negative_user_id_returns_400(self, admin_client):
        response = admin_client.get(
            '/admin/words/export?format=json&user_id=-1'
        )
        assert response.status_code == 400
