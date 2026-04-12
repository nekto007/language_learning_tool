# app/curriculum/routes/vocabulary_lessons.py

import logging
from datetime import UTC, datetime

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from marshmallow import ValidationError

from app.curriculum.models import LessonProgress, Lessons
from app.curriculum.routes.lessons import lessons_bp
from app.curriculum.security import require_lesson_access, sanitize_html
from app.curriculum.service import get_next_lesson, process_matching_submission
from app.curriculum.services.progress_service import ProgressService
from app.curriculum.validators import LessonContentValidator
from app.study.models import UserWord
from app.utils.db import db
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)


# =============================================================================
# RENDER FUNCTIONS - called from main.py without redirects
# =============================================================================

def render_vocabulary_lesson(lesson):
    """Рендер vocabulary урока"""
    if lesson.type not in ['vocabulary', 'flashcards']:
        abort(400, "This is not a vocabulary lesson")

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    words = []

    try:
        is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
            'vocabulary', lesson.content
        )
    except ValidationError as e:
        error_msg = str(e.messages)
        logger.error(f"Invalid vocabulary content for lesson {lesson.id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    if not is_valid:
        logger.error(f"Invalid vocabulary content for lesson {lesson.id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    if isinstance(cleaned_content, dict):
        word_list = cleaned_content.get('words', cleaned_content.get('items', cleaned_content.get('cards', cleaned_content.get('vocabulary', []))))
    else:
        word_list = cleaned_content

    english_words = []
    for word_data in word_list:
        english_word = word_data.get('english', word_data.get('word', word_data.get('front', '')))
        if english_word:
            english_words.append(english_word.lower())

    db_words = {}
    if english_words:
        collection_words = CollectionWords.query.filter(
            CollectionWords.english_word.in_(english_words)
        ).all()
        db_words = {w.english_word: w for w in collection_words}

    user_words_dict = {}
    if current_user.is_authenticated and db_words:
        word_ids = [w.id for w in db_words.values()]
        user_words = UserWord.query.filter(
            UserWord.user_id == current_user.id,
            UserWord.word_id.in_(word_ids)
        ).all()
        user_words_dict = {uw.word_id: uw for uw in user_words}

    for idx, word_data in enumerate(word_list):
        english_word = word_data.get('english', word_data.get('word', word_data.get('front', '')))
        if english_word:
            word = db_words.get(english_word.lower())

            if word:
                user_word = user_words_dict.get(word.id)
                audio_url = word.listening if hasattr(word, 'listening') and word.listening else word_data.get('audio', '')
                word_dict = {
                    'id': word.id,
                    'english': sanitize_html(word.english_word),
                    'russian': sanitize_html(word.russian_word),
                    'pronunciation': word_data.get('pronunciation', ''),
                    'example': sanitize_html(word_data.get('example', '')),
                    'usage': sanitize_html(word_data.get('usage', word_data.get('example_translation', ''))),
                    'hint': sanitize_html(word_data.get('hint', '')),
                    'status': user_word.status if user_word else 'new',
                    'audio_url': audio_url or None,
                    'get_download': 1 if word.get_download == 1 else 0
                }
                words.append(word_dict)
            else:
                russian_word = word_data.get('russian', word_data.get('translation', word_data.get('back', '')))
                audio_from_json = word_data.get('audio', '')
                word_dict = {
                    'id': 10000 + idx,
                    'english': sanitize_html(english_word),
                    'russian': sanitize_html(russian_word),
                    'pronunciation': word_data.get('pronunciation', ''),
                    'example': sanitize_html(word_data.get('example', '')),
                    'usage': sanitize_html(word_data.get('usage', word_data.get('example_translation', ''))),
                    'hint': sanitize_html(word_data.get('hint', '')),
                    'status': word_data.get('status', 'new'),
                    'audio_url': audio_from_json or None,
                    'get_download': 0
                }
                words.append(word_dict)

    next_lesson = get_next_lesson(lesson.id)

    return render_template(
        'curriculum/lessons/vocabulary.html',
        lesson=lesson,
        words=words,
        progress=progress,
        next_lesson=next_lesson
    )


def render_matching_lesson(lesson):
    """Рендер matching урока"""
    if lesson.type != 'matching':
        abort(400, "This is not a matching lesson")

    try:
        is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
            'matching', lesson.content
        )
    except ValidationError as e:
        error_msg = str(e.messages)
        logger.error(f"Invalid matching content for lesson {lesson.id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    if not is_valid:
        logger.error(f"Invalid matching content for lesson {lesson.id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    for pair in cleaned_content['pairs']:
        pair['left'] = sanitize_html(pair['left'])
        pair['right'] = sanitize_html(pair['right'])
        if 'hint' in pair:
            pair['hint'] = sanitize_html(pair['hint'])

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    next_lesson = get_next_lesson(lesson.id)

    return render_template(
        'curriculum/lessons/matching.html',
        lesson=lesson,
        pairs=cleaned_content['pairs'],
        settings=cleaned_content,
        progress=progress,
        next_lesson=next_lesson
    )


def render_text_lesson(lesson):
    """Рендер text урока"""
    if lesson.type not in ['text', 'reading', 'listening_immersion']:
        abort(400, "This is not a text lesson")

    try:
        is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
            'text', lesson.content
        )
    except ValidationError as e:
        error_msg = str(e.messages)
        logger.error(f"Invalid text content for lesson {lesson.id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    if not is_valid:
        logger.error(f"Invalid text content for lesson {lesson.id}: {error_msg}")
        flash('Ошибка в содержимом урока', 'error')
        return redirect('/learn/')

    text_content = cleaned_content.get('content', cleaned_content.get('text', ''))

    if isinstance(text_content, dict) and 'lines' in text_content:
        cleaned_content['text'] = text_content
        cleaned_content['is_reading_with_lines'] = True
    else:
        cleaned_content['content'] = sanitize_html(text_content)
        if 'text' not in cleaned_content and text_content:
            cleaned_content['text'] = cleaned_content['content']

    if lesson.type == 'listening_immersion':
        cleaned_content['is_listening_immersion'] = True
        if 'translation' in cleaned_content:
            cleaned_content['translation'] = sanitize_html(cleaned_content['translation'])
        if 'instruction' in cleaned_content:
            cleaned_content['instruction'] = sanitize_html(cleaned_content['instruction'])

    if 'title' in cleaned_content:
        cleaned_content['title'] = sanitize_html(cleaned_content['title'])

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

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    next_lesson = get_next_lesson(lesson.id)

    if request.method == 'POST':
        comprehension_data = request.json.get('comprehension_results') if request.is_json else None

        if comprehension_data:
            score = comprehension_data.get('score', 100.0)
            result = {
                'score': score,
                'status': 'completed',
                'comprehension': comprehension_data
            }
        else:
            result = {'score': 100.0, 'status': 'completed'}

        progress, completion_result = ProgressService.update_progress_with_grading(
            user_id=current_user.id,
            lesson=lesson,
            result=result,
            passing_score=70
        )

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

        flash('Урок отмечен как прочитанный!', 'success')
        return redirect(f'/learn/{lesson.id}/')

    book = None
    if lesson.book_id:
        from app.books.models import Book
        book = Book.query.get(lesson.book_id)

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


# =============================================================================
# ROUTE HANDLERS
# =============================================================================

@lessons_bp.route('/lesson/<int:lesson_id>/vocabulary')
@login_required
@require_lesson_access
def vocabulary_lesson(lesson_id):
    """Display vocabulary lesson with sanitized content"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type not in ['vocabulary', 'flashcards']:
        abort(400, "This is not a vocabulary lesson")

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    words = []

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

    logger.info(f"Lesson {lesson_id} cleaned_content type: {type(cleaned_content)}")
    if isinstance(cleaned_content, dict):
        logger.info(f"Lesson {lesson_id} cleaned_content keys: {list(cleaned_content.keys())}")

    if isinstance(cleaned_content, dict):
        word_list = cleaned_content.get('words', cleaned_content.get('items', cleaned_content.get('cards', cleaned_content.get('vocabulary', []))))
    else:
        word_list = cleaned_content

    logger.info(f"Lesson {lesson_id} word_list length: {len(word_list) if word_list else 0}")

    english_words = []
    for word_data in word_list:
        english_word = word_data.get('english', word_data.get('word', word_data.get('front', '')))
        if english_word:
            english_words.append(english_word.lower())

    db_words = {}
    if english_words:
        collection_words = CollectionWords.query.filter(
            CollectionWords.english_word.in_(english_words)
        ).all()
        db_words = {w.english_word: w for w in collection_words}

    user_words_dict = {}
    if current_user.is_authenticated and db_words:
        word_ids = [w.id for w in db_words.values()]
        user_words = UserWord.query.filter(
            UserWord.user_id == current_user.id,
            UserWord.word_id.in_(word_ids)
        ).all()
        user_words_dict = {uw.word_id: uw for uw in user_words}

    for idx, word_data in enumerate(word_list):
        english_word = word_data.get('english', word_data.get('word', word_data.get('front', '')))
        if english_word:
            word = db_words.get(english_word.lower())

            if word:
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
                russian_word = word_data.get('russian', word_data.get('translation', word_data.get('back', '')))

                word_dict = {
                    'id': 10000 + idx,
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

    next_lesson = get_next_lesson(lesson.id)

    return render_template(
        'curriculum/lessons/vocabulary.html',
        lesson=lesson,
        words=words,
        progress=progress,
        next_lesson=next_lesson
    )


@lessons_bp.route('/lesson/<int:lesson_id>/matching')
@login_required
@require_lesson_access
def matching_lesson(lesson_id):
    """Display matching lesson with sanitized pairs"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type != 'matching':
        abort(400, "This is not a matching lesson")

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

    for pair in cleaned_content['pairs']:
        pair['left'] = sanitize_html(pair['left'])
        pair['right'] = sanitize_html(pair['right'])
        if 'hint' in pair:
            pair['hint'] = sanitize_html(pair['hint'])

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

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

    text_content = cleaned_content.get('content', cleaned_content.get('text', ''))

    if isinstance(text_content, dict) and 'lines' in text_content:
        cleaned_content['text'] = text_content
        cleaned_content['is_reading_with_lines'] = True
    else:
        cleaned_content['content'] = sanitize_html(text_content)
        if 'text' not in cleaned_content and text_content:
            cleaned_content['text'] = cleaned_content['content']

    if lesson.type == 'listening_immersion':
        cleaned_content['is_listening_immersion'] = True
        if 'audio' in cleaned_content:
            cleaned_content['audio'] = cleaned_content['audio']
        if 'translation' in cleaned_content:
            cleaned_content['translation'] = sanitize_html(cleaned_content['translation'])
        if 'instruction' in cleaned_content:
            cleaned_content['instruction'] = sanitize_html(cleaned_content['instruction'])

    if 'title' in cleaned_content:
        cleaned_content['title'] = sanitize_html(cleaned_content['title'])

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

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    next_lesson = get_next_lesson(lesson.id)

    if request.method == 'POST':
        comprehension_data = request.json.get('comprehension_results') if request.is_json else None

        if comprehension_data:
            score = comprehension_data.get('score', 100.0)
            result = {
                'score': score,
                'status': 'completed',
                'comprehension': comprehension_data
            }
        else:
            result = {'score': 100.0, 'status': 'completed'}

        progress, completion_result = ProgressService.update_progress_with_grading(
            user_id=current_user.id,
            lesson=lesson,
            result=result,
            passing_score=70
        )

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

        flash('Урок отмечен как прочитанный!', 'success')
        return redirect(url_for('curriculum_lessons.text_lesson', lesson_id=lesson.id))

    book = None
    if lesson.book_id:
        from app.books.models import Book
        book = Book.query.get(lesson.book_id)

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
