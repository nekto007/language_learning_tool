# app/curriculum/card_service.py
"""Card / SRS functions for curriculum lessons."""

import logging
import random
from datetime import datetime, UTC

from sqlalchemy import Date, cast, func

from app.curriculum.models import LessonProgress, Lessons
from app.study.models import UserCardDirection, UserWord
from app.utils.audio import normalize_listening
from app.utils.db import db
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)


def get_audio_filename(word):
    """
    Получает имя аудио файла для слова.
    Поддерживает оба формата в БД:
    - Clean filename: pronunciation_en_word.mp3
    - Legacy Anki format: [sound:pronunciation_en_word.mp3]
    """
    if not hasattr(word, 'get_download') or word.get_download != 1 or not word.listening:
        return None

    from app.utils.audio import parse_audio_filename
    return parse_audio_filename(word.listening)


def get_cards_for_lesson(lesson_id, user_id):
    """
    Получает карточки для урока типа 'card' из общего пула слов пользователя
    """
    from app.study.models import StudySettings

    lesson = Lessons.query.get_or_404(lesson_id)

    # Получаем или создаем прогресс урока
    progress = LessonProgress.query.filter_by(
        user_id=user_id,
        lesson_id=lesson_id
    ).first()

    if not progress:
        progress = LessonProgress(
            user_id=user_id,
            lesson_id=lesson_id,
            status='in_progress',
            data={
                'studied_cards': {},  # {card_direction_id: {status, rating, timestamp, was_new}}
                'cards_studied': 0,
                'correct_answers': 0,
                'total_answers': 0,
                'card_progress': {}
            },
            started_at=datetime.now(UTC),
            last_activity=datetime.now(UTC)
        )
        db.session.add(progress)
        db.session.commit()

    # Убедимся, что data содержит нужные поля
    if not progress.data:
        progress.data = {}
    if 'studied_cards' not in progress.data:
        progress.data['studied_cards'] = {}

    # Получаем данные об изученных карточках
    studied_cards = progress.data.get('studied_cards', {})  # {card_direction_id: {status, rating, timestamp}}
    shown_card_ids = list(studied_cards.keys())  # ID карточек которые уже показывались

    # Подсчитываем статистику на основе изученных карточек
    # Считаем только успешно пройденные карточки для лимитов
    new_cards_shown = 0
    review_cards_shown = 0

    for card_id, card_info in studied_cards.items():
        # Считаем все карточки (и passed и failed) для исключения из выдачи
        # Но для лимитов считаем только успешно пройденные
        if card_info.get('status') == 'passed':
            if card_info.get('was_new', True):
                new_cards_shown += 1
            else:
                review_cards_shown += 1


    # Определяем лимиты для урока
    lesson_number = lesson.number
    if lesson_number in [3, 5]:
        max_new_cards = 10
        max_review_cards = 20
    else:
        # Для других уроков используем стандартные настройки
        user_settings = StudySettings.get_settings(user_id)
        max_new_cards = user_settings.new_words_per_day
        max_review_cards = user_settings.reviews_per_day

    cards = []

    # 1. Получаем карточки для повторения (не больше лимита и не показанные ранее)
    remaining_reviews = max_review_cards - review_cards_shown
    if remaining_reviews > 0:
        due_directions = UserCardDirection.query.join(
            UserWord, UserCardDirection.user_word_id == UserWord.id
        ).filter(
            UserWord.user_id == user_id,
            UserCardDirection.last_reviewed.isnot(None),
            cast(UserCardDirection.next_review, Date) <= func.current_date(),
            ~UserCardDirection.id.in_([int(id) for id in shown_card_ids]) if shown_card_ids else True
        ).order_by(
            UserCardDirection.next_review.asc()
        ).limit(remaining_reviews).all()

        for direction in due_directions:
            user_word = UserWord.query.get(direction.user_word_id)
            word = CollectionWords.query.get(user_word.word_id)

            if word and word.russian_word:
                intervals = calculate_card_intervals(direction)

                card_data = {
                    'word_id': word.id,
                    'direction_id': direction.id,
                    'direction': direction.direction,
                    'front': word.english_word if direction.direction == 'eng-rus' else word.russian_word,
                    'back': word.russian_word if direction.direction == 'eng-rus' else word.english_word,
                    'examples': word.sentences,
                    'audio': get_audio_filename(word),
                    'is_new': False,
                    'interval': direction.interval,
                    'ease_factor': direction.ease_factor,
                    'repetitions': direction.repetitions,
                    'session_attempts': direction.session_attempts,
                    'calculated_intervals': intervals
                }
                cards.append(card_data)

    # 2. Добавляем новые карточки (не больше лимита и не показанные ранее)
    remaining_new = max_new_cards - new_cards_shown
    if remaining_new > 0:
        new_directions = UserCardDirection.query.join(
            UserWord, UserCardDirection.user_word_id == UserWord.id
        ).filter(
            UserWord.user_id == user_id,
            UserCardDirection.last_reviewed.is_(None),
            UserCardDirection.repetitions == 0,
            ~UserCardDirection.id.in_([int(id) for id in shown_card_ids]) if shown_card_ids else True
        ).order_by(
            UserCardDirection.id.asc()
        ).limit(remaining_new).all()

        for direction in new_directions:
            user_word = UserWord.query.get(direction.user_word_id)
            word = CollectionWords.query.get(user_word.word_id)
            if word and word.russian_word:
                card_data = {
                    'word_id': word.id,
                    'direction_id': direction.id,
                    'direction': direction.direction,
                    'front': word.english_word if direction.direction == 'eng-rus' else word.russian_word,
                    'back': word.russian_word if direction.direction == 'eng-rus' else word.english_word,
                    'examples': word.sentences,
                    'audio': get_audio_filename(word),
                    'is_new': True,
                    'interval': 0,
                    'ease_factor': 2.5,
                    'repetitions': 0
                }
                cards.append(card_data)

    # Перемешиваем карточки
    cards = smart_shuffle_cards(cards)

    # Подсчитываем текущие показатели
    new_cards_count = sum(1 for c in cards if c['is_new'])
    review_cards_count = sum(1 for c in cards if not c['is_new'])

    # Подсчитываем общее количество доступных карточек
    total_due = new_cards_count + review_cards_count


    return {
        'cards': cards,
        'total_due': total_due,
        'srs_settings': {
            'new_cards_per_day': max_new_cards,
            'reviews_per_day': max_review_cards,
            'show_hint_time': 7
        },
        'lesson_settings': {
            'min_cards_required': 1,  # Минимум 1 карточка для завершения
            'min_accuracy_required': 0  # Не требуем минимальной точности
        },
        'stats': {
            'new_cards_count': new_cards_count,
            'review_cards_count': review_cards_count,
            'new_cards_shown': new_cards_shown,
            'review_cards_shown': review_cards_shown,
            'new_cards_limit': max_new_cards,
            'reviews_limit': max_review_cards,
            'new_cards_remaining': max_new_cards - new_cards_shown,
            'reviews_remaining': max_review_cards - review_cards_shown,
            'total_due': total_due
        }
    }


def smart_shuffle_cards(cards):
    """
    Умное перемешивание карточек, чтобы не было подряд карточек одного слова

    Args:
        cards: список карточек

    Returns:
        list: перемешанный список карточек
    """
    if len(cards) <= 1:
        return cards

    # Группируем карточки по word_id (fallback to 'id' for test compatibility)
    word_groups = {}
    for card in cards:
        word_id = card.get('word_id', card.get('id'))
        if word_id is None:
            # If no identifying field, treat each card as unique
            word_id = id(card)
        if word_id not in word_groups:
            word_groups[word_id] = []
        word_groups[word_id].append(card)

    # Если у нас только одно слово, просто перемешиваем
    if len(word_groups) == 1:
        random.shuffle(cards)
        return cards

    # Создаем новый список, чередуя слова
    result = []
    word_ids = list(word_groups.keys())
    random.shuffle(word_ids)

    # Распределяем карточки так, чтобы карточки одного слова не шли подряд
    while any(word_groups.values()):
        for word_id in word_ids:
            if word_groups[word_id]:
                card = word_groups[word_id].pop(0)
                result.append(card)

    return result


def process_card_review_for_lesson(lesson_id, user_id, word_id, direction, rating, session_data=None):
    """
    Обрабатывает оценку карточки в контексте урока

    Args:
        lesson_id: ID урока
        user_id: ID пользователя
        word_id: ID слова
        direction: Направление карточки ('eng-rus' или 'rus-eng')
        rating: Оценка (0-5)
        session_data: Дополнительные данные сессии (не используется больше для failed_attempts)

    Returns:
        dict: Результат обработки
    """
    # Получаем или создаем UserWord
    user_word = UserWord.get_or_create(user_id, word_id)

    from app.study.deck_utils import ensure_word_in_default_deck
    ensure_word_in_default_deck(user_id, word_id, user_word.id)

    # Получаем или создаем направление
    card_direction = UserCardDirection.query.filter_by(
        user_word_id=user_word.id,
        direction=direction
    ).first()

    if not card_direction:
        card_direction = UserCardDirection(
            user_word_id=user_word.id,
            direction=direction
        )
        db.session.add(card_direction)

    # Сначала получаем или создаем прогресс урока (нужно для обеих веток)
    progress = LessonProgress.query.filter_by(
        user_id=user_id,
        lesson_id=lesson_id
    ).first()

    if not progress:
        progress = LessonProgress(
            user_id=user_id,
            lesson_id=lesson_id,
            status='in_progress',
            started_at=datetime.now(UTC),
            last_activity=datetime.now(UTC),
            data={
                'cards_studied': 0,
                'correct_answers': 0,
                'total_answers': 0,
                'card_progress': {},
                'shown_card_ids': [],
                'new_cards_shown': 0,
                'review_cards_shown': 0
            }
        )
        db.session.add(progress)
        db.session.flush()  # Чтобы получить ID сразу
    else:
        # Убеждаемся, что data инициализирована правильно
        if not progress.data:
            progress.data = {}

        # Проверяем наличие всех необходимых полей и инициализируем отсутствующие
        required_fields = {
            'cards_studied': 0,
            'correct_answers': 0,
            'total_answers': 0,
            'studied_cards': {},  # {card_direction_id: {status, rating, timestamp, was_new}}
            'session_stats': {
                'start_time': None,
                'cards_attempted': 0,
                'accuracy': 100
            }
        }

        for field, default_value in required_fields.items():
            if field not in progress.data:
                progress.data[field] = default_value

        # ВАЖНО: убедимся, что поле обновляется в БД
        db.session.merge(progress)

    # При оценке 0 ("Не помню") - записываем информацию о карточке
    if rating == 0:
        # Записываем информацию о показанной карточке
        card_id_str = str(card_direction.id)
        if card_id_str not in progress.data['studied_cards']:
            was_new_card = card_direction.repetitions == 0
            progress.data['studied_cards'][card_id_str] = {
                'status': 'failed',
                'rating': rating,
                'timestamp': datetime.now(UTC).isoformat(),
                'was_new': was_new_card,
                'attempts': 1
            }
        else:
            # Увеличиваем количество попыток
            progress.data['studied_cards'][card_id_str]['attempts'] += 1
            progress.data['studied_cards'][card_id_str]['last_attempt'] = datetime.now(UTC).isoformat()

        # Увеличиваем счетчик попыток в текущей сессии
        card_direction.session_attempts += 1

        # Увеличиваем общий счетчик неправильных ответов
        card_direction.incorrect_count += 1

        # Обновляем время последней попытки
        card_direction.last_reviewed = datetime.now(UTC)

        # НЕ обновляем interval и next_review - карточка остается "просроченной"

        # Обновляем статистику урока
        progress.data['total_answers'] = progress.data.get('total_answers', 0) + 1

        # Обновляем прогресс карточки
        card_key = f"{word_id}-{direction}"
        if 'card_progress' not in progress.data:
            progress.data['card_progress'] = {}
        if card_key not in progress.data['card_progress']:
            progress.data['card_progress'][card_key] = {'correct': 0, 'incorrect': 0}
        progress.data['card_progress'][card_key]['incorrect'] += 1

        progress.last_activity = datetime.now(UTC)

        # Помечаем объект как измененный для SQLAlchemy
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(progress, 'data')

        db.session.commit()


        # Рассчитываем интервалы с учетом неудачных попыток
        next_intervals = calculate_card_intervals(card_direction)

        # Возвращаем результат без обновления интервалов
        return {
            'success': True,
            'interval': card_direction.interval,
            'next_review': card_direction.next_review.isoformat() if card_direction.next_review else None,
            'achievements': [],
            'daily_limit_reached': False,
            'failed_attempt': True,
            'session_attempts': card_direction.session_attempts,
            'calculated_intervals': next_intervals  # Добавляем рассчитанные интервалы
        }

    # Для оценок > 0 обрабатываем с учетом накопленных неудач
    effective_rating = rating

    # Корректируем оценку на основе количества неудачных попыток в этой сессии
    if card_direction.session_attempts > 0:
        # Если было 1-2 неудачи - снижаем оценку на количество неудач
        if card_direction.session_attempts <= 2:
            effective_rating = max(1, rating - card_direction.session_attempts)
        # Если было 3+ неудач - максимальная эффективная оценка = 2 ("сложно")
        else:
            effective_rating = min(2, rating)

    # Проверяем была ли это новая карточка до обработки рейтинга
    was_new_card = card_direction.repetitions == 0

    # Записываем информацию о успешно изученной карточке
    card_id_str = str(card_direction.id)
    if card_id_str not in progress.data['studied_cards']:
        progress.data['studied_cards'][card_id_str] = {
            'status': 'passed',
            'rating': rating,
            'effective_rating': effective_rating,
            'timestamp': datetime.now(UTC).isoformat(),
            'was_new': was_new_card,
            'attempts': card_direction.session_attempts + 1  # +1 for current successful attempt
        }
    else:
        # Обновляем существующую запись
        progress.data['studied_cards'][card_id_str].update({
            'status': 'passed',
            'rating': rating,
            'effective_rating': effective_rating,
            'last_success': datetime.now(UTC).isoformat(),
            'attempts': progress.data['studied_cards'][card_id_str].get('attempts', 0) + 1
        })

    # ВАЖНО: старую логику shown_card_ids больше не используем, так как теперь используем studied_cards

    # Обновляем SRS параметры с учетом эффективной оценки
    interval = card_direction.update_after_review(effective_rating)


    # Сбрасываем счетчик попыток текущей сессии после успешного ответа
    card_direction.session_attempts = 0

    # Если это первое успешное изучение карточки
    if card_direction.repetitions == 1 and rating >= 3:
        # Определяем противоположное направление
        if direction == 'eng-rus':
            opposite_direction = 'rus-eng'
        else:
            opposite_direction = 'eng-rus'

        # Проверяем, существует ли уже противоположное направление
        opposite_card = UserCardDirection.query.filter_by(
            user_word_id=user_word.id,
            direction=opposite_direction
        ).first()

        if not opposite_card:
            # Создаем противоположное направление
            opposite_card = UserCardDirection(
                user_word_id=user_word.id,
                direction=opposite_direction
            )
            db.session.add(opposite_card)

    # Обновляем статистику урока
    progress.data['total_answers'] = progress.data.get('total_answers', 0) + 1

    # Увеличиваем счетчик изученных карточек только при первом успешном ответе
    card_key = f"{word_id}-{direction}"

    # Убеждаемся, что card_progress существует
    if 'card_progress' not in progress.data:
        progress.data['card_progress'] = {}

    if card_key not in progress.data['card_progress']:
        progress.data['cards_studied'] = progress.data.get('cards_studied', 0) + 1
        progress.data['card_progress'][card_key] = {'correct': 0, 'incorrect': 0}

    # Обновляем статистику правильных/неправильных ответов
    if rating >= 3:
        progress.data['correct_answers'] = progress.data.get('correct_answers', 0) + 1
        progress.data['card_progress'][card_key]['correct'] += 1
    else:
        progress.data['card_progress'][card_key]['incorrect'] += 1

    progress.last_activity = datetime.now(UTC)

    # Проверяем, завершен ли урок (для уроков 3 и 5)
    lesson = Lessons.query.get(lesson_id)
    if lesson.number in [3, 5]:
        # Проверяем, есть ли еще доступные карточки
        cards_data = get_cards_for_lesson(lesson_id, user_id)
        if not cards_data['cards']:  # Нет больше карточек для показа
            progress.status = 'completed'
            progress.completed_at = datetime.now(UTC)

    # Помечаем объект как измененный для SQLAlchemy
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(progress, 'data')

    # Коммитим все изменения
    db.session.commit()

    # Подсчитываем статистику на основе studied_cards
    studied_cards = progress.data.get('studied_cards', {})
    total_studied = len([c for c in studied_cards.values() if c.get('status') == 'passed'])
    new_cards_studied = len(
        [c for c in studied_cards.values() if c.get('status') == 'passed' and c.get('was_new', True)])
    review_cards_studied = len(
        [c for c in studied_cards.values() if c.get('status') == 'passed' and not c.get('was_new', True)])

    # Проверяем достижения (если нужно)
    achievements = []

    # Проверяем дневные лимиты
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    new_cards_today = db.session.query(func.count(UserCardDirection.id)).filter(
        UserCardDirection.user_word_id.in_(
            db.session.query(UserWord.id).filter_by(user_id=user_id)
        ),
        UserCardDirection.last_reviewed >= today_start,
        UserCardDirection.repetitions == 1
    ).scalar() or 0

    from app.study.models import StudySettings
    user_settings = StudySettings.get_settings(user_id)

    # Для уроков 3 и 5 используем их лимиты
    if lesson.number in [3, 5]:
        daily_limit = 10  # лимит новых карточек для уроков 3 и 5
        # Подсчитываем изученные новые карточки в этой сессии урока
        studied_cards = progress.data.get('studied_cards', {})
        lesson_new_cards_studied = len(
            [c for c in studied_cards.values() if c.get('status') == 'passed' and c.get('was_new', True)])
        daily_limit_reached = lesson_new_cards_studied >= daily_limit
    else:
        daily_limit = user_settings.new_words_per_day
        daily_limit_reached = new_cards_today >= daily_limit

    # Рассчитываем интервалы для следующего показа (после обновления)
    next_intervals = calculate_card_intervals(card_direction)

    return {
        'success': True,
        'interval': interval,
        'next_review': card_direction.next_review.isoformat() if card_direction.next_review else None,
        'achievements': achievements,
        'daily_limit_reached': daily_limit_reached,
        'calculated_intervals': next_intervals,
        'daily_stats': {
            'new_cards_today': new_cards_today,
            'new_cards_limit': daily_limit,
            'lesson_new_cards_studied': new_cards_studied,
            'lesson_review_cards_studied': review_cards_studied
        }
    }


# Комбинированный сервис: возвращает список карточек и при отсутствии due-карточек — время следующего ревью.
def get_card_session_for_lesson(lesson_id, user_id):
    """
    Комбинированный сервис: возвращает список карточек и при отсутствии due-карточек — время следующего ревью.
    """
    # Получаем due-карточки и статистику
    session_data = get_cards_for_lesson(lesson_id, user_id)
    cards = session_data.get('cards', [])
    # Если есть карточки для изучения сегодня, next_review_time не нужен
    if cards:
        session_data['next_review_time'] = None
        return session_data

    # Иначе ищем ближайший следующий review
    from datetime import datetime
    next_dir = (
        UserCardDirection.query.join(
            UserWord, UserCardDirection.user_word_id == UserWord.id
        )
        .filter(
            UserWord.user_id == user_id,
            UserCardDirection.next_review > datetime.now(UTC)
        )
        .order_by(UserCardDirection.next_review)
        .first()
    )

    # Формируем текстовое представление времени до следующего review
    if not next_dir:
        session_data['next_review_time'] = "Нет запланированных повторений"
    else:
        delta = next_dir.next_review - datetime.now(UTC)
        if delta.days == 0:
            hours = delta.seconds // 3600
            if hours == 0:
                minutes = delta.seconds // 60
                session_data['next_review_time'] = f"{minutes} минут"
            else:
                session_data['next_review_time'] = f"{hours} часов"
        elif delta.days == 1:
            session_data['next_review_time'] = "завтра"
        elif delta.days < 7:
            session_data['next_review_time'] = f"{delta.days} дней"
        elif delta.days < 30:
            weeks = delta.days // 7
            session_data['next_review_time'] = f"{weeks} недель"
        else:
            months = delta.days // 30
            session_data['next_review_time'] = f"{months} месяцев"

    return session_data


def calculate_card_intervals(card_direction):
    """
    Рассчитывает интервалы для карточки с учетом текущего состояния и неудачных попыток

    Args:
        card_direction: объект UserCardDirection

    Returns:
        dict: словарь с интервалами для каждой оценки
    """
    ease_factor = card_direction.ease_factor
    current_interval = card_direction.interval
    session_attempts = card_direction.session_attempts

    # Базовые интервалы
    if card_direction.repetitions == 0 or current_interval == 0:
        # Для новых карточек
        base_intervals = {
            'again': 0,  # Повтор сейчас
            'hard': 1,
            'good': 3,
            'easy': 7
        }
    else:
        # Для повторяющихся карточек
        base_intervals = {
            'again': 0,  # Всегда повтор сейчас
            'hard': max(1, round(current_interval * 0.8)),
            'good': max(1, round(current_interval * ease_factor)),
            'easy': max(1, round(current_interval * ease_factor * 1.3))
        }

    # Корректируем интервалы с учетом неудачных попыток
    adjusted_intervals = {}

    # again (0) - всегда повтор сейчас
    adjusted_intervals['again'] = 0

    # Для остальных оценок учитываем неудачные попытки
    for rating_name, rating_value in [('hard', 2), ('good', 4), ('easy', 5)]:
        # Рассчитываем эффективную оценку
        if session_attempts > 0:
            if session_attempts <= 2:
                effective_rating = max(1, rating_value - session_attempts)
            else:
                effective_rating = min(2, rating_value)
        else:
            effective_rating = rating_value

        # Применяем логику из update_after_review
        if card_direction.repetitions == 0:
            # Первое изучение
            if effective_rating >= 3:
                if effective_rating == 3:
                    interval = 1
                elif effective_rating == 4:
                    interval = 3
                else:  # 5
                    interval = 7
            else:
                interval = 1
        else:
            # Повторения
            if effective_rating < 3:
                interval = 1
            else:
                # Используем базовый интервал для данной оценки
                base = base_intervals[rating_name]

                if effective_rating == 3:
                    interval = max(1, round(base * 0.8))
                elif effective_rating == 4:
                    interval = base
                else:  # 5
                    interval = max(1, round(base * 1.3))

        adjusted_intervals[rating_name] = interval

    return adjusted_intervals


def sync_lesson_cards_to_words(lesson):
    """
    Синхронизирует карточки из JSON урока с таблицей collection_words.
    Если слово уже существует - обновляет, если нет - создает.
    Обновляет JSON урока, добавляя word_id к каждой карточке.

    Args:
        lesson: Объект урока (Lessons)

    Returns:
        tuple: (success: bool, message: str, updated_count: int, created_count: int)
    """
    import json

    if not lesson.content:
        logger.warning(f"Lesson {lesson.id} has no content")
        return False, "Урок не имеет контента", 0, 0

    try:
        # Parse content
        content = json.loads(lesson.content) if isinstance(lesson.content, str) else lesson.content

        if not isinstance(content, dict) or 'cards' not in content:
            return False, "Контент не содержит поле 'cards'", 0, 0

        cards = content['cards']
        if not isinstance(cards, list):
            return False, "Поле 'cards' должно быть списком", 0, 0

        created_count = 0
        updated_count = 0
        skipped_count = 0

        # Process each card
        for idx, card in enumerate(cards):
            if not isinstance(card, dict):
                continue

            # Skip if already has word_id
            if 'word_id' in card and card['word_id']:
                skipped_count += 1
                continue

            # Support both formats: front/back (eng-rus) and english/russian
            english = (card.get('english') or card.get('front', '')).strip().lower()
            russian = (card.get('russian') or card.get('back', '')).strip()

            if not english:
                logger.warning(f"Card {idx} (id={card.get('id')}) missing 'english'/'front' field")
                continue

            # Check if word exists
            word = CollectionWords.query.filter_by(english_word=english).first()

            if word:
                # Update existing word
                if russian and not word.russian_word:
                    word.russian_word = russian
                if card.get('audio') and not word.listening:
                    word.listening = normalize_listening(card.get('audio'), english)

                # Update sentences if we have examples
                if card.get('example') and card.get('example_translation'):
                    en = card.get('example', '')
                    ru = card.get('example_translation', '')
                    sentences_text = f"{en}<br>{ru}"
                    if not word.sentences or sentences_text not in word.sentences:
                        word.sentences = sentences_text

                updated_count += 1
                logger.info(f"Updated word: {english} (ID: {word.id})")
            else:
                # Create new word
                sentences_text = None
                if card.get('example') and card.get('example_translation'):
                    en = card.get('example', '')
                    ru = card.get('example_translation', '')
                    sentences_text = f"{en}<br>{ru}"

                word = CollectionWords(
                    english_word=english,
                    russian_word=russian,
                    listening=normalize_listening(card.get('audio', ''), english),
                    sentences=sentences_text,
                    level='A0',  # Default level
                    get_download=1 if card.get('audio') else 0
                )
                db.session.add(word)
                db.session.flush()  # Get ID without committing
                created_count += 1
                logger.info(f"Created word: {english} (ID: {word.id})")

            # Add word_id to card
            card['word_id'] = word.id

        # Update lesson content with word_ids
        # IMPORTANT: Mark column as modified for SQLAlchemy to detect changes in JSONB
        from sqlalchemy.orm.attributes import flag_modified
        lesson.content = content
        flag_modified(lesson, 'content')
        db.session.commit()

        message = f"Создано: {created_count}, Обновлено: {updated_count}, Пропущено: {skipped_count}"
        logger.info(f"Sync completed for lesson {lesson.id}: {message}")

        return True, message, updated_count, created_count

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error syncing lesson cards: {str(e)}")
        return False, f"Ошибка: {str(e)}", 0, 0
