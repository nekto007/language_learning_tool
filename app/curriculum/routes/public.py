# app/curriculum/routes/public.py
"""Public course catalog routes — no login required."""

from collections import defaultdict

from flask import Blueprint, abort, render_template
from sqlalchemy import func

from app.curriculum.models import CEFRLevel, Lessons, Module
from app.utils.db import db

courses_bp = Blueprint('courses', __name__)
PUBLIC_CEFR_CODES = ('A1', 'A2', 'B1', 'B2', 'C1')


@courses_bp.route('/')
def catalog():
    """Public course catalog showing CEFR levels with stats."""
    levels = (
        CEFRLevel.query
        .filter(CEFRLevel.code.in_(PUBLIC_CEFR_CODES))
        .order_by(CEFRLevel.order)
        .all()
    )

    # Batch query: module count and lesson count per level
    stats_by_level = {}
    raw = (
        db.session.query(
            Module.level_id,
            func.count(func.distinct(Module.id)).label('modules'),
            func.count(Lessons.id).label('lessons'),
        )
        .outerjoin(Lessons, Lessons.module_id == Module.id)
        .group_by(Module.level_id)
        .all()
    )
    for level_id, mod_count, lesson_count in raw:
        stats_by_level[level_id] = {
            'modules': mod_count,
            'lessons': lesson_count,
        }

    levels_data = []
    for level in levels:
        stats = stats_by_level.get(level.id, {'modules': 0, 'lessons': 0})
        levels_data.append({
            'level': level,
            'modules': stats['modules'],
            'lessons': stats['lessons'],
        })

    return render_template(
        'curriculum/public_catalog.html',
        levels_data=levels_data,
    )


@courses_bp.route('/<string:level_code>')
def level_detail(level_code: str):
    """Public level detail page with module list and sample lesson titles."""
    normalized_code = level_code.upper()
    if normalized_code not in PUBLIC_CEFR_CODES:
        abort(404)

    level = CEFRLevel.query.filter_by(code=normalized_code).first()
    if not level:
        abort(404)

    modules = (
        Module.query
        .filter_by(level_id=level.id)
        .order_by(Module.number)
        .all()
    )

    # Batch query: all lessons for all modules to avoid N+1
    module_ids = [m.id for m in modules]
    all_lessons: list[Lessons] = []
    if module_ids:
        all_lessons = (
            Lessons.query
            .filter(Lessons.module_id.in_(module_ids))
            .order_by(Lessons.module_id, Lessons.order)
            .all()
        )

    lessons_by_module: dict[int, list[Lessons]] = defaultdict(list)
    for lesson in all_lessons:
        lessons_by_module[lesson.module_id].append(lesson)

    modules_data = []
    for module in modules:
        module_lessons = lessons_by_module[module.id]
        modules_data.append({
            'module': module,
            'sample_lessons': module_lessons[:3],
            'lesson_count': len(module_lessons),
        })

    meta_description = (
        f'Курс английского уровня {level.code} ({level.name}). '
        f'{len(modules)} модулей. Уроки, грамматика, словарь и практика.'
    )

    return render_template(
        'curriculum/public_level.html',
        level=level,
        modules_data=modules_data,
        meta_description=meta_description,
    )
