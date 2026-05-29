"""
OG-image generator for word and grammar pages.

The Open Graph image is the first thing a user sees when our links appear
in Telegram / Twitter / Slack. A branded card with the actual word or
topic title hugely outperforms the static "LLT English" placeholder in
CTR — that's the whole reason we're building this.

Output: 1200×630 PNG, brand-blue gradient background, large centred
title, optional level badge, wordmark at the bottom.

Persistence: rendered images land in ``instance/og_cache/<sha1>.png``,
keyed by (kind, title, subtitle, level). Re-rendering is idempotent and
cheap on a cache hit (single file read).

Fonts: production prefers ``app/static/fonts/Inter-Bold.ttf`` if you drop
one in. Otherwise the loader walks a list of system font paths (DejaVu on
typical Linux servers, Helvetica/Arial on macOS dev boxes) and falls back
to PIL's bitmap default if nothing was found. The fallback still renders a
working image, just with smaller, less polished glyphs.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont
from flask import current_app

logger = logging.getLogger(__name__)


# Standard Open Graph size accepted everywhere (Facebook, Twitter, Telegram).
OG_WIDTH = 1200
OG_HEIGHT = 630
PADDING = 80

# Brand gradient — matches the public landing palette.
BG_TOP = (37, 99, 235)      # blue-600
BG_BOTTOM = (14, 165, 233)  # sky-500

TEXT_COLOR = (255, 255, 255)
SUBTITLE_COLOR = (220, 240, 255)
WORDMARK_COLOR = (236, 244, 255)
LEVEL_BG = (190, 242, 100)  # lime-300
LEVEL_FG = (15, 23, 42)     # slate-900


# Repo-relative path Vendored TTF (user adds it). Checked first so an admin
# can upgrade the look just by dropping the file in — no code change needed.
_REPO_FONT_BOLD = 'app/static/fonts/Inter-Bold.ttf'
_REPO_FONT_REGULAR = 'app/static/fonts/Inter-Regular.ttf'


_SYSTEM_BOLD_FONTS: tuple[str, ...] = (
    # Debian/Ubuntu (`apt install fonts-dejavu`) — almost always present on prod.
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    # Fedora / RHEL.
    '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
    # Arch.
    '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf',
    # macOS dev paths.
    '/Library/Fonts/Arial Bold.ttf',
    '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
)

_SYSTEM_REGULAR_FONTS: tuple[str, ...] = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/TTF/DejaVuSans.ttf',
    '/Library/Fonts/Arial.ttf',
    '/System/Library/Fonts/Supplemental/Arial.ttf',
    '/System/Library/Fonts/Geneva.ttf',
)


def _repo_root() -> str:
    # current_app.root_path points to the ``app`` package directory in this
    # project, so step up to the repo root for static-file lookups.
    return os.path.dirname(current_app.root_path)


def _find_font(candidates: Iterable[str]) -> str | None:
    root = _repo_root()
    for candidate in candidates:
        path = candidate if os.path.isabs(candidate) else os.path.join(root, candidate)
        if os.path.exists(path):
            return path
    return None


_font_cache: dict[tuple[int, bool], ImageFont.ImageFont] = {}


def _load_font(size: int, bold: bool = True) -> ImageFont.ImageFont:
    """Return a usable Pillow font at the requested size.

    Lookup order: vendored Inter → system Bold (or Regular) → PIL bitmap.
    Cached in-process so repeated renders don't re-parse the TTF.
    """
    cache_key = (size, bold)
    cached = _font_cache.get(cache_key)
    if cached is not None:
        return cached

    repo_candidate = _REPO_FONT_BOLD if bold else _REPO_FONT_REGULAR
    system_candidates = _SYSTEM_BOLD_FONTS if bold else _SYSTEM_REGULAR_FONTS

    path = _find_font([repo_candidate, *system_candidates])
    if path:
        try:
            font = ImageFont.truetype(path, size)
            _font_cache[cache_key] = font
            return font
        except Exception:
            logger.warning('Failed to load OG font %s', path, exc_info=True)

    logger.warning(
        'No TTF available for OG images at size %d — falling back to bitmap default. '
        'Drop a TTF at %s for a better look.', size, _REPO_FONT_BOLD,
    )
    font = ImageFont.load_default()
    _font_cache[cache_key] = font
    return font


def _cache_dir() -> str:
    base = current_app.instance_path
    cache = os.path.join(base, 'og_cache')
    os.makedirs(cache, exist_ok=True)
    return cache


def _cache_key(kind: str, title: str, subtitle: str, level: str) -> str:
    raw = f'{kind}|{title}|{subtitle}|{level}'.encode('utf-8')
    return hashlib.sha1(raw).hexdigest()


def _word_wrap(text: str, draw: ImageDraw.ImageDraw, font, max_width: int) -> list[str]:
    """Greedy word-wrap to fit ``max_width`` pixels."""
    words = text.split()
    if not words:
        return [text] if text else []
    lines: list[str] = []
    current = ''
    for word in words:
        candidate = f'{current} {word}'.strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _fit_title_font(
    draw: ImageDraw.ImageDraw, text: str, max_width: int,
    sizes: tuple[int, ...] = (110, 96, 84, 72, 64, 56),
) -> tuple[ImageFont.ImageFont, list[str]]:
    """Pick the largest size that lets the title fit in ≤3 wrapped lines."""
    for size in sizes:
        font = _load_font(size, bold=True)
        lines = _word_wrap(text, draw, font, max_width)
        if len(lines) <= 3:
            return font, lines
    # Worst case: smallest size + a tight wrap.
    font = _load_font(sizes[-1], bold=True)
    return font, _word_wrap(text, draw, font, max_width)


def render_og_image(
    kind: str, title: str, subtitle: str = '', level: str = '',
) -> bytes:
    """Render a branded OG card and return PNG bytes.

    Reads from disk on a cache hit; writes there on a miss. The cache key
    includes every input that affects pixels, so edits to the underlying
    title automatically invalidate the cached version.
    """
    cache_dir = _cache_dir()
    key = _cache_key(kind, title, subtitle, level)
    cache_path = os.path.join(cache_dir, f'{key}.png')
    if os.path.exists(cache_path):
        with open(cache_path, 'rb') as fh:
            return fh.read()

    img = Image.new('RGB', (OG_WIDTH, OG_HEIGHT), BG_TOP)
    draw = ImageDraw.Draw(img)

    # Vertical brand gradient row-by-row. Cheap (~600 rows) and avoids a
    # bigger dependency like numpy just for one effect.
    for y in range(OG_HEIGHT):
        t = y / max(1, OG_HEIGHT - 1)
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (OG_WIDTH, y)], fill=(r, g, b))

    # Rubric label top-left.
    rubric_label = {
        'word': 'СЛОВО ДНЯ',
        'grammar': 'ГРАММАТИКА',
        'mistake': 'ЗАПОМНИ',
    }.get(kind, kind.upper())
    rubric_font = _load_font(36, bold=True)
    draw.text((PADDING, PADDING - 6), rubric_label, font=rubric_font, fill=TEXT_COLOR)

    # Level badge top-right.
    if level:
        level_text = level.upper()
        level_font = _load_font(40, bold=True)
        lw, lh = _text_size(draw, level_text, level_font)
        pad_x, pad_y = 28, 16
        badge_w = lw + pad_x * 2
        badge_h = lh + pad_y * 2
        x0 = OG_WIDTH - PADDING - badge_w
        y0 = PADDING - 16
        draw.rounded_rectangle(
            [x0, y0, x0 + badge_w, y0 + badge_h], radius=20, fill=LEVEL_BG,
        )
        draw.text((x0 + pad_x, y0 + pad_y - 2), level_text, font=level_font, fill=LEVEL_FG)

    # Title — auto-sized, centred, word-wrapped.
    title_font, title_lines = _fit_title_font(draw, title or '', OG_WIDTH - 2 * PADDING)
    line_heights = [_text_size(draw, line, title_font)[1] for line in title_lines]
    line_gap = 16
    block_h = sum(line_heights) + line_gap * max(0, len(title_lines) - 1)
    y = (OG_HEIGHT - block_h) // 2 - (40 if subtitle else 0)
    for line, lh in zip(title_lines, line_heights):
        lw, _ = _text_size(draw, line, title_font)
        draw.text(((OG_WIDTH - lw) // 2, y), line, font=title_font, fill=TEXT_COLOR)
        y += lh + line_gap

    if subtitle:
        subtitle_font = _load_font(48, bold=False)
        wrapped = _word_wrap(subtitle, draw, subtitle_font, OG_WIDTH - 2 * PADDING)
        for line in wrapped[:2]:  # cap at 2 lines so the wordmark is never crushed
            lw, lh = _text_size(draw, line, subtitle_font)
            draw.text(((OG_WIDTH - lw) // 2, y + 8), line, font=subtitle_font, fill=SUBTITLE_COLOR)
            y += lh + 8

    # Wordmark at the bottom.
    wm_font = _load_font(34, bold=True)
    wm = 'llt-english.com'
    lw, lh = _text_size(draw, wm, wm_font)
    draw.text(
        ((OG_WIDTH - lw) // 2, OG_HEIGHT - PADDING - lh),
        wm, font=wm_font, fill=WORDMARK_COLOR,
    )

    buffer = io.BytesIO()
    img.save(buffer, format='PNG', optimize=True)
    data = buffer.getvalue()
    try:
        with open(cache_path, 'wb') as fh:
            fh.write(data)
    except OSError:
        logger.exception('Failed to write OG cache file %s', cache_path)
    return data
