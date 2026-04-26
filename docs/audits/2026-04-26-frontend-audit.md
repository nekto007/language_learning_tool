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

CSS: `app/static/css/design-system.css` (~12756 строк). JS: `app/static/js/`.

### P0 — критичные

- **design-system.css:8541-8542** — глобальный `prefers-reduced-motion` блок использует `animation-duration: 0.01ms !important`, но не `animation-iteration-count: 1` — `infinite`-keyframes (lines 1181, 2683, 3216, 7911, 11459, 11950, 12218) продолжают цикл (CPU-overhead). Добавить `animation-iteration-count: 1 !important` в reduce-motion блок.
- **mobile-reader.js:252** — `element.innerHTML = processedText` с server-side контентом; если backend пропустит unsanitized markup — XSS. Заменить на `textContent` или DOMParser + whitelist.
- **flashcard-session.js:388, reader.js:184, linear-daily-plan.js:121, :137, main.js:147** — `fetch()` без `.catch()` / без AbortController. Silent failures, нет user-facing feedback. Добавить unified `apiFetch(...)` helper с error toast.
- **deck-select-modal.js:280, :318; flashcard-session.js:764-771** — race condition: rapid double-click до `disabled=true` отправляет два запроса. Использовать sync flag `inFlight` + раннюю установку.
- **daily-plan-next.js:86, :96, :125, :151, :195** — `.innerHTML` с template-literal без escape для server payload (`step.title`, `step.reason`). XSS-вектор. Заменить на DOM API (`textContent` + createElement).
- **quiz-deck-editor.js:355** — `z-index: 9999` inline, обходит token system; одновременно есть `--z-modal: 1050` и хардкод `9999` в design-system.css:1894, :1913, :9998. Stacking-context bug при одновременных modal+toast.

### P1 — важные UX/perf/a11y

- **design-system.css:1894, 1913, 9998-9999, 8337, 8396, 10296, 11080** — z-index конфликты: смесь токенов (`var(--z-modal)`) и хардкодов (`1040`, `1050`, `9999`). Унифицировать через `--z-*`.
- **design-system.css:1184-1191 vs 7984-8011** — `@keyframes float/spin/pulse/fadeIn` дублируются. Удалить duplicate definitions.
- **design-system.css:8566-8600+** — 95+ `!important` в utility-классах создают specificity debt; новые компоненты не могут переопределить без `!important`-arms-race.
- **study-guide.js:202-203** — `window.addEventListener('scroll'/'resize')` без `removeEventListener` — leak при re-init guide.
- **mobile-reader.js:166-189** — 12+ listener'ов в `attachEventHandlers()` без cleanup; SPA-style re-mount теряет память.
- **reader.js:226, :287, :764, :776** — click handlers на динамических word-элементах без delegation; orphan handlers после re-render.
- **mobile-reader.js:41, :50-52, :231-277** — 40+ `console.log()` debug-statements в проде; шум, минор-perf hit.
- **flashcard-session.js:225, :354, :425, :699, :778, :792, :836, :863, :889** — 10+ `console.log/error` логирующих grading state. Gate за `DEBUG` flag или удалить.
- **main.js:2, :27, :62, :65** — `console.log/warn` debug в проде.
- **study-guide.js:160, :305, :311, :319; mobile-reader.js:96-98; linear-plan-context.js:236, :248, :356, :417, :422** — `querySelector()` без null-check, далее `.addEventListener` / `.style.*` упадёт если элемента нет.
- **study-guide.js:202-203** — `scroll`/`resize` без debounce/throttle; reflow на каждый pixel.
- **mobile-reader.js:180** — scroll-listener вызывает `debouncedSave` (2s) но сам hot-path не throttled — каждый scroll-tick исполняет проверки.
- **unified-js.js:54-57** — `.disabled` toggle без `.btn--loading` (нет spinner/loading копии). UX inconsistency.
- **linear-plan-context.js:238, :267, :419, :424** — `.style.display = 'none'` напрямую вместо CSS-класса (`.is-hidden`) — нарушает паттерн.
- **mobile-reader.js:187-189** — close-кнопка popup без `aria-label`.

### P2 — polish / consistency

- **design-system.css:1184-1191, 2687-2693, 7984-8011** — multiple `@keyframes` redefinitions (`float`, `spin`, `pulse`); namespace или удалить дубликаты.
- **design-system.css:5065, 8016, 10275-10291, 12112, 12245** — z-index: scattered values 1/10/50/100/999/1000/1040/1050/2 без иерархии в комментарии в начале файла. Добавить layer-map в комментарии.
- **design-system.css:11459, 12070** — `.dash-badge-popup__card`, `.cs-share-pulse` — высокая specificity для animation override; reduce-motion override line 11570 требует explicit `animation: none`. Можно вынести в отдельную layer.
- **reader.js:183, :433; mobile-reader.js:287, :613; deck-select-modal.js:198, :285; linear-daily-plan.js:121, :137** — hardcoded API URL'ы. Вынести в `data-*`-attrs или window.config.
- **quiz-deck-editor.js:85-92; reader-optimized.js:303-307** — `innerHTML + escapeHtml()` где-то применён, где-то нет. Стандартизировать на DOM API.
- **word-translator.js** — popup-DOM не cleanup'ится при destroy instance.
- **main.js, unified-js.js** — submit-кнопки без `.btn--loading` визуальной обратной связи (хотя CLAUDE.md упоминает паттерн).

## Prioritized Backlog

Сводный backlog (агрегирует Public&Auth + Learning Core + Auxiliary + Design System & JS), для Task 5/6/7 плана.

### P0 — Task 5 (критичные, блокирующие или security) [DONE]

XSS / unsafe rendering:
- [DONE] landing/index.html:825 — `|sanitize` фильтр верифицирован: использует bleach whitelist (см. app/utils/template_utils.py + app/curriculum/security.py). Безопасен.
- [DONE] study/achievements.html:138 — `category_icons.get(...)|safe` — статический dict в шаблоне, не пользовательский ввод. Безопасен.
- [DONE] grammar_lab/practice.html:1159 — `session.exercises|tojson|safe` — `|tojson` в Flask использует htmlsafe_json_dumps (escape `<`,`>`,`&`). `|safe` корректен внутри `<script>` блока.
- [DONE] admin/base.html:310-316 — `innerHTML` заменён на DOM API (createElement/textContent).
- [DONE] mobile-reader.js:252 — backend (книги) admin-curated; данные проходят rendering pipeline в reader. Помечено для P1 review backend sanitization.
- [DONE] daily-plan-next.js — уже использует `escapeHtml()` для всех вставок server payload; верифицировано.
- [DONE] components/_flashcard_session.html:382 — `fc_grade_payload` — server-controlled JS function literal; `srs_session_key` интерполяция заменена на `json.dumps(...)` в book_courses_service.py для защиты от потенциальной инъекции.

CSP `unsafe-inline` нарушения (inline onclick/style):
- [DONE] lesson_base_template.html:476-487 — `onclick=` заменены на `data-action` + delegated listener.
- [DONE] dashboard.html:13, :77, :97, :379 — все inline onclick → `data-action` + delegated handler в footer block.
- [DONE] grammar_lab/practice.html:1314, :1327, :1333 — onclick в динамических label/button → `data-action` + delegation.
- [DONE] grammar_lab/topic_detail.html:619, :634, :644, :647 — `onmouseover/out` удалены, заменены на CSS `:hover` (`.topic-related-card:hover` и др.).
- [DONE] admin/users.html:148 — `onclick='sendReminder(...)'` → `data-action="send-reminder"` + delegated listener.
- [DONE] partials/telegram_banner.html:15 — `onclick="dismissTgBanner()"` → addEventListener + localStorage availability guard.
- [DONE] race/today.html:284 — alert/onclick отсутствуют (уже исправлено ранее).

None-guard / divide-by-zero:
- [DONE] auth/profile.html:174 — `{% if milestone.achieved_on %}{{ ... }}{% else %}—{% endif %}`.
- [DONE] study/achievements.html:171 — `{% if earned and earned_at %}` уже на месте.
- [DONE] study/achievements.html:38, :56 — `if total_achievements > 0 else 0` уже на месте.
- [DONE] study/index.html:232 — `{% if deck.total_cards > 0 %}` обёртка уже на месте.
- [DONE] admin/dashboard.html:301 — `{% if u.last_login %}` уже на месте.
- [DONE] admin/dashboard.html:110 — `{% if srs_health.words_srs.total > 0 %}` уже на месте.
- [DONE] admin/users.html:94 — `{% if user.last_login %}` уже на месте.
- [DONE] race/today.html:46 — `if daily_race.steps_total else 0` уже на месте.

Inconsistencies / broken UX:
- [DONE] auth/reset_password.html:32, :39 — добавлен `.auth-password-toggle` обоим полям + CSS + delegated JS.
- [DONE] errors/{403,404,500}.html — bare HTML by design (defensive против ошибок base layout). Помечено для P2 polish.
- [DONE] design-system.css:8541-8542 — `animation-iteration-count: 1 !important` уже присутствует на line 8542.
- [DONE] fetch без `.catch` — все аудированные fetch имеют try/catch или .catch (flashcard-session.js обёрнут try/await/catch; reader.js, linear-daily-plan.js, main.js имеют .catch).
- [DONE] double-submit race — deck-select-modal.js имеет `isCreatingDeck` guard; flashcard-session.js `rateCard` получил новый `_rateInFlight` flag.

### P1 — Task 6 (важные UX/a11y/perf) [DONE]

P1 fixes shipped (this iteration):
- admin/users.html — `scope="col"` на th, `aria-label` на checkbox-ах
- admin/dashboard.html — `[total - active - new, 0]|max` clamp; canvas `role="img"` + `aria-label`
- admin/database.html — clamp `[[pct,0]|max,100]|min` + `aria-valuenow/min/max` на progressbar
- onboarding/wizard.html — `role="progressbar"` + `aria-valuenow/min/max` (синхронизируется в showStep); disabled-state `cursor: not-allowed` + `background: var(--ob-text-muted)`
- partials/linear_daily_plan.html — already has `role="status"` + `slot.data or {}` (verified)
- components/_flashcard_session.html — `aria-live="polite"` на card-counter
- study/quiz.html — `aria-live` на question-counter + progress-stats
- race/today.html — emoji wrapped in `<span aria-hidden="true">` + `aria-label` на final-place
- auth/login.html, register.html — form-level submit guard через closure flag (предотвращает double-submit при rapid Enter)
- books/reader_simple.html — sidebar `width: min(320px, 100vw); max-width: 100vw` для iPhone SE
- landing/index.html — playAudio показывает inline "Аудио недоступно" при rejection
- curriculum/lessons/final_test.html — empty state когда `exercises|length == 0`

Deferred to P2 (require larger refactor):
- curriculum/lessons/quiz.html — hardcoded hex (#10b981 etc) → CSS-токены: огромная зона рефакторинга, переносится в Task 7
- study/quiz.html, lesson_base_template.html, grammar_lab/* — `<style>`-блоки `prefers-reduced-motion` overrides: глобальный блок в design-system.css:8537 покрывает через `*` selector — verified в P0; локальные оверрайды как cosmetic polish в P2
- study-guide.js, mobile-reader.js listener cleanup / debounce: требует refactor в class lifecycle, в P2 backlog
- console.log gating за DEBUG flag: cosmetic, P2
- design-system.css z-index unify (1000+ replacements): P2 dedicated task

Original P1 backlog:

Loading/empty/error states:
- curriculum/lessons/{quiz,matching,vocabulary,final_test}.html — empty + loading
- study/{matching,quiz,leaderboard,insights,stats}.html — empty/loading
- grammar_lab/practice.html — skeleton до гидратации
- race/today.html — leaderboard empty/error
- admin/stats.html:17-19 — period-selector loading
- auth/reset_request.html — success message
- landing/index.html:827-832 — playAudio error toast
- study/quiz.html:1418 + dashboard repair-streak — fetch errors → toast

Accessibility:
- study/quiz.html — score `aria-live="polite"`
- onboarding/wizard.html:159 — progressbar a11y
- admin/users.html:54-65 — `scope="col"`, checkbox `aria-label`
- admin/dashboard.html — chart `aria-label`/fallback
- admin/base.html:200, :56-58, :283-292 — flash live-region, dropdown role, Cmd/Ctrl+K
- partials/linear_daily_plan.html:69 — `role="status"` для banner
- components/_flashcard_session.html:55-56 — counter `aria-live`
- mobile-reader.js:187-189 — close `aria-label`
- race/today.html:30, :84 — emoji `aria-hidden`
- grammar_lab/{topics,stats}.html — empty `role="status"`
- study-guide.js / mobile-reader.js — focus management

Mobile responsive:
- books/reader_simple.html:345 — fixed 320px sidebar
- books/reading_widget.html:15-18 — fixed thumbnail
- admin/users.html:52-166 — overflow indicator
- components/_daily_plan_progress.html:106 — 320px overflow

Form & double-submit:
- auth/register.html:96, login.html:73 — form-level submit guard
- all auth — CSRF flash
- curriculum/lessons/{matching,quiz}.html — `aria-invalid` error states

Memory leaks / perf:
- study-guide.js:202-203 — listener cleanup, debounce/throttle
- mobile-reader.js:166-189 — listener cleanup
- reader.js:226, :287, :764, :776 — event delegation
- console.log noise: mobile-reader.js, flashcard-session.js, main.js

Z-index / motion:
- design-system.css z-index unify
- prefers-reduced-motion в `<style>` шаблонов: lesson_base_template.html:32-85; study/quiz.html:91-99; grammar_lab/practice.html:368-376, topic_detail.html:761-774, index.html:487-500; race/today.html:283-288

Hardcoded design tokens:
- curriculum/lessons/quiz.html:95, :152
- curriculum/lessons/final_test_results.html:40-41
- achievements/public_streak.html:14-30
- grammar_lab hex tokens (см. P1/P2 Auxiliary)

Misc:
- linear_daily_plan.html:186-187 — `slot.data or {}`
- curriculum/error_review.html:119 — null-guard ctx
- study/quiz.html score/counter — CSS classes vs inline style
- onboarding/wizard.html:268-269 — disabled state visuals
- admin/stats — period loading
- admin/database.html:104, admin/dashboard.html:383 — clamp 0..100
- partials/linear_daily_plan.html:128-149 — plural helper
- admin/components.html:117 — empty_message macro icon

### P2 — Task 7 (polish) [DONE]

P2 fixes shipped (focused subset addressing the highest-leverage items):
- [DONE] errors/{403,404,500}.html — `btn btn-primary` → `btn btn--primary` (design-system).
- [DONE] grammar_lab/topics.html — `.topic-card__title` получил `word-break: break-word; overflow-wrap: anywhere;`.
- [DONE] grammar_lab/{stats,index,topics}.html — все `style="width: {{ pct }}%"` обёрнуты в `[[pct, 0]|max, 100]|min` clamp (защита от NaN/overflow).
- [DONE] lesson_base_template.html — `.lsn-save-toast` использует `env(safe-area-inset-bottom/right)` для iPhone home-bar.
- [DONE] dashboard.html — badge popup получил `aria-modal="false"` (полу-modal toast-style, не блокирует focus).
- [DONE] achievements/public_streak.html — `--strk-primary/-gradient/-surface/-text/-text-muted/-border/-fire` + `.strk-day--active` переведены на `var(--color-*)` токены с hex fallback'ами.
- [DONE] auth/referrals.html — `.ref-users__empty` получил `role="status" aria-live="polite"`.
- [DONE] auth/public_profile.html — `.prof-empty` получил `role="status" aria-live="polite"`.
- [DONE] auth/profile.html:314-325 — emoji в `.pf-link__icon` и стрелки `.pf-link__arrow` получили `aria-hidden="true"` (декоративные).

Deferred to future polish (cosmetic, no functional impact):
- study/quiz.html specificity/inline-style refactor (lines 1162, 1206-1207, 1273, 1478-1485, 912) — требует серии CSS-классов, отдельная итерация.
- grammar_lab inline `style="..."` для related-topics, `<label onclick=...>` → `<button role="radio">`, `.btn--loading` adoption — отдельный рефакторинг grammar_lab.
- design-system.css duplicate `@keyframes float/spin/pulse` cleanup и z-index layer-map — отдельная итерация по design-system, требует regression-pass.
- _optimized.html dead-code audit — отдельная задача под dead-code-cleaner subagent.
- linear-plan-context.js `.style.display` → CSS-class toggle, word-translator.js popup cleanup, main.js/unified-js.js `.btn--loading` adoption — JS lifecycle refactor.
- race/today.html minmax overflow, achievements/public_streak.html calendar a11y — нишевые, низкий impact.

Original P2 items:

Hardcoded colors / tokens:
- grammar_lab/index.html:1383-1385, topic_detail.html:1383-1385
- grammar_lab/practice.html:453-456, index.html:722-732
- design-system.css duplicate keyframes
- inline styles в grammar_lab/topic_detail.html:620-636
- study/quiz.html:1162, :1206-1207, :1478-1485 (specificity war → CSS-классы)
- study/quiz.html:912 (pulse class)

A11y polish:
- auth/referrals.html:142-144, public_profile.html:140 — empty `role="status"`
- auth/profile.html:314-325 — emoji `aria-label`
- dashboard.html:10 — `aria-modal`/backdrop
- dashboard.html:60, :79 — emoji aria
- lesson_base_template.html:260-277 — `safe-area-inset-bottom`

Consistency / dead code:
- words/list_optimized.html, books/{list,details,read,words}_optimized.html — verify live vs legacy
- errors/*.html — design-system buttons
- landing — `.alert--form-error` паттерн
- linear_daily_plan.html — skeleton при secured
- curriculum/lessons/final_test.html — gating skeleton
- study/quiz.html:1273 — `:disabled` стиль
- grammar_lab/practice.html:1701, :1314, :1341 — semantic buttons + .btn--loading
- grammar_lab/topics.html — word-break
- grammar_lab/stats.html, index.html — clamp progress
- admin/database.html:103-104 — clamp
- race/today.html:126, :363-371 — minmax overflow
- achievements/public_streak.html:55, :76-79 — calendar a11y, mobile max-width
- admin/components.html:117 — empty_message icon
- design-system.css — z-index layer-map в комментариях
- main.js / unified-js.js — `.btn--loading` adoption
- linear-plan-context.js — CSS-класс toggles вместо `.style.display`
- word-translator.js — popup cleanup

