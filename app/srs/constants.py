# app/srs/constants.py
"""
SRS Constants - Unified rating system and parameters.

Rating Scale (1-2-3):
    1 - Не знаю (Don't know) → Show again in 1-2 cards
    2 - Сомневаюсь (Doubt) → Show again in 3-5 cards
    3 - Знаю (Know) → Remove from session, schedule next_review
"""

# Rating values
RATING_DONT_KNOW = 1  # Не знаю → показать через 1-2 карточки
RATING_DOUBT = 2       # Сомневаюсь → показать через 3-5 карточек
RATING_KNOW = 3        # Знаю → убрать из сессии

# Session limits
MAX_SESSION_ATTEMPTS = 3  # Макс. показов карточки за сессию

# Requeue positions (min, max) for random selection
REQUEUE_RANGE_DONT_KNOW = (1, 2)   # Rating 1: show in 1-2 cards
REQUEUE_RANGE_DOUBT = (3, 5)       # Rating 2: show in 3-5 cards

# SM-2 Algorithm parameters
DEFAULT_EASE_FACTOR = 2.5
MIN_EASE_FACTOR = 1.3
MAX_EASE_FACTOR = 2.5

# Ease factor adjustments
EF_DECREASE_DONT_KNOW = 0.20  # Rating 1: decrease by 0.20
EF_DECREASE_HARD = 0.15       # Compatibility with old "Hard" (2)
EF_INCREASE_KNOW = 0.15       # Rating 3: increase by 0.15

# Interval multipliers
INTERVAL_MULTIPLIER_DOUBT = 0.8   # Rating 2: 80% of normal interval
INTERVAL_MULTIPLIER_KNOW = 1.2    # Rating 3: 120% bonus to interval

# Card statuses
STATUS_NEW = 'new'
STATUS_LEARNING = 'learning'
STATUS_REVIEW = 'review'
STATUS_MASTERED = 'mastered'

# Directions
DIRECTION_ENG_RUS = 'eng-rus'
DIRECTION_RUS_ENG = 'rus-eng'

# Threshold for "learned" word (both directions must have interval >= this)
LEARNED_INTERVAL_THRESHOLD = 35  # days
