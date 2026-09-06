from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, RadioField, SelectField, SubmitField
from wtforms.validators import DataRequired, NumberRange


class StudySettingsForm(FlaskForm):
    """
    Form for user study settings
    """
    new_words_per_day = IntegerField(_l('New Words Per Day'),
                                     validators=[DataRequired(),
                                                 NumberRange(min=1, max=50)],
                                     default=20)

    reviews_per_day = IntegerField(_l('Reviews Per Day'),
                                   validators=[DataRequired(),
                                               NumberRange(min=5, max=500)],
                                   default=200)

    include_translations = BooleanField(_l('Show Translations'), default=True)
    include_examples = BooleanField(_l('Show Examples'), default=True)
    include_audio = BooleanField(_l('Play Audio'), default=True)

    show_hint_time = IntegerField(_l('Show Hint After (seconds)'),
                                  validators=[DataRequired(),
                                              NumberRange(min=0, max=60)],
                                  default=10)
    # Lesson audit item 14: explicit pace (stored on User.plan_difficulty) and a
    # personal daily reading goal (0 = reading stays optional in the plan).
    lessons_per_day = RadioField(_l('Lessons Per Day'),
                                 choices=[('1', _l('1 урок')), ('2', _l('2 урока')), ('3', _l('3 урока'))],
                                 default='2',
                                 validators=[DataRequired()])
    reading_minutes_per_day = SelectField(_l('Daily Reading Goal'),
                                          choices=[(0, _l('По желанию, без нормы')), (5, _l('5 минут')),
                                                   (10, _l('10 минут')), (15, _l('15 минут'))],
                                          coerce=int, default=0)

    submit = SubmitField(_l('Save Settings'))


class StudySessionForm(FlaskForm):
    """
    Form for configuring a new study session
    """
    session_type = SelectField(_l('Study Mode'),
                               choices=[
                                   ('cards', _l('Flashcards (Anki-style)')),
                                   ('quiz', _l('Quiz Mode')),
                                   ('matching', _l('Matching Game'))
                               ],
                               default='cards')

    word_source = SelectField(_l('Words Source'),
                              choices=[
                                  ('new', _l('New Words')),
                                  ('learning', _l('Words in Learning')),
                                  ('all', _l('Mixed (New & Review)'))
                              ],
                              default='learning')

    submit = SubmitField(_l('Start Session'))
