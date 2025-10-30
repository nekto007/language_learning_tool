# app/curriculum/services/content_migration_service.py

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ContentMigrationService:
    """
    Service for migrating lesson content between schema versions.

    Version History:
    - v1: Initial schema (current)
    - v2: (Future) Normalized field names across lesson types
    - v3: (Future) Enhanced metadata and accessibility features
    """

    LATEST_VERSION = 1  # Update this when adding new versions

    @classmethod
    def migrate_content(
        cls,
        lesson_type: str,
        content: Dict[str, Any],
        from_version: int,
        to_version: int
    ) -> Optional[Dict[str, Any]]:
        """
        Migrate content from one version to another.

        Args:
            lesson_type: Type of lesson (vocabulary, grammar, etc.)
            content: Content to migrate
            from_version: Current version
            to_version: Target version

        Returns:
            Migrated content or None if migration failed
        """
        if from_version == to_version:
            return content

        if from_version > to_version:
            logger.warning(f"Cannot downgrade from v{from_version} to v{to_version}")
            return None

        try:
            migrated = content.copy()

            # Apply migrations sequentially
            for version in range(from_version, to_version):
                next_version = version + 1
                migration_method = getattr(
                    cls,
                    f'_migrate_v{version}_to_v{next_version}',
                    None
                )

                if migration_method:
                    migrated = migration_method(lesson_type, migrated)
                    if migrated is None:
                        logger.error(f"Migration from v{version} to v{next_version} failed")
                        return None
                else:
                    logger.warning(f"No migration method for v{version} to v{next_version}")

            return migrated

        except Exception as e:
            logger.error(f"Error migrating content: {str(e)}")
            return None

    @classmethod
    def _migrate_v1_to_v2(cls, lesson_type: str, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Migrate from version 1 to version 2.

        V2 Changes:
        - Normalize field names across lesson types
        - Add required metadata fields
        - Standardize exercise structure
        """
        migrated = content.copy()

        # Lesson type specific migrations
        if lesson_type == 'vocabulary':
            migrated = cls._migrate_vocabulary_v1_to_v2(migrated)
        elif lesson_type == 'grammar':
            migrated = cls._migrate_grammar_v1_to_v2(migrated)
        elif lesson_type == 'quiz':
            migrated = cls._migrate_quiz_v1_to_v2(migrated)
        elif lesson_type == 'matching':
            migrated = cls._migrate_matching_v1_to_v2(migrated)
        elif lesson_type == 'text':
            migrated = cls._migrate_text_v1_to_v2(migrated)
        elif lesson_type == 'card':
            migrated = cls._migrate_card_v1_to_v2(migrated)
        elif lesson_type == 'final_test':
            migrated = cls._migrate_final_test_v1_to_v2(migrated)

        # Add version metadata
        migrated['_schema_version'] = 2
        migrated['_migrated_at'] = 'auto'

        return migrated

    @classmethod
    def _migrate_vocabulary_v1_to_v2(cls, content: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate vocabulary lesson from v1 to v2."""
        migrated = content.copy()

        # Normalize 'items' to 'words'
        if 'items' in migrated and 'words' not in migrated:
            migrated['words'] = migrated.pop('items')

        # Ensure each word has required fields
        if 'words' in migrated:
            for word in migrated['words']:
                # Normalize field names
                if 'front' in word and 'word' not in word:
                    word['word'] = word.pop('front')
                if 'back' in word and 'translation' not in word:
                    word['translation'] = word.pop('back')

        return migrated

    @classmethod
    def _migrate_grammar_v1_to_v2(cls, content: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate grammar lesson from v1 to v2."""
        migrated = content.copy()

        # Normalize 'rule' to 'content' if no content exists
        if 'rule' in migrated and 'content' not in migrated:
            migrated['content'] = migrated.get('rule', '')

        # Ensure exercises have standard structure
        if 'exercises' in migrated:
            for exercise in migrated['exercises']:
                # Normalize question field
                if 'prompt' in exercise and 'question' not in exercise:
                    exercise['question'] = exercise.pop('prompt')

        return migrated

    @classmethod
    def _migrate_quiz_v1_to_v2(cls, content: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate quiz lesson from v1 to v2."""
        migrated = content.copy()

        if 'questions' in migrated:
            for question in migrated['questions']:
                # Normalize answer fields
                if 'correct_index' in question and 'correct' not in question:
                    question['correct'] = question['correct_index']

                # Normalize prompt to question
                if 'prompt' in question and 'question' not in question:
                    question['question'] = question.pop('prompt')

        return migrated

    @classmethod
    def _migrate_matching_v1_to_v2(cls, content: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate matching lesson from v1 to v2."""
        # No changes needed for v2
        return content.copy()

    @classmethod
    def _migrate_text_v1_to_v2(cls, content: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate text lesson from v1 to v2."""
        migrated = content.copy()

        # Normalize 'text' to 'content'
        if 'text' in migrated and 'content' not in migrated:
            migrated['content'] = migrated.get('text', '')

        return migrated

    @classmethod
    def _migrate_card_v1_to_v2(cls, content: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate card lesson from v1 to v2."""
        # No changes needed for v2
        return content.copy()

    @classmethod
    def _migrate_final_test_v1_to_v2(cls, content: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate final test lesson from v1 to v2."""
        migrated = content.copy()

        # Normalize exercises/questions
        if 'exercises' in migrated and 'questions' not in migrated:
            migrated['questions'] = migrated.get('exercises', [])

        return migrated

    @classmethod
    def check_content_health(cls, lesson) -> Dict[str, Any]:
        """
        Check content health and provide migration recommendations.

        Args:
            lesson: Lesson object

        Returns:
            Health check results
        """
        health = {
            'current_version': lesson.content_version or 1,
            'latest_version': cls.LATEST_VERSION,
            'needs_migration': (lesson.content_version or 1) < cls.LATEST_VERSION,
            'is_valid': False,
            'errors': [],
            'warnings': []
        }

        try:
            # Validate content
            is_valid, error_msg = lesson.validate_content_schema()
            health['is_valid'] = is_valid

            if not is_valid:
                health['errors'].append(error_msg)

            # Check for deprecated fields
            if lesson.content:
                deprecated = cls._check_deprecated_fields(lesson.type, lesson.content)
                if deprecated:
                    health['warnings'].extend(deprecated)

        except Exception as e:
            health['errors'].append(f"Health check failed: {str(e)}")

        return health

    @classmethod
    def _check_deprecated_fields(cls, lesson_type: str, content: Dict[str, Any]) -> list:
        """Check for deprecated fields in content."""
        warnings = []

        deprecated_fields = {
            'vocabulary': ['front', 'back', 'items'],
            'grammar': ['rule', 'prompt'],
            'quiz': ['correct_index', 'prompt'],
            'text': ['text']
        }

        if lesson_type in deprecated_fields:
            for field in deprecated_fields[lesson_type]:
                if field in content:
                    warnings.append(f"Deprecated field '{field}' found. Consider migrating.")

        return warnings
