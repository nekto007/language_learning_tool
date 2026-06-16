import logging
import threading
import time
from datetime import datetime
from typing import Any

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Query

from app.modules.decorators import module_required
from app.study.models import GameScore
from app.utils.db import db
from app.words.detail_service import build_word_profile, build_word_study_summary, get_related_words
from app.words.forms import WordFilterForm, WordSearchForm
from app.words.models import CollectionWords
from config.settings import DEFAULT_TIMEZONE

logger = logging.getLogger(__name__)


# Simple TTL cache for leaderboard data (shared across requests)
_leaderboard_cache: dict = {'data': None, 'expires': 0.0, 'lock': threading.Lock()}
_MISSION_PHASE_POINTS = {
    'recall': 8,
    'learn': 22,
    'use': 18,
    'read': 20,
    'check': 12,
    'close': 0,
}
_LEGACY_STEP_POINTS = {
    'lesson': 22,
    'grammar': 18,
    'words': 14,
    'books': 20,
    'book_course_practice': 18,
}
_LINEAR_SLOT_POINTS = {
    'curriculum': 22,
    'srs': 14,
    'reading': 20,
    'error_review': 12,
}


words = Blueprint('words', __name__)
PUBLIC_DICTIONARY_ALPHABET = tuple('abcdefghijklmnopqrstuvwxyz')


def encode_word_slug(english_word: str) -> str:
    """Reversible slug: spaces → '_', preserve hyphens (e.g. 'mother-in-law')."""
    return (english_word or '').strip().lower().replace(' ', '_')


def decode_word_slug(slug: str) -> str:
    """Inverse of encode_word_slug: '_' → space, preserve hyphens."""
    return (slug or '').strip().lower().replace('_', ' ')


@words.app_template_filter('word_slug')
def _word_slug_filter(value: str) -> str:
    return encode_word_slug(value)


def _public_dictionary_query() -> Query:
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES

    return CollectionWords.query.filter(
        CollectionWords.item_type == 'word',
        CollectionWords.level.in_(PUBLIC_CEFR_CODES),
    )


def _public_site_url() -> str:
    return (current_app.config.get('SITE_URL') or 'https://llt-english.com').rstrip('/')


@words.route('/dictionary')
@words.route('/dictionary/letter/<string:letter>')
@words.route('/dictionary/level/<string:level>')
def public_dictionary(letter: str | None = None, level: str | None = None):
    """Public dictionary index for SEO — no login required."""
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES

    selected_letter = (letter or '').strip().lower()
    if selected_letter and (
        len(selected_letter) != 1 or selected_letter not in PUBLIC_DICTIONARY_ALPHABET
    ):
        abort(404)

    search = request.args.get('q', '').strip()

    # Level filtering has a single canonical address: the clean path
    # /dictionary/level/<level>. The legacy ?level= query form is 301-redirected
    # to it (when standalone) so each level is indexed once, not as a duplicate
    # of /dictionary.
    path_level = (level or '').strip().upper()
    if path_level and path_level not in PUBLIC_CEFR_CODES:
        abort(404)
    # Canonical level path is lowercase — 301 non-canonical casing.
    if level and level != level.lower():
        page_arg = request.args.get('page', type=int)
        return redirect(
            url_for(
                'words.public_dictionary',
                level=level.lower(),
                page=page_arg if page_arg and page_arg > 1 else None,
            ),
            code=301,
        )

    query_level = request.args.get('level', '').strip().upper()
    if (
        query_level in PUBLIC_CEFR_CODES
        and not path_level
        and not selected_letter
        and not search
    ):
        page_arg = request.args.get('page', type=int)
        return redirect(
            url_for(
                'words.public_dictionary',
                level=query_level.lower(),
                page=page_arg if page_arg and page_arg > 1 else None,
            ),
            code=301,
        )

    selected_level = path_level or query_level
    if selected_level and selected_level not in PUBLIC_CEFR_CODES:
        selected_level = ''

    page = request.args.get('page', 1, type=int)
    query = _public_dictionary_query()

    if selected_letter:
        query = query.filter(CollectionWords.english_word.ilike(f'{selected_letter}%'))

    if selected_level:
        query = query.filter(CollectionWords.level == selected_level)

    if search:
        search_term = f'%{search}%'
        query = query.filter(or_(
            CollectionWords.english_word.ilike(search_term),
            CollectionWords.russian_word.ilike(search_term),
        ))

    words_page = query.order_by(
        CollectionWords.frequency_rank.asc().nullslast(),
        CollectionWords.english_word.asc(),
    ).paginate(page=page, per_page=48, error_out=False)

    level_counts = dict(
        db.session.query(CollectionWords.level, func.count(CollectionWords.id))
        .filter(
            CollectionWords.item_type == 'word',
            CollectionWords.level.in_(PUBLIC_CEFR_CODES),
        )
        .group_by(CollectionWords.level)
        .all()
    )

    popular_words = _public_dictionary_query().order_by(
        CollectionWords.frequency_rank.asc().nullslast(),
        CollectionWords.english_word.asc(),
    ).limit(12).all()

    if selected_letter:
        meta_description = (
            f'Английские слова на букву {selected_letter.upper()}: '
            f'{words_page.total} переводов с примерами, уровни CEFR, произношение.'
        )
    elif selected_level:
        meta_description = (
            f'Английские слова уровня {selected_level}: '
            f'{words_page.total} переводов на русский с примерами и произношением.'
        )
    else:
        meta_description = (
            'Англо-русский словарь LLT English: переводы, уровни CEFR, '
            'примеры употребления и произношение английских слов.'
        )

    return render_template(
        'words/public_dictionary.html',
        words_page=words_page,
        popular_words=popular_words,
        levels=PUBLIC_CEFR_CODES,
        level_counts=level_counts,
        alphabet=PUBLIC_DICTIONARY_ALPHABET,
        selected_letter=selected_letter,
        selected_level=selected_level,
        search=search,
        meta_description=meta_description,
        should_noindex=bool(search),
    )


@words.route('/dictionary/')
def public_dictionary_trailing_slash():
    """Redirect the trailing-slash variant to the canonical no-slash URL (SEO)."""
    return redirect(url_for('words.public_dictionary'), code=301)


@words.route('/dictionary/<path:word_slug>')
def public_word(word_slug: str):
    """Public word page for SEO — no login required."""
    # Slug uses '_' for spaces; hyphens are preserved (e.g. 'mother-in-law').
    search_term = decode_word_slug(word_slug)

    word = CollectionWords.query.filter(
        func.lower(CollectionWords.english_word) == search_term
    ).first()

    if not word:
        # Legacy fallback: older slug format used '-' for spaces; if a hyphen
        # was used as a space separator, try interpreting all hyphens as spaces.
        legacy_term = word_slug.strip().lower().replace('-', ' ').replace('_', ' ')
        if legacy_term != search_term:
            word = CollectionWords.query.filter(
                func.lower(CollectionWords.english_word) == legacy_term
            ).first()
        if not word:
            abort(404)

    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
    if word.level and word.level not in PUBLIC_CEFR_CODES:
        abort(404)

    # Single canonical address per word — 301 non-canonical casing / legacy
    # hyphen slugs to the encoded canonical slug.
    canonical_slug = encode_word_slug(word.english_word)
    if word_slug != canonical_slug:
        return redirect(url_for('words.public_word', word_slug=canonical_slug), code=301)

    word_profile = build_word_profile(word, public_only=True)
    related_words = get_related_words(word, limit=6, public_only=True)

    # Related grammar topics (same level)
    related_grammar = []
    if word.level:
        from app.grammar_lab.models import GrammarTopic
        related_grammar = (
            GrammarTopic.query
            .filter(GrammarTopic.level == word.level)
            .order_by(GrammarTopic.order)
            .limit(3)
            .all()
        )

    # Collocations (many-per-word; surface for SEO depth)
    from app.curriculum.models import WordCollocation
    collocations = (
        WordCollocation.query
        .filter(WordCollocation.word_id == word.id)
        .order_by(WordCollocation.id)
        .all()
    )

    # Contrast pairs — surface as unique on-page content (SEO depth) and to
    # help learners distinguish commonly-confused words.
    from app.words.models import WordContrast
    contrast_rows = (
        WordContrast.query
        .filter((WordContrast.word_a_id == word.id) | (WordContrast.word_b_id == word.id))
        .order_by(WordContrast.id)
        .all()
    )
    contrasts = []
    for row in contrast_rows:
        other = row.other_word(word.id)
        if other is None:
            continue
        contrasts.append({'other': other, 'note_ru': row.note_ru})

    meta_description = (
        f'{word.english_word} — перевод: {word.russian_word}. '
        f'Уровень {word.level or ""}. Примеры, произношение и упражнения.'
    )
    canonical_url = (
        f'{_public_site_url()}'
        f'{url_for("words.public_word", word_slug=canonical_slug)}'
    )

    return render_template(
        'words/public_word.html',
        word=word,
        word_profile=word_profile,
        word_profile_public=True,
        related_words=related_words,
        related_grammar=related_grammar,
        collocations=collocations,
        contrasts=contrasts,
        meta_description=meta_description,
        canonical_url=canonical_url,
    )


@words.route('/contrast/<a_slug>/<b_slug>')
def public_contrast(a_slug: str, b_slug: str):
    """Standalone page for a word-contrast pair (X vs Y).

    Target SEO intent: «разница между X и Y» / «X or Y». Each contrast pair
    gets one canonical URL with ``word_a`` always the smaller-id side, so a
    request for the reverse order 301-redirects to the canonical form. This
    keeps PageRank consolidated on a single URL and avoids duplicate-content
    flags.
    """
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
    from app.words.models import WordContrast

    a_name = decode_word_slug(a_slug)
    b_name = decode_word_slug(b_slug)
    word_a = CollectionWords.query.filter(
        func.lower(CollectionWords.english_word) == a_name.lower()
    ).first()
    word_b = CollectionWords.query.filter(
        func.lower(CollectionWords.english_word) == b_name.lower()
    ).first()
    if not word_a or not word_b or word_a.id == word_b.id:
        abort(404)
    for w in (word_a, word_b):
        if w.level and w.level not in PUBLIC_CEFR_CODES:
            abort(404)

    low_id, high_id = sorted((word_a.id, word_b.id))
    contrast = WordContrast.query.filter_by(
        word_a_id=low_id, word_b_id=high_id,
    ).first()
    if contrast is None:
        abort(404)

    # Canonicalise URL order. word_a in the URL must be the row's word_a
    # (smaller id). If the visitor came in via the reverse order, redirect.
    canonical_a = contrast.word_a
    canonical_b = contrast.word_b
    if word_a.id != canonical_a.id:
        return redirect(
            url_for(
                'words.public_contrast',
                a_slug=encode_word_slug(canonical_a.english_word),
                b_slug=encode_word_slug(canonical_b.english_word),
            ),
            code=301,
        )

    canonical_url = _public_site_url() + url_for(
        "words.public_contrast",
        a_slug=encode_word_slug(canonical_a.english_word),
        b_slug=encode_word_slug(canonical_b.english_word),
    )
    meta_description = (
        f'{canonical_a.english_word} vs {canonical_b.english_word} — '
        f'в чём разница. {canonical_a.russian_word or ""} или '
        f'{canonical_b.russian_word or ""}. Объяснение с примерами и ссылками '
        f'на полные карточки слов.'
    )

    # Other pairs that share either word — gives the page some internal
    # depth and helps crawlers discover related contrasts.
    related = (
        WordContrast.query
        .filter(WordContrast.id != contrast.id)
        .filter(
            (WordContrast.word_a_id == canonical_a.id)
            | (WordContrast.word_b_id == canonical_a.id)
            | (WordContrast.word_a_id == canonical_b.id)
            | (WordContrast.word_b_id == canonical_b.id)
        )
        .order_by(WordContrast.id)
        .limit(6)
        .all()
    )

    return render_template(
        'words/public_contrast.html',
        contrast=contrast,
        word_a=canonical_a,
        word_b=canonical_b,
        related=related,
        canonical_url=canonical_url,
        meta_description=meta_description,
    )


def _process_referral_reward_on_first_visit(user) -> None:
    """Award referral XP to referrer after the referred user completes onboarding.

    Checks the explicit onboarding_completed flag so the reward is not
    triggered before the user has actually finished the onboarding flow.
    """
    if not getattr(user, 'referred_by_id', None):
        return

    # Only award after onboarding is completed
    if not getattr(user, 'onboarding_completed', False):
        return

    from app.notifications.models import Notification

    # Check if reward already delivered (notification to referrer about this user)
    already = Notification.query.filter_by(
        user_id=user.referred_by_id,
        type='referral',
    ).filter(Notification.title.contains(user.username)).first()
    if already:
        return

    try:
        from app.achievements.xp_service import award_referral_xp_idempotent
        from app.admin.site_settings import get_referral_bonus_xp
        bonus_xp = get_referral_bonus_xp()
        award_referral_xp_idempotent(user.referred_by_id, user.id, bonus_xp)

        from app.notifications.services import notify_referral
        notify_referral(user.referred_by_id, user.username, bonus_xp=bonus_xp)

        from app.auth.routes import _check_referral_achievements
        _check_referral_achievements(user.referred_by_id)

        db.session.commit()
    except Exception as e:
        logger.exception("Referral reward processing failed for user %s: %s", user.referred_by_id, e)
        db.session.rollback()


def _safe_widget_call(name: str, fn, *args, default=None, **kwargs) -> Any:
    """Call a widget data function safely, returning default on failure.

    Uses a savepoint so that a widget failure only rolls back its own
    queries, leaving the outer transaction (and already-loaded objects
    like current_user) intact.
    """
    try:
        with db.session.begin_nested():
            return fn(*args, **kwargs)
    except Exception as e:
        db.session.rollback()
        logger.exception("Dashboard widget '%s' failed: %s", name, e)
        return default


def _get_cached_leaderboard(stats_service_cls, limit: int = 5) -> list:
    """Return leaderboard data with 5-minute TTL cache."""
    cache = _leaderboard_cache
    now = time.time()
    with cache['lock']:
        if cache['data'] is not None and now < cache['expires']:
            return cache['data']
    # Query outside the lock to avoid serializing all dashboard requests
    data = stats_service_cls.get_xp_leaderboard(limit=limit)
    with cache['lock']:
        cache['data'] = data
        cache['expires'] = time.time() + 300  # 5 minutes
    return data


def invalidate_leaderboard_cache() -> None:
    """Expire the leaderboard cache immediately.

    Call this after any XP award so the next dashboard request reflects
    the updated ranking without waiting for the 5-minute TTL to expire.
    """
    with _leaderboard_cache['lock']:
        _leaderboard_cache['expires'] = 0.0


_MEDAL_BY_RANK = {1: 'gold', 2: 'silver', 3: 'bronze'}


def _participant_initials(username: str | None) -> str:
    """Return 1-2 uppercase initials from a username for avatar display."""
    if not username:
        return '?'
    clean = username.strip()
    if not clean:
        return '?'
    # If the username contains separators, take the first letter of first two parts.
    parts = [p for p in clean.replace('_', ' ').replace('.', ' ').split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return clean[:2].upper() if len(clean) >= 2 else clean[0].upper()


def _next_phase_points(plan: dict, plan_completion: dict) -> tuple[str | None, int]:
    """Return (title, points) for the first incomplete required phase."""
    phases = plan.get('phases') or []
    if phases:
        for phase in phases:
            if not phase.get('required', True):
                continue
            if plan_completion.get(phase.get('id'), False):
                continue
            points = _MISSION_PHASE_POINTS.get(phase.get('phase', ''), 12)
            return phase.get('title') or 'Следующий этап', points

    baseline_slots = plan.get('baseline_slots') or []
    if plan.get('mode') == 'linear' and baseline_slots:
        for slot in baseline_slots:
            kind = slot.get('kind', '')
            if plan_completion.get(kind, False):
                continue
            return slot.get('title') or 'Следующий слот', _LINEAR_SLOT_POINTS.get(kind, 12)
        continuation = plan.get('continuation') or {}
        next_lessons = continuation.get('next_lessons') or []
        if next_lessons:
            next_lesson = next_lessons[0] or {}
            module_number = next_lesson.get('module_number')
            lesson_number = next_lesson.get('lesson_number')
            title = 'Следующий урок'
            if module_number and lesson_number:
                title = f'Модуль {module_number} · Урок {lesson_number}'
            return title, _LINEAR_SLOT_POINTS['curriculum']

    steps = plan.get('steps') or {}
    for key in ('lesson', 'grammar', 'words', 'books', 'book_course_practice'):
        step = steps.get(key)
        if not step or plan_completion.get(key, False):
            continue
        title = step.get('title') or 'Следующий шаг'
        return title, _LEGACY_STEP_POINTS.get(key, 15)
    return None, 0


def _get_next_plan_action(plan: dict, daily_summary: dict) -> tuple[str | None, str | None]:
    from app.achievements.streak_service import _compute_linear_slot_completion

    if plan.get('mode') == 'unified':
        from app.achievements.streak_service import compute_plan_steps
        plan_completion, _avail, _done, _total = compute_plan_steps(plan, daily_summary)
        all_items = list(plan.get('required') or []) + list(plan.get('optional') or [])
        for item in all_items:
            item_id = item.get('id', '')
            summary_done = plan_completion.get(item_id, False)
            if (
                item.get('completed')
                or item.get('skipped')
                or item.get('blocked')
                or summary_done
            ):
                continue
            item_url = item.get('url')
            if item_url:
                return item.get('title') or 'Следующий шаг', item_url
        return None, None

    if plan.get('mode') == 'linear':
        # Iterate the full chain (baseline + extensions) so that, after the
        # baseline is closed, the next chain extension's slot URL is used as
        # the canonical "next step" rather than continuation.next_lessons[0]
        # (which is a *preview* of lessons after the current chain extension).
        # Baseline slots may be marked done via summary activity even when
        # ``slot.completed`` is False (the SRS slot only flips on the
        # ``linear_srs_global`` XP event), so merge plan_completion for the
        # baseline portion. Extension slots are kind-deduped per chain build,
        # so trust ``slot.completed`` directly there.
        baseline_slots = plan.get('baseline_slots') or []
        chain_slots = plan.get('slots') or baseline_slots
        chain_meta = plan.get('chain_meta') or {}
        baseline_count = int(chain_meta.get('baseline_count') or len(baseline_slots))
        completion = _compute_linear_slot_completion(baseline_slots, daily_summary)
        def _slot_effectively_done(idx: int, slot: dict) -> bool:
            return (
                slot.get('completed', False)
                or (idx < baseline_count and completion.get(slot.get('kind', ''), False))
            )
        next_slot = next(
            (
                slot for idx, slot in enumerate(chain_slots)
                if not _slot_effectively_done(idx, slot)
                and not slot.get('skipped')
                and not slot.get('blocked')
            ),
            None,
        )
        if next_slot is None:
            next_slot = next(
                (
                    slot for idx, slot in enumerate(chain_slots)
                    if not _slot_effectively_done(idx, slot)
                    and slot.get('skipped')
                    and not slot.get('blocked')
                ),
                None,
            )
        if next_slot and next_slot.get('url'):
            return next_slot.get('title') or 'Следующий слот', next_slot.get('url')
        if any(
            not _slot_effectively_done(idx, slot)
            and (slot.get('skipped') or slot.get('blocked'))
            for idx, slot in enumerate(chain_slots)
        ):
            return None, None
        continuation = plan.get('continuation') or {}
        next_lessons = continuation.get('next_lessons') or []
        if next_lessons:
            next_lesson = next_lessons[0] or {}
            if next_lesson.get('lesson_id'):
                module_number = next_lesson.get('module_number')
                lesson_number = next_lesson.get('lesson_number')
                title = 'Следующий урок'
                if module_number and lesson_number:
                    title = f'Модуль {module_number} · Урок {lesson_number}'
                return (
                    title,
                    url_for('curriculum_lessons.lesson_detail', lesson_id=next_lesson['lesson_id'])
                    + '?from=linear_plan_continuation',
                )

    steps = plan.get('steps') or {}
    legacy_order = ('lesson', 'grammar', 'words', 'books', 'book_course_practice')
    for key in legacy_order:
        step = steps.get(key)
        if step and not step.get('is_done'):
            return step.get('title') or 'Следующий шаг', step.get('url')

    return None, None


def _build_rank_info(current_user_id: int) -> dict | None:
    from app.achievements.models import UserStatistics
    from app.achievements.ranks import (
        RANK_COLORS,
        RANK_ICONS,
        RANK_RU_NAMES,
        get_user_rank,
    )

    stats = UserStatistics.query.filter_by(user_id=current_user_id).first()
    plans_completed = int(stats.plans_completed_total) if stats and stats.plans_completed_total else 0
    info = get_user_rank(plans_completed)

    return {
        'code': info.code,
        'name': info.name,
        'display_name': RANK_RU_NAMES.get(info.code, info.name),
        'icon': RANK_ICONS.get(info.code, '\U0001F3C6'),
        'color': RANK_COLORS.get(info.code, '#64748b'),
        'plans_completed': info.plans_completed,
        'threshold': info.threshold,
        'next_code': info.next_code,
        'next_name': info.next_name,
        'next_display_name': RANK_RU_NAMES.get(info.next_code) if info.next_code else None,
        'next_threshold': info.next_threshold,
        'progress_percent': info.progress_percent,
        'plans_to_next': info.plans_to_next,
        'is_max': info.next_code is None,
    }


def _compute_daily_race_state(plan: dict, daily_summary: dict, streak: int) -> dict:
    """Compute score, step counts, and next-step info for a single user in the daily race."""
    from app.achievements.streak_service import compute_plan_steps

    plan_completion, _steps_available, steps_done, steps_total = compute_plan_steps(plan, daily_summary)

    score = 0
    phases = plan.get('phases') or []
    if phases:
        for phase in phases:
            if not phase.get('required', True):
                continue
            if plan_completion.get(phase.get('id'), False):
                score += _MISSION_PHASE_POINTS.get(phase.get('phase', ''), 12)
    elif plan.get('mode') == 'linear':
        for key, pts in _LINEAR_SLOT_POINTS.items():
            if plan_completion.get(key, False):
                score += pts
    else:
        for key, pts in _LEGACY_STEP_POINTS.items():
            if plan_completion.get(key, False):
                score += pts

    next_step_title, next_step_points = _next_phase_points(plan, plan_completion)

    return {
        'score': score,
        'steps_done': steps_done,
        'steps_total': steps_total,
        'next_step_title': next_step_title,
        'next_step_points': next_step_points,
    }


def _build_daily_race_widget(current_user_id: int, tz: str) -> dict | None:
    from datetime import datetime as _dt_age

    import pytz

    from app.achievements.daily_race import get_race_standings
    from app.admin.site_settings import get_site_setting
    from app.auth.models import User
    from app.daily_plan.service import get_daily_plan_unified
    from app.telegram.queries import get_current_streak, get_daily_summary

    def _is_adult(birth_year):
        if birth_year is None:
            return True
        try:
            return (_dt_age.utcnow().year - int(birth_year)) >= 18
        except (TypeError, ValueError):
            return True

    if get_site_setting('daily_race_enabled', 'true') != 'true':
        return None

    user = User.query.get(current_user_id)
    if user is None or not _is_adult(getattr(user, 'birth_year', None)):
        return None

    try:
        tz_obj = pytz.timezone(tz or DEFAULT_TIMEZONE)
    except pytz.UnknownTimeZoneError:
        tz_obj = pytz.timezone(DEFAULT_TIMEZONE)
    local_today = datetime.now(tz_obj).date()

    standings = get_race_standings(current_user_id, local_today, tz=tz)
    if not standings:
        return None

    participant_rows = standings.get('participants') or []
    if not participant_rows:
        return None

    human_entries: dict[int, dict] = {}
    current_user_max_score = 1

    for row in participant_rows:
        if row.get('is_ghost') or row.get('user_id') is None:
            continue
        participant_user_id = int(row['user_id'])
        user = User.query.get(participant_user_id)
        if user is None:
            continue
        user_tz = user.timezone or tz
        try:
            plan = get_daily_plan_unified(user.id, tz=user_tz)
            summary = get_daily_summary(user.id, tz=user_tz)
            streak = get_current_streak(user.id, tz=user_tz)
            race_state = _compute_daily_race_state(plan, summary, streak)
        except Exception as e:
            logger.exception(
                "Failed to build daily race entry for user %s: %s",
                participant_user_id,
                e,
            )
            continue

        if race_state['steps_total'] <= 0:
            continue

        uname = user.username or ''
        max_score = 0
        for phase in plan.get('phases') or []:
            if not phase.get('required', True):
                continue
            max_score += _MISSION_PHASE_POINTS.get(phase.get('phase', ''), 12)
        if plan.get('mode') == 'linear':
            for slot in plan.get('baseline_slots') or []:
                max_score += _LINEAR_SLOT_POINTS.get(slot.get('kind', ''), 0)
        if user.id == current_user_id:
            current_user_max_score = max(1, max_score)

        human_entries[user.id] = {
            'user_id': user.id,
            'username': uname,
            'initials': _participant_initials(uname),
            'score': int(row.get('points', 0) or 0),
            'steps_done': race_state['steps_done'],
            'steps_total': race_state['steps_total'],
            'streak': streak,
            'next_step_title': race_state['next_step_title'],
            'next_step_points': race_state['next_step_points'],
            'is_me': user.id == current_user_id,
            'is_bot': False,
            'max_score': max(1, max_score),
        }

    entries = []
    for row in participant_rows:
        if row.get('is_ghost') or row.get('user_id') is None:
            ghost_score = int(row.get('points', 0) or 0)
            route_position = min(100, int(round(ghost_score / max(1, current_user_max_score) * 100)))
            entries.append({
                'user_id': row.get('user_id'),
                'username': row.get('username') or 'Тренировочный соперник',
                'initials': _participant_initials(row.get('username')),
                'score': ghost_score,
                'steps_done': 0,
                'steps_total': 0,
                'streak': 0,
                'next_step_title': None,
                'next_step_points': 0,
                'is_me': False,
                'is_bot': True,
                'rank': row.get('rank'),
                'place_class': _MEDAL_BY_RANK.get(row.get('rank'), ''),
                'is_complete': False,
                'route_position': route_position,
            })
            continue

        human = human_entries.get(row.get('user_id'))
        if human is None:
            continue
        human['rank'] = row.get('rank')
        human['place_class'] = _MEDAL_BY_RANK.get(row.get('rank'), '')
        human['is_complete'] = human['steps_done'] >= human['steps_total'] and human['steps_total'] > 0
        st = human['steps_total']
        human['route_position'] = int(human['steps_done'] / st * 100) if st > 0 else 0
        entries.append(human)

    current_index = next((i for i, item in enumerate(entries) if item['is_me']), None)
    if current_index is None:
        return None

    me = entries[current_index]
    rival_above = entries[current_index - 1] if current_index > 0 else None
    rival_below = entries[current_index + 1] if current_index + 1 < len(entries) else None

    gap_up = max(1, rival_above['score'] - me['score']) if rival_above else 0
    gap_down = max(1, me['score'] - rival_below['score']) if rival_below else None

    if rival_above:
        if me['next_step_points'] and me['next_step_points'] > gap_up:
            callout = f'«{me["next_step_title"]}» даст рывок и поднимет тебя выше {rival_above["username"]}.'
        elif me['next_step_points']:
            remaining = max(0, gap_up - me['next_step_points'])
            callout = (
                f'«{me["next_step_title"]}» сократит отрыв до {remaining} '
                f'и приблизит тебя к {rival_above["username"]}.'
            )
        else:
            callout = f'До {rival_above["username"]}: {gap_up} очков.'
    else:
        callout = 'Ты впереди. Закрой следующий этап и закрепи лидерство.'

    start = max(0, current_index - 2)
    end = min(len(entries), current_index + 3)

    me_is_complete = me['steps_done'] >= me['steps_total'] and me['steps_total'] > 0

    # Build route_rivals: compact set for on-route token display (one ahead, one behind, optional leader)
    entries_by_pos = sorted(entries, key=lambda e: (-e['route_position'], -e['score']))
    me_pos_idx = next((i for i, e in enumerate(entries_by_pos) if e['is_me']), None)
    route_rivals: list[dict] = []
    if me_pos_idx is not None:
        ahead = entries_by_pos[me_pos_idx - 1] if me_pos_idx > 0 else None
        behind = entries_by_pos[me_pos_idx + 1] if me_pos_idx + 1 < len(entries_by_pos) else None
        leader = entries_by_pos[0] if not entries_by_pos[0]['is_me'] else None
        if ahead:
            route_rivals.append({**ahead, 'rival_role': 'ahead'})
        route_rivals.append({**entries_by_pos[me_pos_idx], 'rival_role': 'me'})
        if behind:
            route_rivals.append({**behind, 'rival_role': 'behind'})
        if leader and leader['user_id'] not in {e['user_id'] for e in route_rivals}:
            route_rivals.append({**leader, 'rival_role': 'leader'})

    return {
        'rank': me['rank'],
        'place_class': me['place_class'],
        'total': len(entries),
        'score': me['score'],
        'steps_done': me['steps_done'],
        'steps_total': me['steps_total'],
        'streak': me['streak'],
        'is_complete': me_is_complete,
        'rival_above': rival_above,
        'rival_below': rival_below,
        'gap_up': gap_up,
        'gap_down': gap_down,
        'callout': callout,
        'next_step_title': me['next_step_title'],
        'next_step_points': me['next_step_points'],
        'duel_target': rival_above or rival_below,
        'has_bot_rivals': any(entry.get('is_bot') for entry in entries),
        'leaderboard': entries[start:end],
        'route_rivals': route_rivals,
    }


_FOCUS_DEFAULT_XP_TARGET = 30
_FOCUS_DEFAULT_WORDS_TARGET = 10


def _build_week_rhythm(user_id: int, tz: str) -> dict:
    """Return {days: [{date, label, active, today}*7], summary} for the rail.

    Pulls the activity heatmap from insights_service (already covers all
    six learning sources) and projects the last 7 calendar days. ``today``
    is the user's local today; ``active`` is heatmap.count > 0.
    """
    from datetime import datetime, timedelta

    import pytz

    from app.study.insights_service import get_activity_heatmap
    try:
        heatmap = get_activity_heatmap(user_id, days=14, tz=tz)
    except Exception:
        logger.warning('week_rhythm heatmap lookup failed', exc_info=True)
        heatmap = []
    by_date = {row['date']: row.get('count', 0) for row in heatmap}

    try:
        local_today = datetime.now(pytz.timezone(tz)).date()
    except Exception:
        local_today = datetime.utcnow().date()

    labels = ('Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс')
    monday = local_today - timedelta(days=local_today.weekday())
    days = []
    active_count = 0
    for i in range(7):
        d = monday + timedelta(days=i)
        is_today = (d == local_today)
        is_active = by_date.get(d.isoformat(), 0) > 0
        if is_active:
            active_count += 1
        days.append({
            'date': d.isoformat(),
            'label': labels[i],
            'active': is_active,
            'today': is_today,
        })
    summary = f'{active_count} из 7 учебных дней'
    return {'days': days, 'summary': summary}


_RU_MONTHS_GEN = {
    1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля', 5: 'мая', 6: 'июня',
    7: 'июля', 8: 'августа', 9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря',
}


def _build_weekly_report() -> dict | None:
    """Monday recap card: last calendar week stats, dismissible per ISO week.

    Shared by the legacy and unified dashboards. Returns None outside Monday,
    when already dismissed this week, or when last week had no activity.
    """
    try:
        import pytz as _pytz_wr

        from datetime import datetime as _dt_wr, timedelta as _td_wr

        _tz_wr_name = getattr(current_user, 'timezone', None) or DEFAULT_TIMEZONE
        try:
            _tz_wr = _pytz_wr.timezone(_tz_wr_name)
        except Exception:
            _tz_wr = _pytz_wr.timezone(DEFAULT_TIMEZONE)
        _today_wr = _dt_wr.now(_tz_wr).date()
        if _today_wr.weekday() != 0:
            return None
        # ISO week key e.g. "2026-W19" — dismissed once per Monday session
        _week_key = _today_wr.strftime('%G-W%V')
        _dismissed_key = f'weekly_report_dismissed_{_week_key}'
        if session.get(_dismissed_key):
            return None
        from app.study.insights_service import get_last_week_summary
        report = _safe_widget_call(
            'last_week_summary',
            get_last_week_summary,
            current_user.id,
            _tz_wr_name,
            default=None,
        )
        if not report or not report.get('has_activity'):
            return None
        report['dismiss_key'] = _dismissed_key
        # get_last_week_summary не возвращает week_label — собираем здесь
        # («19–25 мая» / «28 апреля – 4 мая»), легаси-шаблон рендерил пустоту.
        last_monday = _today_wr - _td_wr(days=7)
        last_sunday = _today_wr - _td_wr(days=1)
        if last_monday.month == last_sunday.month:
            report['week_label'] = (
                f'{last_monday.day}–{last_sunday.day} {_RU_MONTHS_GEN[last_sunday.month]}'
            )
        else:
            report['week_label'] = (
                f'{last_monday.day} {_RU_MONTHS_GEN[last_monday.month]} – '
                f'{last_sunday.day} {_RU_MONTHS_GEN[last_sunday.month]}'
            )
        return report
    except Exception:
        logger.warning('weekly_report build failed', exc_info=True)
        return None


def _render_unified_dashboard(tz: str):
    """Render the two-column dashboard for unified-plan users.

    Reuses the Path dashboard's hero + rail components (focus / week rhythm
    / challenge) so visual context stays consistent across plan modes, but
    swaps the path partial for partials/unified_daily_plan.html.
    """
    from app.achievements.models import UserStatistics
    from app.achievements.streak_service import (
        compute_plan_steps,
        process_streak_on_activity,
    )
    from app.achievements.xp_service import get_level_info, get_today_xp
    from app.daily_plan.service import get_daily_plan_unified
    from app.telegram.queries import get_current_streak, get_daily_summary

    streak = get_current_streak(current_user.id, tz=tz)
    daily_summary = get_daily_summary(current_user.id, tz=tz)
    unified_plan = get_daily_plan_unified(current_user.id, tz=tz) or {}
    # Снапшот состава дня пишется flush-only при сборке — фиксируем его,
    # иначе teardown откатит запись и план продолжит «плыть» между запросами.
    try:
        db.session.commit()
    except Exception:
        logger.warning('plan snapshot commit failed', exc_info=True)
        db.session.rollback()
    plan_completion, _avail, steps_done, steps_total = compute_plan_steps(
        unified_plan, daily_summary
    )

    # Normalise required-section state from plan_completion: if summary data
    # says an item is done (e.g. user returned to a skipped SRS slot and
    # reviewed cards), clear any stale skipped/blocked flag and mark the
    # item completed. Otherwise the template's strict precedence keeps
    # showing «Пропущено» / locked even though plan_completion already
    # credits the slot — and the top counter never increments.
    for _it in (unified_plan.get('required') or []):
        if plan_completion.get(_it.get('id'), False):
            _it['completed'] = True
            _it['skipped'] = False
            _it['blocked'] = False
    for _it in (unified_plan.get('optional') or []):
        if plan_completion.get(_it.get('id'), False):
            _it['completed'] = True
            _it['skipped'] = False
            _it['blocked'] = False

    # plan payload приходит с day_secured=False (assembly-time всегда False);
    # пересчитываем по фактической активности и записываем в payload, иначе
    # шаблон оставляет «Дополнительно» заблокированным даже при 4/4.
    from app.daily_plan.service import compute_day_secured_from_activity, write_secured_at
    _day_secured = compute_day_secured_from_activity(unified_plan, plan_completion)
    unified_plan['day_secured'] = _day_secured
    if _day_secured:
        try:
            from datetime import datetime as _dt_sec

            import pytz as _pytz_sec
            try:
                _tz_sec = _pytz_sec.timezone(tz)
            except _pytz_sec.UnknownTimeZoneError:
                _tz_sec = _pytz_sec.timezone(DEFAULT_TIMEZONE)
            write_secured_at(current_user.id, _dt_sec.now(_tz_sec).date())
            try:
                # Rank progression + rank-up notification on a secured day
                # (idempotent per local day). Gated on the unified day_secured;
                # record_plan_completion was previously only reachable from dead
                # mission/phase paths, freezing ranks at Novice.
                from app.achievements.ranks import record_plan_completion
                _rank_up = record_plan_completion(current_user.id)
                if _rank_up is not None:
                    from app.notifications.services import notify_rank_up
                    notify_rank_up(current_user.id, _rank_up.new_name)
            except Exception:
                logger.warning('rank-up recording failed in unified dashboard', exc_info=True)
            db.session.commit()
        except Exception:
            logger.warning('write_secured_at failed in unified dashboard', exc_info=True)
            db.session.rollback()

    streak_result = process_streak_on_activity(
        current_user.id, steps_done, steps_total, tz=tz,
        daily_plan=unified_plan, plan_completion=plan_completion,
    )
    streak = streak_result['streak_status'].get('streak', streak)

    # Daily challenge card (right rail) — best-effort.
    challenge_card = None
    try:
        from app.daily_plan.challenge import get_today_challenge
        ch = get_today_challenge(current_user.id, db)
        if ch and ch.get('lesson_id'):
            challenge_card = {
                'title': 'Бонусная цель дня',
                'badge': f"×{2 if ch.get('bonus_xp') else 1} XP",
                'completed': bool(ch.get('is_completed')),
                'url': f"/learn/{ch['lesson_id']}/",
            }
    except Exception:
        logger.warning('daily_challenge build failed (unified)', exc_info=True)

    stats = UserStatistics.query.filter_by(user_id=current_user.id).first()
    total_xp = (stats.total_xp if stats else 0) or 0
    level_info = get_level_info(total_xp)
    try:
        # get_today_xp требует date — без него падал в TypeError, и из-за
        # silent except шло «0 XP сегодня» даже после выполненных заданий.
        from datetime import datetime

        import pytz as _pytz_xp
        try:
            _tz = _pytz_xp.timezone(tz)
        except _pytz_xp.UnknownTimeZoneError:
            _tz = _pytz_xp.timezone(DEFAULT_TIMEZONE)
        _today_local = datetime.now(_tz).date()
        xp_today = get_today_xp(current_user.id, _today_local) or 0
    except Exception:
        logger.warning('get_today_xp failed in unified dashboard', exc_info=True)
        xp_today = 0

    # Daily word goal counter: total cards reviewed today (new + reviews).
    # The previous `daily_summary['words_studied']` key never existed in
    # get_daily_summary()'s return value, so the hero counter was stuck at 0
    # regardless of activity. `words_reviewed` is the broadest signal the
    # summary exposes and is the one users expect to see grow as they study.
    words_today = (daily_summary or {}).get('words_reviewed', 0) or 0
    words_goal = getattr(current_user, 'daily_word_goal', None) or _FOCUS_DEFAULT_WORDS_TARGET

    from app.admin.site_settings import is_streak_shield_enabled
    shield_visible = bool(
        getattr(current_user, 'streak_shield_active', False)
    ) and is_streak_shield_enabled()
    stats_card = {
        'streak_days': streak or 0,
        'streak_shield': shield_visible,
        'xp_today': xp_today,
        'level': level_info.current_level,
        'goal_target': words_goal,
        'goal_current': words_today,
        'goal_label': 'слов',
    }

    # Live remaining minutes: assembly-time total_estimated_minutes ignores
    # slots credited later via plan_completion (normalised above), so re-sum
    # eta over the still-incomplete required items.
    minutes_left = sum(
        int(_it.get('eta_minutes') or 0)
        for _it in (unified_plan.get('required') or [])
        if not _it.get('completed')
    )
    if steps_total and steps_done >= steps_total:
        subtitle = 'Минимум на сегодня выполнен — продолжайте, если есть силы'
    elif steps_total and steps_total - steps_done == 1:
        subtitle = 'Остался 1 шаг'
        if minutes_left:
            subtitle += f' · ~{minutes_left} мин'
        subtitle += ' — и день закрыт'
    elif steps_total:
        subtitle = f'{steps_done} из {steps_total} шагов'
        if minutes_left:
            subtitle += f' · осталось ~{minutes_left} мин'
    else:
        subtitle = 'Откройте каталог, чтобы начать обучение'
    hero = {
        'title': 'План на сегодня',
        'subtitle': subtitle,
        'steps_done': steps_done or 0,
        'steps_total': steps_total or 0,
        'minutes_left': minutes_left,
    }

    focus = {
        'targets': [
            {'label': 'Опыт', 'current': xp_today, 'target': _FOCUS_DEFAULT_XP_TARGET,
             'icon_key': 'sparkles', 'suffix': 'XP'},
            {'label': 'Словарь', 'current': words_today, 'target': words_goal,
             'icon_key': 'book-open', 'suffix': 'слов'},
        ],
    }

    week_rhythm = _build_week_rhythm(current_user.id, tz)

    # Social-row widgets: rank (титул), leaderboard, achievements.
    # All three live next to the unified plan in dedicated layout slots:
    #   - rank_info → full-width band above the plan
    #   - achievements_by_category → right rail, below week rhythm
    #   - xp_leaderboard → left column, below «Показать ещё задания»
    weekly_report = _build_weekly_report()

    rank_info = _safe_widget_call('rank_info', _build_rank_info, current_user.id, default=None)
    try:
        from app.study.services.stats_service import StatsService
    except Exception:
        StatsService = None
    if StatsService is not None:
        xp_leaderboard = _safe_widget_call(
            'xp_leaderboard', _get_cached_leaderboard, StatsService, limit=5, default=[])
        user_xp_rank = _safe_widget_call(
            'user_xp_rank', StatsService.get_user_xp_rank, current_user.id, default=None)
        achievements_by_category = _safe_widget_call(
            'achievements_by_category', StatsService.get_achievements_by_category,
            current_user.id, default={})
    else:
        xp_leaderboard, user_xp_rank, achievements_by_category = [], None, {}

    return render_template(
        'words/dashboard_unified.html',
        unified_plan=unified_plan,
        plan_completion=plan_completion,
        stats_card=stats_card,
        hero=hero,
        focus=focus,
        week_rhythm=week_rhythm,
        challenge_card=challenge_card,
        weekly_report=weekly_report,
        rank_info=rank_info,
        xp_leaderboard=xp_leaderboard,
        user_xp_rank=user_xp_rank,
        achievements_by_category=achievements_by_category,
    )


@words.route('/dashboard')
@login_required
@module_required('words')
def dashboard():
    """Main dashboard with daily plan, streak and activity summary."""
    tz = current_user.timezone or DEFAULT_TIMEZONE

    # Process deferred referral reward on first visit
    _process_referral_reward_on_first_visit(current_user)

    return _render_unified_dashboard(tz)


@words.route('/words')
@login_required
@module_required('words')
def word_list():
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
    from app.study.models import UserCardDirection, UserWord

    # Получение параметров фильтра
    search = request.args.get('search', '')
    status = request.args.get('status', '')  # Изменяем на строку для новой системы
    letter = request.args.get('letter', '')
    book_id = request.args.get('book_id', type=int)
    item_type = request.args.get('type', 'all')  # 'all', 'word', 'phrasal_verb'
    selected_level = request.args.get('level', '').strip().upper()
    if selected_level not in PUBLIC_CEFR_CODES:
        selected_level = ''
    sort = request.args.get('sort', 'recommended')
    if sort not in {'recommended', 'frequency', 'alpha', 'level', 'status', 'due'}:
        sort = 'recommended'

    # Параметры пагинации
    page = request.args.get('page', 1, type=int)
    per_page = max(1, min(request.args.get('per_page', 50, type=int), 200))

    # Создаем формы фильтров с параметрами запроса
    search_form = WordSearchForm(request.args)
    filter_form = WordFilterForm(request.args)

    # Формирование базового запроса с JOIN для получения статусов пользователя и информации о колоде
    from app.study.models import QuizDeck, QuizDeckWord

    # Subquery to get deck info for each word (first deck only)
    deck_subquery = db.session.query(
        QuizDeckWord.word_id,
        QuizDeck.id.label('deck_id'),
        QuizDeck.title.label('deck_title')
    ).join(
        QuizDeck, QuizDeckWord.deck_id == QuizDeck.id
    ).filter(
        QuizDeck.user_id == current_user.id
    ).distinct(QuizDeckWord.word_id).subquery()

    mastered_subquery = db.session.query(
        UserWord.word_id.label('word_id')
    ).join(
        CollectionWords, CollectionWords.id == UserWord.word_id
    ).join(
        UserCardDirection, UserCardDirection.user_word_id == UserWord.id
    ).filter(
        UserWord.user_id == current_user.id,
        UserWord.status == 'review',
        CollectionWords.english_word.isnot(None),
        func.trim(CollectionWords.english_word) != '',
        CollectionWords.level.in_(PUBLIC_CEFR_CODES),
    ).group_by(UserWord.word_id).having(
        func.min(UserCardDirection.interval) >= UserWord.MASTERED_THRESHOLD_DAYS
    ).subquery()

    next_review_subquery = db.session.query(
        UserWord.word_id.label('word_id'),
        func.min(UserCardDirection.next_review).label('next_review_at')
    ).filter(
        UserWord.user_id == current_user.id
    ).join(
        UserCardDirection, UserCardDirection.user_word_id == UserWord.id
    ).group_by(UserWord.word_id).subquery()

    query = db.session.query(
        CollectionWords,
        UserWord.status.label('user_status'),
        deck_subquery.c.deck_id.label('deck_id'),
        deck_subquery.c.deck_title.label('deck_title'),
        mastered_subquery.c.word_id.label('mastered_word_id'),
        next_review_subquery.c.next_review_at.label('next_review_at')
    ).outerjoin(
        UserWord,
        (CollectionWords.id == UserWord.word_id) & (UserWord.user_id == current_user.id)
    ).outerjoin(
        deck_subquery,
        CollectionWords.id == deck_subquery.c.word_id
    ).outerjoin(
        mastered_subquery,
        CollectionWords.id == mastered_subquery.c.word_id
    ).outerjoin(
        next_review_subquery,
        CollectionWords.id == next_review_subquery.c.word_id
    ).filter(
        CollectionWords.english_word.isnot(None),
        func.trim(CollectionWords.english_word) != '',
        CollectionWords.level.in_(PUBLIC_CEFR_CODES),
    )

    # Применяем фильтр по типу (word/phrasal_verb)
    if item_type == 'word':
        query = query.filter(CollectionWords.item_type == 'word')
    elif item_type == 'phrasal_verb':
        query = query.filter(CollectionWords.item_type == 'phrasal_verb')

    # Применяем фильтр поиска
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                CollectionWords.english_word.ilike(search_term),
                CollectionWords.russian_word.ilike(search_term)
            )
        )

    # Применяем фильтр статуса
    if status and status != 'all':
        if status == 'mine':
            query = query.filter(UserWord.id.isnot(None))
        elif status == 'not_added':
            query = query.filter(UserWord.id.is_(None))
        elif status == 'new':
            query = query.filter(UserWord.status == 'new')
        elif status == 'mastered':
            query = query.filter(mastered_subquery.c.word_id.isnot(None))
        elif status == 'review':
            query = query.filter(
                UserWord.status == 'review',
                mastered_subquery.c.word_id.is_(None),
            )
        else:
            query = query.filter(UserWord.status == status)

    if selected_level:
        query = query.filter(CollectionWords.level == selected_level)

    # Применяем фильтр по букве
    if letter:
        query = query.filter(CollectionWords.english_word.ilike(f"{letter}%"))

    # Применяем фильтр по книге
    if book_id:
        from app.words.models import word_book_link
        query = query.join(
            word_book_link,
            CollectionWords.id == word_book_link.c.word_id
        ).filter(word_book_link.c.book_id == book_id)

    level_order = case(
        (CollectionWords.level == 'A1', 1),
        (CollectionWords.level == 'A2', 2),
        (CollectionWords.level == 'B1', 3),
        (CollectionWords.level == 'B2', 4),
        (CollectionWords.level == 'C1', 5),
        else_=10,
    )
    frequency_order = (
        case((CollectionWords.frequency_rank > 0, 0), else_=1),
        CollectionWords.frequency_rank.asc(),
        CollectionWords.english_word.asc(),
    )
    status_order = case(
        (mastered_subquery.c.word_id.isnot(None), 1),
        (UserWord.status == 'review', 2),
        (UserWord.status == 'learning', 3),
        (UserWord.status == 'new', 4),
        else_=10,
    )

    # Smart sorting: prioritize exact matches when searching
    if search:
        search_lower = search.lower()
        query = query.order_by(
            # Priority 1: Exact match (case-insensitive)
            case(
                (func.lower(CollectionWords.english_word) == search_lower, 1),
                (func.lower(CollectionWords.russian_word) == search_lower, 1),
                else_=10
            ),
            # Priority 2: Starts with search term
            case(
                (func.lower(CollectionWords.english_word).like(f'{search_lower}%'), 2),
                (func.lower(CollectionWords.russian_word).like(f'{search_lower}%'), 2),
                else_=10
            ),
            # Priority 3: Alphabetically by English word
            CollectionWords.english_word.asc()
        )
    elif sort == 'alpha':
        query = query.order_by(CollectionWords.english_word.asc())
    elif sort == 'level':
        query = query.order_by(level_order, *frequency_order)
    elif sort == 'status':
        query = query.order_by(status_order, *frequency_order)
    elif sort == 'due':
        query = query.order_by(
            case((next_review_subquery.c.next_review_at.isnot(None), 0), else_=1),
            next_review_subquery.c.next_review_at.asc(),
            *frequency_order,
        )
    elif sort == 'frequency':
        query = query.order_by(*frequency_order)
    else:
        query = query.order_by(level_order, *frequency_order)

    # Пагинация
    words = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    # Преобразуем результат для шаблона
    word_list = []
    for word_obj, user_status, deck_id, deck_title, mastered_word_id, next_review_at in words.items:
        is_mastered = mastered_word_id is not None
        if is_mastered:
            display_status = 'mastered'
            status_label = 'Знаю'
            status_title = 'Слово отмечено как известное'
        elif user_status == 'review':
            display_status = 'review'
            status_label = 'Повторение'
            status_title = 'Слово в интервальном повторении'
        elif user_status == 'learning':
            display_status = 'learning'
            status_label = 'Изучаю'
            status_title = 'Слово сейчас изучается'
        elif user_status == 'new':
            display_status = 'new'
            status_label = 'Новое'
            status_title = 'Слово добавлено, но еще не отвечалось'
        else:
            display_status = 'not_added'
            status_label = 'Не добавлено'
            status_title = 'Слово еще не в ваших карточках'

        word_obj.user_status = display_status
        word_obj.action_status = user_status or 'new'
        word_obj.status_label = status_label
        word_obj.status_title = f'{status_title}. Колода: {deck_title}' if deck_title else status_title
        word_obj.is_mastered = is_mastered
        word_obj.in_study = bool(user_status) or bool(deck_id)
        word_obj.deck_id = deck_id
        word_obj.deck_title = deck_title
        word_obj.next_review_at = next_review_at
        word_list.append(word_obj)

    # Обновляем words.items
    words.items = word_list

    # Предзагружаем book ассоциации для текущей страницы одним запросом
    # чтобы избежать N+1 при обращении к word.books в шаблоне.
    # Используем set_committed_value, чтобы пометить атрибут как уже загруженный
    # и не дать SQLAlchemy запустить lazy-load при обращении из шаблона.
    if word_list:
        from sqlalchemy.orm import attributes as _sa_attrs

        from app.books.models import Book
        from app.words.models import word_book_link as _wbl
        _page_word_ids = [w.id for w in word_list]
        _book_rows = db.session.query(Book, _wbl.c.word_id).join(
            _wbl, Book.id == _wbl.c.book_id
        ).filter(
            _wbl.c.word_id.in_(_page_word_ids),
            Book.is_published == True,
        ).all()
        _word_books: dict[int, list] = {}
        for _book, _wid in _book_rows:
            _word_books.setdefault(_wid, []).append(_book)
        for _word in word_list:
            _sa_attrs.set_committed_value(_word, 'books', _word_books.get(_word.id, []))

    # Получаем статистику по статусам — один GROUP BY запрос вместо N отдельных COUNT
    status_counts = {}
    if current_user.is_authenticated:
        _base_filters = [
            UserWord.user_id == current_user.id,
            CollectionWords.english_word.isnot(None),
            func.trim(CollectionWords.english_word) != '',
            CollectionWords.level.in_(PUBLIC_CEFR_CODES),
        ]
        status_rows = db.session.query(
            UserWord.status,
            func.count(UserWord.id).label('cnt'),
        ).join(
            CollectionWords, CollectionWords.id == UserWord.word_id
        ).filter(*_base_filters).group_by(UserWord.status).all()
        _sc = {row.status: row.cnt for row in status_rows}

        mastered_count = db.session.query(func.count()).select_from(mastered_subquery).scalar() or 0
        review_total = _sc.get('review', 0)
        status_counts = {
            'new': _sc.get('new', 0),
            'learning': _sc.get('learning', 0),
            'mastered': mastered_count,
            'review': max(0, review_total - mastered_count),
        }
        status_counts['mine'] = (
            status_counts['new']
            + status_counts['learning']
            + status_counts['review']
            + status_counts['mastered']
        )

    # Получаем количество по типам — один GROUP BY запрос вместо трёх COUNT
    _base_type_filters = [
        CollectionWords.english_word.isnot(None),
        func.trim(CollectionWords.english_word) != '',
        CollectionWords.level.in_(PUBLIC_CEFR_CODES),
    ]
    type_rows = db.session.query(
        CollectionWords.item_type,
        func.count(CollectionWords.id).label('cnt'),
    ).filter(*_base_type_filters).group_by(CollectionWords.item_type).all()
    _tc = {row.item_type: row.cnt for row in type_rows}
    type_counts = {
        'word': _tc.get('word', 0),
        'phrasal_verb': _tc.get('phrasal_verb', 0),
        'all': sum(_tc.values()),
    }

    return render_template(
        'words/list_optimized.html',
        words=words,
        search_form=search_form,
        filter_form=filter_form,
        status_counts=status_counts,
        item_type=item_type,
        type_counts=type_counts,
        selected_level=selected_level,
        sort=sort,
        levels=PUBLIC_CEFR_CODES,
    )


@words.route('/words/<int:word_id>')
@login_required
@module_required('words')
def word_detail(word_id):
    from app.books.models import Book
    from app.study.models import UserWord
    from app.words.models import word_book_link

    word = CollectionWords.query.get_or_404(word_id)

    # Получаем статус пользователя для этого слова
    user_word = UserWord.query.filter_by(
        user_id=current_user.id,
        word_id=word_id
    ).first()

    # Status и is_mastered для шаблона
    # Note: 'mastered' больше не статус, а порог внутри 'review'
    if user_word:
        word.user_status = user_word.status
        word.is_mastered = user_word.is_mastered
    else:
        word.user_status = 'new'
        word.is_mastered = False

    books = (
        db.session.query(Book, word_book_link.c.frequency)
        .join(word_book_link, Book.id == word_book_link.c.book_id)
        .filter(word_book_link.c.word_id == word.id)
        .order_by(word_book_link.c.frequency.desc(), Book.title.asc())
        .all()
    )

    try:
        word_profile = build_word_profile(word)
    except Exception:
        logger.exception('build_word_profile failed for word_id=%s', word_id)
        word_profile = {
            'synonyms': [], 'antonyms': [], 'usage_context': '', 'etymology': '',
            'frequency_band_label': 'Не указана', 'item_type_label': '',
            'audio_available': False, 'facts': [], 'admin_facts': [],
            'study_facts': [], 'public_facts': [],
            'base_word': None, 'phrasal_verbs': [], 'common_mistake': None,
        }
    study_summary = build_word_study_summary(user_word)
    try:
        related_words = get_related_words(word, limit=6)
    except Exception:
        logger.exception('get_related_words failed for word_id=%s', word_id)
        related_words = []

    return render_template(
        'words/details_optimized.html',
        word=word,
        word_profile=word_profile,
        word_profile_public=False,
        study_summary=study_summary,
        books=books,
        related_words=related_words
    )


# Dummy CSRF form for protection
class DummyCSRFForm(FlaskForm):
    pass


@words.route('/update-word-status/<int:word_id>/<int:status>', methods=['POST'])
@login_required
def update_word_status(word_id, status):
    form = DummyCSRFForm(request.form)
    if not form.validate_on_submit():
        from flask import abort
        abort(400, description="CSRF token missing or invalid.")

    word = CollectionWords.query.get_or_404(word_id)

    # Используем обновленный метод set_word_status из модели User
    # Этот метод должен быть обновлен для работы с новыми моделями
    current_user.set_word_status(word_id, status)

    flash(f'Status for word \"{word.english_word}\" updated successfully.', 'success')

    # Перенаправляем обратно на страницу, с которой пришел запрос (с проверкой безопасности)
    from app.auth.routes import get_safe_redirect_url
    next_page = get_safe_redirect_url(
        request.args.get('next') or request.referrer,
        fallback='words.word_list'
    )
    return redirect(next_page)


@words.route('/phrasal-verbs')
@login_required
@module_required('words')
def phrasal_verb_list():
    """Редирект на единую страницу слов с фильтром по фразовым глаголам"""
    # Сохраняем параметры поиска при редиректе
    args = request.args.to_dict()
    args['type'] = 'phrasal_verb'
    return redirect(url_for('words.word_list', **args))


@words.route('/api/daily-plan/next-step')
@login_required
def daily_plan_next_step() -> tuple:
    """Return the next incomplete step from today's daily plan."""
    from app.daily_plan.service import get_daily_plan_unified
    from app.telegram.queries import get_daily_summary

    tz = current_user.timezone or DEFAULT_TIMEZONE
    daily_plan = get_daily_plan_unified(current_user.id, tz=tz)
    daily_summary = get_daily_summary(current_user.id, tz=tz)

    if daily_plan.get('mode') == 'unified':
        return _next_step_from_unified(daily_plan, daily_summary)

    return _next_step_from_legacy(daily_plan, daily_summary)


def _next_step_from_unified(plan: dict, daily_summary: dict) -> tuple:
    """Return next incomplete step from the unified daily plan.

    Iterates required then optional in order; the first item whose id is not
    marked done by plan_completion or item.completed is returned as the next
    step.  When everything is done returns has_next=False with fallback_url so
    the frontend can redirect to the dashboard.
    """
    from app.achievements.streak_service import compute_plan_steps

    plan_completion, _, steps_done, steps_total = compute_plan_steps(plan, daily_summary)

    KIND_ICONS: dict[str, str] = {
        'curriculum': '\U0001f3af',
        'srs': '\U0001f4d6',
        'reading': '\U0001f4d5',
        'listening': '\U0001f3a7',
        'speaking': '\U0001f399',
        'writing': '\u270d',
        'error_review': '\U0001f50d',
        'challenge': '\U0001f3c6',
        'grammar_review': '\U0001f9e0',
    }

    required = plan.get('required') or []
    optional = plan.get('optional') or []

    def _is_done(item: dict) -> bool:
        item_id = item.get('id', '')
        return (
            plan_completion.get(item_id, False)
            or bool(item.get('completed', False))
            or bool(item.get('skipped', False))
        )

    next_item = next(
        (
            item for item in (required + optional)
            if not _is_done(item)
            and not item.get('blocked', False)
            and item.get('url')
        ),
        None,
    )

    if next_item is None:
        # Graduated users always get a free-study CTA instead of a dead end.
        graduated = bool(
            plan.get('graduated', False)
            or (plan.get('_plan_meta') or {}).get('graduated', False)
        )
        if graduated:
            return jsonify({
                'has_next': True,
                'step_type': 'free_study',
                'step_title': 'Свободная практика',
                'step_url': '/study?source=infinite_practice',
                'step_icon': KIND_ICONS.get('srs', '\U0001f4d6'),
                'steps_done': steps_done,
                'steps_total': steps_total,
            }), 200
        return jsonify({
            'has_next': False,
            'all_done': True,
            'steps_done': steps_done,
            'steps_total': steps_total,
            'fallback_url': url_for('words.dashboard'),
            'continue_study_url': '/study?source=free_practice',
        }), 200

    kind = next_item.get('kind', '')
    return jsonify({
        'has_next': True,
        'step_type': kind,
        'step_title': next_item.get('title') or 'Следующий шаг',
        'step_url': next_item['url'],
        'step_icon': KIND_ICONS.get(kind, '\U0001f4cc'),
        'steps_done': steps_done,
        'steps_total': steps_total,
    }), 200


def _next_step_from_legacy(daily_plan: dict, daily_summary: dict) -> tuple:
    """No-op shim: mission and linear modes have been removed.

    The dispatcher only reaches this branch for unrecognised plan modes.
    Return all_done so the frontend always gets a valid response shape.
    """
    return jsonify({
        'has_next': False,
        'all_done': True,
        'steps_done': 0,
        'steps_total': 0,
        'fallback_url': url_for('words.dashboard'),
    }), 200


@words.route('/api/weekly-report/dismiss', methods=['POST'])
@login_required
def weekly_report_dismiss():
    """Mark the current week's Monday report card as dismissed (session-only)."""
    data = request.get_json(silent=True) or {}
    dismiss_key = data.get('dismiss_key', '')
    if dismiss_key and dismiss_key.startswith('weekly_report_dismissed_'):
        session[dismiss_key] = True
    return jsonify({'ok': True})


@words.route('/api/streak/repair-web', methods=['POST'])
@login_required
def streak_repair_web():
    """Session-based streak repair for web dashboard."""
    from app.achievements.streak_service import apply_paid_repair, find_missed_date
    from app.telegram.queries import get_current_streak

    tz = request.json.get('tz', DEFAULT_TIMEZONE) if request.is_json else DEFAULT_TIMEZONE

    missed = find_missed_date(current_user.id, tz=tz)
    if not missed:
        return jsonify({'success': False, 'error': 'no_missed_date'}), 400

    result = apply_paid_repair(current_user.id, missed)
    if result['success']:
        db.session.commit()
        result['new_streak'] = get_current_streak(current_user.id, tz=tz)
    else:
        db.session.rollback()

    return jsonify(result)
