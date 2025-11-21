"""Integration tests for Anki Export API endpoint"""
import pytest
import uuid
from unittest.mock import patch, MagicMock


@pytest.fixture
def test_words_for_anki(db_session, test_user):
    """Create test words for Anki export"""
    from app.words.models import CollectionWords

    words = []
    for i in range(3):
        word = CollectionWords(
            english_word=f'ankiword{i}_{uuid.uuid4().hex[:6]}',
            russian_word=f'анкислово{i}',
            level='B1',
            sentences=f'Example sentence with ankiword{i}.',
            listening='pronunciation audio'
        )
        db_session.add(word)
        words.append(word)

    db_session.commit()
    return words


class TestExportAnki:
    """Test POST /api/export-anki endpoint"""

    @patch('app.api.anki.create_anki_package')
    @patch('app.api.anki.send_file')
    def test_export_anki_success(self, mock_send_file, mock_create_package,
                                  authenticated_client, test_words_for_anki):
        """Test successfully exporting words to Anki"""
        word_ids = [word.id for word in test_words_for_anki]

        # Mock send_file to return a mock response
        mock_response = MagicMock()
        mock_send_file.return_value = mock_response

        response = authenticated_client.post(
            '/api/export-anki',
            json={
                'deckName': 'Test Deck',
                'cardFormat': 'basic',
                'includePronunciation': True,
                'includeExamples': True,
                'updateStatus': False,
                'wordIds': word_ids
            }
        )

        assert mock_create_package.called
        assert mock_send_file.called

        # Verify parameters
        call_args = mock_create_package.call_args
        assert len(call_args.kwargs['words']) == 3
        assert call_args.kwargs['deck_name'] == 'Test Deck'

    def test_export_anki_missing_required_fields(self, authenticated_client):
        """Test error when missing required parameters"""
        response = authenticated_client.post(
            '/api/export-anki',
            json={
                'deckName': 'Test Deck',
                # Missing cardFormat and wordIds
            }
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'Missing required parameters' in data['error']

    def test_export_anki_invalid_json(self, authenticated_client):
        """Test error with invalid JSON"""
        response = authenticated_client.post(
            '/api/export-anki',
            data='not json',
            content_type='application/json'
        )

        # Flask returns 400 for invalid JSON, might not have JSON body
        assert response.status_code == 400

    def test_export_anki_no_words_found(self, authenticated_client):
        """Test error when no words match the IDs"""
        response = authenticated_client.post(
            '/api/export-anki',
            json={
                'deckName': 'Test Deck',
                'cardFormat': 'basic',
                'wordIds': [999999, 999998]
            }
        )

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'No words found' in data['error']

    @patch('app.api.anki.create_anki_package')
    @patch('app.api.anki.send_file')
    def test_export_anki_with_status_update(self, mock_send_file, mock_create_package,
                                            authenticated_client, test_words_for_anki, db_session):
        """Test exporting with status update"""
        word_ids = [word.id for word in test_words_for_anki]

        mock_response = MagicMock()
        mock_send_file.return_value = mock_response

        response = authenticated_client.post(
            '/api/export-anki',
            json={
                'deckName': 'Test Deck',
                'cardFormat': 'basic',
                'updateStatus': True,
                'wordIds': word_ids
            }
        )

        # Verify called
        assert mock_create_package.called

    @patch('app.api.anki.create_anki_package', side_effect=Exception('Package creation failed'))
    @patch('app.api.anki.os.unlink')
    def test_export_anki_error_handling(self, mock_unlink, mock_create_package,
                                       authenticated_client, test_words_for_anki):
        """Test error handling when package creation fails"""
        word_ids = [word.id for word in test_words_for_anki]

        response = authenticated_client.post(
            '/api/export-anki',
            json={
                'deckName': 'Test Deck',
                'cardFormat': 'basic',
                'wordIds': word_ids
            }
        )

        assert response.status_code == 500
        data = response.get_json()
        assert data['success'] is False
        assert 'Package creation failed' in data['error']

    @patch('app.api.anki.create_anki_package')
    @patch('app.api.anki.send_file')
    def test_export_anki_different_formats(self, mock_send_file, mock_create_package,
                                           authenticated_client, test_words_for_anki):
        """Test export with different card formats"""
        word_ids = [word.id for word in test_words_for_anki]

        mock_response = MagicMock()
        mock_send_file.return_value = mock_response

        for card_format in ['basic', 'reverse', 'both']:
            response = authenticated_client.post(
                '/api/export-anki',
                json={
                    'deckName': 'Test Deck',
                    'cardFormat': card_format,
                    'wordIds': word_ids
                }
            )

            # Should succeed
            assert mock_create_package.called

    def test_export_anki_without_auth(self, client, test_words_for_anki):
        """Test endpoint requires authentication"""
        word_ids = [word.id for word in test_words_for_anki]

        response = client.post(
            '/api/export-anki',
            json={
                'deckName': 'Test Deck',
                'cardFormat': 'basic',
                'wordIds': word_ids
            }
        )

        assert response.status_code == 401

    @patch('app.api.anki.create_anki_package')
    @patch('app.api.anki.send_file')
    def test_export_anki_with_options(self, mock_send_file, mock_create_package,
                                     authenticated_client, test_words_for_anki):
        """Test export with all optional parameters"""
        word_ids = [word.id for word in test_words_for_anki]

        mock_response = MagicMock()
        mock_send_file.return_value = mock_response

        response = authenticated_client.post(
            '/api/export-anki',
            json={
                'deckName': 'Complete Test Deck',
                'cardFormat': 'both',
                'includePronunciation': True,
                'includeExamples': True,
                'updateStatus': True,
                'wordIds': word_ids
            }
        )

        # Verify create_anki_package was called with correct parameters
        call_args = mock_create_package.call_args
        assert call_args.kwargs['deck_name'] == 'Complete Test Deck'
        assert call_args.kwargs['card_format'] == 'both'
        assert call_args.kwargs['include_pronunciation'] is True
        assert call_args.kwargs['include_examples'] is True

    @patch('app.api.anki.create_anki_package')
    @patch('app.api.anki.send_file')
    def test_export_anki_empty_word_list(self, mock_send_file, mock_create_package,
                                        authenticated_client):
        """Test export with empty word list"""
        response = authenticated_client.post(
            '/api/export-anki',
            json={
                'deckName': 'Test Deck',
                'cardFormat': 'basic',
                'wordIds': []
            }
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
