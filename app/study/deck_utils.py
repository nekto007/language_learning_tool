from app.utils.db import db


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


def ensure_word_in_default_deck(user_id: int, word_id: int, user_word_id: int = None) -> None:
    """Add word to user's default deck if it's not already in any of user's decks.

    Creates a default deck ('Мои слова') if the user doesn't have one yet.
    """
    from app.study.models import QuizDeck, QuizDeckWord
    from app.auth.models import User

    existing = QuizDeckWord.query.join(QuizDeck).filter(
        QuizDeck.user_id == user_id,
        QuizDeckWord.word_id == word_id
    ).first()
    if existing:
        return

    user = User.query.get(user_id)
    deck = QuizDeck.query.get(user.default_study_deck_id) if user.default_study_deck_id else None

    if not deck or deck.user_id != user_id:
        deck = QuizDeck(user_id=user_id, title='Мои слова')
        db.session.add(deck)
        db.session.flush()
        user.default_study_deck_id = deck.id

    dw = QuizDeckWord(deck_id=deck.id, word_id=word_id, user_word_id=user_word_id)
    db.session.add(dw)
