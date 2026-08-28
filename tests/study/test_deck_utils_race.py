"""Default-deck membership must survive a concurrent writer.

`ensure_word_in_default_deck` is called from every «добавить в изучение»
path (word sets, topics, collections, card lessons, book SRS). Its check and
its insert are two statements, so a double-click or a retry can have a
competitor land the same `(deck_id, word_id)` row in between and trip
`uix_deck_word`. That must read as «already where we wanted it», not as a 500.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.orm.attributes import set_committed_value

from app.study import deck_utils
from app.study.models import QuizDeck, QuizDeckWord
from app.words.models import CollectionWords


@pytest.fixture
def word(db_session):
    w = CollectionWords(english_word='racecheck', russian_word='гонка', level='A1')
    db_session.add(w)
    db_session.commit()
    return w


def test_creates_default_deck_and_adds_word(db_session, test_user, word):
    deck_utils.ensure_word_in_default_deck(test_user.id, word.id)
    db_session.commit()

    deck = QuizDeck.query.filter_by(user_id=test_user.id).one()
    assert deck.title == 'Мои слова'
    assert test_user.default_study_deck_id == deck.id
    assert QuizDeckWord.query.filter_by(deck_id=deck.id, word_id=word.id).count() == 1


def test_second_call_is_a_no_op(db_session, test_user, word):
    deck_utils.ensure_word_in_default_deck(test_user.id, word.id)
    db_session.commit()
    deck_utils.ensure_word_in_default_deck(test_user.id, word.id)
    db_session.commit()

    assert QuizDeckWord.query.filter_by(word_id=word.id).count() == 1
    assert QuizDeck.query.filter_by(user_id=test_user.id).count() == 1


def test_losing_the_insert_race_does_not_raise(db_session, test_user, word, monkeypatch):
    """The membership row is already there; our pre-check missed it."""
    deck = QuizDeck(user_id=test_user.id, title='Мои слова')
    db_session.add(deck)
    db_session.flush()
    test_user.default_study_deck_id = deck.id
    db_session.add(QuizDeckWord(deck_id=deck.id, word_id=word.id))
    db_session.commit()

    # Stand in for the competitor committing between our check and our insert.
    monkeypatch.setattr(deck_utils, '_word_already_in_a_deck', lambda *_a, **_k: False)

    deck_utils.ensure_word_in_default_deck(test_user.id, word.id)
    db_session.commit()

    assert QuizDeckWord.query.filter_by(deck_id=deck.id, word_id=word.id).count() == 1


def test_race_loss_does_not_discard_the_callers_staged_work(
    db_session, test_user, word, monkeypatch
):
    """The savepoint must contain the failure, not the whole unit of work."""
    deck = QuizDeck(user_id=test_user.id, title='Мои слова')
    db_session.add(deck)
    db_session.flush()
    test_user.default_study_deck_id = deck.id
    db_session.add(QuizDeckWord(deck_id=deck.id, word_id=word.id))
    db_session.commit()

    other = CollectionWords(english_word='staged', russian_word='до', level='A1')
    db_session.add(other)
    db_session.flush()

    monkeypatch.setattr(deck_utils, '_word_already_in_a_deck', lambda *_a, **_k: False)
    deck_utils.ensure_word_in_default_deck(test_user.id, word.id)
    db_session.commit()

    assert CollectionWords.query.filter_by(english_word='staged').count() == 1


def test_locked_reread_sees_a_deck_created_behind_our_back(db_session, test_user, word):
    """The re-read under the lock must come from the row, not the identity map.

    ``_get_or_create_default_deck`` reads the user once unlocked, and only then
    takes the lock. SQLAlchemy hands the locked query's row back through the
    instance already in the identity map *without overwriting attributes it has
    loaded*, so ``default_study_deck_id`` keeps reading as the stale ``None``
    the lock was taken to get past — and the competitor's deck is duplicated.

    Two halves reproduce the production state. The raw UPDATE stands in for the
    competitor: it moves the row without touching the ORM instance, exactly as
    a just-committed concurrent writer does. ``set_committed_value`` puts the
    pre-competitor value back into the instance as a *loaded* one — which is
    how the request already holds it, since Flask-Login loads ``current_user``
    from this session before any of this runs.
    """
    deck = QuizDeck(user_id=test_user.id, title='Мои слова')
    db_session.add(deck)
    db_session.flush()

    db_session.execute(
        text('UPDATE users SET default_study_deck_id = :deck WHERE id = :uid'),
        {'deck': deck.id, 'uid': test_user.id},
    )
    set_committed_value(test_user, 'default_study_deck_id', None)

    resolved = deck_utils._get_or_create_default_deck(test_user.id)

    assert resolved is not None
    assert resolved.id == deck.id
    assert QuizDeck.query.filter_by(user_id=test_user.id).count() == 1
