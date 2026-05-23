# app/curriculum/routes/public.py
"""Public course catalog routes — no login required."""

from types import SimpleNamespace

from flask import Blueprint, abort, render_template
from sqlalchemy import func

from app.curriculum.models import CEFRLevel, Lessons, Module
from app.utils.db import db

courses_bp = Blueprint('courses', __name__)

_CEFR_FALLBACKS = {
    'A0': {
        'name': 'Starter',
        'description': 'Стартовый уровень для тех, кто начинает английский с полного нуля.',
        'order': 0,
    },
    'A1': {
        'name': 'Beginner',
        'description': 'Базовые фразы, простая грамматика и первые разговорные ситуации.',
        'order': 1,
    },
    'A2': {
        'name': 'Elementary',
        'description': 'Повседневные темы, устойчивые фразы и уверенная базовая коммуникация.',
        'order': 2,
    },
    'B1': {
        'name': 'Intermediate',
        'description': 'Самостоятельное общение, рассказы о событиях и аргументация простых идей.',
        'order': 3,
    },
    'B2': {
        'name': 'Upper-Intermediate',
        'description': 'Свободная речь на широкий круг тем, сложная грамматика и точная лексика.',
        'order': 4,
    },
    'C1': {
        'name': 'Advanced',
        'description': 'Продвинутая речь, академический английский и работа с нюансами регистра.',
        'order': 5,
    },
    'C2': {
        'name': 'Proficiency',
        'description': 'Профессиональный уровень владения английским для сложных текстов и точной речи.',
        'order': 6,
    },
}


def _fallback_level(level_code: str):
    data = _CEFR_FALLBACKS.get(level_code.upper())
    if not data:
        return None
    return SimpleNamespace(
        id=None,
        code=level_code.upper(),
        name=data['name'],
        description=data['description'],
        order=data['order'],
    )


@courses_bp.route('/')
def catalog():
    """Public course catalog showing CEFR levels with stats."""
    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

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
    level = CEFRLevel.query.filter_by(code=normalized_code).first()
    is_placeholder_level = False
    if not level:
        level = _fallback_level(normalized_code)
        if not level:
            abort(404)
        is_placeholder_level = True

    modules = []
    if level.id is not None:
        modules = (
            Module.query
            .filter_by(level_id=level.id)
            .order_by(Module.number)
            .all()
        )

    # Get sample lesson titles per module (first 3)
    modules_data = []
    for module in modules:
        sample_lessons = (
            Lessons.query
            .filter_by(module_id=module.id)
            .order_by(Lessons.order)
            .limit(3)
            .all()
        )
        lesson_count = Lessons.query.filter_by(module_id=module.id).count()
        modules_data.append({
            'module': module,
            'sample_lessons': sample_lessons,
            'lesson_count': lesson_count,
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
        is_placeholder_level=is_placeholder_level,
    )
