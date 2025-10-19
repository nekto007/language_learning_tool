# app/curriculum/routes/lessons.py

import logging
from datetime import datetime

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

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
                started_at=datetime.utcnow(),
                last_activity=datetime.utcnow()
            )
            db.session.add(progress)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error creating lesson progress: {str(e)}")
            db.session.rollback()
            flash('Ошибка при создании прогресса урока', 'error')
            return redirect(url_for('curriculum.module_lessons', module_id=lesson.module_id))
    else:
        # Update last activity
        progress.last_activity = datetime.utcnow()
        db.session.commit()

    # Route to appropriate handler based on lesson type
    route_map = {
        'vocabulary': 'curriculum_lessons.vocabulary_lesson',
        'grammar': 'curriculum_lessons.grammar_lesson',
        'quiz': 'curriculum_lessons.quiz_lesson',
        'matching': 'curriculum_lessons.matching_lesson',
        'text': 'curriculum_lessons.text_lesson',
        'card': 'curriculum_lessons.card_lesson',
        'final_test': 'curriculum_lessons.final_test_lesson'  # Final test uses its own template
    }

    route_name = route_map.get(lesson.type)
    if route_name:
        return redirect(url_for(route_name, lesson_id=lesson.id))
    else:
        flash(f'Неизвестный тип урока: {lesson.type}', 'error')
        return redirect(url_for('curriculum.module_lessons', module_id=lesson.module_id))


@lessons_bp.route('/lesson/<int:lesson_id>/vocabulary')
@login_required
@require_lesson_access
def vocabulary_lesson(lesson_id):
    """Display vocabulary lesson with sanitized content"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type != 'vocabulary':
        abort(400, "This is not a vocabulary lesson")

    # Get user progress
    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    # Process vocabulary content
    words = []

    # Validate and sanitize content
    is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
        'vocabulary', lesson.content
    )

    if not is_valid:
        logger.error(f"Invalid vocabulary content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect(url_for('curriculum.module_lessons', module_id=lesson.module_id))

    # Process words based on content structure
    if isinstance(cleaned_content, dict):
        word_list = cleaned_content.get('words', cleaned_content.get('items', []))
    else:
        word_list = cleaned_content

    for idx, word_data in enumerate(word_list):
        # Get word from database (приводим к нижнему регистру для поиска)
        english_word = word_data.get('front', word_data.get('word', ''))
        if english_word:
            word = CollectionWords.query.filter_by(
                english_word=english_word.lower()
            ).first()

            if word:
                # Get user's learning status
                user_word = None
                if current_user.is_authenticated:
                    user_word = UserWord.query.filter_by(
                        user_id=current_user.id,
                        word_id=word.id
                    ).first()

                word_dict = {
                    'id': word.id,
                    'english': sanitize_html(word.english_word),
                    'russian': sanitize_html(word.russian_word),
                    'example': sanitize_html(word_data.get('example', '')),
                    'usage': sanitize_html(word_data.get('usage', '')),
                    'hint': sanitize_html(word_data.get('hint', '')),
                    'status': user_word.status if user_word else 'new',
                    'audio_url': word.audio_url if hasattr(word, 'audio_url') else None,
                    'get_download': 1 if word.get_download == 1 else 0
                }
                words.append(word_dict)
            else:
                # If word not in database, use lesson data directly
                word_dict = {
                    'id': 10000 + idx,  # Generate a unique id for lesson words
                    'english': sanitize_html(english_word),
                    'russian': sanitize_html(word_data.get('translation', word_data.get('back', ''))),
                    'example': sanitize_html(word_data.get('example', '')),
                    'usage': sanitize_html(word_data.get('usage', '')),
                    'hint': sanitize_html(word_data.get('hint', '')),
                    'status': word_data.get('status', 'new'),
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
    is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
        'grammar', lesson.content
    )

    if not is_valid:
        logger.error(f"Invalid grammar content for lesson {lesson_id}: {error_msg}")
        logger.error(f"Lesson content: {lesson.content}")
        flash(f'Ошибка в содержимом урока: {error_msg}', 'error')
        return redirect(url_for('curriculum.module_lessons', module_id=lesson.module_id))

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
        progress.last_activity = datetime.utcnow()
        db.session.commit()

    # Get next lesson
    next_lesson = get_next_lesson(lesson.id)

    # Prepare template variables for different content formats
    grammar_rule = cleaned_content.get('title') or cleaned_content.get('rule') or lesson.title
    grammar_description = cleaned_content.get('content') or cleaned_content.get('description') or cleaned_content.get(
        'text', '')
    examples = cleaned_content.get('examples', [])
    exercises = cleaned_content.get('exercises', [])

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

        # Update progress
        if progress:
            progress.score = result.get('score', 0)
            progress.status = 'completed' if result.get('score', 0) >= 70 else 'in_progress'
            progress.data = result
            progress.last_activity = datetime.utcnow()
            if progress.status == 'completed' and not progress.completed_at:
                progress.completed_at = datetime.utcnow()
        else:
            progress = LessonProgress(
                user_id=current_user.id,
                lesson_id=lesson.id,
                score=result.get('score', 0),
                status='completed' if result.get('score', 0) >= 70 else 'in_progress',
                data=result,
                started_at=datetime.utcnow(),
                last_activity=datetime.utcnow()
            )
            if progress.status == 'completed':
                progress.completed_at = datetime.utcnow()
            db.session.add(progress)

        db.session.commit()

        # Return JSON response for AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True,
                'score': result.get('score', 0),
                'feedback': result.get('feedback', {}),
                'correct_count': result.get('correct_count', 0),
                'total_count': result.get('total_count', 0)
            })

    return render_template(
        'curriculum/lessons/grammar.html',
        lesson=lesson,
        content=cleaned_content,
        grammar_rule=grammar_rule,
        grammar_description=grammar_description,
        examples=examples,
        exercises=exercises,
        progress=progress,
        next_lesson=next_lesson
    )


@lessons_bp.route('/lesson/<int:lesson_id>/quiz', methods=['GET', 'POST'])
@login_required
@require_lesson_access
def quiz_lesson(lesson_id):
    """Display quiz lesson with sanitized questions"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type != 'quiz':
        abort(400, "This is not a quiz lesson")

    # Validate and sanitize content
    is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
        'quiz', lesson.content
    )

    if not is_valid:
        logger.error(f"Invalid quiz content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect(url_for('curriculum.module_lessons', module_id=lesson.module_id))

    # Sanitize question content
    for question in cleaned_content['questions']:
        # Handle both 'question' and 'prompt' fields
        if 'question' in question:
            question['question'] = sanitize_html(question['question'])
        elif 'prompt' in question:
            # Normalize 'prompt' to 'question' for template compatibility
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
        progress.last_activity = datetime.utcnow()
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

        # Process the submission
        result = process_quiz_submission(cleaned_content['questions'], answers)

        # Update progress
        if progress:
            progress.score = result.get('score', 0)
            progress.status = 'completed' if result.get('score', 0) >= 70 else 'in_progress'
            progress.data = result
            progress.last_activity = datetime.utcnow()
            if progress.status == 'completed' and not progress.completed_at:
                progress.completed_at = datetime.utcnow()
        else:
            progress = LessonProgress(
                user_id=current_user.id,
                lesson_id=lesson.id,
                score=result.get('score', 0),
                status='completed' if result.get('score', 0) >= 70 else 'in_progress',
                data=result,
                started_at=datetime.utcnow(),
                last_activity=datetime.utcnow()
            )
            if progress.status == 'completed':
                progress.completed_at = datetime.utcnow()
            db.session.add(progress)

        db.session.commit()

        # Return JSON response for AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True,
                'score': result.get('score', 0),
                'feedback': result.get('feedback', {}),
                'correct_count': result.get('correct_count', 0),
                'total_count': result.get('total_count', 0)
            })

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

    # Validate and sanitize content using quiz schema (same structure)
    is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
        'quiz', lesson.content
    )

    if not is_valid:
        logger.error(f"Invalid final test content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом финального теста', 'error')
        return redirect(url_for('curriculum.module_lessons', module_id=lesson.module_id))

    # Sanitize question content (same as quiz)
    questions_field = 'exercises' if 'exercises' in cleaned_content else 'questions'
    if questions_field in cleaned_content:
        for question in cleaned_content[questions_field]:
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
        progress.last_activity = datetime.utcnow()
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

        # Process the submission using quiz processing
        result = process_quiz_submission(cleaned_content[questions_field], answers)

        # Get passing score from content or use default
        passing_score = cleaned_content.get('passing_score_percent', cleaned_content.get('passing_score', 70))

        # Update progress
        if progress:
            progress.score = result.get('score', 0)
            progress.status = 'completed' if result.get('score', 0) >= passing_score else 'in_progress'
            progress.data = result
            progress.last_activity = datetime.utcnow()
            if progress.status == 'completed' and not progress.completed_at:
                progress.completed_at = datetime.utcnow()
        else:
            progress = LessonProgress(
                user_id=current_user.id,
                lesson_id=lesson.id,
                score=result.get('score', 0),
                status='completed' if result.get('score', 0) >= passing_score else 'in_progress',
                data=result,
                started_at=datetime.utcnow(),
                last_activity=datetime.utcnow()
            )
            if progress.status == 'completed':
                progress.completed_at = datetime.utcnow()
            db.session.add(progress)

        db.session.commit()

        # For final tests, redirect to results page
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True,
                'score': result.get('score', 0),
                'feedback': result.get('feedback', {}),
                'correct_count': result.get('correct_count', 0),
                'total_count': result.get('total_count', 0),
                'passing_score': passing_score,
                'passed': result.get('score', 0) >= passing_score
            })
        else:
            # Redirect to results page for final tests
            return redirect(url_for('curriculum_lessons.final_test_results', lesson_id=lesson.id))

    # Get next lesson
    next_lesson = get_next_lesson(lesson.id)

    # Extract questions from exercises or questions field
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
    is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
        'quiz', lesson.content
    )

    if not is_valid:
        flash('Ошибка в содержимом теста', 'error')
        return redirect(url_for('curriculum_lessons.final_test_lesson', lesson_id=lesson.id))

    # Extract questions
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
    is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
        'matching', lesson.content
    )

    if not is_valid:
        logger.error(f"Invalid matching content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect(url_for('curriculum.module_lessons', module_id=lesson.module_id))

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

    if lesson.type != 'text':
        abort(400, "This is not a text lesson")

    # Validate and sanitize content
    is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
        'text', lesson.content
    )

    if not is_valid:
        logger.error(f"Invalid text content for lesson {lesson_id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect(url_for('curriculum.module_lessons', module_id=lesson.module_id))

    # Sanitize text content
    text_content = cleaned_content.get('content', cleaned_content.get('text', ''))
    cleaned_content['content'] = sanitize_html(text_content)
    # Ensure text field is also available for template compatibility
    if 'text' not in cleaned_content and text_content:
        cleaned_content['text'] = cleaned_content['content']

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
        # Update progress to completed
        if not progress:
            progress = LessonProgress(
                user_id=current_user.id,
                lesson_id=lesson.id,
                status='completed',
                score=100.0,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                last_activity=datetime.utcnow()
            )
            db.session.add(progress)
        else:
            progress.status = 'completed'
            progress.score = 100.0
            progress.completed_at = datetime.utcnow()
            progress.last_activity = datetime.utcnow()

        db.session.commit()

        # Return JSON response for AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True,
                'status': 'completed',
                'score': 100.0
            })

        # Regular form submission - redirect to avoid resubmission
        flash('Урок отмечен как прочитанный!', 'success')
        return redirect(url_for('curriculum_lessons.text_lesson', lesson_id=lesson.id))

    # Get book if linked
    book = None
    if lesson.book_id:
        from app.books.models import Book
        book = Book.query.get(lesson.book_id)

    return render_template(
        'curriculum/lessons/text.html',
        lesson=lesson,
        text_content=cleaned_content,
        book=book,
        progress=progress,
        next_lesson=next_lesson
    )


@lessons_bp.route('/lesson/<int:lesson_id>/card')
@login_required
@require_lesson_access
def card_lesson(lesson_id):
    """Display SRS card lesson"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type != 'card':
        abort(400, "This is not a card lesson")

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
        progress.data = {
            'studied_cards': {},  # {card_direction_id: {status, rating, timestamp, was_new}}
            'cards_studied': 0,
            'correct_answers': 0,
            'total_answers': 0,
            'card_progress': {}
        }
        progress.completed_at = None
        progress.last_activity = datetime.utcnow()
        db.session.commit()

    # Get SRS settings
    srs_settings = lesson.get_srs_settings()

    # Get cards for review
    cards_data = get_cards_for_lesson(lesson.id, current_user.id)

    # Check if lesson should be marked as completed
    if cards_data['total_due'] == 0 and progress and progress.status != 'completed':
        progress.status = 'completed'
        progress.completed_at = datetime.utcnow()
        db.session.commit()

    # Get next lesson
    next_lesson = get_next_lesson(lesson.id)

    return render_template(
        'curriculum/lessons/card.html',
        lesson=lesson,
        progress=progress,
        cards_data=cards_data,
        srs_settings=srs_settings,
        next_lesson=next_lesson
    )


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
            progress.score = cleaned_data['score']

        if 'data' in cleaned_data:
            # Sanitize any string values in data
            progress.data = sanitize_json_content(cleaned_data['data'])

        # Store reading_time in progress data if provided
        if 'reading_time' in cleaned_data:
            if not progress.data:
                progress.data = {}
            progress.data['reading_time'] = cleaned_data['reading_time']

        progress.last_activity = datetime.utcnow()

        if progress.status == 'completed' and not progress.completed_at:
            progress.completed_at = datetime.utcnow()

        db.session.commit()

        return jsonify({
            'success': True,
            'progress': {
                'status': progress.status,
                'score': progress.score,
                'completed_at': progress.completed_at.isoformat() if progress.completed_at else None
            }
        })

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
        lesson = Lessons.query.get_or_404(lesson_id)

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


# =============================================================================
# КРАСИВЫЕ URL ДЛЯ УРОКОВ
# =============================================================================

# Импортируем функции для работы с красивыми URL
from app.curriculum.url_helpers import (
    slug_to_level, slug_to_module_number, slug_to_lesson_info,
    get_lesson_by_beautiful_url, generate_breadcrumbs
)

# Создаем новый blueprint для красивых URL уроков  
learn_lessons_bp = Blueprint('learn_lessons', __name__)


@learn_lessons_bp.route('/<string:level_slug>/<string:module_slug>/<string:lesson_slug>/')
@login_required
def beautiful_lesson_detail(level_slug, module_slug, lesson_slug):
    """Красивый URL для урока - redirects to lesson detail"""
    # Парсим URL
    level_code = slug_to_level(level_slug)
    module_number = slug_to_module_number(module_slug)
    lesson_number, lesson_type = slug_to_lesson_info(lesson_slug)

    if not all([level_code, module_number, lesson_number]):
        abort(404, "Invalid lesson URL")

    # Находим урок
    lesson = get_lesson_by_beautiful_url(level_code, module_number, lesson_number, lesson_type)
    if not lesson:
        abort(404, "Lesson not found")

    # Redirect to the appropriate lesson type route using lesson ID
    route_map = {
        'vocabulary': 'curriculum_lessons.vocabulary_lesson',
        'grammar': 'curriculum_lessons.grammar_lesson',
        'quiz': 'curriculum_lessons.quiz_lesson',
        'matching': 'curriculum_lessons.matching_lesson',
        'text': 'curriculum_lessons.text_lesson',
        'card': 'curriculum_lessons.card_lesson',
        'final_test': 'curriculum_lessons.final_test_lesson'
    }

    route_name = route_map.get(lesson.type)
    if route_name:
        return redirect(url_for(route_name, lesson_id=lesson.id))
    else:
        # По умолчанию показываем как детали урока
        return redirect(url_for('curriculum_lessons.lesson_detail', lesson_id=lesson.id))
