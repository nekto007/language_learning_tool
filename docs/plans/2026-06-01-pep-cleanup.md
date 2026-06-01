---
# PEP Cleanup & Dead Code Removal

## Overview

Systematic production-readiness cleanup: remove confirmed dead code (mission/*, rivals), strip unnecessary/commented-out code blocks, fix unused imports via autoflake, sort imports via isort, add missing type hints to public service functions, and fix PEP 8 violations (long lines, naming) across the 281-file codebase. DB and migrations untouched per decision.

## Context

- Files involved: всё app/ (281 Python-файлов), фокус — app/daily_plan/, app/words/routes.py, app/curriculum/routes/, app/achievements/, app/srs/, app/admin/, app/__init__.py
- Related patterns: type hints уже есть в daily_plan/service.py и srs/service.py — этот стиль берём за образец
- Dependencies: flake8, autoflake, isort (dev-only tools, не меняют runtime)
- Решение по БД: только Python, миграции не создаём

## Development Approach

- **Testing approach**: Regular — сначала код, потом smoke-тесты
- Инкрементально по модулю: каждый task = один логический блок файлов
- После каждого task — `pytest -m smoke`, нельзя переходить к следующему при red
- Комментарии в коде — только когда WHY неочевиден (не WHAT)
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Аудит и удаление мёртвого кода — mission/rivals

**Files:**
- Investigate & possibly delete: `app/daily_plan/mission_selector.py`, `app/daily_plan/rivals.py`
- Modify: `app/daily_plan/assembler.py`, `app/words/routes.py`, любые другие импортёры

- [x] grep всех импортов mission_selector, rivals по всему проекту
- [x] удалить функцию `_next_step_from_mission()` из app/words/routes.py если не вызывается
- [x] удалить app/daily_plan/mission_selector.py если нет живых вызовов
- [x] удалить app/daily_plan/rivals.py если нет живых вызовов
- [x] убрать все осиротевшие импорты из assembler.py и других файлов
- [x] run pytest -m smoke — должны пройти

### Task 2: Автоматическая чистка импортов (autoflake + isort)

**Files:**
- Modify: все файлы в app/ (autoflake --remove-unused-variables --remove-all-unused-imports)

- [x] запустить autoflake --check на всё app/ — зафиксировать список файлов с проблемами
- [x] применить autoflake --in-place к app/ (исключить app/migrations/)
- [x] запустить isort --check-only app/ — зафиксировать расхождения
- [x] применить isort app/ с профилем black (line_length=120)
- [x] вручную проверить diff на app/__init__.py и app/words/routes.py (наибольший риск)
- [x] run pytest -m smoke

### Task 3: Чистка комментариев и типы — app/daily_plan/

**Files:**
- Modify: `app/daily_plan/plan.py`, `app/daily_plan/assembler.py`, `app/daily_plan/service.py`, `app/daily_plan/next_step.py`, `app/daily_plan/items/*.py`, `app/daily_plan/linear/*.py`

- [x] удалить раздельные === section-divider комментарии, заменить docstring там где needed
- [x] удалить TODO/FIXME/заметки-напоминалки которые уже выполнены
- [x] добавить отсутствующие return-аннотации к public функциям (образец — service.py)
- [x] убрать отключённые блоки кода (if False: ..., закомментированные куски)
- [x] run pytest -m smoke

### Task 4: Чистка комментариев и типы — app/words/ и app/study/

**Files:**
- Modify: `app/words/routes.py`, `app/study/insights_service.py`, `app/study/services/stats_service.py`

- [x] убрать "===="-разделители из words/routes.py (>25 штук)
- [x] добавить return type к helper-функциям: _safe_widget_call, _get_cached_leaderboard, _public_dictionary_query
- [x] разбить сверхдлинные строки (>120 символов) в словарных call-цепочках
- [x] удалить закомментированные куски кода
- [x] run pytest -m smoke

### Task 5: Чистка — app/curriculum/

**Files:**
- Modify: `app/curriculum/routes/lessons.py`, `app/curriculum/routes/vocabulary_lessons.py`, `app/curriculum/routes/grammar_quiz_lessons.py`, `app/curriculum/routes/admin.py`, `app/curriculum/navigation.py`, `app/curriculum/grading.py`

- [x] удалить неактуальные inline-комментарии объясняющие WHAT (а не WHY)
- [x] добавить return type hints к публичным функциям в navigation.py, grading.py
- [x] исправить строки >120 символов
- [x] run pytest -m smoke

### Task 6: Чистка — app/achievements/, app/srs/, app/books/

**Files:**
- Modify: `app/achievements/xp_service.py`, `app/achievements/services.py`, `app/achievements/streak_service.py`, `app/srs/service.py`, `app/srs/counting.py`, `app/books/vocab_pull.py`, `app/books/reading_session.py`

- [x] удалить TODO-комментарии которые уже реализованы
- [x] добавить отсутствующие return type hints к публичным функциям
- [x] убрать мёртвые ветки (закомментированный старый код)
- [x] run pytest -m smoke

### Task 7: Чистка — app/admin/, app/api/, app/auth/, app/__init__.py

**Files:**
- Modify: `app/__init__.py`, `app/auth/routes.py`, `app/api/*.py`, `app/admin/main_routes.py`, `app/admin/routes/*.py`

- [x] добавить return type к nested helper-функциям в app/__init__.py
- [x] удалить устаревшие inline-объяснения поведения (перенесённые в CLAUDE.md)
- [x] исправить нарушения PEP 8 в admin routes (строки, импорты)
- [x] run pytest -m smoke

### Task 8: Финальная верификация

- [x] запустить полный `pytest` (все тесты, не только smoke)
- [x] запустить `flake8 app/ --max-line-length=120 --extend-ignore=E203,W503` — 0 критических ошибок
- [x] проверить что `python -c "from app import create_app"` работает чисто
- [x] убедиться что pytest -m smoke < 30 секунд

### Task 9: Обновить CLAUDE.md

- [ ] обновить секцию Code Style если выработали новые конвенции в ходе чистки
