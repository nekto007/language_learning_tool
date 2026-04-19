"""Router tests for get_daily_plan_unified linear-plan branch.

Covers:
- ``use_linear_plan=True`` routes to the linear assembler (mission flag is
  ignored when linear is also enabled)
- linear-plan exception falls back to mission plan when mission flag is set
- linear-plan exception with no mission flag falls back to legacy payload
- the mission and legacy paths remain unaffected when linear is off
- the stub payload contains the expected skeleton keys
"""
from unittest.mock import patch

import pytest

from app.daily_plan.service import get_daily_plan_unified

SERVICE_MOD = "app.daily_plan.service"
LEGACY_MOD = "app.telegram.queries"


class TestLinearPlanRouting:
    """When use_linear_plan=True, the linear assembler is used."""

    def test_linear_flag_routes_to_linear_assembler(self, app, db_session, test_user):
        """use_linear_plan=True → linear branch fires and mission is skipped."""
        test_user.use_linear_plan = True
        test_user.use_mission_plan = False
        db_session.flush()

        linear_payload = {
            'mode': 'linear',
            'position': None,
            'progress': {'level': '', 'percent': 0},
            'baseline_slots': [],
            'continuation': {'available': False, 'next_lessons': []},
            'day_secured': False,
        }

        with patch(f"{SERVICE_MOD}._get_linear_plan_safe", return_value=linear_payload) as mock_linear, \
                patch(f"{SERVICE_MOD}.get_mission_plan") as mock_mission:
            result = get_daily_plan_unified(test_user.id)

        mock_linear.assert_called_once()
        mock_mission.assert_not_called()
        assert result['mode'] == 'linear'
        assert result['_plan_meta']['effective_mode'] == 'linear'
        assert result['_plan_meta']['fallback_reason'] is None

    def test_linear_flag_wins_over_mission_flag(self, app, db_session, test_user):
        """Both flags on → linear takes priority."""
        test_user.use_linear_plan = True
        test_user.use_mission_plan = True
        db_session.flush()

        linear_payload = {'mode': 'linear'}

        with patch(f"{SERVICE_MOD}._get_linear_plan_safe", return_value=linear_payload), \
                patch(f"{SERVICE_MOD}.get_mission_plan") as mock_mission, \
                patch(f"{LEGACY_MOD}.get_daily_plan_v2") as mock_legacy:
            result = get_daily_plan_unified(test_user.id)

        mock_mission.assert_not_called()
        mock_legacy.assert_not_called()
        assert result['_plan_meta']['effective_mode'] == 'linear'
        assert result['_plan_meta']['mission_plan_enabled'] is True


class TestLinearPlanFallback:
    """When linear assembly fails, fall back gracefully."""

    def test_linear_failure_falls_back_to_mission(self, app, db_session, test_user):
        """Linear returns None → mission plan runs when its flag is on."""
        test_user.use_linear_plan = True
        test_user.use_mission_plan = True
        db_session.flush()

        mission_payload = {'mission': {'type': 'progress'}, 'phases': []}

        with patch(f"{SERVICE_MOD}._get_linear_plan_safe", return_value=None), \
                patch(f"{SERVICE_MOD}.get_mission_plan", return_value=mission_payload) as mock_mission:
            result = get_daily_plan_unified(test_user.id)

        mock_mission.assert_called_once()
        assert result['_plan_meta']['effective_mode'] == 'mission'
        assert result['_plan_meta']['fallback_reason'] == 'linear_build_failed'

    def test_linear_failure_no_mission_falls_back_to_legacy(
        self, app, db_session, test_user
    ):
        """Linear returns None and no mission flag → legacy payload."""
        test_user.use_linear_plan = True
        test_user.use_mission_plan = False
        db_session.flush()

        legacy_payload = {'steps': [], 'next_lesson': None}

        with patch(f"{SERVICE_MOD}._get_linear_plan_safe", return_value=None), \
                patch(f"{LEGACY_MOD}.get_daily_plan_v2", return_value=legacy_payload) as mock_legacy:
            result = get_daily_plan_unified(test_user.id)

        mock_legacy.assert_called_once()
        assert result['_plan_meta']['effective_mode'] == 'legacy_fallback'
        assert result['_plan_meta']['fallback_reason'] == 'linear_build_failed'
        assert 'steps' in result

    def test_linear_failure_mission_also_fails_falls_back_to_legacy(
        self, app, db_session, test_user
    ):
        """Linear None → mission None → legacy."""
        test_user.use_linear_plan = True
        test_user.use_mission_plan = True
        db_session.flush()

        legacy_payload = {'steps': [], 'next_lesson': None}

        with patch(f"{SERVICE_MOD}._get_linear_plan_safe", return_value=None), \
                patch(f"{SERVICE_MOD}.get_mission_plan", return_value=None), \
                patch(f"{LEGACY_MOD}.get_daily_plan_v2", return_value=legacy_payload):
            result = get_daily_plan_unified(test_user.id)

        assert result['_plan_meta']['effective_mode'] == 'legacy_fallback'
        assert result['_plan_meta']['fallback_reason'] == 'linear_build_failed'

    def test_linear_assembler_exception_is_caught(self, app, db_session, test_user):
        """Internal raise inside linear assembler → _get_linear_plan_safe returns None."""
        from app.daily_plan.service import _get_linear_plan_safe

        test_user.use_linear_plan = True
        db_session.flush()

        with patch(
            'app.daily_plan.linear.plan.get_linear_plan',
            side_effect=RuntimeError("DB timeout"),
        ):
            result = _get_linear_plan_safe(test_user.id, tz=None)

        assert result is None

    def test_linear_exception_falls_back_end_to_end(self, app, db_session, test_user):
        """Exception in linear path propagates through safe wrapper → mission."""
        test_user.use_linear_plan = True
        test_user.use_mission_plan = True
        db_session.flush()

        mission_payload = {'mission': {'type': 'progress'}, 'phases': []}

        with patch(
            'app.daily_plan.linear.plan.get_linear_plan',
            side_effect=RuntimeError("boom"),
        ), patch(f"{SERVICE_MOD}.get_mission_plan", return_value=mission_payload):
            result = get_daily_plan_unified(test_user.id)

        assert result['_plan_meta']['effective_mode'] == 'mission'
        assert result['_plan_meta']['fallback_reason'] == 'linear_build_failed'

    def test_linear_failure_emits_warning_log(
        self, app, db_session, test_user, caplog
    ):
        """Falling out of the linear branch logs a structured warning."""
        import logging

        test_user.use_linear_plan = True
        test_user.use_mission_plan = False
        db_session.flush()

        with patch(f"{SERVICE_MOD}._get_linear_plan_safe", return_value=None), \
                patch(f"{LEGACY_MOD}.get_daily_plan_v2", return_value={'steps': []}):
            with caplog.at_level(logging.WARNING, logger="app.daily_plan.service"):
                get_daily_plan_unified(test_user.id)

        assert any(
            "linear plan failed" in r.message for r in caplog.records
        )


class TestNoRegressionOnMissionOrLegacy:
    """Mission and legacy paths must still work when linear flag is off."""

    def test_mission_path_unchanged(self, app, db_session, test_user):
        test_user.use_linear_plan = False
        test_user.use_mission_plan = True
        db_session.flush()

        mission_payload = {'mission': {'type': 'progress'}, 'phases': []}

        with patch(f"{SERVICE_MOD}._get_linear_plan_safe") as mock_linear, \
                patch(f"{SERVICE_MOD}.get_mission_plan", return_value=mission_payload):
            result = get_daily_plan_unified(test_user.id)

        mock_linear.assert_not_called()
        assert result['_plan_meta']['effective_mode'] == 'mission'

    def test_legacy_path_unchanged(self, app, db_session, test_user):
        test_user.use_linear_plan = False
        test_user.use_mission_plan = False
        db_session.flush()

        with patch(f"{SERVICE_MOD}._get_linear_plan_safe") as mock_linear, \
                patch(f"{SERVICE_MOD}.get_mission_plan") as mock_mission, \
                patch(f"{LEGACY_MOD}.get_daily_plan_v2", return_value={'steps': []}):
            result = get_daily_plan_unified(test_user.id)

        mock_linear.assert_not_called()
        mock_mission.assert_not_called()
        assert result['_plan_meta']['effective_mode'] == 'legacy'
        assert result['_plan_meta']['mission_plan_enabled'] is False


class TestLinearStubPayloadShape:
    """The stub payload must have the structural keys the API contract expects."""

    def test_payload_contains_skeleton_keys(self, app, db_session, test_user):
        from app.daily_plan.linear.plan import get_linear_plan

        payload = get_linear_plan(test_user.id, tz=None)

        assert payload['mode'] == 'linear'
        for key in ('position', 'progress', 'baseline_slots', 'continuation', 'day_secured'):
            assert key in payload
        assert payload['baseline_slots'] == []
        assert payload['day_secured'] is False
        assert 'available' in payload['continuation']
        assert 'next_lessons' in payload['continuation']

    def test_payload_wrapped_with_plan_meta_by_router(self, app, db_session, test_user):
        test_user.use_linear_plan = True
        db_session.flush()

        result = get_daily_plan_unified(test_user.id)

        assert '_plan_meta' in result
        assert result['_plan_meta']['effective_mode'] == 'linear'
        assert result['mode'] == 'linear'
