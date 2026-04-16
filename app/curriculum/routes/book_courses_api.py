import logging
import re
from datetime import UTC, datetime

from flask import current_app, jsonify, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified

from app.curriculum.book_courses import (
    BookCourse, BookCourseEnrollment, BookCourseModule, BookModuleProgress,
)
from app.curriculum.daily_lessons import DailyLesson, SliceVocabulary
from app.curriculum.routes.book_courses import book_courses_bp
from app.curriculum.routes.book_courses_service import truncate_context
from app.curriculum.services.book_srs_integration import BookSRSIntegration
from app.utils.db import db

logger = logging.getLogger(__name__)


@book_courses_bp.route('/api/v1/lesson/<int:lesson_id>')
@login_required
def get_lesson_api(lesson_id):
    """Get lesson data according to specification"""
    try:
        daily_lesson = DailyLesson.query.get(lesson_id)
        if not daily_lesson:
            return jsonify({'error': 'Not found'}), 404

        module = BookCourseModule.query.get(daily_lesson.book_course_module_id)
        if not module:
            return jsonify({'error': 'Not found'}), 404

        enrollment = BookCourseEnrollment.query.filter_by(
            course_id=module.course_id,
            user_id=current_user.id
        ).first()

        if not enrollment:
            return jsonify({'error': 'Not found'}), 404

        lesson_type = daily_lesson.lesson_type

        if lesson_type == 'vocabulary':
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
            slice_vocab = SliceVocabulary.query.filter_by(
                daily_lesson_id=daily_lesson.id
            ).options(joinedload(SliceVocabulary.word)).all()

            tooltip_map = {}

            if not slice_vocab:
                from app.books.models import BlockVocab
                from app.words.models import CollectionWords as CW

                module = BookCourseModule.query.get(daily_lesson.book_course_module_id)
                if module and module.block_id:
                    block_vocab = (db.session.query(BlockVocab, CW)
                                   .join(CW, BlockVocab.word_id == CW.id)
                                   .filter(BlockVocab.block_id == module.block_id)
                                   .order_by(BlockVocab.freq.desc())
                                   .limit(50)
                                   .all())

                    text_lower = (daily_lesson.slice_text or '').lower()
                    for bv, word in block_vocab:
                        word_lower = word.english_word.lower()
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

            html_text = daily_lesson.slice_text or ''
            html_text = html_text.replace('\\n', '\n')
            html_text = html_text.replace('\r\n', '\n')

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

                highlighted_paragraph = paragraph
                for lemma in tooltip_map:
                    pattern = r'\b(' + re.escape(lemma) + r')\b'
                    highlighted_paragraph = re.sub(
                        pattern,
                        lambda m, l=lemma: f'<span class="word" data-lemma="{l}">{m.group(1)}</span>',
                        highlighted_paragraph,
                        flags=re.IGNORECASE
                    )

                html_paragraphs.append(
                    f'<p data-paragraph-index="{idx}">{highlighted_paragraph}</p>'
                )

            if not html_paragraphs and html_text.strip():
                html_paragraphs = [f'<p>{html_text.strip()}</p>']

            final_html = '\n'.join(html_paragraphs)

            audio_url = daily_lesson.audio_url
            if not audio_url and daily_lesson.chapter_id:
                from app.books.models import Chapter
                chapter = Chapter.query.get(daily_lesson.chapter_id)
                if chapter and chapter.audio_url:
                    audio_url = url_for('books_api.serve_chapter_audio',
                                        book_id=chapter.book_id,
                                        chapter_num=chapter.chap_num)

            return jsonify({
                'html': final_html,
                'tooltip_map': tooltip_map,
                'word_count': daily_lesson.word_count,
                'title': f'Чтение — День {daily_lesson.day_number}',
                'audio_url': audio_url
            })

        else:
            return jsonify({'error': 'Lesson type not supported'}), 400

    except Exception as e:
        logger.error(f"Error getting lesson {lesson_id}: {str(e)}")
        return jsonify({'error': 'Server error'}), 500


@book_courses_bp.route('/api/v1/lesson/<int:lesson_id>/progress', methods=['GET', 'POST'])
@login_required
def lesson_progress_api(lesson_id):
    """Save/load reading progress and self-check answers for a lesson."""
    try:
        from app.curriculum.daily_lessons import UserLessonProgress

        daily_lesson = DailyLesson.query.get(lesson_id)
        if not daily_lesson:
            return jsonify({'error': 'Not found'}), 404

        module = BookCourseModule.query.get(daily_lesson.book_course_module_id)
        if not module:
            return jsonify({'error': 'Not found'}), 404

        enrollment = BookCourseEnrollment.query.filter_by(
            course_id=module.course_id,
            user_id=current_user.id
        ).first()
        if not enrollment:
            return jsonify({'error': 'Not found'}), 404

        progress = UserLessonProgress.query.filter_by(
            user_id=current_user.id,
            daily_lesson_id=lesson_id,
            enrollment_id=enrollment.id
        ).first()

        if request.method == 'GET':
            if progress and progress.lesson_data:
                return jsonify(progress.lesson_data)
            return jsonify({})

        data = request.get_json(silent=True) or {}

        if not progress:
            progress = UserLessonProgress(
                user_id=current_user.id,
                daily_lesson_id=lesson_id,
                enrollment_id=enrollment.id,
                status='in_progress',
                started_at=datetime.now(UTC)
            )
            db.session.add(progress)

        lesson_data = dict(progress.lesson_data or {})
        if 'reading_progress' in data:
            lesson_data['reading_progress'] = min(int(data['reading_progress']), 100)
        if 'self_check' in data:
            lesson_data['self_check'] = data['self_check']

        progress.lesson_data = lesson_data
        flag_modified(progress, 'lesson_data')
        db.session.commit()

        return jsonify({'ok': True})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error saving lesson progress: {e}')
        return jsonify({'error': 'Server error'}), 500


@book_courses_bp.route('/api/v1/lesson/<int:lesson_id>/complete', methods=['POST'])
@login_required
def complete_lesson_api_v1(lesson_id):
    """Complete lesson according to specification"""
    try:
        from app.curriculum.daily_lessons import UserLessonProgress, LessonCompletionEvent

        daily_lesson = DailyLesson.query.get(lesson_id)
        if not daily_lesson:
            return jsonify({'error': 'Not found'}), 404

        module = BookCourseModule.query.get(daily_lesson.book_course_module_id)
        if not module:
            return jsonify({'error': 'Not found'}), 404

        enrollment = BookCourseEnrollment.query.filter_by(
            course_id=module.course_id,
            user_id=current_user.id
        ).first()

        if not enrollment:
            return jsonify({'error': 'Not found'}), 404

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
                module_progress.status = 'in_progress'

        completion_event = LessonCompletionEvent(
            daily_lesson_id=lesson_id,
            user_id=current_user.id,
            event_type='lesson_completed',
            event_data={'lesson_type': daily_lesson.lesson_type}
        )
        db.session.add(completion_event)

        if daily_lesson.lesson_type == 'vocabulary':
            try:
                srs_integration = BookSRSIntegration()
                srs_integration.auto_create_srs_cards_from_vocabulary_lesson(
                    user_id=current_user.id,
                    daily_lesson=daily_lesson
                )
            except Exception as e:
                logger.error(f"Error auto-creating SRS cards: {str(e)}")

        if daily_lesson.lesson_type in ['grammar', 'language_focus']:
            try:
                from app.grammar_lab.models import GrammarTopic, UserGrammarTopicStatus

                topic = None
                task = daily_lesson.task
                if task and getattr(task, 'grammar_topic_id', None):
                    topic = GrammarTopic.query.get(task.grammar_topic_id)

                if not topic:
                    course = BookCourse.query.get(module.course_id)
                    course_level = course.level if course else 'A1'

                    grammar_topics = GrammarTopic.query.filter_by(
                        level=course_level
                    ).order_by(GrammarTopic.order).all()

                    if not grammar_topics:
                        for fallback in ['A1', 'A2', 'B1']:
                            grammar_topics = GrammarTopic.query.filter_by(
                                level=fallback
                            ).order_by(GrammarTopic.order).all()
                            if grammar_topics:
                                break

                    if grammar_topics:
                        grammar_lesson_index = (daily_lesson.day_number - 1) // 6
                        topic = grammar_topics[grammar_lesson_index % len(grammar_topics)]

                if topic:
                    topic_status = UserGrammarTopicStatus.get_or_create(
                        user_id=current_user.id,
                        topic_id=topic.id
                    )
                    topic_status.transition_to('theory_completed')

            except Exception as e:
                logger.error(f"Error syncing grammar with Grammar Lab: {str(e)}")

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

        module_progress.mark_lesson_completed(lesson_number, score)

        try:
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
        except Exception as e:
            logger.error(f"Error auto-creating SRS cards: {str(e)}")

        enrollment.last_activity = datetime.now(UTC)

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
    """Get SRS session for vocabulary lesson."""
    try:
        daily_lesson = DailyLesson.query.get(lesson_id)
        if not daily_lesson:
            return jsonify({'error': 'Not found'}), 404

        module = BookCourseModule.query.get(daily_lesson.book_course_module_id)
        if not module:
            return jsonify({'error': 'Not found'}), 404

        enrollment = BookCourseEnrollment.query.filter_by(
            user_id=current_user.id,
            course_id=module.course_id
        ).first()

        if not enrollment:
            return jsonify({'error': 'Not found'}), 404

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
    """Grade an SRS card."""
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
    """Add a word to user's SRS flashcards."""
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
            return jsonify(result), 400

    except Exception as e:
        logger.error(f"Error adding word to SRS: {str(e)}")
        return jsonify({'success': False, 'error': 'Server error'}), 500
