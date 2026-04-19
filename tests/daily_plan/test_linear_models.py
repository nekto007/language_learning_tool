"""Smoke CRUD tests for linear-daily-plan SQLAlchemy models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.auth.models import User
from app.books.models import Book
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.linear.models import (
    GrammarTheoryView,
    QuizErrorLog,
    UserReadingPreference,
)
from app.grammar_lab.models import GrammarTopic


def _make_user(db_session) -> User:
    uid = uuid.uuid4().hex[:8]
    user = User(username=f'linear_{uid}', email=f'linear_{uid}@example.com', active=True)
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_book(db_session, level: str = 'B1') -> Book:
    uid = uuid.uuid4().hex[:8]
    book = Book(
        slug=f'book-{uid}',
        title=f'Linear Book {uid}',
        author='Author',
        chapters_cnt=1,
        lang='en',
        level=level,
    )
    db_session.add(book)
    db_session.commit()
    return book


def _make_lesson(db_session) -> Lessons:
    uid = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(code=uid, name='Beginner', description='desc', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='Module 1',
        description='desc',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Lesson 1',
        type='quiz',
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _make_grammar_topic(db_session) -> GrammarTopic:
    uid = uuid.uuid4().hex[:8]
    topic = GrammarTopic(
        slug=f'topic-{uid}',
        title=f'Topic {uid}',
        title_ru='Тема',
        level='B1',
        order=0,
        content={},
    )
    db_session.add(topic)
    db_session.commit()
    return topic


class TestUserReadingPreference:
    def test_create_and_read(self, db_session):
        user = _make_user(db_session)
        book = _make_book(db_session)
        pref = UserReadingPreference(user_id=user.id, book_id=book.id)
        db_session.add(pref)
        db_session.commit()

        loaded = db_session.get(UserReadingPreference, user.id)
        assert loaded is not None
        assert loaded.book_id == book.id
        assert loaded.selected_at is not None

    def test_update_book(self, db_session):
        user = _make_user(db_session)
        book_a = _make_book(db_session, level='A2')
        book_b = _make_book(db_session, level='B1')
        db_session.add(UserReadingPreference(user_id=user.id, book_id=book_a.id))
        db_session.commit()

        pref = db_session.get(UserReadingPreference, user.id)
        pref.book_id = book_b.id
        db_session.commit()

        reloaded = db_session.get(UserReadingPreference, user.id)
        assert reloaded.book_id == book_b.id

    def test_delete(self, db_session):
        user = _make_user(db_session)
        book = _make_book(db_session)
        db_session.add(UserReadingPreference(user_id=user.id, book_id=book.id))
        db_session.commit()

        pref = db_session.get(UserReadingPreference, user.id)
        db_session.delete(pref)
        db_session.commit()

        assert db_session.get(UserReadingPreference, user.id) is None


class TestQuizErrorLog:
    def test_create_with_payload(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        payload = {'question': 'pick the tense', 'answer': 'past', 'correct': 'present'}
        entry = QuizErrorLog(
            user_id=user.id,
            lesson_id=lesson.id,
            question_payload=payload,
        )
        db_session.add(entry)
        db_session.commit()

        loaded = db_session.get(QuizErrorLog, entry.id)
        assert loaded.user_id == user.id
        assert loaded.lesson_id == lesson.id
        assert loaded.question_payload == payload
        assert loaded.resolved_at is None
        assert loaded.answered_wrong_at is not None

    def test_mark_resolved(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        entry = QuizErrorLog(
            user_id=user.id,
            lesson_id=lesson.id,
            question_payload={'q': 'x'},
        )
        db_session.add(entry)
        db_session.commit()

        entry.resolved_at = datetime.now(timezone.utc)
        db_session.commit()

        reloaded = db_session.get(QuizErrorLog, entry.id)
        assert reloaded.resolved_at is not None

    def test_filter_unresolved(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        resolved = QuizErrorLog(
            user_id=user.id,
            lesson_id=lesson.id,
            question_payload={'q': '1'},
            resolved_at=datetime.now(timezone.utc),
        )
        pending = QuizErrorLog(
            user_id=user.id,
            lesson_id=lesson.id,
            question_payload={'q': '2'},
        )
        db_session.add_all([resolved, pending])
        db_session.commit()

        unresolved = (
            db_session.query(QuizErrorLog)
            .filter(
                QuizErrorLog.user_id == user.id,
                QuizErrorLog.resolved_at.is_(None),
            )
            .all()
        )
        assert len(unresolved) == 1
        assert unresolved[0].id == pending.id


class TestGrammarTheoryView:
    def test_create_and_read(self, db_session):
        user = _make_user(db_session)
        topic = _make_grammar_topic(db_session)
        lesson = _make_lesson(db_session)
        view = GrammarTheoryView(
            user_id=user.id,
            topic_id=topic.id,
            lesson_id=lesson.id,
        )
        db_session.add(view)
        db_session.commit()

        loaded = db_session.get(GrammarTheoryView, view.id)
        assert loaded is not None
        assert loaded.topic_id == topic.id
        assert loaded.lesson_id == lesson.id
        assert loaded.shown_at is not None

    def test_multiple_views_same_lesson(self, db_session):
        user = _make_user(db_session)
        topic = _make_grammar_topic(db_session)
        lesson = _make_lesson(db_session)
        for _ in range(3):
            db_session.add(GrammarTheoryView(
                user_id=user.id,
                topic_id=topic.id,
                lesson_id=lesson.id,
            ))
        db_session.commit()

        rows = (
            db_session.query(GrammarTheoryView)
            .filter_by(user_id=user.id, lesson_id=lesson.id)
            .all()
        )
        assert len(rows) == 3


class TestUserFeatureFlag:
    def test_use_linear_plan_defaults_false(self, db_session):
        user = _make_user(db_session)
        assert user.use_linear_plan is False

    def test_enable_linear_plan(self, db_session):
        user = _make_user(db_session)
        user.use_linear_plan = True
        db_session.commit()

        reloaded = db_session.get(User, user.id)
        assert reloaded.use_linear_plan is True
