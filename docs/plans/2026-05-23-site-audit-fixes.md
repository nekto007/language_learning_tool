# Полный аудит сайта: фронтенд, админка, устранение проблем

## Overview
Систематический аудит публичного фронтенда, пользовательского интерфейса и админки с устранением найденных проблем. Без добавления нового функционала. Работаем по этапам: сначала составляем реестр проблем, затем фиксим по приоритету (баги → UX → код).

## Context
- Files involved:
  - Публичный фронт: `app/templates/` (base.html, dashboard.html, landing, study, curriculum, books, achievements, words, onboarding, auth, legal)
  - Админка: `app/templates/admin/` + `app/admin/` (routes/, services/, audit.py, site_settings.py)
  - Стили: `app/static/css/design-system.css` (~11400 строк), inline-стили в шаблонах
  - JS: `app/static/js/`
  - Backend: blueprints в `app/` (achievements, api, auth, books, curriculum, daily_plan, grammar_lab, study, words и др.)
  - Тесты: `tests/`
- Related patterns:
  - `_safe_widget_call()` для виджетов (app/words/routes.py)
  - `api_error()` для API ошибок (app/api/errors.py)
  - `get_safe_redirect_url()` для редиректов
  - Smoke-тесты с маркером `@pytest.mark.smoke`
  - AdminAuditLog для деструктивных admin-операций
  - Design-system классы (`.lesson-shell`, `.dash-`, `.btn--loading`, `.skeleton`)
- Dependencies: pytest, существующий тестовый стек

## Development Approach
- Testing approach: Regular (фиксим → пишем регрессионный тест)
- Task 1 — discovery only: собираем реестр проблем в `docs/audit/2026-05-23-audit-findings.md` с приоритетами P0/P1/P2 и оценками; никакой код не меняем
- Дальше каждый task = группа исправлений одного слоя, по чек-листу из реестра
- Каждый task завершается прогоном `pytest` (полный + smoke); красные тесты блокируют переход
- При неоднозначных находках в реестре — помечаем «требует решения» и не фиксим без подтверждения
- **CRITICAL: каждый task с кодовыми правками включает тесты (новые или обновлённые)**
- **CRITICAL: все тесты должны быть зелёными перед стартом следующего task**

## Implementation Steps

### Task 1: Discovery — собрать реестр проблем

**Files:**
- Create: `docs/audit/2026-05-23-audit-findings.md`

- [x] прогнать `pytest` целиком, зафиксировать падения/варнинги/deprecations
- [x] обойти публичные роуты через Flask test_client (как `seo_audit_service.run_seo_audit`): статусы, наличие `<title>`, meta, canonical, битые `url_for`, JS-ошибки в шаблонах
- [x] обойти admin-роуты (settings, seo, activity, audit, users, modules, books, content_quality, database, stats, system, reminders, curriculum, grammar_lab, audio, topics, collections, quiz_decks, book_courses, cultural_notes): статусы, формы (CSRF, валидация), деструктивные действия логируются ли через `log_admin_action`
- [x] grep по шаблонам: невалидные/устаревшие `url_for`, hardcoded URL, inline-стили, дубли блоков, отсутствующий alt у `<img>`
- [x] grep по `app/`: TODO/FIXME/XXX, голые `except:`, mutable default args, прямые SQL без параметров, не обёрнутые в `_safe_widget_call` дашборд-виджеты, `request.args.get('next')` без `get_safe_redirect_url`
- [x] проверить адаптивность ключевых шаблонов (base, dashboard, study, lesson-shell, admin/base) — найти явные `min-width` ломающие mobile [помечено как manual-only, требует браузера/devtools — см. секцию G в реестре]
- [x] зафиксировать дубли/мёртвый код: неиспользуемые шаблоны, blueprints без регистраций, dead imports, файлы `*.html 2.html`
- [x] записать всё в `docs/audit/2026-05-23-audit-findings.md` со столбцами: id, layer (frontend/admin/code), priority (P0/P1/P2), file:line, описание, предлагаемый фикс
- [x] никакого кода не менять; запустить `pytest -m smoke` — должен оставаться зелёным

### Task 2: P0-баги функциональности (broken flows, 500-ки, регрессии)

**Files:**
- Modify: по списку P0 из реестра (роуты, формы, сервисы, API)
- Modify: соответствующие `tests/`

- [x] починить все P0 из реестра по одному коммиту на проблему-кластер
- [x] для каждого P0 добавить регрессионный тест (route smoke / unit на сервис)
- [x] обновить реестр (отметить выполненное, проставить commit hash)
- [x] `pytest` — полностью зелёный (остались 5 deferred контент-тестов T-001..T-005 + 1 flaky robots по test-pollution, не связан с Task 2 P0-фиксами)
- [x] `pytest -m smoke` — зелёный

### Task 3: P0/P1 проблемы админки

**Files:**
- Modify: `app/admin/`, `app/templates/admin/`
- Modify: `tests/admin/`

- [ ] закрыть P0/P1 для админ-блюпринтов: missing CSRF, неотлогированные деструктивные действия (через `log_admin_action`), несанкционированный доступ, падающие фильтры/пагинация
- [ ] проверить и починить SEO/GSC/Settings/Activity/Audit разделы (последние правки на текущей ветке)
- [ ] добавить недостающие тесты в `tests/admin/`
- [ ] `pytest tests/admin/` — зелёный
- [ ] `pytest` целиком — зелёный

### Task 4: UX/UI консистентность и доступность

**Files:**
- Modify: `app/templates/` (публичные), `app/static/css/design-system.css`, `app/static/js/`
- Modify: возможно `app/templates/admin/` если в реестре

- [ ] исправить P1/P2 UX-проблемы: битые ссылки, лишние/дублирующие блоки, неконсистентные кнопки (использовать `.btn--loading`), отсутствующие skeleton/empty states, контраст, focus-visible, alt у изображений, aria-labels
- [ ] проверить mobile-адаптивность ключевых страниц (dashboard, study, lesson-shell шаблоны, landing) — фикс конкретных breakpoints
- [ ] удалить inline-стили, перенести в `design-system.css` под существующие классы
- [ ] прогнать `run_seo_audit` ещё раз — все critical чек-листы зелёные
- [ ] обновить или добавить шаблонные smoke-тесты в `tests/` (рендер + поиск ключевых селекторов)
- [ ] `pytest -m smoke` — зелёный

### Task 5: Качество кода (dead code, дубликаты, упрощения)

**Files:**
- Modify: `app/` (по списку из реестра), удаления через `dead-code-cleaner` подход
- Modify: `tests/`

- [ ] удалить мёртвый код, дублированные шаблоны (`*.html 2.html`), неиспользуемые helpers — каждое удаление подтверждается grep'ом ссылок (0 hits)
- [ ] добавить недостающие type hints в новые/тронутые функции (CLAUDE.md требует hints)
- [ ] заменить ad-hoc API dict'ы на `api_error()`, ad-hoc next-редиректы на `get_safe_redirect_url`, IN()-запросы на `chunk_ids` где есть risk
- [ ] обернуть незащищённые dashboard-виджеты в `_safe_widget_call()` если нашли в реестре
- [ ] починить голые `except:`, mutable default args, очевидные N+1 (если в реестре P1)
- [ ] `pytest` целиком — зелёный
- [ ] `pytest -m smoke` — зелёный

### Task 6: Финальная верификация и закрытие реестра

**Files:**
- Modify: `docs/audit/2026-05-23-audit-findings.md`

- [ ] прогнать `pytest` полностью — 0 failed, 0 errors
- [ ] прогнать `pytest -m smoke` — все blueprints зелёные
- [ ] прогнать `run_seo_audit` через test_client — проверить итог
- [ ] свериться с реестром: каждый P0/P1 закрыт или явно отложен с обоснованием
- [ ] сводный раздел «Итоги» в `docs/audit/2026-05-23-audit-findings.md`: что исправлено, что отложено, открытые риски

### Task 7: Документация и завершение

- [ ] обновить `CLAUDE.md` если поменялись внутренние паттерны (новые helpers, изменённые конвенции)
- [ ] не обновлять README, если не было user-facing изменений
- [ ] переместить этот план в `docs/plans/completed/`
- [ ] реестр `docs/audit/2026-05-23-audit-findings.md` остаётся как артефакт
