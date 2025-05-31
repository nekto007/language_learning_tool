# app/curriculum/content_schemas.py

from enum import Enum
from typing import Any, Dict


class LessonType(Enum):
    """Enum for lesson types"""
    VOCABULARY = "vocabulary"
    GRAMMAR = "grammar"
    QUIZ = "quiz"
    MATCHING = "matching"
    TEXT = "text"
    CARD = "card"
    FINAL_TEST = "final_test"


class StandardContentSchemas:
    """Standard schemas for lesson content"""

    @staticmethod
    def vocabulary_schema() -> Dict[str, Any]:
        """Standard schema for vocabulary lessons"""
        return {
            "type": "object",
            "properties": {
                "words": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "word": {"type": "string", "maxLength": 100},
                            "translation": {"type": "string", "maxLength": 200},
                            "example": {"type": "string", "maxLength": 500},
                            "hint": {"type": "string", "maxLength": 200},
                            "pronunciation": {"type": "string", "maxLength": 100},
                            "audio_url": {"type": "string", "format": "uri"},
                            "image_url": {"type": "string", "format": "uri"},
                            "difficulty": {"type": "integer", "minimum": 1, "maximum": 5}
                        },
                        "required": ["word", "translation"],
                        "additionalProperties": False
                    },
                    "minItems": 1,
                    "maxItems": 50
                },
                "settings": {
                    "type": "object",
                    "properties": {
                        "review_mode": {
                            "type": "string",
                            "enum": ["flashcard", "typing", "multiple_choice"]
                        },
                        "show_translation": {"type": "boolean"},
                        "show_example": {"type": "boolean"},
                        "show_hint": {"type": "boolean"},
                        "auto_play_audio": {"type": "boolean"}
                    },
                    "additionalProperties": False
                }
            },
            "required": ["words"],
            "additionalProperties": False
        }

    @staticmethod
    def grammar_schema() -> Dict[str, Any]:
        """Standard schema for grammar lessons"""
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "maxLength": 200},
                "content": {"type": "string", "maxLength": 5000},
                "rules": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 500},
                    "maxItems": 20
                },
                "examples": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sentence": {"type": "string", "maxLength": 300},
                            "translation": {"type": "string", "maxLength": 300},
                            "explanation": {"type": "string", "maxLength": 500}
                        },
                        "required": ["sentence"],
                        "additionalProperties": False
                    },
                    "maxItems": 20
                },
                "exercises": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["fill_blank", "multiple_choice", "transformation", "correction"]
                            },
                            "question": {"type": "string", "maxLength": 500},
                            "options": {
                                "type": "array",
                                "items": {"type": "string", "maxLength": 100},
                                "maxItems": 6
                            },
                            "answer": {"type": "string", "maxLength": 200},
                            "explanation": {"type": "string", "maxLength": 500},
                            "hint": {"type": "string", "maxLength": 200}
                        },
                        "required": ["type", "question", "answer"],
                        "additionalProperties": False
                    },
                    "maxItems": 30
                }
            },
            "required": ["title", "content"],
            "additionalProperties": False
        }

    @staticmethod
    def quiz_schema() -> Dict[str, Any]:
        """Standard schema for quiz lessons"""
        return {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "maxLength": 500},
                            "type": {
                                "type": "string",
                                "enum": ["multiple_choice", "true_false", "fill_blank"]
                            },
                            "options": {
                                "type": "array",
                                "items": {"type": "string", "maxLength": 200},
                                "minItems": 2,
                                "maxItems": 6
                            },
                            "correct": {"type": "integer", "minimum": 0},
                            "explanation": {"type": "string", "maxLength": 500},
                            "hint": {"type": "string", "maxLength": 200},
                            "points": {"type": "integer", "minimum": 1, "maximum": 10}
                        },
                        "required": ["question", "options", "correct"],
                        "additionalProperties": False
                    },
                    "minItems": 1,
                    "maxItems": 50
                },
                "settings": {
                    "type": "object",
                    "properties": {
                        "time_limit": {"type": "integer", "minimum": 0, "maximum": 7200},
                        "passing_score": {"type": "integer", "minimum": 0, "maximum": 100},
                        "shuffle_questions": {"type": "boolean"},
                        "shuffle_options": {"type": "boolean"},
                        "show_feedback": {"type": "boolean"},
                        "allow_retries": {"type": "boolean"},
                        "max_attempts": {"type": "integer", "minimum": 1, "maximum": 10}
                    },
                    "additionalProperties": False
                }
            },
            "required": ["questions"],
            "additionalProperties": False
        }

    @staticmethod
    def matching_schema() -> Dict[str, Any]:
        """Standard schema for matching lessons"""
        return {
            "type": "object",
            "properties": {
                "pairs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "left": {"type": "string", "maxLength": 200},
                            "right": {"type": "string", "maxLength": 200},
                            "hint": {"type": "string", "maxLength": 200}
                        },
                        "required": ["left", "right"],
                        "additionalProperties": False
                    },
                    "minItems": 2,
                    "maxItems": 20
                },
                "settings": {
                    "type": "object",
                    "properties": {
                        "instructions": {"type": "string", "maxLength": 500},
                        "time_limit": {"type": "integer", "minimum": 0, "maximum": 3600},
                        "shuffle_items": {"type": "boolean"},
                        "show_hints": {"type": "boolean"}
                    },
                    "additionalProperties": False
                }
            },
            "required": ["pairs"],
            "additionalProperties": False
        }

    @staticmethod
    def text_schema() -> Dict[str, Any]:
        """Standard schema for text reading lessons"""
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "maxLength": 10000},
                "title": {"type": "string", "maxLength": 200},
                "author": {"type": "string", "maxLength": 100},
                "source": {"type": "string", "maxLength": 200},
                "vocabulary_highlight": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 100},
                    "maxItems": 100
                },
                "comprehension_questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "maxLength": 300},
                            "type": {
                                "type": "string",
                                "enum": ["multiple_choice", "open_ended", "true_false"]
                            },
                            "options": {
                                "type": "array",
                                "items": {"type": "string", "maxLength": 200}
                            },
                            "answer": {"type": "string", "maxLength": 500}
                        },
                        "required": ["question", "type"],
                        "additionalProperties": False
                    },
                    "maxItems": 20
                },
                "settings": {
                    "type": "object",
                    "properties": {
                        "reading_time_estimate": {"type": "integer", "minimum": 1},
                        "difficulty_level": {"type": "integer", "minimum": 1, "maximum": 5},
                        "highlight_vocabulary": {"type": "boolean"},
                        "show_translations": {"type": "boolean"}
                    },
                    "additionalProperties": False
                }
            },
            "required": ["content"],
            "additionalProperties": False
        }

    @staticmethod
    def card_schema() -> Dict[str, Any]:
        """Standard schema for SRS card lessons"""
        return {
            "type": "object",
            "properties": {
                "collection_id": {"type": "integer", "minimum": 1},
                "word_ids": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "maxItems": 1000
                },
                "srs_settings": {
                    "type": "object",
                    "properties": {
                        "min_cards_required": {"type": "integer", "minimum": 1, "maximum": 100},
                        "min_accuracy_required": {"type": "integer", "minimum": 0, "maximum": 100},
                        "new_cards_limit": {"type": "integer", "minimum": 1, "maximum": 50},
                        "show_hint_time": {"type": "integer", "minimum": 0, "maximum": 30},
                        "auto_advance": {"type": "boolean"},
                        "review_directions": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["eng-rus", "rus-eng"]
                            },
                            "minItems": 1,
                            "maxItems": 2
                        }
                    },
                    "additionalProperties": False
                }
            },
            "additionalProperties": False
        }

    @staticmethod
    def final_test_schema() -> Dict[str, Any]:
        """Standard schema for final test lessons"""
        return {
            "type": "object",
            "properties": {
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "maxLength": 100},
                            "type": {
                                "type": "string",
                                "enum": ["quiz", "grammar", "vocabulary", "listening", "reading"]
                            },
                            "weight": {"type": "number", "minimum": 0.1, "maximum": 1.0},
                            "content": {"type": "object"},
                            "time_limit": {"type": "integer", "minimum": 0, "maximum": 7200}
                        },
                        "required": ["name", "type", "content"],
                        "additionalProperties": False
                    },
                    "minItems": 1,
                    "maxItems": 10
                },
                "settings": {
                    "type": "object",
                    "properties": {
                        "passing_score": {"type": "integer", "minimum": 0, "maximum": 100},
                        "total_time_limit": {"type": "integer", "minimum": 0, "maximum": 14400},
                        "allow_retries": {"type": "boolean"},
                        "max_attempts": {"type": "integer", "minimum": 1, "maximum": 5},
                        "show_results_immediately": {"type": "boolean"}
                    },
                    "additionalProperties": False
                }
            },
            "required": ["sections"],
            "additionalProperties": False
        }

    @staticmethod
    def get_schema_for_type(lesson_type: str) -> Dict[str, Any]:
        """Get schema for specific lesson type"""
        schema_map = {
            LessonType.VOCABULARY.value: StandardContentSchemas.vocabulary_schema(),
            LessonType.GRAMMAR.value: StandardContentSchemas.grammar_schema(),
            LessonType.QUIZ.value: StandardContentSchemas.quiz_schema(),
            LessonType.MATCHING.value: StandardContentSchemas.matching_schema(),
            LessonType.TEXT.value: StandardContentSchemas.text_schema(),
            LessonType.CARD.value: StandardContentSchemas.card_schema(),
            LessonType.FINAL_TEST.value: StandardContentSchemas.final_test_schema()
        }

        return schema_map.get(lesson_type, {})

    @staticmethod
    def normalize_content(lesson_type: str, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize content to match standard schema
        
        Args:
            lesson_type: Type of lesson
            content: Raw content
            
        Returns:
            Normalized content
        """
        if lesson_type == LessonType.VOCABULARY.value:
            return StandardContentSchemas._normalize_vocabulary_content(content)
        elif lesson_type == LessonType.GRAMMAR.value:
            return StandardContentSchemas._normalize_grammar_content(content)
        elif lesson_type == LessonType.QUIZ.value:
            return StandardContentSchemas._normalize_quiz_content(content)
        elif lesson_type == LessonType.MATCHING.value:
            return StandardContentSchemas._normalize_matching_content(content)
        elif lesson_type == LessonType.TEXT.value:
            return StandardContentSchemas._normalize_text_content(content)
        elif lesson_type == LessonType.CARD.value:
            return StandardContentSchemas._normalize_card_content(content)

        return content

    @staticmethod
    def _normalize_vocabulary_content(content: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize vocabulary content"""
        normalized = {"words": [], "settings": {}}

        # Handle different input formats
        if isinstance(content, list):
            # Direct list of words
            word_list = content
        elif isinstance(content, dict):
            # Dictionary with words key
            word_list = content.get('words', content.get('items', []))
            normalized['settings'] = content.get('settings', {})
        else:
            word_list = []

        # Normalize each word
        for word_data in word_list:
            if isinstance(word_data, dict):
                normalized_word = {
                    'word': word_data.get('word', word_data.get('front', '')),
                    'translation': word_data.get('translation', word_data.get('back', ''))
                }

                # Add optional fields
                for field in ['example', 'hint', 'pronunciation', 'audio_url', 'image_url']:
                    if field in word_data:
                        normalized_word[field] = word_data[field]

                normalized['words'].append(normalized_word)

        return normalized

    @staticmethod
    def _normalize_grammar_content(content: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize grammar content"""
        normalized = {
            'title': content.get('title', ''),
            'content': content.get('content', '')
        }

        # Add optional fields
        for field in ['rules', 'examples', 'exercises']:
            if field in content:
                normalized[field] = content[field]

        return normalized

    @staticmethod
    def _normalize_quiz_content(content: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize quiz content"""
        normalized = {
            'questions': content.get('questions', []),
            'settings': content.get('settings', {})
        }

        # Ensure each question has required fields
        for question in normalized['questions']:
            if 'type' not in question:
                question['type'] = 'multiple_choice'

        return normalized

    @staticmethod
    def _normalize_matching_content(content: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize matching content"""
        return {
            'pairs': content.get('pairs', []),
            'settings': content.get('settings', {})
        }

    @staticmethod
    def _normalize_text_content(content: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize text content"""
        normalized = {
            'content': content.get('content', content.get('text', ''))
        }

        # Add optional fields
        for field in ['title', 'author', 'source', 'vocabulary_highlight', 'comprehension_questions', 'settings']:
            if field in content:
                normalized[field] = content[field]

        return normalized

    @staticmethod
    def _normalize_card_content(content: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize card content"""
        normalized = {}

        # Add optional fields
        for field in ['collection_id', 'word_ids', 'srs_settings']:
            if field in content:
                normalized[field] = content[field]

        return normalized
