# app/curriculum/routes/main.py

import logging
from datetime import UTC, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.security import require_lesson_access
from app.utils.db import db

logger = logging.getLogger(__name__)

# Create blueprint for main routes - use curriculum name for compatibility
main_bp = Blueprint('curriculum', __name__)

_CANONICAL_LESSON_ROUTE_TYPES = frozenset({
    'dictation',
    'audio_fill_blank',
    'translation',
    'sentence_correction',
    'writing_prompt',
    'sentence_completion',
    'collocation_matching',
    'shadow_reading',
    'pronunciation',
    'idiom',
})


@main_bp.route('/')
@login_required
def index():
    """Главная страница учебной программы - редирект на /learn/"""
    return redirect('/learn/', code=302)


@main_bp.route('/search')
@login_required
def search():
    """Full-text search over lesson titles and vocabulary words.

    GET /curriculum/search?q=<query>
    Empty query redirects to /learn/.
    """
    from app.words.models import CollectionWords
    from app.grammar_lab.models import GrammarTopic

    q = request.args.get('q', '').strip()[:200]
    if not q:
        return redirect(url_for('learn.learn_index'))

    pattern = f'%{q}%'

    # Search lessons by title (joined with module and level for context)
    lesson_results = (
        Lessons.query
        .join(Module, Lessons.module_id == Module.id)
        .join(CEFRLevel, Module.level_id == CEFRLevel.id)
        .filter(Lessons.title.ilike(pattern))
        .options(
            joinedload(Lessons.module).joinedload(Module.level)
        )
        .order_by(CEFRLevel.order, Module.number, Lessons.number)
        .limit(50)
        .all()
    )

    # Group lessons by module
    modules_map: dict = {}
    for lesson in lesson_results:
        mod = lesson.module
        key = mod.id
        if key not in modules_map:
            modules_map[key] = {
                'module': mod,
                'level_code': mod.level.code,
                'lessons': [],
            }
        modules_map[key]['lessons'].append(lesson)
    lesson_groups = list(modules_map.values())

    # Search vocabulary words by English term
    word_results = (
        CollectionWords.query
        .filter(CollectionWords.english_word.ilike(pattern))
        .order_by(CollectionWords.frequency_rank)
        .limit(30)
        .all()
    )

    # Search grammar topics by title or Russian title
    topic_results = (
        GrammarTopic.query
        .filter(
            GrammarTopic.title.ilike(pattern) | GrammarTopic.title_ru.ilike(pattern)
        )
        .order_by(GrammarTopic.level, GrammarTopic.order)
        .limit(20)
        .all()
    )

    total = len(lesson_results) + len(word_results) + len(topic_results)

    return render_template(
        'curriculum/search.html',
        query=q,
        lesson_groups=lesson_groups,
        word_results=word_results,
        topic_results=topic_results,
        total=total,
    )


# =============================================================================
# НОВЫЕ КРАСИВЫЕ URL МАРШРУТЫ
# =============================================================================

# Создаем новый blueprint для красивых URL
learn_bp = Blueprint('learn', __name__)


@learn_bp.route('/')
@login_required
def learn_index():
    """Главная страница обучения - оптимизированная версия с eager loading"""
    # Pre-select onboarding level on first visit
    onboarding_level = getattr(current_user, 'onboarding_level', None)
    if onboarding_level and not request.args.get('skip_redirect'):
        # Check if user has any completed lessons
        has_progress = LessonProgress.query.filter_by(
            user_id=current_user.id, status='completed'
        ).first()
        if not has_progress:
            level = CEFRLevel.query.filter_by(code=onboarding_level.upper()).first()
            if level:
                return redirect(url_for('learn.learn_level', level_code=level.code))

    try:
        from app.curriculum.services.curriculum_cache_service import CurriculumCacheService

        # Используем оптимизированный сервис - 3 запроса вместо 1000+
        levels_data = CurriculumCacheService.get_levels_with_progress(current_user.id)

        if not levels_data:
            flash('Учебные материалы еще не загружены. Обратитесь к администратору.', 'info')
            return render_template('curriculum/index.html',
                                 levels_data=[],
                                 recent_activity=[],
                                 total_stats={},
                                 gamification={})

        # Рассчитываем общую статистику
        total_stats = {
            'total_lessons': sum(ld['total_lessons'] for ld in levels_data),
            'completed_lessons': sum(ld['completed_lessons'] for ld in levels_data)
        }
        total_stats['progress_percent'] = round(
            (total_stats['completed_lessons'] / total_stats['total_lessons'] * 100)
            if total_stats['total_lessons'] > 0 else 0
        )

        # Получаем последние активности (1 оптимизированный запрос)
        recent_activity = CurriculumCacheService.get_recent_activity(current_user.id, limit=5)

        # Получаем геймификацию (2 оптимизированных запроса)
        gamification = CurriculumCacheService.get_gamification_stats(current_user.id)

        return render_template('curriculum/index.html',
                             levels_data=levels_data,
                             recent_activity=recent_activity,
                             total_stats=total_stats,
                             gamification=gamification)

    except Exception as e:
        logger.error(f"Ошибка загрузки curriculum: {str(e)}")
        flash('Произошла ошибка при загрузке учебной программы.', 'error')
        return render_template('curriculum/index.html',
                             levels_data=[],
                             recent_activity=[],
                             total_stats={},
                             gamification={})






@learn_bp.route('/error-review/', methods=['GET'])
@login_required
def error_review_session():
    """Linear-plan error-review session.

    Renders the unresolved quiz-error pool so the user can review and
    resolve them; the page POSTs to ``/api/daily-plan/error-review/complete``
    to mark them resolved and credit the linear slot XP. Reachable via
    the linear plan 4th baseline slot.
    """
    import re as _re

    def _fill_word(question_text: str, correct_answer: str):
        """Extract the word/phrase that fills ___ from the correct sentence."""
        try:
            # Replace any run of underscores with a capture group after escaping
            blank_re = _re.sub(r'_+', r'(.+?)', _re.escape(question_text.strip()))
            m = _re.match(r'^' + blank_re + r'\s*$', correct_answer.strip(), _re.IGNORECASE)
            if m:
                return m.group(1).strip()
        except Exception:
            pass
        return None

    from app.daily_plan.linear.errors import (
        get_review_pool_grouped,
        get_unresolved_breakdown,
    )

    raw_groups = get_review_pool_grouped(current_user.id, db)
    breakdown = get_unresolved_breakdown(current_user.id, db)
    top_lessons = [
        item for item in breakdown.get('by_lesson', []) if item.get('title')
    ][:3]
    top_topics = [
        item for item in breakdown.get('by_topic', []) if item.get('title')
    ][:3]
    topic_groups = []
    all_error_ids: list[int] = []

    for group in raw_groups:
        topic = group['topic']
        all_error_ids.extend(group['error_ids'])

        # Preprocess topic theory so template stays logic-free
        topic_title = None
        grammar_url = None
        theory_text = None
        common_mistakes = None
        content: dict = {}

        if topic is not None:
            topic_title = topic.title_ru or topic.title
            grammar_url = f'/grammar/{topic.slug}'
            content = topic.content or {}
            if topic.telegram_summary:
                theory_text = topic.telegram_summary
            elif content.get('introduction'):
                theory_text = content['introduction']
            raw_mistakes = content.get('common_mistakes') or []
            if raw_mistakes:
                common_mistakes = raw_mistakes[:2]

        # Fallback: infer grammar topic from the module's grammar/language_focus lesson
        if topic is None:
            module_ids: set[int] = set()
            for e in group['errors']:
                lesson_obj = getattr(e, 'lesson', None)
                if lesson_obj and lesson_obj.module_id:
                    module_ids.add(lesson_obj.module_id)
            for mid in module_ids:
                gl = Lessons.query.filter(
                    Lessons.module_id == mid,
                    Lessons.type.in_(['grammar', 'language_focus']),
                    Lessons.grammar_topic_id.isnot(None),
                ).first()
                if gl and gl.grammar_topic:
                    topic = gl.grammar_topic
                    topic_title = topic.title_ru or topic.title
                    grammar_url = f'/grammar/{topic.slug}'
                    content = topic.content or {}
                    if topic.telegram_summary:
                        theory_text = topic.telegram_summary
                    elif content.get('introduction'):
                        theory_text = content['introduction']
                    raw_mistakes = content.get('common_mistakes') or []
                    if raw_mistakes:
                        common_mistakes = raw_mistakes[:2]
                    break

        # Collect unique lesson titles for the theory card (needed when topic is None)
        lesson_titles: list[str] = []
        seen_lesson_ids: set[int] = set()
        for e in group['errors']:
            lesson_obj = getattr(e, 'lesson', None)
            if lesson_obj and lesson_obj.id not in seen_lesson_ids:
                seen_lesson_ids.add(lesson_obj.id)
                if lesson_obj.title:
                    lesson_titles.append(lesson_obj.title)
        lesson_titles = list(dict.fromkeys(lesson_titles))[:3]

        errors_display = []
        for e in group['errors']:
            p = e.question_payload or {}
            user_ans = p.get('user_answer', '')
            correct_ans = p.get('correct_answer') or ''
            # Skip matching errors with no meaningful data (empty arrows)
            if user_ans == 'completed' and isinstance(correct_ans, str) and '→' in correct_ans:
                pairs = [seg.strip() for seg in correct_ans.split(',')]
                if all(seg in ('→', '') for seg in pairs):
                    continue
            # Format arrow-pair strings (translation/matching) as a list
            formatted_correct = correct_ans
            if isinstance(correct_ans, str) and ' → ' in correct_ans and ',' in correct_ans:
                formatted_correct = [seg.strip() for seg in correct_ans.split(',') if seg.strip()]
            # Extract just the missing word whenever the question has a blank
            fw = None
            q_text = p.get('question_text', '') or ''
            c_str = correct_ans if isinstance(correct_ans, str) else ''
            if '_' in q_text and c_str:
                fw = _fill_word(q_text, c_str)
            errors_display.append({
                'id': e.id,
                'payload': {**p, 'correct_answer': formatted_correct, 'fill_word': fw},
            })

        topic_groups.append({
            'topic_title': topic_title,
            'grammar_url': grammar_url,
            'theory_text': theory_text,
            'common_mistakes': common_mistakes,
            'topic_content': content,
            'lesson_titles': lesson_titles,
            'errors': errors_display,
            'error_ids': group['error_ids'],
        })

    return render_template(
        'curriculum/error_review.html',
        topic_groups=topic_groups,
        all_error_ids=all_error_ids,
        total_errors=len(all_error_ids),
        top_lessons=top_lessons,
        top_topics=top_topics,
    )


@learn_bp.route('/<string:level_code>/')
@login_required
def learn_by_level(level_code):
    """Страница уровня: /learn/a1/, /learn/a2/ и т.д."""
    from app.curriculum.services.curriculum_cache_service import CurriculumCacheService

    # Валидация и нормализация кода уровня
    level_code_upper = level_code.upper()
    valid_levels = ['A0', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2']
    if level_code_upper not in valid_levels:
        flash('Уровень не найден', 'error')
        return redirect(url_for('learn.learn_index'))

    # Получаем уровень из БД
    level = CEFRLevel.query.filter_by(code=level_code_upper).first_or_404()

    try:
        # Получаем все данные через существующий сервис и фильтруем
        levels_data = CurriculumCacheService.get_levels_with_progress(current_user.id)
        level_data = next((ld for ld in levels_data if ld['level'].code == level_code_upper), None)

        if not level_data:
            flash('Данные уровня не найдены', 'error')
            return redirect(url_for('learn.learn_index'))

        # Преобразуем данные в формат для шаблона level_modules.html
        modules = [m['module'] for m in level_data['modules']]
        user_module_progress = {
            m['module'].id: {
                'total_lessons': m['total_lessons'],
                'completed_lessons': m['completed_lessons'],
                'progress_percent': m['progress_percent'],
                'percentage': m['progress_percent'],  # alias для шаблона
                'is_accessible': m['is_available'],
                'is_completed': m['progress_percent'] == 100,
                'is_locked': not m['is_available'],
                'is_current': m['is_available'] and m['progress_percent'] > 0 and m['progress_percent'] < 100
            }
            for m in level_data['modules']
        }

        level_stats = {
            'total_lessons': level_data['total_lessons'],
            'completed_lessons': level_data['completed_lessons'],
            'progress_percent': level_data['progress_percent'],
            'total_modules': len(modules),
            'completed_modules': sum(1 for m in level_data['modules'] if m['progress_percent'] == 100),
            'estimated_hours': level_data.get('estimated_time', 0) // 60
        }

        # Находим следующий урок
        next_lesson_info = None
        if level_data.get('next_lesson'):
            next_lesson_info = {'lesson': level_data['next_lesson']}

        return render_template('curriculum/level_modules.html',
                             level=level,
                             modules=modules,
                             user_module_progress=user_module_progress,
                             level_stats=level_stats,
                             next_lesson_info=next_lesson_info)

    except Exception as e:
        logger.error(f"Ошибка загрузки уровня {level_code}: {str(e)}")
        flash('Произошла ошибка при загрузке уровня.', 'error')
        return redirect(url_for('learn.learn_index'))


@learn_bp.route('/<string:level_code>/module-<int:module_number>/')
@login_required
def learn_by_module(level_code, module_number):
    """Страница модуля: /learn/a1/module-1/ - показывает список уроков модуля"""
    # Валидация уровня
    level_code_upper = level_code.upper()
    if not CEFRLevel.query.filter_by(code=level_code_upper).first():
        abort(404)

    # Находим модуль — eager-load lessons to avoid lazy N+1 on module.lessons
    module = Module.query.options(joinedload(Module.lessons)).join(CEFRLevel).filter(
        CEFRLevel.code == level_code_upper,
        Module.number == module_number
    ).first_or_404()

    # Сортируем уроки по номеру
    sorted_lessons = sorted(module.lessons, key=lambda l: l.number)

    if not sorted_lessons:
        flash('В модуле нет уроков', 'info')
        return redirect(url_for('learn.learn_by_level', level_code=level_code))

    # Получаем прогресс пользователя по урокам этого модуля
    lesson_ids = [l.id for l in sorted_lessons]
    user_progress = LessonProgress.query.filter(
        LessonProgress.user_id == current_user.id,
        LessonProgress.lesson_id.in_(lesson_ids)
    ).all()

    # Создаём словарь прогресса
    user_lesson_progress = {p.lesson_id: p for p in user_progress}

    # Module-level access info (prerequisite module name + required score)
    module_lock_reason = None
    if module.number > 1:
        prev_module = Module.query.filter_by(
            level_id=module.level_id, number=module.number - 1
        ).first()
        if prev_module:
            from app.curriculum.security import check_module_access
            if not check_module_access(module.id):
                total = Lessons.query.filter_by(module_id=prev_module.id).count()
                completed = LessonProgress.query.filter_by(
                    user_id=current_user.id, status='completed'
                ).join(Lessons).filter(Lessons.module_id == prev_module.id).count()
                pct = round(completed / total * 100) if total > 0 else 0
                module_lock_reason = {
                    'prev_module_title': prev_module.title,
                    'prev_module_number': prev_module.number,
                    'required_pct': 80,
                    'current_pct': pct,
                }

    return render_template(
        'curriculum/module_lessons.html',
        module=module,
        lessons=sorted_lessons,
        user_lesson_progress=user_lesson_progress,
        module_lock_reason=module_lock_reason,
    )


@learn_bp.route('/<int:lesson_id>/', methods=['GET', 'POST'])
@login_required
@require_lesson_access
def lesson_by_id(lesson_id):
    """Прямой рендер урока: /learn/{lesson_id}/"""
    from app.curriculum.routes.vocabulary_lessons import (
        render_vocabulary_lesson, render_matching_lesson, render_text_lesson,
    )
    from app.curriculum.routes.grammar_quiz_lessons import (
        render_grammar_lesson, render_quiz_lesson, render_final_test_lesson,
    )
    from app.curriculum.routes.card_lessons import render_card_lesson

    lesson = Lessons.query.get_or_404(lesson_id)
    if lesson.type in _CANONICAL_LESSON_ROUTE_TYPES:
        return redirect(url_for('curriculum_lessons.lesson_detail', lesson_id=lesson.id))

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

    # Маппинг типов уроков на render-функции
    render_map = {
        'vocabulary': render_vocabulary_lesson,
        'flashcards': render_vocabulary_lesson,
        'grammar': render_grammar_lesson,
        'matching': render_matching_lesson,
        'text': render_text_lesson,
        'reading': render_text_lesson,
        'listening_immersion': render_text_lesson,
        'card': render_card_lesson,
        'final_test': render_final_test_lesson,
        # Quiz-based lessons
        'quiz': render_quiz_lesson,
        'ordering_quiz': render_quiz_lesson,
        'translation_quiz': render_quiz_lesson,
        'listening_quiz': render_quiz_lesson,
        'dialogue_completion_quiz': render_quiz_lesson,
        'listening_immersion_quiz': render_text_lesson,
    }

    render_func = render_map.get(lesson.type)
    if not render_func:
        flash(f'Неизвестный тип урока: {lesson.type}', 'error')
        return redirect('/learn/')

    # Validate that lesson has content before rendering (card lessons may use collection_id)
    content_required_types = {'vocabulary', 'flashcards', 'grammar', 'matching', 'text',
                              'reading', 'listening_immersion', 'quiz', 'ordering_quiz',
                              'translation_quiz', 'listening_quiz', 'dialogue_completion_quiz',
                              'listening_immersion_quiz', 'final_test'}
    if lesson.type in content_required_types and not lesson.content:
        logger.warning(f"Lesson {lesson.id} ({lesson.type}) has no content")
        return render_template('curriculum/lessons/empty_content.html', lesson=lesson)

    return render_func(lesson)
