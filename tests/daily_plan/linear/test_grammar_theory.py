"""Tests for ``app.daily_plan.linear.grammar_theory``.

Covers matching rules for the grammar-theory pull:

- ``content['topic']`` → ``GrammarTopic.title`` case-insensitive match,
  filtered by the lesson's module level.
- Multiple candidates at the same level resolve to the lowest
  ``GrammarTopic.order``.
- Missing hint / non-grammar lessons / wrong-level topics return None
  without raising.
- Revisiting the same grammar lesson does not create a duplicate
  ``GrammarTheoryView``.
- ``Lesson.grammar_topic_id`` is honoured as a direct link.
"""
from __future__ import annotations

import uuid

from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.linear.grammar_theory import get_theory_for_lesson
from app.daily_plan.linear.models import GrammarTheoryView
from app.grammar_lab.models import GrammarTopic
from app.utils.db import db as real_db


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'gtuser_{suffix}',
        email=f'gtuser_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_lesson(
    db_session,
    *,
    level_code: str = 'B1',
    level_order: int = 4,
    lesson_type: str = 'grammar',
    content: dict | None = None,
    grammar_topic_id: int | None = None,
) -> Lessons:
    level = CEFRLevel(code=_unique_code(), name=level_code, description='', order=level_order)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='M1',
        description='',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Grammar lesson',
        type=lesson_type,
        content=content or {},
        grammar_topic_id=grammar_topic_id,
    )
    # Store the canonical code on the level so matching uses the real value.
    level.code = level_code
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _make_topic(
    db_session,
    *,
    title: str,
    level: str = 'B1',
    order: int = 0,
    slug: str | None = None,
    title_ru: str | None = None,
) -> GrammarTopic:
    topic = GrammarTopic(
        slug=slug or f'{title.lower().replace(" ", "-")}-{uuid.uuid4().hex[:4]}',
        title=title,
        title_ru=title_ru or title,
        level=level,
        order=order,
        content={'introduction': f'Intro for {title}'},
    )
    db_session.add(topic)
    db_session.commit()
    return topic


class TestResolve:
    def test_matches_by_title_and_level(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(
            db_session,
            level_code='B1',
            content={'topic': 'Present Perfect'},
        )
        _make_topic(db_session, title='Past Simple', level='B1', order=0)
        present_perfect = _make_topic(
            db_session, title='Present Perfect', level='B1', order=5,
        )

        topic = get_theory_for_lesson(user.id, lesson, real_db, commit=True)

        assert topic is not None
        assert topic.id == present_perfect.id

    def test_match_is_case_insensitive(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(
            db_session,
            level_code='B1',
            content={'topic': 'present   perfect'.strip()},
        )
        topic = _make_topic(db_session, title='Present Perfect', level='B1')

        lesson.content = {'topic': 'PRESENT PERFECT'}
        db_session.add(lesson)
        db_session.commit()

        found = get_theory_for_lesson(user.id, lesson, real_db, commit=True)

        assert found is not None
        assert found.id == topic.id

    def test_wrong_level_is_ignored(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(
            db_session,
            level_code='A2',
            content={'topic': 'Present Perfect'},
        )
        _make_topic(db_session, title='Present Perfect', level='B1')

        topic = get_theory_for_lesson(user.id, lesson, real_db, commit=True)

        assert topic is None

    def test_multiple_candidates_picks_lowest_order(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(
            db_session,
            level_code='B1',
            content={'topic': 'Articles'},
        )
        second = _make_topic(db_session, title='Articles', level='B1', order=9)
        first = _make_topic(db_session, title='Articles', level='B1', order=1)

        topic = get_theory_for_lesson(user.id, lesson, real_db, commit=True)

        assert topic is not None
        assert topic.id == first.id
        assert topic.id != second.id

    def test_no_topic_hint_returns_none(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session, level_code='B1', content={})
        _make_topic(db_session, title='Something', level='B1')

        topic = get_theory_for_lesson(user.id, lesson, real_db, commit=True)

        assert topic is None

    def test_non_grammar_lesson_returns_none(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(
            db_session,
            level_code='B1',
            lesson_type='quiz',
            content={'topic': 'Present Perfect'},
        )
        _make_topic(db_session, title='Present Perfect', level='B1')

        topic = get_theory_for_lesson(user.id, lesson, real_db, commit=True)

        assert topic is None

    def test_foreign_key_takes_precedence(self, db_session):
        """When grammar_topic_id is set, the hint is ignored."""
        user = _make_user(db_session)
        linked = _make_topic(db_session, title='Linked Topic', level='B1', order=0)
        lesson = _make_lesson(
            db_session,
            level_code='B1',
            content={'topic': 'Unrelated Topic'},
            grammar_topic_id=linked.id,
        )

        topic = get_theory_for_lesson(user.id, lesson, real_db, commit=True)

        assert topic is not None
        assert topic.id == linked.id


class TestViewLogging:
    def test_first_visit_creates_view_row(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(
            db_session,
            level_code='B1',
            content={'topic': 'Present Perfect'},
        )
        topic = _make_topic(db_session, title='Present Perfect', level='B1')

        assert (
            db_session.query(GrammarTheoryView)
            .filter_by(user_id=user.id, lesson_id=lesson.id)
            .count()
            == 0
        )

        get_theory_for_lesson(user.id, lesson, real_db, commit=True)

        rows = (
            db_session.query(GrammarTheoryView)
            .filter_by(user_id=user.id, lesson_id=lesson.id)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].topic_id == topic.id
        assert rows[0].shown_at is not None

    def test_revisit_does_not_duplicate(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(
            db_session,
            level_code='B1',
            content={'topic': 'Present Perfect'},
        )
        _make_topic(db_session, title='Present Perfect', level='B1')

        get_theory_for_lesson(user.id, lesson, real_db, commit=True)
        get_theory_for_lesson(user.id, lesson, real_db, commit=True)
        get_theory_for_lesson(user.id, lesson, real_db, commit=True)

        assert (
            db_session.query(GrammarTheoryView)
            .filter_by(user_id=user.id, lesson_id=lesson.id)
            .count()
            == 1
        )

    def test_no_match_no_view(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(
            db_session,
            level_code='B1',
            content={'topic': 'Non Existent'},
        )

        topic = get_theory_for_lesson(user.id, lesson, real_db, commit=True)

        assert topic is None
        assert (
            db_session.query(GrammarTheoryView)
            .filter_by(user_id=user.id, lesson_id=lesson.id)
            .count()
            == 0
        )

    def test_different_users_get_independent_rows(self, db_session):
        user_a = _make_user(db_session)
        user_b = _make_user(db_session)
        lesson = _make_lesson(
            db_session,
            level_code='B1',
            content={'topic': 'Present Perfect'},
        )
        _make_topic(db_session, title='Present Perfect', level='B1')

        get_theory_for_lesson(user_a.id, lesson, real_db, commit=True)
        get_theory_for_lesson(user_b.id, lesson, real_db, commit=True)

        assert (
            db_session.query(GrammarTheoryView)
            .filter_by(lesson_id=lesson.id)
            .count()
            == 2
        )


class TestEdgeCases:
    def test_none_lesson_returns_none(self, db_session):
        user = _make_user(db_session)

        assert get_theory_for_lesson(user.id, None, real_db) is None

    def test_non_string_topic_hint_returns_none(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session, content={'topic': 42})
        _make_topic(db_session, title='Present Perfect', level='B1')

        assert get_theory_for_lesson(user.id, lesson, real_db) is None

    def test_empty_string_topic_hint_returns_none(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session, content={'topic': '   '})
        _make_topic(db_session, title='Present Perfect', level='B1')

        assert get_theory_for_lesson(user.id, lesson, real_db) is None
