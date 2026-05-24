"""
Comprehensive tests for app/admin/routes/audio_routes.py
Tests for audio management routes (169 lines)
Target: Increase coverage to help reach 55% overall project coverage
"""
import pytest
from unittest.mock import patch, MagicMock


class TestAudioManagement:
    """Tests for audio_management() route"""

    @pytest.mark.smoke
    @patch('app.admin.routes.audio_routes.AudioManagementService.get_audio_statistics')
    @patch('config.settings.MEDIA_FOLDER', '/media')
    def test_audio_management_success(self, mock_get_stats, admin_client, mock_admin_user):
        """Test successful audio management page"""
        # Setup mock
        mock_get_stats.return_value = {
            'words_total': 1000,
            'words_with_audio': 800,
            'words_without_audio': 200,
            'problematic_audio': 10,
            'recent_audio_updates': [],
            'media_folder': '/media'
        }

        # Execute
        response = admin_client.get('/admin/audio')

        # Assert
        assert response.status_code == 200
        mock_get_stats.assert_called_once()

    @patch('app.admin.routes.audio_routes.AudioManagementService.get_audio_statistics')
    @patch('config.settings.MEDIA_FOLDER', '/media')
    def test_audio_management_with_error(self, mock_get_stats, admin_client, mock_admin_user):
        """Test audio management with error in stats"""
        # Setup mock to return error
        mock_get_stats.return_value = {'error': 'Database error'}

        # Execute
        response = admin_client.get('/admin/audio', follow_redirects=False)

        # Assert - should redirect to dashboard
        assert response.status_code == 302
        assert '/admin/' in response.location

    @patch('app.admin.routes.audio_routes.AudioManagementService.get_audio_statistics')
    @patch('config.settings.MEDIA_FOLDER', '/media')
    def test_audio_management_exception(self, mock_get_stats, admin_client, mock_admin_user):
        """Test audio management with exception"""
        # Setup mock to raise exception
        mock_get_stats.side_effect = Exception("Service error")

        # Execute
        response = admin_client.get('/admin/audio', follow_redirects=False)

        # Assert - should redirect to dashboard
        assert response.status_code == 302

    def test_audio_management_requires_admin(self, client):
        """Test that audio management requires admin authentication"""
        response = client.get('/admin/audio')
        assert response.status_code == 302


class TestUpdateAudioDownloadStatus:
    """Tests for update_audio_download_status() route"""

    @patch('app.admin.routes.audio_routes.AudioManagementService.update_download_status')
    @patch('config.settings.MEDIA_FOLDER', '/media')
    @patch('config.settings.COLLECTIONS_TABLE', 'collection_words')
    def test_update_download_status_success(self, mock_update, admin_client, mock_admin_user):
        """Test successful audio download status update"""
        # Setup mock
        mock_update.return_value = 50

        # Execute
        response = admin_client.post(
            '/admin/audio/update-download-status',
            json={'table': 'collection_words'}
        )

        # Assert
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is True
        assert json_data['updated_count'] == 50
        mock_update.assert_called_once()

    @patch('app.admin.routes.audio_routes.AudioManagementService.update_download_status')
    @patch('config.settings.MEDIA_FOLDER', '/media')
    @patch('config.settings.COLLECTIONS_TABLE', 'collection_words')
    def test_update_download_status_default_table(self, mock_update, admin_client, mock_admin_user):
        """Test update status with default table"""
        # Setup mock
        mock_update.return_value = 30

        # Execute
        response = admin_client.post(
            '/admin/audio/update-download-status',
            json={}
        )

        # Assert
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is True
        assert json_data['table_name'] == 'collection_words'

    @patch('app.admin.routes.audio_routes.AudioManagementService.update_download_status')
    @patch('config.settings.MEDIA_FOLDER', '/media')
    @patch('config.settings.COLLECTIONS_TABLE', 'collection_words')
    def test_update_download_status_phrasal_verbs(self, mock_update, admin_client, mock_admin_user):
        """Test update status with phrasal verbs table"""
        # Setup mock
        mock_update.return_value = 10

        # Execute
        response = admin_client.post(
            '/admin/audio/update-download-status',
            json={'table': 'phrasal_verbs'}
        )

        # Assert
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is True

    @patch('app.admin.routes.audio_routes.AudioManagementService.update_download_status')
    @patch('config.settings.MEDIA_FOLDER', '/media')
    @patch('config.settings.COLLECTIONS_TABLE', 'collection_words')
    def test_update_download_status_error(self, mock_update, admin_client, mock_admin_user):
        """Test update status with error"""
        # Setup mock to raise exception
        mock_update.side_effect = Exception("Update failed")

        # Execute
        response = admin_client.post(
            '/admin/audio/update-download-status',
            json={'table': 'collection_words'}
        )

        # Assert
        assert response.status_code == 500
        json_data = response.get_json()
        assert json_data['success'] is False

    def test_update_download_status_requires_admin(self, client):
        """Test that update download status requires admin authentication"""
        response = client.post('/admin/audio/update-download-status', json={})
        assert response.status_code == 302


class TestFixAudioListeningFields:
    """Tests for fix_audio_listening_fields() route"""

    @patch('app.admin.routes.audio_routes.clear_admin_cache')
    @patch('app.admin.routes.audio_routes.AudioManagementService.fix_listening_fields')
    def test_fix_listening_fields_success(self, mock_fix, mock_cache, admin_client, mock_admin_user):
        """Test successful listening fields fix"""
        # Setup mock
        mock_fix.return_value = (True, 25, 'Fixed 25 records')

        # Execute
        response = admin_client.post('/admin/audio/fix-listening-fields')

        # Assert
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is True
        assert json_data['fixed_count'] == 25
        mock_cache.assert_called_once()

    @patch('app.admin.routes.audio_routes.AudioManagementService.fix_listening_fields')
    def test_fix_listening_fields_failure(self, mock_fix, admin_client, mock_admin_user):
        """Test listening fields fix with service failure"""
        # Setup mock to return failure
        mock_fix.return_value = (False, 0, 'Fix failed')

        # Execute
        response = admin_client.post('/admin/audio/fix-listening-fields')

        # Assert
        assert response.status_code == 500
        json_data = response.get_json()
        assert json_data['success'] is False

    @patch('app.admin.routes.audio_routes.AudioManagementService.fix_listening_fields')
    def test_fix_listening_fields_exception(self, mock_fix, admin_client, mock_admin_user):
        """Test listening fields fix with exception"""
        # Setup mock to raise exception
        mock_fix.side_effect = Exception("Service error")

        # Execute
        response = admin_client.post('/admin/audio/fix-listening-fields')

        # Assert
        assert response.status_code == 500
        json_data = response.get_json()
        assert json_data['success'] is False

    def test_fix_listening_fields_requires_admin(self, client):
        """Test that fix listening fields requires admin authentication"""
        response = client.post('/admin/audio/fix-listening-fields')
        assert response.status_code == 302


class TestGetAudioDownloadList:
    """Tests for get_audio_download_list() route"""

    @patch('app.admin.routes.audio_routes.export_audio_list_txt')
    @patch('app.admin.routes.audio_routes.AudioManagementService.get_download_list')
    def test_get_download_list_txt(self, mock_get_list, mock_export, admin_client, mock_admin_user):
        """Test download list in TXT format"""
        # Setup mocks
        mock_get_list.return_value = ['word1', 'word2', 'word3']
        mock_export.return_value = 'text file response'

        # Execute
        response = admin_client.get('/admin/audio/get-download-list?format=txt')

        # Assert
        assert response.status_code == 200
        mock_get_list.assert_called_once_with(None)
        mock_export.assert_called_once()

    @patch('app.admin.routes.audio_routes.export_audio_list_json')
    @patch('app.admin.routes.audio_routes.AudioManagementService.get_download_list')
    def test_get_download_list_json(self, mock_get_list, mock_export, admin_client, mock_admin_user):
        """Test download list in JSON format"""
        # Setup mocks
        mock_get_list.return_value = ['word1', 'word2']
        mock_export.return_value = 'json response'

        # Execute
        response = admin_client.get('/admin/audio/get-download-list?format=json')

        # Assert
        assert response.status_code == 200
        mock_export.assert_called_once()

    @patch('app.admin.routes.audio_routes.export_audio_list_csv')
    @patch('app.admin.routes.audio_routes.AudioManagementService.get_download_list')
    def test_get_download_list_csv(self, mock_get_list, mock_export, admin_client, mock_admin_user):
        """Test download list in CSV format"""
        # Setup mocks
        mock_get_list.return_value = ['word1']
        mock_export.return_value = 'csv response'

        # Execute
        response = admin_client.get('/admin/audio/get-download-list?format=csv')

        # Assert
        assert response.status_code == 200
        mock_export.assert_called_once()

    @patch('app.admin.routes.audio_routes.export_audio_list_txt')
    @patch('app.admin.routes.audio_routes.AudioManagementService.get_download_list')
    def test_get_download_list_with_pattern(self, mock_get_list, mock_export, admin_client, mock_admin_user):
        """Test download list with pattern filter"""
        # Setup mocks
        mock_get_list.return_value = ['apple', 'application']
        mock_export.return_value = 'filtered response'

        # Execute
        response = admin_client.get('/admin/audio/get-download-list?pattern=app')

        # Assert
        assert response.status_code == 200
        mock_get_list.assert_called_once_with('app')

    @patch('app.admin.routes.audio_routes.AudioManagementService.get_download_list')
    def test_get_download_list_empty(self, mock_get_list, admin_client, mock_admin_user):
        """Test download list with no words"""
        # Setup mock to return empty list
        mock_get_list.return_value = []

        # Execute
        response = admin_client.get('/admin/audio/get-download-list', follow_redirects=False)

        # Assert - should redirect back to audio management
        assert response.status_code == 302
        assert 'audio' in response.location

    @patch('app.admin.routes.audio_routes.AudioManagementService.get_download_list')
    def test_get_download_list_error(self, mock_get_list, admin_client, mock_admin_user):
        """Test download list with error"""
        # Setup mock to raise exception
        mock_get_list.side_effect = Exception("Service error")

        # Execute
        response = admin_client.get('/admin/audio/get-download-list', follow_redirects=False)

        # Assert - should redirect with error flash
        assert response.status_code == 302

    def test_get_download_list_requires_admin(self, client):
        """Test that get download list requires admin authentication"""
        response = client.get('/admin/audio/get-download-list')
        assert response.status_code == 302


class TestAudioStatistics:
    """Tests for audio_statistics() route"""

    @patch('app.admin.routes.audio_routes.render_template')
    @patch('app.admin.routes.audio_routes.AudioManagementService.get_detailed_statistics')
    def test_audio_statistics_success(self, mock_get_stats, mock_render, admin_client, mock_admin_user):
        """Test successful audio statistics page"""
        # Setup mock
        mock_get_stats.return_value = {
            'download_stats': {'total': 1000},
            'listening_stats': {'completed': 500},
            'level_audio_stats': {'A1': 200, 'A2': 300}
        }

        # Mock render_template to avoid template rendering issues
        mock_render.return_value = '<html>audio statistics</html>'

        # Execute
        response = admin_client.get('/admin/audio/statistics')

        # Assert
        assert response.status_code == 200
        mock_get_stats.assert_called_once()
        mock_render.assert_called_once()

    @patch('app.admin.routes.audio_routes.AudioManagementService.get_detailed_statistics')
    def test_audio_statistics_with_error(self, mock_get_stats, admin_client, mock_admin_user):
        """Test audio statistics with error"""
        # Setup mock to return error
        mock_get_stats.return_value = {'error': 'Statistics error'}

        # Execute
        response = admin_client.get('/admin/audio/statistics', follow_redirects=False)

        # Assert - should redirect back to audio management
        assert response.status_code == 302
        assert 'audio' in response.location

    @patch('app.admin.routes.audio_routes.AudioManagementService.get_detailed_statistics')
    def test_audio_statistics_exception(self, mock_get_stats, admin_client, mock_admin_user):
        """Test audio statistics with exception"""
        # Setup mock to raise exception
        mock_get_stats.side_effect = Exception("Service error")

        # Execute
        response = admin_client.get('/admin/audio/statistics', follow_redirects=False)

        # Assert - should redirect with error flash
        assert response.status_code == 302

    def test_audio_statistics_requires_admin(self, client):
        """Test that audio statistics requires admin authentication"""
        response = client.get('/admin/audio/statistics')
        assert response.status_code == 302


class TestSafeFilenameHelpers:
    """Filename / path traversal helpers — Task 14."""

    def test_safe_audio_filename_accepts_plain_mp3(self):
        from app.admin.services.audio_management_service import safe_audio_filename
        assert safe_audio_filename('pronunciation_en_word.mp3') == 'pronunciation_en_word.mp3'
        assert safe_audio_filename('foo-bar_baz.mp3') == 'foo-bar_baz.mp3'

    @pytest.mark.parametrize('bad', [
        '',
        None,
        '../escape.mp3',
        '../../etc/passwd.mp3',
        '/abs/path.mp3',
        'sub/dir.mp3',
        '.hidden.mp3',
        'space name.mp3',
        'with\x00null.mp3',
        'no-extension',
        'wrong.txt',
        'tricky..mp3',
    ])
    def test_safe_audio_filename_rejects_unsafe(self, bad):
        from app.admin.services.audio_management_service import safe_audio_filename
        assert safe_audio_filename(bad) is None

    def test_safe_audio_path_blocks_traversal(self, tmp_path):
        from app.admin.services.audio_management_service import safe_audio_path
        # Crafted inputs all rejected: separators stripped before resolve.
        assert safe_audio_path(str(tmp_path), '../escape.mp3') is None
        assert safe_audio_path(str(tmp_path), '/etc/passwd.mp3') is None
        # Plain filename inside folder resolves cleanly even if file doesn't exist.
        ok = safe_audio_path(str(tmp_path), 'pronunciation_en_word.mp3')
        assert ok is not None
        assert ok.endswith('pronunciation_en_word.mp3')

    def test_safe_audio_path_rejects_missing_media_folder(self):
        from app.admin.services.audio_management_service import safe_audio_path
        assert safe_audio_path('', 'file.mp3') is None
        assert safe_audio_path(None, 'file.mp3') is None

    def test_safe_audio_filename_for_word_sanitises_slug(self):
        from app.admin.services.audio_management_service import safe_audio_filename_for_word
        assert safe_audio_filename_for_word('hello') == 'pronunciation_en_hello.mp3'
        assert safe_audio_filename_for_word('two words') == 'pronunciation_en_two_words.mp3'
        # Strips traversal chars instead of preserving them.
        assert safe_audio_filename_for_word('../etc/passwd') == 'pronunciation_en_etcpasswd.mp3'
        # Strips slashes / dots completely.
        assert safe_audio_filename_for_word('a/b\\c') == 'pronunciation_en_abc.mp3'

    def test_safe_audio_filename_for_word_rejects_empty_slug(self):
        from app.admin.services.audio_management_service import safe_audio_filename_for_word
        assert safe_audio_filename_for_word('') is None
        assert safe_audio_filename_for_word(None) is None
        assert safe_audio_filename_for_word('!!!') is None


class TestOrphanAudioService:
    """Service-level orphan listing/cleanup — Task 14."""

    def _seed_word(self, db_session, listening):
        from app.words.models import CollectionWords
        import uuid
        slug = uuid.uuid4().hex[:6]
        w = CollectionWords(
            english_word=f'orphan_test_{slug}',
            russian_word='тест',
            listening=listening,
            level='A1',
        )
        db_session.add(w)
        db_session.flush()
        return w

    def test_find_orphan_audio_files_lists_only_unreferenced(self, tmp_path, db_session):
        from app.admin.services.audio_management_service import AudioManagementService
        # Files: one referenced, one orphan, one with traversal-ish name (skipped via filename gate).
        ref = tmp_path / 'pronunciation_en_keep.mp3'
        ref.write_bytes(b'\x00')
        orphan = tmp_path / 'pronunciation_en_orphan.mp3'
        orphan.write_bytes(b'\x00')
        self._seed_word(db_session, 'pronunciation_en_keep.mp3')

        result = AudioManagementService.find_orphan_audio_files(str(tmp_path))
        assert 'error' not in result
        assert result['total_files'] == 2
        assert 'pronunciation_en_orphan.mp3' in result['orphans']
        assert 'pronunciation_en_keep.mp3' not in result['orphans']
        assert result['orphan_count'] == 1

    def test_find_orphan_audio_files_returns_error_for_missing_folder(self):
        from app.admin.services.audio_management_service import AudioManagementService
        result = AudioManagementService.find_orphan_audio_files('/nonexistent/path/xyz')
        assert 'error' in result

    def test_delete_orphan_audio_files_dry_run_keeps_files(self, tmp_path, db_session):
        from app.admin.services.audio_management_service import AudioManagementService
        orphan = tmp_path / 'pronunciation_en_orphan.mp3'
        orphan.write_bytes(b'\x00')
        result = AudioManagementService.delete_orphan_audio_files(str(tmp_path), dry_run=True)
        assert result['dry_run'] is True
        assert result['deleted'] == 0
        assert orphan.exists()
        assert 'pronunciation_en_orphan.mp3' in result['orphans']

    def test_delete_orphan_audio_files_actually_deletes(self, tmp_path, db_session):
        from app.admin.services.audio_management_service import AudioManagementService
        orphan = tmp_path / 'pronunciation_en_orphan.mp3'
        orphan.write_bytes(b'\x00')
        result = AudioManagementService.delete_orphan_audio_files(str(tmp_path), dry_run=False)
        assert result['dry_run'] is False
        assert result['deleted'] == 1
        assert not orphan.exists()

    def test_delete_orphan_audio_files_skips_referenced(self, tmp_path, db_session):
        from app.admin.services.audio_management_service import AudioManagementService
        keep = tmp_path / 'pronunciation_en_keep.mp3'
        keep.write_bytes(b'\x00')
        self._seed_word(db_session, 'pronunciation_en_keep.mp3')
        result = AudioManagementService.delete_orphan_audio_files(str(tmp_path), dry_run=False)
        assert result['deleted'] == 0
        assert keep.exists()


class TestOrphanAudioRoutes:
    """HTTP endpoints for orphan listing/cleanup — Task 14."""

    def test_list_orphans_requires_admin(self, client):
        response = client.get('/admin/audio/orphans')
        assert response.status_code in (302, 401, 403)

    def test_cleanup_orphans_requires_admin(self, client):
        response = client.post('/admin/audio/orphans/cleanup', json={'confirm': 'yes'})
        assert response.status_code in (302, 401, 403)

    def test_list_orphans_returns_json(self, admin_client, mock_admin_user, tmp_path, db_session):
        (tmp_path / 'pronunciation_en_orph.mp3').write_bytes(b'\x00')
        with patch('config.settings.MEDIA_FOLDER', str(tmp_path)):
            response = admin_client.get('/admin/audio/orphans')
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'orphans' in data
        assert 'pronunciation_en_orph.mp3' in data['orphans']

    def test_list_orphans_rejects_invalid_limit(self, admin_client, mock_admin_user):
        response = admin_client.get('/admin/audio/orphans?limit=not-a-number')
        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False

    def test_cleanup_orphans_without_confirm_is_dry_run(
        self, admin_client, mock_admin_user, tmp_path, db_session
    ):
        orphan = tmp_path / 'pronunciation_en_orph.mp3'
        orphan.write_bytes(b'\x00')
        with patch('config.settings.MEDIA_FOLDER', str(tmp_path)):
            response = admin_client.post('/admin/audio/orphans/cleanup', json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['dry_run'] is True
        assert data['deleted'] == 0
        assert orphan.exists()

    def test_cleanup_orphans_with_confirm_deletes(
        self, admin_client, mock_admin_user, tmp_path, db_session
    ):
        orphan = tmp_path / 'pronunciation_en_orph.mp3'
        orphan.write_bytes(b'\x00')
        with patch('config.settings.MEDIA_FOLDER', str(tmp_path)):
            response = admin_client.post(
                '/admin/audio/orphans/cleanup', json={'confirm': 'yes'}
            )
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['dry_run'] is False
        assert data['deleted'] == 1
        assert not orphan.exists()

    def test_cleanup_orphans_writes_audit_log(
        self, admin_client, mock_admin_user, tmp_path, db_session
    ):
        from app.admin.audit import AdminAuditLog
        (tmp_path / 'pronunciation_en_orph.mp3').write_bytes(b'\x00')
        before = db_session.query(AdminAuditLog).filter(
            AdminAuditLog.action.like('audio.orphans%')
        ).count()
        with patch('config.settings.MEDIA_FOLDER', str(tmp_path)):
            response = admin_client.post(
                '/admin/audio/orphans/cleanup', json={'confirm': 'yes'}
            )
        assert response.status_code == 200
        after = db_session.query(AdminAuditLog).filter(
            AdminAuditLog.action.like('audio.orphans%')
        ).count()
        assert after == before + 1


class TestFixListeningFieldsSafety:
    """Bulk DB fixes must not crash on unsafe data — Task 14."""

    def test_fix_listening_fields_skips_unsafe_word(self, db_session):
        from app.admin.services.audio_management_service import AudioManagementService
        from app.words.models import CollectionWords
        # Seed a row with HTTP URL whose english_word contains traversal chars.
        bad = CollectionWords(
            english_word='../../etc/passwd',
            russian_word='тест',
            listening='http://example.com/audio.mp3',
            level='A1',
        )
        db_session.add(bad)
        db_session.commit()
        ok, count, msg = AudioManagementService.fix_listening_fields()
        assert ok is True
        # The unsafe row is skipped — its listening remains the original HTTP value.
        refreshed = db_session.get(CollectionWords, bad.id)
        # Either skipped entirely or replaced with sanitised slug — never traversal.
        assert refreshed.listening is None or '..' not in (refreshed.listening or '')
        assert '/' not in (refreshed.listening or '')

    def test_normalize_listening_fields_skips_unsafe_sound(self, db_session):
        from app.admin.services.audio_management_service import AudioManagementService
        from app.words.models import CollectionWords
        bad = CollectionWords(
            english_word='hello',
            russian_word='привет',
            listening='[sound:../escape.mp3]',
            level='A1',
        )
        db_session.add(bad)
        db_session.commit()
        ok, count, msg = AudioManagementService.normalize_listening_fields()
        assert ok is True
        refreshed = db_session.get(CollectionWords, bad.id)
        # Unsafe sound payload was rejected — original bracket form remains.
        assert refreshed.listening == '[sound:../escape.mp3]'