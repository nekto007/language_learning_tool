"""Tests for ComprehensionMCQGenerator, ClozePracticeGenerator, and block_schema_importer
handling of None content, structural validation, deduplication, and unknown lesson types.
"""

import pytest
from unittest.mock import Mock, patch

from app.curriculum.services.comprehension_generator import (
    ComprehensionMCQGenerator,
    ClozePracticeGenerator,
)
from app.grammar_lab.content_validator import validate_exercise_content


LONG_TEXT = (
    "The sun rises in the east every morning and sets in the west every evening. "
    "The moon reflects the light of the sun as it orbits around the Earth. "
    "Stars are large balls of hot gas that burn brightly in the night sky. "
    "The planets orbit the sun in elliptical paths of varying size. "
    "Ancient astronomers used the stars to navigate across oceans and deserts. "
    "Modern telescopes allow scientists to observe distant galaxies far away. "
    "The universe is estimated to be about 13.8 billion years old. "
    "Black holes are regions where gravity is so strong that nothing escapes. "
    "Comets are icy bodies that travel through the solar system very fast. "
    "Meteorites fall to Earth and provide clues about the early solar system. "
) * 3  # Repeat to ensure enough sentences


# ---------------------------------------------------------------------------
# ComprehensionMCQGenerator
# ---------------------------------------------------------------------------

class TestComprehensionMCQGeneratorNoneInput:
    def test_none_text_returns_fallback(self):
        result = ComprehensionMCQGenerator.generate_questions(None)
        assert "questions" in result
        assert len(result["questions"]) == 10

    def test_empty_text_returns_fallback(self):
        result = ComprehensionMCQGenerator.generate_questions("")
        assert len(result["questions"]) == 10

    def test_short_text_returns_fallback(self):
        # Under 50 chars triggers fallback
        result = ComprehensionMCQGenerator.generate_questions("Too short.")
        assert len(result["questions"]) == 10


class TestComprehensionMCQGeneratorStructure:
    def test_generated_questions_have_required_fields(self):
        result = ComprehensionMCQGenerator.generate_questions(LONG_TEXT)
        assert "questions" in result
        for q in result["questions"]:
            assert "question" in q, "question field missing"
            assert "options" in q, "options field missing"
            assert "correct" in q, "correct field missing"
            assert "explanation" in q, "explanation field missing"
            assert isinstance(q["options"], list)
            assert len(q["options"]) >= 2
            assert isinstance(q["correct"], int)
            assert 0 <= q["correct"] < len(q["options"])

    def test_generated_returns_requested_count(self):
        result = ComprehensionMCQGenerator.generate_questions(LONG_TEXT, num_questions=5)
        assert len(result["questions"]) == 5

    def test_default_count_is_ten(self):
        result = ComprehensionMCQGenerator.generate_questions(LONG_TEXT)
        assert len(result["questions"]) == 10


class TestComprehensionMCQGeneratorDedup:
    def test_no_duplicate_question_texts(self):
        result = ComprehensionMCQGenerator.generate_questions(LONG_TEXT, num_questions=10)
        question_texts = [q["question"] for q in result["questions"]]
        assert len(question_texts) == len(set(question_texts)), (
            "Duplicate question texts found"
        )

    def test_fallback_questions_are_distinct_objects(self):
        """Fallback must not use shared mutable dict references."""
        result = ComprehensionMCQGenerator._get_fallback_questions()
        questions = result["questions"]
        assert len(questions) == 10
        for i in range(len(questions)):
            for j in range(i + 1, len(questions)):
                assert questions[i] is not questions[j], (
                    f"questions[{i}] and questions[{j}] are the same object"
                )

    def test_fallback_mutation_does_not_propagate(self):
        """Mutating one fallback question must not affect another."""
        result = ComprehensionMCQGenerator._get_fallback_questions()
        q0, q1 = result["questions"][0], result["questions"][1]
        q0["question"] = "MUTATED"
        assert q1["question"] != "MUTATED"


class TestComprehensionMCQValidateExerciseContent:
    def test_unknown_lesson_type_passes_validator(self):
        """validate_exercise_content accepts unknown types (forward compat)."""
        content = ComprehensionMCQGenerator.generate_questions(LONG_TEXT)
        # 'comprehension_mcq' is not in _REQUIRED_KEYS — must not raise
        validate_exercise_content("comprehension_mcq", content)

    def test_phrase_cloze_type_passes_validator(self):
        content = ClozePracticeGenerator.generate_cloze(LONG_TEXT)
        validate_exercise_content("phrase_cloze", content)


# ---------------------------------------------------------------------------
# ClozePracticeGenerator
# ---------------------------------------------------------------------------

class TestClozePracticeGeneratorNoneInput:
    def test_none_text_returns_fallback(self):
        result = ClozePracticeGenerator.generate_cloze(None)
        assert "text" in result
        assert "gaps" in result
        assert isinstance(result["gaps"], list)

    def test_empty_text_returns_fallback(self):
        result = ClozePracticeGenerator.generate_cloze("")
        assert "text" in result
        assert "gaps" in result

    def test_short_text_returns_fallback(self):
        result = ClozePracticeGenerator.generate_cloze("Too short.")
        assert len(result["gaps"]) > 0


class TestClozePracticeGeneratorStructure:
    def test_generated_cloze_has_required_fields(self):
        result = ClozePracticeGenerator.generate_cloze(LONG_TEXT)
        assert "text" in result
        assert "gaps" in result
        for gap in result["gaps"]:
            assert "id" in gap
            assert "answer" in gap
            assert "hint" in gap
            assert isinstance(gap["id"], int)
            assert isinstance(gap["answer"], str)

    def test_gap_placeholders_in_text(self):
        result = ClozePracticeGenerator.generate_cloze(LONG_TEXT)
        for gap in result["gaps"]:
            assert f"({gap['id']}) ______" in result["text"]

    def test_gap_ids_are_unique(self):
        result = ClozePracticeGenerator.generate_cloze(LONG_TEXT)
        ids = [g["id"] for g in result["gaps"]]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# task_generators — None in vocab fields
# ---------------------------------------------------------------------------

class TestTaskGeneratorsNoneVocab:
    def _make_vocab_with_none_english(self):
        return [
            {"english": None, "russian": "тест", "frequency": 1, "level": "A1", "sentences": ""},
            {"english": "hello", "russian": None, "frequency": 2, "level": "A1", "sentences": ""},
            {"english": "", "russian": "пустой", "frequency": 1, "level": "A2", "sentences": ""},
        ]

    def test_vocabulary_task_none_english_does_not_crash(self):
        from app.curriculum.services.task_generators import _generate_vocabulary_task
        block = Mock()
        vocab = self._make_vocab_with_none_english()
        # Should not raise AttributeError / TypeError
        result = _generate_vocabulary_task(block, LONG_TEXT, vocab)
        # Result may be None (no valid words) or a dict
        if result is not None:
            assert "cards" in result

    def test_reading_passage_task_none_english_does_not_crash(self):
        from app.curriculum.services.task_generators import _generate_reading_passage_task
        block = Mock()
        vocab = self._make_vocab_with_none_english()
        result = _generate_reading_passage_task(block, LONG_TEXT, vocab)
        assert result is not None
        assert "vocabulary_words" in result
        # None entries should be excluded from vocab_words
        for word in result["vocabulary_words"]:
            assert word is not None


# ---------------------------------------------------------------------------
# BlockSchemaImporter — unknown lesson types / extra fields
# ---------------------------------------------------------------------------

class TestBlockSchemaImporterUnknownFields:
    """Schema blocks with unknown/extra fields (e.g. lesson_type) are handled gracefully."""

    @patch("app.curriculum.services.block_schema_importer.Chapter")
    @patch("app.curriculum.services.block_schema_importer.Book")
    def test_schema_with_unknown_extra_fields_validates(self, mock_book_model, mock_chapter_model):
        from app.curriculum.services.block_schema_importer import BlockSchemaImporter

        mock_book = Mock()
        mock_book.id = 1
        mock_book_model.query.get_or_404.return_value = mock_book

        # Mock chapters exist
        ch1 = Mock(id=1, book_id=1, chap_num=1)
        ch2 = Mock(id=2, book_id=1, chap_num=2)
        mock_chapter_model.query.filter_by.return_value.first.side_effect = [ch1, ch2]

        importer = BlockSchemaImporter(book_id=1)

        # Schema with unknown fields that should be ignored
        schema_with_extra = [
            {
                "block": 1,
                "chapters": [1, 2],
                "lesson_type": "unknown_type",       # unknown field
                "custom_key": "some_value",           # another unknown field
                "grammar": "Present_Perfect",
            }
        ]

        result = importer._validate_schema(schema_with_extra)
        assert result is True, "Schema with extra fields should pass validation"

    @patch("app.curriculum.services.block_schema_importer.Chapter")
    @patch("app.curriculum.services.block_schema_importer.Book")
    def test_schema_with_unknown_lesson_type_string_validates(self, mock_book_model, mock_chapter_model):
        from app.curriculum.services.block_schema_importer import BlockSchemaImporter

        mock_book = Mock()
        mock_book.id = 1
        mock_book_model.query.get_or_404.return_value = mock_book

        ch1 = Mock(id=1, book_id=1, chap_num=1)
        mock_chapter_model.query.filter_by.return_value.first.return_value = ch1

        importer = BlockSchemaImporter(book_id=1)

        schema = [
            {
                "block": 1,
                "chapters": [1],
                "lesson_type": "comprehension_mcq",   # not a known block field
            }
        ]

        result = importer._validate_schema(schema)
        assert result is True

    @patch("app.curriculum.services.block_schema_importer.db")
    @patch("app.curriculum.services.block_schema_importer.BlockChapter")
    @patch("app.curriculum.services.block_schema_importer.Chapter")
    @patch("app.curriculum.services.block_schema_importer.Block")
    @patch("app.curriculum.services.block_schema_importer.Book")
    def test_import_block_ignores_unknown_fields(
        self, mock_book_model, mock_block_model, mock_chapter_model,
        mock_block_chapter_model, mock_db
    ):
        from app.curriculum.services.block_schema_importer import BlockSchemaImporter

        mock_book = Mock()
        mock_book.id = 1
        mock_book_model.query.get_or_404.return_value = mock_book

        mock_block = Mock()
        mock_block.id = 10
        mock_block_model.return_value = mock_block

        ch1 = Mock(id=1)
        mock_chapter_model.query.filter_by.return_value.first.return_value = ch1

        importer = BlockSchemaImporter(book_id=1)

        block_data = {
            "block": 1,
            "chapters": [1],
            "lesson_type": "unknown_future_type",
            "arbitrary_new_field": 42,
        }

        result = importer._import_block(block_data)
        assert result is True
