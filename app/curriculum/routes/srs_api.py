# app/curriculum/routes/srs_api.py

import logging
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.curriculum.book_courses import BookCourseEnrollment
from app.curriculum.daily_lessons import DailyLesson
from app.curriculum.services.book_srs_integration import BookSRSIntegration

logger = logging.getLogger(__name__)

# Create blueprint for SRS API routes
srs_api_bp = Blueprint('srs_api', __name__)


@srs_api_bp.route('/api/v1/srs/session')
@login_required
def get_srs_session():
    """
    GET /api/v1/srs/session?lesson_id=:id 
    → { deck:[{card_id,front,back,phase,new}], session_key }
    
    Согласно детальному плану 3.2.2 Anki-card
    """
    try:
        lesson_id = request.args.get('lesson_id', type=int)
        if not lesson_id:
            return jsonify({'error': 'lesson_id parameter required'}), 400

        # Получаем daily lesson
        daily_lesson = DailyLesson.query.get_or_404(lesson_id)

        # Проверяем enrollment пользователя
        enrollment = BookCourseEnrollment.query.filter_by(
            user_id=current_user.id,
            course_id=daily_lesson.module.course_id
        ).first()

        if not enrollment:
            return jsonify({'error': 'User not enrolled in this course'}), 403

        # Создаем SRS сессию
        srs_integration = BookSRSIntegration()
        session_data = srs_integration.create_srs_session_for_lesson(
            user_id=current_user.id,
            daily_lesson=daily_lesson,
            enrollment=enrollment
        )

        if not session_data['session_key']:
            return jsonify({'error': 'No cards available for review'}), 404

        return jsonify(session_data)

    except Exception as e:
        logger.error(f"Error creating SRS session: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@srs_api_bp.route('/api/v1/srs/grade', methods=['POST'])
@login_required
def grade_card():
    """
    POST /api/v1/srs/grade {card_id,grade,session_key}
    
    Система оценок согласно детальному плану:
    0 (Again): "Не помню" - сброс прогресса
    1-2: Неправильный ответ
    3 (Hard): Правильно, но сложно  
    4 (Good): Стандартный правильный ответ
    5 (Easy): Легкий ответ
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'JSON data required'}), 400

        card_id = data.get('card_id')
        grade = data.get('grade')
        session_key = data.get('session_key')

        if card_id is None or grade is None or session_key is None:
            return jsonify({'error': 'card_id, grade, and session_key are required'}), 400

        if not isinstance(grade, int) or grade < 0 or grade > 5:
            return jsonify({'error': 'grade must be integer from 0 to 5'}), 400

        # Обрабатываем оценку карточки
        srs_integration = BookSRSIntegration()
        result = srs_integration.process_card_grade(
            user_id=current_user.id,
            card_id=card_id,
            grade=grade,
            session_key=session_key
        )

        if not result['success']:
            return jsonify(result), 400

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error grading card: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@srs_api_bp.route('/api/v1/srs/session/complete', methods=['POST'])
@login_required
def complete_srs_session():
    """
    POST /api/v1/srs/session/complete {session_key, lesson_id, stats}
    
    Завершает SRS сессию и сохраняет статистику
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'JSON data required'}), 400

        session_key = data.get('session_key')
        lesson_id = data.get('lesson_id')
        stats = data.get('stats', {})

        if not session_key or not lesson_id:
            return jsonify({'error': 'session_key and lesson_id are required'}), 400

        # Завершаем сессию
        srs_integration = BookSRSIntegration()
        success = srs_integration.complete_srs_session(
            user_id=current_user.id,
            daily_lesson_id=lesson_id,
            session_key=session_key,
            session_stats=stats
        )

        if not success:
            return jsonify({'error': 'Failed to complete session'}), 500

        return jsonify({
            'success': True,
            'message': 'SRS session completed successfully'
        })

    except Exception as e:
        logger.error(f"Error completing SRS session: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@srs_api_bp.route('/api/v1/srs/due-count')
@login_required
def get_due_cards_count():
    """
    GET /api/v1/srs/due-count
    
    Возвращает количество карточек, готовых к повторению
    """
    try:
        srs_integration = BookSRSIntegration()
        due_count = srs_integration.get_due_cards_count(current_user.id)

        return jsonify({
            'due_count': due_count,
            'has_due_cards': due_count > 0
        })

    except Exception as e:
        logger.error(f"Error getting due cards count: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@srs_api_bp.route('/api/v1/srs/next-session-time')
@login_required
def get_next_session_time():
    """
    GET /api/v1/srs/next-session-time?course_id=:id
    
    Возвращает время следующей SRS сессии
    """
    try:
        course_id = request.args.get('course_id', type=int)

        srs_integration = BookSRSIntegration()
        next_time = srs_integration.get_next_srs_session_time(
            user_id=current_user.id,
            course_id=course_id
        )

        return jsonify({
            'next_session_time': next_time.isoformat() if next_time else None,
            'has_session_due': next_time <= datetime.now() if next_time else False
        })

    except Exception as e:
        logger.error(f"Error getting next session time: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@srs_api_bp.route('/api/v1/lesson/<int:lesson_id>/create-srs-cards', methods=['POST'])
@login_required
def create_srs_cards_for_lesson():
    """
    POST /api/v1/lesson/:id/create-srs-cards
    
    Создает SRS карточки для vocabulary урока
    """
    try:
        lesson_id = request.args.get('lesson_id', type=int)

        daily_lesson = DailyLesson.query.get_or_404(lesson_id)

        # Проверяем что это vocabulary урок
        if daily_lesson.lesson_type != 'vocabulary':
            return jsonify({'error': 'Can only create SRS cards for vocabulary lessons'}), 400

        # Проверяем enrollment
        enrollment = BookCourseEnrollment.query.filter_by(
            user_id=current_user.id,
            course_id=daily_lesson.module.course_id
        ).first()

        if not enrollment:
            return jsonify({'error': 'User not enrolled in this course'}), 403

        # Создаем SRS карточки
        srs_integration = BookSRSIntegration()
        success = srs_integration.auto_create_srs_cards_from_vocabulary_lesson(
            user_id=current_user.id,
            daily_lesson=daily_lesson
        )

        if not success:
            return jsonify({'error': 'Failed to create SRS cards'}), 500

        return jsonify({
            'success': True,
            'message': 'SRS cards created successfully'
        })

    except Exception as e:
        logger.error(f"Error creating SRS cards for lesson: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


# Webhook для автоматического создания SRS карточек после vocabulary урока
@srs_api_bp.route('/api/v1/lesson/<int:lesson_id>/completed', methods=['POST'])
@login_required
def on_lesson_completed(lesson_id):
    """
    Webhook вызывается при завершении урока
    Автоматически создает SRS карточки для vocabulary уроков
    """
    try:
        daily_lesson = DailyLesson.query.get_or_404(lesson_id)

        # Если это vocabulary урок, создаем SRS карточки
        if daily_lesson.lesson_type == 'vocabulary':
            srs_integration = BookSRSIntegration()
            srs_integration.auto_create_srs_cards_from_vocabulary_lesson(
                user_id=current_user.id,
                daily_lesson=daily_lesson
            )

            logger.info(f"Auto-created SRS cards for vocabulary lesson {lesson_id}")

        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"Error in lesson completion webhook: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
