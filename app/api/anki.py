import os
import tempfile

from flask import Blueprint, jsonify, request, send_file
from flask_login import current_user

from app import csrf
from app.api.auth import api_login_required
from app.utils.anki_export import create_anki_package
from app.words.models import CollectionWords

api_anki = Blueprint('api_anki', __name__)


@api_anki.route('/export-anki', methods=['POST'])
@# CSRF protection REQUIRED
@api_login_required
def export_anki():
    if not request.is_json:
        return jsonify({
            'success': False,
            'error': 'Invalid JSON format',
            'status_code': 400
        }), 400

    data = request.get_json()
    deck_name = data.get('deckName')
    card_format = data.get('cardFormat')
    include_pronunciation = data.get('includePronunciation', False)
    include_examples = data.get('includeExamples', False)
    update_status = data.get('updateStatus', False)
    word_ids = data.get('wordIds', [])

    if not deck_name or not card_format or not word_ids:
        return jsonify({
            'success': False,
            'error': 'Missing required parameters',
            'status_code': 400
        }), 400

    try:
        # Get words
        words = CollectionWords.query.filter(CollectionWords.id.in_(word_ids)).all()

        if not words:
            return jsonify({
                'success': False,
                'error': 'No words found',
                'status_code': 404
            }), 404

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
            except:
                pass

        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 500
        }), 500
