"""Сертификаты уровней CEFR: завершённость уровня + генерация share-image.

Уровень считается завершённым, когда КАЖДЫЙ урок каждого модуля уровня
имеет ``LessonProgress.status == 'completed'`` (тот же критерий, что у
``Module.check_prerequisites`` — 100% уроков). Экстерн (test-out)
закрывает уроки штатным LessonProgress, так что сертификат честно
учитывает и его.

PNG 1200x630 (OG-формат) рендерится Pillow на лету — юзеров мало,
кэш не нужен. Шрифт берётся из системных кандидатов (DejaVu на проде,
Arial на macOS); без TTF падаем на встроенный шрифт Pillow.
"""
from __future__ import annotations

import io
import logging
from datetime import date
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.utils.db import db as _db

logger = logging.getLogger(__name__)

CERT_WIDTH = 1200
CERT_HEIGHT = 630

LEVEL_NAMES = {
    'A1': 'Beginner',
    'A2': 'Elementary',
    'B1': 'Intermediate',
    'B2': 'Upper-Intermediate',
    'C1': 'Advanced',
    'C2': 'Proficiency',
}

# Кандидаты TTF с кириллицей: Debian/Ubuntu (prod), macOS (dev).
_FONT_CANDIDATES = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/System/Library/Fonts/Supplemental/Arial.ttf',
    '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
)
_FONT_BOLD_CANDIDATES = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/System/Library/Fonts/Supplemental/Arial.ttf',
)

_BG = (49, 46, 129)          # indigo-900
_PANEL = (255, 255, 255)
_ACCENT = (79, 70, 229)      # indigo-600
_TEXT = (30, 41, 59)         # slate-800
_MUTED = (100, 116, 139)     # slate-500


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = _FONT_BOLD_CANDIDATES if bold else _FONT_CANDIDATES
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # старый Pillow без size-аргумента
        return ImageFont.load_default()


def get_completed_levels(user_id: int, db: Any = _db) -> list:
    """Уровни, где завершены все уроки всех модулей.

    Возвращает [{'code', 'name', 'completed_at': date|None, 'total_lessons'}]
    в порядке CEFRLevel.order. Уровни без уроков не учитываются.
    """
    from sqlalchemy import func

    totals = dict(
        db.session.query(CEFRLevel.id, func.count(Lessons.id))
        .join(Module, Module.level_id == CEFRLevel.id)
        .join(Lessons, Lessons.module_id == Module.id)
        .group_by(CEFRLevel.id)
        .all()
    )
    completed_rows = (
        db.session.query(
            CEFRLevel.id,
            CEFRLevel.code,
            CEFRLevel.name,
            CEFRLevel.order,
            func.count(LessonProgress.id),
            func.max(LessonProgress.completed_at),
        )
        .join(Module, Module.level_id == CEFRLevel.id)
        .join(Lessons, Lessons.module_id == Module.id)
        .join(
            LessonProgress,
            (LessonProgress.lesson_id == Lessons.id)
            & (LessonProgress.user_id == user_id)
            & (LessonProgress.status == 'completed'),
        )
        .group_by(CEFRLevel.id, CEFRLevel.code, CEFRLevel.name, CEFRLevel.order)
        .all()
    )

    result = []
    for level_id, code, name, order, completed_count, last_completed in completed_rows:
        total = totals.get(level_id, 0)
        if total > 0 and completed_count >= total:
            result.append({
                'code': code,
                'name': name or LEVEL_NAMES.get(code, ''),
                'order': order,
                'total_lessons': total,
                'completed_at': last_completed.date() if last_completed else None,
            })
    result.sort(key=lambda item: item['order'])
    return result


def get_completed_level(user_id: int, level_code: str, db: Any = _db) -> Optional[dict]:
    """Данные сертификата конкретного уровня или None, если не завершён."""
    code = (level_code or '').upper()
    for entry in get_completed_levels(user_id, db):
        if entry['code'] == code:
            return entry
    return None


def render_certificate_png(
    username: str,
    level_code: str,
    level_name: str = '',
    completed_at: Optional[date] = None,
) -> bytes:
    """Сгенерировать PNG-сертификат 1200x630 (OG-размер)."""
    img = Image.new('RGB', (CERT_WIDTH, CERT_HEIGHT), _BG)
    draw = ImageDraw.Draw(img)

    # Белая карточка с двойной рамкой
    margin = 36
    draw.rounded_rectangle(
        (margin, margin, CERT_WIDTH - margin, CERT_HEIGHT - margin),
        radius=24, fill=_PANEL,
    )
    inner = margin + 16
    draw.rounded_rectangle(
        (inner, inner, CERT_WIDTH - inner, CERT_HEIGHT - inner),
        radius=18, outline=_ACCENT, width=3,
    )

    def _center(text: str, y: int, font: ImageFont.ImageFont, fill) -> None:
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (CERT_WIDTH - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), text, font=font, fill=fill)

    _center('LLT ENGLISH', 86, _load_font(28, bold=True), _ACCENT)
    _center('СЕРТИФИКАТ', 130, _load_font(54, bold=True), _TEXT)
    _center('подтверждает, что', 208, _load_font(26), _MUTED)

    display_name = (username or '')[:40]
    _center(display_name, 252, _load_font(48, bold=True), _TEXT)

    _center('успешно завершил(а) уровень английского', 330, _load_font(26), _MUTED)

    code = (level_code or '').upper()
    name = level_name or LEVEL_NAMES.get(code, '')
    level_line = f'{code} — {name}' if name else code
    _center(level_line, 380, _load_font(64, bold=True), _ACCENT)

    if completed_at is not None:
        _center(completed_at.strftime('%d.%m.%Y'), 488, _load_font(24), _MUTED)
    _center('llt-english.com', 530, _load_font(22), _MUTED)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()
