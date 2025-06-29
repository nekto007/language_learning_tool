"""
Block Schema Importer for Book Courses

This module handles importing YAML/JSON schemas that define how chapters
are grouped into blocks for course generation.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import yaml

from app.books.models import Block, BlockChapter, Book, Chapter
from app.utils.db import db

logger = logging.getLogger(__name__)


class BlockSchemaImporter:
    """Handles importing block schemas for books"""

    def __init__(self, book_id: int):
        self.book_id = book_id
        self.book = Book.query.get_or_404(book_id)

    def import_from_file(self, file_path: str) -> bool:
        """Import block schema from YAML or JSON file"""
        try:
            file_path = Path(file_path)

            if not file_path.exists():
                logger.error(f"Schema file not found: {file_path}")
                return False

            # Read file content
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Parse based on file extension
            if file_path.suffix.lower() in ['.yml', '.yaml']:
                schema_data = yaml.safe_load(content)
            elif file_path.suffix.lower() == '.json':
                schema_data = json.loads(content)
            else:
                logger.error(f"Unsupported file format: {file_path.suffix}")
                return False

            return self.import_from_data(schema_data)

        except Exception as e:
            logger.error(f"Error importing schema from file {file_path}: {str(e)}")
            return False

    def import_from_data(self, schema_data: List[Dict[str, Any]]) -> bool:
        """Import block schema from parsed data"""
        try:
            # Validate schema structure
            if not self._validate_schema(schema_data):
                return False

            # Clear existing blocks for this course
            self._clear_existing_blocks()

            # Import each block
            for block_data in schema_data:
                if not self._import_block(block_data):
                    db.session.rollback()
                    return False

            db.session.commit()
            logger.info(f"Successfully imported {len(schema_data)} blocks for book {self.book.id}")
            return True

        except Exception as e:
            logger.error(f"Error importing schema data: {str(e)}")
            db.session.rollback()
            return False

    def _validate_schema(self, schema_data: List[Dict[str, Any]]) -> bool:
        """Validate the schema structure"""
        if not isinstance(schema_data, list):
            logger.error("Schema must be a list of blocks")
            return False

        required_fields = ['block', 'chapters']

        for i, block_data in enumerate(schema_data):
            if not isinstance(block_data, dict):
                logger.error(f"Block {i} must be a dictionary")
                return False

            # Check required fields
            for field in required_fields:
                if field not in block_data:
                    logger.error(f"Block {i} missing required field: {field}")
                    return False

            # Validate block number
            if not isinstance(block_data['block'], int) or block_data['block'] <= 0:
                logger.error(f"Block {i} must have a positive integer block number")
                return False

            # Validate chapters list
            if not isinstance(block_data['chapters'], list) or not block_data['chapters']:
                logger.error(f"Block {i} must have a non-empty chapters list")
                return False

            # Check if chapters exist in the book
            for chapter_num in block_data['chapters']:
                if not isinstance(chapter_num, int) or chapter_num <= 0:
                    logger.error(f"Block {i} contains invalid chapter number: {chapter_num}")
                    return False

                chapter = Chapter.query.filter_by(
                    book_id=self.book.id,
                    chap_num=chapter_num
                ).first()

                if not chapter:
                    logger.error(f"Block {i} references non-existent chapter {chapter_num}")
                    return False

        return True

    def _clear_existing_blocks(self):
        """Remove existing blocks for this book"""
        existing_blocks = Block.query.filter_by(book_id=self.book_id).all()
        for block in existing_blocks:
            db.session.delete(block)

    def _import_block(self, block_data: Dict[str, Any]) -> bool:
        """Import a single block"""
        try:
            # Create block using existing Block model
            block = Block(
                book_id=self.book_id,
                block_num=block_data['block'],
                grammar_key=block_data.get('grammar', ''),
                focus_vocab=block_data.get('focus_vocab', '')
            )

            db.session.add(block)
            db.session.flush()  # Get the block ID

            # Create block-chapter relationships
            for chapter_num in block_data['chapters']:
                chapter = Chapter.query.filter_by(
                    book_id=self.book.id,
                    chap_num=chapter_num
                ).first()

                if chapter:
                    block_chapter = BlockChapter(
                        block_id=block.id,
                        chapter_id=chapter.id
                    )
                    db.session.add(block_chapter)

            logger.info(f"Created block {block.block_num} with {len(block_data['chapters'])} chapters")
            return True

        except Exception as e:
            logger.error(f"Error importing block {block_data.get('block', 'unknown')}: {str(e)}")
            return False

    def generate_default_schema(self) -> List[Dict[str, Any]]:
        """Generate a default schema based on book chapters"""
        chapters = Chapter.query.filter_by(book_id=self.book.id).order_by(Chapter.chap_num).all()

        if not chapters:
            return []

        # Group chapters into blocks of 2
        blocks = []
        chapters_per_block = 2

        for i in range(0, len(chapters), chapters_per_block):
            block_chapters = chapters[i:i + chapters_per_block]
            block_number = (i // chapters_per_block) + 1

            block_data = {
                'block': block_number,
                'chapters': [ch.chap_num for ch in block_chapters],
                'title': f"Block {block_number}",
                'description': f"Chapters {block_chapters[0].chap_num}-{block_chapters[-1].chap_num}",
                'grammar': '',
                'focus_vocab': '',
                'duration_hours': 2
            }

            blocks.append(block_data)

        return blocks

    def export_schema(self) -> List[Dict[str, Any]]:
        """Export current block structure as schema"""
        blocks = Block.query.filter_by(
            book_id=self.book_id
        ).order_by(Block.block_num).all()

        schema = []
        for block in blocks:
            # Get chapter numbers for this block
            chapters = []
            for chapter in block.chapters:
                chapters.append(chapter.chap_num)
            chapters.sort()

            block_data = {
                'block': block.block_num,
                'chapters': chapters,
                'grammar': block.grammar_key or '',
                'focus_vocab': block.focus_vocab or ''
            }

            schema.append(block_data)

        return schema


def create_example_schema(book_title: str = "Example Book") -> str:
    """Create an example YAML schema"""
    example_schema = [
        {
            'block': 1,
            'chapters': [1, 2],
            'title': 'Introduction',
            'description': 'Getting started with the story',
            'grammar': 'Present_Perfect_vs_Past_Simple',
            'focus_vocab': 'family, feelings',
            'duration_hours': 2
        },
        {
            'block': 2,
            'chapters': [3, 4],
            'title': 'Development',
            'description': 'The plot thickens',
            'grammar': 'Reported_Speech',
            'focus_vocab': 'letters, animals',
            'duration_hours': 2
        },
        {
            'block': 3,
            'chapters': [5, 6],
            'title': 'Climax',
            'description': 'Peak of the story',
            'grammar': 'Relative_Clauses',
            'focus_vocab': 'shopping, transport',
            'duration_hours': 3
        }
    ]

    yaml_content = f"""# Block Schema for {book_title}
# This file defines how chapters are grouped into learning blocks

# Each block should contain:
# - block: unique block number (integer)
# - chapters: list of chapter numbers to include
# - title: descriptive title for the block
# - description: what students will learn in this block
# - grammar: main grammar focus (optional)
# - focus_vocab: key vocabulary themes (optional)
# - duration_hours: estimated time to complete (optional)

{yaml.dump(example_schema, default_flow_style=False, allow_unicode=True)}"""

    return yaml_content
