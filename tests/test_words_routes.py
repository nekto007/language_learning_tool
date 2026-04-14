"""Tests for words routes: word list, word detail, status update, API endpoints."""
import uuid

import pytest

from app.words.models import CollectionWords
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
            english_word=f'{eng}_{suffix}',
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

    def test_pagination(self, authenticated_client, words_module, sample_words):
        resp = authenticated_client.get('/words?page=1')
        assert resp.status_code == 200

    def test_pagination_out_of_range(self, authenticated_client, words_module, sample_words):
        resp = authenticated_client.get('/words?page=9999')
        assert resp.status_code == 200


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

    def test_word_detail_with_user_status(self, authenticated_client, words_module, sample_words, user_word_statuses):
        word = sample_words[0]
        resp = authenticated_client.get(f'/words/{word.id}')
        assert resp.status_code == 200

    def test_word_detail_not_found(self, authenticated_client, words_module):
        resp = authenticated_client.get('/words/999999')
        assert resp.status_code == 404


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
        slug = word.english_word.replace(' ', '-')
        resp = client.get(f'/dictionary/{slug}')
        assert resp.status_code == 200

    def test_public_word_not_found(self, client):
        resp = client.get('/dictionary/nonexistent-word-xyz')
        assert resp.status_code == 404

    def test_public_word_no_auth_required(self, client, sample_words):
        word = sample_words[0]
        slug = word.english_word.replace(' ', '-')
        resp = client.get(f'/dictionary/{slug}')
        assert resp.status_code == 200


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
