"""maybe_award_linear_perfect_day считает бонус по UNIFIED-плану.

Regression: раньше бонус собирал legacy linear-план (get_linear_plan),
чьи слоты расходились с required unified-плана — бонус был недостижим
для части конфигураций или выдавался без закрытия видимого плана.
"""
from datetime import date
from unittest.mock import patch

from app.daily_plan.linear.xp import maybe_award_linear_perfect_day
from app.utils.db import db as real_db


def _unified_plan(required, *, mode='unified', graduated=False, user_id=1):
    return {
        '_plan_meta': {
            'effective_mode': mode,
            'graduated': graduated,
            'user_id': user_id,
        },
        'required': required,
        'optional': [],
    }


def _item(item_id, completed=False):
    return {'id': item_id, 'kind': item_id.split(':')[0], 'completed': completed}


class TestPerfectDayUsesUnifiedPlan:
    def test_award_when_all_unified_required_completed(self, db_session, test_user):
        plan = _unified_plan(
            [_item('curriculum:lesson:1'), _item('srs:global')],
            user_id=test_user.id,
        )
        completion = {'curriculum:lesson:1': True, 'srs:global': True}

        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value={},
        ), patch(
            'app.achievements.streak_service.compute_plan_steps',
            return_value=(completion, 2, 2, 2),
        ), patch(
            'app.daily_plan.linear.xp.award_perfect_day_xp_idempotent',
        ) as mock_award:
            maybe_award_linear_perfect_day(
                test_user.id, for_date=date(2026, 6, 11), db_session=real_db,
            )

        mock_award.assert_called_once()

    def test_no_award_when_unified_required_incomplete(self, db_session, test_user):
        plan = _unified_plan(
            [_item('curriculum:lesson:1'), _item('srs:global')],
            user_id=test_user.id,
        )
        completion = {'curriculum:lesson:1': True, 'srs:global': False}

        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value={},
        ), patch(
            'app.achievements.streak_service.compute_plan_steps',
            return_value=(completion, 1, 1, 2),
        ), patch(
            'app.daily_plan.linear.xp.award_perfect_day_xp_idempotent',
        ) as mock_award:
            result = maybe_award_linear_perfect_day(
                test_user.id, for_date=date(2026, 6, 11), db_session=real_db,
            )

        assert result is None
        mock_award.assert_not_called()

    def test_no_award_when_plan_paused(self, db_session, test_user):
        plan = _unified_plan([], mode='paused', user_id=test_user.id)

        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value={},
        ), patch(
            'app.daily_plan.linear.xp.award_perfect_day_xp_idempotent',
        ) as mock_award:
            result = maybe_award_linear_perfect_day(
                test_user.id, for_date=date(2026, 6, 11), db_session=real_db,
            )

        assert result is None
        mock_award.assert_not_called()
