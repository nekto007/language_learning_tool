# app/grammar_lab/routes.py
"""
Routes for Grammar Lab module.

Provides both HTML pages and JSON API endpoints.
Uses UnifiedSRSService for Anki-like spaced repetition.
"""

import logging
from typing import Any
from uuid import uuid4

from flask import Response, abort, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app import limiter
from app.curriculum.routes.public import PUBLIC_CEFR_CODES
from app.grammar_lab import grammar_lab_bp
from app.grammar_lab.models import GrammarExercise, GrammarTopic, UserGrammarExercise
from app.grammar_lab.services import GrammarLabService
from app.grammar_lab.theory_schema import THEORY_CELL_ORDER as _THEORY_CELL_ORDER
from app.utils.db import db
from app.utils.rate_limit_helpers import get_authenticated_user_key

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


@grammar_lab_bp.route('/topics/')
def topics_trailing_slash():
    """Redirect the trailing-slash variant to the canonical no-slash URL (SEO)."""
    return redirect(url_for('grammar_lab.topics'), code=301)


@grammar_lab_bp.route('/topics')
@grammar_lab_bp.route('/topics/<level>')
def topics(level=None):
    """Topics listing page — public, with progress for authenticated users"""
    if level:
        level_norm = level.upper()
        if level_norm not in PUBLIC_CEFR_CODES:
            abort(404)
        # Canonical level path is lowercase — 301 non-canonical casing.
        if level != level.lower():
            return redirect(url_for('grammar_lab.topics', level=level.lower()), code=301)
        level = level_norm

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
def topic_detail_legacy(topic_id):
    """Legacy ID-based URL. 301-redirect to slug URL for SEO."""
    topic = GrammarTopic.query.get(topic_id)
    if not topic:
        abort(404)
    return redirect(
        url_for('grammar_lab.topic_detail', slug=topic.slug, **request.args.to_dict()),
        code=301,
    )


# JSONB stores object keys sorted by length, not in authored order, so a theory
# row {pronoun, form, example, translation} comes back as form, example,
# pronoun, translation. Cells are re-ordered before rendering: label-like
# keys first, then example and translation, then anything else as stored
# (lesson audit item 21, Codex review).



def _order_theory_cells(content):
    """Return ``content`` with every section-table row rebuilt in
    ``_THEORY_CELL_ORDER`` (non-mapping rows and non-dict content untouched)."""
    if not isinstance(content, dict):
        return content
    sections = content.get('sections')
    if not isinstance(sections, list):
        return content
    for section in sections:
        table = section.get('table') if isinstance(section, dict) else None
        if not isinstance(table, list):
            continue
        ordered_rows = []
        for row in table:
            if not isinstance(row, dict):
                ordered_rows.append(row)
                continue
            ordered = {}
            for key in _THEORY_CELL_ORDER:
                if key == 'example' and 'translation' in row and 'example_translation' in row:
                    ordered['translation'] = row['translation']
                if key in row:
                    ordered[key] = row[key]
                if key == 'example' and 'translation' in row and 'translation' not in ordered:
                    ordered['translation'] = row['translation']
            ordered.update({key: value for key, value in row.items() if key not in ordered})
            ordered_rows.append(ordered)
        section['table'] = ordered_rows
    return content


@grammar_lab_bp.route('/topic/<slug>')
def topic_detail(slug):
    """Topic detail page with theory — public, exercises require auth"""
    topic_row = GrammarTopic.query.filter_by(slug=slug).first()
    if not topic_row:
        abort(404)

    topic_id = topic_row.id
    user_id = current_user.id if current_user.is_authenticated else None
    topic = grammar_service.get_topic_detail(topic_id, user_id)

    if not topic:
        abort(404)

    # Hide legacy/non-public CEFR topics: their related CTAs (/courses/<level>,
    # /grammar-lab/topics/<level>) and related-word links 404 downstream.
    if topic.get('level') not in PUBLIC_CEFR_CODES:
        abort(404)

    _order_theory_cells(topic.get('content'))
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

    from app.auth.routes import get_safe_redirect_url
    raw_return_url = request.args.get('return_url', '')
    return_url = get_safe_redirect_url(raw_return_url, fallback='grammar_lab.topics') if raw_return_url else ''

    return render_template(
        'grammar_lab/topic_detail.html',
        topic=topic,
        meta_description=meta_description,
        related_topics=related_topics,
        related_words=related_words,
        prev_topic=adjacent['prev'],
        next_topic=adjacent['next'],
        return_url=return_url,
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
        session = grammar_service.start_topic_practice(topic_id, current_user.id, reset_session_attempts=False)
        topic = session.get('topic')
        if not topic:
            return redirect(url_for('grammar_lab.topics'))
    else:
        # SRS mixed practice
        session = grammar_service.get_practice_session(current_user.id, count=10)

    session.setdefault('exercises', [])
    session.setdefault('total_exercises', len(session['exercises']))
    session.setdefault('exercise_revisions', {})
    for exercise in session['exercises']:
        exercise['submission_id'] = str(uuid4())
    response = Response(render_template(
        'grammar_lab/practice.html',
        session=session,
        topic=topic,
        return_url=return_url
    ))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


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
    from app.grammar_lab.exercise_visibility import active_exercise_clause

    topic = GrammarTopic.query.get(topic_id)
    if not topic:
        return jsonify({'error': 'Topic not found'}), 404

    exercises = GrammarExercise.query.filter_by(topic_id=topic_id).filter(active_exercise_clause()).order_by(
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
def api_submit_answer(exercise_id: int) -> Response | tuple[Response, int]:
    """POST: Submit exercise answer"""
    from app.grammar_lab.answer_review import lab_revision
    from app.grammar_lab.dispute_receipts import issue_rejection_receipt, normalized_lab_answer

    data = request.get_json()

    if not isinstance(data, dict):
        return jsonify({'error': 'Answer required'}), 400

    if 'submission_id' in data or 'exercise_revision' in data:
        from app.api.native_lessons import NativeLessonError
        from app.grammar_lab.submissions import submit_once

        try:
            result = submit_once(grammar_service, current_user.id, exercise_id, data)
        except NativeLessonError as error:
            db.session.rollback()
            if error.status >= 500:
                logger.warning('Idempotent grammar submission failed for exercise %s', exercise_id, exc_info=True)
            return jsonify(error=error.code, code=error.code), error.status
        except Exception:
            db.session.rollback()
            logger.exception('Idempotent grammar submission failed for exercise %s', exercise_id)
            return jsonify(error='grading_failed', code='grading_failed'), 503
        response = jsonify(result)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    if 'answer' not in data:
        return jsonify({'error': 'Answer required'}), 400
    exercise = GrammarExercise.query.get(exercise_id)
    if not exercise:
        return jsonify({'error': 'Exercise not found'}), 404
    if (exercise.content or {}).get('guided_retired'):
        return jsonify({'error': 'Упражнение обновлено. Открой актуальную практику.',
                        'code': 'lesson_changed'}), 409

    answer = data['answer']
    # Capture the revision on the ORM instance used by the grader, before its
    # commit expires that instance and a subsequent lookup could see edits.
    revision = lab_revision(exercise)
    disputable = normalized_lab_answer(exercise, answer) is not None
    result = grammar_service.submit_answer(
        exercise_id=exercise_id,
        user_id=current_user.id,
        answer=answer,
        session_id=data.get('session_id'),
        source=data.get('source', 'topic_practice'),
        time_spent=data.get('time_spent')
    )

    if disputable and result.get('is_correct') is False and not result.get('error'):
        result['dispute_token'] = issue_rejection_receipt(current_user.id, exercise_id, revision, answer)
    response = jsonify(result)
    if 'dispute_token' in result:
        response.headers['Cache-Control'] = 'private, no-store'
    return response


@grammar_lab_bp.post('/api/exercise/<int:exercise_id>/dispute')
@login_required
@limiter.limit('10 per minute', key_func=get_authenticated_user_key)
def api_answer_dispute(exercise_id: int) -> Response:
    from app.api.native_lessons import NativeLessonError, native_error
    from app.curriculum.answer_disputes import record_lab_rejected_answer
    from app.grammar_lab.dispute_receipts import read_rejection_receipt, verify_rejected_answer

    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != {'dispute_token', 'answer'}:
            raise NativeLessonError('invalid_input')
        claims = read_rejection_receipt(data['dispute_token'], current_user.id, exercise_id)
        exercise = GrammarExercise.query.filter_by(id=exercise_id).populate_existing().one_or_none()
        if exercise is None:
            raise NativeLessonError('not_found', 404)
        if (exercise.content or {}).get('guided_retired'):
            raise NativeLessonError('lesson_changed', 409)
        answer = data['answer']
        normalized = verify_rejected_answer(claims, exercise, answer)
        record_lab_rejected_answer(db.session, exercise, answer, normalized)
        db.session.commit()
        response = jsonify(success=True)
    except NativeLessonError as error:
        body, status = native_error(error)
        response = body
        response.status_code = status
    response.headers['Cache-Control'] = 'private, no-store'
    return response


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
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return jsonify(error='invalid_input'), 400
    if data.get('mode') == 'resume':
        result, status = _resume_practice_session(data, current_user.id)
        response = jsonify(result)
        response.headers['Cache-Control'] = 'private, no-store'
        return response, status
    if 'mode' in data:
        return jsonify(error='invalid_input'), 400

    result = grammar_service.get_practice_session(
        user_id=current_user.id,
        topic_ids=data.get('topic_ids'),
        count=data.get('count', 10),
        include_new=data.get('include_new', True)
    )

    return jsonify(result)


def _resume_practice_session(data: dict[str, Any], user_id: int) -> tuple[dict[str, Any], int]:
    """Validate a small saved mixed queue without sampling or changing its SRS."""
    import re
    from sqlalchemy.orm import joinedload
    from app.grammar_lab.answer_review import lab_revision
    from app.grammar_lab.exercise_visibility import active_exercise_clause

    if set(data) != {'mode', 'account_id', 'session_id', 'items'}:
        return {'error': 'invalid_input'}, 400
    if data['account_id'] != str(user_id):
        return {'error': 'account_changed'}, 403
    key, items = data['session_id'], data['items']
    if (not isinstance(key, str) or not 0 < len(key) <= 100
            or any(ord(char) < 32 for char in key)
            or not isinstance(items, list) or not 1 <= len(items) <= 10):
        return {'error': 'invalid_input'}, 400
    for item in items:
        if (not isinstance(item, dict) or set(item) != {'id', 'revision'}
                or type(item['id']) is not int or not 0 < item['id'] <= 2**31 - 1
                or not isinstance(item['revision'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', item['revision'])):
            return {'error': 'invalid_input'}, 400
    ids = [item['id'] for item in items]
    if len(set(ids)) != len(ids):
        return {'error': 'invalid_input'}, 400
    rows = GrammarExercise.query.options(
        joinedload(GrammarExercise.topic).load_only(GrammarTopic.title)
    ).filter(GrammarExercise.id.in_(ids), active_exercise_clause()).populate_existing().all()
    by_id = {row.id: row for row in rows}
    if len(by_id) != len(ids):
        return {'error': 'lesson_changed', 'code': 'lesson_changed'}, 409
    revisions = {row.id: lab_revision(row) for row in rows}
    if any(revisions[item['id']] != item['revision'] for item in items):
        return {'error': 'lesson_changed', 'code': 'lesson_changed'}, 409
    exercises = []
    for item_id in ids:
        row = by_id[item_id]
        exercises.append({**row.to_dict(hide_answer=True), 'topic_title': row.topic.title if row.topic else None,
                          'submission_id': str(uuid4())})
    return {'account_id': str(user_id), 'session_id': key, 'exercises': exercises,
            'exercise_revisions': revisions, 'total_exercises': len(exercises)}, 200


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
        level: str - CEFR level (A1-C1)
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
