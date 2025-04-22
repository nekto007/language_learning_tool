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
    # Получение статистики по словам пользователя на основе новых моделей
    from app.study.models import UserWord

    # Получаем количество слов в каждом статусе
    status_counts = db.session.query(
        UserWord.status,
        func.count(UserWord.id).label('count')
    ).filter(
        UserWord.user_id == current_user.id
    ).group_by(
        UserWord.status
    ).all()

    # Преобразуем в словарь для более удобного доступа
    # Используем строковые статусы из новой модели
    status_stats = {'new': 0, 'learning': 0, 'review': 0, 'mastered': 0}
    # Для обратной совместимости добавим числовые индексы
    int_status_stats = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}

    for status, count in status_counts:
        status_stats[status] = count
        # Преобразуем строковые статусы в числовые для обратной совместимости
        if status == 'new':
            int_status_stats[0] = count
        elif status == 'learning':
            int_status_stats[1] = count
        elif status == 'review':
            int_status_stats[2] = count
        elif status == 'mastered':
            int_status_stats[3] = count

    # Общее количество слов
    total_words = CollectionWords.query.count()

    # Считаем процент прогресса
    progress = 0
    if total_words > 0:
        learned_words = UserWord.query.filter_by(user_id=current_user.id).count()
        progress = int((learned_words / total_words) * 100)

    # Получаем недавно изученные слова
    recent_words = db.session.query(CollectionWords) \
        .join(UserWord, CollectionWords.id == UserWord.word_id) \
        .filter(UserWord.user_id == current_user.id) \
        .order_by(UserWord.created_at.desc()) \
        .limit(5) \
        .all()

    # Получаем лучшие результаты в играх
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
        status_stats=int_status_stats,
        new_status_stats=status_stats,
        total_words=total_words,
        progress=progress,
        recent_words=recent_words
    )


@words.route('/words')
@login_required
def word_list():
    # Получение параметров фильтра
    search = request.args.get('search', '')
    status = request.args.get('status', type=int)
    letter = request.args.get('letter', '')
    book_id = request.args.get('book_id', type=int)

    # Параметры пагинации
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Параметры сортировки
    sort_field = request.args.get('sort', 'english_word')
    sort_order = request.args.get('order', 'asc')

    # Создаем формы фильтров с параметрами запроса
    search_form = WordSearchForm(request.args)
    filter_form = WordFilterForm(request.args)

    # Формирование запроса
    query = db.select(CollectionWords)

    # Применяем фильтр поиска, если указан
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                CollectionWords.english_word.like(search_term),
                CollectionWords.russian_word.like(search_term)
            )
        )

    # Применяем фильтр статуса, если указан
    if status is not None and status != -1:  # -1 означает "Все статусы"
        from app.study.models import UserWord
        from app.utils.db import status_to_string

        status_str = status_to_string(status)

        if status == 0:  # Новые/Неклассифицированные
            # Слова, для которых у пользователя еще нет статуса или статус 'new'
            existing_word_ids = db.session.query(UserWord.word_id).filter(
                UserWord.user_id == current_user.id
            ).subquery()

            query = query.where(~CollectionWords.id.in_(existing_word_ids))
        else:
            # Слова с конкретным статусом
            query = query.join(
                UserWord,
                (CollectionWords.id == UserWord.word_id) &
                (UserWord.user_id == current_user.id)
            ).where(UserWord.status == status_str)

    # Применяем фильтр по первой букве, если указан
    if letter:
        query = query.where(CollectionWords.english_word.ilike(f"{letter}%"))

    # Применяем фильтр по книге, если указан
    if book_id:
        from app.utils.db import word_book_link
        query = query.join(
            word_book_link,
            CollectionWords.id == word_book_link.c.word_id
        ).where(word_book_link.c.book_id == book_id)

    # Применяем сортировку
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

    # Выполняем запрос с пагинацией
    pagination = db.paginate(
        query,
        page=page,
        per_page=per_page,
        error_out=False
    )

    words = pagination.items

    # Получаем статус для каждого слова, используя обновленный метод
    word_statuses = {}
    for word in words:
        word_statuses[word.id] = current_user.get_word_status(word.id)

    # Получаем доступные книги для выпадающего списка
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

    # Используем обновленный метод set_word_status из модели User
    # Этот метод должен быть обновлен для работы с новыми моделями
    current_user.set_word_status(word_id, status)

    flash(f'Status for word "{word.english_word}" updated successfully.', 'success')

    # Перенаправляем обратно на страницу, с которой пришел запрос
    next_page = request.args.get('next') or request.referrer or url_for('words.word_list')
    return redirect(next_page)
