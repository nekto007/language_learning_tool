# Фронтенд-аудит и поэтапные фиксы по всем разделам

## Overview

Систематический аудит фронтенд-части (шаблоны Jinja, CSS design-system, JS, UX-флоу) по всем blueprint-ам приложения. Результат: аудит-документ с категоризацией находок (P0 critical / P1 important / P2 nice-to-have), затем инкрементальные фиксы по приоритету.

## Context

- Templates: `app/templates/{auth,onboarding,landing,dashboard.html,study,words,curriculum,books,grammar_lab,achievements,race,admin,legal,errors,components,partials}`
- CSS: `app/static/css/design-system.css` (~11400 строк, единая)
- JS: `app/static/js/`
- Blueprints: achievements, admin, api, auth, books, curriculum, courses, grammar_lab, landing, legal, notifications, onboarding, race, seo, study, telegram, words
- Patterns to respect: skeleton loaders, `.btn--loading`, `prefers-reduced-motion`, `.alert--form-error`, `dash-*` widget classes, `_safe_widget_call`, design-system tokens
- Audit doc: `docs/audits/2026-04-26-frontend-audit.md`

## Development Approach

- Audit-first: сначала полный обход + документ, потом фиксы по приоритету
- Каждый раздел проверяется по чек-листу: visual polish, empty states, loading states, error states, accessibility (a11y), mobile responsive, keyboard nav, prefers-reduced-motion, broken links/dead UI, console errors
- Фиксы коммитятся инкрементально (один раздел = один коммит минимум)
- CRITICAL: каждый task с фиксами включает регресс-тесты (smoke + integration где релевантно)
- CRITICAL: pytest должен проходить после каждого task

## Implementation Steps

### Task 1: Аудит публичных и auth-разделов

**Files (read-only audit):**
- `app/templates/landing/`, `app/templates/auth/`, `app/templates/onboarding/`, `app/templates/legal/`, `app/templates/errors/`

- [x] Пройти каждый шаблон: landing, login/register/reset, onboarding (все шаги), legal (privacy/terms), 404/500
- [x] Проверить: empty states, form validation feedback, password toggle, mobile layout, CTA hierarchy, broken links
- [x] Записать находки в `docs/audits/2026-04-26-frontend-audit.md` (раздел "Public & Auth") с категоризацией P0/P1/P2

### Task 2: Аудит learning core (study, words, curriculum, books)

**Files (read-only audit):**
- `app/templates/study/`, `app/templates/words/`, `app/templates/curriculum/`, `app/templates/books/`, `app/templates/lesson_base_template.html`

- [x] Пройти: dashboard.html, study session UI, vocab learning, lesson templates (все типы карточек/quiz/matching/final-test), book reader, daily plan widgets
- [x] Проверить: SRS card animations, loading states при API-вызовах, error toasts, day_secured UI, linear plan slots, reading progress, скелетоны
- [x] Дописать находки в audit-документ (раздел "Learning Core")

### Task 3: Аудит вспомогательных разделов (grammar_lab, achievements, race, admin)

**Files (read-only audit):**
- `app/templates/grammar_lab/`, `app/templates/achievements/`, `app/templates/race/`, `app/templates/admin/`, `app/templates/components/`, `app/templates/partials/`

- [x] Пройти grammar exercises, achievements/badges, daily race board, admin dashboards, общие компоненты (notification dropdown, modals)
- [x] Проверить интерактив, leaderboards, mission popups, admin tables responsive
- [x] Дописать находки в audit-документ (раздел "Auxiliary")

### Task 4: Аудит CSS design-system + JS

**Files (read-only audit):**
- `app/static/css/design-system.css`, `app/static/js/`

- [x] Найти дубликаты правил, неиспользуемые классы, отсутствие prefers-reduced-motion для новых анимаций, токены вне системы (хардкод цветов/spacing)
- [x] Проверить JS: console.error в проде, отсутствие debounce, неотменяемые fetch, утечки event listeners
- [x] Дописать находки в audit-документ (раздел "Design System & JS"), сформировать сводный приоритезированный backlog в конце документа

### Task 5: Фиксы P0 (критичные — сломанные/недоступные UI)

**Files:** определяются Task 1-4

- [ ] Реализовать все P0-фиксы
- [ ] Добавить smoke-тесты на затронутые route'ы (если шаблон рендерится — `pytest -m smoke` должен покрывать)
- [ ] `pytest -m smoke` — должен пройти
- [ ] Отметить P0-пункты в audit-документе как `[DONE]`

### Task 6: Фиксы P1 (важные UX-проблемы)

**Files:** определяются аудитом

- [ ] Реализовать P1-фиксы (loading/empty states, a11y, mobile responsive, error feedback)
- [ ] Обновить/добавить тесты где затронута логика
- [ ] `pytest` — полный прогон
- [ ] Отметить P1-пункты как `[DONE]`

### Task 7: Фиксы P2 (полировка)

**Files:** определяются аудитом

- [ ] Реализовать P2-фиксы (косметика, микро-анимации, консистентность)
- [ ] `pytest` — полный прогон
- [ ] Отметить P2-пункты как `[DONE]`

### Task 8: Финальная верификация и документация

- [ ] `pytest` полный прогон — всё зелёное
- [ ] Проверить отсутствие console errors в браузере (golden path по каждому разделу)
- [ ] Обновить CLAUDE.md если появились новые UI-паттерны
- [ ] Переместить план в `docs/plans/completed/`
- [ ] Переместить аудит-документ в `docs/audits/completed/` (или оставить как референс)
