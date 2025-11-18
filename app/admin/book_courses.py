# app/admin/book_courses.py

"""
Административная панель для управления курсами-книгами (Book Courses)
"""

import json
import logging
from datetime import UTC, datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for, abort
from flask_login import current_user, login_required
from sqlalchemy import desc, func, and_, or_
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from app.utils.db import db
from app.utils.decorators import admin_required
from app.books.models import Book, Chapter
from app.curriculum.book_courses import BookCourse, BookCourseModule, BookCourseEnrollment, BookModuleProgress
from app.curriculum.daily_lessons import DailyLesson, SliceVocabulary, UserLessonProgress

logger = logging.getLogger(__name__)

try:
    from app.curriculum.services.book_course_generator import BookCourseGenerator
except ImportError:
    logger.warning("BookCourseGenerator not available")
    BookCourseGenerator = None

# Import handle_admin_errors from admin.routes
def handle_admin_errors(return_json=True):
    """Декоратор для обработки ошибок в админ операциях"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {str(e)}", exc_info=True)
                
                # Откатываем изменения в базе данных
                try:
                    db.session.rollback()
                except:
                    pass
                
                if return_json:
                    return jsonify({
                        'success': False,
                        'error': f'Внутренняя ошибка сервера: {str(e)}',
                        'operation': func.__name__
                    }), 500
                else:
                    flash(f'Ошибка в операции {func.__name__}: {str(e)}', 'danger')
                    return redirect(url_for('admin.dashboard'))
        return wrapper
    return decorator

def get_difficulty_score(level):
    """Get difficulty score based on CEFR level"""
    scores = {
        'A1': 2.0, 'A2': 3.5, 'B1': 5.0, 
        'B2': 6.5, 'C1': 8.0, 'C2': 9.5
    }
    return scores.get(level, 5.0)

# Simple in-memory cache for statistics
_cache = {}
_cache_timeout = 300  # 5 minutes


def cache_result(key, timeout=_cache_timeout):
    """Decorator for caching function results"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{key}_{hash(str(args) + str(kwargs))}"

            # Check cache
            if cache_key in _cache:
                cached_data, cached_time = _cache[cache_key]
                if (datetime.now() - cached_time).seconds < timeout:
                    return cached_data

            # Execute function and cache result
            result = func(*args, **kwargs)
            _cache[cache_key] = (result, datetime.now())

            return result

        return wrapper

    return decorator


def handle_admin_errors(return_json=True):
    """Decorator for handling admin operation errors"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {str(e)}", exc_info=True)

                if return_json:
                    return jsonify({
                        'success': False,
                        'error': str(e)
                    }), 500
                else:
                    flash(f'Ошибка: {str(e)}', 'danger')
                    return redirect(url_for('admin.book_courses'))

        return wrapper

    return decorator


# Register blueprint from main admin routes
def register_book_course_routes(admin_bp):
    """Register book course routes to the main admin blueprint"""
    
    logger.info("[BOOK_COURSE_ROUTES] Registering book course routes")

    # ====================
    # MAIN ROUTES
    # ====================

    @admin_bp.route('/book-courses')
    @admin_required
    @handle_admin_errors(return_json=False)
    def book_courses():
        """Main book courses management page"""

        # Get all book courses with statistics
        courses = db.session.query(
            BookCourse,
            func.count(BookCourseEnrollment.id).label('total_enrollments'),
            func.count(BookCourseModule.id).label('total_modules')
        ).outerjoin(
            BookCourseEnrollment, BookCourse.id == BookCourseEnrollment.course_id
        ).outerjoin(
            BookCourseModule, BookCourse.id == BookCourseModule.course_id
        ).group_by(BookCourse.id).order_by(desc(BookCourse.created_at)).all()

        # Get all books that can become courses
        available_books = Book.query.filter(
            ~Book.id.in_(
                db.session.query(BookCourse.book_id).distinct()
            )
        ).order_by(Book.title).all()

        # Course statistics
        stats = {
            'total_courses': BookCourse.query.count(),
            'active_courses': BookCourse.query.filter_by(is_active=True).count(),
            'featured_courses': BookCourse.query.filter_by(is_featured=True).count(),
            'total_enrollments': BookCourseEnrollment.query.count(),
            'total_modules': BookCourseModule.query.count(),
            'total_daily_lessons': DailyLesson.query.count()
        }

        return render_template(
            'admin/book_courses/list.html',
            courses=courses,
            available_books=available_books,
            stats=stats
        )

    @admin_bp.route('/book-courses/create')
    @admin_required
    @handle_admin_errors(return_json=False)
    def create_book_course():
        """Create new book course page"""

        # Get available books (not yet converted to courses)
        available_books = Book.query.filter(
            ~Book.id.in_(
                db.session.query(BookCourse.book_id).distinct()
            )
        ).order_by(Book.title).all()

        return render_template(
            'admin/book_courses/create.html',
            available_books=available_books
        )

    @admin_bp.route('/book-courses/create', methods=['POST'])
    @admin_required
    def create_book_course_post():
        """Process book course creation"""
        
        logger.info("[BOOK_COURSE] POST /book-courses/create endpoint called")
        logger.info(f"[BOOK_COURSE] Request method: {request.method}")
        logger.info(f"[BOOK_COURSE] Request content type: {request.content_type}")
        logger.info(f"[BOOK_COURSE] Request headers: {dict(request.headers)}")

        try:
            logger.info(f"[BOOK_COURSE] Starting course creation. Form data: {dict(request.form)}")
            
            # Get form data
            book_id = request.form.get('book_id', type=int)
            course_title = request.form.get('course_title', '').strip()
            course_description = request.form.get('course_description', '').strip()
            level = request.form.get('level', 'B1')
            is_featured = request.form.get('is_featured') == 'on'
            auto_generate = request.form.get('auto_generate') == 'on'

            logger.info(f"[BOOK_COURSE] Parsed data: book_id={book_id}, title='{course_title}', level={level}, auto_generate={auto_generate}")

            # Validation
            if not book_id:
                logger.warning("[BOOK_COURSE] Validation failed: no book_id")
                return jsonify({'success': False, 'error': 'Выберите книгу'}), 400

            book = Book.query.get_or_404(book_id)
            logger.info(f"[BOOK_COURSE] Found book: {book.title}")

            # Check if course already exists
            existing_course = BookCourse.query.filter_by(book_id=book_id).first()
            if existing_course:
                logger.warning(f"[BOOK_COURSE] Course already exists for book {book_id}")
                return jsonify({
                    'success': False,
                    'error': f'Курс для книги "{book.title}" уже существует'
                }), 400

            if not course_title:
                course_title = f"English Course: {book.title}"
                logger.info(f"[BOOK_COURSE] Generated title: {course_title}")

            if not course_description:
                course_description = f"Learn English through reading {book.title}"
                logger.info(f"[BOOK_COURSE] Generated description: {course_description}")

            if not BookCourseGenerator:
                logger.error("[BOOK_COURSE] BookCourseGenerator not available")
                return jsonify({
                    'success': False,
                    'error': 'Генератор курсов недоступен'
                }), 500

            # Create course using BookCourseGenerator
            logger.info(f"[BOOK_COURSE] Creating generator for book {book_id}")
            generator = BookCourseGenerator(book_id)

            if auto_generate:
                logger.info("[BOOK_COURSE] Starting automatic course generation")
                # Full automatic generation
                course = generator.create_course_from_book(
                    course_title=course_title,
                    course_description=course_description,
                    level=level
                )

                if not course:
                    logger.error("[BOOK_COURSE] Course generation failed")
                    return jsonify({
                        'success': False,
                        'error': 'Ошибка при генерации курса'
                    }), 500

                # Set featured status
                course.is_featured = is_featured
                db.session.commit()

                logger.info(f"[BOOK_COURSE] Course created successfully: {course.id}")
                flash(f'Курс "{course_title}" успешно создан и сгенерирован!', 'success')
                return jsonify({
                    'success': True,
                    'message': f'Курс "{course_title}" успешно создан!',
                    'course_id': course.id,
                    'redirect_url': url_for('admin.view_book_course', course_id=course.id)
                })
            else:
                logger.info("[BOOK_COURSE] Creating manual course structure")
                # Manual course creation (just structure)
                course = BookCourse(
                    book_id=book_id,
                    title=course_title,
                    description=course_description,
                    level=level,
                    is_featured=is_featured,
                    is_active=False  # Inactive until manually configured
                )

                db.session.add(course)
                db.session.commit()

                logger.info(f"[BOOK_COURSE] Manual course structure created: {course.id}")
                flash(f'Структура курса "{course_title}" создана. Настройте модули.', 'info')
                return jsonify({
                    'success': True,
                    'message': f'Структура курса "{course_title}" создана!',
                    'course_id': course.id,
                    'redirect_url': url_for('admin.view_book_course', course_id=course.id)
                })

        except Exception as e:
            logger.error(f"[BOOK_COURSE] Exception in create_book_course_post: {str(e)}", exc_info=True)
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': f'Ошибка при создании курса: {str(e)}'
            }), 500

    @admin_bp.route('/book-courses/<int:course_id>')
    @admin_required
    @handle_admin_errors(return_json=False)
    def view_book_course(course_id):
        """View and manage specific book course"""

        course = BookCourse.query.get_or_404(course_id)

        # Get course modules with statistics
        modules_query = db.session.query(
            BookCourseModule,
            func.count(DailyLesson.id).label('daily_lessons_count')
        ).outerjoin(
            DailyLesson, BookCourseModule.id == DailyLesson.book_course_module_id
        ).filter(
            BookCourseModule.course_id == course_id
        ).group_by(BookCourseModule.id).order_by(BookCourseModule.order_index).all()
        
        # Convert to list of modules with stats
        modules = []
        for module_obj, lessons_count in modules_query:
            module_obj.daily_lessons_count = lessons_count
            modules.append(module_obj)

        # Get enrollments with user info
        enrollments = BookCourseEnrollment.query.filter_by(
            course_id=course_id
        ).options(
            joinedload(BookCourseEnrollment.user)
        ).order_by(desc(BookCourseEnrollment.enrolled_at)).limit(20).all()

        # Course statistics
        stats = {
            'total_enrollments': BookCourseEnrollment.query.filter_by(course_id=course_id).count(),
            'active_enrollments': BookCourseEnrollment.query.filter_by(
                course_id=course_id, status='active'
            ).count(),
            'completed_enrollments': BookCourseEnrollment.query.filter_by(
                course_id=course_id, status='completed'
            ).count(),
            'total_modules': len(modules),
            'total_daily_lessons': sum(m.daily_lessons_count for m in modules),
            'avg_progress': db.session.query(
                func.avg(BookCourseEnrollment.progress_percentage)
            ).filter_by(course_id=course_id).scalar() or 0
        }

        return render_template(
            'admin/book_courses/detail.html',
            course=course,
            modules=modules,
            enrollments=enrollments,
            stats=stats
        )

    @admin_bp.route('/book-courses/<int:course_id>/edit')
    @admin_required
    @handle_admin_errors(return_json=False)
    def edit_book_course(course_id):
        """Edit book course settings"""

        course = BookCourse.query.get_or_404(course_id)

        return render_template(
            'admin/book_courses/edit.html',
            course=course
        )

    @admin_bp.route('/book-courses/<int:course_id>/edit', methods=['POST'])
    @admin_required
    @handle_admin_errors(return_json=True)
    def edit_book_course_post(course_id):
        """Update book course settings"""

        course = BookCourse.query.get_or_404(course_id)

        try:
            # Update course data
            course.title = request.form.get('title', course.title).strip()
            course.description = request.form.get('description', course.description).strip()
            course.level = request.form.get('level', course.level)
            course.is_active = request.form.get('is_active') == 'on'
            course.is_featured = request.form.get('is_featured') == 'on'
            course.requires_prerequisites = request.form.get('requires_prerequisites') == 'on'

            course.updated_at = datetime.now(UTC)

            db.session.commit()

            flash(f'Курс "{course.title}" успешно обновлен!', 'success')
            return jsonify({
                'success': True,
                'message': 'Курс успешно обновлен!',
                'redirect_url': url_for('admin.view_book_course', course_id=course_id)
            })

        except Exception as e:
            logger.error(f"Error updating course {course_id}: {str(e)}", exc_info=True)
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': f'Ошибка при обновлении курса: {str(e)}'
            }), 500

    @admin_bp.route('/book-courses/<int:course_id>/delete', methods=['POST'])
    @admin_required
    @handle_admin_errors(return_json=True)
    def delete_book_course(course_id):
        """Delete a specific book course"""
        
        course = BookCourse.query.get_or_404(course_id)
        delete_type = request.form.get('delete_type', 'soft')  # 'soft' or 'hard'
        
        try:
            if delete_type == 'hard':
                # Physical deletion
                logger.info(f"Hard deleting course {course_id}: {course.title}")
                
                # Delete related data in proper order
                # Delete user lesson progress
                UserLessonProgress.query.filter(
                    UserLessonProgress.daily_lesson_id.in_(
                        db.session.query(DailyLesson.id).filter(
                            DailyLesson.book_course_module_id.in_(
                                [m.id for m in course.modules]
                            )
                        )
                    )
                ).delete(synchronize_session=False)
                
                # Delete slice vocabulary
                SliceVocabulary.query.filter(
                    SliceVocabulary.daily_lesson_id.in_(
                        db.session.query(DailyLesson.id).filter(
                            DailyLesson.book_course_module_id.in_(
                                [m.id for m in course.modules]
                            )
                        )
                    )
                ).delete(synchronize_session=False)
                
                # Delete daily lessons
                DailyLesson.query.filter(
                    DailyLesson.book_course_module_id.in_(
                        [m.id for m in course.modules]
                    )
                ).delete(synchronize_session=False)
                
                # Delete module progress
                BookModuleProgress.query.filter(
                    BookModuleProgress.module_id.in_(
                        [m.id for m in course.modules]
                    )
                ).delete(synchronize_session=False)
                
                # Delete enrollments
                BookCourseEnrollment.query.filter_by(course_id=course.id).delete()
                
                # Delete modules
                BookCourseModule.query.filter_by(course_id=course.id).delete()
                
                # Delete the course itself
                course_title = course.title
                db.session.delete(course)
                db.session.commit()
                
                logger.info(f"Successfully deleted course {course_id}: {course_title}")
                flash(f'Курс "{course_title}" полностью удален!', 'success')
                
                return jsonify({
                    'success': True,
                    'message': f'Курс "{course_title}" полностью удален!',
                    'redirect_url': url_for('admin.book_courses')
                })
                
            else:
                # Soft deletion - just deactivate
                course.is_active = False
                course.updated_at = datetime.now(timezone.utc)
                db.session.commit()
                
                flash(f'Курс "{course.title}" деактивирован!', 'info')
                return jsonify({
                    'success': True,
                    'message': f'Курс "{course.title}" деактивирован!',
                    'redirect_url': url_for('admin.view_book_course', course_id=course_id)
                })
                
        except Exception as e:
            logger.error(f"Error deleting course {course_id}: {str(e)}", exc_info=True)
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': f'Ошибка при удалении курса: {str(e)}'
            }), 500

    # ====================
    # MODULE MANAGEMENT
    # ====================

    @admin_bp.route('/book-courses/<int:course_id>/modules/<int:module_id>')
    @admin_required
    @handle_admin_errors(return_json=False)
    def view_course_module(course_id, module_id):
        """View specific course module with daily lessons"""

        course = BookCourse.query.get_or_404(course_id)
        module = BookCourseModule.query.filter_by(
            id=module_id, course_id=course_id
        ).first_or_404()

        # Get daily lessons for this module
        daily_lessons = DailyLesson.query.filter_by(
            book_course_module_id=module_id
        ).order_by(DailyLesson.day_number).all()

        # Get vocabulary statistics
        vocab_stats = db.session.query(
            func.count(SliceVocabulary.id).label('total_vocab_words')
        ).join(
            DailyLesson, SliceVocabulary.daily_lesson_id == DailyLesson.id
        ).filter(
            DailyLesson.book_course_module_id == module_id
        ).first()

        # Get user progress for this module
        user_progress = BookModuleProgress.query.filter_by(
            module_id=module_id
        ).options(
            joinedload(BookModuleProgress.enrollment).joinedload(BookCourseEnrollment.user)
        ).order_by(desc(BookModuleProgress.started_at)).limit(10).all()

        return render_template(
            'admin/book_courses/module_detail.html',
            course=course,
            module=module,
            daily_lessons=daily_lessons,
            vocab_stats=vocab_stats,
            user_progress=user_progress
        )

    @admin_bp.route('/book-courses/<int:course_id>/generate-modules', methods=['POST'])
    @admin_required
    @handle_admin_errors(return_json=True)
    def generate_course_modules(course_id):
        """Generate modules and daily lessons for course"""

        course = BookCourse.query.get_or_404(course_id)

        try:
            if not BookCourseGenerator:
                return jsonify({
                    'success': False,
                    'error': 'Генератор курсов недоступен'
                }), 500

            # Use BookCourseGenerator to generate modules
            generator = BookCourseGenerator(course.book_id)
            generator.course = course  # Use existing course

            # Generate modules and daily slices
            generator._create_course_modules()
            generator._generate_daily_slices()

            # Update course status
            course.is_active = True
            course.updated_at = datetime.now(UTC)

            db.session.commit()

            # Get updated module count
            module_count = BookCourseModule.query.filter_by(course_id=course_id).count()
            lesson_count = DailyLesson.query.join(BookCourseModule).filter(
                BookCourseModule.course_id == course_id
            ).count()

            flash(f'Сгенерировано {module_count} модулей и {lesson_count} уроков!', 'success')
            return jsonify({
                'success': True,
                'message': f'Сгенерировано {module_count} модулей и {lesson_count} уроков!',
                'module_count': module_count,
                'lesson_count': lesson_count
            })

        except Exception as e:
            logger.error(f"Error generating modules for course {course_id}: {str(e)}", exc_info=True)
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': f'Ошибка при генерации модулей: {str(e)}'
            }), 500

    # ====================
    # STATISTICS & ANALYTICS
    # ====================

    @admin_bp.route('/book-courses/analytics')
    @admin_required
    @handle_admin_errors(return_json=False)
    def book_courses_analytics():
        """Book courses analytics and statistics"""

        # Overall statistics
        total_courses = BookCourse.query.count()
        active_courses = BookCourse.query.filter_by(is_active=True).count()
        total_enrollments = BookCourseEnrollment.query.count()

        # Enrollment trends (last 30 days)
        thirty_days_ago = datetime.now(UTC) - timedelta(days=30)
        daily_enrollments = db.session.query(
            func.date(BookCourseEnrollment.enrolled_at).label('date'),
            func.count(BookCourseEnrollment.id).label('count')
        ).filter(
            BookCourseEnrollment.enrolled_at >= thirty_days_ago
        ).group_by(
            func.date(BookCourseEnrollment.enrolled_at)
        ).order_by('date').all()

        # Most popular courses
        popular_courses = db.session.query(
            BookCourse,
            func.count(BookCourseEnrollment.id).label('enrollment_count'),
            func.avg(BookCourseEnrollment.progress_percentage).label('avg_progress')
        ).outerjoin(
            BookCourseEnrollment, BookCourse.id == BookCourseEnrollment.course_id
        ).group_by(BookCourse.id).order_by(
            desc('enrollment_count')
        ).limit(10).all()

        # User engagement
        engagement_stats = db.session.query(
            func.avg(BookCourseEnrollment.progress_percentage).label('avg_progress'),
            func.count(
                BookCourseEnrollment.id.distinct()
            ).filter(
                BookCourseEnrollment.progress_percentage > 50
            ).label('above_50_percent'),
            func.count(
                BookCourseEnrollment.id.distinct()
            ).filter(
                BookCourseEnrollment.status == 'completed'
            ).label('completed_courses')
        ).first()

        return render_template(
            'admin/book_courses/analytics.html',
            total_courses=total_courses,
            active_courses=active_courses,
            total_enrollments=total_enrollments,
            daily_enrollments=daily_enrollments,
            popular_courses=popular_courses,
            engagement_stats=engagement_stats
        )

    # ====================
    # BULK OPERATIONS
    # ====================

    @admin_bp.route('/book-courses/bulk-operations', methods=['POST'])
    @admin_required
    @handle_admin_errors(return_json=True)
    def bulk_course_operations():
        """Perform bulk operations on courses"""

        operation = request.form.get('operation')
        course_ids = request.form.getlist('course_ids', type=int)

        if not course_ids:
            return jsonify({'success': False, 'error': 'Выберите курсы'}), 400

        try:
            courses = BookCourse.query.filter(BookCourse.id.in_(course_ids)).all()

            if operation == 'activate':
                for course in courses:
                    course.is_active = True
                message = f'Активировано {len(courses)} курсов'

            elif operation == 'deactivate':
                for course in courses:
                    course.is_active = False
                message = f'Деактивировано {len(courses)} курсов'

            elif operation == 'feature':
                for course in courses:
                    course.is_featured = True
                message = f'Добавлено в рекомендуемые {len(courses)} курсов'

            elif operation == 'unfeature':
                for course in courses:
                    course.is_featured = False
                message = f'Убрано из рекомендуемых {len(courses)} курсов'

            elif operation == 'delete':
                # Soft delete - deactivate instead
                for course in courses:
                    course.is_active = False
                message = f'Деактивировано {len(courses)} курсов'
                
            elif operation == 'delete_permanently':
                # Hard delete - physically remove from database
                deleted_count = 0
                for course in courses:
                    try:
                        # Delete related data first
                        # Delete daily lessons and their vocabulary
                        DailyLesson.query.filter(
                            DailyLesson.book_course_module_id.in_(
                                [m.id for m in course.modules]
                            )
                        ).delete(synchronize_session=False)
                        
                        # Delete module progress
                        BookModuleProgress.query.filter(
                            BookModuleProgress.module_id.in_(
                                [m.id for m in course.modules]
                            )
                        ).delete(synchronize_session=False)
                        
                        # Delete enrollments
                        BookCourseEnrollment.query.filter_by(course_id=course.id).delete()
                        
                        # Delete modules
                        BookCourseModule.query.filter_by(course_id=course.id).delete()
                        
                        # Delete the course itself
                        db.session.delete(course)
                        deleted_count += 1
                        
                    except Exception as e:
                        logger.error(f"Error deleting course {course.id}: {str(e)}")
                        
                message = f'Полностью удалено {deleted_count} курсов'

            else:
                return jsonify({'success': False, 'error': 'Неизвестная операция'}), 400

            db.session.commit()

            return jsonify({
                'success': True,
                'message': message
            })

        except Exception as e:
            logger.error(f"Error in bulk course operation: {str(e)}", exc_info=True)
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': f'Ошибка при выполнении операции: {str(e)}'
            }), 500


# Cache statistics for performance
@cache_result('book_course_stats', timeout=300)  # 5 minutes cache
def get_book_course_statistics():
    """Get cached book course statistics"""

    stats = {
        'total_courses': BookCourse.query.count(),
        'active_courses': BookCourse.query.filter_by(is_active=True).count(),
        'featured_courses': BookCourse.query.filter_by(is_featured=True).count(),
        'total_enrollments': BookCourseEnrollment.query.count(),
        'active_enrollments': BookCourseEnrollment.query.filter_by(status='active').count(),
        'completed_enrollments': BookCourseEnrollment.query.filter_by(status='completed').count(),
        'total_modules': BookCourseModule.query.count(),
        'total_daily_lessons': DailyLesson.query.count(),
        'total_vocabulary_words': SliceVocabulary.query.count()
    }

    return stats
