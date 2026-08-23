# API Documentation

Language Learning Tool — каталог HTTP-эндпоинтов приложения. ~150 маршрутов вне `/admin` содержат `/api` в пути; ниже описаны все они плюс системные и публичные страницы.

**Скоуп.** Документируются JSON-эндпоинты (плюс несколько file/HTML-ответов, которые потребляет фронтенд). Админка (`/admin/**`, ещё ~198 маршрутов) и HTML-страницы кабинета (`/study/*`, `/learn/*`, `/books/*`, `/curriculum/lesson/*`) сюда не входят — они рендерят шаблоны, а не контракт.

**Соглашения.**
- Все ответы — `application/json`, если не указано иное.
- Ошибки, собранные через `api_error()` (`app/api/errors.py`), имеют вид `{"success": false, "error": "<code>", "message": "<текст>", "status": <int>}`. Часть старых обработчиков отдаёт `{"success": false, "error": "<текст>"}` — это отмечено по месту.
- `tz` в Daily Plan API валидируется через `ZoneInfo`; невалидное значение молча заменяется на `DEFAULT_TIMEZONE` (env `DEFAULT_TIMEZONE`, дефолт `Europe/Moscow`). Дедуп XP/стриков всё равно считается по `User.timezone`, а не по клиентскому `tz`.

## Содержание

- [Аутентификация](#аутентификация)
- [Words API](#words-api)
- [Books API](#books-api)
- [Topics & Collections API](#topics--collections-api)
- [Study / Flashcards API](#study--flashcards-api)
- [Curriculum API](#curriculum-api)
- [SRS API](#srs-api)
- [Book Courses API](#book-courses-api)
- [Grammar Lab API](#grammar-lab-api)
- [Daily Plan API](#daily-plan-api)
- [Modules API](#modules-api)
- [Onboarding API](#onboarding-api)
- [Anki Export API](#anki-export-api)
- [Telegram API](#telegram-api)
- [Notifications API](#notifications-api)
- [Feedback API](#feedback-api)
- [System API](#system-api)
- [SEO & Public Pages](#seo--public-pages)
- [Типы авторизации](#типы-авторизации)
- [Обработка ошибок](#обработка-ошибок)

---

## Аутентификация

### `POST /api/login`
Авторизация внешнего клиента. Возвращает JWT-пару. CSRF exempt.

**Rate limit:** 15/мин на username + 60/час на IP.

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
  "expires_in": 900,
  "user": { "id": 1, "username": "user123", "is_admin": false }
}
```

**Errors:** `400 invalid_json` / `400 missing_fields`, `401 invalid_credentials`, `403 account_inactive`.

### `POST /api/refresh`
Обновление access-токена. CSRF exempt.

**Headers:** `Authorization: Bearer <refresh_token>`

**Response:**
```json
{ "success": true, "access_token": "eyJ...", "expires_in": 900 }
```

**Errors:** `401 token_refresh_failed`.

`access_token` живёт 15 минут, `refresh_token` — 30 дней.

---

## Words API

### `GET /api/words`
Список слов с фильтрами и пагинацией.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| status | int | Числовой статус (0 new / 1 learning / 2 review / 3 mastered) |
| book_id | int | Фильтр по книге |
| topic_id | int | Фильтр по теме |
| collection_id | int | Фильтр по коллекции |
| letter | string | Первая буква |
| search | string | Поиск по english/russian |
| page | int | Страница (default: 1) |
| per_page | int | На странице (default: 50, max: 200) |

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
      "sentences": "This is an example.<br>Это пример."
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
Обновление статуса одного слова. CSRF обязателен.

**Auth:** `@api_auth_required`

**Body:**
```json
{ "word_id": 1, "status": 3 }
```

**Response:** возвращается **фактически сохранённый** статус (он выводится из состояний карточек, а не из присланного значения).
```json
{ "success": true, "status": "mastered" }
```

**Errors:** `400 invalid_json`, `400 missing_fields`, `404 not_found`, `500 server_error`.

### `POST /api/batch-update-status`
Массовое обновление статусов (+ опционально добавление в колоду).

**Auth:** `@api_auth_required`

**Body:** `status` — строка (`new` | `learning` | `review` | `mastered`).
```json
{ "word_ids": [1, 2, 3], "status": "learning", "deck_id": 5 }
```

**Response:**
```json
{ "success": true, "updated_count": 3, "total_count": 3, "deck_added_count": 3 }
```
`deck_added_count` присутствует только когда передан `deck_id`.

**Errors:** `400 invalid_json` / `400 missing_fields` / `400 invalid_status`, `404 not_found` (часть id не существует), `500 db_error`.

### `POST /api/words/<word_id>/status`
Обновление статуса одного слова (используется шаблонами).

**Auth:** `@api_auth_required`

**Body:**
```json
{ "status": "learning", "deck_id": 5 }
```

**Response:**
```json
{ "success": true, "status": "learning", "deck_added": true }
```
`deck_added` / `deck_message` присутствуют только при переданном `deck_id` (`deck_message` — текст ошибки добавления в колоду; статус слова при этом уже обновлён).

### `POST /api/user-words-status`
Статусы для списка слов.

**Auth:** `@api_auth_required`

**Body:**
```json
{ "word_ids": [1, 2, 3] }
```

**Response:** статусы — строки (`new` для слов без `UserWord`).
```json
{ "success": true, "words": [{ "word_id": 1, "status": "learning" }] }
```

### `GET /api/search`
Быстрый поиск слов (минимум 2 символа, до 50 результатов).

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

Все маршруты, отдающие содержимое книги, проходят через гейт прав (`can_user_access_book`, аудит `SEC-001`):
- `404 not_found` — книги нет; черновик (`is_published=false`) для не-админа; блок/задача не резолвится в книгу;
- `403 forbidden` — `licensed`/`companion_only` без модуля `books` либо с истёкшим `expiration_date`.

### `GET /api/books`
Список доступных книг (черновики видит только админ).

**Auth:** `@api_auth_required`

**Response:**
```json
{
  "books": [
    { "id": 1, "title": "Sample Book", "words_total": 1500, "unique_words": 350, "created_at": "2023-01-15T14:30:45" }
  ]
}
```

### `GET /api/books/<book_id>`
Детали книги со статистикой слов пользователя.

**Auth:** `@api_auth_required`

**Response:**
```json
{
  "id": 1,
  "title": "Sample Book",
  "words_total": 1500,
  "unique_words": 350,
  "created_at": "2023-01-15T14:30:45",
  "word_stats": { "new": 120, "learning": 180, "review": 25, "mastered": 15 }
}
```

### `GET /api/books/<slug>/chapters`
Главы книги по slug. Данные кешируются на 1 час (кешируется payload, не ответ роута — проверки доступа выполняются всегда).

**Auth:** `@api_auth_required`

**Response:**
```json
[{ "id": 1, "num": 1, "title": "Chapter One", "words": 1200, "audio_url": "/audio/ch1.mp3" }]
```

### `GET /api/books/<book_id>/chapters`
То же по числовому ID.

**Auth:** `@api_auth_required`

### `GET /api/books/<book_id>/chapters/<chapter_num>`
Контент главы. Поддерживает gzip (`Accept-Encoding: gzip` → бинарный ответ с `Content-Encoding: gzip`).

**Auth:** `@api_auth_required`

**Response:**
```json
{ "id": 5, "num": 3, "title": "Chapter Three", "text": "...", "next": 4, "prev": 2 }
```

### `PATCH /api/progress`
Сохранение прогресса чтения главы (основной save-путь десктопного ридера). Offset монотонно растёт (`max`), поэтому скролл вверх не откатывает прогресс.

**Auth:** `@api_auth_required`

**Body:**
```json
{ "book_id": 1, "chapter_id": 5, "offset_pct": 0.75 }
```

**Response:** поля блока «глава дочитана» появляются только при пересечении `CHAPTER_COMPLETION_THRESHOLD` (0.99).
```json
{
  "success": true,
  "chapter_id": 5,
  "offset_pct": 0.99,
  "reading_slot_completed": true,
  "chapter_completed": true,
  "xp_earned": 15,
  "book_completed": false,
  "completed_chapters": 4,
  "total_chapters": 12
}
```

**Errors:** `400 no_data` / `400 missing_fields` / `400 invalid_value` / `400 chapter_book_mismatch`, `404 not_found`, `403 forbidden`, `500 server_error`.

### `GET /api/books/<book_id>/progress`
Прогресс чтения пользователя по книге.

**Auth:** `@api_auth_required`

**Response:** `chapters_read` — список записей прогресса, не список номеров.
```json
{
  "current_chapter": 5,
  "offset_pct": 0.75,
  "chapters_read": [{ "chapter_num": 5, "offset_pct": 0.75, "updated_at": "2026-08-01T10:00:00" }]
}
```

### `GET /api/word-translation/<word>`
Перевод слова с определением формы (для ридера): неправильные глаголы, `-ing`/`-ed`/множественное число.

**Auth:** `@api_auth_required`

**Response:**
```json
{
  "word": "running",
  "translation": "бег",
  "in_dictionary": true,
  "id": 42,
  "status": "learning",
  "has_audio": true,
  "audio_url": "/static/audio/run.mp3",
  "is_form": true,
  "form_text": "длительная форма от",
  "base_form": "run",
  "in_reading_deck": false
}
```
Если слово не найдено: `{ "word": "...", "translation": null, "in_dictionary": false }`.

### `GET /books/api/word-translation/<word>`
Расширенный вариант того же лукапа для оптимизированного ридера (морфология через pymorphy2/лемматизацию).

**Auth:** `@login_required`

### `GET /api/book/<book_id>/content`
Контент книги для reading-assignment.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| start_position | int | Начальная позиция (default: 0) |
| end_position | int | Конечная позиция |

**Response:**
```json
{
  "success": true,
  "content": { "book_id": 1, "title": "...", "start_position": 0, "end_position": null,
               "content_html": "...", "vocabulary_highlights": [], "interactive_elements": [] }
}
```
NB: тело контента пока заглушечное — реален только гейт доступа и метаданные.

### `GET /api/tasks/<task_id>`
Задание по ID. Гейт: задача через блок ИЛИ через `daily_lesson.chapter.book`; задача без обоих → 404 (fail closed).

**Auth:** `@api_auth_required`

**Response:**
```json
{ "success": true, "task": { "id": 1, "block_id": 2, "task_type": "fill_gap", "payload": {}, "created_at": "..." } }
```

### `GET /api/blocks/<block_id>`
Информация о блоке с типами заданий.

**Auth:** `@api_auth_required`

**Response:**
```json
{ "success": true, "block": { "id": 2, "block_num": 1, "grammar_key": "present_simple",
                              "focus_vocab": [], "task_types": ["fill_gap"], "created_at": "..." } }
```

### `GET /api/blocks/<block_id>/tasks`
Все задания блока.

**Auth:** `@api_auth_required`

**Response:**
```json
{ "success": true, "block_id": 2, "tasks": [{ "id": 1, "task_type": "fill_gap", "created_at": "..." }] }
```

### `GET /api/chapters/<chapter_id>`
Глава по ID (сырой текст + аудио).

**Auth:** `@api_auth_required`

**Response:**
```json
{ "success": true, "chapter": { "id": 5, "num": 3, "title": "...", "text_raw": "...",
                                "audio_url": null, "words": 1500, "book_id": 1 } }
```

### `GET /api/books/catalog`
Каталог книг для слота чтения: уровень пользователя ±1, только опубликованные и доступные, уже прочитанные исключены.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| level | string | Переопределить уровень пользователя (A1…C1) |

**Response:**
```json
{
  "user_level": "B1",
  "books": [{ "id": 3, "title": "...", "author": "...", "level": "B1", "summary": "...",
              "cover_image": "...", "chapters_cnt": 12, "words_total": 41000 }]
}
```

### `POST /api/books/select`
Зафиксировать книгу для слота чтения (`UserReadingPreference`) и получить обновлённый слот.

**Auth:** `@api_auth_required`

**Body:**
```json
{ "book_id": 3 }
```

**Response:**
```json
{ "success": true, "slot": { "kind": "reading", "title": "...", "completed": false, "...": "..." } }
```

**Errors:** `400 invalid_book_id`, `404 book_not_found`, `403 book_access_denied`, `409 book_already_completed`, `500 server_error`.

### `POST /api/books/reading-session/start`
Открыть сессию чтения (вызывается при входе главы во вьюпорт).

**Auth:** `@login_required`

**Body:**
```json
{ "chapter_id": 12 }
```

**Response:**
```json
{
  "success": true,
  "session_id": 991,
  "book_seconds_today": 180,
  "today_target_seconds": 300,
  "study_date": "2026-08-13"
}
```
Побочный эффект: если дневная норма чтения уже набрана, а XP-событие не записалось (потерянный `sendBeacon` при закрытии вкладки), слот докредитовывается здесь.

**Errors:** `400 missing_chapter_id` / `400 invalid_chapter_id`, `404 not_found`, `403 forbidden`.

### `POST /api/books/reading-session/end`
Закрыть сессию чтения. CSRF exempt (приходит через `navigator.sendBeacon` с `text/plain`; тело парсится как JSON в обоих случаях), владелец сессии проверяется на сервере.

**Auth:** `@login_required`

**Body:**
```json
{ "session_id": 991, "current_offset_pct": 0.62 }
```

**Response:**
```json
{
  "success": true,
  "session_id": 991,
  "duration_seconds": 312,
  "reading_slot_completed": true,
  "daily_target_met": true,
  "chapter_completed_in_session": false,
  "book_completed": false,
  "banner_state": "daily_target",
  "next_slot_url": "/study?from=linear_plan&slot=srs",
  "next_slot_title": "Повторение слов",
  "dashboard_url": "/dashboard",
  "queued_vocab_count": 7,
  "completed_chapters": 4,
  "total_chapters": 12
}
```
`banner_state` ∈ `none` | `daily_target` | `chapter_completed` | `both`. `completed_chapters`/`total_chapters` — только когда глава закрылась в этой сессии.

**Errors:** `400 missing_session_id` / `400 invalid_session_id` / `400 invalid_offset_delta`, `404 not_found`, `403 forbidden`.

### `POST /api/save-reading-position`
Сохранение позиции чтения из мобильного ридера (+ XP за главу).

**Auth:** `@login_required`

**Body:**
```json
{ "book_id": 1, "chapter": 3, "position": 0.99 }
```

**Response:**
```json
{
  "success": true,
  "chapter_completed": true,
  "xp_earned": 15,
  "total_xp": 1500,
  "level": 5,
  "book_completed": false,
  "completed_chapters": 4,
  "total_chapters": 12
}
```

**Errors:** `400`/`404`/`403` в формате `{"success": false, "message": "..."}`.

### `POST /api/translate`
Перевод слова для оптимизированного ридера (с лемматизацией).

**Auth:** `@login_required`

**Body:** `{ "word": "running" }`

**Response:**
```json
{ "success": true, "translation": "бежать", "word": "running", "word_id": 42, "sentences": "..." }
```
Если перевода нет — `translation: "Перевод не найден"`, `word_id: null`.

### `POST /api/add-to-learning`
Добавить слово из словаря в изучение и в колоду «Слова из чтения».

**Auth:** `@login_required`

**Body:** `{ "word_id": 42 }`

**Response:** `{ "success": true, "message": "Word added to learning queue", "new_status": 1 }` — либо `{"success": true, "message": "Word added to reading deck", "status": <current>}` / `"Word is already in your list"`.

### `POST /api/add-word-to-learning`
То же, но по тексту слова (ридер не знает id).

**Auth:** `@login_required`

**Body:** `{ "word": "marlin" }`

**Response:** `{ "success": true, "message": "Word \"marlin\" added to learning list" }`

### `GET /api/bookmarks/<book_id>`
Закладки пользователя в книге.

**Auth:** `@login_required`

**Response:**
```json
[{ "id": 1, "name": "Начало главы 3", "position": 12045, "context": "...", "created_at": "..." }]
```

### `POST /api/bookmarks`
Создать закладку.

**Auth:** `@login_required`

**Body:**
```json
{ "book_id": 1, "name": "Начало главы 3", "position": 12045, "context": "..." }
```

**Response:** `{ "success": true, "id": 17 }`

### `GET /audio/<book_id>/chapter/<chapter_num>`
Аудио главы (`audio/mpeg`) с поддержкой Range-запросов (`206 Partial Content`).

**Auth:** `@login_required` + гейт книги + отдельный гейт аудио-прав (`audio_rights_status='none'` → 404 для не-админа).

### `GET /api/test`
Health-пинг ридер-API.

**Auth:** `@login_required`

**Response:** `{ "status": "ok", "message": "API is working" }`

---

## Topics & Collections API

### `GET /api/topics`
Список тем с пагинацией.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| search | string | Поиск |
| page | int | Страница (default: 1) |
| per_page | int | На странице (default: 50, max: 200) |

**Response:**
```json
{
  "topics": [{ "id": 1, "name": "Food", "description": "...", "word_count": 25, "words_in_study": 7 }],
  "total": 10, "page": 1, "per_page": 50, "total_pages": 1
}
```

### `GET /api/topics/<topic_id>`
Детали темы со словами и связанными коллекциями.

**Auth:** `@api_auth_required`

**Response:**
```json
{ "id": 1, "name": "Food", "description": "...", "word_count": 25,
  "words": [], "related_collections": [], "creator": { "id": 1, "username": "admin" } }
```

### `GET /api/topics/<topic_id>/words`
Слова темы с пагинацией.

**Auth:** `@api_auth_required`

**Response:**
```json
{ "topic_id": 1, "topic_name": "Food", "words": [], "total": 25, "page": 1, "per_page": 50, "total_pages": 1 }
```

### `POST /api/topics/<topic_id>/add-to-study`
Добавить все слова темы в изучение + колоду по умолчанию. CSRF обязателен.

**Auth:** `@api_auth_required`

**Response:**
```json
{ "success": true, "topic_id": 1, "topic_name": "Food", "added_count": 15, "total_count": 20 }
```

### `GET /api/collections`
Список коллекций.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| search | string | Поиск |
| topic_id | int | Фильтр по теме |
| page | int | Страница |
| per_page | int | На странице (default: 50, max: 200) |

### `GET /api/collections/<collection_id>`
Детали коллекции со словами и темами.

**Auth:** `@api_auth_required`

**Response:**
```json
{ "id": 2, "name": "A1 Vocabulary", "description": "...", "created_by": 1, "created_at": "...",
  "creator": { "id": 1, "username": "admin" }, "word_count": 50, "words": [], "topics": [] }
```

### `GET /api/collections/<collection_id>/words`
Слова коллекции с пагинацией.

**Auth:** `@api_auth_required`

### `POST /api/collections/<collection_id>/add-to-study`
Добавить все слова коллекции в изучение + колоду по умолчанию.

**Auth:** `@api_auth_required`

**Response:**
```json
{ "success": true, "collection_id": 2, "collection_name": "A1 Vocabulary", "added_count": 30, "total_count": 50 }
```

### `GET /api/words/<word_id>/topics`
Темы, содержащие слово.

**Auth:** `@api_auth_required`

**Response:** `{ "word_id": 1, "english_word": "example", "topics": [{ "id": 1, "name": "Food", "description": "..." }] }`

### `GET /api/words/<word_id>/collections`
Коллекции, содержащие слово.

**Auth:** `@api_auth_required`

---

## Study / Flashcards API

Все эндпоинты — `@login_required` (browser-AJAX, CSRF включён).

### `GET /study/api/get-study-items`
Карточки для SRS-сессии (приоритет: relearning → learning → review → new).

| Параметр | Тип | Описание |
|----------|-----|----------|
| source | string | `auto`, `deck`, `daily_plan_mix`, `word_detail`, `custom_list`, `linear_plan` |
| deck_id | int | ID колоды |
| word_id | int | Обязателен при `source=word_detail` |
| list_id | int | ID кастомного списка при `source=custom_list` |
| extra_study | bool | Доп. изучение сверх лимита |
| exclude_card_ids | string | Список id через запятую (anti-repeat) |
| from / slot | string | `linear_plan` / `srs` — маркеры слота плана дня |

**Response:**
```json
{
  "status": "success",
  "stats": {
    "new_cards_today": 4, "reviews_today": 12,
    "new_cards_limit": 10, "reviews_limit": 60,
    "has_more_new": true, "has_more_reviews": false,
    "leech_suspended_count": 2
  },
  "items": [
    { "id": 501, "word_id": 1, "direction": "eng-rus", "word": "example", "translation": "пример",
      "examples": "...", "audio_url": "/static/audio/example.mp3",
      "is_new": false, "state": "review", "step_index": 0, "lapses": 0 }
  ]
}
```
У новых карточек `id: null`.

**Errors:** `404 deck_not_found`, `400 invalid_input`.

### `POST /study/api/update-study-item`
Оценка карточки (SM-2 через `UserCardDirection.update_after_review`).

**Rate limit:** 120/мин на пользователя.

**Body:**
```json
{ "word_id": 1, "direction": "eng-rus", "quality": 3, "session_id": 42, "deck_id": 5,
  "lesson_mode": false, "extra_study": false }
```

**Response:**
```json
{
  "success": true,
  "card_id": 501,
  "interval": 1,
  "next_review": "2026-08-14 00:00",
  "requeue_position": 5,
  "requeue_minutes": 1,
  "session_attempts": 1,
  "state": "learning",
  "step_index": 1,
  "lapses": 0,
  "difficulty_score": 0,
  "is_recovery": false,
  "recovery_successes": 0,
  "recovery_target": 2,
  "is_buried": false,
  "resting_until": null
}
```
`resting_until` (локальная дата) заполняется только для многодневного отдыха карточки; четырёхчасовой session-bury наружу не отдаётся.

**Errors:** `415` (не JSON), `400` (нет `word_id` / битый `quality`), исключённое из SRS слово → `{"success": false, ...}`.

### `POST /study/api/complete-session`
Завершение сессии карточек. Начисляет XP (идемпотентно по факту первого завершения).

**Body:** `{ "session_id": 42 }`

**Response:**
```json
{
  "success": true,
  "stats": { "duration": 300, "words_studied": 20, "correct": 18, "incorrect": 2, "percentage": 90.0 },
  "xp_earned": 25, "total_xp": 1500, "level": 5, "streak": 7
}
```
Невалидная сессия → `{"success": false, "message": "Invalid session"}` со статусом 200.

### `POST /study/api/card-association`
Сохранить личную ассоциацию (подсказку) для одного направления карточки.

**Body:** `{ "word_id": 1, "direction": "eng-rus", "note": "как в «exemplar»" }` (note ≤ 500 символов, пустая строка очищает)

**Response:** `{ "success": true, "note": "как в «exemplar»" }`

**Errors:** `400 invalid_input`, `404 not_found`.

### `POST /study/api/exclude-word`
Исключить слово из всех SRS-очередей (история сохраняется).

**Body:** `{ "word_id": 1 }` → **Response:** `{ "success": true, "word_id": 1 }`

### `POST /study/api/include-word`
Вернуть слово в SRS.

**Body:** `{ "word_id": 1 }` → **Response:** `{ "success": true, "word_id": 1, "status": "learning" }`

### `POST /study/api/difficult-words/complete`
Завершение контекстной проработки: снять leech-бан с угаданных слов (до 100 id за вызов).

**Body:** `{ "correct_word_ids": [1, 2, 3] }`

**Response:** `{ "success": true, "unburied": 3 }`

**Errors:** `400 invalid_input`, `500 internal_error`.

### `POST /study/api/custom-lists/<list_id>/words`
Добавить слово в кастомный список (идемпотентно). Используется AJAX'ом словарного урока.

**Body:** `{ "word": "marlin", "translation": "марлин" }`

**Response:** `{ "ok": true, "entry_id": 12, "word": "marlin", "translation": "марлин", "already_existed": false }`

**Errors:** `403 forbidden` (чужой список), `400 invalid_input`, `404` (списка нет).

### `GET /study/api/get-quiz-questions`
Вопросы для квиза.

| Параметр | Тип | Описание |
|----------|-----|----------|
| source | string | `auto` или `linear_plan_deck_quiz` |
| count | int | Количество (default: 20, max: 200; для слота плана — свой лимит) |
| deck_id | int | ID колоды |

**Response:**
```json
{
  "status": "success",
  "questions": [
    { "id": "mc_1_eng_to_rus", "word_id": 1, "type": "multiple_choice", "text": "example",
      "question_label": "Переведите на русский:", "options": ["пример", "..."],
      "answer": "пример", "hint": "Начинается с: п... (6 букв)",
      "audio_url": null, "direction": "eng_to_rus" }
  ]
}
```
Типы вопросов: `multiple_choice`, `fill_blank`. Нет слов → `{"status": "error", "message": "No words available for quiz", "questions": []}`.

### `POST /study/api/submit-quiz-answer`
Зафиксировать ответ: обновляет счётчики сессии и продвигает SM-2 состояние карточки.

**Body:**
```json
{ "session_id": 42, "is_correct": true, "word_id": 1, "direction": "eng-rus" }
```

**Response:** `{ "success": true, "srs_graded": true }` (`srs_graded=false`, если карточки нет, слово исключено или исчерпан бюджет новых).

### `POST /study/api/complete-quiz`
Завершение квиза: результат, XP, ачивки.

**Body:**
```json
{ "session_id": 42, "deck_id": 5, "total_questions": 10, "correct_answers": 8,
  "time_taken": 120, "has_streak": false, "source": "linear_plan_deck_quiz", "from": "linear_plan", "slot": "srs" }
```

**Response:**
```json
{ "success": true, "score": 80.0, "xp_earned": 20, "xp_breakdown": { "...": 0 },
  "total_xp": 1520, "level": 5, "achievements": [] }
```

### `GET /study/api/get-matching-words`
Слова для игры «Matching».

| Параметр | Тип | Описание |
|----------|-----|----------|
| count | int | Количество слов (default: 10, max: 20) |

**Response:**
```json
{ "status": "success", "words": [{ "id": 1, "word": "cat", "translation": "кошка",
                                   "example": "...", "audio_url": null }] }
```

### `POST /study/api/complete-matching-game`
Завершение игры «Matching». XP идемпотентен по `(session_id, game_type)`.

**Body:**
```json
{ "session_id": 42, "difficulty": "easy", "pairs_matched": 7, "total_pairs": 8,
  "moves": 20, "time_taken": 45, "word_ids": [1, 2] }
```

**Response:**
```json
{ "success": true, "score": 340, "rank": 3, "is_personal_best": true,
  "game_score_id": 88, "xp_earned": 15, "total_xp": 1535, "level": 5 }
```
Античит: несогласованные данные (`pairs_matched > total_pairs`, слишком мало ходов) → `{"success": false, "error": "Invalid game data detected"}` со статусом 200.

### `GET /study/api/leaderboard/<game_type>`
Рейтинг игроков. `game_type` ∈ `quiz` | `matching`.

| Параметр | Тип | Описание |
|----------|-----|----------|
| difficulty | string | Фильтр сложности (matching) |
| limit | int | default: 10, max: 50 |

**Response:**
```json
{
  "status": "success",
  "leaderboard": [{ "rank": 1, "username": "...", "score": 100, "time_taken": 45, "date": "2026-08-01 10:00",
                    "correct_answers": 10, "total_questions": 10 }],
  "user_best": { "rank": 3, "score": 80, "time_taken": 60, "date": "2026-07-30 21:00" }
}
```
Для `matching` вместо quiz-полей отдаются `pairs_matched` / `total_pairs` / `moves`.

### `GET /study/api/search-words`
Поиск слов для добавления в колоду.

| Параметр | Тип | Описание |
|----------|-----|----------|
| q | string | Запрос |
| limit | int | default: 10, max: 50 |

**Response:**
```json
[{ "id": 1, "english": "cat", "russian": "кошка", "sentences": "" }]
```

### `GET /study/api/collections-topics`
Коллекции и темы для добавления в колоду.

**Response:**
```json
{ "collections": [{ "id": 1, "name": "A1 Vocab", "description": "", "word_count": 50 }],
  "topics": [{ "id": 1, "name": "Food", "description": "", "word_count": 25 }] }
```

### `POST /study/api/decks/<deck_id>/add-from-collection`
Добавить слова из коллекции в колоду. **Body:** `{ "collection_id": 5 }`

### `POST /study/api/decks/<deck_id>/add-from-topic`
Добавить слова из темы в колоду. **Body:** `{ "topic_id": 3 }`

### `GET /study/api/my-decks`
Колоды пользователя (авто-колоды скрыты).

**Response:**
```json
{ "success": true, "decks": [{ "id": 1, "name": "Мои слова", "word_count": 100, "is_public": false }],
  "default_deck_id": 1 }
```

### `GET|POST /study/api/default-deck`
Чтение и установка колоды по умолчанию. POST-body: `{ "deck_id": 5 }` (`null` — сбросить).

**Response:** `{ "success": true, "default_deck_id": 5, "default_deck_name": "Мои слова" }`

**Errors:** `404` — колода не найдена/чужая.

### `POST /study/api/decks/create`
Создание колоды (название ≤ 200 символов).

**Body:** `{ "name": "New Deck" }`

**Response:** `{ "success": true, "deck": { "id": 6, "name": "New Deck", "word_count": 0, "is_public": false } }`

### `POST /study/api/decks/<deck_id>/add-word`
Добавление слова в колоду. **Body:** `{ "word_id": 123 }`

### `POST /study/api/add-phrase-to-deck`
Добавление произвольной фразы в колоду по умолчанию.

**Body:** `{ "english": "custom phrase", "russian": "кастомная фраза", "context": "from reading" }`

**Response:** `{ "success": true, "message": "\"custom phrase\" added to your deck" }`
Нет дефолтной колоды → `{"success": false, "error": "no_default_deck"}` со статусом 200.

### `GET /study/api/srs-stats`
SRS-статистика по словам.

| Параметр | Тип | Описание |
|----------|-----|----------|
| deck_id | int | Фильтр по колоде |

**Response:**
```json
{ "new_count": 50, "learning_count": 30, "review_count": 100, "mastered_count": 200, "total": 380, "due_today": 25 }
```

### `GET /study/api/srs-overview`
Сводка по словам и грамматике.

**Response:**
```json
{
  "words": { "new_count": 50, "learning_count": 30, "review_count": 100, "mastered_count": 200, "total": 380, "due_today": 25 },
  "grammar": { "new_count": 5, "learning_count": 10, "review_count": 15, "mastered_count": 20, "total": 50, "due_today": 8 },
  "totals": { "new_count": 55, "learning_count": 40, "review_count": 115, "mastered_count": 220, "total": 430, "due_today": 33 }
}
```

### `GET /study/api/celebrations`
Новые достижения и стрик-майлстоуны для показа поздравлений.

| Параметр | Тип | Описание |
|----------|-----|----------|
| after | string | ISO timestamp; по умолчанию — последние 5 минут |

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

Справочные эндпоинты — `@login_required`; уроковые дополнительно проходят `@require_lesson_access` (гейт prerequisites, `403` для API-клиента).

### `GET /curriculum/api/levels`
Все CEFR-уровни с прогрессом.

**Response:**
```json
{
  "success": true,
  "levels": [{ "id": 1, "code": "A1", "name": "Beginner", "description": "...",
               "total_lessons": 120, "completed_lessons": 36, "progress_percentage": 30 }]
}
```

### `GET /curriculum/api/level/<level_code>/modules`
Модули уровня.

**Response:**
```json
{
  "success": true,
  "level": { "id": 1, "code": "A1", "name": "Beginner" },
  "modules": [{ "id": 5, "number": 2, "title": "...", "description": "...",
                "total_lessons": 12, "completed_lessons": 4, "progress_percentage": 33, "is_accessible": true }]
}
```

### `GET /curriculum/api/module/<module_id>/lessons`
Уроки модуля с доступом и прогрессом.

**Response:**
```json
{
  "success": true,
  "module": { "id": 5, "number": 2, "title": "...", "level_code": "A1" },
  "lessons": [{ "id": 40, "number": 1, "title": "...", "type": "vocabulary", "description": "...",
                "status": "completed", "score": 90.0, "completed_at": "...", "is_accessible": true }]
}
```

**Errors:** `404` (модуля нет), `403` (нет доступа к модулю).

### `GET /curriculum/api/lesson/<lesson_id>/info`
Детали урока с прогрессом.

**Response:**
```json
{
  "success": true,
  "lesson": { "id": 40, "number": 1, "title": "...", "type": "card", "description": "...",
              "module": { "id": 5, "title": "...", "number": 2 },
              "level": { "code": "A1", "name": "Beginner" } },
  "progress": { "status": "in_progress", "score": null, "started_at": "...", "completed_at": null, "last_activity": "..." },
  "additional_info": { "cards": { "total_due": 12, "new_cards": 4, "review_cards": 8 } }
}
```
`additional_info` присутствует только для `card` (счётчики карточек) и `vocabulary` (`word_count`).

### `GET /curriculum/api/user/progress`
Общий прогресс по программе.

**Response:**
```json
{
  "success": true,
  "progress": { "total_lessons": 900, "started_lessons": 120, "completed_lessons": 96,
                "in_progress_lessons": 24, "completion_percentage": 11, "average_score": 87.4, "current_streak": 7 },
  "recent_activity": [{ "lesson_id": 40, "lesson_title": "...", "lesson_type": "quiz",
                        "module_title": "...", "level_code": "A1", "last_activity": "...",
                        "status": "completed", "score": 90.0 }]
}
```

### `GET /curriculum/api/lesson/<lesson_id>/card/session`
Данные SRS-сессии для карточного урока.

**Response:** `{ "success": true, "session": { "cards": [], "next_review_time": "...", "...": "..." } }`

**Errors:** `400` — урок не типа `card`.

### `POST /curriculum/api/lesson/<lesson_id>/progress`
Обновление прогресса урока. Для server-graded типов `score` и `status='completed'` из тела **игнорируются** (защита от подделки очков) — такие уроки закрываются через `/submit`.

**Body:** `{ "status": "completed", "score": 100, "reading_time": 240 }` (JSON или form-data)

**Response:**
```json
{
  "success": true,
  "progress": { "status": "completed", "score": 100.0, "completed_at": "..." },
  "grade": "A", "grade_name": "Отлично", "new_achievements": [],
  "daily_plan_ctx": { "is_daily_plan": true, "slot_kind": "curriculum",
                      "next_slot_url": "...", "next_slot_title": "...", "next_slot_kind": "srs",
                      "day_secured": false, "dashboard_url": "/dashboard" }
}
```
Блок `grade`/`grade_name`/`new_achievements` появляется только когда сработал `process_lesson_completion`.

### `POST /curriculum/api/lesson/<lesson_id>/submit`
Отправка ответов урока. Единая точка серверной проверки для `quiz`, `grammar`, `matching`, `final_test`, `dictation`, `translation`, `sentence_correction`, `sentence_completion`, `collocation_matching`, `writing_prompt`, `shadow_reading`, `listening_immersion`, `pronunciation`, `idiom`.

**Rate limit:** 30/мин на пользователя. Дополнительно: pronunciation — дневной лимит попыток, writing/translation/sentence_correction — свой дневной лимит.

**Body:**
```json
{ "answers": { "0": 2, "1": "goes" }, "time_spent_seconds": 95 }
```

**Response:** формат зависит от типа урока (`score`, `passed`, `correct_answers`, `total_questions`, `results`…). Дополнительно всегда прикрепляется `daily_plan_ctx`, а при автозачёте дневного челленджа — `challenge_completed` / `challenge_bonus_xp`.

**Errors:**
- `429 rate_limit_exceeded` — дневной лимит попыток (у pronunciation — с `retry_after`);
- `429 attempts_exhausted` — исчерпаны 3 попытки финального теста за 24 часа; тело содержит `passed: false`, `retry_after` (ISO 8601 UTC), `max_attempts`, `window_hours`. В лимит попадают только проваленные попытки (`passed=false`);
- `500 grading_failed` — не удалось сохранить результат финального теста (попытка не записана, квота не тратится);
- `400` — неизвестный тип урока или невалидные данные игры.

### `POST /curriculum/api/lesson/<lesson_id>/check-item`
Поштучная серверная проверка ответа (`sentence_completion`, `audio_fill_blank`, `translation`, `sentence_correction`, `collocation_matching`). Правильный ответ на клиент не уходит, пока не решён или не исчерпаны попытки.

**Rate limit:** 120/мин на пользователя.

**Body:** `{ "index": 0, "answer": "goes", "final": false }`

**Response:** `{ "success": true, "correct": true, "answer": "goes", "explanation": "..." }`
`answer`/`explanation` отдаются только при `correct=true` или `final=true` (для `collocation_matching` give-up-раскрытие отключено).

**Errors:** `400 invalid_lesson_type` / `400 bad_index` / `400 index_out_of_range`.

### `POST /curriculum/api/lesson/<lesson_id>/dictation-word`
Проверка одного пропуска диктанта (3 попытки на слово).

**Body:** `{ "index": 2, "answer": "harbour" }`

**Response:**
```json
{ "success": true, "correct": false, "attempt": 3, "attempts_left": 0, "exhausted": true, "correct_word": "harbour" }
```
`correct_word` возвращается только когда попытки исчерпаны.

### `POST /curriculum/api/lesson/<lesson_id>/card/review`
Оценка карточки внутри урока (валидация через `SRSReviewSchema`).

**Body:** `{ "word_id": 1, "direction": "eng-rus", "quality": 4 }`

**Response:**
```json
{
  "success": true, "interval": 3, "next_review": "2026-08-16T00:00:00",
  "achievements": [], "daily_limit_reached": false,
  "calculated_intervals": { "...": "..." },
  "daily_stats": { "new_cards_today": 4, "new_cards_limit": 10,
                   "lesson_new_cards_studied": 2, "lesson_review_cards_studied": 6 }
}
```
При оценке 0 в ответе дополнительно `failed_attempt: true` и `session_attempts`.

### `POST /curriculum/api/rate-card`
То же действие, но `lesson_id` передаётся в теле (легаси-клиент).

**Body:** `{ "lesson_id": 40, "word_id": 1, "direction": "eng-rus", "rating": 3 }`

### `GET /curriculum/api/lesson/<lesson_id>/next-review-time`
Время следующего повторения для урока.

**Response:** `{ "next_review_time": "через 2 дня" }` (при ошибке — человекочитаемая заглушка, статус 500).

### `POST /curriculum/lessons/<lesson_id>/complete-srs`
Завершение карточной сессии урока. Урок помечается `completed`, только если пройдено ≥ `min_cards_required` карточек (порог ограничивается реальным размером колоды).

**Body:** `{ "cards_studied": 12, "accuracy": 92 }`

**Response:**
```json
{
  "success": true, "cards_studied": 12, "accuracy": 92,
  "stats": { "words_studied": 12, "correct": 11, "incorrect": 1, "percentage": 92 },
  "xp_earned": 20, "total_xp": 1520, "level": 5,
  "daily_plan_ctx": { "...": "..." }
}
```

### `POST /curriculum/api/lessons/<lesson_id>/feedback`
Оценка урока пользователем (`LessonFeedback`).

**Body:** `{ "rating": 5, "comment": "..." }` (rating 1–5, комментарий обрезается до 500 символов)

**Response:** `{ "success": true, "lesson_id": 40, "rating": 5 }`

**Errors:** `400 invalid_rating`, `500 server_error`.

### `POST /curriculum/api/module/<module_id>/test-out`
Сдача экстерном: приём ответов, при успехе — массовое закрытие уроков модуля.

**Body:** `{ "answers": { "0": 1, "1": "goes" } }`

**Response:**
```json
{ "success": true, "score": 88.0, "passed": true, "correct_answers": 22, "total_questions": 25,
  "completed_lessons": 12, "module_url": "/learn/a1/module-2/" }
```

**Errors:** `403 forbidden`, `409 no_active_test` / `409 <причина недоступности>`, `400 invalid_input`, `500 internal_error`.

### `POST /curriculum/api/words/<word_id>/annotation`
Личная заметка к слову (`VocabAnnotation`), HTML вычищается, ≤ 2000 символов.

**Body:** `{ "note": "путать с ‘lend’" }`

**Response:** `{ "ok": true, "word_id": 42, "note": "путать с ‘lend’" }`

**Errors:** `404` (слова нет), `400` (пустая или слишком длинная заметка).

---

## SRS API

Курсовой SRS поверх book-course уроков (`DailyLesson`). Auth — `@login_required`.

### `GET /curriculum/api/v1/srs/session`
Сессия карточек для урока.

| Параметр | Тип | Описание |
|----------|-----|----------|
| lesson_id | int | ID daily lesson (обязателен) |

**Response:** `{ "deck": [{ "card_id": 1, "front": "...", "back": "...", "...": "..." }], "session_key": "abc123" }`

**Errors:** `400` (нет `lesson_id`), `403` (нет enrollment), `404` (нет карточек к повторению), `500`.

### `POST /curriculum/api/v1/srs/grade`
Оценка карточки. Шкала 1–2–3 (`rating`) либо легаси 0–5 (`grade`, маппится 0–1→1, 2–3→2, 4–5→3).

**Body:** `{ "card_id": 42, "rating": 3, "session_key": "abc123" }`

**Response:** результат `unified_srs_service.grade_card` — `success`, `requeue_position`, `requeue_minutes`, `state`, `interval`, `days_until_review` и т.д.

**Errors:** `400` (`card_id` / `rating` отсутствует либо вне 1–3), `500`.

### `POST /curriculum/api/v1/srs/session/complete`
Завершение SRS-сессии.

**Body:** `{ "session_key": "abc123", "lesson_id": 5, "stats": { "correct": 10, "incorrect": 2 } }`

**Response:** `{ "success": true, "message": "SRS session completed successfully" }`

### `GET /curriculum/api/v1/srs/due-count`
**Response:** `{ "due_count": 15, "has_due_cards": true }`

### `GET /curriculum/api/v1/srs/next-session-time`
| Параметр | Тип | Описание |
|----------|-----|----------|
| course_id | int | Опциональный фильтр по курсу |

**Response:** `{ "next_session_time": "2026-08-14T15:00:00", "has_session_due": false }`

### `POST /curriculum/api/v1/lesson/<lesson_id>/create-srs-cards`
Создание карточек для vocabulary-урока курса.

**Response:** `{ "success": true, "message": "SRS cards created successfully" }`

**Errors:** `400` (урок не vocabulary), `403` (нет enrollment), `500`.

### `POST /curriculum/api/v1/lesson/<lesson_id>/completed`
Webhook завершения урока: для vocabulary-уроков создаёт карточки автоматически.

**Response:** `{ "success": true }`

### `GET /curriculum/api/srs/session/<lesson_id>`
Альтернативный вход в ту же сессию (book-course клиент).

### `POST /curriculum/api/srs/grade`
Оценка карточки book-course SRS.

**Body:** `{ "card_id": 42, "grade": 4, "session_key": "abc" }`

**Errors:** `400` (нет `card_id`/`grade`), `500`.

### `POST /curriculum/api/srs/add-card`
Добавление слова в карточки пользователя.

**Body:** `{ "word_id": 123, "source": "book_reading", "course_id": 5 }`

**Response:** `{ "success": true, "...": "..." }`; при неуспехе — тот же объект со статусом 400.

---

## Book Courses API

Курсы, построенные вокруг книги. Auth — `@login_required` + активный enrollment (иначе `404 Not found`).

### `GET /curriculum/api/v1/lesson/<lesson_id>`
Данные daily-урока курса (структура зависит от `lesson_type`: `vocabulary` отдаёт до 10 слов с контекстом, reading — срез главы и т.д.).

### `GET|POST /curriculum/api/v1/lesson/<lesson_id>/progress`
Чтение и сохранение прогресса урока (позиция чтения, ответы самопроверки).

**POST Body:** `{ "reading_progress": 80, "self_check": { "q1": true } }` (`reading_progress` обрезается до 100)

**Response:** GET — сохранённый `lesson_data` (или `{}`); POST — `{ "ok": true }`.

### `POST /curriculum/api/v1/lesson/<lesson_id>/complete`
Завершение урока курса (пишет `UserLessonProgress` + `LessonCompletionEvent`).

### `POST /curriculum/api/book-courses/<course_id>/modules/<module_id>/complete-lesson`
Отметить урок модуля как пройденный.

**Body:** `{ "lesson_number": 3, "score": 100 }`

**Errors:** `400` — не передан `lesson_number`.

### `GET /curriculum/api/book-courses/<course_id>/progress`
Прогресс пользователя по курсу.

**Response:**
```json
{
  "success": true,
  "course_id": 2,
  "progress": {
    "enrollment": { "status": "active", "progress_percentage": 40.0, "total_study_time": 3600,
                    "words_learned": 120, "enrolled_at": "...", "last_activity": "..." },
    "modules": [{ "module_id": 7, "status": "in_progress", "progress_percentage": 50.0,
                  "lessons_completed": [1, 2], "current_lesson": 3, "reading_position": 0.4,
                  "vocabulary_score": 90.0, "comprehension_score": 85.0 }]
  }
}
```

**Errors:** `404 Not enrolled`.

---

## Grammar Lab API

Auth — `@login_required`.

### `GET /grammar-lab/api/topics`
Список тем с прогрессом.

| Параметр | Тип | Описание |
|----------|-----|----------|
| level | string | Фильтр по уровню (A1…C1) |

**Response:** массив тем с полями темы и прогрессом пользователя.

### `POST /grammar-lab/api/topics`
Создание темы. **Только админ** (`403` иначе).

**Body:** `{ "slug": "present-simple", "title": "Present Simple", "title_ru": "...", "level": "A1",
"order": 0, "estimated_time": 15, "difficulty": 1, "content": {} }`

**Response:** `201` с объектом темы.

**Errors:** `403`, `415` (не JSON), `400` (нет `slug`/`title`, нечисловые `order`/`estimated_time`/`difficulty`), `409 slug_taken` (+ `suggestion`).

### `GET /grammar-lab/api/levels`
Сводка по уровням грамматики.

### `GET /grammar-lab/api/topic/<topic_id>`
Детали темы с контентом и упражнениями. `404` — темы нет.

### `GET /grammar-lab/api/topic/<topic_id>/exercises`
Упражнения темы с скрытыми ответами (`to_dict(hide_answer=True)`).

### `POST /grammar-lab/api/topic/<topic_id>/start-practice`
Старт практики по теме.

### `POST /grammar-lab/api/exercise/<exercise_id>/submit`
Отправка ответа. Начисляет XP: раз в день кредитует глобальный `total_xp` (`maybe_award_grammar_review_xp`), плюс per-topic косметический счётчик.

**Body:**
```json
{ "answer": "He goes to school", "session_id": "abc", "source": "topic_practice", "time_spent": 15 }
```

**Response:**
```json
{ "is_correct": true, "explanation": "...", "xp_earned": 10,
  "srs_update": { "...": "..." }, "requeue_position": 3, "requeue_minutes": 10,
  "exercise_state": "learning", "exercise_interval": 0 }
```

**Errors:** `400` (нет `answer`), `404` (упражнения нет).

### `POST /grammar-lab/api/topic/<topic_id>/complete-theory`
Отметить теорию изученной.

**Response:** `{ "status": { "...": "..." }, "xp_earned": 5 }`

### `POST /grammar-lab/api/practice/session`
Смешанная SRS-сессия по грамматике.

**Body:** `{ "topic_ids": [1, 2, 3], "count": 10, "include_new": true }`

### `GET /grammar-lab/api/stats`
Статистика пользователя по грамматике.

### `GET /grammar-lab/api/recommendations`
Рекомендованные темы. Параметр `limit` (default: 5).

### `GET /grammar-lab/api/due-topics`
Темы к повторению. Параметр `limit` (default: 10).

### `GET /grammar-lab/api/srs-stats`
SRS-статистика по упражнениям.

| Параметр | Тип | Описание |
|----------|-----|----------|
| topic_id | int | Фильтр по теме |
| level | string | Фильтр по уровню |

**Response:**
```json
{ "new_count": 5, "learning_count": 10, "review_count": 15, "mastered_count": 20, "total": 50, "due_today": 8 }
```

### `GET /grammar-lab/api/topics-srs-stats`
Те же счётчики сразу по всем темам (batch). Параметр `level`.

### `GET /grammar-lab/api/exercise/<exercise_id>/srs-info`
SRS-состояние конкретного упражнения; для незатронутого — дефолт.

**Response:**
```json
{ "state": "new", "interval": 0, "lapses": 0, "is_due": true, "ease_factor": 2.5, "repetitions": 0 }
```

---

## Daily Plan API

### `GET /api/daily-status`
Единый эндпоинт: план + сводка + стрик + цели за один запрос. Побочные эффекты при закрытом дне: `secured_at`, ранги, ачивки иммерсии, майлстоуны стрика, очки дневной гонки.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| tz | string | Часовой пояс (default: `User.timezone` → `DEFAULT_TIMEZONE`) |

**Response:**
```json
{
  "success": true,
  "plan": { "mode": "unified", "required": [], "optional": [], "setup": [],
            "day_secured": false, "graduated": false, "blocked_module": null,
            "total_estimated_minutes": 22, "plan_intensity": "normal",
            "has_more_optional": true, "position": {}, "progress": {}, "module_progress": {},
            "_plan_meta": { "effective_mode": "unified", "graduated": false, "user_id": 1, "blocked_module_id": null } },
  "summary": { "lessons_count": 2, "words_reviewed": 15, "books_read": [], "book_course_lessons_today": 0 },
  "streak": { "streak": 7, "coins_balance": 100, "has_activity_today": true,
              "can_repair": false, "missed_date": null, "repair_cost": 0 },
  "yesterday": { "lessons_count": 1 },
  "plan_completion": { "curriculum:lesson:40": true, "srs:global": false },
  "steps_done": 2,
  "steps_total": 4,
  "required_steps": 1,
  "streak_repaired": false,
  "day_secured": false,
  "listening_streak_days": 3,
  "writing_streak_days": 0,
  "speaking_streak_days": 1,
  "immersion_streak_days": 0,
  "pronunciation_weak_words": [],
  "minutes_studied_today": 18,
  "streak_shield_active": false,
  "leech_suspended_count": 2,
  "listening_goal_minutes": 10,
  "listening_minutes_today": 5.0,
  "listening_goal_reached": false,
  "goal_progress": {
    "daily_words": { "goal": 10, "actual": 4, "reached": false },
    "weekly_lessons": { "goal": 5, "actual": 3, "reached": false }
  }
}
```
Условные поля: `srs_limit_reason` (когда адаптивный лимит SRS не `normal`), `recovery_suggestion` (`{missed_kind, action_url, missed_date}` — вчера день не закрыт), `plan_paused` + `paused_until` (план на паузе).

### `GET /api/daily-plan`
Только план дня (unified payload) + состояние маршрута.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| tz | string | Часовой пояс |

**Response:** `{ "success": true, "route_state": { ... }, ...plan }`, где `plan` — тот же unified-payload, что в `/api/daily-status` (плюс `srs_limit_reason` при необходимости).

**Элемент плана (`required[]` / `optional[]` / `setup[]`):**
```json
{
  "id": "curriculum:lesson:40",
  "section": "required",
  "kind": "curriculum",
  "title": "Урок 1 · Артикли",
  "subtitle": "Модуль 2",
  "lesson_type": "vocabulary",
  "eta_minutes": 7,
  "url": "/learn/40/?from=linear_plan&slot=curriculum",
  "completed": false,
  "completion_signal": "lesson_progress",
  "data": { "lesson_id": 40, "slot_skip_allowed": true, "slot_skips_remaining": 1 }
}
```
`kind` ∈ `curriculum`, `srs`, `reading`, `listening`, `speaking`, `writing`, `error_review`, `grammar_review`, `challenge`. Режим `paused` отдаёт короткий payload: `{ "mode": "paused", "paused_until": "...", "day_secured": <до паузы>, "_plan_meta": {...} }`.

### `GET /api/daily-summary`
Сводка учебной активности за сегодня.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| tz | string | Часовой пояс |

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
{ "success": true, "streak": 7, "coins_balance": 22, "has_activity_today": true,
  "can_repair": false, "missed_date": null, "repair_cost": 0 }
```

### `POST /api/streak/repair`
Восстановить стрик за монеты. CSRF exempt (JWT-клиент).

**Auth:** `@api_auth_required`

**Body:** `{ "tz": "Europe/Moscow" }`

**Response:** `{ "success": true, "new_streak": 8 }`
**Errors:** `400 no_missed_date`; при нехватке монет — `{"success": false, "error": "insufficient_coins", "cost": 5, "balance": 2}`.

### `POST /api/streak/repair-web`
То же для дашборда (session-auth).

**Auth:** `@login_required`

**Body:** `{ "tz": "Europe/Moscow" }`

**Errors:** `400 {"success": false, "error": "no_missed_date"}`.

### `GET /api/daily-plan/next-step`
Первый невыполненный шаг плана (потребитель — прогресс-бар дашборда).

**Auth:** `@login_required`

**Response:**
```json
{ "has_next": true, "step_type": "grammar_review", "step_title": "Повторение грамматики",
  "step_url": "/grammar-lab/practice?from=linear_plan", "step_icon": "🧠",
  "steps_done": 1, "steps_total": 4 }
```
Всё выполнено → `{ "has_next": false, "all_done": true, "steps_done": …, "steps_total": …, "fallback_url": "/dashboard", "continue_study_url": "/study?source=free_practice" }`. Для graduated-пользователя всегда возвращается шаг `free_study` (`/study?source=infinite_practice`).

### `GET /api/daily-plan/next-slot`
Следующий слот плана относительно текущего — используется экраном завершения урока/сессии.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| current | string | Текущий слот (`curriculum`, `srs`, `reading`, …) |
| lesson_id | int | Уточняет активный урок для curriculum-слота |

**Response:**
```json
{
  "success": true,
  "is_daily_plan": true,
  "slot_kind": "curriculum",
  "next_slot_url": "/study?from=linear_plan&slot=srs",
  "next_slot_title": "Повторение слов",
  "next_slot_kind": "srs",
  "day_secured": false,
  "dashboard_url": "/dashboard",
  "next": { "kind": "srs", "url": "/study?from=linear_plan&slot=srs", "title": "Повторение слов" }
}
```
Вложенный `next` — легаси-обёртка над плоскими `next_slot_*`. При внутренней ошибке отдаёт `200 {"success": false, "day_secured": false, "next": null}`.

### `GET /api/daily-plan/continuation`
До 3 рекомендаций «что дальше» после закрытия дня (эвристики приоритета: урок > SRS > слабая грамматика > чтение > словарь).

**Auth:** `@api_auth_required`

**Response:**
```json
{
  "success": true,
  "steps": [{ "kind": "srs", "reason": "due_cards", "data": {}, "estimated_minutes": 5 }],
  "step": { "kind": "srs", "reason": "due_cards", "data": {}, "estimated_minutes": 5 }
}
```

### `POST /api/daily-plan/events`
Поведенческие события клиента. CSRF exempt.

**Auth:** `@api_auth_required`

**Body:**
```json
{ "event_type": "slot_skipped", "step_kind": "reading", "reason_text": "no_time", "plan_date": "2026-08-13" }
```

| Поле | Описание |
|------|----------|
| event_type | `next_step_shown`, `next_step_accepted`, `next_step_dismissed`, `session_ended_at_minimum`, `rival_strip_shown`, `rival_strip_dismissed`, `steps_taken_while_rival_visible`, `vocab_lookup`, `slot_skipped` |
| step_kind | Для `slot_skipped` обязателен: `curriculum`, `srs`, `reading`, `listening`, `writing`, `error_review`, `speaking` |
| reason_text | Для `slot_skipped` обязателен: `no_time`, `too_hard`, `not_today` |
| plan_date | ISO-дата; вне окна «сегодня − 2 дня» заменяется на сегодня |

**Response:** `{ "success": true, "event_type": "slot_skipped" }`

**Errors:** `400 invalid_content_type` / `400 invalid_event_type` / `400 invalid_slot_kind` / `400 invalid_reason` / `400 not_current_slot`, `403 plan_paused` (для событий, меняющих состояние), `429 skip_quota_exhausted` (квота 1 слот-скип в день, гарантируется частичным unique-индексом), `500 db_error`.

### `POST /api/daily-plan/skip-lesson`
Отложить текущий curriculum-урок на завтра (`LessonSkip`, квота 1/день). CSRF exempt.

**Auth:** `@api_auth_required`

**Body:** `{ "lesson_id": 40 }`

**Response:** `{ "success": true, "next_lesson_id": 41 }` (`null`, если подходящего урока не осталось)

**Errors:** `400 invalid_content_type` / `400 invalid_input` / `400 invalid_lesson` / `400 already_deferred`, `429 skip_quota_exhausted`, `500 db_error`.

### `GET /api/error-review/summary`
Разбор нерешённых ошибок по урокам и грамматическим темам.

**Auth:** `@api_auth_required`

**Response:**
```json
{ "unresolved_count": 12, "last_resolved_at": "2026-08-11T20:15:00", "by_lesson": [], "by_topic": [] }
```

### `POST /api/daily-plan/error-review/complete`
Завершение сессии разбора ошибок. CSRF exempt. XP идемпотентен по дню.

**Auth:** `@api_auth_required`

**Body:** `{ "error_ids": [11, 12] }` (чужие/несуществующие id молча пропускаются)

**Response:**
```json
{
  "success": true,
  "resolved_count": 2,
  "xp": { "awarded": 10, "total": 1510, "level": 5, "leveled_up": false },
  "perfect_day_bonus": { "awarded": 25, "total": 1535, "level": 5, "leveled_up": false }
}
```
Блоки `xp` / `perfect_day_bonus` появляются только когда начисление действительно произошло.

**Errors:** `400 invalid_error_ids`, `500 db_error`.

### `POST /api/daily-plan/phrase-review/complete`
Проверка ежедневной необязательной активности «три фразы». Элементы берутся из серверной сессии. CSRF exempt.

**Auth:** `@api_auth_required`

**Body:** `{ "answers": ["...", "...", "..."] }`

**Response:**
```json
{ "success": true, "correct_count": 2, "total": 3,
  "results": [{ "id": 1, "correct": true, "answer": "at the moment" }] }
```

**Errors:** `400 phrase_review_expired` (сессия не открыта/просрочена), `400 invalid_answers`, `500 db_error`.

### `POST /api/daily-plan/challenge/complete`
Завершение дневного челленджа. CSRF exempt. Идемпотентно (`already_completed`); бонусный XP начисляется атомарно с записью о завершении.

**Auth:** `@api_auth_required`

**Body:** `{ "challenge_id": 7, "score": 95, "time_spent_seconds": 180 }`

**Response:** результат `complete_challenge` (`success`, `bonus_xp`, `already_completed`, …).

**Errors:** `400 invalid_input` (нет id, чужой/не сегодняшний челлендж, некорректные `score`/`time_spent_seconds`), `403 criteria_not_met`, `404 not_found`, `500 challenge_error` / `500 db_error`.

### `GET /api/daily-race`
Дневная гонка: зачисление в когорту при первом заходе, пересчёт очков, отсортированные результаты с ghost-участниками.

**Auth:** `@api_auth_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| tz | string | Часовой пояс (дата когорты всё равно берётся из `User.timezone`) |

**Response:** `{ "success": true, "race": { "participants": [], "...": "..." } }`

**Errors:** `403 feature_disabled` (флаг `daily_race_enabled` выключен), `403 age_restricted` (< 18 по `birth_year`), `404 not_found`.

### `POST /api/plan/pause`
Пауза плана на 1–14 дней. CSRF exempt. Пишет `StreakEvent(plan_pause)` на каждый день — эти дни нейтральны для стрика.

**Auth:** `@api_auth_required`

**Body:** `{ "days": 3 }`

**Response:** `{ "status": "ok", "paused_until": "2026-08-16" }`

**Errors:** `400 invalid_days`, `404 not_found`, `500 db_error`.

### `POST /api/plan/resume`
Снять паузу немедленно (удаляет будущие `plan_pause`-события). CSRF exempt.

**Auth:** `@api_auth_required`

**Response:** `{ "status": "ok" }`

---

## Modules API

Пользовательские фича-модули (`words`, `books`, …). Auth — `@login_required`.

### `GET /api/modules/user`
Включённые модули пользователя. **Response:** `{ "success": true, "modules": [ { … } ] }`

### `GET /api/modules/all`
Все активные модули системы.

### `GET /api/modules/enabled-codes`
Только коды включённых модулей. **Response:** `{ "success": true, "codes": ["words", "books"] }`

### `POST /api/modules/<module_id>/toggle`
Переключить модуль для текущего пользователя.

**Response:** `{ "success": true, "enabled": true }` / `500 {"success": false, "error": "Не удалось переключить модуль"}`

---

## Onboarding API

Auth — `@login_required`.

### `POST /onboarding/placement/start`
Старт адаптивного placement-теста (лесенка по уровням, состояние — в серверной сессии).

**Response:**
```json
{ "success": true, "question": { "id": 12, "question": "He ___ to school.", "options": ["go", "goes"] },
  "number": 1, "max": 8 }
```

**Errors:** `409 no_content` — нет пула упражнений.

### `POST /onboarding/placement/answer`
Ответ на текущий вопрос; в ответе либо следующий вопрос, либо рекомендация уровня.

**Body:** `{ "exercise_id": 12, "answer": "goes" }` (`answer` — строка ≤ 200 символов)

**Response:**
```json
{ "success": true, "correct": true, "done": false,
  "question": { "id": 18, "question": "...", "options": ["..."] }, "number": 2, "max": 8 }
```
По завершении: `{ "success": true, "correct": …, "done": true, "recommended_level": "B1" }`.

**Errors:** `400 invalid_input`, `409 no_active_test` (нет активного теста или `exercise_id` не совпадает с последним выданным).

### `POST /onboarding/complete`
Сохранение выбора мастера (`level`, `focus`) и завершение онбординга. Принимает **form-data**, отвечает редиректом (не JSON). `next` санитизируется через `get_safe_redirect_url`.

---

## Anki Export API

### `POST /api/export-anki`
Экспорт слов в Anki-пакет (`.apkg`). CSRF обязателен.

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

**Response:** файл `.apkg` (`application/octet-stream`, attachment). При `updateStatus: true` статусы экспортированных слов переводятся в «активные».

**Errors:** `400 invalid_json` / `400 missing_fields`, `404 not_found`, `500 export_failed`.

---

## Telegram API

### `POST /telegram/generate-code`
Генерация 6-значного кода привязки.

**Auth:** `@login_required` · **Rate limit:** 3/мин

**Response:** `{ "success": true, "code": "123456", "expires_in_minutes": 5 }`
Уже привязан → `400 {"success": false, "error": "Telegram уже привязан"}`.

### `POST /telegram/unlink`
Отвязка аккаунта.

**Auth:** `@login_required`

**Response:** `{ "success": true }` / `400 {"success": false, "error": "Telegram не привязан"}`

### `GET /telegram/status`
Статус привязки.

**Auth:** `@login_required`

**Response:** `{ "linked": true, "username": "john_doe", "linked_at": "2026-01-15T10:30:00" }` либо `{ "linked": false }`

### `POST /telegram/webhook`
Приём обновлений Telegram Bot API. CSRF exempt, без пользовательской авторизации.

Секрет проверяется по заголовку `X-Telegram-Bot-Api-Secret-Token` (сравнение через `hmac.compare_digest`). Fail-closed: не сконфигурирован `TELEGRAM_WEBHOOK_SECRET` → `500`; неверный/отсутствующий токен → `403`; пустое тело → `400`. Дубликаты по `update_id` (окно 1000 апдейтов, per-worker) отбрасываются с `200`. Тело ответа всегда пустое.

### Команды бота

Обрабатываются внутри webhook, HTTP API не задействуется.

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие + инструкция привязки |
| `/link XXXXXX` | Привязка аккаунта по 6-значному коду |
| `/unlink` | Отвязка аккаунта |
| `/plan` | План обучения на сегодня с чеклистом |
| `/stats` | Статистика: стрик, уроки, слова, книги, рефералы |
| `/invite` | Реферальная ссылка |
| `/settings` | Настройки уведомлений и часовой пояс |
| `/help` | Справка по командам |

Автоматические рассылки (утренний план, вечерняя сводка, напоминание о пропуске, предупреждение о стрике, недельный отчёт, слово дня) идут из выделенного процесса `scheduler` и защищены от дублей через `TelegramNotificationLog.claim(user_id, kind, local_date)`.

---

## Notifications API

Auth — `@login_required`.

### `GET /api/notifications/list`
Недавние уведомления.

| Параметр | Тип | Описание |
|----------|-----|----------|
| limit | int | default: 20, max: 50 |

**Response:**
```json
{
  "success": true,
  "notifications": [
    { "id": 1, "type": "achievement", "title": "Новое достижение: Первый квиз", "message": "",
      "link": "/study/stats", "icon": "🏆", "read": false, "created_at": "2026-04-10T12:00:00" }
  ],
  "unread_count": 3
}
```

### `POST /api/notifications/<notif_id>/read`
Отметить уведомление прочитанным. **Response:** `{ "success": true }` / `404`.

### `POST /api/notifications/read-all`
Отметить все прочитанными. **Response:** `{ "success": true }`

### `GET /api/notifications/unread-count`
Счётчик для бейджа. **Response:** `{ "success": true, "count": 3 }`

---

## Feedback API

In-app канал обратной связи (баг/идея/вопрос). Виджет в футере авторизованных страниц; админ разбирает очередь на `/admin/feedback`.

Четвёртая категория `survey` **не принимается от клиента** (`POST /api/feedback` отбивает её `400 invalid_category`) — её пишет сервер из ответов на двухнедельный опрос, а в админских списках она ведёт себя как обычная категория.

### `POST /api/feedback`
Создать обращение. Каждая отправка рассылает in-app (и Telegram) уведомление администраторам.

**Auth:** `@login_required` · **Rate limit:** 5/час · **Headers:** `X-CSRFToken`

Принимает `application/json` **или** `multipart/form-data` (со скриншотом).

| Поле | Тип | Описание | Обязательное |
|------|-----|----------|:---:|
| category | string | `bug`, `idea`, `question` | ✓ |
| message | string | Текст, обрезается до 4000 символов | ✓ |
| url | string | URL страницы; пусто → берётся `Referer` (только http/https) | - |
| screenshot | file | PNG/JPEG/WebP ≤ 5 MiB (multipart); валидация magic bytes + Pillow, EXIF вырезается | - |
| viewport_width / viewport_height / screen_width / screen_height | int | Метрики окна | - |
| device_pixel_ratio | float | DPR | - |
| locale / timezone / platform | string | Клиентское окружение | - |
| context | object | Доп. контекст (JS-ошибки, `lesson_id`, `book_id`, …), ≤ 8 KiB | - |
| app_version | string | Версия клиента; сервер подставляет git SHA, если не задана | - |

`user_agent` пишется сервером. `priority` клиентом не управляется: `high` только для бага со скриншотом. `lesson_id`/`book_id`, распознанные из URL сервером, имеют приоритет над клиентскими.

**Response (201):**
```json
{
  "success": true,
  "id": 42,
  "thread_url": "/feedback/42",
  "screenshot_status": "attached",
  "screenshot_message": null,
  "screenshot_reject_reason": null
}
```
`screenshot_status` ∈ `attached` | `skipped` | `rejected` (при `rejected` заполнены `screenshot_message` и `screenshot_reject_reason`).

**Errors:** `400 invalid_category`, `400 empty_message`, `429`, `500 save_failed`.

### `POST /api/feedback/<feedback_id>/reply`
Ответ в своём треде (админ может отвечать здесь же — тогда уведомляется владелец треда).

**Auth:** `@login_required` · **Rate limit:** 20/час

**Body:** `{ "body": "..." }` (JSON или form; обрезается до лимита)

**Response (201):** `{ "success": true, "reply_id": 88, "created_at": "2026-08-13T10:00:00" }`

**Errors:** `404 not_found`, `403 forbidden` (чужой тред), `400 empty_body`, `500 save_failed`.

### `GET /api/feedback/threads`
Последние треды пользователя для поповера FAB.

**Auth:** `@login_required`

| Параметр | Тип | Описание |
|----------|-----|----------|
| limit | int | default: 5, max: 20 |

**Response:**
```json
{
  "success": true,
  "threads": [{ "id": 42, "url": "/feedback/42", "category": "bug", "status": "in_progress",
                "priority": "high", "preview": "…", "last_at": "2026-08-12T18:00:00",
                "last_is_admin": true, "unread": 1 }]
}
```

### `GET /api/feedback/unread-count`
Счётчик непрочитанных ответов для бейджа FAB (считает `Notification(type='feedback', read=False)`).

**Auth:** `@login_required`

**Response:** `{ "success": true, "count": 2 }`

### `POST /api/feedback/survey`
Ответы на двухнедельный опрос. Сохраняются как обычный тред `Feedback` с `category='survey'`, поэтому видны на `/feedback` и в админской очереди.

**Auth:** `@login_required` · **Rate limit:** 5/час · **Headers:** `X-CSRFToken`

**Body:**
```json
{ "works": "Повторения удобные", "annoys": "Много кликов", "missing": "" }
```

| Поле | Тип | Описание |
|------|-----|----------|
| works | string | «Что работает хорошо?», ≤ 1000 символов |
| annoys | string | «Что раздражает или мешает?» |
| missing | string | «Чего не хватает?» |
| url | string | URL страницы отправки |

Хотя бы одно поле должно быть непустым. Право на ответ «занимается» условным `UPDATE` до создания треда, поэтому две вкладки не создадут два опроса. Отправка закрывает опрос для аккаунта навсегда.

**Response (201):** `{ "success": true, "id": 42, "thread_url": "/feedback/42" }`

**Errors:** `400 invalid_input`, `400 empty_survey`, `409 not_eligible` (аккаунт моложе 14 дней, уже отвечал или исчерпал два показа — гейт серверный), `429`, `500 save_failed`.

### `POST /api/feedback/survey/dismiss`
«Не сейчас». Первый отказ прячет приглашение на неделю, второй — навсегда.

**Auth:** `@login_required` · **Rate limit:** 20/час

**Response:** `{ "success": true, "dismiss_count": 1 }`

**Errors:** `409 not_eligible` (тот же серверный гейт — двойной клик не должен сжигать обе попытки), `500 save_failed`.

### `GET /feedback/screenshots/<path>`
Отдача приложенного скриншота. Доступ — только автор обращения или админ; `Cache-Control: private`.

---

## System API

### `GET /csrf-token`
Свежий CSRF-токен для долгоживущих страниц (квизы, карточки).

**Auth:** `@login_required`

**Response:** `{ "csrf_token": "ImE2MzQ4..." }`

### `POST /api/weekly-report/dismiss`
Скрыть недельную карточку-отчёт на дашборде. Состояние живёт в серверной сессии (не в БД), поэтому сбрасывается вместе с ней.

**Auth:** `@login_required`

**Body:** `{ "dismiss_key": "weekly_report_dismissed_2026-W33" }` (ключ приходит в payload виджета; значения с другим префиксом игнорируются)

**Response:** `{ "ok": true }`

### `GET /health`
Health-check для мониторинга. Без авторизации и без CSRF. Пинг БД выполняется в отдельном соединении с `statement_timeout = 3000 ms`.

**Response (200):**
```json
{ "status": "ok", "db": "ok", "version": "1.0.0", "timestamp": "2026-08-13T09:00:00+00:00" }
```
БД недоступна → `503` с `{"status": "error", "db": "error", ...}`.

---

## SEO & Public Pages

Публичные страницы, не требующие авторизации. Возвращают HTML/XML/текст/PNG, не JSON.

| URL | Описание |
|-----|----------|
| `GET /` | Лендинг |
| `GET /sitemap.xml` | XML-карта сайта: курсы и уровни, страницы грамматики, словарь (все публичные слова, до 50 000 URL), буквенные/уровневые индексы, contrast-пары |
| `GET /robots.txt` | robots.txt со ссылкой на sitemap |
| `GET /llms.txt` | Машиночитаемое описание проекта для LLM-краулеров |
| `GET /dictionary` · `/dictionary/letter/<letter>` · `/dictionary/level/<level>` | Публичный словарь (индекс и фильтры). `/dictionary/` — 301 на канонический URL |
| `GET /dictionary/<word_slug>` | Страница слова: перевод, примеры, аудио, OG-теги, JSON-LD `DefinedTerm` |
| `GET /contrast/<a_slug>/<b_slug>` | Страница пары «X vs Y» |
| `GET /courses/` · `/courses/<level_code>` | Каталог курсов по уровням CEFR и детали уровня |
| `GET /u/<username>` | Публичный профиль: уровень, XP, стрик, достижения |
| `GET /u/<username>/certificate/<level_code>` · `.png` | Публичный сертификат уровня и его OG-картинка 1200×630 |
| `GET /streak/<username>` | Публичная страница стрика с календарём активности (90 дней) |
| `GET /og/word/<word_slug>.png` · `/og/grammar/<slug>.png` · `/og/contrast/<a>/<b>.png` | Генерируемые OG-изображения |
| `GET /privacy` | Политика конфиденциальности (`/privacy/` — редирект) |
| `GET /r/o/<token>.gif` · `/r/c/<blob>` | Пиксель открытия и трекинг кликов в письмах-напоминаниях |

---

## Типы авторизации

| Метод | Описание | Где используется |
|-------|----------|-----------------|
| `@api_auth_required` | JWT Bearer → fallback на session cookie | Words, Books (`app/api/books.py`), Topics/Collections, Anki, Daily Plan, Streak, Books catalog |
| `@login_required` | Flask-Login с редиректом на логин | Study, Curriculum, Grammar Lab, Book Courses, Reader API (`app/books/api.py`), Telegram, Notifications, Feedback, Modules, Onboarding |
| `@csrf.exempt` | Без CSRF-проверки | `/api/login`, `/api/refresh`, `/telegram/webhook`, `/health`, POST-эндпоинты Daily Plan (events, skip-lesson, error-review/complete, phrase-review/complete, challenge/complete, plan pause/resume, streak/repair), `/api/books/reading-session/end` |
| `@require_lesson_access` | Гейт prerequisites модуля поверх `@login_required` | Уроковые API curriculum |
| Public | Без авторизации | `/health`, `/sitemap.xml`, `/robots.txt`, `/llms.txt`, `/dictionary/*`, `/courses/*`, `/contrast/*`, `/u/*`, `/streak/*`, `/og/*`, `/privacy` |

**Unified auth model.** `@api_auth_required` принимает и JWT Bearer (мобильные/внешние клиенты), и session cookie (browser-AJAX). Если заголовок `Authorization: Bearer …` есть — проверяется JWT, пользователь загружается и логинится в контекст запроса; иначе используется Flask-Login. Ошибки авторизации возвращают `401 {"success": false, "error": "...", "status_code": 401}`.

**Telegram-бот** работает внутри Flask app context и вызывает Python-функции напрямую, JWT-эндпоинты им не используются.

**Для внешних клиентов** (сторонний бот, мобильное приложение):

```
# 1. Авторизация
POST /api/login
Body: {"username": "...", "password": "..."}
→ {"access_token": "eyJ...", "refresh_token": "eyJ...", "expires_in": 900}

# 2. Запросы с токеном
GET /api/daily-status?tz=Europe/Moscow
Headers: Authorization: Bearer <access_token>

# 3. Обновление токена (access_token живёт 15 минут)
POST /api/refresh
Headers: Authorization: Bearer <refresh_token>
→ {"success": true, "access_token": "eyJ...", "expires_in": 900}
```

**JWT-эндпоинты для бота:**

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/api/daily-status` | GET | Единый: план + сводка + стрик + цели |
| `/api/daily-plan` | GET | План на день (unified payload) |
| `/api/daily-summary` | GET | Сводка за сегодня |
| `/api/streak` | GET | Стрик + монеты + возможность ремонта |
| `/api/streak/repair` | POST | Восстановить стрик за монеты |

Все принимают `?tz=<IANA timezone>`. `access_token` живёт 15 минут, `refresh_token` — 30 дней.

---

## Обработка ошибок

Канонический формат (helper `api_error` в `app/api/errors.py`):

```json
{ "success": false, "error": "invalid_input", "message": "lesson_id must be a positive integer", "status": 400 }
```

Глобальные обработчики (`handle_403/404/500_error` в `app/__init__.py`) отдают JSON клиентам, запрашивающим JSON (`/api/`-путь, XHR, `Accept: application/json`), и HTML — браузеру:

```json
{ "success": false, "error": "not_found", "message": "...", "status": 404 }
```

Часть старых обработчиков (Study games, book-courses, часть Grammar Lab) отвечает упрощённо: `{"success": false, "error": "<текст>"}` или `{"error": "<текст>"}` — это указано в описании конкретных эндпоинтов.

| Код | Описание |
|-----|----------|
| 200 | OK |
| 201 | Created (feedback, survey, reply, создание grammar-темы) |
| 206 | Partial Content (Range-запросы аудио глав) |
| 301 | Redirect (канонизация URL словаря/приватности) |
| 400 | Bad Request — неверный формат или данные запроса |
| 401 | Unauthorized — нет/просрочен токен или сессия |
| 403 | Forbidden — нет прав (модуль, книга, возраст, админ-гейт) |
| 404 | Not Found — ресурс не найден или скрыт (черновик книги) |
| 409 | Conflict — состояние не позволяет действие (опрос закрыт, книга уже прочитана, нет активного теста) |
| 415 | Unsupported Media Type — ожидался `application/json` |
| 416 | Range Not Satisfiable (аудио) |
| 429 | Too Many Requests — rate limit или исчерпанная дневная квота |
| 500 | Internal Server Error |
| 503 | Service Unavailable (`/health` при недоступной БД) |
