# app/curriculum/routes/book_courses.py

import logging
from datetime import UTC, datetime

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified
from app import csrf

from app.curriculum.book_courses import (BookCourse, BookCourseEnrollment, BookCourseModule, BookModuleProgress, generate_slug)
from app.curriculum.daily_lessons import DailyLesson, SliceVocabulary
from app.curriculum.services.book_srs_integration import BookSRSIntegration
from app.curriculum.services.grammar_focus_generator import GrammarFocusGenerator
from app.curriculum.services.comprehension_generator import ComprehensionMCQGenerator, ClozePracticeGenerator
from app.utils.db import db

logger = logging.getLogger(__name__)

# Словарь переводов типов уроков
LESSON_TYPE_TRANSLATIONS = {
    # v3.0 lesson types
    'vocabulary': 'Словарь',
    'reading': 'Чтение',
    'grammar_focus': 'Грамматика',
    'comprehension_mcq': 'Тест на понимание',
    'cloze_practice': 'Заполнение пропусков',
    'vocabulary_review': 'Повторение слов',
    'summary_writing': 'Пересказ',
    'module_test': 'Тест модуля',
    # v2.0 lesson types (legacy)
    'reading_part1': 'Чтение (часть 1)',
    'reading_part2': 'Чтение (часть 2)',
    'vocabulary_practice': 'Практика словаря',
    'discussion': 'Обсуждение',
    'mixed_practice': 'Смешанная практика',
    # Legacy lesson types
    'reading_passage': 'Чтение',
    'reading_mcq': 'Тест по чтению',
    'match_headings': 'Заголовки',
    'open_cloze': 'Пропуски',
    'word_formation': 'Словообразование',
    'keyword_transform': 'Трансформации',
    'grammar_sheet': 'Грамматика',
    'grammar': 'Грамматика',
    'final_test': 'Финальный тест'
}


def get_lesson_type_display(lesson_type: str) -> str:
    """Получить русское название типа урока"""
    return LESSON_TYPE_TRANSLATIONS.get(lesson_type, lesson_type.replace('_', ' ').title())


def truncate_context(text: str, max_sentences: int = 1) -> str:
    """Обрезать контекст до указанного количества предложений"""
    if not text:
        return ''

    import re
    # Разбиваем по точке с пробелом и заглавной буквой (более надёжно)
    # Ищем: точка + пробел + заглавная буква
    parts = re.split(r'\.\s+(?=[A-Z])', text.strip())

    if len(parts) <= max_sentences:
        return text

    # Возвращаем первые N предложений с точкой
    result = '. '.join(parts[:max_sentences])
    if not result.endswith('.'):
        result += '.'
    return result


# Create blueprint for book course routes
book_courses_bp = Blueprint('book_courses', __name__)


def get_course_by_slug_or_id(course_identifier):
    """Get course by slug or id"""
    # Try to parse as integer (id)
    try:
        course_id = int(course_identifier)
        return BookCourse.query.get_or_404(course_id)
    except (ValueError, TypeError):
        # It's a slug
        return BookCourse.query.filter_by(slug=course_identifier).first_or_404()


@book_courses_bp.route('/book-courses')
@login_required
def list_book_courses():
    """Display all available book courses"""
    try:
        # Get all active book courses
        courses = BookCourse.query.filter_by(is_active=True).order_by(
            BookCourse.is_featured.desc(),
            BookCourse.created_at.desc()
        ).all()

        # Get user's enrollments
        user_enrollments = {}
        if current_user.is_authenticated:
            enrollments = BookCourseEnrollment.query.filter_by(
                user_id=current_user.id
            ).all()
            user_enrollments = {e.course_id: e for e in enrollments}

        # Prepare course data with enrollment status
        course_data = []
        for course in courses:
            enrollment = user_enrollments.get(course.id)
            course_info = {
                'course': course,
                'book': course.book,
                'enrollment': enrollment,
                'is_enrolled': enrollment is not None,
                'progress_percentage': enrollment.progress_percentage if enrollment else 0,
                'current_module': enrollment.current_module if enrollment else None
            }
            course_data.append(course_info)

        return render_template(
            'curriculum/book_courses/list.html',
            courses=course_data,
            total_courses=len(course_data)
        )

    except Exception as e:
        logger.error(f"Error listing book courses: {str(e)}")
        flash('Ошибка при загрузке курсов', 'error')
        return redirect(url_for('curriculum.index'))


@book_courses_bp.route('/book-courses/<int:course_id>')
@login_required
def view_course(course_id):
    """Display course details and modules"""
    try:
        course = BookCourse.query.get_or_404(course_id)

        if not course.is_active:
            flash('Этот курс больше не доступен', 'error')
            return redirect(url_for('book_courses.list_book_courses'))

        # Get user enrollment
        enrollment = BookCourseEnrollment.query.filter_by(
            user_id=current_user.id,
            course_id=course_id
        ).first()

        # Get course modules
        modules = BookCourseModule.query.filter_by(
            course_id=course_id
        ).order_by(BookCourseModule.order_index).all()

        # Get module progress if enrolled
        module_progress = {}
        if enrollment:
            progress_records = BookModuleProgress.query.filter_by(
                enrollment_id=enrollment.id
            ).all()
            module_progress = {p.module_id: p for p in progress_records}

        # Prepare modules with progress and lock status
        module_data = []
        for i, module in enumerate(modules):
            progress = module_progress.get(module.id)

            # Check if module is unlocked
            is_unlocked = True
            if module.is_locked and i > 0:
                # Module is unlocked if previous module is completed
                prev_module = modules[i - 1]
                prev_progress = module_progress.get(prev_module.id)
                is_unlocked = prev_progress and prev_progress.status == 'completed'

            module_info = {
                'module': module,
                'progress': progress,
                'is_unlocked': is_unlocked,
                'progress_percentage': progress.progress_percentage if progress else 0,
                'status': progress.status if progress else 'not_started'
            }
            module_data.append(module_info)

        return render_template(
            'curriculum/book_courses/course_detail.html',
            course=course,
            book=course.book,
            enrollment=enrollment,
            modules=module_data,
            total_modules=len(modules),
            is_enrolled=enrollment is not None
        )

    except Exception as e:
        logger.error(f"Error viewing course {course_id}: {str(e)}")
        flash('Ошибка при загрузке курса', 'error')
        return redirect(url_for('book_courses.list_book_courses'))


@book_courses_bp.route('/book-courses/<int:course_id>/enroll', methods=['POST'])
@csrf.exempt
@login_required
def enroll_in_course(course_id):
    """Enroll user in a book course"""
    try:
        logger.info(f"User {current_user.id} attempting to enroll in course {course_id}")

        course = BookCourse.query.get_or_404(course_id)

        if not course.is_active:
            logger.warning(f"Course {course_id} is not active")
            return jsonify({'success': False, 'error': 'Курс недоступен'}), 400

        # Check if already enrolled
        existing_enrollment = BookCourseEnrollment.query.filter_by(
            user_id=current_user.id,
            course_id=course_id
        ).first()

        if existing_enrollment:
            logger.info(f"User {current_user.id} already enrolled in course {course_id}")
            return jsonify({'success': False, 'error': 'Вы уже записаны на этот курс'}), 400

        # Check prerequisites if required
        if course.requires_prerequisites and course.prerequisites:
            pass

        # Create enrollment
        enrollment = BookCourseEnrollment(
            user_id=current_user.id,
            course_id=course_id,
            status='active',
            enrolled_at=datetime.now(UTC)
        )

        # Set current module to first module
        first_module = BookCourseModule.query.filter_by(
            course_id=course_id
        ).order_by(BookCourseModule.order_index).first()

        if first_module:
            enrollment.current_module_id = first_module.id

        db.session.add(enrollment)
        db.session.commit()

        logger.info(
            f"User {current_user.id} successfully enrolled in course {course_id} with enrollment ID {enrollment.id}")

        return jsonify({
            'success': True,
            'message': 'Вы успешно записались на курс!',
            'enrollment_id': enrollment.id
        })

    except Exception as e:
        logger.error(f"Error enrolling in course {course_id}: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Ошибка при записи на курс'}), 500


@book_courses_bp.route('/book-courses/<int:course_id>/modules/<int:module_id>')
@login_required
def view_module(course_id, module_id):
    """Display module details and lessons"""
    try:
        course = BookCourse.query.get_or_404(course_id)
        module = BookCourseModule.query.get_or_404(module_id)

        if module.course_id != course_id:
            abort(404)

        # Check enrollment
        enrollment = BookCourseEnrollment.query.filter_by(
            user_id=current_user.id,
            course_id=course_id
        ).first()

        if not enrollment:
            flash('Вы должны записаться на курс, чтобы просматривать модули', 'error')
            return redirect(url_for('book_courses.view_course', course_id=course_id))

        # Check if module is unlocked
        if module.is_locked:
            # Get previous module
            prev_module = BookCourseModule.query.filter(
                BookCourseModule.course_id == course_id,
                BookCourseModule.order_index < module.order_index
            ).order_by(BookCourseModule.order_index.desc()).first()

            if prev_module:
                prev_progress = BookModuleProgress.query.filter_by(
                    enrollment_id=enrollment.id,
                    module_id=prev_module.id
                ).first()

                if not prev_progress or prev_progress.status != 'completed':
                    flash('Вы должны завершить предыдущий модуль', 'error')
                    return redirect(url_for('book_courses.view_course', course_id=course_id))

        # Get or create module progress
        module_progress = BookModuleProgress.query.filter_by(
            enrollment_id=enrollment.id,
            module_id=module_id
        ).first()

        if not module_progress:
            module_progress = BookModuleProgress(
                enrollment_id=enrollment.id,
                module_id=module_id,
                status='not_started',
                started_at=datetime.now(UTC)
            )
            db.session.add(module_progress)
            db.session.commit()

        # Get lessons from DailyLesson table (new architecture)
        daily_lessons = DailyLesson.query.filter_by(
            book_course_module_id=module.id
        ).order_by(DailyLesson.day_number, DailyLesson.id).all()

        # Convert to template format
        lessons = []
        for dl in daily_lessons:
            lessons.append({
                'lesson_number': dl.day_number,
                'type': dl.lesson_type,
                'title': f'День {dl.day_number}: {get_lesson_type_display(dl.lesson_type)}',
                'id': dl.id,
                'estimated_time': 15,
                'description': None
            })

        # Get next and previous modules
        next_module = BookCourseModule.query.filter(
            BookCourseModule.course_id == course_id,
            BookCourseModule.order_index > module.order_index
        ).order_by(BookCourseModule.order_index).first()

        prev_module = BookCourseModule.query.filter(
            BookCourseModule.course_id == course_id,
            BookCourseModule.order_index < module.order_index
        ).order_by(BookCourseModule.order_index.desc()).first()

        # Get due cards count for SRS review badge
        srs_integration = BookSRSIntegration()
        due_cards_count = srs_integration.get_due_cards_count(current_user.id)

        return render_template(
            'curriculum/book_courses/module_detail.html',
            course=course,
            module=module,
            enrollment=enrollment,
            module_progress=module_progress,
            lessons=lessons,
            next_module=next_module,
            prev_module=prev_module,
            due_cards_count=due_cards_count
        )

    except Exception as e:
        logger.error(f"Error viewing module {module_id}: {str(e)}")
        flash('Ошибка при загрузке модуля', 'error')
        return redirect(url_for('book_courses.view_course', course_id=course_id))


@book_courses_bp.route('/book-courses/<int:course_id>/modules/<int:module_id>/lessons/<int:lesson_number>')
@login_required
def view_lesson(course_id, module_id, lesson_number):
    """Display specific lesson within a module"""
    try:
        course = BookCourse.query.get_or_404(course_id)
        module = BookCourseModule.query.get_or_404(module_id)

        if module.course_id != course_id:
            abort(404)

        # Check enrollment and module access
        enrollment = BookCourseEnrollment.query.filter_by(
            user_id=current_user.id,
            course_id=course_id
        ).first()

        if not enrollment:
            flash('Доступ запрещен', 'error')
            return redirect(url_for('book_courses.view_course', course_id=course_id))

        # Get Daily Lesson according to new architecture
        from app.curriculum.daily_lessons import DailyLesson

        daily_lesson = DailyLesson.query.filter_by(
            book_course_module_id=module_id,
            day_number=lesson_number
        ).first()

        if not daily_lesson:
            # Fallback to old lessons_data format for backward compatibility
            lessons_data = module.lessons_data or {}
            lessons = lessons_data.get('lessons', [])

            lesson = None
            for l in lessons:
                if l.get('lesson_number') == lesson_number:
                    lesson = l
                    break

            if not lesson:
                abort(404)
        else:
            # Convert DailyLesson to lesson format for templates
            lesson = {
                'lesson_number': daily_lesson.day_number,
                'type': daily_lesson.lesson_type,
                'title': f'День {daily_lesson.day_number}: {get_lesson_type_display(daily_lesson.lesson_type)}',
                'slice_text': daily_lesson.slice_text,
                'word_count': daily_lesson.word_count,
                'task_id': daily_lesson.task_id,
                'daily_lesson_id': daily_lesson.id,
                'available_at': daily_lesson.available_at
            }

        # Get module progress
        module_progress = BookModuleProgress.query.filter_by(
            enrollment_id=enrollment.id,
            module_id=module_id
        ).first()

        if not module_progress:
            flash('Ошибка доступа к модулю', 'error')
            return redirect(url_for('book_courses.view_module',
                                    course_id=course_id, module_id=module_id))

        # Get review cards for SRS section in all lessons
        srs_integration = BookSRSIntegration()
        review_cards = srs_integration.get_due_cards_for_review(current_user.id, limit=5)

        # Get next lesson URL
        next_lesson_url = None
        has_next_lesson = False
        if daily_lesson:
            # Get all lessons in order and find the next one
            all_lessons = DailyLesson.query.filter_by(
                book_course_module_id=module_id
            ).order_by(DailyLesson.day_number, DailyLesson.id).all()

            # Find current lesson position and get next
            for i, dl in enumerate(all_lessons):
                if dl.id == daily_lesson.id and i < len(all_lessons) - 1:
                    next_daily_lesson = all_lessons[i + 1]
                    has_next_lesson = True
                    next_lesson_url = url_for(
                        'book_courses.view_lesson_by_id',
                        course_id=course_id,
                        module_id=module_id,
                        lesson_id=next_daily_lesson.id
                    )
                    break

        # Route to appropriate lesson type handler
        lesson_type = lesson.get('type', 'text')
        logger.info(f"view_lesson: course={course_id}, module={module_id}, lesson_type='{lesson_type}'")

        # Special handling for SRS/Anki sessions
        if lesson_type == 'anki_session' or lesson_type == 'srs':
            return render_template(
                'curriculum/book_courses/lessons/anki_session.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                book=course.book,
                review_cards=review_cards
            )
        elif lesson_type in ['reading', 'reading_assignment', 'reading_passage', 'reading_part1', 'reading_part2']:
            # All reading types use the reading_passage template
            template = 'curriculum/book_courses/lessons/reading_passage.html'

            return render_template(
                template,
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                book=course.book,
                daily_lesson=daily_lesson if 'daily_lesson' in dir() else None,
                use_api=True if daily_lesson else False,
                review_cards=review_cards,
                next_lesson_url=next_lesson_url,
                has_next_lesson=has_next_lesson
            )
        elif lesson_type == 'vocabulary':
            # Load vocabulary from SliceVocabulary according to new architecture
            vocabulary_data = []

            if daily_lesson:
                # Use new DailyLesson vocabulary with proper eager loading
                slice_vocab = SliceVocabulary.query.filter_by(
                    daily_lesson_id=daily_lesson.id
                ).options(joinedload(SliceVocabulary.word)).all()

                for sv in slice_vocab:
                    word = sv.word
                    # Context sentence from book (relevant to current reading) - max 1 sentences
                    context = truncate_context(sv.context_sentence or '', max_sentences=1)

                    # Example with translation from DB
                    db_example = getattr(word, 'sentences', '') or ''
                    db_example = db_example.replace('\\n', '\n').replace('<br>', '\n').replace('<br/>', '\n')

                    vocab_item = {
                        'id': word.id,
                        'lemma': word.english_word,  # As per specification
                        'translation': word.russian_word,
                        'context': context,  # From book
                        'example': db_example,  # From DB with translation
                        'audio_url': f'/static/audio/pronunciation_en_{word.english_word.lower().replace(" ", "_")}.mp3',
                        'has_audio': getattr(word, 'get_download', 0) == 1,
                        'frequency': sv.frequency_in_slice,
                        'part_of_speech': getattr(word, 'pos', 'unknown'),
                        'level': getattr(word, 'level', None),
                        'transcription': getattr(word, 'transcription', None)
                    }
                    vocabulary_data.append(vocab_item)
            else:
                # Fallback to old task-based vocabulary
                task_id = lesson.get('task_id')
                if task_id:
                    from app.books.models import Task
                    task = Task.query.get(task_id)
                    if task and task.payload:
                        cards = task.payload.get('cards', [])
                        for idx, card in enumerate(cards):
                            vocab_item = {
                                'id': idx + 1,
                                'lemma': card.get('front', ''),
                                'translation': card.get('back', {}).get('translation', ''),
                                'example': card.get('back', {}).get('examples', [''])[0] if card.get('back', {}).get(
                                    'examples') else '',
                                'audio_url': card.get('audio_url', ''),
                                'frequency': card.get('back', {}).get('frequency', 0)
                            }
                            vocabulary_data.append(vocab_item)

            # Limit to 10 words as per specification
            vocabulary_data = vocabulary_data[:10]

            # Create deck for this book course (if not exists) and add words
            from app.curriculum.services.book_srs_integration import get_or_create_book_course_deck
            from app.study.models import QuizDeckWord
            try:
                logger.info(f"Creating/getting book deck for user {current_user.id}, course {course.id} (vocabulary in view_lesson)")
                book_deck = get_or_create_book_course_deck(current_user.id, course)

                # Add vocabulary words to deck
                if book_deck and vocabulary_data:
                    words_added = 0
                    for vocab in vocabulary_data:
                        word_id = vocab.get('id')
                        if word_id:
                            existing = QuizDeckWord.query.filter_by(
                                deck_id=book_deck.id, word_id=word_id
                            ).first()
                            if not existing:
                                deck_word = QuizDeckWord(deck_id=book_deck.id, word_id=word_id)
                                db.session.add(deck_word)
                                words_added += 1
                    if words_added > 0:
                        logger.info(f"Added {words_added} words to deck {book_deck.id}")

                db.session.commit()
                logger.info(f"Book deck created/retrieved: {book_deck.id if book_deck else 'None'}, title={book_deck.title if book_deck else 'None'}")
            except Exception as e:
                logger.error(f"Error creating book deck: {str(e)}", exc_info=True)
                db.session.rollback()
                book_deck = None

            return render_template(
                'curriculum/book_courses/lessons/vocabulary.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                vocabulary_data=vocabulary_data,
                total_words=len(vocabulary_data),
                daily_lesson=daily_lesson,
                review_cards=review_cards,
                book_deck=book_deck
            )
        elif lesson_type in ['grammar', 'grammar_focus']:
            # Get grammar content from GrammarFocusGenerator
            course_level = course.level or 'B1'
            day_number = daily_lesson.day_number if daily_lesson else lesson_number
            grammar_data = GrammarFocusGenerator.get_grammar_for_day(course_level, day_number)

            return render_template(
                'curriculum/book_courses/lessons/grammar.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards,
                grammar_data=grammar_data,
                daily_lesson=daily_lesson,
                next_lesson_url=next_lesson_url,
                has_next_lesson=has_next_lesson
            )
        elif lesson_type in ['vocabulary_review']:
            # Vocabulary review - similar to vocabulary but for review
            vocabulary_data = []

            if daily_lesson:
                slice_vocab = SliceVocabulary.query.filter_by(
                    daily_lesson_id=daily_lesson.id
                ).options(joinedload(SliceVocabulary.word)).all()

                for sv in slice_vocab:
                    word = sv.word
                    vocab_item = {
                        'id': word.id,
                        'lemma': word.english_word,
                        'translation': word.russian_word,
                        'example': truncate_context(sv.context_sentence or '', max_sentences=1),
                        'audio_url': f'/static/audio/pronunciation_en_{word.english_word.lower().replace(" ", "_")}.mp3',
                        'frequency': sv.frequency_in_slice,
                    }
                    vocabulary_data.append(vocab_item)

            # Create deck for this book course (if not exists) and add words
            from app.curriculum.services.book_srs_integration import get_or_create_book_course_deck
            from app.study.models import QuizDeckWord
            try:
                logger.info(f"Creating/getting book deck for user {current_user.id}, course {course.id} (vocabulary_review in view_lesson)")
                book_deck = get_or_create_book_course_deck(current_user.id, course)

                # Add vocabulary words to deck
                vocab_to_add = vocabulary_data[:15]
                if book_deck and vocab_to_add:
                    words_added = 0
                    for vocab in vocab_to_add:
                        word_id = vocab.get('id')
                        if word_id:
                            existing = QuizDeckWord.query.filter_by(
                                deck_id=book_deck.id, word_id=word_id
                            ).first()
                            if not existing:
                                deck_word = QuizDeckWord(deck_id=book_deck.id, word_id=word_id)
                                db.session.add(deck_word)
                                words_added += 1
                    if words_added > 0:
                        logger.info(f"Added {words_added} words to deck {book_deck.id} (vocabulary_review)")

                db.session.commit()
                logger.info(f"Book deck created/retrieved: {book_deck.id if book_deck else 'None'}")
            except Exception as e:
                logger.error(f"Error creating book deck: {str(e)}", exc_info=True)
                db.session.rollback()
                book_deck = None

            return render_template(
                'curriculum/book_courses/lessons/vocabulary.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                vocabulary_data=vocabulary_data[:15],
                total_words=len(vocabulary_data[:15]),
                daily_lesson=daily_lesson,
                review_cards=review_cards,
                is_review=True,  # Flag to show review mode
                book_deck=book_deck
            )
        elif lesson_type in ['comprehension_mcq']:
            # Comprehension MCQ - use reading_mcq template
            mcq_data = None
            if daily_lesson and daily_lesson.task_id:
                from app.books.models import Task
                task = Task.query.get(daily_lesson.task_id)
                if task and task.payload:
                    mcq_data = task.payload

            # Generate MCQ from slice text if no task data
            if not mcq_data and daily_lesson and daily_lesson.slice_text:
                mcq_data = ComprehensionMCQGenerator.generate_questions(
                    daily_lesson.slice_text, num_questions=10
                )

            return render_template(
                'curriculum/book_courses/lessons/reading_mcq.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards,
                daily_lesson=daily_lesson if 'daily_lesson' in dir() else None,
                mcq_data=mcq_data
            )
        elif lesson_type in ['cloze_practice']:
            # Cloze practice - use open_cloze template
            cloze_data = None
            if daily_lesson and daily_lesson.task_id:
                from app.books.models import Task
                task = Task.query.get(daily_lesson.task_id)
                if task and task.payload:
                    cloze_data = task.payload

            # Generate cloze from slice text if no task data
            if not cloze_data and daily_lesson and daily_lesson.slice_text:
                cloze_data = ClozePracticeGenerator.generate_cloze(
                    daily_lesson.slice_text, num_gaps=8
                )

            return render_template(
                'curriculum/book_courses/lessons/open_cloze.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards,
                daily_lesson=daily_lesson if 'daily_lesson' in dir() else None,
                cloze_data=cloze_data
            )
        elif lesson_type in ['reading_mcq', 'match_headings', 'open_cloze', 'word_formation', 'keyword_transform', 'vocabulary_practice']:
            # Vocabulary practice uses word_formation template as fallback
            template_name = 'word_formation' if lesson_type == 'vocabulary_practice' else lesson_type
            return render_template(
                f'curriculum/book_courses/lessons/{template_name}.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards
            )
        elif lesson_type == 'summary_writing':
            # Summary writing - productive task
            return render_template(
                'curriculum/book_courses/lessons/summary.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards,
                daily_lesson=daily_lesson if 'daily_lesson' in dir() else None
            )
        elif lesson_type == 'discussion':
            # Discussion questions - productive task
            return render_template(
                'curriculum/book_courses/lessons/discussion.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards,
                daily_lesson=daily_lesson if 'daily_lesson' in dir() else None
            )
        elif lesson_type in ['module_test', 'final_test']:
            # Load test data from task
            test_data = None
            if daily_lesson and daily_lesson.task_id:
                from app.books.models import Task
                task = Task.query.get(daily_lesson.task_id)
                if task and task.payload:
                    test_data = task.payload

            return render_template(
                'curriculum/book_courses/lessons/final_test.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards,
                daily_lesson=daily_lesson,
                test_data=test_data,
                next_lesson_url=next_lesson_url,
                has_next_lesson=has_next_lesson
            )
        elif lesson_type == 'mixed_practice':
            # Mixed practice uses text template
            return render_template(
                'curriculum/book_courses/lessons/text.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards
            )
        else:
            # Default text lesson for other types
            return render_template(
                'curriculum/book_courses/lessons/text.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards
            )

    except Exception as e:
        logger.error(f"Error viewing lesson {lesson_number}: {str(e)}")
        flash('Ошибка при загрузке урока', 'error')
        return redirect(url_for('book_courses.view_module',
                                course_id=course_id, module_id=module_id))


@book_courses_bp.route('/book-courses/<int:course_id>/modules/<int:module_id>/lesson/<int:lesson_id>')
@login_required
def view_lesson_by_id(course_id, module_id, lesson_id):
    """Display specific lesson by ID within a module"""
    try:
        course = BookCourse.query.get_or_404(course_id)
        module = BookCourseModule.query.get_or_404(module_id)

        if module.course_id != course_id:
            abort(404)

        # Check enrollment and module access
        enrollment = BookCourseEnrollment.query.filter_by(
            user_id=current_user.id,
            course_id=course_id
        ).first()

        if not enrollment:
            flash('Доступ запрещен', 'error')
            return redirect(url_for('book_courses.view_course', course_id=course_id))

        # Get Daily Lesson by ID
        daily_lesson = DailyLesson.query.get_or_404(lesson_id)

        if daily_lesson.book_course_module_id != module_id:
            abort(404)

        # Convert DailyLesson to lesson format for templates
        lesson = {
            'lesson_number': daily_lesson.day_number,
            'type': daily_lesson.lesson_type,
            'title': f'День {daily_lesson.day_number}: {get_lesson_type_display(daily_lesson.lesson_type)}',
            'slice_text': daily_lesson.slice_text,
            'word_count': daily_lesson.word_count,
            'task_id': daily_lesson.task_id,
            'daily_lesson_id': daily_lesson.id,
            'available_at': daily_lesson.available_at
        }

        # Get module progress
        module_progress = BookModuleProgress.query.filter_by(
            enrollment_id=enrollment.id,
            module_id=module_id
        ).first()

        if not module_progress:
            flash('Ошибка доступа к модулю', 'error')
            return redirect(url_for('book_courses.view_module',
                                    course_id=course_id, module_id=module_id))

        # Get review cards for SRS section in all lessons
        srs_integration = BookSRSIntegration()
        review_cards = srs_integration.get_due_cards_for_review(current_user.id, limit=5)

        # Get next lesson URL
        next_lesson_url = None
        has_next_lesson = False
        # Get all lessons in order and find the next one
        all_lessons = DailyLesson.query.filter_by(
            book_course_module_id=module_id
        ).order_by(DailyLesson.day_number, DailyLesson.id).all()

        # Find current lesson position and get next
        for i, dl in enumerate(all_lessons):
            if dl.id == daily_lesson.id and i < len(all_lessons) - 1:
                next_daily_lesson = all_lessons[i + 1]
                has_next_lesson = True
                next_lesson_url = url_for(
                    'book_courses.view_lesson_by_id',
                    course_id=course_id,
                    module_id=module_id,
                    lesson_id=next_daily_lesson.id
                )
                break

        # Route to appropriate lesson type handler
        lesson_type = lesson.get('type', 'text')
        lesson_number = daily_lesson.day_number

        # Special handling for SRS/Anki sessions
        if lesson_type == 'anki_session' or lesson_type == 'srs':
            return render_template(
                'curriculum/book_courses/lessons/anki_session.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                book=course.book,
                review_cards=review_cards
            )
        elif lesson_type in ['reading', 'reading_assignment', 'reading_passage', 'reading_part1', 'reading_part2']:
            # All reading types use the reading_passage template
            template = 'curriculum/book_courses/lessons/reading_passage.html'

            return render_template(
                template,
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                book=course.book,
                daily_lesson=daily_lesson,
                use_api=True,
                review_cards=review_cards,
                next_lesson_url=next_lesson_url,
                has_next_lesson=has_next_lesson
            )
        elif lesson_type == 'vocabulary':
            # Load vocabulary from SliceVocabulary
            vocabulary_data = []

            slice_vocab = SliceVocabulary.query.filter_by(
                daily_lesson_id=daily_lesson.id
            ).options(joinedload(SliceVocabulary.word)).all()

            for sv in slice_vocab:
                word = sv.word
                # Context sentence from book (relevant to current reading) - max 1 sentences
                context = truncate_context(sv.context_sentence or '', max_sentences=1)

                # Example with translation from DB
                db_example = getattr(word, 'sentences', '') or ''
                db_example = db_example.replace('\\n', '\n').replace('<br>', '\n').replace('<br/>', '\n')

                vocab_item = {
                    'id': word.id,
                    'lemma': word.english_word,
                    'translation': word.russian_word,
                    'context': context,  # From book
                    'example': db_example,  # From DB with translation
                    'audio_url': f'/static/audio/pronunciation_en_{word.english_word.lower().replace(" ", "_")}.mp3',
                    'frequency': sv.frequency_in_slice,
                    'part_of_speech': getattr(word, 'pos', 'unknown')
                }
                vocabulary_data.append(vocab_item)

            vocabulary_data = vocabulary_data[:10]

            # Create deck for this book course (if not exists) and add words
            from app.curriculum.services.book_srs_integration import get_or_create_book_course_deck
            from app.study.models import QuizDeckWord
            try:
                logger.info(f"Creating/getting book deck for user {current_user.id}, course {course.id}")
                book_deck = get_or_create_book_course_deck(current_user.id, course)

                # Add vocabulary words to deck
                if book_deck and vocabulary_data:
                    words_added = 0
                    for vocab in vocabulary_data:
                        word_id = vocab.get('id')
                        if word_id:
                            existing = QuizDeckWord.query.filter_by(
                                deck_id=book_deck.id, word_id=word_id
                            ).first()
                            if not existing:
                                deck_word = QuizDeckWord(deck_id=book_deck.id, word_id=word_id)
                                db.session.add(deck_word)
                                words_added += 1
                    if words_added > 0:
                        logger.info(f"Added {words_added} words to deck {book_deck.id}")

                db.session.commit()
                logger.info(f"Book deck created/retrieved: {book_deck.id if book_deck else 'None'}")
            except Exception as e:
                logger.error(f"Error creating book deck: {str(e)}", exc_info=True)
                db.session.rollback()
                book_deck = None

            return render_template(
                'curriculum/book_courses/lessons/vocabulary.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                vocabulary_data=vocabulary_data,
                total_words=len(vocabulary_data),
                daily_lesson=daily_lesson,
                review_cards=review_cards,
                book_deck=book_deck
            )
        elif lesson_type in ['grammar', 'grammar_focus']:
            # Get grammar content from GrammarFocusGenerator
            course_level = course.level or 'B1'
            day_number = daily_lesson.day_number if daily_lesson else lesson_number
            grammar_data = GrammarFocusGenerator.get_grammar_for_day(course_level, day_number)

            return render_template(
                'curriculum/book_courses/lessons/grammar.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards,
                grammar_data=grammar_data,
                daily_lesson=daily_lesson,
                next_lesson_url=next_lesson_url,
                has_next_lesson=has_next_lesson
            )
        elif lesson_type in ['vocabulary_review']:
            # Vocabulary review - similar to vocabulary but for review
            vocabulary_data = []
            slice_vocab = SliceVocabulary.query.filter_by(
                daily_lesson_id=daily_lesson.id
            ).options(joinedload(SliceVocabulary.word)).all()

            for sv in slice_vocab:
                word = sv.word
                vocab_item = {
                    'id': word.id,
                    'lemma': word.english_word,
                    'translation': word.russian_word,
                    'example': truncate_context(sv.context_sentence or '', max_sentences=1),
                    'audio_url': f'/static/audio/pronunciation_en_{word.english_word.lower().replace(" ", "_")}.mp3',
                    'frequency': sv.frequency_in_slice,
                }
                vocabulary_data.append(vocab_item)

            # Create deck for this book course (if not exists) and add words
            from app.curriculum.services.book_srs_integration import get_or_create_book_course_deck
            from app.study.models import QuizDeckWord
            try:
                logger.info(f"Creating/getting book deck for user {current_user.id}, course {course.id} (vocabulary_review)")
                book_deck = get_or_create_book_course_deck(current_user.id, course)

                # Add vocabulary words to deck
                vocab_to_add = vocabulary_data[:15]
                if book_deck and vocab_to_add:
                    words_added = 0
                    for vocab in vocab_to_add:
                        word_id = vocab.get('id')
                        if word_id:
                            existing = QuizDeckWord.query.filter_by(
                                deck_id=book_deck.id, word_id=word_id
                            ).first()
                            if not existing:
                                deck_word = QuizDeckWord(deck_id=book_deck.id, word_id=word_id)
                                db.session.add(deck_word)
                                words_added += 1
                    if words_added > 0:
                        logger.info(f"Added {words_added} words to deck {book_deck.id} (vocabulary_review)")

                db.session.commit()
                logger.info(f"Book deck created/retrieved: {book_deck.id if book_deck else 'None'}")
            except Exception as e:
                logger.error(f"Error creating book deck: {str(e)}", exc_info=True)
                db.session.rollback()
                book_deck = None

            return render_template(
                'curriculum/book_courses/lessons/vocabulary.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                vocabulary_data=vocabulary_data[:15],
                total_words=len(vocabulary_data[:15]),
                daily_lesson=daily_lesson,
                review_cards=review_cards,
                is_review=True,
                book_deck=book_deck
            )
        elif lesson_type in ['comprehension_mcq']:
            # Comprehension MCQ - use reading_mcq template
            mcq_data = None
            if daily_lesson and daily_lesson.task_id:
                from app.books.models import Task
                task = Task.query.get(daily_lesson.task_id)
                if task and task.payload:
                    mcq_data = task.payload

            # Generate MCQ from slice text if no task data
            if not mcq_data and daily_lesson and daily_lesson.slice_text:
                mcq_data = ComprehensionMCQGenerator.generate_questions(
                    daily_lesson.slice_text, num_questions=10
                )

            return render_template(
                'curriculum/book_courses/lessons/reading_mcq.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards,
                daily_lesson=daily_lesson,
                mcq_data=mcq_data
            )
        elif lesson_type in ['cloze_practice']:
            # Cloze practice - use open_cloze template
            cloze_data = None
            if daily_lesson and daily_lesson.task_id:
                from app.books.models import Task
                task = Task.query.get(daily_lesson.task_id)
                if task and task.payload:
                    cloze_data = task.payload

            # Generate cloze from slice text if no task data
            if not cloze_data and daily_lesson and daily_lesson.slice_text:
                cloze_data = ClozePracticeGenerator.generate_cloze(
                    daily_lesson.slice_text, num_gaps=8
                )

            return render_template(
                'curriculum/book_courses/lessons/open_cloze.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards,
                daily_lesson=daily_lesson,
                cloze_data=cloze_data
            )
        elif lesson_type == 'summary_writing':
            # Summary writing - productive task
            return render_template(
                'curriculum/book_courses/lessons/summary.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards,
                daily_lesson=daily_lesson
            )
        elif lesson_type in ['reading_mcq', 'match_headings', 'open_cloze', 'word_formation', 'keyword_transform']:
            return render_template(
                f'curriculum/book_courses/lessons/{lesson_type}.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards
            )
        elif lesson_type in ['module_test', 'final_test']:
            # Load test data from task
            test_data = None
            if daily_lesson and daily_lesson.task_id:
                from app.books.models import Task
                task = Task.query.get(daily_lesson.task_id)
                if task and task.payload:
                    test_data = task.payload

            return render_template(
                'curriculum/book_courses/lessons/final_test.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards,
                daily_lesson=daily_lesson,
                test_data=test_data,
                next_lesson_url=next_lesson_url,
                has_next_lesson=has_next_lesson
            )
        elif lesson_type == 'mixed_practice':
            return render_template(
                'curriculum/book_courses/lessons/text.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards
            )
        else:
            return render_template(
                'curriculum/book_courses/lessons/text.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards
            )

    except Exception as e:
        logger.error(f"Error viewing lesson by id {lesson_id}: {str(e)}")
        flash('Ошибка при загрузке урока', 'error')
        return redirect(url_for('book_courses.view_module',
                                course_id=course_id, module_id=module_id))


# API endpoints according to Детальный_план_уроков.md

@book_courses_bp.route('/api/v1/lesson/<int:lesson_id>')
@login_required
def get_lesson_api(lesson_id):
    """Get lesson data according to specification"""
    try:
        # lesson_id here is daily_lesson_id for new architecture
        from app.curriculum.daily_lessons import DailyLesson, SliceVocabulary
        from app.words.models import CollectionWords

        daily_lesson = DailyLesson.query.get_or_404(lesson_id)

        # Check user access
        enrollment = BookCourseEnrollment.query.join(
            BookCourseModule
        ).filter(
            BookCourseModule.id == daily_lesson.book_course_module_id,
            BookCourseEnrollment.user_id == current_user.id
        ).first()

        if not enrollment:
            return jsonify({'error': 'Access denied'}), 403

        lesson_type = daily_lesson.lesson_type

        if lesson_type == 'vocabulary':
            # GET /api/v1/lesson/:id → JSON: { words:[{id,lemma,translation,example,audio_url}] }
            slice_vocab = SliceVocabulary.query.filter_by(
                daily_lesson_id=daily_lesson.id
            ).options(joinedload(SliceVocabulary.word)).limit(10).all()

            words = []
            for sv in slice_vocab:
                word = sv.word
                words.append({
                    'id': word.id,
                    'lemma': word.english_word,
                    'translation': word.russian_word,
                    'example': truncate_context(sv.context_sentence or '', max_sentences=1),
                    'audio_url': f'/static/audio/pronunciation_en_{word.english_word.lower().replace(" ", "_")}.mp3'
                })

            return jsonify({'words': words})

        elif lesson_type in ['reading', 'reading_passage']:
            # { html, tooltip_map:{lemma:{id,translation,example,audio_url}} }

            # Try to get vocabulary from this lesson first
            slice_vocab = SliceVocabulary.query.filter_by(
                daily_lesson_id=daily_lesson.id
            ).options(joinedload(SliceVocabulary.word)).all()

            tooltip_map = {}

            # If no vocabulary for this lesson, try to get from module's block vocabulary
            if not slice_vocab:
                from app.books.models import BlockVocab
                from app.words.models import CollectionWords as CW

                module = BookCourseModule.query.get(daily_lesson.book_course_module_id)
                if module and module.block_id:
                    # Get all vocabulary from the block
                    block_vocab = (db.session.query(BlockVocab, CW)
                                   .join(CW, BlockVocab.word_id == CW.id)
                                   .filter(BlockVocab.block_id == module.block_id)
                                   .order_by(BlockVocab.freq.desc())
                                   .limit(50)
                                   .all())

                    text_lower = (daily_lesson.slice_text or '').lower()
                    for bv, word in block_vocab:
                        word_lower = word.english_word.lower()
                        # Only include words that appear in this slice
                        if word_lower in text_lower:
                            tooltip_map[word_lower] = {
                                'id': word.id,
                                'translation': word.russian_word,
                                'example': '',
                                'audio_url': f'/static/audio/pronunciation_en_{word_lower.replace(" ", "_")}.mp3',
                                'transcription': getattr(word, 'transcription', None),
                                'pos': getattr(word, 'pos', None)
                            }
            else:
                # Use vocabulary from SliceVocabulary
                for sv in slice_vocab:
                    word = sv.word
                    tooltip_map[word.english_word.lower()] = {
                        'id': word.id,
                        'translation': word.russian_word,
                        'example': truncate_context(sv.context_sentence or '', max_sentences=1),
                        'audio_url': f'/static/audio/pronunciation_en_{word.english_word.lower().replace(" ", "_")}.mp3',
                        'transcription': getattr(word, 'transcription', None),
                        'pos': getattr(word, 'pos', None)
                    }

            # Highlight vocabulary words in text with better regex
            import re
            html_text = daily_lesson.slice_text or ''

            # Handle both literal \n (escaped) and actual newlines
            # First replace literal backslash-n with actual newlines
            html_text = html_text.replace('\\n', '\n')
            html_text = html_text.replace('\r\n', '\n')

            # Split by double newlines or treat single newlines as paragraph breaks
            if '\n\n' in html_text:
                paragraphs = html_text.split('\n\n')
            elif '\n' in html_text:
                paragraphs = html_text.split('\n')
            else:
                paragraphs = [html_text]

            html_paragraphs = []

            for idx, paragraph in enumerate(paragraphs):
                paragraph = paragraph.strip()
                if not paragraph:
                    continue

                # Highlight vocabulary words in this paragraph (preserve original case)
                highlighted_paragraph = paragraph
                for lemma in tooltip_map:
                    # Use word boundaries to match whole words only, preserve original case
                    pattern = r'\b(' + re.escape(lemma) + r')\b'
                    highlighted_paragraph = re.sub(
                        pattern,
                        lambda m: f'<span class="word" data-lemma="{lemma}">{m.group(1)}</span>',
                        highlighted_paragraph,
                        flags=re.IGNORECASE
                    )

                # Wrap in paragraph with data-paragraph-index
                html_paragraphs.append(
                    f'<p data-paragraph-index="{idx}">{highlighted_paragraph}</p>'
                )

            # If no paragraphs found, wrap entire text in one paragraph
            if not html_paragraphs and html_text.strip():
                html_paragraphs = [f'<p>{html_text.strip()}</p>']

            final_html = '\n'.join(html_paragraphs)

            return jsonify({
                'html': final_html,
                'tooltip_map': tooltip_map,
                'word_count': daily_lesson.word_count,
                'title': f'Чтение — День {daily_lesson.day_number}'
            })

        else:
            return jsonify({'error': 'Lesson type not supported'}), 400

    except Exception as e:
        logger.error(f"Error getting lesson {lesson_id}: {str(e)}")
        return jsonify({'error': 'Server error'}), 500


@book_courses_bp.route('/api/v1/lesson/<int:lesson_id>/complete', methods=['POST'])
@login_required
def complete_lesson_api_v1(lesson_id):
    """Complete lesson according to specification"""
    try:
        # POST /api/v1/lesson/:id/complete → 201
        from app.curriculum.daily_lessons import DailyLesson, UserLessonProgress, LessonCompletionEvent

        daily_lesson = DailyLesson.query.get_or_404(lesson_id)

        # Check user access
        enrollment = BookCourseEnrollment.query.join(
            BookCourseModule
        ).filter(
            BookCourseModule.id == daily_lesson.book_course_module_id,
            BookCourseEnrollment.user_id == current_user.id
        ).first()

        if not enrollment:
            return jsonify({'error': 'Access denied'}), 403

        # Create or update progress
        progress = UserLessonProgress.query.filter_by(
            user_id=current_user.id,
            daily_lesson_id=lesson_id,
            enrollment_id=enrollment.id
        ).first()

        if not progress:
            progress = UserLessonProgress(
                user_id=current_user.id,
                daily_lesson_id=lesson_id,
                enrollment_id=enrollment.id,
                status='completed',
                started_at=datetime.now(UTC)
            )
            db.session.add(progress)

        progress.status = 'completed'
        progress.completed_at = datetime.now(UTC)

        # Also update BookModuleProgress.lessons_completed for template compatibility
        module_progress = BookModuleProgress.query.filter_by(
            enrollment_id=enrollment.id,
            module_id=daily_lesson.book_course_module_id
        ).first()

        if module_progress:
            lessons_completed = list(module_progress.lessons_completed or [])
            if daily_lesson.id not in lessons_completed:
                lessons_completed.append(daily_lesson.id)
                module_progress.lessons_completed = lessons_completed
                flag_modified(module_progress, 'lessons_completed')
                # Update module status
                module_progress.status = 'in_progress'

        # Create completion event
        completion_event = LessonCompletionEvent(
            daily_lesson_id=lesson_id,
            user_id=current_user.id,
            event_type='lesson_completed',
            event_data={'lesson_type': daily_lesson.lesson_type}
        )
        db.session.add(completion_event)

        # Auto-create SRS cards for vocabulary lessons
        if daily_lesson.lesson_type == 'vocabulary':
            try:
                from app.curriculum.services.book_srs_integration import BookSRSIntegration
                srs_integration = BookSRSIntegration()
                srs_integration.auto_create_srs_cards_from_vocabulary_lesson(
                    user_id=current_user.id,
                    daily_lesson=daily_lesson
                )
                logger.info(f"Auto-created SRS cards for lesson {lesson_id}")
            except Exception as e:
                logger.error(f"Error auto-creating SRS cards: {str(e)}")

        db.session.commit()

        return jsonify({'success': True, 'message': 'Lesson completed'}), 201

    except Exception as e:
        logger.error(f"Error completing lesson {lesson_id}: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Server error'}), 500


@book_courses_bp.route('/api/book-courses/<int:course_id>/modules/<int:module_id>/complete-lesson', methods=['POST'])
@login_required
def complete_lesson_api(course_id, module_id):
    """Mark a lesson as completed"""
    try:
        data = request.get_json()
        lesson_number = data.get('lesson_number')
        score = data.get('score', 100)

        if not lesson_number:
            return jsonify({'success': False, 'error': 'lesson_number required'}), 400

        # Get enrollment and module progress
        enrollment = BookCourseEnrollment.query.filter_by(
            user_id=current_user.id,
            course_id=course_id
        ).first()

        if not enrollment:
            return jsonify({'success': False, 'error': 'Not enrolled'}), 403

        module_progress = BookModuleProgress.query.filter_by(
            enrollment_id=enrollment.id,
            module_id=module_id
        ).first()

        if not module_progress:
            return jsonify({'success': False, 'error': 'Module progress not found'}), 404

        # Mark lesson as completed
        module_progress.mark_lesson_completed(lesson_number, score)

        # Auto-create SRS cards for vocabulary lessons
        try:
            from app.curriculum.services.book_srs_integration import BookSRSIntegration
            from app.curriculum.daily_lessons import DailyLesson

            # Find the corresponding daily lesson and check if it's vocabulary
            daily_lesson = DailyLesson.query.filter_by(
                book_course_module_id=module_id,
                day_number=lesson_number,
                lesson_type='vocabulary'
            ).first()

            if daily_lesson:
                srs_integration = BookSRSIntegration()
                srs_integration.auto_create_srs_cards_from_vocabulary_lesson(
                    user_id=current_user.id,
                    daily_lesson=daily_lesson
                )
                logger.info(f"Auto-created SRS cards for vocabulary lesson {lesson_number}")
        except Exception as e:
            logger.error(f"Error auto-creating SRS cards: {str(e)}")

        # Update enrollment progress
        enrollment.last_activity = datetime.now(UTC)

        # Calculate overall course progress
        total_modules = BookCourseModule.query.filter_by(course_id=course_id).count()
        completed_modules = BookModuleProgress.query.filter_by(
            enrollment_id=enrollment.id,
            status='completed'
        ).count()

        enrollment.progress_percentage = (completed_modules / total_modules) * 100 if total_modules > 0 else 0

        db.session.commit()

        return jsonify({
            'success': True,
            'lesson_completed': True,
            'module_progress': module_progress.progress_percentage,
            'module_status': module_progress.status,
            'course_progress': enrollment.progress_percentage
        })

    except Exception as e:
        logger.error(f"Error completing lesson: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Server error'}), 500


@book_courses_bp.route('/api/book-courses/<int:course_id>/progress')
@login_required
def get_course_progress_api(course_id):
    """Get user's progress in a course"""
    try:
        enrollment = BookCourseEnrollment.query.filter_by(
            user_id=current_user.id,
            course_id=course_id
        ).first()

        if not enrollment:
            return jsonify({'success': False, 'error': 'Not enrolled'}), 404

        # Get module progress
        module_progress = BookModuleProgress.query.filter_by(
            enrollment_id=enrollment.id
        ).all()

        progress_data = {
            'enrollment': {
                'status': enrollment.status,
                'progress_percentage': enrollment.progress_percentage,
                'total_study_time': enrollment.total_study_time,
                'words_learned': enrollment.words_learned,
                'enrolled_at': enrollment.enrolled_at.isoformat(),
                'last_activity': enrollment.last_activity.isoformat() if enrollment.last_activity else None
            },
            'modules': [
                {
                    'module_id': mp.module_id,
                    'status': mp.status,
                    'progress_percentage': mp.progress_percentage,
                    'lessons_completed': mp.lessons_completed or [],
                    'current_lesson': mp.current_lesson_number,
                    'reading_position': mp.reading_position,
                    'vocabulary_score': mp.vocabulary_score,
                    'comprehension_score': mp.comprehension_score
                }
                for mp in module_progress
            ]
        }

        return jsonify({
            'success': True,
            'course_id': course_id,
            'progress': progress_data
        })

    except Exception as e:
        logger.error(f"Error getting course progress: {str(e)}")
        return jsonify({'success': False, 'error': 'Server error'}), 500


@book_courses_bp.route('/api/srs/session/<int:lesson_id>', methods=['GET'])
@login_required
def get_srs_session(lesson_id):
    """
    Get SRS session for vocabulary lesson.
    Returns only cards that are due for review today.
    """
    try:
        daily_lesson = DailyLesson.query.get_or_404(lesson_id)

        # Get enrollment
        module = BookCourseModule.query.get(daily_lesson.book_course_module_id)
        enrollment = BookCourseEnrollment.query.filter_by(
            user_id=current_user.id,
            course_id=module.course_id
        ).first()

        if not enrollment:
            return jsonify({'error': 'Not enrolled'}), 403

        srs_integration = BookSRSIntegration()
        session_data = srs_integration.create_srs_session_for_lesson(
            user_id=current_user.id,
            daily_lesson=daily_lesson,
            enrollment=enrollment
        )

        return jsonify(session_data)

    except Exception as e:
        logger.error(f"Error creating SRS session: {str(e)}")
        return jsonify({'error': 'Server error'}), 500


@book_courses_bp.route('/api/srs/grade', methods=['POST'])
@login_required
def grade_srs_card():
    """
    Grade an SRS card.
    POST /api/srs/grade {card_id, grade, session_key}

    Grade scale:
    1 = "Не знаю" (Again)
    3 = "Сомневаюсь" (Hard)
    5 = "Знаю" (Easy)
    """
    try:
        data = request.get_json()
        card_id = data.get('card_id')
        grade = data.get('grade')
        session_key = data.get('session_key', '')

        if not card_id or grade is None:
            return jsonify({'success': False, 'error': 'card_id and grade required'}), 400

        srs_integration = BookSRSIntegration()
        result = srs_integration.process_card_grade(
            user_id=current_user.id,
            card_id=card_id,
            grade=grade,
            session_key=session_key
        )

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error grading SRS card: {str(e)}")
        return jsonify({'success': False, 'error': 'Server error'}), 500


@book_courses_bp.route('/api/srs/add-card', methods=['POST'])
@login_required
def add_word_to_srs():
    """
    Add a word to user's SRS flashcards.
    POST /api/srs/add-card {word_id, source, course_id}

    Returns word_status: 'not_added', 'in_learning', or 'learned'
    """
    try:
        data = request.get_json()
        word_id = data.get('word_id')
        source = data.get('source', 'book_reading')
        course_id = data.get('course_id')

        if not word_id:
            return jsonify({'success': False, 'error': 'word_id required'}), 400

        srs_integration = BookSRSIntegration()
        result = srs_integration.add_word_to_srs(
            user_id=current_user.id,
            word_id=word_id,
            source=source,
            course_id=course_id
        )

        if result.get('success'):
            return jsonify(result)
        else:
            # Return word_status even on failure (for UI to update)
            return jsonify(result), 400

    except Exception as e:
        logger.error(f"Error adding word to SRS: {str(e)}")
        return jsonify({'success': False, 'error': 'Server error'}), 500


# ==================== NEW ROUTES WITH SLUG AND ORDINAL NUMBERS ====================
# URL format: /curriculum/courses/<slug>/modules/<module_number>/lessons/<lesson_number>
# Example: /curriculum/courses/harry-potter-order-phoenix/modules/1/lessons/2

@book_courses_bp.route('/courses/<course_slug>')
@login_required
def view_course_by_slug(course_slug):
    """Display course details by slug - redirects to main view_course"""
    course = get_course_by_slug_or_id(course_slug)
    return view_course(course.id)


@book_courses_bp.route('/courses/<course_slug>/enroll', methods=['POST'])
@csrf.exempt
@login_required
def enroll_by_slug(course_slug):
    """Enroll in course by slug"""
    course = get_course_by_slug_or_id(course_slug)
    return enroll_in_course(course.id)


@book_courses_bp.route('/courses/<course_slug>/modules/<int:module_number>')
@login_required
def view_module_by_slug(course_slug, module_number):
    """Display module by course slug and module number"""
    course = get_course_by_slug_or_id(course_slug)

    # Get module by number
    module = BookCourseModule.query.filter_by(
        course_id=course.id,
        module_number=module_number
    ).first_or_404()

    return view_module(course.id, module.id)


@book_courses_bp.route('/courses/<course_slug>/modules/<int:module_number>/lessons/<int:lesson_number>')
@login_required
def view_lesson_by_slug(course_slug, module_number, lesson_number):
    """Display lesson by course slug, module number and lesson number"""
    course = get_course_by_slug_or_id(course_slug)

    # Get module by number
    module = BookCourseModule.query.filter_by(
        course_id=course.id,
        module_number=module_number
    ).first_or_404()

    # Get lesson by number within module
    daily_lesson = DailyLesson.query.filter_by(
        book_course_module_id=module.id
    ).order_by(DailyLesson.day_number, DailyLesson.id).all()

    # Find lesson by index (lesson_number is 1-based)
    if lesson_number < 1 or lesson_number > len(daily_lesson):
        abort(404)

    lesson = daily_lesson[lesson_number - 1]

    return view_lesson_by_id(course.id, module.id, lesson.id)


# Helper to generate URL for lessons with pretty format
def get_pretty_lesson_url(course, module, lesson_index):
    """Generate pretty URL for lesson"""
    if course.slug:
        return url_for('book_courses.view_lesson_by_slug',
                      course_slug=course.slug,
                      module_number=module.module_number,
                      lesson_number=lesson_index)
    else:
        # Fallback to id-based URL
        return url_for('book_courses.view_lesson',
                      course_id=course.id,
                      module_id=module.id,
                      lesson_number=lesson_index)
