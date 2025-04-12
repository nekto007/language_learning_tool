from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from app.study.models import GameScore
from app.utils.db import db
from app.words.forms import WordFilterForm, WordSearchForm
from app.words.models import CollectionWords

words = Blueprint('words', __name__)


@words.route('/')
@login_required
def dashboard():
    # Get user's word statistics
    from app.utils.db import user_word_status

    status_counts = db.session.execute(
        db.select(
            user_word_status.c.status,
            func.count().label('count')
        ).where(
            user_word_status.c.user_id == current_user.id
        ).group_by(
            user_word_status.c.status
        )
    ).all()

    # Convert to dictionary for easier access
    status_stats = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}  # Default values for all statuses
    for status, count in status_counts:
        status_stats[status] = count

    # Get total words count
    total_words = CollectionWords.query.count()

    # Calculate progress percentage
    progress = 0
    if total_words > 0:
        learned_words = sum(status_stats.values())
        progress = int((learned_words / total_words) * 100)

    # Get recently studied words
    recent_words = db.session.execute(
        db.select(CollectionWords)
        .join(user_word_status, CollectionWords.id == user_word_status.c.word_id)
        .where(user_word_status.c.user_id == current_user.id)
        .order_by(user_word_status.c.last_updated.desc())
        .limit(5)
    ).scalars().all()

    user_best_matching = GameScore.query.filter_by(
        user_id=current_user.id,
        game_type='matching'
    ).order_by(GameScore.score.desc()).first()

    user_best_quiz = GameScore.query.filter_by(
        user_id=current_user.id,
        game_type='quiz'
    ).order_by(GameScore.score.desc()).first()

    return render_template(
        'dashboard.html',
        user_best_matching=user_best_matching,
        user_best_quiz=user_best_quiz,
        status_stats=status_stats,
        total_words=total_words,
        progress=progress,
        recent_words=recent_words
    )


@words.route('/words')
@login_required
def word_list():
    # Get filter parameters
    search = request.args.get('search', '')
    status = request.args.get('status', type=int)
    letter = request.args.get('letter', '')
    book_id = request.args.get('book_id', type=int)

    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Get sorting parameters
    sort_field = request.args.get('sort', 'english_word')
    sort_order = request.args.get('order', 'asc')

    # Create filter forms with the request parameters
    search_form = WordSearchForm(request.args)
    filter_form = WordFilterForm(request.args)

    # Build query
    query = db.select(CollectionWords)

    # Apply search filter if provided
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                CollectionWords.english_word.like(search_term),
                CollectionWords.russian_word.like(search_term)
            )
        )

    # Apply status filter if provided
    if status is not None and status != -1:  # -1 means "All statuses"
        from app.utils.db import user_word_status
        if status == 0:  # New/Unclassified
            # Words that don't have a status entry or have status 0
            subquery = db.select(user_word_status.c.word_id).where(
                (user_word_status.c.user_id == current_user.id) &
                (user_word_status.c.status != 0)
            ).scalar_subquery()

            query = query.where(CollectionWords.id.not_in(subquery))
        else:
            query = query.join(
                user_word_status,
                (CollectionWords.id == user_word_status.c.word_id) &
                (user_word_status.c.user_id == current_user.id)
            ).where(user_word_status.c.status == status)

    # Apply letter filter if provided
    if letter:
        query = query.where(CollectionWords.english_word.ilike(f"{letter}%"))

    # Apply book filter if provided
    if book_id:
        from app.utils.db import word_book_link
        query = query.join(
            word_book_link,
            CollectionWords.id == word_book_link.c.word_id
        ).where(word_book_link.c.book_id == book_id)

    # Apply sorting
    if sort_field == 'english_word':
        query = query.order_by(
            CollectionWords.english_word.asc() if sort_order == 'asc'
            else CollectionWords.english_word.desc()
        )
    elif sort_field == 'level':
        query = query.order_by(
            CollectionWords.level.asc() if sort_order == 'asc'
            else CollectionWords.level.desc()
        )

    # Execute paginated query
    pagination = db.paginate(
        query,
        page=page,
        per_page=per_page,
        error_out=False
    )

    words = pagination.items

    # Get status for each word
    word_statuses = {}
    for word in words:
        word_statuses[word.id] = current_user.get_word_status(word.id)

    # Get available books for filter dropdown
    from app.books.models import Book
    books = Book.query.all()

    return render_template(
        'words/list.html',
        words=words,
        word_statuses=word_statuses,
        pagination=pagination,
        search_form=search_form,
        filter_form=filter_form,
        books=books,
        sort_field=sort_field,
        sort_order=sort_order
    )


@words.route('/words/<int:word_id>')
@login_required
def word_details(word_id):
    word = CollectionWords.query.get_or_404(word_id)
    status = current_user.get_word_status(word_id)

    # Get books containing this word
    from app.utils.db import word_book_link
    from app.books.models import Book

    books_query = db.select(Book, word_book_link.c.frequency) \
        .join(word_book_link, Book.id == word_book_link.c.book_id) \
        .where(word_book_link.c.word_id == word_id) \
        .order_by(word_book_link.c.frequency.desc())

    books = db.session.execute(books_query).all()

    # Get related phrasal verbs
    phrasal_verbs = word.phrasal_verbs

    return render_template(
        'words/details.html',
        word=word,
        status=status,
        books=books,
        phrasal_verbs=phrasal_verbs
    )


@words.route('/update-word-status/<int:word_id>/<int:status>', methods=['POST'])
@login_required
def update_word_status(word_id, status):
    word = CollectionWords.query.get_or_404(word_id)
    current_user.set_word_status(word_id, status)

    flash(f'Status for word "{word.english_word}" updated successfully.', 'success')

    # Redirect back to the referring page
    next_page = request.args.get('next') or request.referrer or url_for('words.word_list')
    return redirect(next_page)
