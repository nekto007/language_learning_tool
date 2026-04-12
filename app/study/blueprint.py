from flask import Blueprint, url_for

from app.study.services import DeckService

study = Blueprint('study', __name__, template_folder='templates')

is_auto_deck = DeckService.is_auto_deck


def get_audio_url_for_word(word):
    if not hasattr(word, 'get_download') or word.get_download != 1 or not word.listening:
        return None

    from app.utils.audio import parse_audio_filename
    filename = parse_audio_filename(word.listening)
    if not filename:
        return None

    return url_for('static', filename=f'audio/{filename}')
