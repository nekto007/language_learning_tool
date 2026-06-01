import logging
import os
import tempfile

from flask import Blueprint, request, send_file
from flask_login import current_user

from app.api.decorators import api_auth_required
from app.api.errors import api_error
from app.utils.anki_export import create_anki_package
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)

api_anki = Blueprint('api_anki', __name__)


@api_anki.route('/export-anki', methods=['POST'])
# CSRF protection REQUIRED
@api_auth_required
def export_anki():
    if not request.is_json:
        return api_error('invalid_json', 'Invalid JSON format', 400)

    data = request.get_json()
    deck_name = data.get('deckName')
    card_format = data.get('cardFormat')
    include_pronunciation = data.get('includePronunciation', False)
    include_examples = data.get('includeExamples', False)
    update_status = data.get('updateStatus', False)
    word_ids = data.get('wordIds', [])

    if not deck_name or not card_format or not word_ids:
        return api_error('missing_fields', 'Missing required parameters', 400)

    try:
        # Get words
        words = CollectionWords.query.filter(CollectionWords.id.in_(word_ids)).all()

        if not words:
            return api_error('not_found', 'No words found', 404)

        # Temporary file to store the Anki package
        with tempfile.NamedTemporaryFile(suffix='.apkg', delete=False) as temp_file:
            temp_path = temp_file.name

        # Create Anki package
        create_anki_package(
            words=words,
            output_file=temp_path,
            deck_name=deck_name,
            card_format=card_format,
            include_pronunciation=include_pronunciation,
            include_examples=include_examples
        )

        # Update status if requested
        if update_status:
            for word in words:
                current_user.set_word_status(word.id, 3)  # Set to "Active"

        # Send the file
        return send_file(
            temp_path,
            as_attachment=True,
            download_name=f"{deck_name}.apkg",
            mimetype='application/octet-stream'
        )

    except Exception as e:
        if 'temp_path' in locals():
            try:
                os.unlink(temp_path)
            except Exception:
                logger.exception("Failed to clean up temp file: %s", temp_path)

        logger.error(f'Anki export error: {e}', exc_info=True)
        return api_error('export_failed', 'Export failed', 500)
