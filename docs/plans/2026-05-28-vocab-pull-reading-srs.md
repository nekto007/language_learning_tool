---
# Vocab Pull из чтения + Стоп таймера при выполнении нормы

## Overview

Два независимых улучшения reading-слота:

A) Таймер в `reader_simple.html` перестаёт тикать и замерзает на 5:00 как только `elapsed >= DAILY_TARGET_SECONDS`. Сессия и beacon-close работают без изменений.

B) После первого закрытия сессии, при котором `daily_target_met` переходит с False → True, бэкенд парсит прочитанный участок `chapter.text_raw`, матчит слова с `CollectionWords`, фильтрует уже изученные и добавляет 3 SRS-карточек (eng-rus + rus-eng) на завтра.

## Context

- Files involved:
  - `app/templates/books/reader_simple.html` — inline JS-таймер (lines 1380–1665)
  - `app/books/api.py` — `reading_session_end()` (line 1092)
  - `app/books/reading_session.py` — `is_daily_reading_target_met_today()`
  - `app/books/models.py` — `Chapter.text_raw`, `UserChapterProgress`
  - `app/study/models.py` — `UserWord.get_or_create()`, `UserCardDirection`
  - `app/words/models.py` — `CollectionWords`, `word_book_link`
  - New: `app/books/vocab_pull.py`
- Related patterns:
  - `_get_or_create_card_direction()` in `app/curriculum/services/book_srs_integration.py` — шаблон создания карточки с `source='book_reading'`
  - `_user_local_day_window_utc()` в `reading_session.py` — для tomorrow midnight
  - SRS naive-UTC convention: `next_review` — naive datetime
- Dependencies: none external

## Development Approach

- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- Run `pytest -m smoke` after each task
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Стоп таймера при выполнении дневной нормы

**Files:**
- Modify: `app/templates/books/reader_simple.html`

- [x] В функции `_renderTimer()` (line ~1488) после `bar.classList.toggle('is-target-met', elapsed >= DAILY_TARGET_SECONDS)` добавить: если `elapsed >= DAILY_TARGET_SECONDS` и `displayTickerInterval` запущен — заморозить `activeSecondsToday = DAILY_TARGET_SECONDS`, обнулить `activeTickAnchor = null`, вызвать `_stopDisplayTicker()`
- [x] Убедиться, что `_pause()` и `_resume()` вызванные вручную после заморозки не ломают состояние (resume не должен перезапускать ticker если норма уже выполнена); добавить флаг `targetReached = false` и проверку в `_resume()`
- [x] Написать pytest smoke-тест: `GET /books/<book_id>/chapter/<chap_id>` возвращает 200 (проверяет, что шаблон рендерится без ошибок)
- [x] Запустить `pytest -m smoke` — должны пройти

### Task 2: Vocab pull — утилита извлечения слов

**Files:**
- Create: `app/books/vocab_pull.py`

- [x] Определить `STOP_WORDS: frozenset` — ~80 частотных английских function words (the, a, an, is, are, was, were, be, been, being, have, has, had, do, does, did, will, would, could, should, may, might, shall, can, need, dare, used, ought, to, of, in, on, at, by, for, with, from, into, through, about, after, before, and, or, but, not, if, so, as, when, that, this, these, those, it, its, he, she, they, we, you, i, my, your, his, her, their, our, me, him, us, them, up, out, over, down)
- [x] Определить `def extract_chapter_vocab(chapter_id, start_offset, end_offset, user_id, db_session, count=3) -> list[CollectionWords]`:
  - Загрузить `chapter.text_raw`
  - Вычислить char range по offset: `start_char = int(start_offset * len(text))`, `end_char = int(end_offset * len(text))`
  - `re.findall(r'\b[a-zA-Z]{3,}\b', text_slice.lower())` → deduplicate → filter stop words
  - Batch query: `CollectionWords.query.filter(CollectionWords.english_word.in_(words_set)).all()`
  - Get known word_ids: `{uw.word_id for uw in UserWord.query.filter_by(user_id=user_id).filter(UserWord.word_id.in_([w.id for w in found]))}`
  - Filter unlearned, sort by `frequency_rank ASC` (nulls last), return top `count`
- [x] Определить `def queue_vocab_as_srs(words, user_id, db_session) -> int`:
  - Для каждого слова: `UserWord.get_or_create(user_id, word.id)`
  - Вычислить `tomorrow_naive_utc`: `datetime.combine(today+1, time.min)` в local tz → convert to UTC → `.replace(tzinfo=None)` (naive convention)
  - Для каждого направления `['eng-rus', 'rus-eng']`: создать `UserCardDirection` только если не существует, установить `source='book_reading'`, `next_review=tomorrow_naive_utc`, flush only
  - Вернуть количество новых карточек
- [x] Написать unit-тесты в `tests/books/test_vocab_pull.py`: extract вернул правильные слова, stop words фильтруются, слова уже в UserWord пропускаются, `next_review >= tomorrow`
- [x] Запустить `pytest tests/books/test_vocab_pull.py` — должны пройти

### Task 3: Интеграция vocab pull в reading_session_end

**Files:**
- Modify: `app/books/api.py`

- [x] В `reading_session_end()` перед вызовом `end_session()` сохранить `was_target_met = is_daily_reading_target_met_today(current_user.id, chapter.book_id, db)` (запрос только по closed sessions — safe)
- [x] После вычисления `state` и `daily_target_met_today` добавить: если `not was_target_met and daily_target_met_today` — вызвать `extract_chapter_vocab()` используя `state['earliest_start_offset']` и `state['current_offset']`, затем `queue_vocab_as_srs()`, сохранить `queued_vocab_count`; ошибки обёртываем в `try/except` (best-effort, не блокируем response)
- [x] Добавить `queued_vocab_count` в response dict (0 если не запускался или ошибка)
- [x] Запустить `pytest -m smoke` — должны пройти

### Task 4: Verify acceptance criteria

- [x] Запустить полный тест-сьют: `pytest`
- [x] Проверить импорты: `python -c "from app.books.vocab_pull import extract_chapter_vocab, queue_vocab_as_srs"`
- [x] Убедиться: coverage на `vocab_pull.py` ≥ 80%

### Task 5: Обновить документацию

- [ ] Добавить паттерн `vocab_pull` в CLAUDE.md (раздел Key Patterns): `extract_chapter_vocab` + `queue_vocab_as_srs` в `app/books/vocab_pull.py`, source='book_reading', fired on `daily_target_met` transition
