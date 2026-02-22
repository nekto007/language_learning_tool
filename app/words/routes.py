from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy import func, or_

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

    # Completion flags: compare daily_summary with daily_plan
    plan_completion = {
        'lesson': daily_summary['lessons_count'] > 0,
        'grammar': daily_summary['grammar_exercises'] > 0,
        'words': daily_summary['words_reviewed'] > 0,
        'books': len(daily_summary.get('books_read', [])) > 0,
    }

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
    from app.study.models import UserCardDirection

    status_counts = db.session.query(
        UserWord.status,
        func.count(UserWord.id).label('count')
    ).filter(
        UserWord.user_id == current_user.id
    ).group_by(UserWord.status).all()

    words_stats = {'new': 0, 'learning': 0, 'review': 0, 'mastered': 0}
    for status, count in status_counts:
        if status in words_stats:
            words_stats[status] = count

    mastered_count = db.session.query(func.count(func.distinct(UserWord.id))).filter(
        UserWord.user_id == current_user.id,
        UserWord.status == 'review'
    ).join(
        UserCardDirection, UserCardDirection.user_word_id == UserWord.id
    ).group_by(UserWord.id).having(
        func.min(UserCardDirection.interval) >= UserWord.MASTERED_THRESHOLD_DAYS
    ).count()

    words_stats['mastered'] = mastered_count
    words_stats['review'] = max(0, words_stats['review'] - mastered_count)

    words_total = sum(words_stats.values())
    words_in_progress = words_stats['learning'] + words_stats['review']

    # === BOOKS STATS ===
    books_reading = current_user.get_reading_progress_count() if hasattr(current_user, 'get_reading_progress_count') else 0
    recent_book = None
    if hasattr(current_user, 'get_recent_reading_progress'):
        recent_books = current_user.get_recent_reading_progress(1)
        recent_book = recent_books[0] if recent_books else None

    # === GRAMMAR LAB STATS ===
    grammar_total = GrammarTopic.query.count()
    grammar_studied = UserGrammarTopicStatus.query.filter(
        UserGrammarTopicStatus.user_id == current_user.id,
        UserGrammarTopicStatus.theory_completed == True
    ).count()
    grammar_mastered = grammar_studied

    # === BOOK COURSES STATS ===
    courses_enrolled = BookCourseEnrollment.query.filter_by(
        user_id=current_user.id, status='active'
    ).count()
    active_course = BookCourseEnrollment.query.filter_by(
        user_id=current_user.id, status='active'
    ).order_by(BookCourseEnrollment.last_activity.desc()).first()

    # === ACHIEVEMENTS ===
    total_achievements = Achievement.query.count()
    earned_achievements = UserAchievement.query.filter_by(user_id=current_user.id).count()

    # === GAME SCORES ===
    best_matching = GameScore.query.filter_by(
        user_id=current_user.id, game_type='matching'
    ).order_by(GameScore.score.desc()).first()
    best_quiz = GameScore.query.filter_by(
        user_id=current_user.id, game_type='quiz'
    ).order_by(GameScore.score.desc()).first()

    # === TELEGRAM ===
    telegram_linked = TelegramUser.query.filter_by(
        user_id=current_user.id, is_active=True
    ).first() is not None

    return render_template('dashboard.html',
        # Daily plan
        streak=streak,
        daily_plan=daily_plan,
        daily_summary=daily_summary,
        plan_completion=plan_completion,
        cards_url=cards_url,
        lesson_minutes=lesson_minutes,
        words_minutes=words_minutes,
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
                CollectionWords.english_word.like(search_term),
                CollectionWords.russian_word.like(search_term)
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
            # Mastered = review status + min_interval >= 180 days
            # Используем подзапрос для фильтрации
            from app.study.models import UserCardDirection
            mastered_subquery = db.session.query(UserWord.word_id).filter(
                UserWord.user_id == current_user.id,
                UserWord.status == 'review'
            ).join(
                UserCardDirection, UserCardDirection.user_word_id == UserWord.id
            ).group_by(UserWord.word_id).having(
                func.min(UserCardDirection.interval) >= UserWord.MASTERED_THRESHOLD_DAYS
            ).subquery()
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

    # Перенаправляем обратно на страницу, с которой пришел запрос
    next_page = request.args.get('next') or request.referrer or url_for('words.word_list')
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
        'words': daily_summary['words_reviewed'] > 0,
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
