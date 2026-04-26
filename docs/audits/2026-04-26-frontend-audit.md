# Frontend Audit — 2026-04-26

Систематический аудит фронтенд-части (Jinja-шаблоны, CSS design-system, JS, UX-флоу). Категоризация: P0 (critical / сломан) / P1 (important UX) / P2 (polish). Фиксы реализуются в Task 5/6/7 плана `docs/plans/2026-04-26-frontend-audit-and-fixes.md`.

## Public & Auth

Шаблоны: `app/templates/{landing,auth,onboarding,legal,errors}`.

### P0 — критичные

- **auth/reset_password.html:32, :39** — поля password/password confirm БЕЗ `.auth-password-toggle`, тогда как `login.html`/`register.html` используют его. Несогласованность UX в самом чувствительном флоу (восстановление пароля).
- **auth/profile.html:174** — `milestone.achieved_on.strftime(...)` без guard на None упадёт на пустой дате milestone (если такой возможен в data layer). Проверить и обернуть в `{% if milestone.achieved_on %}`.
- **landing/index.html:825** — `{{ word_of_day.sentences|truncate(150)|sanitize }}` потенциально небезопасен, если `sanitize` не whitelisted (XSS в публичной странице). Аудитировать фильтр.
- **errors/403.html, 404.html, 500.html** — голые HTML без `extends "base.html"` (если так): ломается навигация / footer / стилевая система. Проверить и привести к base layout.

### P1 — важные UX

- **landing/index.html:827-832** — onclick `playAudio(...)` без user-facing error при отсутствующем audio (silent catch). Нужен toast/inline feedback.
- **auth/register.html:96, login.html:73** — submit-кнопка получает loading-класс, но форма не блокируется от двойного submit (`form.submit` event guard отсутствует).
- **auth/register.html:36-42** — social-proof показывает fallback "0+ учеников" при пустом learner_count. Должен быть скрыт или замен на нейтральный CTA.
- **onboarding/wizard.html:268-269** — disabled CTA различается только opacity 0.5; нужно добавить `cursor: not-allowed`, `background: var(--color-disabled)` для ясности.
- **onboarding/wizard.html:383-384** — русский текст в JS захардкожен; не блокер, но нарушает паттерн i18n (если он планируется).
- **auth/reset_request.html** — после submit нет success-сообщения "Проверьте почту"; пользователь не знает, что заявка ушла.
- **all auth forms** — отсутствует обработка CSRF-ошибок (silent fail); flash-сообщение нужно при `validate_csrf` exception.

### P2 — polish

- **landing/index.html:91-96, auth/login.html:156-165** — keyframes (land-float, auth-float-1/2, slideUp) запускаются независимо от `prefers-reduced-motion`. Глобальный блок в design-system.css (~line 8537) их частично гасит, но кастомные анимации в `<style>` шаблонов могут проскакивать — проверить cascade.
- **landing/index.html:615-639** — stats секция показывает `{{ stats.words }}+` без guard на None/0; при пустых данных получаем "undefined+ слов".
- **auth/referrals.html:142-144** — empty state без `role="status"`/`aria-live` для screen readers.
- **public_profile.html:140** — empty "Пока нет достижений" без иконки/семантики; косметика.
- **auth/profile.html:314-325** — emoji-only в "Links" без `aria-label`; на mobile, если текст скрыт, теряется смысл.
- **onboarding/wizard.html:159** — progress bar без `role="progressbar"` / `aria-valuenow`/`aria-valuemax`.
- **landing & onboarding** — нет `.alert--form-error` паттерна для form-level ошибок.
- **errors/*.html** — могут не использовать дизайн-системные кнопки (`.btn .btn--primary`); привести к консистентности.

## Learning Core

(Заполняется в Task 2.)

## Auxiliary

(Заполняется в Task 3.)

## Design System & JS

(Заполняется в Task 4.)

## Prioritized Backlog

(Сводный backlog формируется после Task 4.)
