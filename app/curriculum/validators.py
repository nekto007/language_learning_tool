# app/curriculum/validators.py

from typing import Any, Dict, Optional

from marshmallow import Schema, ValidationError, fields, validate, validates_schema
from marshmallow.decorators import post_load


class VocabularyItemSchema(Schema):
    """Schema for vocabulary lesson items"""
    word = fields.Str(required=False)
    front = fields.Str(required=False)
    back = fields.Str(required=False)
    translation = fields.Str(required=False)
    example = fields.Str(required=False)
    hint = fields.Str(required=False)
    usage = fields.Str(required=False)  # Добавляем поле usage
    status = fields.Str(required=False)  # Добавляем поле status

    @validates_schema
    def validate_word_fields(self, data, **kwargs):
        if not data.get('word') and not data.get('front'):
            raise ValidationError('Either "word" or "front" field is required')


class VocabularyContentSchema(Schema):
    """Schema for vocabulary lesson content"""
    words = fields.List(fields.Nested(VocabularyItemSchema), required=False)
    items = fields.List(fields.Nested(VocabularyItemSchema), required=False)
    settings = fields.Dict(required=False)

    @validates_schema
    def validate_content(self, data, **kwargs):
        if not data.get('words') and not data.get('items'):
            raise ValidationError('Either "words" or "items" field is required')


class GrammarContentSchema(Schema):
    """Schema for grammar lesson content"""
    title = fields.Str(required=False, validate=validate.Length(min=1, max=200))
    content = fields.Str(required=False, validate=validate.Length(min=1))
    rule = fields.Str(required=False)  # Alternative field name
    text = fields.Str(required=False)  # Alternative field name
    description = fields.Str(required=False)  # Alternative field name
    examples = fields.List(fields.Raw(), required=False)  # Accept both strings and dicts
    exercises = fields.List(fields.Dict(), required=False)
    rules = fields.List(fields.Str(), required=False)

    @validates_schema
    def validate_grammar_content(self, data, **kwargs):
        # Require at least one content field
        if not any([data.get('content'), data.get('rule'), data.get('text'),
                    data.get('title'), data.get('description')]):
            raise ValidationError('At least one content field is required')


class QuizQuestionSchema(Schema):
    """Schema for quiz questions"""
    type = fields.Str(required=False, validate=validate.OneOf(
        ['multiple_choice', 'true_false', 'fill_blank', 'fill_in_blank', 'translation', 'reorder']))
    question = fields.Str(required=False, validate=validate.Length(min=1, max=500))
    prompt = fields.Str(required=False, validate=validate.Length(min=1, max=500))  # Alternative to question
    options = fields.List(
        fields.Str(),
        required=False,  # Not required for all question types
        validate=validate.Length(min=2, max=6)
    )
    correct = fields.Int(required=False, validate=validate.Range(min=0, max=5))
    correct_index = fields.Int(required=False, validate=validate.Range(min=0, max=5))  # Alternative to correct
    correct_answer = fields.Raw(required=False)  # Can be string, bool, or list
    answer = fields.Raw(required=False)  # Alternative to correct_answer
    alternative_answers = fields.List(fields.Str(), required=False)
    explanation = fields.Str(required=False)
    hint = fields.Str(required=False)
    words = fields.List(fields.Str(), required=False)  # For reorder type questions

    @validates_schema
    def validate_question_fields(self, data, **kwargs):
        # Must have either 'question' or 'prompt'
        if not data.get('question') and not data.get('prompt'):
            raise ValidationError('Either "question" or "prompt" field is required')

        # Validate based on question type
        q_type = data.get('type', 'multiple_choice')

        if q_type == 'multiple_choice':
            if not data.get('options'):
                raise ValidationError('Multiple choice questions require "options" field')

            # Must have either 'correct' or 'correct_index'
            correct_idx = data.get('correct') if data.get('correct') is not None else data.get('correct_index')
            if correct_idx is None:
                raise ValidationError('Multiple choice questions require "correct" or "correct_index" field')

            if correct_idx >= len(data.get('options', [])):
                raise ValidationError('Correct answer index is out of range')

        elif q_type in ['true_false']:
            # Must have either 'correct_answer' or 'answer'
            if data.get('correct_answer') is None and data.get('answer') is None:
                raise ValidationError('True/false questions require "correct_answer" or "answer" field')

        elif q_type in ['fill_blank', 'fill_in_blank', 'translation']:
            # Must have either 'correct_answer' or 'answer'
            if not data.get('correct_answer') and not data.get('answer'):
                raise ValidationError(f'{q_type} questions require "correct_answer" or "answer" field')

        elif q_type == 'reorder':
            # Must have 'words' array and 'correct_answer'
            if not data.get('words'):
                raise ValidationError('Reorder questions require "words" field')
            if not data.get('correct_answer'):
                raise ValidationError('Reorder questions require "correct_answer" field')


class QuizContentSchema(Schema):
    """Schema for quiz lesson content"""
    questions = fields.List(
        fields.Nested(QuizQuestionSchema),
        required=False,
        validate=validate.Length(min=1)
    )
    exercises = fields.List(
        fields.Nested(QuizQuestionSchema),
        required=False,
        validate=validate.Length(min=1)
    )
    time_limit = fields.Int(required=False, validate=validate.Range(min=0))
    passing_score = fields.Int(
        required=False,
        validate=validate.Range(min=0, max=100)
    )
    passing_score_percent = fields.Int(
        required=False,
        validate=validate.Range(min=0, max=100)
    )
    shuffle_questions = fields.Bool(required=False)
    shuffle_options = fields.Bool(required=False)

    @validates_schema
    def validate_quiz_content(self, data, **kwargs):
        # Must have either 'questions' or 'exercises'
        if not data.get('questions') and not data.get('exercises'):
            raise ValidationError('Either "questions" or "exercises" field is required')

    @post_load
    def normalize_fields(self, data, **kwargs):
        # Normalize 'exercises' to 'questions'
        if 'exercises' in data and 'questions' not in data:
            data['questions'] = data.pop('exercises')
        return data


class MatchingPairSchema(Schema):
    """Schema for matching pairs"""
    left = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    right = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    hint = fields.Str(required=False)


class MatchingContentSchema(Schema):
    """Schema for matching lesson content"""
    pairs = fields.List(
        fields.Nested(MatchingPairSchema),
        required=True,
        validate=validate.Length(min=2)
    )
    instructions = fields.Str(required=False)
    time_limit = fields.Int(required=False, validate=validate.Range(min=0))


class TextContentSchema(Schema):
    """Schema for text lesson content"""
    content = fields.Str(required=False)
    text = fields.Str(required=False)
    questions = fields.List(fields.Dict(), required=False)
    comprehension_questions = fields.List(fields.Dict(), required=False)  # For dialogues
    vocabulary_highlight = fields.List(fields.Str(), required=False)
    # Additional fields for dialogue content
    type = fields.Str(required=False)  # dialogue, text, etc.
    ref = fields.Str(required=False)  # reference code like A0M1D1
    title = fields.Str(required=False)  # dialogue title
    audio = fields.Str(required=False)  # audio file name

    @validates_schema
    def validate_text_content(self, data, **kwargs):
        if not data.get('content') and not data.get('text'):
            raise ValidationError('Either "content" or "text" field is required')


class CardContentSchema(Schema):
    """Schema for card/SRS lesson content"""
    collection_id = fields.Int(required=False)
    word_ids = fields.List(fields.Int(), required=False)
    srs_settings = fields.Dict(required=False)
    review_mode = fields.Str(
        required=False,
        validate=validate.OneOf(['flashcard', 'typing', 'multiple_choice'])
    )


class LessonContentValidator:
    """Validator for lesson content based on lesson type"""

    SCHEMAS = {
        'vocabulary': VocabularyContentSchema,
        'grammar': GrammarContentSchema,
        'quiz': QuizContentSchema,
        'matching': MatchingContentSchema,
        'text': TextContentSchema,
        'card': CardContentSchema,
    }

    @classmethod
    def validate(cls, lesson_type: str, content: Any) -> tuple[bool, Optional[str], Optional[Dict]]:
        """
        Validate lesson content based on type.
        
        Args:
            lesson_type: Type of lesson
            content: Content to validate
            
        Returns:
            Tuple of (is_valid, error_message, cleaned_data)
        """
        schema_class = cls.SCHEMAS.get(lesson_type)
        if not schema_class:
            return False, f"Unknown lesson type: {lesson_type}", None

        schema = schema_class()

        try:
            # Handle both list and dict content for vocabulary
            if lesson_type == 'vocabulary' and isinstance(content, list):
                # Convert list format to dict format
                content = {'words': content}

            cleaned_data = schema.load(content)
            return True, None, cleaned_data
        except ValidationError as e:
            error_messages = []
            for field, errors in e.messages.items():
                if isinstance(errors, list):
                    error_messages.extend([f"{field}: {err}" for err in errors])
                else:
                    error_messages.append(f"{field}: {errors}")
            return False, "; ".join(error_messages), None


class ImportDataSchema(Schema):
    """Schema for imported curriculum data"""
    levels = fields.List(fields.Dict(), required=True)

    @validates_schema
    def validate_import_structure(self, data, **kwargs):
        levels = data.get('levels', [])
        if not levels:
            raise ValidationError('Import data must contain at least one level')

        for i, level in enumerate(levels):
            if 'code' not in level:
                raise ValidationError(f'Level {i + 1} must have a "code" field')
            if 'modules' not in level:
                raise ValidationError(f'Level {i + 1} must have a "modules" field')

            for j, module in enumerate(level.get('modules', [])):
                if 'number' not in module:
                    raise ValidationError(
                        f'Module {j + 1} in level {level["code"]} must have a "number" field'
                    )
                if 'lessons' not in module:
                    raise ValidationError(
                        f'Module {j + 1} in level {level["code"]} must have a "lessons" field'
                    )


class ProgressUpdateSchema(Schema):
    """Schema for updating lesson progress"""
    score = fields.Float(
        required=False,
        validate=validate.Range(min=0, max=100)
    )
    status = fields.Str(
        required=False,
        validate=validate.OneOf(['not_started', 'in_progress', 'completed'])
    )
    data = fields.Dict(required=False)
    completed_items = fields.Int(required=False, validate=validate.Range(min=0))
    total_items = fields.Int(required=False, validate=validate.Range(min=1))
    reading_time = fields.Int(required=False, validate=validate.Range(min=0))

    @validates_schema
    def validate_items(self, data, **kwargs):
        completed = data.get('completed_items')
        total = data.get('total_items')
        if completed is not None and total is not None:
            if completed > total:
                raise ValidationError('Completed items cannot exceed total items')


class SRSReviewSchema(Schema):
    """Schema for SRS review submissions"""
    word_id = fields.Int(required=True)
    direction = fields.Str(
        required=True,
        validate=validate.OneOf(['eng-rus', 'rus-eng'])
    )
    quality = fields.Int(
        required=True,
        validate=validate.Range(min=0, max=5)
    )
    time_spent = fields.Int(required=False, validate=validate.Range(min=0))
    user_answer = fields.Str(required=False)


def validate_request_data(schema_class: Schema, data: Dict) -> tuple[bool, Optional[str], Optional[Dict]]:
    """
    Generic validator for request data.
    
    Args:
        schema_class: Marshmallow schema class
        data: Data to validate
        
    Returns:
        Tuple of (is_valid, error_message, cleaned_data)
    """
    schema = schema_class()

    try:
        cleaned_data = schema.load(data)
        return True, None, cleaned_data
    except ValidationError as e:
        error_messages = []
        for field, errors in e.messages.items():
            if isinstance(errors, list):
                error_messages.extend([f"{field}: {err}" for err in errors])
            else:
                error_messages.append(f"{field}: {errors}")
        return False, "; ".join(error_messages), None
