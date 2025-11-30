# app/curriculum/services/book_srs_integration.py

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.curriculum.book_courses import BookCourse, BookCourseEnrollment
from app.curriculum.daily_lessons import DailyLesson, LessonCompletionEvent, SliceVocabulary
from app.study.models import QuizDeck, QuizDeckWord, UserCardDirection, UserWord
from app.utils.db import db, word_book_link
from app.words.models import CollectionWords

# Константа для определения "выученного" слова
LEARNED_INTERVAL_THRESHOLD = 35  # дней

logger = logging.getLogger(__name__)


def is_word_learned(user_id: int, word_id: int, threshold: int = LEARNED_INTERVAL_THRESHOLD) -> bool:
    """
    Проверяет, выучено ли слово пользователем.
    Слово считается выученным если ОБА направления (eng-rus и rus-eng)
    имеют interval >= threshold дней.
    """
    user_word = UserWord.query.filter_by(user_id=user_id, word_id=word_id).first()
    if not user_word:
        return False

    cards = UserCardDirection.query.filter_by(user_word_id=user_word.id).all()
    if len(cards) < 2:
        return False

    return all(card.interval >= threshold for card in cards)


def get_word_status_for_ui(user_id: int, word_id: int) -> str:
    """
    Возвращает статус слова для UI:
    - 'not_added': слово не добавлено, можно добавить
    - 'in_learning': слово в процессе изучения (скрыть кнопку добавления)
    - 'learned': слово выучено (показать ✓ Выучено)
    """
    user_word = UserWord.query.filter_by(user_id=user_id, word_id=word_id).first()
    if not user_word:
        return 'not_added'

    # Проверяем есть ли карточки
    cards_count = UserCardDirection.query.filter_by(user_word_id=user_word.id).count()
    if cards_count == 0:
        return 'not_added'

    if is_word_learned(user_id, word_id):
        return 'learned'

    return 'in_learning'


def get_or_create_book_course_deck(user_id: int, course: BookCourse) -> QuizDeck:
    """
    Создаёт или получает колоду для книжного курса.
    Название: "Книга: {book.title}"
    """
    # Получаем название книги
    book_title = course.book.title if course.book else f"Курс {course.id}"
    deck_title = f"Книга: {book_title}"

    existing = QuizDeck.query.filter_by(
        user_id=user_id,
        title=deck_title
    ).first()

    if existing:
        return existing

    deck = QuizDeck(
        user_id=user_id,
        title=deck_title,
        description=f"Слова из курса: {course.title}",
        is_public=False
    )
    db.session.add(deck)
    db.session.flush()  # Получаем ID без полного коммита

    logger.info(f"Created book course deck '{deck_title}' for user {user_id}")
    return deck


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

            # Получаем слова для этого daily lesson (фильтруем выученные)
            vocabulary_words = self._get_vocabulary_words_for_lesson(daily_lesson, user_id=user_id)

            if not vocabulary_words:
                logger.warning(f"No vocabulary words found for lesson {daily_lesson.id}")
                return {'deck': [], 'session_key': None}

            # Создаем или получаем SRS карточки для этих слов
            cards = self._get_or_create_srs_cards(user_id, vocabulary_words, daily_lesson)

            # Commit новые карточки в базу
            db.session.commit()

            # Фильтруем карточки по дате повторения (due today or overdue)
            due_cards = self._filter_due_cards(cards)

            # Если слишком много карточек (>50), разбиваем сессию
            if len(due_cards) > 50:
                due_cards = due_cards[:25]  # Split in two как в спецификации
                logger.info(f"Too many cards ({len(due_cards)}), limiting to 25")

            # Считаем сколько слов изучено СЕГОДНЯ в рамках этого урока
            # (карточки с last_reviewed = сегодня, направление eng-rus)
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            studied_today = 0
            for item in cards:
                card = item['card']
                if card.direction == 'eng-rus' and card.last_reviewed:
                    last_rev = card.last_reviewed
                    if last_rev.tzinfo is None:
                        last_rev = last_rev.replace(tzinfo=timezone.utc)
                    if last_rev >= today_start:
                        studied_today += 1

            # Формируем deck согласно API спецификации
            deck = self._format_deck_for_session(due_cards)

            # Создаем session_key для отслеживания
            session_key = f"book_lesson_{daily_lesson.id}_{user_id}_{datetime.now().timestamp()}"

            logger.info(f"Created SRS session with {len(deck)} cards for lesson {daily_lesson.id}, studied today: {studied_today}")

            return {
                'deck': deck,
                'session_key': session_key,
                'lesson_id': daily_lesson.id,
                'total_cards': len(deck),
                'studied_today': studied_today  # Слов изучено сегодня
            }

        except Exception as e:
            logger.error(f"Error creating SRS session for lesson {daily_lesson.id}: {str(e)}")
            return {'deck': [], 'session_key': None}

    def _get_vocabulary_words_for_lesson(self, daily_lesson: DailyLesson,
                                          user_id: int = None,
                                          filter_learned: bool = True,
                                          target_count: int = 10) -> List[Dict[str, Any]]:
        """
        Получает vocabulary words для изучения.

        Логика:
        1. Сначала берём слова из текущего урока (SliceVocabulary)
        2. Если не хватает — берём слова из всей книги (word_book_link)
        3. Ищем пока не найдём target_count незнакомых слов или не переберём все слова книги

        Returns:
            List[Dict] с ключами: word, context, frequency, word_id
            Пустой список если все слова книги выучены
        """
        result = []
        seen_word_ids = set()

        # 1. Сначала слова из текущего урока (с контекстом)
        current_lesson_words = self._get_words_from_lesson(
            daily_lesson, user_id, filter_learned, seen_word_ids
        )
        result.extend(current_lesson_words)

        if len(result) >= target_count:
            return result[:target_count]

        # 2. Если не хватает — берём слова из всей книги через word_book_link
        module = daily_lesson.module
        if module and module.book_course:
            book_id = module.book_course.book_id
            if book_id:
                book_words = self._get_words_from_book(
                    book_id, user_id, filter_learned, seen_word_ids,
                    limit=target_count - len(result)
                )
                result.extend(book_words)

        logger.info(f"Found {len(result)} unknown words for lesson {daily_lesson.id} "
                   f"(target: {target_count}, searched whole book)")

        return result[:target_count] if result else result

    def _get_words_from_book(self, book_id: int, user_id: int,
                             filter_learned: bool, seen_word_ids: set,
                             limit: int = 10) -> List[Dict[str, Any]]:
        """
        Получает незнакомые слова из всей книги через word_book_link.
        Слова отсортированы по частоте (самые частые первыми).
        """
        # Получаем слова книги, отсортированные по частоте
        query = (
            db.session.query(CollectionWords, word_book_link.c.frequency)
            .join(word_book_link, CollectionWords.id == word_book_link.c.word_id)
            .filter(word_book_link.c.book_id == book_id)
            .order_by(word_book_link.c.frequency.desc())
        )

        result = []
        for word, frequency in query.all():
            if len(result) >= limit:
                break

            # Пропускаем уже добавленные слова
            if word.id in seen_word_ids:
                continue

            # Фильтруем выученные слова
            if filter_learned and user_id:
                if is_word_learned(user_id, word.id):
                    continue

            seen_word_ids.add(word.id)
            result.append({
                'word': word,
                'context': None,  # Контекст берётся только из SliceVocabulary
                'frequency': frequency,
                'word_id': word.id
            })

        return result

    def _get_words_from_lesson(self, lesson: DailyLesson, user_id: int,
                               filter_learned: bool, seen_word_ids: set) -> List[Dict[str, Any]]:
        """
        Получает незнакомые слова из конкретного урока.
        Обновляет seen_word_ids чтобы избежать дубликатов.
        """
        vocabulary_entries = (
            SliceVocabulary.query
            .filter_by(daily_lesson_id=lesson.id)
            .join(CollectionWords)
            .order_by(SliceVocabulary.frequency_in_slice.desc())
            .all()
        )

        result = []
        for entry in vocabulary_entries:
            # Пропускаем уже добавленные слова
            if entry.word_id in seen_word_ids:
                continue

            # Фильтруем выученные слова
            if filter_learned and user_id:
                if is_word_learned(user_id, entry.word_id):
                    continue

            seen_word_ids.add(entry.word_id)
            result.append({
                'word': entry.word,
                'context': entry.context_sentence,
                'frequency': entry.frequency_in_slice,
                'word_id': entry.word_id
            })

        return result

    def _get_or_create_srs_cards(self, user_id: int, word_data_list: List[Dict[str, Any]],
                                 daily_lesson: DailyLesson) -> List[Dict[str, Any]]:
        """Создает или получает SRS карточки для слов с контекстом"""
        cards_with_context = []

        for word_data in word_data_list:
            word = word_data['word']
            context = word_data.get('context')

            # Создаем или получаем UserWord
            user_word = UserWord.get_or_create(user_id, word.id)

            # Создаем или получаем карточки для обоих направлений
            eng_rus_card = self._get_or_create_card_direction(user_word, 'eng-rus')
            rus_eng_card = self._get_or_create_card_direction(user_word, 'rus-eng')

            # Добавляем связь с book course через метаданные
            self._link_card_to_book_lesson(eng_rus_card, daily_lesson)
            self._link_card_to_book_lesson(rus_eng_card, daily_lesson)

            # Store cards with context
            cards_with_context.append({'card': eng_rus_card, 'context': context})
            cards_with_context.append({'card': rus_eng_card, 'context': context})

        return cards_with_context

    def _get_or_create_card_direction(self, user_word: UserWord, direction: str) -> UserCardDirection:
        """Создает или получает карточку для направления"""
        card = UserCardDirection.query.filter_by(
            user_word_id=user_word.id,
            direction=direction
        ).first()

        if not card:
            card = UserCardDirection(
                user_word_id=user_word.id,
                direction=direction
            )
            # Set defaults (model has defaults, but set explicitly for clarity)
            card.ease_factor = 2.5
            card.interval = 0
            card.repetitions = 0
            card.next_review = datetime.now(timezone.utc)
            db.session.add(card)
            db.session.flush()

        return card

    def _link_card_to_book_lesson(self, card: UserCardDirection, daily_lesson: DailyLesson):
        """Связывает карточку с book lesson через метаданные"""
        # Можно расширить модель UserCardDirection полем metadata: JSONB
        # Пока используем existing поля для отслеживания источника
        pass

    def _filter_due_cards(self, cards_with_context: List[Dict[str, Any]],
                          direction_filter: str = None) -> List[Dict[str, Any]]:
        """Фильтрует карточки, которые нужно повторить сегодня

        По умолчанию включает оба направления (eng-rus и rus-eng).
        Если указан direction_filter - только указанное направление.

        Каждая карточка (eng-rus, rus-eng) фильтруется независимо.
        """
        now = datetime.now(timezone.utc)
        due_cards = []

        for item in cards_with_context:
            card = item['card']

            # Only include specified direction if filter is set
            if direction_filter and card.direction != direction_filter:
                continue

            # Новые карточки (repetitions = 0) или просроченные
            if card.repetitions == 0:
                due_cards.append(item)
            elif card.next_review:
                # Make timezone-aware comparison safe
                next_review = card.next_review
                if next_review.tzinfo is None:
                    next_review = next_review.replace(tzinfo=timezone.utc)
                if next_review <= now:
                    due_cards.append(item)

        return due_cards

    def _format_deck_for_session(self, cards_with_context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Форматирует карточки для SRS сессии согласно API спецификации"""
        deck = []

        for item in cards_with_context:
            card = item['card']
            context = item.get('context')
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

            # Get examples, but filter out Anki templates (contain {{ }})
            examples = getattr(word, 'sentences', None)
            if examples and '{{' in examples:
                examples = None  # Skip Anki template syntax

            deck_item = {
                'card_id': card.id,
                'front': front,
                'back': back,
                'phase': phase,
                'new': card.repetitions == 0,
                'direction': card.direction,
                'ease_factor': card.ease_factor,
                'interval': card.interval,
                'audio_url': self._get_audio_url(word, card.direction),
                'has_audio': getattr(word, 'get_download', 0) == 1,
                # Full word data for vocabulary template
                'word_id': word.id,
                'lemma': word.english_word,
                'translation': word.russian_word,
                'part_of_speech': getattr(word, 'part_of_speech', None),
                'level': getattr(word, 'level', None),
                'transcription': getattr(word, 'transcription', None),
                'examples': examples,
                # Context from book (SliceVocabulary)
                'context': context,
            }

            deck.append(deck_item)

        return deck

    def _get_audio_url(self, word: CollectionWords, direction: str) -> Optional[str]:
        """
        Получает URL аудио для слова.
        Поддерживает оба формата в БД:
        - Clean filename: pronunciation_en_word.mp3
        - Legacy Anki format: [sound:pronunciation_en_word.mp3]

        Аудио возвращается для обоих направлений (английское произношение).
        """
        if hasattr(word, 'listening') and word.listening:
            filename = word.listening
            # Извлекаем имя файла из Anki формата если нужно
            if filename.startswith('[sound:') and filename.endswith(']'):
                filename = filename[7:-1]  # Remove [sound: and ]
            return f"/static/audio/{filename}"
        # Fallback: генерируем URL на основе слова (пробелы -> _)
        word_slug = word.english_word.lower().replace(' ', '_')
        return f"/static/audio/pronunciation_en_{word_slug}.mp3"

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

    def add_word_to_srs(self, user_id: int, word_id: int, source: str = 'book_reading',
                         course_id: int = None) -> Dict[str, Any]:
        """
        Добавляет одно слово в SRS карточки.
        Создает UserWord и карточки для обоих направлений.
        Если указан course_id — добавляет слово в колоду книжного курса.

        Args:
            user_id: ID пользователя
            word_id: ID слова из CollectionWords
            source: Источник добавления (book_reading, vocabulary_lesson и т.д.)
            course_id: ID книжного курса (опционально)

        Returns:
            Dict с результатом операции и word_status
        """
        try:
            # Проверяем текущий статус слова
            word_status = get_word_status_for_ui(user_id, word_id)

            # Если слово уже выучено — возвращаем статус
            if word_status == 'learned':
                return {
                    'success': False,
                    'error': 'Слово уже выучено',
                    'word_status': 'learned',
                    'already_exists': True
                }

            # Если слово уже в обучении — возвращаем статус
            if word_status == 'in_learning':
                return {
                    'success': True,
                    'message': 'Слово уже в обучении',
                    'word_status': 'in_learning',
                    'already_exists': True
                }

            # Проверяем, существует ли слово
            word = CollectionWords.query.get(word_id)
            if not word:
                return {'success': False, 'error': 'Слово не найдено', 'word_status': 'not_added'}

            # Создаем или получаем UserWord
            user_word = UserWord.get_or_create(user_id, word_id)

            # Создаем карточки для обоих направлений
            eng_rus_card = self._get_or_create_card_direction(user_word, 'eng-rus')
            rus_eng_card = self._get_or_create_card_direction(user_word, 'rus-eng')

            # Если указан course_id — добавляем в колоду курса
            deck_id = None
            if course_id:
                course = BookCourse.query.get(course_id)
                if course:
                    deck = get_or_create_book_course_deck(user_id, course)
                    deck_id = deck.id

                    # Добавляем слово в колоду если его там нет
                    existing_deck_word = QuizDeckWord.query.filter_by(
                        deck_id=deck.id, word_id=word_id
                    ).first()
                    if not existing_deck_word:
                        deck_word = QuizDeckWord(deck_id=deck.id, word_id=word_id)
                        db.session.add(deck_word)

            db.session.commit()

            logger.info(f"Added word {word_id} to SRS for user {user_id} (source: {source}, course: {course_id})")

            return {
                'success': True,
                'message': 'Слово добавлено в карточки',
                'word_id': word_id,
                'word_status': 'in_learning',
                'cards_created': 2,
                'eng_rus_card_id': eng_rus_card.id,
                'rus_eng_card_id': rus_eng_card.id,
                'deck_id': deck_id
            }

        except Exception as e:
            logger.error(f"Error adding word {word_id} to SRS: {str(e)}")
            db.session.rollback()
            return {'success': False, 'error': str(e), 'word_status': 'not_added'}

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
