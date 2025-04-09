from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import func

from app.study.forms import StudySessionForm, StudySettingsForm
from app.study.models import StudyItem, StudySession, StudySettings
from app.utils.db import db
from app.words.models import CollectionWords

study = Blueprint('study', __name__, template_folder='templates')


@study.route('/')
@login_required
def index():
    """Main study dashboard"""
    # Get study statistics
    due_items_count = StudyItem.query.filter_by(user_id=current_user.id) \
        .filter(StudyItem.next_review <= datetime.utcnow()).count()

    total_items = StudyItem.query.filter_by(user_id=current_user.id).count()

    # Get user's recent sessions
    recent_sessions = StudySession.query.filter_by(user_id=current_user.id) \
        .order_by(StudySession.start_time.desc()).limit(5).all()

    # Get learned words percentage
    total_words = CollectionWords.query.count()
    learned_words = StudyItem.query.filter_by(user_id=current_user.id).count()

    if total_words > 0:
        learned_percentage = int((learned_words / total_words) * 100)
    else:
        learned_percentage = 0

    # Get study session form
    form = StudySessionForm()

    return render_template(
        'study/index.html',
        due_items_count=due_items_count,
        total_items=total_items,
        learned_percentage=learned_percentage,
        recent_sessions=recent_sessions,
        form=form
    )


@study.route('/settings', methods=['GET', 'POST'])
@login_required
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


@study.route('/cards')
@login_required
def cards():
    """Anki-style flashcard study interface"""
    # Get query parameters
    word_source = request.args.get('word_source', 'all')

    # Get user settings
    settings = StudySettings.get_settings(current_user.id)

    # Create new study session
    session = StudySession(
        user_id=current_user.id,
        session_type='cards'
    )
    db.session.add(session)
    db.session.commit()

    return render_template(
        'study/cards.html',
        session_id=session.id,
        settings=settings,
        word_source=word_source
    )


@study.route('/quiz')
@login_required
def quiz():
    """Quiz study interface"""
    # Get query parameters
    word_source = request.args.get('word_source', 'all')

    # Get user settings
    settings = StudySettings.get_settings(current_user.id)

    # Create new study session
    session = StudySession(
        user_id=current_user.id,
        session_type='quiz'
    )
    db.session.add(session)
    db.session.commit()

    return render_template(
        'study/quiz.html',
        session_id=session.id,
        settings=settings,
        word_source=word_source
    )


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
            flash(_('This study mode is not implemented yet.'), 'warning')
            return redirect(url_for('study.index'))

    flash(_('Invalid form data.'), 'danger')
    return redirect(url_for('study.index'))


# API routes for AJAX calls from study interfaces

@study.route('/api/get-study-items', methods=['GET'])
@login_required
def get_study_items():
    """Get words for study based on source and limits"""
    word_source = request.args.get('source', 'all')
    extra_study = request.args.get('extra_study', 'false').lower() == 'true'

    # Получаем настройки пользователя
    settings = StudySettings.get_settings(current_user.id)

    # Проверяем, были ли достигнуты дневные лимиты
    # Для этого нам нужно подсчитать, сколько новых карточек и повторений было сделано сегодня
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Получаем количество новых карточек, изученных сегодня
    new_cards_today = db.session.query(func.count(StudyItem.id)).filter(
        StudyItem.user_id == current_user.id,
        StudyItem.last_reviewed >= today_start,
        StudyItem.repetitions == 1  # Это новая карточка (первое изучение)
    ).scalar()

    # Получаем количество повторений, сделанных сегодня
    reviews_today = db.session.query(func.count(StudyItem.id)).filter(
        StudyItem.user_id == current_user.id,
        StudyItem.last_reviewed >= today_start,
        StudyItem.repetitions > 1  # Это повторение (не первое изучение)
    ).scalar()

    # Проверяем, достигнуты ли лимиты
    new_cards_limit_reached = new_cards_today >= settings.new_words_per_day
    reviews_limit_reached = reviews_today >= settings.reviews_per_day

    # Если оба лимита достигнуты и не запрошено дополнительное занятие, возвращаем пустой список
    # с особым статусом, чтобы фронтенд мог показать сообщение о завершении дневной нормы
    if not extra_study and new_cards_limit_reached and reviews_limit_reached:
        return jsonify({
            'status': 'daily_limit_reached',
            'message': 'Дневные лимиты достигнуты',
            'stats': {
                'new_cards_today': new_cards_today,
                'reviews_today': reviews_today,
                'new_cards_limit': settings.new_words_per_day,
                'reviews_limit': settings.reviews_per_day
            },
            'items': []
        })

    result_items = []

    # Определяем лимиты в зависимости от того, что уже изучено сегодня
    # Для обычного занятия - оставшиеся лимиты, для дополнительного - можно установить фиксированное число
    if extra_study:
        new_limit = 5  # Фиксированное количество для дополнительного занятия
        review_limit = 10
    else:
        new_limit = max(0, settings.new_words_per_day - new_cards_today)
        review_limit = max(0, settings.reviews_per_day - reviews_today)

    # Делим лимиты пополам, так как каждое слово создает 2 карточки (eng-rus и rus-eng)
    new_limit = max(1, new_limit // 2)
    review_limit = max(1, review_limit // 2)

    # Зависит от запрошенного источника - новые, изучаемые или все
    if word_source in ['new', 'all'] and new_limit > 0:
        # Получаем слова, которые пользователь еще не изучал
        existing_word_ids = db.session.query(StudyItem.word_id) \
            .filter_by(user_id=current_user.id).subquery()

        new_words = CollectionWords.query.filter(
            ~CollectionWords.id.in_(existing_word_ids),
            CollectionWords.russian_word != None,
            CollectionWords.russian_word != ''
        ).order_by(CollectionWords.id).limit(new_limit).all()

        # Добавляем новые слова в результат
        for word in new_words:
            audio_url = None
            if word.get_download == 1:
                audio_url = url_for('static', filename=f'audio/pronunciation_en_{word.english_word}.mp3')

            result_items.append({
                'id': None,
                'word_id': word.id,
                'word': word.english_word,
                'translation': word.russian_word,
                'definition': '',
                'examples': word.sentences,
                'audio_url': audio_url,
                'is_new': True
            })

    # Получаем просроченные карточки для повторения, если лимит не исчерпан
    if word_source in ['all', 'learning'] and review_limit > 0:
        # Получаем карточки для повторения
        due_items = StudyItem.query.filter_by(user_id=current_user.id) \
            .filter(StudyItem.next_review <= datetime.utcnow().date() + timedelta(days=1)) \
            .order_by(StudyItem.next_review).limit(review_limit).all()
        # Добавляем карточки для повторения
        for item in due_items:
            word = item.word
            if not word or not word.russian_word:
                continue

            result_items.append({
                'id': item.id,
                'word_id': word.id,
                'word': word.english_word,
                'translation': word.russian_word,
                'examples': word.sentences,
                'audio_url': url_for('static', filename=f'audio/pronunciation_en_{word.english_word}.mp3')
                if word.get_download else None,
                'is_new': False
            })

    # Возвращаем результаты с информацией о статусе
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
    """Update study item after review"""
    data = request.json
    word_id = data.get('word_id')
    quality = int(data.get('quality', 0))  # 0-5 rating
    session_id = data.get('session_id')

    # Get or create study item
    study_item = StudyItem.query.filter_by(user_id=current_user.id, word_id=word_id).first()

    if not study_item:
        # Create new study item if it doesn't exist
        study_item = StudyItem(user_id=current_user.id, word_id=word_id)
        db.session.add(study_item)

    # Update study item
    interval = study_item.update_after_review(quality)

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

    return jsonify({
        'success': True,
        'interval': interval,
        'next_review': study_item.next_review.strftime('%Y-%m-%d')
    })


@study.route('/api/complete-session', methods=['POST'])
@login_required
def complete_session():
    """Mark a study session as complete"""
    data = request.json
    session_id = data.get('session_id')

    session = StudySession.query.get(session_id)
    if session and session.user_id == current_user.id:
        session.complete_session()
        db.session.commit()

        return jsonify({
            'success': True,
            'stats': {
                'duration': session.duration,
                'words_studied': session.words_studied,
                'correct': session.correct_answers,
                'incorrect': session.incorrect_answers,
                'percentage': session.performance_percentage
            }
        })

    return jsonify({'success': False, 'message': 'Invalid session'})


@study.route('/stats')
@login_required
def stats():
    """Study statistics page"""
    # Get overall statistics
    total_items = StudyItem.query.filter_by(user_id=current_user.id).count()
    mastered_items = StudyItem.query.filter_by(user_id=current_user.id) \
        .filter(StudyItem.interval >= 30).count()

    # Calculate mastery percentage
    if total_items > 0:
        mastery_percentage = int((mastered_items / total_items) * 100)
    else:
        mastery_percentage = 0

    # Get recent sessions
    recent_sessions = StudySession.query.filter_by(user_id=current_user.id) \
        .order_by(StudySession.start_time.desc()).limit(10).all()

    # Get daily study statistics
    today = datetime.now().date()
    today_sessions = StudySession.query.filter_by(user_id=current_user.id) \
        .filter(func.date(StudySession.start_time) == today).all()

    # Calculate today's statistics
    today_words_studied = sum(session.words_studied for session in today_sessions)
    today_time_spent = sum(session.duration for session in today_sessions)

    # Get daily study streak
    # This would require more complex logic to track consecutive days
    study_streak = 0

    # Get words by stage (learning vs mastered)
    new_words = StudyItem.query.filter_by(user_id=current_user.id) \
        .filter(StudyItem.repetitions == 0).count()
    learning_words = StudyItem.query.filter_by(user_id=current_user.id) \
        .filter(StudyItem.repetitions > 0, StudyItem.interval < 30).count()
    mastered_words = mastered_items  # We already calculated this

    return render_template(
        'study/stats.html',
        total_items=total_items,
        mastered_items=mastered_items,
        mastery_percentage=mastery_percentage,
        recent_sessions=recent_sessions,
        study_streak=study_streak,
        today_words_studied=today_words_studied,
        today_time_spent=today_time_spent,
        new_words=new_words,
        learning_words=learning_words,
        mastered_words=mastered_words
    )
