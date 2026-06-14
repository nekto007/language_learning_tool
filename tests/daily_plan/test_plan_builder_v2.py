"""Static daily-plan snapshot composition (``app/daily_plan/plan_builder.py``).

Tests cover:
- Tier-driven item count (calm=3, normal=4, intensive=5 baseline)
- SRS deck-quiz swap when first curriculum lesson is a card-type
- Grammar-prep insertion before final_test
- Warmup layout when final_test is the first curriculum lesson
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.plan_builder import build_required_snapshot
from app.daily_plan.linear.models import UserReadingPreference
from app.grammar_lab.models import GrammarTopic
from app.utils.db import db as real_db
from tests.conftest import unique_level_code


def _seed_due_srs_card(db_session, user_id: int) -> None:
    """Create one due REVIEW card so build_srs_item yields a non-None slot."""
    from app.srs.constants import CardState, DEFAULT_EASE_FACTOR
    from app.study.models import UserCardDirection, UserWord
    from app.words.models import CollectionWords

    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'pb_{suffix}', russian_word=f'pb_ru_{suffix}', level='A1',
    )
    db_session.add(word)
    db_session.flush()
    uw = UserWord(user_id=user_id, word_id=word.id)
    uw.status = 'review'
    db_session.add(uw)
    db_session.flush()
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    db_session.add(UserCardDirection(
        user_word_id=uw.id, direction='eng-rus',
        state=CardState.REVIEW.value, interval=5,
        ease_factor=DEFAULT_EASE_FACTOR, next_review=past,
    ))
    db_session.commit()


@pytest.fixture
def user_no_book(db_session):
    suffix = uuid.uuid4().hex[:10]
    u = User(
        username=f'pbv2_{suffix}',
        email=f'pbv2_{suffix}@example.com',
        active=True,
    )
    u.set_password('secret123')
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def book_with_chapter(db_session):
    """Minimal Book + Chapter so reading_item builder yields a real slot."""
    from app.books.models import Book, Chapter

    suffix = uuid.uuid4().hex[:6]
    book = Book(
        title=f'BookPB-{suffix}',
        slug=f'book-pb-{suffix}',
        author='Test Author',
        chapters_cnt=1,
        level='A1',
        is_published=True,
    )
    db_session.add(book)
    db_session.commit()
    chap = Chapter(
        book_id=book.id, chap_num=1, title='Ch1',
        words=10, text_raw='hello world',
    )
    db_session.add(chap)
    db_session.commit()
    return book


@pytest.fixture
def user_with_book(db_session, user_no_book, book_with_chapter):
    """User + reading preference pointing at the test book, selected yesterday
    so it's eligible to join required (mid-day picks defer to tomorrow)."""
    pref = UserReadingPreference(
        user_id=user_no_book.id, book_id=book_with_chapter.id,
        selected_at=datetime.now(timezone.utc).replace(tzinfo=None).replace(year=2025),
    )
    db_session.add(pref)
    db_session.commit()
    return user_no_book


def _make_module_with_lessons(
    db_session, level_order: int, lesson_types: list[str],
) -> tuple[CEFRLevel, Module, list[Lessons]]:
    code = unique_level_code()
    level = CEFRLevel(
        code=code, name=f'L-{code}', order=level_order,
    )
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id, number=1, title=f'M-{code}',
        description='', raw_content={},
    )
    db_session.add(module)
    db_session.commit()
    lessons = []
    for i, t in enumerate(lesson_types, start=1):
        lesson = Lessons(
            module_id=module.id, number=i, title=f'L{i}', type=t, content={},
        )
        db_session.add(lesson)
        lessons.append(lesson)
    db_session.commit()
    return level, module, lessons


class TestComposition:

    def test_calm_three_items_baseline(
        self, db_session, user_with_book, book_with_chapter,
    ):
        _seed_due_srs_card(db_session, user_with_book.id)
        _, _, _ = _make_module_with_lessons(
            db_session, level_order=1,
            lesson_types=['vocabulary', 'grammar', 'quiz'],
        )

        items = build_required_snapshot(user_with_book.id, 'calm', real_db)

        kinds = [it['kind'] for it in items]
        assert kinds == ['curriculum', 'srs', 'reading']

    def test_normal_four_items_baseline(
        self, db_session, user_with_book, book_with_chapter,
    ):
        _seed_due_srs_card(db_session, user_with_book.id)
        _, _, _ = _make_module_with_lessons(
            db_session, level_order=2,
            lesson_types=['vocabulary', 'grammar', 'quiz'],
        )

        items = build_required_snapshot(user_with_book.id, 'normal', real_db)

        kinds = [it['kind'] for it in items]
        assert kinds == ['curriculum', 'srs', 'reading', 'curriculum']
        # The two curriculum slots reference different lessons.
        c_ids = [it['data']['lesson_id'] for it in items if it['kind'] == 'curriculum']
        assert len(set(c_ids)) == 2

    def test_intensive_five_items_baseline(
        self, db_session, user_with_book, book_with_chapter,
    ):
        _seed_due_srs_card(db_session, user_with_book.id)
        _, _, _ = _make_module_with_lessons(
            db_session, level_order=3,
            lesson_types=['vocabulary', 'grammar', 'quiz'],
        )

        items = build_required_snapshot(user_with_book.id, 'intensive', real_db)

        kinds = [it['kind'] for it in items]
        assert kinds == ['curriculum', 'srs', 'reading', 'curriculum', 'curriculum']

    def test_no_reading_when_no_book_preference(self, db_session, user_no_book):
        """No UserReadingPreference → reading slot is dropped entirely."""
        _, _, _ = _make_module_with_lessons(
            db_session, level_order=4,
            lesson_types=['vocabulary'],
        )
        items = build_required_snapshot(user_no_book.id, 'calm', real_db)
        kinds = [it['kind'] for it in items]
        # Curriculum + SRS only; no reading.
        assert kinds[0] == 'curriculum'
        assert 'reading' not in kinds

    def test_empty_when_no_curriculum_available(self, db_session):
        """User on a level with no lessons → empty snapshot."""
        suffix = uuid.uuid4().hex[:10]
        u = User(
            username=f'empty_{suffix}',
            email=f'empty_{suffix}@example.com',
            active=True,
        )
        u.set_password('secret123')
        db_session.add(u)
        db_session.commit()

        items = build_required_snapshot(u.id, 'normal', real_db)
        assert items == []


class TestFinalTestLayout:

    def test_grammar_prep_inserted_before_final_test_in_normal(
        self, db_session, user_with_book, book_with_chapter,
    ):
        """final_test as 2nd curriculum (normal tier) → prep step before it."""
        _seed_due_srs_card(db_session, user_with_book.id)

        # Grammar topic for the module's grammar lesson.
        suffix = uuid.uuid4().hex[:6]
        topic = GrammarTopic(
            slug=f'topic-{suffix}',
            title=f'Topic {suffix}',
            title_ru=f'Тема {suffix}',
            level='A1',
            order=1,
            content={'introduction': 'hello'},
        )
        db_session.add(topic)
        db_session.commit()

        level, module, lessons = _make_module_with_lessons(
            db_session, level_order=5,
            lesson_types=['vocabulary', 'final_test', 'quiz'],
        )
        # Grammar lesson sits AFTER the final_test on the spine (higher number)
        # so the curriculum chain still picks vocabulary → final_test; the
        # grammar lesson is only used for topic resolution.
        grammar_lesson = Lessons(
            module_id=module.id, number=99, title='G', type='grammar',
            content={}, grammar_topic_id=topic.id,
        )
        db_session.add(grammar_lesson)
        db_session.commit()

        items = build_required_snapshot(user_with_book.id, 'normal', real_db)
        kinds = [it['kind'] for it in items]
        # Expected: curriculum (vocab) → srs → reading → grammar_review (prep) → curriculum (final_test)
        assert 'grammar_review' in kinds
        gr_idx = kinds.index('grammar_review')
        # The prep step sits immediately before the final_test.
        assert kinds[gr_idx + 1] == 'curriculum'
        assert items[gr_idx + 1]['lesson_type'] == 'final_test'
        # Prep step references the grammar topic.
        prep = items[gr_idx]
        assert prep['data']['topic_id'] == topic.id
        assert prep['data']['pre_final_test'] is True

    def test_final_test_first_warmup_layout(
        self, db_session, user_with_book, book_with_chapter,
    ):
        """final_test as 1st curriculum → SRS, prep, reading, FT order."""
        _seed_due_srs_card(db_session, user_with_book.id)

        suffix = uuid.uuid4().hex[:6]
        topic = GrammarTopic(
            slug=f'wtopic-{suffix}',
            title=f'WTopic {suffix}',
            title_ru=f'ВТема {suffix}',
            level='A1',
            order=1,
            content={'introduction': 'hello'},
        )
        db_session.add(topic)
        db_session.commit()

        level, module, lessons = _make_module_with_lessons(
            db_session, level_order=6,
            lesson_types=['final_test'],
        )
        # Grammar lesson sits after the final_test on the spine so the
        # curriculum chain still picks just final_test; the grammar lesson
        # is only used for topic resolution by _grammar_prep_item_dict.
        grammar_lesson = Lessons(
            module_id=module.id, number=99, title='G', type='grammar',
            content={}, grammar_topic_id=topic.id,
        )
        db_session.add(grammar_lesson)
        db_session.commit()

        items = build_required_snapshot(user_with_book.id, 'calm', real_db)
        kinds = [it['kind'] for it in items]
        # Warmup layout: SRS → grammar_review → reading → curriculum(FT).
        assert kinds == ['srs', 'grammar_review', 'reading', 'curriculum']
        assert items[-1]['lesson_type'] == 'final_test'
