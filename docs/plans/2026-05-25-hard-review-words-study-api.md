# Жесткое ревью текущих изменений словаря и Study API

## Overview

Провести жесткое ревью текущего git diff без установки дополнительных библиотек: найти реальные баги, регрессии, дыры в авторизации/данных, слабые тесты, UX/SEO-проблемы и исправить их маленькими проверяемыми шагами. Каждый пункт начинается с брейншторма рисков и гипотез, затем фиксируется в audit-журнале, покрывается тестами и только потом правится код.

## Context

- Files involved:
  - `app/study/api_routes.py`
  - `app/study/routes.py`
  - `app/words/detail_service.py`
  - `app/words/forms.py`
  - `app/words/routes.py`
  - `app/templates/words/_word_profile.html`
  - `app/templates/words/details_optimized.html`
  - `app/templates/words/list_optimized.html`
  - `app/templates/words/public_word.html`
  - `tests/test_public_words_seo.py`
  - `tests/test_words_routes.py`
  - `tests/api/test_study_api.py` if this test module is present and matches the API coverage
  - `docs/audits/2026-05-25-hard-review/README.md`
- Related patterns:
  - API errors through `api_error(code, message, status)`.
  - Flask test client and shared fixtures from `tests/conftest.py`.
  - PostgreSQL-aware tests; do not create local app instances.
  - Jinja escaping by default; no `|safe` for user-controlled text.
  - URL generation through `url_for`, without hardcoded domains.
  - For Python-file changes, verify imports after edits.
- Dependencies:
  - Do not add or install new dependencies.
  - Use only existing project tools: `pytest`, `ruff`, Flask test client, stdlib, `rg`, and `git diff`.

## Development Approach

- **Testing approach**: TDD for confirmed bugs: first add a failing/regression test, then fix the code.
- Complete each task fully before moving to the next.
- For every task:
  - start with a brainstorm of risks and hypotheses in `docs/audits/2026-05-25-hard-review/README.md`;
  - add or update tests;
  - make the minimal code fix;
  - run the targeted test command for that task.
- No new libraries, no architecture expansion for future needs, no cosmetic refactor-only changes.
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Зафиксировать review baseline и карту рисков

**Files:**
- Create: `docs/audits/2026-05-25-hard-review/README.md`
- Modify: `tests/test_words_routes.py`
- Modify: `tests/test_public_words_seo.py`

- [x] Брейншторм: выписать все измененные entry points из `git diff --name-only`, разделить риски на P0/P1/P2: auth/data leak, SRS correctness, XSS/escaping, SEO, N+1/performance, broken empty states.
- [x] Создать audit-журнал с таблицей findings: id, severity, file, hypothesis, evidence, fix, test, status.
- [x] Добавить baseline tests для основных измененных страниц словаря: word list, authenticated detail, public word page.
- [x] Добавить baseline tests, которые проверяют, что публичная SEO-страница слова отдает title/meta/canonical без 500.
- [x] Записать в audit-журнал, какие риски покрыты baseline tests, а какие пойдут в следующие Task.
- [x] Run `pytest tests/test_words_routes.py tests/test_public_words_seo.py -q`.

### Task 2: Проверить Study API и SRS-логику word_detail

**Files:**
- Modify: `app/study/api_routes.py`
- Modify: `app/study/routes.py`
- Modify: `tests/test_words_routes.py`
- Modify: `tests/api/test_study_api.py` if the existing test layout fits better

- [x] Брейншторм: перечислить состояния `word_source=word_detail`: отсутствующий `word_id`, чужое слово, несуществующее слово, buried card, overdue card, future due card, `extra_study=true`, new/review limits.
- [x] Добавить tests на `word_source=word_detail`: не возвращает чужие слова, не падает без `word_id`, корректно работает с `extra_study`, не обходит buried cards.
- [x] Проверить, что `due_filter = None` не открывает лишние карточки вне выбранного `word_id`.
- [x] Проверить, что API использует существующий формат ошибок через `api_error`, без ad-hoc JSON.
- [x] Исправить найденные дефекты минимально в API/routes, не меняя публичный контракт без необходимости.
- [x] Run `pytest tests/test_words_routes.py tests/api/test_study_api.py -q`.

### Task 3: Проверить words service/forms/routes на корректность данных

**Files:**
- Modify: `app/words/detail_service.py`
- Modify: `app/words/forms.py`
- Modify: `app/words/routes.py`
- Modify: `tests/test_words_routes.py`

- [x] Брейншторм: перечислить грязные данные для словаря: `None`, пустые строки, `"null"`, `"[]"`, дубли synonyms/antonyms, нет audio, нет level/frequency, слово без связей с books/topics/collections.
- [x] Добавить unit tests для нормализации profile data: empty text cleanup, list cleanup, frequency labels, review time formatting, semantic hints.
- [x] Добавить route tests для поиска/фильтров/пагинации словаря, если измененный код влияет на query-string или форму.
- [x] Проверить routes на authorization boundaries: private user word detail не должен стать публичным через новые helper-данные.
- [x] Проверить запросы на явные N+1 в новых связанных данных; использовать существующие eager-loading patterns, если дефект подтвержден.
- [x] Исправить найденные дефекты в сервисе/forms/routes.
- [x] Run `pytest tests/test_words_routes.py -q`.

### Task 4: Проверить templates на XSS, UX-регрессии и SEO

**Files:**
- Modify: `app/templates/words/_word_profile.html`
- Modify: `app/templates/words/details_optimized.html`
- Modify: `app/templates/words/list_optimized.html`
- Modify: `app/templates/words/public_word.html`
- Modify: `tests/test_public_words_seo.py`
- Modify: `tests/test_words_routes.py`

- [x] Брейншторм: перечислить dangerous template inputs: English word, translation, usage context, etymology, synonyms, antonyms, user notes, book titles, topic names.
- [x] Добавить render tests с HTML-like payload в слове и проверить, что пользовательский текст escaped, а не исполняется как markup.
- [x] Добавить tests на empty states: нет synonyms, нет etymology, нет audio, нет related books/topics.
- [x] Добавить SEO tests для public word page: canonical, title, description, no private-only controls.
- [x] Исправить template defects: убрать небезопасный `safe`, broken links, hardcoded URLs, private UI на публичной странице, если найдено.
- [x] Run `pytest tests/test_public_words_seo.py tests/test_words_routes.py -q`.

### Task 5: Свести findings, убрать мертвый код и закрыть регрессии

**Files:**
- Modify: `docs/audits/2026-05-25-hard-review/README.md`
- Modify: `app/study/api_routes.py` if findings remain
- Modify: `app/study/routes.py` if findings remain
- Modify: `app/words/detail_service.py` if findings remain
- Modify: `app/words/forms.py` if findings remain
- Modify: `app/words/routes.py` if findings remain
- Modify: `tests/test_words_routes.py`
- Modify: `tests/test_public_words_seo.py`

- [x] Брейншторм: пройти все unresolved findings и решить для каждого: fix now, false positive with evidence, or defer with explicit reason.
- [x] Проверить `rg` по новым helper names и template variables: нет неиспользуемых функций, дублирующих branches, stale imports.
- [x] Добавить regression tests для каждого исправленного P0/P1 finding, если они не были добавлены в предыдущих Task.
- [x] Выполнить import checks: `python -c "import app.words.detail_service; import app.words.routes; import app.study.api_routes"`.
- [x] Обновить audit-журнал: все fixed findings должны ссылаться на test name или команду проверки.
- [x] Run `pytest tests/test_words_routes.py tests/test_public_words_seo.py -q`.

### Task 6: Verify acceptance criteria

**Files:**
- Modify: `docs/audits/2026-05-25-hard-review/README.md`
- Modify: tests only if final verification exposes uncovered defects

- [x] Брейншторм: финальный pass по критериям приемки: нет новых зависимостей, каждый Task имеет tests, P0/P1 закрыты, P2 либо закрыты, либо явно задокументированы.
- [x] Run `git diff -- requirements.txt requirements-test.txt pyproject.toml` and confirm no new dependency was added.
- [x] Run `ruff check app/study/api_routes.py app/study/routes.py app/words/detail_service.py app/words/forms.py app/words/routes.py tests/test_words_routes.py tests/test_public_words_seo.py` (skipped - `ruff` is not installed in the active environment; exact command attempted and documented in the audit).
- [x] Run `pytest tests/test_words_routes.py tests/test_public_words_seo.py tests/api/test_study_api.py -q`.
- [x] Run `pytest -m smoke -q`.
- [x] Run full test suite: `pytest tests/ -q --timeout=60`.
- [x] Verify coverage does not regress below the project target: use the existing coverage workflow if present; otherwise document the coverage-command gap in the audit journal (documented - no tracked coverage target/workflow is configured).

### Task 7: Update documentation

**Files:**
- Modify: `docs/audits/2026-05-25-hard-review/README.md`
- Modify: `README.md` only if user-facing behavior changed
- Modify: `CLAUDE.md` only if internal patterns changed

- [x] Брейншторм: определить, появились ли новые project patterns или только локальные fixes.
- [x] Финализировать audit-журнал: summary, fixed findings count, remaining risks, commands run, test status.
- [x] Update `README.md` only if public/user-facing word page behavior or study flow changed (not changed - README has no word-page/study-flow behavior section to update).
- [x] Update `CLAUDE.md` only if появился новый внутренний паттерн, который будущим задачам нужно соблюдать (not changed - existing API error and URL rules cover the reviewed fixes).
- [x] Run documentation-related tests if changed: `pytest tests/docs -q`.
- [x] Run targeted tests again after docs-only changes if no docs tests exist: `pytest tests/test_words_routes.py tests/test_public_words_seo.py -q` (skipped - docs tests exist and passed).
