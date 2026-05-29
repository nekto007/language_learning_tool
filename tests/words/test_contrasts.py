"""Tests for word contrast pairs (model, seed loader, public word page)."""
import json
import os
import uuid

import pytest

from app.words.models import CollectionWords, WordContrast, get_contrasts_for_word
from app.words.seed_contrasts import seed_word_contrasts


@pytest.fixture
def two_public_words(db_session):
    suffix = uuid.uuid4().hex[:6]
    a = CollectionWords(
        english_word=f'pairA {suffix}', russian_word='первое',
        item_type='word', level='A1', ipa_transcription='x',
    )
    b = CollectionWords(
        english_word=f'pairB {suffix}', russian_word='второе',
        item_type='word', level='A1', ipa_transcription='y',
    )
    db_session.add_all([a, b])
    db_session.commit()
    return a, b


# ─── Model ──────────────────────────────────────────────────────────────


def test_contrast_other_word(db_session, two_public_words):
    a, b = two_public_words
    low_id, high_id = sorted((a.id, b.id))
    row = WordContrast(word_a_id=low_id, word_b_id=high_id, note_ru='diff.')
    db_session.add(row)
    db_session.commit()
    assert row.other_word(a.id).id == b.id
    assert row.other_word(b.id).id == a.id
    assert row.other_word(999_999) is None


def test_get_contrasts_for_word_returns_both_sides(db_session, two_public_words):
    a, b = two_public_words
    low_id, high_id = sorted((a.id, b.id))
    row = WordContrast(word_a_id=low_id, word_b_id=high_id, note_ru='diff.')
    db_session.add(row)
    db_session.commit()
    contrasts_for_a = get_contrasts_for_word(a.id, db_session)
    contrasts_for_b = get_contrasts_for_word(b.id, db_session)
    assert len(contrasts_for_a) == 1
    assert len(contrasts_for_b) == 1


# ─── Seed loader ────────────────────────────────────────────────────────


def test_seed_loads_pairs_and_is_idempotent(db_session, two_public_words, tmp_path):
    a, b = two_public_words
    seed_file = tmp_path / 'contrasts.json'
    seed_file.write_text(json.dumps([
        {'a': a.english_word, 'b': b.english_word, 'note': 'Curated diff.'},
    ]), encoding='utf-8')

    created, skipped, missing = seed_word_contrasts(path=str(seed_file))
    assert created == 1
    assert skipped == 0
    assert missing == 0

    # Re-run — must NOT create a duplicate.
    created2, skipped2, missing2 = seed_word_contrasts(path=str(seed_file))
    assert created2 == 0
    assert skipped2 == 1


def test_seed_skips_missing_words(db_session, two_public_words, tmp_path):
    a, _ = two_public_words
    seed_file = tmp_path / 'contrasts.json'
    seed_file.write_text(json.dumps([
        {'a': a.english_word, 'b': 'word-not-in-db-xyz', 'note': 'd'},
        {'a': 'nope-1', 'b': 'nope-2', 'note': 'd'},
    ]), encoding='utf-8')

    created, skipped, missing = seed_word_contrasts(path=str(seed_file))
    assert created == 0
    assert missing == 2


def test_seed_normalises_pair_ordering(db_session, two_public_words, tmp_path):
    """Whichever side the JSON puts first, the row must store word_a < word_b."""
    a, b = two_public_words
    high, low = (a, b) if a.id > b.id else (b, a)
    seed_file = tmp_path / 'contrasts.json'
    # Put the higher-id word first in the JSON.
    seed_file.write_text(json.dumps([
        {'a': high.english_word, 'b': low.english_word, 'note': 'reversed'},
    ]), encoding='utf-8')

    seed_word_contrasts(path=str(seed_file))
    row = WordContrast.query.first()
    assert row.word_a_id < row.word_b_id


# ─── Word page integration ──────────────────────────────────────────────


def test_word_page_shows_contrast_section(client, db_session, two_public_words):
    from app.words.routes import encode_word_slug
    a, b = two_public_words
    low_id, high_id = sorted((a.id, b.id))
    db_session.add(WordContrast(
        word_a_id=low_id, word_b_id=high_id,
        note_ru='<b>pairA</b> используется для X. <b>pairB</b> для Y.',
    ))
    db_session.commit()

    resp = client.get(f'/dictionary/{encode_word_slug(a.english_word)}')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'Не путай с' in html
    # Other side of the pair must be rendered with its translation.
    assert b.english_word in html
    assert 'второе' in html


def test_word_page_without_contrasts_omits_section(client, db_session, two_public_words):
    """Absence of contrast rows must hide the rendered section (HTML comment
    in the template still appears, that's harmless — we look for the visible
    heading wrapper)."""
    from app.words.routes import encode_word_slug
    a, _ = two_public_words
    resp = client.get(f'/dictionary/{encode_word_slug(a.english_word)}')
    assert resp.status_code == 200
    html = resp.data.decode()
    # The visible heading lives inside an h2 — its presence means the card rendered.
    assert '<h2 class="pubw-card__title">Не путай с</h2>' not in html
