"""Screenshot storage helper for the in-app feedback widget.

Files land under ``uploads/feedback/`` (outside ``app/static``); served by
``/feedback/screenshots/<filename>`` route with admin or owner ACL —
public links would leak sensitive screenshots (passwords, private chats,
etc.).
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

from PIL import Image
from werkzeug.datastructures import FileStorage

from app.utils.file_security import (
    UPLOAD_BASE_FOLDER,
    check_forbidden_magic_bytes,
    strip_image_metadata,
)

logger = logging.getLogger(__name__)


FEEDBACK_UPLOAD_FOLDER = os.path.join(UPLOAD_BASE_FOLDER, 'feedback')
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024  # 5 MiB — matches cover limit
ALLOWED_SCREENSHOT_FORMATS = frozenset({'PNG', 'JPEG', 'WEBP'})
MAX_SCREENSHOT_DIMENSION = 2400  # downscale runaway hi-DPI captures


SCREENSHOT_REJECT_REASONS = {
    'too_large': 'Файл больше 5 МБ — сожмите или сделайте меньший снимок.',
    'unsupported_format': 'Поддерживаются PNG, JPEG и WEBP.',
    'malicious_content': 'Файл отклонён как небезопасный.',
    'read_failed': 'Не удалось прочитать файл.',
    'process_failed': 'Не удалось обработать изображение.',
    'empty': 'Пустой файл.',
}


def save_feedback_screenshot(file: FileStorage) -> tuple[Optional[str], Optional[str]]:
    """Validate + persist a feedback screenshot.

    Returns ``(relative_path, reject_reason)``:
      - ``(path, None)`` on success.
      - ``(None, None)`` when no file was attached.
      - ``(None, reason_code)`` when the file was rejected. Reason maps to a
        human-readable hint in ``SCREENSHOT_REJECT_REASONS`` — the caller
        passes it through to the client so the user knows their screenshot
        didn't land (previously the upload was silently dropped and the
        submission still returned 201, leaving the user puzzled).
    """
    if not file or not getattr(file, 'filename', ''):
        return None, None

    # Read once into memory (small cap), then operate via Pillow buffer.
    try:
        file.stream.seek(0)
        head = file.stream.read(MAX_SCREENSHOT_BYTES + 1)
    except Exception:
        logger.warning('feedback_screenshot_read_failed', exc_info=True)
        return None, 'read_failed'
    if not head:
        return None, 'empty'
    if len(head) > MAX_SCREENSHOT_BYTES:
        logger.info('feedback_screenshot_too_large bytes=%s', len(head))
        return None, 'too_large'

    forbidden = check_forbidden_magic_bytes(head)
    if forbidden:
        logger.warning('feedback_screenshot_dangerous_magic_bytes=%s', forbidden)
        return None, 'malicious_content'

    os.makedirs(FEEDBACK_UPLOAD_FOLDER, exist_ok=True)

    import io
    try:
        with Image.open(io.BytesIO(head)) as img:
            img_format = (img.format or '').upper()
            if img_format not in ALLOWED_SCREENSHOT_FORMATS:
                logger.info('feedback_screenshot_bad_format=%s', img_format)
                return None, 'unsupported_format'
            img.load()
            cleaned = strip_image_metadata(img)
            # Cap dimensions — protects against memory blow-ups + keeps
            # storage predictable across hi-DPI captures.
            if max(cleaned.size) > MAX_SCREENSHOT_DIMENSION:
                cleaned.thumbnail(
                    (MAX_SCREENSHOT_DIMENSION, MAX_SCREENSHOT_DIMENSION),
                    Image.LANCZOS,
                )
            ext = 'jpg' if img_format == 'JPEG' else img_format.lower()
            filename = f'{uuid.uuid4().hex}.{ext}'
            target = os.path.join(FEEDBACK_UPLOAD_FOLDER, filename)
            # WEBP/PNG can keep alpha; JPEG drops it. Save as the same
            # format the user uploaded — re-encoding to a single format
            # would lose transparency on UI screenshots.
            save_kwargs = {}
            if img_format == 'JPEG':
                save_kwargs['quality'] = 85
                save_kwargs['optimize'] = True
                if cleaned.mode != 'RGB':
                    cleaned = cleaned.convert('RGB')
            cleaned.save(target, format=img_format, **save_kwargs)
    except Exception:
        logger.warning('feedback_screenshot_process_failed', exc_info=True)
        return None, 'process_failed'

    # Relative path so we can ship the upload between hosts / containers
    # without baking the absolute filesystem layout into the DB.
    return os.path.join('feedback', filename), None


def feedback_screenshot_abs_path(rel_path: str) -> Optional[str]:
    """Return absolute path on disk for a stored screenshot, or None.

    Defensive: rejects ``..`` traversal in the stored ``rel_path``.
    """
    if not rel_path:
        return None
    # Stored values always begin with ``feedback/`` (folder name is the
    # legacy compatibility tag). Anything else is suspicious.
    normalized = os.path.normpath(rel_path)
    if normalized.startswith('..') or os.path.isabs(normalized):
        return None
    candidate = os.path.join(UPLOAD_BASE_FOLDER, normalized)
    abs_candidate = os.path.abspath(candidate)
    abs_root = os.path.abspath(FEEDBACK_UPLOAD_FOLDER)
    if not abs_candidate.startswith(abs_root + os.sep):
        return None
    if not os.path.exists(abs_candidate):
        return None
    return abs_candidate
