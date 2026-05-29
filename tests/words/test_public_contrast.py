"""Tests for the public contrast page (/contrast/<a>/<b>) and its sitemap entries."""
import uuid

import pytest

from app.utils.db import db
from app.words.models import CollectionWords, WordContrast
from app.words.routes import encode_word_slug


@pytest.fixture
def contrast_pair(db_session):
    suffix = uuid.uuid4().hex[:6]
    a = CollectionWords(
        english_word=f'contX {suffix}', russian_word='первое',
        item_type='word', level='A1', ipa_transcription='kɒntX',
    )
    b = CollectionWords(
        english_word=f'contY {suffix}', russian_word='второе',
        item_type='word', level='A1', ipa_transcription='kɒntY',
    )
    db_session.add_all([a, b])
    db_session.commit()
    low_id, high_id = sorted((a.id, b.id))
    row = WordContrast(
        word_a_id=low_id, word_b_id=high_id,
        note_ru='<b>contX</b> для X. <b>contY</b> для Y.',
    )
    db_session.add(row)
    db_session.commit()
    return row


def _canonical_url(contrast: WordContrast) -> str:
    a = contrast.word_a
    b = contrast.word_b
    return f'/contrast/{encode_word_slug(a.english_word)}/{encode_word_slug(b.english_word)}'


@pytest.mark.smoke
def test_public_contrast_page_returns_200(client, contrast_pair):
    resp = client.get(_canonical_url(contrast_pair))
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'vs' in html
    assert contrast_pair.word_a.english_word in html
    assert contrast_pair.word_b.english_word in html
    # Note must render with curated bold markup intact.
    assert '<b>contX</b>' in html


def test_public_contrast_reverse_order_301s_to_canonical(client, contrast_pair):
    """Visiting /contrast/B/A redirects to /contrast/A/B (where A is the
    smaller-id word) so PageRank consolidates on one URL."""
    a = contrast_pair.word_a
    b = contrast_pair.word_b
    reverse = f'/contrast/{encode_word_slug(b.english_word)}/{encode_word_slug(a.english_word)}'
    resp = client.get(reverse, follow_redirects=False)
    assert resp.status_code == 301
    assert _canonical_url(contrast_pair) in resp.headers['Location']


def test_public_contrast_404_for_missing_pair(client, db_session):
    """Two words without a contrast row → 404."""
    suffix = uuid.uuid4().hex[:6]
    a = CollectionWords(
        english_word=f'aloneA {suffix}', russian_word='первое',
        item_type='word', level='A1',
    )
    b = CollectionWords(
        english_word=f'aloneB {suffix}', russian_word='второе',
        item_type='word', level='A1',
    )
    db_session.add_all([a, b])
    db_session.commit()
    resp = client.get(
        f'/contrast/{encode_word_slug(a.english_word)}/{encode_word_slug(b.english_word)}'
    )
    assert resp.status_code == 404


def test_public_contrast_canonical_meta(client, contrast_pair):
    resp = client.get(_canonical_url(contrast_pair))
    html = resp.data.decode()
    assert '<link rel="canonical"' in html
    assert _canonical_url(contrast_pair) in html
    # FAQPage schema is emitted.
    assert 'FAQPage' in html


def test_contrast_appears_in_sitemap(client, contrast_pair):
    resp = client.get('/sitemap.xml')
    assert resp.status_code == 200
    xml = resp.data.decode()
    assert _canonical_url(contrast_pair) in xml


def test_word_page_links_to_contrast_detail(client, contrast_pair):
    """The «Не путай с» block on the word page must link to the standalone
    contrast page so crawlers can follow."""
    a = contrast_pair.word_a
    resp = client.get(f'/dictionary/{encode_word_slug(a.english_word)}')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert '/contrast/' in html
    assert _canonical_url(contrast_pair) in html


def test_og_contrast_route_returns_png(client, contrast_pair):
    a = contrast_pair.word_a
    b = contrast_pair.word_b
    url = f'/og/contrast/{encode_word_slug(a.english_word)}/{encode_word_slug(b.english_word)}.png'
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.mimetype == 'image/png'
    assert resp.data[:8] == b'\x89PNG\r\n\x1a\n'


def test_og_contrast_404_when_pair_missing(client, db_session):
    suffix = uuid.uuid4().hex[:6]
    a = CollectionWords(english_word=f'noogA {suffix}', russian_word='1', item_type='word', level='A1')
    b = CollectionWords(english_word=f'noogB {suffix}', russian_word='2', item_type='word', level='A1')
    db_session.add_all([a, b])
    db_session.commit()
    resp = client.get(
        f'/og/contrast/{encode_word_slug(a.english_word)}/{encode_word_slug(b.english_word)}.png'
    )
    assert resp.status_code == 404
