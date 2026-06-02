# Аудит и исправление багов в уроках Curriculum

## Overview
Систематическое исправление критических багов и UX-несоответствий в уроках curriculum:
грейдинг, XP-начисление, интеграция с планом дня, и консистентность UI. Аудит выявил 10+
конкретных проблем с точными line numbers.

## Context
- Files involved:
  - `app/curriculum/routes/lessons.py` — основной файл маршрутов (2200 строк), большинство багов здесь
  - `app/curriculum/grading.py` — логика грейдинга, final test attempt limit
  - `app/daily_plan/items/curriculum.py` — интеграция с планом дня
  - `app/curriculum/constants.py` — создать для централизованных порогов
  - `app/templates/curriculum/lessons/` — шаблоны уроков
- Related patterns: `award_xp` savepoint pattern в `app/achievements/services.py`; `db_session fixture` savepoint rollback из conftest
- Dependencies: нет новых

## Development Approach
- **Testing approach**: Regular (сначала код, потом тесты)
- Чинить по одной group багов, запускать smoke после каждой задачи
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Централизовать пороги прохождения + исправить sentence_correction 100%

Найденная проблема: в `lessons.py:1260` для single-item sentence correction стоит `passing_score=100`, тогда как все
остальные типы уроков используют 70. Также пороги разбросаны по всему файлу (dictation=80, все
остальные=70).

**Files:**
- Create: `app/curriculum/constants.py`
- Modify: `app/curriculum/routes/lessons.py`

- [x] Создать `app/curriculum/constants.py` с константами `PASSING_SCORE_DEFAULT = 70`, `PASSING_SCORE_DICTATION = 80`
- [x] Заменить хардкоженные числа 70/80 на импорт из constants во всех `_process_*` функциях lessons.py
- [x] Исправить строку ~1260: `passing_score=70 if is_multi else 100` → `passing_score=PASSING_SCORE_DEFAULT` (убрать различие single/multi)
- [x] Запустить `python -c "import app.curriculum.routes.lessons"` и `pytest -m smoke`

### Task 2: Исправить XP-начисление — savepoint и score=None для writing/pronunciation

Найденные проблемы:
- `lessons.py:259-276`: exception handler не делает rollback, LessonProgress помечается completed без XP
- `lessons.py:1514`: writing_prompt передаёт `score=None` в `maybe_award_curriculum_xp`, другие уроки передают реальный score
- `lessons.py:2007`: pronunciation передаёт `score=None`

**Files:**
- Modify: `app/curriculum/routes/lessons.py`

- [x] Обернуть блок XP-начисления (строки ~259-276) в savepoint: `db.session.execute(text("SAVEPOINT xp_award"))` и `ROLLBACK TO SAVEPOINT` в except
- [x] Для writing_prompt (`~line 1514`): вычислить score из результата чеклиста перед `maybe_award_curriculum_xp`; передать реальный score (0–100) вместо None
- [x] Для pronunciation (`~line 2007`): вычислить score на основе `matched / total_attempts` если есть записи в PronunciationAttempt; передать score или 0 если нет данных
- [x] Убедиться что аналогичный savepoint-паттерн применён во всех местах где XP начисляется в lessons.py
- [x] Запустить `pytest -m smoke`

### Task 3: Исправить pronunciation — require минимум одну попытку перед finish

Найденная проблема: `finish=True` позволяет получить XP без реальной практики — никакой
валидации не происходит. Пользователь может сразу отправить `{"finish": true}` и получить XP.

**Files:**
- Modify: `app/curriculum/routes/lessons.py`

- [x] В обработчике pronunciation submission (~строки 1970-2025): перед установкой `status='completed'` проверить наличие хотя бы одной записи `PronunciationAttempt` для этого урока сегодня (или в текущей сессии через progress_data)
- [x] Если записей нет — вернуть `{"success": False, "error": "requires_attempt", "message": "Необходимо сделать хотя бы одну попытку"}` с кодом 400
- [x] Добавить `LessonProgress.score` tracking для pronunciation: сохранять `matched_count / total_count * 100` в `progress.score`
- [x] Запустить `pytest -m smoke`

### Task 4: Исправить final test attempt limit — не считать NULL passed

Найденная проблема: `grading.py:~61` фильтр включает `passed.is_(None)` при подсчёте попыток.
Незавершённые/упавшие попытки без значения `passed` засчитываются в лимит 3 попыток за 24ч.

**Files:**
- Modify: `app/curriculum/grading.py`

- [x] В функции подсчёта попыток финального теста: изменить фильтр с `(passed.is_(False)) | (passed.is_(None))` на `passed.is_(False)` — считать только явно провальные попытки
- [x] Убедиться что `LessonAttempt.passed` правильно выставляется в `False` при провале (а не остаётся NULL)
- [x] Запустить `pytest tests/test_curriculum.py` и `pytest -m smoke`

### Task 5: Исправить daily plan — _curriculum_done_today должен проверять score

Найденная проблема: `app/daily_plan/items/curriculum.py` функция `_curriculum_done_today` проверяет только
`LessonProgress.status == 'completed'`, не проверяя `score >= passing_threshold`. Урок с failing score засчитывается как
выполненный в плане дня.

**Files:**
- Modify: `app/daily_plan/items/curriculum.py`

- [x] В `_curriculum_done_today` (или аналогичной функции проверки завершения): добавить условие `LessonProgress.score >= PASSING_SCORE_DEFAULT` (или конкретный threshold для типа урока) как дополнительное требование
- [x] Проверить что это не ломает graduated/paused план (для completed curriculum lessons из истории)
- [x] Импортировать `PASSING_SCORE_DEFAULT` из `app/curriculum/constants`
- [x] Запустить `pytest -m smoke`

### Task 6: UX-фиксы — reset feature и ошибки rate limit

Найденные проблемы:
- `?reset=true` работает только в `translation_lesson`, не в `sentence_correction_lesson` и `writing_prompt_lesson`
- Rate limit ошибки не сообщают когда можно повторить
- Ошибка доступа к модулю не объясняет WHY заблокирован

**Files:**
- Modify: `app/curriculum/routes/lessons.py`
- Modify: `app/templates/curriculum/lessons/sentence_correction.html` (если шаблон есть)
- Modify: `app/templates/curriculum/lessons/writing_prompt.html` (если шаблон есть)

- [x] Добавить обработку `?reset=true` в `sentence_correction_lesson` аналогично `translation_lesson`: при reset удалять прогресс и перенаправлять
- [x] Добавить обработку `?reset=true` в `writing_prompt_lesson`
- [x] В ответах rate limit (pronunciation attempts) добавить `retry_after` timestamp с оставшимся временем
- [x] Запустить `pytest -m smoke`

### Task 7: Тесты для исправленных компонентов

**Files:**
- Modify/Create: `tests/test_curriculum_grading.py` или `tests/curriculum/`

- [x] Тест: sentence_correction single-item теперь проходит при score=70 (не требует 100%)
- [x] Тест: pronunciation finish=True без попыток возвращает 400
- [x] Тест: final test attempt limit не считает NULL passed записи
- [x] Тест: _curriculum_done_today не засчитывает урок с низким score как completed
- [x] Тест: XP-начисление при исключении откатывается через savepoint (lesson остаётся completed, XP не записан)
- [x] Запустить `pytest -m smoke` — все должны пройти
- [x] Запустить `pytest tests/test_curriculum*.py` — все должны пройти

### Task 8: Проверка acceptance criteria

- [x] Запустить полный test suite: `pytest -m smoke`
- [x] Запустить `python -c "import app"` — нет import errors
- [x] Проверить что `PASSING_SCORE_DEFAULT` и `PASSING_SCORE_DICTATION` импортируются из constants во всех местах использования
- [x] Grep на `passing_score=100` в lessons.py — должно быть 0 результатов (или только обоснованные случаи)
- [x] Grep на `score=None` в вызовах `maybe_award_curriculum_xp` — должно быть 0 необоснованных случаев (3 оставшихся — shadow_reading/listening_immersion/idiom — justified, self-assessed без score)
