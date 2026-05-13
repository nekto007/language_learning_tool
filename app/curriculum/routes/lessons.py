# app/curriculum/routes/lessons.py

import logging
import random
import re
from datetime import UTC, datetime, timezone

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

PRONUNCIATION_DAILY_LIMIT = 200
WRITING_DAILY_LIMIT = 70


def _count_pronunciation_attempts_today(user_id: int) -> int:
    from app.curriculum.models import PronunciationAttempt
    from app.utils.time_utils import get_user_local_day_bounds
    from app.utils.db import db as _db
    today_start, _ = get_user_local_day_bounds(user_id, _db)
    return PronunciationAttempt.query.filter(
        PronunciationAttempt.user_id == user_id,
        PronunciationAttempt.created_at >= today_start,
    ).count()


def _count_writing_attempts_today(user_id: int) -> int:
    from app.curriculum.models import UserWritingAttempt
    from app.utils.time_utils import get_user_local_day_bounds
    from app.utils.db import db as _db
    today_start, _ = get_user_local_day_bounds(user_id, _db)
    return UserWritingAttempt.query.filter(
        UserWritingAttempt.user_id == user_id,
        UserWritingAttempt.created_at >= today_start,
    ).count()

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
        if progress.status != 'completed':
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
        'idiom': 'curriculum_lessons.idiom_lesson',
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
            data = request.get_json(silent=True) or {}
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

        # Server-graded lesson types must be submitted via /api/lesson/<id>/submit
        # where the score is computed server-side. Reject score and completed status
        # from this endpoint to prevent challenge score forgery.
        # Note: 'grammar' and 'listening_immersion_quiz' complete via this endpoint
        # (theory-only auto-complete and text-template flow respectively) so they are
        # excluded from the full block; score is still stripped to prevent forgery.
        _SERVER_GRADED_TYPES = frozenset((
            'dictation', 'audio_fill_blank', 'translation',
            'sentence_correction', 'sentence_completion', 'collocation_matching',
            'quiz', 'ordering_quiz', 'translation_quiz', 'listening_quiz',
            'dialogue_completion_quiz',
        ))
        # For these types score must come from the submit endpoint, but status
        # can be set via the progress endpoint (e.g. theory-only auto-complete).
        _SCORE_STRIP_ONLY_TYPES = frozenset(('grammar', 'listening_immersion_quiz'))
        lesson_for_check = Lessons.query.get(lesson_id)
        if lesson_for_check and lesson_for_check.type in _SERVER_GRADED_TYPES:
            cleaned_data.pop('score', None)
            if cleaned_data.get('status') == 'completed':
                cleaned_data.pop('status', None)
        elif lesson_for_check and lesson_for_check.type in _SCORE_STRIP_ONLY_TYPES:
            cleaned_data.pop('score', None)

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
        # Skip process_lesson_completion for theory-only types (grammar, listening_immersion_quiz)
        # whose score is stripped above — their score defaults to 0.0, not None, so the
        # is-not-None guard alone would pass and record a spurious F-grade.
        _is_score_strip_type = bool(
            lesson_for_check and lesson_for_check.type in _SCORE_STRIP_ONLY_TYPES
        )
        if progress.status == 'completed' and progress.score is not None and not _is_score_strip_type:
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
        data = request.get_json(silent=True) or {}

        # Rate limit checks to prevent leaderboard abuse.
        # The finish=True action only marks the lesson completed; it does not
        # log a new attempt, so it must not be blocked by the rate limit.
        from app.api.errors import api_error as _api_error
        if lesson.type == 'pronunciation' and not (isinstance(data, dict) and data.get('finish')):
            if _count_pronunciation_attempts_today(current_user.id) >= PRONUNCIATION_DAILY_LIMIT:
                return _api_error('rate_limit_exceeded', 'Daily pronunciation attempt limit reached.', 429)
        elif lesson.type in ('writing_prompt', 'translation', 'sentence_correction'):
            if _count_writing_attempts_today(current_user.id) >= WRITING_DAILY_LIMIT:
                return _api_error('rate_limit_exceeded', 'Daily writing attempt limit reached.', 429)

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
        elif lesson.type == 'idiom':
            result = _process_idiom_submission(lesson, current_user.id, data)
        else:
            return jsonify({'success': False, 'error': 'Invalid lesson type'}), 400

        if result.get('passed') or result.get('completed'):
            try:
                from app.daily_plan.challenge import maybe_auto_complete_challenge
                time_spent = data.get('time_spent_seconds') if isinstance(data, dict) else None
                if isinstance(time_spent, (int, float)) and time_spent >= 0:
                    time_spent = int(time_spent)
                else:
                    time_spent = None
                challenge_result = maybe_auto_complete_challenge(
                    user_id=current_user.id,
                    lesson_id=lesson_id,
                    passed=True,
                    score=result.get('score'),
                    time_spent_seconds=time_spent,
                    db=db,
                )
                if challenge_result and not challenge_result.get('already_completed'):
                    result['challenge_completed'] = True
                    result['challenge_bonus_xp'] = challenge_result.get('bonus_xp', 0)
                    db.session.commit()
            except Exception as ch_err:
                db.session.rollback()
                logger.warning("Challenge auto-complete failed for lesson %s: %s", lesson_id, ch_err)

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error submitting lesson: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Server error'}), 500


_DICTATION_MAX_REPLAYS = 3
_DICTATION_MAX_WORD_ATTEMPTS = 3


def _get_next_lesson_for_completion(lesson: 'Lessons') -> 'Lessons | None':
    """Return the next lesson URL target after a lesson is completed."""
    from app.curriculum.service import get_next_lesson
    return get_next_lesson(lesson.id)


def _lesson_completion_url(lesson: 'Lessons') -> str:
    return url_for('learn.lesson_by_id', lesson_id=lesson.id)


def _normalize_dictation_token(value: str) -> str:
    """Normalize one dictation token the same way full dictation grading does."""
    if value is None:
        return ""
    token = str(value).lower().strip()
    token = re.sub(r"[^\w\s']", "", token)
    token = re.sub(r'\s+', ' ', token).strip()
    return token


def _dictation_word_items(transcript: str, hint_chars: int = 0) -> list[dict]:
    """Return aligned display/normalized words for interactive dictation gaps."""
    items = []
    for raw_word in str(transcript or "").split():
        match = re.match(r"^([^\w']*)([\w']+)([^\w']*)$", raw_word, flags=re.UNICODE)
        if match:
            prefix, display_word, suffix = match.groups()
        else:
            prefix, display_word, suffix = "", raw_word, ""
        normalized = _normalize_dictation_token(display_word)
        if not normalized:
            continue
        hint = ""
        if hint_chars > 0:
            hint = normalized[:hint_chars]
        items.append({
            "display": display_word,
            "normalized": normalized,
            "prefix": prefix,
            "suffix": suffix,
            "hint": hint,
        })
    return items


def _dictation_items_from_content(content: dict, hint_chars: int = 0) -> list[dict]:
    """Return the checkable dictation gaps from authored content or transcript fallback."""
    gaps = content.get('gaps') if isinstance(content, dict) else None
    if isinstance(gaps, list) and gaps:
        items = []
        for gap in gaps:
            if not isinstance(gap, dict):
                continue
            display_word = str(gap.get('answer') or '').strip()
            normalized = _normalize_dictation_token(display_word)
            if not normalized:
                continue
            hint = str(gap.get('hint') or '').strip()
            if not hint and hint_chars > 0:
                hint = normalized[:hint_chars]
            items.append({
                "display": display_word,
                "normalized": normalized,
                "prefix": "",
                "suffix": "",
                "hint": hint,
            })
        if items:
            return items
    return _dictation_word_items(content.get('transcript', ''), hint_chars)


def _dictation_gap_segments(content: dict, items: list[dict]) -> list[dict]:
    """Build render-only inline text/gap segments. Answers are not included."""
    gap_text = content.get('gap_text') if isinstance(content, dict) else None
    if isinstance(gap_text, str) and gap_text.strip() and items:
        segments: list[dict] = []
        cursor = 0
        for match in re.finditer(r"\{(\d+)\}", gap_text):
            if match.start() > cursor:
                segments.append({"type": "text", "text": gap_text[cursor:match.start()]})
            gap_index = int(match.group(1))
            if 0 <= gap_index < len(items):
                item = items[gap_index]
                segments.append({
                    "type": "gap",
                    "index": gap_index,
                    "hint": item.get("hint", ""),
                })
            else:
                segments.append({"type": "text", "text": match.group(0)})
            cursor = match.end()
        if cursor < len(gap_text):
            segments.append({"type": "text", "text": gap_text[cursor:]})
        return segments

    segments = []
    for index, item in enumerate(items):
        if item.get("prefix"):
            segments.append({"type": "text", "text": item["prefix"]})
        segments.append({"type": "gap", "index": index, "hint": item.get("hint", "")})
        if item.get("suffix"):
            segments.append({"type": "text", "text": item["suffix"]})
        segments.append({"type": "text", "text": " "})
    return segments


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


@lessons_bp.route('/api/lesson/<int:lesson_id>/dictation-word', methods=['POST'])
@login_required
@require_lesson_access
def check_dictation_word(lesson_id: int):
    """Check one dictation gap without exposing the transcript before attempts are exhausted."""
    lesson = Lessons.query.get_or_404(lesson_id)
    if lesson.type != 'dictation':
        return jsonify({'success': False, 'error': 'Invalid lesson type'}), 400

    data = request.get_json(silent=True) or {}
    try:
        index = int(data.get('index'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Invalid word index'}), 400
    try:
        attempt = max(1, int(data.get('attempt') or 1))
    except (TypeError, ValueError):
        attempt = 1

    word_items = _dictation_items_from_content(lesson.content or {})
    if index < 0 or index >= len(word_items):
        return jsonify({'success': False, 'error': 'Invalid word index'}), 400

    user_answer = _normalize_dictation_token(data.get('answer', ''))
    correct_item = word_items[index]
    is_correct = user_answer == correct_item["normalized"]
    exhausted = (not is_correct) and attempt >= _DICTATION_MAX_WORD_ATTEMPTS

    if exhausted:
        progress = LessonProgress.query.filter_by(
            user_id=current_user.id,
            lesson_id=lesson.id,
        ).first()
        if not progress:
            progress = LessonProgress(
                user_id=current_user.id,
                lesson_id=lesson.id,
                status='in_progress',
                started_at=datetime.now(UTC),
                last_activity=datetime.now(UTC),
            )
            db.session.add(progress)

        progress_data = dict(progress.data or {})
        failed_indices = set(progress_data.get('dictation_failed_indices') or [])
        failed_indices.add(index)
        progress_data['dictation_failed_indices'] = sorted(failed_indices)
        progress.data = progress_data
        progress.last_activity = datetime.now(UTC)
        flag_modified(progress, 'data')
        db.session.commit()

    response = {
        'success': True,
        'correct': is_correct,
        'attempt': attempt,
        'attempts_left': max(0, _DICTATION_MAX_WORD_ATTEMPTS - attempt),
        'exhausted': exhausted,
    }
    if exhausted:
        response['correct_word'] = correct_item["display"]
    return jsonify(response)


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

    word_items = _dictation_items_from_content(content, hint_chars)
    gap_segments = _dictation_gap_segments(content, word_items)
    hint_text = _build_hint_text(transcript, hint_chars) if hint_chars > 0 else ""

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()
    completed_result = None
    completed_gap_values = []
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
    elif progress.status == 'completed' and isinstance(progress.data, dict):
        completed_result = dict(progress.data)
        completed_result.setdefault('passed', True)
        completed_result.setdefault('score', progress.score or 100)
        completed_result.setdefault('transcript', None)
        next_lesson = _get_next_lesson_for_completion(lesson)
        if next_lesson:
            completed_result['next_lesson_url'] = _lesson_completion_url(next_lesson)
        completed_gap_values = [item.get("display", "") for item in word_items]
    elif isinstance(progress.data, dict):
        if progress.data.get('dictation_failed_indices'):
            progress_data = dict(progress.data)
            progress_data.pop('dictation_failed_indices', None)
            progress.data = progress_data
            progress.last_activity = datetime.now(UTC)
            flag_modified(progress, 'data')
            db.session.commit()

    return render_template(
        'curriculum/lessons/dictation.html',
        lesson=lesson,
        progress=progress,
        audio_url=audio_url,
        transcript=transcript,
        hint_chars=hint_chars,
        hint_text=hint_text,
        word_items=word_items,
        gap_segments=gap_segments,
        completed_result=completed_result,
        completed_gap_values=completed_gap_values,
        max_replays=_DICTATION_MAX_REPLAYS,
        max_word_attempts=_DICTATION_MAX_WORD_ATTEMPTS,
    )


def _process_dictation_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Grade a dictation submission, update progress, award XP, and return result."""
    from app.curriculum.grading import grade_dictation
    from app.curriculum.services.progress_service import ProgressService
    from app.curriculum.listening_service import log_listening_attempt

    content = lesson.content or {}
    transcript = content.get('transcript', '')
    word_items = _dictation_items_from_content(content, hint_chars=0)
    reference_text = " ".join(item["display"] for item in word_items) if content.get('gaps') else transcript
    try:
        hint_chars = int(data.get('hint_chars') or content.get('hint_chars') or 0)
    except (TypeError, ValueError):
        hint_chars = 0
    user_text = (data.get('user_text') or '')[:50000]
    try:
        replay_count = min(int(data.get('replay_count') or 0), _DICTATION_MAX_REPLAYS)
    except (TypeError, ValueError):
        replay_count = 0

    grade = grade_dictation(user_text, reference_text, hint_chars)
    grade['user_text'] = user_text

    existing_progress = LessonProgress.query.filter_by(
        user_id=user_id,
        lesson_id=lesson.id,
    ).first()
    failed_indices = []
    if existing_progress and isinstance(existing_progress.data, dict):
        failed_indices = existing_progress.data.get('dictation_failed_indices') or []
    if failed_indices:
        grade['passed'] = False
        grade['score'] = min(int(grade.get('score') or 0), 79)
        grade['failed_by_attempt_limit'] = True
        grade['failed_indices'] = failed_indices

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
        db.session.rollback()

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

    next_lesson = _get_next_lesson_for_completion(lesson)
    if grade.get('passed') and next_lesson:
        result['next_lesson_url'] = _lesson_completion_url(next_lesson)

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
    from app.curriculum.services.progress_service import ProgressService
    from app.curriculum.listening_service import log_listening_attempt

    content = lesson.content or {}
    items = content.get('items', [])
    user_answers = data.get('answers') or []
    if not isinstance(user_answers, list):
        user_answers = []
    try:
        replay_count = min(int(data.get('replay_count') or 0), _DICTATION_MAX_REPLAYS)
    except (TypeError, ValueError):
        replay_count = 0

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
        db.session.rollback()

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
    next_lesson = _get_next_lesson_for_completion(lesson)
    if grade.get('passed') and next_lesson:
        result['next_lesson_url'] = _lesson_completion_url(next_lesson)
    # Only reveal correct answers after the lesson is passed
    if grade.get('passed'):
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
    from app.curriculum.models import save_writing_attempt
    from app.curriculum.services.progress_service import ProgressService

    content = lesson.content or {}
    correct_answer = content.get('english', '')
    user_answer = (data.get('user_answer', '') or '')[:2000]

    grade = grade_translation(user_answer, correct_answer)
    passed = grade['is_correct']

    try:
        save_writing_attempt(user_id, lesson.id, user_answer, passed, db)
        db.session.flush()
    except Exception as save_err:
        logger.warning(f"Translation writing attempt save failed for lesson {lesson.id}: {save_err}")
        db.session.rollback()

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
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp, maybe_award_writing_xp
            maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=100)
            maybe_award_writing_xp(user_id, lesson.id, db_session=db)
            db.session.commit()
        except Exception as xp_err:
            logger.warning(f"Translation XP award failed for lesson {lesson.id}: {xp_err}")

    try:
        from app.achievements.services import check_writing_achievements
        check_writing_achievements(user_id, db_session=db.session)
    except Exception as ach_err:
        logger.warning(f"Writing achievements check failed for user {user_id}: {ach_err}")

    result = {**grade, 'passed': passed}
    next_lesson = _get_next_lesson_for_completion(lesson)
    if passed and next_lesson:
        result['next_lesson_url'] = _lesson_completion_url(next_lesson)

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
    from app.curriculum.models import save_writing_attempt
    from app.curriculum.services.progress_service import ProgressService

    content = lesson.content or {}
    correct_sentence = content.get('correct_sentence', '')
    explanation = content.get('explanation', '')
    user_answer = (data.get('user_answer', '') or '')[:2000]

    grade = grade_sentence_correction(user_answer, correct_sentence)
    passed = grade['is_correct']

    try:
        save_writing_attempt(user_id, lesson.id, user_answer, passed, db)
        db.session.flush()
    except Exception as save_err:
        logger.warning(f"Sentence correction writing attempt save failed for lesson {lesson.id}: {save_err}")
        db.session.rollback()

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
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp, maybe_award_writing_xp
            maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=100)
            maybe_award_writing_xp(user_id, lesson.id, db_session=db)
            db.session.commit()
        except Exception as xp_err:
            logger.warning(f"Sentence correction XP award failed for lesson {lesson.id}: {xp_err}")

    try:
        from app.achievements.services import check_writing_achievements
        check_writing_achievements(user_id, db_session=db.session)
    except Exception as ach_err:
        logger.warning(f"Writing achievements check failed for user {user_id}: {ach_err}")

    result = {**grade, 'passed': passed, 'explanation': explanation}
    next_lesson = _get_next_lesson_for_completion(lesson)
    if passed and next_lesson:
        result['next_lesson_url'] = _lesson_completion_url(next_lesson)

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

    content = lesson.content or {}
    example_response = content.get('example_response') or None
    response_text = (data.get('response_text') or '')[:20000].strip()
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
        db.session.rollback()

    completed = meets_min and len(checked_items) >= 2

    if completed:
        progress = LessonProgress.query.filter_by(
            user_id=user_id, lesson_id=lesson.id
        ).first()
        if progress:
            progress.status = 'completed'
            if not progress.completed_at:
                progress.completed_at = datetime.now(UTC)
            progress.last_activity = datetime.now(UTC)
        else:
            progress = LessonProgress(
                user_id=user_id,
                lesson_id=lesson.id,
                status='completed',
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                last_activity=datetime.now(UTC),
            )
            db.session.add(progress)
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

        try:
            from app.achievements.services import check_writing_achievements
            check_writing_achievements(user_id, db_session=db.session)
        except Exception as ach_err:
            logger.warning(f"Writing achievements check failed for user {user_id}: {ach_err}")

    result: dict = {
        'success': True,
        'completed': completed,
        'word_count': word_count,
        'meets_min_words': meets_min,
        'checklist_completed': checklist_completed,
    }
    if completed and example_response:
        result['example_response'] = example_response

    next_lesson = _get_next_lesson_for_completion(lesson)
    if completed and next_lesson:
        result['next_lesson_url'] = _lesson_completion_url(next_lesson)

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
    from app.curriculum.services.progress_service import ProgressService

    content = lesson.content or {}
    items = content.get('items', [])
    user_answers = data.get('answers') or []
    if not isinstance(user_answers, list):
        user_answers = []

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
    next_lesson = _get_next_lesson_for_completion(lesson)
    if grade.get('passed') and next_lesson:
        result['next_lesson_url'] = _lesson_completion_url(next_lesson)

    return result




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
    next_lesson = _get_next_lesson_for_completion(lesson)
    if grade.get('passed') and next_lesson:
        result['next_lesson_url'] = _lesson_completion_url(next_lesson)

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
    words = content.get('words', [])

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
        words=words,
    )


def _process_shadow_reading_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Mark a shadow reading lesson complete on self-assessment, award XP, return result."""
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
        else:
            progress = LessonProgress(
                user_id=user_id,
                lesson_id=lesson.id,
                status='completed',
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                last_activity=datetime.now(UTC),
            )
            db.session.add(progress)
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

        try:
            from app.curriculum.listening_service import log_pronunciation_attempt
            from app.achievements.services import check_speaking_achievements
            log_pronunciation_attempt(user_id, 'shadow_reading', '', False, db)
            db.session.commit()
            check_speaking_achievements(user_id, db_session=db.session)
        except Exception as sp_err:
            logger.warning(f"Shadow reading speaking signal failed for lesson {lesson.id}: {sp_err}")

    result: dict = {'success': True, 'completed': self_assessed}
    if self_assessed:
        next_lesson = _get_next_lesson_for_completion(lesson)
        if next_lesson:
            result['next_lesson_url'] = _lesson_completion_url(next_lesson)

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
        else:
            progress = LessonProgress(
                user_id=user_id,
                lesson_id=lesson.id,
                status='completed',
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                last_activity=datetime.now(UTC),
            )
            db.session.add(progress)
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

        try:
            from app.achievements.services import check_speaking_achievements
            check_speaking_achievements(user_id, db_session=db.session)
        except Exception as ach_err:
            logger.warning(f"Speaking achievements check failed for user {user_id}: {ach_err}")

        result: dict = {'success': True, 'completed': True}
        next_lesson = _get_next_lesson_for_completion(lesson)
        if next_lesson:
            result['next_lesson_url'] = _lesson_completion_url(next_lesson)
        return result

    # Single-item attempt
    target_word = str(data.get('target_word') or '')[:200]
    recognized_text = str(data.get('recognized_text') or '')[:500]
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
        try:
            from app.achievements.services import check_speaking_achievements
            check_speaking_achievements(user_id, db_session=db.session)
        except Exception as ach_err:
            logger.warning(f"Speaking achievements check failed for user {user_id}: {ach_err}")
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
    try:
        from app.achievements.services import check_speaking_achievements
        check_speaking_achievements(user_id, db_session=db.session)
    except Exception as ach_err:
        logger.warning(f"Speaking achievements check failed for user {user_id}: {ach_err}")
    return {'success': True, **grade}


@lessons_bp.route('/lesson/<int:lesson_id>/idiom')
@login_required
@require_lesson_access
def idiom_lesson(lesson_id: int):
    """Display an idiom lesson — present phrase, animated meaning reveal, self-assess."""
    lesson = Lessons.query.get_or_404(lesson_id)
    if lesson.type != 'idiom':
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
            logger.error(f"Error creating idiom progress: {e}")
            db.session.rollback()

    return render_template(
        'curriculum/lessons/idiom.html',
        lesson=lesson,
        progress=progress,
        items=items,
    )


def _process_idiom_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Mark an idiom lesson complete when user finishes all items."""
    if not data.get('finish'):
        return {'success': True, 'completed': False}

    progress = LessonProgress.query.filter_by(
        user_id=user_id, lesson_id=lesson.id
    ).first()
    if progress:
        progress.status = 'completed'
        if not progress.completed_at:
            progress.completed_at = datetime.now(UTC)
        progress.last_activity = datetime.now(UTC)
    else:
        progress = LessonProgress(
            user_id=user_id,
            lesson_id=lesson.id,
            status='completed',
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            last_activity=datetime.now(UTC),
        )
        db.session.add(progress)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    try:
        from app.daily_plan.linear.xp import maybe_award_curriculum_xp
        maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=None)
        db.session.commit()
    except Exception as xp_err:
        logger.warning(f"Idiom XP award failed for lesson {lesson.id}: {xp_err}")

    result: dict = {'success': True, 'completed': True}
    next_lesson = _get_next_lesson_for_completion(lesson)
    if next_lesson:
        result['next_lesson_url'] = _lesson_completion_url(next_lesson)
    return result


@lessons_bp.route('/api/lessons/<int:lesson_id>/feedback', methods=['POST'])
@login_required
@require_lesson_access
def lesson_feedback(lesson_id):
    """Save or update user thumbs-up/down feedback for a completed lesson."""
    from app.api.errors import api_error
    from app.curriculum.models import LessonFeedback, save_lesson_feedback

    lesson = Lessons.query.get_or_404(lesson_id)
    data = request.get_json(silent=True) or {}

    rating = data.get('rating')
    if rating is None or not isinstance(rating, int) or rating < 1 or rating > 5:
        return api_error('invalid_rating', 'Rating must be an integer between 1 and 5.', 400)

    comment = data.get('comment')
    if comment is not None:
        comment = str(comment)[:500]  # Truncate long comments

    try:
        save_lesson_feedback(current_user.id, lesson.id, rating, comment, db)
        db.session.commit()
    except Exception as exc:
        logger.exception(f"Error saving lesson feedback for lesson {lesson_id}: {exc}")
        db.session.rollback()
        return api_error('server_error', 'Could not save feedback.', 500)

    return jsonify({'success': True, 'lesson_id': lesson_id, 'rating': rating})


# Import route modules to register their routes on lessons_bp
import app.curriculum.routes.vocabulary_lessons  # noqa: E402, F401
import app.curriculum.routes.grammar_quiz_lessons  # noqa: E402, F401
import app.curriculum.routes.card_lessons  # noqa: E402, F401
