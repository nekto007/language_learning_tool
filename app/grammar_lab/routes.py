# app/grammar_lab/routes.py
"""
Routes for Grammar Lab module.

Provides both HTML pages and JSON API endpoints.
Uses UnifiedSRSService for Anki-like spaced repetition.
"""

from flask import render_template, jsonify, request, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
import logging

from app.grammar_lab import grammar_lab_bp
from app.grammar_lab.models import GrammarTopic, GrammarExercise, UserGrammarExercise
from app.grammar_lab.services import GrammarLabService
from app.utils.db import db

logger = logging.getLogger(__name__)


def _get_srs_stats_service():
    """Lazy import to avoid circular dependency."""
    from app.srs.stats_service import srs_stats_service
    return srs_stats_service

# Initialize service
grammar_service = GrammarLabService()


# ============ HTML Pages ============

@grammar_lab_bp.route('/')
def index():
    """Grammar Lab home page — public, with personal stats for authenticated users"""
    user_id = current_user.id if current_user.is_authenticated else None
    levels = grammar_service.get_levels_summary(user_id)
    recommendations = grammar_service.get_recommendations(user_id, limit=5) if user_id else []
    stats = grammar_service.get_user_stats(user_id) if user_id else None
    next_topic = grammar_service.get_next_recommended_topic(user_id) if user_id else None
    level_mastery = grammar_service.get_level_mastery_stats(user_id) if user_id else {}

    return render_template(
        'grammar_lab/index.html',
        levels=levels,
        recommendations=recommendations,
        stats=stats,
        next_topic=next_topic,
        level_mastery=level_mastery,
    )


@grammar_lab_bp.route('/topics')
@grammar_lab_bp.route('/topics/<level>')
def topics(level=None):
    """Topics listing page — public, with progress for authenticated users"""
    user_id = current_user.id if current_user.is_authenticated else None
    topics_list = grammar_service.get_topics_by_level(level, user_id)
    levels = grammar_service.get_levels_summary(user_id)

    return render_template(
        'grammar_lab/topics.html',
        topics=topics_list,
        levels=levels,
        current_level=level
    )


@grammar_lab_bp.route('/topic/<int:topic_id>')
def topic_detail(topic_id):
    """Topic detail page with theory — public, exercises require auth"""
    user_id = current_user.id if current_user.is_authenticated else None
    topic = grammar_service.get_topic_detail(topic_id, user_id)

    if not topic:
        return redirect(url_for('grammar_lab.topics'))

    # SEO meta description
    intro = (topic.get('content') or {}).get('introduction', '')
    meta_description = intro[:150].rstrip() if intro else f'{topic["title"]} — правила, примеры, таблицы.'
    if topic.get('exercise_count'):
        meta_description += f' {topic["exercise_count"]} упражнений для практики.'

    # Previous/next topic navigation
    adjacent = grammar_service.get_adjacent_topics(topic_id)

    # Related topics (same level, excluding current)
    related_topics = GrammarTopic.query.filter(
        GrammarTopic.level == topic.get('level'),
        GrammarTopic.id != topic_id,
    ).order_by(GrammarTopic.order).limit(4).all()

    # Related vocabulary words (same level, for cross-linking)
    from app.words.models import CollectionWords
    related_words = []
    if topic.get('level'):
        from sqlalchemy import func as sqla_func
        related_words = (
            CollectionWords.query
            .filter(CollectionWords.level == topic['level'])
            .order_by(sqla_func.random())
            .limit(4)
            .all()
        )

    return render_template(
        'grammar_lab/topic_detail.html',
        topic=topic,
        meta_description=meta_description,
        related_topics=related_topics,
        related_words=related_words,
        prev_topic=adjacent['prev'],
        next_topic=adjacent['next'],
    )


@grammar_lab_bp.route('/practice')
@grammar_lab_bp.route('/practice/topic/<int:topic_id>')
@login_required
def practice(topic_id=None):
    """
    Unified practice page.

    - /practice - SRS practice (mixed topics)
    - /practice/topic/<id> - Practice for specific topic
    """
    topic = None

    # return_url: after practice completion, redirect here (e.g., back to book course lesson)
    # Validate return_url to prevent open redirect attacks (including backslash tricks)
    from app.auth.routes import get_safe_redirect_url
    raw_return_url = request.args.get('return_url', '')
    return_url = get_safe_redirect_url(raw_return_url, fallback='grammar_lab.topics') if raw_return_url else ''

    if topic_id:
        # Topic-specific practice
        topic = grammar_service.get_topic_detail(topic_id, current_user.id)
        if not topic:
            return redirect(url_for('grammar_lab.topics'))

        session = grammar_service.start_topic_practice(topic_id, current_user.id)
    else:
        # SRS mixed practice
        session = grammar_service.get_practice_session(current_user.id, count=10)

    return render_template(
        'grammar_lab/practice.html',
        session=session,
        topic=topic,
        return_url=return_url
    )


@grammar_lab_bp.route('/stats')
@login_required
def stats():
    """User stats page"""
    user_stats = grammar_service.get_user_stats(current_user.id)
    levels = grammar_service.get_levels_summary(current_user.id)

    return render_template(
        'grammar_lab/stats.html',
        stats=user_stats,
        levels=levels
    )


# ============ JSON API ============

@grammar_lab_bp.route('/api/topics')
@login_required
def api_topics():
    """GET: List of topics with progress"""
    level = request.args.get('level')
    topics_list = grammar_service.get_topics_by_level(level, current_user.id)
    return jsonify(topics_list)


@grammar_lab_bp.route('/api/levels')
@login_required
def api_levels():
    """GET: Levels summary with progress"""
    levels = grammar_service.get_levels_summary(current_user.id)
    return jsonify(levels)


@grammar_lab_bp.route('/api/topic/<int:topic_id>')
@login_required
def api_topic_detail(topic_id):
    """GET: Topic detail with exercises"""
    topic = grammar_service.get_topic_detail(topic_id, current_user.id)
    if not topic:
        return jsonify({'error': 'Topic not found'}), 404
    return jsonify(topic)


@grammar_lab_bp.route('/api/topic/<int:topic_id>/exercises')
@login_required
def api_topic_exercises(topic_id):
    """GET: Exercises for a topic"""
    topic = GrammarTopic.query.get(topic_id)
    if not topic:
        return jsonify({'error': 'Topic not found'}), 404

    exercises = GrammarExercise.query.filter_by(topic_id=topic_id).order_by(
        GrammarExercise.order,
        GrammarExercise.difficulty
    ).all()

    return jsonify([e.to_dict(hide_answer=True) for e in exercises])


@grammar_lab_bp.route('/api/topic/<int:topic_id>/start-practice', methods=['POST'])
@login_required
def api_start_practice(topic_id):
    """POST: Start practice session for a topic"""
    result = grammar_service.start_topic_practice(topic_id, current_user.id)
    return jsonify(result)


@grammar_lab_bp.route('/api/exercise/<int:exercise_id>/submit', methods=['POST'])
@login_required
def api_submit_answer(exercise_id):
    """POST: Submit exercise answer"""
    data = request.get_json()

    if not data or 'answer' not in data:
        return jsonify({'error': 'Answer required'}), 400

    result = grammar_service.submit_answer(
        exercise_id=exercise_id,
        user_id=current_user.id,
        answer=data['answer'],
        session_id=data.get('session_id'),
        source=data.get('source', 'topic_practice'),
        time_spent=data.get('time_spent')
    )

    return jsonify(result)


@grammar_lab_bp.route('/api/topic/<int:topic_id>/complete-theory', methods=['POST'])
@login_required
def api_complete_theory(topic_id):
    """POST: Mark theory as completed"""
    result = grammar_service.complete_theory(topic_id, current_user.id)
    return jsonify(result)


@grammar_lab_bp.route('/api/practice/session', methods=['POST'])
@login_required
def api_create_practice_session():
    """POST: Create SRS practice session"""
    data = request.get_json() or {}

    result = grammar_service.get_practice_session(
        user_id=current_user.id,
        topic_ids=data.get('topic_ids'),
        count=data.get('count', 10),
        include_new=data.get('include_new', True)
    )

    return jsonify(result)


@grammar_lab_bp.route('/api/stats')
@login_required
def api_stats():
    """GET: User stats"""
    stats = grammar_service.get_user_stats(current_user.id)
    return jsonify(stats)


@grammar_lab_bp.route('/api/recommendations')
@login_required
def api_recommendations():
    """GET: Recommended topics"""
    limit = request.args.get('limit', 5, type=int)
    recommendations = grammar_service.get_recommendations(current_user.id, limit)
    return jsonify(recommendations)


@grammar_lab_bp.route('/api/due-topics')
@login_required
def api_due_topics():
    """GET: Topics due for review"""
    limit = request.args.get('limit', 10, type=int)
    due_topics = grammar_service.srs.get_due_topics(current_user.id, limit)
    return jsonify([t.to_dict() for t in due_topics])


# ============ Unified SRS Stats API ============

@grammar_lab_bp.route('/api/srs-stats')
@login_required
def api_srs_stats():
    """
    GET: Unified SRS stats for grammar exercises.

    Query params:
        topic_id: Optional topic filter
        level: Optional CEFR level filter (A1, A2, etc.)

    Returns:
        {
            'new_count': int,
            'learning_count': int,
            'review_count': int,
            'mastered_count': int,
            'total': int,
            'due_today': int
        }
    """
    topic_id = request.args.get('topic_id', type=int)
    level = request.args.get('level')

    if topic_id:
        stats = _get_srs_stats_service().get_grammar_stats(current_user.id, topic_id=topic_id)
    elif level:
        stats = _get_srs_stats_service().get_grammar_stats(current_user.id, level=level)
    else:
        stats = _get_srs_stats_service().get_grammar_stats(current_user.id)

    return jsonify(stats)


@grammar_lab_bp.route('/api/topics-srs-stats')
@login_required
def api_topics_srs_stats():
    """
    GET: SRS stats for all grammar topics.

    Query params:
        level: Optional CEFR level filter

    Returns:
        List of topic dicts with SRS stats
    """
    level = request.args.get('level')
    topics_stats = _get_srs_stats_service().get_grammar_topics_stats(current_user.id, level=level)
    return jsonify(topics_stats)


@grammar_lab_bp.route('/api/exercise/<int:exercise_id>/srs-info')
@login_required
def api_exercise_srs_info(exercise_id):
    """
    GET: SRS info for a specific exercise.

    Returns:
        Exercise SRS state and scheduling info
    """
    exercise = GrammarExercise.query.get(exercise_id)
    if not exercise:
        return jsonify({'error': 'Exercise not found'}), 404

    progress = UserGrammarExercise.query.filter_by(
        user_id=current_user.id,
        exercise_id=exercise_id
    ).first()

    if not progress:
        return jsonify({
            'state': 'new',
            'interval': 0,
            'lapses': 0,
            'is_due': True,
            'ease_factor': 2.5,
            'repetitions': 0
        })

    return jsonify(progress.to_dict())


@grammar_lab_bp.route('/api/topics', methods=['POST'])
@login_required
def api_create_topic():
    """
    POST: Create a new grammar topic (admin use).

    Request body (JSON):
        slug: str - unique slug identifier
        title: str - English title
        title_ru: str - Russian title
        level: str - CEFR level (A1-C2)
        order: int - display order (default 0)
        estimated_time: int - minutes (default 15)
        difficulty: int - 1-5 (default 1)
        content: dict - topic content (optional)

    Returns:
        201 with topic dict on success
        409 {'error': 'slug_taken', 'suggestion': '...'} on duplicate slug
        400 on missing required fields
        403 if user is not admin
    """
    if not getattr(current_user, 'is_admin', False):
        return jsonify({'error': 'admin access required'}), 403

    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 415

    data = request.get_json()
    slug = (data.get('slug') or '').strip()
    title = (data.get('title') or '').strip()

    if not slug or not title:
        return jsonify({'error': 'slug and title are required'}), 400

    try:
        order = int(data.get('order', 0))
        estimated_time = int(data.get('estimated_time', 15))
        difficulty = int(data.get('difficulty', 1))
    except (ValueError, TypeError):
        return jsonify({'error': 'order, estimated_time, and difficulty must be integers'}), 400

    topic = GrammarTopic(
        slug=slug,
        title=title,
        title_ru=(data.get('title_ru') or '').strip(),
        level=data.get('level', 'A1'),
        order=order,
        estimated_time=estimated_time,
        difficulty=difficulty,
        content=data.get('content') or {},
    )
    db.session.add(topic)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        logger.warning("Duplicate slug '%s' on grammar topic API create", slug)
        suggestion = f'{slug}_2'
        return jsonify({
            'error': 'slug_taken',
            'message': f'Slug "{slug}" is already taken.',
            'suggestion': suggestion,
        }), 409

    return jsonify(topic.to_dict()), 201
