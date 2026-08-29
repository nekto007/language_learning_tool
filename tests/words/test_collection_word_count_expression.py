"""Collection.word_count must be usable as a SQL expression.

The hybrid's `@expression` half referenced a name that does not exist in the
module (`collection_words` — the words table, which has no `collection_id`),
so any query that sorted or filtered on `Collection.word_count` raised
NameError at statement-build time. Only the Python-side half was ever
exercised, which is why nothing caught it.
"""
from app.utils.db import db
from app.words.models import Collection, CollectionWordLink, CollectionWords


def test_word_count_expression_builds_and_runs(db_session, test_user):
    collection = Collection(name='Counting collection', created_by=test_user.id)
    db_session.add(collection)
    db_session.flush()

    for eng in ('alpha', 'beta', 'gamma'):
        word = CollectionWords(english_word=eng, russian_word='x', level='A1')
        db_session.add(word)
        db_session.flush()
        db_session.add(
            CollectionWordLink(collection_id=collection.id, word_id=word.id)
        )
    db_session.commit()

    row = (
        db.session.query(Collection.id, Collection.word_count.label('total'))
        .filter(Collection.id == collection.id)
        .one()
    )
    assert row.total == 3

    # Ordering must build too — that is what the admin list would use.
    ordered = (
        db.session.query(Collection.id)
        .order_by(Collection.word_count.desc())
        .limit(1)
        .all()
    )
    assert ordered


def test_word_count_python_side_still_counts(db_session, test_user):
    collection = Collection(name='Python side collection', created_by=test_user.id)
    db_session.add(collection)
    db_session.flush()
    word = CollectionWords(english_word='delta', russian_word='x', level='A1')
    db_session.add(word)
    db_session.flush()
    db_session.add(CollectionWordLink(collection_id=collection.id, word_id=word.id))
    db_session.commit()

    assert collection.word_count == 1
