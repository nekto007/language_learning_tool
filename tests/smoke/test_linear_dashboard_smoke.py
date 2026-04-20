"""Smoke tests for the linear daily plan dashboard (Task 12).

Four scenarios covering the linear-vs-mission flows end-to-end through
both the dashboard route and the ``/api/daily-plan`` endpoint:

1. ``use_linear_plan=True`` → dashboard renders the linear partial (3
   baseline slots) and the API returns ``mode=linear``.
2. ``use_linear_plan=False`` → legacy mission flow keeps working with no
   linear-only markers (guard against regressions).
3. First entry without ``UserReadingPreference`` → reading slot shows
   "Выбрать книгу" and the dashboard ships the book-select modal.
4. All 3 baseline slots done → continuation CTA + preview visible,
   ``day_secured=True`` in both the dashboard HTML and the API payload.

Marked ``@pytest.mark.smoke`` so they participate in ``pytest -m smoke``
fast lane (<30s for the whole smoke suite).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


pytestmark = pytest.mark.smoke


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def words_module_access(app, db_session, test_user):
    """Grant words module access to ``test_user`` so the dashboard route
    clears ``@module_required('words')``."""
    from app.modules.models import SystemModule, UserModule

    words_module = SystemModule.query.filter_by(code='words').first()
    if not words_module:
        words_module = SystemModule(
            code='words',
            name='Words',
            description='Words module',
        )
        db_session.add(words_module)
        db_session.flush()

    existing = UserModule.query.filter_by(
        user_id=test_user.id, module_id=words_module.id,
    ).first()
    if not existing:
        db_session.add(UserModule(
            user_id=test_user.id,
            module_id=words_module.id,
            is_enabled=True,
        ))
        db_session.commit()
    return words_module


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _strip_inline_style(markup: str) -> str:
    """Drop ``<style>…</style>`` blocks so CSS class names in the
    stylesheet don't satisfy string-contains assertions on rendered
    markup."""
    out = markup
    while '<style>' in out and '</style>' in out:
        start = out.index('<style>')
        end = out.index('</style>', start) + len('</style>')
        out = out[:start] + out[end:]
    return out


def _seed_user_activity(db_session, user):
    """Add one study word for scenarios that need non-zero activity."""
    import uuid

    from app.srs.constants import CardState
    from app.study.models import UserCardDirection, UserWord
    from app.words.models import CollectionWords

    word = CollectionWords(
        english_word=f'smoke_{uuid.uuid4().hex[:6]}',
        russian_word='дым',
        level='A1',
    )
    db_session.add(word)
    db_session.flush()
    user_word = UserWord(user_id=user.id, word_id=word.id)
    db_session.add(user_word)
    db_session.flush()
    direction = UserCardDirection(user_word_id=user_word.id, direction='eng-rus')
    direction.state = CardState.NEW.value
    db_session.add(direction)
    db_session.commit()


# ── Plan payload builders (mirror the linear-plan assembler shape) ───


def _linear_plan(
    *,
    reading_needs_selection: bool = False,
    curriculum_done: bool = False,
    srs_done: bool = False,
    reading_done: bool = False,
    next_lessons: list[dict] | None = None,
) -> dict:
    curriculum_slot = {
        'kind': 'curriculum',
        'title': 'B1 · M1 · L1 (card)',
        'lesson_type': 'card',
        'eta_minutes': 8,
        'url': '/curriculum_lessons/101?from=linear_plan&source=linear_plan_card',
        'completed': curriculum_done,
        'data': {},
    }
    srs_slot = {
        'kind': 'srs',
        'title': 'Карточки на повторение',
        'lesson_type': None,
        'eta_minutes': 5,
        'url': '/study?source=linear_plan',
        'completed': srs_done,
        'data': {'due_count': 3},
    }
    if reading_needs_selection:
        reading_slot = {
            'kind': 'reading',
            'title': 'Выбрать книгу',
            'lesson_type': None,
            'eta_minutes': 10,
            'url': '#book-select-modal',
            'completed': False,
            'data': {'needs_selection': True},
        }
    else:
        reading_slot = {
            'kind': 'reading',
            'title': 'The Hobbit',
            'lesson_type': None,
            'eta_minutes': 10,
            'url': '/read/42?from=linear_plan',
            'completed': reading_done,
            'data': {
                'book_id': 42,
                'book_title': 'The Hobbit',
                'book_level': 'B1',
                'cover_image': None,
                'current_chapter_num': 1,
                'current_chapter_title': 'An Unexpected Party',
                'needs_selection': False,
            },
        }

    return {
        'mode': 'linear',
        'position': {
            'lesson_id': 101,
            'lesson_type': 'card',
            'lesson_number': 1,
            'module_id': 50,
            'module_number': 1,
            'level_code': 'B1',
        },
        'progress': {
            'level': 'B1',
            'percent': 0,
            'lessons_remaining_in_level': 60,
        },
        'baseline_slots': [curriculum_slot, srs_slot, reading_slot],
        'continuation': {
            'available': curriculum_done and srs_done and reading_done,
            'next_lessons': next_lessons or [],
        },
        'day_secured': False,
        '_plan_meta': {
            'mission_plan_enabled': False,
            'effective_mode': 'linear',
            'fallback_reason': None,
        },
    }


def _mission_plan() -> dict:
    return {
        'next_lesson': None,
        'grammar_topic': None,
        'words_due': 0,
        'has_any_words': False,
        'book_to_read': None,
        'suggested_books': [],
        'book_course_lesson': None,
        'book_course_done_today': False,
        'onboarding': None,
        'bonus': [],
        'mission': {
            'type': 'progress',
            'title': 'Продвигаемся вперёд',
            'reason_code': 'progress_default',
            'reason_text': 'Следующий урок готов',
        },
        'primary_goal': {
            'type': 'complete_lesson',
            'title': 'Завершить урок',
            'success_criterion': '1 урок',
        },
        'primary_source': {
            'kind': 'normal_course',
            'id': '1',
            'label': 'English Basics',
        },
        'phases': [
            {
                'id': 'p1',
                'phase': 'recall',
                'title': 'Разогрев',
                'source_kind': 'srs',
                'mode': 'srs_review',
                'required': True,
                'completed': False,
                'preview': None,
            },
        ],
        'completion': None,
        'day_secured': False,
        '_plan_meta': {
            'mission_plan_enabled': True,
            'effective_mode': 'mission',
            'fallback_reason': None,
        },
    }


def _empty_summary() -> dict:
    return {
        'lessons_count': 0,
        'lesson_types': [],
        'words_reviewed': 0,
        'srs_words_reviewed': 0,
        'srs_new_reviewed': 0,
        'srs_review_reviewed': 0,
        'grammar_exercises': 0,
        'grammar_correct': 0,
        'books_read': [],
        'book_course_lessons_today': 0,
    }


# ── Scenario 1: linear user renders linear partial + API mode=linear ─


def test_scenario_1_linear_user_renders_linear_partial(
    client, db_session, test_user, words_module_access,
):
    """use_linear_plan=True → linear partial renders 3 slots; API returns mode=linear."""
    test_user.use_linear_plan = True
    db_session.commit()
    _login(client, test_user)

    plan = _linear_plan()
    with patch(
        'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
    ):
        dashboard_response = client.get('/dashboard')
        api_response = client.get('/api/daily-plan')

    assert dashboard_response.status_code == 200
    html = _strip_inline_style(dashboard_response.data.decode('utf-8'))
    assert 'data-linear-plan="true"' in html
    assert 'data-zero-state="true"' not in html
    # All three baseline slots should appear with the expected kinds.
    assert 'data-slot-kind="curriculum"' in html
    assert 'data-slot-kind="srs"' in html
    assert 'data-slot-kind="reading"' in html
    # Mission-only markers must not leak into the linear render.
    assert 'data-mission-plan' not in html

    assert api_response.status_code == 200
    data = api_response.get_json()
    assert data['success'] is True
    assert data['mode'] == 'linear'
    assert {s['kind'] for s in data['baseline_slots']} == {
        'curriculum', 'srs', 'reading',
    }


# ── Scenario 2: legacy mission user keeps working (no regression) ────


def test_scenario_2_legacy_mission_user_no_regression(
    client, db_session, test_user, words_module_access,
):
    """use_linear_plan=False + mission plan → no linear markers in HTML/API."""
    test_user.use_linear_plan = False
    test_user.use_mission_plan = True
    db_session.commit()
    _seed_user_activity(db_session, test_user)
    _login(client, test_user)

    plan = _mission_plan()
    with patch(
        'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
    ):
        dashboard_response = client.get('/dashboard')
        api_response = client.get('/api/daily-plan')

    assert dashboard_response.status_code == 200
    html = _strip_inline_style(dashboard_response.data.decode('utf-8'))
    # Linear-only markers absent on legacy/mission flow.
    assert 'data-linear-plan="true"' not in html
    assert 'data-linear-slots="true"' not in html

    assert api_response.status_code == 200
    data = api_response.get_json()
    # Mission payload keeps its shape — no `mode=linear`, no baseline_slots.
    assert data.get('mode') != 'linear'
    assert data.get('baseline_slots') is None
    # Mission-shape keys stay present.
    assert 'phases' in data
    assert data.get('mission', {}).get('type') == 'progress'


# ── Scenario 3: no book preference → "Выбрать книгу" + modal shipped ─


def test_scenario_3_first_entry_shows_select_book_and_modal(
    client, db_session, test_user, words_module_access,
):
    """First entry without UserReadingPreference → slot label + modal markup present."""
    test_user.use_linear_plan = True
    db_session.commit()
    _seed_user_activity(db_session, test_user)
    _login(client, test_user)

    plan = _linear_plan(reading_needs_selection=True)
    with patch(
        'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
    ):
        response = client.get('/dashboard')

    assert response.status_code == 200
    html = _strip_inline_style(response.data.decode('utf-8'))
    # Reading slot renders in select-book mode.
    assert 'data-linear-action="select-book"' in html
    assert 'Выбрать книгу' in html
    assert 'href="#book-select-modal"' in html
    # Modal markup is in the dashboard so the link can open it.
    assert 'id="book-select-modal"' in html
    assert 'book-select-modal-list' in html


# ── Scenario 4: all 3 slots done → continuation CTA + day_secured ────


def test_scenario_4_all_slots_done_shows_continuation_and_secured(
    client, db_session, test_user, words_module_access,
):
    """All 3 baseline slots completed → continuation CTA + day_secured=True."""
    test_user.use_linear_plan = True
    db_session.commit()
    _seed_user_activity(db_session, test_user)
    _login(client, test_user)

    next_lessons = [
        {
            'lesson_id': 102,
            'lesson_type': 'grammar',
            'lesson_number': 2,
            'module_id': 50,
            'module_number': 1,
            'level_code': 'B1',
        },
        {
            'lesson_id': 103,
            'lesson_type': 'quiz',
            'lesson_number': 3,
            'module_id': 50,
            'module_number': 1,
            'level_code': 'B1',
        },
    ]
    plan = _linear_plan(
        curriculum_done=True,
        srs_done=True,
        reading_done=True,
        next_lessons=next_lessons,
    )
    # Summary is empty — slot.completed=True in the mock alone drives
    # the template's day_secured computation.
    with patch(
        'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
    ), patch(
        'app.telegram.queries.get_daily_summary', return_value=_empty_summary(),
    ):
        dashboard_response = client.get('/dashboard')
        api_response = client.get('/api/daily-plan')

    assert dashboard_response.status_code == 200
    html = _strip_inline_style(dashboard_response.data.decode('utf-8'))
    # Day-secured banner + continuation CTA are rendered.
    assert 'data-linear-secured="true"' in html
    assert 'data-linear-continuation="true"' in html
    # Continuation CTA points at the first upcoming lesson.
    assert '/learn/102/?from=linear_plan_continuation' in html

    assert api_response.status_code == 200
    data = api_response.get_json()
    assert data['mode'] == 'linear'
    assert data['day_secured'] is True
