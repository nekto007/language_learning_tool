import json
from pathlib import Path
from typing import Dict, List

from app.curriculum.models import CEFRLevel, Module, Lessons
from app.utils.db import db

LESSON_TYPE_MAP = {
    'vocabulary': 'vocabulary',
    'grammar': 'grammar',
    'quiz': 'quiz',
    'flashcards': 'card',
    'listening': 'matching',
    'reading': 'text',
    'listening_immersion': 'text',
    'test': 'final_test'
}


def _load_json(path: Path) -> Dict:
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def _get_or_create_level(level_code: str) -> CEFRLevel:
    target_code = level_code or 'A1'

    level = CEFRLevel.query.filter_by(code=target_code).first()
    if level:
        return level

    if target_code != 'A1':
        fallback = CEFRLevel.query.filter_by(code='A1').first()
        if fallback:
            return fallback
        target_code = 'A1'

    level = CEFRLevel(
        code=target_code,
        name='Beginner',
        description='Beginner level',
        order=1
    )
    db.session.add(level)
    db.session.commit()
    return level


def _should_replace_module(existing_module: Module) -> bool:
    """Ask user whether to replace existing module."""
    response = input(
        f"Module with number {existing_module.number} already exists at level "
        f"{existing_module.level.code if existing_module.level else 'unknown'}. Replace? [y/N]: "
    ).strip().lower()
    return response == 'y'


def _create_lessons(module: Module, lessons_data: List[Dict]) -> None:
    for idx, lesson_data in enumerate(lessons_data):
        lesson_type = LESSON_TYPE_MAP.get(lesson_data.get('type'), 'quiz')
        lesson_number = lesson_data.get('order', idx)

        lesson = Lessons(
            module_id=module.id,
            number=lesson_number,
            title=lesson_data.get('title', f'Lesson {lesson_number}'),
            type=lesson_type,
            order=lesson_number,
            content=lesson_data.get('content', {})
        )
        db.session.add(lesson)


def import_module_from_json(file_path: str) -> bool:
    """
    Import curriculum module definition from JSON file.

    Returns:
        bool: True if import succeeded, False otherwise.
    """
    try:
        path = Path(file_path)
        if not path.exists():
            print(f"File not found: {file_path}")
            return False

        data = _load_json(path)
        module_data = data.get('module')
        if not module_data:
            print("Invalid file format: missing 'module' key")
            return False

        module_number = module_data.get('id')
        if module_number is None:
            print("Module id is required")
            return False

        level_code = module_data.get('level', 'A1')
        level = _get_or_create_level(level_code)

        # Handle existing module
        existing_module = Module.query.filter_by(level_id=level.id, number=module_number).first()
        if existing_module:
            if not _should_replace_module(existing_module):
                return False
            db.session.delete(existing_module)
            db.session.commit()

        module = Module(
            level_id=level.id,
            number=module_number,
            title=module_data.get('title', 'Untitled Module'),
            description=module_data.get('description'),
            raw_content=module_data
        )
        db.session.add(module)
        db.session.flush()  # populate module.id for lesson FK

        lessons_data = module_data.get('lessons', [])
        _create_lessons(module, lessons_data)

        db.session.commit()
        return True
    except Exception as exc:
        db.session.rollback()
        print(f"Error importing module: {exc}")
        return False
