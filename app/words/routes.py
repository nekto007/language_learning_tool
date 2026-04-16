import logging
import time
import threading

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy import case, func, or_

from app.study.models import GameScore
from app.utils.db import db
from app.words.forms import WordFilterForm, WordSearchForm
from app.words.models import CollectionWords
from app.modules.decorators import module_required

logger = logging.getLogger(__name__)


# Simple TTL cache for leaderboard data (shared across requests)
_leaderboard_cache: dict = {'data': None, 'expires': 0.0, 'lock': threading.Lock()}
_MISSION_PHASE_POINTS = {
    'recall': 8,
    'learn': 22,
    'use': 18,
    'read': 20,
    'check': 12,
    'close': 0,
}
_LEGACY_STEP_POINTS = {
    'lesson': 22,
    'grammar': 18,
    'words': 14,
    'books': 20,
    'book_course_practice': 18,
}

words = Blueprint('words', __name__)


@words.route('/dictionary/<path:word_slug>')
def public_word(word_slug: str):
    """Public word page for SEO — no login required."""
    from flask import abort

    # Normalize slug back to word (hyphens → spaces)
    search_term = word_slug.replace('-', ' ').strip().lower()

    word = CollectionWords.query.filter(
        func.lower(CollectionWords.english_word) == search_term
    ).first()

    if not word:
        abort(404)

    # Related words (same level, limit 6)
    related_words = []
    if word.level:
        related_words = (
            CollectionWords.query
            .filter(CollectionWords.id != word.id, CollectionWords.level == word.level)
            .order_by(func.random())
            .limit(6)
            .all()
        )

    # Related grammar topics (same level)
    related_grammar = []
    if word.level:
        from app.grammar_lab.models import GrammarTopic
        related_grammar = (
            GrammarTopic.query
            .filter(GrammarTopic.level == word.level)
            .order_by(GrammarTopic.order)
            .limit(3)
            .all()
        )

    meta_description = (
        f'{word.english_word} — перевод: {word.russian_word}. '
        f'Уровень {word.level or ""}. Примеры, произношение и упражнения.'
    )

    return render_template(
        'words/public_word.html',
        word=word,
        related_words=related_words,
        related_grammar=related_grammar,
        meta_description=meta_description,
    )


def _process_referral_reward_on_first_visit(user) -> None:
    """Award referral XP to referrer after the referred user completes onboarding.

    Checks the explicit onboarding_completed flag so the reward is not
    triggered before the user has actually finished the onboarding flow.
    """
    if not getattr(user, 'referred_by_id', None):
        return

    # Only award after onboarding is completed
    if not getattr(user, 'onboarding_completed', False):
        return

    from app.notifications.models import Notification
    # Check if reward already delivered (notification to referrer about this user)
    already = Notification.query.filter_by(
        user_id=user.referred_by_id,
        type='referral',
    ).filter(Notification.title.contains(user.username)).first()
    if already:
        return

    try:
        from app.study.models import UserXP
        referrer_xp = UserXP.get_or_create(user.referred_by_id)
        referrer_xp.add_xp(100)

        from app.notifications.services import notify_referral
        notify_referral(user.referred_by_id, user.username)

        from app.auth.routes import _check_referral_achievements
        _check_referral_achievements(user.referred_by_id)

        db.session.commit()
    except Exception as e:
        logger.exception("Referral reward processing failed for user %s: %s", user.referred_by_id, e)
        db.session.rollback()


def _safe_widget_call(name: str, fn, *args, default=None, **kwargs):
    """Call a widget data function safely, returning default on failure.

    Uses a savepoint so that a widget failure only rolls back its own
    queries, leaving the outer transaction (and already-loaded objects
    like current_user) intact.
    """
    try:
        with db.session.begin_nested():
            return fn(*args, **kwargs)
    except Exception as e:
        db.session.rollback()
        logger.exception("Dashboard widget '%s' failed: %s", name, e)
        return default


def _get_cached_leaderboard(stats_service_cls, limit: int = 5):
    """Return leaderboard data with 5-minute TTL cache."""
    cache = _leaderboard_cache
    now = time.time()
    with cache['lock']:
        if cache['data'] is not None and now < cache['expires']:
            return cache['data']
    # Query outside the lock to avoid serializing all dashboard requests
    data = stats_service_cls.get_xp_leaderboard(limit=limit)
    with cache['lock']:
        cache['data'] = data
        cache['expires'] = time.time() + 300  # 5 minutes
    return data


def _compute_daily_race_state(daily_plan: dict, daily_summary: dict, streak: int) -> dict:
    from app.achievements.streak_service import compute_plan_steps

    plan_completion, _, steps_done, steps_total = compute_plan_steps(daily_plan, daily_summary)
    score = 0
    next_step_title = None
    next_step_points = 0

    phases = daily_plan.get('phases') or []
    if phases:
        required_phases = [p for p in phases if p.get('required', True)]
        for phase in required_phases:
            points = _MISSION_PHASE_POINTS.get(phase.get('phase', ''), 12)
            if plan_completion.get(phase.get('id'), False):
                score += points
            elif next_step_title is None:
                next_step_title = phase.get('title') or 'Следующий этап'
                next_step_points = points

        if steps_total > 0 and steps_done >= steps_total:
            score += 12
    else:
        steps = daily_plan.get('steps') or {}
        for key in ('lesson', 'grammar', 'words', 'books', 'book_course_practice'):
            step = steps.get(key)
            if not step:
                continue
            points = _LEGACY_STEP_POINTS.get(key, 15)
            if plan_completion.get(key, False):
                score += points
            elif next_step_title is None:
                next_step_title = step.get('title') or 'Следующий шаг'
                next_step_points = points

        if steps_total > 0 and steps_done >= steps_total:
            score += 12

    score += min(max(streak, 0), 10)

    return {
        'score': score,
        'steps_done': steps_done,
        'steps_total': steps_total,
        'next_step_title': next_step_title,
        'next_step_points': next_step_points,
    }


def _get_next_plan_action(plan: dict, daily_summary: dict) -> tuple[str | None, str | None]:
    from app.achievements.streak_service import _compute_phase_completion

    phases = plan.get('phases') or []
    if phases:
        completion = _compute_phase_completion(phases, daily_summary)
        next_phase = next((p for p in phases if not completion.get(p['id'])), None)
        if next_phase:
            return next_phase.get('title'), _phase_url(next_phase, plan)

    steps = plan.get('steps') or {}
    legacy_order = ('lesson', 'grammar', 'words', 'books', 'book_course_practice')
    for key in legacy_order:
        step = steps.get(key)
        if step and not step.get('is_done'):
            return step.get('title') or 'Следующий шаг', step.get('url')

    return None, None


def _build_daily_race_widget(current_user_id: int, tz: str) -> dict | None:
    from app.auth.models import User
    from app.daily_plan.service import get_daily_plan_unified
    from app.telegram.queries import get_current_streak, get_daily_summary

    candidates = (
        User.query
        .filter(
            User.active.is_(True),
            User.is_admin.is_(False),
            User.onboarding_completed.is_(True),
        )
        .order_by(User.last_login.desc().nullslast(), User.created_at.desc())
        .limit(18)
        .all()
    )

    current_user_row = User.query.get(current_user_id)
    if current_user_row and not any(user.id == current_user_id for user in candidates):
        candidates.append(current_user_row)

    entries = []
    for user in candidates:
        user_tz = user.timezone or tz
        try:
            with db.session.begin_nested():
                plan = get_daily_plan_unified(user.id, tz=user_tz)
                summary = get_daily_summary(user.id, tz=user_tz)
                streak = get_current_streak(user.id, tz=user_tz)
                race_state = _compute_daily_race_state(plan, summary, streak)
        except Exception as e:
            logger.exception("Failed to build daily race entry for user %s: %s", user.id, e)
            continue

        if race_state['steps_total'] <= 0:
            continue

        entries.append({
            'user_id': user.id,
            'username': user.username,
            'score': race_state['score'],
            'steps_done': race_state['steps_done'],
            'steps_total': race_state['steps_total'],
            'streak': streak,
            'next_step_title': race_state['next_step_title'],
            'next_step_points': race_state['next_step_points'],
            'is_me': user.id == current_user_id,
            'is_bot': False,
        })

    current_index = next((i for i, item in enumerate(entries) if item['is_me']), None)
    if current_index is None:
        return None

    me_seed = entries[current_index]

    if len(entries) < 4:
        bot_names = ['Молния', 'Ракета', 'Спринтер']
        bot_offsets = [8, -6, 15]
        bot_steps = [0, 0, 1]
        for idx, name in enumerate(bot_names):
            entries.append({
                'user_id': -(idx + 1),
                'username': name,
                'score': max(0, me_seed['score'] + bot_offsets[idx]),
                'steps_done': min(me_seed['steps_total'], max(0, me_seed['steps_done'] + bot_steps[idx])),
                'steps_total': me_seed['steps_total'],
                'streak': max(0, me_seed['streak'] + idx + 1),
                'next_step_title': me_seed['next_step_title'],
                'next_step_points': me_seed['next_step_points'],
                'is_me': False,
                'is_bot': True,
            })

    entries.sort(key=lambda item: (-item['score'], -item['steps_done'], -item['streak'], item['username'].lower()))
    current_index = next((i for i, item in enumerate(entries) if item['is_me']), None)
    if current_index is None:
        return None

    for idx, entry in enumerate(entries, start=1):
        entry['rank'] = idx

    me = entries[current_index]
    rival_above = entries[current_index - 1] if current_index > 0 else None
    rival_below = entries[current_index + 1] if current_index + 1 < len(entries) else None

    gap_up = max(1, rival_above['score'] - me['score']) if rival_above else 0
    gap_down = max(1, me['score'] - rival_below['score']) if rival_below else None

    if rival_above:
        if me['next_step_points'] and me['next_step_points'] > gap_up:
            callout = f'«{me["next_step_title"]}» даст рывок и поднимет тебя выше {rival_above["username"]}.'
        elif me['next_step_points']:
            remaining = max(0, gap_up - me['next_step_points'])
            callout = (
                f'«{me["next_step_title"]}» сократит отрыв до {remaining} '
                f'и приблизит тебя к {rival_above["username"]}.'
            )
        else:
            callout = f'До {rival_above["username"]}: {gap_up} очков.'
    else:
        callout = 'Ты впереди. Закрой следующий этап и закрепи лидерство.'

    start = max(0, current_index - 2)
    end = min(len(entries), current_index + 3)

    return {
        'rank': me['rank'],
        'total': len(entries),
        'score': me['score'],
        'steps_done': me['steps_done'],
        'steps_total': me['steps_total'],
        'streak': me['streak'],
        'rival_above': rival_above,
        'rival_below': rival_below,
        'gap_up': gap_up,
        'gap_down': gap_down,
        'callout': callout,
        'next_step_title': me['next_step_title'],
        'next_step_points': me['next_step_points'],
        'duel_target': rival_above or rival_below,
        'has_bot_rivals': any(entry.get('is_bot') for entry in entries),
        'leaderboard': entries[start:end],
    }


@words.route('/dashboard')
@login_required
@module_required('words')
def dashboard():
    """Main dashboard with daily plan, streak and activity summary."""
    t_start = time.time()
    tz = current_user.timezone or 'Europe/Moscow'

    # Process deferred referral reward on first visit
    _process_referral_reward_on_first_visit(current_user)

    from app.study.models import Achievement, UserAchievement
    from app.grammar_lab.models import GrammarTopic, UserGrammarTopicStatus
    from app.curriculum.book_courses import BookCourseEnrollment
    from app.telegram.models import TelegramUser
    from app.daily_plan.service import get_daily_plan_unified
    from app.telegram.queries import get_current_streak, get_daily_summary
    from app.telegram.notifications import _lesson_minutes, _words_minutes
    from app.study.insights_service import get_activity_heatmap, get_words_at_risk, get_grammar_weaknesses, get_best_study_time, get_reading_speed_trend
    from app.grammar_lab.services.grammar_lab_service import GrammarLabService
    from app.study.services.session_service import SessionService
    from app.study.services.stats_service import StatsService
    from app.achievements.streak_service import get_streak_calendar, get_milestone_history

    # === DAILY PLAN & STREAK ===
    streak = get_current_streak(current_user.id, tz=tz)
    daily_plan = get_daily_plan_unified(current_user.id, tz=tz)
    daily_summary = get_daily_summary(current_user.id, tz=tz)

    # Time-based greeting
    from datetime import datetime as dt
    import pytz
    try:
        local_hour = dt.now(pytz.timezone('Europe/Moscow')).hour
    except (pytz.exceptions.UnknownTimeZoneError, OverflowError, OSError) as e:
        logger.warning("Failed to determine local hour via pytz, using UTC fallback: %s", e)
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
    yesterday_summary = get_yesterday_summary(current_user.id, tz=tz)

    # === PLAN COMPLETION & STREAK ===
    from app.achievements.streak_service import compute_plan_steps, process_streak_on_activity

    plan_completion, steps_available, steps_done, steps_total = compute_plan_steps(daily_plan, daily_summary)

    streak_result = process_streak_on_activity(current_user.id, steps_done, steps_total, tz=tz)
    streak_status = streak_result['streak_status']
    required_steps = streak_result['required_steps']
    streak_repaired = streak_result['streak_repaired']
    streak = streak_status.get('streak', streak)
    daily_race = _safe_widget_call('daily_race', _build_daily_race_widget, current_user.id, tz, default=None)

    # Cards URL (user's default deck or generic)
    cards_url = url_for('study.cards')
    if current_user.default_study_deck_id:
        cards_url = url_for('study.cards_deck', deck_id=current_user.default_study_deck_id)

    # Lesson time estimate
    lesson_minutes = None
    if daily_plan.get('next_lesson'):
        lesson_minutes = _lesson_minutes(daily_plan['next_lesson'].get('lesson_type'))

    words_minutes = _words_minutes(daily_plan.get('words_due', 0))

    # === ACTIVITY HEATMAP & STREAK CALENDAR ===
    activity_heatmap = _safe_widget_call(
        'activity_heatmap', get_activity_heatmap, current_user.id, days=90, tz=tz, default=[])
    # Show empty state if user has no activity (all counts zero)
    if activity_heatmap and not any(d.get('count', 0) > 0 for d in activity_heatmap):
        activity_heatmap = []
    # Pad heatmap so first day aligns to correct weekday row.
    # Grid rows: 0=Sun, 1=Mon, ..., 6=Sat. Python weekday: 0=Mon, ..., 6=Sun.
    heatmap_pad = 0
    if activity_heatmap:
        try:
            from datetime import date as _date
            first_date = _date.fromisoformat(activity_heatmap[0]['date'])
            # Convert Python weekday (Mon=0) to grid row (Sun=0): (wd + 1) % 7
            heatmap_pad = (first_date.weekday() + 1) % 7
        except (ValueError, KeyError, IndexError):
            heatmap_pad = 0
    streak_calendar = _safe_widget_call(
        'streak_calendar', get_streak_calendar, current_user.id, days=90, tz=tz, default={})

    # === WORDS AT RISK & GRAMMAR WEAKNESSES ===
    words_at_risk = _safe_widget_call(
        'words_at_risk', get_words_at_risk, current_user.id, limit=5, default=[])
    grammar_weaknesses = _safe_widget_call(
        'grammar_weaknesses', get_grammar_weaknesses, current_user.id, limit=5, default=[])

    # === BEST STUDY TIME & SESSION STATS ===
    best_study_time = _safe_widget_call(
        'best_study_time', get_best_study_time, current_user.id, tz=tz,
        default={'best_hour': None, 'hourly_scores': {}})
    _empty_session_stats = {
        'period_days': 7, 'total_sessions': 0, 'total_words_studied': 0,
        'total_correct': 0, 'total_incorrect': 0, 'accuracy_percent': 0,
        'total_time_seconds': 0, 'avg_session_time_seconds': 0,
    }
    session_stats = _safe_widget_call(
        'session_stats', SessionService.get_session_stats, current_user.id, days=7,
        default=_empty_session_stats)

    # === LEADERBOARD & XP RANK (leaderboard cached for 5 min) ===
    xp_leaderboard = _safe_widget_call(
        'xp_leaderboard', _get_cached_leaderboard, StatsService, limit=5, default=[])
    user_xp_rank = _safe_widget_call(
        'user_xp_rank', StatsService.get_user_xp_rank, current_user.id, default=None)

    # === ACHIEVEMENTS BY CATEGORY & MILESTONES ===
    achievements_by_category = _safe_widget_call(
        'achievements_by_category', StatsService.get_achievements_by_category, current_user.id, default={})
    milestone_history = _safe_widget_call(
        'milestone_history', get_milestone_history, current_user.id, default=[])

    # === READING SPEED TREND & GRAMMAR BY LEVEL ===
    reading_speed_trend = _safe_widget_call(
        'reading_speed_trend', get_reading_speed_trend, current_user.id, default=[])
    grammar_levels_summary = _safe_widget_call(
        'grammar_levels_summary', lambda uid: GrammarLabService().get_levels_summary(user_id=uid),
        current_user.id, default=[])

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

    # === WEEKLY ANALYTICS (via insights_service — week-to-date, not lifetime) ===
    from app.study.insights_service import get_weekly_summary
    weekly_analytics = get_weekly_summary(current_user.id)

    # === CONTINUE WHERE YOU LEFT OFF ===
    from app.curriculum.service import get_user_active_lessons
    active_lessons = get_user_active_lessons(current_user.id, limit=1)
    continue_lesson = active_lessons[0] if active_lessons else None

    # === GRAMMAR PROGRESS SUMMARY ===
    grammar_user_stats = srs_stats_service.get_grammar_user_stats(current_user.id)

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

    # === PERFORMANCE LOGGING ===
    t_elapsed = time.time() - t_start
    logger.info("Dashboard data loaded in %.3fs for user_id=%s", t_elapsed, current_user.id)

    mission_plan = daily_plan if daily_plan.get('mission') else None
    plan_meta = daily_plan.get('_plan_meta', {})
    phase_urls = {}
    if mission_plan:
        for p in daily_plan.get('phases', []):
            phase_urls[p.get('id', '')] = _phase_url(p, daily_plan)
    next_plan_title, next_plan_url = _get_next_plan_action(daily_plan, daily_summary)
    if daily_race:
        daily_race['next_action_title'] = next_plan_title
        daily_race['next_action_url'] = next_plan_url

    return render_template('dashboard.html',
        # Daily plan
        greeting=greeting,
        streak=streak,
        streak_status=streak_status,
        streak_repaired=streak_repaired,
        daily_race=daily_race,
        daily_plan=daily_plan,
        daily_summary=daily_summary,
        yesterday_summary=yesterday_summary,
        plan_completion=plan_completion,
        plan_steps=daily_plan.get('steps', {}),
        mission_plan=mission_plan,
        plan_meta=plan_meta,
        phase_urls=phase_urls,
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
        # Personalization
        onboarding_focus=getattr(current_user, 'onboarding_focus', None),
        onboarding_level=getattr(current_user, 'onboarding_level', None),
        # Activity heatmap
        activity_heatmap=activity_heatmap,
        heatmap_pad=heatmap_pad,
        streak_calendar=streak_calendar,
        # Words at risk & grammar weaknesses
        words_at_risk=words_at_risk,
        grammar_weaknesses=grammar_weaknesses,
        # Best study time & session stats
        best_study_time=best_study_time,
        session_stats=session_stats,
        # Leaderboard
        xp_leaderboard=xp_leaderboard,
        user_xp_rank=user_xp_rank,
        # Achievements by category & milestones
        achievements_by_category=achievements_by_category,
        milestone_history=milestone_history,
        # Reading speed trend & grammar by level
        reading_speed_trend=reading_speed_trend,
        grammar_levels_summary=grammar_levels_summary,
        # Summary widgets
        weekly_analytics=weekly_analytics,
        continue_lesson=continue_lesson,
        grammar_user_stats=grammar_user_stats,
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
    per_page = min(request.args.get('per_page', 50, type=int), 200)

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
    from app.daily_plan.service import get_daily_plan_unified
    from app.telegram.queries import get_daily_summary

    tz = current_user.timezone or 'Europe/Moscow'
    daily_plan = get_daily_plan_unified(current_user.id, tz=tz)
    daily_summary = get_daily_summary(current_user.id, tz=tz)

    if daily_plan.get('phases'):
        return _next_step_from_mission(daily_plan, daily_summary)

    return _next_step_from_legacy(daily_plan, daily_summary)


def _next_step_from_mission(plan: dict, daily_summary: dict) -> tuple:
    """Return next incomplete phase from mission plan."""
    from app.achievements.streak_service import _compute_phase_completion, compute_plan_steps

    phases = plan['phases']
    completion = _compute_phase_completion(phases, daily_summary)
    _, _, steps_done, steps_total = compute_plan_steps(plan, daily_summary)
    phases_done = steps_done
    phases_total = steps_total

    next_phase = next((p for p in phases if not completion.get(p['id'])), None)

    if not next_phase:
        return jsonify({
            'has_next': False,
            'all_done': True,
            'steps_done': phases_done,
            'steps_total': phases_total,
        }), 200

    PHASE_ICONS = {
        'recall': '\U0001f504',
        'learn': '\U0001f3af',
        'use': '\U0001f9e0',
        'read': '\U0001f4d5',
        'check': '\u2705',
        'close': '\U0001f3c1',
    }

    return jsonify({
        'has_next': True,
        'step_type': next_phase['phase'],
        'step_title': next_phase['title'],
        'step_url': _phase_url(next_phase, plan),
        'step_icon': PHASE_ICONS.get(next_phase['phase'], '\U0001f4cc'),
        'steps_done': phases_done,
        'steps_total': phases_total,
    }), 200


def _phase_url(phase: dict, plan: dict) -> str:
    """Build URL for a mission phase based on its mode and legacy data."""
    mode = phase.get('mode', '')
    cards_url = url_for('study.cards')
    if current_user.default_study_deck_id:
        cards_url = url_for('study.cards_deck', deck_id=current_user.default_study_deck_id)

    if mode in ('srs_review', 'guided_recall', 'book_vocab_recall',
                'micro_check', 'meaning_prompt', 'vocab_drill'):
        return url_for('study.cards', source='daily_plan_mix') + '&from=daily_plan'

    if mode in ('curriculum_lesson', 'lesson_practice'):
        nl = plan.get('next_lesson')
        if nl and nl.get('lesson_id'):
            return url_for('curriculum_lessons.lesson_detail',
                           lesson_id=nl['lesson_id']) + '?from=daily_plan'

    if mode in ('book_course_lesson', 'book_course_practice'):
        bc = plan.get('book_course_lesson')
        if bc and bc.get('course_id') and bc.get('module_id') and bc.get('lesson_id'):
            return url_for('book_courses.view_lesson_by_id',
                           course_id=bc['course_id'],
                           module_id=bc['module_id'],
                           lesson_id=bc['lesson_id']) + '?from=daily_plan'

    if mode in ('grammar_practice', 'targeted_quiz'):
        gt = plan.get('grammar_topic')
        if gt and gt.get('topic_id'):
            return url_for('grammar_lab.practice',
                           topic_id=gt['topic_id']) + '?from=daily_plan'
        return url_for('grammar_lab.practice') + '?from=daily_plan'

    if mode in ('book_reading', 'reading_vocab_extract'):
        book = plan.get('book_to_read')
        if book and book.get('id'):
            return url_for('books.read_book_chapters',
                           book_id=book['id']) + '?from=daily_plan'

    return url_for('words.dashboard')


def _next_step_from_legacy(daily_plan: dict, daily_summary: dict) -> tuple:
    """Return next incomplete step from legacy flat plan."""
    plan_completion = {
        'lesson': daily_summary['lessons_count'] > 0,
        'grammar': daily_summary['grammar_exercises'] > 0,
        'words': (daily_summary.get('words_reviewed', 0) > 0
                  or daily_summary.get('srs_words_reviewed', 0) > 0),
        'books': len(daily_summary.get('books_read', [])) > 0,
    }

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


@words.route('/api/streak/repair-web', methods=['POST'])
@login_required
def streak_repair_web():
    """Session-based streak repair for web dashboard."""
    from app.achievements.streak_service import find_missed_date, apply_paid_repair
    from app.telegram.queries import get_current_streak

    tz = request.json.get('tz', 'Europe/Moscow') if request.is_json else 'Europe/Moscow'

    missed = find_missed_date(current_user.id, tz=tz)
    if not missed:
        return jsonify({'success': False, 'error': 'no_missed_date'}), 400

    result = apply_paid_repair(current_user.id, missed)
    if result['success']:
        db.session.commit()
        result['new_streak'] = get_current_streak(current_user.id, tz=tz)
    else:
        db.session.rollback()

    return jsonify(result)
