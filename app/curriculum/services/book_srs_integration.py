# app/curriculum/services/book_srs_integration.py

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.curriculum.book_courses import BookCourseEnrollment
from app.curriculum.daily_lessons import DailyLesson, LessonCompletionEvent, SliceVocabulary
from app.study.models import UserCardDirection, UserWord
from app.utils.db import db
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)


class BookSRSIntegration:
    """
    Интеграция существующего SRS модуля с book courses
    согласно детальному плану уроков (3.2.2 Anki-card)
    """

    def __init__(self):
        self.book_collection_cache = {}

    def create_srs_session_for_lesson(self, user_id: int, daily_lesson: DailyLesson,
                                      enrollment: BookCourseEnrollment) -> Dict[str, Any]:
        """
        Создает SRS сессию для daily lesson согласно спецификации:
        GET /api/v1/srs/session?lesson_id=:id → { deck:[{card_id,front,back,phase,new}], session_key }
        """
        try:
            logger.info(f"Creating SRS session for user {user_id}, lesson {daily_lesson.id}")

            # Получаем слова для этого daily lesson
            vocabulary_words = self._get_vocabulary_words_for_lesson(daily_lesson)

            if not vocabulary_words:
                logger.warning(f"No vocabulary words found for lesson {daily_lesson.id}")
                return {'deck': [], 'session_key': None}

            # Создаем или получаем SRS карточки для этих слов
            cards = self._get_or_create_srs_cards(user_id, vocabulary_words, daily_lesson)

            # Фильтруем карточки по дате повторения (due today or overdue)
            due_cards = self._filter_due_cards(cards)

            # Если слишком много карточек (>50), разбиваем сессию
            if len(due_cards) > 50:
                due_cards = due_cards[:25]  # Split in two как в спецификации
                logger.info(f"Too many cards ({len(due_cards)}), limiting to 25")

            # Формируем deck согласно API спецификации
            deck = self._format_deck_for_session(due_cards)

            # Создаем session_key для отслеживания
            session_key = f"book_lesson_{daily_lesson.id}_{user_id}_{datetime.now().timestamp()}"

            logger.info(f"Created SRS session with {len(deck)} cards for lesson {daily_lesson.id}")

            return {
                'deck': deck,
                'session_key': session_key,
                'lesson_id': daily_lesson.id,
                'total_cards': len(deck)
            }

        except Exception as e:
            logger.error(f"Error creating SRS session for lesson {daily_lesson.id}: {str(e)}")
            return {'deck': [], 'session_key': None}

    def _get_vocabulary_words_for_lesson(self, daily_lesson: DailyLesson) -> List[CollectionWords]:
        """Получает vocabulary words для daily lesson"""
        vocabulary_entries = (SliceVocabulary.query
                              .filter_by(daily_lesson_id=daily_lesson.id)
                              .join(CollectionWords)
                              .order_by(SliceVocabulary.frequency_in_slice.desc())
                              .limit(10)  # Максимум 10 слов согласно спецификации
                              .all())

        return [entry.word for entry in vocabulary_entries]

    def _get_or_create_srs_cards(self, user_id: int, words: List[CollectionWords],
                                 daily_lesson: DailyLesson) -> List[UserCardDirection]:
        """Создает или получает SRS карточки для слов"""
        cards = []

        for word in words:
            # Создаем или получаем UserWord
            user_word = UserWord.get_or_create(user_id, word.id)

            # Создаем или получаем карточки для обоих направлений
            eng_rus_card = self._get_or_create_card_direction(user_word, 'eng-rus')
            rus_eng_card = self._get_or_create_card_direction(user_word, 'rus-eng')

            # Добавляем связь с book course через метаданные
            self._link_card_to_book_lesson(eng_rus_card, daily_lesson)
            self._link_card_to_book_lesson(rus_eng_card, daily_lesson)

            cards.extend([eng_rus_card, rus_eng_card])

        return cards

    def _get_or_create_card_direction(self, user_word: UserWord, direction: str) -> UserCardDirection:
        """Создает или получает карточку для направления"""
        card = UserCardDirection.query.filter_by(
            user_word_id=user_word.id,
            direction=direction
        ).first()

        if not card:
            card = UserCardDirection(
                user_word_id=user_word.id,
                direction=direction,
                ease_factor=2.5,
                interval=0,
                repetitions=0,
                next_review=datetime.now(timezone.utc)
            )
            db.session.add(card)
            db.session.flush()

        return card

    def _link_card_to_book_lesson(self, card: UserCardDirection, daily_lesson: DailyLesson):
        """Связывает карточку с book lesson через метаданные"""
        # Можно расширить модель UserCardDirection полем metadata: JSONB
        # Пока используем existing поля для отслеживания источника
        pass

    def _filter_due_cards(self, cards: List[UserCardDirection]) -> List[UserCardDirection]:
        """Фильтрует карточки, которые нужно повторить сегодня"""
        now = datetime.now(timezone.utc)
        due_cards = []

        for card in cards:
            # Новые карточки (repetitions = 0) или просроченные
            if card.repetitions == 0 or (card.next_review and card.next_review <= now):
                due_cards.append(card)

        return due_cards

    def _format_deck_for_session(self, cards: List[UserCardDirection]) -> List[Dict[str, Any]]:
        """Форматирует карточки для SRS сессии согласно API спецификации"""
        deck = []

        for card in cards:
            word = card.user_word.word

            # Определяем front и back согласно направлению
            if card.direction == 'eng-rus':
                front = word.english_word
                back = word.russian_word
            else:  # rus-eng
                front = word.russian_word
                back = word.english_word

            # Определяем фазу обучения
            if card.repetitions == 0:
                phase = 'new'
            elif card.repetitions < 3:
                phase = 'learning'
            else:
                phase = 'review'

            deck_item = {
                'card_id': card.id,
                'front': front,
                'back': back,
                'phase': phase,
                'new': card.repetitions == 0,
                'direction': card.direction,
                'ease_factor': card.ease_factor,
                'interval': card.interval,
                'audio_url': self._get_audio_url(word, card.direction)
            }

            deck.append(deck_item)

        return deck

    def _get_audio_url(self, word: CollectionWords, direction: str) -> Optional[str]:
        """Получает URL аудио для слова"""
        # Аудио только для английских слов
        if direction == 'eng-rus' and hasattr(word, 'get_download') and word.get_download == 1:
            if hasattr(word, 'listening') and word.listening:
                # Предполагаем, что listening содержит имя файла
                return f"/static/audio/{word.listening}"
        return None

    def process_card_grade(self, user_id: int, card_id: int, grade: int,
                           session_key: str) -> Dict[str, Any]:
        """
        Обрабатывает оценку карточки согласно спецификации:
        POST /api/v1/srs/grade {card_id,grade,session_key}
        
        Система оценок (согласно детальному плану):
        0 (Again): "Не помню" - сброс прогресса
        1-2: Неправильный ответ
        3 (Hard): Правильно, но сложно  
        4 (Good): Стандартный правильный ответ
        5 (Easy): Легкий ответ
        """
        try:
            card = UserCardDirection.query.filter_by(id=card_id).first()

            if not card or card.user_word.user_id != user_id:
                return {'success': False, 'error': 'Card not found or access denied'}

            # Обновляем карточку согласно алгоритму SM-2
            result = card.update_after_review(grade)

            # Логируем review
            self._log_card_review(card, grade, session_key)

            db.session.commit()

            # Возвращаем результат с next_due для фронтенда
            return {
                'success': True,
                'card_id': card_id,
                'next_due': card.next_review.isoformat() if card.next_review else None,
                'interval': card.interval,
                'ease_factor': card.ease_factor,
                'repetitions': card.repetitions
            }

        except Exception as e:
            logger.error(f"Error processing card grade: {str(e)}")
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    def _log_card_review(self, card: UserCardDirection, grade: int, session_key: str):
        """Логирует review карточки"""
        # Можно расширить для детального логирования
        logger.info(f"Card {card.id} reviewed with grade {grade} in session {session_key}")

    def complete_srs_session(self, user_id: int, daily_lesson_id: int,
                             session_key: str, session_stats: Dict[str, Any]) -> bool:
        """
        Завершает SRS сессию и создает completion event
        """
        try:
            # Создаем completion event
            event = LessonCompletionEvent(
                user_id=user_id,
                daily_lesson_id=daily_lesson_id,
                event_type='srs_session_completed',
                event_data={
                    'session_key': session_key,
                    'cards_reviewed': session_stats.get('cards_reviewed', 0),
                    'correct_count': session_stats.get('correct_count', 0),
                    'total_count': session_stats.get('total_count', 0),
                    'session_duration': session_stats.get('duration_seconds', 0)
                }
            )

            db.session.add(event)
            db.session.commit()

            logger.info(f"SRS session completed for user {user_id}, lesson {daily_lesson_id}")
            return True

        except Exception as e:
            logger.error(f"Error completing SRS session: {str(e)}")
            db.session.rollback()
            return False

    def auto_create_srs_cards_from_vocabulary_lesson(self, user_id: int,
                                                     daily_lesson: DailyLesson) -> bool:
        """
        Автоматически создает SRS карточки после завершения Vocabulary урока
        согласно спецификации: "если это Vocabulary — создаёт srs_card (phase=0)"
        """
        try:
            if daily_lesson.lesson_type != 'vocabulary':
                return False

            vocabulary_words = self._get_vocabulary_words_for_lesson(daily_lesson)

            if not vocabulary_words:
                return False

            # Создаем SRS карточки для всех слов
            self._get_or_create_srs_cards(user_id, vocabulary_words, daily_lesson)

            db.session.commit()

            logger.info(f"Auto-created SRS cards for {len(vocabulary_words)} words from lesson {daily_lesson.id}")
            return True

        except Exception as e:
            logger.error(f"Error auto-creating SRS cards: {str(e)}")
            db.session.rollback()
            return False

    def get_next_srs_session_time(self, user_id: int, course_id: int) -> Optional[datetime]:
        """
        Определяет время следующей SRS сессии для пользователя в курсе
        """
        try:
            # Найти ближайшую карточку, которую нужно повторить
            earliest_card = (UserCardDirection.query
                             .join(UserWord)
                             .filter(UserWord.user_id == user_id)
                             .filter(UserCardDirection.next_review.isnot(None))
                             .order_by(UserCardDirection.next_review)
                             .first())

            if earliest_card and earliest_card.next_review:
                return earliest_card.next_review

            return None

        except Exception as e:
            logger.error(f"Error getting next SRS session time: {str(e)}")
            return None

    def get_due_cards_count(self, user_id: int) -> int:
        """Получает количество карточек, готовых к повторению"""
        try:
            now = datetime.now(timezone.utc)

            count = (UserCardDirection.query
                     .join(UserWord)
                     .filter(UserWord.user_id == user_id)
                     .filter(
                db.or_(
                    UserCardDirection.repetitions == 0,  # Новые карточки
                    UserCardDirection.next_review <= now  # Просроченные
                )
            )
                     .count())

            return count

        except Exception as e:
            logger.error(f"Error getting due cards count: {str(e)}")
            return 0

    def get_due_cards_for_review(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Получает карточки для повторения в уроке.
        Возвращает до `limit` карточек, отсортированных по приоритету.
        """
        try:
            # Use naive datetime for DB comparison (SQLite doesn't handle timezone well)
            now_utc = datetime.now(timezone.utc)
            now_naive = datetime.utcnow()

            # Get due cards with word data
            due_cards = (UserCardDirection.query
                         .join(UserWord)
                         .join(CollectionWords, UserWord.word_id == CollectionWords.id)
                         .filter(UserWord.user_id == user_id)
                         .filter(
                db.or_(
                    UserCardDirection.repetitions == 0,  # New cards
                    UserCardDirection.next_review <= now_naive  # Overdue
                )
            )
                         .order_by(
                # Priority: overdue cards first, then by interval
                UserCardDirection.next_review.asc().nullsfirst()
            )
                         .limit(limit)
                         .all())

            # Format cards for review
            review_cards = []
            for card in due_cards:
                word = card.user_word.word

                if card.direction == 'eng-rus':
                    front = word.english_word
                    back = word.russian_word
                else:
                    front = word.russian_word
                    back = word.english_word

                # Determine card urgency (handle both naive and aware datetimes)
                urgency = 'new'
                if card.next_review:
                    next_review = card.next_review
                    # Make both naive for comparison
                    if next_review.tzinfo is not None:
                        next_review = next_review.replace(tzinfo=None)
                    if next_review < now_naive:
                        days_overdue = (now_naive - next_review).days
                        urgency = 'overdue' if days_overdue > 0 else 'due'

                review_cards.append({
                    'card_id': card.id,
                    'front': front,
                    'back': back,
                    'direction': card.direction,
                    'word_id': word.id,
                    'urgency': urgency,
                    'repetitions': card.repetitions,
                    'ease_factor': card.ease_factor,
                    'audio_url': self._get_audio_url(word, card.direction)
                })

            return review_cards

        except Exception as e:
            logger.error(f"Error getting due cards for review: {str(e)}")
            return []

    def add_word_to_srs(self, user_id: int, word_id: int, source: str = 'book_reading') -> Dict[str, Any]:
        """
        Добавляет одно слово в SRS карточки.
        Создает UserWord и карточки для обоих направлений.

        Args:
            user_id: ID пользователя
            word_id: ID слова из CollectionWords
            source: Источник добавления (book_reading, vocabulary_lesson и т.д.)

        Returns:
            Dict с результатом операции
        """
        try:
            # Проверяем, существует ли слово
            word = CollectionWords.query.get(word_id)
            if not word:
                return {'success': False, 'error': 'Слово не найдено'}

            # Создаем или получаем UserWord
            user_word = UserWord.get_or_create(user_id, word_id)

            # Проверяем, есть ли уже карточки
            existing_cards = UserCardDirection.query.filter_by(user_word_id=user_word.id).count()

            if existing_cards >= 2:
                return {'success': True, 'message': 'Слово уже добавлено в карточки', 'already_exists': True}

            # Создаем карточки для обоих направлений
            eng_rus_card = self._get_or_create_card_direction(user_word, 'eng-rus')
            rus_eng_card = self._get_or_create_card_direction(user_word, 'rus-eng')

            db.session.commit()

            logger.info(f"Added word {word_id} to SRS for user {user_id} (source: {source})")

            return {
                'success': True,
                'message': 'Слово добавлено в карточки',
                'word_id': word_id,
                'cards_created': 2,
                'eng_rus_card_id': eng_rus_card.id,
                'rus_eng_card_id': rus_eng_card.id
            }

        except Exception as e:
            logger.error(f"Error adding word {word_id} to SRS: {str(e)}")
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    def get_review_summary(self, user_id: int) -> Dict[str, Any]:
        """
        Получает сводку карточек для повторения.
        """
        try:
            now = datetime.now(timezone.utc)

            # Count by category
            new_count = (UserCardDirection.query
                         .join(UserWord)
                         .filter(UserWord.user_id == user_id)
                         .filter(UserCardDirection.repetitions == 0)
                         .count())

            due_count = (UserCardDirection.query
                         .join(UserWord)
                         .filter(UserWord.user_id == user_id)
                         .filter(UserCardDirection.repetitions > 0)
                         .filter(UserCardDirection.next_review <= now)
                         .count())

            total_learned = (UserCardDirection.query
                             .join(UserWord)
                             .filter(UserWord.user_id == user_id)
                             .filter(UserCardDirection.repetitions > 0)
                             .count())

            return {
                'new_cards': new_count,
                'due_cards': due_count,
                'total_due': new_count + due_count,
                'total_learned': total_learned
            }

        except Exception as e:
            logger.error(f"Error getting review summary: {str(e)}")
            return {
                'new_cards': 0,
                'due_cards': 0,
                'total_due': 0,
                'total_learned': 0
            }
