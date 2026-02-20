from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class WordSearchForm(FlaskForm):
    search = StringField(_l('Search'), validators=[Optional()])
    submit = SubmitField(_l('Search'))

    class Meta:
        csrf = False  # Disable CSRF for GET forms


class WordFilterForm(FlaskForm):
    status = SelectField(_l('Статус'), choices=[
        ('all', _l('Все')),
        ('new', _l('Новые')),
        ('learning', _l('Изучаемые')),
        ('review', _l('На повторении')),
        ('mastered', _l('Выученные'))
    ], default='all', validators=[Optional()])

    letter = StringField(_l('Letter'), validators=[Optional()])
    book_id = SelectField(_l('Book'), coerce=int, validators=[Optional()])

    class Meta:
        csrf = False  # Disable CSRF for GET forms

    def __init__(self, *args, **kwargs):
        super(WordFilterForm, self).__init__(*args, **kwargs)
        from app.books.models import Book

        # Populate book choices dynamically
        books = [(0, _l('All Books'))]
        try:
            from app.utils.db import db
            # Получаем книги отсортированные по названию
            all_books = db.session.execute(
                db.select(Book).order_by(Book.title.asc())
            ).scalars().all()
            books.extend([(b.id, b.title) for b in all_books])
        except Exception:
            pass

        self.book_id.choices = books


class TopicForm(FlaskForm):
    """Форма для создания и редактирования тем"""
    name = StringField(_l('Topic Name'), validators=[DataRequired(), Length(min=2, max=100)])
    description = TextAreaField(_l('Description'), validators=[Optional(), Length(max=500)])
    submit = SubmitField(_l('Save Topic'))
    
    # CSRF enabled by default for data modification forms


class CollectionForm(FlaskForm):
    """Форма для создания и редактирования коллекций"""
    name = StringField(_l('Collection Name'), validators=[DataRequired(), Length(min=2, max=150)])
    description = TextAreaField(_l('Description'), validators=[Optional(), Length(max=500)])

    # Эти поля будут заполняться динамически через JavaScript
    topic_ids = HiddenField(_l('Selected Topics'))
    word_ids = HiddenField(_l('Selected Words'))

    submit = SubmitField(_l('Save Collection'))
    
    # CSRF enabled by default for data modification forms


class CollectionFilterForm(FlaskForm):
    """Форма для фильтрации коллекций"""
    topic = SelectField(_l('Filter by Topic'), choices=[], validators=[Optional()])
    search = StringField(_l('Search'), validators=[Optional(), Length(max=100)])
    submit = SubmitField(_l('Filter'))

    class Meta:
        csrf = False  # Disable CSRF for GET filter forms

    def __init__(self, *args, **kwargs):
        super(CollectionFilterForm, self).__init__(*args, **kwargs)
        from app.words.models import Topic
        # Динамическое заполнение списка тем
        topics = Topic.query.order_by(Topic.name).all()
        self.topic.choices = [('', _l('All Topics'))] + [(str(t.id), t.name) for t in topics]


class AnkiExportForm(FlaskForm):
    """Форма для экспорта в Anki"""
    status = SelectField(_l('Статус слов'), choices=[
        ('all', _l('Все слова')),
        ('new', _l('Новые')),
        ('learning', _l('Изучаемые')),
        ('review', _l('На повторении')),
        ('mastered', _l('Выученные'))
    ], default='all', validators=[DataRequired()])
    
    include_audio = BooleanField(_l('Включить аудио произношение'), default=True)
    
    submit = SubmitField(_l('Экспортировать'))
    
    # CSRF enabled by default for export operations
