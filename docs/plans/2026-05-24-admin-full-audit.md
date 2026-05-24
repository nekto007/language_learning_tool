# Полный аудит админки: безопасность, производительность, UX, качество, тесты, observability

## Overview

Сквозной аудит-фиксы по всем секциям админки (`app/admin/`, `app/templates/admin/`, `tests/admin/`). Каждая таска — это аудит одного среза или подсистемы с немедленным исправлением найденных проблем и добавлением/обновлением тестов. Цель — после прохода всех ~30 тасок админка имеет согласованную безопасность (auth/CSRF/audit), производительность (без N+1, с пагинацией и кэшем), UX (consistent layout/feedback), code quality (без backup'ов, дублирования, мёртвого кода), >=80% покрытие admin-модулей и осмысленное логирование/метрики.

## Context

- Корневые директории: `app/admin/` (5221 LOC routes + services + utils), `app/templates/admin/` (15 поддиректорий), `tests/admin/` (15 тест-файлов)
- Ключевые подсистемы routes: `main_routes.py` (1435 LOC — рефакторить), `routes/{activity,audio,audit,book,collection,curriculum,grammar_lab,seo,settings,system,topic,user,word}_routes.py`
- Services: `activity_feed_service`, `audio_management_service`, `book_processing_service`, `cohort_service`, `curriculum_import_service`, `gsc_service`, `linear_plan_metrics`, `seo_audit_service`, `system_service`, `user_management_service`, `word_management_service`
- Существующие паттерны (CLAUDE.md): `AdminAuditLog` + `log_admin_action`, `SiteSettings.get/set`, `_sanitize_csv_cell` + MAX_EXPORT_ROWS=10000, sub-blueprints через `register_admin_routes`, `chunk_ids`, `api_error`
- Auth-декораторы: `app/admin/utils/decorators.py`
- Связанные тесты: `tests/admin/test_*.py` (audit, gsc, settings, cohort, dau_wau_cache, dashboard, users, content_quality)

## Development Approach

- Testing approach: Regular — сначала фикс, затем добавление/обновление тестов в `tests/admin/`
- Каждая таска самодостаточна (можно мержить отдельно), формат «аудит-чеклист → фикс → тест»
- В начале каждой таски — собрать findings (короткий внутренний отчёт в комментариях коммита/PR), затем сразу применить фиксы
- Все деструктивные admin-операции должны логироваться через `log_admin_action`
- Использовать `@pytest.mark.smoke` для одного happy-path теста на каждый отрефакторенный модуль
- CRITICAL: каждая таска MUST включать новые/обновлённые тесты
- CRITICAL: все тесты должны проходить (`pytest tests/admin/ -x`) до начала следующей таски

## Implementation Steps

### Task 1: Инвентаризация и базовая аудит-инфраструктура

**Files:**
- Create: `docs/audits/2026-05-24-admin-audit/README.md` (живой findings-журнал на весь аудит)
- Modify: `app/admin/utils/decorators.py`

- [x] построить карту admin URL-tree: enumerate всех `@bp.route` через AST-скрипт, выписать (метод, URL, view, blueprint, auth-декоратор) в `docs/audits/2026-05-24-admin-audit/url-map.md`
- [x] выписать список всех services / templates / forms / тестов с LOC и связями
- [x] добавить `admin_required` (если уже есть — нормализовать) и `admin_audit_required(action_name)` декораторы, документировать в `app/admin/utils/decorators.py`
- [x] написать тест `tests/admin/test_admin_url_inventory.py`: assert каждая admin-роут защищена `admin_required` (либо явный whitelist для login)
- [x] прогнать `pytest tests/admin/ -x`

### Task 2: Аудит auth/admin-gate на всех routes

**Files:**
- Modify: `app/admin/main_routes.py`, `app/admin/routes/*.py`

- [x] прогнать тест из Task 1, зафиксить все роуты без admin-гейта
- [x] убедиться, что view-функции не возвращают 200 анонимам/обычным юзерам (curl smoke в `tests/admin/test_admin_access_control.py`)
- [x] добавить тест для каждой подгруппы blueprint (parametrize по URL)
- [x] прогнать `pytest tests/admin/test_admin_access_control.py`

### Task 3: CSRF coverage на всех POST/PUT/DELETE

**Files:**
- Modify: `app/templates/admin/**/*.html`, `app/admin/routes/*.py`

- [x] аудит каждой формы и AJAX POST: убедиться, что `{{ csrf_token() }}` присутствует, JS отправляет `X-CSRFToken`
- [x] для JSON endpoints — `@csrf.exempt` запрещён; использовать `validate_csrf`
- [x] починить найденные пропуски
- [x] обновить/добавить тесты в `tests/admin/test_task3_admin_audit_csrf.py` (parametrize по всем mutating endpoints)
- [x] прогнать `pytest tests/admin/test_task3_admin_audit_csrf.py`

### Task 4: Покрытие деструктивных операций AdminAuditLog

**Files:**
- Modify: `app/admin/routes/{user,book,word,topic,curriculum,collection,grammar_lab,audio,seo,settings,system}_routes.py`, `app/admin/main_routes.py`

- [x] найти все DELETE/UPDATE handlers (модели, пользователи, words, modules, lessons, collections, settings, OAuth tokens) и обеспечить вызов `log_admin_action(admin_id, action, target)`
- [x] унифицировать имена actions (snake_case, `entity.action`)
- [x] тесты `tests/admin/test_audit_log_coverage.py` — parametrize: дернуть каждый mutating endpoint, assert строка в `AdminAuditLog`
- [x] прогнать тесты

### Task 5: Sanitize input + защита от SQL/HTML injection

**Files:**
- Modify: `app/admin/routes/{user,word,book,topic}_routes.py`, `app/admin/services/*.py`

- [x] grep сырых строковых конкатенаций в SQL (`text(f"...")`), заменить на bindparam/SQLAlchemy
- [x] аудит шаблонов на `|safe`, `{% autoescape false %}` — обосновать или убрать
- [x] валидация query-params: integer/enum cast через `validate_enum` и `int(...)` с try/except
- [x] тесты `tests/admin/test_input_validation.py` — невалидные params → 400
- [x] прогнать тесты

### Task 6: Redirect safety + open-redirect в админке

**Files:**
- Modify: `app/admin/routes/user_routes.py`, `app/admin/main_routes.py`

- [x] аудит `request.args.get('next')` / `redirect(url)` — везде через `get_safe_redirect_url`
- [x] тест `tests/admin/test_redirect_safety.py` (external `?next=https://evil` блокируется)
- [x] прогнать тесты

### Task 7: Рефакторинг main_routes.py (1435 LOC) — выделение sub-blueprints

**Files:**
- Modify: `app/admin/main_routes.py`, `app/admin/routes/__init__.py`
- Delete: `app/admin/main_routes.py.backup`

- [x] удалить `main_routes.py.backup` (мёртвый файл)
- [x] перенести dashboard/stats/cache-related routes в `app/admin/routes/dashboard_routes.py`
- [x] зарегистрировать новый sub-blueprint в `register_admin_routes`
- [x] обновить `_ONBOARDING_SKIP_PREFIXES` если нужно
- [x] перенести/расширить тесты `tests/admin/test_dashboard_stats.py`
- [x] прогнать `pytest tests/admin/`

### Task 8: Dashboard performance — DAU/WAU/MAU и кэш

**Files:**
- Modify: `app/admin/main_routes.py` (или новый `dashboard_routes.py`), `tests/admin/test_dau_wau_cache.py`

- [x] аудит `_count_active_users_in_range`, `_active_user_ids_for_date` на повторные UNION/timeouts
- [x] вынести расчёт в materialized helper с TTL-кэшем; проверить, что cache key не race-y
- [x] добавить query-counter тест (`SQLALCHEMY_RECORD_QUERIES`) — assert <= N запросов на dashboard
- [x] прогнать тесты

### Task 9: User-list pagination + поиск

**Files:**
- Modify: `app/admin/routes/user_routes.py`, `app/templates/admin/users.html`, `app/templates/admin/user_detail.html`

- [x] аудит на N+1 в списке юзеров (last_login, statistics joinedload)
- [x] стандартизировать пагинацию (limit/offset через `flask_sqlalchemy.Pagination`), параметры `page`, `per_page`, max=100
- [x] поиск по email/username с экранированием
- [x] обновить `tests/admin/test_user_list_pagination.py` и `test_user_management_detail.py`
- [x] прогнать тесты

### Task 10: Books admin (734 LOC route) — рефакторинг + аудит

**Files:**
- Modify: `app/admin/routes/book_routes.py`, `app/admin/services/book_processing_service.py`, `app/templates/admin/books/*.html`

- [x] выделить тяжёлые методы (process/upload/parse) в `book_processing_service`
- [x] аудит upload: проверка MIME, размер, путь сохранения (защита от path traversal)
- [x] N+1 на chapter list — joinedload
- [x] тесты `tests/admin/routes/test_book_routes.py` (новый файл)
- [x] прогнать тесты

### Task 11: Words admin — bulk-операции и CSV

**Files:**
- Modify: `app/admin/routes/word_routes.py`, `app/admin/services/word_management_service.py`, `app/admin/utils/export_helpers.py`

- [x] аудит bulk delete/update: транзакция + `log_admin_action` per batch
- [x] CSV export — sanitize `=+@-`, MAX_EXPORT_ROWS=10000, streaming
- [x] аудит CSV import (utils/import_helpers): валидация заголовков, UTF-8 BOM, ошибки построчно
- [x] обновить `tests/admin/test_batch_operations.py`
- [x] прогнать тесты

### Task 12: Curriculum admin (modules/lessons) — JSON-валидация

**Files:**
- Modify: `app/admin/routes/curriculum_routes.py`, `app/admin/curriculum.py`, `app/admin/modules.py`, `app/admin/services/curriculum_import_service.py`

- [x] аудит формы редактирования lesson content — провалидировать через `validate_exercise_content` и lesson-type schemas
- [x] миграция module/lesson order — гарантировать unique constraint
- [x] тесты `tests/admin/routes/test_curriculum_routes.py`
- [x] прогнать тесты

### Task 13: Grammar Lab admin (729 LOC) — split + аудит

**Files:**
- Modify: `app/admin/routes/grammar_lab_routes.py`, `app/templates/admin/grammar_lab/*.html`

- [x] разделить routes по domain (topics, exercises, attempts review) в подмодули или region-комментарии
- [x] аудит на cascade при удалении exercise (см. `20260425_grammar_exercise_cascade`)
- [x] тесты `tests/admin/routes/test_grammar_lab_routes.py`
- [x] прогнать тесты

### Task 14: Audio admin — длинные операции и safety

**Files:**
- Modify: `app/admin/routes/audio_routes.py`, `app/admin/services/audio_management_service.py`

- [x] аудит mass-generate: rate limit / progress feedback / fail-safe (частичный коммит)
- [x] проверка путей сохранения mp3 (no traversal), очистка orphan-файлов
- [x] тесты `tests/admin/routes/test_audio_routes.py`
- [x] прогнать тесты

### Task 15: SEO + GSC admin — OAuth и cache

**Files:**
- Modify: `app/admin/routes/seo_routes.py`, `app/admin/services/{gsc_service,seo_audit_service}.py`

- [x] аудит OAuth flow: state parameter, токены хранятся через SiteSettings (не plaintext в логах), `disconnect` чистит все ключи
- [x] seo_audit_service: per-worker cache → переключить на общий backend (Redis/file) или явно задокументировать ограничение
- [x] тесты `tests/admin/test_gsc.py` + `tests/admin/routes/test_seo_routes.py` (флоу авторизации с моком)
- [x] прогнать тесты

### Task 16: Settings/Feature-flags admin

**Files:**
- Modify: `app/admin/routes/settings_routes.py`, `app/admin/site_settings.py`, `app/templates/admin/settings/*.html`

- [x] аудит SETTING_DEFAULTS — добавить tooltips/описания в UI
- [x] валидация типов value (bool/int/json) перед записью
- [x] audit-log на каждое изменение
- [x] обновить `tests/admin/test_settings_routes.py` и `test_site_settings.py`
- [x] прогнать тесты

### Task 17: System / Database admin — opasные операции

**Files:**
- Modify: `app/admin/routes/system_routes.py`, `app/admin/services/system_service.py`, `app/templates/admin/{system,database}.html`

- [x] аудит endpoints запускающих миграции/cache-clear/db-dump — требовать confirmation token, rate limit
- [x] hide raw connection strings
- [x] тесты `tests/admin/routes/test_system_routes.py`
- [x] прогнать тесты

### Task 18: Topics + Collections admin

**Files:**
- Modify: `app/admin/routes/{topic,collection}_routes.py`, `app/templates/admin/{topics,collections}/*.html`

- [x] аудит CRUD на N+1, валидацию slug uniqueness
- [x] audit-log на mutation
- [x] тесты `tests/admin/routes/test_topic_collection_routes.py`
- [x] прогнать тесты

### Task 19: Activity Feed + Cohort + Funnel — perf и точность

**Files:**
- Modify: `app/admin/routes/activity_routes.py`, `app/admin/services/{activity_feed_service,cohort_service}.py`

- [x] аудит agg-запросов: индексы, LIMIT/OFFSET на больших таблицах, naive vs aware datetime (см. CLAUDE.md)
- [x] корректность funnel monotonicity (тесты edge: 0 пользователей, 1 пользователь)
- [x] обновить `tests/admin/test_cohort_service.py`, `test_activity_metrics.py`
- [x] прогнать тесты

### Task 20: Audit log UI — пагинация, фильтры, экспорт

**Files:**
- Modify: `app/admin/routes/audit_routes.py`, `app/admin/audit.py`, `app/templates/admin/audit/index.html`

- [x] фильтры по admin/action/date, пагинация, CSV-export с `_sanitize_csv_cell`
- [x] обновить `tests/admin/test_audit.py`
- [x] прогнать тесты

### Task 21: Linear plan metrics + admin inspector

**Files:**
- Modify: `app/admin/services/linear_plan_metrics.py`, `app/templates/admin/linear_plan_user.html`

- [x] аудит запросов на крупной cohort (>10k users) — добавить агрегацию через SQL, не Python loops; `chunk_ids` где нужно
- [x] обновить `tests/admin/test_linear_plan_metrics.py`, `test_linear_plan_user_inspector.py`
- [x] прогнать тесты

### Task 22: Шаблоны админки — единый layout/UX

**Files:**
- Modify: `app/templates/admin/base.html`, `app/templates/admin/components.html`, все sub-шаблоны

- [x] проверить наличие breadcrumbs, единый header, flash messages, кнопки `.btn--loading`
- [x] добавить empty states + skeleton loaders где есть async load
- [x] проверить responsive (узкие колонки таблиц)
- [x] smoke-тест рендера ключевых шаблонов в `tests/admin/test_templates_smoke.py`
- [x] прогнать тесты

### Task 23: Accessibility (WCAG) для админки

**Files:**
- Modify: `app/templates/admin/base.html`, `app/templates/admin/**/*.html`

- [x] aria-labels на иконки/sort headers, focus-visible, контраст цветов
- [x] keyboard navigation для drop-down/dialog
- [x] тесты `tests/admin/test_accessibility.py` (smoke-проверка наличия aria-атрибутов в ключевых страницах)
- [x] прогнать тесты

### Task 24: Observability — структурированные логи

**Files:**
- Modify: `app/admin/routes/*.py`, `app/admin/services/*.py`

- [x] везде где есть исключения / fallback'и — `current_app.logger.warning/error` с контекстом (admin_id, target, action)
- [x] заменить `print(...)` на logger
- [x] тесты `tests/admin/test_observability.py` (caplog: assert лог при критических операциях)
- [x] прогнать тесты

### Task 25: Rate limiting на критических endpoints

**Files:**
- Modify: `app/admin/utils/decorators.py`, `app/admin/routes/{audio,system,seo}_routes.py`

- [ ] подключить Flask-Limiter (если ещё нет) для генерации аудио, миграций, OAuth callback
- [ ] тесты `tests/admin/test_rate_limit.py` (превышение → 429)
- [ ] прогнать тесты

### Task 26: Кэш-инвалидация и cache.py review

**Files:**
- Modify: `app/admin/utils/cache.py`

- [ ] аудит TTL, ключей, per-worker vs shared (см. SEO audit cache замечание)
- [ ] явный invalidate-button с audit-log
- [ ] тесты `tests/admin/test_cache.py`
- [ ] прогнать тесты

### Task 27: Удаление мёртвого кода и duplicate-файлов

**Files:**
- Delete: `app/admin/main_routes.py.backup`, `app/templates/admin/book_courses` (если duplicate с books)
- Modify: `app/admin/{book_courses,form,modules,quiz_decks,curriculum,secret_store}.py`

- [ ] grep-аудит — найти неимпортируемые модули/функции в `app/admin/`
- [ ] удалить с проверкой 0 ссылок (см. CLAUDE.md "перед удалением — grep ВСЕ импорты")
- [ ] прогнать `pytest tests/admin/`

### Task 28: Improve admin error pages

**Files:**
- Modify: `app/admin/__init__.py` или новый `app/admin/error_handlers.py`, `app/templates/admin/errors/{403,404,500}.html`

- [ ] кастомные admin 403/404/500 шаблоны с правильным branding и линком назад в hub
- [ ] hook через `bp.app_errorhandler` или `bp.errorhandler`
- [ ] тесты `tests/admin/test_error_pages.py`
- [ ] прогнать тесты

### Task 29: Test coverage gap-анализ

**Files:**
- Modify: `tests/admin/*` (новые файлы)

- [ ] прогнать `pytest --cov=app.admin --cov-report=term-missing tests/admin/`
- [ ] для модулей с покрытием <80% — добавить тесты до 80%
- [ ] добавить `@pytest.mark.smoke` на ключевые happy-path тесты каждой секции
- [ ] прогнать `pytest -m smoke`

### Task 30: Verify acceptance criteria

- [ ] прогнать полный `pytest` (включая `tests/admin/`)
- [ ] прогнать линтер (`ruff check app/admin tests/admin`)
- [ ] прогнать `pytest --cov=app.admin --cov-fail-under=80`
- [ ] вручную пройти каждую страницу админки в браузере (golden path), зафиксировать остаточные баги в `docs/audits/2026-05-24-admin-audit/README.md`
- [ ] прогнать `pytest -m smoke` (<30с)

### Task 31: Update documentation

- [ ] обновить CLAUDE.md секцию "Admin sub-blueprints" если изменены paths
- [ ] обновить `docs/audits/2026-05-24-admin-audit/README.md` финальным резюме
- [ ] переместить план в `docs/plans/completed/`
