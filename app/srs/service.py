# app/srs/service.py
"""
Unified SRS Service - Anki-like spaced repetition system.

Responsibilities:
- Card scheduling with state machine (NEW → LEARNING → REVIEW ⟷ RELEARNING)
- Session management with priority queues
- Requeue position calculation for intra-session learning
- Both directions (eng-rus, rus-eng)
"""

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.srs.constants import (
    CardState,
    RATING_DONT_KNOW,
    RATING_DOUBT,
    RATING_KNOW,
    MAX_SESSION_ATTEMPTS,
    REQUEUE_RANGE_STEP_0,
    REQUEUE_RANGE_STEP_1,
    REQUEUE_RANGE_HARD,
    REQUEUE_RANGE_DONT_KNOW,
    REQUEUE_RANGE_DOUBT,
    LEARNING_STEPS,
    RELEARNING_STEPS,
    GRADUATING_INTERVAL,
    EASY_INTERVAL,
    DEFAULT_EASE_FACTOR,
    MIN_EASE_FACTOR,
    MAX_EASE_FACTOR,
    EF_DECREASE_LAPSE,
    EF_DECREASE_HARD,
    EF_INCREASE_EASY,
    INTERVAL_MULTIPLIER_HARD,
    INTERVAL_MULTIPLIER_EASY,
    LAPSE_MINIMUM_INTERVAL,
    DIRECTION_ENG_RUS,
    DIRECTION_RUS_ENG,
)
from app.study.models import UserCardDirection, UserWord
from app.utils.db import db
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)


class UnifiedSRSService:
    """
    Anki-like SRS service for all application modules.

    State Machine:
        NEW → LEARNING → REVIEW ⟷ RELEARNING

    Used in:
    - /study (flashcards)
    - /book-courses (vocabulary lessons)
    - /curriculum (lessons)
    """

    @staticmethod
    def get_requeue_position(
        rating: int,
        state: str = None,
        step_index: int = 0
    ) -> Optional[int]:
        """
        Returns position for re-showing card in queue based on state and rating.

        For LEARNING/RELEARNING states, uses step-based requeue ranges.
        For REVIEW state (or unknown), returns None (card scheduled for days).

        Args:
            rating: Card rating (1, 2, or 3)
            state: Current card state ('new', 'learning', 'review', 'relearning')
            step_index: Current learning step index (0-based)

        Returns:
            int: Position for insertion (show in N cards)
            None: If card should not be requeued (scheduled for days)
        """
        # For REVIEW state, cards are scheduled for days, not requeued
        if state == CardState.REVIEW.value:
            return None

        # For NEW cards becoming LEARNING
        if state == CardState.NEW.value or state is None:
            if rating == RATING_DONT_KNOW:
                return random.randint(*REQUEUE_RANGE_STEP_0)
            elif rating == RATING_DOUBT:
                return random.randint(*REQUEUE_RANGE_HARD)
            elif rating == RATING_KNOW:
                return None  # Graduated or moved to next step
            return None

        # For LEARNING or RELEARNING states
        if state in (CardState.LEARNING.value, CardState.RELEARNING.value):
            if rating == RATING_DONT_KNOW:
                # Reset to step 0
                return random.randint(*REQUEUE_RANGE_STEP_0)
            elif rating == RATING_DOUBT:
                # Repeat current step
                return random.randint(*REQUEUE_RANGE_HARD)
            elif rating == RATING_KNOW:
                # Advance to next step
                steps = LEARNING_STEPS if state == CardState.LEARNING.value else RELEARNING_STEPS
                next_step = step_index + 1
                if next_step >= len(steps):
                    return None  # Graduated
                elif next_step == 1 and len(REQUEUE_RANGE_STEP_1) == 2:
                    return random.randint(*REQUEUE_RANGE_STEP_1)
                else:
                    return random.randint(*REQUEUE_RANGE_STEP_0)

        # Default fallback
        if rating == RATING_DONT_KNOW:
            return random.randint(*REQUEUE_RANGE_DONT_KNOW)
        elif rating == RATING_DOUBT:
            return random.randint(*REQUEUE_RANGE_DOUBT)
        return None

    @staticmethod
    def calculate_sm2_update(
        rating: int,
        state: str,
        step_index: int,
        repetitions: int,
        interval: int,
        ease_factor: float,
        lapses: int = 0
    ) -> Dict[str, Any]:
        """
        Calculate new SM-2 parameters based on Anki-like state machine.

        Args:
            rating: Rating (1, 2, 3)
            state: Current card state
            step_index: Current learning step (0-based)
            repetitions: Current repetition count
            interval: Current interval (days)
            ease_factor: Current ease factor
            lapses: Current lapse count

        Returns:
            Dict with new state, step_index, repetitions, interval, ease_factor,
            lapses, requeue_minutes, and days_until_review
        """
        result = {
            'state': state,
            'step_index': step_index,
            'repetitions': repetitions,
            'interval': interval,
            'ease_factor': ease_factor,
            'lapses': lapses,
            'requeue_minutes': None,
            'days_until_review': 0
        }

        # Initialize state if missing
        if not state or state == 'new':
            state = CardState.NEW.value

        # =========================================================================
        # Handle based on current state
        # =========================================================================

        if state == CardState.NEW.value:
            result = UnifiedSRSService._handle_new(rating, ease_factor)

        elif state == CardState.LEARNING.value:
            result = UnifiedSRSService._handle_learning(
                rating, step_index, ease_factor, LEARNING_STEPS
            )

        elif state == CardState.REVIEW.value:
            result = UnifiedSRSService._handle_review(
                rating, interval, ease_factor, lapses
            )

        elif state == CardState.RELEARNING.value:
            result = UnifiedSRSService._handle_relearning(
                rating, step_index, ease_factor, lapses, RELEARNING_STEPS
            )

        # Update repetitions
        if rating >= RATING_DOUBT:
            result['repetitions'] = repetitions + 1
        elif rating == RATING_DONT_KNOW and state == CardState.REVIEW.value:
            # Keep repetitions on lapse
            result['repetitions'] = repetitions
        elif rating == RATING_DONT_KNOW:
            result['repetitions'] = 0

        return result

    @staticmethod
    def _handle_new(rating: int, ease_factor: float) -> Dict[str, Any]:
        """Handle rating for NEW card."""
        if rating == RATING_KNOW:
            # Easy: skip learning entirely
            return {
                'state': CardState.REVIEW.value,
                'step_index': 0,
                'interval': EASY_INTERVAL,
                'ease_factor': min(MAX_EASE_FACTOR, ease_factor + EF_INCREASE_EASY),
                'lapses': 0,
                'requeue_minutes': None,
                'days_until_review': EASY_INTERVAL
            }
        else:
            # Start learning
            step = 0 if rating == RATING_DONT_KNOW else 1
            step = min(step, len(LEARNING_STEPS) - 1) if LEARNING_STEPS else 0
            return {
                'state': CardState.LEARNING.value,
                'step_index': step,
                'interval': 0,
                'ease_factor': ease_factor,
                'lapses': 0,
                'requeue_minutes': LEARNING_STEPS[step] if LEARNING_STEPS else 1,
                'days_until_review': 0
            }

    @staticmethod
    def _handle_learning(
        rating: int,
        step_index: int,
        ease_factor: float,
        steps: List[int]
    ) -> Dict[str, Any]:
        """Handle rating for LEARNING card."""
        if rating == RATING_DONT_KNOW:
            # Reset to step 0
            return {
                'state': CardState.LEARNING.value,
                'step_index': 0,
                'interval': 0,
                'ease_factor': ease_factor,
                'lapses': 0,
                'requeue_minutes': steps[0] if steps else 1,
                'days_until_review': 0
            }
        elif rating == RATING_DOUBT:
            # Repeat current step
            return {
                'state': CardState.LEARNING.value,
                'step_index': step_index,
                'interval': 0,
                'ease_factor': ease_factor,
                'lapses': 0,
                'requeue_minutes': steps[step_index] if step_index < len(steps) else 10,
                'days_until_review': 0
            }
        else:  # RATING_KNOW
            # Advance or graduate
            next_step = step_index + 1
            if next_step >= len(steps):
                # Graduate to REVIEW
                return {
                    'state': CardState.REVIEW.value,
                    'step_index': 0,
                    'interval': GRADUATING_INTERVAL,
                    'ease_factor': min(MAX_EASE_FACTOR, ease_factor + EF_INCREASE_EASY),
                    'lapses': 0,
                    'requeue_minutes': None,
                    'days_until_review': GRADUATING_INTERVAL
                }
            else:
                # Continue learning
                return {
                    'state': CardState.LEARNING.value,
                    'step_index': next_step,
                    'interval': 0,
                    'ease_factor': ease_factor,
                    'lapses': 0,
                    'requeue_minutes': steps[next_step],
                    'days_until_review': 0
                }

    @staticmethod
    def _handle_review(
        rating: int,
        interval: int,
        ease_factor: float,
        lapses: int
    ) -> Dict[str, Any]:
        """Handle rating for REVIEW card."""
        old_interval = max(1, interval)
        old_ef = ease_factor or DEFAULT_EASE_FACTOR

        if rating == RATING_DONT_KNOW:
            # Lapse: go to RELEARNING
            return {
                'state': CardState.RELEARNING.value,
                'step_index': 0,
                'interval': LAPSE_MINIMUM_INTERVAL,
                'ease_factor': max(MIN_EASE_FACTOR, old_ef - EF_DECREASE_LAPSE),
                'lapses': lapses + 1,
                'requeue_minutes': RELEARNING_STEPS[0] if RELEARNING_STEPS else 10,
                'days_until_review': 0
            }
        elif rating == RATING_DOUBT:
            # Hard: small increase, ease penalty
            new_interval = max(old_interval + 1, round(old_interval * INTERVAL_MULTIPLIER_HARD))
            new_ef = max(MIN_EASE_FACTOR, old_ef - EF_DECREASE_HARD)
            return {
                'state': CardState.REVIEW.value,
                'step_index': 0,
                'interval': new_interval,
                'ease_factor': new_ef,
                'lapses': lapses,
                'requeue_minutes': None,
                'days_until_review': new_interval
            }
        else:  # RATING_KNOW
            # Good: normal increase with ease bonus
            new_interval = max(old_interval + 1, round(old_interval * old_ef * INTERVAL_MULTIPLIER_EASY))
            new_ef = min(MAX_EASE_FACTOR, old_ef + EF_INCREASE_EASY)
            return {
                'state': CardState.REVIEW.value,
                'step_index': 0,
                'interval': new_interval,
                'ease_factor': new_ef,
                'lapses': lapses,
                'requeue_minutes': None,
                'days_until_review': new_interval
            }

    @staticmethod
    def _handle_relearning(
        rating: int,
        step_index: int,
        ease_factor: float,
        lapses: int,
        steps: List[int]
    ) -> Dict[str, Any]:
        """Handle rating for RELEARNING card."""
        if rating == RATING_DONT_KNOW:
            # Reset to step 0
            return {
                'state': CardState.RELEARNING.value,
                'step_index': 0,
                'interval': LAPSE_MINIMUM_INTERVAL,
                'ease_factor': ease_factor,
                'lapses': lapses,
                'requeue_minutes': steps[0] if steps else 10,
                'days_until_review': 0
            }
        elif rating == RATING_DOUBT:
            # Repeat current step
            return {
                'state': CardState.RELEARNING.value,
                'step_index': step_index,
                'interval': LAPSE_MINIMUM_INTERVAL,
                'ease_factor': ease_factor,
                'lapses': lapses,
                'requeue_minutes': steps[step_index] if step_index < len(steps) else 10,
                'days_until_review': 0
            }
        else:  # RATING_KNOW
            # Advance or return to REVIEW
            next_step = step_index + 1
            if next_step >= len(steps):
                # Return to REVIEW
                return {
                    'state': CardState.REVIEW.value,
                    'step_index': 0,
                    'interval': LAPSE_MINIMUM_INTERVAL,
                    'ease_factor': ease_factor,
                    'lapses': lapses,
                    'requeue_minutes': None,
                    'days_until_review': LAPSE_MINIMUM_INTERVAL
                }
            else:
                return {
                    'state': CardState.RELEARNING.value,
                    'step_index': next_step,
                    'interval': LAPSE_MINIMUM_INTERVAL,
                    'ease_factor': ease_factor,
                    'lapses': lapses,
                    'requeue_minutes': steps[next_step],
                    'days_until_review': 0
                }

    def grade_card(
        self,
        card_id: int,
        rating: int,
        user_id: int,
        session_key: str = None
    ) -> Dict[str, Any]:
        """
        Process card rating and update SM-2 parameters using Anki-like state machine.

        Args:
            card_id: Card ID (UserCardDirection)
            rating: Rating (1, 2, 3)
            user_id: User ID (for access check)
            session_key: Session key (optional, for logging)

        Returns:
            Dict with result:
            {
                'success': bool,
                'state': str,
                'interval': int,
                'next_review': datetime,
                'requeue_position': int | None,
                'requeue_minutes': int | None,
                'session_attempts': int,
                'error': str (if success=False)
            }
        """
        try:
            # Get card
            card = UserCardDirection.query.get(card_id)

            if not card:
                return {'success': False, 'error': 'Card not found'}

            # Check access
            if card.user_word.user_id != user_id:
                return {'success': False, 'error': 'Access denied'}

            # Get current state (default to 'new' for legacy cards)
            current_state = card.state or CardState.NEW.value
            current_step = card.step_index or 0

            # Calculate new parameters using state machine
            update_result = self.calculate_sm2_update(
                rating=rating,
                state=current_state,
                step_index=current_step,
                repetitions=card.repetitions or 0,
                interval=card.interval or 0,
                ease_factor=card.ease_factor or DEFAULT_EASE_FACTOR,
                lapses=card.lapses or 0
            )

            # Update card with new values
            card.state = update_result['state']
            card.step_index = update_result['step_index']
            card.repetitions = update_result['repetitions']
            card.interval = update_result['interval']
            card.ease_factor = update_result['ease_factor']
            card.lapses = update_result['lapses']
            card.last_reviewed = datetime.now(timezone.utc)

            # Update correct/incorrect count
            if rating >= RATING_DOUBT:
                card.correct_count = (card.correct_count or 0) + 1
            else:
                card.incorrect_count = (card.incorrect_count or 0) + 1

            # Increment session_attempts
            card.session_attempts = (card.session_attempts or 0) + 1

            # Calculate next_review based on state
            now = datetime.now(timezone.utc)
            requeue_minutes = update_result['requeue_minutes']
            days_until_review = update_result['days_until_review']

            if card.state == CardState.REVIEW.value and days_until_review > 0:
                # Add ±10% variance to prevent review cliff
                variance = random.uniform(0.9, 1.1)
                adjusted_days = max(1, round(days_until_review * variance))
                card.next_review = now + timedelta(days=adjusted_days)
            elif requeue_minutes:
                # Learning/Relearning: schedule for minutes from now
                card.next_review = now + timedelta(minutes=requeue_minutes)
            else:
                card.next_review = now

            # Update parent UserWord status
            self._update_user_word_status(card)

            db.session.commit()

            # Calculate requeue position for client-side queue management
            requeue_position = self.get_requeue_position(
                rating=rating,
                state=current_state,
                step_index=current_step
            )

            # Check session limit
            if card.session_attempts >= MAX_SESSION_ATTEMPTS:
                requeue_position = None  # Don't show again this session

            logger.info(
                f"Card {card_id} graded: state={current_state}→{card.state}, "
                f"rating={rating}, interval={card.interval}, "
                f"requeue_pos={requeue_position}, requeue_min={requeue_minutes}, "
                f"session={session_key}"
            )

            return {
                'success': True,
                'card_id': card_id,
                'state': card.state,
                'step_index': card.step_index,
                'interval': card.interval,
                'next_review': card.next_review.isoformat() if card.next_review else None,
                'requeue_position': requeue_position,
                'requeue_minutes': requeue_minutes,
                'session_attempts': card.session_attempts,
                'ease_factor': card.ease_factor,
                'repetitions': card.repetitions,
                'lapses': card.lapses
            }

        except Exception as e:
            logger.error(f"Error grading card {card_id}: {str(e)}")
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    def _update_user_word_status(self, card: UserCardDirection) -> None:
        """Обновляет статус UserWord на основе прогресса карточек."""
        user_word = card.user_word

        if user_word.status == 'new':
            user_word.status = 'learning'
            return

        # Проверяем другое направление
        other_direction = DIRECTION_RUS_ENG if card.direction == DIRECTION_ENG_RUS else DIRECTION_ENG_RUS
        other_card = UserCardDirection.query.filter_by(
            user_word_id=user_word.id,
            direction=other_direction
        ).first()

        if not other_card:
            return

        # Оба направления пройдены хотя бы раз → review
        if other_card.repetitions > 0 and card.repetitions > 0:
            if user_word.status == 'learning':
                user_word.status = 'review'

            # Оба направления с интервалом >= 30 дней → mastered
            if other_card.interval >= 30 and card.interval >= 30:
                if user_word.status == 'review':
                    user_word.status = 'mastered'

    def create_session(
        self,
        user_id: int,
        source: str,
        source_id: int = None,
        word_ids: List[int] = None,
        limit: int = 50,
        directions: List[str] = None
    ) -> Dict[str, Any]:
        """
        Создаёт SRS сессию для указанного источника.

        Args:
            user_id: ID пользователя
            source: Источник ('study', 'book_course', 'curriculum')
            source_id: ID источника (урока, колоды и т.д.)
            word_ids: Список ID слов для сессии (опционально)
            limit: Максимум карточек в сессии
            directions: Направления для включения (по умолчанию оба)

        Returns:
            {
                'session_key': str,
                'cards': List[CardData],
                'studied_today': int,
                'total_due': int
            }
        """
        try:
            if directions is None:
                directions = [DIRECTION_ENG_RUS, DIRECTION_RUS_ENG]

            # Создаём session_key
            session_key = f"{source}_{source_id or 'auto'}_{user_id}_{datetime.now().timestamp()}"

            # Получаем карточки
            cards = self._get_due_cards(
                user_id=user_id,
                word_ids=word_ids,
                directions=directions,
                limit=limit
            )

            # Считаем изученные сегодня
            studied_today = self._count_studied_today(user_id, word_ids)

            # Форматируем карточки для клиента
            formatted_cards = self._format_cards_for_session(cards)

            logger.info(
                f"Created SRS session: source={source}, user={user_id}, "
                f"cards={len(formatted_cards)}, studied_today={studied_today}"
            )

            return {
                'session_key': session_key,
                'cards': formatted_cards,
                'studied_today': studied_today,
                'total_due': len(formatted_cards),
                'source': source,
                'source_id': source_id
            }

        except Exception as e:
            logger.error(f"Error creating SRS session: {str(e)}")
            return {
                'session_key': None,
                'cards': [],
                'studied_today': 0,
                'total_due': 0,
                'error': str(e)
            }

    def _get_due_cards(
        self,
        user_id: int,
        word_ids: List[int] = None,
        directions: List[str] = None,
        limit: int = 50,
        exclude_card_ids: List[int] = None
    ) -> List[UserCardDirection]:
        """
        Get cards for review with Anki-like priority queue.

        Priority order:
        1. RELEARNING cards (due now) - failed reviews need immediate attention
        2. LEARNING cards (due now) - cards in learning steps
        3. REVIEW cards (due today) - regular spaced repetition
        4. NEW cards - fresh cards (with daily limit)

        Args:
            exclude_card_ids: List of card IDs to exclude (for anti-repeat)
        """
        now = datetime.now(timezone.utc)
        result = []

        # Base query builder with buried filter and anti-repeat
        def base_query():
            q = (
                UserCardDirection.query
                .join(UserWord)
                .filter(UserWord.user_id == user_id)
                # Filter out buried cards
                .filter(
                    db.or_(
                        UserCardDirection.buried_until.is_(None),
                        UserCardDirection.buried_until <= now
                    )
                )
            )
            if word_ids:
                q = q.filter(UserWord.word_id.in_(word_ids))
            if directions:
                q = q.filter(UserCardDirection.direction.in_(directions))
            # Anti-repeat: exclude specified card IDs
            if exclude_card_ids:
                q = q.filter(~UserCardDirection.id.in_(exclude_card_ids))
            return q

        remaining = limit

        # PRIORITY 1: RELEARNING cards (due now)
        if remaining > 0:
            relearning = base_query().filter(
                UserCardDirection.state == CardState.RELEARNING.value,
                UserCardDirection.next_review <= now
            ).order_by(
                UserCardDirection.next_review.asc()
            ).limit(remaining).all()
            result.extend(relearning)
            remaining -= len(relearning)

        # PRIORITY 2: LEARNING cards (due now)
        if remaining > 0:
            learning = base_query().filter(
                UserCardDirection.state == CardState.LEARNING.value,
                UserCardDirection.next_review <= now
            ).order_by(
                UserCardDirection.next_review.asc()
            ).limit(remaining).all()
            result.extend(learning)
            remaining -= len(learning)

        # PRIORITY 3: REVIEW cards (due today)
        if remaining > 0:
            reviews = base_query().filter(
                UserCardDirection.state == CardState.REVIEW.value,
                UserCardDirection.next_review <= now
            ).order_by(
                UserCardDirection.next_review.asc()
            ).limit(remaining).all()
            result.extend(reviews)
            remaining -= len(reviews)

        # PRIORITY 4: NEW cards (never reviewed, or legacy cards without state)
        if remaining > 0:
            new_cards = base_query().filter(
                db.or_(
                    UserCardDirection.state == CardState.NEW.value,
                    UserCardDirection.state.is_(None),
                    db.and_(
                        UserCardDirection.repetitions == 0,
                        UserCardDirection.state.is_(None)
                    )
                )
            ).order_by(
                UserCardDirection.id.asc()  # Oldest first for consistency
            ).limit(remaining).all()
            result.extend(new_cards)

        return result

    def _count_studied_today(
        self,
        user_id: int,
        word_ids: List[int] = None
    ) -> int:
        """Считает количество слов, изученных сегодня."""
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        query = (
            UserCardDirection.query
            .join(UserWord)
            .filter(UserWord.user_id == user_id)
            .filter(UserCardDirection.direction == DIRECTION_ENG_RUS)  # Считаем по одному направлению
            .filter(UserCardDirection.last_reviewed >= today_start)
        )

        if word_ids:
            query = query.filter(UserWord.word_id.in_(word_ids))

        return query.count()

    def _format_cards_for_session(self, cards: List[UserCardDirection]) -> List[Dict[str, Any]]:
        """Format cards for client with Anki-like state information."""
        result = []

        for card in cards:
            word = card.user_word.word

            if card.direction == DIRECTION_ENG_RUS:
                front = word.english_word
                back = word.russian_word
            else:
                front = word.russian_word
                back = word.english_word

            # Get state (default to 'new' for legacy cards)
            state = card.state or CardState.NEW.value
            if not card.state and card.repetitions == 0:
                state = CardState.NEW.value
            elif not card.state and card.repetitions > 0:
                state = CardState.REVIEW.value

            # Map state to phase for backwards compatibility
            if state == CardState.NEW.value:
                phase = 'new'
            elif state in (CardState.LEARNING.value, CardState.RELEARNING.value):
                phase = 'learning'
            else:
                phase = 'review'

            result.append({
                'card_id': card.id,
                'word_id': word.id,
                'front': front,
                'back': back,
                'direction': card.direction,
                'state': state,
                'phase': phase,  # Backwards compatibility
                'step_index': card.step_index or 0,
                'new': state == CardState.NEW.value,
                'ease_factor': card.ease_factor or DEFAULT_EASE_FACTOR,
                'interval': card.interval or 0,
                'lapses': card.lapses or 0,
                'session_attempts': card.session_attempts or 0,
                'audio_url': self._get_audio_url(word, card.direction),
                'transcription': getattr(word, 'transcription', None),
                'examples': getattr(word, 'sentences', None),
            })

        return result

    def _get_audio_url(self, word: CollectionWords, direction: str) -> Optional[str]:
        """Получает URL аудио для слова."""
        if direction != DIRECTION_ENG_RUS:
            return None

        if hasattr(word, 'listening') and word.listening:
            filename = word.listening
            # Извлекаем имя файла из Anki формата если нужно
            if filename.startswith('[sound:') and filename.endswith(']'):
                filename = filename[7:-1]
            return f"/static/audio/{filename}"

        return None

    def get_or_create_cards_for_word(
        self,
        user_id: int,
        word_id: int,
        directions: List[str] = None
    ) -> List[UserCardDirection]:
        """
        Create or get cards for a word with proper Anki-like state initialization.

        Args:
            user_id: User ID
            word_id: Word ID
            directions: Directions (default both)

        Returns:
            List of UserCardDirection objects
        """
        if directions is None:
            directions = [DIRECTION_ENG_RUS, DIRECTION_RUS_ENG]

        # Get or create UserWord
        user_word = UserWord.query.filter_by(user_id=user_id, word_id=word_id).first()

        if not user_word:
            user_word = UserWord(user_id=user_id, word_id=word_id)
            db.session.add(user_word)
            db.session.flush()

        cards = []

        for direction in directions:
            card = UserCardDirection.query.filter_by(
                user_word_id=user_word.id,
                direction=direction
            ).first()

            if not card:
                card = UserCardDirection(
                    user_word_id=user_word.id,
                    direction=direction
                )
                # Initialize with Anki-like state
                card.state = CardState.NEW.value
                card.step_index = 0
                card.lapses = 0
                card.ease_factor = DEFAULT_EASE_FACTOR
                card.interval = 0
                card.repetitions = 0
                card.next_review = datetime.now(timezone.utc)
                db.session.add(card)
                db.session.flush()

            cards.append(card)

        return cards

    def reset_session_attempts(self, user_id: int, word_ids: List[int] = None) -> int:
        """
        Сбрасывает session_attempts для начала новой сессии.

        Args:
            user_id: ID пользователя
            word_ids: Список ID слов (опционально)

        Returns:
            Количество сброшенных карточек
        """
        query = (
            UserCardDirection.query
            .join(UserWord)
            .filter(UserWord.user_id == user_id)
            .filter(UserCardDirection.session_attempts > 0)
        )

        if word_ids:
            query = query.filter(UserWord.word_id.in_(word_ids))

        cards = query.all()

        for card in cards:
            card.session_attempts = 0

        db.session.commit()

        return len(cards)


# Singleton instance for convenience
unified_srs_service = UnifiedSRSService()
