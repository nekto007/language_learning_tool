"""Unit tests for app/daily_plan/next_step.py.

Covers each priority branch and the None (all-exhausted) case.

All private helpers use lazy imports inside their function body, so patches
target the source modules (e.g. 'app.curriculum.models.LessonProgress'), not
'app.daily_plan.next_step.<Name>'.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from app.daily_plan.next_step import get_next_best_step, NextStep


# ── helpers ──────────────────────────────────────────────────────────────────

class _ColMock:
    """Simple mock for SQLAlchemy column attributes used in filter expressions.

    Plain MagicMock has __gt__, __le__ etc. defaulting to NotImplemented, which
    causes TypeError in Python's comparison protocol. This class uses a plain
    object (not MagicMock subclass, since MagicMixin.__init__ overwrites magic
    methods) so comparison operators return a truthy value that filter() accepts.
    """
    def __gt__(self, other): return True
    def __lt__(self, other): return True
    def __ge__(self, other): return True
    def __le__(self, other): return True
    def __eq__(self, other): return True
    def __ne__(self, other): return True
    def in_(self, other): return True
    def isnot(self, other): return True
    def is_(self, other): return True


def _make_col_mock():
    return _ColMock()


def _make_mock_lesson(lesson_id=1, title='Test Lesson', lesson_type='grammar', order=1, module_id=1):
    m = MagicMock()
    m.id = lesson_id
    m.title = title
    m.type = lesson_type
    m.order = order
    m.module_id = module_id
    return m


def _make_mock_module(module_id=1, number=1):
    m = MagicMock()
    m.id = module_id
    m.number = number
    return m


def _make_mock_db():
    db = MagicMock()
    scalar_mock = MagicMock()
    scalar_mock.scalar.return_value = 0
    db.session.query.return_value.filter.return_value = scalar_mock
    return db


# ── Priority 1: unfinished lesson ────────────────────────────────────────────

class TestCheckUnfinishedLesson:
    def test_returns_lesson_when_in_progress(self, app):
        """In-progress lesson is returned as highest priority."""
        with app.app_context():
            from app.daily_plan.next_step import _check_unfinished_lesson

            mock_progress = MagicMock()
            mock_progress.lesson_id = 42

            mock_lesson = _make_mock_lesson(lesson_id=42, title='Present Simple')
            mock_module = _make_mock_module(number=2)

            db = _make_mock_db()

            with patch('app.curriculum.models.LessonProgress') as MockLP, \
                 patch('app.curriculum.models.Lessons') as MockL, \
                 patch('app.curriculum.models.Module') as MockM:

                MockLP.query.filter_by.return_value.order_by.return_value.first.return_value = mock_progress
                MockL.query.get.return_value = mock_lesson
                MockM.query.get.return_value = mock_module

                step = _check_unfinished_lesson(1, db)

            assert step is not None
            assert step.kind == 'lesson'
            assert step.data['lesson_id'] == 42
            assert step.data['status'] == 'in_progress'
            assert 'Present Simple' in step.reason

    def test_returns_next_lesson_after_last_completed(self, app):
        """When no in-progress lesson exists, returns the next available lesson."""
        with app.app_context():
            from app.daily_plan.next_step import _check_unfinished_lesson

            mock_completed_progress = MagicMock()
            mock_completed_progress.lesson_id = 10

            current_lesson = _make_mock_lesson(lesson_id=10, order=1, module_id=1)
            next_lesson = _make_mock_lesson(lesson_id=11, title='Past Simple', order=2, module_id=1)
            mock_module = _make_mock_module(number=1)

            db = _make_mock_db()

            with patch('app.curriculum.models.LessonProgress') as MockLP, \
                 patch('app.curriculum.models.Lessons') as MockL, \
                 patch('app.curriculum.models.Module') as MockM:

                # Use col mocks so SQLAlchemy-style comparisons (order > x) don't raise TypeError
                MockL.order = _make_col_mock()
                MockL.module_id = _make_col_mock()
                MockL.number = _make_col_mock()

                # First call: no in_progress, second call: last completed
                MockLP.query.filter_by.return_value.order_by.return_value.first.side_effect = [
                    None,
                    mock_completed_progress,
                ]
                MockL.query.get.return_value = current_lesson
                MockM.query.get.return_value = mock_module
                MockL.query.filter.return_value.order_by.return_value.first.return_value = next_lesson

                step = _check_unfinished_lesson(1, db)

            assert step is not None
            assert step.kind == 'lesson'
            assert step.data['lesson_id'] == 11

    def test_returns_none_when_all_lessons_done(self, app):
        """Returns None when no next lesson exists in any module."""
        with app.app_context():
            from app.daily_plan.next_step import _check_unfinished_lesson

            mock_progress = MagicMock()
            mock_progress.lesson_id = 99

            current_lesson = _make_mock_lesson(lesson_id=99, order=5, module_id=1)
            mock_module = _make_mock_module(number=1)

            db = _make_mock_db()

            with patch('app.curriculum.models.LessonProgress') as MockLP, \
                 patch('app.curriculum.models.Lessons') as MockL, \
                 patch('app.curriculum.models.Module') as MockM:

                MockL.order = _make_col_mock()
                MockL.module_id = _make_col_mock()
                MockL.number = _make_col_mock()

                MockLP.query.filter_by.return_value.order_by.return_value.first.side_effect = [
                    None,
                    mock_progress,
                ]
                MockL.query.get.return_value = current_lesson
                MockM.query.get.return_value = mock_module
                # No next lesson in same module
                MockL.query.filter.return_value.order_by.return_value.first.return_value = None
                # No next module
                MockM.query.filter.return_value.first.return_value = None

                step = _check_unfinished_lesson(1, db)

            assert step is None

    def test_cold_start_suggests_first_lesson(self, app):
        """Cold-start user (no lessons ever) sees the first lesson suggested."""
        with app.app_context():
            from app.daily_plan.next_step import _check_unfinished_lesson

            first_module = _make_mock_module(number=1)
            first_lesson = _make_mock_lesson(lesson_id=1, title='Введение', lesson_type='text', order=1)

            db = _make_mock_db()

            with patch('app.curriculum.models.LessonProgress') as MockLP, \
                 patch('app.curriculum.models.Lessons') as MockL, \
                 patch('app.curriculum.models.Module') as MockM:

                # No in_progress, no completed
                MockLP.query.filter_by.return_value.order_by.return_value.first.return_value = None
                MockM.query.order_by.return_value.first.return_value = first_module
                MockL.query.filter_by.return_value.order_by.return_value.first.return_value = first_lesson

                step = _check_unfinished_lesson(1, db)

            assert step is not None
            assert step.kind == 'lesson'
            assert step.data['status'] == 'not_started'
            assert 'Введение' in step.reason


# ── Priority 2: SRS due ───────────────────────────────────────────────────────

class TestCheckSrsDue:
    def test_returns_step_when_cards_due(self, app):
        """Returns SRS step when there are due cards."""
        with app.app_context():
            from app.daily_plan.next_step import _check_srs_due

            mock_user = MagicMock()
            mock_user.default_study_deck_id = None

            mock_settings = MagicMock()
            mock_settings.reviews_per_day = 20

            db = MagicMock()
            scalar_mock = MagicMock()
            scalar_mock.scalar.return_value = 12
            db.session.query.return_value.filter.return_value = scalar_mock

            with patch('app.auth.models.User') as MockUser, \
                 patch('app.study.models.UserWord'), \
                 patch('app.study.models.UserCardDirection') as MockUCD, \
                 patch('app.study.models.StudySettings') as MockSS, \
                 patch('app.daily_plan.next_step.func'):

                MockUser.query.get.return_value = mock_user
                MockSS.get_settings.return_value = mock_settings
                MockUCD.next_review = _make_col_mock()
                MockUCD.direction = _make_col_mock()
                MockUCD.user_word_id = _make_col_mock()

                step = _check_srs_due(1, db)

            assert step is not None
            assert step.kind == 'srs'
            assert '12' in step.reason
            assert step.data['words_due'] == 12

    def test_returns_none_when_no_cards_due(self, app):
        """Returns None when no cards are due."""
        with app.app_context():
            from app.daily_plan.next_step import _check_srs_due

            mock_user = MagicMock()
            mock_user.default_study_deck_id = None

            db = MagicMock()
            scalar_mock = MagicMock()
            scalar_mock.scalar.return_value = 0
            db.session.query.return_value.filter.return_value = scalar_mock

            with patch('app.auth.models.User') as MockUser, \
                 patch('app.study.models.UserWord'), \
                 patch('app.study.models.UserCardDirection') as MockUCD, \
                 patch('app.study.models.StudySettings'), \
                 patch('app.daily_plan.next_step.func'):

                MockUser.query.get.return_value = mock_user
                MockUCD.next_review = _make_col_mock()
                MockUCD.direction = _make_col_mock()
                MockUCD.user_word_id = _make_col_mock()

                step = _check_srs_due(1, db)

            assert step is None


# ── Priority 3: grammar weak ──────────────────────────────────────────────────

class TestCheckGrammarWeak:
    def test_returns_topic_with_due_exercises(self, app):
        """Returns grammar step when a topic has due exercises."""
        with app.app_context():
            from app.daily_plan.next_step import _check_grammar_weak

            mock_status = MagicMock()
            mock_status.topic_id = 5
            mock_status.status = 'practicing'

            mock_topic = MagicMock()
            mock_topic.id = 5
            mock_topic.title = 'Conditional sentences'

            db = _make_mock_db()

            with patch('app.grammar_lab.models.UserGrammarTopicStatus') as MockUGTS, \
                 patch('app.grammar_lab.models.UserGrammarExercise') as MockUGE, \
                 patch('app.grammar_lab.models.GrammarExercise') as MockGE, \
                 patch('app.grammar_lab.models.GrammarTopic') as MockGT:

                MockUGTS.query.filter.return_value.all.return_value = [mock_status]
                MockUGE.query.join.return_value.filter.return_value.count.return_value = 8
                MockGT.query.get.return_value = mock_topic
                MockUGE.next_review = _make_col_mock()
                MockUGE.exercise_id = _make_col_mock()
                MockGE.id = _make_col_mock()
                MockGE.topic_id = _make_col_mock()

                step = _check_grammar_weak(1, db)

            assert step is not None
            assert step.kind == 'grammar'
            assert step.data['topic_id'] == 5
            assert '8' in step.reason
            assert 'Conditional sentences' in step.reason

    def test_returns_none_when_no_due_exercises(self, app):
        """Returns None when active topic has no due exercises."""
        with app.app_context():
            from app.daily_plan.next_step import _check_grammar_weak

            mock_status = MagicMock()
            mock_status.topic_id = 5
            mock_status.status = 'practicing'

            db = _make_mock_db()

            with patch('app.grammar_lab.models.UserGrammarTopicStatus') as MockUGTS, \
                 patch('app.grammar_lab.models.UserGrammarExercise') as MockUGE, \
                 patch('app.grammar_lab.models.GrammarExercise') as MockGE, \
                 patch('app.grammar_lab.models.GrammarTopic'):

                MockUGTS.query.filter.return_value.all.return_value = [mock_status]
                MockUGE.query.join.return_value.filter.return_value.count.return_value = 0
                MockUGE.next_review = _make_col_mock()
                MockUGE.exercise_id = _make_col_mock()
                MockGE.id = _make_col_mock()
                MockGE.topic_id = _make_col_mock()

                step = _check_grammar_weak(1, db)

            assert step is None

    def test_returns_none_when_no_active_topics(self, app):
        """Returns None when user has no active grammar topics."""
        with app.app_context():
            from app.daily_plan.next_step import _check_grammar_weak

            db = _make_mock_db()

            with patch('app.grammar_lab.models.UserGrammarTopicStatus') as MockUGTS, \
                 patch('app.grammar_lab.models.UserGrammarExercise'), \
                 patch('app.grammar_lab.models.GrammarExercise'), \
                 patch('app.grammar_lab.models.GrammarTopic'):

                MockUGTS.query.filter.return_value.all.return_value = []

                step = _check_grammar_weak(1, db)

            assert step is None


# ── Priority 4: reading progress ──────────────────────────────────────────────

class TestCheckReadingProgress:
    def test_returns_book_when_started(self, app):
        """Returns reading step when user has a book in progress."""
        with app.app_context():
            from app.daily_plan.next_step import _check_reading_progress

            mock_book = MagicMock()
            mock_book.id = 7
            mock_book.title = 'Harry Potter'

            db = MagicMock()
            db.session.query.return_value.join.return_value.filter.return_value.all.return_value = [(7,)]

            with patch('app.books.models.Book') as MockBook, \
                 patch('app.books.models.Chapter'), \
                 patch('app.books.models.UserChapterProgress'), \
                 patch('app.daily_plan.next_step.distinct'):

                MockBook.query.get.return_value = mock_book

                step = _check_reading_progress(1, db)

            assert step is not None
            assert step.kind == 'reading'
            assert step.data['book_id'] == 7
            assert 'Harry Potter' in step.reason

    def test_returns_none_when_no_books_started(self, app):
        """Returns None when user hasn't started any books."""
        with app.app_context():
            from app.daily_plan.next_step import _check_reading_progress

            db = MagicMock()
            db.session.query.return_value.join.return_value.filter.return_value.all.return_value = []

            with patch('app.books.models.Book'), \
                 patch('app.books.models.Chapter'), \
                 patch('app.books.models.UserChapterProgress'), \
                 patch('app.daily_plan.next_step.distinct'):

                step = _check_reading_progress(1, db)

            assert step is None


# ── Priority 5: vocab ─────────────────────────────────────────────────────────

class TestCheckVocab:
    def test_returns_vocab_when_user_has_words(self, app):
        """Returns vocab step when user has words in their study list."""
        with app.app_context():
            from app.daily_plan.next_step import _check_vocab

            db = _make_mock_db()

            with patch('app.study.models.UserWord') as MockUW:
                MockUW.query.filter_by.return_value.first.return_value = MagicMock()

                step = _check_vocab(1, db)

            assert step is not None
            assert step.kind == 'vocab'
            assert step.data['has_words'] is True

    def test_returns_none_when_no_words(self, app):
        """Returns None when user has no words in their study list."""
        with app.app_context():
            from app.daily_plan.next_step import _check_vocab

            db = _make_mock_db()

            with patch('app.study.models.UserWord') as MockUW:
                MockUW.query.filter_by.return_value.first.return_value = None

                step = _check_vocab(1, db)

            assert step is None


# ── Priority ordering ─────────────────────────────────────────────────────────

class TestGetNextBestStepPriorityOrdering:
    def test_lesson_beats_srs(self, app):
        """Lesson priority beats SRS when both are available."""
        with app.app_context():
            lesson_step = NextStep(kind='lesson', reason='Lesson', data={})
            srs_step = NextStep(kind='srs', reason='SRS', data={})

            with patch('app.daily_plan.next_step._check_unfinished_lesson', return_value=lesson_step), \
                 patch('app.daily_plan.next_step._check_srs_due', return_value=srs_step):

                result = get_next_best_step(1, _make_mock_db())

            assert result.kind == 'lesson'

    def test_srs_beats_grammar_when_no_lesson(self, app):
        """SRS priority beats grammar when no lesson is available."""
        with app.app_context():
            srs_step = NextStep(kind='srs', reason='SRS', data={})
            grammar_step = NextStep(kind='grammar', reason='Grammar', data={})

            with patch('app.daily_plan.next_step._check_unfinished_lesson', return_value=None), \
                 patch('app.daily_plan.next_step._check_srs_due', return_value=srs_step), \
                 patch('app.daily_plan.next_step._check_grammar_weak', return_value=grammar_step):

                result = get_next_best_step(1, _make_mock_db())

            assert result.kind == 'srs'

    def test_grammar_beats_reading_when_no_lesson_srs(self, app):
        """Grammar priority beats reading when no lesson or SRS available."""
        with app.app_context():
            grammar_step = NextStep(kind='grammar', reason='Grammar', data={})
            reading_step = NextStep(kind='reading', reason='Reading', data={})

            with patch('app.daily_plan.next_step._check_unfinished_lesson', return_value=None), \
                 patch('app.daily_plan.next_step._check_srs_due', return_value=None), \
                 patch('app.daily_plan.next_step._check_grammar_weak', return_value=grammar_step), \
                 patch('app.daily_plan.next_step._check_reading_progress', return_value=reading_step):

                result = get_next_best_step(1, _make_mock_db())

            assert result.kind == 'grammar'

    def test_reading_beats_vocab(self, app):
        """Reading priority beats vocab."""
        with app.app_context():
            reading_step = NextStep(kind='reading', reason='Reading', data={})
            vocab_step = NextStep(kind='vocab', reason='Vocab', data={})

            with patch('app.daily_plan.next_step._check_unfinished_lesson', return_value=None), \
                 patch('app.daily_plan.next_step._check_srs_due', return_value=None), \
                 patch('app.daily_plan.next_step._check_grammar_weak', return_value=None), \
                 patch('app.daily_plan.next_step._check_reading_progress', return_value=reading_step), \
                 patch('app.daily_plan.next_step._check_vocab', return_value=vocab_step):

                result = get_next_best_step(1, _make_mock_db())

            assert result.kind == 'reading'

    def test_returns_none_when_all_sources_exhausted(self, app):
        """Returns None when every priority check returns None."""
        with app.app_context():
            with patch('app.daily_plan.next_step._check_unfinished_lesson', return_value=None), \
                 patch('app.daily_plan.next_step._check_srs_due', return_value=None), \
                 patch('app.daily_plan.next_step._check_grammar_weak', return_value=None), \
                 patch('app.daily_plan.next_step._check_reading_progress', return_value=None), \
                 patch('app.daily_plan.next_step._check_vocab', return_value=None):

                result = get_next_best_step(1, _make_mock_db())

            assert result is None

    def test_vocab_returned_when_only_source(self, app):
        """Vocab is returned when it is the only available source."""
        with app.app_context():
            vocab_step = NextStep(kind='vocab', reason='Vocab', data={'has_words': True})

            with patch('app.daily_plan.next_step._check_unfinished_lesson', return_value=None), \
                 patch('app.daily_plan.next_step._check_srs_due', return_value=None), \
                 patch('app.daily_plan.next_step._check_grammar_weak', return_value=None), \
                 patch('app.daily_plan.next_step._check_reading_progress', return_value=None), \
                 patch('app.daily_plan.next_step._check_vocab', return_value=vocab_step):

                result = get_next_best_step(1, _make_mock_db())

            assert result is not None
            assert result.kind == 'vocab'


# ── API endpoint tests ────────────────────────────────────────────────────────

class TestNextStepApiEndpoint:
    @pytest.mark.smoke
    def test_continuation_endpoint_returns_step(self, authenticated_client):
        """GET /api/daily-plan/continuation returns step when available."""
        mock_step = NextStep(
            kind='srs',
            reason='You have 5 cards due for review',
            data={'words_due': 5, 'daily_limit': 20},
            estimated_minutes=3,
        )
        with patch('app.daily_plan.next_step.get_next_best_step', return_value=mock_step):
            response = authenticated_client.get('/api/daily-plan/continuation')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['step'] is not None
        assert data['step']['kind'] == 'srs'
        assert data['step']['reason'] == 'You have 5 cards due for review'
        assert data['step']['estimated_minutes'] == 3

    def test_continuation_endpoint_returns_null_when_exhausted(self, authenticated_client):
        """GET /api/daily-plan/continuation returns null step when all sources exhausted."""
        with patch('app.daily_plan.next_step.get_next_best_step', return_value=None):
            response = authenticated_client.get('/api/daily-plan/continuation')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['step'] is None

    def test_continuation_endpoint_requires_auth(self, client):
        """Unauthenticated request to continuation endpoint returns 401."""
        response = client.get('/api/daily-plan/continuation')
        assert response.status_code == 401
