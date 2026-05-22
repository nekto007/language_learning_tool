"""Tests for SiteSettings model and get/set helpers."""
import pytest

from app.admin.site_settings import (
    SiteSettings,
    SETTING_DEFAULTS,
    get_site_setting,
    set_site_setting,
    ensure_defaults_seeded,
)
from app.utils.db import db


class TestGetSiteSetting:
    """Tests for get_site_setting()."""

    @pytest.mark.smoke
    def test_returns_default_when_key_missing(self, app, db_session):
        """get_site_setting returns the provided default for an unknown key."""
        result = get_site_setting('nonexistent_key_xyz', default='my_default', db_session=db_session)
        assert result == 'my_default'

    def test_returns_stored_value(self, app, db_session):
        """get_site_setting returns the DB value when the key exists."""
        row = SiteSettings(key='test_key_read', value='stored_value')
        db_session.add(row)
        db_session.flush()

        result = get_site_setting('test_key_read', default='fallback', db_session=db_session)
        assert result == 'stored_value'

    def test_seeds_default_on_first_access(self, app, db_session):
        """First access for a known default key seeds the row."""
        # Ensure the row does not pre-exist
        existing = db_session.get(SiteSettings, 'support_email')
        if existing is not None:
            db_session.delete(existing)
            db_session.flush()

        result = get_site_setting('support_email', db_session=db_session)
        # Should return the SETTING_DEFAULTS value (empty string)
        assert result == SETTING_DEFAULTS['support_email']

        # Row should now exist in DB
        seeded = db_session.get(SiteSettings, 'support_email')
        assert seeded is not None

    def test_returns_none_default_when_no_default_arg(self, app, db_session):
        """get_site_setting with no default arg returns SETTING_DEFAULTS value or None."""
        # A key not in SETTING_DEFAULTS with no default arg
        result = get_site_setting('totally_unknown_key_abc', db_session=db_session)
        assert result is None


class TestSetSiteSetting:
    """Tests for set_site_setting()."""

    @pytest.mark.smoke
    def test_creates_new_row(self, app, db_session):
        """set_site_setting creates a row when key does not exist."""
        set_site_setting('new_test_key', 'hello', db_session=db_session)
        row = db_session.get(SiteSettings, 'new_test_key')
        assert row is not None
        assert row.value == 'hello'

    def test_updates_existing_row(self, app, db_session):
        """set_site_setting updates value when key already exists."""
        db_session.add(SiteSettings(key='update_key', value='old'))
        db_session.flush()

        set_site_setting('update_key', 'new', db_session=db_session)
        row = db_session.get(SiteSettings, 'update_key')
        assert row.value == 'new'

    def test_returns_row_object(self, app, db_session):
        """set_site_setting returns the SiteSettings row."""
        row = set_site_setting('ret_key', 'ret_val', db_session=db_session)
        assert isinstance(row, SiteSettings)
        assert row.key == 'ret_key'
        assert row.value == 'ret_val'

    def test_updated_at_set(self, app, db_session):
        """set_site_setting sets updated_at timestamp."""
        row = set_site_setting('ts_key', 'v', db_session=db_session)
        assert row.updated_at is not None


class TestEnsureDefaultsSeeded:
    """Tests for ensure_defaults_seeded()."""

    def test_seeds_missing_keys(self, app, db_session):
        """ensure_defaults_seeded creates rows for all missing default keys."""
        ensure_defaults_seeded(db_session=db_session)
        for key, expected in SETTING_DEFAULTS.items():
            row = db_session.get(SiteSettings, key)
            assert row is not None, f'Expected row for key {key!r}'
            assert row.value == expected

    def test_idempotent(self, app, db_session):
        """Calling ensure_defaults_seeded twice does not raise or duplicate rows."""
        ensure_defaults_seeded(db_session=db_session)
        ensure_defaults_seeded(db_session=db_session)
        count = db_session.query(SiteSettings).count()
        assert count >= len(SETTING_DEFAULTS)
