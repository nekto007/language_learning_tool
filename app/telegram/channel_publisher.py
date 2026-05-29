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
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from typing import Any

import requests
from flask import current_app
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.admin.site_settings import get_site_setting
from app.curriculum.routes.public import PUBLIC_CEFR_CODES
from app.grammar_lab.models import GrammarTopic
from app.telegram.channel_models import (
    ALLOWED_KINDS, ChannelPost,
    KIND_GRAMMAR, KIND_MANUAL, KIND_WORD,
    STATUS_FAILED, STATUS_PUBLISHED, STATUS_QUEUED, STATUS_SKIPPED,
)
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


def format_word_post(word: CollectionWords, site_url: str | None = None) -> str:
    """Render a Word-of-Day post in Telegram HTML."""
    base = (site_url or _site_url()).rstrip('/')
    parts = [
        '📖 <b>Слово дня</b>',
        '',
        f'🇬🇧 <b>{_h(word.english_word)}</b>'
        + (f' <code>/{_h(word.ipa_transcription)}/</code>' if word.ipa_transcription else ''),
        f'🇷🇺 {_h(word.russian_word)}',
    ]
    if word.sentences:
        # ``sentences`` may contain markup tags from the seed data; strip them
        # by escaping for safety even though Telegram HTML supports <i>.
        snippet = _h(word.sentences)[:300]
        parts.extend(['', f'<i>{snippet}</i>'])
    parts.append('')
    if word.level:
        parts.append(f'📚 Уровень {_h(word.level)}')
    # Escape the URL line too: defends against words containing HTML special
    # characters (none in production seed data, but cheap insurance).
    parts.append(
        '🔗 ' + _h(f'{base}/dictionary/{encode_word_slug(word.english_word)}')
    )
    return '\n'.join(parts)


def format_grammar_post(topic: GrammarTopic, site_url: str | None = None) -> str:
    """Render a Grammar-tip post in Telegram HTML."""
    base = (site_url or _site_url()).rstrip('/')
    content = topic.content if isinstance(topic.content, dict) else {}
    intro = (content.get('introduction') or '').strip()
    if not intro and topic.telegram_summary:
        intro = topic.telegram_summary.strip()
    if not intro:
        intro = ''  # Worst case: no body, just title + link.

    title_ru = topic.title_ru or topic.title
    parts = [
        f'🧠 <b>Грамматика: {_h(title_ru)}</b>'
        + (f' ({_h(topic.title)})' if topic.title and topic.title != title_ru else ''),
    ]
    if intro:
        parts.extend(['', _h(intro[:600])])

    # Surface one common mistake when present — useful, attention-grabbing.
    mistakes = content.get('common_mistakes') or []
    if mistakes:
        first = mistakes[0] if isinstance(mistakes[0], dict) else {}
        wrong = (first.get('wrong') or '').strip()
        correct = (first.get('correct') or '').strip()
        if wrong and correct:
            parts.extend([
                '',
                '⚠️ Частая ошибка:',
                f'❌ <i>{_h(wrong)}</i>',
                f'✅ <i>{_h(correct)}</i>',
            ])

    parts.append('')
    if topic.level:
        parts.append(f'📚 Уровень {_h(topic.level)}')
    parts.append(f'🔗 {base}/grammar-lab/topic/{_h(topic.slug)}')
    return '\n'.join(parts)


# ─── Queueing ──────────────────────────────────────────────────────────


def _slot_kind_for_time(
    hour: int, minute: int, morning_hour: int, morning_minute: int,
) -> str:
    """Decide which content kind a given UTC slot represents.

    Morning slot → word; evening slot → grammar. The publisher only ever
    fills the two configured slots, so anything else defaults to KIND_WORD
    defensively.
    """
    is_morning = hour == morning_hour and minute == morning_minute
    return KIND_WORD if is_morning else KIND_GRAMMAR


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
    return None


# ─── Publishing ────────────────────────────────────────────────────────


def _send_to_channel(channel_id: str, text: str) -> tuple[bool, int | None, str | None]:
    """POST sendMessage to Telegram. Returns (success, message_id, error)."""
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

    if not resp.ok:
        # Telegram error bodies are short JSON — safe to surface.
        return False, None, resp.text[:400]

    body = resp.json() if resp.content else {}
    message_id = (body.get('result') or {}).get('message_id')
    return True, message_id, None


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
