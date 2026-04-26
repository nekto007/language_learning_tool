import html
import json
import logging
import random
from datetime import UTC, datetime

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from marshmallow import ValidationError

from app.curriculum.models import LessonProgress, Lessons
from app.curriculum.routes.lessons import lessons_bp
from app.curriculum.security import require_lesson_access, sanitize_html
from app.curriculum.grading import check_final_test_attempts_exhausted
from app.curriculum.service import get_next_lesson, process_quiz_submission
from app.curriculum.services.progress_service import ProgressService
from app.curriculum.validators import LessonContentValidator
from app.daily_plan.linear.errors import log_quiz_errors_from_result
from app.daily_plan.linear.grammar_theory import get_theory_for_lesson
from app.utils.db import db

logger = logging.getLogger(__name__)


def render_grammar_lesson(lesson):
    """Рендер grammar урока"""
    if lesson.type != 'grammar':
        abort(400, "This is not a grammar lesson")

    try:
        is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
            'grammar', lesson.content
        )
    except ValidationError as e:
        error_msg = str(e.messages)
        logger.error(f"Invalid grammar content for lesson {lesson.id}: {error_msg}")
        flash(f'Ошибка в содержимом урока: {error_msg}', 'error')
        return redirect('/learn/')

    if not is_valid:
        logger.error(f"Invalid grammar content for lesson {lesson.id}: {error_msg}")
        flash(f'Ошибка в содержимом урока: {error_msg}', 'error')
        return redirect('/learn/')

    for field in ['content', 'rule', 'text', 'title', 'description']:
        if field in cleaned_content:
            cleaned_content[field] = sanitize_html(cleaned_content[field])

    if 'examples' in cleaned_content:
        if cleaned_content['examples'] and isinstance(cleaned_content['examples'][0], dict):
            for example in cleaned_content['examples']:
                if 'sentence' in example:
                    example['sentence'] = sanitize_html(example['sentence'])
                if 'translation' in example:
                    example['translation'] = sanitize_html(example['translation'])
        else:
            cleaned_content['examples'] = [
                sanitize_html(ex) if isinstance(ex, str) else ex
                for ex in cleaned_content['examples']
            ]

    reset_progress = request.args.get('reset') == 'true'

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    if reset_progress and progress:
        progress.status = 'in_progress'
        progress.score = None
        progress.data = None
        progress.completed_at = None
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

    next_lesson = get_next_lesson(lesson.id)

    grammar_rule = cleaned_content.get('title') or cleaned_content.get('rule') or lesson.title
    grammar_description = cleaned_content.get('content') or cleaned_content.get('description') or cleaned_content.get('text', '')
    examples = cleaned_content.get('examples', [])
    exercises = cleaned_content.get('exercises', [])
    grammar_explanation = cleaned_content.get('grammar_explanation')

    if not grammar_explanation and cleaned_content.get('sections'):
        grammar_explanation = {
            'title': cleaned_content.get('title', ''),
            'introduction': cleaned_content.get('description', ''),
            'sections': cleaned_content.get('sections', []),
            'important_notes': cleaned_content.get('important_notes', []),
            'summary': cleaned_content.get('summary', {})
        }

    if grammar_explanation:
        def decode_html_in_dict(obj):
            if isinstance(obj, dict):
                return {k: decode_html_in_dict(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [decode_html_in_dict(item) for item in obj]
            elif isinstance(obj, str):
                return html.unescape(obj)
            else:
                return obj
        grammar_explanation = decode_html_in_dict(grammar_explanation)

    if request.method == 'POST':
        try:
            answers = {}
            for key in request.form:
                if key.startswith('answer_'):
                    exercise_idx = key.replace('answer_', '')
                    answers[exercise_idx] = request.form[key]

            from app.curriculum.service import process_grammar_submission as service_process_grammar
            result = service_process_grammar(exercises, answers)

        except Exception as e:
            logger.error(f"Error processing grammar submission: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': False,
                    'error': 'Ошибка при обработке ответов.'
                }), 500
            else:
                flash('Ошибка при обработке ответов', 'error')
                return redirect(f'/learn/{lesson.id}/')

        try:
            log_quiz_errors_from_result(
                current_user.id,
                lesson.id,
                exercises,
                result,
                db,
                source='grammar',
            )
        except Exception as log_error:
            logger.warning(f"Failed to log grammar errors for lesson {lesson.id}: {log_error}")

        progress, completion_result = ProgressService.update_progress_with_grading(
            user_id=current_user.id,
            lesson=lesson,
            result=result,
            passing_score=70
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            response_data = {
                'success': True,
                'score': result.get('score', 0),
                'feedback': result.get('feedback', {}),
                'correct_answers': result.get('correct_answers', 0),
                'total_questions': result.get('total_questions', 0)
            }
            if completion_result:
                response_data['grade'] = completion_result['grade']
                response_data['grade_name'] = completion_result['grade_name']
                response_data['new_achievements'] = completion_result['new_achievements']
            return jsonify(response_data)

    theory_topic = _resolve_grammar_theory(current_user.id, lesson)

    return render_template(
        'curriculum/lessons/grammar.html',
        lesson=lesson,
        content=cleaned_content,
        grammar_rule=grammar_rule,
        grammar_description=grammar_description,
        examples=examples,
        exercises=exercises,
        grammar_explanation=grammar_explanation,
        theory_topic=theory_topic,
        progress=progress,
        next_lesson=next_lesson
    )


def _resolve_grammar_theory(user_id: int, lesson: Lessons):
    """Fetch (and record) the grammar-lab theory topic linked to this lesson.

    Delegates to ``get_theory_for_lesson`` with ``commit=True`` so the new
    ``GrammarTheoryView`` row is persisted immediately. The helper already
    swallows and rolls back internal failures, so we only need to guard
    against unexpected errors from the caller's perspective.
    """
    try:
        return get_theory_for_lesson(user_id, lesson, db, commit=True)
    except Exception:  # noqa: BLE001
        logger.exception(
            'grammar_theory: unexpected error user=%s lesson=%s', user_id, lesson.id,
        )
        db.session.rollback()
        return None


def _sanitize_quiz_questions(cleaned_content: dict) -> None:
    """Sanitize and normalize quiz question content in-place."""
    for question in cleaned_content['questions']:
        if 'question' in question:
            question['question'] = html.unescape(sanitize_html(question['question']))
        elif 'prompt' in question:
            question['question'] = html.unescape(sanitize_html(question['prompt']))

        if 'sentence' in question:
            question['sentence'] = html.unescape(question['sentence'])

        if 'options' in question:
            sanitized_options = [html.unescape(sanitize_html(opt)) for opt in question['options']]
            seen = set()
            unique_options = []
            for opt in sanitized_options:
                if opt not in seen:
                    seen.add(opt)
                    unique_options.append(opt)
            question['options'] = unique_options

        if 'explanation' in question:
            question['explanation'] = html.unescape(sanitize_html(question['explanation']))

        if 'correct_index' in question and 'correct' not in question:
            question['correct'] = question['correct_index']

        if 'answer' in question and 'correct_answer' not in question:
            question['correct_answer'] = question['answer']

        if question.get('type') == 'matching' and 'pairs' in question:
            normalized_pairs = []
            for pair in question['pairs']:
                if 'left' in pair and 'right' in pair:
                    normalized_pairs.append(pair)
                elif 'english' in pair and 'russian' in pair:
                    normalized_pairs.append({
                        'left': pair['english'],
                        'right': pair['russian'],
                        'hint': pair.get('hint')
                    })
            question['pairs'] = normalized_pairs
            right_items = [pair['right'] for pair in normalized_pairs]
            random.shuffle(right_items)
            question['shuffled_right_items'] = right_items

        if question.get('type') in ['ordering', 'reorder'] and 'words' in question:
            shuffled_words = question['words'][:]
            random.shuffle(shuffled_words)
            question['shuffled_words'] = shuffled_words

        if question.get('type') in ['multiple_choice', 'fill_blank', 'fill_in_blank', 'listening_choice', 'dialogue_completion'] and 'options' in question and len(question['options']) > 0:
            correct_answer = question.get('correct') or question.get('correct_answer') or question.get('answer')
            original_correct_index = None
            if isinstance(correct_answer, str):
                for i, opt in enumerate(question['options']):
                    if opt.lower().strip() == correct_answer.lower().strip():
                        original_correct_index = i
                        break
            elif isinstance(correct_answer, int):
                original_correct_index = correct_answer

            shuffled_options = question['options'][:]
            random.shuffle(shuffled_options)

            if original_correct_index is not None and original_correct_index < len(question['options']):
                original_correct_text = question['options'][original_correct_index]
                new_correct_index = shuffled_options.index(original_correct_text)
                question['correct_index'] = new_correct_index
                question['correct'] = new_correct_index

            question['options'] = shuffled_options


def render_quiz_lesson(lesson):
    """Рендер quiz урока"""
    quiz_types = ['quiz', 'ordering_quiz', 'translation_quiz', 'listening_quiz',
                  'dialogue_completion_quiz', 'listening_immersion_quiz']
    if lesson.type not in quiz_types:
        abort(400, "This is not a quiz lesson")

    try:
        is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
            'quiz', lesson.content
        )
    except ValidationError as e:
        error_msg = str(e.messages)
        logger.error(f"Invalid quiz content for lesson {lesson.id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    if not is_valid:
        logger.error(f"Invalid quiz content for lesson {lesson.id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    _sanitize_quiz_questions(cleaned_content)

    reset_progress = request.args.get('reset') == 'true'

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    if reset_progress and progress:
        progress.status = 'in_progress'
        progress.score = None
        progress.data = None
        progress.completed_at = None
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

    if not progress:
        progress = LessonProgress(
            user_id=current_user.id,
            lesson_id=lesson.id,
            status='in_progress',
            started_at=datetime.now(UTC),
            last_activity=datetime.now(UTC)
        )
        db.session.add(progress)
        db.session.commit()

    if request.method == 'POST':
        answers = {}
        for key in request.form:
            if key.startswith('answer_'):
                question_idx = key.replace('answer_', '')
                try:
                    idx = int(question_idx)
                    answers[idx] = request.form[key]
                except ValueError:
                    logger.error(f"Invalid question index: {question_idx}")

        if 'client_results' in request.form:
            try:
                client_results = json.loads(request.form['client_results'])
                client_score = float(request.form['client_score'])
                client_correct_count = int(request.form.get('client_correct_count') or request.form.get('client_correct_answers') or 0)

                feedback = _build_quiz_feedback(client_results, cleaned_content['questions'])

                result = {
                    'score': client_score,
                    'correct_answers': client_correct_count,
                    'total_questions': len(cleaned_content['questions']),
                    'feedback': feedback,
                    'answers': answers
                }
            except (ValueError, TypeError) as e:
                logger.error(f"Invalid client results data: {e}")
                result = process_quiz_submission(cleaned_content['questions'], answers)
        else:
            result = process_quiz_submission(cleaned_content['questions'], answers)
            if 'client_score' in request.form:
                try:
                    client_score = float(request.form['client_score'])
                    client_correct_count = int(request.form.get('client_correct_count') or request.form.get('client_correct_answers') or 0)
                    result['score'] = client_score
                    result['correct_answers'] = client_correct_count
                except (ValueError, TypeError) as e:
                    logger.error(f"Invalid client score data: {e}")

        try:
            log_quiz_errors_from_result(
                current_user.id,
                lesson.id,
                cleaned_content['questions'],
                result,
                db,
            )
        except Exception as log_error:
            logger.warning(f"Failed to log quiz errors for lesson {lesson.id}: {log_error}")

        progress, completion_result = ProgressService.update_progress_with_grading(
            user_id=current_user.id,
            lesson=lesson,
            result=result,
            passing_score=70
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            response_data = {
                'success': True,
                'score': result.get('score', 0),
                'feedback': result.get('feedback', {}),
                'correct_answers': result.get('correct_answers', 0),
                'total_questions': result.get('total_questions', 0)
            }
            if completion_result:
                response_data['grade'] = completion_result['grade']
                response_data['grade_name'] = completion_result['grade_name']
                response_data['new_achievements'] = completion_result['new_achievements']
            return jsonify(response_data)

    next_lesson = get_next_lesson(lesson.id)

    return render_template(
        'curriculum/lessons/quiz.html',
        lesson=lesson,
        questions=cleaned_content['questions'],
        settings=cleaned_content,
        progress=progress,
        next_lesson=next_lesson
    )


def _build_quiz_feedback(client_results: list, questions: list) -> dict:
    """Build feedback dict from client-side quiz results."""
    feedback = {}
    for item in client_results:
        q_idx = item['question_index']
        is_correct = item['is_correct']
        attempts = item['attempts']
        user_answer = item['answer']
        question = questions[q_idx]
        correct_answer = question.get('correct_answer') or question.get('correct') or question.get('answer')

        if question.get('type') == 'matching' and 'pairs' in question:
            correct_answer = ', '.join(
                f"{p.get('left', '')} → {p.get('right', '')}"
                for p in question['pairs']
            )

        q_type = question.get('type', '')
        if q_type in ('multiple_choice', 'fill_blank', 'fill_in_blank', 'listening_choice', 'dialogue_completion') and 'options' in question:
            opts = question['options']
            if isinstance(correct_answer, int) and 0 <= correct_answer < len(opts):
                correct_answer = opts[correct_answer]
            elif isinstance(correct_answer, str) and correct_answer.isdigit():
                ca_idx = int(correct_answer)
                if 0 <= ca_idx < len(opts):
                    correct_answer = opts[ca_idx]
                elif 1 <= ca_idx <= len(opts):
                    correct_answer = opts[ca_idx - 1]
            if isinstance(user_answer, str) and user_answer.isdigit():
                ua_idx = int(user_answer)
                if 0 <= ua_idx < len(opts):
                    user_answer = opts[ua_idx]
                elif 1 <= ua_idx <= len(opts):
                    user_answer = opts[ua_idx - 1]

        if is_correct:
            feedback[str(q_idx)] = {
                'status': 'correct',
                'message': 'Правильно!' if attempts == 1 else f'Правильно! (попытка {attempts})',
                'user_answer': user_answer,
                'correct_answer': correct_answer,
                'attempts': attempts
            }
        else:
            feedback[str(q_idx)] = {
                'status': 'incorrect',
                'message': f'Неправильно. Правильный ответ: {correct_answer}',
                'user_answer': user_answer,
                'correct_answer': correct_answer,
                'attempts': attempts
            }

    return feedback


def render_final_test_lesson(lesson):
    """Рендер final_test урока"""
    if lesson.type != 'final_test':
        abort(400, "This is not a final test lesson")

    try:
        is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
            'final_test', lesson.content
        )
    except ValidationError as e:
        error_msg = str(e.messages)
        logger.error(f"Invalid final test content for lesson {lesson.id}: {error_msg}")
        flash('Ошибка в содержимом финального теста', 'error')
        return redirect('/learn/')

    if not is_valid:
        logger.error(f"Invalid final test content for lesson {lesson.id}: {error_msg}")
        flash('Ошибка в содержимом финального теста', 'error')
        return redirect('/learn/')

    questions_to_sanitize = []
    sections_list = cleaned_content.get('test_sections') or cleaned_content.get('sections') or []
    if sections_list:
        for section in sections_list:
            questions_to_sanitize.extend(section.get('exercises') or section.get('questions') or [])
    else:
        questions_field = 'exercises' if 'exercises' in cleaned_content else 'questions'
        questions_to_sanitize = cleaned_content.get(questions_field, [])

    for question in questions_to_sanitize:
        if 'question' in question:
            question['question'] = sanitize_html(question['question'])
        elif 'prompt' in question:
            question['question'] = sanitize_html(question['prompt'])

        if 'options' in question:
            question['options'] = [sanitize_html(opt) for opt in question['options']]

        if 'explanation' in question:
            question['explanation'] = sanitize_html(question['explanation'])

        if 'correct_index' in question and 'correct' not in question:
            question['correct'] = question['correct_index']

        if 'answer' in question and 'correct_answer' not in question:
            question['correct_answer'] = question['answer']

    reset_progress = request.args.get('reset') == 'true'

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    if reset_progress and progress:
        progress.status = 'in_progress'
        progress.score = None
        progress.data = None
        progress.completed_at = None
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

    if request.method == 'POST':
        rate_limit = check_final_test_attempts_exhausted(current_user.id, lesson.id, db_session=db)
        if rate_limit is not None:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, **rate_limit}), 429
            flash('Достигнут лимит попыток финального теста. Попробуйте позже.', 'error')
            return redirect(url_for('curriculum.lesson_by_id', lesson_id=lesson.id))

        answers = {}
        for key in request.form:
            if key.startswith('answer_'):
                question_idx = key.replace('answer_', '')
                try:
                    idx = int(question_idx)
                    answers[idx] = request.form[key]
                except ValueError:
                    logger.error(f"Invalid question index: {question_idx}")

        all_questions = []
        sections_list = cleaned_content.get('test_sections') or cleaned_content.get('sections') or []
        if sections_list:
            for section in sections_list:
                all_questions.extend(section.get('exercises') or section.get('questions') or [])
        else:
            questions_field = 'exercises' if 'exercises' in cleaned_content else 'questions'
            all_questions = cleaned_content.get(questions_field, [])

        result = process_quiz_submission(all_questions, answers)
        passing_score = cleaned_content.get('passing_score_percent', cleaned_content.get('passing_score', 70))

        try:
            log_quiz_errors_from_result(
                current_user.id,
                lesson.id,
                all_questions,
                result,
                db,
            )
        except Exception as log_error:
            logger.warning(f"Failed to log quiz errors for lesson {lesson.id}: {log_error}")

        progress, completion_result = ProgressService.update_progress_with_grading(
            user_id=current_user.id,
            lesson=lesson,
            result=result,
            passing_score=passing_score
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            response_data = {
                'success': True,
                'score': result.get('score', 0),
                'feedback': result.get('feedback', {}),
                'correct_count': result.get('correct_count', 0),
                'total_count': result.get('total_count', 0),
                'passing_score': passing_score,
                'passed': result.get('score', 0) >= passing_score
            }
            if completion_result:
                response_data['grade'] = completion_result['grade']
                response_data['grade_name'] = completion_result['grade_name']
                response_data['new_achievements'] = completion_result['new_achievements']
            return jsonify(response_data)
        else:
            return redirect(url_for('curriculum_lessons.final_test_results', lesson_id=lesson.id))

    next_lesson = get_next_lesson(lesson.id)

    sections_list = cleaned_content.get('test_sections') or cleaned_content.get('sections') or []
    if sections_list:
        questions = []
        for section in sections_list:
            questions.extend(section.get('exercises') or section.get('questions') or [])
    else:
        questions = cleaned_content.get('exercises', cleaned_content.get('questions', []))

    return render_template(
        'curriculum/lessons/final_test.html',
        lesson=lesson,
        questions=questions,
        exercises=questions,
        settings=cleaned_content,
        progress=progress,
        next_lesson=next_lesson,
        passing_score=cleaned_content.get('passing_score_percent', cleaned_content.get('passing_score', 70))
    )


@lessons_bp.route('/lesson/<int:lesson_id>/grammar', methods=['GET', 'POST'])
@login_required
@require_lesson_access
def grammar_lesson(lesson_id):
    """Display grammar lesson with sanitized content"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type != 'grammar':
        abort(400, "This is not a grammar lesson")

    try:
        is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
            'grammar', lesson.content
        )
    except ValidationError as e:
        error_msg = str(e.messages)
        logger.error(f"Invalid grammar content for lesson {lesson_id}: {error_msg}")
        flash(f'Ошибка в содержимом урока: {error_msg}', 'error')
        return redirect('/learn/')

    if not is_valid:
        logger.error(f"Invalid grammar content for lesson {lesson_id}: {error_msg}")
        flash(f'Ошибка в содержимом урока: {error_msg}', 'error')
        return redirect('/learn/')

    for field in ['content', 'rule', 'text', 'title', 'description']:
        if field in cleaned_content:
            cleaned_content[field] = sanitize_html(cleaned_content[field])

    if 'examples' in cleaned_content:
        if cleaned_content['examples'] and isinstance(cleaned_content['examples'][0], dict):
            for example in cleaned_content['examples']:
                if 'sentence' in example:
                    example['sentence'] = sanitize_html(example['sentence'])
                if 'translation' in example:
                    example['translation'] = sanitize_html(example['translation'])
        else:
            cleaned_content['examples'] = [
                sanitize_html(ex) if isinstance(ex, str) else ex
                for ex in cleaned_content['examples']
            ]

    reset_progress = request.args.get('reset') == 'true'

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    if reset_progress and progress:
        progress.status = 'in_progress'
        progress.score = None
        progress.data = None
        progress.completed_at = None
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

    next_lesson = get_next_lesson(lesson.id)

    grammar_rule = cleaned_content.get('title') or cleaned_content.get('rule') or lesson.title
    grammar_description = cleaned_content.get('content') or cleaned_content.get('description') or cleaned_content.get(
        'text', '')
    examples = cleaned_content.get('examples', [])
    exercises = cleaned_content.get('exercises', [])
    grammar_explanation = cleaned_content.get('grammar_explanation')

    if grammar_explanation:
        def decode_html_in_dict(obj):
            if isinstance(obj, dict):
                return {k: decode_html_in_dict(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [decode_html_in_dict(item) for item in obj]
            elif isinstance(obj, str):
                return html.unescape(obj)
            else:
                return obj

        grammar_explanation = decode_html_in_dict(grammar_explanation)

    if request.method == 'POST':
        try:
            answers = {}
            for key in request.form:
                if key.startswith('answer_'):
                    exercise_idx = key.replace('answer_', '')
                    answers[exercise_idx] = request.form[key]

            from app.curriculum.service import process_grammar_submission as service_process_grammar
            result = service_process_grammar(exercises, answers)

        except Exception as e:
            logger.error(f"Error processing grammar submission: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': False,
                    'error': 'Ошибка при обработке ответов. Пожалуйста, попробуйте снова.'
                }), 500
            else:
                flash('Ошибка при обработке ответов', 'error')
                return redirect(url_for('curriculum_lessons.grammar_lesson', lesson_id=lesson_id))

        try:
            log_quiz_errors_from_result(
                current_user.id,
                lesson.id,
                exercises,
                result,
                db,
                source='grammar',
            )
        except Exception as log_error:
            logger.warning(f"Failed to log grammar errors for lesson {lesson.id}: {log_error}")

        progress, completion_result = ProgressService.update_progress_with_grading(
            user_id=current_user.id,
            lesson=lesson,
            result=result,
            passing_score=70
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            response_data = {
                'success': True,
                'score': result.get('score', 0),
                'feedback': result.get('feedback', {}),
                'correct_answers': result.get('correct_answers', 0),
                'total_questions': result.get('total_questions', 0)
            }
            if completion_result:
                response_data['grade'] = completion_result['grade']
                response_data['grade_name'] = completion_result['grade_name']
                response_data['new_achievements'] = completion_result['new_achievements']
            return jsonify(response_data)

    theory_topic = _resolve_grammar_theory(current_user.id, lesson)

    return render_template(
        'curriculum/lessons/grammar.html',
        lesson=lesson,
        content=cleaned_content,
        grammar_rule=grammar_rule,
        grammar_description=grammar_description,
        examples=examples,
        exercises=exercises,
        grammar_explanation=grammar_explanation,
        theory_topic=theory_topic,
        progress=progress,
        next_lesson=next_lesson
    )


@lessons_bp.route('/lesson/<int:lesson_id>/quiz', methods=['GET', 'POST'])
@login_required
@require_lesson_access
def quiz_lesson(lesson_id):
    """Display quiz lesson with sanitized questions"""
    lesson = Lessons.query.get_or_404(lesson_id)

    quiz_types = ['quiz', 'ordering_quiz', 'translation_quiz', 'listening_quiz',
                  'dialogue_completion_quiz', 'listening_immersion_quiz']
    if lesson.type not in quiz_types:
        abort(400, "This is not a quiz lesson")

    try:
        is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
            'quiz', lesson.content
        )
    except ValidationError as e:
        error_msg = str(e.messages)
        logger.error(f"Invalid quiz content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    if not is_valid:
        logger.error(f"Invalid quiz content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    _sanitize_quiz_questions(cleaned_content)

    reset_progress = request.args.get('reset') == 'true'

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    if reset_progress and progress:
        progress.status = 'in_progress'
        progress.score = None
        progress.data = None
        progress.completed_at = None
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

    if not progress:
        progress = LessonProgress(
            user_id=current_user.id,
            lesson_id=lesson.id,
            status='in_progress',
            started_at=datetime.now(UTC),
            last_activity=datetime.now(UTC)
        )
        db.session.add(progress)
        db.session.commit()

    if request.method == 'POST':
        answers = {}
        for key in request.form:
            if key.startswith('answer_'):
                question_idx = key.replace('answer_', '')
                try:
                    idx = int(question_idx)
                    answers[idx] = request.form[key]
                except ValueError:
                    logger.error(f"Invalid question index: {question_idx}")

        if 'client_results' in request.form:
            try:
                client_results = json.loads(request.form['client_results'])
                client_score = float(request.form['client_score'])
                client_correct_count = int(request.form.get('client_correct_count') or request.form.get('client_correct_answers') or 0)

                feedback = _build_quiz_feedback(client_results, cleaned_content['questions'])

                result = {
                    'score': client_score,
                    'correct_answers': client_correct_count,
                    'total_questions': len(cleaned_content['questions']),
                    'feedback': feedback,
                    'answers': answers
                }
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                logger.error(f"Invalid client results data: {e}")
                result = process_quiz_submission(cleaned_content['questions'], answers)
        else:
            result = process_quiz_submission(cleaned_content['questions'], answers)

            if 'client_score' in request.form:
                try:
                    client_score = float(request.form['client_score'])
                    client_correct_count = int(request.form.get('client_correct_count') or request.form.get('client_correct_answers') or 0)
                    result['score'] = client_score
                    result['correct_answers'] = client_correct_count
                except (ValueError, TypeError) as e:
                    logger.error(f"Invalid client score data: {e}")

        try:
            log_quiz_errors_from_result(
                current_user.id,
                lesson.id,
                cleaned_content['questions'],
                result,
                db,
            )
        except Exception as log_error:
            logger.warning(f"Failed to log quiz errors for lesson {lesson.id}: {log_error}")

        progress, completion_result = ProgressService.update_progress_with_grading(
            user_id=current_user.id,
            lesson=lesson,
            result=result,
            passing_score=70
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            response_data = {
                'success': True,
                'score': result.get('score', 0),
                'feedback': result.get('feedback', {}),
                'correct_answers': result.get('correct_answers', 0),
                'total_questions': result.get('total_questions', 0)
            }
            if completion_result:
                response_data['grade'] = completion_result['grade']
                response_data['grade_name'] = completion_result['grade_name']
                response_data['new_achievements'] = completion_result['new_achievements']
            return jsonify(response_data)

    next_lesson = get_next_lesson(lesson.id)

    return render_template(
        'curriculum/lessons/quiz.html',
        lesson=lesson,
        questions=cleaned_content['questions'],
        settings=cleaned_content,
        progress=progress,
        next_lesson=next_lesson
    )


@lessons_bp.route('/lesson/<int:lesson_id>/final_test', methods=['GET', 'POST'])
@login_required
@require_lesson_access
def final_test_lesson(lesson_id):
    """Display final test lesson with specialized handling"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type != 'final_test':
        abort(400, "This is not a final test lesson")

    try:
        is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
            'final_test', lesson.content
        )
    except ValidationError as e:
        error_msg = str(e.messages)
        logger.error(f"Invalid final test content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом финального теста', 'error')
        return redirect('/learn/')

    if not is_valid:
        logger.error(f"Invalid final test content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом финального теста', 'error')
        return redirect('/learn/')

    questions_to_sanitize = []
    sections_list = cleaned_content.get('test_sections') or cleaned_content.get('sections') or []
    if sections_list:
        for section in sections_list:
            questions_to_sanitize.extend(section.get('exercises') or section.get('questions') or [])
    else:
        questions_field = 'exercises' if 'exercises' in cleaned_content else 'questions'
        questions_to_sanitize = cleaned_content.get(questions_field, [])

    for question in questions_to_sanitize:
        if 'question' in question:
            question['question'] = sanitize_html(question['question'])
        elif 'prompt' in question:
            question['question'] = sanitize_html(question['prompt'])

        if 'options' in question:
            question['options'] = [sanitize_html(opt) for opt in question['options']]

        if 'explanation' in question:
            question['explanation'] = sanitize_html(question['explanation'])

        if 'correct_index' in question and 'correct' not in question:
            question['correct'] = question['correct_index']

        if 'answer' in question and 'correct_answer' not in question:
            question['correct_answer'] = question['answer']

    reset_progress = request.args.get('reset') == 'true'

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    if reset_progress and progress:
        progress.status = 'in_progress'
        progress.score = None
        progress.data = None
        progress.completed_at = None
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

    if request.method == 'POST':
        rate_limit = check_final_test_attempts_exhausted(current_user.id, lesson.id, db_session=db)
        if rate_limit is not None:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, **rate_limit}), 429
            flash('Достигнут лимит попыток финального теста. Попробуйте позже.', 'error')
            return redirect(url_for('curriculum_lessons.final_test_lesson', lesson_id=lesson.id))

        answers = {}
        for key in request.form:
            if key.startswith('answer_'):
                question_idx = key.replace('answer_', '')
                try:
                    idx = int(question_idx)
                    answers[idx] = request.form[key]
                except ValueError:
                    logger.error(f"Invalid question index: {question_idx}")

        all_questions = []
        if 'test_sections' in cleaned_content:
            for section in cleaned_content['test_sections']:
                all_questions.extend(section.get('exercises', []))
        else:
            questions_field = 'exercises' if 'exercises' in cleaned_content else 'questions'
            all_questions = cleaned_content.get(questions_field, [])

        result = process_quiz_submission(all_questions, answers)

        passing_score = cleaned_content.get('passing_score_percent', cleaned_content.get('passing_score', 70))

        try:
            log_quiz_errors_from_result(
                current_user.id,
                lesson.id,
                all_questions,
                result,
                db,
            )
        except Exception as log_error:
            logger.warning(f"Failed to log quiz errors for lesson {lesson.id}: {log_error}")

        progress, completion_result = ProgressService.update_progress_with_grading(
            user_id=current_user.id,
            lesson=lesson,
            result=result,
            passing_score=passing_score
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            response_data = {
                'success': True,
                'score': result.get('score', 0),
                'feedback': result.get('feedback', {}),
                'correct_count': result.get('correct_count', 0),
                'total_count': result.get('total_count', 0),
                'passing_score': passing_score,
                'passed': result.get('score', 0) >= passing_score
            }
            if completion_result:
                response_data['grade'] = completion_result['grade']
                response_data['grade_name'] = completion_result['grade_name']
                response_data['new_achievements'] = completion_result['new_achievements']
            return jsonify(response_data)
        else:
            return redirect(url_for('curriculum_lessons.final_test_results', lesson_id=lesson.id))

    next_lesson = get_next_lesson(lesson.id)

    if 'test_sections' in cleaned_content:
        questions = []
        for section in cleaned_content.get('test_sections', []):
            questions.extend(section.get('exercises', []))
    else:
        questions = cleaned_content.get('exercises', cleaned_content.get('questions', []))

    return render_template(
        'curriculum/lessons/final_test.html',
        lesson=lesson,
        questions=questions,
        exercises=questions,
        settings=cleaned_content,
        progress=progress,
        next_lesson=next_lesson,
        passing_score=cleaned_content.get('passing_score_percent', cleaned_content.get('passing_score', 70))
    )


@lessons_bp.route('/lesson/<int:lesson_id>/final_test/results')
@login_required
@require_lesson_access
def final_test_results(lesson_id):
    """Display final test results"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type != 'final_test':
        abort(400, "This is not a final test lesson")

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    if not progress or not progress.data:
        flash('Результаты теста не найдены', 'error')
        return redirect(url_for('curriculum_lessons.final_test_lesson', lesson_id=lesson.id))

    try:
        is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
            'final_test', lesson.content
        )
    except ValidationError as e:
        flash('Ошибка в содержимом теста', 'error')
        return redirect(url_for('curriculum_lessons.final_test_lesson', lesson_id=lesson.id))

    if not is_valid:
        flash('Ошибка в содержимом теста', 'error')
        return redirect(url_for('curriculum_lessons.final_test_lesson', lesson_id=lesson.id))

    sections_list = cleaned_content.get('test_sections') or cleaned_content.get('sections') or []
    if sections_list:
        questions = []
        for section in sections_list:
            questions.extend(section.get('exercises') or section.get('questions') or [])
    else:
        questions_field = 'exercises' if 'exercises' in cleaned_content else 'questions'
        questions = cleaned_content.get(questions_field, [])

    passing_score = cleaned_content.get('passing_score_percent', cleaned_content.get('passing_score', 70))

    next_lesson = get_next_lesson(lesson.id)

    return render_template(
        'curriculum/lessons/final_test_results.html',
        lesson=lesson,
        questions=questions,
        exercises=questions,
        progress=progress,
        results=progress.data,
        next_lesson=next_lesson,
        passing_score=passing_score,
        passed=progress.score >= passing_score if progress.score else False
    )
