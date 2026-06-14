# app/curriculum/validators.py

from typing import Any, Dict, Optional

from marshmallow import INCLUDE, Schema, ValidationError, fields, validate, validates_schema
from marshmallow.decorators import post_load


class VocabularyItemSchema(Schema):
    """Schema for vocabulary lesson items"""
    class Meta:
        unknown = INCLUDE  # Allow additional fields not defined in schema

    word = fields.Str(required=False)
    front = fields.Str(required=False)
    back = fields.Str(required=False)
    translation = fields.Str(required=False)
    example = fields.Str(required=False)
    hint = fields.Str(required=False)
    usage = fields.Str(required=False)
    status = fields.Str(required=False)
    # Additional fields from JSON (будут разрешены через Meta.unknown)
    english = fields.Str(required=False)
    russian = fields.Str(required=False)
    pronunciation = fields.Str(required=False)
    audio = fields.Str(required=False)
    example_translation = fields.Str(required=False)

    @validates_schema
    def validate_word_fields(self, data, **kwargs):
        if not data.get('word') and not data.get('front') and not data.get('english'):
            raise ValidationError('Either "word", "front", or "english" field is required')


class VocabularyContentSchema(Schema):
    """Schema for vocabulary lesson content"""
    class Meta:
        unknown = INCLUDE  # Allow additional fields for backward compatibility

    words = fields.List(fields.Nested(VocabularyItemSchema), required=False)
    items = fields.List(fields.Nested(VocabularyItemSchema), required=False)
    cards = fields.List(fields.Nested(VocabularyItemSchema), required=False)
    settings = fields.Dict(required=False)

    # Legacy fields for backward compatibility
    vocabulary = fields.List(fields.Nested(VocabularyItemSchema), required=False)
    exercises = fields.List(fields.Dict(), required=False)

    @validates_schema
    def validate_content(self, data, **kwargs):
        # Check if at least one vocabulary field exists AND is non-empty
        has_vocab = any([
            data.get('words') and len(data.get('words')) > 0,
            data.get('items') and len(data.get('items')) > 0,
            data.get('cards') and len(data.get('cards')) > 0,
            data.get('vocabulary') and len(data.get('vocabulary')) > 0
        ])
        if not has_vocab:
            raise ValidationError('At least one vocabulary field (words/items/cards/vocabulary) must be present and non-empty')


class GrammarContentSchema(Schema):
    """Schema for grammar lesson content"""
    class Meta:
        unknown = INCLUDE  # Allow additional fields not defined in schema

    title = fields.Str(required=False, validate=validate.Length(min=1, max=200))
    content = fields.Str(required=False, validate=validate.Length(min=1))
    rule = fields.Str(required=False)  # Alternative field name
    text = fields.Str(required=False)  # Alternative field name
    description = fields.Str(required=False)  # Alternative field name
    examples = fields.List(fields.Raw(), required=False)  # Accept both strings and dicts
    exercises = fields.List(fields.Dict(), required=False)
    rules = fields.List(fields.Str(), required=False)
    grammar_explanation = fields.Dict(required=False)  # Complex grammar explanation structure

    @validates_schema
    def validate_grammar_content(self, data, **kwargs):
        # Require at least one content field
        if not any([data.get('content'), data.get('rule'), data.get('text'),
                    data.get('title'), data.get('description'), data.get('grammar_explanation')]):
            raise ValidationError('At least one content field is required')


class QuizQuestionSchema(Schema):
    """Schema for quiz questions"""
    class Meta:
        unknown = INCLUDE  # Allow additional fields not defined in schema

    type = fields.Str(required=False, load_default=None, allow_none=True)
    question = fields.Str(required=False, validate=validate.Length(min=1, max=500))
    prompt = fields.Str(required=False, validate=validate.Length(min=1, max=500))  # Alternative to question
    sentence = fields.Str(required=False)  # For fill_blank questions
    russian = fields.Str(required=False)  # For translation questions
    instruction = fields.Str(required=False)  # For matching/ordering questions
    options = fields.List(
        fields.Str(),
        required=False,  # Not required for all question types
        validate=validate.Length(min=2, max=6)
    )
    correct = fields.Raw(required=False)  # Can be int (index) or string (answer)
    correct_index = fields.Int(required=False, validate=validate.Range(min=0, max=5))  # Alternative to correct
    correct_answer = fields.Raw(required=False)  # Can be string, bool, or list
    answer = fields.Raw(required=False)  # Alternative to correct_answer
    acceptable_answers = fields.List(fields.Str(), required=False)
    alternative_answers = fields.List(fields.Str(), required=False)
    explanation = fields.Str(required=False)
    hint = fields.Str(required=False)
    words = fields.List(fields.Str(), required=False)  # For reorder/ordering type questions
    pairs = fields.List(fields.Dict(), required=False)  # For matching type questions

    @validates_schema
    def validate_question_fields(self, data, **kwargs):
        # Get question type
        q_type = data.get('type', 'multiple_choice')

        # For these types, question/prompt is not strictly required
        # They may have alternative fields like 'instruction', 'russian', 'sentence', 'audio', etc.
        skip_question_prompt = q_type in ['fill_blank', 'fill_in_blank', 'translation', 'matching', 'ordering',
                                          'transformation', 'dialogue_completion', 'listening_choice', 'reorder',
                                          'true_false', 'tf']

        # Must have either 'question' or 'prompt' for other types
        if not skip_question_prompt and not data.get('question') and not data.get('prompt'):
            raise ValidationError('Either "question" or "prompt" field is required')

        # Validate based on question type
        if q_type == 'multiple_choice':
            if not data.get('options'):
                raise ValidationError('Multiple choice questions require "options" field')

            # Optional: validate 'correct' or 'correct_index' if provided
            correct_val = data.get('correct') if data.get('correct') is not None else data.get('correct_index')

            # If correct is an integer (index), validate it's in range
            if correct_val is not None and isinstance(correct_val, int):
                if correct_val >= len(data.get('options', [])):
                    raise ValidationError('Correct answer index is out of range')
            # If correct is a string (answer text), validate it's in options
            elif isinstance(correct_val, str):
                if correct_val not in data.get('options', []):
                    # It's okay if the string is not in options - might be normalized later
                    pass

        elif q_type in ['true_false']:
            # Must have either 'correct_answer', 'answer', or 'correct'
            if data.get('correct_answer') is None and data.get('answer') is None and data.get('correct') is None:
                raise ValidationError('True/false questions require "correct_answer", "answer", or "correct" field')

        elif q_type in ['fill_blank', 'fill_in_blank', 'translation']:
            # Must have either 'correct_answer', 'answer', or 'correct'
            if not data.get('correct_answer') and not data.get('answer') and not data.get('correct'):
                raise ValidationError(f'{q_type} questions require "correct_answer", "answer", or "correct" field')

        elif q_type == 'reorder':
            # Must have 'words' array and 'correct_answer'
            if not data.get('words'):
                raise ValidationError('Reorder questions require "words" field')
            if not data.get('correct_answer'):
                raise ValidationError('Reorder questions require "correct_answer" field')


class QuizContentSchema(Schema):
    """Schema for quiz lesson content"""
    class Meta:
        unknown = INCLUDE  # Allow additional fields like xp_reward

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
    xp_reward = fields.Int(required=False, validate=validate.Range(min=0))

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
    class Meta:
        unknown = INCLUDE

    left = fields.Str(required=False, validate=validate.Length(min=1, max=200))
    right = fields.Str(required=False, validate=validate.Length(min=1, max=200))
    english = fields.Str(required=False, validate=validate.Length(min=1, max=200))
    russian = fields.Str(required=False, validate=validate.Length(min=1, max=200))
    hint = fields.Str(required=False)

    @validates_schema
    def validate_pair(self, data, **kwargs):
        # Must have either (left, right) or (english, russian)
        has_left_right = 'left' in data and 'right' in data
        has_english_russian = 'english' in data and 'russian' in data

        if not has_left_right and not has_english_russian:
            raise ValidationError('Pair must have either (left, right) or (english, russian) fields')


class MatchingContentSchema(Schema):
    """Schema for matching lesson content"""
    pairs = fields.List(
        fields.Nested(MatchingPairSchema),
        required=True,
        validate=validate.Length(min=1)
    )
    instructions = fields.Str(required=False)
    time_limit = fields.Int(required=False, validate=validate.Range(min=0))


class TextContentSchema(Schema):
    """Schema for text lesson content"""
    class Meta:
        unknown = INCLUDE  # Allow additional fields like 'exercises'

    content = fields.Str(required=False)
    text = fields.Raw(required=False)  # Can be string OR object (for reading lessons)
    questions = fields.List(fields.Dict(), required=False)
    comprehension_questions = fields.List(fields.Dict(), required=False)  # For dialogues
    vocabulary_highlight = fields.List(fields.Str(), required=False)
    exercises = fields.List(fields.Dict(), required=False)  # For reading lessons
    # Additional fields for dialogue content
    type = fields.Str(required=False)  # dialogue, text, etc.
    ref = fields.Str(required=False)  # reference code like A1M1D1
    title = fields.Str(required=False)  # dialogue title
    audio = fields.Str(required=False)  # audio file name

    @validates_schema
    def validate_text_content(self, data, **kwargs):
        if not data.get('content') and not data.get('text'):
            raise ValidationError('Either "content" or "text" field is required')


class DictationContentSchema(Schema):
    """Schema for dictation lesson content.

    Difficulty ladder (single lesson type, four modes — A1→C1):
      * ``cloze`` — A1/A2: visible text with key-word gaps via ``gap_text`` +
        ``gaps[]``. Current default when ``gaps`` is present.
      * ``phrase_cloze`` — B1: multi-word phrase gaps (``gaps[].span_words``).
      * ``sentence_reconstruction`` — B2: numbered prompts, learner writes
        each sentence into its own textarea.
      * ``full_dictation`` — C1: single textarea, exact word-by-word
        comparison with the transcript.

    ``mode`` is optional and auto-derived when absent: presence of ``gaps``
    implies ``cloze``, otherwise ``full_dictation``. Future B1+/C-modules
    can set it explicitly without touching the schema again.
    """
    class Meta:
        unknown = INCLUDE

    audio_url = fields.Str(required=True, validate=validate.Length(min=1))
    transcript = fields.Str(required=True, validate=validate.Length(min=1))
    hint_chars = fields.Int(required=False, load_default=0, validate=validate.Range(min=0))
    mode = fields.Str(
        required=False,
        load_default=None,
        validate=validate.OneOf([
            'cloze', 'phrase_cloze', 'sentence_reconstruction', 'full_dictation',
        ]),
    )


class AudioFillBlankItemSchema(Schema):
    """Schema for a single audio fill-in-blank item"""
    class Meta:
        unknown = INCLUDE

    audio_clip_url = fields.Str(required=False, allow_none=True)
    text_with_gap = fields.Str(required=True, validate=validate.Length(min=1))
    answer = fields.Str(required=True, validate=validate.Length(min=1))
    options = fields.List(fields.Str(), required=False, validate=validate.Length(min=2, max=6))


class AudioFillBlankContentSchema(Schema):
    """Schema for audio fill-in-blank lesson content"""
    class Meta:
        unknown = INCLUDE

    audio_url = fields.Str(required=True, validate=validate.Length(min=1))
    items = fields.List(
        fields.Nested(AudioFillBlankItemSchema),
        required=True,
        validate=validate.Length(min=1),
    )


class TranslationItemSchema(Schema):
    """One item in a multi-item translation lesson (guided practice mode)."""
    class Meta:
        unknown = INCLUDE

    russian = fields.Str(required=True, validate=validate.Length(min=1))
    english = fields.Str(required=True, validate=validate.Length(min=1))
    hint_words = fields.List(fields.Str(), required=False, load_default=None)
    alternatives = fields.List(fields.Str(), required=False, load_default=None)


class TranslationContentSchema(Schema):
    """Schema for standalone translation lesson content (Russian → English).

    Two valid shapes:
      * **Single-item (legacy)**: top-level ``russian``/``english``/``hint_words``.
      * **Multi-item (guided practice)**: ``items: [{russian, english, hint_words}, ...]``.

    Multi-item is the preferred shape for new content — it lets translation
    play the «training with hints» role before the translation_quiz «check
    without hints» step. The route always normalises to multi-item internally,
    so the template branches on a single ``items`` list either way.

    Difficulty ladder (single lesson type — `mode` selects support level):

      * ``guided`` — **A1–A2**. Слова-подсказки видны сразу, можно кликать
        для вставки. Короткие предложения. Мягкая проверка с Levenshtein-
        толерантностью на одиночных словах. Цель: научить собирать фразы
        по шаблону.
      * ``open`` — **B1–B2**. Подсказки спрятаны за кнопкой «Показать
        подсказки» и используются как safety-net. Принимаются несколько
        правильных вариантов (``alternatives``). Цель: передавать смысл,
        не цепляясь за слово-в-слово.
      * ``rubric`` — **C1**. Без подсказок, рубричная оценка
        (смысл / грамматика / естественность / стиль), несколько эталонных
        переводов. Цель: переводить как переводческое решение. Требует
        более гибкого грейдера (semantic similarity / AI feedback) —
        ставится поэтапно по мере появления C-уровневого контента.

    ``mode`` опциональный — авто-вывод: если у любого item есть
    ``hint_words`` (или top-level ``hint_words`` в legacy-shape) → ``guided``,
    иначе → ``open``. Авто-вывод позволяет существующему A1-контенту
    работать без миграции, новые модули B1+ просто выставляют ``mode``
    явно или просто не дают ``hint_words``.
    """
    class Meta:
        unknown = INCLUDE

    russian = fields.Str(required=False, load_default=None, allow_none=True)
    english = fields.Str(required=False, load_default=None, allow_none=True)
    hint_words = fields.List(fields.Str(), required=False, load_default=None)
    items = fields.List(
        fields.Nested(TranslationItemSchema),
        required=False,
        load_default=None,
    )
    mode = fields.Str(
        required=False,
        load_default=None,
        validate=validate.OneOf(['guided', 'open', 'rubric']),
    )

    @validates_schema
    def validate_has_payload(self, data, **kwargs):
        items = data.get('items')
        russian = (data.get('russian') or '').strip() if data.get('russian') else ''
        english = (data.get('english') or '').strip() if data.get('english') else ''
        if items:
            return  # multi-item ok
        if russian and english:
            return  # legacy single-item ok
        raise ValidationError(
            'translation content must have either `items[]` or top-level `russian`+`english`'
        )


class SentenceCorrectionItemSchema(Schema):
    """A single sentence-correction item for the multi-item flow."""
    class Meta:
        unknown = INCLUDE

    incorrect_sentence = fields.Str(required=True, validate=validate.Length(min=1))
    correct_sentence = fields.Str(required=True, validate=validate.Length(min=1))
    error_type = fields.Str(required=False, load_default='', allow_none=True)
    error_type_ru = fields.Str(required=False, load_default='', allow_none=True)
    translation = fields.Str(required=False, load_default='', allow_none=True)
    explanation = fields.Str(required=False, load_default='', allow_none=True)
    options = fields.List(fields.Str(), required=False, validate=validate.Length(min=2, max=6))


class SentenceCorrectionContentSchema(Schema):
    """Schema for sentence correction lesson content.

    Two supported shapes:
    - Single-item legacy: top-level fields (incorrect_sentence,
      correct_sentence, error_type, explanation, options).
    - Multi-item: `items` array of SentenceCorrectionItemSchema. Used when
      the lesson contains several errors to fix (e.g. five BE-form
      corrections after the BE grammar lesson).
    """
    class Meta:
        unknown = INCLUDE

    # Single-item fields (legacy) — now optional so the multi-item shape
    # can omit them entirely.
    incorrect_sentence = fields.Str(required=False, validate=validate.Length(min=1))
    correct_sentence = fields.Str(required=False, validate=validate.Length(min=1))
    error_type = fields.Str(required=False, validate=validate.Length(min=1))
    explanation = fields.Str(required=False, validate=validate.Length(min=1))
    options = fields.List(fields.Str(), required=False, validate=validate.Length(min=2, max=6))
    # Multi-item flow.
    items = fields.List(
        fields.Nested(SentenceCorrectionItemSchema),
        required=False,
        validate=validate.Length(min=1),
    )

    @validates_schema
    def validate_has_payload(self, data, **kwargs):
        items = data.get('items')
        has_single = bool(data.get('incorrect_sentence')) and bool(data.get('correct_sentence'))
        if not items and not has_single:
            raise ValidationError(
                'sentence_correction needs either an `items` array or both '
                '`incorrect_sentence` and `correct_sentence` at the top level.'
            )


class WritingPromptContentSchema(Schema):
    """Schema for writing prompt lesson content — user writes free-form response.

    A1 → C1 ladder (single lesson type, varying support level via mode):

      * ``guided`` — **A1**. Russian task copy, template/example revealable,
        clickable hint chips that insert into textarea, count by sentences
        (``min_sentences``) rather than raw word count. Auto-tick checklist
        items via target-phrase detection. Goal: «собрать 4-5 простых
        предложений по шаблону».
      * ``structured`` — **A2**. Plan/useful phrases, example behind toggle,
        word target ≈ 50-70. Goal: «связный короткий текст на бытовую тему».
      * ``paragraph`` — **B1**. Less scaffolding, accept multiple structures,
        80-120 words. Goal: «абзац с причиной/мнением».
      * ``opinion`` — **B2**. Argument-oriented, linking-word hints, 150-220.
      * ``style`` — **C1**. Task context + audience + tone, rubric grading.

    All new fields are optional — legacy content (``prompt`` + ``min_words``
    + ``checklist``) keeps working unchanged. Default mode derives from
    presence: ``min_sentences`` or ``hint_words`` → ``guided``, otherwise
    ``structured``.
    """
    class Meta:
        unknown = INCLUDE

    prompt = fields.Str(required=True, validate=validate.Length(min=1))
    prompt_ru = fields.Str(required=False, load_default=None, allow_none=True)
    min_words = fields.Int(required=False, load_default=None, allow_none=True,
                            validate=validate.Range(min=1))
    min_sentences = fields.Int(required=False, load_default=None, allow_none=True,
                                validate=validate.Range(min=1, max=20))
    example_response = fields.Str(required=False, load_default=None, allow_none=True)
    template = fields.Str(required=False, load_default=None, allow_none=True)
    hint_words = fields.List(fields.Str(), required=False, load_default=None)
    target_phrases = fields.List(fields.Str(), required=False, load_default=None)
    # Минимум отмеченных пунктов чек-листа для завершения. Default зависит
    # от mode: guided → 3 (структурный контроль), остальные → 2.
    min_checklist = fields.Int(required=False, load_default=None, allow_none=True,
                                validate=validate.Range(min=1))
    mode = fields.Str(
        required=False, load_default=None,
        validate=validate.OneOf(['guided', 'structured', 'paragraph', 'opinion', 'style', 'rhetoric']),
    )
    checklist = fields.List(
        fields.Str(validate=validate.Length(min=1)),
        required=False,
        load_default=None,
        validate=validate.Length(min=2),
    )

    @validates_schema
    def validate_min_target(self, data, **kwargs):
        # Need at least one length target — words OR sentences. Otherwise
        # we can't gate completion.
        if not data.get('min_words') and not data.get('min_sentences'):
            raise ValidationError(
                'writing_prompt requires `min_words` or `min_sentences`',
            )

    @validates_schema
    def validate_checklist_unique(self, data, **kwargs):
        # Submission requires ≥2 distinct checked items (see
        # _process_writing_prompt_submission, which collapses checked items to
        # a set). A checklist with duplicate strings would render multiple
        # checkboxes but could never satisfy the completion gate, so reject
        # duplicates at content-validation time.
        checklist = data.get('checklist')
        if checklist and len(set(checklist)) != len(checklist):
            raise ValidationError('checklist items must be unique', field_name='checklist')


class SentenceCompletionItemSchema(Schema):
    """Schema for a single sentence completion item."""
    class Meta:
        unknown = INCLUDE

    prompt = fields.Str(required=True, validate=validate.Length(min=1))
    answer = fields.Str(required=True, validate=validate.Length(min=1))
    context = fields.Str(required=False, load_default=None, allow_none=True)


class SentenceCompletionContentSchema(Schema):
    """Schema for sentence completion lesson content — user fills in the second half."""
    class Meta:
        unknown = INCLUDE

    items = fields.List(
        fields.Nested(SentenceCompletionItemSchema),
        required=True,
        validate=validate.Length(min=1),
    )


class CollocationPairSchema(Schema):
    """Schema for a single collocation matching pair."""
    class Meta:
        unknown = INCLUDE

    phrase = fields.Str(required=True, validate=validate.Length(min=1))
    translation = fields.Str(required=True, validate=validate.Length(min=1))


class CollocationMatchingContentSchema(Schema):
    """Schema for collocation matching lesson — match English phrases to Russian translations."""
    class Meta:
        unknown = INCLUDE

    pairs = fields.List(
        fields.Nested(CollocationPairSchema),
        required=True,
        validate=validate.Length(min=1),
    )


class ShadowReadingContentSchema(Schema):
    """Schema for shadow reading lesson — listen then read aloud (honor system)."""
    class Meta:
        unknown = INCLUDE

    audio_url = fields.Str(required=True, validate=validate.Length(min=1))
    text = fields.Str(required=True, validate=validate.Length(min=1))
    translation = fields.Str(required=True, validate=validate.Length(min=1))


class PronunciationItemSchema(Schema):
    """Schema for a single pronunciation practice item."""
    class Meta:
        unknown = INCLUDE

    word = fields.Str(required=True, validate=validate.Length(min=1))
    pronunciation_hint = fields.Str(required=False, load_default=None, allow_none=True)
    audio_url = fields.Str(required=False, load_default=None, allow_none=True)


class PronunciationContentSchema(Schema):
    """Schema for pronunciation exercise — user listens then speaks each word."""
    class Meta:
        unknown = INCLUDE

    items = fields.List(
        fields.Nested(PronunciationItemSchema),
        required=True,
        validate=validate.Length(min=1),
    )


class IdiomItemSchema(Schema):
    """Schema for a single idiom item."""
    class Meta:
        unknown = INCLUDE

    phrase = fields.Str(required=True, validate=validate.Length(min=1))
    meaning = fields.Str(required=True, validate=validate.Length(min=1))
    example = fields.Str(required=True, validate=validate.Length(min=1))
    audio_url = fields.Str(required=False, load_default=None, allow_none=True)


class IdiomContentSchema(Schema):
    """Schema for idiom lesson — present phrase, reveal meaning, example, self-assess."""
    class Meta:
        unknown = INCLUDE

    items = fields.List(
        fields.Nested(IdiomItemSchema),
        required=True,
        validate=validate.Length(min=1),
    )


class CardContentSchema(Schema):
    """Schema for card/SRS lesson content"""
    class Meta:
        unknown = INCLUDE  # Allow additional fields for flexibility

    collection_id = fields.Int(required=False)
    word_ids = fields.List(fields.Int(), required=False)
    cards = fields.List(fields.Dict(), required=False)  # For flashcards lessons
    srs_settings = fields.Dict(required=False)
    review_mode = fields.Str(
        required=False,
        validate=validate.OneOf(['flashcard', 'typing', 'multiple_choice'])
    )


class FinalTestSectionSchema(Schema):
    """Schema for final test section"""
    class Meta:
        unknown = INCLUDE

    section = fields.Str(required=False)
    name = fields.Str(required=False)  # Alternative to section
    exercises = fields.List(fields.Nested(QuizQuestionSchema), required=False)
    questions = fields.List(fields.Nested(QuizQuestionSchema), required=False)  # Alternative to exercises


class FinalTestContentSchema(Schema):
    """Schema for final test lesson content"""
    class Meta:
        unknown = INCLUDE  # Allow additional fields

    test_sections = fields.List(fields.Nested(FinalTestSectionSchema), required=False)
    sections = fields.List(fields.Nested(FinalTestSectionSchema), required=False)  # Alternative to test_sections
    passing_score = fields.Int(required=False, validate=validate.Range(min=0, max=100))
    pass_score = fields.Int(required=False, validate=validate.Range(min=0, max=100))  # Alternative
    total_points = fields.Int(required=False, validate=validate.Range(min=0))
    total_questions = fields.Int(required=False, validate=validate.Range(min=0))
    time_limit = fields.Int(required=False, validate=validate.Range(min=0))


class LessonContentValidator:
    """Validator for lesson content based on lesson type"""

    SCHEMAS = {
        'vocabulary': VocabularyContentSchema,
        'flashcards': VocabularyContentSchema,  # alias
        'grammar': GrammarContentSchema,
        'quiz': QuizContentSchema,
        'ordering_quiz': QuizContentSchema,  # alias
        'translation_quiz': QuizContentSchema,  # alias
        'listening_quiz': QuizContentSchema,  # alias
        'dialogue_completion_quiz': QuizContentSchema,  # alias
        'listening_immersion_quiz': QuizContentSchema,  # alias
        'matching': MatchingContentSchema,
        'text': TextContentSchema,
        'reading': TextContentSchema,  # alias
        'listening_immersion': TextContentSchema,  # alias
        'card': CardContentSchema,
        'dictation': DictationContentSchema,
        'audio_fill_blank': AudioFillBlankContentSchema,
        'translation': TranslationContentSchema,
        'sentence_correction': SentenceCorrectionContentSchema,
        'writing_prompt': WritingPromptContentSchema,
        'sentence_completion': SentenceCompletionContentSchema,
        'collocation_matching': CollocationMatchingContentSchema,
        'shadow_reading': ShadowReadingContentSchema,
        'pronunciation': PronunciationContentSchema,
        'idiom': IdiomContentSchema,
        'final_test': FinalTestContentSchema,
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

        Raises:
            ValueError: If lesson_type is unknown
            ValidationError: If content is invalid
        """
        schema_class = cls.SCHEMAS.get(lesson_type)
        if not schema_class:
            raise ValueError(f"Unknown lesson type: {lesson_type}")

        schema = schema_class()

        # Handle both list and dict content for vocabulary
        if lesson_type == 'vocabulary' and isinstance(content, list):
            # Convert list format to dict format
            content = {'words': content}

        # Load and validate - will raise ValidationError if invalid
        cleaned_data = schema.load(content)
        return True, None, cleaned_data


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
    lesson_id = fields.Int(required=False, validate=validate.Range(min=1))
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
    time_spent = fields.Int(required=False, validate=validate.Range(min=0))
    attempts = fields.Int(required=False, validate=validate.Range(min=1))
    comprehension_results = fields.Dict(required=False)  # Результаты comprehension questions

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
        validate=validate.OneOf(['eng-rus', 'rus-eng', 'en_ru', 'ru_en'])
    )
    quality = fields.Int(
        required=False,
        validate=validate.Range(min=0, max=5)
    )
    rating = fields.Int(
        required=False,
        validate=validate.Range(min=0, max=5)
    )
    time_spent = fields.Int(required=False, validate=validate.Range(min=0))
    response_time = fields.Float(required=False, validate=validate.Range(min=0))
    session_id = fields.Str(required=False)
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


def validate_sentence_correction_content(content: Optional[Dict[str, Any]]) -> list:
    """Validate single-item sentence_correction content integrity.

    For a single-item lesson the selectable ``options`` must include the
    ``correct_sentence`` (after normalization); otherwise the options UI is
    structurally unpassable — the correct option never matches the canonical
    sentence (audit E-092). Multi-item content (``items`` present) is exempt,
    and content without ``options`` is free-text and exempt too.

    Returns a list of human-readable error strings (empty == valid).
    """
    from app.curriculum.grading import _normalize_answer

    errors: list = []
    if not isinstance(content, dict):
        return ["content must be a mapping"]
    if content.get('items'):
        return errors  # multi-item handled per-item by its own grader
    options = content.get('options')
    correct = content.get('correct_sentence')
    if options and correct is not None:
        normalized_options = {_normalize_answer(o) for o in options}
        if _normalize_answer(correct) not in normalized_options:
            errors.append(
                "correct_sentence is not among options (after normalization) — "
                "options UI would be unpassable"
            )
    return errors
