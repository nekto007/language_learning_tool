# app/curriculum/routes/lessons.py

import logging
from datetime import UTC, datetime

from flask import Blueprint, flash, jsonify, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm.attributes import flag_modified

from app.curriculum.models import LessonProgress, Lessons
from app.curriculum.security import require_lesson_access, sanitize_json_content
from app.curriculum.service import (
    process_final_test_submission, process_grammar_submission,
    process_matching_submission, process_quiz_submission,
)
from app.curriculum.validators import ProgressUpdateSchema, validate_request_data
from app.utils.db import db

logger = logging.getLogger(__name__)

lessons_bp = Blueprint('curriculum_lessons', __name__)


@lessons_bp.route('/lesson/<int:lesson_id>')
@login_required
@require_lesson_access
def lesson_detail(lesson_id):
    """Display lesson details and route to appropriate lesson type"""
    lesson = Lessons.query.get_or_404(lesson_id)

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    if not progress:
        try:
            progress = LessonProgress(
                user_id=current_user.id,
                lesson_id=lesson.id,
                status='in_progress',
                started_at=datetime.now(UTC),
                last_activity=datetime.now(UTC)
            )
            db.session.add(progress)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error creating lesson progress: {str(e)}")
            db.session.rollback()
            flash('Ошибка при создании прогресса урока', 'error')
            return redirect('/learn/')
    else:
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

    route_map = {
        'vocabulary': 'curriculum_lessons.vocabulary_lesson',
        'grammar': 'curriculum_lessons.grammar_lesson',
        'matching': 'curriculum_lessons.matching_lesson',
        'text': 'curriculum_lessons.text_lesson',
        'reading': 'curriculum_lessons.text_lesson',
        'card': 'curriculum_lessons.card_lesson',
        'flashcards': 'curriculum_lessons.card_lesson',
        'listening_immersion': 'curriculum_lessons.text_lesson',
        'final_test': 'curriculum_lessons.final_test_lesson',
        'ordering_quiz': 'curriculum_lessons.quiz_lesson',
        'translation_quiz': 'curriculum_lessons.quiz_lesson',
        'listening_quiz': 'curriculum_lessons.quiz_lesson',
        'dialogue_completion_quiz': 'curriculum_lessons.quiz_lesson',
        'listening_immersion_quiz': 'curriculum_lessons.text_lesson',
        'quiz': 'curriculum_lessons.quiz_lesson',
    }

    route_name = route_map.get(lesson.type)
    if route_name:
        return redirect(url_for(route_name, lesson_id=lesson.id))
    else:
        flash(f'Неизвестный тип урока: {lesson.type}', 'error')
        return redirect('/learn/')


@lessons_bp.route('/api/lesson/<int:lesson_id>/progress', methods=['POST'])
@login_required
@require_lesson_access
def update_lesson_progress(lesson_id):
    """Update lesson progress with validation"""
    try:
        if request.is_json:
            data = request.get_json()
            if 'csrf_token' in data:
                del data['csrf_token']
        else:
            data = {}
            if 'status' in request.form:
                data['status'] = request.form['status']
            if 'score' in request.form:
                try:
                    data['score'] = float(request.form['score'])
                except (ValueError, TypeError):
                    data['score'] = 0.0
            if 'reading_time' in request.form:
                try:
                    data['reading_time'] = int(request.form['reading_time'])
                except (ValueError, TypeError):
                    data['reading_time'] = 0

        is_valid, error_msg, cleaned_data = validate_request_data(
            ProgressUpdateSchema, data
        )

        if not is_valid:
            return jsonify({'success': False, 'error': error_msg}), 400

        progress = LessonProgress.query.filter_by(
            user_id=current_user.id,
            lesson_id=lesson_id
        ).first()

        if not progress:
            progress = LessonProgress(
                user_id=current_user.id,
                lesson_id=lesson_id
            )
            db.session.add(progress)

        if 'status' in cleaned_data:
            progress.status = cleaned_data['status']

        if 'score' in cleaned_data:
            progress.score = round(cleaned_data['score'], 2)

        if 'data' in cleaned_data:
            progress.data = sanitize_json_content(cleaned_data['data'])

        if 'reading_time' in cleaned_data:
            if not progress.data:
                progress.data = {}
            progress.data['reading_time'] = cleaned_data['reading_time']

        if 'comprehension_results' in cleaned_data:
            if not progress.data:
                progress.data = {}
            progress.data['comprehension'] = cleaned_data['comprehension_results']
            flag_modified(progress, 'data')

        progress.last_activity = datetime.now(UTC)

        if progress.status == 'completed' and not progress.completed_at:
            progress.completed_at = datetime.now(UTC)

        db.session.commit()

        if progress.status == 'completed':
            try:
                from app.daily_plan.linear.xp import maybe_award_curriculum_xp
                lesson_for_xp = Lessons.query.get(lesson_id)
                if lesson_for_xp:
                    maybe_award_curriculum_xp(
                        current_user.id, lesson_for_xp,
                        db_session=db,
                        score=progress.score,
                    )
                    db.session.commit()
            except Exception as xp_err:
                logger.warning(f"Linear XP award failed for lesson {lesson_id}: {xp_err}")

        completion_result = None
        if progress.status == 'completed' and progress.score is not None:
            try:
                from app.achievements.services import process_lesson_completion
                lesson = Lessons.query.get(lesson_id)
                completion_result = process_lesson_completion(
                    user_id=current_user.id,
                    lesson_id=lesson_id,
                    score=progress.score
                )
            except Exception as e:
                logger.error(f"Error processing lesson completion: {e}")

        response_data = {
            'success': True,
            'progress': {
                'status': progress.status,
                'score': progress.score,
                'completed_at': progress.completed_at.isoformat() if progress.completed_at else None
            }
        }

        if completion_result:
            response_data['grade'] = completion_result['grade']
            response_data['grade_name'] = completion_result['grade_name']
            response_data['new_achievements'] = completion_result['new_achievements']

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error updating lesson progress: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Server error'}), 500


@lessons_bp.route('/api/lesson/<int:lesson_id>/submit', methods=['POST'])
@login_required
@require_lesson_access
def submit_lesson(lesson_id):
    """Submit lesson answers with proper validation"""
    try:
        lesson = Lessons.query.get_or_404(lesson_id)
        data = request.get_json()

        if lesson.type == 'quiz':
            result = process_quiz_submission(lesson, current_user.id, data)
        elif lesson.type == 'grammar':
            result = process_grammar_submission(lesson, current_user.id, data)
        elif lesson.type == 'matching':
            result = process_matching_submission(lesson, current_user.id, data)
        elif lesson.type == 'final_test':
            result = process_final_test_submission(lesson, current_user.id, data)
        else:
            return jsonify({'success': False, 'error': 'Invalid lesson type'}), 400

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error submitting lesson: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Server error'}), 500


# Import route modules to register their routes on lessons_bp
import app.curriculum.routes.vocabulary_lessons  # noqa: E402, F401
import app.curriculum.routes.grammar_quiz_lessons  # noqa: E402, F401
import app.curriculum.routes.card_lessons  # noqa: E402, F401
