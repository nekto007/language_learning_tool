import random
from datetime import datetime, timezone

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from app import csrf
from app.study.forms import StudySessionForm, StudySettingsForm
from app.study.models import GameScore, StudySession, StudySettings, UserCardDirection, UserWord
from app.utils.db import db
from app.words.forms import CollectionFilterForm
from app.words.models import Collection, CollectionWords, Topic
from app.modules.decorators import module_required

# Import service layer
from app.study.services import (
    DeckService, SRSService, SessionService,
    QuizService, GameService, StatsService, CollectionTopicService
)

study = Blueprint('study', __name__, template_folder='templates')

# Use DeckService methods directly
is_auto_deck = DeckService.is_auto_deck
sync_master_decks = DeckService.sync_master_decks


@study.route('/')
@login_required
@module_required('study')
def index():
    """Упрощенная панель изучения - коллекции и колоды с минимальными кликами"""
    from app.study.models import QuizDeck, QuizResult

    # Статистика по SRS словам
    due_items_count = UserCardDirection.query \
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id) \
        .filter(
        UserWord.user_id == current_user.id,
        UserCardDirection.next_review <= datetime.now(timezone.utc)
    ).count()

    total_items = UserWord.query.filter_by(
        user_id=current_user.id
    ).filter(
        UserWord.status != 'mastered'
    ).count()

    mastered_count = UserWord.query.filter_by(
        user_id=current_user.id,
        status='mastered'
    ).count()

    # Мои колоды
    my_decks = QuizDeck.query.filter_by(
        user_id=current_user.id
    ).order_by(QuizDeck.updated_at.desc()).all()

    # Предзагружаем все слова всех колод одним запросом
    deck_words_dict = {}
    user_words_dict = {}
    if my_decks:
        from app.study.models import QuizDeckWord

        deck_ids = [deck.id for deck in my_decks]
        deck_words = QuizDeckWord.query.filter(
            QuizDeckWord.deck_id.in_(deck_ids)
        ).all()

        # Группируем слова по deck_id
        for dw in deck_words:
            if dw.deck_id not in deck_words_dict:
                deck_words_dict[dw.deck_id] = []
            deck_words_dict[dw.deck_id].append(dw)

        # Собираем все уникальные word_id
        all_deck_word_ids = set([dw.word_id for dw in deck_words if dw.word_id])

        if all_deck_word_ids:
            user_words = UserWord.query.filter(
                UserWord.user_id == current_user.id,
                UserWord.word_id.in_(all_deck_word_ids)
            ).all()
            user_words_dict = {uw.word_id: uw for uw in user_words}

    # Предзагружаем review count одним запросом
    now = datetime.now(timezone.utc)
    review_counts = {}
    if user_words_dict:
        user_word_ids = [uw.id for uw in user_words_dict.values()]
        review_data = db.session.query(
            UserWord.word_id,
            func.count(UserCardDirection.id).label('review_count')
        ).join(
            UserCardDirection, UserCardDirection.user_word_id == UserWord.id
        ).filter(
            UserWord.id.in_(user_word_ids),
            UserCardDirection.next_review <= now
        ).group_by(UserWord.word_id).all()

        review_counts = {word_id: count for word_id, count in review_data}

    # Добавляем статистику для каждой колоды
    for deck in my_decks:
        # Получаем слова из предзагруженного словаря
        deck_words_list = deck_words_dict.get(deck.id, [])
        deck_word_ids = [dw.word_id for dw in deck_words_list if dw.word_id]

        if deck_word_ids:
            new_count = 0
            learning_count = 0
            mastered_count_deck = 0
            review_count = 0

            for word_id in deck_word_ids:
                if word_id in user_words_dict:
                    uw = user_words_dict[word_id]
                    if uw.status == 'learning':
                        learning_count += 1
                    elif uw.status == 'mastered':
                        mastered_count_deck += 1

                    # Подсчет слов к повторению
                    if word_id in review_counts:
                        review_count += review_counts[word_id]
                else:
                    new_count += 1

            deck.new_count = new_count
            deck.learning_count = learning_count
            deck.mastered_count = mastered_count_deck
            deck.review_count = review_count
        else:
            deck.new_count = 0
            deck.learning_count = 0
            deck.review_count = 0
            deck.mastered_count = 0

    # Публичные колоды - топ 12 по популярности
    public_decks = QuizDeck.query.filter(
        QuizDeck.is_public == True,
        QuizDeck.user_id != current_user.id
    ).order_by(QuizDeck.times_played.desc(), QuizDeck.created_at.desc()).limit(12).all()

    return render_template(
        'study/index.html',
        due_items_count=due_items_count,
        total_items=total_items,
        mastered_count=mastered_count,
        my_decks=my_decks,
        public_decks=public_decks
    )


@study.route('/settings', methods=['GET', 'POST'])
@login_required
@module_required('study')
def settings():
    """Study settings page"""
    # Get or create user settings
    user_settings = StudySettings.get_settings(current_user.id)

    form = StudySettingsForm(obj=user_settings)

    if form.validate_on_submit():
        form.populate_obj(user_settings)
        db.session.commit()
        flash(_('Your study settings have been updated!'), 'success')
        return redirect(url_for('study.index'))

    return render_template('study/settings.html', form=form)


# Маршрут /learn убран - используем отдельные страницы cards, quiz, matching


@study.route('/cards')
@login_required
@module_required('study')
def cards():
    """Anki-style flashcard study interface"""
    settings = StudySettings.get_settings(current_user.id)

    # Get card counts
    counts = SRSService.get_card_counts(current_user.id)

    # Create new study session
    session = SessionService.start_session(current_user.id, 'cards')

    return render_template(
        'study/cards.html',
        session_id=session.id,
        settings=settings,
        word_source='auto',
        nothing_to_study=counts['nothing_to_study'],
        limit_reached=counts['limit_reached'],
        daily_limit=counts['new_limit'],
        new_cards_today=counts['new_today']
    )


@study.route('/cards/deck/<int:deck_id>')
@login_required
@module_required('study')
def cards_deck(deck_id):
    """SRS cards from specific deck"""
    from app.study.models import QuizDeck

    deck = DeckService.get_deck_with_words(deck_id)
    if not deck:
        flash('Колода не найдена', 'danger')
        return redirect(url_for('study.index'))

    # Check if user has access (own deck or public)
    if not deck.is_public and deck.user_id != current_user.id:
        flash('У вас нет доступа к этой колоде', 'danger')
        return redirect(url_for('study.index'))

    # Check if deck has words
    if deck.word_count == 0:
        flash('В колоде нет слов', 'warning')
        return redirect(url_for('study.index'))

    # Mastered words don't need SRS review
    if deck.title == DeckService.MASTERED_DECK_TITLE:
        flash('Выученные слова не требуют повторения. Используйте режим квиза для практики.', 'info')
        return redirect(url_for('study.index'))

    # Get word IDs from deck
    deck_word_ids = [dw.word_id for dw in deck.words if dw.word_id]
    if not deck_word_ids:
        flash('В колоде нет слов для SRS повторения', 'info')
        return redirect(url_for('study.index'))

    # Get card counts for this deck
    settings = StudySettings.get_settings(current_user.id)
    counts = SRSService.get_card_counts(current_user.id, deck_word_ids)

    # Create new study session
    session = SessionService.start_session(current_user.id, 'cards')

    return render_template(
        'study/cards.html',
        session_id=session.id,
        settings=settings,
        word_source='deck',
        deck_id=deck_id,
        deck_title=deck.title,
        nothing_to_study=counts['nothing_to_study'],
        limit_reached=counts['limit_reached'],
        daily_limit=counts['new_limit'],
        new_cards_today=counts['new_today']
    )


@study.route('/quiz')
@login_required
@module_required('study')
def quiz():
    """Quiz deck selection page"""
    my_decks = DeckService.get_user_decks(current_user.id, include_public=False)

    # Get top public decks from other users
    from app.study.models import QuizDeck
    public_decks = QuizDeck.query.filter(
        QuizDeck.is_public == True,
        QuizDeck.user_id != current_user.id
    ).order_by(QuizDeck.times_played.desc()).limit(10).all()

    return render_template(
        'study/quiz_deck_select.html',
        my_decks=my_decks,
        public_decks=public_decks
    )


@study.route('/quiz/auto')
@login_required
@module_required('study')
def quiz_auto():
    """Automatic quiz (old behavior) - random questions from user's words"""
    settings = StudySettings.get_settings(current_user.id)
    word_limit = request.args.get('limit', type=int)
    session = SessionService.start_session(current_user.id, 'quiz')

    return render_template(
        'study/quiz.html',
        session_id=session.id,
        settings=settings,
        word_source='auto',
        deck_id=None,
        word_limit=word_limit
    )


@study.route('/quiz/deck/<int:deck_id>')
@login_required
@module_required('study')
def quiz_deck(deck_id):
    """Quiz from specific deck"""
    from app.study.models import QuizDeck

    deck = QuizDeck.query.get_or_404(deck_id)

    # Check if user has access (own deck or public)
    if not deck.is_public and deck.user_id != current_user.id:
        flash('У вас нет доступа к этой колоде', 'danger')
        return redirect(url_for('study.quiz'))

    # Check if deck has words
    if deck.word_count == 0:
        flash('В колоде нет слов', 'warning')
        return redirect(url_for('study.quiz'))

    settings = StudySettings.get_settings(current_user.id)
    word_limit = request.args.get('limit', type=int)

    # Create new study session
    session = SessionService.start_session(current_user.id, 'quiz')

    # Increment times played
    deck.times_played += 1
    db.session.commit()

    return render_template(
        'study/quiz.html',
        session_id=session.id,
        settings=settings,
        word_source='deck',
        deck_id=deck_id,
        deck_title=deck.title,
        word_limit=word_limit
    )


@study.route('/quiz/shared/<code>')
@login_required
@module_required('study')
def quiz_deck_shared(code):
    """Access quiz deck via share code"""
    from app.study.models import QuizDeck

    deck = QuizDeck.query.filter_by(share_code=code, is_public=True).first_or_404()

    # Redirect to regular deck quiz
    return redirect(url_for('study.quiz_deck', deck_id=deck.id))


@study.route('/start-session', methods=['POST'])
@login_required
def start_session():
    """Start a new study session"""
    form = StudySessionForm()

    if form.validate_on_submit():
        session_type = form.session_type.data
        word_source = form.word_source.data

        if session_type == 'cards':
            return redirect(url_for('study.cards', word_source=word_source))
        elif session_type == 'quiz':
            return redirect(url_for('study.quiz', word_source=word_source))
        else:
            return redirect(url_for('study.matching', word_source=word_source))
            # return redirect(url_for('study.index'))

    flash(_('Invalid form data.'), 'danger')
    return redirect(url_for('study.index'))


# API routes for AJAX calls from study interfaces

# Modified function that properly handles learning words
@study.route('/api/get-study-items', methods=['GET'])
@login_required
def get_study_items():
    """Get words for study - automatic selection with priorities or from specific deck"""
    from app.study.models import QuizDeck

    word_source = request.args.get('source', 'auto')
    deck_id = request.args.get('deck_id', type=int)
    extra_study = request.args.get('extra_study', 'false').lower() == 'true'

    # Get user settings
    settings = StudySettings.get_settings(current_user.id)

    # Count how many new cards and reviews were done today
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Get new cards reviewed today
    new_cards_today = db.session.query(func.count(UserCardDirection.id)).filter(
        UserCardDirection.user_word_id.in_(
            db.session.query(UserWord.id).filter_by(user_id=current_user.id)
        ),
        UserCardDirection.last_reviewed >= today_start,
        UserCardDirection.repetitions == 1  # First review
    ).scalar()

    # Get reviews done today
    reviews_today = db.session.query(func.count(UserCardDirection.id)).filter(
        UserCardDirection.user_word_id.in_(
            db.session.query(UserWord.id).filter_by(user_id=current_user.id)
        ),
        UserCardDirection.last_reviewed >= today_start,
        UserCardDirection.repetitions > 1  # Not first review
    ).scalar()

    # Check if limits reached
    new_cards_limit_reached = new_cards_today >= settings.new_words_per_day
    reviews_limit_reached = reviews_today >= settings.reviews_per_day

    # If both limits reached and not extra study, return empty list with status
    if not extra_study and new_cards_limit_reached and reviews_limit_reached:
        return jsonify({
            'status': 'daily_limit_reached',
            'message': 'Daily limits reached',
            'stats': {
                'new_cards_today': new_cards_today,
                'reviews_today': reviews_today,
                'new_cards_limit': settings.new_words_per_day,
                'reviews_limit': settings.reviews_per_day
            },
            'items': []
        })

    result_items = []

    # Get word IDs from deck if deck_id is provided
    deck_word_ids = None
    if deck_id:
        deck = QuizDeck.query.get(deck_id)
        if deck and (deck.user_id == current_user.id or deck.is_public):
            deck_word_ids = [dw.word_id for dw in deck.words.all() if dw.word_id]
        else:
            return jsonify({
                'status': 'error',
                'message': 'Deck not found or access denied',
                'items': []
            })

    # Determine limits based on what's already studied today
    if extra_study:
        new_limit = 5  # Fixed amount for extra study
        review_limit = 10
    else:
        new_limit = max(0, settings.new_words_per_day - new_cards_today)
        review_limit = max(0, settings.reviews_per_day - reviews_today)

    # PRIORITY 1: Get due review cards (excluding mastered)
    if review_limit > 0:
        review_query = UserCardDirection.query \
            .join(UserWord, UserCardDirection.user_word_id == UserWord.id) \
            .filter(
                UserWord.user_id == current_user.id,
                UserWord.status.in_(['learning', 'review']),  # EXCLUDE 'mastered'
                UserCardDirection.next_review <= datetime.now(timezone.utc)
            )

        # Filter by deck if deck_id provided
        if deck_word_ids is not None:
            review_query = review_query.filter(UserWord.word_id.in_(deck_word_ids))

        review_directions = review_query.order_by(
                UserCardDirection.next_review  # Most overdue first
            ).limit(review_limit).all()
        
        for direction in review_directions:
            user_word = UserWord.query.get(direction.user_word_id)
            word = user_word.word
            
            if not word or not word.russian_word:
                continue
            
            audio_url = None
            if hasattr(word, 'get_download') and word.get_download == 1 and word.listening:
                audio_url = url_for('static', filename=f'audio/{word.listening[7:-1]}')
            
            if direction.direction == 'eng-rus':
                result_items.append({
                    'id': direction.id,
                    'word_id': word.id,
                    'direction': 'eng-rus',
                    'word': word.english_word,
                    'translation': word.russian_word,
                    'examples': word.sentences,
                    'audio_url': audio_url,
                    'is_new': False
                })
            else:
                result_items.append({
                    'id': direction.id,
                    'word_id': word.id,
                    'direction': 'rus-eng',
                    'word': word.russian_word,
                    'translation': word.english_word,
                    'examples': word.sentences,
                    'audio_url': audio_url,
                    'is_new': False
                })

    # PRIORITY 2: Get new cards if needed
    if new_limit > 0:
        # Use efficient LEFT JOIN instead of NOT IN subquery
        # This avoids N+1 problem and performs better on large datasets
        new_words_query = db.session.query(CollectionWords).outerjoin(
            UserWord,
            (CollectionWords.id == UserWord.word_id) & (UserWord.user_id == current_user.id)
        ).filter(
            UserWord.id == None,  # Words not in user's collection
            CollectionWords.russian_word.isnot(None),
            CollectionWords.russian_word != ''
        )

        # Filter by deck if deck_id provided
        if deck_word_ids is not None:
            new_words_query = new_words_query.filter(CollectionWords.id.in_(deck_word_ids))

        new_words = new_words_query.order_by(
            CollectionWords.id.desc()  # Deterministic ordering (most recent first), indexed
        ).limit(new_limit).all()

        # Add new words to result
        for word in new_words:
            audio_url = None
            if hasattr(word, 'get_download') and word.get_download == 1 and word.listening:
                audio_url = url_for('static', filename=f'audio/{word.listening[7:-1]}')

            # Add both directions (eng-rus and rus-eng)
            # English to Russian
            result_items.append({
                'id': None,
                'word_id': word.id,
                'direction': 'eng-rus',
                'word': word.english_word,
                'translation': word.russian_word,
                'examples': word.sentences,
                'audio_url': audio_url,
                'is_new': True
            })

            # Russian to English
            result_items.append({
                'id': None,
                'word_id': word.id,
                'direction': 'rus-eng',
                'word': word.russian_word,
                'translation': word.english_word,
                'examples': word.sentences,
                'audio_url': audio_url,
                'is_new': True
            })

            # Only get up to the limit
            if len(result_items) >= new_limit * 2:  # x2 because we add both directions
                break

    # Return results with stats
    return jsonify({
        'status': 'success',
        'stats': {
            'new_cards_today': new_cards_today,
            'reviews_today': reviews_today,
            'new_cards_limit': settings.new_words_per_day,
            'reviews_limit': settings.reviews_per_day
        },
        'items': result_items
    })


@study.route('/api/update-study-item', methods=['POST'])
@login_required
def update_study_item():
    """Update study item after review with daily limit validation"""
    data = request.json
    word_id = data.get('word_id')
    direction_str = data.get('direction', 'eng-rus')  # Get direction from request
    quality = int(data.get('quality', 0))  # 0-5 rating
    session_id = data.get('session_id')
    is_new = data.get('is_new', False)  # Whether this is a new card

    # Get or create user word
    user_word = UserWord.get_or_create(current_user.id, word_id)

    # Get or create card direction
    direction = UserCardDirection.query.filter_by(
        user_word_id=user_word.id,
        direction=direction_str
    ).first()

    if not direction:
        # This is a new card - check daily limit to prevent race condition
        if is_new:
            # Use SELECT FOR UPDATE to lock the settings row and prevent race conditions
            settings = StudySettings.query.filter_by(user_id=current_user.id).with_for_update().first()
            if not settings:
                settings = StudySettings(user_id=current_user.id)
                db.session.add(settings)
                db.session.flush()

            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

            # Re-check new cards count with database lock to prevent race condition
            new_cards_today = db.session.query(func.count(UserCardDirection.id)).filter(
                UserCardDirection.user_word_id.in_(
                    db.session.query(UserWord.id).filter_by(user_id=current_user.id)
                ),
                UserCardDirection.last_reviewed >= today_start,
                UserCardDirection.repetitions == 1
            ).scalar() or 0

            # If limit would be exceeded, reject the update
            if new_cards_today >= settings.new_words_per_day:
                db.session.rollback()
                return jsonify({
                    'success': False,
                    'error': 'daily_limit_exceeded',
                    'message': 'Daily limit for new cards has been reached'
                }), 429  # 429 Too Many Requests

        # Create new direction if it doesn't exist
        direction = UserCardDirection(user_word_id=user_word.id, direction=direction_str)
        db.session.add(direction)

    # Update the direction with the review
    interval = direction.update_after_review(quality)

    # Update session statistics if provided
    if session_id:
        session = StudySession.query.get(session_id)
        if session and session.user_id == current_user.id:
            session.words_studied += 1
            if quality >= 3:
                session.correct_answers += 1
            else:
                session.incorrect_answers += 1

    db.session.commit()

    # Синхронизация мастер-колод при изменении статуса слова
    sync_master_decks(current_user.id)
    db.session.commit()

    return jsonify({
        'success': True,
        'interval': interval,
        'next_review': direction.next_review.strftime('%Y-%m-%d') if direction.next_review else None
    })


@study.route('/api/complete-session', methods=['POST'])
@login_required
def complete_session():
    """Mark a study session as complete and award XP"""
    from app.study.xp_service import XPService

    data = request.json
    session_id = data.get('session_id')

    session = StudySession.query.get(session_id)
    if session and session.user_id == current_user.id:
        session.complete_session()
        db.session.commit()

        # Calculate and award XP
        xp_breakdown = XPService.calculate_flashcard_xp(
            cards_reviewed=session.words_studied or 0,
            correct_answers=session.correct_answers or 0
        )
        user_xp = XPService.award_xp(current_user.id, xp_breakdown['total_xp'])

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
            'level': user_xp.level
        })

    return jsonify({'success': False, 'message': 'Invalid session'})


@study.route('/stats')
@login_required
@module_required('study')
def stats():
    """Study statistics page"""
    stats = StatsService.get_user_stats(current_user.id)

    return render_template(
        'study/stats.html',
        total_items=stats['total'],
        mastered_items=stats['mastered'],
        mastery_percentage=stats['mastery_percentage'],
        recent_sessions=stats['recent_sessions'],
        study_streak=stats['study_streak'],
        today_words_studied=stats['today_words_studied'],
        today_time_spent=stats['today_time_spent'],
        new_words=stats['new'],
        learning_words=stats['learning'],
        mastered_words=stats['mastered']
    )


@study.route('/leaderboard')
@login_required
def leaderboard():
    """Leaderboard showing top users by XP and achievements (cached for 5 minutes)"""
    from app.utils.cache import cache

    # Try to get leaderboard data from cache
    cache_key_xp = 'leaderboard_xp_top100'
    cache_key_ach = 'leaderboard_achievements_top100'

    top_xp_users = cache.get(cache_key_xp)
    if not top_xp_users:
        top_xp_users = StatsService.get_xp_leaderboard(limit=100)
        cache.set(cache_key_xp, top_xp_users, timeout=300)  # 5 minutes

    top_achievement_users = cache.get(cache_key_ach)
    if not top_achievement_users:
        top_achievement_users = StatsService.get_achievement_leaderboard(limit=100)
        cache.set(cache_key_ach, top_achievement_users, timeout=300)  # 5 minutes

    # Get current user's ranks
    current_user_xp_rank = StatsService.get_user_xp_rank(current_user.id)
    current_user_achievement_rank = StatsService.get_user_achievement_rank(current_user.id)

    return render_template(
        'study/leaderboard.html',
        top_xp_users=top_xp_users,
        top_achievement_users=top_achievement_users,
        current_user_xp_rank=current_user_xp_rank,
        current_user_achievement_rank=current_user_achievement_rank
    )


@study.route('/achievements')
@login_required
def achievements():
    """Achievements page showing all available and earned achievements"""
    data = StatsService.get_achievements_by_category(current_user.id)

    # Calculate total XP available (not just earned)
    from app.study.models import Achievement
    total_xp_available = sum(
        ach.xp_reward for ach in Achievement.query.all()
    )

    return render_template(
        'study/achievements.html',
        achievements_by_category=data['by_category'],
        total_achievements=data['total_achievements'],
        earned_count=data['earned_count'],
        total_xp_available=total_xp_available,
        earned_xp=data['total_xp_earned']
    )


@study.route('/matching')
@login_required
@module_required('study')
def matching():
    """Matching game study interface"""
    settings = StudySettings.get_settings(current_user.id)
    session = SessionService.start_session(current_user.id, 'matching')

    return render_template(
        'study/matching.html',
        session_id=session.id,
        settings=settings,
        word_source='auto'
    )


@study.route('/api/get-quiz-questions', methods=['GET'])
@login_required
def get_quiz_questions():
    """Get questions for quiz mode - supports both auto and deck mode"""
    from app.study.models import QuizDeck, QuizDeckWord

    question_count = min(int(request.args.get('count', 20)), 200)  # Limit max questions to 200
    deck_id = request.args.get('deck_id', type=int)

    words = []

    if deck_id:
        # DECK MODE: Get words from specific deck
        deck = QuizDeck.query.get_or_404(deck_id)

        # Check access
        if not deck.is_public and deck.user_id != current_user.id:
            return jsonify({
                'status': 'error',
                'message': 'Access denied',
                'questions': []
            }), 403

        # Get words from deck
        deck_words = deck.words.order_by(QuizDeckWord.order_index).all()

        if not deck_words:
            return jsonify({
                'status': 'error',
                'message': 'No words in deck',
                'questions': []
            })

        # Convert QuizDeckWord to CollectionWords format for question generation
        # We'll create a temporary object with same interface
        class DeckWordAdapter:
            def __init__(self, deck_word):
                self.id = deck_word.id
                self.english_word = deck_word.english_word
                self.russian_word = deck_word.russian_word
                self.get_download = 0  # Deck words don't have audio by default
                self.listening = None
                if deck_word.word_id and deck_word.word:
                    # If it's a reference to collection word, get audio
                    self.get_download = deck_word.word.get_download
                    self.listening = deck_word.word.listening

        words = [DeckWordAdapter(dw) for dw in deck_words]

        # Limit to question count (or use all words if less than count)
        if len(words) > question_count:
            import random
            words = random.sample(words, question_count)

    else:
        # AUTO MODE: Get words with same priority as cards
        # PRIORITY 1: Words in learning/review status (exclude mastered)
        learning_words = db.session.query(CollectionWords).join(
            UserWord,
            (CollectionWords.id == UserWord.word_id) &
            (UserWord.user_id == current_user.id)
        ).filter(
            UserWord.status.in_(['learning', 'review']),  # EXCLUDE 'mastered'
            CollectionWords.russian_word != None,
            CollectionWords.russian_word != ''
        ).order_by(func.random()).limit(question_count // 2).all()

        words.extend(learning_words)

        # PRIORITY 2: New words not yet in user's collection
        if len(words) < question_count:
            new_words = CollectionWords.query.filter(
                ~CollectionWords.id.in_(
                    db.session.query(UserWord.word_id)
                    .filter(UserWord.user_id == current_user.id)
                ),
                CollectionWords.russian_word != None,
                CollectionWords.russian_word != ''
            ).order_by(func.random()).limit(question_count - len(words)).all()

            words.extend(new_words)

    # Ensure we have words to create questions
    if not words:
        return jsonify({
            'status': 'error',
            'message': 'No words available for quiz',
            'questions': []
        })

    # Generate questions from the words
    questions = generate_quiz_questions(words, question_count)

    return jsonify({
        'status': 'success',
        'questions': questions
    })


def generate_quiz_questions(words, count):
    """
    Generate quiz questions from words

    Question types:
    - multiple_choice: Multiple choice questions
    - true_false: True/False questions
    - fill_blank: Fill in the blank
    """
    questions = []

    # Ensure we don't try to create more questions than words
    count = min(count, len(words) * 2)

    # Create a list of all the words for creating distractors (limit to avoid loading thousands)
    all_words = CollectionWords.query.filter(
        CollectionWords.russian_word != None,
        CollectionWords.russian_word != ''
    ).limit(500).all()

    # Create two questions per word (eng->rus and rus->eng)
    for word in words:
        if len(questions) >= count:
            break

        # Skip words without translations
        if not word.russian_word or word.russian_word.strip() == '':
            continue

        # Generate English to Russian question
        if len(questions) < count:
            question_type = random.choice(['multiple_choice', 'fill_blank'])

            if question_type == 'multiple_choice':
                # Create multiple choice question (eng->rus)
                question = create_multiple_choice_question(word, all_words, 'eng_to_rus')
                questions.append(question)

            elif question_type == 'fill_blank':
                # Create fill-in-the-blank question (eng->rus)
                question = create_fill_blank_question(word, 'eng_to_rus')
                questions.append(question)

        # Generate Russian to English question
        if len(questions) < count:
            question_type = random.choice(['multiple_choice', 'fill_blank'])

            if question_type == 'multiple_choice':
                # Create multiple choice question (rus->eng)
                question = create_multiple_choice_question(word, all_words, 'rus_to_eng')
                questions.append(question)

            elif question_type == 'fill_blank':
                # Create fill-in-the-blank question (rus->eng)
                question = create_fill_blank_question(word, 'rus_to_eng')
                questions.append(question)

    # Shuffle the questions
    random.shuffle(questions)

    # Limit to requested count
    return questions[:count]


def create_multiple_choice_question(word, all_words, direction):
    """Create a multiple choice question"""
    if direction == 'eng_to_rus':
        question_template = 'Переведите на русский:'
        question_text = word.english_word
        correct_answer = word.russian_word

        # Find distractors (other Russian words)
        distractors = []
        for distractor_word in random.sample(all_words, min(10, len(all_words))):
            if (distractor_word.id != word.id and
                    distractor_word.russian_word and
                    distractor_word.russian_word != correct_answer):
                distractors.append(distractor_word.russian_word)
                if len(distractors) >= 3:
                    break
    else:
        question_template = 'Переведите на английский:'
        question_text = word.russian_word
        correct_answer = word.english_word

        # Find distractors (other English words)
        distractors = []
        for distractor_word in random.sample(all_words, min(10, len(all_words))):
            if (distractor_word.id != word.id and
                    distractor_word.english_word and
                    distractor_word.english_word != correct_answer):
                distractors.append(distractor_word.english_word)
                if len(distractors) >= 3:
                    break

    # Ensure we have at least 3 distractors
    while len(distractors) < 3:
        if direction == 'eng_to_rus':
            distractors.append(f"[вариант {len(distractors) + 1}]")
        else:
            distractors.append(f"[option {len(distractors) + 1}]")

    # Create options and shuffle
    options = [correct_answer] + distractors[:3]  # Ensure exactly 4 options
    random.shuffle(options)

    # Audio for English word
    audio_url = None
    if direction == 'eng_to_rus' and word.get_download == 1 and word.listening:
        audio_url = url_for('static', filename=f'audio/{word.listening[7:-1]}')

    first_word = correct_answer.split(',')[0].strip()
    letter_form = "букв"

    hint = f"Начинается с: {first_word[0]}... ({len(first_word)} {letter_form})"

    return {
        'id': f'mc_{word.id}_{direction}',
        'word_id': word.id,
        'type': 'multiple_choice',
        'text': question_text,
        'question_label': question_template,
        'options': options,
        'answer': correct_answer,
        'hint': hint,
        'audio_url': audio_url,
        'direction': direction
    }


def create_true_false_question(word, all_words, direction):
    """Create a true/false question"""
    # Decide if question will be true or false
    is_true = random.choice([True, False])

    if direction == 'eng_to_rus':
        english_word = word.english_word

        if is_true:
            russian_word = word.russian_word
            answer = 'true'
        else:
            # Find a different Russian word
            other_words = [w for w in all_words if w.id != word.id and w.russian_word]
            if other_words:
                other_word = random.choice(other_words)
                russian_word = other_word.russian_word
            else:
                # If no other words available, make up a fake translation
                russian_word = word.russian_word + 'ский'
            answer = 'false'

        question_template = 'Это правильный перевод?'
        question_text = f"{english_word} = {russian_word}"
        hint_word = word.russian_word

    else:
        russian_word = word.russian_word

        if is_true:
            english_word = word.english_word
            answer = 'true'
        else:
            # Find a different English word
            other_words = [w for w in all_words if w.id != word.id and w.english_word]
            if other_words:
                other_word = random.choice(other_words)
                english_word = other_word.english_word
            else:
                # If no other words available, make up a fake translation
                english_word = 'un' + word.english_word
            answer = 'false'

        question_template = 'Это правильный перевод?'
        question_text = f"{russian_word} = {english_word}"
        hint_word = word.english_word

    # Audio for English word
    audio_url = None
    # if word.get_download == 1:
    #     audio_url = url_for('static', filename=f'audio/{word.listening[7:-1]}')

    # Create hint based on the actual correct translation, not "true"/"false"
    first_word = hint_word.split(',')[0].strip()
    letter_form = "букв"
    hint = f"Правильный ответ: {first_word[0]}{"_" * (len(first_word) - 1)} ({len(first_word)} {letter_form})"

    return {
        'id': f'tf_{word.id}_{direction}',
        'word_id': word.id,
        'type': 'true_false',
        'text': question_text,
        'question_label': question_template,
        'answer': answer,
        'hint': hint,
        'audio_url': audio_url
    }


def create_fill_blank_question(word, direction):
    """Create a fill-in-the-blank question"""
    if direction == 'eng_to_rus':
        question_template = 'Введите перевод на русский:'
        question_text = word.english_word
        answer = word.russian_word
    else:
        question_template = 'Введите перевод на английский:'
        question_text = word.russian_word
        answer = word.english_word

    # Get acceptable alternative answers
    acceptable_answers = [answer]

    # If the answer contains commas, each part is an acceptable answer
    if ',' in answer:
        alternative_answers = [a.strip() for a in answer.split(',')]
        acceptable_answers.extend(alternative_answers)

    # Audio for English word
    audio_url = None
    if direction == 'eng_to_rus' and word.get_download == 1 and word.listening:
        audio_url = url_for('static', filename=f'audio/{word.listening[7:-1]}')

    first_word = answer.split(',')[0].strip()
    letter_form = "букв"

    hint = f"Начинается с: {first_word[0]}... ({len(first_word)} {letter_form})"

    return {
        'id': f'fb_{word.id}_{direction}',
        'word_id': word.id,
        'type': 'fill_blank',
        'text': question_text,
        'question_label': question_template,
        'answer': answer,
        'acceptable_answers': acceptable_answers,
        'hint': hint,
        'audio_url': audio_url,
        'direction': direction
    }


@study.route('/api/submit-quiz-answer', methods=['POST'])
@login_required
def submit_quiz_answer():
    """Process a submitted quiz answer"""
    data = request.json
    session_id = data.get('session_id')
    word_id = data.get('word_id')
    direction = data.get('direction', 'eng_to_rus')  # Получаем направление из запроса
    is_correct = data.get('is_correct', False)

    # Преобразуем direction из формата квиза в формат для UserCardDirection
    direction_str = 'eng-rus' if direction.startswith('eng') else 'rus-eng'

    # Получаем или создаем UserWord
    user_word = UserWord.get_or_create(current_user.id, word_id)

    # Получаем или создаем UserCardDirection
    dir_obj = UserCardDirection.query.filter_by(
        user_word_id=user_word.id,
        direction=direction_str
    ).first()

    if not dir_obj:
        # Создаем направление, если оно еще не существует
        dir_obj = UserCardDirection(user_word_id=user_word.id, direction=direction_str)
        db.session.add(dir_obj)

    # Преобразуем boolean в качество ответа (0-5)
    quality = 4 if is_correct else 1

    # Обновляем SRS параметры для направления
    interval = dir_obj.update_after_review(quality)

    # Обновляем статистику сессии
    if session_id:
        session = StudySession.query.get(session_id)
        if session and session.user_id == current_user.id:
            session.words_studied += 1
            if is_correct:
                session.correct_answers += 1
            else:
                session.incorrect_answers += 1

    db.session.commit()

    return jsonify({
        'success': True,
        'interval': interval,
        'next_review': dir_obj.next_review.strftime('%Y-%m-%d') if dir_obj.next_review else None
    })


@study.route('/api/get-matching-words', methods=['GET'])
@login_required
def get_matching_words():
    """Get words for matching game - automatic selection"""
    word_count = min(int(request.args.get('count', 10)), 20)  # Limit max pairs

    # Get words with same priority as cards
    words = []

    # PRIORITY 1: Words in learning/review status (exclude mastered)
    learning_words = db.session.query(CollectionWords).join(
        UserWord,
        (CollectionWords.id == UserWord.word_id) &
        (UserWord.user_id == current_user.id)
    ).filter(
        UserWord.status.in_(['learning', 'review']),  # EXCLUDE 'mastered'
        CollectionWords.russian_word != None,
        CollectionWords.russian_word != ''
    ).order_by(func.random()).limit(word_count // 2).all()
    
    words.extend(learning_words)

    # PRIORITY 2: New words not yet in user's collection
    if len(words) < word_count:
        new_words = CollectionWords.query.filter(
            ~CollectionWords.id.in_(
                db.session.query(UserWord.word_id)
                .filter(UserWord.user_id == current_user.id)
            ),
            CollectionWords.russian_word != None,
            CollectionWords.russian_word != ''
        ).order_by(func.random()).limit(word_count - len(words)).all()
        
        words.extend(new_words)

    # Ensure we have words
    if not words:
        return jsonify({
            'status': 'error',
            'message': 'No words available for matching game',
            'words': []
        })

    # Format the words for the game
    game_words = []
    for word in words:
        # Skip words without translations
        if not word.russian_word or word.russian_word.strip() == '':
            continue

        # Format example if available
        example = None
        if word.sentences:
            example = word.sentences

        # Get audio URL if available
        audio_url = None
        if hasattr(word, 'get_download') and word.get_download == 1 and word.listening:
            audio_url = url_for('static', filename=f'audio/{word.listening[7:-1]}')

        game_words.append({
            'id': word.id,
            'word': word.english_word,
            'translation': word.russian_word,
            'example': example,
            'audio_url': audio_url
        })

    return jsonify({
        'status': 'success',
        'words': game_words
    })


def _calculate_matching_score(difficulty, pairs_matched, total_pairs, time_taken, moves):
    """
    Server-side score calculation for matching game
    Returns calculated score or 0 if data is invalid
    """
    # Validate difficulty
    if difficulty not in ['easy', 'medium', 'hard']:
        return 0

    # Difficulty settings
    settings = {
        'easy': {'time_limit': 60, 'multiplier': 1},
        'medium': {'time_limit': 120, 'multiplier': 1.5},
        'hard': {'time_limit': 180, 'multiplier': 2}
    }

    config = settings[difficulty]
    time_limit = config['time_limit']
    multiplier = config['multiplier']

    # Validate game data
    if not (0 <= pairs_matched <= total_pairs):
        return 0
    if time_taken < 0 or moves < 0:
        return 0
    if total_pairs == 0:
        return 0
    # Minimum valid moves is pairs_matched * 2 (perfect play)
    if moves < pairs_matched * 2:
        return 0

    # Calculate score components
    time_bonus = max(0, time_limit - time_taken)
    move_efficiency = min(1.0, (total_pairs * 2) / moves) if moves > 0 else 0

    # Calculate base score
    base_score = (
        (pairs_matched * 10) +
        (time_bonus * 2) +
        (move_efficiency * 30)
    )

    # Apply difficulty multiplier
    score = int(base_score * multiplier)

    # Cap between 0 and reasonable maximum
    return max(0, min(score, 500))


@study.route('/api/complete-matching-game', methods=['POST'])
@login_required
def complete_matching_game():
    """Process a completed matching game with server-side score validation"""
    data = request.json
    session_id = data.get('session_id')
    difficulty = data.get('difficulty', 'easy')

    # Validate and parse numeric values
    try:
        pairs_matched = int(data.get('pairs_matched', 0))
        total_pairs = int(data.get('total_pairs', 0))
        moves = int(data.get('moves', 0))
        time_taken = int(data.get('time_taken', 0))
        word_ids = data.get('word_ids', [])  # IDs of words used in game
    except (ValueError, TypeError):
        return jsonify({
            'success': False,
            'error': 'Invalid game data'
        }), 400

    # Calculate score on server side (ignore client-submitted score)
    score = _calculate_matching_score(difficulty, pairs_matched, total_pairs, time_taken, moves)

    # Calculate and award XP
    from app.study.xp_service import XPService
    score_percentage = (pairs_matched / total_pairs * 100) if total_pairs > 0 else 0
    xp_breakdown = XPService.calculate_matching_xp(
        score=score_percentage,
        total_pairs=total_pairs
    )
    user_xp = XPService.award_xp(current_user.id, xp_breakdown['total_xp'])

    # Update SRS data for words used in matching game
    # Quality is determined by performance: perfect match = 4 (Easy), good = 3, poor = 2
    if word_ids and pairs_matched > 0:
        # Calculate performance ratio to determine quality
        performance = pairs_matched / total_pairs if total_pairs > 0 else 0
        efficiency = (total_pairs * 2) / moves if moves > 0 else 0

        # Determine quality based on performance
        if performance >= 1.0 and efficiency > 0.8:
            quality = 4  # Easy - perfect match with good efficiency
        elif performance >= 1.0:
            quality = 3  # Good - perfect match but not efficient
        elif performance >= 0.7:
            quality = 2  # Hard - decent performance
        else:
            quality = 0  # Again - poor performance

        # Update each word's SRS data
        for word_id in word_ids:
            try:
                # Get or create user word
                user_word = UserWord.get_or_create(current_user.id, word_id)

                # Update both directions (eng-rus and rus-eng)
                for direction_str in ['eng-rus', 'rus-eng']:
                    direction = UserCardDirection.query.filter_by(
                        user_word_id=user_word.id,
                        direction=direction_str
                    ).first()

                    if not direction:
                        direction = UserCardDirection(user_word_id=user_word.id, direction=direction_str)
                        db.session.add(direction)
                        db.session.flush()

                    # Update with calculated quality
                    direction.update_after_review(quality)

            except Exception as e:
                # Continue with other words even if one fails
                pass

        db.session.commit()

    # Update session
    if session_id:
        session = StudySession.query.get(session_id)
        if session and session.user_id == current_user.id:
            session.words_studied = total_pairs
            session.correct_answers = pairs_matched
            session.complete_session()
            db.session.commit()

    try:
        # Save score to leaderboard
        game_score = GameScore(
            user_id=current_user.id,
            game_type='matching',
            difficulty=difficulty,
            score=score,
            time_taken=time_taken,
            pairs_matched=pairs_matched,
            total_pairs=total_pairs,
            moves=moves,
            date_achieved=datetime.now(timezone.utc)
        )

        # Явно добавляем объект в сессию и коммитим изменения
        db.session.add(game_score)
        db.session.commit()

        # Get user's rank
        rank = game_score.get_rank()

        # Get personal best
        personal_best = db.session.query(func.max(GameScore.score)).filter(
            GameScore.user_id == current_user.id,
            GameScore.game_type == 'matching',
            GameScore.difficulty == difficulty
        ).scalar() or 0

        is_personal_best = score >= personal_best

        return jsonify({
            'success': True,
            'score': score,
            'rank': rank,
            'is_personal_best': is_personal_best,
            'game_score_id': game_score.id,  # Возвращаем ID созданной записи для проверки
            'xp_earned': xp_breakdown['total_xp'],
            'total_xp': user_xp.total_xp,
            'level': user_xp.level
        })
    except Exception as e:
        # В случае ошибки откатываем транзакцию
        db.session.rollback()

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@study.route('/api/complete-quiz', methods=['POST'])
@login_required
def complete_quiz():
    """Process a completed quiz with XP and achievements"""
    from app.study.models import QuizDeck, QuizResult
    from app.study.xp_service import XPService

    data = request.json
    session_id = data.get('session_id')
    deck_id = data.get('deck_id')
    score = data.get('score', 0)
    total_questions = data.get('total_questions', 0)
    correct_answers = data.get('correct_answers', 0)
    time_taken = data.get('time_taken', 0)
    has_streak = data.get('has_streak', False)  # Frontend can track this

    # Update session
    if session_id:
        session = StudySession.query.get(session_id)
        if session and session.user_id == current_user.id:
            session.complete_session()

    # If this is a deck quiz, save result to deck
    if deck_id:
        deck = QuizDeck.query.get(deck_id)
        if deck:
            # Save quiz result
            quiz_result = QuizResult(
                deck_id=deck_id,
                user_id=current_user.id,
                total_questions=total_questions,
                correct_answers=correct_answers,
                score_percentage=score,
                time_taken=time_taken
            )
            db.session.add(quiz_result)

            # Update deck average score
            deck.average_score = db.session.query(func.avg(QuizResult.score_percentage)).filter(
                QuizResult.deck_id == deck_id
            ).scalar() or 0

            db.session.commit()

    # Save score to leaderboard (keeping old system for compatibility)
    game_score = GameScore(
        user_id=current_user.id,
        game_type='quiz',
        score=score,
        time_taken=time_taken,
        correct_answers=correct_answers,
        total_questions=total_questions,
        date_achieved=datetime.now(timezone.utc)
    )
    db.session.add(game_score)
    db.session.commit()

    # === NEW XP SYSTEM ===
    # Calculate XP earned
    xp_breakdown = XPService.calculate_quiz_xp(
        correct_answers=correct_answers,
        total_questions=total_questions,
        time_taken=time_taken,
        has_streak=has_streak
    )

    # Award XP to user
    user_xp = XPService.award_xp(current_user.id, xp_breakdown['total_xp'])

    # Check and award achievements
    quiz_data = {
        'score': score,
        'total_questions': total_questions,
        'correct_answers': correct_answers,
        'time_taken': time_taken,
        'has_streak': has_streak
    }
    newly_earned = XPService.check_quiz_achievements(current_user.id, quiz_data)

    # Format achievements for response
    achievements = [
        {
            'code': ach.code,
            'name': ach.name,
            'description': ach.description,
            'icon': ach.icon,
            'xp_reward': ach.xp_reward
        }
        for ach in newly_earned
    ] if newly_earned else []

    return jsonify({
        'success': True,
        'score': score,
        'xp_earned': xp_breakdown['total_xp'],
        'xp_breakdown': xp_breakdown,
        'total_xp': user_xp.total_xp,
        'level': user_xp.level,
        'achievements': achievements
    })


@study.route('/api/leaderboard/<game_type>')
@login_required
def get_leaderboard(game_type):
    """Get leaderboard for a game"""
    difficulty = request.args.get('difficulty')
    limit = min(int(request.args.get('limit', 10)), 50)

    # Get leaderboard from model method (already optimized)
    leaderboard = GameScore.get_leaderboard(game_type, difficulty, limit)

    # Format leaderboard data
    leaderboard_data = []
    for i, entry in enumerate(leaderboard):
        user_data = {
            'rank': i + 1,
            'username': entry.user.username,
            'score': entry.score,
            'time_taken': entry.time_taken,
            'date': entry.date_achieved.strftime('%Y-%m-%d %H:%M')
        }

        if game_type == 'matching':
            user_data.update({
                'pairs_matched': entry.pairs_matched,
                'total_pairs': entry.total_pairs,
                'moves': entry.moves
            })
        elif game_type == 'quiz':
            user_data.update({
                'correct_answers': entry.correct_answers,
                'total_questions': entry.total_questions
            })

        leaderboard_data.append(user_data)

    # Get user's best score
    user_best = db.session.query(GameScore).filter(
        GameScore.user_id == current_user.id,
        GameScore.game_type == game_type
    )

    if difficulty:
        user_best = user_best.filter_by(difficulty=difficulty)

    user_best = user_best.order_by(GameScore.score.desc()).first()

    user_best_data = None
    if user_best:
        user_rank = user_best.get_rank()
        user_best_data = {
            'rank': user_rank,
            'score': user_best.score,
            'time_taken': user_best.time_taken,
            'date': user_best.date_achieved.strftime('%Y-%m-%d %H:%M')
        }

        if game_type == 'matching':
            user_best_data.update({
                'pairs_matched': user_best.pairs_matched,
                'total_pairs': user_best.total_pairs,
                'moves': user_best.moves
            })
        elif game_type == 'quiz':
            user_best_data.update({
                'correct_answers': user_best.correct_answers,
                'total_questions': user_best.total_questions
            })

    return jsonify({
        'status': 'success',
        'leaderboard': leaderboard_data,
        'user_best': user_best_data
    })


@study.route('/my-decks/create', methods=['GET', 'POST'])
@login_required
@module_required('study')
def create_deck():
    """Create new quiz deck for current user"""
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        is_public = request.form.get('is_public') == 'on'

        if not title:
            flash('Название колоды обязательно', 'danger')
            return redirect(url_for('study.create_deck'))

        deck = DeckService.create_deck(
            user_id=current_user.id,
            title=title,
            description=description,
            is_public=is_public
        )

        flash(f'Колода "{title}" успешно создана!', 'success')
        return redirect(url_for('study.edit_deck', deck_id=deck.id))

    return render_template('study/deck_create.html')


@study.route('/my-decks/<int:deck_id>/edit', methods=['GET', 'POST'])
@login_required
@module_required('study')
def edit_deck(deck_id):
    """Edit user's quiz deck"""
    from app.study.models import QuizDeck, QuizDeckWord

    deck = QuizDeck.query.get_or_404(deck_id)

    # Check permissions using service
    if deck.user_id != current_user.id:
        flash('У вас нет прав для редактирования этой колоды', 'danger')
        return redirect(url_for('study.index'))

    if is_auto_deck(deck.title):
        flash('Нельзя редактировать автоматические колоды', 'warning')
        return redirect(url_for('study.index'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        is_public = request.form.get('is_public') == 'on'

        if not title:
            flash('Название колоды обязательно', 'danger')
            words = deck.words.order_by(QuizDeckWord.order_index).all()
            return render_template('study/deck_edit.html', deck=deck, words=words)

        updated_deck, error = DeckService.update_deck(
            deck_id=deck_id,
            user_id=current_user.id,
            title=title,
            description=description,
            is_public=is_public,
            generate_share=True
        )

        if error:
            flash(error, 'danger')
        else:
            flash('Колода успешно обновлена!', 'success')

        return redirect(url_for('study.edit_deck', deck_id=deck.id))

    words = deck.words.order_by(QuizDeckWord.order_index).all()
    return render_template('study/deck_edit.html', deck=deck, words=words)


@study.route('/my-decks/<int:deck_id>/delete', methods=['POST'])
@login_required
@module_required('study')
def delete_deck(deck_id):
    """Delete user's quiz deck"""
    from app.study.models import QuizDeck

    deck = QuizDeck.query.get_or_404(deck_id)
    title = deck.title

    success, error = DeckService.delete_deck(deck_id, current_user.id)

    if error:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': error}), 403
        flash(error, 'danger')
        return redirect(url_for('study.index'))

    flash(f'Колода "{title}" успешно удалена', 'success')
    return redirect(url_for('study.index'))


@study.route('/decks/<int:deck_id>/copy', methods=['POST'])
@login_required
@module_required('study')
def copy_deck(deck_id):
    """Copy a public deck to user's collection"""
    from app.study.models import QuizDeck

    original_deck = QuizDeck.query.get_or_404(deck_id)

    new_deck, error = DeckService.copy_deck(deck_id, current_user.id)

    if error:
        flash(error, 'info' if new_deck else 'danger')
        if new_deck:  # Already copied - redirect to existing
            return redirect(url_for('study.edit_deck', deck_id=new_deck.id))
        return redirect(url_for('study.index'))

    flash(f'Колода "{original_deck.title}" успешно скопирована!', 'success')
    return redirect(url_for('study.edit_deck', deck_id=new_deck.id))


@study.route('/my-decks/<int:deck_id>/words/add', methods=['POST'])
@login_required
@module_required('study')
def add_word_to_deck(deck_id):
    """Add word to user's quiz deck"""
    word_id = request.form.get('word_id', type=int)
    custom_english = request.form.get('custom_english', '').strip()
    custom_russian = request.form.get('custom_russian', '').strip()
    custom_sentences = request.form.get('custom_sentences', '').strip()

    deck_word, error = DeckService.add_word_to_deck(
        deck_id=deck_id,
        user_id=current_user.id,
        word_id=word_id,
        custom_english=custom_english,
        custom_russian=custom_russian,
        custom_sentences=custom_sentences if custom_sentences else None
    )

    if error:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': error}), 400
        flash(error, 'danger' if 'не найден' in error else 'info')
        return redirect(url_for('study.edit_deck', deck_id=deck_id))

    # Check if AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        sentences = deck_word.sentences
        return jsonify({
            'success': True,
            'message': 'Слово добавлено в колоду!',
            'word': {
                'id': deck_word.id,
                'english': deck_word.english_word,
                'russian': deck_word.russian_word,
                'has_custom': deck_word.custom_english is not None or deck_word.custom_russian is not None or deck_word.custom_sentences is not None,
                'sentences': sentences[:150] if sentences and len(sentences) > 150 else sentences
            }
        })

    flash('Слово добавлено в колоду!', 'success')
    return redirect(url_for('study.edit_deck', deck_id=deck_id))


@study.route('/my-decks/<int:deck_id>/words/<int:word_id>/edit', methods=['POST'])
@login_required
@module_required('study')
def edit_deck_word(deck_id, word_id):
    """Edit word in user's quiz deck"""
    custom_english = request.form.get('custom_english', '').strip()
    custom_russian = request.form.get('custom_russian', '').strip()
    custom_sentences = request.form.get('custom_sentences', '').strip()

    deck_word, error = DeckService.edit_deck_word(
        deck_id=deck_id,
        deck_word_id=word_id,
        user_id=current_user.id,
        custom_english=custom_english,
        custom_russian=custom_russian,
        custom_sentences=custom_sentences if custom_sentences else None
    )

    if error:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': error}), 400
        flash(error, 'danger')
        return redirect(url_for('study.edit_deck', deck_id=deck_id))

    # Return JSON response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'message': 'Слово успешно обновлено!',
            'word': {
                'id': deck_word.id,
                'english': deck_word.english_word,
                'russian': deck_word.russian_word,
                'has_custom': deck_word.custom_english is not None or deck_word.custom_russian is not None or deck_word.custom_sentences is not None,
                'sentences': deck_word.sentences
            }
        })

    flash('Слово успешно обновлено!', 'success')
    return redirect(url_for('study.edit_deck', deck_id=deck_id))


@study.route('/my-decks/<int:deck_id>/words/<int:word_id>/delete', methods=['POST'])
@login_required
@module_required('study')
def remove_word_from_deck(deck_id, word_id):
    """Remove word from user's quiz deck"""
    success, error = DeckService.remove_word_from_deck(
        deck_id=deck_id,
        deck_word_id=word_id,
        user_id=current_user.id
    )

    if error:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': error}), 403
        flash(error, 'danger')
        return redirect(url_for('study.edit_deck', deck_id=deck_id))

    flash('Слово удалено из колоды', 'success')
    return redirect(url_for('study.edit_deck', deck_id=deck_id))


@study.route('/api/search-words')
@login_required
def api_search_words():
    """API endpoint to search words for autocomplete"""
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


@study.route('/collections')
@login_required
def collections():
    """Отображение списка коллекций для изучения"""
    form = CollectionFilterForm(request.args)

    topic_id = request.args.get('topic')
    topic_id = int(topic_id) if topic_id and topic_id.isdigit() else None
    search = request.args.get('search')

    # Get collections with stats using service
    collections_data = CollectionTopicService.get_collections_with_stats(
        user_id=current_user.id,
        topic_id=topic_id,
        search=search
    )

    # Add stats to collection objects for template
    for data in collections_data:
        data['collection'].words_in_study = data['words_in_study']
        data['collection'].topic_list = data['topics']

    # Get all topics for filter
    topics = Topic.query.order_by(Topic.name).all()

    return render_template(
        'study/collections.html',
        collections=[d['collection'] for d in collections_data],
        form=form,
        topics=topics
    )


@study.route('/collections/<int:collection_id>')
@login_required
def collection_details(collection_id):
    """Просмотр деталей коллекции"""
    collection = Collection.query.get_or_404(collection_id)

    # Get words with status using service
    words_data = CollectionTopicService.get_collection_words_with_status(
        collection_id=collection_id,
        user_id=current_user.id
    )

    # Add is_studying to word objects for template
    words = [data['word'] for data in words_data]
    for i, word in enumerate(words):
        word.is_studying = words_data[i]['is_studying']

    topics = collection.topics

    return render_template(
        'study/collections_details.html',
        collection=collection,
        words=words,
        topics=topics
    )


@study.route('/add_collection/<int:collection_id>', methods=['POST'])
@login_required
def add_collection(collection_id):
    """Добавление всех слов из коллекции в список изучения"""
    collection = Collection.query.get_or_404(collection_id)

    # Add collection words using service
    added_count, message = CollectionTopicService.add_collection_to_study(
        collection_id=collection_id,
        user_id=current_user.id
    )

    if added_count > 0:
        flash(_('%(count)d words from "%(name)s" collection added to your study list!',
                count=added_count, name=collection.name), 'success')
    else:
        flash(_('All words from this collection are already in your study list.'), 'info')

    # AJAX request or regular
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'added_count': added_count,
            'message': _('%(count)d words added to your study list!', count=added_count)
        })

    return redirect(url_for('study.collections'))


@study.route('/topics')
@login_required
def topics():
    """Отображение списка тем для изучения"""
    # Get topics with stats using service
    topics_data = CollectionTopicService.get_topics_with_stats(current_user.id)

    # Add stats to topic objects for template
    for data in topics_data:
        data['topic'].word_count = data['word_count']
        data['topic'].words_in_study = data['words_in_study']

    return render_template(
        'study/topics.html',
        topics=[d['topic'] for d in topics_data]
    )


@study.route('/topics/<int:topic_id>')
@login_required
def topic_details(topic_id):
    """Просмотр деталей темы и слов в ней"""
    # Get topic, words with status, and related collections using service
    topic, words_data, related_collections = CollectionTopicService.get_topic_words_with_status(
        topic_id=topic_id,
        user_id=current_user.id
    )

    if not topic:
        from flask import abort
        abort(404)

    # Add is_studying to word objects for template
    words = [data['word'] for data in words_data]
    for i, word in enumerate(words):
        word.is_studying = words_data[i]['is_studying']

    return render_template(
        'study/topic_details.html',
        topic=topic,
        words=words,
        related_collections=related_collections
    )


@study.route('/add_topic/<int:topic_id>', methods=['POST'])
@login_required
def add_topic(topic_id):
    """Добавление всех слов из темы в список изучения"""
    topic = Topic.query.get_or_404(topic_id)

    # Add topic words using service
    added_count, message = CollectionTopicService.add_topic_to_study(
        topic_id=topic_id,
        user_id=current_user.id
    )

    if added_count > 0:
        flash(_('%(count)d words from "%(name)s" topic added to your study list!',
                count=added_count, name=topic.name), 'success')
    else:
        flash(_('All words from this topic are already in your study list.'), 'info')

    # AJAX request or regular
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'added_count': added_count,
            'message': _('%(count)d words added to your study list!', count=added_count)
        })

    return redirect(url_for('study.topics'))
