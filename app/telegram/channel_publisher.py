"""
Telegram channel auto-publisher.

Daily routine:
- ``queue_upcoming(...)`` runs once a day and fills future slots
  (morning + evening) for the next N days with picked content. Skips slots
  that already have a queued/published post.
- ``publish_due(...)`` runs hourly. It fetches queued posts whose
  ``scheduled_for`` has arrived, sends each to the channel, and updates
  the row to ``published``/``failed``.

Both functions are idempotent: running them twice within a tick never
duplicates a post or re-sends one that already went out.

Content selection is deduped via the ``telegram_channel_dedup_days`` window
(default 90 days) so the channel doesn't loop on the same words/topics.

Channel ID, schedule hours, and dedup window all live in SiteSettings so an
admin can change them without a deploy. Empty ``telegram_channel_id`` is
the off-switch: the picker still computes candidates (cheap), but the sender
short-circuits with a warning instead of calling Telegram.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from typing import Any


# Match every <br> / <br/> / <br /> variant case-insensitively.
_BR_RE = re.compile(r'<\s*br\s*/?\s*>', flags=re.IGNORECASE)
# Strip any remaining HTML tags so we don't leak markup into the channel
# post (Telegram HTML allows a restricted set, and content like word.sentences
# is authored as web-style HTML rather than Telegram-style).
_TAG_RE = re.compile(r'<[^>]+>')

import requests
from flask import current_app
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.admin.site_settings import get_site_setting
from app.curriculum.routes.public import PUBLIC_CEFR_CODES
from app.grammar_lab.models import GrammarTopic
from app.telegram.channel_models import (
    ALLOWED_KINDS, ChannelPost,
    KIND_GRAMMAR, KIND_MANUAL, KIND_MISTAKE, KIND_WORD,
    STATUS_FAILED, STATUS_PUBLISHED, STATUS_QUEUED, STATUS_SKIPPED,
)


# Within a KIND_MISTAKE post, content_ref_id encodes (topic_id, mistake_index)
# as topic_id * _MISTAKE_INDEX_STRIDE + mistake_index. This keeps the dedup
# index unique per (topic, mistake) pair without a schema migration. Stride
# of 1000 is safe — no grammar topic ships with anywhere near 1000 mistakes.
_MISTAKE_INDEX_STRIDE = 1000
from app.utils.db import db as _default_db
from app.words.models import CollectionWords
from app.words.routes import encode_word_slug

logger = logging.getLogger(__name__)


# Site URL fallback when SITE_URL config is empty (e.g. tests).
_CANONICAL_HOST = 'https://llt-english.com'

# Maximum days_ahead queue_upcoming will fill at once.
_MAX_QUEUE_DAYS = 30

# Telegram message body cap (4096 chars). Format functions stay well under,
# but we truncate defensively before sending.
_TELEGRAM_MAX_LEN = 4000

# Default schedule hours (UTC). Used when SiteSettings keys are missing or
# malformed. 6 UTC ≈ 09:00 MSK; 15 UTC ≈ 18:00 MSK.
_DEFAULT_MORNING_HOUR = 6
_DEFAULT_EVENING_HOUR = 15

# Default dedup window when SiteSettings key is missing.
_DEFAULT_DEDUP_DAYS = 90


# ─── Config helpers ─────────────────────────────────────────────────────


def _site_url() -> str:
    try:
        configured = (current_app.config.get('SITE_URL') or '').rstrip('/')
    except RuntimeError:
        configured = ''
    return configured or _CANONICAL_HOST


def _get_int_setting(key: str, default: int, db_session: Session) -> int:
    raw = get_site_setting(key, str(default), db_session=db_session)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def get_channel_config(db_session: Session) -> dict:
    """Snapshot of all publisher knobs from SiteSettings."""
    return {
        'channel_id': (get_site_setting('telegram_channel_id', '', db_session=db_session) or '').strip(),
        'channel_username': (get_site_setting('telegram_channel_username', '', db_session=db_session) or '').strip(),
        'morning_hour': max(0, min(23, _get_int_setting(
            'telegram_channel_morning_utc_hour', _DEFAULT_MORNING_HOUR, db_session,
        ))),
        'morning_minute': max(0, min(59, _get_int_setting(
            'telegram_channel_morning_utc_minute', 0, db_session,
        ))),
        'evening_hour': max(0, min(23, _get_int_setting(
            'telegram_channel_evening_utc_hour', _DEFAULT_EVENING_HOUR, db_session,
        ))),
        'evening_minute': max(0, min(59, _get_int_setting(
            'telegram_channel_evening_utc_minute', 0, db_session,
        ))),
        'dedup_days': max(1, min(365, _get_int_setting(
            'telegram_channel_dedup_days', _DEFAULT_DEDUP_DAYS, db_session,
        ))),
    }


# ─── Pickers ───────────────────────────────────────────────────────────


def _recently_posted_ids(
    kind: str, content_type: str, dedup_days: int, db_session: Session,
) -> set[int]:
    """IDs of content already used for *kind* posts in the last *dedup_days*."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=dedup_days)
    rows = (
        db_session.query(ChannelPost.content_ref_id)
        .filter(
            ChannelPost.kind == kind,
            ChannelPost.content_ref_type == content_type,
            ChannelPost.content_ref_id.isnot(None),
            ChannelPost.created_at >= cutoff,
        )
        .all()
    )
    return {row[0] for row in rows if row[0] is not None}


def pick_next_word(db_session: Session, dedup_days: int) -> CollectionWords | None:
    """Pick a high-quality public word not posted recently.

    Selection criteria, applied in order:
    - public CEFR level
    - has Russian translation (otherwise the post is useless to a RU audience)
    - has IPA transcription (looks professional)
    - prefer lower ``frequency_rank`` (more commonly searched words)
    - skip anything in the recent-posts dedup set
    """
    skip_ids = _recently_posted_ids(KIND_WORD, 'word', dedup_days, db_session)
    query = (
        CollectionWords.query
        .filter(CollectionWords.item_type == 'word')
        .filter(CollectionWords.level.in_(PUBLIC_CEFR_CODES))
        .filter(CollectionWords.russian_word.isnot(None))
        .filter(func.length(CollectionWords.russian_word) > 0)
        .filter(CollectionWords.ipa_transcription.isnot(None))
        .filter(func.length(CollectionWords.ipa_transcription) > 0)
    )
    if skip_ids:
        query = query.filter(~CollectionWords.id.in_(skip_ids))
    return (
        query.order_by(
            CollectionWords.frequency_rank.asc().nullslast(),
            CollectionWords.id.asc(),
        )
        .first()
    )


def _topic_tip_candidates(topic: GrammarTopic) -> list[tuple[int, dict | str]]:
    """Return a list of (index, payload) tips this topic can contribute.

    Two sources, in priority order:
    1. ``content['common_mistakes']`` — structured ``{wrong, correct, ...}``
       dicts (rarely populated in the current seed; richer post when present).
    2. ``content['important_notes']`` — list of curated tip strings (universal:
       all 76 seeded topics have these).

    Indices reuse ``_MISTAKE_INDEX_STRIDE`` slots so dedup keeps both sources
    distinct: structured mistakes occupy indices 0..499, free-form notes
    500..999.
    """
    content = topic.content if isinstance(topic.content, dict) else {}
    out: list[tuple[int, dict | str]] = []

    mistakes = content.get('common_mistakes') or []
    if isinstance(mistakes, list):
        for i, mistake in enumerate(mistakes):
            if not isinstance(mistake, dict):
                continue
            if (mistake.get('wrong') or '').strip() and (mistake.get('correct') or '').strip():
                out.append((i, mistake))
                if i >= 499:
                    break

    notes = content.get('important_notes') or []
    if isinstance(notes, list):
        for i, note in enumerate(notes):
            if not isinstance(note, str):
                continue
            text = note.strip()
            if not text:
                continue
            out.append((500 + i, text))
            if i >= 499:
                break

    return out


def pick_next_mistake(
    db_session: Session, dedup_days: int,
) -> tuple[GrammarTopic, dict | str, int] | None:
    """Pick a (topic, payload, index) triple not posted recently.

    ``payload`` is either a structured ``common_mistakes`` dict or a free-form
    ``important_notes`` string. Dedup keys on (topic_id, encoded index) so the
    same tip never recurs within ``dedup_days``.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=dedup_days)
    rows = (
        db_session.query(ChannelPost.content_ref_id)
        .filter(
            ChannelPost.kind == KIND_MISTAKE,
            ChannelPost.content_ref_type == 'grammar_mistake',
            ChannelPost.content_ref_id.isnot(None),
            ChannelPost.created_at >= cutoff,
        )
        .all()
    )
    skip_pairs: set[tuple[int, int]] = {
        (row[0] // _MISTAKE_INDEX_STRIDE, row[0] % _MISTAKE_INDEX_STRIDE)
        for row in rows if row[0] is not None
    }

    topics = (
        GrammarTopic.query
        .filter(GrammarTopic.level.in_(PUBLIC_CEFR_CODES))
        .order_by(GrammarTopic.order.asc(), GrammarTopic.id.asc())
        .all()
    )
    level_priority = {'A1': 1, 'A2': 2, 'B1': 3, 'B2': 4, 'C1': 5}
    topics.sort(key=lambda t: (level_priority.get(t.level, 99), t.order or 0, t.id))

    for topic in topics:
        for idx, payload in _topic_tip_candidates(topic):
            if (topic.id, idx) in skip_pairs:
                continue
            return topic, payload, idx
    return None


def pick_next_grammar_topic(db_session: Session, dedup_days: int) -> GrammarTopic | None:
    """Pick a grammar topic not posted recently.

    Prefers A1/A2 first (broadest audience), then B1, then B2/C1.
    """
    skip_ids = _recently_posted_ids(KIND_GRAMMAR, 'grammar_topic', dedup_days, db_session)
    query = (
        GrammarTopic.query
        .filter(GrammarTopic.level.in_(PUBLIC_CEFR_CODES))
    )
    if skip_ids:
        query = query.filter(~GrammarTopic.id.in_(skip_ids))
    # Custom ordering: A1 < A2 < B1 < B2 < C1 < anything else.
    level_priority = {'A1': 1, 'A2': 2, 'B1': 3, 'B2': 4, 'C1': 5}
    candidates = query.order_by(GrammarTopic.order.asc(), GrammarTopic.id.asc()).all()
    if not candidates:
        return None
    candidates.sort(key=lambda t: (level_priority.get(t.level, 99), t.order or 0, t.id))
    return candidates[0]


# ─── Formatters ────────────────────────────────────────────────────────


def _h(value: Any) -> str:
    """HTML-escape any value, stringifying None → ''. Telegram HTML mode."""
    return escape(str(value)) if value is not None else ''


def _clean_html_for_telegram(value: Any) -> str:
    """Convert web-style HTML content into plain text suitable for Telegram.

    word.sentences and a few grammar fields are stored as web-page snippets:
    they wrap translations in <br>, sometimes <i>/<b>. Telegram's HTML mode
    only supports a tiny subset and treats <br> as a literal. We strip every
    tag here, leaving Telegram-safe text that the formatter can still wrap
    in <i>/<b> on the outside.
    """
    if value is None:
        return ''
    text = str(value)
    # Normalise breaks BEFORE stripping tags so we keep line structure.
    text = _BR_RE.sub('\n', text)
    text = _TAG_RE.sub('', text)
    # Collapse any 3+ consecutive blank lines that the strip may produce.
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


_FREQ_LABELS = {1: 'Топ-1000', 2: 'Топ-3000', 3: 'Топ-10000'}


def _word_examples(word: CollectionWords, max_pairs: int = 2) -> list[tuple[str, str]]:
    """Split word.sentences into up to *max_pairs* (english, russian) lines.

    Stored format alternates English then Russian, separated by <br>. After
    _clean_html_for_telegram() those breaks become real newlines, so we just
    pair adjacent non-empty lines.
    """
    if not word.sentences:
        return []
    cleaned = _clean_html_for_telegram(word.sentences)
    lines = [line.strip() for line in cleaned.split('\n') if line.strip()]
    pairs: list[tuple[str, str]] = []
    for i in range(0, len(lines) - 1, 2):
        pairs.append((lines[i], lines[i + 1]))
        if len(pairs) >= max_pairs:
            break
    if not pairs and lines:
        # Odd line out: at least show the first sentence.
        pairs.append((lines[0], ''))
    return pairs


def format_word_post(word: CollectionWords, site_url: str | None = None) -> str:
    """Render a Word-of-Day post in Telegram HTML."""
    base = (site_url or _site_url()).rstrip('/')

    parts: list[str] = ['📖 <b>Слово дня</b>', '']

    head = f'🇬🇧 <b>{_h(word.english_word)}</b>'
    if word.ipa_transcription:
        head += f' <code>/{_h(word.ipa_transcription)}/</code>'
    parts.append(head)
    parts.append(f'🇷🇺 {_h(word.russian_word)}')

    # Level + frequency tag on one line.
    tags: list[str] = []
    if word.level:
        tags.append(f'📚 Уровень {_h(word.level)}')
    freq_label = _FREQ_LABELS.get(getattr(word, 'frequency_band', None) or 0)
    if freq_label:
        tags.append(f'🏆 {freq_label}')
    if tags:
        parts.extend(['', ' · '.join(tags)])

    pairs = _word_examples(word)
    if pairs:
        parts.extend(['', '📝 <b>Примеры:</b>'])
        for en, ru in pairs:
            parts.append(f'• <i>{_h(en)}</i>')
            if ru:
                parts.append(f'  {_h(ru)}')

    # Synonyms / antonyms — stored as JSON lists on CollectionWords.
    # Some legacy rows have the literal string 'null' or whitespace-only
    # entries; filter both out so we don't print garbage tags.
    def _clean_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for raw in value:
            if raw is None:
                continue
            text = str(raw).strip()
            if not text or text.lower() in ('null', 'none', 'nan'):
                continue
            out.append(text)
        return out

    synonyms = _clean_list(getattr(word, 'synonyms', None))
    antonyms = _clean_list(getattr(word, 'antonyms', None))
    if synonyms:
        names = ', '.join(_h(s) for s in synonyms[:4])
        parts.extend(['', f'🔄 Синонимы: {names}'])
    if antonyms:
        names = ', '.join(_h(a) for a in antonyms[:3])
        parts.append(f'⚡ Антонимы: {names}')

    # Mini-practice: works without curated per-word data. The "Попробуй сам"
    # framing pushes the reader from passive recognition to active recall —
    # the single biggest predictor of retention.
    parts.extend([
        '',
        '✍️ <b>Мини-практика:</b>',
        f'Составь своё предложение со словом <b>{_h(word.english_word)}</b>.',
    ])

    # Action-oriented CTA — tells the user what they get on the page,
    # not just "more details".
    parts.extend([
        '',
        '🎧 Послушай произношение и добавь в карточки →',
        _h(f'{base}/dictionary/{encode_word_slug(word.english_word)}'),
    ])
    return '\n'.join(parts)


def format_mistake_post(
    topic: GrammarTopic, payload: dict | str, site_url: str | None = None,
) -> str:
    """Render an 'Ошибка дня / Запомни' post in Telegram HTML.

    Two layouts depending on the payload type:
    - dict (from ``common_mistakes``): ❌ wrong → ✅ correct → 💬 explanation.
      Best when curated structured data is available.
    - str (from ``important_notes``): a single tip rendered verbatim under
      the 💡 heading. Fallback used when no structured mistakes exist.
    """
    base = (site_url or _site_url()).rstrip('/')

    parts: list[str] = []
    if isinstance(payload, dict):
        wrong = (payload.get('wrong') or '').strip()
        correct = (payload.get('correct') or '').strip()
        explanation = (payload.get('explanation') or '').strip()
        parts.extend(['❌ <b>Ошибка дня</b>', ''])
        parts.append(f'❌ <i>{_h(wrong)}</i>')
        parts.append(f'✅ <i>{_h(correct)}</i>')
        if explanation:
            parts.extend(['', f'💬 {_h(explanation[:400])}'])
    else:
        # important_notes entries already start with their own emoji (⚠️, 💡, …);
        # strip a leading copy so we don't repeat it next to our 💡 heading.
        tip = str(payload).strip()
        tip = re.sub(r'^[⚠️💡📌🔥✨]+\s*', '', tip)
        parts.extend(['💡 <b>Запомни сегодня</b>', '', _h(tip[:500])])

    title_ru = topic.title_ru or topic.title
    meta_bits: list[str] = []
    if topic.level:
        meta_bits.append(f'📚 Уровень {_h(topic.level)}')
    if title_ru:
        meta_bits.append(f'из темы «{_h(title_ru)}»')
    if meta_bits:
        parts.extend(['', ' · '.join(meta_bits)])

    parts.extend([
        '',
        '✅ Разобрать тему до конца + упражнения →',
        _h(f'{base}/grammar-lab/topic/{topic.slug}'),
    ])
    return '\n'.join(parts)


def _extract_grammar_examples(content: dict, limit: int = 3) -> list[str]:
    """Pull a handful of concrete usage examples from topic.content.

    The seed format has examples in two places:
    - ``content['sections'][i]['examples']`` — list of strings or
      {'en': ..., 'ru': ...} dicts.
    - ``content['summary_table']['rows']`` — fallback for terse topics.

    Examples land in the post BEFORE the prose theory so the reader sees a
    concrete pattern first (the "грамматика без боли" framing from the
    Telegram-channel feedback).
    """
    found: list[str] = []
    sections = content.get('sections') or []
    if not isinstance(sections, list):
        sections = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        for raw in section.get('examples') or []:
            if isinstance(raw, dict):
                en = (raw.get('en') or raw.get('english') or '').strip()
                ru = (raw.get('ru') or raw.get('russian') or '').strip()
                if en and ru:
                    found.append(f'{en} — {ru}')
                elif en:
                    found.append(en)
            elif isinstance(raw, str):
                text = raw.strip()
                if text:
                    found.append(text)
            if len(found) >= limit:
                return found
    return found


def format_grammar_post(topic: GrammarTopic, site_url: str | None = None) -> str:
    """Render a Grammar-tip post in Telegram HTML.

    Order is deliberate: title → meta → live examples → short rule →
    common mistake → CTA. Reader gets a pattern they recognise before
    any abstract terminology, which mirrors how the channel feedback
    asked us to frame grammar posts.
    """
    base = (site_url or _site_url()).rstrip('/')
    content = topic.content if isinstance(topic.content, dict) else {}

    # telegram_summary is curated specifically for messenger length —
    # prefer it over the longer web intro when both exist.
    intro = _clean_html_for_telegram(topic.telegram_summary)
    if not intro:
        intro = _clean_html_for_telegram(content.get('introduction'))

    title_ru = topic.title_ru or topic.title
    head = f'🧠 <b>Грамматика: {_h(title_ru)}</b>'
    if topic.title and topic.title != title_ru:
        head += f' ({_h(topic.title)})'
    parts: list[str] = [head]

    # Level + estimated time as a single meta line.
    meta_bits: list[str] = []
    if topic.level:
        meta_bits.append(f'📚 Уровень {_h(topic.level)}')
    if topic.estimated_time:
        meta_bits.append(f'⏱ ~{int(topic.estimated_time)} мин')
    if meta_bits:
        parts.append(' · '.join(meta_bits))

    examples = _extract_grammar_examples(content)
    if examples:
        parts.extend(['', '✅ <b>Примеры:</b>'])
        for ex in examples:
            parts.append(f'• <i>{_h(ex)}</i>')

    # Short rule body. Kept tight: 400 chars is enough for a quick read
    # without crowding out the examples and CTA.
    if intro:
        parts.extend(['', _h(intro[:400])])

    # Surface one common mistake when present — high-engagement element.
    mistakes = content.get('common_mistakes') or []
    if mistakes:
        first = mistakes[0] if isinstance(mistakes[0], dict) else {}
        wrong = (first.get('wrong') or '').strip()
        correct = (first.get('correct') or '').strip()
        explanation = (first.get('explanation') or '').strip()
        if wrong and correct:
            parts.extend([
                '',
                '⚠️ <b>Частая ошибка:</b>',
                f'❌ <i>{_h(wrong)}</i>',
                f'✅ <i>{_h(correct)}</i>',
            ])
            if explanation:
                parts.append(f'💬 {_h(explanation[:200])}')

    parts.extend([
        '',
        '✍️ <b>Мини-практика:</b>',
        'Составь своё предложение по этому правилу — проверь себя в упражнениях по ссылке.',
    ])

    parts.extend([
        '',
        '✅ Пройти упражнения с автопроверкой →',
        _h(f'{base}/grammar-lab/topic/{topic.slug}'),
    ])
    return '\n'.join(parts)


# ─── Queueing ──────────────────────────────────────────────────────────


def _slot_kind_for_time(
    hour: int, minute: int, morning_hour: int, morning_minute: int,
    slot_date: date,
) -> str:
    """Decide which content kind a given UTC slot represents.

    Morning slot → always KIND_WORD.
    Evening slot → alternates by weekday parity:
        Mon (0) Wed (2) Fri (4) Sun (6) → KIND_GRAMMAR
        Tue (1) Thu (3) Sat (5)         → KIND_MISTAKE
    Gives 4 grammar + 3 mistake posts per week without any extra config.
    """
    is_morning = hour == morning_hour and minute == morning_minute
    if is_morning:
        return KIND_WORD
    return KIND_MISTAKE if slot_date.weekday() % 2 else KIND_GRAMMAR


def _existing_slot(scheduled_for: datetime, db_session: Session) -> ChannelPost | None:
    """Find any auto-queued or manual post already covering this exact slot."""
    return (
        db_session.query(ChannelPost)
        .filter(ChannelPost.scheduled_for == scheduled_for)
        .filter(ChannelPost.status.in_([STATUS_QUEUED, STATUS_PUBLISHED]))
        .first()
    )


def queue_upcoming(
    db_session: Session | None = None,
    days_ahead: int = 7,
    today: date | None = None,
) -> list[ChannelPost]:
    """Fill morning + evening slots for the next *days_ahead* days.

    Returns the list of newly-created ``ChannelPost`` rows. Existing rows
    for the same slot are left untouched (idempotent).

    No-op when ``telegram_channel_id`` is empty — without a channel there is
    nothing useful to queue.
    """
    db_session = db_session or _default_db.session
    days_ahead = max(1, min(_MAX_QUEUE_DAYS, days_ahead))

    cfg = get_channel_config(db_session)
    if not cfg['channel_id']:
        logger.info('Channel publisher: telegram_channel_id not set, skipping queue refill')
        return []

    today = today or datetime.now(timezone.utc).date()
    created: list[ChannelPost] = []
    site_url = _site_url()

    slots = [
        (cfg['morning_hour'], cfg['morning_minute']),
        (cfg['evening_hour'], cfg['evening_minute']),
    ]
    for offset in range(days_ahead):
        slot_date = today + timedelta(days=offset)
        for hour, minute in slots:
            scheduled_for = datetime.combine(slot_date, time(hour=hour, minute=minute))  # naive UTC

            # Skip past slots (only fills forward).
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if scheduled_for <= now:
                continue
            if _existing_slot(scheduled_for, db_session):
                continue

            kind = _slot_kind_for_time(
                hour, minute, cfg['morning_hour'], cfg['morning_minute'],
                slot_date,
            )
            post = _build_auto_post(
                kind=kind,
                scheduled_for=scheduled_for,
                dedup_days=cfg['dedup_days'],
                site_url=site_url,
                db_session=db_session,
            )
            if post is None:
                # Picker exhausted (no eligible content). Log and continue —
                # tomorrow's window may have new candidates.
                logger.warning(
                    'Channel publisher: no candidate for kind=%s slot=%s',
                    kind, scheduled_for.isoformat(),
                )
                continue
            db_session.add(post)
            created.append(post)

    if created:
        db_session.commit()
    return created


def _build_auto_post(
    kind: str,
    scheduled_for: datetime,
    dedup_days: int,
    site_url: str,
    db_session: Session,
) -> ChannelPost | None:
    """Pick content and assemble a ChannelPost row. Returns None when no
    candidate is available."""
    if kind == KIND_WORD:
        word = pick_next_word(db_session, dedup_days)
        if word is None:
            return None
        return ChannelPost(
            kind=KIND_WORD,
            content_ref_type='word',
            content_ref_id=word.id,
            scheduled_for=scheduled_for,
            status=STATUS_QUEUED,
            text_snapshot=format_word_post(word, site_url=site_url),
            is_manual=False,
        )
    if kind == KIND_GRAMMAR:
        topic = pick_next_grammar_topic(db_session, dedup_days)
        if topic is None:
            return None
        return ChannelPost(
            kind=KIND_GRAMMAR,
            content_ref_type='grammar_topic',
            content_ref_id=topic.id,
            scheduled_for=scheduled_for,
            status=STATUS_QUEUED,
            text_snapshot=format_grammar_post(topic, site_url=site_url),
            is_manual=False,
        )
    if kind == KIND_MISTAKE:
        picked = pick_next_mistake(db_session, dedup_days)
        if picked is None:
            return None
        topic, mistake, idx = picked
        return ChannelPost(
            kind=KIND_MISTAKE,
            content_ref_type='grammar_mistake',
            content_ref_id=topic.id * _MISTAKE_INDEX_STRIDE + idx,
            scheduled_for=scheduled_for,
            status=STATUS_QUEUED,
            text_snapshot=format_mistake_post(topic, mistake, site_url=site_url),
            is_manual=False,
        )
    return None


# ─── Publishing ────────────────────────────────────────────────────────


def _send_to_channel(channel_id: str, text: str) -> tuple[bool, int | None, str | None]:
    """POST sendMessage to Telegram. Returns (success, message_id, error).

    ``success`` reflects *Telegram's* ok flag, not just HTTP 200. Some
    error cases (e.g. inactive chat, missing rights) come back as 200/OK
    with ``ok: false`` in the body; treating those as success would let the
    publisher mark the post published while nothing actually appeared in
    the channel.
    """
    try:
        token = current_app.config.get('TELEGRAM_BOT_TOKEN')
    except RuntimeError:
        token = None
    if not token:
        return False, None, 'TELEGRAM_BOT_TOKEN not configured'
    payload = {
        'chat_id': channel_id,
        'text': text[:_TELEGRAM_MAX_LEN],
        'parse_mode': 'HTML',
        'disable_web_page_preview': False,
    }
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json=payload,
            timeout=10,
        )
    except requests.RequestException as e:
        # Avoid leaking token in repr.
        return False, None, f'{type(e).__name__}'

    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {}

    if not resp.ok or not body.get('ok'):
        # Build a single-line diagnostic the admin can grok at a glance.
        description = body.get('description') or resp.text[:200]
        return False, None, f'HTTP {resp.status_code}: {description}'

    message_id = (body.get('result') or {}).get('message_id')
    return True, message_id, None


def send_test_message(db_session: Session) -> tuple[bool, str]:
    """Send a one-off test post to the configured channel.

    Returns ``(ok, message)`` where ``message`` is a human-readable
    description of what happened — suitable for surfacing via flash().
    The post is NOT recorded in the queue (we don't want test traffic in
    the published history).
    """
    cfg = get_channel_config(db_session)
    channel_id = cfg['channel_id']
    if not channel_id:
        return False, 'telegram_channel_id не задан в настройках.'
    text = (
        '🧪 <b>Тест канала</b>\n\n'
        'Если вы видите это сообщение в канале — публикатор настроен правильно.\n'
        f'<i>Отправлено: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</i>'
    )
    ok, message_id, err = _send_to_channel(channel_id, text)
    if ok:
        return True, f'Тест отправлен. message_id={message_id}. Проверьте канал.'
    return False, f'Ошибка отправки: {err}'


def publish_due(
    db_session: Session | None = None,
    now: datetime | None = None,
) -> dict:
    """Send every queued post whose scheduled_for has arrived.

    Returns a small dict with counters for telemetry/logging:
    ``{'sent': int, 'failed': int, 'skipped_no_channel': int}``.
    Caller (scheduler) doesn't need the return value but tests do.
    """
    db_session = db_session or _default_db.session
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    cfg = get_channel_config(db_session)
    channel_id = cfg['channel_id']

    due = (
        db_session.query(ChannelPost)
        .filter(ChannelPost.status == STATUS_QUEUED)
        .filter(ChannelPost.scheduled_for <= now)
        .order_by(ChannelPost.scheduled_for.asc())
        .all()
    )
    if not due:
        return {'sent': 0, 'failed': 0, 'skipped_no_channel': 0}

    if not channel_id:
        # Channel disabled: mark everything as skipped so an old queue
        # doesn't fire days later when admin finally configures the channel.
        for post in due:
            post.status = STATUS_SKIPPED
            post.error = 'telegram_channel_id not set at publish time'
        db_session.commit()
        return {'sent': 0, 'failed': 0, 'skipped_no_channel': len(due)}

    sent = 0
    failed = 0
    for post in due:
        ok, message_id, err = _send_to_channel(channel_id, post.text_snapshot)
        if ok:
            post.status = STATUS_PUBLISHED
            post.published_at = datetime.now(timezone.utc).replace(tzinfo=None)
            post.message_id = message_id
            post.error = None
            sent += 1
        else:
            post.status = STATUS_FAILED
            post.error = (err or 'unknown')[:500]
            failed += 1
    db_session.commit()
    logger.info('Channel publisher: sent=%d failed=%d', sent, failed)
    return {'sent': sent, 'failed': failed, 'skipped_no_channel': 0}
