# Аудит подсистемы «План дня» (2026-08-26)

## Overview

Аудит-только: найти баги и слабые места в подсистеме «План дня», **ничего не чинить**.
Результат — реестр находок `docs/audit/2026-08-26-daily-plan-audit.md` в формате прецедента
`docs/audit/2026-08-08-cross-zone-audit.md` (ID `DP-NNN`, severity P0–P3, схема «Файл:строка · Симптом · Сценарий отказа · Верификация»).

Метод (выбран пользователем): многоагентный фан-аут финдеров по линзам + **отдельный агент-скептик на каждую находку**, настроенный опровергать (при сомнении → refuted). В реестр идут только **CONFIRMED**; **PLAUSIBLE** — в приложение, опровергнутые — в секцию «Не переоткрывать без новых фактов».

Ключевое правило зоны: находка, противоречащая инварианту из раздела Daily Plan в `CLAUDE.md`, — это баг **либо в коде, либо в CLAUDE.md**; в каждой такой находке обязательна колонка «Где расхождение: код / CLAUDE.md».

## Context

Размер зоны (посчитано): 44 Python-файла в `app/daily_plan/` = 11 347 строк; `app/api/daily_plan.py` = 1 391 строка, 16 эндпоинтов; фронт — 3 шаблона (1 221 строка) + 2 JS (951 строка); тесты — 26 файлов в `tests/daily_plan/` = 8 021 строка.

- Ядро сборки: `app/daily_plan/plan.py` (549), `service.py` (222), `plan_builder.py` (355), `snapshot.py` (460), `next_step.py` (443), `route_progress.py` (211), `assembler.py` (831), `tier.py`, `milestones.py`, `repair_pressure.py`, `challenge.py`, `skips.py`, `level_utils.py`, `models.py`
- Item builders: `items/` — curriculum (739), srs (257), phrase_review, reading, grammar_review, error_review, challenge, skills, setup, word_set_quiz
- `linear/`: `chain.py` (530), `plan.py` (407), `xp.py` (559), `errors.py` (651), `progression.py` (368), `lesson_context.py` (329), `slots/` (7 файлов, 1 337), `grammar_theory.py`, `context.py`, `models.py`
- Роуты: `app/api/daily_plan.py` — `/daily-status`, `/daily-plan`, `/daily-summary`, `/streak`, `/daily-race`, `/daily-plan/next-slot`, `/daily-plan/continuation`, `/daily-plan/events`, `/error-review/summary`, `/daily-plan/error-review/complete`, `/daily-plan/phrase-review/complete`, `/plan/pause`, `/plan/resume`, `/streak/repair`, `/daily-plan/challenge/complete`, `/daily-plan/skip-lesson`
- `app/words/routes.py`: `_render_unified_dashboard` (:994), `daily_plan_next_step` (:1680), `_next_step_from_unified` (:1695); `compute_plan_steps` живёт в `app/achievements/streak_service.py:189` (не в words/routes.py — учесть при трассировке)
- Фронт: `partials/unified_daily_plan.html` (876), `words/dashboard_unified.html` (163), `components/_daily_plan_progress.html` (182), `app/static/js/linear-daily-plan.js` (418), `linear-plan-context.js` (533)

Уже видимые кандидаты (гипотезы для проверки, не находки):

- `linear/plan.py` **жив частично**: `app/study/routes.py:1016` тянет `SLOT_ESTIMATED_MINUTES`, `daily_plan/plan.py:353` импортирует 4 хелпера; при этом `get_linear_plan` (:299) и `build_chain` (`chain.py:427`) вызываются только друг из друга — продакшн-вызывателей не найдено, живые ссылки только из тестов (`tests/telegram/test_plan_status.py` патчит `linear.chain.extend_chain_after_activity`)
- `assembler.py` (831 строка) — прод-вызывателей не найдено, ссылки только из тестов (`test_daily_mission_models`, `test_get_card_counts`, `test_counting`, `test_navigation`), при том что CLAUDE.md объявляет mission-код удалённым

Внешние факты, которые финдеры обязаны знать (иначе дадут ложные срабатывания):

- учебный день начинается в 02:00 — это **осознанное решение владельца**, не баг
- на master 26 заранее красных теста (baseline 2026-08-08) — сравнивать с baseline, а не винить зону
- `docs/` и `scripts/` в `.gitignore`, но отслеживаются: для правок — `git add -u`, для нового файла — `git add -f`

## Development Approach

- **Testing approach**: неприменимо в обычном смысле — **это аудит, а не фича**. Ни одна задача не меняет продакшн-код и не добавляет тестов, поэтому пункты «write tests» здесь заменены на **верификацию находок**: каждая находка подтверждается перечитанным кодом (`path:line`) и явным сценарием отказа, а не правдоподобием.
- Порядок жёсткий: сбор (Task 2–7) → верификация и дедуп (Task 8) → реестр (Task 9). Финдеры не пишут в итоговый документ напрямую — только в промежуточные заметки, иначе неопровергнутые гипотезы просачиваются в реестр.
- Фан-аут — через параллельные субагенты (Agent tool) внутри каждой задачи сбора; скептик на находку — отдельный агент, не тот же, что нашёл.
- Каждая линза в промпте финдера получает: раздел Daily Plan из CLAUDE.md, список инвариантов, и «известные не-баги» (02:00, baseline-краснота).
- **Без молчаливых усечений:** если линза не запускалась или файл не читался — это фиксируется в секции «Покрытие и сознательные пропуски», а не замалчивается.

## Implementation Steps

### Task 1: Базис, инвентаризация и скелет реестра

**Files:**
- Create: `docs/audit/2026-08-26-daily-plan-audit.md` (скелет)
- Create: `.ralphex/audit-notes/daily-plan/` (промежуточные заметки финдеров, не коммитятся в реестр)

- [x] выписать из `CLAUDE.md` раздел Daily Plan в машиночитаемый список инвариантов INV-01…INV-NN (day_secured только от required; заблокированный спайн ≠ graduated; `_plan_meta.user_id` обязателен; `write_secured_at` идемпотентен и race-safe; подмена required-SRS на deck-quiz только при наличии колод; дедуп очереди по `id` И по `data.lesson_id`; `day_secured` всегда False на assembly time; событие `dailyPlanStepComplete` слушателей не имеет) — этот список идёт в промпт каждому финдеру
- [x] построить фактическую инвентаризацию зоны из живого `app.url_map` (все 16 эндпоинтов + `words.*`), а не по grep: имя функции, методы, декораторы auth/rate-limit
- [x] построить call-graph зоны: кто импортирует `assembler.py`, `linear/plan.py`, `linear/chain.py`, `milestones.py`, `tier.py`, `repair_pressure.py`, `route_progress.py`, `snapshot.py` — отдельно прод-вызыватели и тест-вызыватели
- [x] снять baseline: `pytest tests/daily_plan -q` + `pytest -m smoke -q`, сохранить вывод в `docs/audit/2026-08-26-baseline-daily-plan.txt` (аудит на него ссылается; красные тесты вне baseline — сами по себе находка)
- [x] создать скелет реестра: схема находки, критерии P0–P3, таблица линз, пустые секции по подзонам, секция «Покрытие и сознательные пропуски»

### Task 2: Финдеры по ядру сборки плана

**Files:**
- Read: `app/daily_plan/plan.py`, `service.py`, `plan_builder.py`, `snapshot.py`, `next_step.py`, `route_progress.py`, `tier.py`, `milestones.py`, `repair_pressure.py`, `skips.py`, `level_utils.py`, `models.py`
- Write: заметки финдеров в `.ralphex/audit-notes/daily-plan/core-*.md`

- [x] линза A — **границы**: `None` от `find_next_lesson_state`, пустой `required`, graduated, заблокированный модуль, `plan_paused_until`, новый юзер без истории, юзер без `onboarding_level`; для каждой ветки — что попадает в payload и что делает `compute_day_secured_from_activity`
- [x] линза B — **инварианты INV-01…INV-NN**: для каждого — найти код, который его держит, и код, который его может нарушить; помечать сторону расхождения (код / CLAUDE.md)
- [x] линза C — **часовые пояса и граница учебного дня**: `get_user_local_date` vs naive-UTC колонки, `day_to_naive_utc`, граница 02:00, юзер с `timezone=None`, смена tz в течение дня, plan_date в snapshot vs plan_date в `write_secured_at`
- [x] линза D — **идемпотентность и гонки двух вкладок**: `write_secured_at` (savepoint + IntegrityError), snapshot-reconcile, `overlay_completion`, точки commit/flush, что происходит при двух одновременных `/api/daily-plan`
- [x] линза E — **N+1 и стоимость сборки**: запросы внутри циклов по item'ам/урокам очереди, повторные резолвы `Module`/`Lesson`, отсутствие `selectinload`; замерить фактическое число запросов на сборку плана (echo/counter), а не оценивать на глаз
- [x] свести заметки 5 финдеров в единый список кандидатов ядра с `path:line` и сценарием отказа (без дедупа — он в Task 8)

### Task 3: Финдеры по item builders и linear/*

**Files:**
- Read: `app/daily_plan/items/*` (10 файлов), `app/daily_plan/linear/` (slots/, xp.py, errors.py, progression.py, lesson_context.py, grammar_theory.py, context.py, models.py)
- Write: `.ralphex/audit-notes/daily-plan/items-*.md`

- [x] линза A — **curriculum-очередь**: дедуп по `id` И по `data.lesson_id`, фильтр заблокированных модулей и «hard-блок выбрасывает остаток CEFR-уровня», кеш решения per `module_id`, over-fetch +1 → `has_more_optional`, `OPTIONAL_MAX=15` / `CONTINUATION_QUEUE_LIMIT=12`, поведение при отсутствии anchor
- [x] линза B — **SRS-слот**: подмена required-SRS на deck-quiz строго при `_count_user_deck_quiz_words > 0`, схлопывание optional-дубля, completion gate при внутридневных learning-шагах, согласованность с `app/srs/counting.py`
- [x] линза C — **прочие слоты** (reading / listening / speaking / writing / error_review / grammar_review / phrase_review / challenge / word_set_quiz / skills / setup): book-scoped `_read_today`, union курсовой и standalone грамматики, пороги и cooldown'ы, что происходит при пустых источниках
- [x] линза D — **XP и идемпотентность в `linear/xp.py`**: dedup-ключи `(user, date, source)`, perfect-day для graduated и заблокированного, `LESSON_TYPE_TO_SOURCE` — полнота против списка типов уроков, score-aware пробрасывание
- [x] линза E — **порядок и бюджет**: адаптация порядка по времени суток, `plan_difficulty` light/normal/intensive, `total_estimated_minutes` vs фактический состав, `graduated=True` для заблокированного в `build_optional`
- [x] свести заметки в список кандидатов подзоны с `path:line`

### Task 4: Финдеры по API и серверному рендеру дашборда

**Files:**
- Read: `app/api/daily_plan.py` (16 эндпоинтов), `app/words/routes.py` (`_render_unified_dashboard`, `daily_plan_next_step`, `_next_step_from_unified`), `app/achievements/streak_service.py:compute_plan_steps`, `app/daily_plan/service.py`
- Write: `.ralphex/audit-notes/daily-plan/api-*.md`

- [x] линза A — **расхождение payload**: собрать фактические ответы `/api/daily-plan`, `/api/daily-status`, `/api/daily-plan/next-slot`, `/api/daily-plan/continuation` и контекст серверного рендера дашборда для одного и того же юзера в одном и том же состоянии; таблица «ключ → значение в каждом источнике» и явный список расхождений (`day_secured`, `srs_limit_reason`, счётчики required/optional, `tomorrow_preview`)
- [x] линза B — **контракт ошибок и валидация ввода**: 16 эндпоинтов × (не-dict тело, чужой `lesson_id`, невалидный enum, отсутствующие поля) → 400/403/404 против 500; соответствие `api_error` и глобальному JSON-контракту ошибок
- [x] линза C — **квоты, гонки, транзакции**: `DAILY_SKIP_QUOTA=1` и `DAILY_SLOT_SKIP_QUOTA=1` (DB-enforce vs проверка в коде), двойной POST на `/events`, `/plan/pause` + `/plan/resume` в один день, `/streak/repair`, `/daily-plan/challenge/complete`, где commit, где flush, что откатывается при исключении
- [x] линза D — **нормализация completion на дашборде**: precedence `completed / skipped / blocked` в `_render_unified_dashboard`, согласованность с `compute_plan_steps` и с тем, что читает шаблон
- [x] линза E — **auth и rate-limit**: `@login_required`/module-гейты/лимиты на каждом из 16 эндпоинтов, чтение чужого `user_id` из параметров
- [x] свести заметки в список кандидатов подзоны с `path:line`

### Task 5: Финдеры по фронтенду плана

**Files:**
- Read: `app/templates/partials/unified_daily_plan.html`, `app/templates/words/dashboard_unified.html`, `app/templates/components/_daily_plan_progress.html`, `app/static/js/linear-daily-plan.js`, `app/static/js/linear-plan-context.js`
- Write: `.ralphex/audit-notes/daily-plan/frontend-*.md`

- [x] линза A — **расхождение клиента и сервера**: какие поля payload шаблон/JS читают, каких не существует, какие существуют и игнорируются; ветки шаблона, недостижимые при пустом `required` (прецедент: `show_survey` был заперт внутри `{% if u_required %}`), **i18n и a11y**: литералы, вставляемые в DOM мимо `window.I18N`; `_('…')` в inline-JS; `aria-valuenow` при обновлении ширины прогресс-бара; single-select vs toggle роли
- [x] линза B — **fetch-надёжность**: обработка не-2xx и сетевого сбоя в `fetchNextSlot` / `showLessonCompletion` / `linear-daily-plan.js`, ложный успех на упавшем сохранении, двойная отправка по двойному клику, гонка inline `daily_plan_ctx` против HTTP round-trip, **мёртвый фронт-код**: диспатчеры `dailyPlanStepComplete` (слушателей нет по CLAUDE.md — проверить фактически), осиротевшие контейнеры/флаги после удаления `daily-plan-next.js`, неиспользуемые ветки
- [x] свести заметки в список кандидатов подзоны с `path:line`

### Task 6: Liveness-аудит — что из зоны реально мёртвое

**Files:**
- Read: `app/daily_plan/assembler.py`, `linear/plan.py`, `linear/chain.py`, `milestones.py`, `tier.py`, `repair_pressure.py`, `challenge.py`, `route_progress.py`
- Write: `.ralphex/audit-notes/daily-plan/liveness.md`

- [x] для каждого модуля-кандидата построить полный список вызывателей, **раздельно**: прод-код / тесты / только внутренние ссылки — методом импорт-графа плюс живой прогон (`app.url_map`, реальный запрос к дашборду с трассировкой импортов), а не только grep
- [x] `assembler.py` (831 строка): подтвердить или опровергнуть, что весь модуль удерживается только тестами; выписать, какие символы тянутся из `app/srs/*` и `tests/*`
- [x] `linear/plan.py`: разделить живую часть (`SLOT_ESTIMATED_MINUTES` → `app/study/routes.py:1016`; 4 хелпера → `daily_plan/plan.py:353`; `_get_user_focus`) и мёртвую (`get_linear_plan` и её транзитивные зависимости, включая `chain.build_chain`)
- [x] `linear/chain.py` (530 строк): подтвердить или опровергнуть отсутствие прод-вызывателей; отдельно отметить `tests/telegram/test_plan_status.py`, который патчит `extend_chain_after_activity` — патч несуществующего пути в проде это тест, который ничего не проверяет
- [x] зафиксировать расхождение с CLAUDE.md явно: где документ говорит «удалено», а код на месте — это находка **в CLAUDE.md**, если код действительно мёртв, и находка **в коде**, если код жив вопреки документу
- [x] оценить объём мёртвого кода в строках — без этого невозможно приоритизировать будущую чистку (сама чистка в этот аудит не входит)

### Task 7: Дыры в покрытии tests/daily_plan

**Files:**
- Read: `tests/daily_plan/**` (26 файлов), плюс тесты зоны вне каталога (`tests/telegram/test_plan_status.py`, `tests/study/test_settings.py`, `tests/test_daily_mission_models.py`)
- Write: `.ralphex/audit-notes/daily-plan/coverage.md`

- [x] прогнать покрытие по зоне: `pytest tests/daily_plan --cov=app/daily_plan --cov=app/api/daily_plan.py --cov-report=term-missing`, сохранить отчёт; красные тесты сверить с baseline из Task 1
- [x] составить матрицу «модуль зоны × есть ли тест»: непокрытые модули и функции с нулевым покрытием — отдельным списком
- [x] проверить покрытие именно **инвариантов** INV-01…INV-NN: у какого инварианта есть тест-страж, у какого нет (инвариант без теста — слабое место, даже если код сегодня верен)
- [x] найти тесты-пустышки: патчат несуществующие пути, ассертят на мок вместо результата, дублируют друг друга; для каждого — почему он ничего не ловит
- [x] проверить покрытие граничных состояний из линзы A Task 2 (пустой required, graduated, заблокированный, paused, новый юзер) — какие из них не встречаются ни в одном тесте
- [x] свести в список кандидатов-находок категории «покрытие» (severity, как правило, P2–P3, но инвариант P1-уровня без стража может быть P2)

### Task 8: Адверсариальная верификация и приоритизация

**Files:**
- Read: все заметки `.ralphex/audit-notes/daily-plan/*`
- Write: `.ralphex/audit-notes/daily-plan/verified.md`

- [x] дедуплицировать кандидатов между подзонами (одна первопричина, проявляющаяся в API и во фронте, — одна находка с перечислением мест проявления)
- [x] на **каждую** находку запустить отдельного агента-скептика с задачей **опровергнуть**: при сомнении вердикт `refuted`; подтверждение только по факту перечитанного кода, с цитатой `path:line`; скептик не видит, кто нашёл
- [x] по находкам-кандидатам в P0/P1 прогнать второй проход тремя **независимыми** агентами-линзами (корректность / воспроизводимость / влияние на пользователя) — не одним читателем с тремя линзами (ограничение прецедента 2026-08-08, которое там честно признано ценой коррелированности суждений)
- [x] присвоить severity P0–P3 по критериям прецедента; для каждой находки, задевающей инвариант, заполнить обязательную колонку «Где расхождение: код / CLAUDE.md»
- [x] сформировать три корзины: CONFIRMED (в реестр), PLAUSIBLE (в приложение), REFUTED (в секцию «не переоткрывать без новых фактов», с причиной опровержения)

### Task 9: Сборка реестра и критик на полноту

**Files:**
- Modify: `docs/audit/2026-08-26-daily-plan-audit.md`

- [x] заполнить реестр: индексная таблица (`ID | Sev | Файл:строка | Симптом | Вериф.`) + детали по P0/P1/P2/P3, формат — как в `docs/audit/2026-08-08-cross-zone-audit.md`
- [x] отдельные секции: «Расхождения с CLAUDE.md» (с явным указанием стороны ошибки), «Liveness / мёртвый код», «Дыры в покрытии», «Опровергнуто скептиками — не переоткрывать без новых фактов», «PLAUSIBLE (приложение)»
- [x] секция «Покрытие и сознательные пропуски»: что просканировано, что нет, какие линзы не запускались (например, CSRF, CSP, миграции, фоновые процессы, нагрузочное поведение) — без молчаливых усечений
- [x] запустить агента-критика на полноту: какие файлы зоны не прочитаны ни одним финдером, какие эндпоинты не тронуты, какие инварианты не проверены; его находки — либо новая работа, либо явная запись в «сознательные пропуски»
- [x] проверить документ на самосогласованность: числа в шапке = числа в индексе = число секций деталей; каждая находка имеет `path:line`, сценарий отказа и вердикт верификации
- [x] убедиться, что **ни один продакшн-файл не изменён**: `git status` показывает только новые файлы в `docs/audit/` (файлы в `docs/` gitignored, но отслеживаются — для нового файла нужен `git add -f`)

### Task 10: Verify acceptance criteria

- [ ] `git diff --stat` по `app/` и `tests/` — пусто (аудит не правит код; любое изменение здесь = нарушение задания)
- [ ] `pytest tests/daily_plan -q` и `pytest -m smoke -q` дают тот же результат, что baseline из Task 1 (аудит не мог ничего сломать, это проверка гигиены прогонов)
- [ ] каждая находка реестра имеет: ID, severity, `path:line`, сценарий отказа, вердикт скептика; находок без вердикта — ноль
- [ ] все 16 эндпоинтов, все 44 Python-файла зоны, 3 шаблона и 2 JS либо покрыты финдером, либо перечислены в «сознательных пропусках» с причиной

### Task 11: Update documentation

- [ ] добавить в `CLAUDE.md` короткую ссылку на новый реестр в блоке аудитов (без переписывания раздела Daily Plan — исправления инвариантов делает ремедиация, не аудит)
- [ ] если аудит нашёл расхождения именно в тексте `CLAUDE.md` — перечислить их в реестре как отдельный список с предлагаемыми формулировками, но **не править** документ в рамках аудита
- [ ] README не трогать — пользовательских изменений нет

## Post-Completion (вручную, вне чекбоксов задач)

- Решение о ремедиации: какие находки чинить и в каком порядке — отдельный план, отдельная ветка.
- Удаление мёртвого кода из Task 6 — только после подтверждения владельцем; агент `dead-code-cleaner` подходит, но это отдельная задача.
