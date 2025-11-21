# app/admin/utils/export_helpers.py

"""
Утилиты для экспорта данных в различных форматах (JSON, CSV, TXT)
"""
import csv
import io
import json
from datetime import datetime, timezone

from flask import make_response


# =============================================================================
# Экспорт слов (Words)
# =============================================================================

def export_words_json(words, status=None):
    """Экспорт слов в формате JSON"""
    words_data = []
    for word in words:
        word_dict = {
            'english_word': word.english_word,
            'russian_word': word.russian_word,
            'level': word.level if hasattr(word, 'level') else None
        }
        if hasattr(word, 'status'):
            word_dict['status'] = word.status
        words_data.append(word_dict)

    response_data = {
        'export_date': datetime.now(timezone.utc).isoformat(),
        'words_total': len(words_data),
        'status_filter': status,
        'words': words_data
    }

    response = make_response(json.dumps(response_data, ensure_ascii=False, indent=2))
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    filename = f"words_export_{status or 'all'}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


def export_words_csv(words, status=None):
    """Экспорт слов в формате CSV"""
    output = io.StringIO()
    writer = csv.writer(output)

    # Заголовки
    headers = ['English', 'Russian', 'Level']
    if words and hasattr(words[0], 'status'):
        headers.append('Status')
    writer.writerow(headers)

    # Данные
    for word in words:
        row = [word.english_word, word.russian_word, word.level if hasattr(word, 'level') else '']
        if hasattr(word, 'status'):
            row.append(word.status)
        writer.writerow(row)

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    filename = f"words_export_{status or 'all'}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


def export_words_txt(words, status=None):
    """Экспорт слов в текстовом формате"""
    lines = [f"# Words Export - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"]
    if status:
        lines.append(f"# Status filter: {status}")
    lines.append(f"# Total words: {len(words)}")
    lines.append("")

    for word in words:
        if hasattr(word, 'status'):
            lines.append(f"{word.english_word} | {word.russian_word} | {word.status}")
        else:
            lines.append(f"{word.english_word} | {word.russian_word}")

    content = '\n'.join(lines)
    response = make_response(content)
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    filename = f"words_export_{status or 'all'}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


# =============================================================================
# Экспорт аудио (Audio/Forvo)
# =============================================================================

def export_audio_list_json(words, pattern=None):
    """Экспорт списка аудио в формате JSON с Forvo URL"""
    # Создаем список объектов с word и forvo_url
    words_data = []
    for word in words:
        words_data.append({
            'word': word,
            'forvo_url': f"https://forvo.com/word/{word}/#en"
        })

    response_data = {
        'export_date': datetime.now(timezone.utc).isoformat(),
        'words_total': len(words),
        'pattern_filter': pattern,
        'purpose': 'forvo_audio_download_list',
        'words': words_data
    }

    response = make_response(json.dumps(response_data, ensure_ascii=False, indent=2))
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    filename = f"forvo_download_list_{pattern or 'all'}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


def export_audio_list_csv(words, pattern=None):
    """Экспорт списка аудио в формате CSV с Forvo URL"""
    output = io.StringIO()
    writer = csv.writer(output)

    # Заголовки
    writer.writerow(['English Word', 'Forvo URL'])

    # Данные
    for word in words:
        forvo_url = f"https://forvo.com/word/{word}/#en"
        writer.writerow([word, forvo_url])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    filename = f"forvo_download_list_{pattern or 'all'}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


def export_audio_list_txt(words, pattern=None):
    """Экспорт списка аудио в текстовом формате с Forvo URL"""
    lines = [f"# Audio Download List - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"]
    if pattern:
        lines.append(f"# Pattern filter: {pattern}")
    lines.append(f"# Total words: {len(words)}")
    lines.append(f"# Format: https://forvo.com/word/{{word}}/#en")
    lines.append("")

    for word in words:
        # Создаем URL для Forvo
        forvo_url = f"https://forvo.com/word/{word}/#en"
        lines.append(forvo_url)

    content = '\n'.join(lines)
    response = make_response(content)
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    filename = f"forvo_download_list_{pattern or 'all'}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response
