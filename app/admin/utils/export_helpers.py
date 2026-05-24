# app/admin/utils/export_helpers.py

"""
Утилиты для экспорта данных в различных форматах (JSON, CSV, TXT)
"""
import csv
import json
from datetime import datetime, timezone

from flask import Response, make_response, stream_with_context

MAX_EXPORT_ROWS = 10000


class _LineBuffer:
    """csv.writer-compatible sink that captures the most recent line."""

    def __init__(self) -> None:
        self.value = ''

    def write(self, value: str) -> int:  # pragma: no cover - trivial
        self.value = value
        return len(value)


def _stream_csv_rows(headers, rows):
    """Yield CSV bytes header + rows, suitable for ``Response(generator)``."""
    buffer = _LineBuffer()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    yield buffer.value
    for row in rows:
        writer.writerow(row)
        yield buffer.value


def _sanitize_csv_cell(value) -> str:
    """Prevent CSV injection by prefixing dangerous characters with apostrophe.

    Characters =, +, -, @, \\t, \\r at the start of a cell can trigger
    formula execution in Excel/Google Sheets.
    """
    if value is None:
        return ''
    s = str(value)
    if s and s[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + s
    return s


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
    """Экспорт слов в формате CSV (streaming, sanitized, лимит MAX_EXPORT_ROWS)."""
    words = list(words)[:MAX_EXPORT_ROWS]  # Enforce limit

    headers = ['English', 'Russian', 'Level']
    has_status = bool(words) and hasattr(words[0], 'status')
    if has_status:
        headers.append('Status')

    def row_iter():
        for word in words:
            row = [
                _sanitize_csv_cell(word.english_word),
                _sanitize_csv_cell(word.russian_word),
                _sanitize_csv_cell(word.level if hasattr(word, 'level') else ''),
            ]
            if has_status:
                row.append(_sanitize_csv_cell(word.status))
            yield row

    filename = (
        f"words_export_{status or 'all'}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    )
    response = Response(
        stream_with_context(_stream_csv_rows(headers, row_iter())),
        mimetype='text/csv; charset=utf-8',
    )
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
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
    """Экспорт списка аудио в формате CSV (streaming, sanitized, лимит MAX_EXPORT_ROWS)."""
    words_iter = list(words)[:MAX_EXPORT_ROWS]

    def row_iter():
        for word in words_iter:
            forvo_url = f"https://forvo.com/word/{word}/#en"
            yield [_sanitize_csv_cell(word), forvo_url]

    filename = (
        f"forvo_download_list_{pattern or 'all'}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    )
    response = Response(
        stream_with_context(_stream_csv_rows(['English Word', 'Forvo URL'], row_iter())),
        mimetype='text/csv; charset=utf-8',
    )
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
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
