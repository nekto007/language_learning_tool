"""DP-073 — карточка «Челлендж» в правой колонке строится из пункта плана.

Старый код требовал ``DailyChallenge.lesson_id``, который сеятель никогда не
заполняет (одна строка на день для всех пользователей не может нести
персональный урок) — карточка не рендерилась ни у кого ни в один день
(85 из 85 челленджей прода с ``lesson_id IS NULL``).
"""
from __future__ import annotations

from app.words.routes import _challenge_card_from_plan


def _plan(optional):
    return {'mode': 'unified', 'required': [], 'optional': optional, 'setup': []}


class TestChallengeCardFromPlan:

    def test_pending_challenge_item_becomes_a_card(self):
        card = _challenge_card_from_plan(_plan([
            {'id': 'srs:global', 'kind': 'srs', 'title': 'Повторение', 'url': '/study'},
            {
                'id': 'challenge:7', 'kind': 'challenge',
                'title': 'Челлендж дня: целься в точность',
                'url': '/learn/42/?from=linear_plan&slot=challenge',
                'completed': False,
                'data': {'is_challenge': True, 'bonus_xp': 60, 'lesson_id': 42},
            },
        ]))
        assert card == {
            'title': 'Челлендж дня: целься в точность',
            'badge': '+60 XP',
            'completed': False,
            'url': '/learn/42/?from=linear_plan&slot=challenge',
        }

    def test_completed_challenge_keeps_the_card_without_a_link(self):
        card = _challenge_card_from_plan(_plan([{
            'id': 'challenge:7', 'kind': 'challenge', 'title': 'Челлендж дня',
            'url': None, 'completed': True, 'data': {'bonus_xp': 50},
        }]))
        assert card is not None
        assert card['completed'] is True
        assert card['url'] is None
        assert card['badge'] == '+50 XP'

    def test_no_challenge_item_means_no_card(self):
        assert _challenge_card_from_plan(_plan([
            {'id': 'srs:global', 'kind': 'srs', 'title': 'Повторение', 'url': '/study'},
        ])) is None

    def test_paused_payload_without_optional_means_no_card(self):
        assert _challenge_card_from_plan({'mode': 'paused', 'paused_until': '2026-09-10'}) is None
        assert _challenge_card_from_plan({}) is None

    def test_badge_is_the_real_bonus_not_a_multiplier(self):
        """Старая карточка печатала «×2 XP», чего челлендж не делает."""
        card = _challenge_card_from_plan(_plan([{
            'id': 'challenge:1', 'kind': 'challenge', 'title': 'x', 'url': '/learn/1/',
            'completed': False, 'data': {'bonus_xp': 'oops'},
        }]))
        assert card is not None
        assert card['badge'] == ''
        assert '×' not in card['badge']
