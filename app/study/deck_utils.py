import logging

from sqlalchemy.exc import IntegrityError

from app.utils.db import db

logger = logging.getLogger(__name__)


def get_daily_plan_mix_word_ids(user_id: int) -> list[int]:
    """Return a mixed pool of word IDs from all of the user's decks.

    The daily plan uses this to build a shared review/practice block across
    multiple decks instead of binding itself to a single default deck.
    """
    from app.study.models import QuizDeck, QuizDeckWord

    rows = (
        db.session.query(QuizDeckWord.word_id)
        .join(QuizDeck, QuizDeck.id == QuizDeckWord.deck_id)
        .filter(
            QuizDeck.user_id == user_id,
            QuizDeckWord.word_id.isnot(None),
        )
        .distinct()
        .all()
    )
    return [word_id for (word_id,) in rows]


def _word_already_in_a_deck(user_id: int, word_id: int) -> bool:
    """Is this word in any deck of the user's already?"""
    from app.study.models import QuizDeck, QuizDeckWord

    return db.session.query(
        QuizDeckWord.query.join(QuizDeck).filter(
            QuizDeck.user_id == user_id,
            QuizDeckWord.word_id == word_id,
        ).exists()
    ).scalar()


def _get_or_create_default_deck(user_id: int):
    """Return the user's default deck, creating «Мои слова» on first use.

    The read-then-create pair is serialised on the ``users`` row: two parallel
    «добавить в изучение» requests (double-click, retry) would otherwise both
    see ``default_study_deck_id`` empty and create a deck each, leaving the
    learner with two identically named decks and their words split between
    them. The lock is only taken on the create path, and only until the caller
    commits.
    """
    from app.auth.models import User
    from app.study.models import QuizDeck

    user = User.query.get(user_id)
    if user is None:
        return None

    deck = QuizDeck.query.get(user.default_study_deck_id) if user.default_study_deck_id else None
    if deck is not None and deck.user_id == user_id:
        return deck

    # ``populate_existing`` is what makes this a re-read. The unlocked
    # ``get`` above put the row in the identity map, and by default a later
    # query reuses that instance without overwriting loaded attributes — so
    # ``default_study_deck_id`` would still hold the stale ``None`` the lock
    # was taken to get past, and we would create the second deck anyway.
    user = (
        db.session.query(User)
        .filter(User.id == user_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if user is None:
        return None

    # Re-read under the lock: a competitor may have created it while we waited.
    deck = QuizDeck.query.get(user.default_study_deck_id) if user.default_study_deck_id else None
    if deck is not None and deck.user_id == user_id:
        return deck

    deck = QuizDeck(user_id=user_id, title='Мои слова')
    db.session.add(deck)
    db.session.flush()
    user.default_study_deck_id = deck.id
    return deck


def ensure_word_in_default_deck(user_id: int, word_id: int, user_word_id: int = None) -> None:
    """Add word to user's default deck if it's not already in any of user's decks.

    Creates a default deck ('Мои слова') if the user doesn't have one yet.

    Flush only — the caller commits. Membership is idempotent: the check and
    the insert are not atomic, so a concurrent writer can land the same row
    first and trip ``uix_deck_word``. That collision means the word already is
    where we wanted it, so it is swallowed rather than surfaced as a 500 on
    every bulk «добавить в изучение» retry. The insert runs in a savepoint so
    the failure does not poison work the caller has already staged.
    """
    from app.study.models import QuizDeckWord

    if _word_already_in_a_deck(user_id, word_id):
        return

    deck = _get_or_create_default_deck(user_id)
    if deck is None:
        return

    try:
        with db.session.begin_nested():
            db.session.add(
                QuizDeckWord(deck_id=deck.id, word_id=word_id, user_word_id=user_word_id)
            )
    except IntegrityError:
        logger.debug(
            'ensure_word_in_default_deck: word %s already in deck %s for user %s',
            word_id, deck.id, user_id,
        )
