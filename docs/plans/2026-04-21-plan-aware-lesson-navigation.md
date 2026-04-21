# 9 Tasks: Plan-Aware Lesson Navigation

## Overview

Сейчас linear daily plan виден только на дашборде, но как только юзер проваливается в урок через baseline-слот, контекст плана теряется: кнопка «Следующий урок» в completion-экране ведёт в curriculum-next (следующий урок модуля), а не в следующий слот дневного плана. Нет ощущения «прохождения дня». План добавляет **контекстно-зависимую навигацию**: если юзер вошёл в урок через план (маркер `?from=linear_plan&slot=<kind>`), completion-экран предлагает «Следующий слот плана» (primary) + «На дашборд» (secondary), а не curriculum-next. Контекст сбрасывается только при `day_secured=True` (редирект на дашборд с completion-summary) или при явном «На дашборд». После `day_secured` юзер продолжает curriculum уже обычным способом, без plan-обёртки.

## Context

- Files involved: `app/templates/lesson_base_template.html`, `app/templates/curriculum/lessons/*.html`, `app/templates/partials/linear_daily_plan.html`, `app/static/js/linear-daily-plan.js`, `app/daily_plan/linear/plan.py`, `app/api/daily_plan.py`, `app/study/routes.py` (card-lesson flow), `app/books/routes.py` (reading slot entry)
- Related patterns: `?from=daily_plan` уже используется legacy-миссиями (не ломать), `showLessonCompletion()` helper в base-шаблоне, `#lesson-completion` блок, `MutationObserver` на `#complete-exercise`, `_safe_widget_call` wrapper
- Dependencies: linear plan уже в master (PR #39), feature flag `User.use_linear_plan`
- Feature flags: всё новое поведение гейтится через `User.use_linear_plan` — юзеры на mission-режиме не затрагиваются

## Current State

- Входя в baseline-слот с дашборда, юзер идёт на `/curriculum_lessons/<id>` без plan-контекста (или с минимальным `?from=daily_plan`).
- На completion-экране кнопка «Следующий урок» ведёт в `/learn/<next_lesson.id>/` — это curriculum-next, а не следующий baseline-слот.
- `day_secured` не вычисляется/не коммуницируется внутри сессии урока — юзер завершает 3 обязательных слота, но не видит «День сохранён» пока не вернётся на дашборд вручную.
- `linear_daily_plan.html` partial уже рендерит baseline-слоты, каждый слот имеет URL, но query-параметры контекста не унифицированы.
- `dailyPlanStepComplete` event уже диспатчится из `showLessonCompletion()` (после правки в prev-PR), но `daily-plan-next.js` под него не подстроен для linear-режима.

## Development Approach

- **Testing approach**: Regular (код сначала, потом тесты)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**
- Только `use_linear_plan=True` поведение меняется. Mission/legacy ветка не затрагивается
- Query-param `?from=linear_plan&slot=<kind>` — единственный первичный источник правды. sessionStorage — страховка для внешних редиректов внутри урока

## Design Decisions (зафиксировано в брейншторме)

- **Контекст = источник входа**: `?from=linear_plan&slot=<kind>` при клике на baseline-слот на дашборде. Query-param прокидывается через все промежуточные редиректы урока. sessionStorage `linear_plan_context = {date, slot_kind, started_at}` — страховка.
- **Completion-экран при активном контексте**: primary CTA «Следующий слот плана» → URL следующего baseline-слота; secondary CTA «На дашборд» → `/dashboard`. Никакого curriculum-next.
- **Пропуск слота**: две кнопки — «Следующий слот плана» (primary) + «На дашборд» (secondary, для прерывания сессии).
- **`day_secured` triggered after last baseline**: вместо показа completion-блока урока — редирект на `/dashboard?day_secured=1` с completion-summary («День сохранён, +X XP»). Контекст сбрасывается.
- **После `day_secured` юзер продолжает curriculum с дашборда** (continuation CTA), уже **без** plan-обёртки. Query-param не проставляется, completion-экран работает как в standalone-curriculum.
- **Contextless вход в урок** (прямо через /learn/ URL) — completion как сейчас, curriculum-next. Не трогаем.
- **Query-param для slot-URL**: `?from=linear_plan&slot=curriculum|srs|book|error_review`. Prefix `linear_plan_*` для внутренних source-маркеров в XP и grading (`source=linear_plan_card` как сейчас) сохраняется.

## Implementation Steps

---

### BLOCK 1: API and context tracking (Tasks 1-3)

### Task 1: Unified slot URL builder with plan context

Единая функция формирования URL'ов baseline-слотов — все со сквозным `?from=linear_plan&slot=<kind>`.

**Files:**
- Modify: `app/daily_plan/linear/slots/curriculum_slot.py`
- Modify: `app/daily_plan/linear/slots/srs_slot.py`
- Modify: `app/daily_plan/linear/slots/reading_slot.py`
- Modify: `app/daily_plan/linear/slots/error_review_slot.py`
- Create: `app/daily_plan/linear/context.py` (URL builder + slot-kind enum)
- Create: `tests/daily_plan/linear/test_context.py`

- [x] Создать `LinearSlotKind` enum: `CURRICULUM`, `SRS`, `BOOK`, `ERROR_REVIEW`
- [x] `build_slot_url(base_url, slot_kind) → str` — добавляет `from=linear_plan&slot=<kind>` к любому URL (учитывая существующие query-params)
- [x] Обновить 4 slot-builder'а так, чтобы URL формировался через `build_slot_url`
- [x] Write tests: URL корректно формируется для каждого kind; существующие query-params сохраняются; enum значения стабильны
- [x] Run project test suite — must pass before task 2

### Task 2: API endpoint `GET /api/daily-plan/next-slot`

Возвращает следующий incomplete baseline-слот по текущей позиции в плане.

**Files:**
- Modify: `app/api/daily_plan.py`
- Create: `tests/api/test_next_slot_endpoint.py`

- [x] `GET /api/daily-plan/next-slot?current=<slot_kind>`:
  - Вызывает `get_linear_plan(user_id)` → фильтрует `baseline_slots` по `completed=False`
  - Берёт первый по порядку slot, не равный `current`
  - Response: `{"next": {"kind": "srs", "url": "...", "title": "..."}, "day_secured": false, "secured_just_now": false}`
  - Если все baseline done → `next=null`, `day_secured=true`, `secured_just_now=true` (первый раз за день)
- [x] Требует `login_required` и `User.use_linear_plan=True` (иначе 404)
- [x] `secured_just_now`: true только если `DailyPlanLog.secured_at` записан в рамках этого вызова (т.е. сейчас достигли secured). Идемпотентно при повторных вызовах того же дня
- [x] Write tests: вызов с `current=curriculum` при 3 incomplete → возвращает `srs`; вызов когда все done → `day_secured=true`; второй вызов того же дня → `secured_just_now=false`; без флага → 404
- [x] Run project test suite — must pass before task 3

### Task 3: Context tracker — query-param + sessionStorage helper

Клиентский helper, который помнит контекст плана между страницами урока.

**Files:**
- Create: `app/static/js/linear-plan-context.js`
- Modify: `app/templates/lesson_base_template.html` (подключить скрипт)
- Create: `tests/static/test_linear_plan_context.py` (Jinja include + pytest-инвариант)

- [ ] `window.linearPlanContext` объект с API:
  - `init()` — при загрузке страницы читает `?from=linear_plan&slot=<kind>` из URL; если есть — пишет в sessionStorage `{date: YYYY-MM-DD, slot_kind, started_at}`; если нет — проверяет sessionStorage (страховка) и сверяет date = today
  - `isActive() → bool` — true, если context живой (date=today + slot_kind валидный)
  - `getSlotKind() → string|null`
  - `clear()` — удаляет sessionStorage
- [ ] Автоматический `clear()` при cross-midnight (date mismatch) или явном переходе на `/dashboard`
- [ ] Подключить в `lesson_base_template.html` до `showLessonCompletion` helper'а
- [ ] Write tests: file-level asserts, что скрипт подключён в base-шаблоне; unit-тест в JS можно отложить, но добавить snapshot Jinja
- [ ] Run project test suite — must pass before task 4

---

### BLOCK 2: Lesson completion UX (Tasks 4-6)

### Task 4: Plan-aware completion screen

Completion-экран меняет CTA при активном контексте плана.

**Files:**
- Modify: `app/templates/lesson_base_template.html` (block `#lesson-completion`)
- Modify: `app/static/js/linear-plan-context.js` (методы для получения next-slot URL)
- Modify: `app/static/css/design-system.css` (при необходимости)
- Modify: `tests/test_lesson_ux.py` (добавить plan-aware кейсы)

- [ ] В `showLessonCompletion(opts)`:
  - Если `linearPlanContext.isActive()` → fetch `GET /api/daily-plan/next-slot?current=<kind>`
  - На основе response рендерим CTA:
    - `day_secured=true` → редирект на `/dashboard?day_secured=1` (не показываем completion-блок вовсе; опционально — мини-оверлей «День сохранён!» 800ms → redirect)
    - `next` present → primary: «Следующий слот плана · <next.title>» → `next.url`; secondary: «На дашборд» → `/dashboard`
  - Если `isActive()=false` (curriculum-прямой вход) → старое поведение (curriculum-next + «К урокам»)
- [ ] Добавить `data-completion-mode="plan"|"standalone"` на `#lesson-completion` для тестов и CSS-хуков
- [ ] Write tests: план-контекст активен + не последний slot → «Следующий слот плана» CTA; плана нет → старое поведение; secured → redirect
- [ ] Run project test suite — must pass before task 5

### Task 5: Remove curriculum-next bleed in plan context

Сейчас в vocabulary/grammar/text/matching урок после `showLessonCompletion` может всё ещё содержать фон «next_lesson» ссылок (аналитика, рендер), что путает. Зачистить.

**Files:**
- Modify: `app/templates/curriculum/lessons/vocabulary.html`
- Modify: `app/templates/curriculum/lessons/grammar.html`
- Modify: `app/templates/curriculum/lessons/text.html`
- Modify: `app/templates/curriculum/lessons/matching.html`
- Modify: `app/templates/curriculum/lessons/quiz.html`

- [ ] Найти все inline-ссылки типа `href="/learn/{{ next_lesson.id }}"` вне `#lesson-completion` (другие кнопки/ссылки)
- [ ] Если контекст плана активен — скрывать их CSS-ом через `[data-completion-mode="plan"] ~ .legacy-next-link { display: none }` или через JS-тоггл в `linear-plan-context.js`
- [ ] Quiz.html: если completion-блок теперь вызывается (мы его раньше не вызывали) — добавить вызов `showLessonCompletion` аналогично другим типам; иначе — только footer-кнопка, но с plan-aware логикой в JS
- [ ] Write tests: при plan-активном контексте в rendered HTML нет dangling-ссылок на curriculum-next кроме CTA внутри completion-блока
- [ ] Run project test suite — must pass before task 6

### Task 6: Dashboard completion-summary on return

При редиректе с `?day_secured=1` дашборд показывает overlay/баннер с результатами дня.

**Files:**
- Modify: `app/templates/partials/linear_daily_plan.html`
- Modify: `app/words/routes.py` (dashboard route: detect `day_secured` query + last `DailyPlanLog`)
- Modify: `app/static/js/linear-daily-plan.js`
- Create: `tests/test_dashboard_day_secured_banner.py`

- [ ] В dashboard route: `show_day_secured_banner = request.args.get('day_secured') == '1' and DailyPlanLog for today has secured_at`
- [ ] В partial: если `show_day_secured_banner` → рендерим блок с:
  - Заголовок «🏆 День сохранён»
  - Сводка: +X XP за день, streak=N дней, N слотов из baseline
  - CTA «Продолжить обучение» → прокручивает к continuation-preview
  - CTA «На сегодня хватит» → ссылка-якорь, убирающая баннер без закрытия страницы
- [ ] JS: auto-clear `linearPlanContext` при наличии баннера (для страховки)
- [ ] Write tests: баннер рендерится при query-param; XP-сумма корректно агрегируется из сегодняшних awards; без query — баннер отсутствует
- [ ] Run project test suite — must pass before task 7

---

### BLOCK 3: Cross-slot navigation (Tasks 7-9)

### Task 7: SRS session completion in plan context

SRS-сессия (`/study/cards?source=linear_plan_card`) тоже должна попадать в plan-aware completion-flow.

**Files:**
- Modify: `app/study/routes.py` (cards session complete template)
- Modify: шаблон результатов SRS-сессии
- Modify: `app/static/js/linear-plan-context.js`
- Create: `tests/test_srs_plan_aware_completion.py`

- [ ] На странице результатов SRS: если `linearPlanContext.isActive()` + slot=srs → показать plan-aware CTA («Следующий слот плана · Чтение книги» / «На дашборд»)
- [ ] Иначе — старое поведение (перемешать колоду/вернуться)
- [ ] Write tests: вход через `?source=linear_plan_card&from=linear_plan&slot=srs` → результаты → plan-aware CTA; вход через `/study/cards` напрямую → старое
- [ ] Run project test suite — must pass before task 8

### Task 8: Book reading slot completion

Чтение книги — особый случай: нет чёткого «конца сессии». Считать слот завершённым после прочтения минимального threshold.

**Files:**
- Modify: `app/books/routes.py` (reader view)
- Modify: шаблон reader'а
- Modify: `app/static/js/linear-plan-context.js` (threshold detection)
- Create: `tests/test_reading_plan_aware.py`

- [ ] Threshold для «слот завершён»: прочитано ≥ N слов или ≥ M% главы (уже используется в baseline-slot completion logic). Точный threshold уже есть в `reading_slot.py`, переиспользовать
- [ ] При достижении threshold внутри reader'а — показать floating-toast «Слот чтения выполнен» с CTA «Продолжить план → следующий слот»
- [ ] Юзер может продолжать читать — toast исчезает через 5 сек, но контекст остаётся активным до явного клика на CTA
- [ ] Если юзер покидает reader без клика — при следующем заходе на дашборд баннер всё равно показывается, т.к. threshold был достигнут (БД уже знает)
- [ ] Write tests: threshold достигнут → toast рендерится; клик на CTA → next-slot URL; без plan-контекста → toast не рендерится
- [ ] Run project test suite — must pass before task 9

### Task 9: Error review session completion

Error review — сессия по QuizErrorLog, завершается после прохождения всех ошибок в pool.

**Files:**
- Modify: роут error-review сессии (создан в task 7 прошлого плана)
- Modify: шаблон error-review completion
- Create: `tests/test_error_review_plan_aware.py`

- [ ] По завершении сессии error-review — plan-aware completion screen (как в curriculum-уроке)
- [ ] Если после error-review slot = last baseline → `day_secured` triggered → редирект на дашборд
- [ ] Иначе — «Следующий слот плана» CTA
- [ ] Write tests: session complete → next-slot endpoint вызван; secured → redirect; error-review как 4-й slot корректно замыкает день
- [ ] Run project test suite — must pass before final verification

---

## Acceptance Criteria

- Юзер с `use_linear_plan=True` кликает на baseline-слот на дашборде → URL содержит `?from=linear_plan&slot=<kind>` → sessionStorage записан.
- После завершения урока (любого типа curriculum + SRS + book + error review) — completion-экран показывает CTA «Следующий слот плана · <title>» (primary) и «На дашборд» (secondary). Curriculum-next CTA не появляется.
- Клик «Следующий слот плана» → ведёт точно в следующий incomplete baseline-слот в порядке `curriculum → srs → book → error_review`.
- Клик «На дашборд» → редирект на `/dashboard`, `linearPlanContext` clear.
- После завершения последнего baseline-слота → редирект на `/dashboard?day_secured=1`, дашборд показывает «🏆 День сохранён» баннер с XP/streak/continuation CTA.
- После `day_secured` клик «Продолжить обучение» на дашборде ведёт в следующий curriculum-урок **без** `?from=linear_plan` → completion этого следующего урока работает в standalone-режиме (curriculum-next).
- Контекст сбрасывается при cross-midnight (смена даты) и при явном «На дашборд».
- Юзеры без `use_linear_plan` (mission/legacy) — поведение completion-экрана не изменилось.
- `/api/daily-plan/next-slot` для юзера без флага возвращает 404.
- `pytest -m smoke` проходит <30 сек, включает 2 plan-aware сценария (не-последний слот + последний слот).

## Out of Scope / Backlog

1. **Bonus phase / continuation XP boost** — сейчас continuation после `day_secured` даёт обычный XP; идея с 1.2x-множителем «бонусного режима» отложена (можно добавить отдельным PR).
2. **Notification/Telegram** — plan-aware уведомления («Осталось 2 слота до сохранения дня») — future work.
3. **Pause/resume слот** — если юзер закрыл урок не досрочно, при возврате мы показываем «Продолжить слот плана» на дашборде — отдельный UX-фитч, не в этом плане.
4. **Cross-device context** — sessionStorage живёт в одной вкладке; синхронизация через cookie или серверный `UserDailyPlanContext` — при необходимости.
5. **Bonus slot 5** — редкие «бонусные слоты» (daily-race, weekly challenge) как 5-й опциональный элемент в plan-aware navigation.

## Risks

- **Legacy mission breakage**: все правки в `lesson_base_template.html` гейтятся через `linearPlanContext.isActive()`; missions не затрагиваются. Но тесты должны явно проверять обе ветки.
- **sessionStorage disabled**: некоторые браузеры/приватный режим отключают storage. Query-param остаётся primary source, sessionStorage — just страховка. При отсутствии storage просто работает только query-param.
- **Редирект race**: если `day_secured=true` и параллельно пользователь открывает несколько вкладок — может быть несколько одновременных редиректов. `DailyPlanLog.secured_at` идемпотентен (unique per user+date), лишнего XP не начислится.
- **Query-param leaks**: внешние интеграции (Telegram-бот, email-ссылки) могут случайно получить URL'ы с `?from=linear_plan` и запускать у несоответствующего юзера. Проверка `User.use_linear_plan=True` в API + ignoring в JS для юзеров без флага.
- **Book reading threshold edge case**: если юзер прочитал 99% и вышел — слот не завершён, при следующем заходе надо показать «осталось чуть-чуть». UX-полировка вне scope.
