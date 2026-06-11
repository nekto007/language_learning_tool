import logging
import random
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from app import limiter
from app.api.errors import api_error
from app.srs.stats_service import srs_stats_service
from app.study.blueprint import get_audio_url_for_word, study
from app.study.deck_utils import get_daily_plan_mix_word_ids
from app.study.models import QuizDeck, StudySession, StudySettings, UserCardDirection, UserWord
from app.study.services import DeckService, SRSService
from app.utils.db import db
from app.utils.rate_limit_helpers import get_authenticated_user_key
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)

# Inlined flashcard XP helper (formerly XPService.calculate_flashcard_xp)
_XP_PER_CARD_REVIEWED = 5
_XP_FLASHCARD_SESSION = 15


def _calculate_flashcard_xp(cards_reviewed, correct_answers):
    """Flashcard session XP: 5 XP per card + 15 XP completion bonus (only if any cards studied)."""
    base_xp = cards_reviewed * _XP_PER_CARD_REVIEWED
    completion_bonus = _XP_FLASHCARD_SESSION if cards_reviewed > 0 else 0
    return {
        'base_xp': base_xp,
        'completion_bonus': completion_bonus,
        'total_xp': base_xp + completion_bonus,
    }


def _count_leech_suspended(user_id: int, now: datetime) -> int:
    """Count distinct words currently buried because they crossed the leech threshold.

    Counts distinct user_word_id rather than UserCardDirection rows so a word
    leeched in both directions surfaces as a single suspended card in the UI.
    """
    from sqlalchemy import distinct

    from app.srs.constants import LEECH_THRESHOLD

    return (
        db.session.query(func.count(distinct(UserCardDirection.user_word_id)))
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            UserWord.user_id == user_id,
            UserCardDirection.lapses >= LEECH_THRESHOLD,
            UserCardDirection.buried_until.isnot(None),
            UserCardDirection.buried_until > now,
        )
        .scalar() or 0
    )


def _is_linear_plan_srs_completion(data: dict) -> bool:
    """Return whether a complete-session request belongs to the linear SRS slot."""
    if (
        data.get('source') == 'linear_plan'
        and data.get('from') == 'linear_plan'
        and data.get('slot') == 'srs'
    ):
        return True

    ref = request.headers.get('Referer') or ''
    if not ref:
        return False
    try:
        query = parse_qs(urlsplit(ref).query or '')
    except ValueError:
        return False
    return (
        (query.get('source', [''])[0] or '') == 'linear_plan'
        and (query.get('from', [''])[0] or '') == 'linear_plan'
        and (query.get('slot', [''])[0] or '') == 'srs'
    )


@study.route('/api/get-study-items', methods=['GET'])
@login_required
def get_study_items():
    from app.srs.constants import CardState

    word_source = request.args.get('source', 'auto')
    deck_id = request.args.get('deck_id', type=int)
    extra_study = request.args.get('extra_study', 'false').lower() == 'true'
    is_linear_plan_srs = (
        word_source == 'linear_plan'
        and request.args.get('from') == 'linear_plan'
        and request.args.get('slot') == 'srs'
    )

    exclude_ids_str = request.args.get('exclude_card_ids', '')
    exclude_card_ids = []
    if exclude_ids_str:
        try:
            exclude_card_ids = [int(x) for x in exclude_ids_str.split(',') if x.strip()]
        except ValueError:
            pass

    settings = StudySettings.get_settings(current_user.id)

    today_start = datetime.now(timezone.utc).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    deck_word_ids = None
    deck = None
    if deck_id:
        deck = QuizDeck.query.get(deck_id)
        if deck and (deck.user_id == current_user.id or deck.is_public):
            deck_word_ids = [dw.word_id for dw in deck.words.all() if dw.word_id]
        else:
            return api_error('deck_not_found', 'Deck not found or access denied', 404)
    elif word_source == 'daily_plan_mix':
        deck_word_ids = get_daily_plan_mix_word_ids(current_user.id)
    elif word_source == 'word_detail':
        word_id_param = request.args.get('word_id', type=int)
        if not word_id_param:
            return api_error('invalid_input', 'word_id is required for word_detail study', 400)
        deck_word_ids = [word_id_param]
    elif word_source == 'custom_list':
        list_id_param = request.args.get('list_id', type=int)
        if list_id_param:
            from app.study.models import CustomWordList
            custom_list = CustomWordList.query.get(list_id_param)
            if custom_list and custom_list.user_id == current_user.id:
                entry_words = [e.word.lower() for e in custom_list.entries.all()]
                if entry_words:
                    matched = CollectionWords.query.filter(
                        func.lower(CollectionWords.english_word).in_(entry_words)
                    ).all()
                    deck_word_ids = [w.id for w in matched]
                else:
                    deck_word_ids = []

    if deck_id and deck:
        new_cards_today, reviews_today = SRSService.get_deck_stats_today(current_user.id, deck_id)
        new_cards_limit = deck.get_new_words_limit(settings)
        reviews_limit = deck.get_reviews_limit(settings)
    else:
        from app.srs.counting import (
            count_new_cards_today,
            count_reviews_today,
        )

        new_cards_today = count_new_cards_today(current_user.id, db)
        reviews_today = count_reviews_today(current_user.id, db)

        # Linear-plan SRS slot uses the same adaptive budget as free study.
        # Previously it forced new_limit=0 (no new cards) and inflated
        # reviews_limit by the linear due count — both bypassed user
        # preferences. Now the slot is a universal "daily review" pool:
        # NEW + LEARNING/RELEARNING + REVIEW within the user's caps.
        adaptive_new, adaptive_reviews = SRSService.get_adaptive_limits(current_user.id)
        new_cards_limit = adaptive_new
        reviews_limit = adaptive_reviews

    new_cards_limit_reached = new_cards_today >= new_cards_limit
    reviews_limit_reached = reviews_today >= reviews_limit

    # Daily plan sessions own their own budget via the phase assembler, so
    # never terminate a plan session mid-way with the daily_limit_reached
    # banner — let the flow return empty items when done and the frontend
    # renders "session complete" instead of the scary limit message.
    is_daily_plan_session = word_source == 'daily_plan_mix'

    leech_suspended_count = _count_leech_suspended(current_user.id, now)

    if (not extra_study
            and not is_linear_plan_srs
            and not is_daily_plan_session
            and new_cards_limit_reached
            and reviews_limit_reached):
        return jsonify({
            'status': 'daily_limit_reached',
            'message': 'Daily limits reached',
            'stats': {
                'new_cards_today': new_cards_today,
                'reviews_today': reviews_today,
                'new_cards_limit': new_cards_limit,
                'reviews_limit': reviews_limit,
                'leech_suspended_count': leech_suspended_count,
            },
            'items': []
        })

    result_items = []

    if extra_study:
        new_limit = 5
        review_limit = 10
    else:
        new_limit = max(0, new_cards_limit - new_cards_today)
        review_limit = max(0, reviews_limit - reviews_today)

    remaining_new = new_limit
    remaining_reviews = review_limit

    # Combined daily ceiling for due cards (RELEARNING + LEARNING + REVIEW),
    # using the BASE reviews_per_day (deck base for decks) rather than the
    # adaptive reduction — so the session is bounded but a struggling user is
    # never frozen out of recovery. Mirrors app/srs/counting.py::
    # get_due_card_budget so the plan tile count and this served queue agree.
    # extra_study explicitly bypasses the cap ("study beyond limits").
    if extra_study:
        due_budget = None
    elif deck_id and deck:
        due_budget = max(0, reviews_limit - reviews_today)
    else:
        due_budget = max(0, (settings.reviews_per_day or 0) - reviews_today)
    is_word_detail_study = word_source == 'word_detail' and deck_word_ids is not None

    def format_card(direction, word, state_type):
        audio_url = get_audio_url_for_word(word)
        state = direction.state or CardState.NEW.value
        is_new = state == CardState.NEW.value
        is_leech = direction.is_leech

        leech_hint = word.sentences if is_leech and word.sentences else None

        if direction.direction == 'eng-rus':
            return {
                'id': direction.id,
                'word_id': word.id,
                'direction': 'eng-rus',
                'word': word.english_word,
                'translation': word.russian_word,
                'examples': word.sentences,
                'audio_url': audio_url,
                'is_new': is_new,
                'state': state,
                'step_index': direction.step_index or 0,
                'lapses': direction.lapses or 0,
                'is_leech': is_leech,
                'leech_hint': leech_hint,
                'frequency_band': word.frequency_band,
                'source': direction.source,
            }
        else:
            return {
                'id': direction.id,
                'word_id': word.id,
                'direction': 'rus-eng',
                'word': word.russian_word,
                'translation': word.english_word,
                'examples': word.sentences,
                'audio_url': audio_url,
                'is_new': is_new,
                'state': state,
                'step_index': direction.step_index or 0,
                'lapses': direction.lapses or 0,
                'is_leech': is_leech,
                'leech_hint': leech_hint,
                'frequency_band': word.frequency_band,
                'source': direction.source,
            }

    learning_grace_period = timedelta(minutes=15)
    # «Конец сегодня» — по локальной полуночи юзера (тот же day-anchor, что
    # в scheduling/counting), а не по UTC-дню. Иначе для восточных таймзон
    # (UTC+3: завтрашняя карта = сегодня 21:00 UTC) «завтрашние» карточки
    # попадали в выдачу сегодня, расходясь со счётчиком count_due_cards.
    from app.utils.time_utils import day_to_naive_utc
    end_of_today = (
        day_to_naive_utc(current_user.id, db, days_ahead=1)
        - timedelta(microseconds=1)
    )

    def base_due_query(include_learning_grace=False, include_today=False):
        if is_word_detail_study and extra_study:
            due_filter = None
        elif include_today:
            due_filter = UserCardDirection.next_review <= end_of_today
        elif include_learning_grace:
            due_filter = UserCardDirection.next_review <= (now + learning_grace_period)
        else:
            due_filter = UserCardDirection.next_review <= now

        # UserCardDirection.state is authoritative; UserWord.status is a
        # derived UI label and may lag behind direction grades.
        filters = [
            UserWord.user_id == current_user.id,
            or_(
                UserCardDirection.buried_until.is_(None),
                UserCardDirection.buried_until <= now
            ),
        ]
        if due_filter is not None:
            filters.append(due_filter)

        query = UserCardDirection.query \
            .join(UserWord, UserCardDirection.user_word_id == UserWord.id) \
            .options(
                joinedload(UserCardDirection.user_word).joinedload(UserWord.word)
            ) \
            .filter(*filters)
        if deck_word_ids is not None:
            query = query.filter(UserWord.word_id.in_(deck_word_ids))
        if exclude_card_ids:
            query = query.filter(~UserCardDirection.id.in_(exclude_card_ids))
        return query

    # PRIORITY 1: RELEARNING cards — first claim on the combined due budget.
    # Bounded by `due_budget` (base reviews_per_day) so the session can't grow
    # unbounded; the plan tile (build_srs_item) applies the same cap, so the
    # count and this queue stay in sync. `due_budget is None` = extra-study
    # (uncapped). Cards over the cap aren't lost — they surface next day.
    relearning_query = base_due_query(include_learning_grace=not is_linear_plan_srs).filter(
        UserCardDirection.state == CardState.RELEARNING.value
    ).order_by(
        UserCardDirection.next_review
    )
    if due_budget is None:
        relearning_cards = relearning_query.all()
    elif due_budget > 0:
        relearning_cards = relearning_query.limit(due_budget).all()
    else:
        relearning_cards = []
    if due_budget is not None:
        due_budget -= len(relearning_cards)

    for direction in relearning_cards:
        word = direction.user_word.word
        if word and word.russian_word:
            result_items.append(format_card(direction, word, 'relearning'))

    # PRIORITY 2: LEARNING cards — share the same combined budget (after relearning).
    learning_query = base_due_query(include_learning_grace=not is_linear_plan_srs).filter(
        UserCardDirection.state == CardState.LEARNING.value
    ).order_by(
        UserCardDirection.next_review
    )
    if due_budget is None:
        learning_cards = learning_query.all()
    elif due_budget > 0:
        learning_cards = learning_query.limit(due_budget).all()
    else:
        learning_cards = []
    if due_budget is not None:
        due_budget -= len(learning_cards)

    for direction in learning_cards:
        word = direction.user_word.word
        if word and word.russian_word:
            result_items.append(format_card(direction, word, 'learning'))

    # PRIORITY 2.5: NEW state cards (already have UserWord entries)
    if remaining_new > 0:
        new_state_query = UserCardDirection.query \
            .join(UserWord, UserCardDirection.user_word_id == UserWord.id) \
            .options(
                joinedload(UserCardDirection.user_word).joinedload(UserWord.word)
            ) \
            .filter(
                UserWord.user_id == current_user.id,
                UserCardDirection.state == CardState.NEW.value,
                or_(
                    UserCardDirection.next_review.is_(None),
                    UserCardDirection.next_review <= end_of_today
                ),
                or_(
                    UserCardDirection.buried_until.is_(None),
                    UserCardDirection.buried_until <= now
                )
            )
        if deck_word_ids is not None:
            new_state_query = new_state_query.filter(UserWord.word_id.in_(deck_word_ids))
        if exclude_card_ids:
            new_state_query = new_state_query.filter(~UserCardDirection.id.in_(exclude_card_ids))

        new_state_cards = new_state_query.order_by(
            UserCardDirection.next_review.nullsfirst()
        ).limit(remaining_new).all()

        for direction in new_state_cards:
            word = direction.user_word.word
            if word and word.russian_word:
                result_items.append(format_card(direction, word, 'new'))
        remaining_new -= len(new_state_cards)

    # PRIORITY 3: REVIEW cards (due today) — fill whatever the combined budget
    # has left after learning/relearning, additionally capped by the adaptive
    # review limit (mature reviews are reduced when the user is struggling).
    review_cap = remaining_reviews if due_budget is None else min(due_budget, remaining_reviews)
    if review_cap > 0:
        review_cards = base_due_query(include_today=not is_linear_plan_srs).filter(
            or_(
                UserCardDirection.state == CardState.REVIEW.value,
                UserCardDirection.state.is_(None)
            )
        ).order_by(
            UserCardDirection.next_review
        ).limit(review_cap).all()

        for direction in review_cards:
            word = direction.user_word.word
            if word and word.russian_word:
                result_items.append(format_card(direction, word, 'review'))

    # PRIORITY 4: NEW cards (words without UserCardDirection records)
    if remaining_new > 0:
        words_to_fetch = (remaining_new + 1) // 2

        user_words_with_directions = db.session.query(UserWord.word_id).join(
            UserCardDirection, UserWord.id == UserCardDirection.user_word_id
        ).filter(
            UserWord.user_id == current_user.id
        ).scalar_subquery()

        new_words_query = db.session.query(CollectionWords).outerjoin(
            UserWord,
            (CollectionWords.id == UserWord.word_id) & (UserWord.user_id == current_user.id)
        ).filter(
            or_(
                UserWord.id.is_(None),
                ~CollectionWords.id.in_(user_words_with_directions)
            ),
            CollectionWords.russian_word.isnot(None),
            CollectionWords.russian_word != ''
        )

        if deck_word_ids is not None:
            new_words_query = new_words_query.filter(CollectionWords.id.in_(deck_word_ids))

        new_words = new_words_query.order_by(
            CollectionWords.frequency_rank.asc(),
            CollectionWords.level.asc(),
            func.random()
        ).limit(words_to_fetch).all()

        selected_base_ids = set()
        filtered_words = []
        for word in new_words:
            base = word.base_word_id
            if base and base in selected_base_ids:
                continue
            filtered_words.append(word)
            if base:
                selected_base_ids.add(base)
        new_words = filtered_words

        RUS_ENG_PROBABILITY = 0.7

        new_cards_added = 0
        for word in new_words:
            if new_cards_added >= remaining_new:
                break

            audio_url = get_audio_url_for_word(word)

            if random.random() < RUS_ENG_PROBABILITY:
                directions = [
                    ('rus-eng', word.russian_word, word.english_word),
                    ('eng-rus', word.english_word, word.russian_word)
                ]
            else:
                directions = [
                    ('eng-rus', word.english_word, word.russian_word),
                    ('rus-eng', word.russian_word, word.english_word)
                ]

            for dir_str, front, back in directions:
                if new_cards_added >= remaining_new:
                    break
                result_items.append({
                    'id': None,
                    'word_id': word.id,
                    'direction': dir_str,
                    'word': front,
                    'translation': back,
                    'examples': word.sentences,
                    'audio_url': audio_url,
                    'is_new': True,
                    'state': CardState.NEW.value,
                    'step_index': 0,
                    'lapses': 0
                })
                new_cards_added += 1

    has_more_new = False
    has_more_reviews = False

    if not extra_study and len(result_items) == 0:
        more_new_state = base_due_query(include_today=True).filter(
            UserCardDirection.state == CardState.NEW.value
        ).limit(1).first()

        more_new_words = db.session.query(CollectionWords).outerjoin(
            UserWord,
            (CollectionWords.id == UserWord.word_id) & (UserWord.user_id == current_user.id)
        ).filter(
            UserWord.id == None,
            CollectionWords.russian_word.isnot(None),
            CollectionWords.russian_word != ''
        )
        if deck_word_ids is not None:
            more_new_words = more_new_words.filter(CollectionWords.id.in_(deck_word_ids))
        more_new_words = more_new_words.limit(1).first()

        has_more_new = more_new_state is not None or more_new_words is not None

        more_reviews = base_due_query(include_today=True).filter(
            or_(
                UserCardDirection.state == CardState.REVIEW.value,
                UserCardDirection.state == CardState.LEARNING.value,
                UserCardDirection.state == CardState.RELEARNING.value,
                UserCardDirection.state.is_(None)
            )
        ).limit(1).first()
        has_more_reviews = more_reviews is not None

    return jsonify({
        'status': 'success',
        'stats': {
            'new_cards_today': new_cards_today,
            'reviews_today': reviews_today,
            'new_cards_limit': new_cards_limit,
            'reviews_limit': reviews_limit,
            'has_more_new': has_more_new,
            'has_more_reviews': has_more_reviews,
            'leech_suspended_count': leech_suspended_count,
        },
        'items': result_items
    })


@study.route('/api/update-study-item', methods=['POST'])
@login_required
@limiter.limit("120 per minute", key_func=get_authenticated_user_key)
def update_study_item():
    from app.srs.constants import CardState

    if not request.is_json:
        return jsonify({'success': False, 'error': 'Content-Type must be application/json'}), 415
    data = request.json or {}
    word_id = data.get('word_id')
    if not word_id:
        return jsonify({'success': False, 'error': 'word_id is required'}), 400
    direction_str = data.get('direction', 'eng-rus')
    try:
        quality = int(data.get('quality', 0))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Invalid quality value'}), 400
    session_id = data.get('session_id')
    data.get('is_new', False)
    deck_id = data.get('deck_id')

    extra_study = request.args.get('extra_study') == 'true' or data.get('extra_study', False)
    # lesson_mode bypasses new-card daily limits: once a lesson has started it must be completable
    lesson_mode = data.get('lesson_mode', False)

    user_word = UserWord.get_or_create(current_user.id, word_id)

    direction = UserCardDirection.query.filter_by(
        user_word_id=user_word.id,
        direction=direction_str
    ).first()

    is_first_review = (not direction) or (direction and direction.first_reviewed is None)

    if is_first_review and not extra_study and not lesson_mode:
        settings = StudySettings.query.filter_by(user_id=current_user.id).with_for_update().first()
        if not settings:
            settings = StudySettings(user_id=current_user.id)
            db.session.add(settings)
            db.session.flush()

        from app.srs.counting import count_new_cards_today

        if deck_id:
            deck = QuizDeck.query.get(deck_id)
            if deck and (deck.user_id == current_user.id or deck.is_public):
                new_cards_today, _ = SRSService.get_deck_stats_today(current_user.id, deck_id)
                new_cards_limit = deck.get_new_words_limit(settings)
            else:
                new_cards_today = count_new_cards_today(current_user.id, db)
                adaptive_new, _ = SRSService.get_adaptive_limits(current_user.id)
                new_cards_limit = adaptive_new
        else:
            new_cards_today = count_new_cards_today(current_user.id, db)
            adaptive_new, _ = SRSService.get_adaptive_limits(current_user.id)
            new_cards_limit = adaptive_new

        if new_cards_today >= new_cards_limit:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': 'daily_limit_exceeded',
                'message': 'Daily limit for new cards has been reached',
                'deck_id': deck_id
            }), 429

    if not direction:
        from app.srs.constants import CardState as CS
        direction = UserCardDirection(user_word_id=user_word.id, direction=direction_str)
        direction.state = CS.NEW.value
        direction.step_index = 0
        direction.lapses = 0
        db.session.add(direction)

    current_state = direction.state or CardState.NEW.value
    current_step = direction.step_index or 0

    interval = direction.update_after_review(quality)

    if session_id:
        session = StudySession.query.get(session_id)
        if session and session.user_id == current_user.id:
            session.words_studied += 1
            if quality >= 2:
                session.correct_answers += 1
            else:
                session.incorrect_answers += 1

    try:
        from app.achievements.streak_service import earn_daily_coin
        earn_daily_coin(current_user.id)
    except (SQLAlchemyError, ValueError, AttributeError) as e:
        logger.exception("Failed to award daily coin for user %s: %s", current_user.id, e)

    db.session.commit()

    # Card achievements — best-effort, fired after commit.
    try:
        from app.achievements.services import AchievementService, StatisticsService
        _stats = StatisticsService.get_or_create_statistics(current_user.id)
        AchievementService.check_card_achievements(current_user.id, _stats)
    except Exception:
        logger.exception("Card achievement check failed for user %s", current_user.id)

    from app.srs.constants import LEARNING_STEPS, MAX_SESSION_ATTEMPTS, RELEARNING_STEPS
    from app.srs.service import UnifiedSRSService

    if quality == 1:
        rating = 1
    elif quality == 2:
        rating = 2
    else:
        rating = 3

    requeue_position = UnifiedSRSService.get_requeue_position(
        rating=rating,
        state=current_state,
        step_index=current_step
    )

    requeue_minutes = None
    if direction.state in (CardState.LEARNING.value, CardState.RELEARNING.value):
        steps = LEARNING_STEPS if direction.state == CardState.LEARNING.value else RELEARNING_STEPS
        if direction.step_index < len(steps):
            requeue_minutes = steps[direction.step_index]

    if requeue_minutes is not None and requeue_minutes >= 60:
        requeue_position = None

    is_buried = False
    if direction.session_attempts >= MAX_SESSION_ATTEMPTS:
        direction.bury_for_session(session_duration_hours=4)
        requeue_position = None
        is_buried = True
        db.session.commit()

    return jsonify({
        'success': True,
        'card_id': direction.id,
        'interval': interval,
        'next_review': direction.next_review.strftime('%Y-%m-%d %H:%M') if direction.next_review else None,
        'requeue_position': requeue_position,
        'requeue_minutes': requeue_minutes,
        'session_attempts': direction.session_attempts or 1,
        'state': direction.state,
        'step_index': direction.step_index or 0,
        'lapses': direction.lapses or 0,
        'is_buried': is_buried
    })


@study.route('/api/complete-session', methods=['POST'])
@login_required
def complete_session():
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 415
    data = request.json or {}
    session_id = data.get('session_id')
    is_linear_plan_srs = _is_linear_plan_srs_completion(data)

    session = StudySession.query.get(session_id)
    if session and session.user_id == current_user.id:
        was_already_completed = session.end_time is not None
        session.complete_session()
        db.session.commit()

        logger.info(
            'study_session_complete user=%s session=%s session_type=%s duration=%s words_studied=%s',
            current_user.id, session.id, session.session_type, session.duration, session.words_studied
        )

        xp_breakdown = _calculate_flashcard_xp(
            cards_reviewed=session.words_studied or 0,
            correct_answers=session.correct_answers or 0,
        )
        from app.achievements.models import UserStatistics as _UserStats
        from app.achievements.xp_service import award_xp as _award_xp_unified
        from app.achievements.xp_service import get_level_info
        xp_award = None
        if xp_breakdown['total_xp'] > 0 and not was_already_completed:
            xp_award = _award_xp_unified(current_user.id, xp_breakdown['total_xp'], 'study_cards_session')
            db.session.commit()

        if is_linear_plan_srs:
            try:
                from app.daily_plan.linear.xp import (
                    maybe_award_linear_perfect_day,
                    maybe_award_srs_global_xp,
                )
                from app.srs.counting import (
                    count_due_by_states,
                    count_pending_new,
                    get_new_card_budget,
                )
                from app.srs.constants import CardState as _CS

                # Slot is "done" when no cards remain to surface today across
                # all three buckets (Раздел 5 universal pool model).
                remaining_new_budget, remaining_reviews = get_new_card_budget(
                    current_user.id, db,
                )
                new_remaining = min(
                    count_pending_new(current_user.id, db), remaining_new_budget,
                )
                learning_remaining = count_due_by_states(
                    current_user.id, db,
                    states=(_CS.LEARNING.value, _CS.RELEARNING.value),
                )
                review_remaining = min(
                    count_due_by_states(current_user.id, db, states=(_CS.REVIEW.value,)),
                    remaining_reviews,
                )
                total_remaining = new_remaining + learning_remaining + review_remaining
                if total_remaining <= 0:
                    if maybe_award_srs_global_xp(current_user.id, db_session=db) is not None:
                        maybe_award_linear_perfect_day(current_user.id, db_session=db)
                        db.session.commit()
                else:
                    logger.info(
                        "linear_xp: srs-session incomplete user=%s remaining=%s "
                        "(new=%d learning=%d review=%d)",
                        current_user.id, total_remaining,
                        new_remaining, learning_remaining, review_remaining,
                    )
            except Exception:
                logger.warning(
                    "linear_xp: srs-session award failed user=%s",
                    current_user.id, exc_info=True,
                )
                db.session.rollback()

        try:
            from app.achievements.services import AchievementService as _AchSvc
            _AchSvc.check_perfect_session_achievements(
                current_user.id,
                correct_answers=session.correct_answers or 0,
                total_answered=(session.correct_answers or 0) + (session.incorrect_answers or 0),
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.warning(
                'perfect_session: achievement check failed user=%s',
                current_user.id, exc_info=True,
            )

        _stats = _UserStats.query.filter_by(user_id=current_user.id).first()
        _total_xp = int(_stats.total_xp or 0) if _stats else 0
        _level = get_level_info(_total_xp).current_level

        from app.achievements.models import UserStatistics
        user_stats = UserStatistics.query.filter_by(user_id=current_user.id).first()
        current_streak = user_stats.current_streak_days if user_stats else 0

        return jsonify({
            'success': True,
            'stats': {
                'duration': session.duration,
                'words_studied': session.words_studied,
                'correct': session.correct_answers,
                'incorrect': session.incorrect_answers,
                'percentage': session.performance_percentage
            },
            'xp_earned': xp_award.xp_awarded if xp_award else 0,
            'total_xp': _total_xp,
            'level': _level,
            'streak': current_streak,
        })

    return jsonify({'success': False, 'message': 'Invalid session'})


@study.route('/api/srs-stats')
@login_required
def api_srs_stats():
    deck_id = request.args.get('deck_id', type=int)
    stats = srs_stats_service.get_words_stats(current_user.id, deck_id=deck_id)
    return jsonify(stats)


@study.route('/api/srs-overview')
@login_required
def api_srs_overview():
    overview = srs_stats_service.get_user_overview(current_user.id)
    return jsonify(overview)


@study.route('/api/search-words')
@login_required
def api_search_words():
    query = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 10)), 50)

    words = DeckService.search_words(query, limit)

    results = [{
        'id': w.id,
        'english': w.english_word,
        'russian': w.russian_word,
        'sentences': w.sentences if w.sentences else ''
    } for w in words]

    return jsonify(results)


@study.route('/api/celebrations')
@login_required
def check_celebrations():
    from app.achievements.models import UserStatistics
    from app.achievements.xp_service import get_level_info
    from app.study.models import Achievement, UserAchievement

    celebrations = []

    stats = UserStatistics.query.filter_by(user_id=current_user.id).first()
    current_total_xp = (stats.total_xp if stats else 0) or 0
    current_level = get_level_info(current_total_xp).current_level

    from dateutil.parser import isoparse
    after_param = request.args.get('after')
    if after_param:
        try:
            cutoff = isoparse(after_param).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)

    recent_achievements = (
        db.session.query(UserAchievement, Achievement)
        .join(Achievement, UserAchievement.achievement_id == Achievement.id)
        .filter(
            UserAchievement.user_id == current_user.id,
            UserAchievement.earned_at >= cutoff,
        )
        .all()
    )

    for ua, ach in recent_achievements:
        celebrations.append({
            'type': 'achievement',
            'title': ach.name,
            'description': ach.description or '',
            'icon': ach.icon,
            'xp': ach.xp_reward,
        })

    from app.achievements.models import StreakEvent
    recent_milestones = StreakEvent.query.filter(
        StreakEvent.user_id == current_user.id,
        StreakEvent.event_type == 'milestone',
        StreakEvent.created_at >= cutoff,
    ).all()

    for ms in recent_milestones:
        details = ms.details or {}
        celebrations.append({
            'type': 'streak_milestone',
            'title': f'Стрик {details.get("streak", 0)} дней!',
            'description': f'+{details.get("reward", 0)} монет',
            'icon': '🔥',
            'coins': details.get('reward', 0),
        })

    return jsonify({
        'success': True,
        'level': current_level,
        'total_xp': current_total_xp,
        'celebrations': celebrations,
    })


@study.route('/api/custom-lists/<int:list_id>/words', methods=['POST'])
@login_required
def add_word_to_custom_list(list_id: int):
    """Add a word to a custom list (idempotent). Used from vocabulary lesson AJAX."""
    from app.study.models import CustomWordList, CustomWordListEntry

    word_list = CustomWordList.query.get_or_404(list_id)
    if word_list.user_id != current_user.id:
        return api_error('forbidden', 'Access denied', 403)

    data = request.get_json(silent=True) or {}
    word = data.get('word', '').strip()
    translation = data.get('translation', '').strip()

    if not word or not translation:
        return api_error('invalid_input', 'word and translation are required', 400)

    if len(word) > 200 or len(translation) > 500:
        return api_error('invalid_input', 'word or translation too long', 400)

    existing = CustomWordListEntry.query.filter_by(list_id=list_id, word=word).first()
    if existing:
        return jsonify({'ok': True, 'entry_id': existing.id, 'word': word,
                        'translation': translation, 'already_existed': True})

    entry = CustomWordListEntry(list_id=list_id, word=word, translation=translation)
    db.session.add(entry)
    db.session.commit()
    return jsonify({'ok': True, 'entry_id': entry.id, 'word': word,
                    'translation': translation, 'already_existed': False})


@study.route('/api/difficult-words/complete', methods=['POST'])
@login_required
def api_difficult_words_complete():
    """Завершение контекстной проработки: снять leech-бан с угаданных слов."""
    from app.study.services.difficult_words_service import unbury_words

    data = request.get_json(silent=True) or {}
    raw_ids = data.get('correct_word_ids', [])
    if not isinstance(raw_ids, list):
        return api_error('invalid_input', 'correct_word_ids must be a list', 400)
    word_ids = [i for i in raw_ids if isinstance(i, int)][:100]

    try:
        unburied = unbury_words(current_user.id, word_ids)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception(
            "difficult-words complete failed for user %s", current_user.id
        )
        return api_error('internal_error', 'failed to update cards', 500)

    return jsonify({'success': True, 'unburied': unburied})
