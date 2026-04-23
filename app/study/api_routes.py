import logging
import random
from datetime import datetime, timezone, timedelta

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from app.study.blueprint import study, get_audio_url_for_word
from app.study.deck_utils import get_daily_plan_mix_word_ids
from app.study.models import QuizDeck, StudySession, StudySettings, UserCardDirection, UserWord
from app.utils.db import db
from app.words.models import CollectionWords
from app.study.services import DeckService, SRSService
from app.srs.stats_service import srs_stats_service
from app.api.errors import api_error

logger = logging.getLogger(__name__)


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

    if deck_id and deck:
        new_cards_today, reviews_today = SRSService.get_deck_stats_today(current_user.id, deck_id)
        new_cards_limit = deck.get_new_words_limit(settings)
        reviews_limit = deck.get_reviews_limit(settings)
    else:
        from app.srs.counting import (
            count_new_cards_today,
            count_reviews_today,
            get_new_card_budget,
        )

        new_cards_today = count_new_cards_today(current_user.id, db)
        reviews_today = count_reviews_today(current_user.id, db)

        if is_linear_plan_srs:
            from app.daily_plan.linear.slots.srs_slot import count_linear_plan_srs_due_cards

            new_cards_limit = new_cards_today
            reviews_limit = reviews_today + count_linear_plan_srs_due_cards(current_user.id, db)
        else:
            remaining_new, remaining_reviews = get_new_card_budget(current_user.id, db)
            new_cards_limit = new_cards_today + remaining_new
            reviews_limit = reviews_today + remaining_reviews

    new_cards_limit_reached = new_cards_today >= new_cards_limit
    reviews_limit_reached = reviews_today >= reviews_limit

    # Daily plan sessions own their own budget via the phase assembler, so
    # never terminate a plan session mid-way with the daily_limit_reached
    # banner — let the flow return empty items when done and the frontend
    # renders "session complete" instead of the scary limit message.
    is_daily_plan_session = word_source == 'daily_plan_mix'

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
                'reviews_limit': reviews_limit
            },
            'items': []
        })

    result_items = []

    if is_linear_plan_srs:
        new_limit = 0
        review_limit = max(0, reviews_limit - reviews_today)
    elif extra_study:
        new_limit = 5
        review_limit = 10
    else:
        new_limit = max(0, new_cards_limit - new_cards_today)
        review_limit = max(0, reviews_limit - reviews_today)

    remaining_new = new_limit
    remaining_reviews = review_limit

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
                'leech_hint': leech_hint
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
                'leech_hint': leech_hint
            }

    learning_grace_period = timedelta(minutes=15)
    end_of_today = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    def base_due_query(include_learning_grace=False, include_today=False):
        if include_today:
            due_filter = UserCardDirection.next_review <= end_of_today
        elif include_learning_grace:
            due_filter = UserCardDirection.next_review <= (now + learning_grace_period)
        else:
            due_filter = UserCardDirection.next_review <= now

        query = UserCardDirection.query \
            .join(UserWord, UserCardDirection.user_word_id == UserWord.id) \
            .options(
                joinedload(UserCardDirection.user_word).joinedload(UserWord.word)
            ) \
            .filter(
                UserWord.user_id == current_user.id,
                UserWord.status.in_(['new', 'learning', 'review']),
                due_filter,
                or_(
                    UserCardDirection.buried_until.is_(None),
                    UserCardDirection.buried_until <= now
                )
            )
        if deck_word_ids is not None:
            query = query.filter(UserWord.word_id.in_(deck_word_ids))
        if exclude_card_ids:
            query = query.filter(~UserCardDirection.id.in_(exclude_card_ids))
        return query

    # PRIORITY 1: RELEARNING cards
    if remaining_reviews > 0:
        relearning_cards = base_due_query(include_learning_grace=not is_linear_plan_srs).filter(
            UserCardDirection.state == CardState.RELEARNING.value
        ).order_by(
            UserCardDirection.next_review
        ).limit(remaining_reviews).all()

        for direction in relearning_cards:
            word = direction.user_word.word
            if word and word.russian_word:
                result_items.append(format_card(direction, word, 'relearning'))
        remaining_reviews -= len(relearning_cards)

    # PRIORITY 2: LEARNING cards
    if remaining_reviews > 0:
        learning_cards = base_due_query(include_learning_grace=not is_linear_plan_srs).filter(
            UserCardDirection.state == CardState.LEARNING.value
        ).order_by(
            UserCardDirection.next_review
        ).limit(remaining_reviews).all()

        for direction in learning_cards:
            word = direction.user_word.word
            if word and word.russian_word:
                result_items.append(format_card(direction, word, 'learning'))
        remaining_reviews -= len(learning_cards)

    # PRIORITY 2.5: NEW state cards (already have UserWord entries)
    if remaining_new > 0:
        new_state_query = UserCardDirection.query \
            .join(UserWord, UserCardDirection.user_word_id == UserWord.id) \
            .options(
                joinedload(UserCardDirection.user_word).joinedload(UserWord.word)
            ) \
            .filter(
                UserWord.user_id == current_user.id,
                UserWord.status.in_(['new', 'learning', 'review']),
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

    # PRIORITY 3: REVIEW cards (due today)
    if remaining_reviews > 0:
        review_cards = base_due_query(include_today=not is_linear_plan_srs).filter(
            or_(
                UserCardDirection.state == CardState.REVIEW.value,
                UserCardDirection.state.is_(None)
            )
        ).order_by(
            UserCardDirection.next_review
        ).limit(remaining_reviews).all()

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
            'has_more_reviews': has_more_reviews
        },
        'items': result_items
    })


@study.route('/api/update-study-item', methods=['POST'])
@login_required
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
    is_new = data.get('is_new', False)
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

        today_start = datetime.now(timezone.utc).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)

        if deck_id:
            deck = QuizDeck.query.get(deck_id)
            if deck and (deck.user_id == current_user.id or deck.is_public):
                new_cards_today, _ = SRSService.get_deck_stats_today(current_user.id, deck_id)
                new_cards_limit = deck.get_new_words_limit(settings)
            else:
                new_cards_today = db.session.query(func.count(UserCardDirection.id)).filter(
                    UserCardDirection.user_word_id.in_(
                        db.session.query(UserWord.id).filter_by(user_id=current_user.id)
                    ),
                    UserCardDirection.first_reviewed >= today_start,
                    UserCardDirection.first_reviewed.isnot(None)
                ).scalar() or 0
                new_cards_limit = settings.new_words_per_day
        else:
            new_cards_today = db.session.query(func.count(UserCardDirection.id)).filter(
                UserCardDirection.user_word_id.in_(
                    db.session.query(UserWord.id).filter_by(user_id=current_user.id)
                ),
                UserCardDirection.first_reviewed >= today_start,
                UserCardDirection.first_reviewed.isnot(None)
            ).scalar() or 0
            new_cards_limit = settings.new_words_per_day

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

    from app.srs.service import UnifiedSRSService
    from app.srs.constants import MAX_SESSION_ATTEMPTS, LEARNING_STEPS, RELEARNING_STEPS

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
    from app.study.xp_service import XPService

    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 415
    data = request.json or {}
    session_id = data.get('session_id')

    session = StudySession.query.get(session_id)
    if session and session.user_id == current_user.id:
        session.complete_session()
        db.session.commit()

        logger.info(
            'study_session_complete user=%s session=%s session_type=%s duration=%s words_studied=%s',
            current_user.id, session.id, session.session_type, session.duration, session.words_studied
        )

        xp_breakdown = XPService.calculate_flashcard_xp(
            cards_reviewed=session.words_studied or 0,
            correct_answers=session.correct_answers or 0
        )
        user_xp = XPService.award_xp(current_user.id, xp_breakdown['total_xp'])

        try:
            from app.daily_plan.linear.xp import (
                maybe_award_srs_global_xp,
                maybe_award_linear_perfect_day,
            )
            if maybe_award_srs_global_xp(current_user.id, db_session=db) is not None:
                maybe_award_linear_perfect_day(current_user.id, db_session=db)
                db.session.commit()
        except Exception:
            logger.warning(
                "linear_xp: srs-session award failed user=%s",
                current_user.id, exc_info=True,
            )
            db.session.rollback()

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
            'xp_earned': xp_breakdown['total_xp'],
            'total_xp': user_xp.total_xp,
            'level': user_xp.level,
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
    from app.study.models import UserXP, UserAchievement, Achievement

    celebrations = []

    user_xp = UserXP.query.filter_by(user_id=current_user.id).first()
    current_level = user_xp.level if user_xp else 1
    current_total_xp = user_xp.total_xp if user_xp else 0

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
