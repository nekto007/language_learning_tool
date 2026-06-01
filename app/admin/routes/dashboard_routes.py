# app/admin/routes/dashboard_routes.py

"""Admin dashboard sub-blueprint: main index page, content quality, and the
stats/cache helpers that feed them.

Split from ``app/admin/main_routes.py`` during the 2026-05-24 admin audit. The
``admin`` blueprint still owns the curriculum routes; this blueprint owns the
landing dashboard (``/admin/``) plus the content quality drill-down.
"""

import logging
import time as _time
from datetime import datetime, timedelta, timezone

from flask import Blueprint, make_response, render_template
from sqlalchemy import case, desc, distinct, func
from sqlalchemy.exc import SQLAlchemyError

from app.admin.utils.decorators import admin_required, cache_result
from app.auth.models import User
from app.books.models import Book
from app.curriculum.models import CEFRLevel, LessonAttempt, LessonProgress, Lessons, Module
from app.utils.db import db
from app.words.models import CollectionWords

dashboard_bp = Blueprint('dashboard_admin', __name__)

logger = logging.getLogger(__name__)

_app_start_time = _time.time()
_error_5xx_count = 0


def _activity_date_expr(*columns):
    """Return the first non-null date column for activity tracking."""
    return func.date(func.coalesce(*columns))


def _active_user_ids_for_date(target_date):
    """UNION DISTINCT user_id across all 7 activity tables for a single date.

    Kept for compatibility with ``get_retention_metrics`` and external callers.
    DAU/WAU/MAU and the daily activity chart use ``get_active_user_dates``
    instead so they pay for one materialised UNION rather than 1 per date.
    """
    from app.books.models import UserChapterProgress
    from app.curriculum.book_courses import BookCourseEnrollment
    from app.curriculum.daily_lessons import UserLessonProgress
    from app.grammar_lab.models import UserGrammarExercise
    from app.study.models import StudySession

    q1 = db.session.query(LessonProgress.user_id).filter(
        _activity_date_expr(LessonProgress.last_activity, LessonProgress.completed_at) == target_date,
    )
    q2 = db.session.query(StudySession.user_id).filter(
        func.date(StudySession.start_time) == target_date,
    )
    q3 = db.session.query(UserGrammarExercise.user_id).filter(
        UserGrammarExercise.last_reviewed.isnot(None),
        func.date(UserGrammarExercise.last_reviewed) == target_date,
    )
    q4 = db.session.query(UserChapterProgress.user_id).filter(
        UserChapterProgress.updated_at.isnot(None),
        func.date(UserChapterProgress.updated_at) == target_date,
    )
    q5 = db.session.query(BookCourseEnrollment.user_id).filter(
        BookCourseEnrollment.last_activity.isnot(None),
        func.date(BookCourseEnrollment.last_activity) == target_date,
    )
    q6 = db.session.query(LessonAttempt.user_id).filter(
        func.date(LessonAttempt.started_at) == target_date,
    )
    q7 = db.session.query(UserLessonProgress.user_id).filter(
        UserLessonProgress.completed_at.isnot(None),
        func.date(UserLessonProgress.completed_at) == target_date,
    )
    return q1.union(q2, q3, q4, q5, q6, q7)


def _build_active_user_date_pairs_query(start_date, end_date):
    """UNION of ``(user_id, activity_date)`` pairs across the 7 activity tables.

    Single round trip materialises the full window. Use ``get_active_user_dates``
    to materialise into a ``{date: set(user_id)}`` dict.
    """
    from app.books.models import UserChapterProgress
    from app.curriculum.book_courses import BookCourseEnrollment
    from app.curriculum.daily_lessons import UserLessonProgress
    from app.grammar_lab.models import UserGrammarExercise
    from app.study.models import StudySession

    date1 = _activity_date_expr(LessonProgress.last_activity, LessonProgress.completed_at)
    q1 = db.session.query(
        LessonProgress.user_id.label('user_id'),
        date1.label('activity_date'),
    ).filter(date1 >= start_date, date1 <= end_date)

    date2 = func.date(StudySession.start_time)
    q2 = db.session.query(
        StudySession.user_id.label('user_id'),
        date2.label('activity_date'),
    ).filter(date2 >= start_date, date2 <= end_date)

    date3 = func.date(UserGrammarExercise.last_reviewed)
    q3 = db.session.query(
        UserGrammarExercise.user_id.label('user_id'),
        date3.label('activity_date'),
    ).filter(
        UserGrammarExercise.last_reviewed.isnot(None),
        date3 >= start_date, date3 <= end_date,
    )

    date4 = func.date(UserChapterProgress.updated_at)
    q4 = db.session.query(
        UserChapterProgress.user_id.label('user_id'),
        date4.label('activity_date'),
    ).filter(
        UserChapterProgress.updated_at.isnot(None),
        date4 >= start_date, date4 <= end_date,
    )

    date5 = func.date(BookCourseEnrollment.last_activity)
    q5 = db.session.query(
        BookCourseEnrollment.user_id.label('user_id'),
        date5.label('activity_date'),
    ).filter(
        BookCourseEnrollment.last_activity.isnot(None),
        date5 >= start_date, date5 <= end_date,
    )

    date6 = func.date(LessonAttempt.started_at)
    q6 = db.session.query(
        LessonAttempt.user_id.label('user_id'),
        date6.label('activity_date'),
    ).filter(date6 >= start_date, date6 <= end_date)

    date7 = func.date(UserLessonProgress.completed_at)
    q7 = db.session.query(
        UserLessonProgress.user_id.label('user_id'),
        date7.label('activity_date'),
    ).filter(
        UserLessonProgress.completed_at.isnot(None),
        date7 >= start_date, date7 <= end_date,
    )

    return q1.union(q2, q3, q4, q5, q6, q7)


def get_active_user_dates(start_date, end_date) -> dict:
    """Materialise ``{date: set(user_id)}`` for the window in a single query.

    Powers DAU/WAU/MAU and the 30-day activity chart without N+1 round trips:
    one UNION query, in-Python aggregation instead of one query per day or one
    per metric.
    """
    rows = _build_active_user_date_pairs_query(start_date, end_date).all()
    bucket: dict = {}
    for user_id, activity_date in rows:
        if user_id is None or activity_date is None:
            continue
        bucket.setdefault(activity_date, set()).add(user_id)
    return bucket


def _count_active_users_in_range(start_date, end_date) -> int:
    """Count distinct active users in ``[start_date, end_date]``.

    Thin wrapper over ``get_active_user_dates`` so callers (retention, ad-hoc
    queries) share the materialised UNION path.
    """
    bucket = get_active_user_dates(start_date, end_date)
    users: set = set()
    for ids in bucket.values():
        users.update(ids)
    return len(users)


@cache_result('dashboard_stats', timeout=180)
def get_dashboard_statistics():
    """Получает статистику для дашборда с кэшированием"""
    week_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)

    total_users = User.query.count()
    active_users = User.query.filter_by(active=True).count()
    new_users = User.query.filter(User.created_at >= week_ago).count()
    logins_last_7d = User.query.filter(User.last_login >= week_ago).count()

    try:
        total_books = db.session.query(func.count(Book.id)).scalar() or 0
        total_readings = db.session.query(func.sum(Book.unique_words)).scalar() or 0
    except SQLAlchemyError:
        logger.exception("Error getting book statistics")
        total_books = 0
        total_readings = 0

    try:
        words_total = db.session.query(func.count(CollectionWords.id)).scalar() or 0
        words_with_audio = CollectionWords.query.filter_by(get_download=1).count()
    except SQLAlchemyError:
        logger.exception("Error getting word statistics")
        words_total = 0
        words_with_audio = 0

    try:
        total_lessons = Lessons.query.count()
        active_lessons = db.session.query(func.count(distinct(LessonProgress.lesson_id))).scalar() or 0
    except SQLAlchemyError:
        logger.exception("Error getting curriculum statistics")
        total_lessons = 0
        active_lessons = 0

    return {
        'total_users': total_users,
        'active_users': active_users,
        'new_users': new_users,
        'logins_last_7d': logins_last_7d,
        'total_books': total_books,
        'total_readings': total_readings,
        'words_total': words_total,
        'words_with_audio': words_with_audio,
        'total_lessons': total_lessons,
        'active_lessons': active_lessons,
    }


@cache_result('daily_activity', timeout=300)
def get_daily_activity_data(days: int = 30) -> dict:
    """Получает данные активности по дням за последние N дней.

    Returns:
        dict with 'labels', 'registrations', 'logins', 'active_users' lists
    """
    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=days - 1)

    reg_rows = db.session.query(
        func.date(User.created_at),
        func.count(User.id),
    ).filter(
        func.date(User.created_at) >= start_date,
    ).group_by(func.date(User.created_at)).all()
    reg_map = {row[0]: row[1] for row in reg_rows}

    login_rows = db.session.query(
        func.date(User.last_login),
        func.count(distinct(User.id)),
    ).filter(
        User.last_login.isnot(None),
        func.date(User.last_login) >= start_date,
    ).group_by(func.date(User.last_login)).all()
    login_map = {row[0]: row[1] for row in login_rows}

    activity_bucket = get_active_user_dates(start_date, today)
    dau_map = {d: len(ids) for d, ids in activity_bucket.items()}

    labels = []
    registrations = []
    logins = []
    active_users = []

    for i in range(days):
        d = start_date + timedelta(days=i)
        labels.append(d.strftime('%d.%m'))
        registrations.append(reg_map.get(d, 0))
        logins.append(login_map.get(d, 0))
        active_users.append(dau_map.get(d, 0))

    return {
        'labels': labels,
        'registrations': registrations,
        'logins': logins,
        'active_users': active_users,
    }


@cache_result('engagement_metrics', timeout=600)
def get_engagement_metrics() -> dict:
    """DAU/WAU/MAU counts with trend arrows vs previous period.

    Uses _count_active_users_in_range (UNION of 6 activity tables).
    Does NOT use User.last_login — see Key Definitions in plan.
    """
    now = datetime.now(timezone.utc)
    today = now.date()

    # One UNION query covers the entire 60-day window. Previously this helper
    # ran six separate UNION counts against the seven activity tables.
    bucket = get_active_user_dates(today - timedelta(days=59), today)

    def _count(start, end) -> int:
        users: set = set()
        d = start
        while d <= end:
            users.update(bucket.get(d, ()))
            d += timedelta(days=1)
        return len(users)

    dau = _count(today, today)
    wau = _count(today - timedelta(days=6), today)
    mau = _count(today - timedelta(days=29), today)

    prev_dau = _count(today - timedelta(days=1), today - timedelta(days=1))
    prev_wau = _count(today - timedelta(days=13), today - timedelta(days=7))
    prev_mau = _count(today - timedelta(days=59), today - timedelta(days=30))

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
    except (SQLAlchemyError, ImportError):
        logger.warning("Error getting book course metrics", exc_info=True)
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
    from app.grammar_lab.models import UserGrammarExercise
    from app.study.models import UserCardDirection

    word_states = db.session.query(
        UserCardDirection.state,
        func.count(UserCardDirection.id),
    ).group_by(UserCardDirection.state).all()
    word_map = {row[0]: row[1] for row in word_states}

    mastered_words = db.session.query(func.count(UserCardDirection.id)).filter(
        UserCardDirection.state == 'review',
        UserCardDirection.interval >= 180,
    ).scalar() or 0

    words_new = word_map.get('new', 0)
    words_learning = word_map.get('learning', 0) + word_map.get('relearning', 0)
    words_review = max(0, word_map.get('review', 0) - mastered_words)
    words_mastered = mastered_words
    words_total = words_new + words_learning + words_review + words_mastered

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
    grammar_review = max(0, grammar_map.get('review', 0) - mastered_grammar)
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
    """Day 1, Day 7, Day 30 retention rates.

    Uses a single bulk query per day_offset instead of one UNION per registration
    date — avoids the previous N+1 pattern that ran _active_user_ids_for_date()
    inside a loop.
    """
    now = datetime.now(timezone.utc)
    today = now.date()
    earliest = today - timedelta(days=90)

    # One query: all user IDs with their registration date for the 90-day window.
    reg_user_rows = db.session.query(
        User.id,
        func.date(User.created_at).label('reg_date'),
    ).filter(
        func.date(User.created_at) >= earliest,
        func.date(User.created_at) <= today,
    ).all()

    cohort_ids_by_date: dict = {}
    for user_id, reg_date in reg_user_rows:
        cohort_ids_by_date.setdefault(reg_date, set()).add(user_id)

    def _retention_rate(day_offset: int) -> float:
        latest = today - timedelta(days=day_offset)
        if latest < earliest:
            return 0.0

        # Determine which (reg_date, target_date) pairs are in range.
        valid_cohorts = []
        for reg_date, cohort_ids in cohort_ids_by_date.items():
            if reg_date > latest:
                continue
            target_date = reg_date + timedelta(days=day_offset)
            if target_date > today:
                continue
            valid_cohorts.append((cohort_ids, target_date))

        if not valid_cohorts:
            return 0.0

        # One UNION query covers all target dates for this day_offset.
        target_dates = [vc[1] for vc in valid_cohorts]
        activity_bucket = get_active_user_dates(min(target_dates), max(target_dates))

        total_cohort = 0
        total_retained = 0
        for cohort_ids, target_date in valid_cohorts:
            total_cohort += len(cohort_ids)
            active_ids = activity_bucket.get(target_date, set())
            total_retained += len(active_ids.intersection(cohort_ids))

        if total_cohort == 0:
            return 0.0
        return round(total_retained / total_cohort * 100, 1)

    return {
        'd1': _retention_rate(1),
        'd7': _retention_rate(7),
        'd30': _retention_rate(30),
    }


# Linear plan rollout metrics widget removed (cohort is now 100% of users).


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

    top_referrers_rows = db.session.query(
        User.username,
        func.count(ReferralLog.id).label('cnt'),
    ).join(ReferralLog, User.id == ReferralLog.referrer_id).group_by(
        User.id, User.username,
    ).order_by(func.count(ReferralLog.id).desc()).limit(5).all()

    top_referrers = [{'username': row[0], 'count': row[1]} for row in top_referrers_rows]

    referred_count = db.session.query(func.count(User.id)).filter(
        User.referred_by_id.isnot(None),
    ).scalar() or 0

    if referred_count > 0:
        converted = db.session.query(func.count(User.id)).filter(
            User.referred_by_id.isnot(None),
            User.onboarding_completed == True,
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

    thirty_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

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

    # Identify low-pass rows first, then bulk-load lessons to avoid N+1.
    low_pass_rows = []
    for row in lesson_stats_rows:
        pass_rate = (row.passed / row.attempts * 100) if row.attempts > 0 else 0
        if pass_rate < 50:
            low_pass_rows.append((row, round(pass_rate, 1)))

    lessons_map: dict = {}
    if low_pass_rows:
        ids = [r[0].lesson_id for r in low_pass_rows]
        lessons_map = {l.id: l for l in Lessons.query.filter(Lessons.id.in_(ids)).all()}

    low_pass_lessons = []
    for row, pass_rate in low_pass_rows:
        lesson = lessons_map.get(row.lesson_id)
        if lesson:
            low_pass_lessons.append({
                'lesson_id': row.lesson_id,
                'title': lesson.title,
                'type': lesson.type,
                'module_id': lesson.module_id,
                'pass_rate': pass_rate,
                'attempts': row.attempts,
                'avg_score': round(row.avg_score or 0, 1),
            })

    low_pass_lessons.sort(key=lambda x: x['pass_rate'])

    completed_lesson_ids = db.session.query(
        distinct(LessonProgress.lesson_id)
    ).filter(LessonProgress.status == 'completed').subquery()

    zero_completions_count = db.session.query(func.count(Lessons.id)).filter(
        ~Lessons.id.in_(db.session.query(completed_lesson_ids))
    ).scalar() or 0

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


def get_content_quality_detail() -> dict:
    """Per-lesson-type content coverage: audio, IPA, examples, completion rate. Used by /admin/content-quality."""
    from app.curriculum.models import LessonFeedback
    from app.utils.db_utils import chunk_ids
    from app.words.models import CollectionWordLink, CollectionWords

    AUDIO_EXPECTED = frozenset({'dictation', 'listening_immersion', 'shadow_reading', 'audio_fill_blank'})

    all_lessons = Lessons.query.all()
    total_lessons = len(all_lessons)

    feedback_rows = db.session.query(
        LessonFeedback.lesson_id,
        func.avg(LessonFeedback.rating).label('avg_rating'),
        func.count(LessonFeedback.id).label('feedback_count'),
    ).group_by(LessonFeedback.lesson_id).all()
    avg_rating_by_lesson: dict[int, float] = {r.lesson_id: float(r.avg_rating) for r in feedback_rows}

    completed_ids: set[int] = set(
        row[0] for row in db.session.query(distinct(LessonProgress.lesson_id))
        .filter(LessonProgress.status == 'completed').all()
    )

    vocab_collection_ids = list({l.collection_id for l in all_lessons if l.type == 'vocabulary' and l.collection_id})
    ipa_by_col: dict[int, int] = {}
    sentences_by_col: dict[int, int] = {}
    word_count_by_col: dict[int, int] = {}

    if vocab_collection_ids:
        for chunk in chunk_ids(vocab_collection_ids):
            rows = db.session.query(
                CollectionWordLink.collection_id,
                func.count(CollectionWords.id).label('total'),
                func.sum(case((CollectionWords.ipa_transcription.isnot(None), 1), else_=0)).label('with_ipa'),
                func.sum(case((CollectionWords.sentences.isnot(None), 1), else_=0)).label('with_sentences'),
            ).join(CollectionWords, CollectionWords.id == CollectionWordLink.word_id).filter(
                CollectionWordLink.collection_id.in_(chunk)
            ).group_by(CollectionWordLink.collection_id).all()
            for row in rows:
                word_count_by_col[row.collection_id] = row.total
                ipa_by_col[row.collection_id] = row.with_ipa
                sentences_by_col[row.collection_id] = row.with_sentences

    by_type: dict[str, dict] = {}
    missing_audio: list[dict] = []
    no_vocabulary: list[dict] = []

    for lesson in all_lessons:
        lt = lesson.type or 'other'
        if lt not in by_type:
            by_type[lt] = {
                'total': 0, 'with_audio': 0, 'with_ipa': 0, 'with_examples': 0,
                'completed': 0, 'rating_sum': 0.0, 'rating_count': 0,
            }
        entry = by_type[lt]
        entry['total'] += 1
        if lesson.id in avg_rating_by_lesson:
            entry['rating_sum'] += avg_rating_by_lesson[lesson.id]
            entry['rating_count'] += 1

        if lesson.id in completed_ids:
            entry['completed'] += 1

        content = lesson.content or {}
        has_audio = bool(content.get('audio_url'))
        if has_audio:
            entry['with_audio'] += 1
        elif lt in AUDIO_EXPECTED:
            missing_audio.append({
                'lesson_id': lesson.id, 'title': lesson.title, 'type': lt, 'module_id': lesson.module_id,
            })

        if lt == 'vocabulary':
            cid = lesson.collection_id
            if cid and word_count_by_col.get(cid, 0) > 0:
                if ipa_by_col.get(cid, 0) > 0:
                    entry['with_ipa'] += 1
                if sentences_by_col.get(cid, 0) > 0:
                    entry['with_examples'] += 1
            else:
                no_vocabulary.append({'lesson_id': lesson.id, 'title': lesson.title, 'module_id': lesson.module_id})

    lesson_number_by_id = {lesson.id: lesson.number for lesson in all_lessons}
    if missing_audio:
        module_ids = list({m['module_id'] for m in missing_audio if m['module_id']})
        if module_ids:
            mod_rows_data = []
            for chunk in chunk_ids(module_ids):
                chunk_rows = (
                    db.session.query(
                        Module.id,
                        Module.number,
                        Module.title,
                        CEFRLevel.order.label('level_order'),
                        CEFRLevel.code.label('level_code'),
                    )
                    .join(CEFRLevel, CEFRLevel.id == Module.level_id)
                    .filter(Module.id.in_(chunk))
                    .all()
                )
                mod_rows_data.extend(chunk_rows)
            mod_info = {r.id: r for r in mod_rows_data}
            for m in missing_audio:
                info = mod_info.get(m['module_id'])
                m['level_code'] = info.level_code if info else ''
                m['level_order'] = info.level_order if info else 0
                m['module_number'] = info.number if info else 0
                m['module_title'] = info.title if info else ''
                m['lesson_number'] = lesson_number_by_id.get(m['lesson_id'], 0)
        missing_audio.sort(key=lambda x: (
            x.get('level_order', 0), x.get('module_number', 0), x.get('lesson_number', 0)
        ))

    type_rows = []
    for lt, data in sorted(by_type.items()):
        total = data['total']
        rc = data['rating_count']
        type_rows.append({
            'type': lt,
            'total': total,
            'with_audio': data['with_audio'],
            'with_ipa': data['with_ipa'],
            'with_examples': data['with_examples'],
            'completed': data['completed'],
            'audio_pct': round(data['with_audio'] / total * 100) if total else 0,
            'ipa_pct': round(data['with_ipa'] / total * 100) if total else 0,
            'examples_pct': round(data['with_examples'] / total * 100) if total else 0,
            'avg_rating': round(data['rating_sum'] / rc, 1) if rc else None,
            'feedback_count': rc,
            'completion_pct': round(data['completed'] / total * 100) if total else 0,
        })

    completed_lesson_count = len(completed_ids.intersection({l.id for l in all_lessons}))
    return {
        'by_type': type_rows,
        'missing_audio': missing_audio[:50],
        'missing_audio_count': len(missing_audio),
        'no_vocabulary': no_vocabulary[:50],
        'no_vocabulary_count': len(no_vocabulary),
        'total_lessons': total_lessons,
        'no_completions_count': total_lessons - completed_lesson_count,
    }


@cache_result('content_alerts', timeout=300)
def get_content_alerts() -> list:
    """Generate content alerts using LessonAnalyticsService."""
    from app.curriculum.services.lesson_analytics_service import LessonAnalyticsService

    try:
        alerts = LessonAnalyticsService.generate_alerts()
        return alerts[:5]
    except (SQLAlchemyError, AttributeError):
        logger.exception("Error generating content alerts")
        return []


@cache_result('system_health', timeout=60)
def get_system_health() -> dict:
    """System health: DB connection, pool stats, uptime, 5xx error count (per worker)."""
    health = {
        'db_status': 'ok',
        'db_error': None,
        'db_pool': None,
        'uptime_seconds': int(_time.time() - _app_start_time),
        'errors_5xx': _error_5xx_count,
    }
    try:
        db.session.execute(db.text('SELECT 1'))
    except SQLAlchemyError as e:
        logger.warning("DB health check failed: %s", e)
        health['db_status'] = 'error'
        health['db_error'] = str(e)

    try:
        pool = db.engine.pool
        health['db_pool'] = {
            'size': pool.size(),
            'checked_in': pool.checkedin(),
            'checked_out': pool.checkedout(),
            'overflow': pool.overflow(),
        }
    except Exception:
        # Not all pool types (StaticPool, NullPool) support size/checkin stats.
        pass

    return health


def increment_5xx_counter():
    """Call from Flask 500 errorhandler to track 5xx errors."""
    global _error_5xx_count
    _error_5xx_count += 1


@dashboard_bp.route('/')
@admin_required
def dashboard():
    """Главная страница административной панели"""
    from app.admin.utils.cache import cleanup_expired
    cleanup_expired(timeout=300)

    stats = get_dashboard_statistics()
    activity_data = get_daily_activity_data(30)
    engagement = get_engagement_metrics()
    learning = get_learning_metrics()
    content = get_content_metrics()
    srs_health = get_srs_health_metrics()
    retention = get_retention_metrics()
    streaks = get_streak_analytics()
    referrals = get_referral_analytics()
    coins = get_coin_economy()
    linear_plan = {}
    content_quality = get_content_quality()
    content_alerts = get_content_alerts()
    system_health = get_system_health()

    recent_users = User.query.order_by(desc(User.created_at)).limit(10).all()

    from app.admin.services import UserManagementService
    at_risk_users = UserManagementService.get_at_risk_users()

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
        linear_plan=linear_plan,
        content_quality=content_quality,
        content_alerts=content_alerts,
        system_health=system_health,
        at_risk_users=at_risk_users,
        **stats,
    )


@dashboard_bp.route('/content-quality')
@admin_required
def content_quality_page():
    """Detailed content quality dashboard — per lesson type coverage and missing content."""
    detail = get_content_quality_detail()
    return render_template('admin/content_quality.html', **detail)


@dashboard_bp.route('/content-quality/export')
@admin_required
def content_quality_export():
    """Export per-lesson-type content quality metrics as CSV."""
    import csv
    import io

    from app.admin.utils.export_helpers import MAX_EXPORT_ROWS, _sanitize_csv_cell

    detail = get_content_quality_detail()
    rows = detail['by_type'][:MAX_EXPORT_ROWS]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Lesson Type', 'Total', 'With Audio', 'Audio %', 'With IPA', 'IPA %',
                     'With Examples', 'Examples %', 'Completed', 'Completion %'])
    for row in rows:
        writer.writerow([
            _sanitize_csv_cell(row['type']),
            row['total'], row['with_audio'], row['audio_pct'],
            row['with_ipa'], row['ipa_pct'],
            row['with_examples'], row['examples_pct'],
            row['completed'], row['completion_pct'],
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    response.headers['Content-Disposition'] = f'attachment; filename=content_quality_{ts}.csv'
    return response
