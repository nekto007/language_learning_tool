# Comprehensive Project Audit, Stabilization, and Cleanup Plan

## Overview
Комплексный план по стабилизации, упрощению и расчистке проекта после детального аудита всего репозитория. Цель: убрать источники скрытых регрессий, выровнять runtime и документацию, сократить объем исторического мусора и подготовить кодовую базу к безопасному дальнейшему развитию.

## Context
- Проект представляет собой крупный Flask-монолит с несколькими доменными подсистемами: auth, words, books, study, curriculum, grammar_lab, telegram, notifications, admin
- В кодовой базе одновременно присутствуют признаки активной продуктовой разработки, legacy CLI/скриптов и большого числа разовых migration/import/audit utilities
- Фабрика приложения перегружена side effects: инициализация БД, сидирование, прогрев кэша, запуск scheduler/polling
- Схема БД управляется не единообразно: Alembic, `db.create_all()`, legacy `init_db`
- API-слой использует смешанную модель auth: часть endpoint-ов работает через JWT, часть через cookie session
- Документация, docker/runtime и тестовый bootstrap расходятся по версиям Python, портам, зависимости и процедурам запуска
- В корне репозитория лежит заметный объем operational/data artifacts, которые не выглядят как постоянная часть продукта

## Audit Summary

### Confirmed High-Risk Findings
- Критический runtime-баг: `init_db(app)` вызывается без `app` в админке и legacy CLI
- `create_app()` выполняет мутации БД и старт фоновых подсистем при каждом создании app
- В проекте несколько конкурирующих путей инициализации схемы БД
- Конфиг исполняет валидацию окружения и печать в stdout/stderr на import-time
- API-аутентификация архитектурно раздвоена
- `run.py` содержит мертвый код
- `celery_app.py` ссылается на несуществующие task modules
- Тестовый запуск из "чистого" окружения не воспроизводится по собственной документации

### Structural Findings
- Крупнейшие route/service модули сильно переразмерены, что повышает риск регрессий при локальных правках
- В проекте много broad `except Exception`, что скрывает реальные сбои и затрудняет диагностику
- Есть дублирующиеся или конкурирующие подсистемы SRS/stats/service naming, усложняющие навигацию
- В корне репозитория слишком много CSV/JSON/SQL и разовых скриптов, из-за чего рабочая область выглядит как смесь app-кода и локального рабочего стола

## Development Approach
- **Testing approach**: сначала стабилизация bootstrap и инфраструктурных инвариантов, затем рефакторинг, затем очистка мусора
- Каждый этап должен завершаться обновлением документации и явной фиксацией того, что считается source of truth
- Любое удаление файлов из legacy/operations слоя делать только после подтверждения отсутствия runtime-use (grep + git blame manifest) и после переноса нужных артефактов в архивную структуру
- Для опасных изменений в app factory, auth и database lifecycle сначала добавить/уточнить тесты, потом менять код

## Dependency Graph

```
Task 1 (factory) → Task 2 (db lifecycle) → Task 3 (config)
                                               ↓
                                          Task 5 (test bootstrap)
                                               ↓
                                          Task 6 (dead entrypoints)
                                               ↓
                                          Task 4 (API auth)
                                               ↓
                                     Task 8a-8b (exception audit)
                                               ↓
                                     Task 7a-7c (refactor modules)
                                               ↓
                                     Task 9 (artifacts cleanup)
                                               ↓
                                     Task 10 (docs realignment)
                                               ↓
                                     Task 11 (final cleanup pass)
```

Не начинать следующий task пока предыдущий не завершён и тесты не проходят.

## Implementation Steps

### Task 1: Stabilize App Startup and Remove Side Effects from Factory

**Files:**
- Modify: `app/__init__.py`
- Modify: `app/curriculum/__init__.py`
- Modify: `app/telegram/scheduler.py` or relevant startup integration
- Modify: `app/email_scheduler.py`

**Переходная стратегия для `db.create_all()`:**
- В `TESTING=True` path `db.create_all()` ОСТАЁТСЯ (тесты зависят от него)
- В production path `db.create_all()` заменяется на no-op; initial schema создаётся через `flask db upgrade` в Docker entrypoint
- Добавить в Dockerfile/docker-compose: `flask db upgrade head` перед `gunicorn`

- [x] Убрать из `create_app()` автоматические сидирование, warm cache, запуск Telegram polling, scheduler и email scheduler
- [x] `db.create_all()` — оставить ТОЛЬКО в `TESTING=True` блоке, убрать из production path
- [x] Оставить в app factory только конфигурацию extensions, blueprint registration и lightweight hooks
- [x] Вынести startup jobs в отдельные CLI-команды: `flask seed`, `flask warm-cache`, `flask start-bot`
- [x] Добавить защиту от повторного запуска background services при reloader/worker startup
- [x] Обновить Docker entrypoint: `flask db upgrade head && gunicorn ...`
- [x] Добавить тесты: `create_app()` в TESTING mode не мутирует БД, не стартует schedulers

### Task 2: Unify Database Lifecycle Around Alembic Only

**Files:**
- Modify: `app/__init__.py`
- Modify: `app/utils/db_init.py`
- Modify: `app/modules/migrations.py`
- Modify: `app/admin/routes/system_routes.py`
- Review: `migrations/versions/*`

**Зависит от:** Task 1 (factory уже не вызывает `db.create_all()` в production)

- [ ] Оставить Alembic единственным supported способом управления схемой в production
- [ ] Удалить legacy `init_db` (или переименовать в `_legacy_init_db` и пометить deprecated)
- [ ] Исправить баг с вызовом `init_db()` без `app` в админке
- [ ] Проверить, какие seed data должны жить в миграциях, а не в runtime (`seed_initial_modules`, `seed_achievements`)
- [ ] Добавить smoke-test: `flask db upgrade head` на чистой БД создаёт все таблицы
- [ ] Документировать: "единственный путь создания/обновления схемы — `flask db upgrade`"

### Task 3: Normalize Configuration and Eliminate Import-Time Behavior

**Files:**
- Modify: `config/settings.py`
- Modify: `app/__init__.py`
- Modify: tests/config bootstrap if needed

**Зависит от:** Task 2

- [ ] Убрать `validate_environment()` с import-time execution
- [ ] Перенести обязательную валидацию окружения в `create_app()` (after config load, before extensions init)
- [ ] Заменить `print()` на structured logging
- [ ] Привести `Config`, `TestConfig`, docker env и `.env.example` к одному источнику истины
- [ ] Явно определить production/dev/test semantics для `SECRET_KEY`, `JWT_SECRET_KEY`, cookie flags и DB URI
- [ ] Покрыть тестами отсутствие import-time side effects: `import config.settings` не печатает и не кидает

### Task 4: Consolidate API Authentication Model

**Files:**
- Modify: `app/api/decorators.py`
- Modify: API blueprint files as needed
- Modify: any API tests affected

**Зависит от:** Task 5 (тесты должны bootstrap-иться)

**Target state (зафиксировано):**
- `/api/*` endpoints принимают И JWT Bearer И session cookie (для browser-AJAX). Это dual-auth, но через **один** декоратор
- Убрать дублирование: `api_login_required` и `api_jwt_required` → единый `@api_auth_required` который проверяет JWT first, fallback на session
- Stateless JWT endpoints (`/api/daily-*`, `/api/streak`) остаются `@csrf.exempt`
- Browser-AJAX endpoints (из study/words pages) продолжают работать через session + CSRF
- НЕ ломать существующие browser flows

- [ ] Создать единый `@api_auth_required` декоратор (JWT → session fallback)
- [ ] Заменить `@api_login_required` и `@api_jwt_required` на `@api_auth_required` где применимо
- [ ] Проверить `@csrf.exempt` — только для чисто-JWT endpoints
- [ ] Обновить тесты: проверить что каждый endpoint принимает и JWT и session
- [ ] Обновить `docs/API.md` — единый auth model description

### Task 5: Repair Developer Bootstrap and Test Bootstrap

**Files:**
- Modify: `requirements-test.txt`
- Modify: `README.md`
- Modify: `pyproject.toml`

**Зависит от:** Task 3

- [ ] Сделать тестовый bootstrap воспроизводимым из чистого окружения
- [ ] Добавить `-r requirements.txt` в `requirements-test.txt`
- [ ] Привести README к фактическим версиям Python, портам, способу запуска
- [ ] Явно описать: PostgreSQL обязателен для тестов (SQLite не поддерживается из-за JSONB, array_agg и т.д.)
- [ ] Добавить минимальный smoke path: `pip install -r requirements-test.txt && python -c "from app import create_app; create_app()" && pytest tests/ -x --timeout=60`

### Task 6: Remove Dead Entry Points

**Files:**
- Modify: `run.py`
- Delete: `celery_app.py` (Celery не используется — нет worker config, нет реальных tasks)
- Delete: `main.py` (дублирует `run.py` + `flask run`, содержит мёртвый код)
- Delete: `setup_web.py` (одноразовый setup script, функционал в seed commands)
- Review: `script_migrations.py`, `run_module_migration.py`

**Зависит от:** Task 5

**Решения зафиксированы (не "либо/либо"):**
- [ ] `run.py` — оставить, убрать мёртвый код, оставить как dev entrypoint
- [ ] `celery_app.py` — удалить (Celery не используется, task modules не существуют)
- [ ] `main.py` — удалить (дублирует функционал, содержит broken imports)
- [ ] `setup_web.py` — удалить (заменён CLI seed commands)
- [ ] `script_migrations.py`, `run_module_migration.py` — удалить если функционал покрыт Alembic
- [ ] Обновить Dockerfile: убрать ссылки на удалённые entrypoints
- [ ] Добавить в README матрицу: "Official entrypoints: `flask run` (dev), `gunicorn` (prod), `flask db` (migrations)"

### Task 7a: Refactor `app/study/routes.py` (~2630 строк)

**Зависит от:** Task 8a

**Target split:**
- `app/study/routes.py` → core routes (index, settings, cards, quiz, matching) — ~800 строк
- `app/study/api_routes.py` → JSON API endpoints (get-study-items, update-study-item, complete-session, srs-stats, celebrations) — ~1000 строк
- `app/study/deck_routes.py` → deck management (create, add-word, default-deck, add-from-collection) — ~500 строк
- `app/study/game_routes.py` → quiz/matching/leaderboard — ~300 строк

**Acceptance:** каждый выделенный файл < 1000 строк, все тесты проходят, нет circular imports.

- [ ] Добавить regression tests для ключевых endpoints перед split
- [ ] Выделить `api_routes.py`
- [ ] Выделить `deck_routes.py`
- [ ] Выделить `game_routes.py`
- [ ] Проверить blueprint registration и url_for ссылки
- [ ] Прогнать полный test suite

### Task 7b: Refactor `app/curriculum/routes/lessons.py` и `book_courses.py`

**Зависит от:** Task 7a (доказали что split-паттерн работает)

**Acceptance:** каждый выделенный файл < 1000 строк, все тесты проходят.

- [ ] Разделить `lessons.py` по типам уроков (vocabulary, grammar, quiz, card) — ~4 файла
- [ ] Разделить `book_courses.py` на routes + service
- [ ] Прогнать тесты

### Task 7c: Refactor `app/books/routes.py` и `app/curriculum/service.py`

**Зависит от:** Task 7b

**Acceptance:** каждый выделенный файл < 1000 строк, все тесты проходят, нет `sys.path` mutation и import-time `os.makedirs`.

- [ ] `books/routes.py` — вынести reader API в `books/api.py`
- [ ] `curriculum/service.py` — вынести бизнес-логику из route-level functions
- [ ] Убрать `sys.path` mutation и import-time `os.makedirs` из `books/routes.py`
- [ ] Прогнать тесты

### Task 8a: Exception Audit — Critical Paths (auth, security, payments)

**Зависит от:** Task 6

**Scope: только 4 модуля** (не все 327 вхождений):
- `app/auth/routes.py`
- `app/curriculum/security.py`
- `app/achievements/streak_service.py` (coin operations)
- `app/admin/main_routes.py`

- [ ] Заменить broad `except Exception` на конкретные exceptions где возможно
- [ ] В оставшихся broad catches — добавить `logger.exception()` с контекстом
- [ ] Убрать `pass` в security-critical paths — заменить на fail-closed (return error / re-raise)
- [ ] Проверить rollback/commit discipline
- [ ] Добавить тесты: exception в auth flow → пользователь не авторизуется (не silent pass)

### Task 8b: Exception Audit — Services and Background Jobs

**Зависит от:** Task 8a

**Scope:**
- `app/telegram/bot.py`
- `app/email_scheduler.py`
- `app/curriculum/services/*.py`
- `app/notifications/services.py`

- [ ] Те же правила что в 8a, но с фокусом на observability (logging), а не на fail-closed
- [ ] Background jobs: exception не должен убивать scheduler, но должен логироваться

### Task 9: Audit and Consolidate Legacy Data/Operations Artifacts

**Зависит от:** Task 7c (все refactor и exception audit завершены)

**Process:**
1. Составить manifest: для каждого файла в корне — `git blame` (кто/когда), `grep -r` (есть ли runtime-use), размер
2. Категоризировать: `needed` / `archive` / `delete`
3. Для `delete` — показать пользователю manifest и получить подтверждение
4. Для `archive` — перенести в `_archive/` директорию (gitignored)

**Candidate Removal List (привязан к этому task):**
- `celery_app.py` — удалён в Task 6
- `main.py` — удалён в Task 6
- `module_backups/` → archive
- root `coverage*.json` → delete
- root `missing_lessons.json` → delete
- root CSV dumps (`words_new_*.csv`, `new_word_*.csv`, `flashcards_all.csv`, `first.csv`) → delete
- root `module_mapping.csv`, `module_topics.csv` → archive если не используются runtime

- [ ] Составить manifest с evidence (grep + git blame) для каждого файла
- [ ] Получить подтверждение пользователя перед удалением
- [ ] Перенести archives в `_archive/`
- [ ] Проверить что `scripts/` реально используемые имеют usage notes
- [ ] Обновить `.gitignore` для `_archive/`

### Task 10: Documentation Realignment

**Зависит от:** Task 9

**Files:**
- Modify: `README.md`
- Modify: `docs/API.md`
- Modify: `docs/DATABASE.md`
- Modify: `docs/USAGE.md`
- Update: `CLAUDE.md`

- [ ] Привести docs к реальному состоянию проекта после cleanup
- [ ] Явно описать supported runtime stack (Python version, PostgreSQL, Redis if used)
- [ ] Явно описать operational workflows: migrate, seed, create admin, run tests, background jobs
- [ ] Добавить раздел "Deprecated / Archived" со ссылкой на `_archive/`
- [ ] Обновить `docs/API.md` — auth model после Task 4

### Task 11: Final Repository Cleanup Pass

**Зависит от:** все предыдущие tasks

- [ ] Удалить подтвержденные dead files
- [ ] Проверить что Docker, tests, app startup и docs согласованы
- [ ] Smoke checklist:
  - [ ] `docker compose up -d --build` → app starts, /health returns 200
  - [ ] `flask db upgrade head` на чистой БД → все таблицы созданы
  - [ ] `pytest tests/ -x` → проходит
  - [ ] `/api/login` → JWT работает
  - [ ] `/dashboard` → рендерится без ошибок
  - [ ] `/admin/` → табы работают, данные реальные
- [ ] Зафиксировать residual risks и deferred items в `docs/DEFERRED.md`

## Exit Criteria
- `create_app()` в production не мутирует БД и не стартует background services
- `create_app()` в TESTING mode создаёт таблицы через `db.create_all()` (оставлено намеренно)
- Alembic — единственный documented schema-management path для production
- API auth: единый `@api_auth_required` декоратор (JWT + session fallback)
- Test bootstrap работает из чистого окружения по README
- README/docs соответствуют реальному runtime
- `celery_app.py`, `main.py`, `setup_web.py` удалены
- `study/routes.py` разделён на 4 файла, каждый < 1000 строк
- Exception audit завершён для auth/security/coin paths (Task 8a scope)
- Confirmed dead files удалены, archives перемещены в `_archive/`
- Smoke checklist пройден
