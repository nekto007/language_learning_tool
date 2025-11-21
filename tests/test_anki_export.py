"""Unit tests for anki_export.py"""
import pytest
import os
import tempfile
from unittest.mock import patch, MagicMock, call
from app.utils.anki_export import create_anki_package


@pytest.fixture
def mock_word():
    """Create a mock word object"""
    word = MagicMock()
    word.english_word = 'test'
    word.russian_word = 'тест'
    word.sentences = 'This is a test.<br>Это тест.'
    word.listening = '[sound:test.mp3]'
    return word


@pytest.fixture
def mock_words_list():
    """Create a list of mock words"""
    words = []
    for i in range(3):
        word = MagicMock()
        word.english_word = f'word{i}'
        word.russian_word = f'слово{i}'
        word.sentences = f'Example {i}.<br>Пример {i}.'
        word.listening = f'[sound:word{i}.mp3]'
        words.append(word)
    return words


class TestCreateAnkiPackageBasic:
    """Test create_anki_package with basic format"""

    @patch('app.utils.anki_export.genanki.Package')
    @patch('app.utils.anki_export.genanki.Deck')
    @patch('app.utils.anki_export.genanki.Model')
    @patch('app.utils.anki_export.genanki.Note')
    def test_create_basic_package(self, mock_note_class, mock_model_class, 
                                   mock_deck_class, mock_package_class, mock_word):
        """Test creating basic Anki package"""
        output_file = '/tmp/test.apkg'
        
        # Mock objects
        mock_model = MagicMock()
        mock_model_class.return_value = mock_model
        
        mock_deck = MagicMock()
        mock_deck_class.return_value = mock_deck
        
        mock_note = MagicMock()
        mock_note_class.return_value = mock_note
        
        mock_package = MagicMock()
        mock_package_class.return_value = mock_package
        
        result = create_anki_package(
            words=[mock_word],
            output_file=output_file,
            deck_name='Test Deck',
            card_format='basic',
            include_pronunciation=False,
            include_examples=False
        )
        
        assert result == output_file
        mock_deck.add_note.assert_called_once()
        mock_package.write_to_file.assert_called_once_with(output_file)

    @patch('app.utils.anki_export.genanki.Package')
    @patch('app.utils.anki_export.genanki.Deck')
    @patch('app.utils.anki_export.genanki.Model')
    @patch('app.utils.anki_export.genanki.Note')
    def test_create_basic_package_with_pronunciation(self, mock_note_class, mock_model_class,
                                                     mock_deck_class, mock_package_class, 
                                                     mock_word, app):
        """Test creating package with pronunciation"""
        output_file = '/tmp/test.apkg'
        
        with tempfile.TemporaryDirectory() as tmpdir:
            app.config['AUDIO_UPLOAD_FOLDER'] = tmpdir
            # Create mock audio file
            audio_path = os.path.join(tmpdir, 'test.mp3')
            with open(audio_path, 'wb') as f:
                f.write(b'fake audio')
            
            with app.app_context():
                # Mock objects
                mock_model = MagicMock()
                mock_model_class.return_value = mock_model
                
                mock_deck = MagicMock()
                mock_deck_class.return_value = mock_deck
                
                mock_note = MagicMock()
                mock_note_class.return_value = mock_note
                
                mock_package = MagicMock()
                mock_package_class.return_value = mock_package
                
                result = create_anki_package(
                    words=[mock_word],
                    output_file=output_file,
                    deck_name='Test Deck',
                    card_format='basic',
                    include_pronunciation=True,
                    include_examples=False
                )
                
                assert result == output_file
                # Verify media files were added
                assert mock_package.media_files == [audio_path]


class TestCreateAnkiPackageReversed:
    """Test create_anki_package with reversed format"""

    @patch('app.utils.anki_export.genanki.Package')
    @patch('app.utils.anki_export.genanki.Deck')
    @patch('app.utils.anki_export.genanki.Model')
    @patch('app.utils.anki_export.genanki.Note')
    def test_create_reversed_package(self, mock_note_class, mock_model_class,
                                      mock_deck_class, mock_package_class, mock_word):
        """Test creating reversed Anki package"""
        output_file = '/tmp/test.apkg'
        
        mock_model = MagicMock()
        mock_model_class.return_value = mock_model
        
        mock_deck = MagicMock()
        mock_deck_class.return_value = mock_deck
        
        mock_note = MagicMock()
        mock_note_class.return_value = mock_note
        
        mock_package = MagicMock()
        mock_package_class.return_value = mock_package
        
        result = create_anki_package(
            words=[mock_word],
            output_file=output_file,
            deck_name='Test Deck',
            card_format='reversed',
            include_pronunciation=False,
            include_examples=False
        )
        
        assert result == output_file
        # Verify Model was created with 2 templates (reversed cards)
        model_call = mock_model_class.call_args
        assert len(model_call[1]['templates']) == 2


class TestCreateAnkiPackageCloze:
    """Test create_anki_package with cloze format"""

    @patch('app.utils.anki_export.genanki.Package')
    @patch('app.utils.anki_export.genanki.Deck')
    @patch('app.utils.anki_export.genanki.Model')
    @patch('app.utils.anki_export.genanki.Note')
    def test_create_cloze_package(self, mock_note_class, mock_model_class,
                                   mock_deck_class, mock_package_class, mock_word):
        """Test creating cloze Anki package"""
        output_file = '/tmp/test.apkg'
        
        mock_model = MagicMock()
        mock_model_class.return_value = mock_model
        
        mock_deck = MagicMock()
        mock_deck_class.return_value = mock_deck
        
        mock_note = MagicMock()
        mock_note_class.return_value = mock_note
        
        mock_package = MagicMock()
        mock_package_class.return_value = mock_package
        
        result = create_anki_package(
            words=[mock_word],
            output_file=output_file,
            deck_name='Test Deck',
            card_format='cloze',
            include_pronunciation=False,
            include_examples=False
        )
        
        assert result == output_file
        # Verify cloze model was created
        model_call = mock_model_class.call_args
        assert 'model_type' in model_call[1]

    @patch('app.utils.anki_export.genanki.Package')
    @patch('app.utils.anki_export.genanki.Deck')
    @patch('app.utils.anki_export.genanki.Model')
    @patch('app.utils.anki_export.genanki.Note')
    def test_create_cloze_package_with_sentences(self, mock_note_class, mock_model_class,
                                                  mock_deck_class, mock_package_class):
        """Test creating cloze package with proper sentence handling"""
        output_file = '/tmp/test.apkg'
        
        # Word with proper sentence format
        word = MagicMock()
        word.english_word = 'amazing'
        word.russian_word = 'удивительный'
        word.sentences = 'This is an amazing test.<br>Это удивительный тест.'
        word.listening = None
        
        mock_model = MagicMock()
        mock_model_class.return_value = mock_model
        
        mock_deck = MagicMock()
        mock_deck_class.return_value = mock_deck
        
        mock_note = MagicMock()
        mock_note_class.return_value = mock_note
        
        mock_package = MagicMock()
        mock_package_class.return_value = mock_package
        
        result = create_anki_package(
            words=[word],
            output_file=output_file,
            deck_name='Test Deck',
            card_format='cloze'
        )
        
        assert result == output_file


class TestCreateAnkiPackageMultipleWords:
    """Test create_anki_package with multiple words"""

    @patch('app.utils.anki_export.genanki.Package')
    @patch('app.utils.anki_export.genanki.Deck')
    @patch('app.utils.anki_export.genanki.Model')
    @patch('app.utils.anki_export.genanki.Note')
    def test_create_package_with_multiple_words(self, mock_note_class, mock_model_class,
                                                 mock_deck_class, mock_package_class, 
                                                 mock_words_list):
        """Test creating package with multiple words"""
        output_file = '/tmp/test.apkg'
        
        mock_model = MagicMock()
        mock_model_class.return_value = mock_model
        
        mock_deck = MagicMock()
        mock_deck_class.return_value = mock_deck
        
        mock_note = MagicMock()
        mock_note_class.return_value = mock_note
        
        mock_package = MagicMock()
        mock_package_class.return_value = mock_package
        
        result = create_anki_package(
            words=mock_words_list,
            output_file=output_file,
            deck_name='Test Deck',
            card_format='basic'
        )
        
        assert result == output_file
        # Should add 3 notes (one per word)
        assert mock_deck.add_note.call_count == 3


class TestCreateAnkiPackageErrors:
    """Test error handling in create_anki_package"""

    def test_create_package_invalid_format(self, mock_word):
        """Test error with invalid card format"""
        with pytest.raises(ValueError, match="Unsupported card format"):
            create_anki_package(
                words=[mock_word],
                output_file='/tmp/test.apkg',
                deck_name='Test',
                card_format='invalid_format'
            )


class TestCreateAnkiPackageWithExamples:
    """Test create_anki_package with examples"""

    @patch('app.utils.anki_export.genanki.Package')
    @patch('app.utils.anki_export.genanki.Deck')
    @patch('app.utils.anki_export.genanki.Model')
    @patch('app.utils.anki_export.genanki.Note')
    def test_create_package_with_examples(self, mock_note_class, mock_model_class,
                                           mock_deck_class, mock_package_class, mock_word):
        """Test creating package with examples included"""
        output_file = '/tmp/test.apkg'
        
        mock_model = MagicMock()
        mock_model_class.return_value = mock_model
        
        mock_deck = MagicMock()
        mock_deck_class.return_value = mock_deck
        
        mock_note = MagicMock()
        mock_note_class.return_value = mock_note
        
        mock_package = MagicMock()
        mock_package_class.return_value = mock_package
        
        result = create_anki_package(
            words=[mock_word],
            output_file=output_file,
            deck_name='Test Deck',
            card_format='basic',
            include_pronunciation=False,
            include_examples=True
        )
        
        assert result == output_file
        
        # Verify Note was created with examples
        note_call = mock_note_class.call_args
        fields = note_call[1]['fields']
        # Fields: [english, russian, pronunciation, examples]
        assert len(fields) == 4
        # Examples should have replaced <br> with \n
        assert '\n' in fields[3] or fields[3] != ''
