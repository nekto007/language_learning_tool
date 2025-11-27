# app/curriculum/routes/book_courses.py

import logging
from datetime import UTC, datetime

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload
from app import csrf

from app.curriculum.book_courses import (BookCourse, BookCourseEnrollment, BookCourseModule, BookModuleProgress)
from app.curriculum.daily_lessons import DailyLesson, SliceVocabulary
from app.curriculum.services.book_srs_integration import BookSRSIntegration
from app.utils.db import db

logger = logging.getLogger(__name__)

# Create blueprint for book course routes
book_courses_bp = Blueprint('book_courses', __name__)


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
            lesson_type_display = {
                'vocabulary': 'Словарь',
                'reading_passage': 'Чтение',
                'reading_mcq': 'Тест по чтению',
                'match_headings': 'Заголовки',
                'open_cloze': 'Пропуски',
                'word_formation': 'Словообразование',
                'keyword_transform': 'Трансформации',
                'grammar_sheet': 'Грамматика',
                'final_test': 'Финальный тест'
            }.get(dl.lesson_type, dl.lesson_type.replace('_', ' ').title())

            lessons.append({
                'lesson_number': dl.day_number,
                'type': dl.lesson_type,
                'title': f'Day {dl.day_number}: {lesson_type_display}',
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
                'title': f'Day {daily_lesson.day_number}: {daily_lesson.lesson_type.replace("_", " ").title()}',
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

        # Route to appropriate lesson type handler
        lesson_type = lesson.get('type', 'text')

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
        elif lesson_type in ['reading_assignment', 'reading_passage']:
            template = 'curriculum/book_courses/lessons/reading_passage.html' if lesson_type == 'reading_passage' else 'curriculum/book_courses/lessons/reading_assignment.html'

            # For reading_passage, prepare data according to specification
            if lesson_type == 'reading_passage' and daily_lesson:
                return render_template(
                    template,
                    course=course,
                    module=module,
                    lesson=lesson,
                    lesson_number=lesson_number,
                    module_progress=module_progress,
                    book=course.book,
                    daily_lesson=daily_lesson,
                    use_api=True,  # Flag to use API loading
                    review_cards=review_cards
                )
            else:
                return render_template(
                    template,
                    course=course,
                    module=module,
                    lesson=lesson,
                    lesson_number=lesson_number,
                    module_progress=module_progress,
                    book=course.book,
                    daily_lesson=daily_lesson if 'daily_lesson' in locals() else None,
                    use_api=False,
                    review_cards=review_cards
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
                    vocab_item = {
                        'id': word.id,
                        'lemma': word.english_word,  # As per specification
                        'translation': word.russian_word,
                        'example': sv.context_sentence or '',
                        'audio_url': f'/static/audio/pronunciation_en_{word.english_word.lower()}.mp3',
                        'frequency': sv.frequency_in_slice,
                        'part_of_speech': getattr(word, 'pos', 'unknown')
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
                review_cards=review_cards
            )
        elif lesson_type == 'grammar':
            return render_template(
                'curriculum/book_courses/lessons/grammar.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards
            )
        elif lesson_type in ['reading_mcq', 'match_headings', 'open_cloze', 'word_formation', 'keyword_transform']:
            # Specific lesson types with their own templates
            return render_template(
                f'curriculum/book_courses/lessons/{lesson_type}.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards
            )
        else:
            # Default text lesson for 'text', 'final_test' and other types
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
            'title': f'Day {daily_lesson.day_number}: {daily_lesson.lesson_type.replace("_", " ").title()}',
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
        elif lesson_type in ['reading_assignment', 'reading_passage']:
            template = 'curriculum/book_courses/lessons/reading_passage.html' if lesson_type == 'reading_passage' else 'curriculum/book_courses/lessons/reading_assignment.html'

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
                review_cards=review_cards
            )
        elif lesson_type == 'vocabulary':
            # Load vocabulary from SliceVocabulary
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
                    'example': sv.context_sentence or '',
                    'audio_url': f'/static/audio/pronunciation_en_{word.english_word.lower()}.mp3',
                    'frequency': sv.frequency_in_slice,
                    'part_of_speech': getattr(word, 'pos', 'unknown')
                }
                vocabulary_data.append(vocab_item)

            vocabulary_data = vocabulary_data[:10]

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
                review_cards=review_cards
            )
        elif lesson_type == 'grammar':
            return render_template(
                'curriculum/book_courses/lessons/grammar.html',
                course=course,
                module=module,
                lesson=lesson,
                lesson_number=lesson_number,
                module_progress=module_progress,
                review_cards=review_cards
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
                    'example': sv.context_sentence or '',
                    'audio_url': f'/static/audio/pronunciation_en_{word.english_word.lower()}.mp3'
                })

            return jsonify({'words': words})

        elif lesson_type == 'reading_passage':
            # { html, tooltip_map:{lemma:{translation,example}} }
            slice_vocab = SliceVocabulary.query.filter_by(
                daily_lesson_id=daily_lesson.id
            ).options(joinedload(SliceVocabulary.word)).all()

            tooltip_map = {}
            for sv in slice_vocab:
                word = sv.word
                tooltip_map[word.english_word.lower()] = {
                    'translation': word.russian_word,
                    'example': sv.context_sentence or ''
                }

            # Highlight vocabulary words in text with better regex
            import re
            html_text = daily_lesson.slice_text

            # Split text into paragraphs and wrap them
            paragraphs = html_text.split('\n\n')
            html_paragraphs = []

            for idx, paragraph in enumerate(paragraphs):
                if paragraph.strip():
                    # Highlight vocabulary words in this paragraph
                    highlighted_paragraph = paragraph
                    for lemma in tooltip_map:
                        # Use word boundaries to match whole words only
                        pattern = r'\b' + re.escape(lemma) + r'\b'
                        highlighted_paragraph = re.sub(
                            pattern,
                            f'<span class="word" data-lemma="{lemma}">{lemma}</span>',
                            highlighted_paragraph,
                            flags=re.IGNORECASE
                        )

                    # Wrap in paragraph with data-paragraph-index
                    html_paragraphs.append(
                        f'<p data-paragraph-index="{idx}">{highlighted_paragraph}</p>'
                    )

            final_html = '\n'.join(html_paragraphs)

            return jsonify({
                'html': final_html,
                'tooltip_map': tooltip_map,
                'word_count': daily_lesson.word_count,
                'title': f'Reading Passage - Day {daily_lesson.day_number}'
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

        return '', 201

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
