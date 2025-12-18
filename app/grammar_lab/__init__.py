# app/grammar_lab/__init__.py
"""
Grammar Lab - Standalone grammar training module.

Provides:
- Grammar topics organized by CEFR level (A1-C2)
- Multiple exercise types (fill_blank, multiple_choice, etc.)
- SRS-based spaced repetition for grammar
- Progress tracking and gamification
"""

from flask import Blueprint

grammar_lab_bp = Blueprint('grammar_lab', __name__, url_prefix='/grammar-lab')

from . import routes  # noqa: E402, F401
