# app/curriculum/form.py+

from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import BooleanField, IntegerField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.books.models import Book
from app.curriculum.models import CEFRLevel, Module
from app.words.models import Collection


class CEFRLevelForm(FlaskForm):
    """Форма для создания/редактирования уровня CEFR"""
    code = StringField(_l('Code'), validators=[DataRequired(), Length(min=2, max=2)])
    name = StringField(_l('Name'), validators=[DataRequired(), Length(max=100)])
    description = TextAreaField(_l('Description'), validators=[Optional()])
    order = IntegerField(_l('Order'), validators=[Optional(), NumberRange(min=0)], default=0)
    submit = SubmitField(_l('Save'))


class ModuleForm(FlaskForm):
    """Форма для создания/редактирования модуля"""
    level_id = SelectField(_l('Level'), coerce=int, validators=[DataRequired()])
    number = IntegerField(_l('Number'), validators=[DataRequired(), NumberRange(min=1)])
    title = StringField(_l('Title'), validators=[DataRequired(), Length(max=200)])
    description = TextAreaField(_l('Description'), validators=[Optional()])
    submit = SubmitField(_l('Save'))

    def __init__(self, *args, **kwargs):
        super(ModuleForm, self).__init__(*args, **kwargs)
        self.level_id.choices = [(level.id, f"{level.code} - {level.name}")
                                 for level in CEFRLevel.query.order_by(CEFRLevel.order).all()]


class LessonForm(FlaskForm):
    """Форма для создания/редактирования урока"""
    module_id = SelectField(_l('Module'), coerce=int, validators=[DataRequired()])
    number = IntegerField(_l('Number'), validators=[DataRequired(), NumberRange(min=1)])
    type = SelectField(_l('Type'), choices=[
        ('vocabulary', _l('Vocabulary')),
        ('grammar', _l('Grammar')),
        ('quiz', _l('Quiz')),
        ('matching', _l('Matching')),
        ('text', _l('Text')),
        ('anki_cards', _l('Anki Cards')),
        ('checkpoint', _l('Checkpoint'))
    ], validators=[DataRequired()])
    title = StringField(_l('Title'), validators=[DataRequired(), Length(max=200)])
    order = IntegerField(_l('Order'), validators=[Optional(), NumberRange(min=0)], default=0)
    collection_id = SelectField(_l('Collection'), coerce=int, validators=[Optional()])
    book_id = SelectField(_l('Book'), coerce=int, validators=[Optional()])
    description = TextAreaField(_l('Description'), validators=[Optional()])
    submit = SubmitField(_l('Save'))

    def __init__(self, *args, **kwargs):
        super(LessonForm, self).__init__(*args, **kwargs)
        # Заполняем список модулей
        modules = Module.query.join(CEFRLevel).order_by(CEFRLevel.order, Module.number).all()
        self.module_id.choices = [(m.id, f"{m.level.code} - {m.title} (Module {m.number})")
                                  for m in modules]

        # Заполняем список коллекций
        self.collection_id.choices = [(0, _l('-- Выберите коллекцию --'))] + [
            (c.id, c.name) for c in Collection.query.order_by(Collection.name).all()
        ]

        # Заполняем список книг
        self.book_id.choices = [(0, _l('-- Выберите книгу --'))] + [
            (b.id, b.title) for b in Book.query.order_by(Book.title).all()
        ]


class QuizForm(FlaskForm):
    """Форма для викторины"""
    submit = SubmitField(_l('Check Answers'))


class MatchingForm(FlaskForm):
    """Форма для упражнения на сопоставление"""
    submit = SubmitField(_l('Check Matches'))


class TextReadingForm(FlaskForm):
    """Форма для подтверждения прочтения текста"""
    completed = BooleanField(
        'Я прочитал и понял текст',
        validators=[DataRequired(message='Пожалуйста, подтвердите, что вы прочитали текст')],
        render_kw={'class': 'form-check-input'}
    )
    submit = SubmitField(
        'Отметить как прочитано',
        render_kw={'class': 'btn btn-success btn-lg'}
    )


class AnkiCardsForm(FlaskForm):
    """Форма для подтверждения изучения карточек"""
    submit = SubmitField(_l('Mark as Complete'))


class LessonFeedbackForm(FlaskForm):
    """Форма для обратной связи по уроку"""
    rating = SelectField(_l('Rating'), choices=[
        (1, '1 - Very Difficult'),
        (2, '2 - Difficult'),
        (3, '3 - Normal'),
        (4, '4 - Easy'),
        (5, '5 - Very Easy')
    ], coerce=int)
    comments = TextAreaField(_l('Comments'), validators=[Optional(), Length(max=500)])
    submit = SubmitField(_l('Submit Feedback'))


class GrammarExerciseForm(FlaskForm):
    """Форма для выполнения грамматических упражнений"""
    submit = SubmitField(_l('Check Answers'))


class VocabularyReviewForm(FlaskForm):
    """Форма для подтверждения изучения словарного запаса"""
    completed = BooleanField(_l('I have learned all the words in this list'), validators=[DataRequired()])
    submit = SubmitField(_l('Mark as Complete'))


class ImportCurriculumForm(FlaskForm):
    """Форма для импорта учебного плана из JSON"""
    file = FileField(_l('JSON File'), validators=[
        FileRequired(),
        FileAllowed(['json'], _l('Only JSON files!'))
    ])
    submit = SubmitField(_l('Import'))


class CurriculumSearchForm(FlaskForm):
    """Форма для поиска по учебному плану"""
    level = SelectField(_l('CEFR Level'), choices=[], validators=[Optional()])
    module = SelectField(_l('Module'), choices=[], validators=[Optional()])
    lesson_type = SelectField(_l('Lesson Type'), choices=[
        ('', _l('All Types')),
        ('vocabulary', _l('Vocabulary')),
        ('grammar', _l('Grammar')),
        ('quiz', _l('Quiz')),
        ('matching', _l('Matching')),
        ('text', _l('Text')),
        ('anki_cards', _l('Anki Cards')),
        ('checkpoint', _l('Checkpoint'))
    ], validators=[Optional()])
    search = StringField(_l('Search'), validators=[Optional(), Length(max=100)])
    submit = SubmitField(_l('Search'))

    def __init__(self, *args, **kwargs):
        super(CurriculumSearchForm, self).__init__(*args, **kwargs)
        # Заполняем списки уровней и модулей
        self.level.choices = [(0, _l('All Levels'))] + [
            (level.id, f"{level.code} - {level.name}")
            for level in CEFRLevel.query.order_by(CEFRLevel.order).all()
        ]

        self.module.choices = [(0, _l('All Modules'))]
        if kwargs.get('formdata') and 'level' in kwargs['formdata']:
            level_id = kwargs['formdata']['level']
            if level_id and int(level_id) > 0:
                modules = Module.query.filter_by(level_id=int(level_id)).order_by(Module.number).all()
                self.module.choices.extend([
                    (m.id, f"Module {m.number}: {m.title}")
                    for m in modules
                ])
