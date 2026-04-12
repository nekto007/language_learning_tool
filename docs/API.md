# API Documentation

Language Learning Tool — полный каталог API-эндпоинтов. 85+ endpoints, JSON responses.

## Содержание

- [Аутентификация](#аутентификация)
- [Words API](#words-api)
- [Books API](#books-api)
- [Topics & Collections API](#topics--collections-api)
- [Study / Flashcards API](#study--flashcards-api)
- [Curriculum API](#curriculum-api)
- [SRS API](#srs-api)
- [Grammar Lab API](#grammar-lab-api)
- [Daily Plan API](#daily-plan-api)
- [Anki Export API](#anki-export-api)
- [Telegram API](#telegram-api)
- [Notifications API](#notifications-api)
- [System API](#system-api)
- [SEO & Public Pages](#seo--public-pages)
- [Типы авторизации](#типы-авторизации)
- [Обработка ошибок](#обработка-ошибок)

---

## Аутентификация

### `POST /api/login`
Авторизация. Возвращает JWT-токены.

**Body:**
```json
{ "username": "user123", "password": "password123" }
```

**Response:**
```json
{
  "success": true,
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "user": { "id": 1, "username": "user123" }
}
```

### `POST /api/refresh`
Обновление access-токена. CSRF exempt.

**Headers:** `Authorization: Bearer <refresh_token>`

**Response:**
```json
{ "access_token": "eyJ..." }
```

---

## Words API

### `GET /api/words`
Список слов с фильтрами и пагинацией.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание | Обязательный |
|----------|-----|----------|:---:|
| status | int | Фильтр по статусу | - |
| book_id | int | Фильтр по книге | - |
| topic_id | int | Фильтр по теме | - |
| collection_id | int | Фильтр по коллекции | - |
| letter | string | Фильтр по первой букве | - |
| search | string | Поиск | - |
| page | int | Страница (default: 1) | - |
| per_page | int | Элементов на странице (default: 50) | - |

**Response:**
```json
{
  "words": [
    {
      "id": 1,
      "english_word": "example",
      "russian_word": "пример",
      "status": 2,
      "get_download": 1,
      "sentences": "This is an example.<br>Это пример.",
      "level": "A1"
    }
  ],
  "total": 150,
  "page": 1,
  "per_page": 50,
  "total_pages": 3
}
```

### `GET /api/words/<word_id>`
Детальная информация о слове.

**Auth:** `@api_auth_required`

**Response:**
```json
{
  "id": 1,
  "english_word": "example",
  "russian_word": "пример",
  "listening": "[sound:pronunciation_en_example.mp3]",
  "sentences": "This is an example.<br>Это пример.",
  "level": "A1",
  "brown": 1,
  "get_download": 1,
  "status": 2,
  "books": [{ "id": 3, "title": "Sample Book", "frequency": 5 }],
  "topics": [{ "id": 1, "name": "Food" }],
  "collections": [{ "id": 2, "name": "A1 Vocabulary" }]
}
```

### `POST /api/update-word-status`
Обновление статуса одного слова.

**Auth:** `@api_auth_required`

**Body:**
```json
{ "word_id": 1, "status": 3 }
```

**Response:**
```json
{ "success": true, "status": 3 }
```

### `POST /api/batch-update-status`
Массовое обновление статусов.

**Auth:** `@api_auth_required`

**Body:**
```json
{ "word_ids": [1, 2, 3], "status": 2, "deck_id": 5 }
```

**Response:**
```json
{ "success": true, "updated_count": 3, "deck_added_count": 3 }
```

### `POST /api/words/<word_id>/status`
Альтернативный endpoint обновления статуса слова.

**Auth:** `@api_auth_required`

**Body:**
```json
{ "status": 2, "deck_id": 5 }
```

**Response:**
```json
{ "success": true, "status": "learning", "deck_added": true, "deck_message": "Добавлено в колоду" }
```

### `POST /api/user-words-status`
Получение статусов для списка слов.

**Auth:** `@api_auth_required`

**Body:**
```json
{ "word_ids": [1, 2, 3] }
```

**Response:**
```json
{ "success": true, "words": [{ "word_id": 1, "status": 2 }] }
```

### `GET /api/search`
Быстрый поиск слов.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| term | string | Поисковый запрос |

**Response:**
```json
[{ "id": 1, "english_word": "example", "russian_word": "пример", "level": "A1" }]
```

---

## Books API

### `GET /api/books`
Список всех книг.

**Auth:** `@api_auth_required`

**Response:**
```json
{
  "books": [
    { "id": 1, "title": "Sample Book", "total_words": 1500, "unique_words": 350, "scrape_date": "2023-01-15T14:30:45" }
  ]
}
```

### `GET /api/books/<book_id>`
Детали книги со статистикой слов.

**Auth:** `@api_auth_required`

**Response:**
```json
{
  "id": 1,
  "title": "Sample Book",
  "total_words": 1500,
  "unique_words": 350,
  "word_stats": { "new": 120, "known": 180, "queued": 25, "active": 15, "mastered": 10 }
}
```

### `GET /api/books/<slug>/chapters`
Список глав книги по slug. Кешируется 1 час.

**Auth:** `@api_auth_required`

**Response:**
```json
[{ "id": 1, "num": 1, "title": "Chapter One", "words": 1200, "audio_url": "/audio/ch1.mp3" }]
```

### `GET /api/books/<book_id>/chapters`
Список глав книги по ID. Кешируется 1 час.

**Auth:** `@api_auth_required`

### `GET /api/books/<book_id>/chapters/<chapter_num>`
Контент главы. Поддерживает gzip-сжатие (`Accept-Encoding: gzip`).

**Auth:** `@api_auth_required`

**Response:**
```json
{ "id": 5, "num": 3, "title": "Chapter Three", "text": "<p>...</p>", "next": 4, "prev": 2 }
```

### `PATCH /api/progress`
Обновление прогресса чтения.

**Auth:** `@api_auth_required`

**Body:**
```json
{ "book_id": 1, "chapter_id": 5, "offset_pct": 0.75 }
```

**Response:**
```json
{ "success": true, "chapter_id": 5, "offset_pct": 0.75 }
```

### `GET /api/books/<book_id>/progress`
Прогресс чтения пользователя.

**Auth:** `@api_auth_required`

**Response:**
```json
{ "current_chapter": 5, "offset_pct": 0.75, "chapters_read": [1, 2, 3, 4] }
```

### `GET /api/word-translation/<word>`
Перевод слова с аудио и определением формы (для ридера).

**Auth:** `@api_auth_required`

**Response:**
```json
{
  "word": "running",
  "translation": "бег",
  "in_dictionary": true,
  "id": 42,
  "status": "learning",
  "audio_url": "/audio/running.mp3",
  "is_form": true,
  "form_text": "форма глагола",
  "base_form": "run",
  "in_reading_deck": false
}
```

### `GET /api/book/<book_id>/content`
Контент книги для чтения с подсветкой словаря.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| start_position | int | Начальная позиция |
| end_position | int | Конечная позиция |

**Response:**
```json
{
  "success": true,
  "content": { "book_id": 1, "title": "...", "content_html": "...", "vocabulary_highlights": [], "interactive_elements": [] }
}
```

### `GET /api/tasks/<task_id>`
Получение задания по ID.

**Auth:** `@api_auth_required`

**Response:**
```json
{ "success": true, "task": { "id": 1, "block_id": 2, "task_type": "fill_gap", "payload": {} } }
```

### `GET /api/blocks/<block_id>/tasks`
Все задания блока.

**Auth:** `@api_auth_required`

**Response:**
```json
{ "success": true, "block_id": 2, "tasks": [] }
```

### `GET /api/blocks/<block_id>`
Информация о блоке с типами заданий.

**Auth:** `@api_auth_required`

**Response:**
```json
{ "success": true, "block": { "id": 2, "block_num": 1, "grammar_key": "present_simple", "focus_vocab": [], "task_types": ["fill_gap", "mcq"] } }
```

### `GET /api/chapters/<chapter_id>`
Получение главы по ID.

**Auth:** `@api_auth_required`

**Response:**
```json
{ "success": true, "chapter": { "id": 5, "num": 3, "title": "...", "text_raw": "...", "audio_url": null, "words": 1500, "book_id": 1 } }
```

---

## Topics & Collections API

### `GET /api/topics`
Список тем с пагинацией.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| search | string | Поиск |
| page | int | Страница |
| per_page | int | Элементов на странице |

**Response:**
```json
{
  "topics": [{ "id": 1, "name": "Food", "word_count": 25 }],
  "total": 10, "page": 1, "per_page": 20, "total_pages": 1
}
```

### `GET /api/topics/<topic_id>`
Детали темы со словами и связанными коллекциями.

**Response:**
```json
{ "id": 1, "name": "Food", "description": "...", "word_count": 25, "words": [], "related_collections": [], "creator": "admin" }
```

### `GET /api/topics/<topic_id>/words`
Слова темы с пагинацией.

### `POST /api/topics/<topic_id>/add-to-study`
Добавить все слова темы в изучение + колоду по умолчанию.

**Response:**
```json
{ "success": true, "topic_id": 1, "topic_name": "Food", "added_count": 15, "total_count": 20 }
```

### `GET /api/collections`
Список коллекций.

| Параметр | Тип | Описание |
|----------|-----|----------|
| search | string | Поиск |
| topic_id | int | Фильтр по теме |
| page | int | Страница |
| per_page | int | Элементов на странице |

### `GET /api/collections/<collection_id>`
Детали коллекции со словами и темами.

### `GET /api/collections/<collection_id>/words`
Слова коллекции с пагинацией.

### `POST /api/collections/<collection_id>/add-to-study`
Добавить все слова коллекции в изучение + колоду по умолчанию.

### `GET /api/words/<word_id>/topics`
Темы, содержащие слово.

### `GET /api/words/<word_id>/collections`
Коллекции, содержащие слово.

---

## Study / Flashcards API

### `GET /study/api/get-study-items`
Получение карточек для SRS-сессии (приоритетная очередь: relearning → learning → review → new).

**Auth:** `@login_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| source | string | `auto` или `deck` |
| deck_id | int | ID колоды |
| extra_study | bool | Доп. изучение сверх лимита |
| exclude_card_ids | string | Через запятую, для anti-repeat |

**Response:**
```json
{
  "status": "ok",
  "items": [{ "word_id": 1, "direction": "eng-rus", "state": "new", "english_word": "...", "russian_word": "..." }],
  "stats": { "new_count": 10, "learning_count": 5, "review_count": 15 },
  "has_more_new": true,
  "has_more_reviews": false
}
```

### `POST /study/api/update-study-item`
Оценка карточки (Anki state machine).

**Auth:** `@login_required`

**Body:**
```json
{ "word_id": 1, "direction": "eng-rus", "quality": 3, "session_id": "abc123", "deck_id": 5 }
```

**Response:**
```json
{
  "success": true,
  "card_id": 42,
  "interval": 1,
  "next_review": "2026-03-21T10:00:00",
  "requeue_position": 5,
  "requeue_minutes": 1,
  "state": "learning"
}
```

### `POST /study/api/complete-session`
Завершение сессии изучения. Начисляет XP.

**Body:**
```json
{ "session_id": "abc123" }
```

**Response:**
```json
{ "success": true, "stats": { "reviewed": 20, "correct": 18 }, "xp_earned": 25, "total_xp": 1500, "level": 5 }
```

### `GET /study/api/get-quiz-questions`
Вопросы для квиза.

| Параметр | Тип | Описание |
|----------|-----|----------|
| count | int | Количество вопросов (default: 10) |
| deck_id | int | ID колоды |
| word_source | string | `all`, `deck`, `book` |

**Response:**
```json
{ "success": true, "session_id": "abc", "total_questions": 10, "questions": [{ "word_id": 1, "question": "...", "options": [...], "correct": 2 }] }
```

### `POST /study/api/submit-quiz-answer`
Отправка ответа на вопрос квиза.

**Body:**
```json
{ "session_id": "abc", "question_index": 0, "answer_index": 2 }
```

**Response:**
```json
{ "success": true, "is_correct": true, "explanation": "..." }
```

### `POST /study/api/complete-quiz`
Завершение квиза.

**Body:**
```json
{ "session_id": "abc" }
```

**Response:**
```json
{ "success": true, "results": { "correct": 8, "total": 10, "score": 80 }, "xp_earned": 20, "total_xp": 1520 }
```

### `GET /study/api/get-matching-words`
Слова для игры "Matching".

| Параметр | Тип | Описание |
|----------|-----|----------|
| count | int | Количество пар (default: 8) |
| deck_id | int | ID колоды |

**Response:**
```json
{ "success": true, "session_id": "abc", "word_pairs": [{ "id": 1, "english": "cat", "russian": "кошка" }] }
```

### `POST /study/api/complete-matching-game`
Завершение игры "Matching".

**Body:**
```json
{ "session_id": "abc", "correct_count": 7, "total_count": 8, "time_seconds": 45 }
```

**Response:**
```json
{ "success": true, "correct_count": 7, "total_count": 8, "xp_earned": 15 }
```

### `GET /study/api/leaderboard/<game_type>`
Рейтинг игроков.

**Auth:** `@login_required`

| Параметр | Тип | Значения |
|----------|-----|----------|
| game_type | string | `quiz`, `matching`, `all` |

**Response:**
```json
{ "status": "success", "leaderboard": [{ "username": "...", "score": 100, "rank": 1 }], "user_best": { "score": 80, "rank": 3 } }
```

### `GET /study/api/search-words`
Поиск слов для добавления в колоду.

| Параметр | Тип | Описание |
|----------|-----|----------|
| q | string | Поисковый запрос |

**Response:**
```json
[{ "id": 1, "english_word": "cat", "russian_word": "кошка" }]
```

### `GET /study/api/collections-topics`
Доступные коллекции и темы для добавления в колоду.

**Response:**
```json
{ "collections": [{ "id": 1, "name": "A1 Vocab", "description": "...", "word_count": 50 }], "topics": [{ "id": 1, "name": "Food", "description": "...", "word_count": 25 }] }
```

### `POST /study/api/decks/<deck_id>/add-from-collection`
Добавить слова из коллекции в колоду.

**Body:**
```json
{ "collection_id": 5 }
```

**Response:**
```json
{ "success": true, "added_count": 15 }
```

### `POST /study/api/decks/<deck_id>/add-from-topic`
Добавить слова из темы в колоду.

**Body:**
```json
{ "topic_id": 3 }
```

### `GET /study/api/srs-stats`
SRS-статистика пользователя.

**Auth:** `@login_required`

**Response:**
```json
{ "new_count": 50, "learning_count": 30, "review_count": 100, "mastered_count": 200, "total": 380, "due_today": 25 }
```

### `GET /study/api/srs-overview`
SRS-обзор с колодами.

**Auth:** `@login_required`

**Response:**
```json
{ "stats": { "new_count": 50, "due_today": 25 }, "decks": [{ "id": 1, "title": "Мои слова", "word_count": 100 }], "default_deck": { "id": 1, "title": "..." } }
```

### `GET /study/api/my-decks`
Список колод пользователя.

**Response:**
```json
{ "success": true, "decks": [{ "id": 1, "title": "Мои слова", "word_count": 100, "is_public": false }] }
```

### `GET /study/api/default-deck`
Получение колоды по умолчанию.

**Response:**
```json
{ "success": true, "default_deck_id": 5, "default_deck_name": "Мои слова" }
```

### `POST /study/api/default-deck`
Установка колоды по умолчанию.

**Body:**
```json
{ "deck_id": 5 }
```

### `POST /study/api/decks/create`
Создание новой колоды.

**Body:**
```json
{ "name": "New Deck" }
```

**Response:**
```json
{ "success": true, "deck_id": 6, "deck": { "id": 6, "title": "New Deck" } }
```

### `POST /study/api/decks/<deck_id>/add-word`
Добавление слова в колоду.

**Body:**
```json
{ "word_id": 123 }
```

### `POST /study/api/add-phrase-to-deck`
Добавление кастомной фразы в колоду по умолчанию.

**Body:**
```json
{ "english": "custom phrase", "russian": "кастомная фраза", "context": "from reading" }
```

**Response:**
```json
{ "success": true, "message": "\"custom phrase\" added to your deck" }
```

### `GET /study/api/celebrations`
Проверка новых достижений и level-up для показа поздравлений.

**Auth:** `@login_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| after | string | ISO timestamp — показывать события после этого момента |

**Response:**
```json
{
  "success": true,
  "level": 5,
  "total_xp": 1500,
  "celebrations": [
    { "type": "achievement", "title": "Первый квиз", "description": "...", "icon": "🏆", "xp": 50 },
    { "type": "streak_milestone", "title": "Стрик 7 дней!", "description": "+5 монет", "icon": "🔥", "coins": 5 }
  ]
}
```

---

## Curriculum API

### `GET /curriculum/api/levels`
Все CEFR-уровни с прогрессом пользователя.

**Auth:** `@login_required`

**Response:**
```json
{
  "success": true,
  "levels": [
    { "code": "A1", "name": "Beginner", "modules_count": 10, "completed": 3, "progress_pct": 30 }
  ]
}
```

### `GET /curriculum/api/level/<level_code>/modules`
Модули уровня с прогрессом.

### `GET /curriculum/api/module/<module_id>/lessons`
Уроки модуля с доступом и прогрессом.

### `GET /curriculum/api/lesson/<lesson_id>/info`
Детали урока с прогрессом.

### `GET /curriculum/api/user/progress`
Общий прогресс пользователя по программе.

**Response:**
```json
{
  "success": true,
  "progress": { "total": 100, "started": 45, "completed": 30, "percentage": 30.0 },
  "recent_activity": [{ "lesson_id": 5, "title": "...", "completed_at": "..." }]
}
```

### `GET /curriculum/api/lesson/<lesson_id>/card/session`
SRS-сессия для карточек урока.

---

## SRS API

### `GET /curriculum/api/v1/srs/session`
Получение SRS-сессии для урока.

**Auth:** `@login_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| lesson_id | int | ID урока |

**Response:**
```json
{ "deck": [{ "card_id": 1, "front": "...", "back": "...", "state": "new" }], "session_key": "abc123" }
```

### `POST /curriculum/api/v1/srs/grade`
Оценка карточки (шкала 1-2-3 или legacy 0-5).

**Body:**
```json
{ "card_id": 42, "rating": 3, "session_key": "abc123" }
```

**Response:**
```json
{ "success": true, "requeue_position": 5, "new_state": "review" }
```

### `POST /curriculum/api/v1/srs/session/complete`
Завершение SRS-сессии.

**Body:**
```json
{ "session_key": "abc123", "lesson_id": 5, "stats": { "correct": 10, "incorrect": 2 } }
```

### `GET /curriculum/api/v1/srs/due-count`
Количество карточек к повторению.

**Response:**
```json
{ "due_count": 15, "has_due_cards": true }
```

### `GET /curriculum/api/v1/srs/next-session-time`
Время следующей SRS-сессии.

| Параметр | Тип | Описание |
|----------|-----|----------|
| course_id | int | ID курса (опционально) |

**Response:**
```json
{ "next_session_time": "2026-04-10T15:00:00", "has_session_due": true }
```

### `POST /curriculum/api/v1/lesson/<lesson_id>/create-srs-cards`
Создание SRS-карточек для урока.

### `POST /curriculum/api/v1/lesson/<lesson_id>/completed`
Webhook завершения урока (авто-создание SRS-карточек).

### `POST /curriculum/api/srs/add-card`
Добавление слова в SRS-карточки.

**Body:**
```json
{ "word_id": 123, "source": "reading", "course_id": 5 }
```

**Response:**
```json
{ "success": true }
```

---

## Grammar Lab API

### `GET /grammar-lab/api/topics`
Список грамматических тем.

**Auth:** `@login_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| level | string | Фильтр по уровню (A1, A2, B1, B2, C1) |

**Response:**
```json
[{ "id": 1, "title": "Present Simple", "level": "A1", "exercise_count": 20, "progress": { "status": "practicing", "correct": 15 } }]
```

### `GET /grammar-lab/api/levels`
Сводка по уровням грамматики.

**Response:**
```json
[{ "level": "A1", "topic_count": 12, "mastered_count": 5 }]
```

### `GET /grammar-lab/api/topic/<topic_id>`
Детали грамматической темы с контентом и упражнениями.

### `GET /grammar-lab/api/topic/<topic_id>/exercises`
Упражнения темы (ответы скрыты).

**Response:**
```json
[{ "id": 1, "question": "He ___ to school every day.", "options": ["go", "goes", "going"], "type": "mcq" }]
```

### `POST /grammar-lab/api/topic/<topic_id>/start-practice`
Начать практику по теме.

**Response:**
```json
{ "session_id": "abc", "exercises": [{ "id": 1, "question": "..." }] }
```

### `POST /grammar-lab/api/exercise/<exercise_id>/submit`
Отправить ответ на упражнение.

**Body:**
```json
{ "answer": "He goes to school", "session_id": "abc", "source": "practice", "time_spent": 15 }
```

**Response:**
```json
{ "success": true, "is_correct": true, "explanation": "Third person singular requires -es" }
```

### `POST /grammar-lab/api/topic/<topic_id>/complete-theory`
Отметить теорию как изученную.

### `POST /grammar-lab/api/practice/session`
Создание SRS-сессии для грамматики (смешанная практика).

**Body:**
```json
{ "topic_ids": [1, 2, 3], "count": 20, "include_new": true }
```

### `GET /grammar-lab/api/stats`
Статистика грамматики пользователя.

**Response:**
```json
{ "total_topics": 77, "mastered_topics": 5, "new_topics": 40, "due_today": 8 }
```

### `GET /grammar-lab/api/recommendations`
Рекомендованные темы (учитывает onboarding_level).

**Response:**
```json
[{ "id": 5, "title": "Past Simple", "level": "A2", "reason": "new", "reason_text": "Новая тема" }]
```

### `GET /grammar-lab/api/due-topics`
Темы, требующие повторения.

### `GET /grammar-lab/api/srs-stats`
SRS-статистика по грамматике.

| Параметр | Тип | Описание |
|----------|-----|----------|
| topic_id | int | Фильтр по теме |
| level | string | Фильтр по уровню |

**Response:**
```json
{ "new_count": 5, "learning_count": 10, "review_count": 15, "mastered_count": 20, "total": 50, "due_today": 8 }
```

### `GET /grammar-lab/api/topics-srs-stats`
SRS-статистика по всем грамматическим темам (batch).

### `GET /grammar-lab/api/exercise/<exercise_id>/srs-info`
SRS-информация по конкретному упражнению.

**Response:**
```json
{ "state": "review", "interval": 7, "lapses": 0, "is_due": false, "ease_factor": 2.5, "repetitions": 3 }
```

---

## Daily Plan API

### `GET /api/daily-status`
Единый endpoint: план + сводка + стрик в одном запросе.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| tz | string | Часовой пояс (default: Europe/Moscow) |

**Response:**
```json
{
  "success": true,
  "plan": { "next_lesson": {...}, "grammar_topic": {...}, "words_due": 12 },
  "summary": { "lessons_count": 2, "words_reviewed": 15, "books_read": [], "book_course_lessons_today": 0 },
  "streak": { "streak": 7, "coins_balance": 100, "has_activity_today": true, "can_repair": false, "missed_date": null, "repair_cost": null, "required_steps": 1, "steps_total": 4 },
  "yesterday": { "lessons_count": 1 },
  "plan_completion": { "lesson": true, "grammar": false },
  "steps_done": 2,
  "steps_total": 4,
  "required_steps": 1,
  "streak_repaired": false
}
```

### `GET /api/daily-plan`
План обучения на день.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| tz | string | Часовой пояс (default: Europe/Moscow) |

**Response:**
```json
{
  "success": true,
  "next_lesson": { "lesson_id": 5, "module_number": 2, "title": "..." },
  "grammar_topic": { "topic_id": 10, "title": "...", "level": "A1" },
  "words_due": 12,
  "has_any_words": true,
  "book_to_read": { "id": 3, "title": "..." },
  "book_course_lesson": { "lesson_id": 1, "title": "..." }
}
```

### `GET /api/daily-summary`
Сводка учебной активности за сегодня.

**Auth:** `@api_auth_required`

**Response:**
```json
{
  "success": true,
  "lessons_count": 2,
  "lesson_types": ["vocabulary", "grammar"],
  "words_reviewed": 15,
  "srs_words_reviewed": 10,
  "srs_new_reviewed": 3,
  "srs_review_reviewed": 7,
  "grammar_exercises": 3,
  "grammar_correct": 2,
  "books_read": ["Book Title"],
  "book_course_lessons_today": 1,
  "lesson_score": 85,
  "lesson_title": "Lesson 5",
  "grammar_topic_title": "Present Simple",
  "book_chapter_title": "Chapter 3"
}
```

### `GET /api/streak`
Текущая серия обучения.

**Auth:** `@api_auth_required`

**Response:**
```json
{
  "success": true,
  "streak": 7,
  "coins_balance": 22,
  "has_activity_today": true,
  "can_repair": false,
  "missed_date": null,
  "repair_cost": 0
}
```

### `POST /api/streak/repair`
Восстановить стрик за монеты (JWT).

**Auth:** `@api_auth_required`

**Body:**
```json
{ "tz": "Europe/Moscow" }
```

**Response (success):**
```json
{ "success": true, "new_streak": 8 }
```

**Response (error):**
```json
{ "success": false, "error": "insufficient_coins", "cost": 5, "balance": 2 }
```

### `GET /api/daily-plan/next-step`
Следующий невыполненный шаг плана (для dashboard progress bar).

**Auth:** `@login_required`

**Response:**
```json
{
  "has_next": true,
  "step_type": "grammar",
  "step_title": "Grammar Lab — Present Perfect",
  "step_url": "/grammar-lab/topic/10?from=daily_plan",
  "step_icon": "🧠",
  "steps_done": 1,
  "steps_total": 4
}
```

### `POST /api/streak/repair-web` (web)
Восстановить стрик за монеты (session-based, для dashboard).

**Auth:** `@login_required`

**Body:**
```json
{ "tz": "Europe/Moscow" }
```

---

## Anki Export API

### `POST /api/export-anki`
Экспорт слов в Anki-пакет (.apkg).

**Auth:** `@api_auth_required`

**Body:**
```json
{
  "deckName": "English Words",
  "cardFormat": "basic",
  "includePronunciation": true,
  "includeExamples": true,
  "updateStatus": true,
  "wordIds": [1, 2, 3, 4, 5]
}
```

**Response:** Файл `.apkg` для скачивания.

---

## Telegram API

### `POST /telegram/generate-code`
Генерация 6-значного кода привязки.

**Auth:** `@login_required`

**Response:**
```json
{ "success": true, "code": "123456", "expires_in_minutes": 5 }
```

### `POST /telegram/unlink`
Отвязка Telegram-аккаунта.

**Auth:** `@login_required`

**Response:**
```json
{ "success": true }
```

### `GET /telegram/status`
Статус привязки Telegram.

**Auth:** `@login_required`

**Response:**
```json
{ "linked": true, "username": "john_doe", "linked_at": "2026-01-15T10:30:00" }
```

### `POST /telegram/webhook`
Получение обновлений от Telegram Bot API. CSRF exempt. Требует секретный токен в URL.

### Команды бота

Бот обрабатывает следующие команды (через webhook, не HTTP API):

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие + инструкция привязки |
| `/link XXXXXX` | Привязка аккаунта по 6-значному коду |
| `/unlink` | Отвязка аккаунта |
| `/plan` | План обучения на сегодня с чеклистом |
| `/stats` | Статистика: стрик, уроки, слова, книги, рефералы |
| `/invite` | Генерация реферальной ссылки для приглашения друзей |
| `/settings` | Настройки уведомлений и часовой пояс |
| `/help` | Справка по командам |

Бот также отправляет автоматические уведомления:
- Утреннее напоминание с планом на день
- Вечерняя сводка результатов
- Напоминание при пропуске занятий
- Предупреждение о потере стрика
- Недельный отчёт с приглашением `/invite`
- Слово дня

---

## Notifications API

### `GET /api/notifications/list`
Список недавних уведомлений.

**Auth:** `@login_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| limit | int | Максимум записей (default: 20, max: 50) |

**Response:**
```json
{
  "success": true,
  "notifications": [
    { "id": 1, "type": "achievement", "title": "Новое достижение: Первый квиз", "message": "", "link": "/study/stats", "icon": "🏆", "read": false, "created_at": "2026-04-10T12:00:00" }
  ],
  "unread_count": 3
}
```

### `POST /api/notifications/<notif_id>/read`
Отметить уведомление как прочитанное.

**Auth:** `@login_required`

**Response:**
```json
{ "success": true }
```

### `POST /api/notifications/read-all`
Отметить все уведомления как прочитанные.

**Auth:** `@login_required`

**Response:**
```json
{ "success": true }
```

### `GET /api/notifications/unread-count`
Количество непрочитанных уведомлений (для badge).

**Auth:** `@login_required`

**Response:**
```json
{ "success": true, "count": 3 }
```

---

## System API

### `GET /csrf-token`
Получение CSRF-токена для длительных сессий (квизы, карточки).

**Auth:** `@login_required`

**Response:**
```json
{ "csrf_token": "ImE2MzQ4..." }
```

---

## SEO & Public Pages

Публичные страницы, не требующие авторизации. Возвращают HTML (не JSON).

### `GET /sitemap.xml`
XML-карта сайта. Включает: курсы, грамматику, словарь (топ-500 слов), grammar level pages.

**Response:** `application/xml`

### `GET /robots.txt`
Файл robots.txt с ссылкой на sitemap.

**Response:** `text/plain`

### `GET /dictionary/<word_slug>`
Публичная страница слова с переводом, примерами, аудио, OG-тегами и JSON-LD (`DefinedTerm`).

### `GET /courses/`
Каталог курсов по уровням CEFR с количеством модулей и уроков.

### `GET /courses/<level_code>`
Детали уровня: список модулей с примерами уроков.

### `GET /u/<username>`
Публичный профиль: уровень, XP, стрик, достижения.

### `GET /streak/<username>`
Публичная страница стрика с календарём активности (90 дней).

---

## Типы авторизации

| Метод | Описание | Где используется |
|-------|----------|-----------------|
| `@api_auth_required` | Unified: JWT Bearer first, session cookie fallback | Все API endpoints (Words, Books, Anki, Topics/Collections, Daily Plan, Streak) |
| `@login_required` | Flask-Login с редиректом на логин | Study, Curriculum, Grammar Lab, Telegram, Notifications |
| `@csrf.exempt` | Без CSRF-проверки | JWT login/refresh, Telegram webhook |
| Public | Без авторизации | /sitemap.xml, /robots.txt, /dictionary/*, /courses/*, /u/*, /streak/* |

**Unified auth model:** все `/api/*` endpoints используют единый декоратор `@api_auth_required`, который принимает и JWT Bearer токены (для мобильных/внешних клиентов) и session cookies (для browser-AJAX). JWT проверяется первым; если заголовок `Authorization` отсутствует, используется Flask-Login session.

**Telegram-бот** работает внутри Flask app context и вызывает Python-функции напрямую (не через HTTP API). JWT endpoints не используются ботом.

**Для внешних клиентов** (сторонний бот, мобильное приложение) используется JWT:

```
# 1. Авторизация
POST /api/login
Body: {"username": "...", "password": "..."}
→ {"access_token": "eyJ...", "refresh_token": "eyJ..."}

# 2. Запросы с токеном
GET /api/daily-status?tz=Europe/Moscow
Headers: Authorization: Bearer <access_token>

# 3. Обновление токена (когда access_token истёк — 15 мин)
POST /api/refresh
Headers: Authorization: Bearer <refresh_token>
→ {"access_token": "eyJ..."}
```

**JWT endpoints для бота:**

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/api/daily-status` | GET | Единый: план + сводка + стрик |
| `/api/daily-plan` | GET | План на день: уроки, грамматика, слова, книги |
| `/api/daily-summary` | GET | Сводка за сегодня: что выполнено |
| `/api/streak` | GET | Стрик + монеты + возможность ремонта |
| `/api/streak/repair` | POST | Восстановить стрик за монеты |

Все принимают `?tz=Europe/Moscow` (часовой пояс). `access_token` живёт 15 минут, `refresh_token` — 30 дней.

---

## Обработка ошибок

Все API-ошибки возвращаются в формате:

```json
{ "success": false, "error": "Описание ошибки" }
```

| Код | Описание |
|-----|----------|
| 200 | OK |
| 400 | Bad Request — неверный формат запроса |
| 401 | Unauthorized — требуется авторизация |
| 403 | Forbidden — недостаточно прав (JSON для API, HTML для браузера) |
| 404 | Not Found — ресурс не найден (JSON для API, HTML для браузера) |
| 500 | Internal Server Error (JSON для API, HTML для браузера) |
