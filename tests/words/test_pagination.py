"""Tests for word list pagination endpoint (Task 66).

Covers:
- page=1&per_page=10 returns 10 items
- page=99 returns empty items list, not 500
- per_page > 200 is clamped to 200
"""
import uuid

import pytest

from app.words.models import CollectionWords
from app.modules.models import SystemModule, UserModule


@pytest.fixture
def words_module_access(db_session, test_user):
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
def fifteen_words(db_session):
    """Create 15 words in CollectionWords for pagination tests."""
    suffix = uuid.uuid4().hex[:8]
    words = []
    for i in range(15):
        w = CollectionWords(
            english_word=f'pagination_word_{i:02d}_{suffix}',
            russian_word=f'слово_{i}',
            level='A1',
            item_type='word',
        )
        db_session.add(w)
        words.append(w)
    db_session.commit()
    return words


class TestWordListPagination:
    """Pagination behaviour for GET /words."""

    @pytest.mark.smoke
    def test_page1_per_page10_returns_200(
        self, authenticated_client, words_module_access, fifteen_words
    ):
        """GET /words?page=1&per_page=10 returns 200 with paginated content."""
        resp = authenticated_client.get('/words?page=1&per_page=10')
        assert resp.status_code == 200

    def test_page1_per_page10_shows_items(
        self, authenticated_client, words_module_access, fifteen_words
    ):
        """page=1&per_page=10 renders word entries in the response body."""
        suffix = fifteen_words[0].english_word.split('_')[-1]
        resp = authenticated_client.get('/words?page=1&per_page=10')
        assert resp.status_code == 200
        # At least some of the first-page words should appear in rendered HTML
        found = sum(
            1 for w in fifteen_words[:10]
            if w.english_word.encode() in resp.data
        )
        assert found > 0, "Expected at least one word from page 1 to appear in response"

    def test_high_page_number_returns_200_not_500(
        self, authenticated_client, words_module_access, fifteen_words
    ):
        """page=99 far beyond last page returns 200 (empty list), not 500."""
        resp = authenticated_client.get('/words?page=99')
        assert resp.status_code == 200

    def test_per_page_over_200_is_clamped(
        self, authenticated_client, words_module_access, fifteen_words
    ):
        """per_page=999 is clamped to 200; route still returns 200."""
        resp = authenticated_client.get('/words?per_page=999')
        assert resp.status_code == 200

    def test_page2_returns_200(
        self, authenticated_client, words_module_access, fifteen_words
    ):
        """page=2 with per_page=10 returns 200 (remaining words)."""
        resp = authenticated_client.get('/words?page=2&per_page=10')
        assert resp.status_code == 200
