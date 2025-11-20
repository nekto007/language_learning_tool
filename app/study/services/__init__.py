"""
Study services module - business logic layer

Architecture:
- deck_service.py: Deck management (CRUD, sync, word operations)
- srs_service.py: Spaced Repetition System logic (card scheduling, reviews)
- quiz_service.py: Quiz generation and scoring
- game_service.py: Matching game logic
- stats_service.py: Statistics and leaderboards
- session_service.py: Study session tracking
"""

from .deck_service import DeckService
from .srs_service import SRSService
from .quiz_service import QuizService
from .game_service import GameService
from .stats_service import StatsService
from .session_service import SessionService

__all__ = [
    'DeckService',
    'SRSService',
    'QuizService',
    'GameService',
    'StatsService',
    'SessionService',
]
