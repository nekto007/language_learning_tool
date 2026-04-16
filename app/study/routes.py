import logging
from datetime import datetime, timezone

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import func, or_, and_, case

from app.study.blueprint import study, is_auto_deck
from app.study.deck_utils import get_daily_plan_mix_word_ids
from app.study.forms import StudySettingsForm
from app.study.models import QuizDeck, StudySettings, UserCardDirection, UserWord
from app.utils.db import db
from app.modules.decorators import module_required
from app.study.services import DeckService, SRSService, SessionService, StatsService

logger = logging.getLogger(__name__)


@study.route('/')
@login_required
@module_required('study')
def index():
    due_items_count = UserCardDirection.query \
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id) \
        .filter(
        UserWord.user_id == current_user.id,
        UserCardDirection.next_review <= datetime.now(timezone.utc)
    ).count()

    new_items_count = UserCardDirection.query \
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id) \
        .filter(
        UserWord.user_id == current_user.id,
        UserCardDirection.state == 'new',
        or_(
            UserCardDirection.next_review.is_(None),
            UserCardDirection.next_review <= datetime.now(timezone.utc)
        )
    ).count()

    mastered_count = db.session.query(func.count(UserWord.id)).filter(
        UserWord.user_id == current_user.id,
        UserWord.status == 'review'
    ).join(
        UserCardDirection, UserCardDirection.user_word_id == UserWord.id
    ).group_by(UserWord.id).having(
        func.min(UserCardDirection.interval) >= UserWord.MASTERED_THRESHOLD_DAYS
    ).count()

    learning_total = UserWord.query.filter(
        UserWord.user_id == current_user.id,
        UserWord.status == 'learning'
    ).count()

    all_words_count = UserWord.query.filter_by(user_id=current_user.id).count()

    review_total = max(0, all_words_count - learning_total - mastered_count)

    my_decks = QuizDeck.query.filter_by(
        user_id=current_user.id
    ).order_by(QuizDeck.updated_at.desc()).all()

    deck_words_dict = {}
    user_words_dict = {}
    user_word_ids_with_cards = set()
    all_deck_word_ids = set()
    if my_decks:
        from app.study.models import QuizDeckWord

        deck_ids = [deck.id for deck in my_decks]
        deck_words = QuizDeckWord.query.filter(
            QuizDeckWord.deck_id.in_(deck_ids)
        ).all()

        for dw in deck_words:
            if dw.deck_id not in deck_words_dict:
                deck_words_dict[dw.deck_id] = []
            deck_words_dict[dw.deck_id].append(dw)

        all_deck_word_ids = set([dw.word_id for dw in deck_words if dw.word_id])

        if all_deck_word_ids:
            user_words = UserWord.query.filter(
                UserWord.user_id == current_user.id,
                UserWord.word_id.in_(all_deck_word_ids)
            ).all()
            user_words_dict = {uw.word_id: uw for uw in user_words}

            if user_words:
                user_word_ids = [uw.id for uw in user_words]
                cards_exist = db.session.query(
                    UserCardDirection.user_word_id
                ).filter(
                    UserCardDirection.user_word_id.in_(user_word_ids)
                ).distinct().all()
                user_word_ids_with_cards = set(row[0] for row in cards_exist)

    deck_stats = {}
    now = datetime.now(timezone.utc)
    end_of_today = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    if my_decks and all_deck_word_ids:
        from app.study.models import QuizDeckWord

        state_category = case(
            (or_(UserCardDirection.state == 'new', UserCardDirection.state.is_(None)), 'new'),
            (UserCardDirection.state.in_(['learning', 'relearning']), 'learning'),
            (and_(
                UserCardDirection.state == 'review',
                UserCardDirection.interval >= UserWord.MASTERED_THRESHOLD_DAYS
            ), 'mastered'),
            (and_(
                UserCardDirection.state == 'review',
                or_(UserCardDirection.interval.is_(None), UserCardDirection.interval < UserWord.MASTERED_THRESHOLD_DAYS)
            ), 'review'),
            else_='new'
        ).label('category')

        stats_query = db.session.query(
            QuizDeckWord.deck_id,
            state_category,
            func.count(UserCardDirection.id)
        ).join(
            UserWord, UserWord.word_id == QuizDeckWord.word_id
        ).join(
            UserCardDirection, UserCardDirection.user_word_id == UserWord.id
        ).filter(
            QuizDeckWord.deck_id.in_([d.id for d in my_decks]),
            UserWord.user_id == current_user.id,
            or_(
                UserCardDirection.state == 'new',
                UserCardDirection.state.is_(None),
                UserCardDirection.next_review <= end_of_today
            )
        ).group_by(QuizDeckWord.deck_id, state_category).all()

        for deck_id, category, count in stats_query:
            if deck_id not in deck_stats:
                deck_stats[deck_id] = {'new': 0, 'learning': 0, 'review': 0, 'mastered': 0}
            deck_stats[deck_id][category] = count

    for deck in my_decks:
        deck_words_list = deck_words_dict.get(deck.id, [])
        deck_word_ids = set(dw.word_id for dw in deck_words_list if dw.word_id)

        stats = deck_stats.get(deck.id, {'new': 0, 'learning': 0, 'review': 0, 'mastered': 0})

        words_with_userword = set(uw.word_id for uw in user_words_dict.values() if uw.word_id in deck_word_ids)
        words_without_userword = len(deck_word_ids - words_with_userword)

        words_with_userword_no_cards = sum(
            1 for uw in user_words_dict.values()
            if uw.word_id in deck_word_ids and uw.id not in user_word_ids_with_cards
        )

        potential_new = (words_without_userword + words_with_userword_no_cards) * 2

        deck.new_count = stats['new'] + potential_new
        deck.learning_count = stats['learning']
        deck.review_count = stats['review']
        deck.mastered_count = stats['mastered']
        deck.total_cards = deck.new_count + deck.learning_count + deck.review_count + deck.mastered_count
        deck.is_auto = is_auto_deck(deck.title)

    public_decks = QuizDeck.query.filter(
        QuizDeck.is_public.is_(True),
        QuizDeck.user_id != current_user.id
    ).order_by(QuizDeck.times_played.desc(), QuizDeck.created_at.desc()).limit(12).all()

    from app.telegram.models import TelegramUser
    telegram_linked = TelegramUser.query.filter_by(
        user_id=current_user.id, is_active=True
    ).first() is not None

    most_urgent_deck = None
    if my_decks:
        best_due = -1
        for deck in my_decks:
            due = deck.learning_count + deck.review_count
            if due > best_due:
                best_due = due
                most_urgent_deck = deck
        if best_due <= 0:
            most_urgent_deck = None

    return render_template(
        'study/index.html',
        due_items_count=due_items_count,
        new_items_count=new_items_count,
        learning_total=learning_total,
        review_total=review_total,
        mastered_count=mastered_count,
        all_words_count=all_words_count,
        my_decks=my_decks,
        public_decks=public_decks,
        telegram_linked=telegram_linked,
        most_urgent_deck=most_urgent_deck,
    )


@study.route('/settings', methods=['GET', 'POST'])
@login_required
@module_required('study')
def settings():
    user_settings = StudySettings.get_settings(current_user.id)

    form = StudySettingsForm(obj=user_settings)

    if form.validate_on_submit():
        form.populate_obj(user_settings)
        db.session.commit()
        flash(_('Your study settings have been updated!'), 'success')
        return redirect(url_for('study.index'))

    bot_username = current_app.config.get('TELEGRAM_BOT_USERNAME', 'llt_englishbot')
    return render_template('study/settings.html', form=form,
                           telegram_bot_username=bot_username)


@study.route('/cards')
@login_required
@module_required('study')
def cards():
    settings = StudySettings.get_settings(current_user.id)
    source = request.args.get('source', 'auto')
    from_daily_plan = request.args.get('from') == 'daily_plan'
    deck_word_ids = get_daily_plan_mix_word_ids(current_user.id) if source == 'daily_plan_mix' else None

    counts = SRSService.get_card_counts(current_user.id, deck_word_ids=deck_word_ids)

    session = SessionService.start_session(current_user.id, 'cards')

    return render_template(
        'study/cards.html',
        session_id=session.id,
        settings=settings,
        word_source=source,
        nothing_to_study=counts['nothing_to_study'],
        limit_reached=counts['limit_reached'],
        daily_limit=counts['new_limit'],
        new_cards_today=counts['new_today'],
        fc_title='Дневной микс' if source == 'daily_plan_mix' else 'Карточки',
        fc_back_url=url_for('words.dashboard') if from_daily_plan else url_for('study.index'),
        fc_cards=[],
        fc_fetch_cards_url='/study/api/get-study-items',
        fc_fetch_cards_params={'source': source},
        fc_grade_url='/study/api/update-study-item',
        fc_complete_url='/study/api/complete-session',
        fc_on_complete_url=url_for('words.dashboard') if from_daily_plan else url_for('study.index'),
        fc_on_complete_text='К плану дня' if from_daily_plan else 'К колодам',
        fc_session_id=session.id,
        fc_show_examples=settings.include_examples if settings else True,
        fc_show_audio=settings.include_audio if settings else True,
        fc_show_book_context=False,
        fc_nothing_to_study=counts['nothing_to_study'],
        fc_limit_reached=counts['limit_reached'],
        fc_daily_limit=counts['new_limit'],
        fc_new_cards_today=counts['new_today'],
        fc_deck_id=None,
    )


@study.route('/cards/deck/<int:deck_id>')
@login_required
@module_required('study')
def cards_deck(deck_id):
    deck = DeckService.get_deck_with_words(deck_id)
    if not deck:
        flash('Колода не найдена', 'danger')
        return redirect(url_for('study.index'))

    if not deck.is_public and deck.user_id != current_user.id:
        flash('У вас нет доступа к этой колоде', 'danger')
        return redirect(url_for('study.index'))

    if deck.word_count == 0:
        flash('В колоде нет слов', 'warning')
        return redirect(url_for('study.index'))

    deck_word_ids = [dw.word_id for dw in deck.words if dw.word_id]
    if not deck_word_ids:
        flash('В колоде нет слов для SRS повторения', 'info')
        return redirect(url_for('study.index'))

    settings = StudySettings.get_settings(current_user.id)
    counts = SRSService.get_card_counts(current_user.id, deck_word_ids)

    deck.times_played += 1
    db.session.commit()

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
        new_cards_today=counts['new_today'],
        fc_title=deck.title,
        fc_back_url=url_for('study.index'),
        fc_cards=[],
        fc_fetch_cards_url='/study/api/get-study-items',
        fc_fetch_cards_params={'source': 'deck', 'deck_id': str(deck_id)},
        fc_grade_url='/study/api/update-study-item',
        fc_complete_url='/study/api/complete-session',
        fc_on_complete_url=url_for('study.index'),
        fc_on_complete_text='К колодам',
        fc_session_id=session.id,
        fc_show_examples=settings.include_examples if settings else True,
        fc_show_audio=settings.include_audio if settings else True,
        fc_show_book_context=False,
        fc_nothing_to_study=counts['nothing_to_study'],
        fc_limit_reached=counts['limit_reached'],
        fc_daily_limit=counts['new_limit'],
        fc_new_cards_today=counts['new_today'],
        fc_deck_id=deck_id,
    )


@study.route('/stats')
@login_required
@module_required('study')
def stats():
    stats_data = StatsService.get_user_stats(current_user.id)

    accuracy_trend = StatsService.get_accuracy_trend(current_user.id)
    mastered_over_time = StatsService.get_mastered_over_time(current_user.id)
    study_heatmap = StatsService.get_study_heatmap(current_user.id)

    from app.telegram.models import TelegramUser
    telegram_linked = TelegramUser.query.filter_by(
        user_id=current_user.id, is_active=True
    ).first() is not None

    return render_template(
        'study/stats.html',
        total_items=stats_data['total'],
        mastered_items=stats_data['mastered'],
        mastery_percentage=stats_data['mastery_percentage'],
        recent_sessions=stats_data['recent_sessions'],
        study_streak=stats_data['study_streak'],
        today_words_studied=stats_data['today_words_studied'],
        today_time_spent=stats_data['today_time_spent'],
        new_words=stats_data['new'],
        learning_words=stats_data['learning'],
        mastered_words=stats_data['mastered'],
        telegram_linked=telegram_linked,
        accuracy_trend=accuracy_trend,
        mastered_over_time=mastered_over_time,
        study_heatmap=study_heatmap,
    )


@study.route('/insights')
@login_required
def insights():
    from app.study.insights_service import (
        get_activity_heatmap, get_best_study_time, get_words_at_risk,
        get_grammar_weaknesses, get_reading_speed_trend, get_learning_summary
    )

    heatmap = get_activity_heatmap(current_user.id)
    best_time = get_best_study_time(current_user.id)
    at_risk = get_words_at_risk(current_user.id)
    weaknesses = get_grammar_weaknesses(current_user.id)
    reading_trend = get_reading_speed_trend(current_user.id)
    summary = get_learning_summary(current_user.id)

    return render_template('study/insights.html',
        heatmap=heatmap,
        best_time=best_time,
        at_risk_words=at_risk,
        grammar_weaknesses=weaknesses,
        reading_trend=reading_trend,
        summary=summary,
    )


# Import sub-modules to register their routes on the blueprint
from app.study import api_routes  # noqa: E402, F401
from app.study import game_routes  # noqa: E402, F401
from app.study import deck_routes  # noqa: E402, F401
