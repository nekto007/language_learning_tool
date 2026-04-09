from flask import redirect, render_template, url_for
from flask_login import current_user

from app.landing import landing_bp
from app.utils.db import db


@landing_bp.route('/')
def index():
    """
    Public landing page.
    Redirects authenticated users to dashboard.
    """
    if current_user.is_authenticated:
        return redirect(url_for('words.dashboard'))

    # Get platform statistics for social proof
    from app.auth.models import User
    from app.words.models import CollectionWords
    from app.curriculum.models import CEFRLevel, LessonProgress, Lessons
    from app.grammar_lab.models import GrammarTopic
    from sqlalchemy import func

    stats = {
        'users': User.query.filter_by(active=True).count(),
        'words': CollectionWords.query.count(),
        'levels': 7,  # A0, A1, A2, B1, B2, C1, C2
        'lessons_completed': db.session.query(func.count(LessonProgress.id)).filter(
            LessonProgress.status == 'completed'
        ).scalar() or 0,
        'grammar_topics': GrammarTopic.query.count(),
    }

    # Word of the Day (deterministic based on date)
    from datetime import date
    import hashlib
    today_seed = int(hashlib.md5(str(date.today()).encode()).hexdigest(), 16)
    total_words = CollectionWords.query.filter(
        CollectionWords.frequency_rank > 0,
        CollectionWords.sentences.isnot(None),
    ).count()
    word_of_day = None
    if total_words > 0:
        offset = today_seed % total_words
        word_of_day = (
            CollectionWords.query
            .filter(CollectionWords.frequency_rank > 0, CollectionWords.sentences.isnot(None))
            .order_by(CollectionWords.frequency_rank.asc())
            .offset(offset)
            .limit(1)
            .first()
        )

    return render_template('landing/index.html', stats=stats, word_of_day=word_of_day)
