"""
Tests for per-record error reporting in batch admin operations.
Covers: bulk_course_operations in app/admin/book_courses.py
"""
import json
from io import BytesIO

import pytest
from unittest.mock import patch, MagicMock, call


@pytest.fixture
def mock_admin_user(admin_user):
    """Mock current_user as authenticated admin."""
    with patch('app.admin.utils.decorators.current_user') as mock_user:
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.id = admin_user.id
        mock_user.username = admin_user.username
        yield mock_user


class TestBulkCourseOperationsErrorReporting:
    """Tests for bulk_course_operations per-record error reporting."""

    @pytest.mark.smoke
    def test_bulk_activate_all_valid_returns_no_errors(self, admin_client, mock_admin_user):
        """All valid courses: returns success_count == N and errors == []."""
        course1 = MagicMock(id=1, title='Course 1', modules=[])
        course2 = MagicMock(id=2, title='Course 2', modules=[])

        with patch('app.admin.book_courses.BookCourse') as mock_bc, \
             patch('app.admin.book_courses.db') as mock_db:
            mock_bc.query.filter.return_value.all.return_value = [course1, course2]
            mock_db.session.flush.return_value = None
            mock_db.session.commit.return_value = None
            mock_db.session.rollback.return_value = None

            response = admin_client.post(
                '/admin/book-courses/bulk-operations',
                data={'operation': 'activate', 'course_ids': '1,2'},
            )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['success_count'] == 2
        assert data['errors'] == []

    def test_bulk_deactivate_all_valid_returns_no_errors(self, admin_client, mock_admin_user):
        """Deactivate: all valid courses, no errors reported."""
        course1 = MagicMock(id=10, title='C1', modules=[])

        with patch('app.admin.book_courses.BookCourse') as mock_bc, \
             patch('app.admin.book_courses.db') as mock_db:
            mock_bc.query.filter.return_value.all.return_value = [course1]
            mock_db.session.flush.return_value = None
            mock_db.session.commit.return_value = None
            mock_db.session.rollback.return_value = None

            response = admin_client.post(
                '/admin/book-courses/bulk-operations',
                data={'operation': 'deactivate', 'course_ids': '10'},
            )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['success_count'] == 1
        assert data['errors'] == []

    def test_bulk_with_one_failing_record_returns_partial_success(self, admin_client, mock_admin_user):
        """1 valid + 1 invalid: returns success_count=1 and errors list with 1 entry."""
        course_ok = MagicMock(id=1, title='Good Course', modules=[])
        course_bad = MagicMock(id=2, title='Bad Course', modules=[])

        call_count = [0]

        def begin_nested_side_effect():
            call_count[0] += 1
            nested = MagicMock()
            if call_count[0] == 2:
                nested.commit.side_effect = Exception("DB constraint violation")
            return nested

        with patch('app.admin.book_courses.BookCourse') as mock_bc, \
             patch('app.admin.book_courses.db') as mock_db:
            mock_bc.query.filter.return_value.all.return_value = [course_ok, course_bad]
            mock_db.session.begin_nested.side_effect = begin_nested_side_effect
            mock_db.session.commit.return_value = None

            response = admin_client.post(
                '/admin/book-courses/bulk-operations',
                data={'operation': 'activate', 'course_ids': '1,2'},
            )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['success_count'] == 1
        assert len(data['errors']) == 1
        assert data['errors'][0]['course_id'] == 2
        assert 'error' in data['errors'][0]

    def test_bulk_all_failing_records_returns_zero_success(self, admin_client, mock_admin_user):
        """All records fail: success_count == 0, errors list has all entries."""
        course1 = MagicMock(id=3, title='Course 3', modules=[])
        course2 = MagicMock(id=4, title='Course 4', modules=[])

        def begin_nested_side_effect():
            nested = MagicMock()
            nested.commit.side_effect = Exception("always fails")
            return nested

        with patch('app.admin.book_courses.BookCourse') as mock_bc, \
             patch('app.admin.book_courses.db') as mock_db:
            mock_bc.query.filter.return_value.all.return_value = [course1, course2]
            mock_db.session.begin_nested.side_effect = begin_nested_side_effect
            mock_db.session.commit.return_value = None

            response = admin_client.post(
                '/admin/book-courses/bulk-operations',
                data={'operation': 'feature', 'course_ids': '3,4'},
            )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True  # the endpoint itself succeeded
        assert data['success_count'] == 0
        assert len(data['errors']) == 2

    def test_bulk_unknown_operation_returns_400(self, admin_client, mock_admin_user):
        """Unknown operation returns 400 before processing any records."""
        with patch('app.admin.book_courses.BookCourse'):
            response = admin_client.post(
                '/admin/book-courses/bulk-operations',
                data={'operation': 'unknown_op', 'course_ids': '1'},
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False

    def test_bulk_empty_course_ids_returns_400(self, admin_client, mock_admin_user):
        """No course_ids returns 400."""
        response = admin_client.post(
            '/admin/book-courses/bulk-operations',
            data={'operation': 'activate', 'course_ids': ''},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False


# ---------------------------------------------------------------------------
# Task 11 — Words admin bulk operations + CSV export / import hardening.
# ---------------------------------------------------------------------------
import uuid as _uuid

from app.admin.audit import AdminAuditLog
from app.admin.services.word_management_service import WordManagementService
from app.admin.utils import export_helpers, import_helpers
from app.auth.models import User
from app.study.models import UserWord
from app.utils.db import db
from app.words.models import CollectionWords


def _make_admin(db_session):
    suffix = _uuid.uuid4().hex[:8]
    admin = User(
        username=f'word_bulk_admin_{suffix}',
        email=f'word_bulk_admin_{suffix}@example.com',
        is_admin=True,
        active=True,
    )
    admin.set_password('pass1234')
    db_session.add(admin)
    db_session.flush()
    return admin


def _make_target_user(db_session):
    suffix = _uuid.uuid4().hex[:8]
    user = User(
        username=f'word_bulk_user_{suffix}',
        email=f'word_bulk_user_{suffix}@example.com',
        active=True,
    )
    user.set_password('pass1234')
    db_session.add(user)
    db_session.flush()
    return user


def _make_word(db_session, english):
    word = CollectionWords(english_word=english, russian_word='перевод')
    db_session.add(word)
    db_session.flush()
    return word


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


@pytest.mark.smoke
class TestWordBulkStatusUpdate:
    """Word bulk-status update: atomic mutation + audit-log entry."""

    def test_bulk_update_writes_audit_log_and_userword(self, app, client, db_session):
        admin = _make_admin(db_session)
        target = _make_target_user(db_session)
        word = _make_word(db_session, f'apple_{_uuid.uuid4().hex[:6]}')
        db_session.commit()

        _login(client, admin)

        resp = client.post(
            '/admin/words/bulk-status-update',
            json={'words': [word.english_word], 'status': 2, 'user_id': target.id},
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['success'] is True
        assert payload['updated_count'] >= 1

        # Audit row exists and is keyed to the same admin.
        entry = (
            db.session.query(AdminAuditLog)
            .filter_by(admin_id=admin.id, action='word.bulk_update_status')
            .order_by(AdminAuditLog.id.desc())
            .first()
        )
        assert entry is not None
        assert entry.target_type == 'word'

        # UserWord row reflects the mutation.
        uw = (
            db.session.query(UserWord)
            .filter_by(user_id=target.id, word_id=word.id)
            .first()
        )
        # set_word_status creates a UserWord row; exact status reflects
        # recalculate_status() outcome which depends on direction states.
        assert uw is not None
        assert uw.status in ('new', 'review', 'learning')

    def test_bulk_update_validation_error_returns_400_no_audit(self, app, client, db_session):
        admin = _make_admin(db_session)
        db_session.commit()
        _login(client, admin)

        before_count = db.session.query(AdminAuditLog).filter_by(
            admin_id=admin.id, action='word.bulk_update_status'
        ).count()

        resp = client.post('/admin/words/bulk-status-update', json={})
        assert resp.status_code == 400

        after_count = db.session.query(AdminAuditLog).filter_by(
            admin_id=admin.id, action='word.bulk_update_status'
        ).count()
        assert after_count == before_count

    def test_bulk_update_ignores_non_string_entries(self, app, client, db_session):
        admin = _make_admin(db_session)
        db_session.commit()
        _login(client, admin)

        resp = client.post(
            '/admin/words/bulk-status-update',
            json={'words': [None, 123, ''], 'status': 1},
        )
        assert resp.status_code == 400


class TestCSVExportHardening:
    """CSV export must sanitize, cap at MAX_EXPORT_ROWS, and stream."""

    def test_export_sanitizes_formula_prefix(self, app):
        word = MagicMock()
        word.english_word = '=cmd|"/c calc"!A1'
        word.russian_word = '+1+1'
        word.level = '-2'
        del word.status  # No status attr → 3-column output

        with app.test_request_context('/admin/words/export'):
            resp = export_helpers.export_words_csv([word])
            body = ''.join(chunk if isinstance(chunk, str) else chunk.decode('utf-8') for chunk in resp.response)
        lines = [line for line in body.split('\r\n') if line]
        assert lines[0] == 'English,Russian,Level'
        # csv writer wraps cells that start with `=` and contain `"` in quotes.
        first_data_cell = lines[1].split(',')[0]
        assert first_data_cell.lstrip('"').startswith("'=")

    def test_export_respects_max_rows_cap(self, app, monkeypatch):
        monkeypatch.setattr(export_helpers, 'MAX_EXPORT_ROWS', 3)
        words = []
        for i in range(10):
            w = MagicMock()
            w.english_word = f'w{i}'
            w.russian_word = 'r'
            w.level = 'A1'
            del w.status
            words.append(w)

        with app.test_request_context('/admin/words/export'):
            resp = export_helpers.export_words_csv(words)
            body = ''.join(chunk if isinstance(chunk, str) else chunk.decode('utf-8') for chunk in resp.response)
        # header + 3 data rows == 4 non-empty lines
        assert len([line for line in body.split('\r\n') if line]) == 4

    def test_export_returns_streaming_response(self, app):
        word = MagicMock()
        word.english_word = 'cat'
        word.russian_word = 'кошка'
        word.level = 'A1'
        del word.status

        with app.test_request_context('/admin/words/export'):
            resp = export_helpers.export_words_csv([word])
        assert resp.is_streamed
        assert 'attachment' in resp.headers.get('Content-Disposition', '')
        assert 'csv' in resp.headers.get('Content-Type', '')

    def test_export_audio_csv_sanitizes_and_caps(self, app, monkeypatch):
        monkeypatch.setattr(export_helpers, 'MAX_EXPORT_ROWS', 2)
        words = ['=danger', 'safe', 'extra']
        with app.test_request_context('/admin/audio/download-list'):
            resp = export_helpers.export_audio_list_csv(words)
            body = ''.join(chunk if isinstance(chunk, str) else chunk.decode('utf-8') for chunk in resp.response)
        rows = [line for line in body.split('\r\n') if line]
        assert rows[0] == 'English Word,Forvo URL'
        assert len(rows) == 3  # header + 2 capped rows
        assert rows[1].lstrip('"').startswith("'=")  # sanitized formula prefix


class TestCSVImportBOM:
    """parse_import_file must accept a BOM-prefixed line (after route decode)."""

    def test_parse_import_file_handles_bom_stripped_content(self):
        # The route decodes with utf-8-sig so BOM is gone before parse_import_file.
        content = "english_word;russian;ex_en;ex_ru;level\napple;яблоко;An apple;Яблоко;A1\n"
        existing, missing, errors = WordManagementService.parse_import_file(content)
        assert errors == []
        # apple may not be in DB (depends on fixtures) — what we care about is the parser succeeded.
        assert len(existing) + len(missing) == 1

    def test_parse_import_file_rejects_wrong_column_count(self):
        content = "only;two\n"
        existing, missing, errors = WordManagementService.parse_import_file(content)
        assert existing == []
        assert missing == []
        assert len(errors) == 1
        assert 'неверный формат' in errors[0]['error']

    def test_word_import_route_strips_bom(self, app, client, db_session):
        admin = _make_admin(db_session)
        db_session.commit()
        _login(client, admin)

        bom_csv = '\ufeffapple;яблоко;An apple;Яблоко;A1\n'.encode('utf-8')
        resp = client.post(
            '/admin/words/import-translations',
            data={
                'action': 'preview',
                'translation_file': (BytesIO(bom_csv), 'words.csv'),
            },
            content_type='multipart/form-data',
        )
        # Either preview render (200) or successful redirect; never decode error.
        assert resp.status_code in (200, 302)
        text = resp.get_data(as_text=True)
        # Validation should not have flagged 'Файл должен быть в UTF-8'.
        assert 'Файл должен быть в UTF-8' not in text


class TestImportHelpersIDValidation:
    """save/load/delete must reject non-UUID identifiers (path-traversal guard)."""

    def test_load_rejects_path_traversal(self):
        assert import_helpers.load_import_data('../etc/passwd') is None
        assert import_helpers.load_import_data('') is None
        assert import_helpers.load_import_data(None) is None
        assert import_helpers.load_import_data('not-a-uuid') is None

    def test_delete_rejects_path_traversal(self):
        # Should silently no-op without raising on a bad id.
        import_helpers.delete_import_data('../../boot.ini')
        import_helpers.delete_import_data('xx')

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(import_helpers, 'IMPORT_TEMP_DIR', str(tmp_path))
        import_id = import_helpers.save_import_data({'k': 'v'})
        loaded = import_helpers.load_import_data(import_id)
        assert loaded == {'k': 'v'}
        import_helpers.delete_import_data(import_id)
        assert import_helpers.load_import_data(import_id) is None
