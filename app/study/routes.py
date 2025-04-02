from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash
from flask_login import login_required, current_user
from app.study.models import StudyItem, StudySession, StudySettings
from app.study.forms import StudySettingsForm, StudySessionForm
# Import CollectionWords model
from app.words.models import CollectionWords
from app.utils.db import db
from datetime import datetime
from flask_babel import gettext as _
import random

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
    max_words = int(request.args.get('max_words', 20))

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
        word_source=word_source,
        max_words=max_words
    )


@study.route('/quiz')
@login_required
def quiz():
    """Quiz study interface"""
    # Get query parameters
    word_source = request.args.get('word_source', 'all')
    max_words = int(request.args.get('max_words', 20))

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
        word_source=word_source,
        max_words=max_words
    )


@study.route('/start-session', methods=['POST'])
@login_required
def start_session():
    """Start a new study session"""
    form = StudySessionForm()

    if form.validate_on_submit():
        session_type = form.session_type.data
        word_source = form.word_source.data
        max_words = form.max_words.data

        if session_type == 'cards':
            return redirect(url_for('study.cards',
                                    word_source=word_source,
                                    max_words=max_words))
        elif session_type == 'quiz':
            return redirect(url_for('study.quiz',
                                    word_source=word_source,
                                    max_words=max_words))
        else:
            flash(_('This study mode is not implemented yet.'), 'warning')
            return redirect(url_for('study.index'))

    flash(_('Invalid form data.'), 'danger')
    return redirect(url_for('study.index'))


# API routes for AJAX calls from study interfaces

@study.route('/api/get-study-items', methods=['GET'])
@login_required
def get_study_items():
    """Get words for study based on source and limit"""
    word_source = request.args.get('source', 'all')
    limit = int(request.args.get('limit', 20))

    # Base query for study items
    query = StudyItem.query.filter_by(user_id=current_user.id)

    # Filter based on word source
    if word_source == 'due':
        query = query.filter(StudyItem.next_review <= datetime.utcnow())
    elif word_source == 'new':
        # Get words that don't have study items yet
        existing_word_ids = db.session.query(StudyItem.word_id) \
            .filter_by(user_id=current_user.id).subquery()

        words = CollectionWords.query.filter(~CollectionWords.id.in_(existing_word_ids)) \
            .order_by(CollectionWords.id).limit(limit).all()

        # Convert to study items format for consistency
        items = []
        for word in words:
            audio_url = None
            # Проверяем наличие аудиофайла по полю get_download
            if word.get_download == 1:
                audio_url = url_for('static', filename=f'audio/pronunciation_en_{word.english_word}.mp3')

            items.append({
                'id': None,
                'word_id': word.id,
                'word': word.english_word,
                'translation': word.russian_word,
                'definition': '',
                'examples': word.sentences,
                'audio_url': audio_url,
                'is_new': True
            })

        return jsonify(items[:limit])

    elif word_source == 'queue':
        # Get words with "In Queue" status (status=1) from user_word_status
        from sqlalchemy import text

        # Query to get words in queue for the current user
        sql = text("""
                SELECT cw.id, cw.english_word, cw.russian_word, cw.sentences, cw.get_download
                FROM collection_words cw
                JOIN user_word_status uws ON cw.id = uws.word_id
                WHERE uws.user_id = :user_id AND uws.status = 2
                ORDER BY uws.last_updated DESC
                LIMIT :limit
            """)

        result = db.session.execute(sql, {'user_id': current_user.id, 'limit': limit})

        # Convert to study items format
        items = []
        for row in result:
            audio_url = None
            if row.get_download == 1:
                audio_url = url_for('static', filename=f'audio/pronunciation_en_{row.english_word}.mp3')

            items.append({
                'id': None,
                'word_id': row.id,
                'word': row.english_word,
                'translation': row.russian_word,
                'definition': '',
                'examples': row.sentences,
                'audio_url': audio_url,
                'is_new': True
            })

        # If no items found, return empty list with message
        if not items:
            return jsonify([]), 204  # No Content status

        return jsonify(items)

    elif word_source == 'difficult':
        # Words with low performance
        study_items = StudyItem.query.filter_by(user_id=current_user.id) \
            .filter(StudyItem.performance_percentage < 70) \
            .order_by(StudyItem.performance_percentage).limit(limit).all()

    elif word_source == 'book':
        # This would require additional logic to get words from a specific book
        flash('Book-specific study is not implemented yet.', 'warning')
        return jsonify([])

    else:  # 'all' - mix of due and new
        # Get due items first
        due_items = query.filter(StudyItem.next_review <= datetime.utcnow()) \
            .order_by(StudyItem.next_review).limit(limit).all()

        # If we need more, add some new words
        if len(due_items) < limit:
            remaining = limit - len(due_items)

            # Get words that don't have study items yet
            existing_word_ids = db.session.query(StudyItem.word_id) \
                .filter_by(user_id=current_user.id).subquery()

            new_words = CollectionWords.query.filter(~CollectionWords.id.in_(existing_word_ids)) \
                .order_by(CollectionWords.id).limit(remaining).all()

            items = []
            # Add due items
            for item in due_items:
                word = item.word
                items.append({
                    'id': item.id,
                    'word_id': word.id,
                    'word': word.english_word,
                    'translation': word.russian_word,
                    'examples': word.sentences,
                    'audio_url': url_for('static',
                                         filename=f'audio/pronunciation_en_{word.english_word}.mp3') if word.get_download else None,
                    'is_new': False
                })

            # Add new words
            for word in new_words:
                items.append({
                    'id': None,
                    'word_id': word.id,
                    'word': word.english_word,
                    'translation': word.russian_word,
                    'examples': word.sentences,
                    'audio_url': url_for('static',
                                         filename=f'audio/pronunciation_en_{word.english_word}.mp3') if word.get_download else None,
                    'is_new': True
                })

            return jsonify(items)

    # For most cases, process the query results
    study_items = query.join(CollectionWords).order_by(StudyItem.next_review).limit(limit).all()

    items = []
    for item in study_items:
        word = item.word
        audio_url = None
        if word.get_download == 1:
            audio_url = url_for('static', filename=f'audio/pronunciation_en_{word.english_word}.mp3')

        items.append({
            'id': item.id,
            'word_id': word.id,
            'word': word.english_word,
            'translation': word.russian_word,
            'definition': '',
            'examples': word.sentences,
            'audio_url': audio_url,
            'is_new': False
        })

    return jsonify(items)


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

    # Get daily study streak
    # This would require more complex logic to track consecutive days
    study_streak = 0

    return render_template(
        'study/stats.html',
        total_items=total_items,
        mastered_items=mastered_items,
        mastery_percentage=mastery_percentage,
        recent_sessions=recent_sessions,
        study_streak=study_streak
    )