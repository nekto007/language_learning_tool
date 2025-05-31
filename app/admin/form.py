# app/admin/forms.py

from flask_wtf import FlaskForm
from wtforms import IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, NumberRange, Optional


class CEFRLevelForm(FlaskForm):
    """Form for CEFR levels"""
    code = StringField('Код уровня', validators=[DataRequired()])
    name = StringField('Название', validators=[DataRequired()])
    description = TextAreaField('Описание', validators=[Optional()])
    order = IntegerField('Порядок', validators=[NumberRange(min=0)], default=0)


class ModuleForm(FlaskForm):
    """Form for modules"""
    level_id = SelectField('Уровень CEFR', coerce=int, validators=[DataRequired()])
    number = IntegerField('Номер модуля', validators=[DataRequired(), NumberRange(min=1)])
    title = StringField('Название', validators=[DataRequired()])
    description = TextAreaField('Описание', validators=[Optional()])


class LessonForm(FlaskForm):
    """Form for creating and editing lessons"""
    module_id = SelectField('Модуль', coerce=int, validators=[DataRequired()])
    number = IntegerField('Номер урока', validators=[DataRequired(), NumberRange(min=1)])
    title = StringField('Название', validators=[DataRequired()])
    type = SelectField('Тип урока', choices=[
        ('vocabulary', 'Словарь'),
        ('grammar', 'Грамматика'),
        ('quiz', 'Викторина'),
        ('matching', 'Сопоставление'),
        ('text', 'Текст'),
        ('card', 'Карточка'),
        ('checkpoint', 'Контрольная точка'),
    ], validators=[DataRequired()])
    order = IntegerField('Порядок отображения', validators=[NumberRange(min=0)], default=0)
    description = TextAreaField('Описание', validators=[Optional()])

    # Fields for specific lesson types
    collection_id = SelectField('Коллекция слов', coerce=int, validators=[Optional()])
    book_id = SelectField('Книга', coerce=int, validators=[Optional()])


class TextLessonForm(FlaskForm):
    """Form for editing text lessons"""
    book_id = SelectField('Книга', coerce=int, validators=[Optional()])
    starting_paragraph = IntegerField('Начальный параграф', validators=[NumberRange(min=0)], default=0)
    ending_paragraph = IntegerField('Конечный параграф', validators=[NumberRange(min=0)], default=0)


class MatchingLessonForm(FlaskForm):
    """Form for editing matching lessons"""
    time_limit = IntegerField('Ограничение времени (секунды)', validators=[NumberRange(min=0)], default=0)
    # Pairs will be handled separately in the view function


class QuizLessonForm(FlaskForm):
    """Form for editing quiz lessons"""
    passing_score = IntegerField('Проходной балл (%)', validators=[NumberRange(min=0, max=100)], default=70)
    # Questions will be handled separately in the view function


class GrammarLessonForm(FlaskForm):
    """Form for editing grammar lessons"""
    rule = TextAreaField('Правило грамматики', validators=[DataRequired()])
    # Examples and exercises will be handled separately in the view function
