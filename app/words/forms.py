from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import HiddenField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class WordSearchForm(FlaskForm):
    search = StringField(_l('Search'), validators=[Optional()])
    submit = SubmitField(_l('Search'))

    class Meta:
        csrf = False  # Disable CSRF for GET forms


class WordFilterForm(FlaskForm):
    status = SelectField(_l('Status'), choices=[
        (-1, _l('All')),
        (0, _l('New')),
        (1, _l('Learning')),
        (2, _l('Review')),
        (3, _l('Mastered'))
    ], coerce=int, validators=[Optional()])

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
            all_books = db.session.execute(db.select(Book)).scalars().all()
            books.extend([(b.id, b.title) for b in all_books])
        except:
            pass

        self.book_id.choices = books


class TopicForm(FlaskForm):
    """Форма для создания и редактирования тем"""
    name = StringField(_l('Topic Name'), validators=[DataRequired(), Length(min=2, max=100)])
    description = TextAreaField(_l('Description'), validators=[Optional(), Length(max=500)])
    submit = SubmitField(_l('Save Topic'))


class CollectionForm(FlaskForm):
    """Форма для создания и редактирования коллекций"""
    name = StringField(_l('Collection Name'), validators=[DataRequired(), Length(min=2, max=150)])
    description = TextAreaField(_l('Description'), validators=[Optional(), Length(max=500)])

    # Эти поля будут заполняться динамически через JavaScript
    topic_ids = HiddenField(_l('Selected Topics'))
    word_ids = HiddenField(_l('Selected Words'))

    submit = SubmitField(_l('Save Collection'))


class CollectionFilterForm(FlaskForm):
    """Форма для фильтрации коллекций"""
    topic = SelectField(_l('Filter by Topic'), choices=[], validators=[Optional()])
    search = StringField(_l('Search'), validators=[Optional(), Length(max=100)])
    submit = SubmitField(_l('Filter'))

    def __init__(self, *args, **kwargs):
        super(CollectionFilterForm, self).__init__(*args, **kwargs)
        from app.words.models import Topic
        # Динамическое заполнение списка тем
        topics = Topic.query.order_by(Topic.name).all()
        self.topic.choices = [('', _l('All Topics'))] + [(str(t.id), t.name) for t in topics]
