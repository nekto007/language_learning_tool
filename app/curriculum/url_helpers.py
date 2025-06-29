# app/curriculum/url_helpers.py

import re
from typing import Optional, Tuple
from flask import url_for
from app.curriculum.models import CEFRLevel, Module, Lessons
from app.utils.db import db

def get_lesson_slug(lesson):
    """Создать slug для урока"""
    if lesson.number == 49:  # Final lesson
        return 'final-summary'
    
    # Get module number from lesson (6 lessons per module)
    module_num = ((lesson.number - 1) // 6) + 1
    lesson_type_num = ((lesson.number - 1) % 6) + 1
    
    lesson_types = {
        1: 'vocabulary',
        2: 'reading', 
        3: 'grammar',
        4: 'quiz',
        5: 'matching',
        6: 'cards'
    }
    
    lesson_type = lesson_types.get(lesson_type_num, lesson.type)
    return f'module-{module_num}-{lesson_type}'

def get_course_slug(module):
    """Создать slug для курса"""
    if not module or not module.title:
        return None
    
    slug = module.title.lower()
    slug = slug.replace('course: ', '')
    slug = slug.replace(' ', '-')
    slug = ''.join(c for c in slug if c.isalnum() or c == '-')
    return slug

def get_beautiful_lesson_url(lesson):
    """Получить красивый URL для урока"""
    module = lesson.module
    
    if module and module.level and module.level.code == 'BC':
        course_slug = get_course_slug(module)
        lesson_slug = get_lesson_slug(lesson)
        
        if course_slug and lesson_slug:
            return url_for('curriculum.book_course_lesson', 
                         course_slug=course_slug, lesson_slug=lesson_slug)
    
    # Fallback to regular lesson URL
    return url_for('curriculum_lessons.lesson_detail', lesson_id=lesson.id)

def get_lesson_return_url(lesson):
    """Получить URL возврата для урока"""
    module = lesson.module
    
    if module and module.level and module.level.code == 'BC':
        course_slug = get_course_slug(module)
        if course_slug:
            return url_for('curriculum.book_course_lessons', course_slug=course_slug)
    
    return url_for('curriculum.module_lessons', module_id=module.id)

def get_next_lesson_url(lesson):
    """Получить URL следующего урока"""
    from app.curriculum.models import Lessons
    
    next_lesson = Lessons.query.filter(
        Lessons.module_id == lesson.module_id,
        Lessons.number > lesson.number
    ).order_by(Lessons.number).first()
    
    if next_lesson:
        return get_beautiful_lesson_url(next_lesson)
    
    return None

def get_book_course_url(module):
    """Получить правильный URL для книжного курса"""
    if hasattr(module, 'raw_content') and module.raw_content:
        slug = module.raw_content.get('slug')
        if slug and module.level and module.level.code == 'BC':
            return url_for('curriculum.book_course_lessons', course_slug=slug)
    
    # Создать slug из названия если нет в метаданных
    if module.level and module.level.code == 'BC':
        course_slug = get_course_slug(module)
        if course_slug:
            return url_for('curriculum.book_course_lessons', course_slug=course_slug)
    
    # Fallback to module ID
    return url_for('curriculum.module_lessons', module_id=module.id)


# =============================================================================
# НОВЫЕ ФУНКЦИИ ДЛЯ КРАСИВЫХ URL
# =============================================================================

def slugify(text: str) -> str:
    """Преобразует текст в URL-friendly slug"""
    if not text:
        return ""
    
    # Приводим к нижнему регистру
    slug = text.lower()
    
    # Заменяем пробелы и специальные символы на дефисы
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '-', slug)
    
    # Убираем дефисы в начале и конце
    slug = slug.strip('-')
    
    return slug


def level_to_slug(level_code: str) -> str:
    """Преобразует код уровня в slug"""
    if not level_code:
        return ""
    return level_code.lower()


def slug_to_level(slug: str) -> Optional[str]:
    """Преобразует slug обратно в код уровня"""
    if not slug:
        return None
    return slug.upper()


def module_to_slug(module: Module) -> str:
    """Преобразует модуль в slug"""
    return f"module-{module.number}"


def slug_to_module_number(slug: str) -> Optional[int]:
    """Извлекает номер модуля из slug"""
    if not slug or not slug.startswith('module-'):
        return None
    
    try:
        number_str = slug.replace('module-', '')
        return int(number_str)
    except ValueError:
        return None


def lesson_to_slug(lesson: Lessons) -> str:
    """Преобразует урок в slug"""
    base_slug = f"lesson-{lesson.number}"
    
    # Добавляем тип урока для уникальности
    if lesson.type:
        base_slug += f"-{lesson.type}"
    
    return base_slug


def slug_to_lesson_info(slug: str) -> Tuple[Optional[int], Optional[str]]:
    """Извлекает номер урока и тип из slug"""
    if not slug or not slug.startswith('lesson-'):
        return None, None
    
    # Удаляем префикс "lesson-"
    remainder = slug[7:]
    
    # Разделяем по дефису
    parts = remainder.split('-', 1)
    
    try:
        lesson_number = int(parts[0])
        lesson_type = parts[1] if len(parts) > 1 else None
        return lesson_number, lesson_type
    except ValueError:
        return None, None


def build_beautiful_lesson_url(level_code: str, module_number: int, lesson_number: int, lesson_type: str = None) -> str:
    """Строит красивый URL для урока"""
    base_url = f"/learn/{level_to_slug(level_code)}/module-{module_number}/lesson-{lesson_number}"
    
    if lesson_type:
        base_url += f"-{lesson_type}"
    
    return base_url + "/"


def get_lesson_by_beautiful_url(level_code: str, module_number: int, lesson_number: int, lesson_type: str = None) -> Optional[Lessons]:
    """Находит урок по красивому URL"""
    # Сначала находим уровень
    level = CEFRLevel.query.filter_by(code=level_code.upper()).first()
    if not level:
        return None
    
    # Находим модуль
    module = Module.query.filter_by(level_id=level.id, number=module_number).first()
    if not module:
        return None
    
    # Находим урок
    query = Lessons.query.filter_by(module_id=module.id, number=lesson_number)
    
    if lesson_type:
        query = query.filter_by(type=lesson_type)
    
    return query.first()


def get_module_by_beautiful_url(level_code: str, module_number: int) -> Optional[Module]:
    """Находит модуль по красивому URL"""
    level = CEFRLevel.query.filter_by(code=level_code.upper()).first()
    if not level:
        return None
    
    return Module.query.filter_by(level_id=level.id, number=module_number).first()


def get_level_by_beautiful_url(level_code: str) -> Optional[CEFRLevel]:
    """Находит уровень по красивому URL"""
    return CEFRLevel.query.filter_by(code=level_code.upper()).first()


def generate_breadcrumbs(level_code: str = None, module_number: int = None, lesson_number: int = None, lesson_type: str = None) -> list:
    """Генерирует breadcrumbs для навигации"""
    breadcrumbs = [
        {'name': 'Обучение', 'url': '/learn/'}
    ]
    
    if level_code:
        level = get_level_by_beautiful_url(level_code)
        if level:
            breadcrumbs.append({
                'name': f"{level.code} - {level.name}",
                'url': f"/learn/{level_to_slug(level_code)}/"
            })
    
    if module_number and level_code:
        module = get_module_by_beautiful_url(level_code, module_number)
        if module:
            breadcrumbs.append({
                'name': f"Модуль {module_number}",
                'url': f"/learn/{level_to_slug(level_code)}/module-{module_number}/"
            })
    
    if lesson_number and level_code and module_number:
        lesson = get_lesson_by_beautiful_url(level_code, module_number, lesson_number, lesson_type)
        if lesson:
            breadcrumbs.append({
                'name': f"Урок {lesson_number}: {lesson.title}",
                'url': build_beautiful_lesson_url(level_code, module_number, lesson_number, lesson_type)
            })
    
    return breadcrumbs
