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

Шаблоны: `app/templates/{dashboard.html,lesson_base_template.html,study,words,curriculum,books}`.

### P0 — критичные

- **study/achievements.html:138** — `{{ category.icon|safe }}` в категории ачивок: если icon приходит из БД с админ-вводом, это XSS-вектор. Заменить на whitelisted SVG/data-URI или экранировать.
- **study/achievements.html:171** — `{{ earned_at.strftime('%d.%m.%Y') }}` без guard на None упадёт при отсутствующей дате. Обернуть `{% if earned_at %}` или fallback `'—'`.
- **study/achievements.html:38, :56** — `earned_count / total_achievements` без guard `if total_achievements > 0`; даёт некорректный width у progress-bar при пустом каталоге ачивок.
- **study/index.html:232** — `mastered_count / total` без guard на zero для пустых деков.
- **lesson_base_template.html:476-487** — inline `onclick="retryLesson()"`, `onclick="window.location.href=..."` нарушают CSP (`unsafe-inline`) и затрудняют CSRF-context для будущих fetch-флоу. Перенести на addEventListener + data-attrs.
- **dashboard.html:13, :77** — multiple inline `onclick=` handlers (mission badge popup, share). Тот же CSP/CSRF риск.

### P1 — важные UX

- **curriculum/lessons/{quiz,matching,vocabulary,final_test}.html** — нет empty state когда `questions|length == 0` или `pairs == []`; пользователь видит пустую страницу или JS-ошибки. Нужен общий fallback `empty_content.html` или inline placeholder.
- **study/quiz.html:741-747** vs **study/matching.html / curriculum/lessons/final_test.html** — несогласованные loading states: spinner есть в quiz, нет в matching/final_test (между загрузкой DOM и JS-гидратацией пустой экран). Добавить `.skeleton` / `.btn--loading`.
- **study/quiz.html:1418, dashboard.html (repair-streak AJAX)** — fetch-ошибки уходят в `console.error` без user-facing toast. Показывать `.alert--form-error` или toast.
- **lesson_base_template.html:32-85** — кастомные `@keyframes lsnFloat1/2` в `<style>` шаблона; глобальный `prefers-reduced-motion` блок (~design-system.css:8537) использует `*` и должен покрывать, но проверить cascade — если `<style>` подключается после, нужно явное `@media (prefers-reduced-motion: reduce)` локально.
- **study/quiz.html:91-99** — floating animations без motion-preference check внутри `<style>` шаблона. То же что выше.
- **curriculum/lessons/quiz.html:95, :152** — захардкожены `#10b981`, `#ef4444`, `#f59e0b` вместо `var(--color-success)`, `var(--color-danger)`, `var(--color-warning)`.
- **curriculum/lessons/final_test_results.html:40-41** — inline `linear-gradient(135deg, #dc2626, #ef4444, #f87171)` хардкодит цвета. Вынести в design-system.
- **study/quiz.html** — score/progress counter обновляется без `aria-live="polite"`; screen reader не озвучит изменение очков.
- **books/reader_simple.html:345** — `width: 320px` фиксированный на сайдбаре; на iPhone SE (375px) ломается. Заменить на `max-width: 100%` или `clamp()`.
- **books/reading_widget.html:15-18** — фиксированные `width: 60px; height: 90px` для cover thumbnail не учитывают flex-wrap.
- **linear_daily_plan.html:186-187** — `slot.data | _data` подразумевает не-None; при пустом payload шаблон может упасть. Использовать `slot.data or {}`.
- **curriculum/error_review.html:119** — `window.linearPlanContext.applyErrorReviewPlanAwareCompletion()` без null-guard, в отличие от `lesson_base_template.html:542-650`, где `if (ctx && typeof ctx.isActive === 'function')`.
- **curriculum/lessons/matching.html, quiz.html** — input-поля без error-state стилей (`aria-invalid`, красный border) при неверном ответе/валидации.

### P2 — polish

- **study/quiz.html:1162, :1206-1207, :1478-1485** — inline `style.color = '#fde68a'` и `setProperty(..., 'important')` указывают на specificity war. Рефакторить через CSS-классы (`.qz-counter--warn`, `.qz-score--success`).
- **study/quiz.html:912** — `pulseElement` хардкодит `'qzPulse 0.6s ease-in-out 3'`; вынести в CSS-переменную/класс.
- **lesson_base_template.html:28, :414, dashboard.html:67** — `padding: 0 1rem`, `margin-bottom: 1.5rem` без `var(--space-*)`-токенов.
- **dashboard.html:10** — badge popup `role="dialog"` без `aria-modal="true"` и без backdrop-элемента; SR не озвучит как modal.
- **dashboard.html:60, :79** — emoji/SVG без консистентного `aria-hidden="true"` для декоративных и `aria-label` для интерактивных.
- **lesson_base_template.html:260-277** — toast `bottom: 1.5rem; right: 1.5rem` без `env(safe-area-inset-bottom)`; на iPhone с home-bar перекрывается.
- **linear_daily_plan.html:156-161** — `progress` отображается как `current/total` без skeleton/визуального состояния, если день уже secured при page load.
- **curriculum/lessons/final_test.html** — `questions|tojson|safe` гидрируется JS; нет "Загрузка..." / skeleton до парсинга, ~0.5-1s пустоты.
- **study/quiz.html:1273** — `submitAnswerBtn.disabled = true` без явного `:disabled` стиля; полагается на browser default.
- **words/list_optimized.html, books/list_optimized.html, books/details_optimized.html, books/read_optimized.html, books/words_optimized.html** — параллельно существуют `*_optimized.html` варианты без явной маркировки, какой live (легаси). Проверить и удалить unused (см. Task 5/6).
- **study/leaderboard.html, study/insights.html, study/stats.html** — empty states без `role="status"` и иконки, как в auth/profile (косметическая консистентность).

## Auxiliary

(Заполняется в Task 3.)

## Design System & JS

(Заполняется в Task 4.)

## Prioritized Backlog

(Сводный backlog формируется после Task 4.)
