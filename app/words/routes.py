from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy import func, or_

from app.study.models import GameScore
from app.utils.db import db
from app.words.forms import WordFilterForm, WordSearchForm
from app.words.models import CollectionWords, Topic
from app.modules.decorators import module_required

words = Blueprint('words', __name__)


@words.route('/')
@login_required
@module_required('words')
def dashboard():
    # Получение статистики по словам пользователя на основе новых моделей
    from app.study.models import UserWord
    from app.words.forms import AnkiExportForm

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
    status_stats = {'new': 0, 'learning': 0, 'review': 0, 'mastered': 0}

    for status, count in status_counts:
        status_stats[status] = count

    # Общее количество слов в коллекции
    total_words = CollectionWords.query.count()

    # Получаем недавно изученные слова с их статусами
    recent_words_query = db.session.query(
        CollectionWords,
        UserWord.status.label('user_status')
    ).outerjoin(
        UserWord, 
        (CollectionWords.id == UserWord.word_id) & (UserWord.user_id == current_user.id)
    ).order_by(
        UserWord.updated_at.desc().nullslast(),
        CollectionWords.id.desc()
    ).limit(10).all()

    # Преобразуем результат в список объектов с атрибутом user_status
    recent_words = []
    for word, user_status in recent_words_query:
        word.user_status = user_status or 'new'
        recent_words.append(word)

    # Форма для экспорта
    export_form = AnkiExportForm()

    return render_template('words/dashboard.html',
                         status_stats=status_stats,
                         total_words=total_words,
                         recent_words=recent_words,
                         export_form=export_form)


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

    # Параметры пагинации
    page = request.args.get('page', 1, type=int)
    per_page = 50  # Увеличиваем для таблицы

    # Создаем формы фильтров с параметрами запроса
    search_form = WordSearchForm(request.args)
    filter_form = WordFilterForm(request.args)

    # Формирование базового запроса с JOIN для получения статусов пользователя
    query = db.session.query(
        CollectionWords,
        UserWord.status.label('user_status')
    ).outerjoin(
        UserWord, 
        (CollectionWords.id == UserWord.word_id) & (UserWord.user_id == current_user.id)
    )

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
        else:
            query = query.filter(UserWord.status == status)

    # Применяем фильтр по букве
    if letter:
        query = query.filter(CollectionWords.english_word.ilike(f"{letter}%"))

    # Применяем фильтр по книге
    if book_id:
        from app.utils.db import word_book_link
        query = query.join(
            word_book_link,
            CollectionWords.id == word_book_link.c.word_id
        ).filter(word_book_link.c.book_id == book_id)

    # Сортировка
    query = query.order_by(CollectionWords.english_word.asc())

    # Пагинация
    words = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    # Преобразуем результат для шаблона
    word_list = []
    for word_obj, user_status in words.items:
        word_obj.user_status = user_status or 'new'
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

    return render_template(
        'words/list_optimized.html',
        words=words,
        search_form=search_form,
        filter_form=filter_form,
        status_counts=status_counts
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
    
    word.user_status = user_word.status if user_word else 'new'

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
