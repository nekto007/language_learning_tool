"""Unit tests for _resolve_hero_cta — 6 scenarios covering the hero action hint.

Tests patch Flask's ``url_for`` and the review-budget check so the helper is
exercised in isolation, without a database or request context.
"""
from types import SimpleNamespace
from unittest.mock import patch


def _fake_url_for(endpoint, **values):
    if endpoint == 'onboarding.wizard':
        return '/onboarding'
    if endpoint == 'study.cards':
        return '/study/cards'
    if endpoint == 'curriculum_lessons.lesson_detail':
        return f'/lesson/{values.get("lesson_id", "x")}'
    if endpoint == 'grammar_lab.practice':
        topic = values.get('topic_id')
        return f'/grammar/{topic}' if topic else '/grammar'
    if endpoint == 'books.read_book_chapters':
        return f'/books/{values.get("book_id", "x")}'
    if endpoint == 'words.dashboard':
        return '/dashboard'
    return f'/stub/{endpoint}'


def _phase(idx: int, *, required: bool = True, completed: bool = False) -> dict:
    return {
        'id': f'ph{idx}',
        'phase': ('recall', 'learn', 'use', 'check')[idx % 4],
        'title': f'Phase {idx}',
        'source_kind': 'normal_course',
        'mode': 'curriculum_lesson' if idx == 1 else 'srs_review',
        'required': required,
        'completed': completed,
        'preview': None,
    }


def _mission_plan(phases_completed: list[bool]) -> dict:
    phases = [_phase(i, completed=done) for i, done in enumerate(phases_completed)]
    return {
        'plan_version': 'v1',
        'mission': {
            'type': 'progress',
            'title': 'Продвигаемся вперёд',
            'reason_code': 'default',
            'reason_text': 'Идём дальше',
        },
        'primary_goal': {
            'type': 'complete_lesson',
            'title': 'Завершить урок',
            'success_criterion': '1 урок',
        },
        'primary_source': {'kind': 'normal_course', 'id': '1', 'label': 'Basics'},
        'phases': phases,
        'completion': None,
        'next_lesson': {'lesson_id': 7, 'title': 'Hello'},
    }


def _completion(plan: dict) -> dict:
    return {p['id']: p.get('completed', False) for p in plan['phases']}


def _user(*, onboarding_completed: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=42, onboarding_completed=onboarding_completed)


class TestResolveHeroCta:
    """Matrix of the six documented scenarios for the hero CTA."""

    def test_onboarding_not_completed(self):
        from app.words import routes
        with patch.object(routes, 'url_for', _fake_url_for):
            cta = routes._resolve_hero_cta(
                _user(onboarding_completed=False), None, {}, {}
            )
        assert cta is not None
        assert cta['kind'] == 'onboarding'
        assert cta['title']
        assert '/onboarding' in cta['url']

    def test_fallback_when_no_mission_plan(self):
        from app.words import routes
        with patch.object(routes, 'url_for', _fake_url_for):
            cta = routes._resolve_hero_cta(_user(), None, {}, {})
        assert cta['kind'] == 'fallback'
        assert cta['url'] == '#dash-plan'
        assert 'план' in cta['title'].lower()

    def test_start_when_plan_not_started(self):
        from app.words import routes
        plan = _mission_plan([False, False, False])
        with patch.object(routes, 'url_for', _fake_url_for):
            cta = routes._resolve_hero_cta(_user(), plan, _completion(plan), plan)
        assert cta['kind'] == 'start'
        assert cta['title'].startswith('Начать:')
        assert 'Phase 0' in cta['title']
        assert cta['url']

    def test_continue_when_mid_plan(self):
        from app.words import routes
        plan = _mission_plan([True, False, False])
        with patch.object(routes, 'url_for', _fake_url_for):
            cta = routes._resolve_hero_cta(_user(), plan, _completion(plan), plan)
        assert cta['kind'] == 'continue'
        assert cta['title'].startswith('Продолжить:')
        assert 'Phase 1' in cta['title']
        assert cta['url']

    def test_extra_when_done_with_review_budget(self):
        from app.words import routes
        plan = _mission_plan([True, True, True])
        with patch.object(routes, 'url_for', _fake_url_for), patch(
            'app.daily_plan.service.has_extra_review_capacity', return_value=True
        ):
            cta = routes._resolve_hero_cta(_user(), plan, _completion(plan), plan)
        assert cta['kind'] == 'extra'
        assert 'Карточки' in cta['title']
        assert '/study/cards' in cta['url']
        assert 'from=daily_plan' in cta['url']

    def test_done_when_all_complete_without_budget(self):
        from app.words import routes
        plan = _mission_plan([True, True, True])
        with patch.object(routes, 'url_for', _fake_url_for), patch(
            'app.daily_plan.service.has_extra_review_capacity', return_value=False
        ):
            cta = routes._resolve_hero_cta(_user(), plan, _completion(plan), plan)
        assert cta['kind'] == 'done'
        assert cta['url'] is None
        assert 'готов' in cta['title'].lower()

    def test_done_when_no_required_incomplete_phases(self):
        """All-optional plans collapse to 'done' — no required phase to target."""
        from app.words import routes
        plan = _mission_plan([False, False, False])
        for phase in plan['phases']:
            phase['required'] = False
        with patch.object(routes, 'url_for', _fake_url_for), patch(
            'app.daily_plan.service.has_extra_review_capacity', return_value=False
        ):
            cta = routes._resolve_hero_cta(_user(), plan, _completion(plan), plan)
        assert cta['kind'] == 'done'
        assert cta['url'] is None

    def test_continue_skips_completed_required_phases(self):
        """With the first two required phases done, the CTA points to phase 2."""
        from app.words import routes
        plan = _mission_plan([True, True, False])
        with patch.object(routes, 'url_for', _fake_url_for):
            cta = routes._resolve_hero_cta(_user(), plan, _completion(plan), plan)
        assert cta['kind'] == 'continue'
        assert 'Phase 2' in cta['title']

    def test_returns_none_when_user_missing(self):
        from app.words import routes
        assert routes._resolve_hero_cta(None, None, {}, {}) is None


class TestResolveNextPhase:
    def test_none_when_no_plan(self):
        from app.daily_plan.service import resolve_next_phase
        assert resolve_next_phase(None, {}) is None

    def test_none_when_all_required_complete(self):
        from app.daily_plan.service import resolve_next_phase
        plan = _mission_plan([True, True, True])
        assert resolve_next_phase(plan, _completion(plan)) is None

    def test_skips_optional_phases(self):
        from app.daily_plan.service import resolve_next_phase
        plan = _mission_plan([False, False, False])
        plan['phases'][0]['required'] = False
        next_phase = resolve_next_phase(plan, _completion(plan))
        assert next_phase is not None
        assert next_phase['id'] == 'ph1'

    def test_returns_first_incomplete_required(self):
        from app.daily_plan.service import resolve_next_phase
        plan = _mission_plan([True, False, False])
        next_phase = resolve_next_phase(plan, _completion(plan))
        assert next_phase is not None
        assert next_phase['id'] == 'ph1'


class TestHeroCtaTemplateMarkers:
    """Template assertions that are independent of the rendering stack."""

    def test_template_wires_hero_cta_block(self):
        import os
        tpl_path = os.path.join(
            os.path.dirname(__file__),
            '..', 'app', 'templates', 'dashboard.html',
        )
        with open(tpl_path, 'r', encoding='utf-8') as f:
            html = f.read()
        assert 'hero_cta' in html
        assert 'dash-hero__cta' in html
        assert 'data-hero-cta' in html

    def test_template_has_hero_cta_styles(self):
        import os
        tpl_path = os.path.join(
            os.path.dirname(__file__),
            '..', 'app', 'templates', 'dashboard.html',
        )
        with open(tpl_path, 'r', encoding='utf-8') as f:
            css = f.read()
        assert '.dash-hero__cta' in css
        for kind in ('done', 'extra'):
            assert f'.dash-hero__cta--{kind}' in css
