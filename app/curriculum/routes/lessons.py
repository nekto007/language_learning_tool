# app/curriculum/routes/lessons.py

import logging
import math
import random
import re
from datetime import UTC, datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified

from app import limiter
from app.curriculum.constants import PASSING_SCORE_DEFAULT, PASSING_SCORE_DICTATION
from app.curriculum.models import LessonProgress, Lessons
from app.curriculum.security import require_lesson_access, sanitize_json_content
from app.curriculum.grading import check_final_test_attempts_exhausted
from app.curriculum.service import (
    process_final_test_submission,
    process_grammar_submission,
    process_matching_submission,
    process_quiz_submission,
)
from app.curriculum.validators import ProgressUpdateSchema, validate_request_data
from app.utils.db import db
from app.utils.rate_limit_helpers import get_authenticated_user_key

logger = logging.getLogger(__name__)

PRONUNCIATION_DAILY_LIMIT = 200
WRITING_DAILY_LIMIT = 70


def _count_pronunciation_attempts_today(user_id: int) -> int:
    from app.curriculum.models import PronunciationAttempt
    from app.utils.db import db as _db
    from app.utils.time_utils import get_user_local_day_bounds
    today_start, _ = get_user_local_day_bounds(user_id, _db)
    return PronunciationAttempt.query.filter(
        PronunciationAttempt.user_id == user_id,
        PronunciationAttempt.created_at >= today_start,
    ).count()


def _count_writing_attempts_today(user_id: int) -> int:
    from app.curriculum.models import UserWritingAttempt
    from app.utils.db import db as _db
    from app.utils.time_utils import get_user_local_day_bounds
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
        except IntegrityError:
            # Concurrent request already created the row — fetch it
            db.session.rollback()
            progress = LessonProgress.query.filter_by(
                user_id=current_user.id,
                lesson_id=lesson.id,
            ).first()
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
        'listening_immersion': 'curriculum_lessons.listening_immersion_lesson',
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
        # Preserve query string across the type-routing redirect so
        # ?from=linear_plan&slot=... survives — otherwise the lesson page
        # loses its daily-plan context and renders catalog-style CTAs
        # after completion.
        query = request.query_string.decode('utf-8') if request.query_string else ''
        target = url_for(route_name, lesson_id=lesson.id)
        if query:
            target = f'{target}?{query}'
        return redirect(target)
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
        # Note: 'listening_immersion_quiz' completes via this endpoint (text-template
        # flow) so it is excluded from the full block; score is still stripped to
        # prevent forgery. 'grammar' is dual-mode: theory-only lessons (no exercises
        # in content) complete via this endpoint; exercise-backed grammar lessons are
        # graded server-side via the grammar form POST and must not be completable here.
        _SERVER_GRADED_TYPES = frozenset((
            'dictation', 'audio_fill_blank', 'translation',
            'sentence_correction', 'sentence_completion', 'collocation_matching',
            'quiz', 'ordering_quiz', 'translation_quiz', 'listening_quiz',
            'dialogue_completion_quiz',
            'writing_prompt', 'shadow_reading', 'pronunciation',
            'listening_immersion', 'idiom',
        ))
        # For these types score must come from the submit endpoint, but status
        # can be set via the progress endpoint (e.g. theory-only auto-complete).
        _SCORE_STRIP_ONLY_TYPES = frozenset(('listening_immersion_quiz',))
        lesson_for_check = Lessons.query.get(lesson_id)
        # Exercise-backed grammar lessons are server-graded; treat them as such.
        # Theory-only grammar lessons (no exercises) still need to auto-complete
        # via this endpoint, so we strip only score for those.
        _is_grammar_with_exercises = bool(
            lesson_for_check
            and lesson_for_check.type == 'grammar'
            and isinstance(lesson_for_check.content, dict)
            and lesson_for_check.content.get('exercises')
        )
        _is_grammar_theory_only = bool(
            lesson_for_check
            and lesson_for_check.type == 'grammar'
            and not _is_grammar_with_exercises
        )
        if lesson_for_check and (
            lesson_for_check.type in _SERVER_GRADED_TYPES or _is_grammar_with_exercises
        ):
            cleaned_data.pop('score', None)
            if cleaned_data.get('status') == 'completed':
                cleaned_data.pop('status', None)
        elif lesson_for_check and (
            lesson_for_check.type in _SCORE_STRIP_ONLY_TYPES or _is_grammar_theory_only
        ):
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
                    with db.session.begin_nested():
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
                db.session.rollback()
                logger.warning(f"Linear XP award failed for lesson {lesson_id}: {xp_err}")

        completion_result = None
        # Skip process_lesson_completion for theory-only types (grammar, listening_immersion_quiz)
        # whose score is stripped above — their score defaults to 0.0, not None, so the
        # is-not-None guard alone would pass and record a spurious F-grade.
        _is_score_strip_type = bool(
            lesson_for_check
            and (lesson_for_check.type in _SCORE_STRIP_ONLY_TYPES or _is_grammar_theory_only)
        )
        if progress.status == 'completed' and progress.score is not None and not _is_score_strip_type:
            try:
                from app.achievements.services import process_lesson_completion
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
@limiter.limit("30 per minute", key_func=get_authenticated_user_key)
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
                from app.utils.time_utils import get_user_local_day_bounds
                from app.utils.db import db as _db
                import calendar
                _, day_end = get_user_local_day_bounds(current_user.id, _db)
                retry_after = int(calendar.timegm(day_end.timetuple()))
                return jsonify({'success': False, 'error': 'rate_limit_exceeded',
                                'message': 'Daily pronunciation attempt limit reached.',
                                'retry_after': retry_after}), 429
        elif lesson.type in ('writing_prompt', 'translation', 'sentence_correction'):
            if _count_writing_attempts_today(current_user.id) >= WRITING_DAILY_LIMIT:
                return _api_error('rate_limit_exceeded', 'Daily writing attempt limit reached.', 429)

        if lesson.type == 'quiz':
            _content = lesson.content if isinstance(lesson.content, dict) else {}
            result = process_quiz_submission(_content.get('questions', []), data.get('answers', {}))
        elif lesson.type == 'grammar':
            _content = lesson.content if isinstance(lesson.content, dict) else {}
            result = process_grammar_submission(_content.get('exercises', []), data.get('answers', {}))
        elif lesson.type == 'matching':
            _content = lesson.content if isinstance(lesson.content, dict) else {}
            result = process_matching_submission(_content.get('pairs', []), data.get('answers', {}))
        elif lesson.type == 'final_test':
            rate_limit = check_final_test_attempts_exhausted(current_user.id, lesson.id, db_session=db)
            if rate_limit is not None:
                return jsonify({'success': False, **rate_limit}), 429
            _content = lesson.content if isinstance(lesson.content, dict) else {}
            result = process_final_test_submission(_content.get('questions', []), data.get('answers', {}))
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
        elif lesson.type == 'listening_immersion':
            result = _process_listening_immersion_submission(lesson, current_user.id, data)
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

        # Attach a refreshed daily_plan_ctx so the client completion helper
        # can update its CTA href/title (and trigger the day-secured redirect
        # to /dashboard?day_secured=1 when this slot just closed the day).
        # Always safe: returns is_daily_plan=False when ?from=linear_plan is
        # absent from the originating request.
        try:
            from app.daily_plan.linear.lesson_context import build_lesson_context
            dp_ctx = build_lesson_context(
                current_user.id, db, current_lesson_id=lesson_id
            )
            result['daily_plan_ctx'] = dp_ctx.to_dict()
        except Exception as ctx_err:
            logger.warning("daily_plan_ctx attach failed for lesson %s: %s", lesson_id, ctx_err)

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error submitting lesson: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Server error'}), 500


_DICTATION_MAX_REPLAYS = 3
_DICTATION_MAX_WORD_ATTEMPTS = 3
_DICTATION_HINT_RATIOS = {
    'A1': 1.0,
    'A2': 0.75,
    'B1': 0.5,
    'B2': 0.33,
    'C1': 0.25,
    'C2': 0.15,
}


def _get_next_lesson_for_completion(lesson: 'Lessons') -> 'Lessons | None':
    """Return the next lesson URL target after a lesson is completed."""
    from app.curriculum.service import get_next_lesson
    return get_next_lesson(lesson.id)


def _lesson_completion_url(lesson: 'Lessons') -> str:
    return url_for('learn.lesson_by_id', lesson_id=lesson.id)


def _dictation_level_code(lesson: 'Lessons') -> str:
    """Return the lesson CEFR code if the module/level relationship is available."""
    level = getattr(getattr(lesson, 'module', None), 'level', None)
    return str(getattr(level, 'code', '') or '').upper()


def _dictation_hint_budget(level_code: str, gap_count: int, hint_chars: int) -> int:
    """Return how many word-level hints are available for a dictation lesson."""
    if gap_count <= 0 or hint_chars <= 0:
        return 0
    ratio = _DICTATION_HINT_RATIOS.get(str(level_code or '').upper(), 0.5)
    return max(1, min(gap_count, math.ceil(gap_count * ratio)))


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

    word_items = _dictation_items_from_content(lesson.content or {})
    if index < 0 or index >= len(word_items):
        return jsonify({'success': False, 'error': 'Invalid word index'}), 400

    user_answer = _normalize_dictation_token(data.get('answer', ''))
    correct_item = word_items[index]
    is_correct = user_answer == correct_item["normalized"]

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
        db.session.flush()

    progress_data = dict(progress.data or {})
    attempts_map = dict(progress_data.get('dictation_attempts') or {})
    key = str(index)
    prev_attempts = int(attempts_map.get(key, 0) or 0)
    if is_correct:
        attempt = prev_attempts + 1
    else:
        attempt = min(prev_attempts + 1, _DICTATION_MAX_WORD_ATTEMPTS)
        attempts_map[key] = attempt
        progress_data['dictation_attempts'] = attempts_map

    exhausted = (not is_correct) and attempt >= _DICTATION_MAX_WORD_ATTEMPTS

    if exhausted:
        failed_indices = set(progress_data.get('dictation_failed_indices') or [])
        failed_indices.add(index)
        progress_data['dictation_failed_indices'] = sorted(failed_indices)

    if not is_correct:
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
    level_code = _dictation_level_code(lesson)
    hint_budget = _dictation_hint_budget(level_code, len(word_items), hint_chars)

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
        # Reset stale state on page reload for an in-progress lesson. Two
        # families to drop:
        #   • per-word counters (``dictation_attempts``, ``dictation_failed_indices``)
        #     from the granular submit path;
        #   • grade-dict leftovers (``failed_indices``, ``failed_by_attempt_limit``,
        #     ``passed``, ``score``) saved by a previous *failed* full submit.
        # Without the second family, the next full submit reads
        # ``failed_indices`` from the leftover dict and re-applies the 79%
        # penalty even though the user just typed everything correctly.
        stale_keys = (
            'dictation_failed_indices', 'dictation_attempts',
            'failed_indices', 'failed_by_attempt_limit',
            'passed', 'score', 'correct_words', 'total_words', 'word_results',
        )
        if any(progress.data.get(k) for k in stale_keys):
            progress_data = dict(progress.data)
            for key in stale_keys:
                progress_data.pop(key, None)
            progress.data = progress_data
            progress.last_activity = datetime.now(UTC)
            flag_modified(progress, 'data')
            db.session.commit()

    next_lesson = _get_next_lesson_for_completion(lesson)
    is_completed = bool(progress and progress.status == 'completed')

    return render_template(
        'curriculum/lessons/dictation.html',
        lesson=lesson,
        progress=progress,
        audio_url=audio_url,
        transcript=transcript,
        hint_chars=hint_chars,
        hint_budget=hint_budget,
        level_code=level_code,
        hint_text=hint_text,
        word_items=word_items,
        gap_segments=gap_segments,
        completed_result=completed_result,
        completed_gap_values=completed_gap_values,
        max_replays=_DICTATION_MAX_REPLAYS,
        max_word_attempts=_DICTATION_MAX_WORD_ATTEMPTS,
        next_lesson=next_lesson,
        is_completed=is_completed,
    )


def _process_dictation_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Grade a dictation submission, update progress, award XP, and return result."""
    from app.curriculum.grading import grade_dictation
    from app.curriculum.listening_service import log_listening_attempt
    from app.curriculum.services.progress_service import ProgressService

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
        replay_count = max(0, min(int(data.get('replay_count') or 0), _DICTATION_MAX_REPLAYS))
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
        # After first full submit, progress.data is the grade result dict which uses
        # 'failed_indices' key (not 'dictation_failed_indices'). Check both so the
        # attempt-limit penalty survives lesson retries.
        failed_indices = (
            existing_progress.data.get('dictation_failed_indices')
            or existing_progress.data.get('failed_indices')
            or []
        )

    # Mastery override: when the CURRENT full submission is 100% correct,
    # ignore historic word-attempt failures. The user typed every word
    # correctly — capping at 79% with "раскрытые слова" is misleading
    # (UI advertises "Доступно подсказок: 4/4") and demotivating after a
    # successful retry. The per-word attempt cap stays as friction during
    # the live exercise; it doesn't override end-to-end mastery on submit.
    correct_words = int(grade.get('correct_words') or 0)
    total_words = int(grade.get('total_words') or 0)
    full_mastery = total_words > 0 and correct_words >= total_words
    if failed_indices and not full_mastery:
        grade['passed'] = False
        grade['score'] = min(int(grade.get('score') or 0), 79)
        grade['failed_by_attempt_limit'] = True
        grade['failed_indices'] = failed_indices

    progress, _ = ProgressService.update_progress_with_grading(
        user_id=user_id,
        lesson=lesson,
        result=grade,
        passing_score=PASSING_SCORE_DICTATION,
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
        db.session.commit()
    except Exception as ach_err:
        db.session.rollback()
        logger.warning(f"Listening achievement check failed for user {user_id}: {ach_err}")

    if grade.get('passed'):
        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp, maybe_award_listening_xp
            with db.session.begin_nested():
                maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=grade['score'])
                maybe_award_listening_xp(user_id, lesson.id, score=grade['score'], db_session=db)
            db.session.commit()
        except Exception as xp_err:
            db.session.rollback()
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

    next_lesson = _get_next_lesson_for_completion(lesson)
    is_completed = bool(progress and progress.status == 'completed')

    return render_template(
        'curriculum/lessons/audio_fill_blank.html',
        lesson=lesson,
        progress=progress,
        audio_url=audio_url,
        items=items,
        next_lesson=next_lesson,
        is_completed=is_completed,
    )


def _process_audio_fill_blank_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Grade an audio fill-in-blank submission, update progress, award XP, return result."""
    from app.curriculum.grading import grade_audio_fill_blank
    from app.curriculum.listening_service import log_listening_attempt
    from app.curriculum.services.progress_service import ProgressService

    content = lesson.content or {}
    items = content.get('items', [])
    user_answers = data.get('answers') or []
    if not isinstance(user_answers, list):
        user_answers = []
    user_answers = [(str(a) if a is not None else '')[:2000] for a in user_answers]
    try:
        replay_count = max(0, min(int(data.get('replay_count') or 0), _DICTATION_MAX_REPLAYS))
    except (TypeError, ValueError):
        replay_count = 0

    grade = grade_audio_fill_blank(user_answers, items)

    progress, _ = ProgressService.update_progress_with_grading(
        user_id=user_id,
        lesson=lesson,
        result=grade,
        passing_score=PASSING_SCORE_DEFAULT,
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
        db.session.commit()
    except Exception as ach_err:
        db.session.rollback()
        logger.warning(f"Listening achievement check failed for user {user_id}: {ach_err}")

    if grade.get('passed'):
        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp, maybe_award_listening_xp
            with db.session.begin_nested():
                maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=grade['score'])
                maybe_award_listening_xp(user_id, lesson.id, score=grade['score'], db_session=db)
            db.session.commit()
        except Exception as xp_err:
            db.session.rollback()
            logger.warning(f"Audio fill blank XP award failed for lesson {lesson.id}: {xp_err}")

    result = {**grade}
    # Only reveal correct answers after the lesson is passed; on failure,
    # strip the `answer` field from per-item results so the retry attempt
    # is still pedagogically useful.
    if not grade.get('passed'):
        result['item_results'] = [
            {k: v for k, v in r.items() if k != 'answer'}
            for r in result.get('item_results', [])
        ]
    next_lesson = _get_next_lesson_for_completion(lesson)
    if grade.get('passed') and next_lesson:
        result['next_lesson_url'] = _lesson_completion_url(next_lesson)

    return result


def _translation_items_from_content(content: dict) -> list:
    """Normalise translation content into a list of items.

    Multi-item is the new shape (preferred for guided practice). Legacy
    single-item content gets wrapped into a one-element list so the template
    can branch on items uniformly.
    """
    items = content.get('items') if isinstance(content, dict) else None
    if isinstance(items, list) and items:
        return [
            {
                'russian': (it.get('russian') or '').strip(),
                'english': (it.get('english') or '').strip(),
                'hint_words': it.get('hint_words') or [],
                'alternatives': it.get('alternatives') or [],
            }
            for it in items
            if isinstance(it, dict) and it.get('russian') and it.get('english')
        ]
    # Legacy single-item shape
    russian = (content.get('russian') or '').strip()
    english = (content.get('english') or '').strip()
    if russian and english:
        return [{
            'russian': russian,
            'english': english,
            'hint_words': content.get('hint_words') or [],
            'alternatives': content.get('alternatives') or [],
        }]
    return []


def _translation_mode(content: dict, items: list) -> str:
    """Resolve translation lesson difficulty mode.

    Explicit ``mode`` in content wins. Otherwise auto-derive: any item with
    hint_words → ``guided`` (A1/A2), else → ``open`` (B1/B2). ``rubric``
    (C1) requires explicit opt-in via content since it implies a
    different grader path.
    """
    explicit = (content or {}).get('mode') if isinstance(content, dict) else None
    if explicit in ('guided', 'open', 'rubric'):
        return explicit
    for it in (items or []):
        if it.get('hint_words'):
            return 'guided'
    return 'open'


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
    items = _translation_items_from_content(content)

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    # ?reset=true сбрасывает LessonProgress, чтобы пользователь мог
    # перепройти урок-тренировку (после partial-score 2/3, например).
    # Прогресс отдельных слов в SRS отдельная история — он живёт в
    # UserCardDirection и не трогается. XP не дублируется (idempotent
    # dedup в maybe_award_curriculum_xp / writing_xp).
    if request.args.get('reset') == 'true' and progress and progress.status in ('completed', 'in_progress'):
        progress.status = 'in_progress'
        progress.score = None
        progress.data = None
        progress.completed_at = None
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

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

    is_completed = bool(progress and progress.status == 'completed')
    next_lesson = _get_next_lesson_for_completion(lesson)
    mode = _translation_mode(content, items)

    return render_template(
        'curriculum/lessons/translation.html',
        lesson=lesson,
        progress=progress,
        items=items,
        is_completed=is_completed,
        next_lesson=next_lesson,
        mode=mode,
    )


def _process_translation_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Grade a translation submission, update progress, award XP, return result.

    Supports two payload shapes:
      * Multi-item: ``{"answers": ["...", "...", ...]}`` (preferred)
      * Single-item legacy: ``{"user_answer": "..."}``
    """
    from app.curriculum.grading import grade_translation, grade_translation_multi
    from app.curriculum.models import save_writing_attempt
    from app.curriculum.services.progress_service import ProgressService

    content = lesson.content or {}
    items = _translation_items_from_content(content)

    answers_payload = data.get('answers')
    if isinstance(answers_payload, list) and items:
        user_answers = [(str(a) if a is not None else '')[:2000] for a in answers_payload]
        grade = grade_translation_multi(user_answers, items)
        passed = grade['passed']
        combined_text = ' | '.join(a.strip() for a in user_answers if a and a.strip())
    else:
        # Legacy single-item path
        legacy_correct = items[0]['english'] if items else (content.get('english') or '')
        user_answer = (data.get('user_answer', '') or '')[:2000]
        single = grade_translation(user_answer, legacy_correct)
        passed = single['is_correct']
        grade = {
            'score': 100 if passed else 0,
            'passed': passed,
            'correct_items': 1 if passed else 0,
            'total_items': 1,
            'item_results': [{
                'answer': legacy_correct,
                'user_answer': user_answer,
                'correct': passed,
            }],
        }
        combined_text = user_answer

    try:
        if combined_text:
            save_writing_attempt(user_id, lesson.id, combined_text, passed, db)
            db.session.flush()
    except Exception as save_err:
        logger.warning(f"Translation writing attempt save failed for lesson {lesson.id}: {save_err}")
        db.session.rollback()

    ProgressService.update_progress_with_grading(
        user_id=user_id,
        lesson=lesson,
        result=grade,
        passing_score=PASSING_SCORE_DEFAULT,
    )

    if passed:
        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp, maybe_award_writing_xp
            with db.session.begin_nested():
                maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=grade.get('score', 100))
                maybe_award_writing_xp(user_id, lesson.id, db_session=db)
            db.session.commit()
        except Exception as xp_err:
            db.session.rollback()
            logger.warning(f"Translation XP award failed for lesson {lesson.id}: {xp_err}")

    try:
        from app.achievements.services import check_writing_achievements
        check_writing_achievements(user_id, db_session=db.session)
        db.session.commit()
    except Exception as ach_err:
        db.session.rollback()
        logger.warning(f"Writing achievements check failed for user {user_id}: {ach_err}")

    result = dict(grade)
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
    items = content.get('items') or []
    # Single-item legacy fields. Stay for backwards-compatible templates;
    # the multi-item flow reads from ``items``.
    incorrect_sentence = content.get('incorrect_sentence', '')
    correct_sentence = content.get('correct_sentence', '')
    error_type = content.get('error_type', '')
    error_type_ru = content.get('error_type_ru', '')
    translation = content.get('translation', '')
    explanation = content.get('explanation', '')
    options = content.get('options') or []

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    if request.args.get('reset') == 'true' and progress and progress.status in ('completed', 'in_progress'):
        progress.status = 'in_progress'
        progress.score = None
        progress.data = None
        progress.completed_at = None
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

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

    module_url = '/learn/'
    if lesson.module and lesson.module.level:
        module_url = url_for(
            'learn.learn_by_module',
            level_code=lesson.module.level.code.lower(),
            module_number=lesson.module.number,
        )

    is_completed = bool(progress and progress.status == 'completed')
    next_lesson_url = None
    if is_completed:
        nxt = _get_next_lesson_for_completion(lesson)
        if nxt:
            next_lesson_url = _lesson_completion_url(nxt)

    return render_template(
        'curriculum/lessons/sentence_correction.html',
        lesson=lesson,
        progress=progress,
        items=items,
        incorrect_sentence=incorrect_sentence,
        correct_sentence=correct_sentence,
        error_type=error_type,
        error_type_ru=error_type_ru,
        translation=translation,
        explanation=explanation,
        options=options,
        module_url=module_url,
        is_completed=is_completed,
        next_lesson_url=next_lesson_url,
    )


def _process_sentence_correction_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Grade a sentence correction submission, update progress, award XP, return result.

    Two payload shapes:
    - Multi-item: data['answers'] is a list — grade each against items[].correct_sentence.
    - Single-item legacy: data['user_answer'] is a string — grade against content.correct_sentence.
    """
    from app.curriculum.grading import grade_sentence_correction, grade_sentence_correction_multi
    from app.curriculum.models import save_writing_attempt
    from app.curriculum.services.progress_service import ProgressService

    content = lesson.content or {}
    items = content.get('items') or []
    is_multi = bool(items) and isinstance(data.get('answers'), list)

    if is_multi:
        user_answers = [(a or '')[:2000] for a in data.get('answers', [])]
        grade = grade_sentence_correction_multi(user_answers, items)
        passed = grade.get('passed', False)
        score_value = float(grade.get('score', 0))
    else:
        correct_sentence = content.get('correct_sentence', '')
        user_answer = (data.get('user_answer', '') or '')[:2000]
        single = grade_sentence_correction(user_answer, correct_sentence)
        passed = single.get('is_correct', False)
        score_value = 100.0 if passed else 0.0
        grade = {**single, 'passed': passed, 'explanation': content.get('explanation', '')}

    # UserWritingAttempt rows — one per submission. For multi we save the
    # joined answers; matches existing per-attempt analytics.
    try:
        if is_multi:
            joined = '\n'.join(filter(None, user_answers))
            save_writing_attempt(user_id, lesson.id, joined, passed, db)
        else:
            save_writing_attempt(user_id, lesson.id, user_answer, passed, db)
        db.session.flush()
    except Exception as save_err:
        logger.warning(f"Sentence correction writing attempt save failed for lesson {lesson.id}: {save_err}")
        db.session.rollback()

    ProgressService.update_progress_with_grading(
        user_id=user_id,
        lesson=lesson,
        result={'passed': passed, 'score': score_value, **grade},
        passing_score=PASSING_SCORE_DEFAULT,
    )

    if passed:
        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp, maybe_award_writing_xp
            with db.session.begin_nested():
                maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=score_value)
                maybe_award_writing_xp(user_id, lesson.id, db_session=db)
            db.session.commit()
        except Exception as xp_err:
            db.session.rollback()
            logger.warning(f"Sentence correction XP award failed for lesson {lesson.id}: {xp_err}")

    try:
        from app.achievements.services import check_writing_achievements
        check_writing_achievements(user_id, db_session=db.session)
        db.session.commit()
    except Exception as ach_err:
        db.session.rollback()
        logger.warning(f"Writing achievements check failed for user {user_id}: {ach_err}")

    next_lesson = _get_next_lesson_for_completion(lesson)
    if passed and next_lesson:
        grade['next_lesson_url'] = _lesson_completion_url(next_lesson)

    return grade


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
    prompt_ru = content.get('prompt_ru') or None
    min_words = content.get('min_words')
    min_sentences = content.get('min_sentences')
    # Default min_words=50 only if neither target is specified — preserves
    # legacy single-target behavior.
    if min_words is None and min_sentences is None:
        min_words = 50
    if min_words is not None:
        try:
            min_words = int(min_words)
        except (TypeError, ValueError):
            min_words = None
    if min_sentences is not None:
        try:
            min_sentences = int(min_sentences)
        except (TypeError, ValueError):
            min_sentences = None
    example_response = content.get('example_response') or None
    template_text = content.get('template') or None
    hint_words = content.get('hint_words') or []
    target_phrases = content.get('target_phrases') or []
    # Mode auto-derive when not specified: presence of guided-only fields
    # (min_sentences, hint_words, template) → 'guided'; else 'structured'.
    mode = content.get('mode')
    if not mode:
        mode = 'guided' if (min_sentences or hint_words or template_text) else 'structured'
    checklist = content.get('checklist') or _DEFAULT_WRITING_CHECKLIST
    # Threshold для чек-листа: guided требует структурный минимум 3 пункта
    # (имя/возраст/страна/нравится/приветствие — без 3 из них writing
    # фактически пустой). Остальные режимы — мягкий минимум 2.
    raw_min_checklist = content.get('min_checklist')
    try:
        min_checklist = int(raw_min_checklist) if raw_min_checklist else None
    except (TypeError, ValueError):
        min_checklist = None
    if not min_checklist:
        min_checklist = 3 if mode == 'guided' else 2
    # Clamp по фактическому размеру checklist — нельзя требовать больше
    # пунктов, чем существует.
    min_checklist = min(min_checklist, max(len(checklist), 2))

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    if request.args.get('reset') == 'true' and progress and progress.status in ('completed', 'in_progress'):
        progress.status = 'in_progress'
        progress.score = None
        progress.data = None
        progress.completed_at = None
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

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

    is_completed = bool(progress and progress.status == 'completed')
    next_lesson = _get_next_lesson_for_completion(lesson)

    return render_template(
        'curriculum/lessons/writing_prompt.html',
        lesson=lesson,
        progress=progress,
        prompt=prompt,
        prompt_ru=prompt_ru,
        min_words=min_words,
        min_sentences=min_sentences,
        example_response=example_response,
        template_text=template_text,
        hint_words=hint_words,
        target_phrases=target_phrases,
        mode=mode,
        checklist=checklist,
        min_checklist=min_checklist,
        is_completed=is_completed,
        next_lesson=next_lesson,
    )


def _process_writing_prompt_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Save a writing prompt attempt, mark lesson complete, award XP, return result."""
    from app.curriculum.models import save_writing_attempt

    def _normalize_phrase(value: str) -> str:
        return re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower().replace('\u2019', '').replace("'", '')).strip()

    content = lesson.content or {}
    example_response = content.get('example_response') or None
    response_text = (data.get('response_text') or '')[:20000].strip()
    raw_checked_items = data.get('checked_items') or []
    if not isinstance(raw_checked_items, list):
        raw_checked_items = []
    checklist = content.get('checklist') or _DEFAULT_WRITING_CHECKLIST
    checklist_set = {str(item) for item in checklist}
    valid_checked = {item for item in raw_checked_items if isinstance(item, str) and item in checklist_set}
    # Threshold согласуем с тем, что вычисляется в render_writing_prompt:
    # guided → 3, иначе → 2. Если в контенте задано явно — используем его.
    mode = content.get('mode') or (
        'guided' if (content.get('min_sentences') or content.get('hint_words') or content.get('template'))
        else 'structured'
    )
    raw_min_checklist = content.get('min_checklist')
    try:
        min_checklist = int(raw_min_checklist) if raw_min_checklist else None
    except (TypeError, ValueError):
        min_checklist = None
    if not min_checklist:
        min_checklist = 3 if mode == 'guided' else 2
    min_checklist = min(min_checklist, max(len(checklist), 2))
    # ``checklist_completed`` is derived purely from the server-side count of
    # validly-checked items. The historical client flag was redundant — and
    # a JS regression that forgot to set it would silently fail a perfectly
    # good submission. ``valid_checked`` already filters out anything not on
    # the checklist, so the count alone is the source of truth.
    checklist_completed = len(valid_checked) >= min_checklist
    # min_words / min_sentences — оба опциональны, нужно хотя бы одно.
    # Если есть min_sentences → проверяем по количеству предложений,
    # иначе по словам. Default 50 слов сохранён для legacy-контента.
    try:
        min_sentences = int(content.get('min_sentences') or 0)
    except (TypeError, ValueError):
        min_sentences = 0
    raw_min_words = content.get('min_words')
    if raw_min_words is None and not min_sentences:
        min_words = 50  # legacy default when ничего не задано
    else:
        try:
            min_words = int(raw_min_words) if raw_min_words is not None else 0
        except (TypeError, ValueError):
            min_words = 0

    word_count = len(response_text.split()) if response_text else 0
    # Sentence count: разделители .!? с любым whitespace вокруг.
    sentence_count = len([s for s in re.split(r'[.!?]+', response_text) if s.strip()])
    target_phrases = [
        phrase for phrase in (content.get('target_phrases') or [])
        if isinstance(phrase, str) and phrase.strip()
    ]
    normalized_response = f" {_normalize_phrase(response_text)} "
    matched_target_phrases = [
        phrase for phrase in target_phrases
        if _normalize_phrase(phrase) and f" {_normalize_phrase(phrase)} " in normalized_response
    ]
    target_phrases_required = bool(target_phrases and mode == 'guided')
    target_phrases_met = (not target_phrases_required) or bool(matched_target_phrases)

    meets_min_words = (min_words == 0) or (word_count >= min_words)
    meets_min_sentences = (min_sentences == 0) or (sentence_count >= min_sentences)
    meets_min = meets_min_words and meets_min_sentences

    completed = meets_min and checklist_completed and target_phrases_met

    if meets_min:
        try:
            with db.session.begin_nested():
                save_writing_attempt(user_id, lesson.id, response_text, checklist_completed, db)
                db.session.flush()
        except Exception as save_err:
            logger.warning(f"Writing attempt save failed for lesson {lesson.id}: {save_err}")

    if completed:
        progress = LessonProgress.query.filter_by(
            user_id=user_id, lesson_id=lesson.id
        ).first()
        # Сохраняем response_text + checked_items в progress.data —
        # на reload урок восстановит ответ и галочки, чтобы пользователь
        # видел свою работу, а не пустую форму.
        progress_data = {
            'response_text': response_text,
            'checked_items': sorted(valid_checked),
            'word_count': word_count,
            'sentence_count': sentence_count,
            'matched_target_phrases': matched_target_phrases,
        }
        if progress:
            progress.status = 'completed'
            if not progress.completed_at:
                progress.completed_at = datetime.now(UTC)
            progress.last_activity = datetime.now(UTC)
            progress.data = progress_data
            flag_modified(progress, 'data')
        else:
            progress = LessonProgress(
                user_id=user_id,
                lesson_id=lesson.id,
                status='completed',
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                last_activity=datetime.now(UTC),
                data=progress_data,
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
            writing_score = round(len(valid_checked) / len(checklist) * 100) if checklist else 100
            with db.session.begin_nested():
                maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=writing_score)
                maybe_award_writing_xp(user_id, lesson.id, db_session=db)
            db.session.commit()
        except Exception as xp_err:
            db.session.rollback()
            logger.warning(f"Writing prompt XP award failed for lesson {lesson.id}: {xp_err}")

        try:
            from app.achievements.services import check_writing_achievements
            check_writing_achievements(user_id, db_session=db.session)
            db.session.commit()
        except Exception as ach_err:
            db.session.rollback()
            logger.warning(f"Writing achievements check failed for user {user_id}: {ach_err}")

    result: dict = {
        'success': True,
        'completed': completed,
        'word_count': word_count,
        'sentence_count': sentence_count,
        'meets_min_words': meets_min_words,
        'meets_min_sentences': meets_min_sentences,
        'checklist_completed': checklist_completed,
        'target_phrases_required': target_phrases_required,
        'target_phrases_met': target_phrases_met,
        'matched_target_phrases': matched_target_phrases,
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

    module_url = '/learn/'
    if lesson.module and lesson.module.level:
        module_url = url_for(
            'learn.learn_by_module',
            level_code=lesson.module.level.code.lower(),
            module_number=lesson.module.number,
        )

    is_completed = bool(progress and progress.status == 'completed')
    next_lesson_url = None
    if is_completed:
        next_lesson = _get_next_lesson_for_completion(lesson)
        if next_lesson:
            next_lesson_url = _lesson_completion_url(next_lesson)

    return render_template(
        'curriculum/lessons/sentence_completion.html',
        lesson=lesson,
        progress=progress,
        items=items,
        module_url=module_url,
        is_completed=is_completed,
        next_lesson_url=next_lesson_url,
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
    user_answers = [(str(a) if a is not None else '')[:2000] for a in user_answers]

    grade = grade_sentence_completion(user_answers, items)

    ProgressService.update_progress_with_grading(
        user_id=user_id,
        lesson=lesson,
        result=grade,
        passing_score=PASSING_SCORE_DEFAULT,
    )

    if grade.get('passed'):
        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp
            with db.session.begin_nested():
                maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=grade['score'])
            db.session.commit()
        except Exception as xp_err:
            db.session.rollback()
            logger.warning(f"Sentence completion XP award failed for lesson {lesson.id}: {xp_err}")

    result = {**grade}
    # Only reveal model answers after the lesson is passed; on failure,
    # strip the `answer` field from per-item results so DevTools inspection
    # can't bypass the retry attempt.
    if not grade.get('passed'):
        result['item_results'] = [
            {k: v for k, v in r.items() if k != 'answer'}
            for r in result.get('item_results', [])
        ]
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

    is_completed = bool(progress and progress.status == 'completed')
    next_lesson_url = None
    if is_completed:
        next_lesson = _get_next_lesson_for_completion(lesson)
        if next_lesson:
            next_lesson_url = _lesson_completion_url(next_lesson)

    # URL of the parent module's lessons page — preferred destination for the
    # "К списку уроков" secondary CTA. Generic /learn/ would drop the user on
    # the curriculum index, one level too high.
    module_url = '/learn/'
    if lesson.module and lesson.module.level:
        module_url = url_for(
            'learn.learn_by_module',
            level_code=lesson.module.level.code.lower(),
            module_number=lesson.module.number,
        )

    return render_template(
        'curriculum/lessons/collocation_matching.html',
        lesson=lesson,
        progress=progress,
        pairs=pairs,
        shuffled_pairs=shuffled_pairs,
        is_completed=is_completed,
        next_lesson_url=next_lesson_url,
        module_url=module_url,
    )


def _process_collocation_matching_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Grade a collocation matching submission, update progress, award XP, return result."""
    from app.curriculum.grading import grade_collocation_matching
    from app.curriculum.services.progress_service import ProgressService

    content = lesson.content or {}
    correct_pairs = content.get('pairs', [])
    user_pairs = data.get('user_pairs', [])
    if not isinstance(user_pairs, list):
        user_pairs = []
    max_pairs = max(len(correct_pairs) * 2, 50)
    user_pairs = user_pairs[:max_pairs]

    grade = grade_collocation_matching(user_pairs, correct_pairs)

    ProgressService.update_progress_with_grading(
        user_id=user_id,
        lesson=lesson,
        result=grade,
        passing_score=PASSING_SCORE_DEFAULT,
    )

    if grade.get('passed'):
        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp
            with db.session.begin_nested():
                maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=grade['score'])
        except Exception as xp_err:
            logger.warning(f"Collocation matching XP award failed for lesson {lesson.id}: {xp_err}")
    db.session.commit()

    # Return the full per-pair grading including the correct translation for
    # wrong pairs — the template renders a "Правильно: ..." correction line
    # so the user learns from the mistake. The lesson is teaching, not
    # testing; a guess-and-retry loop without feedback teaches nothing.
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

    next_lesson = _get_next_lesson_for_completion(lesson)
    is_completed = bool(progress and progress.status == 'completed')

    return render_template(
        'curriculum/lessons/shadow_reading.html',
        lesson=lesson,
        progress=progress,
        audio_url=audio_url,
        text=text,
        translation=translation,
        words=words,
        next_lesson=next_lesson,
        is_completed=is_completed,
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
            with db.session.begin_nested():
                maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=None)
            db.session.commit()
        except Exception as xp_err:
            db.session.rollback()
            logger.warning(f"Shadow reading XP award failed for lesson {lesson.id}: {xp_err}")


    result: dict = {'success': True, 'completed': self_assessed}
    if self_assessed:
        next_lesson = _get_next_lesson_for_completion(lesson)
        if next_lesson:
            result['next_lesson_url'] = _lesson_completion_url(next_lesson)

    return result


def _process_listening_immersion_submission(lesson: 'Lessons', user_id: int, data: dict) -> dict:
    """Mark listening immersion lesson complete on self-assessment.

    Awards curriculum + listening XP and logs a ListeningAttempt.
    """
    self_assessed = bool(data.get('self_assessed', False))
    if not self_assessed:
        return {'success': True, 'completed': False}

    progress = LessonProgress.query.filter_by(
        user_id=user_id, lesson_id=lesson.id
    ).first()
    was_already_completed = bool(progress and progress.status == 'completed')
    if progress:
        progress.status = 'completed'
        progress.score = 100.0
        if not progress.completed_at:
            progress.completed_at = datetime.now(UTC)
        progress.last_activity = datetime.now(UTC)
    else:
        progress = LessonProgress(
            user_id=user_id,
            lesson_id=lesson.id,
            status='completed',
            score=100.0,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            last_activity=datetime.now(UTC),
        )
        db.session.add(progress)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    if not was_already_completed:
        try:
            from app.curriculum.listening_service import log_listening_attempt
            log_listening_attempt(user_id, lesson.id, 100.0, 0, db)
            db.session.commit()
        except Exception as log_err:
            logger.warning(f"Listening attempt log failed for lesson {lesson.id}: {log_err}")
            db.session.rollback()

    try:
        from app.daily_plan.linear.xp import maybe_award_curriculum_xp, maybe_award_listening_xp
        with db.session.begin_nested():
            maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=None)
            maybe_award_listening_xp(user_id, lesson.id, score=100.0, db_session=db)
        db.session.commit()
    except Exception as xp_err:
        db.session.rollback()
        logger.warning(f"Listening immersion XP award failed for lesson {lesson.id}: {xp_err}")

    try:
        from app.achievements.services import check_listening_achievements
        check_listening_achievements(user_id, db_session=db.session)
        db.session.commit()
    except Exception as ach_err:
        db.session.rollback()
        logger.warning(f"Listening achievements check failed for user {user_id}: {ach_err}")

    result: dict = {'success': True, 'completed': True}
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
        # Validate that the user has made at least one attempt before finishing
        from app.curriculum.models import PronunciationAttempt
        pron_content = lesson.content or {}
        pron_items = pron_content.get('items') or []
        lesson_words = {str(item.get('word') or '') for item in pron_items if item.get('word')}
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        pron_attempts = PronunciationAttempt.query.filter(
            PronunciationAttempt.user_id == user_id,
            PronunciationAttempt.created_at >= today_start,
        ).all()
        relevant = [a for a in pron_attempts if a.word in lesson_words] if lesson_words else pron_attempts
        if not relevant:
            return {'success': False, 'error': 'requires_attempt', 'message': 'Необходимо сделать хотя бы одну попытку'}

        pron_score = round(sum(1 for a in relevant if a.matched) / len(relevant) * 100)

        # Final submission — mark lesson completed and award XP
        progress = LessonProgress.query.filter_by(
            user_id=user_id, lesson_id=lesson.id
        ).first()
        if progress:
            progress.status = 'completed'
            if not progress.completed_at:
                progress.completed_at = datetime.now(UTC)
            progress.last_activity = datetime.now(UTC)
            progress.score = pron_score
        else:
            progress = LessonProgress(
                user_id=user_id,
                lesson_id=lesson.id,
                status='completed',
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                last_activity=datetime.now(UTC),
                score=pron_score,
            )
            db.session.add(progress)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        try:
            from app.daily_plan.linear.xp import maybe_award_curriculum_xp
            with db.session.begin_nested():
                maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=pron_score)
            db.session.commit()
        except Exception as xp_err:
            db.session.rollback()
            logger.warning(f"Pronunciation XP award failed for lesson {lesson.id}: {xp_err}")

        try:
            from app.achievements.services import check_speaking_achievements
            check_speaking_achievements(user_id, db_session=db.session)
            db.session.commit()
        except Exception as ach_err:
            db.session.rollback()
            logger.warning(f"Speaking achievements check failed for user {user_id}: {ach_err}")

        result: dict = {'success': True, 'completed': True}
        next_lesson = _get_next_lesson_for_completion(lesson)
        if next_lesson:
            result['next_lesson_url'] = _lesson_completion_url(next_lesson)
        return result

    # Single-item attempt — resolve target word from the lesson content server-side
    # so a client cannot submit a matching pair to game speaking achievements.
    content = lesson.content or {}
    items = content.get('items') or []
    try:
        item_index = int(data.get('item_index', -1))
    except (TypeError, ValueError):
        item_index = -1
    if 0 <= item_index < len(items):
        target_word = str(items[item_index].get('word') or '')[:200]
    else:
        target_word = ''
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
            db.session.commit()
        except Exception as ach_err:
            db.session.rollback()
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
        db.session.commit()
    except Exception as ach_err:
        db.session.rollback()
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
        with db.session.begin_nested():
            maybe_award_curriculum_xp(user_id, lesson, db_session=db, score=None)
        db.session.commit()
    except Exception as xp_err:
        db.session.rollback()
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
    from app.curriculum.models import save_lesson_feedback

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


import app.curriculum.routes.card_lessons  # noqa: E402, F401
import app.curriculum.routes.grammar_quiz_lessons  # noqa: E402, F401

# Import route modules to register their routes on lessons_bp
import app.curriculum.routes.vocabulary_lessons  # noqa: E402, F401
