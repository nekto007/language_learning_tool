# API Documentation

Language Learning Tool — полный каталог API-эндпоинтов. 70+ endpoints, JSON responses.

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

### `GET /csrf-token`
Получение CSRF-токена для длительных сессий.

**Auth:** `@login_required`

**Response:**
```json
{ "csrf_token": "..." }
```

---

## Words API

### `GET /api/words`
Список слов с фильтрами и пагинацией.

**Auth:** `@api_login_required`

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

**Auth:** `@api_login_required`

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

**Auth:** `@api_login_required`

**Body:**
```json
{ "word_id": 1, "status": 3 }
```

### `POST /api/batch-update-status`
Массовое обновление статусов.

**Auth:** `@api_login_required`

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

**Auth:** `@api_login_required`

**Body:**
```json
{ "status": 2, "deck_id": 5 }
```

### `POST /api/user-words-status`
Получение статусов для списка слов.

**Auth:** `@api_login_required`

**Body:**
```json
{ "word_ids": [1, 2, 3] }
```

**Response:**
```json
{ "success": true, "words": [{ "word_id": 1, "status": 2 }, ...] }
```

### `GET /api/search`
Быстрый поиск слов.

**Auth:** `@api_login_required`

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

**Auth:** `@api_login_required`

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

**Auth:** `@api_login_required`

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

**Auth:** `@api_login_required`

### `GET /api/books/<book_id>/chapters`
Список глав книги по ID. Кешируется 1 час.

**Auth:** `@api_login_required`

### `GET /api/books/<book_id>/chapters/<chapter_num>`
Контент главы. Поддерживает gzip-сжатие.

**Auth:** `@api_login_required`

### `PATCH /api/progress`
Обновление прогресса чтения.

**Auth:** `@api_login_required`

**Body:**
```json
{ "book_id": 1, "chapter_id": 5, "offset_pct": 0.75 }
```

### `GET /api/books/<book_id>/progress`
Прогресс чтения пользователя.

**Auth:** `@api_login_required`

**Response:**
```json
{ "current_chapter": 5, "offset_pct": 0.75, "chapters_read": [1, 2, 3, 4] }
```

### `GET /api/word-translation/<word>`
Перевод слова с аудио (для ридера).

**Auth:** `@api_login_required`

**Response:**
```json
{ "word": "example", "translation": "пример", "has_audio": true, "audio_url": "/audio/example.mp3", "is_form": false }
```

### `GET /api/book/<book_id>/content`
Контент книги для чтения с подсветкой словаря.

**Auth:** `@api_login_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| start_position | int | Начальная позиция |
| end_position | int | Конечная позиция |

### `GET /api/tasks/<task_id>`
Получение задания по ID.

### `GET /api/blocks/<block_id>/tasks`
Все задания блока.

### `GET /api/blocks/<block_id>`
Информация о блоке с типами заданий.

### `GET /api/chapters/<chapter_id>`
Получение главы по ID.

---

## Topics & Collections API

### `GET /api/topics`
Список тем с пагинацией.

**Auth:** `@api_login_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| search | string | Поиск |
| page | int | Страница |
| per_page | int | Элементов на странице |

### `GET /api/topics/<topic_id>`
Детали темы со словами и связанными коллекциями.

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
Получение карточек для SRS-сессии (приоритетная очередь).

**Auth:** `@login_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| source | string | `auto` или `deck` |
| deck_id | int | ID колоды |
| extra_study | bool | Доп. изучение |
| exclude_card_ids | string | Исключить карточки |

**Response:**
```json
{
  "status": "ok",
  "items": [{ "word_id": 1, "direction": "eng-rus", "state": "new", ... }],
  "stats": { "new_count": 10, "learning_count": 5, "review_count": 15 }
}
```

### `POST /study/api/update-study-item`
Оценка карточки (Anki state machine).

**Auth:** `@login_required`

**Body:**
```json
{
  "word_id": 1,
  "direction": "eng-rus",
  "quality": 3,
  "session_id": "abc123",
  "deck_id": 5
}
```

**Response:**
```json
{
  "success": true,
  "card_id": 42,
  "interval": 1,
  "next_review": "2026-03-21T10:00:00",
  "requeue_position": 5,
  "requeue_minutes": 1
}
```

### `POST /study/api/complete-session`
Завершение сессии изучения.

**Body:**
```json
{ "session_id": "abc123" }
```

**Response:**
```json
{ "success": true, "stats": {...}, "xp_earned": 25, "total_xp": 1500, "level": 5 }
```

### `GET /study/api/get-quiz-questions`
Вопросы для квиза.

| Параметр | Тип | Описание |
|----------|-----|----------|
| count | int | Количество вопросов |
| deck_id | int | ID колоды |

### `POST /study/api/submit-quiz-answer`
Отправка ответа на вопрос квиза.

### `POST /study/api/complete-quiz`
Завершение квиза.

### `GET /study/api/get-matching-words`
Слова для игры "Matching".

### `POST /study/api/complete-matching-game`
Завершение игры "Matching".

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
Модули уровня.

### `GET /curriculum/api/module/<module_id>/lessons`
Уроки модуля.

### `GET /curriculum/api/lesson/<lesson_id>/info`
Детали урока.

### `GET /curriculum/api/user/progress`
Общий прогресс пользователя по программе.

**Response:**
```json
{
  "success": true,
  "progress": { "total": 100, "started": 45, "completed": 30, "percentage": 30.0 },
  "recent_activity": [...]
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

---

## Grammar Lab API

### `GET /grammar_lab/api/topics`
Список грамматических тем.

**Auth:** `@login_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| level | string | Фильтр по уровню (A1, A2, ...) |

### `GET /grammar_lab/api/levels`
Сводка по уровням грамматики.

### `GET /grammar_lab/api/topic/<topic_id>`
Детали грамматической темы.

### `GET /grammar_lab/api/topic/<topic_id>/exercises`
Упражнения темы (ответы скрыты).

### `POST /grammar_lab/api/topic/<topic_id>/start-practice`
Начать практику по теме.

### `POST /grammar_lab/api/exercise/<exercise_id>/submit`
Отправить ответ на упражнение.

**Body:**
```json
{ "answer": "He goes to school", "session_id": "abc", "source": "practice", "time_spent": 15 }
```

**Response:**
```json
{ "success": true, "is_correct": true, "explanation": "..." }
```

### `POST /grammar_lab/api/topic/<topic_id>/complete-theory`
Отметить теорию как изученную.

### `POST /grammar_lab/api/practice/session`
Создание SRS-сессии для грамматики.

**Body:**
```json
{ "topic_ids": [1, 2, 3], "count": 20, "include_new": true }
```

### `GET /grammar_lab/api/stats`
Статистика грамматики пользователя.

### `GET /grammar_lab/api/recommendations`
Рекомендованные темы.

### `GET /grammar_lab/api/due-topics`
Темы, требующие повторения.

### `GET /grammar_lab/api/srs-stats`
SRS-статистика по грамматике.

| Параметр | Тип | Описание |
|----------|-----|----------|
| topic_id | int | Фильтр по теме |
| level | string | Фильтр по уровню |

**Response:**
```json
{ "new_count": 5, "learning_count": 10, "review_count": 15, "mastered_count": 20, "total": 50, "due_today": 8 }
```

### `GET /grammar_lab/api/topics-srs-stats`
SRS-статистика по всем грамматическим темам.

### `GET /grammar_lab/api/exercise/<exercise_id>/srs-info`
SRS-информация по конкретному упражнению.

---

## Daily Plan API

### `GET /api/daily-plan`
План обучения на день: следующий урок, грамматика, слова на повторение, книги, онбординг.

**Auth:** `@api_login_required`

**Query params:**
- `tz` (str) — часовой пояс пользователя, напр. `Europe/Moscow` (по умолчанию)

**Response:**
```json
{
  "success": true,
  "next_lesson": {"lesson_id": 5, "module_id": 2, "title": "..."},
  "grammar_topic": {"id": 10, "name": "...", "level": "A1"},
  "words_due": 12,
  "has_any_words": true,
  "book_to_read": {"book_id": 3, "title": "...", "chapter": 5},
  "suggested_books": [],
  "book_course_lesson": {"lesson_id": 1, "title": "..."},
  "book_course_done_today": false,
  "onboarding": null,
  "bonus": []
}
```

### `GET /api/daily-summary`
Сводка учебной активности за сегодня.

**Auth:** `@api_login_required`

**Query params:**
- `tz` (str) — часовой пояс пользователя (по умолчанию `Europe/Moscow`)

**Response:**
```json
{
  "success": true,
  "lessons_completed": 2,
  "lesson_types": ["vocabulary", "grammar"],
  "words_reviewed": 15,
  "new_words_learned": 5,
  "grammar_exercises": 3,
  "chapters_read": 1,
  "streak": 7,
  "book_course_lessons": 1
}
```

### `GET /api/streak`
Текущая серия обучения пользователя.

**Auth:** `@api_login_required`

**Query params:**
- `tz` (str) — часовой пояс пользователя (по умолчанию `Europe/Moscow`)

**Response:**
```json
{
  "success": true,
  "streak": 7,
  "has_activity_today": true
}
```

---

## Anki Export API

### `POST /api/export-anki`
Экспорт слов в Anki-пакет (.apkg).

**Auth:** `@api_login_required`

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

### `GET /telegram/status`
Статус привязки Telegram.

**Auth:** `@login_required`

**Response:**
```json
{ "linked": true, "username": "john_doe", "linked_at": "2026-01-15T10:30:00" }
```

### `POST /telegram/webhook`
Получение обновлений от Telegram. CSRF exempt.

---

## Типы авторизации

| Метод | Описание | Где используется |
|-------|----------|-----------------|
| `@api_login_required` | Flask-Login через cookie/session | Words, Books, Anki, Topics/Collections API |
| `@login_required` | Flask-Login с редиректом на логин | Study, Curriculum, Grammar Lab, Telegram |
| `@csrf.exempt` | Без CSRF-проверки | JWT login/refresh, Telegram webhook |
| JWT Bearer token | `Authorization: Bearer <token>` | `/api/login` → access_token |

**Для Telegram-бота** рекомендуется использовать JWT-авторизацию:
1. `POST /api/login` → получить `access_token`
2. Передавать `Authorization: Bearer <access_token>` в заголовках
3. Обновлять через `POST /api/refresh`

---

## Обработка ошибок

Все ошибки возвращаются в формате:

```json
{
  "success": false,
  "error": "Описание ошибки",
  "status_code": 400
}
```

| Код | Описание |
|-----|----------|
| 200 | OK |
| 400 | Bad Request — неверный формат запроса |
| 401 | Unauthorized — требуется авторизация |
| 403 | Forbidden — недостаточно прав |
| 404 | Not Found — ресурс не найден |
| 500 | Internal Server Error |
