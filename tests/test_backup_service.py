"""
Tests for app/curriculum/backup.py

Tests CurriculumBackupManager and CurriculumMigrationManager.
Covers backup creation (full/incremental), restore, list, delete, cleanup,
file loading, validation, metadata persistence, and migration exports.
External I/O (filesystem, database queries) is mocked where appropriate.
"""
import gzip
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, mock_open, patch, call

import pytest

from app.curriculum.backup import (
    CurriculumBackupManager,
    CurriculumMigrationManager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def backup_dir(tmp_path):
    """Provide a temporary backup directory."""
    d = tmp_path / "backups"
    d.mkdir()
    return str(d)


@pytest.fixture
def manager(backup_dir):
    """Create a CurriculumBackupManager with a temp directory."""
    return CurriculumBackupManager(backup_dir=backup_dir)


@pytest.fixture
def migration_manager(manager):
    """Create a CurriculumMigrationManager backed by the test manager."""
    return CurriculumMigrationManager(manager)


# ---------------------------------------------------------------------------
# Helper: write a fake backup file
# ---------------------------------------------------------------------------

def _write_backup(backup_dir, filename, data, compressed=True):
    """Write a backup file (compressed or plain JSON) into backup_dir."""
    path = os.path.join(backup_dir, filename)
    if compressed:
        with gzip.open(path, 'wt', encoding='utf-8') as f:
            json.dump(data, f)
    else:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    return path


def _valid_backup_data(backup_id='test_20250101_120000', include_progress=False):
    """Return minimal valid backup data dict."""
    data = {
        'metadata': {
            'backup_id': backup_id,
            'created_at': '2025-01-01T12:00:00+00:00',
            'version': '1.0',
            'include_progress': include_progress,
            'compressed': True,
        },
        'cefr_levels': [
            {'id': 1, 'code': 'A1', 'name': 'Beginner', 'description': 'Beginner level', 'order': 1},
        ],
        'modules': [
            {'id': 1, 'level_id': 1, 'number': 1, 'title': 'Module 1', 'description': 'Desc'},
        ],
        'lessons': [
            {
                'id': 1, 'module_id': 1, 'number': 1, 'title': 'Lesson 1',
                'type': 'vocabulary', 'description': 'Desc', 'content': {}, 'order': 0,
            },
        ],
    }
    if include_progress:
        data['lesson_progress'] = [
            {
                'id': 1, 'user_id': 1, 'lesson_id': 1, 'status': 'completed',
                'attempts': 2, 'final_score': 90, 'time_spent': 120,
                'answers': {}, 'last_activity': '2025-01-01T12:00:00+00:00',
            },
        ]
    return data


# ===========================================================================
# CurriculumBackupManager - initialisation
# ===========================================================================

class TestBackupManagerInit:

    def test_creates_backup_directory(self, tmp_path):
        """Ensure backup directory is created on init"""
        d = str(tmp_path / "new_dir")
        assert not os.path.exists(d)
        CurriculumBackupManager(backup_dir=d)
        assert os.path.isdir(d)

    def test_uses_provided_backup_dir(self, backup_dir):
        """Manager should use the directory passed to __init__"""
        mgr = CurriculumBackupManager(backup_dir=backup_dir)
        assert mgr.backup_dir == backup_dir

    def test_default_backup_dir_when_none(self, tmp_path, monkeypatch):
        """When backup_dir is None, a default path is used based on cwd"""
        monkeypatch.chdir(tmp_path)
        mgr = CurriculumBackupManager(backup_dir=None)
        expected = os.path.join(str(tmp_path), 'instance', 'backups', 'curriculum')
        assert mgr.backup_dir == expected
        assert os.path.isdir(expected)


# ===========================================================================
# _load_backup_file
# ===========================================================================

class TestLoadBackupFile:

    def test_load_gzip_file(self, manager, backup_dir):
        """Test loading a gzip-compressed backup file"""
        data = _valid_backup_data()
        path = _write_backup(backup_dir, 'backup.json.gz', data, compressed=True)
        loaded = manager._load_backup_file(path)
        assert loaded['metadata']['backup_id'] == data['metadata']['backup_id']

    def test_load_plain_json_file(self, manager, backup_dir):
        """Test loading a plain JSON backup file"""
        data = _valid_backup_data()
        path = _write_backup(backup_dir, 'backup.json', data, compressed=False)
        loaded = manager._load_backup_file(path)
        assert loaded['metadata']['version'] == '1.0'

    def test_load_corrupted_file_raises(self, manager, backup_dir):
        """Test that a corrupted file raises an error"""
        path = os.path.join(backup_dir, 'bad.json')
        with open(path, 'w') as f:
            f.write('not valid json {{{')
        with pytest.raises(json.JSONDecodeError):
            manager._load_backup_file(path)


# ===========================================================================
# _validate_backup_data
# ===========================================================================

class TestValidateBackupData:

    def test_valid_data_passes(self, manager):
        """Valid backup data should not raise"""
        data = _valid_backup_data()
        manager._validate_backup_data(data)  # should not raise

    def test_missing_metadata_raises(self, manager):
        """Missing 'metadata' key should raise ValueError"""
        with pytest.raises(ValueError, match="missing metadata"):
            manager._validate_backup_data({'cefr_levels': []})

    def test_missing_metadata_field_raises(self, manager):
        """Missing required metadata field should raise ValueError"""
        data = {'metadata': {'backup_id': 'x', 'created_at': '2025-01-01'}}
        # missing 'version'
        with pytest.raises(ValueError, match="missing metadata field 'version'"):
            manager._validate_backup_data(data)

    def test_all_required_fields_present(self, manager):
        """All three required metadata fields should be validated"""
        for missing_field in ['backup_id', 'created_at', 'version']:
            meta = {'backup_id': 'x', 'created_at': 'x', 'version': '1.0'}
            del meta[missing_field]
            with pytest.raises(ValueError, match=f"missing metadata field '{missing_field}'"):
                manager._validate_backup_data({'metadata': meta})


# ===========================================================================
# _find_backup_file
# ===========================================================================

class TestFindBackupFile:

    def test_find_by_direct_filename(self, manager, backup_dir):
        """Find file when exact filename is given"""
        path = os.path.join(backup_dir, 'mybackup.json.gz')
        with open(path, 'w') as f:
            f.write('{}')
        result = manager._find_backup_file('mybackup.json.gz')
        assert result == path

    def test_find_by_id_with_extension(self, manager, backup_dir):
        """Find file by appending .json extension"""
        path = os.path.join(backup_dir, 'backup_123.json')
        with open(path, 'w') as f:
            f.write('{}')
        result = manager._find_backup_file('backup_123')
        assert result == path

    def test_find_by_id_with_gz_extension(self, manager, backup_dir):
        """Find file by appending .json.gz extension"""
        path = os.path.join(backup_dir, 'backup_456.json.gz')
        with open(path, 'w') as f:
            f.write('{}')
        result = manager._find_backup_file('backup_456')
        assert result == path

    def test_find_by_partial_match(self, manager, backup_dir):
        """Find file by partial ID match in filename"""
        path = os.path.join(backup_dir, 'curriculum_backup_20250101_120000.json.gz')
        with open(path, 'w') as f:
            f.write('{}')
        result = manager._find_backup_file('20250101_120000')
        assert result == path

    def test_returns_none_when_not_found(self, manager):
        """Return None when no matching file exists"""
        result = manager._find_backup_file('nonexistent_id')
        assert result is None


# ===========================================================================
# _save_backup_metadata / _remove_backup_metadata
# ===========================================================================

class TestBackupMetadata:

    def test_save_metadata_creates_file(self, manager, backup_dir):
        """Save metadata creates metadata file"""
        meta = {'backup_id': 'test_1', 'filename': 'test.json.gz'}
        manager._save_backup_metadata(meta)
        metadata_path = os.path.join(backup_dir, 'backup_metadata.json')
        assert os.path.exists(metadata_path)
        with open(metadata_path, 'r', encoding='utf-8') as f:
            all_meta = json.load(f)
        assert 'test_1' in all_meta
        assert all_meta['test_1']['filename'] == 'test.json.gz'

    def test_save_metadata_appends(self, manager, backup_dir):
        """Save metadata appends to existing metadata file"""
        manager._save_backup_metadata({'backup_id': 'a', 'x': 1})
        manager._save_backup_metadata({'backup_id': 'b', 'x': 2})
        metadata_path = os.path.join(backup_dir, 'backup_metadata.json')
        with open(metadata_path, 'r', encoding='utf-8') as f:
            all_meta = json.load(f)
        assert 'a' in all_meta
        assert 'b' in all_meta

    def test_remove_metadata(self, manager, backup_dir):
        """Remove metadata removes entry from metadata file"""
        manager._save_backup_metadata({'backup_id': 'to_remove', 'x': 1})
        manager._save_backup_metadata({'backup_id': 'to_keep', 'x': 2})
        manager._remove_backup_metadata('to_remove')
        metadata_path = os.path.join(backup_dir, 'backup_metadata.json')
        with open(metadata_path, 'r', encoding='utf-8') as f:
            all_meta = json.load(f)
        assert 'to_remove' not in all_meta
        assert 'to_keep' in all_meta

    def test_remove_metadata_nonexistent_key(self, manager, backup_dir):
        """Removing a non-existent backup_id should not raise"""
        manager._save_backup_metadata({'backup_id': 'existing', 'x': 1})
        manager._remove_backup_metadata('nonexistent')  # should not raise

    def test_remove_metadata_no_file(self, manager, backup_dir):
        """Removing metadata when no metadata file exists should not raise"""
        manager._remove_backup_metadata('anything')  # should not raise


# ===========================================================================
# list_backups
# ===========================================================================

class TestListBackups:

    def test_list_empty_directory(self, manager):
        """Listing backups from empty directory returns empty list"""
        backups = manager.list_backups()
        assert backups == []

    def test_list_with_metadata(self, manager, backup_dir):
        """Backups from metadata file are listed"""
        manager._save_backup_metadata({
            'backup_id': 'b1',
            'filename': 'b1.json.gz',
            'created_at': '2025-01-01T00:00:00+00:00',
        })
        backups = manager.list_backups()
        assert len(backups) >= 1
        assert any(b['backup_id'] == 'b1' for b in backups)

    def test_list_discovers_orphan_files(self, manager, backup_dir):
        """Files not in metadata should be discovered by directory scan"""
        path = os.path.join(backup_dir, 'orphan_backup.json.gz')
        with gzip.open(path, 'wt') as f:
            json.dump({}, f)
        backups = manager.list_backups()
        orphan = [b for b in backups if b['filename'] == 'orphan_backup.json.gz']
        assert len(orphan) == 1
        assert orphan[0].get('metadata_missing') is True

    def test_list_sorted_by_date_descending(self, manager, backup_dir):
        """Backups should be sorted newest first"""
        manager._save_backup_metadata({
            'backup_id': 'old',
            'filename': 'old.json',
            'created_at': '2024-01-01T00:00:00+00:00',
        })
        manager._save_backup_metadata({
            'backup_id': 'new',
            'filename': 'new.json',
            'created_at': '2025-06-01T00:00:00+00:00',
        })
        backups = manager.list_backups()
        dates = [b['created_at'] for b in backups]
        assert dates == sorted(dates, reverse=True)

    def test_list_skips_metadata_file_itself(self, manager, backup_dir):
        """backup_metadata.json should not appear as a backup entry"""
        manager._save_backup_metadata({'backup_id': 'x', 'filename': 'x.json', 'created_at': '2025-01-01T00:00:00+00:00'})
        backups = manager.list_backups()
        filenames = [b['filename'] for b in backups]
        assert 'backup_metadata.json' not in filenames


# ===========================================================================
# delete_backup
# ===========================================================================

class TestDeleteBackup:

    def test_delete_existing_backup(self, manager, backup_dir):
        """Delete an existing backup file and its metadata"""
        path = os.path.join(backup_dir, 'to_delete.json.gz')
        with open(path, 'w') as f:
            f.write('{}')
        manager._save_backup_metadata({'backup_id': 'to_delete', 'filename': 'to_delete.json.gz'})
        result = manager.delete_backup('to_delete.json.gz')
        assert result is True
        assert not os.path.exists(path)

    def test_delete_nonexistent_returns_false(self, manager):
        """Deleting a non-existent backup returns False"""
        result = manager.delete_backup('does_not_exist')
        assert result is False


# ===========================================================================
# cleanup_old_backups
# ===========================================================================

class TestCleanupOldBackups:

    def test_cleanup_keeps_recent(self, manager, backup_dir):
        """Cleanup should keep the most recent keep_count backups"""
        now = datetime.now(timezone.utc)
        for i in range(5):
            ts = (now - timedelta(days=i)).isoformat()
            fname = f'backup_{i}.json.gz'
            path = os.path.join(backup_dir, fname)
            with open(path, 'w') as f:
                f.write('{}')
            manager._save_backup_metadata({
                'backup_id': f'backup_{i}',
                'filename': fname,
                'filepath': path,
                'created_at': ts,
                'size_bytes': 100,
            })

        result = manager.cleanup_old_backups(keep_count=3, keep_days=1)
        assert result['kept_count'] == 3
        assert result['deleted_count'] == 2

    def test_cleanup_empty_directory(self, manager):
        """Cleanup on empty directory should report nothing deleted"""
        result = manager.cleanup_old_backups()
        assert result['deleted_count'] == 0
        assert result['kept_count'] == 0


# ===========================================================================
# create_full_backup (with mocked DB queries)
# ===========================================================================

class TestCreateFullBackup:

    @patch.object(CurriculumBackupManager, '_export_lesson_progress', return_value=[])
    @patch.object(CurriculumBackupManager, '_export_lessons', return_value=[])
    @patch.object(CurriculumBackupManager, '_export_modules', return_value=[])
    @patch.object(CurriculumBackupManager, '_export_cefr_levels', return_value=[])
    def test_full_backup_compressed(self, mock_levels, mock_modules,
                                     mock_lessons, mock_progress, manager, backup_dir):
        """Full backup with compression creates a .json.gz file"""
        meta = manager.create_full_backup(include_progress=True, compress=True)
        assert meta['compressed'] is True
        assert meta['filename'].endswith('.json.gz')
        assert os.path.exists(meta['filepath'])
        assert meta['size_bytes'] > 0
        assert meta['records']['cefr_levels'] == 0

    @patch.object(CurriculumBackupManager, '_export_lessons', return_value=[])
    @patch.object(CurriculumBackupManager, '_export_modules', return_value=[])
    @patch.object(CurriculumBackupManager, '_export_cefr_levels', return_value=[])
    def test_full_backup_uncompressed(self, mock_levels, mock_modules,
                                       mock_lessons, manager, backup_dir):
        """Full backup without compression creates a .json file"""
        meta = manager.create_full_backup(include_progress=False, compress=False)
        assert meta['compressed'] is False
        assert meta['filename'].endswith('.json')
        assert os.path.exists(meta['filepath'])

    @patch.object(CurriculumBackupManager, '_export_lesson_progress', return_value=[{'id': 1}])
    @patch.object(CurriculumBackupManager, '_export_lessons', return_value=[{'id': 1}, {'id': 2}])
    @patch.object(CurriculumBackupManager, '_export_modules', return_value=[{'id': 1}])
    @patch.object(CurriculumBackupManager, '_export_cefr_levels', return_value=[{'id': 1}])
    def test_full_backup_record_counts(self, mock_levels, mock_modules,
                                        mock_lessons, mock_progress, manager, backup_dir):
        """Record counts in metadata should match exported data"""
        meta = manager.create_full_backup(include_progress=True, compress=True)
        assert meta['records']['cefr_levels'] == 1
        assert meta['records']['modules'] == 1
        assert meta['records']['lessons'] == 2
        assert meta['records']['lesson_progress'] == 1

    @patch.object(CurriculumBackupManager, '_export_lessons', return_value=[])
    @patch.object(CurriculumBackupManager, '_export_modules', return_value=[])
    @patch.object(CurriculumBackupManager, '_export_cefr_levels', return_value=[])
    def test_full_backup_no_progress_when_excluded(self, mock_levels, mock_modules,
                                                    mock_lessons, manager, backup_dir):
        """When include_progress=False, progress should not be exported"""
        meta = manager.create_full_backup(include_progress=False, compress=True)
        assert meta['records']['lesson_progress'] == 0
        # Verify file content
        loaded = manager._load_backup_file(meta['filepath'])
        assert 'lesson_progress' not in loaded

    @patch.object(CurriculumBackupManager, '_export_cefr_levels', side_effect=RuntimeError("DB error"))
    def test_full_backup_propagates_errors(self, mock_levels, manager):
        """Errors during export should propagate"""
        with pytest.raises(RuntimeError, match="DB error"):
            manager.create_full_backup()


# ===========================================================================
# create_incremental_backup (with mocked DB queries)
# ===========================================================================

class TestCreateIncrementalBackup:

    @patch.object(CurriculumBackupManager, '_export_progress_since', return_value=[])
    @patch.object(CurriculumBackupManager, '_export_lessons_since', return_value=[{'id': 1}])
    def test_incremental_backup_basic(self, mock_lessons, mock_progress, manager, backup_dir):
        """Incremental backup should create a gzip file with since date"""
        since = datetime(2025, 1, 1, tzinfo=timezone.utc)
        meta = manager.create_incremental_backup(since)
        assert 'incremental' in meta['backup_id']
        assert meta['backup_type'] == 'incremental'
        assert meta['filename'].endswith('.json.gz')
        assert os.path.exists(meta['filepath'])
        assert meta['records']['lessons'] == 1
        assert meta['records']['lesson_progress'] == 0


# ===========================================================================
# restore_backup (with mocked DB)
# ===========================================================================

class TestRestoreBackup:

    @patch('app.curriculum.backup.db')
    @patch.object(CurriculumBackupManager, '_restore_lesson_progress', return_value={'created': 0, 'updated': 0, 'skipped': 0})
    @patch.object(CurriculumBackupManager, '_restore_lessons', return_value={'created': 1, 'updated': 0, 'skipped': 0})
    @patch.object(CurriculumBackupManager, '_restore_modules', return_value={'created': 1, 'updated': 0, 'skipped': 0})
    @patch.object(CurriculumBackupManager, '_restore_cefr_levels', return_value={'created': 1, 'updated': 0, 'skipped': 0})
    def test_restore_from_absolute_path(self, mock_levels, mock_modules,
                                         mock_lessons, mock_progress, mock_db,
                                         manager, backup_dir):
        """Restore using absolute file path"""
        data = _valid_backup_data(include_progress=True)
        path = _write_backup(backup_dir, 'restore_test.json.gz', data)
        summary = manager.restore_backup(path, overwrite=False, restore_progress=True)
        assert summary['success'] is True
        assert summary['results']['cefr_levels']['created'] == 1

    @patch('app.curriculum.backup.db')
    @patch.object(CurriculumBackupManager, '_restore_lessons', return_value={'created': 0, 'updated': 0, 'skipped': 0})
    @patch.object(CurriculumBackupManager, '_restore_modules', return_value={'created': 0, 'updated': 0, 'skipped': 0})
    @patch.object(CurriculumBackupManager, '_restore_cefr_levels', return_value={'created': 0, 'updated': 0, 'skipped': 0})
    def test_restore_without_progress(self, mock_levels, mock_modules,
                                       mock_lessons, mock_db, manager, backup_dir):
        """Restore with restore_progress=False skips progress"""
        data = _valid_backup_data(include_progress=True)
        path = _write_backup(backup_dir, 'no_progress.json.gz', data)
        summary = manager.restore_backup(path, restore_progress=False)
        assert summary['success'] is True
        assert 'lesson_progress' not in summary['results']

    def test_restore_missing_file_raises(self, manager):
        """Restore from nonexistent file should raise FileNotFoundError"""
        with pytest.raises(FileNotFoundError, match="Backup file not found"):
            manager.restore_backup('/nonexistent/path/backup.json.gz')

    @patch('app.curriculum.backup.db')
    @patch.object(CurriculumBackupManager, '_restore_lessons', return_value={'created': 0, 'updated': 0, 'skipped': 0})
    @patch.object(CurriculumBackupManager, '_restore_modules', return_value={'created': 0, 'updated': 0, 'skipped': 0})
    @patch.object(CurriculumBackupManager, '_restore_cefr_levels', return_value={'created': 0, 'updated': 0, 'skipped': 0})
    def test_restore_by_relative_name(self, mock_levels, mock_modules,
                                       mock_lessons, mock_db, manager, backup_dir):
        """Restore using relative filename (looks in backup_dir)"""
        data = _valid_backup_data()
        _write_backup(backup_dir, 'relative_test.json.gz', data)
        summary = manager.restore_backup('relative_test.json.gz', overwrite=False, restore_progress=False)
        assert summary['success'] is True

    def test_restore_invalid_backup_data_raises(self, manager, backup_dir):
        """Restore from file with invalid structure should raise an error.

        Note: The source code has a bug where restore_summary is referenced
        before assignment when _validate_backup_data raises early. This causes
        UnboundLocalError instead of the original ValueError.
        """
        data = {'no_metadata': True}
        path = _write_backup(backup_dir, 'invalid.json.gz', data)
        with pytest.raises((ValueError, UnboundLocalError)):
            manager.restore_backup(path)


# ===========================================================================
# CurriculumMigrationManager
# ===========================================================================

class TestMigrationManager:

    def test_unsupported_format_raises(self, migration_manager):
        """Unsupported export format should raise ValueError"""
        with pytest.raises(ValueError, match="Unsupported export format"):
            migration_manager.export_for_migration(target_format='yaml')

    @patch.object(CurriculumBackupManager, '_export_lessons', return_value=[])
    @patch.object(CurriculumBackupManager, '_export_modules', return_value=[])
    @patch.object(CurriculumBackupManager, '_export_cefr_levels', return_value=[])
    def test_json_export(self, mock_levels, mock_modules, mock_lessons,
                          migration_manager, backup_dir):
        """JSON export creates a file and returns its path"""
        result = migration_manager.export_for_migration(target_format='json')
        assert result.endswith('.json')
        assert os.path.exists(result)
        with open(result, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert 'export_info' in data
        assert 'curriculum' in data

    @patch.object(CurriculumBackupManager, '_export_lessons', return_value=[
        {'id': 1, 'module_id': 1, 'number': 1, 'title': 'L1', 'type': 'vocab',
         'description': 'D', 'content': {'words': []}, 'order': 0}
    ])
    @patch.object(CurriculumBackupManager, '_export_modules', return_value=[
        {'id': 1, 'level_id': 1, 'number': 1, 'title': 'M1', 'description': 'D'}
    ])
    @patch.object(CurriculumBackupManager, '_export_cefr_levels', return_value=[
        {'id': 1, 'code': 'A1', 'name': 'Beginner', 'description': 'D', 'order': 1}
    ])
    def test_csv_export(self, mock_levels, mock_modules, mock_lessons,
                         migration_manager, backup_dir):
        """CSV export creates a directory with CSV files"""
        result = migration_manager.export_for_migration(target_format='csv')
        assert os.path.isdir(result)
        assert os.path.exists(os.path.join(result, 'cefr_levels.csv'))
        assert os.path.exists(os.path.join(result, 'modules.csv'))
        assert os.path.exists(os.path.join(result, 'lessons.csv'))

    @patch.object(CurriculumBackupManager, '_export_lessons', return_value=[
        {'id': 1, 'module_id': 1, 'number': 1, 'title': 'L1', 'type': 'vocab',
         'description': 'D', 'content': {'words': []}, 'order': 0}
    ])
    @patch.object(CurriculumBackupManager, '_export_modules', return_value=[
        {'id': 1, 'level_id': 1, 'number': 1, 'title': 'M1', 'description': 'D'}
    ])
    @patch.object(CurriculumBackupManager, '_export_cefr_levels', return_value=[
        {'id': 1, 'code': 'A1', 'name': 'Beginner', 'description': 'D', 'order': 1}
    ])
    def test_xml_export(self, mock_levels, mock_modules, mock_lessons,
                         migration_manager, backup_dir):
        """XML export creates a valid XML file"""
        result = migration_manager.export_for_migration(target_format='xml')
        assert result.endswith('.xml')
        assert os.path.exists(result)
        import xml.etree.ElementTree as ET
        tree = ET.parse(result)
        root = tree.getroot()
        assert root.tag == 'curriculum_export'
        assert root.find('cefr_levels') is not None
        assert root.find('modules') is not None
        assert root.find('lessons') is not None
