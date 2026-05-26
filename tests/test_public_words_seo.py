"""Tests for public word pages and SEO sitemap."""
import json
import re
import uuid
from urllib.parse import quote

import pytest

from app.words.models import CollectionWords, Topic


@pytest.fixture
def sample_word(db_session):
    """Create a sample word for testing."""
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'testword{suffix}',
        russian_word='тестовое слово',
        level='B1',
        frequency_rank=42,
        sentences='This is a test sentence.',
        item_type='word',
    )
    db_session.add(word)
    db_session.commit()
    return word


class TestPublicWordRoute:
    """Test GET /dictionary/<word_slug> public route."""

    def test_public_word_returns_200(self, client, sample_word):
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        assert response.status_code == 200

    def test_public_word_no_login_required(self, client, sample_word):
        """Public word page should not redirect to login."""
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        assert response.status_code == 200
        assert b'login' not in (response.headers.get('Location', '') or '').encode()

    def test_public_word_contains_word(self, client, sample_word):
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert sample_word.english_word in html
        assert sample_word.russian_word in html

    def test_public_word_has_og_tags(self, client, sample_word):
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert 'og:title' in html
        assert 'og:description' in html

    def test_public_word_has_title_meta_canonical_and_no_private_controls(
        self,
        app,
        client,
        sample_word,
    ):
        slug = sample_word.english_word.lower().replace(' ', '-')
        original_site_url = app.config.get('SITE_URL')
        app.config['SITE_URL'] = 'https://staging.llt-english.com'
        try:
            response = client.get(f'/dictionary/{slug}')
            html = response.data.decode()
        finally:
            app.config['SITE_URL'] = original_site_url

        assert response.status_code == 200
        # Title is built from `word.english_word` + level. Template at
        # app/templates/words/public_word.html renders
        # «<word> — перевод на русский, примеры, произношение | <level> английский».
        assert (
            f'<title>{sample_word.english_word} — перевод на русский, '
            f'примеры, произношение | {sample_word.level} английский</title>'
            in html
        )
        assert '<meta name="description" content="' in html
        assert sample_word.english_word in html
        assert sample_word.russian_word in html
        assert (
            f'<link rel="canonical" href="https://staging.llt-english.com/dictionary/{slug}">'
            in html
        )
        assert f'https://staging.llt-english.com/dictionary/{slug}' in html
        assert f'/words/{sample_word.id}' not in html
        assert 'Статус слова' not in html
        assert 'startLearningWord' not in html

    def test_public_word_json_ld_preserves_unescaped_text_values(self, app, client, db_session):
        suffix = uuid.uuid4().hex[:8]
        word = CollectionWords(
            english_word=f'quote"word{suffix}',
            russian_word='перевод "кавычки"',
            level='A1',
            item_type='word',
        )
        db_session.add(word)
        db_session.commit()

        original_site_url = app.config.get('SITE_URL')
        app.config['SITE_URL'] = 'https://staging.llt-english.com'
        try:
            response = client.get(f'/dictionary/{quote(word.english_word)}')
            html = response.data.decode()
        finally:
            app.config['SITE_URL'] = original_site_url

        assert response.status_code == 200
        match = re.search(
            r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
            html,
            re.S,
        )
        assert match is not None
        data = json.loads(match.group(1))
        assert data['name'] == word.english_word
        assert data['description'] == (
            f'{word.english_word} — перевод: {word.russian_word}. '
            f'Уровень {word.level}. Примеры, произношение и упражнения.'
        )
        expected_slug = quote(word.english_word, safe='')
        assert data['url'] == f'https://staging.llt-english.com/dictionary/{expected_slug}'

    def test_public_word_has_json_ld(self, client, sample_word):
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert 'application/ld+json' in html
        assert 'DefinedTerm' in html

    def test_public_word_has_cta(self, client, sample_word):
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert 'register' in html.lower() or 'auth/register' in html

    def test_public_word_404_for_nonexistent(self, client):
        response = client.get('/dictionary/nonexistentword99999')
        assert response.status_code == 404

    def test_public_word_shows_level(self, client, sample_word):
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert sample_word.level in html

    def test_public_word_shows_examples(self, client, sample_word):
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert 'test sentence' in html

    def test_public_word_uses_extended_collection_word_fields(self, client, db_session):
        suffix = uuid.uuid4().hex[:8]
        word = CollectionWords(
            english_word=f'student{suffix}',
            russian_word='студент',
            level='B1',
            frequency_rank=320,
            frequency_band=1,
            brown=1,
            get_download=1,
            listening=f'[sound:pronunciation_student{suffix}.mp3]',
            sentences='The student asked a clear question.',
            item_type='word',
            usage_context='Used for a person who studies at school or university.',
            ipa_transcription='ˈstjuːdənt',
            synonyms=[f'pupil{suffix}', f'learner{suffix}'],
            antonyms=[f'teacher{suffix}'],
            etymology='From Latin studere, meaning to be eager.',
        )
        related = CollectionWords(
            english_word=f'pupil{suffix}',
            russian_word='ученик, зрачок',
            level='B1',
            frequency_rank=380,
            frequency_band=1,
            item_type='word',
        )
        topic = Topic(name=f'Education {suffix}', description='Education vocabulary')
        topic.words.extend([word, related])
        db_session.add_all([word, related, topic])
        db_session.commit()

        response = client.get(f'/dictionary/{word.english_word}')
        html = response.data.decode()

        assert response.status_code == 200
        assert '/ˈstjuːdənt/' in html
        assert 'Top 1000' in html
        assert 'Brown corpus' not in html
        assert 'ID' not in html
        assert 'Used for a person who studies' in html
        assert f'pupil{suffix}' in html
        assert 'ученик' in html
        assert 'зрачок' not in html
        assert f'teacher{suffix}' in html
        assert 'From Latin studere' in html
        assert 'синоним' in html

    def test_public_word_filters_null_values_and_shows_common_article_error(self, client, db_session):
        word = CollectionWords(
            english_word='student',
            russian_word='студент, ученик',
            level='A1',
            frequency_band=1,
            sentences='I am a student.<br>Я студент.',
            item_type='word',
            usage_context='null',
            synonyms=['null', None, ''],
            antonyms=['null'],
            etymology='null',
        )
        db_session.add(word)
        db_session.commit()

        response = client.get('/dictionary/student')
        html = response.data.decode()

        assert response.status_code == 200
        assert 'Антонимы' not in html
        assert 'Синонимы' not in html
        assert 'Происхождение' not in html
        assert '>null<' not in html
        assert 'I am student.' in html
        assert 'I am a student.' in html

    def test_public_word_escapes_profile_and_related_word_text(self, client, db_session):
        suffix = uuid.uuid4().hex[:8]
        related = CollectionWords(
            english_word=f'relatedxss{suffix}',
            russian_word='<script>alert("related")</script>',
            level='A1',
            frequency_band=1,
            item_type='word',
        )
        word = CollectionWords(
            english_word=f'xsspublic{suffix}',
            russian_word='<script>alert("ru")</script>',
            level='A1',
            frequency_band=1,
            sentences='Example without markup.',
            item_type='word',
            usage_context='<img src=x onerror=alert(1)>',
            synonyms=[related.english_word, '<b>same</b>'],
            antonyms=['<svg onload=alert(1)>'],
            etymology='<iframe src=x></iframe>',
        )
        db_session.add_all([word, related])
        db_session.commit()

        response = client.get(f'/dictionary/{word.english_word}')
        html = response.data.decode()

        assert response.status_code == 200
        assert '<script>alert("ru")</script>' not in html
        assert '<script>alert("related")</script>' not in html
        assert '<img src=x onerror=alert(1)>' not in html
        assert '<b>same</b>' not in html
        assert '<svg onload=alert(1)>' not in html
        assert '<iframe src=x></iframe>' not in html
        assert '&lt;script&gt;alert' in html
        assert '&lt;img src=x onerror=alert(1)&gt;' in html
        assert '&lt;b&gt;same&lt;/b&gt;' in html

    def test_public_word_hides_empty_profile_sections_audio_and_private_controls(
        self,
        client,
        db_session,
    ):
        suffix = uuid.uuid4().hex[:8]
        word = CollectionWords(
            english_word=f'emptypublic{suffix}',
            russian_word='пустой профиль',
            level='B2',
            item_type='word',
        )
        db_session.add(word)
        db_session.commit()

        response = client.get(f'/dictionary/{word.english_word}')
        html = response.data.decode()

        assert response.status_code == 200
        assert 'Синонимы' not in html
        assert 'Антонимы' not in html
        assert 'Происхождение' not in html
        assert 'Произношение' not in html
        assert f'/words/{word.id}' not in html
        assert 'Статус слова' not in html

    def test_public_word_audio_url_uses_json_encoded_handler_argument(self, client, db_session):
        suffix = uuid.uuid4().hex[:8]
        word = CollectionWords(
            english_word=f'audioxss{suffix}',
            russian_word='аудио',
            level='A1',
            get_download=1,
            listening="[sound:bad');alert(1);//.mp3]",
            item_type='word',
        )
        db_session.add(word)
        db_session.commit()

        response = client.get(f'/dictionary/{word.english_word}')
        html = response.data.decode()

        assert response.status_code == 200
        assert "playAudio('" not in html
        assert 'onclick=\'playAudio("' in html


class TestPublicDictionaryRoute:
    """Test GET /dictionary public index route."""

    def test_public_dictionary_returns_200(self, client, sample_word):
        response = client.get('/dictionary')
        assert response.status_code == 200

    def test_public_dictionary_no_login_required(self, client, sample_word):
        response = client.get('/dictionary', follow_redirects=False)
        assert response.status_code == 200
        assert 'login' not in (response.headers.get('Location', '') or '').lower()

    def test_public_dictionary_contains_sample_word(self, client, sample_word):
        response = client.get('/dictionary')
        html = response.data.decode()
        assert sample_word.english_word in html
        assert sample_word.russian_word in html

    def test_public_dictionary_letter_page(self, client, sample_word):
        letter = sample_word.english_word[0].lower()
        response = client.get(f'/dictionary/letter/{letter}')
        html = response.data.decode()
        assert response.status_code == 200
        assert sample_word.english_word in html

    def test_public_dictionary_rejects_invalid_letter(self, client):
        response = client.get('/dictionary/letter/ab')
        assert response.status_code == 404


class TestSitemap:
    """Test sitemap.xml generation."""

    def test_sitemap_returns_xml(self, client):
        response = client.get('/sitemap.xml')
        assert response.status_code == 200
        assert 'application/xml' in response.content_type

    def test_sitemap_contains_root(self, app, client):
        response = client.get('/sitemap.xml')
        xml = response.data.decode()
        site_url = (app.config.get('SITE_URL') or 'https://llt-english.com').rstrip('/')
        assert f'<loc>{site_url}/</loc>' in xml

    def test_sitemap_contains_dictionary_words(self, client, sample_word):
        response = client.get('/sitemap.xml')
        xml = response.data.decode()
        slug = sample_word.english_word.lower().replace(' ', '-')
        assert f'/dictionary/{slug}' in xml

    def test_sitemap_contains_dictionary_index(self, client):
        response = client.get('/sitemap.xml')
        xml = response.data.decode()
        assert '/dictionary' in xml

    def test_sitemap_valid_xml_structure(self, client):
        response = client.get('/sitemap.xml')
        xml = response.data.decode()
        assert '<?xml version="1.0"' in xml
        assert '<urlset' in xml
        assert '</urlset>' in xml


class TestRobotsTxt:
    """Test robots.txt."""

    def test_robots_returns_text(self, client):
        response = client.get('/robots.txt')
        assert response.status_code == 200
        assert 'text/plain' in response.content_type

    def test_robots_contains_sitemap(self, client):
        response = client.get('/robots.txt')
        text = response.data.decode()
        assert 'Sitemap:' in text
        assert 'sitemap.xml' in text
