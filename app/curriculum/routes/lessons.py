# app/curriculum/routes/lessons.py

import logging
from datetime import UTC, datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
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
        'dictation': 'curriculum_lessons.dictation_lesson',
        'audio_fill_blank': 'curriculum_lessons.audio_fill_blank_lesson',
        'translation': 'curriculum_lessons.translation_lesson',
        'sentence_correction': 'curriculum_lessons.sentence_correction_lesson',
        'writing_prompt': 'curriculum_lessons.writing_prompt_lesson',
        'sentence_completion': 'curriculum_lessons.sentence_completion_lesson',
        'collocation_matching': 'curriculum_lessons.collocation_matching_lesson',
        'shadow_reading': 'curriculum_lessons.shadow_reading_lesson',
        'pronunciation': 'curriculum_lessons.pronunciation_lesson',
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
                from app.daily_plan.linear.xp import maybe_award_curriculum_xp, maybe_award_listening_xp
                lesson_for_xp = Lessons.query.get(lesson_id)
                if lesson_for_xp:
                    maybe_award_curriculum_xp(
                        current_user.id, lesson_for_xp,
                        db_session=db,
                        score=progress.score,
                    )
                    if lesson_for_xp.type in ('listening_immersion', 'listening_immersion_quiz'):
                        maybe_award_listening_xp(
                            current_user.id, lesson_for_xp.id,
                            score=progress.score,
                            db_session=db,
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
        elif lesson.type == 'dictation':
            result = _process_dictation_submission(lesson, current_user.id, data)
        elif lesson.type == 'audio_fill_blank':
            result = _process_audio_fill_blank_submission(lesson, current_user.id, data)
        elif lesson.type == 'translation':
            result = _process_translation_submission(lesson, current_user.id, data)
        elif lesson.type == 'sentence_correction':
            result = _process_sentence_correction_submission(lesson, current_user.id, data)
        elif lesson.type == 'writing_prompt':
            result = _process_writing_prompt_submission(lesson, current_user.id, data)
        elif lesson.type == 'sentence_completion':
            result = _process_sentence_completion_submission(lesson, current_user.id, data)
        elif lesson.type == 'collocation_matching':
            result = _process_collocation_matching_submission(lesson, current_user.id, data)
        elif lesson.type == 'shadow_reading':
            result = _process_shadow_reading_submission(lesson, current_user.id, data)
        elif lesson.type == 'pronunciation':
            result = _process_pronunciation_submission(lesson, current_user.id, data)
        else:
            return jsonify({'success': False, 'error': 'Invalid lesson type'}), 400

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error submitting lesson: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Server error'}), 500


_DICTATION_MAX_REPLAYS = 3


def _build_hint_text(transcript: str, hint_chars: int) -> str:
    """Return transcript with each word truncated to hint_chars visible chars, rest blanked."""
    if not hint_chars or not transcript:
        return ""
    words = transcript.split()
    result = []
    for word in words:
        visible = word[:hint_chars]
        blanks = "_" * max(0, len(word) - hint_chars)
        result.append(visible + blanks)
    return " ".join(result)


@lessons_bp.route('/lesson/<int:lesson_id>/dictation')
@login_required
@require_lesson_access
def dictation_lesson(lesson_id: int):
    """Display a dictation lesson."""
    lesson = Lessons.query.get_or_404(lesson_id)
    if lesson.type != 'dictation':
        flash('Неверный тип урока', 'error')
        return redirect('/learn/')

    content = lesson.content or {}
    audio_url = content.get('audio_url', '')
    transcript = content.get('transcript', '')
    hint_chars = int(content.get('hint_chars', 0))

    # Build pre-filled hint text shown in the textarea
    hint_text = _build_hint_text(transcript, hint_chars) if hint_chars > 0 else ""

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
                last_activity=datetime.now(UTC),
            )
            db.session.add(progress)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error creating dictation progress: {e}")
            db.session.rollback()

    return render_template(
        'curriculum/lessons/dictation.html',
        lesson=lesson,
        progress=progress,
        audio_url=audio_url,
        transcript=transcript,
        hint_chars=hint_chars,
        hint_text=hint_text,
        max_replays=_DICTATION_MAX_REPLAYS,
    )


def _process_dictation_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Grade a dictation submission, update progress, award XP, and return result."""
    from app.curriculum.grading import grade_dictation
    from app.curriculum.service import get_next_lesson
    from app.curriculum.services.progress_service import ProgressService
    from app.curriculum.listening_service import log_listening_attempt

    content = lesson.content or {}
    transcript = content.get('transcript', '')
    hint_chars = int(data.get('hint_chars', content.get('hint_chars', 0)))
    user_text = data.get('user_text', '')
    replay_count = int(data.get('replay_count', 0))

    grade = grade_dictation(user_text, transcript, hint_chars)

    progress, _ = ProgressService.update_progress_with_grading(
        user_id=user_id,
        lesson=lesson,
        result=grade,
        passing_score=80,
    )

    try:
        log_listening_attempt(user_id, lesson.id, grade['score'], replay_count, db)
        db.session.flush()
    except Exception as log_err:
        logger.warning(f"Listening attempt log failed for lesson {lesson.id}: {log_err}")

    try:
        from app.achievements.services import check_listening_achievements
        check_listening_achievements(user_id, db_session=db.session)
    except Exception as ach_err:
        logger.warning(f"Listening achievement check failed for user {user_id}: {ach_err}")

    if grade.get('passed'):
        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp, maybe_award_listening_xp
            maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=grade['score'])
            maybe_award_listening_xp(user_id, lesson.id, score=grade['score'], db_session=db)
            db.session.commit()
        except Exception as xp_err:
            logger.warning(f"Dictation XP award failed for lesson {lesson.id}: {xp_err}")

    result = {**grade, 'transcript': transcript if not grade.get('passed') else None}

    next_lesson = get_next_lesson(lesson.id)
    if grade.get('passed') and next_lesson:
        result['next_lesson_url'] = url_for(
            'curriculum_lessons.lesson_detail', lesson_id=next_lesson.id
        )

    return result


@lessons_bp.route('/lesson/<int:lesson_id>/audio-fill-blank')
@login_required
@require_lesson_access
def audio_fill_blank_lesson(lesson_id: int):
    """Display an audio fill-in-blank lesson."""
    lesson = Lessons.query.get_or_404(lesson_id)
    if lesson.type != 'audio_fill_blank':
        flash('Неверный тип урока', 'error')
        return redirect('/learn/')

    content = lesson.content or {}
    audio_url = content.get('audio_url', '')
    items = content.get('items', [])

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
                last_activity=datetime.now(UTC),
            )
            db.session.add(progress)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error creating audio_fill_blank progress: {e}")
            db.session.rollback()

    return render_template(
        'curriculum/lessons/audio_fill_blank.html',
        lesson=lesson,
        progress=progress,
        audio_url=audio_url,
        items=items,
    )


def _process_audio_fill_blank_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Grade an audio fill-in-blank submission, update progress, award XP, return result."""
    from app.curriculum.grading import grade_audio_fill_blank
    from app.curriculum.service import get_next_lesson
    from app.curriculum.services.progress_service import ProgressService
    from app.curriculum.listening_service import log_listening_attempt

    content = lesson.content or {}
    items = content.get('items', [])
    user_answers = data.get('answers', [])
    replay_count = int(data.get('replay_count', 0))

    grade = grade_audio_fill_blank(user_answers, items)

    progress, _ = ProgressService.update_progress_with_grading(
        user_id=user_id,
        lesson=lesson,
        result=grade,
        passing_score=70,
    )

    try:
        log_listening_attempt(user_id, lesson.id, grade['score'], replay_count, db)
        db.session.flush()
    except Exception as log_err:
        logger.warning(f"Listening attempt log failed for lesson {lesson.id}: {log_err}")

    try:
        from app.achievements.services import check_listening_achievements
        check_listening_achievements(user_id, db_session=db.session)
    except Exception as ach_err:
        logger.warning(f"Listening achievement check failed for user {user_id}: {ach_err}")

    if grade.get('passed'):
        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp, maybe_award_listening_xp
            maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=grade['score'])
            maybe_award_listening_xp(user_id, lesson.id, score=grade['score'], db_session=db)
            db.session.commit()
        except Exception as xp_err:
            logger.warning(f"Audio fill blank XP award failed for lesson {lesson.id}: {xp_err}")

    result = {**grade}
    next_lesson = get_next_lesson(lesson.id)
    if grade.get('passed') and next_lesson:
        result['next_lesson_url'] = url_for(
            'curriculum_lessons.lesson_detail', lesson_id=next_lesson.id
        )
    # Always include correct answers for client-side reveal on completion
    result['items'] = [
        {'answer': it.get('answer', ''), 'text_with_gap': it.get('text_with_gap', '')}
        for it in items
    ]

    return result


@lessons_bp.route('/lesson/<int:lesson_id>/translation')
@login_required
@require_lesson_access
def translation_lesson(lesson_id: int):
    """Display a standalone translation lesson."""
    lesson = Lessons.query.get_or_404(lesson_id)
    if lesson.type != 'translation':
        flash('Неверный тип урока', 'error')
        return redirect('/learn/')

    content = lesson.content or {}
    russian = content.get('russian', '')
    correct_answer = content.get('english', '')
    hint_words = content.get('hint_words') or []

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
                last_activity=datetime.now(UTC),
            )
            db.session.add(progress)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error creating translation progress: {e}")
            db.session.rollback()

    return render_template(
        'curriculum/lessons/translation.html',
        lesson=lesson,
        progress=progress,
        russian=russian,
        correct_answer=correct_answer,
        hint_words=hint_words,
    )


def _process_translation_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Grade a translation submission, update progress, award XP, return result."""
    from app.curriculum.grading import grade_translation
    from app.curriculum.service import get_next_lesson
    from app.curriculum.services.progress_service import ProgressService

    content = lesson.content or {}
    correct_answer = content.get('english', '')
    user_answer = data.get('user_answer', '')

    grade = grade_translation(user_answer, correct_answer)
    passed = grade['is_correct']

    # Build a progress-compatible result dict
    progress_result = {
        'passed': passed,
        'score': 100.0 if passed else 0.0,
    }

    ProgressService.update_progress_with_grading(
        user_id=user_id,
        lesson=lesson,
        result=progress_result,
        passing_score=100,
    )

    if passed:
        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp
            maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=100)
            db.session.commit()
        except Exception as xp_err:
            logger.warning(f"Translation XP award failed for lesson {lesson.id}: {xp_err}")

    result = {**grade}
    next_lesson = get_next_lesson(lesson.id)
    if passed and next_lesson:
        result['next_lesson_url'] = url_for(
            'curriculum_lessons.lesson_detail', lesson_id=next_lesson.id
        )

    return result


@lessons_bp.route('/lesson/<int:lesson_id>/sentence-correction')
@login_required
@require_lesson_access
def sentence_correction_lesson(lesson_id: int):
    """Display a sentence correction lesson."""
    lesson = Lessons.query.get_or_404(lesson_id)
    if lesson.type != 'sentence_correction':
        flash('Неверный тип урока', 'error')
        return redirect('/learn/')

    content = lesson.content or {}
    incorrect_sentence = content.get('incorrect_sentence', '')
    correct_sentence = content.get('correct_sentence', '')
    error_type = content.get('error_type', '')
    explanation = content.get('explanation', '')
    options = content.get('options') or []

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
                last_activity=datetime.now(UTC),
            )
            db.session.add(progress)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error creating sentence_correction progress: {e}")
            db.session.rollback()

    return render_template(
        'curriculum/lessons/sentence_correction.html',
        lesson=lesson,
        progress=progress,
        incorrect_sentence=incorrect_sentence,
        correct_sentence=correct_sentence,
        error_type=error_type,
        explanation=explanation,
        options=options,
    )


def _process_sentence_correction_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Grade a sentence correction submission, update progress, award XP, return result."""
    from app.curriculum.grading import grade_sentence_correction
    from app.curriculum.service import get_next_lesson
    from app.curriculum.services.progress_service import ProgressService

    content = lesson.content or {}
    correct_sentence = content.get('correct_sentence', '')
    explanation = content.get('explanation', '')
    user_answer = data.get('user_answer', '')

    grade = grade_sentence_correction(user_answer, correct_sentence)
    passed = grade['is_correct']

    progress_result = {
        'passed': passed,
        'score': 100.0 if passed else 0.0,
    }

    ProgressService.update_progress_with_grading(
        user_id=user_id,
        lesson=lesson,
        result=progress_result,
        passing_score=100,
    )

    if passed:
        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp
            maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=100)
            db.session.commit()
        except Exception as xp_err:
            logger.warning(f"Sentence correction XP award failed for lesson {lesson.id}: {xp_err}")

    result = {**grade, 'explanation': explanation}
    next_lesson = get_next_lesson(lesson.id)
    if passed and next_lesson:
        result['next_lesson_url'] = url_for(
            'curriculum_lessons.lesson_detail', lesson_id=next_lesson.id
        )

    return result


_DEFAULT_WRITING_CHECKLIST = [
    'Использовал(а) новые слова',
    'Структура предложений правильная',
    'Нет пропущенных артиклей',
    'Нет ошибок во временах',
]


@lessons_bp.route('/lesson/<int:lesson_id>/writing-prompt')
@login_required
@require_lesson_access
def writing_prompt_lesson(lesson_id: int):
    """Display a writing prompt lesson."""
    lesson = Lessons.query.get_or_404(lesson_id)
    if lesson.type != 'writing_prompt':
        flash('Неверный тип урока', 'error')
        return redirect('/learn/')

    content = lesson.content or {}
    prompt = content.get('prompt', '')
    min_words = int(content.get('min_words', 50))
    example_response = content.get('example_response') or None
    checklist = content.get('checklist') or _DEFAULT_WRITING_CHECKLIST

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
                last_activity=datetime.now(UTC),
            )
            db.session.add(progress)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error creating writing_prompt progress: {e}")
            db.session.rollback()

    return render_template(
        'curriculum/lessons/writing_prompt.html',
        lesson=lesson,
        progress=progress,
        prompt=prompt,
        min_words=min_words,
        example_response=example_response,
        checklist=checklist,
    )


def _process_writing_prompt_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Save a writing prompt attempt, mark lesson complete, award XP, return result."""
    from app.curriculum.models import save_writing_attempt
    from app.curriculum.service import get_next_lesson

    content = lesson.content or {}
    example_response = content.get('example_response') or None
    response_text = (data.get('response_text') or '').strip()
    checklist_completed = bool(data.get('checklist_completed', False))
    checked_items = data.get('checked_items') or []
    min_words = int(content.get('min_words', 50))

    word_count = len(response_text.split()) if response_text else 0
    meets_min = word_count >= min_words

    try:
        save_writing_attempt(user_id, lesson.id, response_text, checklist_completed, db)
        db.session.flush()
    except Exception as save_err:
        logger.warning(f"Writing attempt save failed for lesson {lesson.id}: {save_err}")

    completed = meets_min and checklist_completed

    if completed:
        progress = LessonProgress.query.filter_by(
            user_id=user_id, lesson_id=lesson.id
        ).first()
        if progress:
            progress.status = 'completed'
            if not progress.completed_at:
                progress.completed_at = datetime.now(UTC)
            progress.last_activity = datetime.now(UTC)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        try:
            from app.daily_plan.linear.xp import (
                maybe_award_curriculum_xp,
                maybe_award_writing_xp,
            )
            maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=None)
            maybe_award_writing_xp(user_id, lesson.id, db_session=db)
            db.session.commit()
        except Exception as xp_err:
            logger.warning(f"Writing prompt XP award failed for lesson {lesson.id}: {xp_err}")

    result: dict = {
        'success': True,
        'completed': completed,
        'word_count': word_count,
        'meets_min_words': meets_min,
        'checklist_completed': checklist_completed,
    }
    if completed and example_response:
        result['example_response'] = example_response

    next_lesson = get_next_lesson(lesson.id)
    if completed and next_lesson:
        result['next_lesson_url'] = url_for(
            'curriculum_lessons.lesson_detail', lesson_id=next_lesson.id
        )

    return result


@lessons_bp.route('/lesson/<int:lesson_id>/sentence-completion')
@login_required
@require_lesson_access
def sentence_completion_lesson(lesson_id: int):
    """Display a sentence completion lesson."""
    lesson = Lessons.query.get_or_404(lesson_id)
    if lesson.type != 'sentence_completion':
        flash('Неверный тип урока', 'error')
        return redirect('/learn/')

    content = lesson.content or {}
    items = content.get('items', [])

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
                last_activity=datetime.now(UTC),
            )
            db.session.add(progress)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error creating sentence_completion progress: {e}")
            db.session.rollback()

    return render_template(
        'curriculum/lessons/sentence_completion.html',
        lesson=lesson,
        progress=progress,
        items=items,
    )


def _process_sentence_completion_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Grade a sentence completion submission, update progress, award XP, return result."""
    from app.curriculum.grading import grade_sentence_completion
    from app.curriculum.service import get_next_lesson
    from app.curriculum.services.progress_service import ProgressService

    content = lesson.content or {}
    items = content.get('items', [])
    user_answers = data.get('answers', [])

    grade = grade_sentence_completion(user_answers, items)

    ProgressService.update_progress_with_grading(
        user_id=user_id,
        lesson=lesson,
        result=grade,
        passing_score=70,
    )

    if grade.get('passed'):
        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp
            maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=grade['score'])
            db.session.commit()
        except Exception as xp_err:
            logger.warning(f"Sentence completion XP award failed for lesson {lesson.id}: {xp_err}")

    result = {**grade}
    next_lesson = get_next_lesson(lesson.id)
    if grade.get('passed') and next_lesson:
        result['next_lesson_url'] = url_for(
            'curriculum_lessons.lesson_detail', lesson_id=next_lesson.id
        )

    return result


import random


@lessons_bp.route('/lesson/<int:lesson_id>/collocation-matching')
@login_required
@require_lesson_access
def collocation_matching_lesson(lesson_id: int):
    """Display a collocation matching lesson."""
    lesson = Lessons.query.get_or_404(lesson_id)
    if lesson.type != 'collocation_matching':
        flash('Неверный тип урока', 'error')
        return redirect('/learn/')

    content = lesson.content or {}
    pairs = content.get('pairs', [])
    shuffled_pairs = pairs[:]
    random.shuffle(shuffled_pairs)

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id,
    ).first()
    if not progress:
        try:
            progress = LessonProgress(
                user_id=current_user.id,
                lesson_id=lesson.id,
                status='in_progress',
                started_at=datetime.now(UTC),
                last_activity=datetime.now(UTC),
            )
            db.session.add(progress)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error creating collocation_matching progress: {e}")
            db.session.rollback()

    return render_template(
        'curriculum/lessons/collocation_matching.html',
        lesson=lesson,
        progress=progress,
        pairs=pairs,
        shuffled_pairs=shuffled_pairs,
    )


def _process_collocation_matching_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Grade a collocation matching submission, update progress, award XP, return result."""
    from app.curriculum.grading import grade_collocation_matching
    from app.curriculum.service import get_next_lesson
    from app.curriculum.services.progress_service import ProgressService

    content = lesson.content or {}
    correct_pairs = content.get('pairs', [])
    user_pairs = data.get('user_pairs', [])

    grade = grade_collocation_matching(user_pairs, correct_pairs)

    ProgressService.update_progress_with_grading(
        user_id=user_id,
        lesson=lesson,
        result=grade,
        passing_score=70,
    )

    if grade.get('passed'):
        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp
            maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=grade['score'])
            db.session.commit()
        except Exception as xp_err:
            logger.warning(f"Collocation matching XP award failed for lesson {lesson.id}: {xp_err}")

    result = {**grade}
    next_lesson = get_next_lesson(lesson.id)
    if grade.get('passed') and next_lesson:
        result['next_lesson_url'] = url_for(
            'curriculum_lessons.lesson_detail', lesson_id=next_lesson.id
        )

    return result


@lessons_bp.route('/lesson/<int:lesson_id>/shadow-reading')
@login_required
@require_lesson_access
def shadow_reading_lesson(lesson_id: int):
    """Display a shadow reading lesson — listen then read aloud (honor system)."""
    lesson = Lessons.query.get_or_404(lesson_id)
    if lesson.type != 'shadow_reading':
        flash('Неверный тип урока', 'error')
        return redirect('/learn/')

    content = lesson.content or {}
    audio_url = content.get('audio_url', '')
    text = content.get('text', '')
    translation = content.get('translation', '')

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id,
    ).first()
    if not progress:
        try:
            progress = LessonProgress(
                user_id=current_user.id,
                lesson_id=lesson.id,
                status='in_progress',
                started_at=datetime.now(UTC),
                last_activity=datetime.now(UTC),
            )
            db.session.add(progress)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error creating shadow_reading progress: {e}")
            db.session.rollback()

    return render_template(
        'curriculum/lessons/shadow_reading.html',
        lesson=lesson,
        progress=progress,
        audio_url=audio_url,
        text=text,
        translation=translation,
    )


def _process_shadow_reading_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Mark a shadow reading lesson complete on self-assessment, award XP, return result."""
    from app.curriculum.service import get_next_lesson

    self_assessed = bool(data.get('self_assessed', False))

    if self_assessed:
        progress = LessonProgress.query.filter_by(
            user_id=user_id, lesson_id=lesson.id
        ).first()
        if progress:
            progress.status = 'completed'
            if not progress.completed_at:
                progress.completed_at = datetime.now(UTC)
            progress.last_activity = datetime.now(UTC)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp
            maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=None)
            db.session.commit()
        except Exception as xp_err:
            logger.warning(f"Shadow reading XP award failed for lesson {lesson.id}: {xp_err}")

    result: dict = {'success': True, 'completed': self_assessed}
    if self_assessed:
        next_lesson = get_next_lesson(lesson.id)
        if next_lesson:
            result['next_lesson_url'] = url_for(
                'curriculum_lessons.lesson_detail', lesson_id=next_lesson.id
            )

    return result


@lessons_bp.route('/lesson/<int:lesson_id>/pronunciation')
@login_required
@require_lesson_access
def pronunciation_lesson(lesson_id: int):
    """Display a pronunciation practice lesson."""
    lesson = Lessons.query.get_or_404(lesson_id)
    if lesson.type != 'pronunciation':
        flash('Неверный тип урока', 'error')
        return redirect('/learn/')

    content = lesson.content or {}
    items = content.get('items', [])

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id,
    ).first()
    if not progress:
        try:
            progress = LessonProgress(
                user_id=current_user.id,
                lesson_id=lesson.id,
                status='in_progress',
                started_at=datetime.now(UTC),
                last_activity=datetime.now(UTC),
            )
            db.session.add(progress)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error creating pronunciation progress: {e}")
            db.session.rollback()

    return render_template(
        'curriculum/lessons/pronunciation.html',
        lesson=lesson,
        progress=progress,
        items=items,
    )


def _process_pronunciation_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Handle a pronunciation lesson submission.

    Three sub-actions:
    - item attempt (recognized_text + target_word): grade word match, log attempt
    - self-assessed item (self_assessed=True): log as matched=False attempt
    - finish (finish=True): mark lesson completed, award XP
    """
    from app.curriculum.grading import grade_pronunciation_match
    from app.curriculum.service import get_next_lesson

    if data.get('finish'):
        # Final submission — mark lesson completed and award XP
        progress = LessonProgress.query.filter_by(
            user_id=user_id, lesson_id=lesson.id
        ).first()
        if progress:
            progress.status = 'completed'
            if not progress.completed_at:
                progress.completed_at = datetime.now(UTC)
            progress.last_activity = datetime.now(UTC)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp
            maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=None)
            db.session.commit()
        except Exception as xp_err:
            logger.warning(f"Pronunciation XP award failed for lesson {lesson.id}: {xp_err}")

        result: dict = {'success': True, 'completed': True}
        next_lesson = get_next_lesson(lesson.id)
        if next_lesson:
            result['next_lesson_url'] = url_for(
                'curriculum_lessons.lesson_detail', lesson_id=next_lesson.id
            )
        return result

    # Single-item attempt
    target_word = data.get('target_word', '')
    recognized_text = data.get('recognized_text') or ''
    self_assessed = bool(data.get('self_assessed', False))

    if self_assessed or not recognized_text:
        try:
            from app.curriculum.listening_service import log_pronunciation_attempt
            log_pronunciation_attempt(
                user_id=user_id,
                word=target_word,
                recognized='',
                matched=False,
                db=db,
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
        return {'success': True, 'matched': False, 'self_assessed': True}

    grade = grade_pronunciation_match(recognized_text, target_word)
    try:
        from app.curriculum.listening_service import log_pronunciation_attempt
        log_pronunciation_attempt(
            user_id=user_id,
            word=target_word,
            recognized=recognized_text,
            matched=grade['matched'],
            db=db,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
    return {'success': True, **grade}


# Import route modules to register their routes on lessons_bp
import app.curriculum.routes.vocabulary_lessons  # noqa: E402, F401
import app.curriculum.routes.grammar_quiz_lessons  # noqa: E402, F401
import app.curriculum.routes.card_lessons  # noqa: E402, F401
