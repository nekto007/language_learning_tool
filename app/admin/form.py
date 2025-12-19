# app/admin/forms.py

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField, DateTimeField, FieldList, FloatField, FormField,
    IntegerField, SelectField, StringField, TextAreaField, HiddenField
)
from wtforms.validators import DataRequired, NumberRange, Optional, Length


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


# =============================================================================
# Book Course Forms - for editing DailyLesson and Task payloads
# =============================================================================

class DailyLessonForm(FlaskForm):
    """Form for editing DailyLesson basic fields"""
    slice_text = TextAreaField('Текст слайса', validators=[Optional()])  # Optional for vocabulary lessons
    lesson_type = SelectField('Тип урока', choices=[
        ('reading', 'Чтение'),
        ('vocabulary', 'Словарь'),
        ('vocabulary_review', 'Повторение словаря'),
        ('reading_mcq', 'Вопросы к тексту (MCQ)'),
        ('comprehension_mcq', 'Вопросы на понимание'),
        ('match_headings', 'Сопоставление заголовков'),
        ('open_cloze', 'Заполнение пропусков'),
        ('cloze_practice', 'Практика заполнения'),
        ('word_formation', 'Словообразование'),
        ('keyword_transform', 'Трансформация предложений'),
        ('grammar_focus', 'Грамматический фокус'),
        ('grammar_sheet', 'Грамматика'),
        ('module_test', 'Тест модуля'),
        ('final_test', 'Финальный тест'),
    ], validators=[DataRequired()])
    audio_url = StringField('URL аудио', validators=[Optional()])
    available_at = DateTimeField('Доступен с', format='%Y-%m-%dT%H:%M', validators=[Optional()])


class VocabularyCardForm(FlaskForm):
    """Subform for a single vocabulary card"""
    class Meta:
        csrf = False  # Disable CSRF for subforms

    front = StringField('Слово', validators=[DataRequired()])
    translation = StringField('Перевод', validators=[DataRequired()])
    examples = TextAreaField('Примеры (по одному на строку)', validators=[Optional()])
    level = StringField('Уровень', validators=[Optional()])


class VocabularyTaskForm(FlaskForm):
    """Form for vocabulary task payload"""
    estimated_time = IntegerField('Время (мин)', default=15, validators=[NumberRange(min=1)])
    # Cards handled via JavaScript in template


class MCQQuestionForm(FlaskForm):
    """Subform for a single MCQ question"""
    class Meta:
        csrf = False

    text = StringField('Вопрос', validators=[DataRequired()])
    option_0 = StringField('Вариант 1', validators=[DataRequired()])
    option_1 = StringField('Вариант 2', validators=[DataRequired()])
    option_2 = StringField('Вариант 3', validators=[DataRequired()])
    option_3 = StringField('Вариант 4', validators=[DataRequired()])
    correct = SelectField('Правильный ответ', choices=[
        ('0', 'Вариант 1'), ('1', 'Вариант 2'), ('2', 'Вариант 3'), ('3', 'Вариант 4')
    ], coerce=str)
    explanation = TextAreaField('Объяснение', validators=[Optional()])


class ReadingMCQTaskForm(FlaskForm):
    """Form for reading MCQ task payload"""
    pass_score = IntegerField('Проходной балл (%)', default=70, validators=[NumberRange(min=0, max=100)])
    estimated_time = IntegerField('Время (мин)', default=15, validators=[NumberRange(min=1)])
    # Questions handled via JavaScript in template


class ParagraphForm(FlaskForm):
    """Subform for match_headings paragraph"""
    class Meta:
        csrf = False

    id = IntegerField('ID', validators=[DataRequired()])
    text = TextAreaField('Текст параграфа', validators=[DataRequired()])


class HeadingForm(FlaskForm):
    """Subform for match_headings heading"""
    class Meta:
        csrf = False

    id = StringField('ID (A, B, C...)', validators=[DataRequired()])
    text = StringField('Текст заголовка', validators=[DataRequired()])
    correct_for = IntegerField('Правильный для параграфа #', validators=[Optional()])


class MatchHeadingsTaskForm(FlaskForm):
    """Form for match headings task payload"""
    estimated_time = IntegerField('Время (мин)', default=10, validators=[NumberRange(min=1)])
    # Paragraphs and headings handled via JavaScript


class GapForm(FlaskForm):
    """Subform for open cloze gap"""
    class Meta:
        csrf = False

    id = IntegerField('ID пропуска', validators=[DataRequired()])
    answer = StringField('Ответ', validators=[DataRequired()])
    hint = StringField('Подсказка', validators=[Optional()])


class OpenClozeTaskForm(FlaskForm):
    """Form for open cloze task payload"""
    text = TextAreaField('Текст с пропусками (используйте (1) ______ для пропусков)', validators=[DataRequired()])
    pass_score = IntegerField('Проходной балл (%)', default=70, validators=[NumberRange(min=0, max=100)])
    estimated_time = IntegerField('Время (мин)', default=12, validators=[NumberRange(min=1)])
    # Gaps handled via JavaScript


class WordFormationItemForm(FlaskForm):
    """Subform for word formation item"""
    class Meta:
        csrf = False

    sentence = StringField('Предложение с пропуском', validators=[DataRequired()])
    base_word = StringField('Базовое слово', validators=[DataRequired()])
    answer = StringField('Правильный ответ', validators=[DataRequired()])
    hint = StringField('Подсказка', validators=[Optional()])


class WordFormationTaskForm(FlaskForm):
    """Form for word formation task payload"""
    pass_score = IntegerField('Проходной балл (%)', default=70, validators=[NumberRange(min=0, max=100)])
    estimated_time = IntegerField('Время (мин)', default=10, validators=[NumberRange(min=1)])
    # Items handled via JavaScript


class KeywordTransformForm(FlaskForm):
    """Subform for keyword transformation item"""
    class Meta:
        csrf = False

    original = StringField('Исходное предложение', validators=[DataRequired()])
    keyword = StringField('Ключевое слово', validators=[DataRequired()])
    target = StringField('Целевое предложение с пропуском', validators=[DataRequired()])
    answer = StringField('Правильный ответ', validators=[DataRequired()])


class KeywordTransformTaskForm(FlaskForm):
    """Form for keyword transformation task payload"""
    instructions = TextAreaField('Инструкции',
                                 default='Complete the second sentence using the keyword. Use between 2-5 words.')
    pass_score = IntegerField('Проходной балл (%)', default=70, validators=[NumberRange(min=0, max=100)])
    estimated_time = IntegerField('Время (мин)', default=12, validators=[NumberRange(min=1)])
    # Sentences handled via JavaScript


class GrammarExerciseForm(FlaskForm):
    """Subform for grammar exercise"""
    class Meta:
        csrf = False

    question = StringField('Вопрос', validators=[DataRequired()])
    option_0 = StringField('Вариант 1', validators=[DataRequired()])
    option_1 = StringField('Вариант 2', validators=[DataRequired()])
    option_2 = StringField('Вариант 3', validators=[DataRequired()])
    option_3 = StringField('Вариант 4', validators=[DataRequired()])
    correct = SelectField('Правильный ответ', choices=[
        ('0', 'Вариант 1'), ('1', 'Вариант 2'), ('2', 'Вариант 3'), ('3', 'Вариант 4')
    ], coerce=str)
    explanation = TextAreaField('Объяснение', validators=[Optional()])


class GrammarSheetTaskForm(FlaskForm):
    """Form for grammar sheet task payload"""
    topic = StringField('Тема грамматики', validators=[DataRequired()])
    explanation = TextAreaField('Объяснение правила', validators=[DataRequired()])
    examples = TextAreaField('Примеры (по одному на строку)', validators=[Optional()])
    pass_score = IntegerField('Проходной балл (%)', default=70, validators=[NumberRange(min=0, max=100)])
    estimated_time = IntegerField('Время (мин)', default=18, validators=[NumberRange(min=1)])
    # Exercises handled via JavaScript


class FinalTestTaskForm(FlaskForm):
    """Form for final test task payload"""
    instructions = TextAreaField('Инструкции',
                                 default='Complete all sections. You need 70% to pass this module.')
    pass_score = IntegerField('Проходной балл (%)', default=70, validators=[NumberRange(min=0, max=100)])
    estimated_time = IntegerField('Время (мин)', default=25, validators=[NumberRange(min=1)])
    # Sections handled via JavaScript


# =============================================================================
# Module lessons_data forms
# =============================================================================

class LessonDataForm(FlaskForm):
    """Form for a single lesson in lessons_data JSON"""
    class Meta:
        csrf = False

    lesson_number = IntegerField('Номер урока', validators=[DataRequired(), NumberRange(min=1)])
    lesson_type = SelectField('Тип урока', choices=[
        ('vocabulary', 'Словарь'),
        ('grammar', 'Грамматика'),
        ('quiz', 'Викторина'),
        ('matching', 'Сопоставление'),
        ('text', 'Текст'),
    ], validators=[DataRequired()])
    title = StringField('Название', validators=[DataRequired()])
    description = TextAreaField('Описание', validators=[Optional()])
