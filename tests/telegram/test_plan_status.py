"""Tests for Telegram /plan command."""
import pytest
from unittest.mock import patch, MagicMock

from app.telegram.models import TelegramUser
from app.telegram.notifications import format_linear_plan_text


# ── format_linear_plan_text unit tests ──────────────────────────────

def _make_linear_plan(slots=None, day_secured=False, progress=None):
    if slots is None:
        slots = [
            {'kind': 'curriculum', 'title': 'Урок: Тема 1', 'completed': False},
            {'kind': 'srs', 'title': 'Повторение слов', 'completed': False},
        ]
    return {
        'mode': 'linear',
        'slots': slots,
        'baseline_slots': slots,
        'day_secured': day_secured,
        'progress': progress or {'level': 'A2', 'percent': 40},
        'continuation': {},
        'position': None,
    }


class TestFormatLinearPlanText:
    def test_returns_formatted_text_with_slots(self):
        plan = _make_linear_plan()
        text = format_linear_plan_text(plan)
        assert 'Линейный план' in text
        assert 'Урок: Тема 1' in text
        assert 'Повторение слов' in text

    def test_shows_completion_counts(self):
        slots = [
            {'kind': 'curriculum', 'title': 'Урок', 'completed': True},
            {'kind': 'srs', 'title': 'Слова', 'completed': False},
        ]
        plan = _make_linear_plan(slots=slots)
        text = format_linear_plan_text(plan)
        assert '1/2' in text

    def test_completed_slot_shows_checkmark(self):
        slots = [{'kind': 'curriculum', 'title': 'Урок', 'completed': True}]
        plan = _make_linear_plan(slots=slots)
        text = format_linear_plan_text(plan)
        assert '\u2705' in text  # ✅

    def test_incomplete_slot_shows_white_square(self):
        slots = [{'kind': 'curriculum', 'title': 'Урок', 'completed': False}]
        plan = _make_linear_plan(slots=slots)
        text = format_linear_plan_text(plan)
        assert '\u2b1c' in text or '\u25b6' in text  # ⬜ or ▶️

    def test_shows_level_info(self):
        plan = _make_linear_plan(progress={'level': 'B1', 'percent': 55})
        text = format_linear_plan_text(plan)
        assert 'B1' in text
        assert '55%' in text


# ── _handle_plan handler unit tests ─────────────────────────────────

class TestHandlePlan:
    """Test /plan command handler via mocking."""

    def _make_update(self, text='/plan', telegram_id=12345, chat_id=12345):
        return {
            'message': {
                'chat': {'id': chat_id},
                'from': {'id': telegram_id, 'username': 'testuser'},
                'text': text,
            }
        }

    def test_plan_no_account_returns_link_message(self, app, db_session):
        from app.telegram.bot import _handle_plan

        sent = []
        with app.app_context():
            with patch('app.telegram.bot._send_message', side_effect=lambda c, t, **kw: sent.append(t)):
                _handle_plan(chat_id=999, telegram_id=999999)

        assert len(sent) == 1
        assert 'привяжи' in sent[0].lower() or 'link' in sent[0].lower()

    def test_plan_no_plan_data_returns_open_app_message(self, app, db_session, test_user):
        from app.telegram.bot import _handle_plan

        tg_user = TelegramUser(
            user_id=test_user.id,
            telegram_id=77777,
            username='plantest',
            is_active=True,
        )
        db_session.add(tg_user)
        db_session.commit()

        sent = []
        with app.app_context():
            with patch('app.telegram.bot._send_message', side_effect=lambda c, t, **kw: sent.append(t)):
                with patch('app.telegram.queries.get_daily_plan_for_telegram', return_value={}):
                    _handle_plan(chat_id=77777, telegram_id=77777)

        assert len(sent) == 1
        assert 'Открой приложение' in sent[0]

    def test_plan_linear_returns_formatted_text(self, app, db_session, test_user):
        from app.telegram.bot import _handle_plan

        tg_user = TelegramUser(
            user_id=test_user.id,
            telegram_id=88888,
            username='lineartest',
            is_active=True,
        )
        db_session.add(tg_user)
        db_session.commit()

        linear_plan = {
            'mode': 'linear',
            'slots': [
                {'kind': 'curriculum', 'title': 'Тема 3', 'completed': False, 'url': '/learn/1/'},
                {'kind': 'srs', 'title': 'Слова', 'completed': True, 'url': '/study'},
            ],
            'baseline_slots': [
                {'kind': 'curriculum', 'title': 'Тема 3', 'completed': False, 'url': '/learn/1/'},
                {'kind': 'srs', 'title': 'Слова', 'completed': True, 'url': '/study'},
            ],
            'day_secured': False,
            'progress': {'level': 'A2', 'percent': 30},
            'continuation': {},
            'position': None,
            'chain_meta': {'baseline_count': 2, 'has_more_available': False, 'exhausted_sources': []},
        }
        summary = {'words_reviewed': 5, 'lessons_count': 0, 'grammar_exercises': 0}
        mock_coins = MagicMock()
        mock_coins.balance = 100

        sent = []
        with app.app_context():
            with patch('app.telegram.bot._send_message', side_effect=lambda c, t, **kw: sent.append(t)):
                with patch('app.telegram.queries.get_daily_plan_for_telegram', return_value=linear_plan):
                    with patch('app.telegram.queries.get_daily_summary', return_value=summary):
                        with patch('app.telegram.queries.get_current_streak', return_value=5):
                            with patch('app.telegram.queries.get_cards_url', return_value=''):
                                with patch('app.achievements.streak_service.get_or_create_coins', return_value=mock_coins):
                                    with patch('app.daily_plan.linear.chain.extend_chain_after_activity'):
                                        with patch('app.achievements.streak_service._compute_linear_slot_completion', return_value={}):
                                            with patch('app.daily_plan.linear.plan.compute_linear_day_secured', return_value=False):
                                                _handle_plan(chat_id=88888, telegram_id=88888)

        assert len(sent) == 1
        text = sent[0]
        assert 'Лине' in text or 'план' in text.lower()
        assert '5 дней' in text
        assert 'Тема 3' in text or 'Слова' in text
