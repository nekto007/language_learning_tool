# app/curriculum/routes/lessons.py

import logging
from datetime import UTC, datetime

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from marshmallow import ValidationError

from app.achievements.services import process_lesson_completion
from app.curriculum.models import LessonProgress, Lessons
from app.curriculum.security import (
    require_lesson_access, sanitize_html, sanitize_json_content,
)
from app.curriculum.service import (
    get_card_session_for_lesson, get_cards_for_lesson, get_next_lesson, process_card_review_for_lesson,
    process_final_test_submission, process_grammar_submission, process_matching_submission, process_quiz_submission,
)
from app.curriculum.validators import (
    LessonContentValidator, ProgressUpdateSchema, SRSReviewSchema,
    validate_request_data,
)
from app.study.models import UserWord
from app.utils.db import db
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)

# Create blueprint for lesson routes
lessons_bp = Blueprint('curriculum_lessons', __name__)


def update_lesson_progress_with_grading(lesson, progress, result, passing_score=70):
    """
    Helper function to update lesson progress and assign grades/achievements

    Args:
        lesson: Lesson object
        progress: LessonProgress object or None
        result: Dict with score and other result data
        passing_score: Minimum score to mark as completed (default 70)

    Returns:
        Tuple of (progress, completion_result)
    """
    from sqlalchemy.orm.attributes import flag_modified

    score = result.get('score', 0)
    # Round score to 2 decimal places
    score = round(score, 2)
    is_completed = score >= passing_score

    if progress:
        progress.score = score
        progress.status = 'completed' if is_completed else 'in_progress'
        progress.data = result
        # IMPORTANT: Mark JSONB field as modified for SQLAlchemy to detect changes
        flag_modified(progress, 'data')
        progress.last_activity = datetime.now(UTC)
        if progress.status == 'completed' and not progress.completed_at:
            progress.completed_at = datetime.now(UTC)
    else:
        progress = LessonProgress(
            user_id=current_user.id,
            lesson_id=lesson.id,
            score=score,
            status='completed' if is_completed else 'in_progress',
            data=result,
            started_at=datetime.now(UTC),
            last_activity=datetime.now(UTC)
        )
        if progress.status == 'completed':
            progress.completed_at = datetime.now(UTC)
        db.session.add(progress)

    db.session.commit()

    # Process grading and achievements if lesson completed
    completion_result = None
    if is_completed:
        try:
            completion_result = process_lesson_completion(
                user_id=current_user.id,
                lesson_id=lesson.id,
                score=score
            )
        except Exception as e:
            logger.error(f"Error processing lesson completion: {e}")
            # Don't fail the request if grading fails

    return progress, completion_result


@lessons_bp.route('/lesson/<int:lesson_id>')
@login_required
@require_lesson_access
def lesson_detail(lesson_id):
    """Display lesson details and route to appropriate lesson type"""
    lesson = Lessons.query.get_or_404(lesson_id)

    # Get or create user progress
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
        # Update last activity
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

    # Route to appropriate handler based on lesson type
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
        # Quiz-based lessons
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


@lessons_bp.route('/lesson/<int:lesson_id>/vocabulary')
@login_required
@require_lesson_access
def vocabulary_lesson(lesson_id):
    """Display vocabulary lesson with sanitized content"""
    lesson = Lessons.query.get_or_404(lesson_id)

    # Accept both vocabulary and flashcards
    if lesson.type not in ['vocabulary', 'flashcards']:
        abort(400, "This is not a vocabulary lesson")

    # Get user progress
    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    # Process vocabulary content
    words = []

    # Validate and sanitize content
    try:
        is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
            'vocabulary', lesson.content
        )
    except ValidationError as e:
        error_msg = str(e.messages)
        logger.error(f"Invalid vocabulary content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    if not is_valid:
        logger.error(f"Invalid vocabulary content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    # Debug: log cleaned content structure
    logger.info(f"Lesson {lesson_id} cleaned_content type: {type(cleaned_content)}")
    if isinstance(cleaned_content, dict):
        logger.info(f"Lesson {lesson_id} cleaned_content keys: {list(cleaned_content.keys())}")

    # Process words based on content structure
    if isinstance(cleaned_content, dict):
        word_list = cleaned_content.get('words', cleaned_content.get('items', cleaned_content.get('cards', cleaned_content.get('vocabulary', []))))
    else:
        word_list = cleaned_content

    logger.info(f"Lesson {lesson_id} word_list length: {len(word_list) if word_list else 0}")

    # Bulk load all words to avoid N+1 queries
    english_words = []
    for word_data in word_list:
        english_word = word_data.get('english', word_data.get('word', word_data.get('front', '')))
        if english_word:
            english_words.append(english_word.lower())

    # Single query for all CollectionWords
    db_words = {}
    if english_words:
        collection_words = CollectionWords.query.filter(
            CollectionWords.english_word.in_(english_words)
        ).all()
        db_words = {w.english_word: w for w in collection_words}

    # Single query for all UserWords
    user_words_dict = {}
    if current_user.is_authenticated and db_words:
        word_ids = [w.id for w in db_words.values()]
        user_words = UserWord.query.filter(
            UserWord.user_id == current_user.id,
            UserWord.word_id.in_(word_ids)
        ).all()
        user_words_dict = {uw.word_id: uw for uw in user_words}

    # Build words list
    for idx, word_data in enumerate(word_list):
        english_word = word_data.get('english', word_data.get('word', word_data.get('front', '')))
        if english_word:
            word = db_words.get(english_word.lower())

            if word:
                # Get user's learning status from pre-loaded dict
                user_word = user_words_dict.get(word.id)

                word_dict = {
                    'id': word.id,
                    'english': sanitize_html(word.english_word),
                    'russian': sanitize_html(word.russian_word),
                    'pronunciation': word_data.get('pronunciation', ''),
                    'example': sanitize_html(word_data.get('example', '')),
                    'usage': sanitize_html(word_data.get('usage', word_data.get('example_translation', ''))),
                    'hint': sanitize_html(word_data.get('hint', '')),
                    'status': user_word.status if user_word else 'new',
                    'audio_url': word.listening if hasattr(word, 'listening') else None,
                    'get_download': 1 if word.get_download == 1 else 0
                }
                words.append(word_dict)
            else:
                # If word not in database, use lesson data directly
                russian_word = word_data.get('russian', word_data.get('translation', word_data.get('back', '')))

                word_dict = {
                    'id': 10000 + idx,  # Generate a unique id for lesson words
                    'english': sanitize_html(english_word),
                    'russian': sanitize_html(russian_word),
                    'pronunciation': word_data.get('pronunciation', ''),
                    'example': sanitize_html(word_data.get('example', '')),
                    'usage': sanitize_html(word_data.get('usage', word_data.get('example_translation', ''))),
                    'hint': sanitize_html(word_data.get('hint', '')),
                    'status': word_data.get('status', 'new'),
                    'audio': word_data.get('audio', ''),
                    'audio_url': None,
                    'get_download': 0
                }
                words.append(word_dict)

    # Get next lesson
    next_lesson = get_next_lesson(lesson.id)

    return render_template(
        'curriculum/lessons/vocabulary.html',
        lesson=lesson,
        words=words,
        progress=progress,
        next_lesson=next_lesson
    )


@lessons_bp.route('/lesson/<int:lesson_id>/grammar', methods=['GET', 'POST'])
@login_required
@require_lesson_access
def grammar_lesson(lesson_id):
    """Display grammar lesson with sanitized content"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type != 'grammar':
        abort(400, "This is not a grammar lesson")

    # Validate and sanitize content
    try:
        is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
            'grammar', lesson.content
        )
    except ValidationError as e:
        error_msg = str(e.messages)
        logger.error(f"Invalid grammar content for lesson {lesson_id}: {error_msg}")
        logger.error(f"Lesson content: {lesson.content}")
        flash(f'Ошибка в содержимом урока: {error_msg}', 'error')
        return redirect('/learn/')

    if not is_valid:
        logger.error(f"Invalid grammar content for lesson {lesson_id}: {error_msg}")
        logger.error(f"Lesson content: {lesson.content}")
        flash(f'Ошибка в содержимом урока: {error_msg}', 'error')
        return redirect('/learn/')

    # Sanitize HTML content in all possible fields
    for field in ['content', 'rule', 'text', 'title', 'description']:
        if field in cleaned_content:
            cleaned_content[field] = sanitize_html(cleaned_content[field])

    if 'examples' in cleaned_content:
        # Handle both list of strings and list of dicts
        if cleaned_content['examples'] and isinstance(cleaned_content['examples'][0], dict):
            # Examples are dictionaries with sentence/translation
            for example in cleaned_content['examples']:
                if 'sentence' in example:
                    example['sentence'] = sanitize_html(example['sentence'])
                if 'translation' in example:
                    example['translation'] = sanitize_html(example['translation'])
        else:
            # Examples are simple strings
            cleaned_content['examples'] = [
                sanitize_html(ex) if isinstance(ex, str) else ex
                for ex in cleaned_content['examples']
            ]

    # Проверяем параметр reset для сброса прогресса
    reset_progress = request.args.get('reset') == 'true'

    # Get user progress
    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    # Сбрасываем прогресс, если запрошен reset
    if reset_progress and progress:
        progress.status = 'in_progress'
        progress.score = None
        progress.data = None
        progress.completed_at = None
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

    # Get next lesson
    next_lesson = get_next_lesson(lesson.id)

    # Prepare template variables for different content formats
    grammar_rule = cleaned_content.get('title') or cleaned_content.get('rule') or lesson.title
    grammar_description = cleaned_content.get('content') or cleaned_content.get('description') or cleaned_content.get(
        'text', '')
    examples = cleaned_content.get('examples', [])
    exercises = cleaned_content.get('exercises', [])
    grammar_explanation = cleaned_content.get('grammar_explanation')

    # Decode HTML entities in grammar_explanation if present
    if grammar_explanation:
        import html

        def decode_html_in_dict(obj):
            """Recursively decode HTML entities in dictionaries, lists, and strings"""
            if isinstance(obj, dict):
                return {k: decode_html_in_dict(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [decode_html_in_dict(item) for item in obj]
            elif isinstance(obj, str):
                return html.unescape(obj)
            else:
                return obj

        grammar_explanation = decode_html_in_dict(grammar_explanation)

    # Debug logging
    logger.info(f"Grammar lesson {lesson_id}: Found {len(exercises)} exercises")

    # Handle POST request (exercise submission)
    if request.method == 'POST':
        try:
            # Get answers from form data
            answers = {}
            for key in request.form:
                if key.startswith('answer_'):
                    exercise_idx = key.replace('answer_', '')
                    answers[exercise_idx] = request.form[key]

            logger.info(f"Grammar submission received with {len(answers)} answers")

            # Process the submission
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

        # Update progress with grading and achievements
        progress, completion_result = update_lesson_progress_with_grading(
            lesson=lesson,
            progress=progress,
            result=result,
            passing_score=70
        )

        # Return JSON response for AJAX request
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

    return render_template(
        'curriculum/lessons/grammar.html',
        lesson=lesson,
        content=cleaned_content,
        grammar_rule=grammar_rule,
        grammar_description=grammar_description,
        examples=examples,
        exercises=exercises,
        grammar_explanation=grammar_explanation,
        progress=progress,
        next_lesson=next_lesson
    )


@lessons_bp.route('/lesson/<int:lesson_id>/quiz', methods=['GET', 'POST'])
@login_required
@require_lesson_access
def quiz_lesson(lesson_id):
    """Display quiz lesson with sanitized questions"""
    lesson = Lessons.query.get_or_404(lesson_id)

    # Accept all quiz-type lessons
    quiz_types = ['quiz', 'ordering_quiz', 'translation_quiz', 'listening_quiz',
                  'dialogue_completion_quiz', 'listening_immersion_quiz']
    if lesson.type not in quiz_types:
        abort(400, "This is not a quiz lesson")

    # Validate and sanitize content
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

    # Sanitize and decode HTML entities in question content
    import html
    import random

    for question in cleaned_content['questions']:
        # Handle both 'question' and 'prompt' fields
        if 'question' in question:
            question['question'] = html.unescape(sanitize_html(question['question']))
        elif 'prompt' in question:
            # Normalize 'prompt' to 'question' for template compatibility
            question['question'] = html.unescape(sanitize_html(question['prompt']))

        # Decode sentence field for fill_blank questions
        if 'sentence' in question:
            question['sentence'] = html.unescape(question['sentence'])

        if 'options' in question:
            # Sanitize and deduplicate options while preserving order
            sanitized_options = [html.unescape(sanitize_html(opt)) for opt in question['options']]
            # Remove duplicates while maintaining order
            seen = set()
            unique_options = []
            for opt in sanitized_options:
                if opt not in seen:
                    seen.add(opt)
                    unique_options.append(opt)
            question['options'] = unique_options

        if 'explanation' in question:
            question['explanation'] = html.unescape(sanitize_html(question['explanation']))

        # Normalize answer fields
        if 'correct_index' in question and 'correct' not in question:
            question['correct'] = question['correct_index']

        if 'answer' in question and 'correct_answer' not in question:
            question['correct_answer'] = question['answer']

        # Normalize and shuffle matching questions
        if question.get('type') == 'matching' and 'pairs' in question:
            # Normalize pairs: convert english/russian to left/right
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

            # Create shuffled_right_items list
            right_items = [pair['right'] for pair in normalized_pairs]
            random.shuffle(right_items)
            question['shuffled_right_items'] = right_items

        # Shuffle words for ordering/reorder questions
        if question.get('type') in ['ordering', 'reorder'] and 'words' in question:
            # Create shuffled copy of words
            shuffled_words = question['words'][:]
            random.shuffle(shuffled_words)
            question['shuffled_words'] = shuffled_words

        # Shuffle options for multiple_choice and fill_blank questions
        if question.get('type') in ['multiple_choice', 'fill_blank', 'fill_in_blank', 'listening_choice', 'dialogue_completion'] and 'options' in question and len(question['options']) > 0:
            # Store the correct answer before shuffling
            correct_answer = question.get('correct') or question.get('correct_answer') or question.get('answer')

            # Find the index of the correct answer in the original options
            original_correct_index = None
            if isinstance(correct_answer, str):
                # Find by matching text
                for i, opt in enumerate(question['options']):
                    if opt.lower().strip() == correct_answer.lower().strip():
                        original_correct_index = i
                        break
            elif isinstance(correct_answer, int):
                original_correct_index = correct_answer

            # Shuffle the options
            shuffled_options = question['options'][:]
            random.shuffle(shuffled_options)

            # Update the correct index to match the new position
            if original_correct_index is not None and original_correct_index < len(question['options']):
                original_correct_text = question['options'][original_correct_index]
                new_correct_index = shuffled_options.index(original_correct_text)
                question['correct_index'] = new_correct_index
                question['correct'] = new_correct_index

            # Update the options to the shuffled version
            question['options'] = shuffled_options

    # Check for reset parameter
    reset_progress = request.args.get('reset') == 'true'

    # Get user progress
    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    # Reset progress if requested
    if reset_progress and progress:
        progress.status = 'in_progress'
        progress.score = None
        progress.data = None
        progress.completed_at = None
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

    # Create progress if it doesn't exist (on first visit)
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

    # Handle POST request (quiz submission)
    if request.method == 'POST':
        # Get answers from form data
        answers = {}
        for key in request.form:
            if key.startswith('answer_'):
                question_idx = key.replace('answer_', '')
                # Convert to integer for process_quiz_submission
                try:
                    idx = int(question_idx)
                    answers[idx] = request.form[key]
                    logger.info(f"Received answer for question {idx}: {request.form[key]}")
                except ValueError:
                    logger.error(f"Invalid question index: {question_idx}")

        logger.info(f"Total answers received: {len(answers)}")

        # Check if client sent detailed results (with retry information)
        if 'client_results' in request.form:
            try:
                import json
                client_results = json.loads(request.form['client_results'])
                client_score = float(request.form['client_score'])
                client_correct_count = int(request.form.get('client_correct_count', 0))

                logger.info(f"Using client-side results with retry data: score={client_score}, correct={client_correct_count}")

                # Build feedback based on final client results (after retry)
                feedback = {}
                for item in client_results:
                    q_idx = item['question_index']
                    is_correct = item['is_correct']
                    attempts = item['attempts']
                    user_answer = item['answer']

                    question = cleaned_content['questions'][q_idx]
                    correct_answer = question.get('correct_answer') or question.get('correct') or question.get('answer')

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

                result = {
                    'score': client_score,
                    'correct_count': client_correct_count,
                    'total_count': len(cleaned_content['questions']),
                    'feedback': feedback,
                    'answers': answers
                }
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                logger.error(f"Invalid client results data: {e}")
                # Fallback to server-side processing
                result = process_quiz_submission(cleaned_content['questions'], answers)
        else:
            # Legacy: Process the submission on server side (no retry information)
            result = process_quiz_submission(cleaned_content['questions'], answers)

            # Override with client-side calculation if provided (handles retry attempts correctly)
            if 'client_score' in request.form:
                try:
                    client_score = float(request.form['client_score'])
                    client_correct_count = int(request.form.get('client_correct_count', 0))
                    logger.info(f"Using client-side calculation: score={client_score}, correct={client_correct_count}")
                    result['score'] = client_score
                    result['correct_answers'] = client_correct_count
                except (ValueError, TypeError) as e:
                    logger.error(f"Invalid client score data: {e}")

        # Update progress with grading and achievements
        progress, completion_result = update_lesson_progress_with_grading(
            lesson=lesson,
            progress=progress,
            result=result,
            passing_score=70  # Passing threshold (70% allows for some mistakes with retry)
        )

        # Return JSON response for AJAX request
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

    # Get next lesson
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

    # Validate and sanitize content using final_test schema
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

    # Sanitize question content (same as quiz)
    # Support test_sections, exercises, or questions
    questions_to_sanitize = []
    if 'test_sections' in cleaned_content:
        for section in cleaned_content['test_sections']:
            questions_to_sanitize.extend(section.get('exercises', []))
    else:
        questions_field = 'exercises' if 'exercises' in cleaned_content else 'questions'
        questions_to_sanitize = cleaned_content.get(questions_field, [])

    for question in questions_to_sanitize:
        # Handle both 'question' and 'prompt' fields
        if 'question' in question:
            question['question'] = sanitize_html(question['question'])
        elif 'prompt' in question:
            question['question'] = sanitize_html(question['prompt'])

        if 'options' in question:
            question['options'] = [sanitize_html(opt) for opt in question['options']]

        if 'explanation' in question:
            question['explanation'] = sanitize_html(question['explanation'])

        # Normalize answer fields
        if 'correct_index' in question and 'correct' not in question:
            question['correct'] = question['correct_index']

        if 'answer' in question and 'correct_answer' not in question:
            question['correct_answer'] = question['answer']

    # Check for reset parameter
    reset_progress = request.args.get('reset') == 'true'

    # Get user progress
    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    # Reset progress if requested
    if reset_progress and progress:
        progress.status = 'in_progress'
        progress.score = None
        progress.data = None
        progress.completed_at = None
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

    # Handle POST request (final test submission)
    if request.method == 'POST':
        # Get answers from form data
        answers = {}
        for key in request.form:
            if key.startswith('answer_'):
                question_idx = key.replace('answer_', '')
                try:
                    idx = int(question_idx)
                    answers[idx] = request.form[key]
                    logger.info(f"Received answer for question {idx}: {request.form[key]}")
                except ValueError:
                    logger.error(f"Invalid question index: {question_idx}")

        logger.info(f"Total answers received: {len(answers)}")

        # Get all questions (handle test_sections)
        all_questions = []
        if 'test_sections' in cleaned_content:
            for section in cleaned_content['test_sections']:
                all_questions.extend(section.get('exercises', []))
        else:
            questions_field = 'exercises' if 'exercises' in cleaned_content else 'questions'
            all_questions = cleaned_content.get(questions_field, [])

        # Process the submission using quiz processing
        result = process_quiz_submission(all_questions, answers)

        # Get passing score from content or use default
        passing_score = cleaned_content.get('passing_score_percent', cleaned_content.get('passing_score', 70))

        # Update progress with grading and achievements
        progress, completion_result = update_lesson_progress_with_grading(
            lesson=lesson,
            progress=progress,
            result=result,
            passing_score=passing_score
        )

        # For final tests, redirect to results page
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
            # Redirect to results page for final tests
            return redirect(url_for('curriculum_lessons.final_test_results', lesson_id=lesson.id))

    # Get next lesson
    next_lesson = get_next_lesson(lesson.id)

    # Extract questions from test_sections, exercises, or questions field
    if 'test_sections' in cleaned_content:
        # Flatten test_sections into a single list of exercises
        questions = []
        for section in cleaned_content.get('test_sections', []):
            questions.extend(section.get('exercises', []))
    else:
        questions = cleaned_content.get('exercises', cleaned_content.get('questions', []))

    return render_template(
        'curriculum/lessons/final_test.html',
        lesson=lesson,
        questions=questions,
        exercises=questions,  # Also pass as exercises for template compatibility
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

    # Get user progress
    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    if not progress or not progress.data:
        flash('Результаты теста не найдены', 'error')
        return redirect(url_for('curriculum_lessons.final_test_lesson', lesson_id=lesson.id))

    # Get lesson content for questions
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

    # Extract questions (handle test_sections)
    if 'test_sections' in cleaned_content:
        questions = []
        for section in cleaned_content['test_sections']:
            questions.extend(section.get('exercises', []))
    else:
        questions_field = 'exercises' if 'exercises' in cleaned_content else 'questions'
        questions = cleaned_content.get(questions_field, [])

    # Get passing score
    passing_score = cleaned_content.get('passing_score_percent', cleaned_content.get('passing_score', 70))

    # Get next lesson
    next_lesson = get_next_lesson(lesson.id)

    return render_template(
        'curriculum/lessons/final_test_results.html',
        lesson=lesson,
        questions=questions,
        exercises=questions,  # Also pass as exercises for template compatibility
        progress=progress,
        results=progress.data,
        next_lesson=next_lesson,
        passing_score=passing_score,
        passed=progress.score >= passing_score if progress.score else False
    )


@lessons_bp.route('/lesson/<int:lesson_id>/matching')
@login_required
@require_lesson_access
def matching_lesson(lesson_id):
    """Display matching lesson with sanitized pairs"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type != 'matching':
        abort(400, "This is not a matching lesson")

    # Validate and sanitize content
    try:
        is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
            'matching', lesson.content
        )
    except ValidationError as e:
        error_msg = str(e.messages)
        logger.error(f"Invalid matching content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    if not is_valid:
        logger.error(f"Invalid matching content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    # Sanitize pair content
    for pair in cleaned_content['pairs']:
        pair['left'] = sanitize_html(pair['left'])
        pair['right'] = sanitize_html(pair['right'])
        if 'hint' in pair:
            pair['hint'] = sanitize_html(pair['hint'])

    # Get user progress
    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    # Get next lesson
    next_lesson = get_next_lesson(lesson.id)

    return render_template(
        'curriculum/lessons/matching.html',
        lesson=lesson,
        pairs=cleaned_content['pairs'],
        settings=cleaned_content,
        progress=progress,
        next_lesson=next_lesson
    )


@lessons_bp.route('/lesson/<int:lesson_id>/text', methods=['GET', 'POST'])
@login_required
@require_lesson_access
def text_lesson(lesson_id):
    """Display text lesson with sanitized content"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type not in ['text', 'reading', 'listening_immersion']:
        abort(400, "This is not a text lesson")

    # Validate and sanitize content
    try:
        is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
            'text', lesson.content
        )
    except ValidationError as e:
        error_msg = str(e.messages)
        logger.error(f"Invalid text content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    if not is_valid:
        logger.error(f"Invalid text content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    # Sanitize text content
    text_content = cleaned_content.get('content', cleaned_content.get('text', ''))

    # Handle reading lessons with 'lines' structure
    if isinstance(text_content, dict) and 'lines' in text_content:
        # Keep the structured format for reading lessons
        cleaned_content['text'] = text_content
        cleaned_content['is_reading_with_lines'] = True
    else:
        # Regular text lesson
        cleaned_content['content'] = sanitize_html(text_content)
        # Ensure text field is also available for template compatibility
        if 'text' not in cleaned_content and text_content:
            cleaned_content['text'] = cleaned_content['content']

    # Mark listening_immersion lessons for special handling
    if lesson.type == 'listening_immersion':
        cleaned_content['is_listening_immersion'] = True
        # Preserve audio, translation and instruction fields for listening immersion
        if 'audio' in cleaned_content:
            cleaned_content['audio'] = cleaned_content['audio']
        if 'translation' in cleaned_content:
            cleaned_content['translation'] = sanitize_html(cleaned_content['translation'])
        if 'instruction' in cleaned_content:
            cleaned_content['instruction'] = sanitize_html(cleaned_content['instruction'])

    # Sanitize additional fields for dialogues
    if 'title' in cleaned_content:
        cleaned_content['title'] = sanitize_html(cleaned_content['title'])

    # Sanitize comprehension questions if present
    if 'comprehension_questions' in cleaned_content:
        for question in cleaned_content['comprehension_questions']:
            if 'question' in question:
                question['question'] = sanitize_html(question['question'])
            if 'correct_answer' in question:
                if isinstance(question['correct_answer'], str):
                    question['correct_answer'] = sanitize_html(question['correct_answer'])
            if 'alternative_answers' in question:
                question['alternative_answers'] = [
                    sanitize_html(ans) if isinstance(ans, str) else ans
                    for ans in question['alternative_answers']
                ]

    # Get user progress
    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    # Get next lesson
    next_lesson = get_next_lesson(lesson.id)

    # Handle POST request (text lesson completion)
    if request.method == 'POST':
        # Get comprehension results from request
        comprehension_data = request.json.get('comprehension_results') if request.is_json else None

        if comprehension_data:
            # Use the calculated score from comprehension questions
            score = comprehension_data.get('score', 100.0)
            result = {
                'score': score,
                'status': 'completed',
                'comprehension': comprehension_data
            }
        else:
            # No comprehension questions - default to 100%
            result = {'score': 100.0, 'status': 'completed'}

        # Update progress with grading and achievements
        progress, completion_result = update_lesson_progress_with_grading(
            lesson=lesson,
            progress=progress,
            result=result,
            passing_score=70
        )

        # Return JSON response for AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            response_data = {
                'success': True,
                'status': 'completed',
                'score': 100.0
            }
            if completion_result:
                response_data['grade'] = completion_result['grade']
                response_data['grade_name'] = completion_result['grade_name']
                response_data['new_achievements'] = completion_result['new_achievements']
            return jsonify(response_data)

        # Regular form submission - redirect to avoid resubmission
        flash('Урок отмечен как прочитанный!', 'success')
        return redirect(url_for('curriculum_lessons.text_lesson', lesson_id=lesson.id))

    # Get book if linked
    book = None
    if lesson.book_id:
        from app.books.models import Book
        book = Book.query.get(lesson.book_id)

    # Get saved comprehension results if they exist
    saved_comprehension = None
    if progress and progress.data:
        saved_comprehension = progress.data.get('comprehension')

    return render_template(
        'curriculum/lessons/text.html',
        lesson=lesson,
        text_content=cleaned_content,
        book=book,
        progress=progress,
        next_lesson=next_lesson,
        saved_comprehension=saved_comprehension
    )


@lessons_bp.route('/lesson/<int:lesson_id>/card')
@login_required
@require_lesson_access
def card_lesson(lesson_id):
    """Display SRS card lesson"""
    from app.words.models import CollectionWordLink, CollectionWords
    from app.curriculum.service import sync_lesson_cards_to_words
    import json

    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type not in ['card', 'flashcards']:
        abort(400, "This is not a card lesson")

    # Sync cards to collection_words (creates word_id if missing)
    success, message, updated, created = sync_lesson_cards_to_words(lesson)
    if success and (created > 0 or updated > 0):
        logger.info(f"Synced lesson {lesson_id} cards: {message}")
        # Always reload lesson after sync to get updated content with word_ids
        db.session.refresh(lesson)

    # Get or create progress
    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    # Get navigation info
    next_lesson = None
    if lesson.number is not None:
        next_lesson = Lessons.query.filter(
            Lessons.module_id == lesson.module_id,
            Lessons.number > lesson.number
        ).order_by(Lessons.number).first()

    # Collect words for this card lesson
    word_ids = []

    # Try collection-based
    if lesson.collection_id:
        word_links = CollectionWordLink.query.filter_by(
            collection_id=lesson.collection_id
        ).all()
        word_ids = [link.word_id for link in word_links]

    # Try JSON content with cards (now all cards should have word_id after sync)
    if lesson.content:
        try:
            content = json.loads(lesson.content) if isinstance(lesson.content, str) else lesson.content
            if isinstance(content, dict) and 'cards' in content:
                for card in content['cards']:
                    if isinstance(card, dict) and 'word_id' in card:
                        word_ids.append(card['word_id'])
        except Exception as e:
            logger.error(f"Error parsing lesson content: {e}")

    # If no words (review lesson), collect from previous lessons
    if not word_ids and lesson.module_id and lesson.number is not None:
        previous_lessons = Lessons.query.filter(
            Lessons.module_id == lesson.module_id,
            Lessons.number < lesson.number,
            Lessons.type.in_(['vocabulary', 'card', 'flashcards'])
        ).all()

        for prev_lesson in previous_lessons:
            if prev_lesson.collection_id:
                word_links = CollectionWordLink.query.filter_by(
                    collection_id=prev_lesson.collection_id
                ).all()
                word_ids.extend([link.word_id for link in word_links])
            elif prev_lesson.content:
                try:
                    prev_content = json.loads(prev_lesson.content) if isinstance(prev_lesson.content, str) else prev_lesson.content
                    if isinstance(prev_content, dict) and 'cards' in prev_content:
                        for card in prev_content['cards']:
                            if isinstance(card, dict) and 'word_id' in card:
                                word_ids.append(card['word_id'])
                except:
                    pass

        word_ids = list(set(word_ids))

    # Load word objects and prepare cards data
    cards_list = []

    # Add cards from word_ids
    if word_ids:
        from app.study.models import UserWord
        word_objects = CollectionWords.query.filter(CollectionWords.id.in_(word_ids)).all()

        # Prepare cards in the format expected by template
        for word in word_objects:
            # Check if user has this word in their study list
            user_word = UserWord.query.filter_by(
                user_id=current_user.id,
                word_id=word.id
            ).first()

            # Parse audio filename from listening field
            audio_file = None
            if word.listening:
                # Format: [sound:pronunciation_en_aunt.mp3]
                import re
                match = re.search(r'\[sound:([^\]]+)\]', word.listening)
                if match:
                    audio_file = match.group(1)
            elif word.get_download == 1:
                # Fallback to generated filename
                audio_file = f"{word.english_word.lower().replace(' ', '_')}.mp3"

            # Parse sentences for examples
            example_en = ''
            example_ru = ''
            if word.sentences:
                try:
                    import json
                    sentences_data = json.loads(word.sentences) if isinstance(word.sentences, str) else word.sentences
                    if isinstance(sentences_data, list) and len(sentences_data) > 0:
                        first_sentence = sentences_data[0]
                        if isinstance(first_sentence, dict):
                            example_en = first_sentence.get('en', '')
                            example_ru = first_sentence.get('ru', '')
                except:
                    pass

            card_data = {
                'id': word.id,
                'word_id': word.id,
                'english': word.english_word,
                'russian': word.russian_word,
                'listening': word.listening if word.listening else '',
                'sentences': word.sentences if word.sentences else '',
                'example': example_en,
                'example_en': example_en,
                'example_ru': example_ru,
                'examples': f"{example_en}|{example_ru}" if example_en and example_ru else '',
                'usage': '',
                'hint': '',
                'is_new': user_word is None,
                'status': user_word.status if user_word else 'new',
                'audio': audio_file,
                'audio_url': f"/static/audio/{audio_file}" if audio_file else None,
                'get_download': 1 if word.get_download == 1 else 0
            }
            cards_list.append(card_data)

    # Calculate next review time if no cards available
    next_review_time = None
    if len(cards_list) == 0:
        if word_ids:
            # Find the earliest next_review time among all words in this lesson
            from datetime import datetime
            from app.study.models import UserWord
            user_words = UserWord.query.filter(
                UserWord.user_id == current_user.id,
                UserWord.word_id.in_(word_ids),
                UserWord.next_review.isnot(None)
            ).order_by(UserWord.next_review.asc()).first()

            if user_words and user_words.next_review:
                # Calculate time difference
                time_diff = user_words.next_review - datetime.now(UTC)
                hours = int(time_diff.total_seconds() / 3600)
                if hours < 1:
                    minutes = int(time_diff.total_seconds() / 60)
                    next_review_time = f"{minutes} мин" if minutes > 0 else "скоро"
                elif hours < 24:
                    next_review_time = f"{hours} ч"
                else:
                    days = int(hours / 24)
                    next_review_time = f"{days} д"

    # Prepare cards_data structure
    cards_data = {
        'cards': cards_list,
        'srs_settings': {
            'new_cards_limit': 20,
            'review_cards_limit': 50,
            'show_hint_time': 5
        },
        'lesson_settings': {},
        'stats': {},
        'next_review_time': next_review_time
    }

    return render_template(
        'curriculum/lessons/card.html',
        lesson=lesson,
        progress=progress,
        cards_data=cards_data,
        next_lesson=next_lesson,
        lesson_id=lesson.id
    )


@lessons_bp.route('/lessons/<int:lesson_id>/complete-srs', methods=['POST'])
@login_required
@require_lesson_access
def complete_srs_session(lesson_id):
    """Complete SRS card session and save progress"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        # Get lesson
        lesson = Lessons.query.get_or_404(lesson_id)

        # Get or create progress
        progress = LessonProgress.query.filter_by(
            user_id=current_user.id,
            lesson_id=lesson.id
        ).first()

        if not progress:
            progress = LessonProgress(
                user_id=current_user.id,
                lesson_id=lesson.id,
                status='in_progress'
            )
            db.session.add(progress)

        # Update progress
        cards_studied = data.get('cards_studied', 0)
        accuracy = data.get('accuracy', 0)

        # Mark as completed if cards were studied
        if cards_studied > 0:
            progress.status = 'completed'
            progress.score = round(accuracy, 2)
            progress.completed_at = datetime.now(UTC)

        db.session.commit()

        return jsonify({
            'success': True,
            'cards_studied': cards_studied,
            'accuracy': accuracy
        })

    except Exception as e:
        logger.error(f"Error completing SRS session: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# API endpoints for lesson interactions
@lessons_bp.route('/api/lesson/<int:lesson_id>/progress', methods=['POST'])
@login_required
@require_lesson_access
def update_lesson_progress(lesson_id):
    """Update lesson progress with validation"""
    try:
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
            # Remove csrf_token from data if present (it's handled by Flask-WTF)
            if 'csrf_token' in data:
                del data['csrf_token']
        else:
            # Convert form data to dict
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

        # Validate request data
        is_valid, error_msg, cleaned_data = validate_request_data(
            ProgressUpdateSchema, data
        )

        if not is_valid:
            return jsonify({'success': False, 'error': error_msg}), 400

        # Get or create progress
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

        # Update progress fields
        if 'status' in cleaned_data:
            progress.status = cleaned_data['status']

        if 'score' in cleaned_data:
            progress.score = round(cleaned_data['score'], 2)

        if 'data' in cleaned_data:
            # Sanitize any string values in data
            progress.data = sanitize_json_content(cleaned_data['data'])

        # Store reading_time in progress data if provided
        if 'reading_time' in cleaned_data:
            if not progress.data:
                progress.data = {}
            progress.data['reading_time'] = cleaned_data['reading_time']

        # Store comprehension_results in progress data if provided
        if 'comprehension_results' in cleaned_data:
            if not progress.data:
                progress.data = {}
            progress.data['comprehension'] = cleaned_data['comprehension_results']
            # Mark as modified for JSONB field
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(progress, 'data')

        progress.last_activity = datetime.now(UTC)

        if progress.status == 'completed' and not progress.completed_at:
            progress.completed_at = datetime.now(UTC)

        db.session.commit()

        # Process grading and achievements if lesson just completed
        completion_result = None
        if progress.status == 'completed' and progress.score is not None:
            try:
                lesson = Lessons.query.get(lesson_id)
                completion_result = process_lesson_completion(
                    user_id=current_user.id,
                    lesson_id=lesson_id,
                    score=progress.score
                )
            except Exception as e:
                logger.error(f"Error processing lesson completion: {e}")
                # Don't fail the request if grading fails

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

        # Process based on lesson type
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


@lessons_bp.route('/api/lesson/<int:lesson_id>/card/review', methods=['POST'])
@login_required
@require_lesson_access
def review_card(lesson_id):
    """Process card review with validation"""
    try:
        data = request.get_json()

        # Validate review data
        is_valid, error_msg, cleaned_data = validate_request_data(
            SRSReviewSchema, data
        )

        if not is_valid:
            return jsonify({'success': False, 'error': error_msg}), 400

        # Process the review
        result = process_card_review_for_lesson(
            lesson_id,
            current_user.id,
            cleaned_data['word_id'],
            cleaned_data['direction'],
            cleaned_data['quality']
        )

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error processing card review: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Server error'}), 500


# Add missing API endpoints for card lessons
@lessons_bp.route('/api/rate-card', methods=['POST'])
@login_required
def rate_card_api():
    """Rate a card for SRS lesson"""
    try:
        data = request.get_json()

        lesson_id = data.get('lesson_id')
        word_id = data.get('word_id')
        direction = data.get('direction')
        rating = data.get('rating')

        logger.info(
            f"Rate card API called with: lesson_id={lesson_id}, word_id={word_id}, direction={direction}, rating={rating}")

        if not all([lesson_id, word_id, direction, rating is not None]):
            logger.error("Missing required fields in rate card request")
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        # Validate lesson access
        lesson = Lessons.query.get(lesson_id)
        if not lesson:
            logger.error(f"Lesson {lesson_id} not found")
            return jsonify({'success': False, 'error': 'Lesson not found'}), 404

        # Process the review
        result = process_card_review_for_lesson(
            lesson_id,
            current_user.id,
            word_id,
            direction,
            rating
        )

        logger.info(f"Rate card result: {result}")
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error rating card: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Server error'}), 500


@lessons_bp.route('/api/lesson/<int:lesson_id>/next-review-time', methods=['GET'])
@login_required
def get_next_review_time(lesson_id):
    """Get next review time for lesson"""
    try:
        # Validate lesson access
        lesson = Lessons.query.get_or_404(lesson_id)

        # Get next review time from card session
        session_data = get_card_session_for_lesson(lesson_id, current_user.id)

        return jsonify({
            'next_review_time': session_data.get('next_review_time', 'Нет запланированных повторений')
        })

    except Exception as e:
        logger.error(f"Error getting next review time: {str(e)}")
        return jsonify({'next_review_time': 'Ошибка получения данных'}), 500
