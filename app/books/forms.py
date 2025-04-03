# app/books/forms.py

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class BookContentForm(FlaskForm):
    """
    Form for adding content to an existing book or creating a new one
    """
    title = StringField('Title', validators=[DataRequired(), Length(max=255)])

    cover_image = FileField('Book Cover', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Only image files are allowed!')
    ])

    file = FileField('Upload Book File', validators=[
        FileAllowed(['txt', 'fb2', 'epub', 'pdf', 'docx'], 'Only supported book formats are allowed!')
    ])

    format_type = SelectField('Formatting Style', choices=[
        ('auto', 'Auto-detect (Preserve Original Formatting)'),
        ('simple', 'Simple Formatting (Paragraphs Only)'),
        ('enhanced', 'Enhanced Reading (Optimized for Language Learning)')
    ], default='enhanced')

    content = TextAreaField('Content')

    submit = SubmitField('Save')
