from flask import redirect, render_template, url_for
from flask_login import current_user

from app.landing import landing_bp
from app.landing.analytics import get_or_create_visit
from app.landing.previews import PREVIEWS_BY_ID, pick_preview
from app.utils.db import db


@landing_bp.route('/')
def index():
    """
    Public landing page.
    Redirects authenticated users to dashboard.
    """
    if current_user.is_authenticated:
        from app.modules.service import ModuleService
        if ModuleService.is_module_enabled_for_user(current_user.id, 'words'):
            return redirect(url_for('words.dashboard'))

    # Get platform statistics for social proof
    from sqlalchemy import func

    from app.auth.models import User
    from app.curriculum.models import LessonProgress
    from app.grammar_lab.models import GrammarTopic
    from app.words.models import CollectionWords

    stats = {
        'users': User.query.filter_by(active=True).count(),
        'words': CollectionWords.query.count(),
        'levels': 5,  # A1, A2, B1, B2, C1
        'lessons_completed': db.session.query(func.count(LessonProgress.id)).filter(
            LessonProgress.status == 'completed'
        ).scalar() or 0,
        'grammar_topics': GrammarTopic.query.count(),
    }

    # Word of the Day (deterministic based on date)
    import hashlib
    from datetime import date
    today_seed = int(hashlib.md5(str(date.today()).encode()).hexdigest(), 16)
    _wotd_filter = [
        CollectionWords.frequency_rank > 0,
        CollectionWords.sentences.isnot(None),
        CollectionWords.russian_word.isnot(None),
    ]
    total_words = CollectionWords.query.filter(*_wotd_filter).count()
    word_of_day = None
    if total_words > 0:
        offset = today_seed % total_words
        word_of_day = (
            CollectionWords.query
            .filter(*_wotd_filter)
            .order_by(CollectionWords.frequency_rank.asc(), CollectionWords.id.asc())
            .offset(offset)
            .limit(1)
            .first()
        )

    preview = pick_preview()
    visit = get_or_create_visit(preview['id']) if not current_user.is_authenticated else None
    if visit:
        preview = PREVIEWS_BY_ID[visit.preview_id]
    recorded_events = ','.join(name for name, timestamp in (
        ('preview_started', visit.started_at if visit else None),
        ('preview_answered', visit.answered_at if visit else None),
        ('registration_clicked', visit.registration_clicked_at if visit else None),
    ) if timestamp is not None)
    return render_template(
        'landing/index.html', stats=stats, word_of_day=word_of_day,
        preview=preview, preview_event_url=url_for('landing.preview_event') if visit else '',
        preview_recorded_events=recorded_events,
    )
