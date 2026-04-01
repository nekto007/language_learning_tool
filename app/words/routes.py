from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy import case, func, or_

from app.study.models import GameScore
from app.utils.db import db
from app.words.forms import WordFilterForm, WordSearchForm
from app.words.models import CollectionWords, Topic
from app.modules.decorators import module_required

words = Blueprint('words', __name__)


@words.route('/dashboard')
@login_required
@module_required('words')
def dashboard():
    """Main dashboard with daily plan, streak and activity summary."""
    from app.study.models import UserWord, Achievement, UserAchievement
    from app.grammar_lab.models import GrammarTopic, UserGrammarTopicStatus
    from app.curriculum.book_courses import BookCourse, BookCourseEnrollment
    from app.telegram.models import TelegramUser
    from app.telegram.queries import get_daily_plan, get_current_streak, get_daily_summary
    from app.telegram.notifications import _lesson_minutes, _words_minutes

    # === DAILY PLAN & STREAK ===
    streak = get_current_streak(current_user.id)
    daily_plan = get_daily_plan(current_user.id)
    daily_summary = get_daily_summary(current_user.id)

    # Time-based greeting
    from datetime import datetime as dt
    import pytz
    try:
        local_hour = dt.now(pytz.timezone('Europe/Moscow')).hour
    except Exception:
        local_hour = dt.utcnow().hour + 3
    if local_hour < 6:
        greeting = 'Доброй ночи'
    elif local_hour < 12:
        greeting = 'Доброе утро'
    elif local_hour < 18:
        greeting = 'Добрый день'
    else:
        greeting = 'Добрый вечер'

    # Yesterday summary
    from app.telegram.queries import get_yesterday_summary
    yesterday_summary = get_yesterday_summary(current_user.id)

    # === PLAN COMPLETION & STREAK ===
    from app.achievements.streak_service import compute_plan_steps, process_streak_on_activity

    plan_completion, steps_available, steps_done, steps_total = compute_plan_steps(daily_plan, daily_summary)

    streak_result = process_streak_on_activity(current_user.id, steps_done, steps_total)
    streak_status = streak_result['streak_status']
    required_steps = streak_result['required_steps']
    streak_repaired = streak_result['streak_repaired']
    streak = streak_status.get('streak', streak)

    # Cards URL (user's default deck or generic)
    cards_url = url_for('study.cards')
    if current_user.default_study_deck_id:
        cards_url = url_for('study.cards_deck', deck_id=current_user.default_study_deck_id)

    # Lesson time estimate
    lesson_minutes = None
    if daily_plan.get('next_lesson'):
        lesson_minutes = _lesson_minutes(daily_plan['next_lesson'].get('lesson_type'))

    words_minutes = _words_minutes(daily_plan.get('words_due', 0))

    # === WORDS STATS ===
    from app.srs.stats_service import srs_stats_service
    _wstats = srs_stats_service.get_words_stats(current_user.id)
    words_stats = {
        'new': _wstats['new_count'],
        'learning': _wstats['learning_count'],
        'review': _wstats['review_count'],
        'mastered': _wstats['mastered_count'],
    }
    words_total = _wstats['total']
    words_in_progress = _wstats['learning_count'] + _wstats['review_count']

    # === BOOKS STATS ===
    books_reading = current_user.get_reading_progress_count() if hasattr(current_user, 'get_reading_progress_count') else 0
    recent_book = None
    if hasattr(current_user, 'get_recent_reading_progress'):
        recent_books = current_user.get_recent_reading_progress(1)
        recent_book = recent_books[0] if recent_books else None

    # === GRAMMAR LAB STATS (single query: total + studied) ===
    grammar_counts = db.session.query(
        func.count(GrammarTopic.id),
        func.count(case(
            (UserGrammarTopicStatus.theory_completed == True, 1),
        ))
    ).select_from(GrammarTopic).outerjoin(
        UserGrammarTopicStatus,
        (UserGrammarTopicStatus.topic_id == GrammarTopic.id) &
        (UserGrammarTopicStatus.user_id == current_user.id)
    ).one()
    grammar_total = grammar_counts[0]
    grammar_studied = grammar_counts[1]
    grammar_mastered = grammar_studied

    # === BOOK COURSES STATS (single query: count + most recent) ===
    active_courses = BookCourseEnrollment.query.filter_by(
        user_id=current_user.id, status='active'
    ).order_by(BookCourseEnrollment.last_activity.desc()).all()
    courses_enrolled = len(active_courses)
    active_course = active_courses[0] if active_courses else None

    # === ACHIEVEMENTS (single query: total + earned) ===
    achievement_counts = db.session.query(
        func.count(Achievement.id),
        func.count(case(
            (UserAchievement.user_id == current_user.id, 1),
        ))
    ).select_from(Achievement).outerjoin(
        UserAchievement,
        (UserAchievement.achievement_id == Achievement.id) &
        (UserAchievement.user_id == current_user.id)
    ).one()
    total_achievements = achievement_counts[0]
    earned_achievements = achievement_counts[1]

    # === DAILY XP (estimated from today's activity) ===
    daily_xp_goal = 100
    today_xp = (
        daily_summary.get('lessons_count', 0) * 30
        + daily_summary.get('grammar_correct', 0) * 10
        + daily_summary.get('srs_words_reviewed', 0) * 5
        + daily_summary.get('book_course_lessons_today', 0) * 30
    )

    # === WEEKLY CHALLENGE ===
    from app.achievements.weekly_challenge import get_weekly_challenge
    weekly_challenge = get_weekly_challenge(current_user.id)

    # === GAME SCORES (single query via union: best matching + best quiz) ===
    q_matching = GameScore.query.filter_by(
        user_id=current_user.id, game_type='matching'
    ).order_by(GameScore.score.desc()).limit(1)
    q_quiz = GameScore.query.filter_by(
        user_id=current_user.id, game_type='quiz'
    ).order_by(GameScore.score.desc()).limit(1)
    best_scores = q_matching.union_all(q_quiz).all()
    best_matching = None
    best_quiz = None
    for score in best_scores:
        if score.game_type == 'matching':
            best_matching = score
        elif score.game_type == 'quiz':
            best_quiz = score

    # === TELEGRAM (exists check, no full row load) ===
    telegram_linked = db.session.query(
        TelegramUser.query.filter_by(
            user_id=current_user.id, is_active=True
        ).exists()
    ).scalar()

    return render_template('dashboard.html',
        # Daily plan
        greeting=greeting,
        streak=streak,
        streak_status=streak_status,
        streak_repaired=streak_repaired,
        daily_plan=daily_plan,
        daily_summary=daily_summary,
        yesterday_summary=yesterday_summary,
        plan_completion=plan_completion,
        cards_url=cards_url,
        lesson_minutes=lesson_minutes,
        words_minutes=words_minutes,
        required_steps=required_steps,
        plan_steps_done=steps_done,
        plan_steps_total=steps_total,
        # Words
        words_stats=words_stats,
        words_total=words_total,
        words_in_progress=words_in_progress,
        # Books
        books_reading=books_reading,
        recent_book=recent_book,
        # Grammar
        grammar_total=grammar_total,
        grammar_studied=grammar_studied,
        grammar_mastered=grammar_mastered,
        # Courses
        courses_enrolled=courses_enrolled,
        active_course=active_course,
        # Achievements
        total_achievements=total_achievements,
        earned_achievements=earned_achievements,
        # Games
        best_matching=best_matching,
        best_quiz=best_quiz,
        # Telegram
        telegram_linked=telegram_linked,
        # Gamification
        today_xp=today_xp,
        daily_xp_goal=daily_xp_goal,
        weekly_challenge=weekly_challenge,
    )


@words.route('/words')
@login_required
@module_required('words')
def word_list():
    from app.study.models import UserWord

    # Получение параметров фильтра
    search = request.args.get('search', '')
    status = request.args.get('status', '')  # Изменяем на строку для новой системы
    letter = request.args.get('letter', '')
    book_id = request.args.get('book_id', type=int)
    item_type = request.args.get('type', 'all')  # 'all', 'word', 'phrasal_verb'

    # Параметры пагинации
    page = request.args.get('page', 1, type=int)
    per_page = 50  # Увеличиваем для таблицы

    # Создаем формы фильтров с параметрами запроса
    search_form = WordSearchForm(request.args)
    filter_form = WordFilterForm(request.args)

    # Формирование базового запроса с JOIN для получения статусов пользователя и информации о колоде
    from app.study.models import QuizDeck, QuizDeckWord

    # Subquery to get deck info for each word (first deck only)
    deck_subquery = db.session.query(
        QuizDeckWord.word_id,
        QuizDeck.id.label('deck_id'),
        QuizDeck.title.label('deck_title')
    ).join(
        QuizDeck, QuizDeckWord.deck_id == QuizDeck.id
    ).filter(
        QuizDeck.user_id == current_user.id
    ).distinct(QuizDeckWord.word_id).subquery()

    query = db.session.query(
        CollectionWords,
        UserWord.status.label('user_status'),
        deck_subquery.c.deck_id.label('deck_id'),
        deck_subquery.c.deck_title.label('deck_title')
    ).outerjoin(
        UserWord,
        (CollectionWords.id == UserWord.word_id) & (UserWord.user_id == current_user.id)
    ).outerjoin(
        deck_subquery,
        CollectionWords.id == deck_subquery.c.word_id
    )

    # Применяем фильтр по типу (word/phrasal_verb)
    if item_type == 'word':
        query = query.filter(CollectionWords.item_type == 'word')
    elif item_type == 'phrasal_verb':
        query = query.filter(CollectionWords.item_type == 'phrasal_verb')

    # Применяем фильтр поиска
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                CollectionWords.english_word.ilike(search_term),
                CollectionWords.russian_word.ilike(search_term)
            )
        )

    # Применяем фильтр статуса
    if status and status != 'all':
        if status == 'new':
            # Слова без записи в UserWord или со статусом 'new'
            query = query.filter(
                or_(
                    UserWord.status.is_(None),
                    UserWord.status == 'new'
                )
            )
        elif status == 'mastered':
            # Mastered = review status + min_interval >= MASTERED_THRESHOLD_DAYS
            # Используем подзапрос для фильтрации
            from app.study.models import UserCardDirection
            mastered_subquery = db.session.query(UserWord.word_id).filter(
                UserWord.user_id == current_user.id,
                UserWord.status == 'review'
            ).join(
                UserCardDirection, UserCardDirection.user_word_id == UserWord.id
            ).group_by(UserWord.word_id).having(
                func.min(UserCardDirection.interval) >= UserWord.MASTERED_THRESHOLD_DAYS
            ).scalar_subquery()
            query = query.filter(CollectionWords.id.in_(mastered_subquery))
        else:
            query = query.filter(UserWord.status == status)

    # Применяем фильтр по букве
    if letter:
        query = query.filter(CollectionWords.english_word.ilike(f"{letter}%"))

    # Применяем фильтр по книге
    if book_id:
        from app.words.models import word_book_link
        query = query.join(
            word_book_link,
            CollectionWords.id == word_book_link.c.word_id
        ).filter(word_book_link.c.book_id == book_id)

    # Smart sorting: prioritize exact matches when searching
    if search:
        from sqlalchemy import case

        search_lower = search.lower()
        query = query.order_by(
            # Priority 1: Exact match (case-insensitive)
            case(
                (func.lower(CollectionWords.english_word) == search_lower, 1),
                (func.lower(CollectionWords.russian_word) == search_lower, 1),
                else_=10
            ),
            # Priority 2: Starts with search term
            case(
                (func.lower(CollectionWords.english_word).like(f'{search_lower}%'), 2),
                (func.lower(CollectionWords.russian_word).like(f'{search_lower}%'), 2),
                else_=10
            ),
            # Priority 3: Alphabetically by English word
            CollectionWords.english_word.asc()
        )
    else:
        # Default sorting when not searching
        query = query.order_by(CollectionWords.english_word.asc())

    # Пагинация
    words = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    # Преобразуем результат для шаблона
    word_list = []
    for word_obj, user_status, deck_id, deck_title in words.items:
        word_obj.user_status = user_status or 'new'
        word_obj.deck_id = deck_id
        word_obj.deck_title = deck_title
        word_list.append(word_obj)

    # Обновляем words.items
    words.items = word_list

    # Получаем статистику по статусам
    status_counts = {}
    if current_user.is_authenticated:
        counts = db.session.query(
            UserWord.status,
            func.count(UserWord.id).label('count')
        ).filter(
            UserWord.user_id == current_user.id
        ).group_by(UserWord.status).all()
        
        for status_val, count in counts:
            status_counts[status_val] = count

    # Получаем количество по типам
    type_counts = {
        'all': CollectionWords.query.count(),
        'word': CollectionWords.query.filter_by(item_type='word').count(),
        'phrasal_verb': CollectionWords.query.filter_by(item_type='phrasal_verb').count()
    }

    return render_template(
        'words/list_optimized.html',
        words=words,
        search_form=search_form,
        filter_form=filter_form,
        status_counts=status_counts,
        item_type=item_type,
        type_counts=type_counts
    )


@words.route('/words/<int:word_id>')
@login_required
@module_required('words')
def word_detail(word_id):
    from app.study.models import UserWord

    word = CollectionWords.query.get_or_404(word_id)

    # Получаем статус пользователя для этого слова
    user_word = UserWord.query.filter_by(
        user_id=current_user.id,
        word_id=word_id
    ).first()

    # Status и is_mastered для шаблона
    # Note: 'mastered' больше не статус, а порог внутри 'review'
    if user_word:
        word.user_status = user_word.status
        word.is_mastered = user_word.is_mastered
    else:
        word.user_status = 'new'
        word.is_mastered = False

    # Получаем книги, содержащие это слово
    books = []
    if word.books:
        # Простое решение - берем книги без частоты
        books = [(book, 1) for book in word.books]

    # Получаем похожие слова (из того же уровня)
    related_words = CollectionWords.query.filter(
        CollectionWords.id != word_id,
        CollectionWords.level == word.level if word.level else CollectionWords.level.isnot(None)
    ).limit(6).all()

    return render_template(
        'words/details_optimized.html',
        word=word,
        books=books,
        related_words=related_words
    )


# Dummy CSRF form for protection
class DummyCSRFForm(FlaskForm):
    pass


@words.route('/update-word-status/<int:word_id>/<int:status>', methods=['POST'])
@login_required
def update_word_status(word_id, status):
    form = DummyCSRFForm(request.form)
    if not form.validate_on_submit():
        from flask import abort
        abort(400, description="CSRF token missing or invalid.")

    word = CollectionWords.query.get_or_404(word_id)

    # Используем обновленный метод set_word_status из модели User
    # Этот метод должен быть обновлен для работы с новыми моделями
    current_user.set_word_status(word_id, status)

    flash(f'Status for word \"{word.english_word}\" updated successfully.', 'success')

    # Перенаправляем обратно на страницу, с которой пришел запрос (с проверкой безопасности)
    from app.auth.routes import get_safe_redirect_url
    next_page = get_safe_redirect_url(
        request.args.get('next') or request.referrer,
        fallback='words.word_list'
    )
    return redirect(next_page)


@words.route('/phrasal-verbs')
@login_required
@module_required('words')
def phrasal_verb_list():
    """Редирект на единую страницу слов с фильтром по фразовым глаголам"""
    # Сохраняем параметры поиска при редиректе
    args = request.args.to_dict()
    args['type'] = 'phrasal_verb'
    return redirect(url_for('words.word_list', **args))


@words.route('/api/daily-plan/next-step')
@login_required
def daily_plan_next_step() -> tuple:
    """Return the next incomplete step from today's daily plan."""
    from app.telegram.queries import get_daily_plan, get_daily_summary

    daily_plan = get_daily_plan(current_user.id)
    daily_summary = get_daily_summary(current_user.id)

    plan_completion = {
        'lesson': daily_summary['lessons_count'] > 0,
        'grammar': daily_summary['grammar_exercises'] > 0,
        'words': daily_summary.get('srs_words_reviewed', 0) > 0,
        'books': len(daily_summary.get('books_read', [])) > 0,
    }

    # Build ordered list of steps that exist in today's plan
    steps: list[dict] = []

    if daily_plan.get('next_lesson'):
        lesson = daily_plan['next_lesson']
        steps.append({
            'type': 'lesson',
            'title': f"\u041c\u043e\u0434\u0443\u043b\u044c {lesson['module_number']} \u2014 {lesson['title']}",
            'url': url_for('curriculum_lessons.lesson_detail',
                           lesson_id=lesson['lesson_id']) + '?from=daily_plan',
            'icon': '\U0001f3af',
            'done': plan_completion['lesson'],
        })

    if daily_plan.get('grammar_topic'):
        gt = daily_plan['grammar_topic']
        grammar_url = url_for('grammar_lab.topic_detail', topic_id=gt['topic_id'])
        steps.append({
            'type': 'grammar',
            'title': f"Grammar Lab \u2014 {gt['title']}",
            'url': grammar_url + '?from=daily_plan',
            'icon': '\U0001f9e0',
            'done': plan_completion['grammar'],
        })

    if daily_plan.get('words_due', 0) > 0 or daily_plan.get('has_any_words'):
        cards_url = url_for('study.cards')
        if current_user.default_study_deck_id:
            cards_url = url_for('study.cards_deck',
                                deck_id=current_user.default_study_deck_id)
        steps.append({
            'type': 'words',
            'title': f"{daily_plan.get('words_due', 0)} \u0441\u043b\u043e\u0432 \u043d\u0430 \u043f\u043e\u0432\u0442\u043e\u0440",
            'url': cards_url + '?from=daily_plan',
            'icon': '\U0001f4d6',
            'done': plan_completion['words'],
        })

    if daily_plan.get('book_to_read'):
        book = daily_plan['book_to_read']
        steps.append({
            'type': 'books',
            'title': book['title'],
            'url': url_for('books.read_book_chapters',
                           book_id=book['id']) + '?from=daily_plan',
            'icon': '\U0001f4d5',
            'done': plan_completion['books'],
        })

    steps_done = sum(1 for s in steps if s['done'])
    steps_total = len(steps)

    # Find first incomplete step
    next_step = next((s for s in steps if not s['done']), None)

    if not next_step:
        return jsonify({
            'has_next': False,
            'all_done': True,
            'steps_done': steps_done,
            'steps_total': steps_total,
        })

    return jsonify({
        'has_next': True,
        'step_type': next_step['type'],
        'step_title': next_step['title'],
        'step_url': next_step['url'],
        'step_icon': next_step['icon'],
        'steps_done': steps_done,
        'steps_total': steps_total,
    })
