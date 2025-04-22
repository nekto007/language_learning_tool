from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, HiddenField, SubmitField
from wtforms.validators import Optional
from flask_babel import lazy_gettext as _l


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
