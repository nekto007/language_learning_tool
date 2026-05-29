"""Tests for OG image generation and routes."""
import io
import uuid

import pytest
from PIL import Image

from app.grammar_lab.models import GrammarTopic
from app.seo.og_image import OG_HEIGHT, OG_WIDTH, render_og_image
from app.words.models import CollectionWords


# ─── Service ────────────────────────────────────────────────────────────


def test_render_returns_png_of_expected_size(app):
    with app.app_context():
        data = render_og_image('word', 'pencil case', 'пенал', 'A1')
        assert data[:8] == b'\x89PNG\r\n\x1a\n'  # PNG magic
        img = Image.open(io.BytesIO(data))
        assert img.size == (OG_WIDTH, OG_HEIGHT)


def test_render_handles_cyrillic_subtitle(app):
    with app.app_context():
        data = render_og_image('grammar', 'Артикли', 'Articles', 'A1')
        img = Image.open(io.BytesIO(data))
        assert img.size == (OG_WIDTH, OG_HEIGHT)


def test_render_is_cached_to_disk(app, tmp_path, monkeypatch):
    """Second call with the same inputs reads from disk; mutating the file
    proves the cache was actually used (we get back the tampered bytes)."""
    with app.app_context():
        data_first = render_og_image('word', 'cache_check', 'кэш', 'A1')
        # Tamper the cached file so a re-render would visibly differ.
        from app.seo.og_image import _cache_dir, _cache_key
        path = f"{_cache_dir()}/{_cache_key('word', 'cache_check', 'кэш', 'A1')}.png"
        with open(path, 'rb') as fh:
            disk = fh.read()
        assert disk == data_first
        # Overwrite the cache contents and confirm the next call returns those bytes.
        sentinel = b'TAMPERED-OG-CACHE-CONTENT'
        with open(path, 'wb') as fh:
            fh.write(sentinel)
        data_second = render_og_image('word', 'cache_check', 'кэш', 'A1')
        assert data_second == sentinel


def test_render_handles_very_long_title(app):
    with app.app_context():
        long_title = 'Очень длинное название грамматической темы с кучей слов внутри'
        data = render_og_image('grammar', long_title, '', 'B2')
        assert data[:8] == b'\x89PNG\r\n\x1a\n'


# ─── Routes ─────────────────────────────────────────────────────────────


@pytest.fixture
def og_word_fixture(db_session):
    """Two-word english phrase so the slug round-trip (' '↔'_') is exercised."""
    suffix = uuid.uuid4().hex[:6]
    word = CollectionWords(
        english_word=f'ogword {suffix}',
        russian_word='тестовое слово',
        item_type='word',
        level='A1',
        ipa_transcription='x',
    )
    db_session.add(word)
    db_session.commit()
    return word


@pytest.fixture
def og_topic_fixture(db_session):
    suffix = uuid.uuid4().hex[:6]
    topic = GrammarTopic(
        slug=f'og-topic-{suffix}',
        title='Test Topic',
        title_ru='Тестовая тема',
        level='A1',
        order=1,
        content={'introduction': 'intro'},
    )
    db_session.add(topic)
    db_session.commit()
    return topic


def test_og_word_route_returns_png(client, og_word_fixture):
    from app.words.routes import encode_word_slug
    slug = encode_word_slug(og_word_fixture.english_word)
    resp = client.get(f'/og/word/{slug}.png')
    assert resp.status_code == 200
    assert resp.mimetype == 'image/png'
    assert resp.data[:8] == b'\x89PNG\r\n\x1a\n'


def test_og_word_route_404_for_missing(client):
    resp = client.get('/og/word/no-such-word-xyz.png')
    assert resp.status_code == 404


def test_og_grammar_route_returns_png(client, og_topic_fixture):
    resp = client.get(f'/og/grammar/{og_topic_fixture.slug}.png')
    assert resp.status_code == 200
    assert resp.mimetype == 'image/png'


def test_og_grammar_route_404_for_missing(client):
    resp = client.get('/og/grammar/nope.png')
    assert resp.status_code == 404


def test_word_page_og_image_meta_points_to_route(client, og_word_fixture):
    """public_word.html must declare og:image as our dynamic route."""
    from app.words.routes import encode_word_slug
    slug = encode_word_slug(og_word_fixture.english_word)
    resp = client.get(f'/dictionary/{slug}')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert f'/og/word/{slug}.png' in html


def test_grammar_topic_og_image_meta_points_to_route(client, og_topic_fixture):
    resp = client.get(f'/grammar-lab/topic/{og_topic_fixture.slug}')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert f'/og/grammar/{og_topic_fixture.slug}.png' in html
