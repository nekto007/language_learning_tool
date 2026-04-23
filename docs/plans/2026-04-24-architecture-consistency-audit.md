# 9 Tasks: Architecture Consistency — SRS Counting, Budget, State & API

## Overview

В результате архитектурного аудита выявлены системные расхождения: одни и те же вещи считаются по-разному в разных точках кодбейза. Центральная группа проблем — SRS-счётчики: mission-plan и linear-plan используют разные функции подсчёта due-карточек, дают разные числа и показывают разные цифры на дашборде и в начале сессии. Параллельно: бюджет новых слов считается в двух алгоритмически разных вариантах, `compute_day_secured` делается в двух несовместимых смыслах под одним именем, API study-роутов возвращает ошибки в формате, несовместимом с остальными API. Всё это исправляется без новых фичей — только унификация и удаление дублирования.

## Context

- **Ключевые файлы:**
  - `app/daily_plan/assembler.py` — mission-plan, `_count_srs_due()`, `_get_remaining_card_budget()`
  - `app/daily_plan/linear/slots/srs_slot.py` — linear-plan, `count_srs_due_cards()`, `get_srs_budget_remaining()`
  - `app/study/api_routes.py` — `/api/get-study-items`, inline budget math, error format
  - `app/daily_plan/service.py` — `compute_day_secured()`, `write_secured_at()`
  - `app/api/daily_plan.py` — `daily_status()`, inline day_secured recompute
  - `app/api/errors.py` — `api_error()` — стандартный формат ошибок
  - `app/study/services/srs_service.py` — `SRSService.update_card_after_review()` (мёртвый код), `get_adaptive_limits()`
  - `app/study/models.py` — `UserCardDirection.update_after_review()` (Anki state machine, используется везде)
- **Паттерны:** `api_error(code, message, status)` в `app/api/errors.py`, `_safe_widget_call()`, `UserCardDirection.state` ∈ `{new, learning, relearning, review}`
- **Dependencies:** нет внешних; всё в Flask/SQLAlchemy/PostgreSQL стеке

## Current State

### Проблемы, подтверждённые аудитом

**P1. Mission-plan не считает карточки в состоянии `learning`**
- `assembler.py:_count_srs_due()` фильтрует `state.in_(('review', 'relearning'))` — пропускает `learning`
- `srs_slot.py:count_srs_due_cards()` включает все три: `LEARNING, RELEARNING, REVIEW`
- Итог: дашборд (mission) занижает число due-карточек, сессия /study даёт другую цифру

**P2. Mission-plan считает due только в daily_plan mix**
- `_count_srs_due()` фильтрует `UserWord.word_id.in_(mix_word_ids)` — только слова текущего микса
- /study подаёт ВСЕ due-карточки пользователя, не только из микса
- Итог: цифра на плане ≠ цифра карточек, которые реально придут в сессию

**P3. Разные алгоритмы бюджета новых слов**
- `assembler.py:_get_remaining_card_budget()` использует `SRSService.get_adaptive_limits()` — адаптивный лимит (снижается при accuracy < 85%)
- `srs_slot.py:get_srs_budget_remaining()` использует `StudySettings.new_words_per_day` напрямую — всегда полный лимит
- Итог: у пользователя с низкой точностью linear-plan показывает больший бюджет, чем реально выдаст /study

**P4. Бюджетная математика дублируется в 3 местах**
- `assembler.py:198-235` — один вариант (naive UTC, adaptive limits)
- `srs_slot.py:46-67` — второй вариант (aware UTC, raw settings)
- `api_routes.py:69-94` — третий вариант (aware UTC, hybrid логика с `is_linear_plan_srs` костылём)

**P5. Naive vs timezone-aware UTC**
- `assembler.py` явно использует `datetime.now(timezone.utc).replace(tzinfo=None)` (правильно — Column(DateTime) хранит naive UTC)
- `srs_slot.py:_today_start()` возвращает `datetime.now(timezone.utc)` — timezone-aware, некорректно для naive DB колонок; работает случайно через psycopg2 conversion

**P6. `compute_day_secured` — два разных смысла под одним именем**
- `service.py:compute_day_secured(phases)` — проверяет `phase.get('completed', False)` из payload, который всегда False при сборке плана; используется только при первоначальной сборке
- `api/daily_plan.py:daily_status()` — вычисляет secured из `plan_completion` (реальная активность); не вызывает service.py-версию, дублирует логику inline для mission и linear

**P7. Мёртвый алгоритм SRS**
- `SRSService.update_card_after_review()` — классический SM-2 (quality 0-5) — нигде не вызывается
- Весь код использует `UserCardDirection.update_after_review()` — Anki state machine (quality 1-2-3)
- Источник путаницы: два алгоритма в кодбейзе, один лишний

**P8. Несовместимый формат ошибок в study API**
- `app/api/errors.py:api_error()` → `{'success': False, 'error': code, 'message': ..., 'status': ...}`
- `study/api_routes.py` → `{'status': 'error', 'message': ..., 'items': []}` или `{'status': 'daily_limit_reached', 'stats': {...}, 'items': []}`
- Frontend вынужден парсить оба формата; добавление новых обработчиков ошибок опасно

## Development Approach

- **Testing approach**: Regular (код → тесты)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**
- Изменения только в существующих файлах; новый модуль только для counting.py (Task 1)
- После каждого Task проверить: `python -c "import app.<module>"` для изменённых файлов

## Design Decisions

- **Canonical due-count**: include `learning` state (P1 fix). No `mix_word_ids` filter — показываем пользователю ВСЕ его due-карточки, а не только из микса (P2 fix). Naive UTC для next_review (P5 fix).
- **Canonical budget**: `SRSService.get_adaptive_limits()` везде — адаптивный лимит корректно защищает от накопления долга (P3 fix). linear-plan и mission-plan оба используют его.
- **UTC**: везде naive UTC для сравнения с `Column(DateTime)` полями next_review, first_reviewed, last_reviewed.
- **compute_day_secured**: разделить на два: `compute_day_secured_at_assembly(phases)` (существующая функция, Assembly-time only) и `compute_day_secured_from_activity(plan, plan_completion)` для real-time статуса (P6 fix).
- **Мёртвый код**: удалить `SRSService.update_card_after_review()` (P7 fix). Комментарий в классе — что используется Anki-SM.
- **API errors**: study/api_routes.py оставить `{'status': 'daily_limit_reached', ...}` — это не ошибка, а бизнес-статус; `{'status': 'error', ...}` заменить на `api_error()`. Frontend уже парсит `status: 'daily_limit_reached'` корректно. (P8 частичный fix)

---

## Implementation Steps

### BLOCK 1: Canonical SRS Counting (Tasks 1–2)

### Task 1: Create `app/srs/counting.py` — unified due-count and budget functions

Новый модуль с тремя каноническими функциями. Заменяет `_count_srs_due()` в assembler и `count_srs_due_cards()` в srs_slot.

**Files:**
- Create: `app/srs/counting.py`
- Create: `tests/srs/test_counting.py`

- [x] `count_due_cards(user_id, db) -> int` — считает `state IN ('learning', 'relearning', 'review')`, `next_review <= now_naive_utc`, `UserWord.status IN ('new', 'learning', 'review')`, без mix-фильтра
- [x] `count_new_cards_today(user_id, db) -> int` — `first_reviewed >= today_start_naive` AND `first_reviewed IS NOT NULL`; today_start = naive UTC midnight
- [x] `count_reviews_today(user_id, db) -> int` — `last_reviewed >= today_start_naive` AND `first_reviewed < today_start_naive` AND `first_reviewed IS NOT NULL`
- [x] Все функции принимают `now_utc: datetime | None = None` для testability (для тестов передаём фиксированное время)
- [x] Write tests: due_count=0 при пустой базе; due_count корректно включает learning/relearning/review; excludes 'new' state; buried_until учитывается; new_cards_today и reviews_today не пересекаются; naive UTC comparison не падает
- [x] `python -c "from app.srs.counting import count_due_cards"` — проходит
- [x] Run pytest — must pass before task 2

---

### Task 2: Wire `counting.py` into assembler, srs_slot, api_routes

Заменить дублирующие inline-функции на вызовы counting.py.

**Files:**
- Modify: `app/daily_plan/assembler.py`
- Modify: `app/daily_plan/linear/slots/srs_slot.py`
- Modify: `app/study/api_routes.py`
- Modify: `tests/daily_plan/test_assembler.py` (если есть)

- [x] `assembler.py:_count_srs_due()` → заменить тело на `count_due_cards(user_id, db)` из counting.py; убрать `mix_word_ids` фильтр (см. Design Decisions)
- [x] `srs_slot.py:count_srs_due_cards()` → заменить тело на `count_due_cards(user_id, db)` или убрать функцию и вызывать напрямую
- [x] `srs_slot.py:_today_start()` → заменить `datetime.now(timezone.utc)` на naive UTC: `datetime.now(timezone.utc).replace(tzinfo=None)`
- [x] `api_routes.py:77-84` (inline reviews_today) → заменить на `count_reviews_today(current_user.id, db)` из counting.py
- [x] `api_routes.py:69-75` (inline new_cards_today) → заменить на `count_new_cards_today(current_user.id, db)`
- [x] Убедиться что `srs_slot.py:count_srs_reviews_today()` согласована с counting.py (или заменить)
- [x] Write tests: интеграционный тест — mission-plan и linear-plan дают одинаковое число due_cards для одного пользователя
- [x] Run pytest — must pass before task 3

---

### BLOCK 2: Budget Unification (Tasks 3–4)

### Task 3: Add canonical budget functions to `app/srs/counting.py`

Добавить бюджетную математику. Решение: adaptive_limits везде.

**Files:**
- Modify: `app/srs/counting.py`
- Modify: `tests/srs/test_counting.py`

- [x] `get_new_card_budget(user_id, db) -> tuple[int, int]` — возвращает `(remaining_new, remaining_reviews)`, используя `SRSService.get_adaptive_limits(user_id)` минус `count_new_cards_today` / `count_reviews_today`
- [x] Никаких дополнительных параметров — adaptive_limits это единый источник истины
- [x] Write tests: при `new_cards_today >= adaptive_new` → `remaining_new = 0`; при низкой accuracy adaptive снижается и budget снижается; результат ≥ 0 всегда
- [x] Run pytest — must pass before task 4

---

### Task 4: Replace all inline budget math

**Files:**
- Modify: `app/daily_plan/assembler.py`
- Modify: `app/daily_plan/linear/slots/srs_slot.py`
- Modify: `app/study/api_routes.py`

- [x] `assembler.py:_get_remaining_card_budget()` → заменить тело на `get_new_card_budget(user_id, db)` из counting.py; удалить функцию если больше нигде не используется
- [x] `srs_slot.py:get_srs_budget_remaining()` → заменить на `get_new_card_budget(user_id, db)[0]` (только remaining_new для slot)
- [x] `api_routes.py:92-94` (`adaptive_new, adaptive_reviews = SRSService.get_adaptive_limits(...)`) → заменить на `get_new_card_budget(current_user.id, db)` и деструктурировать
- [x] Убедиться что `is_linear_plan_srs` логика в api_routes.py по-прежнему работает (linear SRS не даёт новых карточек, только reviews)
- [x] Write tests: mission-plan и linear-plan получают одинаковый бюджет для одного пользователя; `is_linear_plan_srs=True` всё ещё блокирует новые карточки
- [x] Run pytest — must pass before task 5

---

### BLOCK 3: compute_day_secured (Task 5)

### Task 5: Rename assembly-time secured, extract activity-based secured to service.py

**Files:**
- Modify: `app/daily_plan/service.py`
- Modify: `app/api/daily_plan.py`
- Modify: `tests/daily_plan/` (relevant tests)

- [x] В `service.py`: переименовать `compute_day_secured(phases)` в `compute_day_secured_at_assembly(phases)` — явно показывает что это assembly-time (phases.completed всегда False)
- [x] В `service.py`: добавить `compute_day_secured_from_activity(plan: dict, plan_completion: dict[str, bool]) -> bool` — выносим inline логику из `api/daily_plan.py:daily_status()`. Обрабатывает оба effective_mode: `'mission'` (by phase id) и `'linear'` (by slot kind). Остальные режимы → `plan.get('day_secured', False)`
- [x] В `api/daily_plan.py:daily_status()`: заменить inline block (строки 57-74) на вызов `compute_day_secured_from_activity(plan, plan_completion)`
- [x] Обновить все вызовы `compute_day_secured()` → `compute_day_secured_at_assembly()` (grep по кодбейзу)
- [x] Write tests: mission mode с 1 required completed → True; linear mode с 2 slots, оба completed → True; linear с 1 незавершённым → False; пустой plan → False
- [x] Run pytest — must pass before task 6

---

### BLOCK 4: API Error Format (Task 6)

### Task 6: Standardize `study/api_routes.py` error responses

**Files:**
- Modify: `app/study/api_routes.py`
- Modify: `tests/study/` (test_api_routes.py если есть)

- [x] Импортировать `api_error` из `app.api.errors`
- [x] Заменить `return jsonify({'status': 'error', 'message': ..., 'items': []})` на `api_error('deck_not_found', ..., 404)` (строки ~56-60)
- [x] **НЕ менять** `{'status': 'daily_limit_reached', ...}` — это бизнес-статус, не ошибка; JS frontend ожидает этот формат
- [x] Проверить все остальные `return jsonify({'status': 'error', ...})` в study/api_routes.py — заменить на api_error()
- [x] Write tests: при неверном deck_id ответ содержит `{'success': False, 'error': 'deck_not_found'}`; `daily_limit_reached` ответ по-прежнему содержит `status: 'daily_limit_reached'`
- [x] Run pytest — must pass before task 7

---

### BLOCK 5: Dead Code Removal (Tasks 7–8)

### Task 7: Remove dead `SRSService.update_card_after_review()`

**Files:**
- Modify: `app/study/services/srs_service.py`
- Modify: `tests/study/` (удалить тесты для этого метода если есть)

- [x] Grep: убедиться что `SRSService.update_card_after_review` нигде не вызывается (кроме собственного тела)
- [x] Удалить метод полностью из `SRSService`
- [x] Добавить комментарий в класс: SRS-scheduling использует `UserCardDirection.update_after_review()` (Anki state machine)
- [x] `python -c "from app.study.services.srs_service import SRSService"` — проходит
- [x] Run pytest — must pass before task 8

---

### Task 8: Audit and fix remaining naive/aware UTC issues

**Files:**
- Modify: `app/daily_plan/linear/slots/srs_slot.py`
- Possibly: `app/study/api_routes.py`, `app/daily_plan/assembler.py`

- [ ] Grep `datetime.now(timezone.utc)` по всем файлам где есть сравнения с `next_review`, `first_reviewed`, `last_reviewed`
- [ ] Для каждого: убедиться что `.replace(tzinfo=None)` применяется перед сравнением с Column(DateTime)
- [ ] `srs_slot.py:_today_start()`: зафиксировать как `now.replace(tzinfo=None).replace(hour=0, ...)`
- [ ] Проверить `count_srs_due_cards()` в srs_slot.py — `now` для `next_review <= now` должен быть naive
- [ ] Write tests: подтвердить что функции не бросают TypeError при сравнении dts
- [ ] Run pytest — must pass before task 9

---

### BLOCK 6: Final Validation (Task 9)

### Task 9: Full smoke test pass and regression check

**Files:**
- No code changes — validation only

- [ ] `pytest -m smoke` — все smoke тесты зелёные
- [ ] `pytest tests/srs/` — новые тесты из Task 1, 3 проходят
- [ ] `pytest tests/daily_plan/` — all daily_plan tests pass
- [ ] `pytest tests/study/` — all study tests pass
- [ ] Проверить что нет unused import'ов в изменённых файлах: `python -m py_compile app/srs/counting.py app/daily_plan/assembler.py app/daily_plan/linear/slots/srs_slot.py app/study/api_routes.py app/daily_plan/service.py app/api/daily_plan.py`
- [ ] Manual smoke: зайти на дашборд → убедиться что SRS-счётчик на слоте совпадает с числом карточек в начале сессии /study/cards
