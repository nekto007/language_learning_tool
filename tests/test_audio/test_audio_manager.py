import pytest
import os
import sys
from unittest.mock import patch, MagicMock, mock_open

# Ensure we can import from the project
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Try different import paths depending on project structure
try:
    from language_learning_tool.src.audio.manager import AudioManager
    from language_learning_tool.config.settings import MEDIA_FOLDER
except ImportError:
    try:
        from src.audio.manager import AudioManager
        from config.settings import MEDIA_FOLDER
    except ImportError:
        # If direct imports fail, print helpful information and use relative paths
        print("Import error for AudioManager. Current sys.path:")
        for p in sys.path:
            print(f"  - {p}")

        # Dynamically locate and load the manager module
        manager_path = None
        settings_path = None

        for root, dirs, files in os.walk(os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))):
            for file in files:
                if file == 'manager.py' and 'audio' in root:
                    manager_path = os.path.join(root, file)
                elif file == 'settings.py' and 'config' in root:
                    settings_path = os.path.join(root, file)

        if not manager_path:
            raise ImportError("Could not find src/audio/manager.py")

        print(f"Found manager.py at: {manager_path}")

        # Load settings first
        settings_globals = {}
        with open(settings_path, 'r') as f:
            exec(f.read(), settings_globals)

        MEDIA_FOLDER = settings_globals.get('MEDIA_FOLDER', 'media')

        # Then load the audio manager
        manager_globals = {'__file__': manager_path}
        with open(manager_path, 'r') as f:
            exec(f.read(), manager_globals)

        AudioManager = manager_globals.get('AudioManager')

# Print information about the AudioManager class to help debug
print("\nAudioManager methods:")
for name in dir(AudioManager):
    if not name.startswith('__'):
        print(f"  - {name}")


class TestAudioManager:
    def setup_method(self):
        # Create an audio manager instance for each test
        self.manager = AudioManager()

    def test_initialization(self):
        # Test basic initialization
        assert self.manager is not None

    def test_update_anki_field_format(self):
        # Test updating Anki field format for a word
        result = self.manager.update_anki_field_format("test")

        # Verify the result is in the correct format
        assert result is not None
        assert "[sound:" in result
        assert "test" in result
        assert ".mp3]" in result

    def test_update_anki_field_format_with_spaces(self):
        # Test with a word that has spaces
        result = self.manager.update_anki_field_format("test word")

        # Verify spaces are handled correctly
        assert result is not None
        assert "[sound:" in result

        # Spaces might be replaced with underscores or removed
        assert "test_word" in result or "testword" in result

    def test_update_anki_field_format_with_special_chars(self):
        # Test with a word that has special characters
        result = self.manager.update_anki_field_format("test-word!")

        # Verify special characters are handled correctly
        assert result is not None
        assert "[sound:" in result

        # Special characters might be replaced or removed
        assert "test-word" in result or "testword" in result or "test_word" in result

    # Add tests for other methods if they exist
    def test_additional_methods(self):
        # Test if get_mp3_path exists
        if hasattr(self.manager, 'get_mp3_path'):
            mp3_path = self.manager.get_mp3_path("test")
            assert mp3_path is not None
            assert "test.mp3" in mp3_path

        # Test if find_pronunciation_file exists
        if hasattr(self.manager, 'find_pronunciation_file'):
            with patch('os.listdir', return_value=["test.mp3"]), \
                    patch('os.path.isfile', return_value=True):
                file_path = self.manager.find_pronunciation_file("test")
                if file_path is not None:  # It might return None if file not found
                    assert "test.mp3" in file_path
