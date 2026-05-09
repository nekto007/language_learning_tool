# Бесконечная линейная цепочка заданий в плане дня

## Overview

Превратить дневной план из фиксированного списка 3-4 слотов в бесконечную цепочку заданий. После завершения текущего задания оно отмечается как выполненное и в конец цепочки добавляется новое (по доступным источникам: следующий урок курса, SRS-повторение, чтение, разбор ошибок). Перескакивать между заданиями нельзя — кнопка "Начать" доступна только у текущего задания, остальные показываются как "Заблокировано". Минимальный baseline (первые N=3-4 слота, как сейчас) сохраняет смысл `day_secured` — день закрыт, когда пройден минимум, дальше цепочка продолжается опционально.

## Context

- Files involved:
  - `app/daily_plan/linear/plan.py` — assembler возвращает `baseline_slots` + continuation
  - `app/daily_plan/linear/slots/{curriculum_slot,srs_slot,reading_slot,error_review_slot}.py` — построение слотов
  - `app/daily_plan/linear/progression.py` (или `app/curriculum/navigation.py`) — `find_next_lesson_linear`
  - `app/daily_plan/service.py` — `compute_plan_steps`, `compute_day_secured_from_activity`
  - `app/api/daily_plan.py` — `/api/daily-status`, `/api/daily-plan`
  - `app/templates/partials/linear_daily_plan.html` — рендер слотов и состояний
  - `app/static/js/linear-daily-plan.js` — клиентская логика обновлений
  - `app/static/css/design-system.css` — состояния `.linear-slot--current/done/pending`; добавить `--locked`
  - `tests/daily_plan/linear/*` — обновить и расширить
- Related patterns:
  - текущая логика "current_found" в шаблоне (первый незавершённый = current, остальные = pending)
  - `compute_plan_steps` маппит активность пользователя на `slot.kind`
  - `day_secured` уже отделён от длины списка слотов (`compute_linear_day_secured`)
- Dependencies: нет внешних

## Development Approach

- Regular: код → тесты, сначала пайплайн генератора, потом UI, потом acceptance
- Каждая задача завершается полностью перед следующей
- CRITICAL: каждая задача обязана включать новые/обновлённые тесты
- CRITICAL: pytest должен быть зелёным перед началом следующей задачи

## Implementation Steps

### Task 1: Slot chain generator

**Files:**
- Create: `app/daily_plan/linear/chain.py`
- Modify: `app/daily_plan/linear/slots/__init__.py` (если нужно экспортировать билдеры)
- Create: `tests/daily_plan/linear/test_chain.py`

- [x] добавить `build_next_slot(user_id, db, already_in_chain: list[dict])` — возвращает следующий слот по приоритету: curriculum spine → srs (если бюджет/due > 0) → reading (если есть выбранная книга и не достигнут гейт) → error_review (если триггер сработал); пропускает источники, которые уже исчерпаны на сегодня
- [x] добавить `build_chain(user_id, db, baseline_size=3-4, max_extra=10)` — собирает базовый minimum_slots (как сейчас) + дополнительные слоты до тех пор, пока есть выполненная активность по предыдущему звену; останавливается как только встречает невыполненное звено
- [x] вернуть структуру: `list[dict]` плюс metadata `{baseline_count, has_more_available}`
- [x] написать unit-тесты: пустая активность → только baseline; завершён первый слот → добавлен 4-й; источник исчерпан → пропущен; курс пройден → завершение цепочки
- [x] прогнать pytest, должны проходить

### Task 2: Integrate chain into linear plan assembler

**Files:**
- Modify: `app/daily_plan/linear/plan.py`
- Modify: `tests/daily_plan/linear/test_plan.py` (или соответствующий)

- [x] заменить статическое формирование `baseline_slots` на `build_chain`; baseline сохранить как первые N слотов для day_secured math
- [x] payload: добавить `chain_meta {baseline_count, has_more_available, exhausted_sources: [...]}`; `baseline_slots` остаётся для backward compat (равен `chain[:baseline_count]`)
- [x] `continuation` остаётся, но сужается до preview lessons (не перекрывает inline-цепочку)
- [x] обновить `compute_linear_day_secured`: считать только по first N (baseline)
- [x] обновить тесты на assemble: проверка состава цепочки до/после активности, корректность `baseline_count`
- [x] pytest зелёный

### Task 3: Activity-driven chain refresh in API

**Files:**
- Modify: `app/api/daily_plan.py`
- Modify: `app/daily_plan/service.py` (compute_plan_steps если нужны новые kinds или порядок)
- Modify: `tests/api/test_daily_plan.py` или эквивалент

- [x] `/api/daily-status` и `/api/daily-plan`: пересобирать цепочку каждый запрос (chain само-наращивается по факту активности, плюс сервер пересчитывает completed по `plan_completion`)
- [x] вернуть в payload `poll_after_seconds` (или просто полагаться на существующий polling в JS) — полная пересборка ответа уже даёт обновление
- [x] добавить тест: после маркера активности новая цепочка длиннее на 1; вторая активность ещё на 1; источник исчерпан → длина не растёт
- [x] pytest зелёный

### Task 4: Locked/sequential UI state

**Files:**
- Modify: `app/templates/partials/linear_daily_plan.html`
- Modify: `app/static/css/design-system.css`
- Modify: `app/static/js/linear-daily-plan.js`
- Create: `tests/templates/test_linear_plan_partial.py` (или smoke-test через dashboard)

- [x] в Jinja-цикле слотов: первый незавершённый = current (как сейчас), все последующие = locked (новое состояние) вместо pending
- [x] для locked: убрать ссылку/кнопку "Начать", показать иконку замка + текст "Откроется после завершения предыдущего"
- [x] добавить класс `linear-slot--locked` в design-system.css (приглушённый стиль, cursor not-allowed, без hover)
- [x] JS: при клике на locked слот — preventDefault + ненавязчивый toast "Сначала завершите предыдущее задание"
- [x] тест на рендер: после завершения первого слота — второй становится current, третий locked
- [x] pytest зелёный

### Task 5: Chain-extension UX cues

**Files:**
- Modify: `app/templates/partials/linear_daily_plan.html`
- Modify: `app/static/js/linear-daily-plan.js`
- Modify: `app/static/css/design-system.css`
- Modify: existing template tests

- [x] показать индикатор "+1 задание добавлено" при увеличении длины цепочки между двумя ответами `/api/daily-status` (JS сравнивает длину, показывает короткий toast)
- [x] над baseline-частью цепочки — sticky-метка "Минимум на день" (первые N), под ней — "Дальше необязательно, но засчитывается"
- [x] если `has_more_available=false` и весь курс/источники исчерпаны — финальный блок "На сегодня источники исчерпаны"
- [x] обновить JS-тесты или snapshot шаблона
- [x] pytest зелёный

### Task 6: Verify acceptance criteria

- [x] прогнать `pytest` полностью (5397 passed, 58 skipped, 6 xfailed, 3 xpassed)
- [x] прогнать `pytest -m smoke` (141 passed)
- [x] проверить через flask dev (skipped — manual browser test, not automatable)
- [x] проверить admin metrics не сломаны (`tests/admin/test_linear_plan_metrics.py` 33/33 passed)

### Task 7: Update documentation

- [ ] обновить CLAUDE.md секцию "Daily plan (linear, curriculum spine)" — описать `build_chain`, locked state, baseline vs extension semantics
- [ ] переместить план в `docs/plans/completed/`
