# app/grammar_lab/routes.py
"""
Routes for Grammar Lab module.

Provides both HTML pages and JSON API endpoints.
"""

from flask import render_template, jsonify, request, redirect, url_for
from flask_login import login_required, current_user
import logging

from app.grammar_lab import grammar_lab_bp
from app.grammar_lab.models import GrammarTopic, GrammarExercise
from app.grammar_lab.services import GrammarLabService

logger = logging.getLogger(__name__)

# Initialize service
grammar_service = GrammarLabService()


# ============ HTML Pages ============

@grammar_lab_bp.route('/')
@login_required
def index():
    """Grammar Lab home page"""
    levels = grammar_service.get_levels_summary(current_user.id)
    recommendations = grammar_service.get_recommendations(current_user.id, limit=5)
    stats = grammar_service.get_user_stats(current_user.id)

    return render_template(
        'grammar_lab/index.html',
        levels=levels,
        recommendations=recommendations,
        stats=stats
    )


@grammar_lab_bp.route('/topics')
@grammar_lab_bp.route('/topics/<level>')
@login_required
def topics(level=None):
    """Topics listing page, optionally filtered by level"""
    topics_list = grammar_service.get_topics_by_level(level, current_user.id)
    levels = grammar_service.get_levels_summary(current_user.id)

    return render_template(
        'grammar_lab/topics.html',
        topics=topics_list,
        levels=levels,
        current_level=level
    )


@grammar_lab_bp.route('/topic/<int:topic_id>')
@login_required
def topic_detail(topic_id):
    """Topic detail page with theory and exercises"""
    topic = grammar_service.get_topic_detail(topic_id, current_user.id)

    if not topic:
        return redirect(url_for('grammar_lab.topics'))

    return render_template(
        'grammar_lab/topic_detail.html',
        topic=topic
    )


@grammar_lab_bp.route('/practice')
@login_required
def practice():
    """SRS practice page (mixed topics)"""
    session = grammar_service.get_practice_session(current_user.id, count=10)

    return render_template(
        'grammar_lab/practice.html',
        session=session
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
