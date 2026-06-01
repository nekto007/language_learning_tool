"""
Study services module - business logic layer

Architecture:
- deck_service.py: Deck management (CRUD, sync, word operations)
- srs_service.py: Spaced Repetition System logic (card scheduling, reviews)
- quiz_service.py: Quiz generation and scoring
- game_service.py: Matching game logic
- stats_service.py: Statistics and leaderboards
- session_service.py: Study session tracking
- collection_topic_service.py: Collection and topic management
"""

from .collection_topic_service import CollectionTopicService
from .deck_service import DeckService
from .game_service import GameService
from .quiz_service import QuizService
from .session_service import SessionService
from .srs_service import SRSService, get_user_word_ids
from .stats_service import StatsService

__all__ = [
    'DeckService',
    'SRSService',
    'QuizService',
    'GameService',
    'StatsService',
    'SessionService',
    'CollectionTopicService',
    'get_user_word_ids',
]
