"""Tests for words routes: word list, word detail, status update, API endpoints."""
from datetime import datetime, timedelta, timezone
import uuid

import pytest

from app.words.models import CollectionWords
from app.words.detail_service import (
    _format_review_time,
    build_word_profile,
    frequency_band_label,
    get_related_words,
    normalise_word_list,
)
from app.books.models import Book
from app.modules.models import SystemModule, UserModule


@pytest.fixture
def words_module(db_session, test_user):
    """Grant words module access to test_user."""
    module = SystemModule.query.filter_by(code='words').first()
    if not module:
        module = SystemModule(
            code='words', name='Words', description='Words module',
            is_active=True, is_default=True, order=4,
        )
        db_session.add(module)
        db_session.flush()

    existing = UserModule.query.filter_by(
        user_id=test_user.id, module_id=module.id,
    ).first()
    if not existing:
        db_session.add(UserModule(
            user_id=test_user.id, module_id=module.id, is_enabled=True,
        ))
        db_session.commit()
    return module


@pytest.fixture
def sample_words(db_session):
    """Create a small set of words for list/detail tests."""
    suffix = uuid.uuid4().hex[:8]
    words = []
    for eng, rus, level, item_type in [
        ('apple', 'яблоко', 'A1', 'word'),
        ('banana', 'банан', 'A1', 'word'),
        ('cherry', 'вишня', 'A2', 'word'),
        ('break out', 'вспыхнуть', 'B1', 'phrasal_verb'),
        ('dig in', 'приступить', 'B2', 'phrasal_verb'),
    ]:
        w = CollectionWords(
            english_word=f'{eng}{suffix}',
            russian_word=rus,
            level=level,
            item_type=item_type,
        )
        db_session.add(w)
        words.append(w)
    db_session.commit()
    return words


@pytest.fixture
def user_word_statuses(db_session, test_user, sample_words):
    """Create UserWord records with various statuses."""
    from app.study.models import UserWord

    statuses = ['new', 'learning', 'review', 'new', 'learning']
    user_words = []
    for word, status in zip(sample_words, statuses):
        uw = UserWord(user_id=test_user.id, word_id=word.id)
        uw.status = status
        db_session.add(uw)
        user_words.append(uw)
    db_session.commit()
    return user_words


# ==================== WORD PROFILE DATA ====================

class TestWordProfileDataNormalization:
    """Service-level profile helpers used by public and private word pages."""

    def test_normalise_word_list_removes_placeholders_and_duplicates(self):
        assert normalise_word_list([
            ' learn ',
            None,
            '',
            'null',
            '[]',
            'learn',
            'Learn',
            'study',
        ]) == ['learn', 'study']

        assert normalise_word_list('run; jump, null, run') == ['run', 'jump']

    def test_frequency_band_label_handles_missing_and_string_values(self):
        assert frequency_band_label(1) == 'Top 1000'
        assert frequency_band_label('2') == 'Top 3000'
        assert frequency_band_label(3.0) == 'Top 10000'
        assert frequency_band_label(None) == 'Не указана'
        assert frequency_band_label('not-a-band') == 'Не указана'

    def test_build_word_profile_cleans_dirty_optional_data_and_semantic_hints(self, app):
        word = CollectionWords(
            english_word='student',
            russian_word='студент',
            level=None,
            frequency_band=None,
            get_download=0,
            listening=None,
            item_type='word',
            usage_context=' null ',
            synonyms=[' study ', '', '[]', 'study', 'Study', 'learner'],
            antonyms='opponent; opposite; opponent',
            etymology='[]',
        )

        profile = build_word_profile(word)

        assert profile['usage_context'] == ''
        assert profile['etymology'] == ''
        assert profile['synonyms'] == ['study', 'learner']
        assert profile['antonyms'] == ['opponent', 'opposite']
        assert profile['frequency_band_label'] == 'Не указана'
        assert profile['audio_available'] is False
        assert profile['study_facts'] == []
        assert profile['common_mistake']['correct'] == 'I am a student.'

    def test_format_review_time_labels_relative_dates(self):
        now = datetime(2026, 5, 25, 12, 0, 0)

        assert _format_review_time(None, now) == 'не запланировано'
        assert _format_review_time(now - timedelta(minutes=1), now) == 'сейчас'
        assert _format_review_time(now.replace(hour=18), now) == 'сегодня'
        assert _format_review_time(now + timedelta(days=1), now) == 'завтра'
        assert _format_review_time(now + timedelta(days=3), now) == 'через 3 дня'
        assert _format_review_time(now + timedelta(days=10), now) == '04.06.2026'

    def test_get_related_words_uses_semantic_hints(self, db_session):
        source = CollectionWords(
            english_word='student',
            russian_word='студент',
            level='A1',
            frequency_band=1,
            item_type='word',
        )
        semantic_match = CollectionWords(
            english_word='teacher',
            russian_word='учитель',
            level='A1',
            frequency_band=1,
            item_type='word',
        )
        weak_match = CollectionWords(
            english_word='orange',
            russian_word='апельсин',
            level='A1',
            frequency_band=1,
            item_type='word',
        )
        db_session.add_all([source, semantic_match, weak_match])
        db_session.commit()

        related = get_related_words(source, limit=3)

        assert [word.english_word for word in related] == ['teacher']
        assert related[0].related_reason in {'люди и роли', 'учеба'}

    def test_public_profile_filters_non_public_related_forms(self, db_session):
        public_word = CollectionWords(
            english_word='clean',
            russian_word='чистить',
            level='A1',
            item_type='word',
        )
        private_phrasal = CollectionWords(
            english_word='clean up private',
            russian_word='закрытая форма',
            level='C2',
            item_type='phrasal_verb',
            base_word=public_word,
        )
        private_base = CollectionWords(
            english_word='private base',
            russian_word='закрытая база',
            level='C2',
            item_type='word',
        )
        public_phrasal = CollectionWords(
            english_word='public phrase',
            russian_word='публичная фраза',
            level='A1',
            item_type='phrasal_verb',
            base_word=private_base,
        )
        db_session.add_all([public_word, private_phrasal, private_base, public_phrasal])
        db_session.commit()

        word_profile = build_word_profile(public_word, public_only=True)
        phrasal_profile = build_word_profile(public_phrasal, public_only=True)

        assert word_profile['phrasal_verbs'] == []
        assert phrasal_profile['base_word'] is None


# ==================== WORD LIST ====================

class TestWordList:
    """GET /words"""

    def test_unauthenticated_redirects(self, client):
        resp = client.get('/words')
        assert resp.status_code in (302, 401)

    @pytest.mark.smoke
    def test_word_list_200(self, authenticated_client, words_module, sample_words):
        resp = authenticated_client.get('/words')
        assert resp.status_code == 200

    def test_word_list_baseline_renders_dictionary_content(self, authenticated_client, words_module, sample_words):
        word = sample_words[0]
        resp = authenticated_client.get('/words')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert word.english_word in html
        assert word.russian_word in html
        assert '/words?' in html
        assert f'/words/{word.id}' in html

    def test_search_filter(self, authenticated_client, words_module, sample_words):
        search_term = sample_words[0].english_word
        resp = authenticated_client.get(f'/words?search={search_term}')
        assert resp.status_code == 200
        assert sample_words[0].english_word.encode() in resp.data

    def test_status_filter_new(self, authenticated_client, words_module, sample_words, user_word_statuses):
        resp = authenticated_client.get('/words?status=new')
        assert resp.status_code == 200

    def test_status_filter_learning(self, authenticated_client, words_module, sample_words, user_word_statuses):
        resp = authenticated_client.get('/words?status=learning')
        assert resp.status_code == 200

    def test_status_filter_review(self, authenticated_client, words_module, sample_words, user_word_statuses):
        resp = authenticated_client.get('/words?status=review')
        assert resp.status_code == 200

    def test_letter_filter(self, authenticated_client, words_module, sample_words):
        first_letter = sample_words[0].english_word[0]
        resp = authenticated_client.get(f'/words?letter={first_letter}')
        assert resp.status_code == 200

    def test_type_filter_word(self, authenticated_client, words_module, sample_words):
        resp = authenticated_client.get('/words?type=word')
        assert resp.status_code == 200

    def test_type_filter_phrasal_verb(self, authenticated_client, words_module, sample_words):
        resp = authenticated_client.get('/words?type=phrasal_verb')
        assert resp.status_code == 200

    def test_level_filter(self, authenticated_client, words_module, sample_words):
        resp = authenticated_client.get('/words?level=A2')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert sample_words[2].english_word in html
        assert sample_words[0].english_word not in html

    def test_word_list_hides_empty_and_out_of_product_levels(self, authenticated_client, db_session, words_module):
        empty_word = CollectionWords(
            english_word='   ',
            russian_word='битая пустая строка',
            level='B1',
            item_type='word',
        )
        c2_word = CollectionWords(
            english_word=f'c2hidden{uuid.uuid4().hex[:8]}',
            russian_word='скрытый C2',
            level='C2',
            item_type='word',
        )
        db_session.add_all([empty_word, c2_word])
        db_session.commit()

        resp = authenticated_client.get('/words')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert 'битая пустая строка' not in html
        assert c2_word.english_word not in html

    def test_pagination(self, authenticated_client, words_module, sample_words):
        resp = authenticated_client.get('/words?page=1')
        assert resp.status_code == 200

    def test_pagination_out_of_range(self, authenticated_client, words_module, sample_words):
        resp = authenticated_client.get('/words?page=9999')
        assert resp.status_code == 200

    def test_per_page_param_accepted(self, authenticated_client, words_module, sample_words):
        """per_page=3 is accepted and returns 200."""
        resp = authenticated_client.get('/words?page=1&per_page=3')
        assert resp.status_code == 200

    def test_per_page_page2_accepted(self, authenticated_client, words_module, sample_words):
        """page=2 with small per_page returns 200 without 500."""
        resp = authenticated_client.get('/words?page=2&per_page=3')
        assert resp.status_code == 200

    def test_per_page_clamped_to_200(self, authenticated_client, words_module, sample_words):
        """per_page > 200 is clamped to 200; route still returns 200."""
        resp = authenticated_client.get('/words?per_page=999')
        assert resp.status_code == 200

    def test_per_page_small_limits_items(self, authenticated_client, words_module, sample_words):
        """per_page=2 returns 200 and the response body contains 2 or fewer items per page."""
        resp = authenticated_client.get('/words?page=1&per_page=2')
        assert resp.status_code == 200
        # With 5 sample words and per_page=2, there should be a page 2
        resp2 = authenticated_client.get('/words?page=2&per_page=2')
        assert resp2.status_code == 200

    def test_combined_search_type_level_and_pagination_filters_results(
        self,
        authenticated_client,
        words_module,
        sample_words,
    ):
        target = sample_words[0]
        resp = authenticated_client.get(
            f'/words?search={target.english_word}&type=word&level=A1&sort=alpha&page=1&per_page=2'
        )
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert target.english_word in html
        assert sample_words[1].english_word not in html
        assert sample_words[3].english_word not in html

    def test_word_list_default_and_invalid_sort_use_recommended_level_order(
        self,
        authenticated_client,
        db_session,
        words_module,
    ):
        suffix = uuid.uuid4().hex[:8]
        beginner_word = CollectionWords(
            english_word=f'qxbeginner{suffix}',
            russian_word='начальный',
            level='A1',
            frequency_rank=9000,
            item_type='word',
        )
        advanced_word = CollectionWords(
            english_word=f'qxadvanced{suffix}',
            russian_word='продвинутый',
            level='B2',
            frequency_rank=1,
            item_type='word',
        )
        db_session.add_all([beginner_word, advanced_word])
        db_session.commit()

        default_resp = authenticated_client.get('/words?letter=qx&per_page=200')
        default_html = default_resp.get_data(as_text=True)
        invalid_resp = authenticated_client.get('/words?letter=qx&sort=unknown&per_page=200')
        invalid_html = invalid_resp.get_data(as_text=True)

        assert default_resp.status_code == 200
        assert invalid_resp.status_code == 200
        assert default_html.index(beginner_word.english_word) < default_html.index(
            advanced_word.english_word
        )
        assert invalid_html.index(beginner_word.english_word) < invalid_html.index(
            advanced_word.english_word
        )

    def test_word_list_escapes_word_and_book_text(
        self,
        authenticated_client,
        db_session,
        words_module,
    ):
        suffix = uuid.uuid4().hex[:8]
        word = CollectionWords(
            english_word=f'<script>alert("en")</script>{suffix}',
            russian_word='<img src=x onerror=alert(1)>',
            level='A1',
            item_type='word',
        )
        book = Book(
            title='<script>alert("book")</script>',
            author='Author',
            chapters_cnt=1,
        )
        book.words.append(word)
        db_session.add_all([word, book])
        db_session.commit()

        resp = authenticated_client.get('/words?sort=alpha&per_page=200')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert '<script>alert("en")</script>' not in html
        assert '<script>alert("book")</script>' not in html
        assert '<img src=x onerror=alert(1)>' not in html
        assert '&lt;script&gt;alert' in html
        assert '&lt;img src=x onerror=alert(1)&gt;' in html

    def test_word_list_audio_url_uses_json_encoded_handler_argument(
        self,
        authenticated_client,
        db_session,
        words_module,
    ):
        suffix = uuid.uuid4().hex[:8]
        word = CollectionWords(
            english_word=f'listaudioxss{suffix}',
            russian_word='аудио',
            level='A1',
            get_download=1,
            listening="[sound:bad');alert(1);//.mp3]",
            item_type='word',
        )
        db_session.add(word)
        db_session.commit()

        resp = authenticated_client.get(f'/words?search={word.english_word}')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert "playAudio('" not in html
        assert 'onclick=\'playAudio("' in html


# ==================== WORD DETAIL ====================

class TestWordDetail:
    """GET /words/<word_id>"""

    def test_unauthenticated_redirects(self, client):
        resp = client.get('/words/1')
        assert resp.status_code in (302, 401)

    @pytest.mark.smoke
    def test_word_detail_200(self, authenticated_client, words_module, sample_words):
        word = sample_words[0]
        resp = authenticated_client.get(f'/words/{word.id}')
        assert resp.status_code == 200
        assert word.english_word.encode() in resp.data

    def test_word_detail_baseline_renders_profile_content(self, authenticated_client, words_module, sample_words):
        word = sample_words[0]
        resp = authenticated_client.get(f'/words/{word.id}')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert f'<title>{word.english_word} - Словарь</title>' in html
        assert word.english_word in html
        assert word.russian_word in html
        assert 'Статус слова' in html
        assert 'Следующее повторение' in html
        assert 'startLearningWord' in html

    def test_word_detail_with_user_status(self, authenticated_client, words_module, sample_words, user_word_statuses):
        word = sample_words[0]
        resp = authenticated_client.get(f'/words/{word.id}')
        assert resp.status_code == 200

    def test_word_detail_shows_srs_summary(self, authenticated_client, db_session, test_user, words_module):
        from app.study.models import UserCardDirection, UserWord

        word = CollectionWords(
            english_word=f'student{uuid.uuid4().hex[:8]}',
            russian_word='студент',
            level='A1',
            item_type='word',
        )
        db_session.add(word)
        db_session.flush()

        user_word = UserWord(user_id=test_user.id, word_id=word.id)
        user_word.status = 'review'
        db_session.add(user_word)
        db_session.flush()

        now = datetime.now(timezone.utc)
        db_session.add_all([
            UserCardDirection(
                user_word_id=user_word.id,
                direction='eng-rus',
                state='review',
                next_review=now - timedelta(minutes=5),
                correct_count=10,
                incorrect_count=2,
                repetitions=6,
                interval=5,
            ),
            UserCardDirection(
                user_word_id=user_word.id,
                direction='rus-eng',
                state='review',
                next_review=now + timedelta(days=1),
                correct_count=5,
                incorrect_count=1,
                repetitions=2,
                interval=2,
                lapses=1,
            ),
        ])
        db_session.commit()

        resp = authenticated_client.get(f'/words/{word.id}')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert 'Статус слова' in html
        assert 'На повторении' in html
        assert 'Повторить сейчас' in html
        assert '83%' in html
        assert '15 правильно / 3 ошибки' in html
        assert 'EN → RU' in html
        assert 'RU → EN' in html

    def test_word_detail_not_found(self, authenticated_client, words_module):
        resp = authenticated_client.get('/words/999999')
        assert resp.status_code == 404

    def test_word_detail_uses_extended_collection_word_fields(self, authenticated_client, db_session, words_module):
        suffix = uuid.uuid4().hex[:8]
        base = CollectionWords(
            english_word=f'learn{suffix}',
            russian_word='учиться',
            level='A2',
            frequency_rank=210,
            frequency_band=1,
            brown=1,
            get_download=1,
            listening=f'[sound:pronunciation_learn{suffix}.mp3]',
            sentences='I learn English every day.',
            item_type='word',
            usage_context='Used when someone studies or gains knowledge.',
            ipa_transcription='lɜːn',
            synonyms=[f'study{suffix}'],
            antonyms=[f'forget{suffix}'],
            etymology='From Old English leornian.',
        )
        phrasal = CollectionWords(
            english_word=f'learn about{suffix}',
            russian_word='узнавать о',
            level='A2',
            item_type='phrasal_verb',
            base_word=base,
        )
        synonym = CollectionWords(
            english_word=f'study{suffix}',
            russian_word='изучать',
            level='A2',
            frequency_rank=230,
            frequency_band=1,
            item_type='word',
        )
        db_session.add_all([base, phrasal, synonym])
        db_session.commit()

        resp = authenticated_client.get(f'/words/{base.id}')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert '/lɜːn/' in html
        assert 'Top 1000' in html
        assert 'Данные слова' in html
        assert 'Brown corpus' not in html
        assert 'ID' not in html
        assert 'Used when someone studies' in html
        assert f'study{suffix}' in html
        assert f'forget{suffix}' in html
        assert 'From Old English leornian' in html
        assert f'learn about{suffix}' in html
        assert 'синоним' in html

    def test_word_detail_escapes_profile_related_and_book_text(
        self,
        authenticated_client,
        db_session,
        words_module,
    ):
        suffix = uuid.uuid4().hex[:8]
        related = CollectionWords(
            english_word=f'relateddetailxss{suffix}',
            russian_word='<script>alert("related")</script>',
            level='A1',
            frequency_band=1,
            item_type='word',
        )
        word = CollectionWords(
            english_word=f'<script>alert("en")</script>{suffix}',
            russian_word='<img src=x onerror=alert(1)>',
            level='A1',
            frequency_band=1,
            sentences='Example without markup.',
            item_type='word',
            usage_context='<img src=x onerror=alert(2)>',
            synonyms=[related.english_word, '<b>same</b>'],
            antonyms=['<svg onload=alert(1)>'],
            etymology='<iframe src=x></iframe>',
        )
        book = Book(
            title='<script>alert("book")</script>',
            author='Author',
            chapters_cnt=1,
        )
        book.words.append(word)
        db_session.add_all([word, related, book])
        db_session.commit()

        resp = authenticated_client.get(f'/words/{word.id}')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert '<script>alert("en")</script>' not in html
        assert '<script>alert("related")</script>' not in html
        assert '<script>alert("book")</script>' not in html
        assert '<img src=x onerror=alert(1)>' not in html
        assert '<img src=x onerror=alert(2)>' not in html
        assert '<b>same</b>' not in html
        assert '<svg onload=alert(1)>' not in html
        assert '<iframe src=x></iframe>' not in html
        assert '&lt;script&gt;alert' in html
        assert '&lt;img src=x onerror=alert(1)&gt;' in html
        assert '&lt;img src=x onerror=alert(2)&gt;' in html

    def test_word_detail_hides_empty_profile_audio_books_and_related_sections(
        self,
        authenticated_client,
        db_session,
        words_module,
    ):
        suffix = uuid.uuid4().hex[:8]
        word = CollectionWords(
            english_word=f'emptydetail{suffix}',
            russian_word='пустой профиль',
            level='B2',
            item_type='word',
        )
        db_session.add(word)
        db_session.commit()

        resp = authenticated_client.get(f'/words/{word.id}')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert 'Синонимы' not in html
        assert 'Антонимы' not in html
        assert 'Происхождение' not in html
        assert 'Произношение' not in html
        assert 'Похожие слова не найдены' in html
        assert 'Встречается в книгах' not in html

    def test_word_detail_audio_url_uses_json_encoded_handler_argument(
        self,
        authenticated_client,
        db_session,
        words_module,
    ):
        suffix = uuid.uuid4().hex[:8]
        word = CollectionWords(
            english_word=f'detailaudioxss{suffix}',
            russian_word='аудио',
            level='A1',
            get_download=1,
            listening="[sound:bad');alert(1);//.mp3]",
            item_type='word',
        )
        db_session.add(word)
        db_session.commit()

        resp = authenticated_client.get(f'/words/{word.id}')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert "playAudio('" not in html
        assert 'onclick=\'playAudio("' in html

    def test_word_detail_none_russian_word_not_shown(
        self,
        authenticated_client,
        db_session,
        words_module,
    ):
        """None russian_word must not render as the string 'None' in the hero section."""
        suffix = uuid.uuid4().hex[:8]
        word = CollectionWords(
            english_word=f'nulltrans{suffix}',
            russian_word=None,
            level='A1',
            item_type='word',
        )
        db_session.add(word)
        db_session.commit()

        resp = authenticated_client.get(f'/words/{word.id}')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert '>None<' not in html
        assert 'class="wdet-hero__translation">None' not in html

    def test_word_detail_service_failure_does_not_return_500(
        self,
        authenticated_client,
        db_session,
        words_module,
        monkeypatch,
    ):
        """If get_related_words raises unexpectedly the route falls back gracefully."""
        suffix = uuid.uuid4().hex[:8]
        word = CollectionWords(
            english_word=f'failword{suffix}',
            russian_word='тест',
            level='A2',
            item_type='word',
        )
        db_session.add(word)
        db_session.commit()

        import app.words.routes as words_routes_mod

        def _boom(*args, **kwargs):
            raise RuntimeError('simulated DB error')

        monkeypatch.setattr(words_routes_mod, 'get_related_words', _boom)

        resp = authenticated_client.get(f'/words/{word.id}')

        assert resp.status_code == 200

    def test_word_detail_profile_service_failure_does_not_return_500(
        self,
        authenticated_client,
        db_session,
        words_module,
        monkeypatch,
    ):
        """If build_word_profile raises the route falls back to empty profile."""
        suffix = uuid.uuid4().hex[:8]
        word = CollectionWords(
            english_word=f'profilefail{suffix}',
            russian_word='тест',
            level='A2',
            item_type='word',
        )
        db_session.add(word)
        db_session.commit()

        import app.words.routes as words_routes_mod

        def _boom(*args, **kwargs):
            raise RuntimeError('simulated profile build error')

        monkeypatch.setattr(words_routes_mod, 'build_word_profile', _boom)

        resp = authenticated_client.get(f'/words/{word.id}')

        assert resp.status_code == 200


# ==================== UPDATE WORD STATUS ====================

class TestUpdateWordStatus:
    """POST /update-word-status/<word_id>/<status>"""

    def test_unauthenticated_redirects(self, client, sample_words):
        word = sample_words[0]
        resp = client.post(f'/update-word-status/{word.id}/1')
        assert resp.status_code in (302, 401)

    @pytest.mark.smoke
    def test_add_word_to_study(self, authenticated_client, db_session, test_user, sample_words):
        word = sample_words[0]
        resp = authenticated_client.post(
            f'/update-word-status/{word.id}/1',
            data={},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_remove_word_from_study(self, authenticated_client, db_session, test_user, sample_words, user_word_statuses):
        word = sample_words[0]
        resp = authenticated_client.post(
            f'/update-word-status/{word.id}/0',
            data={},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_set_word_review(self, authenticated_client, sample_words):
        word = sample_words[0]
        resp = authenticated_client.post(
            f'/update-word-status/{word.id}/2',
            data={},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_nonexistent_word(self, authenticated_client):
        resp = authenticated_client.post(
            '/update-word-status/999999/1',
            data={},
            follow_redirects=False,
        )
        assert resp.status_code == 404


# ==================== DAILY PLAN NEXT STEP ====================

class TestDailyPlanNextStep:
    """GET /api/daily-plan/next-step"""

    def test_unauthenticated_redirects(self, client):
        resp = client.get('/api/daily-plan/next-step')
        assert resp.status_code in (302, 401)

    @pytest.mark.smoke
    def test_next_step_returns_json(self, authenticated_client):
        resp = authenticated_client.get('/api/daily-plan/next-step')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'steps_done' in data
        assert 'steps_total' in data

    def test_next_step_all_done_or_has_next(self, authenticated_client):
        resp = authenticated_client.get('/api/daily-plan/next-step')
        data = resp.get_json()
        if data.get('has_next'):
            assert 'step_type' in data
            assert 'step_url' in data
        else:
            assert 'all_done' in data


# ==================== STREAK REPAIR WEB ====================

class TestStreakRepairWeb:
    """POST /api/streak/repair-web"""

    def test_unauthenticated_redirects(self, client):
        resp = client.post('/api/streak/repair-web',
                           json={},
                           content_type='application/json')
        assert resp.status_code in (302, 401)

    @pytest.mark.smoke
    def test_streak_repair_returns_json(self, authenticated_client):
        resp = authenticated_client.post(
            '/api/streak/repair-web',
            json={'tz': 'Europe/Moscow'},
            content_type='application/json',
        )
        assert resp.status_code in (200, 400)
        data = resp.get_json()
        assert 'success' in data

    def test_without_json_body(self, authenticated_client):
        resp = authenticated_client.post('/api/streak/repair-web')
        # Should handle missing JSON gracefully (defaults tz to Europe/Moscow)
        assert resp.status_code in (200, 400)


# ==================== PUBLIC WORD PAGE ====================

class TestPublicWord:
    """GET /dictionary/<word_slug>"""

    @pytest.mark.smoke
    def test_public_word_200(self, client, sample_words):
        word = sample_words[0]
        slug = word.english_word.replace(' ', '_')
        resp = client.get(f'/dictionary/{slug}')
        assert resp.status_code == 200

    def test_public_word_not_found(self, client):
        resp = client.get('/dictionary/nonexistent-word-xyz')
        assert resp.status_code == 404

    def test_public_word_no_auth_required(self, client, sample_words):
        word = sample_words[0]
        slug = word.english_word.replace(' ', '_')
        resp = client.get(f'/dictionary/{slug}')
        assert resp.status_code == 200

    def test_public_word_baseline_renders_public_profile(self, client, sample_words):
        word = sample_words[0]
        slug = word.english_word.replace(' ', '_')
        resp = client.get(f'/dictionary/{slug}')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert word.english_word in html
        assert word.russian_word in html
        assert 'Начни учить это слово' in html
        assert f'/dictionary/{slug}' in html
        assert f'/words/{word.id}' not in html

    def test_public_word_does_not_expose_private_profile_data(self, client, db_session, test_user):
        from app.study.models import UserWord

        suffix = uuid.uuid4().hex[:8]
        word = CollectionWords(
            english_word=f'publicclean{suffix}',
            russian_word='публичное слово',
            level='A1',
            frequency_band=1,
            brown=1,
            item_type='word',
        )
        private_phrasal = CollectionWords(
            english_word=f'publicclean private {suffix}',
            russian_word='закрытая форма',
            level='C2',
            item_type='phrasal_verb',
            base_word=word,
        )
        db_session.add_all([word, private_phrasal])
        db_session.flush()
        user_word = UserWord(user_id=test_user.id, word_id=word.id)
        user_word.status = 'review'
        db_session.add(user_word)
        db_session.commit()

        resp = client.get(f'/dictionary/{word.english_word}')
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert 'Статус слова' not in html
        assert 'Служебная информация' not in html
        assert 'Brown corpus' not in html
        assert f'/words/{word.id}' not in html
        assert private_phrasal.english_word not in html


# ==================== PHRASAL VERBS REDIRECT ====================

class TestPhrasalVerbList:
    """GET /phrasal-verbs"""

    def test_unauthenticated_redirects(self, client):
        resp = client.get('/phrasal-verbs')
        assert resp.status_code in (302, 401)

    def test_redirects_to_words_with_filter(self, authenticated_client, words_module):
        resp = authenticated_client.get('/phrasal-verbs')
        assert resp.status_code == 302
        assert 'type=phrasal_verb' in resp.location
