# app/srs/constants.py
"""
SRS Constants - Anki-like spaced repetition system.

Rating Scale (1-2-3):
    1 - Не знаю (Don't know) → Fail: reset to step 0
    2 - Сомневаюсь (Doubt/Hard) → Stay at current step or slight progress
    3 - Знаю (Know/Good) → Advance to next step or graduate

Card States:
    NEW → First time seeing card
    LEARNING → Going through learning steps (minutes)
    REVIEW → Long-term review (days)
    RELEARNING → Failed review, going through relearning steps
"""
from enum import Enum


class CardState(str, Enum):
    """Card states matching Anki's SM-2 implementation."""
    NEW = 'new'
    LEARNING = 'learning'
    REVIEW = 'review'
    RELEARNING = 'relearning'


# Rating values
RATING_DONT_KNOW = 1  # Не знаю → fail, reset to step 0
RATING_DOUBT = 2       # Сомневаюсь → repeat current step or slight penalty
RATING_KNOW = 3        # Знаю → advance step or graduate

# Session limits
MAX_SESSION_ATTEMPTS = 3  # Max shows per card per session

# =============================================================================
# LEARNING STEPS (Anki-style)
# =============================================================================
# Steps are in MINUTES for intra-session requeue
# These define how many minutes until the card is shown again during learning

LEARNING_STEPS = [1, 10]  # [1 minute, 10 minutes] - steps for NEW cards
RELEARNING_STEPS = [10]   # [10 minutes] - steps for failed REVIEW cards

# Graduating interval - when card graduates from LEARNING to REVIEW
GRADUATING_INTERVAL = 1  # days

# Easy interval bonus - when user presses "Know" on first step
EASY_INTERVAL = 4  # days (skip learning steps entirely)

# =============================================================================
# REQUEUE POSITIONS (for intra-session card requeue)
# =============================================================================
# These approximate the learning step times as card positions
# E.g., if a step is 1 minute and ~30 seconds per card, that's ~2 cards

REQUEUE_RANGE_STEP_0 = (1, 3)    # ~1 minute = 1-3 cards away
REQUEUE_RANGE_STEP_1 = (8, 15)   # ~10 minutes = 8-15 cards away
REQUEUE_RANGE_HARD = (3, 6)      # Rating 2 on LEARNING: repeat same step

# Legacy compatibility (still used in some places)
REQUEUE_RANGE_DONT_KNOW = (1, 3)
REQUEUE_RANGE_DOUBT = (3, 6)

# =============================================================================
# SM-2 ALGORITHM PARAMETERS
# =============================================================================

DEFAULT_EASE_FACTOR = 2.5
MIN_EASE_FACTOR = 1.3
MAX_EASE_FACTOR = 2.8  # Anki allows up to 2.8, not 2.5

# Ease factor adjustments
EF_DECREASE_LAPSE = 0.20     # Failed REVIEW: decrease by 0.20
EF_DECREASE_HARD = 0.15      # Rating 2 on REVIEW: decrease by 0.15
EF_INCREASE_GOOD = 0.00      # Rating 2 on first reviews: no change
EF_INCREASE_EASY = 0.15      # Rating 3 (Know): increase by 0.15

# Interval multipliers
INTERVAL_MULTIPLIER_HARD = 1.2    # Rating 2 on REVIEW: interval * 1.2
INTERVAL_MULTIPLIER_GOOD = 1.0    # Rating 2 on LEARNING graduation: normal
INTERVAL_MULTIPLIER_EASY = 1.3    # Rating 3 on REVIEW: interval * ease * 1.3

# Legacy compatibility
INTERVAL_MULTIPLIER_DOUBT = 0.8
INTERVAL_MULTIPLIER_KNOW = 1.2
EF_DECREASE_DONT_KNOW = 0.20
EF_INCREASE_KNOW = 0.15

# =============================================================================
# LAPSE SETTINGS
# =============================================================================

# When a REVIEW card is failed, it becomes RELEARNING with these settings:
LAPSE_NEW_INTERVAL_PERCENT = 0  # New interval = 0% of old (i.e., reset to 1 day)
LAPSE_MINIMUM_INTERVAL = 1      # Minimum interval after lapse (days)
LEECH_THRESHOLD = 8             # Card becomes a "leech" after this many lapses

# =============================================================================
# CARD STATUSES (UserWord level)
# =============================================================================

STATUS_NEW = 'new'
STATUS_LEARNING = 'learning'
STATUS_REVIEW = 'review'
STATUS_MASTERED = 'mastered'

# =============================================================================
# DIRECTIONS
# =============================================================================

DIRECTION_ENG_RUS = 'eng-rus'
DIRECTION_RUS_ENG = 'rus-eng'

# =============================================================================
# THRESHOLDS
# =============================================================================

# Threshold for "mastered" word (both directions must have interval >= this)
LEARNED_INTERVAL_THRESHOLD = 35  # days

# Threshold for LEARNING → REVIEW transition
REVIEW_THRESHOLD_REPETITIONS = 3  # After 3 successful repetitions
