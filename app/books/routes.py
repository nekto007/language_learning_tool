from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.utils.db import db
from app.books.models import Book
from sqlalchemy import func, desc
from app.utils.db import word_book_link, user_word_status
from app.words.models import CollectionWords

books = Blueprint('books', __name__)


@books.route('/books')
@login_required
def book_list():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    # Get books with word counts
    query = db.select(Book).order_by(Book.title)

    # Execute paginated query
    pagination = db.paginate(
        query,
        page=page,
        per_page=per_page,
        error_out=False
    )

    book_items = pagination.items

    # Get word stats for each book
    book_stats = {}
    for book in book_items:
        # Get total words assigned to the user from this book
        words_status_query = db.select(
            func.count().label('count'),
            user_word_status.c.status
        ).select_from(
            word_book_link
        ).join(
            user_word_status,
            (word_book_link.c.word_id == user_word_status.c.word_id) &
            (user_word_status.c.user_id == current_user.id)
        ).where(
            word_book_link.c.book_id == book.id
        ).group_by(
            user_word_status.c.status
        )

        word_status_counts = db.session.execute(words_status_query).all()

        # Initialize statistics
        stats = {
            'total': book.unique_words,
            'new': book.unique_words,  # Default all to new, we'll subtract known words
            'known': 0,
            'queued': 0,
            'active': 0,
            'mastered': 0
        }

        # Update with actual status counts
        for count, status in word_status_counts:
            if status == 1:
                stats['known'] = count
                stats['new'] -= count
            elif status == 2:
                stats['queued'] = count
                stats['new'] -= count
            elif status == 3:
                stats['active'] = count
                stats['new'] -= count
            elif status == 4:
                stats['mastered'] = count
                stats['new'] -= count

        book_stats[book.id] = stats

    return render_template(
        'books/list.html',
        books=book_items,
        pagination=pagination,
        book_stats=book_stats
    )


@books.route('/books/<int:book_id>')
@login_required
def book_details(book_id):
    book = Book.query.get_or_404(book_id)

    # Get word statistics
    word_stats_query = db.select(
        user_word_status.c.status,
        func.count().label('count')
    ).join(
        word_book_link,
        user_word_status.c.word_id == word_book_link.c.word_id
    ).where(
        (word_book_link.c.book_id == book_id) &
        (user_word_status.c.user_id == current_user.id)
    ).group_by(
        user_word_status.c.status
    )

    status_counts = db.session.execute(word_stats_query).all()

    # Build stats dictionary
    word_stats = {
        'total': book.unique_words,
        'new': book.unique_words,  # Default all to new, we'll subtract known words
        'known': 0,
        'queued': 0,
        'active': 0,
        'mastered': 0
    }

    # Update with actual status counts
    for status, count in status_counts:
        if status == 1:
            word_stats['known'] = count
            word_stats['new'] -= count
        elif status == 2:
            word_stats['queued'] = count
            word_stats['new'] -= count
        elif status == 3:
            word_stats['active'] = count
            word_stats['new'] -= count
        elif status == 4:
            word_stats['mastered'] = count
            word_stats['new'] -= count

    # Calculate progress percentage
    if book.unique_words > 0:
        progress = int(((word_stats['known'] + word_stats['mastered']) / book.unique_words) * 100)
    else:
        progress = 0

    # Get most frequent words in this book
    frequent_words_query = db.select(
        CollectionWords,
        word_book_link.c.frequency
    ).join(
        word_book_link,
        CollectionWords.id == word_book_link.c.word_id
    ).where(
        word_book_link.c.book_id == book_id
    ).order_by(
        desc(word_book_link.c.frequency)
    ).limit(20)

    frequent_words = db.session.execute(frequent_words_query).all()

    # Get word statuses
    word_statuses = {}
    for word, _ in frequent_words:
        word_statuses[word.id] = current_user.get_word_status(word.id)

    return render_template(
        'books/details.html',
        book=book,
        word_stats=word_stats,
        progress=progress,
        frequent_words=frequent_words,
        word_statuses=word_statuses
    )


@books.route('/books/<int:book_id>/words')
@login_required
def book_words(book_id):
    book = Book.query.get_or_404(book_id)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    status = request.args.get('status', type=int)

    # Build base query
    query = db.select(
        CollectionWords,
        word_book_link.c.frequency
    ).join(
        word_book_link,
        CollectionWords.id == word_book_link.c.word_id
    ).where(
        word_book_link.c.book_id == book_id
    )

    # Apply status filter if provided
    if status is not None:
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

    # Apply sorting
    sort_by = request.args.get('sort', 'frequency')
    sort_order = request.args.get('order', 'desc')

    if sort_by == 'frequency':
        query = query.order_by(
            desc(word_book_link.c.frequency) if sort_order == 'desc'
            else word_book_link.c.frequency
        )
    elif sort_by == 'english_word':
        query = query.order_by(
            CollectionWords.english_word.desc() if sort_order == 'desc'
            else CollectionWords.english_word
        )
    elif sort_by == 'level':
        query = query.order_by(
            CollectionWords.level.desc() if sort_order == 'desc'
            else CollectionWords.level
        )

    # Execute paginated query
    pagination = db.paginate(
        query,
        page=page,
        per_page=per_page,
        error_out=False
    )

    book_words = pagination.items

    # Get word statuses
    word_statuses = {}
    for word, _ in book_words:
        word_statuses[word.id] = current_user.get_word_status(word.id)

    return render_template(
        'books/words.html',
        book=book,
        book_words=book_words,
        pagination=pagination,
        word_statuses=word_statuses,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order
    )


@books.route('/books/<int:book_id>/add-to-queue', methods=['POST'])
@login_required
def add_book_to_queue(book_id):
    book = Book.query.get_or_404(book_id)

    # Get words from this book that are not already in queue, active, or mastered
    words_query = db.select(
        CollectionWords.id
    ).join(
        word_book_link,
        CollectionWords.id == word_book_link.c.word_id
    ).where(
        word_book_link.c.book_id == book_id
    ).outerjoin(
        user_word_status,
        (CollectionWords.id == user_word_status.c.word_id) &
        (user_word_status.c.user_id == current_user.id)
    ).where(
        (user_word_status.c.status.is_(None)) |
        (user_word_status.c.status == 0) |
        (user_word_status.c.status == 1)  # Include "known" words too
    )

    word_ids = [row[0] for row in db.session.execute(words_query).all()]

    # Add words to queue (status 2)
    for word_id in word_ids:
        current_user.set_word_status(word_id, 2)

    flash(f'Added {len(word_ids)} words from "{book.title}" to your learning queue.', 'success')
    return redirect(url_for('books.book_details', book_id=book_id))
