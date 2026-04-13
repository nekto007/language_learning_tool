# Переработка тестов: скорость + покрытие критичных модулей

## Overview

Полная переработка тестовой инфраструктуры: устранение 19 "островных" тест-файлов с дублированием app fixture, переход на transaction rollback cleanup, добавление маркеров для быстрого smoke-прогона, и покрытие тестами критичных модулей где баги чаще всего утекают в прод (telegram routes, grammar_lab API, words routes).

## Context

- Files involved: `tests/conftest.py`, 19 island test files, `pytest.ini`, + новые тест-файлы для непокрытых модулей
- Related patterns: session-scoped `app` fixture, function-scoped `db_session` с DELETE cleanup, pytest-xdist поддержка
- Dependencies: pytest, pytest-xdist (уже есть)

## Current State

- 3232 теста, ~144 файла, ~49k строк тестового кода
- 19 файлов создают собственный `app` instance вместо shared session-scoped — лишние вызовы `create_app()` + `db.create_all()` + ALTER TABLE introspection
- `db_session` делает DELETE по 6 таблицам перед каждым тестом вместо transaction rollback
- Маркеры `@pytest.mark.slow` и `@pytest.mark.integration` объявлены но не используются (0 и 1 соответственно)
- Непокрытые роуты: telegram (4 HTTP endpoints), grammar_lab API (11 endpoints), words (word list/detail/status update)

## Development Approach

- **Testing approach**: Regular (рефакторинг инфраструктуры, потом добавление тестов)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Переход db_session на transaction rollback (savepoint pattern)

**Files:**
- Modify: `tests/conftest.py`

- [x] Заменить DELETE-based cleanup в `db_session` на nested transaction + savepoint pattern: BEGIN → SAVEPOINT перед тестом → ROLLBACK TO SAVEPOINT после теста
- [x] Убедиться что pattern совместим с pytest-xdist (каждый worker имеет свой connection)
- [x] Добавить fallback: если тест явно вызывает `session.commit()`, savepoint должен корректно обрабатывать это (nested transaction via `begin_nested()`)
- [x] Запустить полный тест-сьют, убедиться что все 3232 теста проходят
- [x] Замерить время до и после — записать в progress log

### Task 2: Консолидация 19 island test files на shared app fixture

**Files:**
- Modify: `tests/test_landing_improvements.py`, `tests/test_telegram_viral.py`, `tests/test_seo_meta.py`, `tests/test_public_words_seo.py`, `tests/test_quiz_sharing.py`, `tests/test_share_buttons.py`, `tests/test_levelup_celebration.py`, `tests/test_word_of_day.py`, `tests/test_streak_milestones.py`, `tests/test_public_courses.py`, `tests/test_notifications.py`, `tests/test_cross_linking.py`, `tests/test_onboarding_personalization.py`, `tests/test_public_profile.py`, `tests/test_improved_registration.py`, `tests/test_reengagement_emails.py`, `tests/test_public_streak.py`, `tests/test_acceptance_criteria.py`, `tests/test_grammar_seo.py`

- [x] Удалить локальные `app`, `client` fixtures из каждого файла — перевести на shared `app`/`client` из conftest.py
- [x] Перенести нужную setup-логику (ALTER TABLE, специфичные данные) в conftest.py fixtures или в setup методы тестовых классов
- [x] Убедиться что все тесты в этих файлах проходят с shared fixtures
- [x] Запустить полный тест-сьют

### Task 3: Добавить маркеры и конфигурацию для быстрого smoke-прогона

**Files:**
- Modify: `pytest.ini`
- Modify: `tests/conftest.py`

- [x] Добавить `@pytest.mark.smoke` маркер в pytest.ini
- [x] Пометить ~50-100 ключевых тестов как `@pytest.mark.smoke` — по 2-5 тестов на каждый blueprint (основные happy path: GET главных страниц, POST ключевых API)
- [x] Добавить `@pytest.mark.slow` на тесты которые создают много данных или делают сложные setup
- [x] Обновить pytest.ini: добавить команду `pytest -m smoke` для быстрого прогона
- [x] Проверить что `pytest -m smoke` работает и покрывает все blueprints
- [x] Запустить полный тест-сьют — убедиться что маркеры не сломали ничего

### Task 4: Тесты для telegram routes

**Files:**
- Create: `tests/test_telegram_routes.py`

- [x] Написать тесты для POST `/telegram/generate-code` — генерация кода привязки (auth required, возвращает код)
- [x] Написать тесты для POST `/telegram/unlink` — отвязка аккаунта (auth required, edge cases)
- [x] Написать тесты для GET `/telegram/status` — статус привязки (auth required, linked/unlinked states)
- [x] Написать тесты для POST `/telegram/webhook` — webhook endpoint (auth token validation, payload handling)
- [x] Пометить ключевые happy-path тесты как `@pytest.mark.smoke`
- [x] Запустить полный тест-сьют

### Task 5: Тесты для grammar_lab API routes

**Files:**
- Create: `tests/test_grammar_lab_routes.py`

- [x] Написать тесты для GET `/grammar-lab/` — главная страница (200, контент)
- [x] Написать тесты для GET `/grammar-lab/topics`, `/grammar-lab/topics/<level>` — списки тем
- [x] Написать тесты для GET `/grammar-lab/topic/<id>` — детальная страница темы (existing/missing)
- [x] Написать тесты для GET `/grammar-lab/practice` и `/grammar-lab/practice/topic/<id>` — практика
- [x] Написать тесты для API endpoints: `/grammar-lab/api/topics`, `/grammar-lab/api/exercise/check`, `/grammar-lab/api/stats`
- [x] Написать тесты для auth-protected endpoints — проверка redirect для неавторизованных
- [x] Пометить ключевые happy-path тесты как `@pytest.mark.smoke`
- [x] Запустить полный тест-сьют

### Task 6: Тесты для words routes (word list, detail, status update)

**Files:**
- Create: `tests/test_words_routes.py`

- [x] Написать тесты для GET `/words` — список слов с фильтрами (status, level, search)
- [x] Написать тесты для GET `/words/<word_id>` — детальная страница слова
- [x] Написать тесты для POST `/update-word-status/<word_id>/<status>` — обновление статуса (valid/invalid статусы)
- [x] Написать тесты для GET `/api/daily-plan/next-step` и POST `/api/streak/repair-web` — API endpoints
- [x] Написать тесты для edge cases: несуществующее слово, чужое слово, невалидный статус
- [x] Пометить ключевые happy-path тесты как `@pytest.mark.smoke`
- [x] Запустить полный тест-сьют

### Task 7: Verify acceptance criteria

- [ ] Запустить полный тест-сьют (`pytest`)
- [ ] Запустить smoke-тесты (`pytest -m smoke`) — должны проходить за < 30 секунд
- [ ] Проверить что полный сьют стал быстрее (transaction rollback + consolidated apps)
- [ ] Проверить покрытие telegram, grammar_lab, words routes через `pytest --cov`

### Task 8: Update documentation

- [ ] Обновить CLAUDE.md если изменились паттерны тестирования (smoke markers, новый db_session pattern)
- [ ] Переместить этот план в `docs/plans/completed/`
