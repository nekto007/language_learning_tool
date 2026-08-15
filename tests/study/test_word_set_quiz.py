"""Themed word-set quiz: access, question sourcing, SRS isolation, results."""
import uuid

import pytest

from app.study.models import (
    StudySession,
    UserCardDirection,
    UserWord,
    WordSet,
    WordSetQuizResult,
    WordSetWord,
)
from app.words.models import CollectionWords


def _make_set(db_session, *, slug=None, published=True, words=4):
    suffix = uuid.uuid4().hex[:8]
    word_set = WordSet(
        slug=slug or f'colors-{suffix}',
        name='Цвета',
        icon='🎨',
        accent='amber',
        is_published=published,
    )
    db_session.add(word_set)
    db_session.flush()

    pairs = [('red', 'красный'), ('blue', 'синий'), ('green', 'зелёный'),
             ('yellow', 'жёлтый'), ('black', 'чёрный')]
    created = []
    for index, (eng, rus) in enumerate(pairs[:words]):
        word = CollectionWords(
            english_word=f'{eng}_{suffix}', russian_word=rus, level='A1'
        )
        db_session.add(word)
        db_session.flush()
        db_session.add(
            WordSetWord(set_id=word_set.id, word_id=word.id, order_index=index)
        )
        created.append(word)

    db_session.commit()
    return word_set, created


class TestSetAccess:
    def test_published_set_is_reachable(self, authenticated_client, db_session):
        word_set, _ = _make_set(db_session)
        response = authenticated_client.get(f'/study/sets/{word_set.slug}')
        assert response.status_code == 200

    def test_unpublished_set_is_hidden_from_learners(self, authenticated_client, db_session):
        word_set, _ = _make_set(db_session, published=False)
        response = authenticated_client.get(f'/study/sets/{word_set.slug}')
        assert response.status_code == 404

    def test_unknown_slug_is_404(self, authenticated_client):
        response = authenticated_client.get('/study/sets/nope-does-not-exist')
        assert response.status_code == 404

    def test_listing_renders(self, authenticated_client, db_session):
        _make_set(db_session)
        response = authenticated_client.get('/study/sets')
        assert response.status_code == 200

    def test_old_topics_listing_redirects_to_sets(self, authenticated_client):
        response = authenticated_client.get('/study/topics')
        assert response.status_code == 302
        assert '/study/sets' in response.location


class TestQuestionSourcing:
    def test_questions_come_from_the_set(self, authenticated_client, db_session):
        word_set, words = _make_set(db_session)
        allowed = {w.english_word for w in words} | {w.russian_word for w in words}

        response = authenticated_client.get(
            f'/study/api/get-quiz-questions?source=word_set&set={word_set.slug}'
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert payload['status'] == 'success'
        assert payload['questions']

        for question in payload['questions']:
            assert question['text'] in allowed

    def test_unpublished_set_yields_404(self, authenticated_client, db_session):
        word_set, _ = _make_set(db_session, published=False)
        response = authenticated_client.get(
            f'/study/api/get-quiz-questions?source=word_set&set={word_set.slug}'
        )
        assert response.status_code == 404

    def test_multiple_choice_options_prefer_the_set(self, authenticated_client, db_session):
        word_set, words = _make_set(db_session, words=5)
        set_translations = {w.russian_word for w in words}

        response = authenticated_client.get(
            f'/study/api/get-quiz-questions?source=word_set&set={word_set.slug}&count=20'
        )
        payload = response.get_json()

        checked = 0
        for question in payload['questions']:
            if question['type'] != 'multiple_choice' or question['direction'] != 'eng_to_rus':
                continue
            checked += 1
            in_theme = sum(1 for option in question['options'] if option in set_translations)
            # correct answer + 2 themed distractors
            assert in_theme >= 3
        assert checked, 'expected at least one eng->rus multiple-choice question'


class TestSrsIsolation:
    def test_answer_does_not_touch_srs(self, authenticated_client, db_session, test_user):
        word_set, words = _make_set(db_session)
        target = words[0]

        page = authenticated_client.get(f'/study/quiz/set/{word_set.slug}')
        assert page.status_code == 200

        session = (
            StudySession.query
            .filter_by(user_id=test_user.id, session_type='quiz_word_set')
            .order_by(StudySession.id.desc())
            .first()
        )
        assert session is not None

        response = authenticated_client.post(
            '/study/api/submit-quiz-answer',
            json={
                'session_id': session.id,
                'word_id': target.id,
                'direction': 'eng_to_rus',
                'is_correct': True,
            },
        )
        assert response.status_code == 200
        assert response.get_json()['srs_graded'] is False

        # Cards hang off UserWord, so absence of that row is what proves no
        # scheduling happened for a word the learner never chose to study.
        user_word = UserWord.query.filter_by(
            user_id=test_user.id, word_id=target.id
        ).first()
        assert user_word is None, 'themed quiz must not enrol the word'

        if user_word is not None:  # pragma: no cover - defensive
            assert UserCardDirection.query.filter_by(
                user_word_id=user_word.id
            ).count() == 0

    def test_deck_quiz_still_grades(self, authenticated_client, db_session, test_user, monkeypatch):
        """The exemption is scoped to themed sets, not to quizzes in general.

        Deck quizzes grade on purpose — that is what lets the daily plan's SRS
        slot be satisfied by playing one.
        """
        import app.study.game_routes as game_routes

        calls = []
        monkeypatch.setattr(
            game_routes, '_grade_quiz_answer',
            lambda word_id, direction, is_correct: calls.append(word_id) or True,
        )

        word_set, words = _make_set(db_session)
        session = StudySession(user_id=test_user.id, session_type='quiz')
        db_session.add(session)
        db_session.commit()

        response = authenticated_client.post(
            '/study/api/submit-quiz-answer',
            json={
                'session_id': session.id,
                'word_id': words[0].id,
                'direction': 'eng_to_rus',
                'is_correct': True,
            },
        )
        assert response.status_code == 200
        assert calls == [words[0].id]


class TestResultRecording:
    def test_completion_writes_a_result(self, authenticated_client, db_session, test_user):
        word_set, _ = _make_set(db_session)
        authenticated_client.get(f'/study/quiz/set/{word_set.slug}')
        session = (
            StudySession.query
            .filter_by(user_id=test_user.id, session_type='quiz_word_set')
            .order_by(StudySession.id.desc())
            .first()
        )

        response = authenticated_client.post(
            '/study/api/complete-quiz',
            json={
                'session_id': session.id,
                'set_slug': word_set.slug,
                'source': 'word_set',
                'total_questions': 8,
                'correct_answers': 6,
                'time_taken': 40,
            },
        )
        assert response.status_code == 200

        result = WordSetQuizResult.query.filter_by(
            user_id=test_user.id, set_id=word_set.id
        ).first()
        assert result is not None
        assert result.total_questions == 8
        assert result.correct_answers == 6

    def test_slug_without_a_matching_session_is_ignored(
        self, authenticated_client, db_session, test_user
    ):
        """A forged body must not be able to write rows the plan reads."""
        word_set, _ = _make_set(db_session)

        response = authenticated_client.post(
            '/study/api/complete-quiz',
            json={
                'session_id': 999999999,
                'set_slug': word_set.slug,
                'total_questions': 8,
                'correct_answers': 8,
                'time_taken': 10,
            },
        )
        assert response.status_code == 200
        assert WordSetQuizResult.query.filter_by(set_id=word_set.id).count() == 0


@pytest.mark.smoke
def test_sets_listing_smoke(authenticated_client, db_session):
    _make_set(db_session)
    assert authenticated_client.get('/study/sets').status_code == 200
