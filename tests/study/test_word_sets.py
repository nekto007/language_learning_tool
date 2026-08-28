"""Curated word sets: suggestion ranking, study enrolment, admin management."""
import uuid

import pytest

from app.admin.audit import AdminAuditLog
from app.admin.routes.word_set_routes import _slugify
from app.study.models import (
    UserWord,
    WordSet,
    WordSetQuizResult,
    WordSetWord,
)
from app.study.services import WordSetService
from app.utils.db import db
from app.words.models import CollectionWords


def _make_set(db_session, *, name='Цвета', published=True, words=2, sort_order=0):
    suffix = uuid.uuid4().hex[:8]
    word_set = WordSet(
        slug=f'set-{suffix}',
        name=name,
        accent='amber',
        is_published=published,
        sort_order=sort_order,
    )
    db_session.add(word_set)
    db_session.flush()

    created = []
    for index in range(words):
        word = CollectionWords(
            english_word=f'w{index}_{suffix}', russian_word=f'слово{index}', level='A1'
        )
        db_session.add(word)
        db_session.flush()
        db_session.add(
            WordSetWord(set_id=word_set.id, word_id=word.id, order_index=index)
        )
        created.append(word)

    db_session.commit()
    return word_set, created


def _record(db_session, user_id, set_id, score):
    db_session.add(WordSetQuizResult(
        user_id=user_id,
        set_id=set_id,
        total_questions=10,
        correct_answers=int(score / 10),
        score_percentage=score,
        time_taken=30,
    ))
    db_session.commit()


class TestSuggestion:
    def test_never_played_set_wins(self, db_session, test_user):
        played, _ = _make_set(db_session, name='Сыгранный', sort_order=1)
        fresh, _ = _make_set(db_session, name='Новый', sort_order=2)
        _record(db_session, test_user.id, played.id, 90.0)

        suggestion = WordSetService.suggest_for_user(test_user.id)
        assert suggestion is not None
        assert suggestion['set'].id == fresh.id

    def test_weakest_set_wins_once_everything_is_played(self, db_session, test_user):
        strong, _ = _make_set(db_session, name='Сильный', sort_order=1)
        weak, _ = _make_set(db_session, name='Слабый', sort_order=2)
        _record(db_session, test_user.id, strong.id, 90.0)
        _record(db_session, test_user.id, weak.id, 40.0)

        suggestion = WordSetService.suggest_for_user(test_user.id)
        assert suggestion is not None
        assert suggestion['set'].id == weak.id
        assert suggestion['best_score'] == pytest.approx(40.0)

    def test_best_score_is_the_max_not_the_latest(self, db_session, test_user):
        word_set, _ = _make_set(db_session)
        _record(db_session, test_user.id, word_set.id, 80.0)
        _record(db_session, test_user.id, word_set.id, 30.0)

        suggestion = WordSetService.suggest_for_user(test_user.id)
        assert suggestion['best_score'] == pytest.approx(80.0)
        assert suggestion['attempts'] == 2

    def test_wordless_set_is_never_suggested(self, db_session, test_user):
        _make_set(db_session, words=0)
        assert WordSetService.suggest_for_user(test_user.id) is None

    def test_unpublished_set_is_never_suggested(self, db_session, test_user):
        _make_set(db_session, published=False)
        assert WordSetService.suggest_for_user(test_user.id) is None

    def test_set_of_untranslated_words_is_never_suggested(self, db_session, test_user):
        """Membership is not the same thing as playable content.

        ``get_words`` drops words without a translation — they can be neither a
        question nor a distractor — so counting raw membership advertised a set
        whose quiz route immediately turns the learner away.
        """
        word_set, words = _make_set(db_session, words=2)
        for word in words:
            word.russian_word = ''
        db_session.commit()

        assert WordSetService.suggest_for_user(test_user.id) is None
        entry = next(
            e for e in WordSetService.list_published(test_user.id)
            if e['set'].id == word_set.id
        )
        assert entry['word_count'] == 0

    @pytest.mark.parametrize('blank', ['   ', '\t', '\n', '\r\n', ' \t ', '\xa0'])
    def test_whitespace_only_translation_is_not_playable_content(
        self, db_session, test_user, blank,
    ):
        """Blank means blank after trimming, as in the quiz generator.

        ``QuizService`` skips a word whose ``russian_word.strip()`` is empty, so
        a set holding only «   » translations counted as playable, got suggested,
        and then produced a successful response with no questions in it.

        Every whitespace form is checked, not just the plain space: SQL's
        one-argument ``trim()`` strips spaces *only*, so tab-, newline- and
        NBSP-only translations used to pass the catalogue's blank check and be
        dropped by the generator anyway — exactly the mismatch this rule exists
        to prevent.
        """
        word_set, words = _make_set(db_session, words=2)
        for word in words:
            word.russian_word = blank
        db_session.commit()

        assert WordSetService.get_words(word_set.id) == []
        entry = next(
            e for e in WordSetService.list_published(test_user.id)
            if e['set'].id == word_set.id
        )
        assert entry['word_count'] == 0
        assert WordSetService.suggest_for_user(test_user.id) is None

    @pytest.mark.parametrize('blank', ['   ', '\t', '\n', '\xa0'])
    def test_whitespace_only_english_side_is_not_playable_content(
        self, db_session, test_user, blank,
    ):
        """The English side is an answer too, not just a label.

        Every word yields a reverse «переведите на английский» question whose
        answer is ``english_word``; its hint indexes the stripped answer's
        first character. A whitespace-only English side therefore prompts an
        empty string or raises — so it must not be counted as playable content
        or pushed into the plan by ``suggest_for_user``.
        """
        word_set, words = _make_set(db_session, words=2)
        # ``english_word`` is unique, so each blank differs in length only —
        # still whitespace-only, still two distinct rows.
        for index, word in enumerate(words):
            word.english_word = blank * (index + 1)
        db_session.commit()

        assert WordSetService.get_words(word_set.id) == []
        entry = next(
            e for e in WordSetService.list_published(test_user.id)
            if e['set'].id == word_set.id
        )
        assert entry['word_count'] == 0
        assert WordSetService.suggest_for_user(test_user.id) is None

    def test_word_count_matches_what_the_quiz_would_serve(self, db_session, test_user):
        word_set, words = _make_set(db_session, words=3)
        words[0].russian_word = None
        db_session.commit()

        entry = next(
            e for e in WordSetService.list_published(test_user.id)
            if e['set'].id == word_set.id
        )
        assert entry['word_count'] == len(WordSetService.get_words(word_set.id)) == 2


class TestAddToStudy:
    def test_adds_every_word_once(self, authenticated_client, db_session, test_user):
        word_set, words = _make_set(db_session, words=3)

        first = authenticated_client.post(f'/study/sets/{word_set.slug}/add')
        assert first.status_code == 302
        assert UserWord.query.filter_by(user_id=test_user.id).filter(
            UserWord.word_id.in_([w.id for w in words])
        ).count() == 3

        second = authenticated_client.post(
            f'/study/sets/{word_set.slug}/add',
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )
        assert second.status_code == 200
        assert second.get_json()['added_count'] == 0
        assert UserWord.query.filter_by(user_id=test_user.id).filter(
            UserWord.word_id.in_([w.id for w in words])
        ).count() == 3

    def test_empty_set_adds_nothing(self, authenticated_client, db_session):
        word_set, _ = _make_set(db_session, words=0)
        response = authenticated_client.post(
            f'/study/sets/{word_set.slug}/add',
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )
        assert response.status_code == 200
        assert response.get_json()['added_count'] == 0


class TestSlugify:
    def test_transliterates_cyrillic(self):
        assert _slugify('Цвета и формы') == 'cveta-i-formy'

    def test_punctuation_only_yields_empty(self):
        assert _slugify('!!! ???') == ''

    def test_truncates_to_the_column_width(self):
        assert len(_slugify('a' * 200)) == 80

    def test_strips_path_separators(self):
        assert _slugify('a/b c') == 'a-b-c'


class TestAdminRoutes:
    def test_opening_the_create_form_writes_no_audit_row(self, admin_client, db_session):
        """A GET renders a form; auditing it would file a mutation that never
        happened, and an admin opens the form far more often than they save."""
        before = AdminAuditLog.query.filter_by(action='word_set.create').count()
        assert admin_client.get('/admin/word-sets/create').status_code == 200
        assert AdminAuditLog.query.filter_by(action='word_set.create').count() == before

    def test_create_audits_and_normalizes_the_slug(self, admin_client, db_session):
        before = AdminAuditLog.query.filter_by(action='word_set.create').count()
        response = admin_client.post('/admin/word-sets/create', data={
            'name': 'Цвета',
            'slug': 'Цвета И Формы/Все',
            'accent': 'amber',
            'sort_order': '0',
        }, follow_redirects=False)
        assert response.status_code == 302

        created = WordSet.query.filter_by(name='Цвета').order_by(WordSet.id.desc()).first()
        assert created is not None
        # A raw slug would reach `/study/sets/<slug>` and the plan item's url.
        assert created.slug == 'cveta-i-formy-vse'
        assert AdminAuditLog.query.filter_by(action='word_set.create').count() == before + 1

    def test_over_length_name_is_clamped_not_a_500(self, admin_client, db_session):
        response = admin_client.post('/admin/word-sets/create', data={
            'name': 'Ц' * 400,
            'slug': 'long-name-set',
            'accent': 'amber',
            'sort_order': '0',
        })
        assert response.status_code == 302
        created = WordSet.query.filter_by(slug='long-name-set').first()
        assert created is not None
        assert len(created.name) == 120

    def test_duplicate_slug_is_rejected(self, admin_client, db_session):
        existing, _ = _make_set(db_session)
        response = admin_client.post('/admin/word-sets/create', data={
            'name': 'Другой',
            'slug': existing.slug,
            'accent': 'amber',
            'sort_order': '0',
        })
        assert response.status_code == 400
        assert WordSet.query.filter_by(slug=existing.slug).count() == 1

    def test_edit_keeps_its_own_slug(self, admin_client, db_session):
        word_set, _ = _make_set(db_session)
        response = admin_client.post(f'/admin/word-sets/{word_set.id}/edit', data={
            'name': 'Переименован',
            'slug': word_set.slug,
            'accent': 'teal',
            'sort_order': '5',
            'is_published': 'on',
        })
        assert response.status_code == 302
        db_session.refresh(word_set)
        assert word_set.name == 'Переименован'
        assert word_set.accent == 'teal'

    def test_delete_removes_membership_and_history(
        self, admin_client, db_session, test_user
    ):
        word_set, words = _make_set(db_session, words=2)
        _record(db_session, test_user.id, word_set.id, 70.0)
        set_id = word_set.id

        response = admin_client.post(f'/admin/word-sets/{set_id}/delete')
        assert response.status_code == 302
        assert WordSet.query.get(set_id) is None
        assert WordSetWord.query.filter_by(set_id=set_id).count() == 0
        db.session.expire_all()
        assert WordSetQuizResult.query.filter_by(set_id=set_id).count() == 0

    def test_adding_the_same_word_twice_is_a_no_op(self, admin_client, db_session):
        word_set, words = _make_set(db_session, words=1)
        target = words[0]

        admin_client.post(
            f'/admin/word-sets/{word_set.id}/words/add', data={'word_id': target.id}
        )
        assert WordSetWord.query.filter_by(
            set_id=word_set.id, word_id=target.id
        ).count() == 1

    def test_word_search_escapes_like_wildcards(self, admin_client, db_session):
        suffix = uuid.uuid4().hex[:8]
        literal = CollectionWords(
            english_word=f'a_b{suffix}', russian_word='подчёркивание'
        )
        decoy = CollectionWords(english_word=f'axb{suffix}', russian_word='ложное')
        db_session.add_all([literal, decoy])
        db_session.commit()

        response = admin_client.get(f'/admin/word-sets/api/word-search?q=a_b{suffix}')
        assert response.status_code == 200
        found = {row['english_word'] for row in response.get_json()['results']}
        # Without escape_like + escape='\\', `_` matches any character (ADM-008).
        assert literal.english_word in found
        assert decoy.english_word not in found

    def test_word_search_needs_two_characters(self, admin_client):
        response = admin_client.get('/admin/word-sets/api/word-search?q=a')
        assert response.get_json()['results'] == []
