import logging
from datetime import UTC, datetime

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.curriculum.book_courses import (
    BookCourse, BookCourseEnrollment, BookCourseModule, BookModuleProgress, generate_slug,
)
from app.curriculum.daily_lessons import DailyLesson, SliceVocabulary
from app.curriculum.routes.book_courses_service import (
    LESSON_ORDER, _build_linked_topics_and_return_url, _build_vocabulary_fc_vars,
    _parse_lesson_scaffold, build_daily_lesson_dict, ensure_words_in_book_deck,
    find_next_lesson_url, get_course_by_slug_or_id, get_lesson_type_display,
    get_pretty_lesson_url, get_ui_lang, load_vocabulary_data, truncate_context,
)
from app.curriculum.services.book_srs_integration import BookSRSIntegration
from app.curriculum.services.comprehension_generator import ClozePracticeGenerator, ComprehensionMCQGenerator
from app.curriculum.services.grammar_focus_generator import GrammarFocusGenerator
from app.utils.db import db

logger = logging.getLogger(__name__)

book_courses_bp = Blueprint('book_courses', __name__)


@book_courses_bp.route('/book-courses')
@login_required
def list_book_courses():
    """Display all available book courses"""
    try:
        courses = BookCourse.query.filter_by(is_active=True).order_by(
            BookCourse.is_featured.desc(),
            BookCourse.created_at.desc()
        ).all()

        user_enrollments = {}
        if current_user.is_authenticated:
            enrollments = BookCourseEnrollment.query.filter_by(
                user_id=current_user.id
            ).all()
            user_enrollments = {e.course_id: e for e in enrollments}

        course_data = []
        for course in courses:
            enrollment = user_enrollments.get(course.id)
            course_data.append({
                'course': course,
                'book': course.book,
                'enrollment': enrollment,
                'is_enrolled': enrollment is not None,
                'progress_percentage': enrollment.progress_percentage if enrollment else 0,
                'current_module': enrollment.current_module if enrollment else None
            })

        from app.telegram.models import TelegramUser
        telegram_linked = TelegramUser.query.filter_by(
            user_id=current_user.id, is_active=True
        ).first() is not None

        return render_template(
            'curriculum/book_courses/list.html',
            courses=course_data,
            total_courses=len(course_data),
            telegram_linked=telegram_linked,
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

        enrollment = BookCourseEnrollment.query.filter_by(
            user_id=current_user.id,
            course_id=course_id
        ).first()

        modules = BookCourseModule.query.filter_by(
            course_id=course_id
        ).order_by(BookCourseModule.order_index).all()

        module_progress = {}
        if enrollment:
            progress_records = BookModuleProgress.query.filter_by(
                enrollment_id=enrollment.id
            ).all()
            module_progress = {p.module_id: p for p in progress_records}

        from app.study.models import UserWord
        known_word_ids = {
            r[0] for r in db.session.query(UserWord.word_id).filter(
                UserWord.user_id == current_user.id
            ).all()
        }

        module_data = []
        for i, module in enumerate(modules):
            progress = module_progress.get(module.id)

            is_unlocked = True
            if module.is_locked and i > 0:
                prev_module = modules[i - 1]
                prev_progress = module_progress.get(prev_module.id)
                is_unlocked = prev_progress and prev_progress.status == 'completed'

            new_words_count = 0
            total_vocab = 0
            if module.vocabulary_focus:
                vocab_word_ids = []
                for v in module.vocabulary_focus:
                    if isinstance(v, dict) and v.get('id'):
                        vocab_word_ids.append(v['id'])
                    elif isinstance(v, int):
                        vocab_word_ids.append(v)
                total_vocab = len(vocab_word_ids)
                new_words_count = sum(1 for wid in vocab_word_ids if wid not in known_word_ids)

            module_data.append({
                'module': module,
                'progress': progress,
                'is_unlocked': is_unlocked,
                'progress_percentage': progress.progress_percentage if progress else 0,
                'status': progress.status if progress else 'not_started',
                'new_words_count': new_words_count,
                'total_vocab': total_vocab,
            })

        return render_template(
            'curriculum/book_courses/course_detail.html',
            course=course, book=course.book, enrollment=enrollment,
            modules=module_data, total_modules=len(modules),
            is_enrolled=enrollment is not None
        )

    except Exception as e:
        logger.error(f"Error viewing course {course_id}: {str(e)}")
        flash('Ошибка при загрузке курса', 'error')
        return redirect(url_for('book_courses.list_book_courses'))


@book_courses_bp.route('/book-courses/<int:course_id>/enroll', methods=['POST'])
@login_required
def enroll_in_course(course_id):
    """Enroll user in a book course"""
    try:
        course = BookCourse.query.get_or_404(course_id)

        if not course.is_active:
            return jsonify({'success': False, 'error': 'Курс недоступен'}), 400

        existing_enrollment = BookCourseEnrollment.query.filter_by(
            user_id=current_user.id, course_id=course_id
        ).first()

        if existing_enrollment:
            return jsonify({'success': False, 'error': 'Вы уже записаны на этот курс'}), 400

        enrollment = BookCourseEnrollment(
            user_id=current_user.id, course_id=course_id,
            status='active', enrolled_at=datetime.now(UTC)
        )

        first_module = BookCourseModule.query.filter_by(
            course_id=course_id
        ).order_by(BookCourseModule.order_index).first()

        if first_module:
            enrollment.current_module_id = first_module.id

        db.session.add(enrollment)
        db.session.commit()

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

        enrollment = BookCourseEnrollment.query.filter_by(
            user_id=current_user.id, course_id=course_id
        ).first()

        if not enrollment:
            flash('Вы должны записаться на курс, чтобы просматривать модули', 'error')
            return redirect(url_for('book_courses.view_course', course_id=course_id))

        if module.is_locked:
            prev_module = BookCourseModule.query.filter(
                BookCourseModule.course_id == course_id,
                BookCourseModule.order_index < module.order_index
            ).order_by(BookCourseModule.order_index.desc()).first()

            if prev_module:
                prev_progress = BookModuleProgress.query.filter_by(
                    enrollment_id=enrollment.id, module_id=prev_module.id
                ).first()
                if not prev_progress or prev_progress.status != 'completed':
                    flash('Вы должны завершить предыдущий модуль', 'error')
                    return redirect(url_for('book_courses.view_course', course_id=course_id))

        module_progress = BookModuleProgress.query.filter_by(
            enrollment_id=enrollment.id, module_id=module_id
        ).first()

        if not module_progress:
            module_progress = BookModuleProgress(
                enrollment_id=enrollment.id, module_id=module_id,
                status='not_started', started_at=datetime.now(UTC)
            )
            db.session.add(module_progress)
            db.session.commit()

        daily_lessons = DailyLesson.query.filter_by(
            book_course_module_id=module.id
        ).order_by(*LESSON_ORDER).all()

        ui_lang = get_ui_lang(course.level)
        lessons = []
        for dl in daily_lessons:
            type_label = get_lesson_type_display(dl.lesson_type, ui_lang)
            if ui_lang == 'en':
                title = f'Day {dl.day_number}: {type_label}'
            else:
                title = f'День {dl.day_number}: {type_label}'
            lessons.append({
                'lesson_number': dl.day_number, 'type': dl.lesson_type,
                'title': title, 'id': dl.id, 'estimated_time': 15, 'description': None
            })

        next_module = BookCourseModule.query.filter(
            BookCourseModule.course_id == course_id,
            BookCourseModule.order_index > module.order_index
        ).order_by(BookCourseModule.order_index).first()

        prev_module = BookCourseModule.query.filter(
            BookCourseModule.course_id == course_id,
            BookCourseModule.order_index < module.order_index
        ).order_by(BookCourseModule.order_index.desc()).first()

        srs_integration = BookSRSIntegration()
        due_cards_count = srs_integration.get_due_cards_count(current_user.id)

        return render_template(
            'curriculum/book_courses/module_detail.html',
            course=course, module=module, enrollment=enrollment,
            module_progress=module_progress, lessons=lessons,
            next_module=next_module, prev_module=prev_module,
            due_cards_count=due_cards_count
        )

    except Exception as e:
        logger.error(f"Error viewing module {module_id}: {str(e)}")
        flash('Ошибка при загрузке модуля', 'error')
        return redirect(url_for('book_courses.view_course', course_id=course_id))


def _prepare_lesson_context(course_id, module_id, daily_lesson=None, lesson_number=None):
    """Common setup for view_lesson and view_lesson_by_id."""
    course = BookCourse.query.get_or_404(course_id)
    module = BookCourseModule.query.get_or_404(module_id)

    if module.course_id != course_id:
        abort(404)

    enrollment = BookCourseEnrollment.query.filter_by(
        user_id=current_user.id, course_id=course_id
    ).first()

    if not enrollment:
        flash('Доступ запрещен', 'error')
        return None

    if daily_lesson is None and lesson_number is not None:
        daily_lesson = DailyLesson.query.filter_by(
            book_course_module_id=module_id,
            day_number=lesson_number
        ).first()

        if not daily_lesson:
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
            lesson = build_daily_lesson_dict(daily_lesson, course.level)
    else:
        lesson = build_daily_lesson_dict(daily_lesson, course.level)
        lesson_number = daily_lesson.day_number

    module_progress = BookModuleProgress.query.filter_by(
        enrollment_id=enrollment.id, module_id=module_id
    ).first()

    if not module_progress:
        flash('Ошибка доступа к модулю', 'error')
        return None

    srs_integration = BookSRSIntegration()
    review_cards = srs_integration.get_due_cards_for_review(current_user.id, limit=5)

    next_lesson_url = None
    has_next_lesson = False
    if daily_lesson:
        next_lesson_url, has_next_lesson = find_next_lesson_url(
            daily_lesson, module_id, course, module
        )

    return {
        'course': course, 'module': module, 'enrollment': enrollment,
        'daily_lesson': daily_lesson, 'lesson': lesson, 'lesson_number': lesson_number,
        'module_progress': module_progress, 'review_cards': review_cards,
        'next_lesson_url': next_lesson_url, 'has_next_lesson': has_next_lesson,
    }


def _render_lesson_by_type(ctx):
    """Render lesson template based on lesson type."""
    course = ctx['course']
    module = ctx['module']
    lesson = ctx['lesson']
    lesson_number = ctx['lesson_number']
    module_progress = ctx['module_progress']
    daily_lesson = ctx['daily_lesson']
    review_cards = ctx['review_cards']
    next_lesson_url = ctx['next_lesson_url']
    has_next_lesson = ctx['has_next_lesson']

    lesson_type = lesson.get('type', 'text')
    common = dict(course=course, module=module, lesson=lesson,
                  lesson_number=lesson_number, module_progress=module_progress,
                  review_cards=review_cards)

    if lesson_type in ('anki_session', 'srs'):
        return render_template(
            'curriculum/book_courses/lessons/anki_session.html',
            **common, book=course.book
        )

    if lesson_type in ['reading', 'reading_assignment', 'reading_passage', 'reading_part1', 'reading_part2']:
        dl = daily_lesson
        reading_difficulty = None
        if dl:
            from app.study.models import UserWord
            slice_vocab = SliceVocabulary.query.filter_by(daily_lesson_id=dl.id).all()
            if slice_vocab:
                known_ids = {
                    r[0] for r in db.session.query(UserWord.word_id).filter(
                        UserWord.user_id == current_user.id
                    ).all()
                }
                new_count = sum(1 for sv in slice_vocab if sv.word_id not in known_ids)
                _ui = get_ui_lang(course.level)
                if new_count < 5:
                    hint = 'Easy reading — enjoy the story!' if _ui == 'en' else 'Лёгкое чтение — наслаждайся историей!'
                    reading_difficulty = {'level': 'easy', 'new_words': new_count, 'hint': hint}
                elif new_count <= 10:
                    hint = 'Moderate reading — highlight key words' if _ui == 'en' else 'Среднее чтение — подчёркивай важные слова'
                    reading_difficulty = {'level': 'medium', 'new_words': new_count, 'hint': hint}
                else:
                    hint = 'Intensive reading — analyze each sentence' if _ui == 'en' else 'Вдумчивое чтение — разбирай каждое предложение'
                    reading_difficulty = {'level': 'hard', 'new_words': new_count, 'hint': hint}

        scaffold = _parse_lesson_scaffold(dl.annotations if dl else None)
        return render_template(
            'curriculum/book_courses/lessons/reading_passage.html',
            **common, book=course.book, daily_lesson=dl,
            use_api=True if dl else False, next_lesson_url=next_lesson_url,
            has_next_lesson=has_next_lesson, reading_difficulty=reading_difficulty,
            **scaffold,
        )

    if lesson_type == 'vocabulary':
        vocabulary_data = load_vocabulary_data(daily_lesson, lesson, course.level)
        book_deck = ensure_words_in_book_deck(current_user.id, course, vocabulary_data)
        fc_vars = _build_vocabulary_fc_vars(
            vocabulary_data=vocabulary_data, course=course, module=module,
            daily_lesson=daily_lesson, next_lesson_url=next_lesson_url,
            has_next_lesson=has_next_lesson,
        )
        return render_template(
            'curriculum/book_courses/lessons/vocabulary.html',
            **common, vocabulary_data=vocabulary_data,
            total_words=len(vocabulary_data), daily_lesson=daily_lesson,
            book_deck=book_deck, **fc_vars,
        )

    if lesson_type in ['grammar', 'language_focus']:
        from app.grammar_lab.models import GrammarTopic, GrammarExercise

        task = daily_lesson.task if daily_lesson else None
        if task and task.payload and isinstance(task.payload, dict) and 'title' in task.payload:
            lf = task.payload
            linked_topics, grammar_return_url = _build_linked_topics_and_return_url(
                lf, course, module, next_lesson_url, has_next_lesson
            )
            return render_template(
                'curriculum/book_courses/lessons/language_focus.html',
                **common, lf=lf, linked_topics=linked_topics,
                daily_lesson=daily_lesson, next_lesson_url=next_lesson_url,
                has_next_lesson=has_next_lesson, grammar_return_url=grammar_return_url,
            )

        topic = None
        if task and getattr(task, 'grammar_topic_id', None):
            topic = GrammarTopic.query.get(task.grammar_topic_id)

        if not topic:
            course_level = course.level or 'B1'
            day_number = daily_lesson.day_number if daily_lesson else lesson_number
            grammar_lesson_index = (day_number - 1) // 6
            grammar_topics = GrammarTopic.query.filter_by(level=course_level).order_by(GrammarTopic.order).all()
            if not grammar_topics:
                for fallback in ['B1', 'A2', 'A1']:
                    grammar_topics = GrammarTopic.query.filter_by(level=fallback).order_by(GrammarTopic.order).all()
                    if grammar_topics:
                        break
            if grammar_topics:
                topic = grammar_topics[grammar_lesson_index % len(grammar_topics)]

        exercises = []
        if topic:
            topic_exercises = GrammarExercise.query.filter_by(
                topic_id=topic.id
            ).filter(
                GrammarExercise.exercise_type.in_(['multiple_choice', 'fill_blank'])
            ).order_by(GrammarExercise.order).limit(5).all()
            for ex in topic_exercises:
                exercises.append({
                    'id': ex.id, 'exercise_type': ex.exercise_type,
                    'content': ex.content, 'question': ex.content.get('question', ''),
                    'options': ex.content.get('options', []),
                    'correct': ex.content.get('correct_answer', 0),
                    'explanation': ex.content.get('explanation', '')
                })

        return render_template(
            'curriculum/book_courses/lessons/grammar_bridge.html',
            **common, topic=topic, exercises=exercises,
            daily_lesson=daily_lesson, next_lesson_url=next_lesson_url,
            has_next_lesson=has_next_lesson,
        )

    if lesson_type == 'context_review':
        task = daily_lesson.task if daily_lesson and daily_lesson.task_id else None
        if task and task.payload and isinstance(task.payload, dict) and 'title' in task.payload:
            return render_template(
                'curriculum/book_courses/lessons/context_review.html',
                **common, daily_lesson=daily_lesson,
                has_next_lesson=has_next_lesson, next_lesson_url=next_lesson_url,
                cr=task.payload,
            )

        vocabulary_data = []
        if daily_lesson:
            slice_vocab = SliceVocabulary.query.filter_by(
                daily_lesson_id=daily_lesson.id
            ).options(joinedload(SliceVocabulary.word)).all()
            for sv in slice_vocab:
                word = sv.word
                vocabulary_data.append({
                    'id': word.id, 'lemma': word.english_word,
                    'translation': word.russian_word,
                    'example': truncate_context(sv.context_sentence or '', max_sentences=1),
                    'audio_url': f'/static/audio/pronunciation_en_{word.english_word.lower().replace(" ", "_")}.mp3',
                    'frequency': sv.frequency_in_slice,
                })

        book_deck = ensure_words_in_book_deck(current_user.id, course, vocabulary_data[:15])
        fc_vars = _build_vocabulary_fc_vars(
            vocabulary_data=vocabulary_data[:15], course=course, module=module,
            daily_lesson=daily_lesson, next_lesson_url=next_lesson_url,
            has_next_lesson=has_next_lesson, is_review=True,
        )
        return render_template(
            'curriculum/book_courses/lessons/vocabulary.html',
            **common, vocabulary_data=vocabulary_data[:15],
            total_words=len(vocabulary_data[:15]), daily_lesson=daily_lesson,
            is_review=True, book_deck=book_deck, **fc_vars,
        )

    if lesson_type == 'comprehension_mcq':
        task = daily_lesson.task if daily_lesson else None
        if task and task.payload and isinstance(task.payload, dict) and 'title' in task.payload:
            return render_template(
                'curriculum/book_courses/lessons/comprehension_check.html',
                **common, cc=task.payload, daily_lesson=daily_lesson,
                next_lesson_url=next_lesson_url, has_next_lesson=has_next_lesson,
            )
        mcq_data = None
        if daily_lesson and daily_lesson.slice_text:
            mcq_data = ComprehensionMCQGenerator.generate_questions(daily_lesson.slice_text, num_questions=10)
        return render_template(
            'curriculum/book_courses/lessons/reading_mcq.html',
            **common, daily_lesson=daily_lesson, mcq_data=mcq_data,
        )

    if lesson_type == 'phrase_cloze':
        task = daily_lesson.task if daily_lesson and daily_lesson.task_id else None
        if task and task.payload and isinstance(task.payload, dict) and 'title' in task.payload:
            return render_template(
                'curriculum/book_courses/lessons/phrase_cloze.html',
                **common, daily_lesson=daily_lesson,
                has_next_lesson=has_next_lesson, next_lesson_url=next_lesson_url,
                pc=task.payload,
            )
        cloze_data = None
        if task and task.payload:
            cloze_data = task.payload
        if not cloze_data and daily_lesson and daily_lesson.slice_text:
            cloze_data = ClozePracticeGenerator.generate_cloze(daily_lesson.slice_text, num_gaps=8)
        return render_template(
            'curriculum/book_courses/lessons/open_cloze.html',
            **common, daily_lesson=daily_lesson, cloze_data=cloze_data,
        )

    if lesson_type in ['reading_mcq', 'match_headings', 'open_cloze', 'word_formation', 'keyword_transform', 'vocabulary_practice']:
        template_name = 'word_formation' if lesson_type == 'vocabulary_practice' else lesson_type
        return render_template(f'curriculum/book_courses/lessons/{template_name}.html', **common)

    if lesson_type == 'guided_retelling':
        task = daily_lesson.task if daily_lesson and daily_lesson.task_id else None
        if task and task.payload and isinstance(task.payload, dict) and 'title' in task.payload:
            return render_template(
                'curriculum/book_courses/lessons/retelling.html',
                **common, daily_lesson=daily_lesson,
                has_next_lesson=has_next_lesson, next_lesson_url=next_lesson_url,
                rt=task.payload,
            )
        return render_template(
            'curriculum/book_courses/lessons/summary.html',
            **common, daily_lesson=daily_lesson,
        )

    if lesson_type == 'discussion':
        return render_template(
            'curriculum/book_courses/lessons/discussion.html',
            **common, daily_lesson=daily_lesson,
        )

    if lesson_type in ['module_test', 'final_test']:
        test_data = None
        if daily_lesson and daily_lesson.task_id:
            from app.books.models import Task
            task = Task.query.get(daily_lesson.task_id)
            if task and task.payload:
                test_data = task.payload
        return render_template(
            'curriculum/book_courses/lessons/final_test.html',
            **common, daily_lesson=daily_lesson, test_data=test_data,
            next_lesson_url=next_lesson_url, has_next_lesson=has_next_lesson,
        )

    if lesson_type == 'mixed_practice':
        return render_template('curriculum/book_courses/lessons/text.html', **common)

    return render_template('curriculum/book_courses/lessons/text.html', **common)


@book_courses_bp.route('/book-courses/<int:course_id>/modules/<int:module_id>/lessons/<int:lesson_number>')
@login_required
def view_lesson(course_id, module_id, lesson_number):
    """Display specific lesson within a module"""
    try:
        ctx = _prepare_lesson_context(course_id, module_id, lesson_number=lesson_number)
        if ctx is None:
            return redirect(url_for('book_courses.view_course', course_id=course_id))
        return _render_lesson_by_type(ctx)
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
        daily_lesson = DailyLesson.query.get_or_404(lesson_id)
        if daily_lesson.book_course_module_id != module_id:
            abort(404)
        ctx = _prepare_lesson_context(course_id, module_id, daily_lesson=daily_lesson)
        if ctx is None:
            return redirect(url_for('book_courses.view_course', course_id=course_id))
        return _render_lesson_by_type(ctx)
    except Exception as e:
        logger.error(f"Error viewing lesson by id {lesson_id}: {str(e)}")
        flash('Ошибка при загрузке урока', 'error')
        return redirect(url_for('book_courses.view_module',
                                course_id=course_id, module_id=module_id))


@book_courses_bp.route('/courses/<course_slug>')
@login_required
def view_course_by_slug(course_slug):
    course = get_course_by_slug_or_id(course_slug)
    return view_course(course.id)


@book_courses_bp.route('/courses/<course_slug>/enroll', methods=['POST'])
@login_required
def enroll_by_slug(course_slug):
    course = get_course_by_slug_or_id(course_slug)
    return enroll_in_course(course.id)


@book_courses_bp.route('/courses/<course_slug>/modules/<int:module_number>')
@login_required
def view_module_by_slug(course_slug, module_number):
    course = get_course_by_slug_or_id(course_slug)
    module = BookCourseModule.query.filter_by(
        course_id=course.id, module_number=module_number
    ).first_or_404()
    return view_module(course.id, module.id)


@book_courses_bp.route('/courses/<course_slug>/modules/<int:module_number>/lessons/<int:lesson_number>')
@login_required
def view_lesson_by_slug(course_slug, module_number, lesson_number):
    course = get_course_by_slug_or_id(course_slug)
    module = BookCourseModule.query.filter_by(
        course_id=course.id, module_number=module_number
    ).first_or_404()

    all_lessons = DailyLesson.query.filter_by(
        book_course_module_id=module.id
    ).order_by(*LESSON_ORDER).all()

    if lesson_number < 1 or lesson_number > len(all_lessons):
        abort(404)

    daily_lesson = all_lessons[lesson_number - 1]
    return view_lesson_by_id(course.id, module.id, daily_lesson.id)


import app.curriculum.routes.book_courses_api  # noqa: E402, F401
