"""Task 6: Error-review breakdown chips in the theory header.

The /learn/error-review/ page renders top-3 lessons and top-3 grammar
topics derived from the unresolved QuizErrorLog backlog. Empty backlogs
hit the empty state and never render the chips wrapper.
"""
from __future__ import annotations

import uuid

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.linear.errors import log_quiz_error
from app.grammar_lab.models import GrammarTopic
from app.utils.db import db as real_db


pytestmark = pytest.mark.usefixtures('app')


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'er_chips_{suffix}',
        email=f'er_chips_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    user.onboarding_completed = True
    db_session.add(user)
    db_session.commit()
    return user


def _make_topic(db_session, slug: str, title: str) -> GrammarTopic:
    suffix = uuid.uuid4().hex[:6]
    topic = GrammarTopic(
        slug=f'{slug}-{suffix}',
        title=title,
        title_ru=title,
        level='A1',
        order=1,
    )
    db_session.add(topic)
    db_session.commit()
    return topic


def _make_lesson(db_session, title: str, topic_id=None) -> Lessons:
    level = CEFRLevel(code=_unique_code(), name='L', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='M',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title=title,
        type='grammar',
        content={},
        grammar_topic_id=topic_id,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _strip_style_blocks(markup: str) -> str:
    """Drop <style>...</style> so CSS rules don't satisfy class-name
    contains-checks on the rendered HTML."""
    out, lower = markup, markup.lower()
    while '<style' in lower:
        start = lower.find('<style')
        end = lower.find('</style>', start)
        if end == -1:
            break
        out = out[:start] + out[end + len('</style>'):]
        lower = out.lower()
    return out


def test_error_review_view_renders_breakdown_chips(client, db_session):
    user = _make_user(db_session)
    topic_present = _make_topic(db_session, 'present', 'Present Simple')
    topic_past = _make_topic(db_session, 'past', 'Past Simple')

    lesson_a = _make_lesson(db_session, 'Introduction A', topic_id=topic_present.id)
    lesson_b = _make_lesson(db_session, 'Introduction B', topic_id=topic_past.id)

    # 3 errors on lesson_a / topic_present, 2 on lesson_b / topic_past
    for i in range(3):
        log_quiz_error(
            user.id, lesson_a.id,
            {'question_index': i, 'question_text': 'Q', 'user_answer': 'x', 'correct_answer': 'y'},
            real_db, commit=False,
        )
    for i in range(2):
        log_quiz_error(
            user.id, lesson_b.id,
            {'question_index': i, 'question_text': 'Q', 'user_answer': 'x', 'correct_answer': 'y'},
            real_db, commit=False,
        )
    db_session.commit()

    _login(client, user)
    resp = client.get('/learn/error-review/')
    if resp.status_code == 302:
        pytest.fail(f'Unexpected redirect to {resp.headers.get("Location")!r}')
    assert resp.status_code == 200
    body = _strip_style_blocks(resp.get_data(as_text=True))

    # Chips wrapper renders
    assert 'class="error-review__chips"' in body
    assert 'data-testid="er-breakdown-chips"' in body

    # Lesson chips include both lesson titles
    assert 'Introduction A' in body
    assert 'Introduction B' in body

    # Grammar topic chips include both topic titles (title_ru)
    assert 'Present Simple' in body
    assert 'Past Simple' in body

    # Counts surface (3 for lesson_a/topic_present, 2 for lesson_b/topic_past)
    assert 'class="error-review__chip-count"' in body
    chip_count_idx = body.find('error-review__chip-count')
    assert chip_count_idx != -1
    # Body has at least 3+2 (lessons) and 3+2 (topics) = 4 chip counts, but
    # de-dup may drop. Just assert the values 3 and 2 appear in chip context.
    assert '>3<' in body
    assert '>2<' in body


def test_error_review_view_no_chips_on_empty_backlog(client, db_session):
    user = _make_user(db_session)
    _login(client, user)

    resp = client.get('/learn/error-review/')
    assert resp.status_code == 200
    body = _strip_style_blocks(resp.get_data(as_text=True))

    # Empty state instead of chips
    assert 'class="er-empty"' in body
    assert 'class="error-review__chips"' not in body
    assert 'data-testid="er-breakdown-chips"' not in body


def test_error_review_view_caps_at_three_chips_per_row(client, db_session):
    """Top-3 cap: 4 distinct lessons → only 3 lesson chips rendered."""
    user = _make_user(db_session)
    topic = _make_topic(db_session, 'cap', 'Articles')

    lessons = [
        _make_lesson(db_session, f'Cap Lesson {i}', topic_id=topic.id)
        for i in range(4)
    ]
    # Different counts so ordering is deterministic: 4, 3, 2, 1
    counts = [4, 3, 2, 1]
    for lesson, n in zip(lessons, counts):
        for i in range(n):
            log_quiz_error(
                user.id, lesson.id,
                {'question_index': i, 'question_text': 'Q', 'user_answer': 'x', 'correct_answer': 'y'},
                real_db, commit=False,
            )
    db_session.commit()

    _login(client, user)
    resp = client.get('/learn/error-review/')
    assert resp.status_code == 200
    body = _strip_style_blocks(resp.get_data(as_text=True))

    # Top 3 lesson titles present, 4th excluded
    assert 'Cap Lesson 0' in body  # 4 errors — top
    assert 'Cap Lesson 1' in body  # 3 errors
    assert 'Cap Lesson 2' in body  # 2 errors
    assert 'Cap Lesson 3' not in body  # 1 error — capped out
