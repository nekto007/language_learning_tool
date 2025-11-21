"""Tests for ContentMigrationService"""
import pytest
from unittest.mock import Mock
from app.curriculum.services.content_migration_service import ContentMigrationService


class TestMigrateContent:
    """Test migrate_content method"""

    def test_same_version_returns_content(self):
        """Test migration with same source and target version"""
        content = {'words': [{'word': 'hello', 'translation': 'привет'}]}

        result = ContentMigrationService.migrate_content(
            'vocabulary', content, from_version=1, to_version=1
        )

        assert result == content

    def test_downgrade_returns_none(self):
        """Test that downgrade is not allowed"""
        content = {'words': []}

        result = ContentMigrationService.migrate_content(
            'vocabulary', content, from_version=2, to_version=1
        )

        assert result is None

    def test_migration_to_nonexistent_version_returns_content(self):
        """Test migration to version without migration method"""
        content = {'words': []}

        # v1 to v3 without v2_to_v3 method
        result = ContentMigrationService.migrate_content(
            'vocabulary', content, from_version=1, to_version=3
        )

        # Should still return content for v1_to_v2, but warn about v2_to_v3
        assert result is not None

    def test_migration_preserves_original(self):
        """Test that migration doesn't modify original content"""
        original = {'items': [{'front': 'hello'}]}

        result = ContentMigrationService.migrate_content(
            'vocabulary', original, from_version=1, to_version=2
        )

        assert 'items' in original  # Original unchanged
        assert result != original  # Result is different


class TestMigrateV1ToV2:
    """Test _migrate_v1_to_v2 method"""

    def test_adds_metadata(self):
        """Test that v2 adds metadata fields"""
        content = {'words': []}

        result = ContentMigrationService._migrate_v1_to_v2('vocabulary', content)

        assert result['_schema_version'] == 2
        assert '_migrated_at' in result

    def test_vocabulary_migration(self):
        """Test vocabulary lesson migration"""
        content = {'items': [{'front': 'hello', 'back': 'привет'}]}

        result = ContentMigrationService._migrate_v1_to_v2('vocabulary', content)

        assert 'words' in result
        assert 'items' not in result
        assert result['words'][0]['word'] == 'hello'
        assert result['words'][0]['translation'] == 'привет'

    def test_grammar_migration(self):
        """Test grammar lesson migration"""
        content = {
            'rule': 'Grammar rule',
            'exercises': [{'prompt': 'Question?'}]
        }

        result = ContentMigrationService._migrate_v1_to_v2('grammar', content)

        assert result['content'] == 'Grammar rule'
        assert result['exercises'][0]['question'] == 'Question?'

    def test_quiz_migration(self):
        """Test quiz lesson migration"""
        content = {
            'questions': [
                {'prompt': 'Q1', 'correct_index': 0}
            ]
        }

        result = ContentMigrationService._migrate_v1_to_v2('quiz', content)

        assert result['questions'][0]['question'] == 'Q1'
        assert result['questions'][0]['correct'] == 0

    def test_text_migration(self):
        """Test text lesson migration"""
        content = {'text': 'Some text content'}

        result = ContentMigrationService._migrate_v1_to_v2('text', content)

        assert result['content'] == 'Some text content'

    def test_matching_migration(self):
        """Test matching lesson migration (no changes)"""
        content = {'pairs': []}

        result = ContentMigrationService._migrate_v1_to_v2('matching', content)

        assert result == {**content, '_schema_version': 2, '_migrated_at': 'auto'}

    def test_card_migration(self):
        """Test card lesson migration (no changes)"""
        content = {'cards': []}

        result = ContentMigrationService._migrate_v1_to_v2('card', content)

        assert '_schema_version' in result

    def test_final_test_migration(self):
        """Test final test migration"""
        content = {'exercises': [{'question': 'Q1'}]}

        result = ContentMigrationService._migrate_v1_to_v2('final_test', content)

        assert 'questions' in result
        assert result['questions'] == [{'question': 'Q1'}]


class TestVocabularyMigration:
    """Test _migrate_vocabulary_v1_to_v2"""

    def test_items_to_words(self):
        """Test renaming items to words"""
        content = {'items': [{'word': 'test'}]}

        result = ContentMigrationService._migrate_vocabulary_v1_to_v2(content)

        assert 'words' in result
        assert 'items' not in result

    def test_front_to_word(self):
        """Test renaming front to word"""
        content = {'words': [{'front': 'hello'}]}

        result = ContentMigrationService._migrate_vocabulary_v1_to_v2(content)

        assert result['words'][0]['word'] == 'hello'
        assert 'front' not in result['words'][0]

    def test_back_to_translation(self):
        """Test renaming back to translation"""
        content = {'words': [{'back': 'привет'}]}

        result = ContentMigrationService._migrate_vocabulary_v1_to_v2(content)

        assert result['words'][0]['translation'] == 'привет'
        assert 'back' not in result['words'][0]

    def test_preserves_existing_fields(self):
        """Test that existing correct fields are preserved"""
        content = {'words': [{'word': 'hello', 'translation': 'привет'}]}

        result = ContentMigrationService._migrate_vocabulary_v1_to_v2(content)

        assert result['words'][0]['word'] == 'hello'
        assert result['words'][0]['translation'] == 'привет'


class TestGrammarMigration:
    """Test _migrate_grammar_v1_to_v2"""

    def test_rule_to_content(self):
        """Test renaming rule to content"""
        content = {'rule': 'Grammar rule'}

        result = ContentMigrationService._migrate_grammar_v1_to_v2(content)

        assert result['content'] == 'Grammar rule'

    def test_preserves_existing_content(self):
        """Test that existing content is preserved"""
        content = {'rule': 'Old', 'content': 'New'}

        result = ContentMigrationService._migrate_grammar_v1_to_v2(content)

        assert result['content'] == 'New'

    def test_prompt_to_question(self):
        """Test renaming prompt to question in exercises"""
        content = {'exercises': [{'prompt': 'Question?'}]}

        result = ContentMigrationService._migrate_grammar_v1_to_v2(content)

        assert result['exercises'][0]['question'] == 'Question?'
        assert 'prompt' not in result['exercises'][0]


class TestQuizMigration:
    """Test _migrate_quiz_v1_to_v2"""

    def test_correct_index_to_correct(self):
        """Test renaming correct_index to correct"""
        content = {'questions': [{'correct_index': 2}]}

        result = ContentMigrationService._migrate_quiz_v1_to_v2(content)

        assert result['questions'][0]['correct'] == 2

    def test_prompt_to_question(self):
        """Test renaming prompt to question"""
        content = {'questions': [{'prompt': 'What is it?'}]}

        result = ContentMigrationService._migrate_quiz_v1_to_v2(content)

        assert result['questions'][0]['question'] == 'What is it?'
        assert 'prompt' not in result['questions'][0]


class TestTextMigration:
    """Test _migrate_text_v1_to_v2"""

    def test_text_to_content(self):
        """Test renaming text to content"""
        content = {'text': 'Some text'}

        result = ContentMigrationService._migrate_text_v1_to_v2(content)

        assert result['content'] == 'Some text'

    def test_preserves_existing_content(self):
        """Test that existing content is preserved"""
        content = {'text': 'Old', 'content': 'New'}

        result = ContentMigrationService._migrate_text_v1_to_v2(content)

        assert result['content'] == 'New'


class TestCheckContentHealth:
    """Test check_content_health method"""

    def test_health_check_current_version(self):
        """Test health check returns current version"""
        lesson = Mock()
        lesson.content_version = 1
        lesson.validate_content_schema.return_value = (True, None)
        lesson.content = {}

        health = ContentMigrationService.check_content_health(lesson)

        assert health['current_version'] == 1
        assert health['latest_version'] == ContentMigrationService.LATEST_VERSION

    def test_health_check_needs_migration(self):
        """Test health check detects need for migration"""
        lesson = Mock()
        lesson.content_version = 1
        lesson.validate_content_schema.return_value = (True, None)
        lesson.content = {}

        # Temporarily set LATEST_VERSION higher
        original = ContentMigrationService.LATEST_VERSION
        ContentMigrationService.LATEST_VERSION = 2

        health = ContentMigrationService.check_content_health(lesson)

        assert health['needs_migration'] is True

        # Restore
        ContentMigrationService.LATEST_VERSION = original

    def test_health_check_invalid_content(self):
        """Test health check with invalid content"""
        lesson = Mock()
        lesson.content_version = 1
        lesson.validate_content_schema.return_value = (False, 'Invalid schema')
        lesson.content = {}

        health = ContentMigrationService.check_content_health(lesson)

        assert health['is_valid'] is False
        assert 'Invalid schema' in health['errors']

    def test_health_check_deprecated_fields(self):
        """Test health check detects deprecated fields"""
        lesson = Mock()
        lesson.content_version = 1
        lesson.type = 'vocabulary'
        lesson.validate_content_schema.return_value = (True, None)
        lesson.content = {'items': [], 'front': 'test'}

        health = ContentMigrationService.check_content_health(lesson)

        assert len(health['warnings']) > 0
        assert any('items' in w for w in health['warnings'])

    def test_health_check_handles_none_version(self):
        """Test health check when content_version is None"""
        lesson = Mock()
        lesson.content_version = None
        lesson.validate_content_schema.return_value = (True, None)
        lesson.content = {}

        health = ContentMigrationService.check_content_health(lesson)

        assert health['current_version'] == 1

    def test_health_check_exception_handling(self):
        """Test health check handles exceptions"""
        lesson = Mock()
        lesson.content_version = 1
        lesson.validate_content_schema.side_effect = Exception('Test error')

        health = ContentMigrationService.check_content_health(lesson)

        assert len(health['errors']) > 0
        assert any('Health check failed' in e for e in health['errors'])


class TestCheckDeprecatedFields:
    """Test _check_deprecated_fields method"""

    def test_vocabulary_deprecated_fields(self):
        """Test detecting deprecated vocabulary fields"""
        warnings = ContentMigrationService._check_deprecated_fields(
            'vocabulary',
            {'items': [], 'front': 'test', 'back': 'тест'}
        )

        assert len(warnings) == 3
        assert any('items' in w for w in warnings)
        assert any('front' in w for w in warnings)
        assert any('back' in w for w in warnings)

    def test_grammar_deprecated_fields(self):
        """Test detecting deprecated grammar fields"""
        warnings = ContentMigrationService._check_deprecated_fields(
            'grammar',
            {'rule': 'test', 'prompt': 'question'}
        )

        assert len(warnings) == 2

    def test_quiz_deprecated_fields(self):
        """Test detecting deprecated quiz fields"""
        warnings = ContentMigrationService._check_deprecated_fields(
            'quiz',
            {'correct_index': 0, 'prompt': 'Q?'}
        )

        assert len(warnings) == 2

    def test_text_deprecated_fields(self):
        """Test detecting deprecated text fields"""
        warnings = ContentMigrationService._check_deprecated_fields(
            'text',
            {'text': 'content'}
        )

        assert len(warnings) == 1

    def test_no_deprecated_fields(self):
        """Test with no deprecated fields"""
        warnings = ContentMigrationService._check_deprecated_fields(
            'vocabulary',
            {'words': []}
        )

        assert len(warnings) == 0

    def test_unknown_lesson_type(self):
        """Test with unknown lesson type"""
        warnings = ContentMigrationService._check_deprecated_fields(
            'unknown_type',
            {'any_field': 'value'}
        )

        assert len(warnings) == 0