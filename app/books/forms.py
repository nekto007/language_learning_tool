# app/books/forms.py
from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class BookContentForm(FlaskForm):
    """
    Form for adding content to an existing book or creating a new one
    """
    title = StringField(_l('Title'), validators=[DataRequired(), Length(max=255)])

    author = StringField(_l('Author'), validators=[Optional(), Length(max=255)])

    level = SelectField(_l('Book Level'), choices=[
        ('', _l('Not specified')),
        ('A1', _l('A1 - Beginner')),
        ('A2', _l('A2 - Elementary')),
        ('B1', _l('B1 - Intermediate')),
        ('B2', _l('B2 - Upper Intermediate')),
        ('C1', _l('C1 - Advanced')),
        ('C2', _l('C2 - Proficiency'))
    ], default='')

    cover_image = FileField(_l('Book Cover'), validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Only image files are allowed!')
    ])

    file = FileField(_l('Upload Book File'), validators=[
        FileAllowed(['txt', 'fb2', 'epub', 'pdf', 'docx'], 'Only supported book formats are allowed!')
    ])

    format_type = SelectField('Formatting Style', choices=[
        ('auto', 'Auto-detect (Preserve Original Formatting)'),
        ('simple', 'Simple Formatting (Paragraphs Only)'),
        ('enhanced', 'Enhanced Reading (Optimized for Language Learning)')
    ], default='enhanced')

    content = TextAreaField(_l('Content'))

    submit = SubmitField(_l('Save'))
