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

Шаблоны: `app/templates/{grammar_lab,achievements,race,admin,components,partials}`.

### P0 — критичные

- **grammar_lab/practice.html:1314** — `onclick="selectOption(this, ${i})"` в динамически генерируемых label-элементах нарушает CSP `unsafe-inline`. Перенести на `addEventListener` + `data-*`.
- **grammar_lab/practice.html:1327, :1333** — `onclick="selectTF(this, 'true'/'false')"` на button-элементах — тот же CSP риск.
- **grammar_lab/practice.html:1159** — `{{ session.exercises|tojson|safe }}` гидрирует JS из шаблона; если данные содержат XSS-вектор, фильтр `|safe` его не блокирует. Проверить sanitization на бэкенде.
- **grammar_lab/topic_detail.html:619** — `onmouseover="this.style..."` / `onmouseout="this.style..."` встроены в HTML — CSP violation. Использовать CSS `:hover`.
- **admin/dashboard.html:301** — `{{ u.last_login.strftime('%d %b') }}` без guard на None упадёт у first-time users.
- **admin/users.html:94** — datetime арифметика `(now - user.last_login).total_seconds() / 86400` упадёт при None last_login (порядковая зависимость от guard на line 93).
- **admin/base.html:310-316** — `innerHTML` из JS без escaping search-результатов (`item.title`, `item.section`) — XSS-вектор в admin search.
- **components/_flashcard_session.html:382** — `{{ fc_grade_payload | default('null') | safe }}` — `|safe` на JS-payload без верификации.
- **race/today.html:46** — `{{ daily_race.steps_done / daily_race.steps_total * 100 }}` — division by zero при пустой race (`steps_total=0`).
- **admin/dashboard.html:110** — `(srs_health.words_srs.new / srs_health.words_srs.total * 100)` — потенциальный divide-by-zero при `total=0` (полагается на хрупкий `if` выше).

### P1 — важные UX

- **race/today.html** — leaderboard-таблица не имеет empty-state-сообщения, если `daily_race.leaderboard` пустой; нет loading/error state.
- **race/today.html:30, :84** — emoji-medal/trophy без `aria-hidden="true"` (декоративные); SR озвучивает невнятно.
- **race/today.html:284** — `onclick="alert(...)"` для информационного сообщения; заменить на toast/modal.
- **race/today.html** — нет `@media (prefers-reduced-motion: reduce)` для transform/box-shadow transitions (lines 283-288).
- **admin/users.html:54-65** — table headers без `scope="col"`, чекбоксы без `aria-label`.
- **admin/users.html:148** — `sendReminder({{ user.id }}, {{ user.username|tojson }})` inline onclick; tight coupling JS ↔ template.
- **admin/users.html:52-166** — responsive wrapper есть, но нет horizontal scroll indicator/overflow hint на mobile.
- **admin/dashboard.html** — charts (activityChart, progressChart) без `aria-label` / fallback для SR.
- **admin/dashboard.html:383** — `total_users - active_users - new_users` может быть отрицательным при stale data; без clamp.
- **admin/base.html:200** — flash `role="alert"` без `aria-live="polite/assertive"`.
- **admin/base.html:56-58** — dropdown без `role="menu"` и `aria-label` на toggle; keyboard nav неясна.
- **admin/base.html:283-292** — Cmd+K shortcut без Ctrl+K fallback на Windows.
- **admin/components.html:203** — `delete_modal` macro с `aria-modal="true"`, но не у всех modals есть `aria-labelledby`.
- **admin/components.html:149** — `confirm('{{ confirm }}')` — Jinja-autoescape работает, но риск edge-case-инъекции при отключении.
- **admin/database.html:104** — `style="width: {{ stat.percentage }}%"` без clamp 0..100.
- **admin/stats.html:17-19** — period-selector кнопки `onclick="updatePeriod(...)"` без loading-state при data fetch.
- **achievements/public_streak.html:14-30** — захардкоженные hex (#2563eb, #0ea5e9, #ef4444, #22c55e) вместо design-токенов.
- **partials/linear_daily_plan.html:69** — day-secured banner `aria-hidden` на emoji, но сам banner интерактивный (line 93-100); должен иметь `role="status"`.
- **partials/linear_daily_plan.html:128-149** — Russian plural-логика inline в шаблоне; вынести в filter/helper.
- **partials/telegram_banner.html:15** — `onclick="dismissTgBanner()"` inline + `localStorage` без availability check.
- **components/_flashcard_session.html:55-56** — counter "Карточка 1 из 20" hardcoded без `aria-live` на динамическое обновление `#card-counter`.
- **components/_daily_plan_progress.html:106** — `.dp-bar__text` max-width 140px на 576px breakpoint может всё равно переполняться на 320px.
- **grammar_lab/practice.html** — нет skeleton/loading state до JS-гидратации (~0.3-0.5s пустой экран).
- **grammar_lab/practice.html:368-376, topic_detail.html:761-774, index.html:487-500** — `@keyframes float-1/2/3` в `<style>` без локального `@media (prefers-reduced-motion: reduce)` override.
- **grammar_lab/practice.html:1417** — `document.getElementById('word-bank').querySelector(...)` без null-check.
- **grammar_lab/topic_detail.html:1656** — `[data-pos="${pos}"]` selector без null-guard перед `.dataset.word`.
- **grammar_lab/topics.html, stats.html** — empty-state без `role="status"` / `aria-live="polite"`.

### P2 — polish

- **achievements/public_streak.html:55** — calendar `grid-template-columns: repeat(13, 1fr)` без label / month-indicator.
- **achievements/public_streak.html:76-79** — 3-col grid на mobile стэкается; нет max-width на `.strk-page`.
- **admin/components.html:117** — `empty_message` macro plain text без иконки/визуальной emphasis.
- **race/today.html:126, :363-371** — `.dash-race__stats` `minmax(0, 1fr)` может переполняться на узких экранах.
- **grammar_lab/index.html:1383-1385, topic_detail.html:1383-1385** — hex `#dbeafe`/`#fef3c7`/`#fce7f3` для level-badge inline; вынести в `--level-*-light` токены.
- **grammar_lab/practice.html:453-456, index.html:722-732** — `#dc2626`/`#d97706`/`#16a34a`/`#2563eb` вместо `var(--color-danger/warning/success/info)`.
- **grammar_lab/index.html:1633** — inline `style="animation:spin 0.8s linear infinite"`; вынести в `.btn--loading`.
- **grammar_lab/practice.html:1314** — `<label class="practice-option" onclick=...>` вместо `<button>`/`role="radio"` уменьшает семантику.
- **grammar_lab/practice.html:1701** — inline `this.style.opacity = '0.7'` вместо CSS `.btn--loading`.
- **grammar_lab/practice.html:1341** — true/false buttons без `:disabled` стиля; полагаются на browser default.
- **grammar_lab/topic_detail.html:68-69, :84-85** — emoji в topic-nav-adjacent без `aria-hidden="true"`.
- **grammar_lab/topic_detail.html:620-636** — inline `style="..."` для related-topics/words; вынести в CSS-классы.
- **grammar_lab/topics.html** — длинные topic-имена без `word-break: break-word` могут переполняться на узких экранах.
- **grammar_lab/stats.html, index.html** — progress fill `width: {{ pct }}%` без `min(pct, 100)` clamp при NaN.
- **admin/database.html:103-104** — progress-bar width не clamped (может выходить за 100% при inconsistent data).
- **race/today.html:46** — нет `@supports (grid)` fallback.

## Design System & JS

(Заполняется в Task 4.)

## Prioritized Backlog

(Сводный backlog формируется после Task 4.)
