"""Daily-plan snapshot v2: persistence, roll-over, overlay completion.

Tests cover:
- Fresh snapshot is written to ``DailyPlanLog.plan_json``
- Existing snapshot is returned unchanged
- Roll-over from yesterday triggers when ``has_learning_activity(yesterday)`` is False
- Roll-over does NOT trigger when yesterday had any activity
- Overlay marks curriculum item completed when its lesson was finished today
- Feature flag honours SiteSettings default OFF
"""
from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest
from freezegun import freeze_time

from app.achievements.models import StreakEvent
from app.auth.models import User
from app.books.models import Book, Chapter, UserChapterProgress
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.models import DailyPlanLog
from app.daily_plan.snapshot import (
    SNAPSHOT_VERSION,
    overlay_completion,
    resolve_snapshot_for_today,
)
from app.utils.db import db as real_db
from tests.conftest import unique_level_code
from tests.support_dates import study_today


@pytest.fixture
def user(db_session):
    suffix = uuid.uuid4().hex[:10]
    u = User(
        username=f'snap2_{suffix}',
        email=f'snap2_{suffix}@example.com',
        active=True,
    )
    u.set_password('secret123')
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def vocabulary_lesson(db_session):
    code = unique_level_code()
    level = CEFRLevel(
        code=code, name=f'L-{code}', order=1,
    )
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id, number=1, title='M1', description='', raw_content={},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id, number=1, title='L1', type='vocabulary', content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestResolveSnapshot:

    def test_creates_fresh_snapshot_for_today(
        self, db_session, user, vocabulary_lesson,
    ):
        today = study_today()
        snap = resolve_snapshot_for_today(user.id, today, real_db)

        assert snap['version'] == SNAPSHOT_VERSION
        assert snap['date'] == today.isoformat()
        assert snap['tier'] in ('calm', 'normal', 'intensive')
        assert snap['rolled_over_from'] is None
        assert isinstance(snap['items'], list)
        # Persisted to DailyPlanLog.plan_json.
        row = db_session.query(DailyPlanLog).filter_by(
            user_id=user.id, plan_date=today,
        ).first()
        assert row is not None
        assert row.plan_json == snap

    def test_returns_existing_snapshot(self, db_session, user, vocabulary_lesson):
        today = study_today()
        # First call writes.
        snap1 = resolve_snapshot_for_today(user.id, today, real_db)
        real_db.session.commit()
        # Second call returns identical payload.
        snap2 = resolve_snapshot_for_today(user.id, today, real_db)
        assert snap2 == snap1


class TestRollover:

    def test_rollover_copies_yesterday_on_zero_activity(
        self, db_session, user, vocabulary_lesson,
    ):
        today = study_today()
        yesterday = today - timedelta(days=1)

        # Pre-seed yesterday's snapshot with one item.
        prior = {
            'version': SNAPSHOT_VERSION,
            'date': yesterday.isoformat(),
            'tier': 'calm',
            'rolled_over_from': None,
            'items': [{
                'id': 'curriculum:lesson:999',
                'section': 'required',
                'kind': 'curriculum',
                'title': 'Yesterday lesson',
                'subtitle': None,
                'lesson_type': 'vocabulary',
                'eta_minutes': 8,
                'url': '/learn/999/',
                'completion_signal': 'lesson_completed',
                'data': {'lesson_id': 999},
            }],
        }
        db_session.add(DailyPlanLog(
            user_id=user.id, plan_date=yesterday, plan_json=prior,
        ))
        db_session.commit()

        # No learning activity for yesterday → today rolls over.
        snap = resolve_snapshot_for_today(user.id, today, real_db)

        assert snap['rolled_over_from'] == yesterday.isoformat()
        assert snap['date'] == today.isoformat()
        # Items copied verbatim.
        assert snap['items'] == prior['items']

    def test_no_rollover_when_yesterday_had_activity(
        self, db_session, user, vocabulary_lesson,
    ):
        today = study_today()
        yesterday = today - timedelta(days=1)

        prior = {
            'version': SNAPSHOT_VERSION,
            'date': yesterday.isoformat(),
            'tier': 'calm',
            'rolled_over_from': None,
            'items': [{
                'id': 'curriculum:lesson:888',
                'section': 'required',
                'kind': 'curriculum',
                'title': 'Yesterday lesson',
                'subtitle': None,
                'lesson_type': 'vocabulary',
                'eta_minutes': 8,
                'url': '/learn/888/',
                'completion_signal': 'lesson_completed',
                'data': {'lesson_id': 888},
            }],
        }
        db_session.add(DailyPlanLog(
            user_id=user.id, plan_date=yesterday, plan_json=prior,
        ))
        # Activity yesterday — any LessonProgress in the user-local day window.
        from app.utils.time_utils import day_to_naive_utc
        y_start = day_to_naive_utc(user.id, real_db, days_ahead=-1)
        db_session.add(LessonProgress(
            user_id=user.id, lesson_id=vocabulary_lesson.id,
            status='in_progress',
            last_activity=y_start + timedelta(hours=10),
        ))
        db_session.commit()

        snap = resolve_snapshot_for_today(user.id, today, real_db)

        assert snap['rolled_over_from'] is None
        # Items reflect today's fresh build, not yesterday's copy.
        assert all(it.get('id') != 'curriculum:lesson:888' for it in snap['items'])

    def test_rollover_activity_window_uses_requested_plan_date(
        self, db_session, user, vocabulary_lesson,
    ):
        user.timezone = 'UTC'
        today = study_today() - timedelta(days=10)
        yesterday = today - timedelta(days=1)

        prior = {
            'version': SNAPSHOT_VERSION,
            'date': yesterday.isoformat(),
            'tier': 'calm',
            'rolled_over_from': None,
            'items': [{
                'id': 'curriculum:lesson:777',
                'section': 'required',
                'kind': 'curriculum',
                'title': 'Old requested-date lesson',
                'subtitle': None,
                'lesson_type': 'vocabulary',
                'eta_minutes': 8,
                'url': '/learn/777/',
                'completion_signal': 'lesson_completed',
                'data': {'lesson_id': 777},
            }],
        }
        db_session.add(DailyPlanLog(
            user_id=user.id, plan_date=yesterday, plan_json=prior,
        ))
        db_session.add(LessonProgress(
            user_id=user.id, lesson_id=vocabulary_lesson.id,
            status='in_progress',
            last_activity=datetime.combine(yesterday, time(hour=10)),
        ))
        db_session.commit()

        snap = resolve_snapshot_for_today(user.id, today, real_db)

        assert snap['rolled_over_from'] is None
        assert all(it.get('id') != 'curriculum:lesson:777' for it in snap['items'])


class TestRolloverStudyDayBoundary:
    """DP-002 / DP-009: окно roll-over якорится в 02:00, не в полночь.

    ``plan_date`` приходит уже учебной датой (`get_user_local_date`), поэтому
    окно `[дата 00:00, дата+1 00:00)` было сдвинуто на два часа: занятие в
    00:30 роняло снапшот дважды (день «пропущен», хотя юзер занимался);
    занятие позапрошлой ночью, наоборот, гасило законный перенос.
    """

    def _seed_yesterday(self, db_session, user, yesterday, lesson_marker):
        prior = {
            'version': SNAPSHOT_VERSION,
            'date': yesterday.isoformat(),
            'tier': 'calm',
            'rolled_over_from': None,
            'items': [{
                'id': f'curriculum:lesson:{lesson_marker}',
                'section': 'required',
                'kind': 'curriculum',
                'title': 'Yesterday lesson',
                'subtitle': None,
                'lesson_type': 'vocabulary',
                'eta_minutes': 8,
                'url': f'/learn/{lesson_marker}/',
                'completion_signal': 'lesson_completed',
                'data': {'lesson_id': lesson_marker},
            }],
        }
        db_session.add(DailyPlanLog(
            user_id=user.id, plan_date=yesterday, plan_json=prior,
        ))
        return prior

    def test_window_starts_at_learning_day_hour(self, db_session, user):
        from app.daily_plan.snapshot import _local_date_start_naive_utc
        from app.utils.time_utils import LEARNING_DAY_START_HOUR

        user.timezone = 'UTC'
        db_session.commit()

        plan_date = study_today() - timedelta(days=10)
        start = _local_date_start_naive_utc(user.id, plan_date, real_db)

        assert start == datetime.combine(
            plan_date, time(hour=LEARNING_DAY_START_HOUR),
        )

    def test_after_midnight_activity_belongs_to_that_study_day(
        self, db_session, user, vocabulary_lesson,
    ):
        """Занятие в 01:00 календарного «завтра» — это ещё вчерашний день."""
        user.timezone = 'UTC'
        today = study_today() - timedelta(days=10)
        yesterday = today - timedelta(days=1)
        self._seed_yesterday(db_session, user, yesterday, 666)
        db_session.add(LessonProgress(
            user_id=user.id, lesson_id=vocabulary_lesson.id,
            status='in_progress',
            # 01:00 на календарной дате `today` — внутри учебного дня
            # `yesterday` (02:00 вчера … 02:00 сегодня).
            last_activity=datetime.combine(today, time(hour=1)),
        ))
        db_session.commit()

        snap = resolve_snapshot_for_today(user.id, today, real_db)

        assert snap['rolled_over_from'] is None
        assert all(it.get('id') != 'curriculum:lesson:666' for it in snap['items'])

    def test_activity_before_study_day_start_does_not_block_rollover(
        self, db_session, user, vocabulary_lesson,
    ):
        """Занятие в 01:00 вчерашней календарной даты — это позавчера."""
        user.timezone = 'UTC'
        today = study_today() - timedelta(days=10)
        yesterday = today - timedelta(days=1)
        prior = self._seed_yesterday(db_session, user, yesterday, 555)
        db_session.add(LessonProgress(
            user_id=user.id, lesson_id=vocabulary_lesson.id,
            status='in_progress',
            last_activity=datetime.combine(yesterday, time(hour=1)),
        ))
        db_session.commit()

        snap = resolve_snapshot_for_today(user.id, today, real_db)

        assert snap['rolled_over_from'] == yesterday.isoformat()
        assert snap['items'] == prior['items']

    def test_rollover_does_not_fire_twice_for_the_same_day(
        self, db_session, user, vocabulary_lesson,
    ):
        """Повторный resolve возвращает уже записанный снапшот, не переносит заново."""
        user.timezone = 'UTC'
        today = study_today() - timedelta(days=10)
        yesterday = today - timedelta(days=1)
        self._seed_yesterday(db_session, user, yesterday, 444)
        db_session.commit()

        first = resolve_snapshot_for_today(user.id, today, real_db)
        real_db.session.commit()
        second = resolve_snapshot_for_today(user.id, today, real_db)
        real_db.session.commit()

        assert first['rolled_over_from'] == yesterday.isoformat()
        assert second == first
        rows = DailyPlanLog.query.filter_by(
            user_id=user.id, plan_date=today,
        ).all()
        assert len(rows) == 1


class TestOverlayCompletion:

    def test_curriculum_completed_today_marks_item_done(
        self, db_session, user, vocabulary_lesson,
    ):
        today = study_today()
        snap = resolve_snapshot_for_today(user.id, today, real_db)
        real_db.session.commit()

        # Find the curriculum item and complete its lesson today.
        cur = next(it for it in snap['items'] if it['kind'] == 'curriculum')
        lesson_id = cur['data']['lesson_id']

        from app.utils.time_utils import day_to_naive_utc
        today_start = day_to_naive_utc(user.id, real_db, days_ahead=0)
        db_session.add(LessonProgress(
            user_id=user.id, lesson_id=lesson_id,
            status='completed', score=100.0,
            last_activity=today_start + timedelta(hours=10),
            completed_at=today_start + timedelta(hours=10),
        ))
        db_session.commit()

        overlaid = overlay_completion(user.id, snap, real_db)
        cur_o = next(it for it in overlaid if it['kind'] == 'curriculum')
        assert cur_o['completed'] is True
        assert cur_o['url'] is None  # CTA hidden when done
        assert cur_o['eta_minutes'] == 0
        # Other slots remain uncompleted (no SRS/reading activity today).
        non_cur = [it for it in overlaid if it['kind'] != 'curriculum']
        assert all(not it.get('completed') for it in non_cur)

    def test_reading_item_removed_when_book_finished(
        self, db_session, user,
    ):
        book = Book(
            title='Snapshot Done Book',
            author='A',
            level='A1',
            chapters_cnt=2,
            is_published=True,
            # Without public_domain the DP-033 unreachable-book drop removes the
            # item first, and this test would pass with _is_finished_reading_book
            # deleted entirely.
            rights_status='public_domain',
        )
        db_session.add(book)
        db_session.flush()
        chapters = [
            Chapter(
                book_id=book.id,
                chap_num=idx,
                title=f'Ch {idx}',
                words=10,
                text_raw='text',
            )
            for idx in (1, 2)
        ]
        db_session.add_all(chapters)
        db_session.flush()
        for chapter in chapters:
            db_session.add(UserChapterProgress(
                user_id=user.id,
                chapter_id=chapter.id,
                offset_pct=1.0,
            ))
        db_session.commit()

        snap = {
            'version': SNAPSHOT_VERSION,
            'date': study_today().isoformat(),
            'items': [{
                'id': f'reading:book:{book.id}',
                'section': 'required',
                'kind': 'reading',
                'title': book.title,
                'subtitle': 'Норма дня — 5 мин',
                'lesson_type': None,
                'eta_minutes': 5,
                'url': f'/read/{book.id}',
                'completed': False,
                'completion_signal': 'reading_gate',
                'data': {'book_id': book.id},
            }],
        }

        overlaid = overlay_completion(user.id, snap, real_db)

        assert overlaid == []


# Локальное время == UTC, поэтому 00:30 попадает ровно в полосу до 02:00.
# Учебный день при этом ещё вчерашний, 14 сентября: он закроется в 02:00.
GRAMMAR_NIGHT = '2026-09-15 00:30:00'


class TestGrammarPracticeStudyDayWindow:
    """DP-009: окно `_grammar_topic_practiced_today` якорится в 02:00.

    Функция получает **учебную** дату, но строила окно от календарной
    полуночи — на два часа раньше. Второй сигнал (курсовой grammar-урок)
    фильтруется по `LessonAttempt.completed_at`, реальному моменту, поэтому
    урок, сданный в 01:00 локального времени, выпадал из своего же учебного
    дня (required-пункт не закрыть, `day_secured` недостижим) и попадал в
    следующий (день без работы закрывался чужой попыткой).

    Часы заморожены: предмет теста — полоса 00:00-02:00, и он не вправе
    зависеть от того, в какой час суток запустили прогон. Зона юзера — UTC,
    поэтому локальное время равно замороженному, как в соседних стражах
    учебного дня (`tests/daily_plan/test_study_day_readers.py`).
    """

    @pytest.fixture
    def grammar_lesson(self, db_session):
        from app.grammar_lab.models import GrammarTopic

        suffix = uuid.uuid4().hex[:10]
        topic = GrammarTopic(
            slug=f'snap2-topic-{suffix}', title='Topic', title_ru='Тема',
            level='A1', order=1, content={},
        )
        db_session.add(topic)
        db_session.commit()
        code = unique_level_code()
        level = CEFRLevel(code=code, name=f'L-{code}', order=1)
        db_session.add(level)
        db_session.commit()
        module = Module(
            level_id=level.id, number=1, title='M-gram', description='',
            raw_content={},
        )
        db_session.add(module)
        db_session.commit()
        lesson = Lessons(
            module_id=module.id, number=1, title='Gram', type='grammar',
            content={}, grammar_topic_id=topic.id,
        )
        db_session.add(lesson)
        db_session.commit()
        return lesson

    @pytest.fixture
    def utc_user(self, db_session, user):
        user.timezone = 'UTC'
        db_session.commit()
        return user

    def _attempt(self, db_session, user, lesson, completed_at_utc):
        from app.curriculum.models import LessonAttempt

        db_session.add(LessonAttempt(
            user_id=user.id, lesson_id=lesson.id, attempt_number=1,
            completed_at=completed_at_utc, score=100.0, passed=True,
        ))
        db_session.commit()

    @freeze_time(GRAMMAR_NIGHT)
    def test_lesson_finished_after_midnight_closes_its_own_study_day(
        self, db_session, utc_user, grammar_lesson,
    ):
        from app.daily_plan.snapshot import _grammar_topic_practiced_today

        # 00:30 15 сентября — это ещё учебный день 14 сентября, он закроется
        # в 02:00. Календарное окно [14 сентября 00:00, 15 сентября 00:00)
        # эту попытку теряло.
        self._attempt(
            db_session, utc_user, grammar_lesson,
            datetime(2026, 9, 15, 0, 30),
        )

        assert _grammar_topic_practiced_today(
            utc_user.id, grammar_lesson.grammar_topic_id,
            grammar_lesson.module_id, real_db,
        ) is True

    @freeze_time(GRAMMAR_NIGHT)
    def test_previous_study_day_attempt_does_not_close_today(
        self, db_session, utc_user, grammar_lesson,
    ):
        from app.daily_plan.snapshot import _grammar_topic_practiced_today

        # 00:30 14 сентября — календарная дата текущего учебного дня, но сам
        # день тогда ещё не начался (старт в 02:00): это учебный день
        # 13 сентября. Календарное окно засчитывало эту попытку сегодняшнему.
        self._attempt(
            db_session, utc_user, grammar_lesson,
            datetime(2026, 9, 14, 0, 30),
        )

        assert _grammar_topic_practiced_today(
            utc_user.id, grammar_lesson.grammar_topic_id,
            grammar_lesson.module_id, real_db,
        ) is False


# ── Кластер B фазы 2: заморозка снапшота ────────────────────────────────────
#
# Снапшот замораживает состав required на учебный день, а мир под ним живёт:
# админ удаляет урок (`DP-005`), пользователь чистит колоды (`DP-044`),
# карточки повторяются, но их счётчик заморожен на моменте сборки (`DP-041`).
# Первые две — про незакрываемый день, третья — про мёртвый прогресс «X из N».


def _snapshot_of(items):
    return {
        'version': SNAPSHOT_VERSION,
        'date': study_today().isoformat(),
        'tier': 'normal',
        'rolled_over_from': None,
        'items': items,
    }


def _curriculum_item(lesson_id, item_id='curriculum:lesson'):
    return {
        'id': item_id,
        'section': 'required',
        'kind': 'curriculum',
        'title': 'Урок',
        'subtitle': None,
        'lesson_type': 'vocabulary',
        'eta_minutes': 10,
        'url': f'/curriculum/lesson/{lesson_id}',
        'completion_signal': 'lesson_completed',
        'data': {'lesson_id': lesson_id},
    }


def _day_secured(user_id, overlaid):
    """day_secured ровно так, как его считает API: по составу required."""
    from app.daily_plan.service import compute_day_secured_from_activity

    plan = {
        'required': overlaid,
        '_plan_meta': {'effective_mode': 'unified', 'user_id': user_id},
        'day_secured': False,
    }
    completion = {it['id']: bool(it.get('completed')) for it in overlaid}
    return compute_day_secured_from_activity(plan, completion)


class TestDeletedLessonSelfHeal:
    """DP-005: урок, удалённый админом среди дня, обязан покинуть required.

    Пункт ведёт в 404, `_curriculum_lesson_done_today` для несуществующей
    строки навсегда False, `skip-lesson` отбивает id как `invalid_lesson` —
    штатного обхода нет, и день не закрывается никаким объёмом работы.
    """

    def test_deleted_lesson_drops_out_of_required(
        self, db_session, user, vocabulary_lesson,
    ):
        snap = _snapshot_of([_curriculum_item(vocabulary_lesson.id)])
        assert [it['id'] for it in overlay_completion(user.id, snap, real_db)] == [
            'curriculum:lesson',
        ]

        db_session.delete(vocabulary_lesson)
        db_session.commit()

        assert overlay_completion(user.id, snap, real_db) == []

    def test_day_closes_on_the_remaining_required(
        self, db_session, user, vocabulary_lesson,
    ):
        """Соседний выполненный пункт закрывает день, когда мёртвый выброшен."""
        alive = _curriculum_item(vocabulary_lesson.id, item_id='curriculum:alive')
        doomed = _curriculum_item(vocabulary_lesson.id + 10_000, 'curriculum:doomed')
        snap = _snapshot_of([alive, doomed])

        from app.utils.time_utils import day_to_naive_utc
        today_start = day_to_naive_utc(user.id, real_db, days_ahead=0)
        db_session.add(LessonProgress(
            user_id=user.id, lesson_id=vocabulary_lesson.id,
            status='completed', score=100.0,
            last_activity=today_start + timedelta(hours=9),
            completed_at=today_start + timedelta(hours=9),
        ))
        db_session.commit()

        overlaid = overlay_completion(user.id, snap, real_db)
        assert [it['id'] for it in overlaid] == ['curriculum:alive']
        assert _day_secured(user.id, overlaid) is True

    def test_completed_item_keeps_its_credit(
        self, db_session, user, vocabulary_lesson,
    ):
        """Выполненный до удаления пункт остаётся — дроп не отбирает кредит.

        Сигнал берётся из `StreakEvent`, строку урока он не трогает, поэтому
        completed=True переживает удаление и пункт обязан уцелеть.
        """
        from app.daily_plan.linear.xp import (
            LINEAR_XP_EVENT_TYPE,
            get_linear_event_local_date,
        )

        lesson_id = vocabulary_lesson.id
        db_session.add(StreakEvent(
            user_id=user.id,
            event_type=LINEAR_XP_EVENT_TYPE,
            event_date=get_linear_event_local_date(user.id, real_db),
            details={
                'source': 'linear_curriculum_vocabulary',
                'lesson_id': str(lesson_id),
            },
        ))
        db_session.delete(vocabulary_lesson)
        db_session.commit()

        overlaid = overlay_completion(user.id, _snapshot_of([
            _curriculum_item(lesson_id),
        ]), real_db)
        assert [it['id'] for it in overlaid] == ['curriculum:lesson']
        assert overlaid[0]['completed'] is True

    def test_item_without_lesson_id_is_dropped(self, db_session, user):
        """Пункт без разрешимого lesson_id так же неисполним навсегда."""
        broken = _curriculum_item(1)
        broken['data'] = {}
        assert overlay_completion(user.id, _snapshot_of([broken]), real_db) == []

    def test_live_lesson_survives(self, db_session, user, vocabulary_lesson):
        """Страж на нерегрессию: живой урок из required не исчезает."""
        overlaid = overlay_completion(user.id, _snapshot_of([
            _curriculum_item(vocabulary_lesson.id),
        ]), real_db)
        assert [it['id'] for it in overlaid] == ['curriculum:lesson']
        assert overlaid[0]['completed'] is False


def _deck_quiz_item(deck_word_count=3):
    return {
        'id': 'srs:deck_quiz',
        'section': 'required',
        'kind': 'srs',
        'title': f'Квиз по словам — {deck_word_count}',
        'subtitle': None,
        'lesson_type': 'quiz',
        'eta_minutes': 8,
        'url': '/study/quiz/linear-plan?source=linear_plan_deck_quiz&limit=3',
        'completion_signal': 'srs_xp_earned',
        'data': {
            'mode': 'deck_quiz',
            'source': 'linear_plan_deck_quiz',
            'deck_word_count': deck_word_count,
            'word_limit': deck_word_count,
            'goal_total': deck_word_count,
        },
    }


@pytest.fixture
def deck_with_words(db_session, user):
    from app.study.models import QuizDeck, QuizDeckWord

    deck = QuizDeck(title='Колода', description='', user_id=user.id, is_public=False)
    db_session.add(deck)
    db_session.flush()
    for i in range(3):
        db_session.add(QuizDeckWord(
            deck_id=deck.id,
            custom_english=f'word {i}',
            custom_russian=f'слово {i}',
            order_index=i,
        ))
    db_session.commit()
    return deck


class TestDeckQuizWordsGoneSelfHeal:
    """DP-044: гейт «есть ли слова в колодах» переживал только сборку.

    Удаление колоды среди дня оставляло required-квиз, генератор которого
    отдаёт ноль вопросов, — собственный сигнал завершения не мог сработать
    никогда.
    """

    def test_slot_survives_while_decks_have_words(self, db_session, user, deck_with_words):
        overlaid = overlay_completion(user.id, _snapshot_of([_deck_quiz_item()]), real_db)
        assert [it['id'] for it in overlaid] == ['srs:deck_quiz']
        assert overlaid[0]['completed'] is False

    def test_emptied_decks_drop_the_slot(self, db_session, user, deck_with_words):
        from app.study.models import QuizDeckWord

        snap = _snapshot_of([_deck_quiz_item()])
        assert overlay_completion(user.id, snap, real_db) != []

        db_session.query(QuizDeckWord).filter_by(deck_id=deck_with_words.id).delete()
        db_session.commit()

        assert overlay_completion(user.id, snap, real_db) == []

    def test_day_closes_after_the_dead_quiz_is_dropped(
        self, db_session, user, vocabulary_lesson, deck_with_words,
    ):
        from app.study.models import QuizDeckWord

        from app.utils.time_utils import day_to_naive_utc
        today_start = day_to_naive_utc(user.id, real_db, days_ahead=0)
        db_session.add(LessonProgress(
            user_id=user.id, lesson_id=vocabulary_lesson.id,
            status='completed', score=100.0,
            last_activity=today_start + timedelta(hours=9),
            completed_at=today_start + timedelta(hours=9),
        ))
        db_session.query(QuizDeckWord).filter_by(deck_id=deck_with_words.id).delete()
        db_session.commit()

        snap = _snapshot_of([
            _curriculum_item(vocabulary_lesson.id, item_id='curriculum:alive'),
            _deck_quiz_item(),
        ])
        overlaid = overlay_completion(user.id, snap, real_db)
        assert [it['id'] for it in overlaid] == ['curriculum:alive']
        assert _day_secured(user.id, overlaid) is True

    def test_srs_global_is_not_touched_by_the_deck_gate(self, db_session, user):
        """Обычный `srs:global` колод не требует и дропу не подлежит."""
        item = _srs_global_item()
        overlaid = overlay_completion(user.id, _snapshot_of([item]), real_db)
        assert [it['id'] for it in overlaid] == ['srs:global']


def _srs_global_item(**data_overrides):
    data = {
        'new_show': 4,
        'learning_due': 2,
        'learning_show': 2,
        'review_show': 18,
        'total_show': 24,
        'new_pending': 10,
        'review_due': 18,
        'overdue_reviews': 7,
        'new_today': 0,
        'reviews_today': 0,
        'remaining_new': 4,
        'remaining_reviews': 20,
        'srs_tier': 'normal',
        'reason_hint': None,
        'goal_total': 24,
    }
    data.update(data_overrides)
    return {
        'id': 'srs:global',
        'section': 'required',
        'kind': 'srs',
        'title': 'Повторение слов — 24',
        'subtitle': '4 новых · 18 на повтор',
        'lesson_type': None,
        'eta_minutes': 8,
        'url': '/study/cards?source=linear_plan&from=linear_plan&slot=srs',
        'completion_signal': 'srs_xp_earned',
        'data': data,
    }


def _reviewed_card_today(db_session, user, *, first_reviewed_days_ago=3):
    """Карточка, повторённая сегодня и впервые увиденная раньше.

    `count_reviews_today` сознательно не считает карточки, впервые увиденные
    сегодня (E-023), поэтому `first_reviewed` обязан быть в прошлом.
    """
    from app.study.models import UserCardDirection, UserWord
    from app.utils.time_utils import day_to_naive_utc
    from app.words.models import CollectionWords

    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(english_word=f'w{suffix}', russian_word=f'с{suffix}')
    db_session.add(word)
    db_session.flush()
    user_word = UserWord(user_id=user.id, word_id=word.id)
    user_word.srs_excluded = False
    db_session.add(user_word)
    db_session.flush()
    today_start = day_to_naive_utc(user.id, real_db, days_ahead=0)
    db_session.add(UserCardDirection(
        user_word_id=user_word.id,
        direction='eng-rus',
        first_reviewed=today_start - timedelta(days=first_reviewed_days_ago),
        last_reviewed=today_start + timedelta(hours=6),
    ))
    db_session.commit()


class TestFrozenSrsCountersAreRefreshed:
    """DP-041: замерзал не только знаменатель, но и числитель.

    `goal_total` заморожен сознательно («12 из 30» не должно превращаться в
    «12 из 18»), а `reviews_today`/`new_today` — живой прогресс дня: шаблон
    прячет весь блок при нуле, поэтому каптион «X из N» не рендерился вовсе.
    """

    def test_live_review_count_reaches_the_overlay(self, db_session, user):
        _reviewed_card_today(db_session, user)

        overlaid = overlay_completion(user.id, _snapshot_of([_srs_global_item()]), real_db)
        data = overlaid[0]['data']
        assert data['reviews_today'] == 1, 'числитель обязан быть живым'
        assert data['goal_total'] == 24, 'знаменатель заморожен на день — не трогать'

    def test_composition_fields_stay_frozen(self, db_session, user):
        _reviewed_card_today(db_session, user)

        overlaid = overlay_completion(user.id, _snapshot_of([_srs_global_item()]), real_db)
        data = overlaid[0]['data']
        assert data['total_show'] == 24
        assert data['new_show'] == 4
        assert data['review_show'] == 18
        assert overlaid[0]['title'] == 'Повторение слов — 24'

    def test_snapshot_payload_is_not_mutated(self, db_session, user):
        """Снапшот — это `DailyPlanLog.plan_json`; править его на месте нельзя."""
        _reviewed_card_today(db_session, user)

        snap = _snapshot_of([_srs_global_item()])
        overlay_completion(user.id, snap, real_db)
        assert snap['items'][0]['data']['reviews_today'] == 0

    def test_deck_quiz_gets_no_card_counters(self, db_session, user, deck_with_words):
        """У квиза свои числа — счётчики карточек ему приписывать нечего."""
        _reviewed_card_today(db_session, user)

        overlaid = overlay_completion(user.id, _snapshot_of([_deck_quiz_item()]), real_db)
        data = overlaid[0]['data']
        assert 'reviews_today' not in data
        assert data['word_limit'] == 3


class TestRolledReadingTargetIsRefreshed:
    """DP-049: a rolled snapshot must use today's reading target everywhere."""

    @freeze_time('2026-09-04 12:00:00')
    def test_target_progress_and_subtitle_move_together(
        self, user, monkeypatch,
    ):
        from app.books import reading_session
        from app.daily_plan import snapshot as snapshot_mod

        monkeypatch.setattr(
            reading_session, 'get_book_reading_seconds_today',
            lambda *_args, **_kwargs: 420,
        )

        frozen = {
            'id': 'reading:book:77',
            'kind': 'reading',
            'subtitle': 'Глава 3 · Old title · Норма дня — 5 мин',
            'eta_minutes': 5,
            'data': {
                'book_id': 77,
                'current_chapter_num': 3,
                'current_chapter_title': 'Old title',
                'time_spent_seconds': 60,
                'gate_seconds': 300,
                'gate_reached': False,
            },
        }
        # Item 14: the target is the learner's own goal (10 min here), no more
        # day-of-month alternation; a goal raised mid-day must reach the snapshot.
        from app.study.models import StudySettings
        real_db.session.add(StudySettings(user_id=user.id, new_words_per_day=5, reviews_per_day=20, reading_minutes_per_day=10))
        real_db.session.commit()
        merged = dict(frozen)
        snapshot_mod._refresh_reading_target(user.id, merged, real_db)
        assert merged['subtitle'] == 'Глава 3 · Old title · Норма дня — 10 мин'
        assert merged['eta_minutes'] == 10
        assert merged['data']['time_spent_seconds'] == 420
        assert merged['data']['gate_seconds'] == 600
        assert merged['data']['gate_reached'] is False
        # The nested snapshot payload remains frozen.
        assert frozen['data']['gate_seconds'] == 300
        assert frozen['data']['time_spent_seconds'] == 60

    @freeze_time('2026-09-05 12:00:00')
    def test_gate_reached_uses_refreshed_odd_day_target(
        self, user, monkeypatch,
    ):
        from app.books import reading_session
        from app.daily_plan import snapshot as snapshot_mod

        monkeypatch.setattr(
            reading_session, 'get_book_reading_seconds_today',
            lambda *_args, **_kwargs: 420,
        )
        item = {
            'kind': 'reading',
            'subtitle': 'Норма дня — 10 мин',
            'eta_minutes': 10,
            'data': {'book_id': 77, 'gate_seconds': 600},
        }

        snapshot_mod._refresh_reading_target(user.id, item, real_db)

        assert item['subtitle'] == 'Норма дня — 5 мин'
        assert item['eta_minutes'] == 5
        assert item['data']['gate_seconds'] == 300
        assert item['data']['gate_reached'] is True


class TestCompletedCurriculumAnchorKeepsImmediateNextLessons:
    """DP-004: done-today may replace one slot, not the whole pending chain."""

    def test_intensive_snapshot_is_completed_plus_first_two_pending(
        self, db_session, user,
    ):
        from app.daily_plan.plan_builder import build_required_snapshot
        from app.utils.time_utils import get_user_local_day_bounds

        code = unique_level_code()
        level = CEFRLevel(code=code, name=f'L-{code}', order=1)
        module = Module(
            level=level, number=1, title='M-chain', description='', raw_content={},
        )
        lessons = [
            Lessons(
                module=module, number=number, order=number,
                title=f'L{number}', type='vocabulary', content={},
            )
            for number in range(1, 5)
        ]
        user.onboarding_level = code
        db_session.add_all([level, module, *lessons])
        db_session.flush()
        today_start, _ = get_user_local_day_bounds(user.id, real_db)
        db_session.add(LessonProgress(
            user_id=user.id,
            lesson_id=lessons[0].id,
            status='completed',
            score=100,
            started_at=today_start + timedelta(hours=1),
            completed_at=today_start + timedelta(hours=2),
            last_activity=today_start + timedelta(hours=2),
        ))
        db_session.commit()

        items = build_required_snapshot(user.id, 'intensive', real_db)
        curriculum_ids = [
            item['data']['lesson_id']
            for item in items
            if item['kind'] == 'curriculum'
        ]

        assert curriculum_ids == [
            lessons[0].id,
            lessons[1].id,
            lessons[2].id,
        ]
        assert len(curriculum_ids) == len(set(curriculum_ids))


class TestSelfRepairEmptyingRequired:
    """Починка, выбросившая ПОСЛЕДНИЙ пункт, не вправе заморозить день.

    `compute_day_secured_from_activity` закрывает пустой `required` только у
    graduated или заблокированного спайна. Дроп даёт третий способ получить
    пустой список — без флага день не закрывался бы никаким объёмом работы,
    то есть починка, существующая ради разблокировки дня, сама бы его и
    блокировала.
    """

    @freeze_time('2026-09-01 12:00:00')
    def test_flag_lets_activity_close_the_day(
        self, db_session, user, vocabulary_lesson,
    ):
        from app.daily_plan.service import compute_day_secured_from_activity

        base_meta = {'effective_mode': 'unified', 'user_id': user.id}
        plan = {'required': [], 'day_secured': False, '_plan_meta': dict(base_meta)}
        assert compute_day_secured_from_activity(plan, {}) is False

        healed = {
            'required': [],
            'day_secured': False,
            '_plan_meta': {**base_meta, 'required_self_healed': True},
        }
        # Активности нет — флаг сам по себе день не закрывает.
        assert compute_day_secured_from_activity(healed, {}) is False

        db_session.add(LessonProgress(
            user_id=user.id, lesson_id=vocabulary_lesson.id,
            status='completed', score=100.0,
            # Must be inside the elapsed part of the current study day.  A
            # fixed 09:00 UTC timestamp is still in the future when this test
            # runs in the morning, so the real-time activity reader correctly
            # excludes it and makes the test depend on wall-clock time.
            last_activity=(
                datetime.now(timezone.utc).replace(tzinfo=None)
                - timedelta(seconds=1)
            ),
        ))
        db_session.commit()

        assert compute_day_secured_from_activity(healed, {}) is True

    def test_assembly_reports_the_repair(self, db_session, user, vocabulary_lesson):
        """Сквозная проводка: снапшот был непуст, оверлей его опустошил."""
        from app.daily_plan.plan import get_daily_plan

        dead = _curriculum_item(vocabulary_lesson.id + 10_000, 'curriculum:dead')
        db_session.add(DailyPlanLog(
            user_id=user.id,
            plan_date=study_today(),
            plan_json=_snapshot_of([dead]),
        ))
        db_session.commit()

        payload = get_daily_plan(user.id)

        assert payload['required'] == []
        assert payload['required_self_healed'] is True
        assert payload['graduated'] is False

    def test_untouched_snapshot_does_not_set_the_flag(
        self, db_session, user, vocabulary_lesson,
    ):
        from app.daily_plan.plan import get_daily_plan

        db_session.add(DailyPlanLog(
            user_id=user.id,
            plan_date=study_today(),
            plan_json=_snapshot_of([_curriculum_item(vocabulary_lesson.id)]),
        ))
        db_session.commit()

        payload = get_daily_plan(user.id)

        assert [it['id'] for it in payload['required']] == ['curriculum:lesson']
        assert payload['required_self_healed'] is False


class TestTransientFailureKeepsRequired:
    """Сбой самой проверки не вправе резать `required`.

    Все три ветки `_item_unreachable` глушат исключение и возвращают False.
    Правило нагружено смыслом: перевернув его в True, транзиентная ошибка БД
    молча выбрасывала бы обязательные пункты и раздавала ложный `day_secured`
    вместе с `xp_perfect_day` — и ни один тест этого бы не заметил.
    """

    def test_curriculum_lookup_failure_keeps_the_item(
        self, db_session, user, vocabulary_lesson,
    ):
        from app.daily_plan import snapshot as snapshot_mod

        class _Boom:
            class session:  # noqa: N801 — имитируем db.session.get
                @staticmethod
                def get(*_args, **_kwargs):
                    raise RuntimeError('db hiccup')

        assert snapshot_mod._curriculum_lesson_unreachable(
            user.id, _curriculum_item(vocabulary_lesson.id), _Boom,
        ) is False

    def test_deck_quiz_counter_failure_keeps_the_item(self, user, monkeypatch):
        from app.daily_plan import snapshot as snapshot_mod
        from app.daily_plan.linear.slots import srs_slot

        def _boom(*_args, **_kwargs):
            raise RuntimeError('db hiccup')

        monkeypatch.setattr(srs_slot, '_count_user_deck_quiz_words', _boom)
        assert snapshot_mod._deck_quiz_unreachable(user.id, real_db) is False

    def test_reading_access_failure_keeps_the_item(self, db_session, user, monkeypatch):
        from app.daily_plan import snapshot as snapshot_mod
        from app.daily_plan.items import reading as reading_items

        def _boom(*_args, **_kwargs):
            raise RuntimeError('db hiccup')

        monkeypatch.setattr(reading_items, 'book_access_ok_for_reading', _boom)
        item = {
            'id': 'reading:book',
            'section': 'required',
            'kind': 'reading',
            'title': 'Чтение',
            'subtitle': None,
            'lesson_type': None,
            'eta_minutes': 10,
            'url': '/read',
            'completion_signal': 'reading_done',
            'data': {'book_id': 1},
        }
        assert snapshot_mod._reading_book_unreachable(user.id, item, real_db) is False

    def test_srs_counter_refresh_failure_leaves_frozen_numbers(
        self, user, monkeypatch,
    ):
        """Сбой обновления счётчиков не должен ронять отдачу плана."""
        from app.daily_plan import snapshot as snapshot_mod
        from app.srs import counting

        def _boom(*_args, **_kwargs):
            raise RuntimeError('db hiccup')

        monkeypatch.setattr(counting, 'count_reviews_today', _boom)
        # 999 — заведомо не то, что вернул бы удачный пересчёт (у свежего
        # юзера ревью 0), поэтому тест различает «сбой проглочен» и «пересчёт
        # прошёл».
        item = {
            'id': 'srs:global',
            'kind': 'srs',
            'data': {'reviews_today': 999, 'goal_total': 30},
        }
        snapshot_mod._refresh_srs_counters(user.id, item, real_db)
        assert item['data'] == {'reviews_today': 999, 'goal_total': 30}
