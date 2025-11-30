# app/srs/service.py
"""
Unified SRS Service - Single service for all SRS operations.

Responsibilities:
- Card scheduling (SM-2 algorithm)
- Session management
- Requeue position calculation
- Both directions (eng-rus, rus-eng)
"""

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.srs.constants import (
    RATING_DONT_KNOW,
    RATING_DOUBT,
    RATING_KNOW,
    MAX_SESSION_ATTEMPTS,
    REQUEUE_RANGE_DONT_KNOW,
    REQUEUE_RANGE_DOUBT,
    DEFAULT_EASE_FACTOR,
    MIN_EASE_FACTOR,
    MAX_EASE_FACTOR,
    EF_DECREASE_DONT_KNOW,
    EF_INCREASE_KNOW,
    INTERVAL_MULTIPLIER_DOUBT,
    INTERVAL_MULTIPLIER_KNOW,
    DIRECTION_ENG_RUS,
    DIRECTION_RUS_ENG,
)
from app.study.models import UserCardDirection, UserWord
from app.utils.db import db
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)


class UnifiedSRSService:
    """
    Единый SRS сервис для всех модулей приложения.

    Используется в:
    - /study (flashcards)
    - /book-courses (vocabulary lessons)
    - /curriculum (lessons)
    """

    @staticmethod
    def get_requeue_position(rating: int) -> Optional[int]:
        """
        Возвращает позицию для повторного показа карточки в очереди.

        Args:
            rating: Оценка карточки (1, 2, или 3)

        Returns:
            int: Позиция для вставки (через N карточек)
            None: Если карточку не нужно показывать повторно
        """
        if rating == RATING_DONT_KNOW:
            return random.randint(*REQUEUE_RANGE_DONT_KNOW)
        elif rating == RATING_DOUBT:
            return random.randint(*REQUEUE_RANGE_DOUBT)
        elif rating == RATING_KNOW:
            return None
        else:
            logger.warning(f"Unknown rating: {rating}, treating as KNOW")
            return None

    @staticmethod
    def calculate_sm2_update(
        rating: int,
        repetitions: int,
        interval: int,
        ease_factor: float
    ) -> Tuple[int, int, float, int]:
        """
        Рассчитывает новые параметры SM-2 на основе оценки.

        Args:
            rating: Оценка (1, 2, 3)
            repetitions: Текущее количество повторений
            interval: Текущий интервал (дни)
            ease_factor: Текущий коэффициент сложности

        Returns:
            Tuple of (new_repetitions, new_interval, new_ease_factor, days_until_review)
        """
        if rating == RATING_DONT_KNOW:
            # Не знаю: сброс прогресса
            new_repetitions = 0
            new_interval = 0
            new_ease_factor = max(MIN_EASE_FACTOR, ease_factor - EF_DECREASE_DONT_KNOW)
            days_until_review = 0  # Покажется в следующей сессии

        elif rating == RATING_DOUBT:
            # Сомневаюсь: умеренный рост
            new_repetitions = repetitions + 1
            new_ease_factor = ease_factor  # Без изменений

            if new_repetitions == 1:
                new_interval = 1
            elif new_repetitions == 2:
                new_interval = 3  # Короче чем для "Знаю"
            else:
                new_interval = max(1, round(interval * ease_factor * INTERVAL_MULTIPLIER_DOUBT))

            days_until_review = new_interval

        elif rating == RATING_KNOW:
            # Знаю: хороший рост с бонусом
            new_repetitions = repetitions + 1
            new_ease_factor = min(MAX_EASE_FACTOR, ease_factor + EF_INCREASE_KNOW)

            if new_repetitions == 1:
                new_interval = 1
            elif new_repetitions == 2:
                new_interval = 6
            else:
                new_interval = max(1, round(interval * ease_factor * INTERVAL_MULTIPLIER_KNOW))

            days_until_review = new_interval

        else:
            # Unknown rating - treat as "know" for safety
            logger.warning(f"Unknown rating {rating}, treating as KNOW")
            new_repetitions = repetitions + 1
            new_interval = max(1, round(interval * ease_factor))
            new_ease_factor = ease_factor
            days_until_review = new_interval

        return new_repetitions, new_interval, new_ease_factor, days_until_review

    def grade_card(
        self,
        card_id: int,
        rating: int,
        user_id: int,
        session_key: str = None
    ) -> Dict[str, Any]:
        """
        Обрабатывает оценку карточки и обновляет SM-2 параметры.

        Args:
            card_id: ID карточки (UserCardDirection)
            rating: Оценка (1, 2, 3)
            user_id: ID пользователя (для проверки доступа)
            session_key: Ключ сессии (опционально, для логирования)

        Returns:
            Dict с результатом:
            {
                'success': bool,
                'interval': int,
                'next_review': datetime,
                'requeue_position': int | None,
                'session_attempts': int,
                'error': str (if success=False)
            }
        """
        try:
            # Получаем карточку
            card = UserCardDirection.query.get(card_id)

            if not card:
                return {'success': False, 'error': 'Card not found'}

            # Проверяем доступ
            if card.user_word.user_id != user_id:
                return {'success': False, 'error': 'Access denied'}

            # Рассчитываем новые параметры
            new_reps, new_interval, new_ef, days = self.calculate_sm2_update(
                rating=rating,
                repetitions=card.repetitions,
                interval=card.interval,
                ease_factor=card.ease_factor
            )

            # Обновляем карточку
            card.repetitions = new_reps
            card.interval = new_interval
            card.ease_factor = new_ef
            card.last_reviewed = datetime.now(timezone.utc)

            # Добавляем ±10% variance для предотвращения "review cliff"
            variance = random.uniform(0.9, 1.1)
            adjusted_days = max(0, round(days * variance))

            card.next_review = datetime.now(timezone.utc) + timedelta(days=adjusted_days)

            # Увеличиваем session_attempts
            card.session_attempts = (card.session_attempts or 0) + 1

            # Обновляем correct/incorrect count
            if rating >= RATING_DOUBT:
                card.correct_count = (card.correct_count or 0) + 1
            else:
                card.incorrect_count = (card.incorrect_count or 0) + 1

            # Обновляем статус родительского UserWord
            self._update_user_word_status(card)

            db.session.commit()

            # Рассчитываем позицию для повторного показа
            requeue_position = self.get_requeue_position(rating)

            # Проверяем лимит показов
            if card.session_attempts >= MAX_SESSION_ATTEMPTS:
                requeue_position = None  # Больше не показывать в этой сессии

            logger.info(
                f"Card {card_id} graded: rating={rating}, interval={new_interval}, "
                f"requeue={requeue_position}, session={session_key}"
            )

            return {
                'success': True,
                'card_id': card_id,
                'interval': new_interval,
                'next_review': card.next_review.isoformat() if card.next_review else None,
                'requeue_position': requeue_position,
                'session_attempts': card.session_attempts,
                'ease_factor': new_ef,
                'repetitions': new_reps
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
        limit: int = 50
    ) -> List[UserCardDirection]:
        """Получает карточки для повторения."""
        now = datetime.now(timezone.utc)

        query = (
            UserCardDirection.query
            .join(UserWord)
            .filter(UserWord.user_id == user_id)
        )

        if word_ids:
            query = query.filter(UserWord.word_id.in_(word_ids))

        if directions:
            query = query.filter(UserCardDirection.direction.in_(directions))

        # Фильтруем по дате повторения
        query = query.filter(
            db.or_(
                UserCardDirection.repetitions == 0,  # Новые
                UserCardDirection.next_review <= now  # Просроченные
            )
        )

        # Сортировка: сначала просроченные, потом новые
        query = query.order_by(
            UserCardDirection.next_review.asc().nullsfirst()
        )

        if limit:
            query = query.limit(limit)

        return query.all()

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
        """Форматирует карточки для передачи клиенту."""
        result = []

        for card in cards:
            word = card.user_word.word

            if card.direction == DIRECTION_ENG_RUS:
                front = word.english_word
                back = word.russian_word
            else:
                front = word.russian_word
                back = word.english_word

            # Определяем фазу
            if card.repetitions == 0:
                phase = 'new'
            elif card.repetitions < 3:
                phase = 'learning'
            else:
                phase = 'review'

            result.append({
                'card_id': card.id,
                'word_id': word.id,
                'front': front,
                'back': back,
                'direction': card.direction,
                'phase': phase,
                'new': card.repetitions == 0,
                'ease_factor': card.ease_factor,
                'interval': card.interval,
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
        Создаёт или получает карточки для слова.

        Args:
            user_id: ID пользователя
            word_id: ID слова
            directions: Направления (по умолчанию оба)

        Returns:
            List of UserCardDirection objects
        """
        if directions is None:
            directions = [DIRECTION_ENG_RUS, DIRECTION_RUS_ENG]

        # Получаем или создаём UserWord
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
