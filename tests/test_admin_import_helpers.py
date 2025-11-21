"""
Tests for Admin Import Helpers (app/admin/utils/import_helpers.py)

Tests temporary file management for import operations:
- save_import_data - saves data to temp files
- load_import_data - loads data from temp files
- delete_import_data - deletes temp files
- cleanup_old_imports - removes old files

Coverage target: 100% for app/admin/utils/import_helpers.py
"""
import pytest
import os
import json
import time
from datetime import datetime


class TestSaveImportData:
    """Test save_import_data function"""

    def test_saves_data_to_file(self):
        """Test saves data to temporary file"""
        from app.admin.utils.import_helpers import save_import_data, IMPORT_TEMP_DIR

        data = {'test': 'value', 'numbers': [1, 2, 3]}
        import_id = save_import_data(data)

        assert import_id is not None
        assert len(import_id) > 0

        # Check file exists
        file_path = os.path.join(IMPORT_TEMP_DIR, f"{import_id}.json")
        assert os.path.exists(file_path)

        # Clean up
        os.remove(file_path)

    def test_returns_uuid(self):
        """Test returns valid UUID string"""
        from app.admin.utils.import_helpers import save_import_data, IMPORT_TEMP_DIR
        import uuid

        data = {'test': 'data'}
        import_id = save_import_data(data)

        # Should be valid UUID
        try:
            uuid.UUID(import_id)
            valid_uuid = True
        except ValueError:
            valid_uuid = False

        assert valid_uuid

        # Clean up
        file_path = os.path.join(IMPORT_TEMP_DIR, f"{import_id}.json")
        if os.path.exists(file_path):
            os.remove(file_path)

    def test_saves_unicode_data(self):
        """Test saves unicode data correctly"""
        from app.admin.utils.import_helpers import save_import_data, load_import_data, delete_import_data

        data = {'russian': 'Привет мир', 'chinese': '你好世界'}
        import_id = save_import_data(data)

        # Load and verify
        loaded = load_import_data(import_id)
        assert loaded['russian'] == 'Привет мир'
        assert loaded['chinese'] == '你好世界'

        # Clean up
        delete_import_data(import_id)

    def test_creates_directory_if_not_exists(self):
        """Test creates IMPORT_TEMP_DIR if it doesn't exist"""
        from app.admin.utils.import_helpers import IMPORT_TEMP_DIR

        # Directory should exist after import
        assert os.path.exists(IMPORT_TEMP_DIR)


class TestLoadImportData:
    """Test load_import_data function"""

    def test_loads_existing_data(self):
        """Test loads data from existing file"""
        from app.admin.utils.import_helpers import save_import_data, load_import_data, delete_import_data

        original_data = {'key': 'value', 'list': [1, 2, 3]}
        import_id = save_import_data(original_data)

        loaded_data = load_import_data(import_id)

        assert loaded_data == original_data

        # Clean up
        delete_import_data(import_id)

    def test_returns_none_for_missing_file(self):
        """Test returns None when file doesn't exist"""
        from app.admin.utils.import_helpers import load_import_data

        result = load_import_data('non-existent-id')

        assert result is None

    def test_loads_complex_data_structures(self):
        """Test loads nested data structures"""
        from app.admin.utils.import_helpers import save_import_data, load_import_data, delete_import_data

        complex_data = {
            'level1': {
                'level2': {
                    'level3': ['a', 'b', 'c']
                }
            },
            'array': [1, 2, {'nested': True}]
        }

        import_id = save_import_data(complex_data)
        loaded = load_import_data(import_id)

        assert loaded == complex_data

        # Clean up
        delete_import_data(import_id)


class TestDeleteImportData:
    """Test delete_import_data function"""

    def test_deletes_existing_file(self):
        """Test deletes existing import file"""
        from app.admin.utils.import_helpers import save_import_data, delete_import_data, IMPORT_TEMP_DIR

        data = {'test': 'data'}
        import_id = save_import_data(data)

        file_path = os.path.join(IMPORT_TEMP_DIR, f"{import_id}.json")
        assert os.path.exists(file_path)

        delete_import_data(import_id)

        assert not os.path.exists(file_path)

    def test_handles_missing_file_gracefully(self):
        """Test doesn't raise error for non-existent file"""
        from app.admin.utils.import_helpers import delete_import_data

        # Should not raise exception
        delete_import_data('non-existent-id')


class TestCleanupOldImports:
    """Test cleanup_old_imports function"""

    def test_removes_old_files(self):
        """Test removes files older than 1 hour"""
        from app.admin.utils.import_helpers import IMPORT_TEMP_DIR, cleanup_old_imports
        import uuid

        # Create an old file (modify its timestamp)
        old_import_id = str(uuid.uuid4())
        old_file_path = os.path.join(IMPORT_TEMP_DIR, f"{old_import_id}.json")

        with open(old_file_path, 'w') as f:
            json.dump({'old': 'data'}, f)

        # Set file timestamp to 2 hours ago
        two_hours_ago = time.time() - 7200
        os.utime(old_file_path, (two_hours_ago, two_hours_ago))

        # Run cleanup
        cleanup_old_imports()

        # Old file should be deleted
        assert not os.path.exists(old_file_path)

    def test_keeps_recent_files(self):
        """Test keeps files newer than 1 hour"""
        from app.admin.utils.import_helpers import save_import_data, delete_import_data, cleanup_old_imports

        # Create a recent file
        data = {'recent': 'data'}
        import_id = save_import_data(data)

        # Run cleanup
        cleanup_old_imports()

        # Recent file should still exist
        from app.admin.utils.import_helpers import load_import_data
        loaded = load_import_data(import_id)

        assert loaded == data

        # Clean up
        delete_import_data(import_id)

    def test_handles_non_json_files(self):
        """Test ignores non-JSON files in directory"""
        from app.admin.utils.import_helpers import IMPORT_TEMP_DIR, cleanup_old_imports

        # Create a non-JSON file
        txt_file = os.path.join(IMPORT_TEMP_DIR, 'test.txt')
        with open(txt_file, 'w') as f:
            f.write('test')

        # Run cleanup
        cleanup_old_imports()

        # Non-JSON file should not be deleted
        assert os.path.exists(txt_file)

        # Clean up
        os.remove(txt_file)

    def test_handles_empty_directory(self):
        """Test handles empty directory gracefully"""
        from app.admin.utils.import_helpers import cleanup_old_imports

        # Should not raise exception on empty directory
        cleanup_old_imports()


class TestImportHelpersIntegration:
    """Integration tests for import helpers"""

    def test_full_import_workflow(self):
        """Test complete workflow: save -> load -> delete"""
        from app.admin.utils.import_helpers import (
            save_import_data, load_import_data, delete_import_data
        )

        # Save data
        original_data = {
            'translations': [
                {'en': 'hello', 'ru': 'привет'},
                {'en': 'world', 'ru': 'мир'}
            ],
            'metadata': {'count': 2}
        }
        import_id = save_import_data(original_data)

        # Load data
        loaded_data = load_import_data(import_id)
        assert loaded_data == original_data

        # Delete data
        delete_import_data(import_id)
        assert load_import_data(import_id) is None

    def test_multiple_imports_dont_conflict(self):
        """Test multiple imports don't interfere with each other"""
        from app.admin.utils.import_helpers import (
            save_import_data, load_import_data, delete_import_data
        )

        data1 = {'import': 1}
        data2 = {'import': 2}
        data3 = {'import': 3}

        id1 = save_import_data(data1)
        id2 = save_import_data(data2)
        id3 = save_import_data(data3)

        # All imports should be independent
        assert load_import_data(id1) == data1
        assert load_import_data(id2) == data2
        assert load_import_data(id3) == data3

        # Clean up
        delete_import_data(id1)
        delete_import_data(id2)
        delete_import_data(id3)
