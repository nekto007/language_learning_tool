"""Кластер A-2 фазы 2: слоты, которые молча исчезают из плана дня.

Четыре находки реестра `docs/audit/2026-08-26-daily-plan-audit.md`:

* ``DP-037`` — ``error_review`` с ``determine_section() == 'required'`` исчезал
  из плана целиком: optional отбрасывал кандидата с секцией не-``'optional'``,
  а в required его не кладёт никто. Чем острее бэклог, тем менее заметен пункт.
* ``DP-043`` — тир ``collapse`` обнуляет адаптивный лимит ревью, поэтому при
  чисто REVIEW-бэклоге ``total_show == 0`` и SRS-слот пропадал на раннем
  ``return None`` — при том что ``get_due_card_budget`` обещает этому же
  пользователю «bounded-but-nonzero batch».
* ``DP-046`` — грейдер «Повтори N фраз» засчитывал пустой ответ верным и
  закрывал ``QuizErrorLog``.
* ``DP-047`` — переэкранированная регулярка служила ключом дедупа и схлопывала
  разные фразы в одну корзину: карточка выдавала 1–2 задания вместо трёх.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.linear.models import QuizErrorLog
from app.srs.constants import CardState
from app.study.models import StudySettings, UserCardDirection, UserWord
from app.words.models import CollectionWords


# ── helpers ──────────────────────────────────────────────────────────────────


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _error_rows(db_session, user_id: int, lesson_id: int, count: int) -> list[QuizErrorLog]:
    rows = [
        QuizErrorLog(
            user_id=user_id,
            lesson_id=lesson_id,
            question_payload={'question_text': f'q{i}', 'correct_answer': f'answer {i}'},
            answered_wrong_at=datetime.now(timezone.utc) - timedelta(hours=i + 1),
            resolved_at=None,
        )
        for i in range(count)
    ]
    db_session.add_all(rows)
    db_session.commit()
    return rows


def _review_card(db_session, user: User) -> UserCardDirection:
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'vanish_{suffix}',
        russian_word=f'слово_{suffix}',
        level='A1',
    )
    db_session.add(word)
    db_session.commit()

    user_word = UserWord(user_id=user.id, word_id=word.id)
    user_word.status = 'learning'
    db_session.add(user_word)
    db_session.commit()

    card = UserCardDirection(user_word_id=user_word.id, direction='eng-rus')
    card.state = CardState.REVIEW.value
    card.repetitions = 3
    card.next_review = _now_naive() - timedelta(days=1)
    card.last_reviewed = _now_naive() - timedelta(days=2)
    card.first_reviewed = _now_naive() - timedelta(days=5)
    db_session.add(card)
    db_session.commit()
    return card


@pytest.fixture()
def a1_lesson(db_session):
    """A `Lessons` row under a real A1 level.

    ``_error_candidates`` only looks at A1/A2 content, so the shared
    ``test_lesson_quiz`` fixture (unique synthetic level code) is invisible
    to the phrase-review builders.
    """
    level = db_session.query(CEFRLevel).filter_by(code='A1').first()
    if level is None:
        level = CEFRLevel(code='A1', name='A1', description='A1', order=1)
        db_session.add(level)
        db_session.commit()

    module = Module(
        level_id=level.id,
        number=1,
        title='Phrase module',
        description='Phrases',
        raw_content={'module': {'id': 1, 'title': 'Phrases', 'lessons': []}},
        min_score_required=70,
        allow_skip_test=False,
        input_mode='mixed',
    )
    db_session.add(module)
    db_session.commit()

    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Phrase quiz',
        type='quiz',
        order=1,
        content={'questions': []},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


# ── DP-037 ───────────────────────────────────────────────────────────────────


class TestAcuteErrorReviewStaysInThePlan:
    """Острый тир error-review не исчезает, а поднимается в начало optional."""

    def _acute_backlog(self, db_session, user_id: int, lesson_id: int) -> None:
        """15+ нерешённых ошибок = required-тир по `determine_section`."""
        from app.daily_plan.items.error_review import REQUIRED_UNRESOLVED_THRESHOLD

        _error_rows(db_session, user_id, lesson_id, REQUIRED_UNRESOLVED_THRESHOLD + 5)

    def test_determine_section_still_escalates(
        self, app, db_session, test_user, test_lesson_quiz,
    ):
        """Предпосылка находки: тир действительно 'required'."""
        from app.daily_plan.items.error_review import determine_section
        from app.utils.db import db as real_db

        self._acute_backlog(db_session, test_user.id, test_lesson_quiz.id)

        with app.test_request_context():
            assert determine_section(test_user.id, real_db) == 'required'

    def test_acute_tier_is_built_and_marked_urgent(
        self, app, db_session, test_user, test_lesson_quiz,
    ):
        """«До»: кандидат отбрасывался, потому что секция ≠ 'optional'."""
        from app.daily_plan.items.error_review import build_optional_error_review_item
        from app.utils.db import db as real_db

        self._acute_backlog(db_session, test_user.id, test_lesson_quiz.id)

        with app.test_request_context():
            item = build_optional_error_review_item(test_user.id, real_db)

        assert item is not None
        assert item.section == 'optional'
        assert item.data['urgent'] is True
        assert item.data['tier'] == 'required'

    def test_calm_tier_is_built_without_urgency(
        self, app, db_session, test_user, test_lesson_quiz,
    ):
        """Регресс-страж: спокойный тир (5–14) работает как раньше."""
        from app.daily_plan.items.error_review import build_optional_error_review_item
        from app.utils.db import db as real_db

        _error_rows(db_session, test_user.id, test_lesson_quiz.id, 6)

        with app.test_request_context():
            item = build_optional_error_review_item(test_user.id, real_db)

        assert item is not None
        assert item.data['urgent'] is False
        assert item.data['tier'] == 'optional'

    def test_below_trigger_still_returns_none(
        self, app, db_session, test_user, test_lesson_quiz,
    ):
        """Регресс-страж: ниже порога пункта нет вовсе."""
        from app.daily_plan.items.error_review import build_optional_error_review_item
        from app.utils.db import db as real_db

        _error_rows(db_session, test_user.id, test_lesson_quiz.id, 2)

        with app.test_request_context():
            assert build_optional_error_review_item(test_user.id, real_db) is None

    def test_optional_candidate_no_longer_drops_required_tier(
        self, app, db_session, test_user, test_lesson_quiz,
    ):
        """Точка находки: `_build_optional_candidate` возвращал None при 'required'."""
        from app.daily_plan.plan import _build_optional_candidate
        from app.utils.db import db as real_db

        self._acute_backlog(db_session, test_user.id, test_lesson_quiz.id)

        with app.test_request_context():
            candidate = _build_optional_candidate(
                test_user.id, real_db, 'error_review', None,
            )

        assert candidate is not None
        assert candidate.id == 'error_review:global'

    def test_urgent_item_precedes_other_optional_sources(
        self, app, db_session, test_user, test_lesson_quiz,
    ):
        """Острый пункт стоит впереди очереди, а не в хвосте `_OPTIONAL_PRIORITY`."""
        from app.daily_plan.plan import build_optional
        from app.utils.db import db as real_db

        self._acute_backlog(db_session, test_user.id, test_lesson_quiz.id)

        with app.test_request_context():
            items, _has_more = build_optional(
                test_user.id, real_db, required_items=[], focus=None,
            )

        ids = [item.id for item in items]
        assert 'error_review:global' in ids
        # Впереди — только phrase_review, если он вообще построился.
        assert ids.index('error_review:global') <= 1

    def test_urgent_item_is_not_duplicated(
        self, app, db_session, test_user, test_lesson_quiz,
    ):
        """Подъём вперёд не должен давать вторую копию из `_OPTIONAL_PRIORITY`."""
        from app.daily_plan.plan import build_optional
        from app.utils.db import db as real_db

        self._acute_backlog(db_session, test_user.id, test_lesson_quiz.id)

        with app.test_request_context():
            items, _has_more = build_optional(
                test_user.id, real_db, required_items=[], focus=None,
            )

        ids = [item.id for item in items]
        assert ids.count('error_review:global') == 1

    def test_error_review_never_gates_the_day(
        self, app, db_session, test_user, test_lesson_quiz,
    ):
        """Острый тир остаётся optional: required-снапшот его не знает."""
        from app.daily_plan.plan import build_optional
        from app.utils.db import db as real_db

        self._acute_backlog(db_session, test_user.id, test_lesson_quiz.id)

        with app.test_request_context():
            items, _has_more = build_optional(
                test_user.id, real_db, required_items=[], focus=None,
            )

        error_items = [it for it in items if it.id == 'error_review:global']
        assert error_items and all(it.section == 'optional' for it in error_items)


# ── DP-043 ───────────────────────────────────────────────────────────────────


class TestCollapseTierKeepsReviewBatch:
    """Нулевой адаптивный лимит ревью не должен обнулять весь слот."""

    def test_floor_applies_when_adaptive_allowance_is_zero(self):
        from app.srs.counting import RECOVERY_REVIEW_FLOOR, get_review_batch_budget

        budget = get_review_batch_budget(
            user_id=1, remaining_reviews=0, due_budget_left=20,
        )
        assert budget == RECOVERY_REVIEW_FLOOR

    def test_floor_never_exceeds_the_combined_ceiling(self):
        from app.srs.counting import get_review_batch_budget

        assert get_review_batch_budget(
            user_id=1, remaining_reviews=0, due_budget_left=2,
        ) == 2
        assert get_review_batch_budget(
            user_id=1, remaining_reviews=0, due_budget_left=0,
        ) == 0

    def test_nonzero_adaptive_allowance_is_respected(self):
        """Регресс-страж: тиры low/critical по-прежнему режут ревью."""
        from app.srs.counting import get_review_batch_budget

        assert get_review_batch_budget(
            user_id=1, remaining_reviews=3, due_budget_left=20,
        ) == 3

    def test_collapse_tier_slot_is_still_built(
        self, app, db_session, test_user,
    ):
        """«До»: чисто REVIEW-бэклог на collapse давал total_show=0 и None."""
        from app.daily_plan.items.srs import build_srs_item
        from app.utils.db import db as real_db

        _review_card(db_session, test_user)
        db_session.add(StudySettings(
            user_id=test_user.id, new_words_per_day=10, reviews_per_day=20,
        ))
        db_session.commit()

        with app.test_request_context(), patch(
            'app.study.services.SRSService.get_adaptive_limits', return_value=(0, 0),
        ), patch(
            'app.study.services.SRSService.get_adaptive_limit_reason',
            return_value='collapse',
        ):
            item = build_srs_item(test_user.id, real_db, section='required')

        assert item is not None, 'SRS-слот исчез из плана на collapse-тире'
        assert item.data['review_show'] > 0
        assert item.data['total_show'] > 0
        assert item.data['srs_tier'] == 'collapse'

    def test_exhausted_floor_stops_the_batch(self, app, db_session, test_user):
        """Пол дневной, а не бесконечный: отработанные сегодня ревью его съедают."""
        from app.srs.counting import RECOVERY_REVIEW_FLOOR, get_review_batch_budget
        from app.utils.db import db as real_db

        with app.test_request_context(), patch(
            'app.srs.counting.count_reviews_today',
            return_value=RECOVERY_REVIEW_FLOOR,
        ):
            assert get_review_batch_budget(
                test_user.id, real_db, remaining_reviews=0, due_budget_left=20,
            ) == 0


# ── DP-046 ───────────────────────────────────────────────────────────────────


class TestPhraseReviewGraderRejectsEmptyAnswers:
    """Пустой ответ не бывает верным и не закрывает `QuizErrorLog`."""

    def _seed_session_items(self, client, item: dict) -> None:
        with client.session_transaction() as sess:
            sess['daily_phrase_review_items'] = [item]

    def test_empty_answer_is_wrong_and_leaves_error_unresolved(
        self, db_session, authenticated_client, test_user, a1_lesson,
    ):
        row = _error_rows(db_session, test_user.id, a1_lesson.id, 1)[0]
        self._seed_session_items(authenticated_client, {
            'id': f'error:{row.id}',
            'prompt': 'Скажите это по-английски.',
            'answer': 'I love you',
            'accepted_answers': ['I love you'],
            'source': 'error',
            'error_id': row.id,
        })

        resp = authenticated_client.post(
            '/api/daily-plan/phrase-review/complete', json={'answers': ['']},
        )

        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['correct_count'] == 0
        assert payload['results'][0]['correct'] is False
        db_session.refresh(row)
        assert row.resolved_at is None

    def test_punctuation_only_answer_is_wrong(
        self, db_session, authenticated_client, test_user, a1_lesson,
    ):
        """Ответ, нормализующийся в пустую строку, тоже не верен."""
        row = _error_rows(db_session, test_user.id, a1_lesson.id, 1)[0]
        self._seed_session_items(authenticated_client, {
            'id': f'error:{row.id}',
            'prompt': 'Скажите это по-английски.',
            'answer': 'Good morning',
            'accepted_answers': ['Good morning'],
            'source': 'error',
            'error_id': row.id,
        })

        resp = authenticated_client.post(
            '/api/daily-plan/phrase-review/complete', json={'answers': ['...!?']},
        )

        assert resp.get_json()['correct_count'] == 0
        db_session.refresh(row)
        assert row.resolved_at is None

    def test_missing_answer_for_index_is_wrong(
        self, db_session, authenticated_client, test_user, a1_lesson,
    ):
        """Короткий список ответов даёт '' — тоже не зачёт."""
        row = _error_rows(db_session, test_user.id, a1_lesson.id, 1)[0]
        self._seed_session_items(authenticated_client, {
            'id': f'error:{row.id}',
            'prompt': 'Скажите это по-английски.',
            'answer': 'Nice to meet you',
            'accepted_answers': ['Nice to meet you'],
            'source': 'error',
            'error_id': row.id,
        })

        resp = authenticated_client.post(
            '/api/daily-plan/phrase-review/complete', json={'answers': []},
        )

        assert resp.get_json()['correct_count'] == 0
        db_session.refresh(row)
        assert row.resolved_at is None

    def test_empty_answer_loses_even_to_an_empty_reference(
        self, db_session, authenticated_client, test_user, a1_lesson,
    ):
        """Изолирующий страж самого гейта, а не починенной регулярки.

        Эталон из одной пунктуации нормализуется в пустую строку. Без
        правила «пустой ответ не бывает верным» пустой ввод совпал бы с ним
        буквально и закрыл `QuizErrorLog` — ровно механизм DP-046.
        """
        row = _error_rows(db_session, test_user.id, a1_lesson.id, 1)[0]
        self._seed_session_items(authenticated_client, {
            'id': f'error:{row.id}',
            'prompt': 'Скажите это по-английски.',
            'answer': '???',
            'accepted_answers': ['???'],
            'source': 'error',
            'error_id': row.id,
        })

        resp = authenticated_client.post(
            '/api/daily-plan/phrase-review/complete', json={'answers': ['']},
        )

        assert resp.get_json()['correct_count'] == 0
        db_session.refresh(row)
        assert row.resolved_at is None

    def test_correct_answer_still_resolves(
        self, db_session, authenticated_client, test_user, a1_lesson,
    ):
        """Регресс-страж: настоящий ответ по-прежнему закрывает ошибку."""
        row = _error_rows(db_session, test_user.id, a1_lesson.id, 1)[0]
        self._seed_session_items(authenticated_client, {
            'id': f'error:{row.id}',
            'prompt': 'Скажите это по-английски.',
            'answer': 'I love you',
            'accepted_answers': ['I love you'],
            'source': 'error',
            'error_id': row.id,
        })

        resp = authenticated_client.post(
            '/api/daily-plan/phrase-review/complete',
            json={'answers': ['  I love you!  ']},
        )

        payload = resp.get_json()
        assert payload['correct_count'] == 1
        db_session.refresh(row)
        assert row.resolved_at is not None

    def test_near_miss_is_not_accepted(
        self, db_session, authenticated_client, test_user, a1_lesson,
    ):
        """Другая фраза больше не совпадает с эталоном (последствие DP-047)."""
        row = _error_rows(db_session, test_user.id, a1_lesson.id, 1)[0]
        self._seed_session_items(authenticated_client, {
            'id': f'error:{row.id}',
            'prompt': 'Скажите это по-английски.',
            'answer': 'I am a student',
            'accepted_answers': ['I am a student'],
            'source': 'error',
            'error_id': row.id,
        })

        resp = authenticated_client.post(
            '/api/daily-plan/phrase-review/complete',
            json={'answers': ['My name is Anna']},
        )

        assert resp.get_json()['correct_count'] == 0
        db_session.refresh(row)
        assert row.resolved_at is None


# ── DP-047 ───────────────────────────────────────────────────────────────────


class TestPhraseNormalisationKeepsPhrasesDistinct:
    """Ключ дедупа обязан различать фразы, а не шаблоны."""

    @pytest.mark.parametrize('phrase,expected', [
        ('I go to school', 'i go to school'),
        ('She works here', 'she works here'),
        ('Present Simple', 'present simple'),
        ('  Hello,   world!  ', 'hello world'),
        ("It's fine", "it's fine"),
        ('', ''),
    ])
    def test_normalisation_keeps_words(self, phrase, expected):
        from app.daily_plan.items.phrase_review import normalise_phrase

        assert normalise_phrase(phrase) == expected

    def test_distinct_phrases_land_in_distinct_buckets(self):
        """Реальный пример из реестра: три фразы схлопывались в корзину 's'."""
        from app.daily_plan.items.phrase_review import normalise_phrase

        phrases = ['My name is Anna', 'I am a student', 'I am not busy']
        assert len({normalise_phrase(p) for p in phrases}) == 3

    def test_grader_and_builder_share_one_normaliser(self):
        """Копии регулярки больше нет — расходиться нечему."""
        from app.api.daily_plan import _normalise_phrase_answer
        from app.daily_plan.items.phrase_review import normalise_phrase

        for phrase in ('I love you', 'Good morning', 'Nice to meet you'):
            assert _normalise_phrase_answer(phrase) == normalise_phrase(phrase)
            assert _normalise_phrase_answer(phrase) != ''

    def test_case_and_punctuation_still_fold_together(self):
        """Регресс-страж: дедуп по-прежнему схлопывает переформулировки регистра."""
        from app.daily_plan.items.phrase_review import normalise_phrase

        assert normalise_phrase('I can swim.') == normalise_phrase('i can swim')

    def test_three_distinct_errors_yield_three_prompts(
        self, app, db_session, test_user, a1_lesson,
    ):
        """«До»: три разные ошибки схлопывались в 1–2 задания."""
        from app.daily_plan.items.phrase_review import (
            PHRASE_REVIEW_SIZE,
            get_phrase_review_items,
        )
        from app.utils.db import db as real_db

        answers = ['My name is Anna', 'I am a student', 'I am not busy']
        rows = [
            QuizErrorLog(
                user_id=test_user.id,
                lesson_id=a1_lesson.id,
                question_payload={'question_text': f'q{i}', 'correct_answer': answer},
                answered_wrong_at=datetime.now(timezone.utc) - timedelta(hours=i + 1),
                resolved_at=None,
            )
            for i, answer in enumerate(answers)
        ]
        db_session.add_all(rows)
        db_session.commit()

        with app.test_request_context():
            items = get_phrase_review_items(test_user.id, real_db)

        assert len(items) == PHRASE_REVIEW_SIZE
        assert {item['answer'] for item in items} == set(answers)

    def test_title_reports_the_real_phrase_count(
        self, app, db_session, test_user, a1_lesson,
    ):
        """Заголовок не обещает 3, когда фраза одна."""
        from app.daily_plan.items.phrase_review import build_phrase_review_item
        from app.utils.db import db as real_db

        db_session.add(QuizErrorLog(
            user_id=test_user.id,
            lesson_id=a1_lesson.id,
            question_payload={'question_text': 'q', 'correct_answer': 'I am not busy'},
            answered_wrong_at=datetime.now(timezone.utc) - timedelta(hours=1),
            resolved_at=None,
        ))
        db_session.commit()

        with app.test_request_context():
            item = build_phrase_review_item(test_user.id, real_db)

        assert item is not None
        assert item.data['phrase_count'] == 1
        assert item.title == 'Повтори 1 фразу'
