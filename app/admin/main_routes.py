# app/admin/routes.py

"""
Основной модуль административной панели для LLT English
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import case, desc, distinct, func

from app import csrf
from app.auth.models import User
from app.books.models import Book, Chapter
from app.curriculum.models import CEFRLevel, LessonAttempt, LessonProgress, Lessons, Module
from app.utils.db import db
from app.words.forms import CollectionForm, TopicForm
from app.words.models import Collection, CollectionWordLink, CollectionWords, Topic, TopicWord

admin = Blueprint('admin', __name__, url_prefix='/admin')

# Настройка логирования
logger = logging.getLogger(__name__)

# Импорт декоратора из единого места
from app.admin.utils.decorators import admin_required, cache_result


@cache_result('dashboard_stats', timeout=180)  # Кэш на 3 минуты
def get_dashboard_statistics():
    """Получает статистику для дашборда с кэшированием"""
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    # Основная статистика пользователей
    total_users = User.query.count()
    active_users = User.query.filter_by(active=True).count()
    new_users = User.query.filter(User.created_at >= week_ago).count()
    active_recently = User.query.filter(User.last_login >= week_ago).count()

    # Статистика по книгам
    try:
        total_books = db.session.query(func.count(Book.id)).scalar() or 0
        total_readings = db.session.query(func.sum(Book.unique_words)).scalar() or 0
    except Exception as e:
        logger.warning(f"Error getting book statistics: {e}")
        total_books = 0
        total_readings = 0

    # Статистика по словам
    try:
        words_total = db.session.query(func.count(CollectionWords.id)).scalar() or 0
        words_with_audio = CollectionWords.query.filter_by(get_download=1).count()
    except Exception as e:
        logger.warning(f"Error getting word statistics: {e}")
        words_total = 0
        words_with_audio = 0

    # Статистика по учебной программе
    try:
        total_lessons = Lessons.query.count()
        active_lessons = db.session.query(func.count(distinct(LessonProgress.lesson_id))).scalar() or 0
    except Exception as e:
        logger.warning(f"Error getting curriculum statistics: {e}")
        total_lessons = 0
        active_lessons = 0

    return {
        'total_users': total_users,
        'active_users': active_users,
        'new_users': new_users,
        'active_recently': active_recently,
        'total_books': total_books,
        'total_readings': total_readings,
        'words_total': words_total,
        'words_with_audio': words_with_audio,
        'total_lessons': total_lessons,
        'active_lessons': active_lessons
    }


@cache_result('daily_activity', timeout=300)
def get_daily_activity_data(days: int = 30) -> dict:
    """Получает данные активности по дням за последние N дней.

    Returns:
        dict with 'labels', 'registrations', 'logins', 'active_users' lists
    """
    from app.study.models import StudySession

    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=days - 1)

    # Daily registrations
    reg_rows = db.session.query(
        func.date(User.created_at),
        func.count(User.id)
    ).filter(
        func.date(User.created_at) >= start_date
    ).group_by(func.date(User.created_at)).all()
    reg_map = {row[0]: row[1] for row in reg_rows}

    # Daily logins (last_login)
    login_rows = db.session.query(
        func.date(User.last_login),
        func.count(distinct(User.id))
    ).filter(
        User.last_login.isnot(None),
        func.date(User.last_login) >= start_date
    ).group_by(func.date(User.last_login)).all()
    login_map = {row[0]: row[1] for row in login_rows}

    # Daily active users (users with LessonProgress or StudySession activity)
    lp_rows = db.session.query(
        func.date(LessonProgress.last_activity),
        func.count(distinct(LessonProgress.user_id))
    ).filter(
        LessonProgress.last_activity.isnot(None),
        func.date(LessonProgress.last_activity) >= start_date
    ).group_by(func.date(LessonProgress.last_activity)).all()
    lp_map = {row[0]: row[1] for row in lp_rows}

    ss_rows = db.session.query(
        func.date(StudySession.start_time),
        func.count(distinct(StudySession.user_id))
    ).filter(
        func.date(StudySession.start_time) >= start_date
    ).group_by(func.date(StudySession.start_time)).all()
    ss_map = {row[0]: row[1] for row in ss_rows}

    labels = []
    registrations = []
    logins = []
    active_users = []

    for i in range(days):
        d = start_date + timedelta(days=i)
        labels.append(d.strftime('%d.%m'))
        registrations.append(reg_map.get(d, 0))
        logins.append(login_map.get(d, 0))
        # Approximate DAU: max of lesson-progress users and study-session users
        # (union would be more accurate but this avoids complex query)
        active_users.append(max(lp_map.get(d, 0), ss_map.get(d, 0)))

    return {
        'labels': labels,
        'registrations': registrations,
        'logins': logins,
        'active_users': active_users,
    }


@cache_result('engagement_metrics', timeout=300)
def get_engagement_metrics() -> dict:
    """DAU/WAU/MAU counts with trend arrows vs previous period."""
    from app.study.models import StudySession

    now = datetime.now(timezone.utc)
    today = now.date()

    def _active_users_in_range(start_date, end_date):
        """Count distinct users with login, lesson progress or study session activity."""
        login_ids = db.session.query(User.id).filter(
            User.last_login.isnot(None),
            func.date(User.last_login) >= start_date,
            func.date(User.last_login) <= end_date,
        )
        lp_ids = db.session.query(LessonProgress.user_id).filter(
            LessonProgress.last_activity.isnot(None),
            func.date(LessonProgress.last_activity) >= start_date,
            func.date(LessonProgress.last_activity) <= end_date,
        )
        ss_ids = db.session.query(StudySession.user_id).filter(
            func.date(StudySession.start_time) >= start_date,
            func.date(StudySession.start_time) <= end_date,
        )
        union_q = login_ids.union(lp_ids, ss_ids).subquery()
        return db.session.query(func.count()).select_from(union_q).scalar() or 0

    # Current periods
    dau = _active_users_in_range(today, today)
    wau = _active_users_in_range(today - timedelta(days=6), today)
    mau = _active_users_in_range(today - timedelta(days=29), today)

    # Previous periods for trend
    prev_dau = _active_users_in_range(today - timedelta(days=1), today - timedelta(days=1))
    prev_wau = _active_users_in_range(today - timedelta(days=13), today - timedelta(days=7))
    prev_mau = _active_users_in_range(today - timedelta(days=59), today - timedelta(days=30))

    def _trend(current: int, previous: int) -> tuple:
        if previous == 0:
            return ('up', '+100%') if current > 0 else ('', '')
        diff = current - previous
        pct = round(abs(diff) / previous * 100)
        if diff > 0:
            return ('up', f'+{pct}%')
        elif diff < 0:
            return ('down', f'-{pct}%')
        return ('', '0%')

    dau_trend, dau_trend_val = _trend(dau, prev_dau)
    wau_trend, wau_trend_val = _trend(wau, prev_wau)
    mau_trend, mau_trend_val = _trend(mau, prev_mau)

    return {
        'dau': dau, 'dau_trend': dau_trend, 'dau_trend_value': dau_trend_val,
        'wau': wau, 'wau_trend': wau_trend, 'wau_trend_value': wau_trend_val,
        'mau': mau, 'mau_trend': mau_trend, 'mau_trend_value': mau_trend_val,
    }


@cache_result('learning_metrics', timeout=300)
def get_learning_metrics() -> dict:
    """Lessons completed today/week, average lesson score, study sessions today."""
    from app.study.models import StudySession

    now = datetime.now(timezone.utc)
    today = now.date()
    week_ago = today - timedelta(days=6)

    lessons_today = db.session.query(func.count(LessonProgress.id)).filter(
        LessonProgress.status == 'completed',
        func.date(LessonProgress.completed_at) == today,
    ).scalar() or 0

    lessons_week = db.session.query(func.count(LessonProgress.id)).filter(
        LessonProgress.status == 'completed',
        func.date(LessonProgress.completed_at) >= week_ago,
    ).scalar() or 0

    avg_score = db.session.query(func.avg(LessonAttempt.score)).filter(
        LessonAttempt.score.isnot(None),
        func.date(LessonAttempt.completed_at) >= week_ago,
    ).scalar()
    avg_score = round(avg_score, 1) if avg_score else 0

    sessions_today = db.session.query(func.count(StudySession.id)).filter(
        func.date(StudySession.start_time) == today,
    ).scalar() or 0

    return {
        'lessons_today': lessons_today,
        'lessons_week': lessons_week,
        'avg_lesson_score': avg_score,
        'sessions_today': sessions_today,
    }


@cache_result('content_metrics', timeout=300)
def get_content_metrics() -> dict:
    """Grammar topics count, book courses with enrollments, active quiz decks."""
    from app.grammar_lab.models import GrammarTopic
    from app.study.models import QuizDeck

    try:
        from app.curriculum.book_courses import BookCourse, BookCourseEnrollment
        book_courses_count = db.session.query(func.count(BookCourse.id)).scalar() or 0
        enrollments_count = db.session.query(func.count(BookCourseEnrollment.id)).scalar() or 0
    except Exception:
        book_courses_count = 0
        enrollments_count = 0

    grammar_topics_count = db.session.query(func.count(GrammarTopic.id)).scalar() or 0
    active_decks = db.session.query(func.count(QuizDeck.id)).scalar() or 0

    return {
        'grammar_topics_count': grammar_topics_count,
        'book_courses_count': book_courses_count,
        'enrollments_count': enrollments_count,
        'active_decks': active_decks,
    }


@cache_result('srs_health_metrics', timeout=300)
def get_srs_health_metrics() -> dict:
    """SRS distribution: new/learning/review/mastered for words and grammar."""
    from app.study.models import UserCardDirection
    from app.grammar_lab.models import UserGrammarExercise

    # Word SRS via UserCardDirection (the actual SRS tracking entity)
    word_states = db.session.query(
        UserCardDirection.state,
        func.count(UserCardDirection.id),
    ).group_by(UserCardDirection.state).all()
    word_map = {row[0]: row[1] for row in word_states}

    # For mastered, we need interval >= 180 days among 'review' state
    mastered_words = db.session.query(func.count(UserCardDirection.id)).filter(
        UserCardDirection.state == 'review',
        UserCardDirection.interval >= 180,
    ).scalar() or 0

    words_new = word_map.get('new', 0)
    words_learning = word_map.get('learning', 0) + word_map.get('relearning', 0)
    words_review = word_map.get('review', 0) - mastered_words
    words_mastered = mastered_words
    words_total = words_new + words_learning + words_review + words_mastered

    # Grammar SRS via UserGrammarExercise
    grammar_states = db.session.query(
        UserGrammarExercise.state,
        func.count(UserGrammarExercise.id),
    ).group_by(UserGrammarExercise.state).all()
    grammar_map = {row[0]: row[1] for row in grammar_states}

    mastered_grammar = db.session.query(func.count(UserGrammarExercise.id)).filter(
        UserGrammarExercise.state == 'review',
        UserGrammarExercise.interval >= 180,
    ).scalar() or 0

    grammar_new = grammar_map.get('new', 0)
    grammar_learning = grammar_map.get('learning', 0) + grammar_map.get('relearning', 0)
    grammar_review = grammar_map.get('review', 0) - mastered_grammar
    grammar_mastered = mastered_grammar
    grammar_total = grammar_new + grammar_learning + grammar_review + grammar_mastered

    return {
        'words_srs': {
            'new': words_new, 'learning': words_learning,
            'review': words_review, 'mastered': words_mastered,
            'total': words_total,
        },
        'grammar_srs': {
            'new': grammar_new, 'learning': grammar_learning,
            'review': grammar_review, 'mastered': grammar_mastered,
            'total': grammar_total,
        },
    }


@cache_result('retention_metrics', timeout=300)
def get_retention_metrics() -> dict:
    """Day 1, Day 7, Day 30 retention rates."""
    now = datetime.now(timezone.utc)
    today = now.date()

    def _retention_rate(day_offset: int) -> float:
        """Percentage of users who were active day_offset days after registration."""
        # Users who registered at least day_offset days ago
        cutoff = today - timedelta(days=day_offset)
        cohort_count = db.session.query(func.count(User.id)).filter(
            func.date(User.created_at) <= cutoff,
        ).scalar() or 0
        if cohort_count == 0:
            return 0.0

        # Of those, how many had last_login on or after their registration + day_offset
        retained = db.session.query(func.count(User.id)).filter(
            func.date(User.created_at) <= cutoff,
            User.last_login.isnot(None),
            func.date(User.last_login) >= func.date(User.created_at) + day_offset,
        ).scalar() or 0

        return round(retained / cohort_count * 100, 1)

    return {
        'd1': _retention_rate(1),
        'd7': _retention_rate(7),
        'd30': _retention_rate(30),
    }


@cache_result('streak_analytics', timeout=300)
def get_streak_analytics() -> dict:
    """Streak analytics: active streaks, average length, distribution."""
    from app.achievements.models import UserStatistics

    active_streaks = db.session.query(func.count(UserStatistics.id)).filter(
        UserStatistics.current_streak_days > 0,
    ).scalar() or 0

    avg_streak = db.session.query(func.avg(UserStatistics.current_streak_days)).filter(
        UserStatistics.current_streak_days > 0,
    ).scalar()
    avg_streak = round(avg_streak, 1) if avg_streak else 0

    longest_overall = db.session.query(func.max(UserStatistics.longest_streak_days)).scalar() or 0

    # Streak distribution buckets: 1-3, 4-7, 8-14, 15-30, 31+
    buckets = [
        ('1-3', 1, 3),
        ('4-7', 4, 7),
        ('8-14', 8, 14),
        ('15-30', 15, 30),
        ('31+', 31, 99999),
    ]
    distribution = {}
    for label, low, high in buckets:
        cnt = db.session.query(func.count(UserStatistics.id)).filter(
            UserStatistics.current_streak_days >= low,
            UserStatistics.current_streak_days <= high,
        ).scalar() or 0
        distribution[label] = cnt

    return {
        'active_streaks': active_streaks,
        'avg_streak': avg_streak,
        'longest_overall': longest_overall,
        'distribution': distribution,
    }


@cache_result('referral_analytics', timeout=300)
def get_referral_analytics() -> dict:
    """Referral dashboard: total referrals, top referrers, conversion rate."""
    from app.auth.models import ReferralLog

    total_referrals = db.session.query(func.count(ReferralLog.id)).scalar() or 0

    # Top 5 referrers
    top_referrers_rows = db.session.query(
        User.username,
        func.count(ReferralLog.id).label('cnt'),
    ).join(ReferralLog, User.id == ReferralLog.referrer_id).group_by(
        User.id, User.username,
    ).order_by(func.count(ReferralLog.id).desc()).limit(5).all()

    top_referrers = [{'username': row[0], 'count': row[1]} for row in top_referrers_rows]

    # Conversion rate: referred users who completed at least one lesson
    referred_count = db.session.query(func.count(User.id)).filter(
        User.referred_by_id.isnot(None),
    ).scalar() or 0

    if referred_count > 0:
        converted = db.session.query(func.count(distinct(LessonProgress.user_id))).filter(
            LessonProgress.status == 'completed',
            LessonProgress.user_id.in_(
                db.session.query(User.id).filter(User.referred_by_id.isnot(None))
            ),
        ).scalar() or 0
        conversion_rate = round(converted / referred_count * 100, 1)
    else:
        converted = 0
        conversion_rate = 0

    return {
        'total_referrals': total_referrals,
        'top_referrers': top_referrers,
        'referred_count': referred_count,
        'converted': converted,
        'conversion_rate': conversion_rate,
    }


@cache_result('coin_economy', timeout=300)
def get_coin_economy() -> dict:
    """Coin economy summary: total in circulation, earned vs spent."""
    from app.achievements.models import StreakCoins

    totals = db.session.query(
        func.sum(StreakCoins.balance),
        func.sum(StreakCoins.total_earned),
        func.sum(StreakCoins.total_spent),
    ).first()

    total_balance = totals[0] or 0
    total_earned = totals[1] or 0
    total_spent = totals[2] or 0

    users_with_coins = db.session.query(func.count(StreakCoins.id)).filter(
        StreakCoins.balance > 0,
    ).scalar() or 0

    return {
        'total_balance': total_balance,
        'total_earned': total_earned,
        'total_spent': total_spent,
        'users_with_coins': users_with_coins,
    }


@cache_result('content_quality', timeout=300)
def get_content_quality() -> dict:
    """Content quality metrics: low pass rate lessons, zero completions, grammar topics without exercises."""
    from app.grammar_lab.models import GrammarExercise, GrammarTopic

    # Lessons with <50% pass rate (at least 5 attempts in last 30 days)
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    lesson_stats_rows = db.session.query(
        LessonAttempt.lesson_id,
        func.count(LessonAttempt.id).label('attempts'),
        func.sum(case((LessonAttempt.passed == True, 1), else_=0)).label('passed'),
        func.avg(LessonAttempt.score).label('avg_score'),
    ).filter(
        LessonAttempt.completed_at.isnot(None),
        LessonAttempt.started_at >= thirty_days_ago,
    ).group_by(LessonAttempt.lesson_id).having(
        func.count(LessonAttempt.id) >= 5,
    ).all()

    low_pass_lessons = []
    for row in lesson_stats_rows:
        pass_rate = (row.passed / row.attempts * 100) if row.attempts > 0 else 0
        if pass_rate < 50:
            lesson = Lessons.query.get(row.lesson_id)
            if lesson:
                low_pass_lessons.append({
                    'lesson_id': row.lesson_id,
                    'title': lesson.title,
                    'type': lesson.type,
                    'module_id': lesson.module_id,
                    'pass_rate': round(pass_rate, 1),
                    'attempts': row.attempts,
                    'avg_score': round(row.avg_score or 0, 1),
                })

    low_pass_lessons.sort(key=lambda x: x['pass_rate'])

    # Lessons with 0 completions (exist in DB but no one completed them)
    completed_lesson_ids = db.session.query(
        distinct(LessonProgress.lesson_id)
    ).filter(LessonProgress.status == 'completed').subquery()

    zero_completions_count = db.session.query(func.count(Lessons.id)).filter(
        ~Lessons.id.in_(db.session.query(completed_lesson_ids))
    ).scalar() or 0

    # Grammar topics with 0 exercises
    topics_with_exercises = db.session.query(
        distinct(GrammarExercise.topic_id)
    ).subquery()

    zero_exercises_count = db.session.query(func.count(GrammarTopic.id)).filter(
        ~GrammarTopic.id.in_(db.session.query(topics_with_exercises))
    ).scalar() or 0

    return {
        'low_pass_lessons': low_pass_lessons[:10],
        'low_pass_count': len(low_pass_lessons),
        'zero_completions_count': zero_completions_count,
        'zero_exercises_count': zero_exercises_count,
    }


@cache_result('content_alerts', timeout=300)
def get_content_alerts() -> list:
    """Generate content alerts using LessonAnalyticsService."""
    from app.curriculum.services.lesson_analytics_service import LessonAnalyticsService

    try:
        alerts = LessonAnalyticsService.generate_alerts()
        return alerts[:5]
    except Exception as e:
        logger.warning(f"Error generating content alerts: {e}")
        return []


@cache_result('system_health', timeout=60)
def get_system_health() -> dict:
    """System health: DB connection status, basic error check."""
    health = {'db_status': 'ok', 'db_error': None}
    try:
        db.session.execute(db.text('SELECT 1'))
    except Exception as e:
        health['db_status'] = 'error'
        health['db_error'] = str(e)

    return health


@admin.route('/')
@admin_required
def dashboard():
    """Главная страница административной панели"""
    # Получаем кэшированную статистику
    stats = get_dashboard_statistics()

    # Данные активности за 30 дней для графика
    activity_data = get_daily_activity_data(30)

    # Engagement & learning metrics
    engagement = get_engagement_metrics()
    learning = get_learning_metrics()
    content = get_content_metrics()
    srs_health = get_srs_health_metrics()

    # Retention, streaks, referrals, coins
    retention = get_retention_metrics()
    streaks = get_streak_analytics()
    referrals = get_referral_analytics()
    coins = get_coin_economy()

    # Content quality & alerts
    content_quality = get_content_quality()
    content_alerts = get_content_alerts()
    system_health = get_system_health()

    # Последние пользователи не кэшируем, так как они часто меняются
    recent_users = User.query.order_by(desc(User.created_at)).limit(10).all()

    return render_template(
        'admin/dashboard.html',
        recent_users=recent_users,
        activity_data=activity_data,
        engagement=engagement,
        learning=learning,
        content=content,
        srs_health=srs_health,
        retention=retention,
        streaks=streaks,
        referrals=referrals,
        coins=coins,
        content_quality=content_quality,
        content_alerts=content_alerts,
        system_health=system_health,
        **stats
    )



@admin.route('/curriculum')
@admin_required
def curriculum():
    """Управление структурой курсов"""
    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

    # Получаем список последних уроков для быстрого доступа
    recent_lessons = Lessons.query.order_by(Lessons.created_at.desc()).limit(10).all()

    # Получаем количество уникальных пользователей с прогрессом
    user_progress_count = db.session.query(func.count(distinct(LessonProgress.user_id))).scalar() or 0

    return render_template(
        'admin/curriculum/index.html',
        levels=levels,
        recent_lessons=recent_lessons,
        user_progress_count=user_progress_count
    )


@admin.route('/curriculum/levels')
@admin_required
def level_list():
    """List all CEFR levels"""
    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

    # Add counts for each level
    for level in levels:
        level.module_count = Module.query.filter_by(level_id=level.id).count()
        level.lesson_count = db.session.query(Lessons).join(
            Module, Module.id == Lessons.module_id
        ).filter(
            Module.level_id == level.id
        ).count()

    return render_template('admin/curriculum/level_list.html', levels=levels)


@admin.route('/curriculum/modules')
@admin_required
def module_list():
    """List all modules"""
    level_id = request.args.get('level_id', type=int)

    query = Module.query.join(CEFRLevel)

    if level_id:
        query = query.filter(Module.level_id == level_id)

    modules = query.order_by(CEFRLevel.order, Module.number).all()

    for module in modules:
        module.lesson_count = Lessons.query.filter_by(module_id=module.id).count()

    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

    return render_template(
        'admin/curriculum/module_list.html',
        modules=modules,
        levels=levels,
        level_id=level_id
    )


@admin.route('/curriculum/lessons')
@admin_required
def lesson_list():
    """List all lessons"""
    level_id = request.args.get('level_id', type=int)
    module_id = request.args.get('module_id', type=int)
    search = request.args.get('search', '')

    query = Lessons.query.join(Module).join(CEFRLevel)

    if level_id:
        query = query.filter(Module.level_id == level_id)

    if module_id:
        query = query.filter(Lessons.module_id == module_id)

    if search:
        query = query.filter(Lessons.title.ilike(f'%{search}%'))

    lessons = query.order_by(CEFRLevel.order, Module.number, Lessons.number).all()

    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

    if level_id:
        modules = Module.query.filter_by(level_id=level_id).order_by(Module.number).all()
    else:
        modules = Module.query.join(CEFRLevel).order_by(CEFRLevel.order, Module.number).all()

    return render_template(
        'admin/curriculum/lesson_list.html',
        lessons=lessons,
        levels=levels,
        modules=modules,
        level_id=level_id,
        module_id=module_id,
        search=search
    )


@admin.route('/curriculum/progress')
@admin_required
def user_progress():
    """View user progress through curriculum"""
    user_id = request.args.get('user_id', type=int)
    level_id = request.args.get('level_id', type=int)
    module_id = request.args.get('module_id', type=int)
    status = request.args.get('status')

    query = db.session.query(
        LessonProgress, Lessons, Module, CEFRLevel, User
    ).join(
        Lessons, LessonProgress.lesson_id == Lessons.id
    ).join(
        Module, Lessons.module_id == Module.id
    ).join(
        CEFRLevel, Module.level_id == CEFRLevel.id
    ).join(
        User, LessonProgress.user_id == User.id
    )

    if user_id:
        query = query.filter(LessonProgress.user_id == user_id)

    if level_id:
        query = query.filter(Module.level_id == level_id)

    if module_id:
        query = query.filter(Lessons.module_id == module_id)

    if status:
        query = query.filter(LessonProgress.status == status)

    progress_entries = query.order_by(
        User.username,
        CEFRLevel.order,
        Module.number,
        Lessons.number
    ).all()

    status_counts = db.session.query(
        LessonProgress.status,
        db.func.count(LessonProgress.id)
    ).group_by(LessonProgress.status).all()

    status_stats = {status: count for status, count in status_counts}

    users = User.query.order_by(User.username).all()
    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

    if level_id:
        modules = Module.query.filter_by(level_id=level_id).order_by(Module.number).all()
    else:
        modules = []

    return render_template(
        'admin/curriculum/user_progress.html',
        progress_entries=progress_entries,
        users=users,
        levels=levels,
        modules=modules,
        status_stats=status_stats,
        user_id=user_id,
        level_id=level_id,
        module_id=module_id,
        status=status
    )


@admin.route('/curriculum/import', methods=['GET', 'POST'])
@admin_required
def import_curriculum():
    """Импорт учебного материала из JSON"""
    if request.method == 'POST':
        # Проверяем, был ли загружен файл или введен JSON-текст
        json_data = None

        if 'json_file' in request.files and request.files['json_file'].filename:
            # Получаем JSON из файла
            file = request.files['json_file']

            # SECURITY: Validate uploaded file
            from app.utils.file_security import validate_text_file_upload
            is_valid, error_msg = validate_text_file_upload(
                file,
                allowed_extensions={'json'},
                max_size_mb=10
            )

            if not is_valid:
                flash(f'Ошибка валидации файла: {error_msg}', 'danger')
                return redirect(url_for('admin.import_curriculum'))

            try:
                json_text = file.read().decode('utf-8')
                json_data = json.loads(json_text)
            except Exception as e:
                flash(f'Ошибка при чтении файла: {str(e)}', 'danger')
                return redirect(url_for('admin.import_curriculum'))
        elif request.form.get('json_text'):
            # Получаем JSON из текстового поля
            try:
                json_data = json.loads(request.form.get('json_text'))
            except Exception as e:
                flash(f'Ошибка в формате JSON: {str(e)}', 'danger')
                return redirect(url_for('admin.import_curriculum'))

        if json_data:
            # Выполняем импорт
            try:
                result = import_curriculum_data(json_data)
                flash(f'Материал успешно импортирован! Создан урок ID: {result["lesson_id"]}', 'success')

                # Перенаправляем на страницу списка уроков модуля
                module = Module.query.get(result["module_id"])
                if module:
                    return redirect(url_for('admin.lesson_list', module_id=module.id))
                else:
                    return redirect(url_for('admin.curriculum'))
            except Exception as e:
                logger.error(f'Ошибка при импорте: {str(e)}', exc_info=True)
                flash(f'Ошибка при импорте: {str(e)}', 'danger')
                return redirect(url_for('admin.import_curriculum'))

    return render_template('admin/curriculum/import.html')


# Вспомогательные функции
def import_curriculum_data(data):
    """
    Импортирует данные курса из JSON

    Args:
        data (dict): JSON-структура курса

    Returns:
        dict: Информация о созданных объектах
    """
    logger.info("Начинаем импорт данных курса из JSON")

    # Нормализация формата JSON (поддержка двух форматов)
    # Формат 1 (старый): {"level": "A1", "module": 6, "lessons": [...]}
    # Формат 2 (новый): {"module": {"id": 6, "level": "A1", "lessons": [...]}}
    if 'module' in data and isinstance(data['module'], dict):
        # Новый формат - извлекаем данные из вложенного объекта
        module_data = data['module']
        data = {
            'level': module_data.get('level'),
            'module': module_data.get('order') or module_data.get('number') or module_data.get('id'),
            'title': module_data.get('title'),
            'description': module_data.get('description', ''),
            'lessons': module_data.get('lessons', [])
        }
        logger.info("Обнаружен новый формат JSON, выполнена нормализация")

    # Проверяем наличие обязательных полей
    if 'level' not in data or 'module' not in data:
        raise ValueError("В JSON отсутствуют обязательные поля 'level' и 'module'")

    # 1. Создаем или находим уровень CEFR
    level_code = data['level']
    level = CEFRLevel.query.filter_by(code=level_code).first()

    if not level:
        # Создаем новый уровень
        level_name = get_level_name(level_code)
        level = CEFRLevel(
            code=level_code,
            name=level_name,
            description=f"Level {level_code}",
            order=get_level_order(level_code)
        )
        db.session.add(level)
        db.session.flush()
        logger.info(f"Создан новый уровень: {level.code}")

    # 2. Создаем или находим модуль
    module_number = data['module']
    module_description = data.get('description', '')
    module = Module.query.filter_by(level_id=level.id, number=module_number).first()

    if not module:
        # Создаем новый модуль
        module_title = data.get('title', f"Module {module_number}")
        module = Module(
            level_id=level.id,
            number=module_number,
            title=module_title,
            description=module_description,
            raw_content=data
        )
        db.session.add(module)
        db.session.flush()
        logger.info(f"Создан новый модуль: {module.number}")
    else:
        # Обновляем существующий модуль
        module.raw_content = data
        if data.get('title'):
            module.title = data.get('title')
        if module_description:
            module.description = module_description

    # 3. Создаём уроки из списка data['lessons']
    for lesson_data in data.get('lessons', []):
        # Нормализация формата урока (поддержка двух форматов)
        # Старый: {"lesson_number": 1, "lesson_type": "vocabulary", "words": [...]}
        # Новый: {"id": 1, "type": "vocabulary", "content": {"vocabulary": [...]}}
        number = lesson_data.get('lesson_number') or lesson_data.get('order') or lesson_data.get('id')
        lesson_type = lesson_data.get('lesson_type') or lesson_data.get('type')
        title = lesson_data.get('title', '')
        lesson = Lessons.query.filter_by(module_id=module.id, number=number).first()
        if not lesson:
            lesson = Lessons(
                module_id=module.id,
                number=number,
                title=title,
                type=lesson_type if lesson_type != 'text' else 'text',
                order=number,
                description=title
            )
            db.session.add(lesson)
            db.session.flush()
        # Обрабатываем контент по типу урока
        if lesson_type == 'grammar':
            # Поддержка обоих форматов грамматики
            theory = lesson_data.get('theory', {})
            content = lesson_data.get('content', {})
            grammar_explanation = content.get('grammar_explanation', {})

            grammar_input = {
                'rule': theory.get('rule', '') or grammar_explanation.get('rule', ''),
                'description': theory.get('description', '') or grammar_explanation.get('introduction', ''),
                'examples': theory.get('examples', []) or grammar_explanation.get('examples', []),
                'exercises': lesson_data.get('exercises', []) or content.get('exercises', [])
            }
            lesson.content = process_grammar(grammar_input)
        elif lesson_type == 'vocabulary':
            # Поддержка обоих форматов: words или content.vocabulary
            vocab_list = lesson_data.get('words', [])
            if not vocab_list and lesson_data.get('content'):
                vocab_list = lesson_data['content'].get('vocabulary', [])
            # Создаем или получаем коллекцию
            collection_name = f"{module.title} - {level_code} Module {module_number} Vocabulary"
            collection = Collection.query.filter_by(name=collection_name).first()
            if not collection:
                collection = Collection(
                    name=collection_name,
                    description=module.title,
                    created_by=current_user.id
                )
                db.session.add(collection)
                db.session.flush()
            # Очищаем старые связи и обрабатываем слова
            CollectionWordLink.query.filter_by(collection_id=collection.id).delete()
            process_vocabulary(vocab_list, collection, level_code)
            lesson.collection_id = collection.id
            lesson.content = vocab_list
        elif lesson_type == 'card':
            lesson.content = {
                'settings': lesson_data.get('settings', {}),
                'cards': lesson_data.get('cards', []),
                'note': lesson_data.get('note', '')
            }
        elif lesson_type == 'quiz':
            lesson.content = {'exercises': lesson_data.get('exercises', [])}
        elif lesson_type == 'text':
            lesson.content = lesson_data.get('content', {})
        elif lesson_type == 'final_test':
            lesson.content = {
                'passing_score_percent': lesson_data.get('passing_score_percent', 0),
                'exercises': lesson_data.get('exercises', [])
            }
        else:
            lesson.content = lesson_data

    # 4. Сохраняем все изменения
    db.session.commit()

    # Возвращаем результат
    # Определяем id первого урока, если есть
    first_lesson = Lessons.query.filter_by(module_id=module.id).order_by(Lessons.number).first()
    first_lesson_id = first_lesson.id if first_lesson else None

    result = {
        "level_id": level.id,
        "module_id": module.id,
        "lesson_id": first_lesson_id
    }

    logger.info("Импорт завершен успешно.")
    return result


def process_vocabulary(vocabulary_data, collection, level_code):
    """Обрабатывает словарь без тегов (поддержка двух форматов)"""
    for word_data in vocabulary_data:
        # Поддержка обоих форматов: {word, translation} и {english, russian}
        english_word = (word_data.get('word') or word_data.get('english', '')).lower()
        translation = word_data.get('translation') or word_data.get('russian', '')
        # Find or create the word
        word = CollectionWords.query.filter_by(english_word=english_word).first()
        if not word:
            word = CollectionWords(
                english_word=english_word,
                russian_word=translation,
                level=level_code,
                frequency_rank=word_data.get('frequency_rank', 0)
            )
            db.session.add(word)
            db.session.flush()
        else:
            # Update translation or rank if provided
            if word_data.get('frequency_rank'):
                word.frequency_rank = word_data['frequency_rank']
            word.russian_word = translation

        # Link the word to the collection
        existing = CollectionWordLink.query.filter_by(collection_id=collection.id, word_id=word.id).first()
        if not existing:
            link = CollectionWordLink(collection_id=collection.id, word_id=word.id)
            db.session.add(link)


def process_grammar(grammar_data):
    """Преобразует грамматические данные в формат для хранения"""
    exercises = []

    if 'exercises' in grammar_data:
        for exercise in grammar_data['exercises']:
            exercise_type = exercise.get('type')

            exercise_data = {
                'type': exercise_type,
                'text': exercise.get('prompt', ''),
                'explanation': exercise.get('explanation', '')
            }

            if exercise_type == 'fill_in_blank':
                exercise_data['answer'] = exercise.get('correct_answer', [])
                if exercise.get('alternative_answers'):
                    exercise_data['alternative_answers'] = exercise.get('alternative_answers', [])
            elif exercise_type == 'multiple_choice':
                exercise_data['options'] = exercise.get('options', [])
                exercise_data['question'] = exercise.get('question', '')
                exercise_data['answer'] = exercise.get('correct_index')
            elif exercise_type == 'true_false':
                exercise_data['question'] = exercise.get('question', '')
                exercise_data['answer'] = exercise.get('correct_answer')
            elif exercise_type == 'match':
                exercise_data['pairs'] = exercise.get('pairs', [])
            elif exercise_type == 'reorder':
                exercise_data['words'] = exercise.get('words', [])
                exercise_data['answer'] = exercise.get('correct_answer', '')
            elif exercise_type == 'translation':
                exercise_data['answer'] = exercise.get('correct_answer', '')
                exercise_data['alternative_answers'] = exercise.get('alternative_answers', [])
            else:
                # Для других типов сохраняем как есть
                exercise_data['answer'] = exercise.get('answer', '')

            exercises.append(exercise_data)

    return {
        'rule': grammar_data.get('rule', ''),
        'description': grammar_data.get('description', ''),
        'examples': grammar_data.get('examples', []),
        'exercises': exercises
    }


def get_level_name(level_code):
    """Возвращает название для кода уровня CEFR"""
    level_names = {
        'A0': 'Pre-Beginner',
        'A1': 'Beginner',
        'A2': 'Elementary',
        'B1': 'Intermediate',
        'B2': 'Upper Intermediate',
        'C1': 'Advanced',
        'C2': 'Proficiency'
    }
    return level_names.get(level_code, f'Level {level_code}')


def get_level_order(level_code):
    """Возвращает порядок для уровня CEFR"""
    level_orders = {
        'A0': 0,
        'A1': 1,
        'A2': 2,
        'B1': 3,
        'B2': 4,
        'C1': 5,
        'C2': 6
    }
    return level_orders.get(level_code, 99)


try:
    from . import curriculum
except ImportError:
    logger.warning("Не удалось импортировать модуль curriculum")
