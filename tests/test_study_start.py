"""The early-learning card must preserve the authoritative existing route."""
from copy import deepcopy
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

import pytest
from jinja2 import ChainableUndefined, ChoiceLoader, DictLoader, Environment, FileSystemLoader
from sqlalchemy import func

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.onboarding.study_start import build_study_start_card
from app.utils.db import db


@pytest.fixture
def start_lessons(db_session, test_user):
    level = db_session.query(CEFRLevel).filter_by(code='C1').first()
    if level is None:
        level = CEFRLevel(code='C1', name='Advanced', order=5)
        db_session.add(level)
        db_session.flush()
    number = (db_session.query(func.max(Module.number)).filter_by(level_id=level.id).scalar() or 0) + 1
    module = Module(level_id=level.id, number=number, title='Discussing academic ideas')
    db_session.add(module)
    db_session.flush()
    lessons = [Lessons(module_id=module.id, number=index, order=index,
                       title=f'Existing lesson {index}', type=kind, content={})
               for index, kind in enumerate(('vocabulary', 'flashcards', 'reading'), start=1)]
    db_session.add_all(lessons)
    test_user.onboarding_level = 'C1'
    db_session.flush()
    return lessons


def _item(lesson, **updates):
    item = {
        'id': f'curriculum:{lesson.id}', 'kind': 'curriculum',
        'title': lesson.title, 'lesson_type': lesson.type, 'eta_minutes': 7,
        'url': f'/curriculum/lesson/{lesson.id}?from=linear_plan&slot=frozen-42&resume=1',
        'completed': False, 'skipped': False, 'blocked': False,
        'data': {'lesson_id': lesson.id, 'level_code': 'A1', 'module_title': 'Old snapshot title'},
    }
    item.update(updates)
    return item


def _plan(item, **updates):
    plan = {
        'mode': 'unified', '_plan_meta': {'effective_mode': 'unified'},
        'required': [item], 'optional': [], 'setup': [], 'day_secured': False,
        'total_estimated_minutes': 7, 'has_more_optional': False,
        'position': None, 'progress': {}, 'module_progress': {},
    }
    plan.update(updates)
    return plan


def _progress(db_session, user_id, lesson, *, status='completed', data=None):
    now = datetime.now(UTC)
    progress = LessonProgress(user_id=user_id, lesson_id=lesson.id, status=status,
                              started_at=now, last_activity=now,
                              completed_at=now if status == 'completed' else None,
                              data=data or {})
    db_session.add(progress)
    db_session.flush()
    return progress


class TestStudyStartSelection:
    def test_first_card_keeps_frozen_url_and_real_c1_context_without_writes(self, db_session, test_user, start_lessons):
        item = _item(start_lessons[0])
        plan = _plan(item)
        original = deepcopy(plan)
        before = db_session.query(LessonProgress).filter_by(user_id=test_user.id).count()
        card = build_study_start_card(test_user.id, db, plan, {})
        assert card['url'] == item['url']
        assert card['level'] == 'C1'
        assert card['topic'] == 'Discussing academic ideas'
        assert card['cta'] == 'Начать первое занятие'
        assert card['resumed'] is False
        assert plan == original
        assert db_session.query(LessonProgress).filter_by(user_id=test_user.id).count() == before
        assert not db_session.new
        assert not db_session.dirty

    def test_resume_uses_own_same_lesson_and_preserves_saved_answers(self, db_session, test_user, start_lessons):
        lesson = start_lessons[0]
        saved = {'current_index': 3, 'answers': ['already answered']}
        progress = _progress(db_session, test_user.id, lesson, status='in_progress', data=saved)
        item = _item(lesson)
        card = build_study_start_card(test_user.id, db, _plan(item), {})
        assert card['resumed'] is True
        assert card['cta'] == 'Продолжить занятие'
        assert card['url'] == item['url']
        db_session.refresh(progress)
        assert progress.data == saved
        assert progress.status == 'in_progress'

    def test_other_students_progress_does_not_create_resume(self, db_session, test_user, start_lessons):
        other = User(username=f'other_{uuid4().hex[:8]}', active=True, onboarding_completed=True)
        other.set_password('testpass123')
        db_session.add(other)
        db_session.flush()
        _progress(db_session, other.id, start_lessons[0], status='in_progress')
        card = build_study_start_card(test_user.id, db, _plan(_item(start_lessons[0])), {})
        assert card['resumed'] is False
        assert card['cta'] == 'Начать первое занятие'

    def test_stale_completed_candidate_does_not_offer_replay(self, db_session, test_user, start_lessons):
        _progress(db_session, test_user.id, start_lessons[0])
        assert build_study_start_card(test_user.id, db, _plan(_item(start_lessons[0])), {}) is None

    def test_two_completed_lessons_restore_regular_dashboard(self, db_session, test_user, start_lessons):
        for lesson in start_lessons[:2]:
            _progress(db_session, test_user.id, lesson)
        assert build_study_start_card(test_user.id, db, _plan(_item(start_lessons[2])), {}) is None

    @pytest.mark.parametrize('flag', ['blocked', 'skipped', 'completed'])
    def test_nonactionable_candidate_has_no_card(self, flag, db_session, test_user, start_lessons):
        item = _item(start_lessons[0], **{flag: True})
        assert build_study_start_card(test_user.id, db, _plan(item), {}) is None

    @pytest.mark.parametrize('pause', ['mode', 'metadata'])
    def test_pause_wins_over_stale_actionable_item(self, pause, db_session, test_user, start_lessons):
        plan = _plan(_item(start_lessons[0]))
        if pause == 'mode':
            plan['mode'] = 'paused'
        else:
            plan['_plan_meta']['effective_mode'] = 'paused'
        assert build_study_start_card(test_user.id, db, plan, {}) is None

    def test_completion_map_is_authoritative(self, db_session, test_user, start_lessons):
        item = _item(start_lessons[0])
        assert build_study_start_card(test_user.id, db, _plan(item), {item['id']: True}) is None

    def test_secured_day_keeps_completion_celebration(self, db_session, test_user, start_lessons):
        plan = _plan(_item(start_lessons[0]), day_secured=True)
        assert build_study_start_card(test_user.id, db, plan, {}) is None

    def test_optional_cannot_bypass_blocked_required_item(self, db_session, test_user, start_lessons):
        required = _item(start_lessons[0], blocked=True)
        optional = _item(start_lessons[1])
        assert build_study_start_card(test_user.id, db, _plan(required, optional=[optional]), {}) is None

    def test_one_completed_lesson_allows_existing_srs_next_action(self, db_session, test_user, start_lessons):
        _progress(db_session, test_user.id, start_lessons[0])
        srs = {'id': 'srs:today', 'kind': 'srs', 'title': 'Повторить знакомые слова',
               'url': '/study/cards?deck=existing&from=daily_plan', 'eta_minutes': 3, 'data': {}}
        card = build_study_start_card(test_user.id, db, _plan(srs), {})
        assert card['url'] == srs['url']
        assert card['cta'] == 'Начать следующее занятие'
        assert 'повторения' in card['outcome']

    def test_no_curriculum_history_does_not_relabel_existing_srs_user(self, db_session, test_user, start_lessons):
        srs = {'id': 'srs:today', 'kind': 'srs', 'title': 'Cards', 'url': '/study/cards', 'data': {}}
        assert build_study_start_card(test_user.id, db, _plan(srs), {}) is None

    @pytest.mark.parametrize('url', ['https://example.test/lesson', '//example.test/lesson'])
    def test_external_plan_url_not_promoted(self, url, db_session, test_user, start_lessons):
        item = _item(start_lessons[0], url=url)
        assert build_study_start_card(test_user.id, db, _plan(item), {}) is None


class _DashboardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.details = []
        self.primary_ctas = []
        self.plan_details = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'details':
            self.details.append(attrs)
            if 'study-start-plan' in attrs.get('class', '').split():
                self.plan_details.append(attrs)
        if tag == 'a' and 'study-start__cta' in attrs.get('class', '').split():
            self.primary_ctas.append({'href': attrs.get('href'), 'inside_details': bool(self.details)})

    def handle_endtag(self, tag):
        if tag == 'details' and self.details:
            self.details.pop()


def _dashboard_html(card):
    """Render real dashboard/plan partials with only the global site layout stubbed."""
    templates = Path(__file__).resolve().parents[1] / 'app/templates'
    env = Environment(loader=ChoiceLoader([
        DictLoader({'base.html': '{% block extra_css %}{% endblock %}{% block content %}{% endblock %}'}),
        FileSystemLoader(templates),
    ]), autoescape=True, undefined=ChainableUndefined)
    env.globals.update(url_for=lambda endpoint, **kw: f'/stub/{kw.get("filename", endpoint)}',
                       current_user=SimpleNamespace(id=1, username='learner'),
                       csrf_token=lambda: 'token', _=lambda text: text)
    item = {'id': 'frozen:1', 'kind': 'curriculum', 'title': 'Full-plan lesson',
            'url': '/existing/lesson?slot=frozen', 'eta_minutes': 7, 'data': {},
            'lesson_type': 'vocabulary', 'completed': False, 'skipped': False, 'blocked': False}
    return env.get_template('words/dashboard_unified.html').render(
        study_start=card, unified_plan=_plan(item), plan_completion={},
        hero={'title': 'План на сегодня', 'steps_done': 0, 'steps_total': 1}, stats_card={},
        focus={'targets': []}, week_rhythm={'days': []}, challenge_card=None,
        weekly_report=None, rank_info={'code': 'novice', 'display_name': 'Новичок', 'plans_completed': 0,
                                      'is_max': False, 'progress_percent': 0, 'next_threshold': 3},
        xp_leaderboard=[], achievements_by_category={}, show_survey=False, word_set_suggestion=None)


class TestStudyStartDashboard:
    def test_dashboard_route_wires_real_card_and_skips_hidden_widgets(
            self, authenticated_client, test_user, start_lessons):
        plan = _plan(_item(start_lessons[0]))
        summary = {'lessons_count': 0, 'lesson_types': [], 'words_reviewed': 0,
                   'grammar_exercises': 0, 'books_read': []}
        with (
            patch('app.modules.service.ModuleService.is_module_enabled_for_user', return_value=True),
            patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan),
            patch('app.telegram.queries.get_daily_summary', return_value=summary),
            patch('app.words.routes._build_week_rhythm') as rhythm,
            patch('app.words.routes._build_weekly_report') as weekly,
            patch('app.words.routes._build_rank_info') as rank,
        ):
            response = authenticated_client.get('/dashboard')
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        parser = _DashboardParser()
        parser.feed(html)
        assert parser.primary_ctas == [{'href': plan['required'][0]['url'], 'inside_details': False}]
        assert len(parser.plan_details) == 1
        assert 'open' not in parser.plan_details[0]
        rhythm.assert_not_called()
        weekly.assert_not_called()
        rank.assert_not_called()

    def test_early_dashboard_has_one_primary_action_and_collapsed_unchanged_plan(self):
        card = {'eyebrow': 'Ваше первое занятие', 'title': 'Начнём изучение полезных фраз',
                'topic': 'Academic ideas', 'level': 'C1', 'minutes': 7,
                'outcome': 'Изучите полезные фразы.', 'cta': 'Начать первое занятие',
                'url': '/curriculum/lesson/42?from=linear_plan&slot=frozen-42'}
        html = _dashboard_html(card)
        parser = _DashboardParser()
        parser.feed(html)
        assert parser.primary_ctas == [{'href': card['url'], 'inside_details': False}]
        assert len(parser.plan_details) == 1
        assert 'open' not in parser.plan_details[0]
        assert 'Full-plan lesson' in html
        assert '/existing/lesson?slot=frozen' in html
        assert 'C1' in html
        assert 'media/dashboard.png' not in html
        assert 'data-rank-code=' not in html
        assert 'class="dash-path__rail-wrap"' not in html

    def test_regular_dashboard_retains_hero_rank_rail_and_expanded_plan(self):
        html = _dashboard_html(None)
        parser = _DashboardParser()
        parser.feed(html)
        assert parser.primary_ctas == []
        assert parser.plan_details == []
        assert 'media/dashboard.png' in html
        assert 'data-rank-code="novice"' in html
        assert 'class="dash-path__rail-wrap"' in html
        assert 'Full-plan lesson' in html
