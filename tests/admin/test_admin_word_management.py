"""Tests for admin word management: bulk delete, collocation audit,
frequency_band validation, and search sanitization (Task 86)."""
import json
from unittest.mock import patch

import pytest

from app.admin.audit import AdminAuditLog
from app.curriculum.models import WordCollocation
from app.study.models import UserWord
from app.utils.db import db
from app.words.models import CollectionWords


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_word(db_session, english="testword", russian="тест", level="B1"):
    word = CollectionWords(
        english_word=f"{english}_{id(object())}",
        russian_word=russian,
        level=level,
    )
    db_session.add(word)
    db_session.flush()
    return word


def _make_collocation(db_session, word_id, phrase="test phrase", translation="тест фраза"):
    col = WordCollocation(
        word_id=word_id,
        collocation_phrase=phrase,
        translation=translation,
    )
    db_session.add(col)
    db_session.flush()
    return col


def _make_user_word(db_session, user_id, word_id):
    uw = UserWord(user_id=user_id, word_id=word_id)
    db_session.add(uw)
    db_session.flush()
    return uw


def _admin_post(admin_client, admin_user, url, payload):
    """POST JSON as admin user with current_user patched."""
    with patch('app.admin.routes.word_routes.current_user') as mock_cu, \
         patch('app.admin.utils.decorators.current_user') as mock_dec:
        mock_cu.is_authenticated = True
        mock_cu.is_admin = True
        mock_cu.id = admin_user.id
        mock_cu.username = admin_user.username
        mock_dec.is_authenticated = True
        mock_dec.is_admin = True
        mock_dec.id = admin_user.id
        mock_dec.username = admin_user.username
        resp = admin_client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
        )
    return resp


def _admin_delete(admin_client, admin_user, url):
    with patch('app.admin.routes.word_routes.current_user') as mock_cu, \
         patch('app.admin.utils.decorators.current_user') as mock_dec:
        mock_cu.is_authenticated = True
        mock_cu.is_admin = True
        mock_cu.id = admin_user.id
        mock_cu.username = admin_user.username
        mock_dec.is_authenticated = True
        mock_dec.is_admin = True
        mock_dec.id = admin_user.id
        mock_dec.username = admin_user.username
        resp = admin_client.delete(url)
    return resp


# ---------------------------------------------------------------------------
# 1. Bulk word delete — cascade and service
# ---------------------------------------------------------------------------


class TestBulkDeleteWords:
    """Bulk delete must remove WordCollocation and UserWord via cascade."""

    @pytest.mark.smoke
    def test_bulk_delete_cascades_collocations(self, app, db_session):
        """Deleting a word must cascade-delete its WordCollocation rows."""
        from app.admin.services.word_management_service import WordManagementService

        word = _make_word(db_session)
        col = _make_collocation(db_session, word.id)
        col_id = col.id
        word_id = word.id
        db_session.flush()

        WordManagementService.bulk_delete_words([word_id])
        db_session.flush()
        db_session.expire_all()

        assert db_session.get(CollectionWords, word_id) is None
        assert db_session.get(WordCollocation, col_id) is None

    def test_bulk_delete_cascades_user_words(self, app, db_session, admin_user):
        """Deleting a word must cascade-delete UserWord rows."""
        from app.admin.services.word_management_service import WordManagementService

        word = _make_word(db_session)
        uw = _make_user_word(db_session, admin_user.id, word.id)
        uw_id = uw.id
        word_id = word.id
        db_session.flush()

        WordManagementService.bulk_delete_words([word_id])
        db_session.flush()
        db_session.expire_all()

        assert db_session.get(CollectionWords, word_id) is None
        assert db_session.get(UserWord, uw_id) is None

    def test_bulk_delete_empty_list_returns_zero(self, app, db_session):
        from app.admin.services.word_management_service import WordManagementService

        deleted = WordManagementService.bulk_delete_words([])
        assert deleted == 0

    def test_bulk_delete_nonexistent_ids_returns_zero(self, app, db_session):
        from app.admin.services.word_management_service import WordManagementService

        deleted = WordManagementService.bulk_delete_words([999999, 999998])
        assert deleted == 0

    def test_bulk_delete_route_requires_word_ids(self, app, admin_client, admin_user):
        resp = _admin_post(admin_client, admin_user, '/admin/words/bulk-delete', {})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False

    def test_bulk_delete_route_rejects_non_integer_ids(self, app, admin_client, admin_user):
        resp = _admin_post(admin_client, admin_user, '/admin/words/bulk-delete',
                           {'word_ids': ['abc', 'xyz']})
        assert resp.status_code == 400

    def test_bulk_delete_route_logs_audit(self, app, db_session, admin_client, admin_user):
        word = _make_word(db_session, english="auditword")
        db_session.commit()
        word_id = word.id

        with patch('app.admin.routes.word_routes.current_user') as mock_cu, \
             patch('app.admin.utils.decorators.current_user') as mock_dec:
            mock_cu.is_authenticated = True
            mock_cu.is_admin = True
            mock_cu.id = admin_user.id
            mock_cu.username = admin_user.username
            mock_dec.is_authenticated = True
            mock_dec.is_admin = True
            mock_dec.id = admin_user.id
            mock_dec.username = admin_user.username
            resp = admin_client.post(
                '/admin/words/bulk-delete',
                data=json.dumps({'word_ids': [word_id]}),
                content_type='application/json',
            )

        assert resp.status_code == 200
        entry = AdminAuditLog.query.filter_by(
            admin_id=admin_user.id,
            action='word.bulk_delete',
        ).first()
        assert entry is not None


# ---------------------------------------------------------------------------
# 2. Collocation add/remove — audit logging
# ---------------------------------------------------------------------------


class TestCollocationManagement:
    """Collocation add/remove must be logged in AdminAuditLog."""

    @pytest.mark.smoke
    def test_add_collocation_creates_row(self, app, db_session, admin_client, admin_user):
        word = _make_word(db_session, english="colword")
        db_session.commit()

        resp = _admin_post(
            admin_client, admin_user,
            f'/admin/words/{word.id}/collocations',
            {'collocation_phrase': 'test phrase', 'translation': 'тест фраза'},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['success'] is True
        col_id = data['collocation_id']

        row = WordCollocation.query.get(col_id)
        assert row is not None
        assert row.word_id == word.id

    def test_add_collocation_logs_audit(self, app, db_session, admin_client, admin_user):
        word = _make_word(db_session, english="auditcolword")
        db_session.commit()

        _admin_post(
            admin_client, admin_user,
            f'/admin/words/{word.id}/collocations',
            {'collocation_phrase': 'audit phrase', 'translation': 'аудит'},
        )

        entry = AdminAuditLog.query.filter_by(
            admin_id=admin_user.id,
            action='word.collocation_add',
            target_id=word.id,
        ).first()
        assert entry is not None

    def test_add_collocation_missing_phrase_returns_400(self, app, db_session, admin_client, admin_user):
        word = _make_word(db_session, english="nophraseword")
        db_session.commit()

        resp = _admin_post(
            admin_client, admin_user,
            f'/admin/words/{word.id}/collocations',
            {'translation': 'only translation'},
        )
        assert resp.status_code == 400

    def test_add_collocation_missing_translation_returns_400(self, app, db_session, admin_client, admin_user):
        word = _make_word(db_session, english="notranslword")
        db_session.commit()

        resp = _admin_post(
            admin_client, admin_user,
            f'/admin/words/{word.id}/collocations',
            {'collocation_phrase': 'only phrase'},
        )
        assert resp.status_code == 400

    def test_add_collocation_unknown_word_returns_404(self, app, db_session, admin_client, admin_user):
        resp = _admin_post(
            admin_client, admin_user,
            '/admin/words/999999/collocations',
            {'collocation_phrase': 'x', 'translation': 'y'},
        )
        assert resp.status_code == 404

    def test_remove_collocation_deletes_row(self, app, db_session, admin_client, admin_user):
        word = _make_word(db_session, english="rmcolword")
        col = _make_collocation(db_session, word.id)
        col_id = col.id
        db_session.commit()

        resp = _admin_delete(
            admin_client, admin_user,
            f'/admin/words/{word.id}/collocations/{col_id}',
        )
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

        assert WordCollocation.query.get(col_id) is None

    def test_remove_collocation_logs_audit(self, app, db_session, admin_client, admin_user):
        word = _make_word(db_session, english="rmauditcolword")
        col = _make_collocation(db_session, word.id)
        col_id = col.id
        db_session.commit()

        _admin_delete(
            admin_client, admin_user,
            f'/admin/words/{word.id}/collocations/{col_id}',
        )

        entry = AdminAuditLog.query.filter_by(
            admin_id=admin_user.id,
            action='word.collocation_remove',
            target_id=word.id,
        ).first()
        assert entry is not None

    def test_remove_collocation_wrong_word_returns_404(self, app, db_session, admin_client, admin_user):
        word1 = _make_word(db_session, english="wrongword1col")
        word2 = _make_word(db_session, english="wrongword2col")
        col = _make_collocation(db_session, word1.id)
        db_session.commit()

        resp = _admin_delete(
            admin_client, admin_user,
            f'/admin/words/{word2.id}/collocations/{col.id}',
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3. frequency_band update — validation
# ---------------------------------------------------------------------------


class TestFrequencyBandUpdate:
    """frequency_band endpoint must only accept 1, 2, 3, or null."""

    @pytest.mark.smoke
    def test_set_valid_frequency_band_1(self, app, db_session, admin_client, admin_user):
        word = _make_word(db_session, english="freqword1")
        db_session.commit()

        resp = _admin_post(
            admin_client, admin_user,
            f'/admin/words/{word.id}/frequency-band',
            {'frequency_band': 1},
        )
        assert resp.status_code == 200
        db_session.expire(word)
        assert word.frequency_band == 1

    def test_set_frequency_band_to_null(self, app, db_session, admin_client, admin_user):
        word = _make_word(db_session, english="freqwordnull")
        word.frequency_band = 2
        db_session.commit()

        resp = _admin_post(
            admin_client, admin_user,
            f'/admin/words/{word.id}/frequency-band',
            {'frequency_band': None},
        )
        assert resp.status_code == 200
        db_session.expire(word)
        assert word.frequency_band is None

    def test_frequency_band_4_rejected(self, app, db_session, admin_client, admin_user):
        word = _make_word(db_session, english="freqword4")
        db_session.commit()

        resp = _admin_post(
            admin_client, admin_user,
            f'/admin/words/{word.id}/frequency-band',
            {'frequency_band': 4},
        )
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_frequency_band_0_rejected(self, app, db_session, admin_client, admin_user):
        word = _make_word(db_session, english="freqword0")
        db_session.commit()

        resp = _admin_post(
            admin_client, admin_user,
            f'/admin/words/{word.id}/frequency-band',
            {'frequency_band': 0},
        )
        assert resp.status_code == 400

    def test_frequency_band_string_rejected(self, app, db_session, admin_client, admin_user):
        word = _make_word(db_session, english="freqwordstr")
        db_session.commit()

        resp = _admin_post(
            admin_client, admin_user,
            f'/admin/words/{word.id}/frequency-band',
            {'frequency_band': 'high'},
        )
        assert resp.status_code == 400

    def test_frequency_band_nonexistent_word_returns_404(self, app, db_session, admin_client, admin_user):
        resp = _admin_post(
            admin_client, admin_user,
            '/admin/words/999999/frequency-band',
            {'frequency_band': 1},
        )
        assert resp.status_code == 404

    def test_frequency_band_update_logs_audit(self, app, db_session, admin_client, admin_user):
        word = _make_word(db_session, english="freqauditword")
        db_session.commit()

        _admin_post(
            admin_client, admin_user,
            f'/admin/words/{word.id}/frequency-band',
            {'frequency_band': 2},
        )

        entry = AdminAuditLog.query.filter_by(
            admin_id=admin_user.id,
            action='word.frequency_band_update',
            target_id=word.id,
        ).first()
        assert entry is not None


# ---------------------------------------------------------------------------
# 4. Search sanitization — SQL-special chars don't crash
# ---------------------------------------------------------------------------


class TestWordSearchSanitization:
    """Admin word search must handle SQL-special characters safely."""

    def _search(self, admin_client, admin_user, q):
        with patch('app.admin.utils.decorators.current_user') as mock_dec:
            mock_dec.is_authenticated = True
            mock_dec.is_admin = True
            mock_dec.id = admin_user.id
            resp = admin_client.get(f'/admin/api/words/search?q={q}')
        return resp

    def test_search_with_percent_sign_does_not_crash(self, app, db_session, admin_client, admin_user):
        resp = self._search(admin_client, admin_user, '%percent%')
        assert resp.status_code == 200

    def test_search_with_single_quote_does_not_crash(self, app, db_session, admin_client, admin_user):
        resp = self._search(admin_client, admin_user, "O'Brien")
        assert resp.status_code == 200

    def test_search_with_underscore_does_not_crash(self, app, db_session, admin_client, admin_user):
        resp = self._search(admin_client, admin_user, "test_word")
        assert resp.status_code == 200

    def test_search_with_semicolon_does_not_crash(self, app, db_session, admin_client, admin_user):
        resp = self._search(admin_client, admin_user, "word; DROP TABLE")
        assert resp.status_code == 200

    def test_search_returns_json(self, app, db_session, admin_client, admin_user):
        resp = self._search(admin_client, admin_user, "hello")
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'words' in data or isinstance(data, list)
