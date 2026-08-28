# Аудит подсистемы «План дня» — 2026-08-26

> Реестр находок одной зоны: **План дня** (`app/daily_plan/`, `app/api/daily_plan.py`,
> дашбордный рендер в `app/words/routes.py`, 3 шаблона, 2 JS).
> План: `docs/plans/2026-08-26-daily-plan-audit.md`.
> Образец формата: `docs/audit/2026-08-08-cross-zone-audit.md`.
> Baseline прогонов: `docs/audit/2026-08-26-baseline-daily-plan.txt`.
>
> **Принцип:** аудит **не правит код**. Ни один файл под `app/` и `tests/` этим аудитом
> не изменён — Task 10 это проверяет через `git diff --stat`. Ремедиация — отдельный план,
> отдельная ветка.
>
> **Базис аудита — ветка `word-sets-quiz` @ `0b1f8b7f`, не `master`.** Task 10 сверяет
> «код не тронут» именно с этой точкой. Ветка несёт поверх `master` фичу курируемых наборов
> слов, и часть зоны существует только в ней: `app/daily_plan/items/word_set_quiz.py`,
> kind `word_set_quiz` в `_OPTIONAL_PRIORITY`/`Kind`/`CompletionSignal`. Поэтому
> **`DP-113` отсутствует на `master` целиком**, а `DP-038` и `CM-3` на `master` верны лишь
> частично (в арифметике бюджета и в перечне `_OPTIONAL_PRIORITY` `word_set_quiz` там нет).
> Ремедиационную ветку резать от того же базиса; «Размер зоны» (44 файла / 11 347 строк)
> и severity-итоги посчитаны по нему же.

**Статус:** ✅ Task 1–9 закрыты. Сбор (Task 2–7), адверсариальная верификация (Task 8) и
сборка реестра (Task 9) выполнены. Итог: **184** канонических кандидата → **127 CONFIRMED**
(0 P0 · 4 P1 · 71 P2 · 52 P3), **3 PLAUSIBLE** (приложение), **54 REFUTED** (секция
«не переоткрывать»). Находок без вердикта скептика — **0**.

---

## Как собрано

Многоагентный аудит с адверсариальной верификацией — метод выбран владельцем.

1. **Фан-аут финдеров по линзам** (Task 2–7). Каждый финдер получает: раздел Daily Plan из
   `CLAUDE.md`, машиночитаемый список инвариантов `INV-01…INV-47`, и список «известных не-багов»
   (граница учебного дня 02:00, заранее красный baseline). Финдеры пишут **только** в промежуточные
   заметки `.ralphex/audit-notes/daily-plan/*`, а не в этот реестр напрямую — иначе неопровергнутые
   гипотезы просачиваются в итог.
2. **Скептик на каждую находку** (Task 8) — отдельный агент, не тот, что нашёл, настроенный
   **опровергать**: при сомнении вердикт `refuted`. Подтверждение — по факту перечитанного кода
   с цитатой `path:line`, а не по правдоподобию.
3. **Второй проход по P0/P1** — тремя **независимыми** агентами-линзами: корректность /
   воспроизводимость / влияние на пользователя. Это сознательно жёстче прецедента 2026-08-08,
   где второй проход честно признан прогнанным одним читателем с тремя линзами, и где цена этого
   (коррелированность суждений) вынесена в ограничения.
4. **Три корзины:** CONFIRMED → в реестр, PLAUSIBLE → в приложение, REFUTED → в секцию
   «Опровергнуто скептиками», с причиной опровержения.

### Ключевое правило зоны

Находка, противоречащая инварианту из раздела Daily Plan в `CLAUDE.md`, — это баг **либо в коде,
либо в `CLAUDE.md`**. У каждой такой находки обязательна колонка **«Где расхождение: код /
CLAUDE.md»**. Документ может быть просто устаревшим; «код неверен» по умолчанию — не позиция аудита.

### Линзы (что планировалось запустить)

| Подзона | Task | Линзы |
|---|---|---|
| **Ядро сборки** — `plan.py`, `service.py`, `plan_builder.py`, `snapshot.py`, `next_step.py`, `route_progress.py`, `tier.py`, `milestones.py`, `repair_pressure.py`, `skips.py`, `level_utils.py`, `models.py` | 2 | (A) границы · (B) инварианты INV-01…INV-47 · (C) часовые пояса и граница дня · (D) идемпотентность и гонки · (E) N+1 и стоимость сборки |
| **Item builders и `linear/`** — `items/` (10 файлов), `linear/slots/`, `xp.py`, `errors.py`, `progression.py`, `lesson_context.py`, `grammar_theory.py`, `context.py`, `models.py` | 3 | (A) curriculum-очередь · (B) SRS-слот · (C) прочие слоты · (D) XP и идемпотентность · (E) порядок и бюджет |
| **API и серверный рендер** — `app/api/daily_plan.py`, `_render_unified_dashboard`, `daily_plan_next_step`, `_next_step_from_unified`, `compute_plan_steps` | 4 | (A) расхождение payload между источниками · (B) контракт ошибок и валидация · (C) квоты, гонки, транзакции · (D) нормализация completion · (E) auth и rate-limit |
| **Фронтенд** — `partials/unified_daily_plan.html`, `words/dashboard_unified.html`, `components/_daily_plan_progress.html`, `linear-daily-plan.js`, `linear-plan-context.js` | 5 | (A) расхождение клиента и сервера · (B) fetch-надёжность · (C) мёртвый фронт-код · (D) i18n и a11y |
| **Liveness** — `assembler.py`, `linear/plan.py`, `linear/chain.py`, `milestones.py`, `tier.py`, `repair_pressure.py`, `challenge.py`, `route_progress.py` | 6 | импорт-граф + живой прогон; раздельно прод-вызыватели / тесты / внутренние ссылки |
| **Покрытие тестами** — `tests/daily_plan/**` (26 файлов) + тесты зоны вне каталога | 7 | покрытие по строкам · матрица «модуль × тест» · покрытие **инвариантов** · тесты-пустышки · граничные состояния |

Секция **«Покрытие и сознательные пропуски»** (ниже) фиксирует, что просканировано, а что нет —
**без молчаливых усечений**. Незапущенная линза записывается туда, а не замалчивается.

---

## Схема находки

`ID | Подзона | Файл:строка | Severity | Симптом | Сценарий отказа | Верификация | Где расхождение`

| Поле | Значение |
|---|---|
| **ID** | `DP-NNN`, сквозная нумерация по всей зоне |
| **Подзона** | Ядро / Items · linear · API · Фронт · Liveness · Покрытие. Находка с одной первопричиной, проявляющаяся в нескольких подзонах, живёт в подзоне первопричины; места проявления перечисляются в теле |
| **Файл:строка** | реальный `path:line` на момент аудита (HEAD `0b1f8b7f`). После ремедиации строки сдвигаются — сверяться с git-историей |
| **Severity** | P0 / P1 / P2 / P3 (критерии ниже) |
| **Симптом** | что видит пользователь / что ломается — одним предложением |
| **Сценарий отказа** | конкретные вход и состояние → неверный результат. Не «может сломаться», а «при X получаем Y» |
| **Верификация** | CONFIRMED (скептик не смог опровергнуть, подтверждено чтением кода) / PLAUSIBLE (не опровергнуто, но и не доказано → в приложение) |
| **Где расхождение** | `код` / `CLAUDE.md` / `—` (если инвариант не задет). Обязательно для любой находки, задевающей INV-NN |

Task 10 проверяет, что **ни одна находка не осталась без вердикта скептика**.

## Критерии severity

- **P0** — сломанный пользовательский путь или утечка данных. Флоу недоступен либо нефункционален
  без обходного пути; данные пользователя видны чужому; необратимая потеря данных или прогресса.
- **P1** — функциональный баг с обходом. Работает неверно, но пользователь может достичь цели
  другим путём; либо баг на неглавном пути.
- **P2** — деградация UX или производительности. Флоу работает и приводит к цели, но с лишними
  шагами, задержкой, шумом или неконсистентностью.
- **P3** — косметика и технический долг. Не влияет на поведение: мёртвый код, дублирование,
  расхождение конвенций, отсутствующий тест-страж при сегодня-верном коде.

**Правило понижения:** при большинстве опровержений на втором проходе severity **понижается**,
а находка не удаляется; понижение фиксируется в её теле.

**Специфика этой зоны.** «План дня» — единственный экран, который учащийся видит каждый день, и
единственный источник `day_secured`, от которого зависят streak, ранги, perfect-day и XP. Поэтому
находка, замораживающая `day_secured` или streak для достижимого состояния пользователя, — это
**P0**, даже если сам экран рисуется без ошибок: пользователь занимается, а прогресс не идёт.
Оговорка касается **невосстановимой** заморозки: если пользователь может сам вернуть себе
закрываемый день (пусть и со следующих суток), находка остаётся P1 — но обязана объяснить
восстановительный путь в своём теле (прецедент — DP-033).

---

## Сводка severity

> Только CONFIRMED. PLAUSIBLE (3) и REFUTED (54) в счёт находок не входят — они в
> приложении и в секции «Опровергнуто скептиками».

| Severity | Ядро | Items · linear | API | Фронт | Liveness | Покрытие | Всего |
|---|---|---|---|---|---|---|---|
| P0 | — | — | — | — | — | — | **0** |
| P1 | 1 | 3 | — | — | — | — | **4** |
| P2 | 20 | 23 | 26 | 2 | — | — | **71** |
| P3 | 11 | 15 | 14 | 3 | 6 | 3 | **52** |
| **Всего** | **32** | **41** | **40** | **5** | **6** | **3** | **127** |

Числа сверены Task 9: шапка = индексы подзон = число секций деталей (проверка
`.ralphex/audit-notes/daily-plan/tools/check_consistency.py`, вывод — в секции «Самосогласованность» в конце файла).

---

## Базовая линия (Task 1)

### Размер зоны — посчитано на HEAD `0b1f8b7f`

| Что | Значение |
|---|---|
| `app/daily_plan/**.py` | **44** файла / **11 347** строк |
| `app/api/daily_plan.py` | **1 391** строка |
| `tests/daily_plan/**.py` | **26** файлов / **8 021** строка |
| Правил зоны в живом `app.url_map` | **19** |
| Шаблоны | 3 (`unified_daily_plan.html`, `dashboard_unified.html`, `_daily_plan_progress.html`) |
| JS | 2 (`linear-daily-plan.js`, `linear-plan-context.js`) |

### Прогоны

| Прогон | Итог | Красные |
|---|---|---|
| `pytest tests/daily_plan --tb=line` | **2 failed, 402 passed** (10.0 с) | `test_srs_slot_completion.py::test_fallback_fires_corrective_award_when_pool_empty`, `::test_fallback_is_idempotent` |
| `pytest -m smoke --tb=line` | **695 passed**, 9917 deselected (16.9 с) | нет |

Обе красные строки присутствуют в baseline 2026-08-08 (`docs/audit/2026-08-08-baseline-pytest.txt:67-68`)
дословно ⇒ **новых красных тестов в зоне нет**. Сами два падения остаются кандидатом-находкой для
Task 7: заранее красный тест зоны — это либо баг, который никто не чинит, либо тест, который ничего
не проверяет. Подробности и команда воспроизведения — в `docs/audit/2026-08-26-baseline-daily-plan.txt`.

### Инвентаризация роутов — из живого `app.url_map`, не по grep

Метод: приложение реально собирается (`create_app` с конфигом-зеркалом `tests/conftest.py`),
карта берётся из Flask, декораторы восстанавливаются по исходнику незавёрнутой функции и по
цепочке `__wrapped__`. Полная выгрузка — `.ralphex/audit-notes/daily-plan/inventory-urlmap.md`.

| # | Rule | Methods | Endpoint | Файл:строка | Auth | CSRF |
|---|---|---|---|---|---|---|
| 1 | `/api/daily-status` | GET | `api_daily_plan.daily_status` | `app/api/daily_plan.py:270` | `@api_auth_required` | — |
| 2 | `/api/daily-plan` | GET | `api_daily_plan.daily_plan` | `app/api/daily_plan.py:448` | `@api_auth_required` | — |
| 3 | `/api/daily-summary` | GET | `api_daily_plan.daily_summary` | `app/api/daily_plan.py:499` | `@api_auth_required` | — |
| 4 | `/api/streak` | GET | `api_daily_plan.streak` | `app/api/daily_plan.py:533` | `@api_auth_required` | — |
| 5 | `/api/daily-race` | GET | `api_daily_plan.daily_race_status` | `app/api/daily_plan.py:553` | `@api_auth_required` | — |
| 6 | `/api/daily-plan/next-slot` | GET | `api_daily_plan.daily_plan_next_slot` | `app/api/daily_plan.py:604` | `@api_auth_required` | — |
| 7 | `/api/daily-plan/continuation` | GET | `api_daily_plan.daily_plan_continuation` | `app/api/daily_plan.py:663` | `@api_auth_required` | — |
| 8 | `/api/daily-plan/events` | POST | `api_daily_plan.record_daily_plan_event` | `app/api/daily_plan.py:715` | `@api_auth_required` | `@csrf.exempt` |
| 9 | `/api/error-review/summary` | GET | `api_daily_plan.error_review_summary` | `app/api/daily_plan.py:902` | `@api_auth_required` | — |
| 10 | `/api/daily-plan/error-review/complete` | POST | `api_daily_plan.complete_error_review` | `app/api/daily_plan.py:923` | `@api_auth_required` | `@csrf.exempt` |
| 11 | `/api/daily-plan/phrase-review/complete` | POST | `api_daily_plan.complete_phrase_review` | `app/api/daily_plan.py:1014` | `@api_auth_required` | `@csrf.exempt` |
| 12 | `/api/plan/pause` | POST | `api_daily_plan.plan_pause` | `app/api/daily_plan.py:1094` | `@api_auth_required` | `@csrf.exempt` |
| 13 | `/api/plan/resume` | POST | `api_daily_plan.plan_resume` | `app/api/daily_plan.py:1151` | `@api_auth_required` | `@csrf.exempt` |
| 14 | `/api/streak/repair` | POST | `api_daily_plan.streak_repair` | `app/api/daily_plan.py:1184` | `@api_auth_required` | `@csrf.exempt` |
| 15 | `/api/daily-plan/challenge/complete` | POST | `api_daily_plan.challenge_complete` | `app/api/daily_plan.py:1209` | `@api_auth_required` | `@csrf.exempt` |
| 16 | `/api/daily-plan/skip-lesson` | POST | `api_daily_plan.skip_lesson` | `app/api/daily_plan.py:1296` | `@api_auth_required` | `@csrf.exempt` |
| 17 | `/api/daily-plan/next-step` | GET | `words.daily_plan_next_step` | `app/words/routes.py:1678` | `@login_required` | — |
| 18 | `/api/streak/repair-web` | POST | `words.streak_repair_web` | `app/words/routes.py:1803` | `@login_required` | — |
| 19 | `/dashboard` | GET | `words.dashboard` | `app/words/routes.py:1233` | `@login_required` + `@module_required('words')` | — |

**Три факта, которые обязаны учесть финдеры Task 4:**

1. Правил зоны **19**, а не 16. Строки 17–19 живут в blueprint `words` и в исходном списке плана
   отсутствовали; `/api/streak/repair-web` (`words.streak_repair_web`) — второй, независимый путь
   починки серии рядом с `/api/streak/repair`, и он **не** покрыт списком «16 эндпоинтов».
2. **Ни на одном эндпоинте зоны нет собственного `@limiter.limit`.** Действуют только глобальные
   дефолты `10000 per hour` и `100 per second` (`limiter._route_limits` для зоны пуст,
   blueprint-лимитов нет). При этом **8 POST-эндпоинтов зоны — `@csrf.exempt`**.
3. Все 19 правил закрыты аутентификацией: 16 через `@api_auth_required`, 3 через `@login_required`.
   Ни одного анонимного правила в зоне нет.

### Call-graph модулей-кандидатов (вход в Task 6)

Метод: AST-обход импортов по `app/ tests/ config/ scripts/ migrations/ run.py` **плюс** строковые
ссылки вида `patch("app.daily_plan…")` — последние обязательны, иначе `mock.patch` по dotted-path
невидим для импорт-графа. Полная выгрузка — `.ralphex/audit-notes/daily-plan/inventory-callgraph.md`.

| Модуль | Строк | Прод-вызывателей | Тест-вызывателей | Ссылок из других кандидатов |
|---|---|---|---|---|
| `app/daily_plan/assembler.py` | 831 | **0** | 10 | 0 |
| `app/daily_plan/linear/chain.py` | 530 | **0** | 1 | 2 (`linear/plan.py:107,337`) |
| `app/daily_plan/snapshot.py` | 460 | 2 | 1 | 0 |
| `app/daily_plan/linear/plan.py` | 407 | 2 | 4 | 1 (`linear/chain.py:373`) |
| `app/daily_plan/milestones.py` | 271 | 3 | 0 | 0 |
| `app/daily_plan/route_progress.py` | 211 | 3 | 1 | 0 |
| `app/daily_plan/tier.py` | 154 | 1 | 1 | 1 (`snapshot.py:130`) |
| `app/daily_plan/repair_pressure.py` | 144 | **0** | **0** | 1 (`assembler.py:15`) |

Наблюдения Task 1 — это **входные данные**, а не вердикты; доказательство мёртвости за Task 6:

- `assembler.py` (831) и `chain.py` (530) прод-вызывателей не имеют. `chain.py` держится за
  `linear/plan.py`, а тот вызывается из прода **только** ради `SLOT_ESTIMATED_MINUTES`
  (`app/study/routes.py:1016`) и четырёх хелперов (`app/daily_plan/plan.py:353`) — ни один из них
  не ведёт в `build_chain`. То есть цепочка `chain.py → linear/plan.py → прод` может оказаться
  разомкнутой.
- `repair_pressure.py` (144) не имеет ни прод-, ни тест-вызывателей: единственная ссылка на него —
  из `assembler.py:15`, у которого своих прод-вызывателей ноль. Кандидат на **транзитивно** мёртвый
  модуль.
- `tests/telegram/test_plan_status.py:150,152` патчит `app.daily_plan.linear.chain.extend_chain_after_activity`
  и `app.daily_plan.linear.plan.compute_linear_day_secured`. Если эти пути в проде не исполняются,
  патч ничего не проверяет — кандидат в «тесты-пустышки» (Task 7).

---

## Индекс P1 — четыре находки, которые ремедиация обязана рассмотреть первыми

> P0 в зоне нет. Все четыре P1 прошли второй проход тремя независимыми линзами
> (корректность / воспроизводимость / влияние на пользователя) и подтверждены всеми тремя.

| ID | Sev | Файл:строка | Симптом | Вериф. | Расхождение |
|---|---|---|---|---|---|
| DP-001 | P1 | `app/api/daily_plan.py:278` | три базиса суток в одном вызове `process_streak_on_activity`: `user_today` — учебный день (02:00), `real_activity` — календарная полночь, `find_missed_date`/починка — календарная полночь на клиентском `?tz=`; клиентский `?tz=` — вторичный вектор | CONFIRMED | код |
| DP-033 | P1 | `app/daily_plan/items/reading.py:50` | required-слот чтения строится без `can_user_access_book`/`is_published`: пункт ведёт в 403 и `day_secured` недостижим (подслучай «черновик» закрыт на ветке — см. тело находки; основной механизм лицензия/модуль открыт) | CONFIRMED | код |
| DP-034 | P1 | `app/curriculum/routes/lessons.py:388` | **theory-only** grammar-уроки (без секции `exercises`) платят 9 XP вместо 18: вычищенный ради антифрода `score` доезжает до скейлера как `0.0` | CONFIRMED | код |
| DP-035 | P1 | `app/daily_plan/linear/xp.py:505` | perfect-day (25 XP) без пассивного «подметальщика»: 30 из 72 закрытых дней прода без `xp_perfect_day` | CONFIRMED | код |

## Расхождения с `CLAUDE.md`

Правило зоны: находка против инварианта — баг **либо в коде, либо в `CLAUDE.md`**. Из 127
подтверждённых находок колонка «Где расхождение» заполнена у **95** (у остальных 32 стоит `—`:
инвариант не задет); из них у **88** ошибка в **коде** (документ описывает намерение верно,
реализация ему не следует) и у **7** — в **тексте `CLAUDE.md`**. Ниже — только семёрка со стороной «`CLAUDE.md`», плюс три расхождения
из liveness-среза и одно документарное, найденное ещё на Task 1.

**Аудит документ не правит.** Формулировки ниже — предложение для ремедиации, не внесённая правка.

| # | Находка | Утверждение `CLAUDE.md` | Факт в коде | Предлагаемая формулировка |
|---|---|---|---|---|
| CM-1 | `DP-023` (`DP-C-016`) | «`tomorrow_preview` при `day_secured=True`» (раздел Daily Plan → Intelligence) | ключ принадлежит вымершему `mode='linear'`-сборщику (`app/daily_plan/linear/plan.py:384`); unified-путь его не эмитит — во всех 5 источниках payload ключа нет, включая закрытый день | убрать `tomorrow_preview` из описания контракта либо пометить: «ключ остался от legacy-сборщика `linear/plan.py`, unified-планом не эмитится; консьюмер — шаблон-сирота» |
| CM-2 | `DP-024` (`DP-C-018`) | порядок кандидатов `get_next_best_step`: «lesson > SRS > grammar weak > reading > vocab» | шагов **7**, а не 5: первым идёт `recovery`, между srs и grammar вклинивается `writing`. Относительный порядок пяти названных не нарушен | «до 3 `NextStep` из 7 кандидатов: recovery > lesson > srs > writing > grammar weak > reading > vocab» |
| CM-3 | `DP-060` (`DP-C-062`) | описание `build_optional` и `_SCORE_BASED_LESSON_TYPES` | 3 из 4 заявленных расхождений подтверждены: не упомянут этап `phrase_review`; `_OPTIONAL_PRIORITY` называет несуществующие `listening/speaking/writing` и не называет реальный `word_set_quiz`; типов в `_SCORE_BASED_LESSON_TYPES` 15, а не 10. Пункт про проходной балл — опровергнут, значения совпадают | синхронизировать перечни с кодом; проходной балл не трогать |
| CM-4 | `DP-063` (`DP-C-072`) | «`get_adaptive_limit_reason() → {'normal','backlog_reduction','accuracy_low'}`» | код возвращает `{'normal','low','critical','collapse'}`; строк `backlog_reduction`/`accuracy_low` в репозитории нет вовсе. Разработчик, написавший по документу `if reason === 'accuracy_low'`, получит мёртвое условие | заменить перечисление на фактическое `{'normal','low','critical','collapse'}` |
| CM-5 | `DP-070` (`DP-C-096`) | блок «LINEAR_XP keys» | блок неполон: не описаны `linear_curriculum_dictation=20`, `linear_curriculum_audio_fill_blank=18`, `linear_curriculum_use`, `linear_listening`, `linear_writing` (последние два описаны в другом разделе) | дополнить блок пятью ключами либо явно сослаться на словарь-источник в `app/achievements/xp_service.py` |
| CM-6 | `DP-071` (`DP-C-098`) | XP-путь curriculum-уроков описан только через `LINEAR_XP` | в `app/curriculum/xp.py` живёт второй, недокументированный путь `xp_curriculum_lesson` / `CURRICULUM_LESSON_XP=30`, чей единственный вход `complete_lesson` (`app/curriculum/service.py:177`) прод-вызывателей не имеет | пометить `award_curriculum_lesson_xp_idempotent`/`complete_lesson` как осиротевшую ветку, либо удалить её ремедиацией |
| CM-7 | `DP-104` (`DP-C-136`) | документ фиксирует `api_error` и глобальный JSON-конверт 4xx/5xx, но не требует `success` в 200-телах | `/api/error-review/summary` — единственный GET зоны без `success` в успешном теле. Скептик уточнил сторону: это внутренняя несогласованность файла `app/api/daily_plan.py`, а не расхождение с документом | по желанию — зафиксировать в `CLAUDE.md` фактический паттерн «`success: true` в 200-телах API», тогда находка станет чисто кодовой |

Ещё три расхождения дал liveness-срез (Task 6). Здесь важно не спутать две стороны: **находки**
`DP-119`/`DP-123`/`DP-124` идут со стороной **`код`** (мёртвый файл лечится удалением файла), а
строки `CM-8…CM-10` ниже — их документарный двойник: пока код не удалён, неверна именно
формулировка `CLAUDE.md` «удалено» при физически присутствующем модуле. Правки ниже адресованы
**`CLAUDE.md`**:

| # | Утверждение `CLAUDE.md` | Факт | Предлагаемая формулировка |
|---|---|---|---|
| CM-8 | «Mission/linear-chain удалены» | файлы на месте: `assembler.py` (831) + `chain.py` (530) + 5 slot-модулей (987) + 267 строк в `linear/plan.py` = **2 615 строк**. Удалены были **вызыватели** (коммит `d197e94a`), не модули | «Mission/linear-chain **отключены**: прод-вызывателей нет, модули остались в дереве и удерживаются только тестами» |
| CM-9 | «мёртвый mission/phase-код удалён (~1000 строк)» | удалён в других местах; сам сборщик фаз `assembler.py` остался, вместе с потребителями ключа `phases` в `words/routes.py` и `streak_service.py` | дописать: «…кроме `app/daily_plan/assembler.py` и веток-потребителей `phases`» |
| CM-10 | «`linear/` остаётся домом для `errors.py`, `progression.py`, `lesson_context.py`, `grammar_theory.py`, SRS/reading slot helpers, XP source map» | перечисление живого верно и полно, но умалчивает, что остальное содержимое `linear/` мертво — читатель не отличит `chain.py` от живого соседа | дописать: «Всё остальное в `linear/` (`chain.py`, 5 из 7 модулей `slots/`, 65 % `plan.py`) — мёртвое наследие, не расширять» |

И одно документарное расхождение, зафиксированное ещё на Task 1 и не ставшее находкой
(поведенческого эффекта нет, значение константы совпадает):

- **CM-11.** `CLAUDE.md` называет константу квоты пропуска урока `DAILY_SKIP_QUOTA=1`; в коде
  символа `DAILY_SKIP_QUOTA` нет — фактическая константа `DAILY_LESSON_SKIP_QUOTA = 1`
  (`app/daily_plan/skips.py:17`), её и читает `app/api/daily_plan.py:1322`. Сторона — **`CLAUDE.md`**.

**Обратного расхождения не найдено:** ни одного случая «документ говорит удалено, а код жив
и исполняется» нет. Все объявленные удалёнными пути в живом прогоне не исполняются.

---

## Подзона: Ядро сборки плана (Task 2)

### Индекс

| ID | Sev | Файл:строка | Симптом | Вериф. | Расхождение |
|---|---|---|---|---|---|
| DP-001 | P1 | `app/api/daily_plan.py:278` | три базиса суток в одном вызове `process_streak_on_activity`: `user_today` — учебный день (02:00), `real_activity` — календарная полночь, `find_missed_date`/починка — календарная полночь на клиентском `?tz=`; клиентский `?tz=` — вторичный вектор | CONFIRMED | код |
| DP-002 | P2 | `app/daily_plan/snapshot.py:196-212` | окно roll-over считается `[00:00,00:00)` локальных суток вместо `[02:00,02:00)` учебного дня | CONFIRMED | код |
| DP-003 | P2 | `app/words/routes.py:1056` | SSR-дашборд пишет `secured_at` по календарной дате, а не по учебному дню (00:00–02:00 уходит в завтра) | CONFIRMED | код |
| DP-004 | P2 | `app/daily_plan/items/curriculum.py:451-480` | если урок уже пройден сегодня, 2–3 curriculum-слота тиров normal/intensive схлопываются в один | CONFIRMED | код |
| DP-005 | P2 | `app/daily_plan/snapshot.py:215-243` | урок, удалённый в админке в течение дня, остаётся в замороженном required → 404 и незакрываемый день | CONFIRMED | код |
| DP-006 | P2 | `app/admin/routes/user_routes.py:315-334` | админ-форма — третий писатель `plan_paused_until`: без `plan_pause`-события, без ограничения длины, дни не streak-нейтральны | CONFIRMED | код |
| DP-007 | P2 | `app/daily_plan/service.py:183-190` | на паузе дашборд рендерит пустой план без объяснения и без кнопки «возобновить» | CONFIRMED | код |
| DP-008 | P2 | `app/words/routes.py:1108-1109` | «XP сегодня» на дашборде считается по календарному дню вопреки контракту `get_today_xp` | CONFIRMED | код |
| DP-009 | P2 | `app/daily_plan/snapshot.py:421-430` | берётся учебная дата (02:00), а окно строится от локальной полуночи | CONFIRMED | код |
| DP-010 | P2 | `app/api/daily_plan.py:196-216` | `add_study_minutes(when=...)` получает учебный день, а сравнивается с иными базисами | CONFIRMED | код |
| DP-011 | P2 | `app/utils/time_utils.py:74-86` | идемпотентные ключи `(user, дата, source)` пересчитываются из текущего `User.timezone`: смена зоны переигрывает прошлое | CONFIRMED | код |
| DP-012 | P2 | `app/words/routes.py:715-721` | дашбордная карточка гонки считает дату кохорты иначе, чем `/api/daily-race` | CONFIRMED | код |
| DP-013 | P2 | `app/api/daily_plan.py:368` | контракт докстринга «`tz` must match the timezone used to derive `target_date`» нарушен на call-site | CONFIRMED | код |
| DP-014 | P2 | `app/daily_plan/service.py:118-137` | проигравший гонку `write_secured_at` роняет `PendingRollbackError` и уносит всю flush-only работу запроса | CONFIRMED | код |
| DP-015 | P2 | `app/api/daily_plan.py:1352-1372` | квота скипов — `SELECT count(*)` + сравнение в питоне без уникального индекса: обходится параллельным запросом | CONFIRMED | код |
| DP-016 | P2 | `app/api/daily_plan.py:344-350` | идемпотентность milestone-уведомления держится на совпадении строки `link` | CONFIRMED | код |
| DP-017 | P2 | `app/daily_plan/items/curriculum.py:661-703` | заблокированный спайн заставляет постранично пролистать остаток каталога: 229 SQL / 390 мс на очередь из 6 пунктов | CONFIRMED | — |
| DP-018 | P2 | `app/daily_plan/linear/progression.py:105-139` | выборка кандидатов — все колонки (включая `content JSON`), без `LIMIT`, с резолвом модуля по одному | CONFIRMED | — |
| DP-019 | P2 | `app/daily_plan/items/curriculum.py:539-598` | один `_module_accessible_for_user` стоит до 5 запросов и зовётся на модуль | CONFIRMED | код |
| DP-020 | P2 | `app/telegram/queries.py:59-104` | `get_current_streak` идёт по дням до 366 итераций × до 8 запросов | CONFIRMED | — |
| DP-021 | P2 | `app/modules/service.py:21-23` | проверка модуля = 2 запроса без мемоизации, зовётся из декоратора и context-процессора | CONFIRMED | — |
| DP-022 | P3 | `app/api/daily_plan.py:117` | две несогласованные реализации «вчера не закрыто» (pytz-ветка в API vs ZoneInfo в `next_step.py`) | CONFIRMED | код |
| DP-023 | P3 | `app/daily_plan/linear/plan.py:384` | `tomorrow_preview` (INV-41) не эмитит ни один живой сборщик; единственный консьюмер — шаблон-сирота | CONFIRMED | CLAUDE.md |
| DP-024 | P3 | `app/daily_plan/next_step.py:43-51` | фактический порядок кандидатов не совпадает с задокументированным (INV-44) | CONFIRMED | CLAUDE.md |
| DP-025 | P3 | `app/words/routes.py:1814` | `repair-web` — единственный роут зоны без `api_error` | CONFIRMED | код |
| DP-026 | P3 | `app/api/daily_plan.py:139-152` | `goal_progress.daily_words` считается от 02:00, `weekly_lessons` — от иной границы | CONFIRMED | код |
| DP-027 | P3 | `app/daily_plan/snapshot.py:4-5` | докстринги модуля описывают границу «полночь», реализация даёт учебный день | CONFIRMED | код |
| DP-028 | P3 | `app/daily_plan/items/curriculum.py:676-677` | голые строки уроков → SELECT на каждый невиденный `module`/`level` | CONFIRMED | — |
| DP-029 | P3 | `app/daily_plan/level_utils.py:11-21` | `_user_min_level_order` без мемоизации: `_cefr_code_to_order` бьёт в БД на каждый вызов | CONFIRMED | — |
| DP-030 | P3 | `app/daily_plan/items/srs.py:171-187` | `count_reviews_today` исполняется трижды за одну сборку SRS-item'а | CONFIRMED | — |
| DP-031 | P3 | `app/daily_plan/next_step.py:371-402` | `started_book_ids` без `LIMIT` + запрос `Book` на каждый id | CONFIRMED | — |
| DP-032 | P3 | `app/daily_plan/plan.py:511-549` | `_compute_module_progress` делает два раздельных COUNT там, где хватает одного | CONFIRMED | — |

### P0 — детали

_(находок этого уровня в подзоне нет)_


### P1 — детали

#### DP-001 · P1 · `app/api/daily_plan.py:278`

- **Кандидат:** `DP-C-024` · линзы-источники: CORE-C-08 · скептик: `skeptics/DP-C-024.md`
- **Симптом:** три базиса суток в одном вызове `process_streak_on_activity`: `user_today` — учебный день (02:00), `real_activity` — календарная полночь, `find_missed_date`/починка — календарная полночь на клиентском `?tz=`; клиентский `?tz=` — вторичный, более редкий вектор того же расхождения
- **Сценарий отказа:** _(формулировка переписана по итогу второго прохода — см. ниже; исходная версия вела с клиентского `?tz=`, что объясняет лишь часть наблюдаемого эффекта)_ **Основной механизм — разные границы суток внутри одного вызова `process_streak_on_activity`.** Базисов там **три**, а не два. `user_today` идёт через `get_user_local_date` → `_study_day_date`, где день начинается в `LEARNING_DAY_START_HOUR=02:00` (`app/utils/time_utils.py:74-93`), на `User.timezone`. `real_activity = has_activity_today(user_id, tz=_user_tz)` берёт **ту же зону, но календарную полночь** — `_user_day_boundaries` строит окно от `time.min`, `LEARNING_DAY_START_HOUR` в `app/telegram/queries.py` не импортируется (`app/telegram/queries.py:22-37,40-44`). `find_missed_date` — та же календарная полночь, но уже на **клиентском** `tz`. Ремедиация, написанная по формуле «`real_activity` считается на учебном дне», перекеит только `find_missed_date` и оставит гейт 00:00–02:00 рассогласованным с ключом дедупа `user_today`, который он же и охраняет (`app/achievements/streak_service.py:328` пишет монету за D-1 по календарной активности дня D). Клиентский `tz` для этого не нужен: `app/api/daily_plan.py:278` по умолчанию подставляет `current_user.timezone`, то есть расхождение срабатывает у **каждого** пользователя на дефолтном пути. Сценарий: занятие между 00:00 и 02:00 локально принадлежит предыдущему учебному дню по `user_today`, но следующему календарному по `find_missed_date` — «пропущенным» объявляется день, который юзер отучился, `apply_shield_repair` пишет `StreakEvent(event_date=<неверная дата>)` и сжигает щит впустую. Это и даёт замеренный эффект: 6 из 11 щитов у всех 3 юзеров, когда-либо их тративших. **Вторичный вектор (тот же дефект, другой вход):** `/api/daily-status?tz=<произвольная_зона>` — `_validate_timezone` проверяет только существование IANA-зоны и не сверяет её с `current_user.timezone`, поэтому клиент может дополнительно развести базисы по смещению. Ни один поставляемый клиент расходящийся `tz` не шлёт, так что одним этим вектором наблюдаемые цифры не объясняются. Ремедиации нужно чинить границу дня, а не только прокидывать `_user_tz`. Исходная (частичная) формулировка: `/api/daily-status?tz=<любая_валидная_зона>` даёт `process_streak_on_activity` два разных tz-базиса одновременно — гейт «есть ли реальная активность сегодня» считается по `User.timezone`, а «какой день чинить» (`find_missed_date`) и запись починки (`apply_shield_repair`/`apply_free_repair`, `event_date=missed_date`) — по клиентскому `tz`. Сценарий: `User.timezone='Europe/Istanbul'`, юзер реально пропустил вчерашний (Istanbul-локальный) день, сегодня позанимался — `real_activity=True` по Стамбулу, `streak_shield_active=True`. Клиент шлёт `?tz=Pacific/Kiritimati` (UTC+14, ~11ч впереди Стамбула) или любую другую сильно смещённую зону. `find_missed_date` идёт по границам суток Kiritimati, которые не совпадают со стамбульскими сутками, и может (а) не найти реальный пропущенный стамбульский день (окно активности «размазано» по другим kiritimati-суткам) — щит не списывается на верную дату, либо (б) найти и «починить» день, который по Стамбулу пропущенным не был — `apply_shield_repair` пишет `StreakEvent(event_date=<неверная дата>)`, тратит щит впустую, а реальный пропуск остаётся неотремонтированным. Эффект тихий (никакой ошибки пользователю), затрагивает щит/бесплатную починку и восстановленный `streak` без обхода — соответствует P1.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:278` — `tz = _validate_timezone(request.args.get('tz', current_user.timezone or DEFAULT_TZ))`: клиент может передать произвольный `?tz=` в `/api/daily-status`, `_validate_timezone` только проверяет, что это существующая IANA-зона, не сверяет с `current_user.timezone`.
  - `app/api/daily_plan.py:287-290` — этот `tz` пробрасывается в `process_streak_on_activity(user_id, steps_done, steps_total, tz=tz, ...)`.
  - `app/achievements/streak_service.py:310-316` — внутри `process_streak_on_activity` явно (с комментарием "audit E-003") зашит отдельный `_user_tz = current_user.timezone`, которым считается ТОЛЬКО `real_activity = has_activity_today(user_id, tz=_user_tz)`; `user_today = get_user_local_date(...)` (строка 302) читает `User.timezone` самостоятельно. **Зона у них общая, база суток — нет:** сам комментарий на :310-313 утверждает «Activity window is keyed on User.timezone (same basis as user_today)», и это утверждение ложно — `has_activity_today` → `_user_day_boundaries` режет по 00:00, `get_user_local_date` → `_study_day_date` по 02:00.
  - `app/achievements/streak_service.py:354,376,382-385,395,398-399,408` — `get_streak_status`, `find_missed_date`, `apply_shield_repair`'s дата-аргумент, `apply_free_repair`'s дата-аргумент и `auto_heal_streak_on_activity` продолжают получать исходный `tz` (клиентский параметр), НЕ `_user_tz`.
  - `app/achievements/streak_service.py:856-889` (`find_missed_date`) — ходит по `_user_day_boundaries(tz, offset_days=-offset)` и `datetime.now(pytz.timezone(tz))`, то есть границы «дней» и текущая локальная дата целиком определяются входным `tz`, отличным от того, что использовал гейт `real_activity`.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-024.md`; здесь список усечён по бюджету, а не по значимости)_
- **Второй проход (три независимые линзы):** correctness=PARTIAL · reproducibility=REPRODUCIBLE · user-impact=P1 → **P1**. P1 подтверждён. Формулировку править: расхождение живёт в `process_streak_on_activity` (`find_missed_date` на календарной полуночи против `user_today` на учебном дне), собственного tz-базиса у `apply_shield_repair` нет. Щит сжигается на днях, которые юзер отучился: 6 из 11 щитов у всех 3 юзеров, когда-либо их тративших.
- **Где расхождение:** код — комментарий на `streak_service.py:310-313` фиксирует инвариант E-003 («activity-window keyed on User.timezone, NOT client tz») только для `real_activity`, но не распространяет его на `find_missed_date`/`apply_shield_repair`/`get_streak_status`/`auto_heal_streak_on_activity`, вызываемые в той же функции с тем же клиентским `tz` Тот же комментарий содержит и **вторую, самостоятельную ошибку**: скобка «same basis as user_today» описывает несуществующее равенство баз суток. Отдельной находки под неё не заводится — это тот же корень (путаница базисов в одной функции), и ремедиация DP-001 обязана переписать комментарий вместе с кодом.


### P2 — детали

#### DP-002 · P2 · `app/daily_plan/snapshot.py:196-212`

- **Кандидат:** `DP-C-002` · линзы-источники: CORE-A-02, CORE-C-02, CORE-D-05 · скептик: `skeptics/DP-C-002.md`
- **Симптом:** окно roll-over считается `[00:00,00:00)` локальных суток вместо `[02:00,02:00)` учебного дня
- **Сценарий отказа:** механизм найден и воспроизводим по коду; перекрывающей проверки нет. Сценарий (Europe/Istanbul, ленивая сборка — сегодняшней строки нет, например ночной джоб `_generate_daily_plans_hourly` для юзера не отработал: `User.active` снят, `plan_paused_until` попал в `skipped`, или ветка `except → errors += 1` откатила транзакцию): вход — учебный день `D = 2026-08-25`, снапшот за `D` записан и содержит `curriculum:lesson:888`; пользователь занимается один раз, в `2026-08-26 00:30` локально (по `get_user_local_date` это ещё день `D`) и проходит этот урок; `LessonProgress.last_activity = 2026-08-25 21:30` naive-UTC. Утром `2026-08-26 10:00` (учебный день `D+1`) грузится дашборд: `_try_rollover_from_yesterday` берёт окно `[2026-08-24 21:00, 2026-08-25 21:00)`, активность в `21:30` за него вываливается, `has_learning_activity → False`. Неверный выход — снапшот `D+1` объявляется `rolled_over_from: D` и дословно копирует `curriculum:lesson:888`; при этом `_curriculum_lesson_done_today` (02:00-базис) на дне `D+1` урок завершённым не считает. Пользователь получает в «обязательное» уже сданный вчера урок, а реальный следующий урок спайна в required не попадает вовсе. Симметрично в штатном пути джоба (`app/telegram/scheduler.py:397`, запуск в 00:05 локально): занятие в `D-1 01:00` локально принадлежит учебному дню `D-2`, но попадает в окно `[D-1 00:00, D 00:00)` и ошибочно читается как «вчера занимался» — roll-over подавляется, хотя весь учебный день `D-1` был пустым. Severity P2, а не P1: данные не портятся, XP/streak/`day_secured` считаются по своему (корректному) 02:00-базису, обход есть — урок можно пересдать, а следующий доступен через очередь «Дальше по курсу»; ломается состав required на части ночей у ночных учащихся.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/utils/time_utils.py:29` — `LEARNING_DAY_START_HOUR = 2`; комментарий выше: «deliberately a single global cutoff (rather than a per-screen workaround) so all daily features agree about what "today" means».
  - `app/utils/time_utils.py:144` — канонический хелпер границ дня `day_to_naive_utc` строит начало суток как `time(hour=LEARNING_DAY_START_HOUR)`; `get_user_local_day_bounds` (:104-113) — поверх него.
  - `app/utils/time_utils.py:86-92` — `_study_day_date`: при `now_local.hour < 2` возвращается предыдущая дата; `get_user_local_date` (:72-84) отдаёт именно эту, 02:00-якорную дату.
  - `app/daily_plan/plan.py:402-404` — `today_local = get_user_local_date(user_id, session)` и `resolve_snapshot_for_today(user_id, today_local, session)`: в снапшот приходит **учебная** дата.
  - `app/daily_plan/snapshot.py:99-101` — `yesterday = today_local - timedelta(days=1)`, то есть тоже учебная дата.
  - `app/daily_plan/snapshot.py:196-211` — `_local_date_start_naive_utc(...)`: `local_midnight = datetime.combine(local_date, time.min, tzinfo=tz)`. Это **00:00**, а не `LEARNING_DAY_START_HOUR`. `LEARNING_DAY_START_HOUR` в файле не импортируется вовсе (`grep` по модулю — 0 совпадений).
  - `app/daily_plan/snapshot.py:177-181` — `y_start = _local_date_start_naive_utc(user_id, yesterday, db)`, `y_end = y_start + timedelta(days=1)`, `if has_learning_activity(user_id, y_start, y_end, db.session)`.
  - _(ещё 5 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-002.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — `CLAUDE.md` объявляет единый пользовательский день (`get_user_local_date` / `day_to_naive_utc`) единственным источником «сегодня», а `_local_date_start_naive_utc` заводит второй, 00:00-базис.

#### DP-003 · P2 · `app/words/routes.py:1056`

- **Кандидат:** `DP-C-003` · линзы-источники: CORE-A-03, CORE-B-01, CORE-C-01, CORE-D-03 · скептик: `skeptics/DP-C-003.md`
- **Симптом:** SSR-дашборд пишет `secured_at` по календарной дате, а не по учебному дню (00:00–02:00 уходит в завтра)
- **Сценарий отказа:** механизм в коде есть и ничем не перекрыт. Сценарий (юзер `Europe/Istanbul`, учебный день D−1 = 26.08): 1. 26.08 в 23:40 юзер добивает последний обязательный пункт, дашборд не открывает (или открывает — не важно, см. п.3). 2. 27.08 в 00:30 (учебный день всё ещё 26.08) он открывает `/dashboard`: `compute_day_secured_from_activity` → True по активности учебного дня 26.08, но `app/words/routes.py:1056` зовёт `write_secured_at(uid, date(2026,8,27))`. 3. Неверный выход: строка `DailyPlanLog(plan_date=2026-08-26)` (та, где лежит снапшот закрытого дня) остаётся `secured_at IS NULL`, а создаётся/помечается строка `plan_date=2026-08-27` с `secured_at`, хотя в учебном дне 27.08 активности ещё ноль. - `_check_recovery` (`app/daily_plan/next_step.py:84`) в учебном дне 27.08 видит `yesterday=26.08` с `secured_at IS NULL` → выдаёт «Вчера не завершил(а) — продолжи с SRS» юзеру, который вчера всё закрыл. - `/study/calendar` рисует 26.08 как level 1 (не закрыт) и 27.08 как level 2 (закрыт) ещё до первого задания; `days_secured` в инсайтах и `day_secured`-ступень админской воронки считаются по тем же строкам. - На 27.08 повторный `write_secured_at` увидит `secured_at is not None` (`app/daily_plan/service.py:135`) и не перезапишет — день 27.08 останется «закрытым» независимо от того, занимался юзер или нет. Severity P2, а не P1: XP, streak и ранги идут другими путями с корректным базисом (`award_*`/`process_streak_on_activity`/`record_plan_completion` через `get_user_local_date`), сам план дня и его закрытие в UI не ломаются; страдает персистентный журнал закрытий и всё, что из него читается (recovery-подсказка, календарь, аналитика, воронка). Окно срабатывания — только рендеры дашборда в 00:00–02:00 локального времени юзера (по MEMORY владелец занимается ночью, т.е. окно реальное).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/words/routes.py:1056` — `write_secured_at(current_user.id, _dt_sec.now(_tz_sec).date())`; `_tz_sec` — таймзона юзера (`app/words/routes.py:1238` `tz = current_user.timezone or DEFAULT_TIMEZONE`), но дата берётся календарная, без учёта `LEARNING_DAY_START_HOUR`.
  - `app/utils/time_utils.py:88-92` — `_study_day_date`: `if now_local.hour < LEARNING_DAY_START_HOUR: return (now_local - timedelta(days=1)).date()`; `LEARNING_DAY_START_HOUR = 2` (`app/utils/time_utils.py:31`). Значит с 00:00 до 02:00 `get_user_local_date` отдаёт D−1, а `datetime.now(tz).date()` — D.
  - `app/daily_plan/plan.py:403-404` — строка `DailyPlanLog` для снапшота создаётся под `today_local = get_user_local_date(user_id, session)` → `resolve_snapshot_for_today(...)` → `_get_or_create_log_row` (`app/daily_plan/snapshot.py:31-53`). Т.е. «строка учебного дня» — это D−1, а `secured_at` в 00:00–02:00 уходит в другую строку (D), которую `write_secured_at` при её отсутствии сама и создаёт (`app/daily_plan/service.py:118-137`).
  - _(ещё 4 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-003.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md фиксирует `get_user_local_date` как «единственный источник today» и `write_secured_at(user_id, plan_date)` как запись по дню плана; `app/words/routes.py:1056` этот базис нарушает.

#### DP-004 · P2 · `app/daily_plan/items/curriculum.py:451-480`

- **Кандидат:** `DP-C-004` · линзы-источники: CORE-A-04 · скептик: `skeptics/DP-C-004.md`
- **Симптом:** если урок уже пройден сегодня, 2–3 curriculum-слота тиров normal/intensive схлопываются в один
- **Сценарий отказа:** попытка опровержения не удалась. Сценарий: юзер тира `intensive` (спайн: L101, L102, L103), снапшота на сегодня ещё нет; он открывает L101 по прямой ссылке и завершает его. `maybe_award_curriculum_xp` пишет StreakEvent, `maybe_award_linear_perfect_day` собирает план → `build_required_snapshot` строит `[curriculum:lesson:101(done_today), srs:global, reading, curriculum:lesson:101, curriculum:lesson:101]` (проверено прогоном) и коммитит его на весь день. Ожидалось: 3 разных урока в required. Фактически: одна уникальная курсовая позиция, уже выполненная, — дневная норма курса уменьшена с 3 уроков до 1, и день закрывается (`day_secured`) без единого нового урока. Для `normal` — 2 → 1. Замечание в сторону (отдельный механизм, не входит в формулировку кандидата, но усугубляет): `app/telegram/scheduler.py:386-397` собирает снапшот в локальный час 00, передавая `today_local = local_dt.date()`, тогда как `_curriculum_done_today` работает по учебному дню (`LEARNING_DAY_START_HOUR=2`, `app/utils/time_utils.py:29,86-90`) и в 00:05 всё ещё указывает на **вчерашний** учебный день. Тогда в снапшот завтрашнего дня попадает вчерашний урок с `url=None`, а `overlay_completion` (`snapshot.py:328-390`) не считает его выполненным сегодня — required-курс становится некликабельным и незакрываемым. Это стоит завести отдельным кандидатом.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/items/curriculum.py:449-457` — в ветке `if done_today and section == 'required'` строится `completed_lesson = _get_lesson_completed_today(user_id, db) or next_lesson`: **переданный аргумент `next_lesson` игнорируется**, пока `_get_lesson_completed_today` вернул хоть что-то. Возвращаемый PlanItem — `id=f'curriculum:lesson:{completed_lesson.id}'`, `eta_minutes=0`, `url=None`, `data['state']='done_today'`.
  - `app/daily_plan/plan_builder.py:56-60` — `_TIER_CURRICULUM_COUNT = {'calm':1,'normal':2,'intensive':3}`; `plan_builder.py:94` и `:131-136` — `_curriculum_item_dict(...)` вызывается по одному разу на каждый урок цепочки, и всегда с `section='required'` (`plan_builder.py:189-191`). Значит на normal/intensive все 2–3 вызова возвращают один и тот же dict.
  - `app/daily_plan/items/curriculum.py:110-145` — `_curriculum_done_today` истинно уже по первому сегодняшнему `StreakEvent(xp_linear, source ∈ curriculum)` (fallback — `LessonProgress`), т.е. сразу после первого пройденного урока дня.
  - `app/daily_plan/snapshot.py:107-110` — свежий снапшот пишется в `log.plan_json` и **фиксируется на весь день** (`resolve_snapshot_for_today` при существующем валидном `plan_json` возвращает его без пересборки, `snapshot.py:96-98`).
  - _(ещё 4 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-004.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md описывает якорение required-курса на первом пройденном сегодня уроке как свойство ОДНОГО слота; при tier-плане с 2–3 курсовыми слотами это якорение применяется к каждому слоту и обнуляет норму.

#### DP-005 · P2 · `app/daily_plan/snapshot.py:215-243`

- **Кандидат:** `DP-C-006` · линзы-источники: CORE-A-06 · скептик: `skeptics/DP-C-006.md`
- **Симптом:** урок, удалённый в админке в течение дня, остаётся в замороженном required → 404 и незакрываемый день
- **Сценарий отказа:** сценарий вход→выход: (1) у пользователя уже есть валидный снапшот на сегодня с required curriculum-item на `lesson_id=42`; (2) админ удаляет урок 42 (или каскадом — весь модуль) через `/admin/curriculum/lessons/42/delete`; (3) `resolve_snapshot_for_today` на следующий запрос дня возвращает старый снапшот без проверки (строка 96-98); (4) клик по item → `/curriculum/lesson/42/...` → `404` (get_or_404); (5) `_curriculum_lesson_done_today` не находит ни `StreakEvent`, ни `LessonProgress` (INNER JOIN с несуществующим `Lessons.id=42`) → `completed=False` навсегда; (6) `skip_lesson` для `lesson_id=42` тоже отбивается `400 invalid_lesson` — штатного обхода нет; (7) `compute_day_secured_from_activity` требует ВСЕ required-элементы завершёнными → `day_secured` остаётся `False` весь оставшийся день независимо от любой другой активности пользователя. На следующий локальный день строится свежий снапшот (`build_required_snapshot` не сошлётся на удалённый урок), так что баг ограничен ОДНИМ учебным днём для пользователей, у кого снапшот уже был заморожен на момент удаления — но именно за этот день streak/rank/perfect-day невосстановимы. Severity: **P1** — ключевой сценарий (закрытие дня) полностью и необратимо (для этого дня) ломается у части пользователей (у кого снапшот содержит удалённый урок), без штатного обхода (skip тоже 404/400-ится на несуществующий lesson_id); совпадает с явным примером P1 из брифинга («день не закрывается, обязательный пункт недостижим, нет обхода»).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/snapshot.py:57-67` — `_valid_snapshot` проверяет только структуру (`version`, `items` — список dict с `id`/`kind`), про существование `lesson_id` в БД речи нет.
  - `app/daily_plan/snapshot.py:96-98` — если у сегодняшней строки уже есть валидный снапшот, `resolve_snapshot_for_today` возвращает его **без какой-либо ревалидации** ссылок на уроки: `existing = _valid_snapshot(log.plan_json); if existing is not None: return existing`.
  - `app/daily_plan/snapshot.py:275-283,328-390` — `_is_item_completed` для `kind == 'curriculum'` зовёт `_curriculum_lesson_done_today(user_id, lesson_id_int, db)`, которая ищет `StreakEvent` по `lesson_id` (ещё не сработал, т.к. урок не пройден) и `LessonProgress JOIN Lessons ON Lessons.id == LessonProgress.lesson_id` — при удалённом уроке `Lessons`-строки нет, INNER JOIN не матчит ничего, `row is None` → `return False`. В отличие от `_is_finished_reading_book` (строки 305-325, есть `try/except`), здесь никакой защиты/специальной обработки отсутствия урока нет — просто перманентный `False`.
  - `app/curriculum/routes/lessons.py:183,472,545,848,...` — каждый lesson-роут открывается `Lessons.query.get_or_404(lesson_id)`. Удалённый `lesson_id` → `404`, ссылка в замороженном item (`/curriculum/lesson/<id>...`, см. `app/daily_plan/plan_builder.py` module docstring, строки 1-30) ведёт в тупик.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-006.md`; здесь список усечён по бюджету, а не по значимости)_
- **Второй проход (три независимые линзы):** correctness=SOUND · reproducibility=REPRODUCIBLE · user-impact=P2 → P1 → P2. P1→P2: механизм и путь через живые поверхности подтверждены, но триггер — админское удаление урока; в проде 0 случаев (0 висячих lesson_id в 1873 снапшотах, 0 delete-записей в аудит-логе), streak и XP уцелевают, назавтра чинится само.
- **Где расхождение:** код — `CLAUDE.md` описывает `day_secured` как «всегда False на assembly time; API пересчитывает из активности через `compute_plan_steps` + `compute_day_secured_from_activity`», но не документирует отсутствие ревалидации существования урока во frozen-снапшоте; это пробел и в документации, и в коде (`resolve_snapshot_for_today` / `_curriculum_lesson_done_today` не участвуют в перечисленных в CLAUDE.md механизмах восстановления вроде «заблокированный спайн»).

#### DP-006 · P2 · `app/admin/routes/user_routes.py:315-334`

- **Кандидат:** `DP-C-007` · линзы-источники: CORE-A-07, CORE-B-06 · скептик: `skeptics/DP-C-007.md`
- **Симптом:** админ-форма — третий писатель `plan_paused_until`: без `plan_pause`-события, без ограничения длины, дни не streak-нейтральны
- **Сценарий отказа:** механизм именно такой, как описан. Сценарий: админ открывает `/admin/users/<id>` → `user_detail.html:220-221` (поле `plan_paused_until` в форме settings) → ставит дату паузы на 30 дней вперёд (никакого ограничения в 1–14 дней, в отличие от API) → `update_user_settings` пишет `user.plan_paused_until` без единого `StreakEvent(event_type='plan_pause')`. Пока дата не наступила, `is_plan_paused`/paused-payload в `app/daily_plan/service.py:173` корректно показывают юзеру паузу (эта часть читает только колонку). Но streak-калькулятор (`get_streak_calendar`) эти дни не увидит как нейтральные — они посчитаются гэпом, streak у пользователя молча обнулится/прервётся, хотя формально план был на паузе. **Severity:** предлагаю **P2**, не P1 из брифинга кандидата: эффект реальный и «тихий» (streak считается неверно), но триггер — не органический пользовательский путь, а исключительно ручное действие администратора через закрытую /admin-панель; обычные пользователи с self-service паузой (через `/plan/pause`) не затронуты. Обход существует: администратор может вручную создать соответствующие `StreakEvent(event_type='plan_pause')` или использовать API-эндпоинт вместо формы.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/admin/routes/user_routes.py:316-320` — `pause_raw = (request.form.get('plan_paused_until') or '').strip(); paused_until = None; if pause_raw: paused_until = date.fromisoformat(pause_raw)` — принимается любая ISO-дата без верхней границы (в отличие от API, где `1 <= days <= 14`, см. `app/api/daily_plan.py:1112-1113`).
  - `app/admin/routes/user_routes.py:334` — `user.plan_paused_until = paused_until` — прямая запись колонки, никакого `StreakEvent` рядом не создаётся (весь handler между строками 295 и 342 не импортирует и не трогает `StreakEvent`).
  - `app/api/daily_plan.py:1124-1141` — канонический `/plan/pause` явно удаляет старые `plan_pause`-события и **вставляет по одному `StreakEvent(event_type='plan_pause', event_date=pause_date)` на каждый день паузы**, и только потом пишет `user.plan_paused_until = paused_until` — то есть колонка и события в этом пути синхронизированы намеренно.
  - `app/achievements/streak_service.py:585-590` — расчёт `active_dates`/streak берёт `event_dates` из `StreakEvent.event_type.in_(['earned_daily', 'free_repair', 'spent_repair', 'plan_pause', 'shield_repair'])`; без записи `plan_pause`-события день паузы не попадает в `active_dates` и учитывается как обычный пропуск.
  - `grep` подтверждает отсутствие иной синхронизации: `plan_paused_until\s*=` встречается только в модели и в трёх местах записи (admin-форма, `/plan/pause`, `/plan/resume`).
- **Где расхождение:** код — CLAUDE.md прямо называет `/api/plan/pause` и `/api/plan/resume` единственными точками записи и синхронизации streak-нейтральности («paused-дни streak-нейтральны»), но код admin-роута нарушает этот инвариант, будучи третьим необъявленным писателем той же колонки.

#### DP-007 · P2 · `app/daily_plan/service.py:183-190`

- **Кандидат:** `DP-C-008` · линзы-источники: CORE-A-08 · скептик: `skeptics/DP-C-008.md`
- **Симптом:** на паузе дашборд рендерит пустой план без объяснения и без кнопки «возобновить»
- **Сценарий отказа:** механизм в коде есть и воспроизводим по коду без внешних данных: любой пользователь с `plan_paused_until > today` (сейчас это выставляется только вручную админом через `/admin/users/<id>/settings`, self-service пути `POST /api/plan/pause` в UI не подключён) при обычном заходе на `/dashboard` получает hero с «Откройте каталог, чтобы начать обучение» и блок плана с текстом «Завершите настройку ниже, чтобы получить план дня» — ни один из них не упоминает паузу, а второй ссылается на пустой (тоже 0 пунктов) setup-блок. Кнопки «возобновить» на дашборде нет ни в одном шаблоне; CSS для баннера паузы существует, но не подключён нигде (dead code). Обход есть (прямой переход на `/study`, `/words` и т.д. работает вне `?from=linear_plan`), поэтому это не полная неработоспособность, а вводящее в заблуждение пустое/неверное сообщение на ключевом экране — предлагаю **P2** (а не выданный в кандидате уровень не указан явно, но по своим ощущениям это не P1: self-service pause ещё не подключён к UI, значит охват сегодня — только вручную приостановленные админом аккаунты; тем не менее сам механизм — реальный баг, а не гипотеза).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/service.py:171-190` — при паузе возвращается payload `{'mode': 'paused', 'paused_until': ..., 'day_secured': pre_pause_secured}` — без ключей `required`/`optional`/`setup`.
  - `app/templates/partials/unified_daily_plan.html:5-7` — `u_required = unified_plan.get('required') or []`, `u_optional = ... or []`, `u_setup = ... or []` → все три пустые для paused-payload (ключей нет вовсе).
  - `app/templates/partials/unified_daily_plan.html:10` — `u_blocked_module = unified_plan.get('blocked_module') or {}` → тоже пусто (paused-payload не несёт `blocked_module`).
  - `app/templates/partials/unified_daily_plan.html:482-511` — единственная ветка, достижимая при пустом `u_required`: если `u_blocked_module` пуст (наш случай), рендерится `<p class="daily-plan__empty">Завершите настройку ниже, чтобы получить план дня.</p>` — сообщение не про паузу, а про несуществующий (тоже пустой, `u_setup=[]`) setup-блок ниже.
  - `app/words/routes.py` (`_render_unified_dashboard`, ветка hero) — при `steps_total=0` (что и есть для paused, см. ниже) `subtitle = 'Откройте каталог, чтобы начать обучение'` — тоже без упоминания паузы.
  - _(ещё 4 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-008.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — раздел CLAUDE.md «Daily Plan (Unified)» документирует `plan_paused_until`, `/api/plan/pause|resume`, «paused-дни streak-нейтральны», но не описывает (и не гарантирует) какого-либо UI-уведомления о паузе на `/dashboard` — сам документ тоже не заявляет о существовании такого сообщения, поэтому расхождения документ↔код нет; расхождение — между ожидаемым UX (сообщить о паузе + дать возобновить) и фактическим кодом шаблона.

#### DP-008 · P2 · `app/words/routes.py:1108-1109`

- **Кандидат:** `DP-C-014` · линзы-источники: CORE-B-04, CORE-C-06 · скептик: `skeptics/DP-C-014.md`
- **Симптом:** «XP сегодня» на дашборде считается по календарному дню вопреки контракту `get_today_xp`
- **Сценарий отказа:** оба базиса реально расходятся, механизм воспроизводим по коду. Сценарий: пользователь (сова, учится ночью — см. `CLAUDE.md`/память «Study day starts at 2am») в 01:30 локального времени 27.08 проходит урок → `award_curriculum_lesson_xp_idempotent` пишет `StreakEvent.event_date = get_user_local_date(...) = 26.08` (учебный день, т.к. `hour(1) < 2`). Он тут же открывает дашборд в 01:35 → виджет вычисляет `_today_local = datetime.now(tz).date() = 27.08` (без сдвига) и зовёт `get_today_xp(user, 27.08)`. Запрос ищет `StreakEvent.event_date == 27.08`, реальная запись лежит под `26.08` — 0 совпадений, `xp_today = 0` вместо только что заработанного XP. Расхождение не самокорректируется в течение всего календарного дня 27.08 (виджет весь день считает `_today_local = 27.08`, независимо от часа), то есть именно это XP-событие никогда не попадёт в счётчик «сегодня» ни в один последующий рендер. `total_xp`/уровень/streak не затронуты — страдает только отображаемый счётчик «XP сегодня».
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/achievements/xp_service.py:600-604` — `"for_date defaults to the user's LOCAL today (audit E-014) so callers can't accidentally sum the wrong calendar day"`, дефолт: `if for_date is None: for_date = get_user_local_date(user_id)`.
  - `app/utils/time_utils.py:91-93` — `if now_local.hour < LEARNING_DAY_START_HOUR: return (now_local - timedelta(days=1)).date()` — учебный день до 02:00 = предыдущая календарная дата.
  - `app/words/routes.py:1104-1109`: ``` _today_local = datetime.now(_tz).date() xp_today = get_today_xp(current_user.id, _today_local) or 0 ``` — календарная дата без сдвига на 02:00, передана явным `for_date`, дефолт функции (учебный день) не срабатывает.
  - `app/curriculum/service.py:262-266` — запись XP-события идёт с `get_user_local_date(user_id, db)`, то есть базис записи — учебный день (02:00), а не календарный.
- **Второй проход (три независимые линзы):** correctness=SOUND · reproducibility=REPRODUCIBLE · user-impact=P2 → P1 → P2. P1→P2: расхождение базисов доказано (окно 00:00–01:59, 40 XP-событий у 5 из 12 аккаунтов в проде), но цена чисто отображательная — реальные XP, уровень, streak и day_secured не страдают.
- **Где расхождение:** код — виджет обходит собственный контракт функции `get_today_xp` (докстринг explicitly привязывает дефолт к `get_user_local_date`/audit E-014), в то время как запись XP (`award_curriculum_lesson_xp_idempotent`, `maybe_award_curriculum_xp` через `get_linear_event_local_date`) последовательно использует учебный день.

#### DP-009 · P2 · `app/daily_plan/snapshot.py:421-430`

- **Кандидат:** `DP-C-021` · линзы-источники: CORE-C-03 · скептик: `skeptics/DP-C-021.md`
- **Симптом:** берётся учебная дата (02:00), а окно строится от локальной полуночи
- **Сценарий отказа:** механизм есть и живой, опровергнуть не удалось. Сценарий (вход → неверный выход): у пользователя в required-снапшоте стоит pre-FT пункт `grammar_review:module:N:topic:T:pre_ft`. В 01:00 по локальному времени 6 августа (учебный день — 5 августа) он проходит курсовой grammar-урок этого модуля; `LessonAttempt.completed_at` = 2026-08-05 22:00 naive UTC. `_grammar_topic_practiced_today` для учебного дня 5 августа строит окно 2026-08-04 21:00 … 2026-08-05 21:00 и **не видит** попытку → `_is_item_completed` = False → `item['completed']` = False → в `compute_day_secured_from_activity` (`app/daily_plan/service.py:73-76`) required-пункт остаётся незакрытым → `day_secured` = False при выполненной работе. Зеркальный эффект: та же попытка попадает в окно **следующего** учебного дня (6 августа: 2026-08-05 21:00 … 2026-08-06 21:00 — да, 22:00 внутри), то есть закрывает пункт дня, в который пользователь ничего не делал. Почему НЕ P1 (частичное опровержение силы кандидата): первая ветка функции (`app/daily_plan/snapshot.py:432-444`, standalone `UserGrammarExercise.last_reviewed`) от рассогласования **не страдает** — `app/srs/scheduling.py:67` пишет туда `day_to_naive_utc(..., days_ahead=0)`, то есть 02:00 учебного дня, а 02:00 всегда лежит внутри окна `[00:00, 24:00)` того же дня (проверено прогоном). Поэтому штатный путь пункта — его собственный URL на grammar-lab (`plan_builder.py:314-317`) — засчитывается верно в любой час, и у пользователя есть рабочий обход. Дефект проявляется только когда единственный сигнал — курсовой grammar-урок, и только в окне 00:00–02:00 локального времени.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/utils/time_utils.py:31` — `LEARNING_DAY_START_HOUR = 2`; `app/utils/time_utils.py:87-91` — `_study_day_date` возвращает вчерашнюю дату при `hour < 2`.
  - `app/daily_plan/snapshot.py:421` — `today = get_user_local_date(user_id, db)` (учебная дата, граница 02:00).
  - `app/daily_plan/snapshot.py:427-428` — `start_local = datetime(today.year, today.month, today.day, tzinfo=tz)`, `end_local = start_local + timedelta(days=1)` — окно **00:00→24:00**, то есть смещено на 2 часа назад относительно учебного дня `[D 02:00, D+1 02:00)`.
  - Контраст в том же файле: `app/daily_plan/snapshot.py:373` — `today_start, today_end = get_user_local_day_bounds(user_id, db)`, то есть сосед-детектор строит окно правильным хелпером (`app/utils/time_utils.py:100-113` → `day_to_naive_utc`, 02:00-anchored).
  - `app/curriculum/models.py:455` — `self.completed_at = datetime.now(timezone.utc)`: реальный момент, а не day-anchored значение. Именно по нему фильтрует вторая ветка `app/daily_plan/snapshot.py:446-458`.
  - Прогон (Europe/Istanbul, момент 2026-08-06 01:00 местного): учебный день = 2026-08-05; окно снапшота в naive UTC = `2026-08-04 21:00 … 2026-08-05 21:00`; `completed_at` = `2026-08-05 22:00` → **вне окна**. Корректные границы `get_user_local_day_bounds` = `2026-08-04 23:00 … 2026-08-05 23:00` → внутри.
- **Где расхождение:** код — CLAUDE.md фиксирует `get_user_local_date` как единственный источник «сегодня» и 02:00 как границу учебного дня; окно из `datetime(today.year, today.month, today.day)` этой границе не соответствует, тогда как сосед в том же файле использует `get_user_local_day_bounds`.

#### DP-010 · P2 · `app/api/daily_plan.py:196-216`

- **Кандидат:** `DP-C-022` · линзы-источники: CORE-C-05 · скептик: `skeptics/DP-C-022.md`
- **Симптом:** `add_study_minutes(when=...)` получает учебный день, а сравнивается с иными базисами
- **Сценарий отказа:** оба базиса реально расходятся в коде, и расхождение не перекрыто никакой дополнительной нормализацией. Сценарий: пользователь в таймзоне Europe/Istanbul завершает SRS-слот в 01:15 по местному времени. `linear_xp()` вызывает `get_linear_event_local_date` → час 1 < 2 → возвращает дату ВЧЕРАШНЕГО календарного дня; `add_study_minutes` пишет строку `DailyStudyMinutes` с `study_date = вчера`. В том же окне (00:00–02:00) `GET /api/daily-status` вызывает `_compute_study_minutes`, где `today = datetime.now(tz_obj).date()` возвращает СЕГОДНЯШНЮЮ календарную дату (сдвига на 02:00 нет) → `get_minutes_today(user_id, сегодня, db)` не находит строку (она лежит под `вчера`) → `minutes_studied_today` возвращает `0`, хотя минуты только что начислены. После 02:00 расхождение не «догоняет» задним числом: строка навсегда осталась под вчерашней датой, и ни один читатель её оттуда не запрашивает — минуты этой конкретной сессии в виджет не попадают никогда. Это ровно рассогласование двух базисов дня (не сам факт 02:00), т.е. не входит в список известных не-багов. Severity: P2, не P1 — `minutes_studied_today` не участвует ни в `day_secured`, ни в XP, ни в streak (это отдельный best-effort счётчик для виджета, `except Exception: return 0` глотает ошибки); эффект — заниженное/нулевое отображение прогресса в узком ежедневном окне 00:00–02:00 по местному времени пользователя, без порчи данных и без потери XP/streak.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/xp.py:171` — `when = for_date or get_linear_event_local_date(user_id, db_obj)`
  - `app/daily_plan/linear/xp.py:221` — `add_study_minutes(user_id, when, minutes, db_obj)`
  - `app/utils/time_utils.py:92-96` — `_study_day_date`: час < 2 → дата предыдущего календарного дня
  - `app/api/daily_plan.py:210` — `today = datetime.now(tz_obj).date()` (без 02:00-сдвига)
  - `app/curriculum/models.py:727-729` — `get_minutes_today` фильтрует по точному `study_date`
- **Где расхождение:** код — оба места читают свой собственный, разный источник даты; инвариант CLAUDE.md («получи текущее today через единый `get_user_local_date`») соблюдён только в writer'е, reader в `app/api/daily_plan.py` его не использует.

#### DP-011 · P2 · `app/utils/time_utils.py:74-86`

- **Кандидат:** `DP-C-025` · линзы-источники: CORE-C-09 · скептик: `skeptics/DP-C-025.md`
- **Симптом:** идемпотентные ключи `(user, дата, source)` пересчитываются из текущего `User.timezone`: смена зоны переигрывает прошлое
- **Сценарий отказа:** механизм воспроизводим по коду без внешних данных: `get_user_local_date` демонстративно не хранит и не сверяет tz на момент прошлой записи (это явно описано как «single source of truth», не как «snapshot at write time»), а идемпотентность всех перечисленных write-path'ов держится буквально на значении `event_date`, полученном пересчётом «сейчас». Смена `User.timezone` — обычное, ничем не защищённое действие (`app/auth/routes.py:576-578`), не взаимодействующее с ledger'ом. Эффект — двойное начисление XP за уже оплаченную активность (P1-грейд по формулировке брифинга: «тихо считает неверно (XP...)»), но снижаю до **P2**, поскольку триггер требует явного добровольного действия пользователя (смена таймзоны в настройках) — редкое, не случайное в фоне событие, и получатель двойного начисления — сам инициатор, а не пострадавшая третья сторона.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/utils/time_utils.py:83-86` — `get_user_local_date` каждый раз читает **текущий** `User.timezone` (через `_get_user_timezone`) и возвращает study-day дату для текущего момента; никакой привязки к историческому значению tz нет.
  - `app/auth/routes.py:576-578` — `current_user.timezone = tz` меняется прямым присваиванием по POST `/profile` (section=settings), без какого-либо взаимодействия с ledger'ом (`StreakEvent`, `DailyPlanLog` и т.п.) — смена tz никак не помечается и не триггерит пересчёт уже записанных дат.
  - `app/daily_plan/linear/xp.py:133-144` (`_already_awarded`) и `:147-210` (`award_linear_slot_xp_idempotent`) — `when = for_date or get_linear_event_local_date(...)` вычисляется заново при каждом вызове; проверка идёт по `StreakEvent.event_date == when` (буквенное значение `DATE`, записанное при первой записи, без сохранения исходного tz). `migrations/versions/20260621_idempotency_constraints.py:26-43` — уникальный индекс `uq_streak_events_xp_linear_source ON streak_events (user_id, event_date, (details->>'source'))` — ключ буквально по значению `event_date`, а не по «дню в исходном tz».
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-025.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — `CLAUDE.md` описывает `get_user_local_date` как «единственный источник правды» для дедупа XP, не оговаривая поведение при смене `User.timezone` задним числом; расхождение — в самом коде между «дедуп по (user, дата, source)» и отсутствием привязки этой даты к tz на момент исходной записи.

#### DP-012 · P2 · `app/words/routes.py:715-721`

- **Кандидат:** `DP-C-027` · линзы-источники: CORE-C-11 · скептик: `skeptics/DP-C-027.md`
- **Симптом:** дашбордная карточка гонки считает дату кохорты иначе, чем `/api/daily-race`
- **Сценарий отказа:** механизм найден и воспроизводится по коду. Сценарий: пользователь с `User.timezone` активен в окне 00:00–01:59 локального времени. Вызов `/race` (через `_build_daily_race_widget`) вычисляет `local_today` как календарный «сегодня» (не откатывает дату). Вызов `/api/daily-race` в ту же минуту вычисляет `local_today` через `get_user_local_date`, который из-за `LEARNING_DAY_START_HOUR=2` откатывает дату на «вчера». Два разных `race_date` → `get_or_create_race` резолвит/создаёт две разные кохорты (`DailyRace`/`DailyRaceParticipant`), т.е. `/race`-страница и `/api/daily-race` в это окно показывают разных участников гонки для одного и того же реального дня — именно эффект, который комментарий в `daily_race_status` заявляет как предотвращённый («клиентский tz позволял бы зачислиться в две гонки за один реальный день»), но по другому вектору (не клиентский tz, а разные функции вычисления даты) та же дыра остаётся открытой. Оговорка по масштабу эффекта: сейчас ни один шаблон/JS не дёргает `/api/daily-race` через fetch (grep по `app/static/js` и `app/templates` — 0 совпадений), так что в проде это не проявляется как одновременно видимое пользователю расхождение на одном экране — это расхождение между двумя независимо вызываемыми путями (SSR-страница `/race` и голый API-эндпоинт), подтверждённое кодом, но не гарантированно наблюдаемое сегодняшним UI одновременно. Отсюда P2, а не P1: чинится обходом «не открывать оба пути в окне 00:00–02:00», ключевой сценарий (закрытие дня/XP/streak) не задет.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:591-596` — ``` # Дата кохорты гонки — по User.timezone: клиентский tz позволял бы # зачислиться в две гонки (две даты) за один реальный день. from app.utils.time_utils import get_user_local_date local_today = get_user_local_date(user_id, db.session) standings = get_race_standings(user_id, local_today, tz=tz) ``` `get_user_local_date` → `app/utils/time_utils.py:85-93`: `_study_day_date(datetime.now(tz_obj))`, где `LEARNING_DAY_START_HOUR = 2` — час < 2 откатывает дату на вчера.
  - `app/words/routes.py:715-721` — ``` try: tz_obj = pytz.timezone(tz or DEFAULT_TIMEZONE) except pytz.UnknownTimeZoneError: tz_obj = pytz.timezone(DEFAULT_TIMEZONE) local_today = datetime.now(tz_obj).date() standings = get_race_standings(current_user_id, local_today, tz=tz) ``` Это обычная календарная полночь, БЕЗ вызова `_study_day_date`/`get_user_local_date` — 02:00-порог здесь не применяется.
  - `app/race/routes.py:32` — `tz = current_user.timezone or DEFAULT_TIMEZONE`, тот же источник tz, что и у `_get_user_timezone` в `get_user_local_date` (при отсутствии `request.args['tz']` источники tz совпадают) — расхождение изолировано именно к разнице в вычислении даты, а не к разным tz.
  - `app/achievements/daily_race.py:296-334` — `get_or_create_race(user_id, race_date)` ищет/создаёт `DailyRaceParticipant`/`DailyRace` по точному значению `race_date`; разные даты → разные строки кохорты.
- **Где расхождение:** код — CLAUDE.md фиксирует `get_user_local_date` как «единственный источник "today" для XP dedup» (scope — XP), но тот же принцип 02:00-границы студийного дня явно продокументирован в docstring `app/utils/time_utils.py` как общий для «plan, reading target, SRS budget, streak»; `_build_daily_race_widget` — код, который эту границу для кохорты гонки не применяет, хотя вычисляет тот же логический «today».

#### DP-013 · P2 · `app/api/daily_plan.py:368`

- **Кандидат:** `DP-C-029` · линзы-источники: CORE-C-13 · скептик: `skeptics/DP-C-029.md`
- **Симптом:** контракт докстринга «`tz` must match the timezone used to derive `target_date`» нарушен на call-site
- **Сценарий отказа:** сценарий: `User.timezone` в БД = `UTC` (или любой tz, отличный от того, что шлёт клиент), запрос `GET /api/daily-status?tz=Europe/Moscow`. Тогда `tz='Europe/Moscow'` (клиентский), а `today` вычислен по `UTC` (профильный). Внутри `check_immersion_achievement`: `day_start_local = tz_obj.localize(datetime(today.year, today.month, today.day))` локализует ДАТУ, посчитанную в UTC-базисе, в московском поясе — окно `[day_start, day_end)` сдвигается на разницу поясов (здесь −3ч) относительно фактических суточных границ пользователя. В итоге активность (Listening/Writing/Pronunciation/ReadingSession) у самой границы дня либо не попадёт в окно (ложный отказ в `immersion_daily`/`immersion_week`), либо в окно попадёт активность соседних суток (ложное начисление) — в обоих случаях неверный результат при валидном, ожидаемом клиентском вводе.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/achievements/services.py:1121-1126` — докстринг: `target_date is the user's LOCAL date. tz must match the timezone used to derive it so that the UTC query window aligns correctly with the user's day.`
  - `app/api/daily_plan.py:278` — `tz = _validate_timezone(request.args.get('tz', current_user.timezone or DEFAULT_TZ))` — приоритет у клиентского query-параметра `tz`.
  - `app/api/daily_plan.py:337` — `today = get_user_local_date(user_id, db.session)`, который внутри (`app/utils/time_utils.py:38-54`, `_get_user_timezone`) читает **только** `User.timezone` из БД, клиентский `tz` не участвует.
  - `app/api/daily_plan.py:368` — `check_immersion_achievement(user_id, today, db.session, tz=tz)` — `today` (источник: БД `User.timezone`) передаётся вместе с `tz` (источник: query-параметр запроса).
  - Показательно, что автор того же файла явно знал про эту ловушку и сознательно её обошёл в соседнем коде: `app/api/daily_plan.py:86` — `# Дедуп route-шагов — по User.timezone, не по клиентскому tz.` и `app/api/daily_plan.py:335-336` — `# secured_at / milestones ключуются по User.timezone — клиентский tz не должен сдвигать дату дедупа`. Именно этот принцип не соблюдён на вызове `check_immersion_achievement` тремя строками ниже.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-029.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — тот же файл двумя явными комментариями (строки 86, 335-336) декларирует принцип «дата дедупа — только по `User.timezone`, клиентский `tz` её не сдвигает», но на вызове `check_immersion_achievement` (368) этот же принцип не соблюдён: `tz` клиентский used together with server-derived `today`.

#### DP-014 · P2 · `app/daily_plan/service.py:118-137`

- **Кандидат:** `DP-C-034` · линзы-источники: CORE-D-02, API-C-09 · скептик: `skeptics/DP-C-034.md`
- **Симптом:** проигравший гонку `write_secured_at` роняет `PendingRollbackError` и уносит всю flush-only работу запроса
- **Сценарий отказа:** механизм воспроизведён напрямую на той же версии SQLAlchemy (1.4.x), что закреплена в `requirements.txt`, с тем же паттерном кода. Сценарий: два конкурентных запроса одного юзера (двойной таб, повторный XHR, гонка `/api/daily-status` и рендера дашборда) в момент первого `day_secured=True` в день — оба вызывают `write_secured_at` с одинаковым `(user_id, plan_date)`. Проигравший: `begin_nested()` сам делает pre-savepoint flush нового `DailyPlanLog`, ловит `IntegrityError` от гонки с уже закоммиченной строкой победителя, но SAVEPOINT для отката ещё не существовал — сессия остаётся «грязной». Повторный `query().first()` в обработчике `except IntegrityError` бросает `PendingRollbackError` вместо возврата строки победителя; это исключение вылетает из `write_secured_at` непойманным и в обоих caller'ах гасится общим `except Exception: db.session.rollback()`, который откатывает всю текущую транзакцию сессии — включая любую другую flush-only работу, накопленную в этом же запросе до этой точки (race-points sync, route-steps sync, milestone-notification flush в `/api/daily-status`). Практический ущерб ограничен тем, что все откатываемые операции (rank-up, `record_plan_completion`, immersion achievement, route-steps) идемпотентны по дню и обычно уже успешно записаны выигравшим запросом — потери данных пользователя не происходит, но именно для проигравшего запроса откатывается не связанный с гонкой flush-only код, а исключение молча гасится (только `logger.warning`), что маскирует саму гонку от наблюдения.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/service.py:118-134`: ```python log = DailyPlanLog.query.filter_by(user_id=user_id, plan_date=plan_date).first() if log is None: log = DailyPlanLog(user_id=user_id, plan_date=plan_date, mission_type=mission_type) db.session.add(log) try: with db.session.begin_nested(): db.session.flush() except IntegrityError: log = DailyPlanLog.query.filter_by(user_id=user_id, plan_date=plan_date).first() ``` Комментарий над функцией (104-113) утверждает: конкурент ловит `IntegrityError` внутри `begin_nested()`, не позже на `commit()` вызывающего. Это не так.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-034.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — `CLAUDE.md` описывает `write_secured_at` как «race-safe» именно через `begin_nested()` + `except IntegrityError`, но в закреплённой версии SQLAlchemy (1.4.x) этот паттерн не даёт заявленной гарантии для объекта, добавленного в сессию непосредственно перед `begin_nested()`: pre-savepoint autoflush уводит INSERT из-под защиты SAVEPOINT.

#### DP-015 · P2 · `app/api/daily_plan.py:1352-1372`

- **Кандидат:** `DP-C-037` · линзы-источники: CORE-D-08, API-C-03 · скептик: `skeptics/DP-C-037.md`
- **Симптом:** квота скипов — `SELECT count(*)` + сравнение в питоне без уникального индекса: обходится параллельным запросом
- **Сценарий отказа:** механизм гонки существует и воспроизводится по коду без выполнения запусков: два параллельных `POST /api/daily-plan/skip-lesson` с разными `lesson_id=A` и `lesson_id=B` от одного пользователя в один user-local день; оба процесса выполняют `count()` до commit друг друга → оба видят `skips_today=0` → оба проходят `0 >= 1 == False` → оба вставляют разные строки `LessonSkip` (уникальный constraint по тройке с `lesson_id` не мешает разным id) → оба коммитятся. Итог: 2 строки `LessonSkip` на пользователя за день вместо `DAILY_LESSON_SKIP_QUOTA=1`, `find_next_lesson(..., exclude_lesson_ids=deferred_ids)` исключает оба урока — квота пропусков уроков молча обходится. Severity — P2 (race/missing index на бизнес-инвариант, не потеря данных и не дыра в доступе; есть частичный аналог этой защиты в соседнем `slot_skipped`-механизме, что говорит о цене исправления как о低 — добавить partial unique index `(user_id, skipped_on_date)` по аналогии).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:1352-1357` — ```python skips_today = db.session.query(LessonSkip).filter_by( user_id=user_id, skipped_on_date=today, ).count() if skips_today >= DAILY_LESSON_SKIP_QUOTA: return api_error('skip_quota_exhausted', ...) ``` Квота проверяется обычным `SELECT count(*)` без `FOR UPDATE`/advisory-lock, вне какой-либо сериализации.
  - `app/daily_plan/models.py:242` — `UniqueConstraint('user_id', 'lesson_id', 'skipped_on_date', name='uq_lesson_skip_user_lesson_date')`. Уникальность — по тройке `(user_id, lesson_id, skipped_on_date)`, НЕ по паре `(user_id, skipped_on_date)`. Значит вставка двух строк с **разными** `lesson_id` на одну дату не конфликтует ни с чем.
  - `app/api/daily_plan.py:1367-1372` — `try: with db.session.begin_nested(): db.session.add(skip) except IntegrityError: return api_error('already_deferred', ...)`. Этот `except` перехватывает только повтор **того же** `lesson_id` (совпадение с уникальным constraint'ом); для разных `lesson_id` IntegrityError не возникает, страховки нет.
  - `app/api/daily_plan.py:1334-1336` — `lesson = db.session.get(Lessons, lesson_id)` — единственная проверка `lesson_id`, привязки к «текущему уроку плана» на сервере нет: любой валидный `lesson_id` принимается, значит два конкурентных запроса с двумя разными валидными id технически достижимы через прямой вызов API (не только через один UI-виджет).
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-037.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md описывает `DAILY_SKIP_QUOTA=1` и race-safe паттерн для *slot*-скипов (`uq_daily_plan_events_slot_skipped`), но не упоминает, что параллельный аналог для *lesson*-скипов (`uq_lesson_skip_user_lesson_date`) этой защиты не имеет — документ фиксирует другой механизм с тем же именем инварианта, не этот пробел.

#### DP-016 · P2 · `app/api/daily_plan.py:344-350`

- **Кандидат:** `DP-C-042` · линзы-источники: CORE-D-14 · скептик: `skeptics/DP-C-042.md`
- **Симптом:** идемпотентность milestone-уведомления держится на совпадении строки `link`
- **Сценарий отказа:** механизм отказа именно такой, как описан: race-safe защищён только `DailyPlanEvent` (уникальный partial-индекс + savepoint в `emit_minimum_completed`), а параллельный `Notification` создаётся в `emit_daily_plan_completed` без какой-либо защиты от гонки, и вызывается раньше по времени (намеренно, согласно комментарию), из-за чего у concurrent-запросов на первом закрытии дня `already_completed_today` синхронно `False` в обеих транзакциях. Эффект — дубль косметического уведомления, не влияет на `day_secured`, XP, streak, ранги — это отдельные ветки того же блока со своими идемпотентными механизмами (`write_secured_at`, `record_plan_completion` — StreakEvent-маркер, `check_plan_streak_milestone_notification`). Предлагаемая severity — P2 (гонка, отсутствующая защита уникальности), не P1: обязательный сценарий дня не ломается, обхода не требуется, задета только пользовательская видимость уведомлений.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/milestones.py:70-81` — `emit_daily_plan_completed` читает `already_completed_today` (SELECT по `DailyPlanEvent.event_type == 'minimum_completed'`) и только затем, если `already_completed_today and _notification_exists(...)`, выходит; иначе безусловно зовёт `create_notification(...)`. Проверка чисто read-then-act, без `SELECT … FOR UPDATE`, без advisory lock.
  - `app/api/daily_plan.py:344-349` — `emit_daily_plan_completed(user_id, today, db)` вызывается **до** `emit_minimum_completed(user_id, None, today)` в том же запросе; комментарий рядом прямо признаёт цель — «so the DailyPlanEvent guard sees the previous state on first secure of the day» — то есть на первом закрытии дня `already_completed_today` заведомо `False` и notification создаётся безусловно.
  - `app/api/daily_plan.py:864-891` (`emit_minimum_completed`) — race-safe запись `DailyPlanEvent` идёт через `db.session.begin_nested()` + `except IntegrityError`, опирающийся на уникальный partial-индекс `uq_daily_plan_events_minimum_completed` (`migrations/versions/20260418_add_minimum_completed_unique_index.py`, `ON daily_plan_events (user_id, plan_date) WHERE event_type = 'minimum_completed'`). Эта защита покрывает **только** сам `DailyPlanEvent`, не `Notification`.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-042.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — `CLAUDE.md` описывает паттерн race-safe idempotent-записи через `begin_nested()` + `except IntegrityError` на других похожих местах (`write_secured_at`, `grant_achievement`, `claim_survey_answer`, `_get_or_create_prompt`), но этот паттерн не применён к `Notification` в `emit_daily_plan_completed` — расхождение с собственным установившимся конвенцией проекта, а не с текстом CLAUDE.md напрямую.

#### DP-017 · P2 · `app/daily_plan/items/curriculum.py:661-703`

- **Кандидат:** `DP-C-043` · линзы-источники: CORE-E-01, ITEMS-A-04 · скептик: `skeptics/DP-C-043.md`
- **Симптом:** заблокированный спайн заставляет постранично пролистать остаток каталога: 229 SQL / 390 мс на очередь из 6 пунктов
- **Сценарий отказа:** с одной поправкой к формулировке: цикл партий **имеет** выход (короткая партия / `max_batches=50`), бесконечного зацикливания нет. Всё остальное воспроизведено на копии прода. Сценарий: пользователь, у которого до конца текущего модуля осталось меньше 13 уроков (у `user=39` — 6), получает очередь из 6 пунктов ценой 230 SQL-запросов и 479 мс, потому что после текущего модуля правило «предыдущий модуль ≥80%» блокирует следующий модуль → выбрасывается весь его CEFR-уровень → level-entry prereq'ы блокируют входные модули всех последующих уровней → цикл дочитывает все ~1500 оставшихся уроков спайна партиями по 39, лениво подгружая модуль каждого отброшенного урока. Эффект — не неверный вывод (очередь из 6 пунктов корректна), а деградация производительности основного экрана: сборка плана вырастает с ~20 SQL/40 мс до ~310 SQL/830 мс на каждый запрос. Это ровно определение P2 («деградация производительности»); на P1 не тяну — план собирается верно и отдаётся.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/items/curriculum.py:665-723` — цикл `for _ in range(max_batches)` с `batch_size = max(limit*3, 30)`; выход только по `limit` набранных items, по короткой партии (спайн исчерпан) или по `max_batches=50`. **Формулировка «не имеет выхода» неточна** — цикл конечен и завершается исчерпанием спайна (при 1548 уроках это ≈40 партий, до потолка 50 он не доходит). Но конечность здесь и есть проблема: он прочитывает ВЕСЬ остаток спайна.
  - `app/daily_plan/items/curriculum.py:680-693` — первый недоступный модуль кладёт `level_id` в `blocked_level_ids`, и весь остаток уровня отбрасывается `continue`. Причём `module`/`level` лениво подгружаются ДО этой проверки (`module = lesson.module`, `level = module.level`, строки 675-677) — то есть каждый отброшенный урок всё равно тянет свой модуль (запрос на каждый новый `module_id`).
  - `app/daily_plan/items/curriculum.py:580-597` — правило 4 `_module_accessible_for_user`: следующий модуль уровня доступен, только если предыдущий выполнен ≥80%. Для юзера, который стоит в середине текущего модуля, следующий модуль недоступен **всегда** → его уровень целиком выбрасывается.
  - _(ещё 4 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-043.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (CLAUDE.md описывает механику отбрасывания уровня и over-fetch корректно; стоимость постраничного скана в нём просто не оговорена)

#### DP-018 · P2 · `app/daily_plan/linear/progression.py:105-139`

- **Кандидат:** `DP-C-044` · линзы-источники: CORE-E-02, CORE-E-03 · скептик: `skeptics/DP-C-044.md`
- **Симптом:** выборка кандидатов — все колонки (включая `content JSON`), без `LIMIT`, с резолвом модуля по одному
- **Сценарий отказа:** механизм найден дословно и воспроизводим по коду. Сценарий: новый или «застрявший» (заблокированный prereq) пользователь → `candidates` включает все ещё не завершённые уроки по всему каталогу от `min_order` (потенциально сотни/тысячи строк с полным JSON `content`, цена которого сам код документирует как ~130ms полного скана); цикл при этом резолвит `Module` отдельным `SELECT` на каждый новый встреченный `module_id`, включая модули внутри уже помеченного заблокированным уровня, хотя `Module` уже участвовал в SQL-JOIN и мог быть заэагерен одним запросом (`contains_eager`) вместо повторных point-запросов. Функция вызывается в hot-path сборки дашборда/ плана дня. Найденный per-request memoize (`request_cache`) — существующая частичная защита от повторных вызовов в рамках одного запроса, но не от самой неэффективности одного вызова, поэтому не опровергает кандидата, а лишь ограничивает severity до P2 (деградация производительности, без потери данных и без сломанного функционального контракта).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/progression.py:105-120` — `db.session.query(Lessons).join(Module, ...).join(CEFRLevel, ...).filter(...).order_by(...)` без единого `.limit(...)` и без `load_only`/`defer` — полный `Lessons` (включая `content JSON`, `app/curriculum/models.py:222`) на каждую подходящую строку.
  - `app/daily_plan/linear/progression.py:81-84` (docstring) — «Result is memoized per request … because dashboard / plan assembly calls this 8+ times with the same args and each call is a full lessons-table scan (~130ms)» — сами авторы подтверждают, что один вызов делает полный скан таблицы lessons.
  - `app/daily_plan/linear/progression.py:137-139` — `for lesson in candidates: module_id = lesson.module_id; module = db.session.get(Module, module_id)` — т.к. `Module` не подгружен через `contains_eager`/`joinedload` из уже выполненного JOIN, `db.session.get()` промахивается мимо identity map при первой встрече каждого нового `module_id` и делает отдельный SELECT — классический N+1, несмотря на то что JOIN с `Module` уже присутствует в SQL для фильтрации.
  - `app/daily_plan/linear/progression.py:139` вызывается безусловно на КАЖДОЙ строке кандидатов (в т.ч. для уже заблокированного уровня — проверка `level_id in blocked_level_ids` идёt только строкой ниже, 152), то есть по одному новому module_id внутри заблокированного уровня — лишний SELECT впустую.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-044.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-019 · P2 · `app/daily_plan/items/curriculum.py:539-598`

- **Кандидат:** `DP-C-048` · линзы-источники: CORE-E-07 · скептик: `skeptics/DP-C-048.md`
- **Симптом:** один `_module_accessible_for_user` стоит до 5 запросов и зовётся на модуль
- **Сценарий отказа:** код `_module_accessible_for_user` и место его вызова в `build_curriculum_queue` в точности реализуют описанный кандидатом механизм: до 5 SQL-запросов на вызов (больше — если у модуля есть явные `prerequisites`), вызов происходит один раз на каждый впервые встреченный за сборку `module_id`, и кеш (`module_access`, `blocked_level_ids`) не переживает вызов `build_curriculum_queue`, то есть не защищает от повторной оплаты той же цены при следующей сборке плана (каждый дашборд/`/api/daily-status`). У «застрявшего» пользователя (заблокированный модуль далеко впереди по спайну, страница `max_batches=50 × batch_size≈30-45`) это означает десятки уникальных `module_id`, то есть потенциально сотни лишних запросов на КАЖДЫЙ рендер дашборда, а не одноразово.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/items/curriculum.py:563-568` — `has_progress = db.session.query(LessonProgress.id).join(Lessons, ...).filter(...).first() is not None` — запрос №1, безусловный (после опционального шага prereq).
  - `app/daily_plan/items/curriculum.py:573-577` — `first_module = Module.query.filter_by(level_id=module.level_id).order_by(Module.number).first()` — запрос №2, выполняется, если `has_progress=False`.
  - `app/daily_plan/items/curriculum.py:581-584` — `prev_module = Module.query.filter(...).order_by(Module.number.desc()).first()` — запрос №3, если модуль не первый в уровне.
  - `app/daily_plan/items/curriculum.py:586-588` — `total_lessons = Lessons.query.filter_by(module_id=prev_module.id).count()` — запрос №4.
  - `app/daily_plan/items/curriculum.py:590-594` — `completed_count = LessonProgress.query.filter_by(...).join(Lessons).filter(...).count()` — запрос №5.
  - Итого ровно 5 запросов в худшей ветке (нет прогресса, не первый модуль уровня, у предыдущего модуля есть уроки) — совпадает с формулировкой кандидата дословно, включая порядок.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-048.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код (как и в строке индекса) — сам инвариант документа не нарушен: CLAUDE.md фиксирует только сам факт per-`module_id` кеша («решение кешируется per `module_id`, не дёргается на каждый урок») — это верно и не противоречит кандидату: кандидат тоже утверждает «на каждый модуль», не «на каждый урок». Расхождения нет, но CLAUDE.md умалчивает про отсутствие кросс-запросного кеша и про рост стоимости при наличии `prerequisites`.

#### DP-020 · P2 · `app/telegram/queries.py:59-104`

- **Кандидат:** `DP-C-049` · линзы-источники: CORE-E-08 · скептик: `skeptics/DP-C-049.md`
- **Симптом:** `get_current_streak` идёт по дням до 366 итераций × до 8 запросов
- **Сценарий отказа:** механизм N+1-подобного обхода по дням с полным набором из 8 запросов на непокрытый repair-событием день буквально присутствует в коде, ничем не ограничен кроме жёсткого потолка 365/366 итераций, и не кэшируется. Сценарий: пользователь с непрерывным реальным streak'ом (например 100+ дней — продукт явно на это рассчитан: rank Grandmaster требует `plans_completed_total >= 365`, XP-мультипликатор завязан на `streak_days`) заходит на дашборд → `get_current_streak` обходит все ~100+ дней назад, для каждого дня без repair-события выполняет до 8 SELECT'ов → сотни лишних запросов на один рендер страницы, и это может повториться до 4 раз за один вызов `process_streak_on_activity` после того же действия (lesson/srs/reading и т.д.). Эффект — деградация производительности (задержка ответа/нагрузка на БД), пропорциональная длине streak'а, без потери данных и без блокировки функциональности напрямую — это оценка P2, а не P0/P1.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/telegram/queries.py:90-101`: ``` for offset in range(1, 366): check_date = local_now.date() - timedelta(days=offset) if check_date in repairs_by_date: streak += 1 continue day_start, day_end = _user_day_boundaries(tz, offset_days=-offset) if _has_activity_in_range(user_id, day_start, day_end): streak += 1 else: break ``` Цикл идёт максимум 365 раз (плюс отдельный вызов `has_activity_today` на сегодняшний день, строка 70) и обрывается (`break`) только при первом дне без активности и без repair-события — то есть при НЕПРЕРЫВНОЙ серии (реальный длинный streak) отрабатывают ВСЕ итерации до границы в 366 дней, каждая с отдельным запросом в БД (кроме repair-дней, которые взяты из предзагруженного словаря `repairs_by_date`, строки 81-87).
  - `app/utils/activity_tracker.py:74-146` (`has_learning_activity`): 8 последовательных `session.query(...).first()` по разным таблицам (`LessonProgress`, `UserGrammarExercise`, `UserCardDirection` join `UserWord`, `UserChapterProgress`, `UserLessonProgress`, `StudySession`, `StreakEvent`, `ListeningAttempt`), с ранним `return True` на первом совпадении — то есть от 1 до 8 запросов на один вызов, максимум достигается когда активность есть только в источнике №8 (или отсутствует вовсе — тогда все 8 отрабатывают перед `return False`).
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-049.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-021 · P2 · `app/modules/service.py:21-23`

- **Кандидат:** `DP-C-050` · линзы-источники: CORE-E-09 · скептик: `skeptics/DP-C-050.md`
- **Симптом:** проверка модуля = 2 запроса без мемоизации, зовётся из декоратора и context-процессора
- **Сценарий отказа:** механизм воспроизводится по коду напрямую: `is_module_enabled_for_user` действительно делает 2 отдельных `.first()`-запроса без какой-либо мемоизации ни на уровне сервиса, ни на уровне `has_module`, ни через `g`/request-scoped кеш. Он вызывается и из декораторов (`module_required`/`admin_or_module_owner` — по одному разу на защищённый роут), и из jinja-global `has_module`, который шаблон `base.html` (родитель `dashboard_unified.html`, страницы плана дня) зовёт 16 раз за один рендер — то есть один заход авторизованного пользователя на дашборд плана дня порождает минимум 32 избыточных SQL round-trip только на проверки модулей (плюс ещё запросы декоратора самого роута). Эффект — деградация производительности/лишняя нагрузка на БД на каждой кабинетной странице, а не порча данных или неверный результат (сами запросы идемпотентны и корректны).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/modules/service.py:71-88` — `is_module_enabled_for_user(user_id, module_code)`: сначала `module = ModuleService.get_module_by_code(module_code)` (запрос 1: `SystemModule.query.filter_by(code=code).first()`), затем `user_module = UserModule.query.filter_by(user_id=user_id, module_id=module.id).first()` (запрос 2). Ни `lru_cache`, ни кеш на `g`, ни мемоизация по `(user_id, module_code)` в файле не встречаются.
  - `app/modules/decorators.py:30` и `:64` — `module_required` и `admin_or_module_owner` вызывают `ModuleService.is_module_enabled_for_user(...)` напрямую на каждый защищённый запрос.
  - `app/__init__.py:255-260` — jinja global `has_module(module_code)` регистрируется как обычная функция (`app.jinja_env.globals.update(has_module=has_module)`), не как context-processor-переменная, вычисляемая один раз: она реально дергает `ModuleService.is_module_enabled_for_user(current_user.id, module_code)` при **каждом вызове из шаблона**.
  - `app/templates/base.html` — `has_module('study')` вызывается **8 раз** (строки 121, 132, 141, 281, 301, 373, 452, 484), `has_module('words')` — **5 раз** (94, 121, 128, 435, 479), `has_module('curriculum')` — **3 раза** (150, 367, 446). Итого 16 вызовов `has_module` в одном рендере `base.html` → 32 отдельных SQL-запроса на проверку модулей за один рендер.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-050.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (в CLAUDE.md нет утверждения о мемоизации модульных проверок; расхождения с документированным инвариантом нет, это чистая находка по коду).


### P3 — детали

#### DP-022 · P3 · `app/api/daily_plan.py:117`

- **Кандидат:** `DP-C-015` · линзы-источники: CORE-B-05, CORE-C-04 · скептик: `skeptics/DP-C-015.md`
- **Симптом:** две несогласованные реализации «вчера не закрыто» (pytz-ветка в API vs ZoneInfo в `next_step.py`)
- **Сценарий отказа:** механизм найден по коду и воспроизведён прямым вычислением дат для конкретного момента (без БД). `_get_recovery_suggestion` (`/api/daily-status`) и `_check_recovery` (`/api/daily-plan/continuation`, через `get_next_best_step`) — два живых HTTP-эндпоинта, оба отвечают на вопрос «не закрыт ли вчерашний план», и в окне 00:00–02:00 локального времени дают разный ответ для одного и того же состояния `DailyPlanLog`. Severity понижена до P3 (а не P1/P2, как можно было бы ожидать для рассинхрона streak/day-closing логики): `grep` по `app/static`, `app/templates`, `app/telegram` не находит ни одного потребителя полей `recovery_suggestion` или ответа `/api/daily-plan/continuation` — оба сейчас достижимы только через прямой HTTP-запрос к API и покрыты только юнит/API-тестами, ни один пользователь их сегодня не видит. Если поле когда-нибудь подключат к UI (баннер «вчера не закрыли»), находка станет минимум P2 — стоит поправить `_get_recovery_suggestion`, чтобы использовать тот же `get_user_local_date`-резолвер, что и `_check_recovery` и что и запись `DailyPlanLog.plan_date` в этом же роуте.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:112-116` — `_get_recovery_suggestion` считает «вчера» календарно: `tz_obj = pytz.timezone(tz)`; `yesterday = (datetime.now(tz_obj) - timedelta(days=1)).date()`. Не знает про `LEARNING_DAY_START_HOUR`.
  - `app/daily_plan/next_step.py:74-82` — `_check_recovery` явно комментирует несоответствие и лечит его: «Use the same ZoneInfo-based resolver as the rest of the app instead of a separate pytz stack... (audit E-026)»; `yesterday = get_user_local_date(user_id) - timedelta(days=1)`, где `get_user_local_date` учитывает 02:00-границу (`_study_day_date`, `app/utils/time_utils.py:88-93`).
  - `app/api/daily_plan.py:335-336` — тот же роут `daily_status()` для записи `DailyPlanLog` берёт дату **не** через pytz-полночь, а через `today = get_user_local_date(user_id, db.session)` — то есть `plan_date` в БД ключуется по study-day (02:00), а `_get_recovery_suggestion` в этом же роуте запрашивает `DailyPlanLog` по календарной дате. Разные базисы дня внутри одного файла на одну и ту же сущность.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-015.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md фиксирует `get_user_local_date` как «единственный источник "today" для XP dedup» и явно описывает 02:00-границу; `_get_recovery_suggestion` — единственное место в этой паре, где инвариант не соблюдён (использует pytz-полночь вместо canonical-резолвера), при этом сосед по тому же файлу (`daily_status()`, строка 335) для той же таблицы `DailyPlanLog` уже использует правильный `get_user_local_date`.

#### DP-023 · P3 · `app/daily_plan/linear/plan.py:384`

- **Кандидат:** `DP-C-016` · линзы-источники: CORE-B-07, API-A-09, ITEMS-E-14 · скептик: `skeptics/DP-C-016.md`
- **Симптом:** `tomorrow_preview` (INV-41) не эмитит ни один живой сборщик; единственный консьюмер — шаблон-сирота
- **Сценарий отказа:** оба звена цепочки подтверждены чтением кода: (1) единственный писатель `tomorrow_preview` — `build_tomorrow_preview`, вызываемый только внутри `get_linear_plan`, а `get_linear_plan` не вызывается ни одним продакшн-путём (реальный оркестратор `get_daily_plan` берёт из того же модуля только 4 несвязанных хелпера); (2) единственный шаблон-консьюмер `day_secured_banner.tomorrow_preview` — `partials/_day_secured_banner.html` — нигде не `{% include %}`-ится. Итог: ни один живой HTTP-путь (`/api/daily-plan`, `/api/daily-status`, dashboard-рендер через `unified_daily_plan.html`) не может отдать `tomorrow_preview`, и даже если бы отдавал — рендерить его некому. Формулировка кандидата точна по обоим пунктам.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/plan.py:384` — `tomorrow_preview = build_tomorrow_preview(user_id, session_provider) if day_secured else None` внутри `get_linear_plan(...)` (определение строка 299).
  - `app/daily_plan/linear/plan.py:405` — `'tomorrow_preview': tomorrow_preview,` в возврате `get_linear_plan`.
  - `app/daily_plan/plan.py:353-358` — реальный `get_daily_plan` импортирует из `linear/plan.py` только 4 хелпера, не `get_linear_plan` и не `build_tomorrow_preview`.
  - `app/daily_plan/plan.py:456,502,542` — три ветки возврата `get_daily_plan` (`mode: 'unified'` / setup-варианты), ни одна не содержит ключа `tomorrow_preview`.
  - `app/daily_plan/service.py:33` (комментарий) — «Only `unified` and `paused` modes are supported now» в `compute_day_secured_from_activity`, т.е. `mode='linear'` вне текущего контракта API.
  - `app/templates/partials/_day_secured_banner.html:76-77` — `{% if day_secured_banner.tomorrow_preview %} {% set _tp = day_secured_banner.tomorrow_preview %}`; `grep -rn "day_secured_banner" app/templates/` вне этого файла — 0 совпадений, `{% include %}` для него нигде не найден.
- **Где расхождение:** CLAUDE.md — секция Daily Plan/Intelligence документирует `tomorrow_preview` как часть текущего контракта payload («`tomorrow_preview` при `day_secured=True`»), хотя ключ принадлежит вымершему `mode='linear'`-сборщику и не эмитится unified-путём, который CLAUDE.md сам называет единственным входом (`get_daily_plan_unified`).

#### DP-024 · P3 · `app/daily_plan/next_step.py:43-51`

- **Кандидат:** `DP-C-018` · линзы-источники: CORE-B-09 · скептик: `skeptics/DP-C-018.md`
- **Симптом:** фактический порядок кандидатов не совпадает с задокументированным (INV-44)
- **Сценарий отказа:** CLAUDE.md перечисляет только 5 из 7 фактических шагов (пропущены `recovery` — первый по приоритету, и `writing` — четвёртый по приоритету между srs и grammar). Относительный порядок пяти упомянутых шагов (lesson > srs > grammar > reading > vocab) в коде не нарушен, но документ вводит в заблуждение по полноте цепочки: читающий CLAUDE.md не узнает, что recovery-подсказка идёт раньше unfinished lesson, и что writing-подсказка существует и вклинивается между srs и grammar. Severity предлагаю P3 (расхождение документа с кодом, без искажения относительного порядка задокументированных пунктов и без наблюдаемого пользовательского эффекта) — по шкале брифинга это ровно пример из категории P3 «расхождение документа с кодом».
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `CLAUDE.md:53` — `` `get_next_best_step(user_id, db)` в `app/daily_plan/next_step.py` — до 3 `NextStep` (lesson > SRS > grammar weak > reading > vocab). ``
  - `app/daily_plan/next_step.py:43-51` — фактический список в порядке вызова: ```python candidates = [s for s in [ _check_recovery(user_id, db), _check_unfinished_lesson(user_id, db), _check_srs_due(user_id, db), _check_writing_suggestion(user_id, db), _check_grammar_weak(user_id, db), _check_reading_progress(user_id, db), _check_vocab(user_id, db), ] if s is not None] ```
  - `app/daily_plan/next_step.py:4` — собственный docstring модуля уже фиксирует более полный порядок: `Priority: unfinished lesson > SRS due > writing > grammar weak > reading > vocab.` (recovery всё ещё не упомянут, но writing — есть, в отличие от CLAUDE.md).
- **Где расхождение:** CLAUDE.md

#### DP-025 · P3 · `app/words/routes.py:1814`

- **Кандидат:** `DP-C-020` · линзы-источники: CORE-B-12 · скептик: `skeptics/DP-C-020.md`
- **Симптом:** `repair-web` — единственный роут зоны без `api_error`
- **Сценарий отказа:** факт подтверждён построчным сравнением: во всей зоне (`app/api/daily_plan.py` целиком + daily-plan-роуты `app/words/routes.py`) `/api/streak/repair-web` — единственный роут, чей explicit-error-status ответ (`400 no_missed_date`) собран как ad-hoc dict вместо `api_error`, при этом twin-роут `/api/streak/repair` на идентичный guard-clause использует `api_error`. Сценарий вход→иной выход: `POST /api/streak/repair-web` без пропущенного дня → `{'success': False, 'error': 'no_missed_date'}` (нет `message`, нет `status`), тогда как `POST /api/streak/repair` на тот же кейс → `{'success': False, 'error': 'no_missed_date', 'message': 'No missed date found', 'status': 400}`. Severity понижена до P3 против выданной, а не до P1/P2: наблюдаемого эффекта нет — фронтенд-потребитель `repair-web` не найден нигде (`grep` по `app/static/js`, `app/templates` — 0 совпадений), а тест эндпоинта проверяет только наличие ключа `success`. Это расхождение форматов ошибок и нарушение конвенции CLAUDE.md, но не поломка сценария.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/words/routes.py:1814` — `return jsonify({'success': False, 'error': 'no_missed_date'}), 400` — ad-hoc dict, в обход `api_error`.
  - `app/api/daily_plan.py:1195-1196` — twin-роут `/api/streak/repair` на тот же guard-clause: `if not missed: return api_error('no_missed_date', 'No missed date found', 400)`.
  - `grep -n "), 4[0-9][0-9])\|), 5[0-9][0-9])" app/api/daily_plan.py` → единственное совпадение вне `api_error(...)` — сам `api_error('not_found', str(e), 404)` (L1281); во всём файле нет ни одного raw-`jsonify` с явным error-статусом, все идут через `api_error` (проверено построчно по всем 17 `return jsonify(...)`, L444-1391).
  - `app/words/routes.py` — 0 импортов и 0 вызовов `api_error` во всём файле; L1814 — единственный `jsonify(...)` с явным не-200 статусом в файле.
  - `tests/test_words_routes.py:891` — `assert 'success' in data` — контракт не проверяет `message`/`status`, отсутствие которых у L1814 (по сравнению с форматом `api_error`) тестами не ловится.
- **Где расхождение:** код — CLAUDE.md прямо предписывает `api_error(code, message, status)` как «единый helper, не ad-hoc dicts» (раздел Dashboard & API), этот роут — единственное известное исключение в зоне daily-plan API.

#### DP-026 · P3 · `app/api/daily_plan.py:139-152`

- **Кандидат:** `DP-C-028` · линзы-источники: CORE-C-12 · скептик: `skeptics/DP-C-028.md`
- **Симптом:** `goal_progress.daily_words` считается от 02:00, `weekly_lessons` — от иной границы
- **Сценарий отказа:** механизм воспроизводим по коду буквально: `daily_words.actual` использует единый проектный "study day" с границей 02:00 (тот же базис, что SRS/XP/streak), а `weekly_lessons.actual` считает неделю от обычной календарной полуночи через независимый inline-расчёт, который никогда не консультируется с `LEARNING_DAY_START_HOUR`. Конкретный сценарий: пользователь активен в понедельник в 00:30–01:59 по своему локальному времени (это ровно тот "ночной" сценарий, ради которого 02:00-граница и введена, см. `time_utils.py:1-14`). В этот момент `get_user_local_date`/`day_to_naive_utc` (и, соответственно, `daily_words`, SRS due-cards, streak, `day_secured`) всё ещё трактуют "сегодня" как воскресенье — предыдущий учебный день. Но `_compute_goal_progress` в этот же момент уже видит `now_local.weekday()==0` (понедельник) и сдвигает `monday_local` на начавшийся календарный понедельник: любой урок, завершённый в 00:00–01:59, уже попадает в счётчик НОВОЙ недели (`lessons_this_week`), а старая неделя обнуляется — притом что по модели самого проекта "учебный день" (и, соответственно, "учебная неделя") ещё не сменился. В ответе одного и того же запроса `daily_words` показывает активность вчерашнего (воскресного) учебного дня, а `weekly_lessons` уже отчитывается по новой неделе. Тестового покрытия этого окна нет (`tests/api/test_daily_status.py` проверяет только "activity после/до понедельника" через прямые вставки `completed_at`, без freeze на 00:00–02:00).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:236` — `words_today = count_new_cards_today(user.id)`; `app/srs/counting.py:96` — `today_start = _today_start_naive(user_id, db, now_utc)`, которая (`app/srs/counting.py:39-40`) зовёт `day_to_naive_utc`.
  - `app/utils/time_utils.py:120-153` (`day_to_naive_utc`) строит границу через `_study_day_date`, а та (`time_utils.py:88-92`) откатывает дату на 1 день, если `now_local.hour < LEARNING_DAY_START_HOUR` (=2). То есть `daily_words.actual` считается от локальной границы 02:00.
  - `app/api/daily_plan.py:243-246` (расчёт `weekly_lessons`) — независимый ad-hoc код: `now_local = datetime.now(tz_obj)`; `days_since_monday = now_local.weekday()`; `monday_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)`. Это чистая календарная полночь (00:00) и календарный `weekday()` — без обращения к `day_to_naive_utc`/`get_user_local_date`/`LEARNING_DAY_START_HOUR` вообще.
  - Оба поля пишутся в один и тот же объект `goal_progress` (`app/api/daily_plan.py:254-266`) и возвращаются одним ответом (`daily_status`, строка 390/435).
- **Где расхождение:** код — `LEARNING_DAY_START_HOUR=2` / `get_user_local_date` документированы как «единственный источник "today"» для дедупа и планового дня (CLAUDE.md, «User-local date», «Study day starts at 2am»), но `_compute_goal_progress` для границы недели этот источник не использует.

#### DP-027 · P3 · `app/daily_plan/snapshot.py:4-5`

- **Кандидат:** `DP-C-032` · линзы-источники: CORE-C-16 · скептик: `skeptics/DP-C-032.md`
- **Симптом:** докстринги модуля описывают границу «полночь», реализация даёт учебный день
- **Сценарий отказа:** докстринг `snapshot.py` (строки 3-5, 10-11) трижды называет границу заморозки/ролловера «user-local midnight», хотя единственный ленивый путь (`plan.py:403-404`) берёт дату через `get_user_local_date`, чья граница — 02:00 local (`LEARNING_DAY_START_HOUR=2`, `_study_day_date`), а не календарная полночь. Разница до двух часов (00:00-01:59) между тем, что докстринг подразумевает под «после полуночи», и тем, когда `today_local` реально переключается на новую дату. Эффект — вводящая в заблуждение документация модуля, не поведенческий сбой рантайма (severity P3, категория «расхождение документа с кодом» из брифинга).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/snapshot.py:3-5` — «It freezes full item dicts (id, kind, title, url, eta, data, completion_signal) at user-local midnight or on the first lazy build after midnight.» Термин «midnight» используется без оговорок трижды в докстринге (строки 4, 5, 10-11).
  - `app/daily_plan/plan.py:403-404` — единственный «ленивый» вызывающий передаёт в `resolve_snapshot_for_today` не календарную дату, а именно то, что докстринг называет границей заморозки: ``` today_local = get_user_local_date(user_id, session) snapshot = resolve_snapshot_for_today(user_id, today_local, session) ```
  - `app/utils/time_utils.py:88-93` — `get_user_local_date` явно НЕ календарная полночь: ```python def _study_day_date(now_local: datetime) -> date_cls: """Map an aware user-local timestamp to its study-day date.""" if now_local.hour < LEARNING_DAY_START_HOUR: return (now_local - timedelta(days=1)).date() return now_local.date() ``` `LEARNING_DAY_START_HOUR = 2` (там же, строка ~29). Собственный докстринг `get_user_local_date` (строки 82-83) прямо противопоставляет себя «calendar-midnight reset»: «A study day starts at 02:00 local time, so a late-night session is not interrupted by a calendar-midnight reset.»
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-032.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код (докстринг `snapshot.py`) расходится с зафиксированным в CLAUDE.md/time_utils.py инвариантом «учебный день начинается в 02:00» — сам докстринг не переиспользует общепринятый в проекте термин «study day», а вводит собственный, неточный.

#### DP-028 · P3 · `app/daily_plan/items/curriculum.py:676-677`

- **Кандидат:** `DP-C-045` · линзы-источники: CORE-E-04 · скептик: `skeptics/DP-C-045.md`
- **Симптом:** голые строки уроков → SELECT на каждый невиденный `module`/`level`
- **Сценарий отказа:** механизм подтверждён чтением кода: `get_spine_upcoming` не делает eager-load для `Module`/`CEFRLevel`, а обе задействованные relationship используют дефолтный ленивый lazy='select'. Сценарий: у пользователя anchor-урок в модуле M1, очередь `build_curriculum_queue(limit=CONTINUATION_QUEUE_LIMIT+1=13)` вызывает `get_spine_upcoming(batch_size=max(13*3,30)=39)`; спайн упорядочен по `(level.order, module.number, lesson.number)`, поэтому 39 уроков обычно покрывают несколько модулей (типично 8-12 уроков/модуль → 3-5 модулей) и иногда границу CEFR-уровня. На каждый новый `module_id`/`level_id` в цикле строки 676-677 бьют по одному дополнительному `SELECT ... WHERE id = ?` — 3-6 лишних запросов на сборку одной страницы очереди, при каждой отрисовке unified daily-plan для не-graduated пользователя. Снижаю severity против заявленной: это не N+1 «по строке» (39 уроков ≠ 39 SELECT'ов) — SQLAlchemy identity map схлопывает повторные обращения к одному и тому же модулю/уровню в рамках сессии, поэтому реальный оверхед — единицы дешёвых индексированных PK-lookup'ов (`idx` на `modules.id`/`cefr_levels.id` — первичные ключи), не пропорционален размеру страницы. Наблюдаемого замедления дашборда это не даёт — P3 (неоптимальность без наблюдаемого эффекта), а не производительностный P1/P2, как можно было бы прочитать из формулировки кандидата.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/progression.py:340-367` — `db.session.query(Lessons).join(Module, ...).join(CEFRLevel, ...)` возвращает **только** `Lessons`-объекты; join используется исключительно для фильтрации/сортировки, `Module`/`CEFRLevel` в результат не попадают и в identity map сессии не кладутся.
  - `app/curriculum/models.py:76` — `level = relationship('CEFRLevel', back_populates='modules')` (lazy='select' по умолчанию).
  - `app/curriculum/models.py:281` — `module = relationship('Module', back_populates='lessons')` (lazy='select' по умолчанию).
  - `app/daily_plan/items/curriculum.py:676-677` — `module = lesson.module` / `level = module.level if module is not None else None` внутри цикла `for lesson in upcoming:` — первое обращение к `lesson.module` для ещё не встречавшегося `module_id` бьёт `SELECT * FROM modules WHERE id = ?`; первое обращение к `module.level` для ещё не встречавшегося `level_id` бьёт `SELECT * FROM cefr_levels WHERE id = ?`. Дальнейшие уроки того же модуля/уровня берут объект из identity map сессии (SQLAlchemy кеширует по PK в рамках сессии) — повторного SELECT не будет, но кандидат и не утверждает обратное («на каждый ранее не виденный»).
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-029 · P3 · `app/daily_plan/level_utils.py:11-21`

- **Кандидат:** `DP-C-046` · линзы-источники: CORE-E-05 · скептик: `skeptics/DP-C-046.md`
- **Симптом:** `_user_min_level_order` без мемоизации: `_cefr_code_to_order` бьёт в БД на каждый вызов
- **Сценарий отказа:** механизм реален: `_user_min_level_order` (не `_cefr_code_to_order` напрямую, но именно она — источник эффекта) не мемоизирована, вызывается ≥3 раза за одну сборку плана для типового пользователя, и каждый раз бьёт БД заново, хотя соседняя функция в том же файле (`find_next_lesson_state`) для аналогичной проблемы («вызывается 8+ раз») уже получила request-level кэш с явным обоснованием в докстринге. Отсутствие того же паттерна здесь — реальная асимметрия. Но эффект не наблюдаем пользователем и почти не наблюдаем в профилировании: `cefr_levels` — таблица на 5-6 строк с уникальным индексом по `code`, а не «full lessons-table scan» как у соседа — лишние round-trips стоят микросекунды, не миллисекунды. Поэтому severity — P3 (неоптимальность без наблюдаемого эффекта), а не P2.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/progression.py:31-38` — `_user_min_level_order` не обёрнута в `_get_cache()`/`request_cache`, в отличие от соседней `find_next_lesson_state` в этом же файле (строки 78-87), которая явно мемоизирована с комментарием «dashboard / plan assembly calls this 8+ times with the same args and each call is a full lessons-table scan (~130ms)».
  - `app/daily_plan/level_utils.py:17` — `_cefr_code_to_order` выполняет `db.session.query(CEFRLevel.order).filter(CEFRLevel.code == level_code).first()`: колоночный запрос, identity map тут не участвует (мимо full-entity load), каждый вызов — новый SQL к БД.
  - `app/daily_plan/plan.py:370` — `get_user_level_progress(user_id, session, next_lesson=next_lesson)` безусловно вызывает `_user_min_level_order` первой строкой тела (`progression.py:215`), даже когда `next_lesson` уже передан.
  - `app/daily_plan/plan.py:254` (`build_curriculum_queue(...)`) — для типового незаблокированного, неграduated пользователя (есть `required_curriculum_lesson_id`, не skipped) вызывает `_user_min_level_order` ещё раз (`curriculum.py:644`).
  - `app/daily_plan/linear/progression.py:92` — сама `find_next_lesson_state` тоже вызывает `_user_min_level_order` на cache-miss (первый вызов в сборке).
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-046.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-030 · P3 · `app/daily_plan/items/srs.py:171-187`

- **Кандидат:** `DP-C-047` · линзы-источники: CORE-E-06 · скептик: `skeptics/DP-C-047.md`
- **Симптом:** `count_reviews_today` исполняется трижды за одну сборку SRS-item'а
- **Сценарий отказа:** механизм ровно такой, как описан: три идентичных по семантике (тот же `user_id`, тот же набор фильтров) SQL COUNT-запроса выполняются последовательно и синхронно внутри одного вызова `build_srs_item` (путь `as_deck_quiz=False`, то есть обычный SRS-item без deck-quiz подмены). Ни один из трёх сайтов не переиспользует результат другого — значения `now_utc=None` независимо резолвятся в `_naive_utc_now`/`_today_start_naive` на каждый вызов, но при обычной скорости выполнения одного запроса это не меняет итог (детерминированность не в фокусе кандидата). Эффекта на корректность нет — это чистая избыточность (2 лишних round-trip к БД на agregate COUNT с теми же фильтрами) без наблюдаемого пользователем сбоя, поэтому предлагаю P3, а не P2: запрос лёгкий (COUNT по индексируемым колонкам), не в горячем цикле (один раз на сборку SRS-item в рамках daily-plan assembly), падений/неверных данных не вызывает.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/items/srs.py:178` — `remaining_new, remaining_reviews = get_new_card_budget(user_id, db)`
  - `app/srs/counting.py:129` — внутри `get_new_card_budget`: `rev_today = count_reviews_today(user_id, db, now_utc=now_utc)` (вызов №1)
  - `app/daily_plan/items/srs.py:179` — `due_budget = get_due_card_budget(user_id, db)`
  - `app/srs/counting.py:160` — внутри `get_due_card_budget`: `rev_today = count_reviews_today(user_id, db, now_utc=now_utc)` (вызов №2)
  - `app/daily_plan/items/srs.py:185` — `reviews_today_total = count_reviews_today(user_id, db)` (вызов №3, напрямую)
  - `count_reviews_today` (`app/srs/counting.py:262-287`) каждый раз строит и выполняет собственный `db.session.query(func.count(...)).filter(...).scalar()` — ORM/движок не мемоизирует агрегатные запросы между вызовами, кеш-обёртки нет.
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-031 · P3 · `app/daily_plan/next_step.py:371-402`

- **Кандидат:** `DP-C-052` · линзы-источники: CORE-E-11 · скептик: `skeptics/DP-C-052.md`
- **Симптом:** `started_book_ids` без `LIMIT` + запрос `Book` на каждый id
- **Сценарий отказа:** оба факта кандидата буквально соответствуют коду: `LIMIT` отсутствует, и на каждый id идёт отдельный `Book.query.get`. Сценарий: юзер с прогрессом по нескольким книгам одновременно (или все его недавние книги — draft/лицензия истекла) → `_check_reading_progress` выполнит `len(started_book_ids)` последовательных PK-запросов к `book` вместо одного батч-запроса. Эффект есть, но верхняя граница — физическое число строк в `book` (сейчас 11, реально по данным — до 3 на юзера), т.е. деградация производительности сегодня не наблюдаема (≤3 лишних PK-lookup вместо одного `IN`-запроса). Понижаю severity до P3 («неоптимальность без наблюдаемого эффекта») относительно выданной, а не подтверждаю как ощутимую проблему — при росте каталога книг (сейчас 11) риск растёт линейно, но это не текущий баг.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/next_step.py:374-382` — запрос: ```python started_book_ids = [ r[0] for r in db.session.query(Chapter.book_id) .join(UserChapterProgress, UserChapterProgress.chapter_id == Chapter.id) .filter(UserChapterProgress.user_id == user_id) .group_by(Chapter.book_id) .order_by(func.max(UserChapterProgress.updated_at).desc()) .all() ] ``` Действительно без `.limit(...)` — вернёт ВСЕ книги, которые юзер когда-либо открывал.
  - `app/daily_plan/next_step.py:394-401` — цикл: ```python for bid in started_book_ids: candidate = Book.query.get(bid) if candidate is None or not getattr(candidate, 'is_published', True): continue if not can_user_access_book(user, candidate): continue book = candidate break ``` Действительно один `Book.query.get(bid)` на каждый id вместо батча `Book.query.filter(Book.id.in_(...))` — классический N+1, worst case (все книги draft/недоступны) = `len(started_book_ids)` отдельных SELECT.
  - Прод-данные (`learn_db_prod`, SELECT-only): `SELECT count(*) FROM book` = **11**; максимум различных `book_id` с прогрессом на одного юзера по всей базе = **3**, среднее 2.0. `UserChapterProgress` — PK `(user_id, chapter_id)`, т.е. `started_book_ids` физически не может превышать общее число книг в каталоге (11) ни при каком объёме активности одного юзера.
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-032 · P3 · `app/daily_plan/plan.py:511-549`

- **Кандидат:** `DP-C-053` · линзы-источники: CORE-E-12 · скептик: `skeptics/DP-C-053.md`
- **Симптом:** `_compute_module_progress` делает два раздельных COUNT там, где хватает одного
- **Сценарий отказа:** код действительно делает два раздельных `.count()`-запроса там, где из-за уникального индекса `(user_id, lesson_id)` на `LessonProgress` их можно безопасно слить в один запрос с условной агрегацией. Эффекта на корректность нет: функция вызывается один раз за сборку плана (не в цикле, N+1 не наблюдается), оба запроса лёгкие и покрыты индексами (`module_id` через FK/PK, `idx_lesson_progress_user_status`), поэтому наблюдаемой деградации производительности не установлено — чистая неоптимальность плюс докстринг, который сам противоречит телу функции.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/plan.py:526-530` — ```python total = ( db.session.query(Lessons.id) .filter(Lessons.module_id == module.id) .count() ) ```
  - `app/daily_plan/plan.py:531-540` — ```python completed = ( db.session.query(LessonProgress.id) .join(Lessons, Lessons.id == LessonProgress.lesson_id) .filter( LessonProgress.user_id == user_id, LessonProgress.status == 'completed', Lessons.module_id == module.id, ) .count() ) ``` Два независимых `.count()` → два круглых рейса к БД (`SELECT count(*) FROM lessons WHERE module_id=...` и `SELECT count(*) FROM lesson_progress JOIN lessons ... WHERE user_id=... AND status='completed' AND module_id=...`).
  - Благодаря уникальному индексу `(user_id, lesson_id)` на `lesson_progress` (`app/curriculum/models.py:341`) их можно было слить в один запрос через `outerjoin(LessonProgress, and_(LessonProgress.lesson_id == Lessons.id, LessonProgress.user_id == user_id))` + условный `func.sum(case(...))`, без риска задвоить `total` — фан-аут невозможен ровно из-за этого constraint'а.
  - Docstring самой функции (`app/daily_plan/plan.py:514`) утверждает «single COUNT for the user's current module», что расходится с фактическими двумя вызовами `.count()` в теле — расхождение комментария и кода налицо.
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)


### Опровергнуто скептиками — не переоткрывать без новых фактов

| Кандидат | Якорь | Утверждение финдера | Почему опровергнуто |
|---|---|---|---|
| `DP-C-001` | `app/telegram/scheduler.py:355-410` | планировщик морозит снапшот в 00:05 — до начала учебного дня; required весь день = карточка вчерашнего урока без ссылки, `day_secured` недостижим | механизм двухчасового опережения сборки в коде есть, но описанный отказ не наступает: (1) протухание состава возможно только для завершений в окне 00:00–02:00, а не «у активного юзера» вообще; (2) ссылка у незакрытого пункта всегда на месте (`url=None` ставится исключительно вместе с `completed=True`); (3) пункт закрывается повторным прохождением урока в тот же день через фолбэк `LessonProgress.last_activity` и повт… |
| `DP-C-005` | `app/daily_plan/snapshot.py:57-67` | пустой снапшот (`items: []`) считается валидным, персистится и морозит день | механизм («`_valid_snapshot` пропускает `items=[]`») в коде есть, но он не приводит к описанному эффекту «юзер видит план без единого пункта до конца дня»: каждая ветка, где `build_required_snapshot`/`_build_fresh_snapshot` легитимно возвращает пустой `items` (graduated, заблокированный спайн, уровень без контента), перекрыта отдельным, НЕ замороженным на день механизмом — `blocked_module` + форсированный `optional`… |
| `DP-C-009` | `app/daily_plan/service.py:183-190` | `_plan_meta.user_id = None` на paused- и fallback-ветках (INV-05), стража-теста нет | механизм (отсутствие `user_id` в двух вызовах `_with_plan_meta`) в коде есть, но заявленное следствие («нужен compute_day_secured_from_activity», то есть поломка вычисления `day_secured`) не наступает никогда: guard на строках 58-61 (`if not (graduated or spine_blocked): return False`) отсекает единственный путь, где `user_id` читается (строка 62), а на paused/fallback-ветках `graduated` и `blocked_module_id` структ… |
| `DP-C-010` | `app/daily_plan/plan.py:473-508` | если описание блокирующего модуля не построилось, `blocked_module_id=None` и заблокированный юзер теряет право закрыть день по активности | описанный кандидатом путь («модуль не резолвится» → `_describe_blocking_module` возвращает `None` → `blocked_module_id=None`) технически существует как код (`if module is None: return None`), но недостижим в штатном исполнении: `blocking_module_id` устанавливается в `find_next_lesson_state` только для `module_id`, для которого `db.session.get(Module, module_id)` уже вернул не-`None` объект в ЭТОЙ ЖЕ сессии нескольки… |
| `DP-C-011` | `app/curriculum/models.py:168-176` | заблокированный требованием «наберите N% в модуле X» не получает ни одного пункта, ведущего в модуль X | заявленный эффект («юзер не получает способа разблокироваться») не наступает: способ есть, просто он не оформлен как элемент daily-plan orchestrator'а, а идёт через отдельный, постоянно доступный маршрут «Курсы» → страница уровня → страница модуля X (модуль помечен `is_available=True`, так как его СОБСТВЕННЫЙ prerequisite давно выполнен) → пересдача любого урока модуля X через `?retry=true`, что обновляет `LessonPro… |
| `DP-C-012` | `app/achievements/streak_service.py:246-262` | GET `/dashboard` юзера на паузе инкрементит `plans_completed_total` и выдаёт монету через legacy-ветку `compute_plan_steps` | описанный механизм («ноль пунктов = план выполнен») перекрыт двумя явными гейтами: `steps_done > 0 and real_activity` для монеты и `steps_total > 0` для `record_plan_completion`. Прогон на настоящем paused-payload'е даёт `(0, 0)`, поэтому просто открыть /dashboard на паузе — no-op для монет и рангов. |
| `DP-C-013` | `app/api/daily_plan.py:270-384` | закрытие дня реализовано дважды, наборы побочных эффектов не совпадают | описанный эффект не наступает. Эффекты дашборда — строгое подмножество эффектов API, все «лишние» эффекты API идемпотентны и рассчитаны на многократный вызов, два из трёх названных кандидатом эффектов вообще не привязаны к `day_secured`, а вторая «поверхность» (`/api/daily-status`) не имеет ни одного клиента в продукте, так что выбора между поверхностями у пользователя нет. Общая часть закрытия (монета, completion,… |
| `DP-C-017` | `app/words/routes.py:1730-1755` | ветка `infinite_practice` вложена в `if next_item is None` и для graduated недостижима | заявленный механизм «optional форсированно содержит SRS/reading/grammar_review» не подтверждается кодом: `graduated` реально влияет только на один билдер (SRS, и то лишь снимает дневной кап, не гарантирует item), reading и grammar_review для graduated строятся точно так же, как для любого пользователя, и оба штатно возвращают `None` при отсутствии книги/тем. Условие `if next_item is None` — корректный, задокументиро… |
| `DP-C-019` | `app/daily_plan/plan.py:382-386` | `graduated` требует дополнительно `blocking_module_id is None` — INV-02 сформулирован иначе | кандидат цитирует только сокращённую формулировку из `CLAUDE.md:41` (это beginning-of-bullet shorthand про `_plan_meta`/`effective_mode`) и игнорирует непосредственно следующий пункт `CLAUDE.md:42` и параллельное упоминание в `CLAUDE.md:68`, которые явно и буквально описывают третье условие `blocking_module_id is None` и даже прямо пишут «требует ОБА условия для graduated». Документ в целом (не одна вырванная строка… |
| `DP-C-023` | `app/telegram/queries.py:22-37` | streak: дата дедупа из `get_user_local_date` (02:00), факт активности — из окна полуночи | расхождение базисов в функции есть, но описанного эффекта нет: streak (и его ремонт) считается по полуночному базису на всех шагах и `get_user_local_date` не читает вообще, поэтому в окне 00:00–02:00 ни один день серии не может быть засчитан или потерян из-за учебного 02:00-базиса. Учебный день в этой функции служит только ключом дедупа монеты/шагов/`record_plan_completion` — это другое свойство (сдвиг ключа дедупа… |
| `DP-C-026` | `app/utils/time_utils.py:46-54` | `get_user_timezone_name` не валидирует строку, `_get_user_timezone` валидирует — два разных ответа на один tz | механизм расхождения в самих хелперах существует (`get_user_timezone_name` действительно не валидирует), но заявленный эффект «потребители второго падают» не наступает: все 4 реальных потребителя строки из `get_user_timezone_name` в кодовой базе оборачивают конструирование таймзоны (`ZoneInfo`/`pytz.timezone`) в собственный `try/except`, откатывающийся на UTC/DEFAULT_TZ — то же поведение, что и у `_get_user_timezone… |
| `DP-C-030` | `app/daily_plan/models.py:29` | naive-колонки `DateTime` получают aware-значения `datetime.now(timezone.utc)` | механизм технически существует (aware-объект действительно улетает в БД как `timestamptz`-литерал и неявно кастуется в `timestamp`-колонку), но эффект «неверных сравнений» не наступает: каст `timestamptz → timestamp` зависит от session TimeZone, а он эмпирически зафиксирован в `Etc/UTC` и на прод-копии, и в тестовой БД, без единого места в коде, которое выставляло бы иной TimeZone. При TimeZone=UTC каст — no-op, nai… |
| `DP-C-031` | `app/books/reading_session.py:48-62` | `today` дефолтится в серверную локальную дату вопреки собственному докстрингу | по факту grep все шесть продакшн-точек вызова (`reading_session.py` x2, `api.py`, `linear/xp.py`, `linear/slots/reading_slot.py`, `daily_plan/items/reading.py`) явно передают `today`, вычисленный через `get_user_local_date`/`_study_day_date`, то есть учебный день пользователя (турновер 02:00), а не серверную UTC-дату. Fallback `date.today()` — защитный дефолт параметра, который в реальных путях никогда не срабатывае… |
| `DP-C-033` | `app/daily_plan/snapshot.py:42-53` | докстринг обещает race-safe get-or-create, фактически INSERT падает во внешней транзакции | описанного механизма в коде не существует: INSERT обёрнут в `begin_nested()` с `except IntegrityError` и re-fetch (`app/daily_plan/snapshot.py:45-53`), а откат savepoint'а в SQLAlchemy 1.4 экспанжит pending-объект, добавленный до savepoint'а, так что проигравший гонку запрос не падает ни на своём flush, ни на commit вызывателя. Докстринг (`snapshot.py:14-16`, `:32`) описывает код точно. Единственное, что действитель… |
| `DP-C-035` | `app/daily_plan/service.py:206-221` | blanket-`except` вокруг сборки плана отдаёт «оборонительный пустой payload» и маскирует отказ БД | заявленный механизм требует одновременно (а) DB-level исключения именно в чисто read-пути без записей и (б) отсутствия рядом стоящей защиты. Оба условия не выполняются: путь сборки плана ничего не пишет/не флашит, а основной потребитель (`_render_unified_dashboard`) явно откатывает сессию сразу после вызова через try/commit/except/rollback; у потребителей без локальной защиты отравление не маскируется, а немедленно… |
| `DP-C-036` | `app/api/daily_plan.py:96,599` | GET-эндпоинты зоны пишут и коммитят в БД | механизм «GET пишет в БД» присутствует буквально (это осознанный паттерн, документированный в CLAUDE.md: `write_secured_at` «идемпотентно, flush only, race-safe»), но описанный эффект («любой префетч/бот/повторная загрузка меняет состояние») не наступает: все три анкера (`route_step_added`, `secured_at`, `daily_race` enrollment/`plan_completed`) перекрыты дедуп-проверками до записи (existence-check / `IS NULL`-guard… |
| `DP-C-038` | `app/daily_plan/plan_builder.py:249-267` | смена книги при замороженном снапшоте: required требует старую книгу, XP считается по новой | механизм, который сравнивал бы «замороженную книгу слота» с «текущим предпочтением» и ломал бы закрытие слота, в коде отсутствует. Завершённость required-слота чтения целиком определяется замороженным `data.book_id` конкретного снапшота и НЕ обращается к живому `UserReadingPreference` вообще (ни в `_is_item_completed`, ни в `_read_today`, ни в `is_daily_reading_target_met_today`). Слот закрывается чтением именно той… |
| `DP-C-039` | `app/api/daily_plan.py:1125-1141` | `plan_pause`-события без идемпотентности и без уникального индекса | в коде есть механизм идемпотентности, просто реализован не как «check-then-insert», а как атомарный «delete-then-insert» в одной транзакции (комментарий на 1124 прямо называет цель: "Remove any existing plan_pause events (e.g., user extending/changing pause)"). При последовательном повторном POST от одного юзера каждый вызов сперва стирает все свои `plan_pause`-события с `event_date >= today`, а затем заново создаёт… |
| `DP-C-040` | `app/daily_plan/route_progress.py:152-183` | первая попытка защищена savepoint'ом, retry — нет | механизм (retry без savepoint) в коде действительно есть, но заявленный эффект «роняет запрос» не наступает: оба единственных вызывающих места оборачивают вызов `add_route_steps_idempotent` вместе с последующим `db.session.commit()` в собственный широкий `except Exception` + `rollback()`. Любой `IntegrityError`, всплывающий из-за отсутствия savepoint'а вокруг retry, перехватывается на уровень выше, логируется как wa… |
| `DP-C-041` | `app/daily_plan/models.py:60-77` | партиальные уникальные индексы объявлены только в миграциях: в любой `create_all`-БД DB-гарантии квот нет | сам факт (индекс не отражён в модели) подтверждён, но описанный эффект не наступает. В проде эта ветка не мертва: там схема ставится Alembic-миграциями (Dockerfile → `flask db upgrade head`), и партиальный индекс реально существует. Пробел ограничен `TESTING`-конфигурацией по явному дизайну (`app/__init__.py` комментарий: «In production, schema is managed by Alembic. In testing, create tables directly»), а не являет… |
| `DP-C-051` | `app/daily_plan/next_step.py:36-53` | все кандидаты `next_step` считаются энергично, хотя нужен первый | предпосылка «нужен только первый» не подтверждается кодом: контракт эндпоинта (докстринг + тесты), единственный вызывающий код и единственный вызов `get_next_best_step` без переопределения `max_steps` показывают, что реально запрашиваются и потребляются **до трёх** кандидатов (`steps`), а `step` — производное поле для обратной совместимости, не отдельная цель расчёта. Механизм «энергичного» вычисления всех 7 источни… |

---

## Подзона: Item builders и `linear/*` (Task 3)

### Индекс

| ID | Sev | Файл:строка | Симптом | Вериф. | Расхождение |
|---|---|---|---|---|---|
| DP-033 | P1 | `app/daily_plan/items/reading.py:50` | required-слот чтения строится без `can_user_access_book`/`is_published`: пункт ведёт в 403 и `day_secured` недостижим (подслучай «черновик» закрыт на ветке — см. тело находки; основной механизм лицензия/модуль открыт) | CONFIRMED | код |
| DP-034 | P1 | `app/curriculum/routes/lessons.py:388` | **theory-only** grammar-уроки (без секции `exercises`) платят 9 XP вместо 18: вычищенный ради антифрода `score` доезжает до скейлера как `0.0` | CONFIRMED | код |
| DP-035 | P1 | `app/daily_plan/linear/xp.py:505` | perfect-day (25 XP) без пассивного «подметальщика»: 30 из 72 закрытых дней прода без `xp_perfect_day` | CONFIRMED | код |
| DP-036 | P2 | `app/templates/partials/unified_daily_plan.html:11` | шаблон рендерит `u_optional[:5]` при очереди в 12–15 пунктов; «Показать ещё уроки» = `window.location.reload()` и нового не показывает | CONFIRMED | код |
| DP-037 | P2 | `app/daily_plan/plan.py:308-311` | `error_review` с `determine_section()=='required'` исчезает из плана целиком: optional отбрасывает, в required не кладёт никто; summary-фолбэк мёртв… | CONFIRMED | код |
| DP-038 | P2 | `app/daily_plan/plan.py:44-48` | арифметика optional-бюджета: `1+12+6=19 > OPTIONAL_MAX=15`, срез съедает хвост `_OPTIONAL_PRIORITY` (`word_set_quiz`, `challenge`) | CONFIRMED | код |
| DP-039 | P2 | `app/daily_plan/plan.py:276` | при полной очереди `completed_slots = 0` — карточки «пройдено сегодня» (INV-17) недостижимы для всех в середине курса | CONFIRMED | код |
| DP-040 | P2 | `app/daily_plan/items/curriculum.py:551-552` | нерезолвящийся модуль: очередь fail-open (`return True`), спайн fail-closed — противоположные дефолты | CONFIRMED | код |
| DP-041 | P2 | `app/daily_plan/snapshot.py:233` | `overlay_completion` не обновляет `data`: числа required-SRS заморожены на день, прогресс «X из N карточек» не рендерится | CONFIRMED | код |
| DP-042 | P2 | `app/daily_plan/linear/xp.py:302` | «строгий» гейт `srs:deck_quiz` читает ключ `linear_srs_global`, который пишет обычная SRS-сессия → required-квиз закрывается без квиза | CONFIRMED | код |
| DP-043 | P2 | `app/daily_plan/items/srs.py:203` | тир critical/collapse + чисто REVIEW-бэклог → `total_show=0`, слот исчезает молча, объясняющий hint гейтится `total_show>0` | CONFIRMED | код |
| DP-044 | P2 | `app/daily_plan/plan_builder.py:200` | гейт на пустые колоды применяется только при сборке снапшота: очистка колод в течение дня оставляет замороженный required `srs:deck_quiz` незакрываемым | CONFIRMED | код |
| DP-045 | P2 | `app/daily_plan/items/srs.py:196` | `ignore_daily_budget` печатает в заголовке весь бэклог, которого сессия не выдаст | CONFIRMED | код |
| DP-046 | P2 | `app/api/daily_plan.py:1010` | грейдер «Повтори 3 фразы»: пустой ответ засчитывается верным и закрывает `QuizErrorLog` | CONFIRMED | — |
| DP-047 | P2 | `app/daily_plan/items/phrase_review.py:20` | та же регексп как ключ дедупа схлопывает 200 фраз в 35 корзин — карточка выдаёт 1–2 задания вместо 3 | CONFIRMED | код |
| DP-048 | P2 | `app/daily_plan/items/challenge.py:81` | карточка челленджа ведёт на урок, тип которого в 44 % случаев не может выполнить критерий | CONFIRMED | код |
| DP-049 | P2 | `app/daily_plan/snapshot.py:192` | перенесённый снапшот тащит вчерашний подзаголовок «Норма дня — N мин» | CONFIRMED | код |
| DP-050 | P2 | `app/curriculum/routes/grammar_quiz_lessons.py:312` | гейт XP — липкий `status == 'completed'`, не `passed`: проваленная пересдача начисляет XP и закрывает required-слот | CONFIRMED | код |
| DP-051 | P2 | `app/achievements/xp_service.py:232` | `award_perfect_day_xp_idempotent` — единственный XP-хелпер без savepoint/уникального индекса | CONFIRMED | код |
| DP-052 | P2 | `app/daily_plan/linear/xp.py:216-225` | `add_study_minutes` — raceable check-then-insert против UNIQUE вне дедуп-savepoint'а; на IntegrityError сессия отравлена | CONFIRMED | код |
| DP-053 | P2 | `app/daily_plan/items/curriculum.py:117-129` | два сигнала `_curriculum_done_today` с разными правилами: первичный не проверяет проходной балл, фолбэк проверяет | CONFIRMED | код |
| DP-054 | P2 | `app/daily_plan/linear/xp.py:537` | blanket-`except` вокруг сборки плана: отравленная сессия рушит `commit()` вызывателя и откатывает уже отданный XP | CONFIRMED | код |
| DP-055 | P2 | `app/daily_plan/tier.py:47` | «признак сверхусилия» считается по источникам, которые пишет обязательный curriculum-урок | CONFIRMED | код |
| DP-056 | P2 | `app/study/routes.py:1035` | `/study/weekly` зовёт `get_daily_plan` с `db.session` вместо `db` | CONFIRMED | код |
| DP-057 | P2 | `app/daily_plan/linear/plan.py:216` | порядок по времени суток и `plan_difficulty` достижимы только из мёртвого `get_linear_plan`; живой план часа не читает | CONFIRMED | код |
| DP-058 | P2 | `app/daily_plan/items/curriculum.py:41` | `_LESSON_ETA_MINUTES` продублирован в двух модулях; 38.9 % уроков падают на дефолт | CONFIRMED | код |
| DP-059 | P3 | `app/daily_plan/items/curriculum.py:534` | реплика `check_module_access` в очереди не воспроизводит admin-байпас и игнорирует переданный `db` в 3 из 4 правил | CONFIRMED | код |
| DP-060 | P3 | `CLAUDE.md` (Daily Plan)` | 4 расхождения документа с кодом: порядок `build_optional`, состав `_OPTIONAL_PRIORITY`, проходной балл, число типов уроков | CONFIRMED | CLAUDE.md |
| DP-061 | P3 | `app/daily_plan/linear/slots/srs_slot.py:153` | легаси `build_srs_slot` подменяет слот на deck-quiz без проверки наличия колод (второе условие INV-27 отсутствует) | CONFIRMED | код |
| DP-062 | P3 | `app/daily_plan/plan_builder.py:110` | `_srs_item_dict` вызывается дважды с идентичными аргументами | CONFIRMED | — |
| DP-063 | P3 | `CLAUDE.md` | значения `get_adaptive_limit_reason()` в документе не совпадают с кодом | CONFIRMED | CLAUDE.md |
| DP-064 | P3 | `app/study/services/srs_service.py:486-487` | мёртвые локальные `now`/`today_start` с календарной UTC-полночью | CONFIRMED | код |
| DP-065 | P3 | `app/daily_plan/items/grammar_review.py:104` | `completion_signal='grammar_exercises'` вне `CompletionSignal` Literal | CONFIRMED | — |
| DP-066 | P3 | `app/curriculum/form.py:47` | `anki_cards`/`checkpoint` остались в choices **мёртвой** `LessonForm` и отсутствуют в `LESSON_TYPE_TO_SOURCE`/`route_map`: живого писателя нет, тип достижим только ручным JSON-импортом | CONFIRMED | код |
| DP-067 | P3 | `app/daily_plan/linear/xp.py:205` | `DailyPlanEvent('linear_slot_completed')` — ноль читателей | CONFIRMED | — |
| DP-068 | P3 | `app/daily_plan/linear/xp.py:68-72` | 5 мёртвых констант | CONFIRMED | — |
| DP-069 | P3 | `app/daily_plan/linear/xp.py:462` | `lesson_id` у listening/writing принимается и не используется | CONFIRMED | — |
| DP-070 | P3 | `CLAUDE.md` | 3 ключа LINEAR_XP не описаны (`_dictation`, `_audio_fill_blank`, `_use`) | CONFIRMED | CLAUDE.md |
| DP-071 | P3 | `app/curriculum/service.py:177` | `complete_lesson` без прод-вызывателей → путь `xp_curriculum_lesson`/30 XP мёртв | CONFIRMED | CLAUDE.md |
| DP-072 | P3 | `app/daily_plan/plan.py:466` | `plan_intensity`/`total_estimated_minutes` без живых консьюмеров; у graduated/blocked = 0 при 122–137 мин работы | CONFIRMED | — |
| DP-073 | P3 | `app/words/routes.py:1085` | `challenge_card` требует `lesson_id`, у всех 84 строк `daily_challenges` он NULL → виджет не рендерится | CONFIRMED | — |

### P0 — детали

_(находок этого уровня в подзоне нет)_


### P1 — детали

#### DP-033 · P1 · `app/daily_plan/items/reading.py:50`

- **Кандидат:** `DP-C-075` · линзы-источники: ITEMS-C-01 · скептик: `skeptics/DP-C-075.md`
- **Симптом:** required-слот чтения строится без `can_user_access_book`/`is_published`: пункт ведёт в 403 и `day_secured` недостижим
- **Сценарий отказа:** механизм воспроизводим по коду целиком, от выбора книги до `day_secured`. Сценарий: пользователь выбирает `licensed`-книгу с `expiration_date` в будущем через `/api/books/select` (доступ на тот момент есть, проверка проходит). `UserReadingPreference` сохраняется без TTL/ревалидации. На следующий день (или после того, как админ выключил модуль `books` пользователю / снял `is_published` / истёк `expiration_date`) `build_required_snapshot` → `_reading_item_dict` → `build_reading_item` → `_book_is_actionable_for_reading` по-прежнему считает книгу «actionable» (она существует, у неё есть главы, она не дочитана) и кладёт слот чтения в `required` с `url=/read/{book_id}`. Клик по URL получает `403` (`license_is_expired`/нет модуля) или `404` (`is_published=False`) на обоих роутах ридера. `_read_today`/`_is_item_completed` никогда не станет `True` для этой книги без реального сеанса чтения, а сеанс невозможен — доступ закрыт. `compute_day_secured_from_activity` требует `all(...)` по required → `day_secured=False` весь день. Обход в тот же день отсутствует: `skip-lesson`/`slot_skipped` по контракту (docstring `compute_day_secured_from_activity`, `app/daily_plan/service.py:44-47`) не засчитывается как learning activity. Смена книги через `/api/books/select` на доступную книгу возможна, но снапшот required заморожен на день (`app/daily_plan/snapshot.py` module docstring: «Required composition is fixed for the day»), поэтому исправляет ситуацию только со следующего дня — на текущий день слот всё равно недостижим.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/items/reading.py:50-72` — `_book_is_actionable_for_reading` проверяет только: книга существует, есть главы, книга не дочитана (`get_book_completion_state`). Ни `can_user_access_book`, ни `book.is_published` не читаются.
  - `app/daily_plan/plan_builder.py:245-263` — `_reading_item_dict` (единственный конструктор required-слота чтения, используемый живым путём) берёт `UserReadingPreference`, проверяет только `book_selected_today`, зовёт `build_reading_item(..., section='required', ...)` — тот же путь без access-проверки.
  - `app/daily_plan/snapshot.py:305-...` (`_is_finished_reading_book`) и `app/daily_plan/snapshot.py:266-273` (`_is_item_completed`, ветка `kind=='reading'`) — оверлей поверх замороженного снапшота тоже не содержит проверки доступа; единственная проверка — «книга дочитана».
  - `app/daily_plan/plan.py:397-404` — `get_daily_plan`: `required_dicts = overlay_completion(user_id, snapshot, session)` — это единственный источник `required` для живого unified-плана (не graduated/не blocked ветка); тот же путь, что и выше.
  - `app/daily_plan/service.py:60-73` (`compute_day_secured_from_activity`) — при непустом `required`: `return all(plan_completion.get(item['id']) or item['completed'] for item in required)`. Если элемент `kind='reading'` не может стать `completed` (пользователь не может физически открыть книгу), `day_secured` навсегда `False` в этот день.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-075.md`; здесь список усечён по бюджету, а не по значимости)_
- **Второй проход (три независимые линзы):** correctness=SOUND · reproducibility=REPRODUCIBLE · user-impact=P1 → **P1**. P1 подтверждён всеми тремя линзами. Read-only прогон по копии прода: user 39 держит `reading:book:4` в required 55 дней подряд, `/read/4` → 403, 0 закрытых дней. Обхода у пользователя нет.
- **Почему не P0(сверка с зональным правилом).** Правило зоны (раздел «Критерии severity») объявляет P0 любую находку, замораживающую `day_secured` для достижимого состояния, и три линзы второго прохода эту сверку не проводили — она делается здесь явно, чтобы «0 P0» в шапке не выглядело результатом недосмотра. Заморозка здесь **односуточная и восстановимая самим пользователем**: `POST /api/books/select` (`app/api/books_catalog.py:90-133`) гейтится `can_user_access_book` и перезаписывает `UserReadingPreference` на доступную книгу, а required-снапшот строится из этой же preference на следующий день — то есть путь к цели существует, он просто сдвинут на сутки. Это ровно определение P1 («пользователь может достичь цели другим путём»), поэтому зональная P0-оговорка (она про **невосстановимую** заморозку) не применяется. Оговорка не смягчает приоритет: 55 дней подряд у user 39 показывают, что восстановление на практике не происходит — UI не подсказывает смену книги, — поэтому DP-033 остаётся **первым** в очереди ремедиации среди P1. **Две поправки, дописанные при верификации 2026-08-28.** (1) Ветка «восстановимо» проверена не до конца: `can_user_access_book` пропускает `public_domain` всем зарегистрированным (`app/books/access.py:64-66`), поэтому обычно доступный кандидат есть; но если у юзера сняли модуль `books` и в каталоге нет ни одной опубликованной `public_domain` книги, каждый кандидат получит `403`, preference переписать нечем, и заморозка становится **невосстановимой** — по зональному правилу этот подслучай тянет на P0. Общий вердикт оставлен P1 (подслучай требует пустого public-domain каталога, чего на проде нет), но ремедиация обязана закрыть и его. (2) У находки был **более короткий репро без лицензий и отзыва доступа**: `POST /api/books/select` не проверял `Book.is_published`, тогда как ридер на нём `abort(404)` (`app/books/routes.py:358`), — то есть черновик записывался в preference и давал ровно тот же незакрываемый слот. Это уже **исправлено** на ветке (гейт черновика добавлен в `select_book`, тест `tests/api/test_books_catalog.py::TestSelectEndpoint::test_draft_book_returns_404_and_persists_nothing`); основной механизм DP-033 — лицензия/модуль — правкой не затронут и остаётся открытым.
- **Где расхождение:** код — `CLAUDE.md` описывает per-book access gate как обязательный «на КАЖДОМ роуте, отдающем содержимое книги» (раздел Books & Reading, `SEC-001`), но не упоминает, что построитель required-слота плана дня — не роут, отдающий контент, а конструктор ссылки на него — обязан ту же проверку делать заранее, иначе план сам предлагает недостижимый пункт. Это тот же класс проблемы, что и уже описанный в CLAUDE.md кейс с `check_module_access`/`find_next_lesson_linear` для курсовых уроков («план не должен предлагать урок, который сам же зафейлит по доступу»), но для чтения такая синхронизация не реализована.

#### DP-034 · P1 · `app/curriculum/routes/lessons.py:388`

- **Кандидат:** `DP-C-084` · линзы-источники: ITEMS-D-01 · скептик: `skeptics/DP-C-084.md`
- **Симптом:** **theory-only** grammar-уроки (без секции `exercises`) платят 9 XP вместо 18: вычищенный ради антифрода `score` доезжает до скейлера как `0.0`. _(Формулировка сужена до фактического охвата — исходный кандидат говорил «все grammar-уроки»; см. разбор ниже.)_
- **Сценарий отказа:** сценарий: пользователь открывает grammar-урок без раздела упражнений (theory-only), `LessonProgress` создаётся с `score=0.0` (DB default) при первом открытии; пользователь жмёт «Я понял(а) правило», клиент шлёт `score:100`, но сервер безусловно вычищает `score` для `_is_grammar_theory_only` (антифрод, комментарий в коде: «prevent challenge score forgery»), оставляя `progress.score == 0.0`; это значение доезжает до `apply_score_to_base` и режет базовые 18 XP (`linear_curriculum_grammar`) ровно пополам до 9. Эффект воспроизводится для КАЖДОГО завершения theory-only grammar-урока каждым пользователем, тихо (нет ошибки, нет визуальной аномалии), без обхода на клиенте — сервер игнорирует любой присланный score. Формулировка кандидата шире фактического охвата (не «все grammar-уроки», а только theory-only подмножество без `exercises`), но описанный механизм и числовой эффект (9 вместо 18) подтверждены буквально по коду. **Severity:** P1 — тихая неверная экономика XP (ключевой инвариант из CLAUDE.md: `_grammar=18`), нет обхода (антифрод-стрип безусловный), затрагивает всех пользователей на каждом theory-only grammar-уроке; не P0, т.к. не ломает основной сценарий и не портит/раскрывает данные — просто занижает вознаграждение.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/curriculum/routes/lessons.py:184-191` (`lesson_detail`) — при первом открытии урока создаётся `LessonProgress(user_id=..., lesson_id=lesson.id, status='in_progress', ...)` **без** `score` и сразу коммитится → колонка получает Python-side default.
  - `app/curriculum/models.py:325` — `score = Column(Float, default=0.0)`: дефолт не `None`, а `0.0`.
  - `app/templates/curriculum/lessons/grammar.html:879-892` (`autoCompleteTheoryLesson`) — клиент шлёт `body: JSON.stringify({ score: 100, status: 'completed', data: {...} })` на `update_lesson_progress` для theory-only урока (без `exercises`).
  - `app/curriculum/routes/lessons.py:324-338` — для `_is_grammar_theory_only`: `cleaned_data.pop('score', None)` — присланные клиентом `100` безусловно вычищаются (антифрод), `status` не трогается.
  - `app/curriculum/routes/lessons.py:354-356` — `if 'score' in cleaned_data: progress.record_score(...)` не выполняется (ключ вычищен) → `progress.score` остаётся тем же, что было при создании строки — `0.0`.
  - `app/curriculum/routes/lessons.py:379-388` — `if progress.status == 'completed': ... maybe_award_curriculum_xp(current_user.id, lesson_for_xp, db_session=db, score=progress.score)` — передаётся `0.0` (якорная строка `388: score=progress.score,`).
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-084.md`; здесь список усечён по бюджету, а не по значимости)_
- **Второй проход (три независимые линзы):** correctness=SOUND · reproducibility=REPRODUCIBLE · user-impact=P1 → **P1**. P1 подтверждён всеми тремя линзами. Все 86 из 86 grammar-уроков прода — theory-only; 18 из 20 реальных начислений `linear_curriculum_grammar` содержат ровно `xp=9` при показанных пользователю «100%».
- **Где расхождение:** код — CLAUDE.md документирует `LINEAR_XP` `_grammar=18` как единую константу без оговорки, что theory-only подтип фактически платит вдвое меньше; расхождение между заявленным инвариантом экономики и реализацией.

#### DP-035 · P1 · `app/daily_plan/linear/xp.py:505`

- **Кандидат:** `DP-C-085` · линзы-источники: ITEMS-D-02 · скептик: `skeptics/DP-C-085.md`
- **Симптом:** perfect-day (25 XP) без пассивного «подметальщика»: 30 из 72 закрытых дней прода без `xp_perfect_day`
- **Сценарий отказа:** механизм найден дважды независимо (структурно в коде — не все слот-завершающие пути вызывают проверку perfect-day, и нет ни одного пассивного пересчёта на уровне `daily_status`/cron; эмпирически в проде — точное совпадение 30/72). Сценарий: пользователь закрывает день последним действием через grammar-lab standalone practice (`grammar_lab_service.submit_answer`) или book-SRS review (`book_srs_integration.review_card`) — `day_secured` становится True на следующем `GET /api/daily-status`, XP за required-слоты уже начислены, но `xp_perfect_day` (25 XP, единственный источник) не создаётся ни в этом запросе (нет вызова), ни позже (нет ретроактивного подметания) → пользователь тихо недополучает 25 XP за закрытый день, что искажает `total_xp`/уровень.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/xp.py:505-559` — `maybe_award_linear_perfect_day` не самодостаточна: её никто не вызывает без внешнего триггера, и вызывается она только из POST-обработчиков конкретных слотов, а не из какого-либо периодического/пассивного пересчёта.
  - `app/api/daily_plan.py:270-388` — `daily_status()` пересчитывает `day_secured`, пишет `write_secured_at`, `record_plan_completion` (rank-up), `emit_daily_plan_completed`, `check_immersion_achievement`, `check_plan_streak_milestone_notification` на КАЖДЫЙ вызов — это и есть образец «подметальщика» для соседних систем. Для perfect-day XP такого шага в этой функции нет вообще.
  - `app/grammar_lab/services/grammar_lab_service.py:448-452` и `app/curriculum/services/book_srs_integration.py:478-481` — два реальных пути закрытия дня (standalone grammar-review, book-SRS review), которые начисляют свой slot-XP, но НИКОГДА не проверяют perfect-day, даже если это действие оказалось последним недостающим для закрытия дня.
  - Прод: 30/72 (41.7%) закрытых дней (`daily_plan_log.secured_at IS NOT NULL`) не имеют соответствующей записи `streak_events.event_type='xp_perfect_day'` за ту же `(user_id, event_date)` — число совпадает с заявленным дословно.
- **Второй проход (три независимые линзы):** correctness=PARTIAL · reproducibility=REPRODUCIBLE · user-impact=P1 → **P1**. P1 подтверждён. Формулировку триггера править: бонус пробуется не «в момент последнего слота», а только при первой за день записи slot-XP данного source внутри `if maybe_award_*(...) is not None`; три пути записи slot-XP не пробуют его вовсе, а оба писателя `secured_at` его не зовут. В проде 30 из 72 закрытых дней (42%, 9 из 11 юзеров) без `xp_perfect_day`.
- **Где расхождение:** код — CLAUDE.md описывает `day_secured` как «API пересчитывает из активности через `compute_plan_steps` + `compute_day_secured_from_activity`» на каждый вызов, и не документирует, что perfect-day XP не следует этому же пересчёту — расхождение между задокументированным «единым источником дня» и фактическим fire-and-forget начислением бонуса.


### P2 — детали

#### DP-036 · P2 · `app/templates/partials/unified_daily_plan.html:11`

- **Кандидат:** `DP-C-054` · линзы-источники: ITEMS-A-01, ITEMS-E-01, ITEMS-A-06 · скептик: `skeptics/DP-C-054.md`
- **Симптом:** шаблон рендерит `u_optional[:5]` при очереди в 12–15 пунктов; «Показать ещё уроки» = `window.location.reload()` и нового не показывает
- **Сценарий отказа:** механизм именно такой, как описан. Сервер (`build_optional`) может вернуть до 15 приоритизированных optional-пунктов за один ответ, но партиал безусловно показывает только первые 5 (`u_optional[:5]`, без какого-либо оффсета, сохранённого в URL/сессии/DOM). Кнопка «Показать ещё уроки» не делает ни AJAX-дозагрузки, ни передачи offset — она вызывает `window.location.reload()`, то есть повторный полный рендер той же страницы с теми же входными данными. Если состояние пользователя не изменилось (не пройден активный урок, не сдвинулась очередь), ответ сервера идентичен предыдущему, и шаблон снова отрежет его до тех же первых 5 пунктов — пункты 6–15 никогда не становятся видимыми через эту кнопку. Сценарий: у юзера continuation-очередь на 12 пунктов (`u_has_more=True` или `u_has_hidden_optional=True`) → жмёт «Показать ещё уроки» → страница перезагружается → снова видит те же 5 пунктов, без прогресса к оставшимся 7. Единственный способ увидеть больше — реально выполнить/пропустить видимые пункты, из-за чего они уйдут в «завершённые сегодня» и следующие пункты очереди поднимутся в первые 5; но это не то, что обещает подпись кнопки, и это не «догрузка», а побочный эффект прогресса.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/templates/partials/unified_daily_plan.html:11-12` — `{% set u_optional_visible = u_optional[:5] %}` / `{% set u_has_hidden_optional = (u_optional | length) > (u_optional_visible | length) %}` — жёсткий срез на 5, без оффсета/страницы.
  - `app/templates/partials/unified_daily_plan.html:582,598` — оба цикла рендера optional-секции идут по `u_optional_visible`, то есть по тем же первым 5 элементам.
  - `app/templates/partials/unified_daily_plan.html:679-687` — кнопка `data-action="reload-plan"` показывается при `u_has_more or u_has_hidden_optional`, подпись «Показать ещё уроки».
  - `app/templates/partials/unified_daily_plan.html:731-739` — единственный обработчик клика: `btn.addEventListener('click', function() { ...; window.location.reload(); });` — просто полная перезагрузка страницы, никакого `fetch`/offset/query-параметра.
  - `app/daily_plan/plan.py:42-48` — `OPTIONAL_MAX = 15`, `CONTINUATION_QUEUE_LIMIT = 12`: сервер реально способен вернуть до 15 optional-пунктов за один вызов `get_daily_plan_unified`.
  - `app/words/routes.py:1012` — `unified_plan = get_daily_plan_unified(current_user.id, tz=tz) or {}` — вызывается без каких-либо параметров пагинации/offset из `request.args`; при повторном GET (в т.ч. после `reload()`) без изменения активности пользователя список `optional` идентичен предыдущему, и шаблон снова отрежет его до тех же первых 5 элементов.
- **Где расхождение:** код — раздел CLAUDE.md про «Optional accumulation (continuation queue)» описывает серверную сторону (`OPTIONAL_MAX=15`, `CONTINUATION_QUEUE_LIMIT=12`, `has_more_optional`) как рабочий контракт для дашборда, но не упоминает, что фронтенд-партиал дополнительно и безусловно режет любой такой список до 5 без реального «догрузки» механизма — это расхождение между задуманным сигналом `has_more`/`has_more_optional` («мягкая подсказка для повторного фетча дашбордом», см. `app/daily_plan/plan.py:274` docstring `has_more`) и фактической реализацией кнопки, которая этот повторный фетч не делает целенаправленно (нет offset), а просто перезагружает страницу.

#### DP-037 · P2 · `app/daily_plan/plan.py:308-311`

- **Кандидат:** `DP-C-055` · линзы-источники: ITEMS-A-02, ITEMS-C-04, ITEMS-C-11 · скептик: `skeptics/DP-C-055.md`
- **Симптом:** `error_review` с `determine_section()=='required'` исчезает из плана целиком: optional отбрасывает, в required не кладёт никто; summary-фолбэк мёртв как следствие
- **Сценарий отказа:** механизм именно такой, как описан. Сценарий: у пользователя `unresolved count_unresolved == 20` (≥ `REQUIRED_UNRESOLVED_THRESHOLD=15`) и cooldown истёк (`should_show_error_review` True). `determine_section` возвращает `'required'`. В `build_optional` кандидат `error_review` получает `section != 'optional'` → `return None` → выброшен из optional. В `build_required_snapshot` (единственный источник `required`) для error_review нет ни одной ветки кода — он туда физически не может попасть. Итог: у пользователя с САМЫМ острым backlog (или после 3 провалов подряд) `error_review` отсутствует одновременно и в required, и в optional — то есть плана дня для разбора ошибок для него нет вовсе, тогда как пользователь с меньшим backlog (5-14 unresolved) получает его в optional. Эскалация переворачивает видимость на противоположную: чем острее сигнал, тем менее заметен пункт в плане. `had_recent_failures`/`REQUIRED_UNRESOLVED_THRESHOLD` фактически не влияют на итоговый payload — их результат используется только для того, чтобы решить, выбросить кандидат или нет, что и есть заявленный «мёртвый summary-фолбэк» (ветка `'required'` в `determine_section` не имеет живого потребителя своего значения кроме самой проверки на неравенство `'optional'`). Severity: понижаю до **P2** (не P1) — на `day_secured`/XP/streak это не влияет (error_review никогда не входил в required и не гейтит день ни в одной ветке `build_required_snapshot`), у пользователя остаётся обход через прямой URL `/learn/error-review/` (роут `error_review_session` в `app/curriculum/routes/main.py:183` не завязан на присутствие пункта в плане). Но это реальное, воспроизводимое расхождение поведения (инверсия эскалации), а не мёртвая ветка без наблюдаемого эффекта — поэтому не P3.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/plan.py:308-312`: ```python if kind == 'error_review': section = determine_section(user_id, db) if section != 'optional': return None return build_error_review_item(user_id, db, section='optional') ``` Единственный вызов `determine_section` во всём `app/`. Когда она возвращает `'required'` (см. ниже), кандидат ловится веткой `if section != 'optional': return None` и молча выбрасывается из optional-секции.
  - `app/daily_plan/items/error_review.py:65-79`: ```python def determine_section(user_id: int, db: Any) -> Optional[str]: if not should_show_error_review(user_id, db): return None unresolved = count_unresolved(user_id, db) if unresolved >= REQUIRED_UNRESOLVED_THRESHOLD or had_recent_failures(user_id, db): return 'required' return 'optional' ``` `REQUIRED_UNRESOLVED_THRESHOLD = 15` (строка 38). При unresolved≥15 ИЛИ 3 подряд проваленных попытки (`had_recent_failures`) функция возвращает `'required'`.
  - `app/daily_plan/plan_builder.py:70-133` (`build_required_snapshot`, единственный сборщик `required`-списка для unified-плана) — импортирует только `build_curriculum_item`, `build_reading_item`, `build_srs_item`, `_grammar_prep_item_dict`; `error_review` там не упоминается ни разу (docstring модуля прямо перечисляет, что входит в required: curriculum, SRS, reading, grammar_prep — error_review не в списке).
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-055.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md не описывает контракт `error_review`/required-тира для unified-плана вообще (раздел Daily Plan упоминает error_review только как источник optional/XP/streak, без деталей `determine_section`), поэтому это внутреннее рассогласование кода с собственным docstring `app/daily_plan/items/error_review.py:4-16` («``required`` only when unresolved ≥ 15 …»), а не с CLAUDE.md.

#### DP-038 · P2 · `app/daily_plan/plan.py:44-48`

- **Кандидат:** `DP-C-056` · линзы-источники: ITEMS-A-03, ITEMS-E-02 · скептик: `skeptics/DP-C-056.md`
- **Симптом:** арифметика optional-бюджета: `1+12+6=19 > OPTIONAL_MAX=15`, срез съедает хвост `_OPTIONAL_PRIORITY` (`word_set_quiz`, `challenge`)
- **Сценарий отказа:** механизм найден и воспроизводим по коду. Вход: активный не-graduated пользователь без карточных колод (SRS-дубль в optional дедупится с required `srs:global` — см. docstring `build_srs_item`), с непустыми `phrase_review`, ≥12 доступными уроками впереди по спайну, и хотя бы одним непустым источником среди `reading`/`error_review`/`grammar_review`. Неверный выход: `word_set_quiz` и/или `challenge` (валидные, ненулевые `PlanItem`) молча выпадают из payload `optional` на срезе `active_candidates[:15]`, а кнопка «Показать ещё», обещанная флагом `has_more_optional`, на деле делает `window.location.reload()` без какой-либо пагинации — то есть не открывает доступ к обрезанным пунктам, пока состояние БД само не изменится (что структурно не гарантировано, пока очередь спайна остаётся ≥12). Итог: заявленный в кандидате арифметический разбор (`1+12+6=19 > 15`, съедается хвост приоритета) подтверждается буквально построчно; практический эффект — не потеря данных и не угроза `day_secured` (контракт явно завязан только на `required`), а систематическое, не самоисправляющееся исчезновение двух engagement-функций (word_set_quiz, challenge, последние с achievements `challenge_first`/`challenge_streak_7`/`challenger`) из «Дополнительно» у типичного активного пользователя. Обход есть — прямые URL уроков/challenge вне дневного плана — поэтому не P1.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/plan.py:42` — `OPTIONAL_MAX = 15`.
  - `app/daily_plan/plan.py:45` — `CONTINUATION_QUEUE_LIMIT = 12`.
  - `app/daily_plan/plan.py:109-116` — `_OPTIONAL_PRIORITY = ('srs', 'reading', 'error_review', 'grammar_review', 'word_set_quiz', 'challenge')` — 6 источников, каждый вкладывает максимум 1 item (`# Other practice sources. Each contributes at most one optional item.`, line ~264-269).
  - `app/daily_plan/plan.py:196-236` — порядок наполнения `active_candidates`: (1) `phrase_review` (0/1, через `_accept(_build_optional_candidate(..., 'phrase_review', ...))`), (2) очередь спайна `queue_items[ :CONTINUATION_QUEUE_LIMIT]` (0..12, через цикл `for queue_item in queue_items[:CONTINUATION_QUEUE_LIMIT]: _accept(queue_item)`), (3) цикл `for kind in _OPTIONAL_PRIORITY: ... _accept(candidate)` — здесь `word_set_quiz` и `challenge` вставляются ПОСЛЕДНИМИ.
  - `app/daily_plan/plan.py:270-277` — срез без учёта приоритета кроме порядка вставки: `active_subset = active_candidates[:max_items]`; `has_more = queue_truncated or ... or len(active_candidates) > len(active_subset)`. Никакого re-balance или round-robin — чистый positional cutoff, значит первым «вылетает» то, что вставлено последним, т.е. хвост `_OPTIONAL_PRIORITY`.
  - _(ещё 5 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-056.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — комментарий в самом `app/daily_plan/plan.py:43-47` заявляет, что `CONTINUATION_QUEUE_LIMIT` «Kept below `OPTIONAL_MAX` so completed-today cards and the other practice sources (SRS, reading, …) still fit under the overall cap», но арифметика (12 очередь + 1 phrase_review = 13, всего 2 слота на 6 источников) этого не гарантирует — сам код опровергает свой же комментарий о намерении. CLAUDE.md раздел «Optional accumulation» документирует константы и `has_more_optional`, но не заявляет, что кнопка «Показать ещё» реально раскрывает обрезанный хвост — это отдельный, не задокументированный разрыв контракта (обещание пагинации без реализации пагинации).

#### DP-039 · P2 · `app/daily_plan/plan.py:276`

- **Кандидат:** `DP-C-057` · линзы-источники: ITEMS-A-05 · скептик: `skeptics/DP-C-057.md`
- **Симптом:** при полной очереди `completed_slots = 0` — карточки «пройдено сегодня» (INV-17) недостижимы для всех в середине курса
- **Сценарий отказа:** механизм детерминирован по коду и не требует рантайм-допущений: длина спайна (76+ модулей, документировано в CLAUDE.md) гарантирует, что `build_curriculum_queue` в середине курса almost always выдаёт полные 12 карточек, а `OPTIONAL_MAX=15` оставляет только 3 места на все прочие активные источники (`phrase_review`, `srs`, `reading`, `error_review`, `grammar_review`, `word_set_quiz`, `challenge`) — типичный активный юзер с `srs`+`reading` уже занимает оставшийся бюджет, и `completed_slots` схлопывается в 0. Сценарий: пользователь в середине курса проходит required-урок, затем ещё один урок из очереди «Дальше по курсу» сверх обязательного минимума → при следующей сборке плана (reload/refetch) карточка только что пройденного урока не отображается в optional, хотя докстринг `get_curriculum_lessons_completed_today` прямо обещает обратное («stay visible instead of being replaced by the next pending lesson»). Функциональные инварианты не задеты: `day_secured` зависит только от `required` (докстринг `build_optional`, строки 128-134, и модульный докстринг `plan.py:1-15`), XP/streak начисляются в момент завершения урока независимо от последующей сборки optional-списка — потеря чисто визуальная (пропадает подтверждающая карточка), не функциональная. Поэтому severity P2 (расхождение контрактов, заметное неверное поведение без обхода), а не P1/P0.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/plan.py:42,48` — `OPTIONAL_MAX = 15`, `CONTINUATION_QUEUE_LIMIT = 12`.
  - `app/daily_plan/plan.py:249-260` — очередь спайна строится с `limit=CONTINUATION_QUEUE_LIMIT + 1` и вставляется до `CONTINUATION_QUEUE_LIMIT` (12) элементов при наличии required curriculum-урока и неисчерпанного спайна — гарантировано в середине курса (76+ модулей, CLAUDE.md), т.к. `build_curriculum_queue` «пейджится» по спайну, пока не наберёт `limit` (докстринг `curriculum.py:654-666`).
  - `app/daily_plan/plan.py:274-278`: ``` active_subset = active_candidates[:max_items] completed_slots = max(0, max_items - len(active_subset)) completed_subset = completed_curriculum_items[:completed_slots] items = completed_subset + active_subset ``` Комментарий над этим блоком (строки 271-273) буквально подтверждает механизм: «Active candidates take priority over completed cards — drop accumulated completions first if the section would otherwise overflow.»
  - `app/daily_plan/plan.py:412-415` — `build_optional(...)` в проде вызывается без `max_items`, то есть `max_items=15` во всех продакшн-путях (не тестовый override).
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-057.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — расхождение между докстрингом `get_curriculum_lessons_completed_today` (обещает персистентность completed-карточек) и логикой распределения слотов в `build_optional` (приоритет active над completed). В CLAUDE.md данный контракт optional-очереди не описан отдельно от общего «day_secured зависит только от required», поэтому формально не нарушает документированный в CLAUDE.md инвариант — расхождение внутрикодовое.

#### DP-040 · P2 · `app/daily_plan/items/curriculum.py:551-552`

- **Кандидат:** `DP-C-058` · линзы-источники: ITEMS-A-07 · скептик: `skeptics/DP-C-058.md`
- **Симптом:** нерезолвящийся модуль: очередь fail-open (`return True`), спайн fail-closed — противоположные дефолты
- **Сценарий отказа:** асимметрия дефолтов подтверждена буквальным чтением трёх мест кода: очередь (`fail-open`, строка 551-552) расходится и со спайном (`fail-closed` через `continue`, progression.py:140-149), и с реальным роутовым гейтом, который она обязана реплицировать (`fail-closed`, security.py:236-237). Сценарий вход→неверный выход: `Lessons`-строка, чей `module_id` не резолвится в существующий `Module` (относительно `lesson.module`) — очередь включает такой урок в «Дальше по курсу» с рабочим на вид URL, клик по которому 403/редиректит на реальном гейте (`check_module_access` fail-closed). Оговорка: `Lessons.module_id` — `nullable=False` FK с `ondelete='CASCADE'` (models.py:216), поэтому в нормальной работе через ORM БД не даёт создать осиротевшую строку, и мой read-only доступ (нет запущенного `learn_db_prod` контейнера в этой сессии) не позволил проверить, есть ли такие строки в реальных данных сейчас. Но сама кодовая база (лог-предупреждение в спайне, defensive-паттерн в `Lessons.input_mode`) трактует этот случай как достижимый, а не чисто гипотетический — асимметрия дефолтов остаётся реальным логическим дефектом независимо от текущего состояния БД.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/items/curriculum.py:551-552`: ```python if module is None: return True ``` — если `lesson.module` (ORM-relationship) не резолвится, `_module_accessible_for_user` считает урок **доступным** и добавляет его в очередь «Дальше по курсу» (`build_curriculum_queue`, 672-717) с кликабельным `url=_lesson_url(lesson)` (280-284, `/learn/<id>/`).
  - `app/daily_plan/linear/progression.py:139-149`: ```python module = db.session.get(Module, module_id) if module is None: logger.warning( "linear_progression user=%s lesson=%s has unresolvable module=%s — skipped", user_id, lesson.id, module_id, ) continue ``` — спайн (`find_next_lesson_state`) в этом же случае урок полностью пропускает: он никогда не становится `required`-элементом. Fail-closed по эффекту (урок не выдаётся).
  - `app/curriculum/security.py:235-237` — реальный роутовый гейт, на который ведёт клик по `_lesson_url`: ```python module = Module.query.get(module_id) if not module: return False ``` — fail-closed: 403/redirect (см. `CLAUDE.md`: «HTML → flash+redirect; API → 403 JSON»).
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-058.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — сам `_module_accessible_for_user` описан в докстринге как реплика `check_module_access`, но её собственная ветка `module is None` этому докстрингу противоречит.

#### DP-041 · P2 · `app/daily_plan/snapshot.py:233`

- **Кандидат:** `DP-C-063` · линзы-источники: ITEMS-B-01 · скептик: `skeptics/DP-C-063.md`
- **Симптом:** `overlay_completion` не обновляет `data`: числа required-SRS заморожены на день, прогресс «X из N карточек» не рендерится
- **Сценарий отказа:** сценарий вход→неверный выход: юзер открывает дашборд первый раз за день (снапшот строится, `reviews_today=0`, `new_today=0` на момент сборки → закэшировано в `DailyPlanLog.plan_json`); идёт на `/study` и проходит, скажем, 12 из 24 карточек; возвращается на дашборд. `overlay_completion` пересчитывает только `completed` (через `is_srs_slot_completed_today`, живая функция) — слот остаётся `current` (не завершён, т.к. XP-событие слота ещё не набрано), а `data.reviews_today`/`new_today` в отданном payload — по-прежнему `0` из закэшированного снапшота. В шаблоне `_srs_done = 0` → условие `_srs_done > 0` ложно → блок `plan-item__slot-progress-caption` («12 из 24 карточек») не рендерится вообще, несмотря на реально пройденные 12 карточек. Это расходится с явным замыслом кода (`_srs_goal_total`: «X из 30» подразумевает живой X) — заморожен не только знаменатель, как задумано, но и числитель, чего код не предполагал.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/snapshot.py:228-230` — докстринг `overlay_completion` прямым текстом: «Other fields (id, kind, title, subtitle, lesson_type, **data**, completion_signal) are passed through unchanged.» — то есть неполнота `data` не побочный эффект, а описанное, но не осмысленное до конца поведение.
  - `app/daily_plan/snapshot.py:233-238` — тело функции: `merged = dict(item)` копирует снапшот-item, затем правится только `merged['section']`, `merged['completed']`, `merged['eta_minutes']`, `merged['url']`. `merged['data']` нигде не переприсваивается.
  - `app/daily_plan/plan_builder.py` (`_srs_item_dict`) — комментарий: «Freeze the daily SRS goal so "X из 30" stays "30" all day rather than tracking the shrinking live `total_show`» — то есть *задумано* держать неизменным только знаменатель (`goal_total`), а числитель (`reviews_today`+`new_today`) должен отражать живой прогресс за день.
  - `app/daily_plan/snapshot.py` (`resolve_snapshot_for_today`) — снапшот строится один раз в день и кэшируется в `DailyPlanLog.plan_json`; при повторных запросах в тот же день возвращается `existing` без повторного вызова `build_srs_item` — то есть `data.reviews_today`/`new_today` фиксируются на моменте первой сборки (обычно 0, если юзер ещё не проходил карточки).
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-063.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — сам себе противоречит: комментарий в `plan_builder.py` описывает намерение «живой числитель / замороженный знаменатель», а `overlay_completion` (по собственному докстрингу) не обновляет `data` вовсе, из-за чего числитель тоже застывает.

#### DP-042 · P2 · `app/daily_plan/linear/xp.py:302`

- **Кандидат:** `DP-C-064` · линзы-источники: ITEMS-B-02, ITEMS-D-15 · скептик: `skeptics/DP-C-064.md`
- **Симптом:** «строгий» гейт `srs:deck_quiz` читает ключ `linear_srs_global`, который пишет обычная SRS-сессия → required-квиз закрывается без квиза
- **Сценарий отказа:** сценарий вход→неверный выход: 1. Первый required-урок дня — карточный (`type in {card, flashcards}`) → snapshot фиксирует required `srs:deck_quiz` (`plan_builder.py:95`). 2. У юзера есть слова в колодах (`deck_word_count>0`) → deck-quiz показывается как невыполненный, но optional параллельно предлагает «Повторение слов» (`srs:global`, `/study/cards?source=linear_plan&from=linear_plan&slot=srs`) как «extra reps» (`plan.py:298-302`). 3. Юзер игнорирует deck-quiz и вместо этого проходит обычную SRS-сессию по optional-ссылке (например, добивает due-карточки). `complete_session` признаёт её «linear-plan SRS» и вызывает `maybe_award_srs_global_xp` → пишет `StreakEvent(details={'source':'linear_srs_global'})`. 4. При следующей отдаче плана `_is_item_completed('srs:deck_quiz')` → `is_srs_slot_completed_today(..., allow_fallback=False)` находит этот же `StreakEvent` по ключу `'linear_srs_global'` и возвращает `True` — required-слот «Квиз по словам из колод» помечается закрытым, хотя `/study/quiz/linear-plan` ни разу не открывался. Комментарий в коде (`is_srs_slot_completed_today` docstring, `xp.py:284-288`) описывает защиту только от counting-фолбэка через парный карточный урок («…поднимает парный curriculum card-урок…»), но не учитывает, что сам optional `srs:global`-путь пишет идентичный XP-source и обходит «strict event-only» гейт тем же легальным способом.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/xp.py:297-307` — `is_srs_slot_completed_today` сначала (независимо от `allow_fallback`) проверяет `StreakEvent.details['source'].astext == 'linear_srs_global'`; `if has_event: return True` стоит ДО `if not allow_fallback: return False`. Т.е. `allow_fallback=False` отключает только counting-фолбэк ниже, но не сам event-чек по общему ключу.
  - `app/daily_plan/items/srs.py:57` — required-слот deck-quiz зовёт именно `is_srs_slot_completed_today(user_id, db, allow_fallback=False)`; `app/daily_plan/snapshot.py:260-264` использует тот же вызов на каждой отдаче плана.
  - `app/daily_plan/plan_builder.py:95` — при `first_is_card=True` required получает `srs_item = _srs_item_dict(user_id, db, as_deck_quiz=True)` → id `srs:deck_quiz`.
  - `app/daily_plan/plan.py:298-302` — optional-кандидат `kind == 'srs'` строится через `build_srs_item(user_id, db, section='optional', ignore_daily_budget=graduated)` — **без** `as_deck_quiz`, т.е. всегда обычный `srs:global`. `seen_ids` берётся из `required_items` (id `srs:deck_quiz`), поэтому `srs:global` не дедупится и остаётся в optional как «extra reps» (соответствует комментарию в CLAUDE.md).
  - _(ещё 4 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-064.md`; здесь список усечён по бюджету, а не по значимости)_
- **Второй проход (три независимые линзы):** correctness=SOUND · reproducibility=REPRODUCIBLE · user-impact=P2 → P1 → P2. P1→P2: гейт действительно не отличает происхождение `linear_srs_global`, но это пере-начисление с обходом, без потери XP/streak/данных; ~18% юзеров с колодами × ~11% дней с карточным уроком.
- **Где расхождение:** код — раздел CLAUDE.md «SRS deck-quiz подмена» заявляет «required-SRS подменяется на deck-quiz… С обычным srs:global в required optional-дубль схлопывается. У юзеров с колодами optional srs:global остаётся как extra reps (id отличается от srs:deck_quiz)» — документ не упоминает, что этот «extra reps» item фактически способен закрыть required deck-quiz за счёт общего XP-ключа, что противоречит цели свопа («так daily plan предлагает vocabulary-review активность без буквального повтора карточек дважды», `app/daily_plan/items/srs.py:36-45`).

#### DP-043 · P2 · `app/daily_plan/items/srs.py:203`

- **Кандидат:** `DP-C-066` · линзы-источники: ITEMS-B-04 · скептик: `skeptics/DP-C-066.md`
- **Симптом:** тир critical/collapse + чисто REVIEW-бэклог → `total_show=0`, слот исчезает молча, объясняющий hint гейтится `total_show>0`
- **Сценарий отказа:** механизм воспроизводим по коду без предположений о недостижимых ветках. Сценарий вход→выход: пользователь с accuracy < 45% (tier=`collapse`), у которого весь текущий due-бэклог сидит в состоянии REVIEW (нет NEW/LEARNING due), сегодня ещё не открывал SRS. Ожидаемый корректный выход — слот в `required`/`optional` с `title` вида «Повторение слов — N» и, при желании, hint про collapse-тир. Фактический выход — SRS-слот отсутствует и в `required`, и в `optional` daily-plan payload'а; поле `data.reason_hint` не существует, потому что PlanItem не создаётся; независимое поле `srs_limit_reason` в API есть, но нигде не рендерится; прямой заход на `/study/cards` тоже отдаёт «дневной лимит исчерпан» без обхода. Итог — реальный бэклог ревью полностью невидим и недостижим через штатный UI в этот день, что усугубляет позиционный застой пользователя, для которого collapse-тир как раз задуман как временная защита с последующим восстановлением.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/study/services/srs_service.py:197-202` — `TIER_PCT['collapse'] = {'new': 0.00, 'review': 0.00}`; `_compute_adaptive_state` (строки 424-444) на collapse даёт `adaptive_reviews = round(base_reviews * 0.0) = 0`.
  - `app/srs/counting.py:127-134` — `get_new_card_budget` возвращает `remaining_reviews = max(0, adaptive_reviews - rev_today)`. При `adaptive_reviews=0` это `0` **независимо** от `rev_today` (свежий день или нет).
  - `app/daily_plan/items/srs.py:178-183`: ``` remaining_new, remaining_reviews = get_new_card_budget(user_id, db) due_budget = get_due_card_budget(user_id, db) new_show = min(new_pending, remaining_new) learning_show = min(learning_due, due_budget) review_show = min(review_due, max(0, due_budget - learning_show), remaining_reviews) total_show = new_show + learning_show + review_show ``` При чистом REVIEW-бэклоге (`new_pending=0`, `learning_due=0`, `review_due>0`) на tier=`collapse`: `new_show=0`, `learning_show=0`, `review_show=min(review_due, due_budget, 0)=0` → `total_show=0` гарантированно, вне зависимости от размера реального бэклога.
  - _(ещё 6 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-066.md`; здесь список усечён по бюджету, а не по значимости)_
- **Второй проход (три независимые линзы):** correctness=PARTIAL · reproducibility=REPRODUCIBLE · user-impact=P2 → P1 → P2. P1→P2. Формулировку править: отказ даёт только тир `collapse` (у `critical` бюджет ненулевой при реальных `reviews_per_day` 20–50), а гейт `total_show>0` на :203 — не причина молчания, до него исполнение не доходит (ранний `return None` на :191). Затронут 1 из 12 юзеров прод-снимка.
- **Где расхождение:** код — расхождение внутри самого кода: комментарий `get_due_card_budget` в `app/srs/counting.py` формулирует цель «bounded-but-nonzero batch» для collapse-тира, но комбинация с `remaining_reviews` в трёх местах (`items/srs.py`, `linear/slots/srs_slot.py`, `linear/xp.py`) эту цель систематически аннулирует.

#### DP-044 · P2 · `app/daily_plan/plan_builder.py:200`

- **Кандидат:** `DP-C-070` · линзы-источники: ITEMS-B-08 · скептик: `skeptics/DP-C-070.md`
- **Симптом:** гейт на пустые колоды применяется только при сборке снапшота: очистка колод в течение дня оставляет замороженный required `srs:deck_quiz` незакрываемым (якорь кандидата — `app/study/game_routes.py:207` — перенесён, см. «Сценарий отказа»)
- **Сценарий отказа:** механизм есть, но не там, где указывает якорь. `/study/quiz/linear-plan` (`game_routes.py:204-241`) сам по себе безопасен: он не гейтит пустые колоды, но и не обязан — 500 не бросает, живой `get_quiz_questions` корректно отдаёт `status:error` при нуле слов, и фронт показывает дружелюбное сообщение вместо зависшего спиннера. Настоящая дыра — в контракте «заморозить на весь день»: `_srs_item_dict` проверяет `_count_user_deck_quiz_words > 0` только один раз, при сборке снапшота в полночь; `overlay_completion`/`_is_item_completed` для `srs:deck_quiz` эту проверку никогда не повторяет, только смотрит на StreakEvent. Сценарий: юзер А, у которого сегодняшний первый урок спайна — карточный (`type in {'card','flashcards'}`) и есть ≥1 слово в колодах на момент полуночной сборки плана → required получает `srs:deck_quiz` с живым URL. В течение дня юзер удаляет слово/колоду через `POST /my-decks/<id>/words/<id>/delete` или `POST /my-decks/<id>/delete` (реальные роуты, не гипотетические) до того, как открыл квиз. Клик по замороженному URL → `/study/api/get-quiz-questions?source=linear_plan_deck_quiz` возвращает 0 вопросов → квиз никогда не может завершиться → `is_srs_slot_completed_today(..., allow_fallback=False)` остаётся False весь день → `_compute_unified_item_completion` даёт `False` для этого id → `compute_day_secured_from_activity` требует ALL required completed → `day_secured` не наступает в этот день независимо от прочей активности юзера (streak/perfect-day/ранг подвешены). Обход технически существует (добавить в любую колоду хотя бы одно слово с валидным переводом до клика по квизу восстанавливает count>0 и разблокирует сдачу), но он не очевиден пользователю и не подсказывается UI — отсюда `P2`, а не `P1`.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/snapshot.py:1-16` — «freezes full item dicts (id, kind, title, url, eta, data, completion_signal) at user-local midnight... Required composition is fixed for the day; only `completed` is overlaid live».
  - `app/daily_plan/plan_builder.py:200-219` (`_srs_item_dict`) — гейт на пустые колоды применяется **только на момент сборки снапшота**: `if as_deck_quiz: ... if _count_user_deck_quiz_words(user_id, db) <= 0: as_deck_quiz = False`. Если на момент полуночи слов ≥1, `as_deck_quiz` остаётся True и в снапшот замораживается item с id `srs:deck_quiz` и живым `url`.
  - `app/daily_plan/items/srs.py:99-114` (`_build_deck_quiz_plan_item`) — при `deck_word_count>0` строит `PlanItem(id='srs:deck_quiz', completed=False, url=build_slot_url('/study/quiz/linear-plan?...&limit=<N>', ...))`. Этот словарь и уходит в замороженный снапшот.
  - `app/daily_plan/snapshot.py:258-263` (`_is_item_completed`) — для `item_id == 'srs:deck_quiz'` overlay проверяет **только** `is_srs_slot_completed_today(user_id, db, allow_fallback=False)`; счётчик `_count_user_deck_quiz_words` здесь не перечитывается вообще.
  - `app/study/deck_routes.py:151` и `:274` — реальные роуты `POST /my-decks/<id>/delete` и `POST /my-decks/<id>/words/<id>/delete`, которыми юзер может обнулить свои колоды в течение дня после полуночной сборки снапшота.
  - _(ещё 6 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-070.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — раздел CLAUDE.md «SRS deck-quiz подмена» описывает гейт `_count_user_deck_quiz_words > 0` как достаточную защиту от «мёртвой заглушки», но не оговаривает, что снапшот замораживает решение на весь день без повторной проверки при overlay — расхождение между документированным намерением (гейт защищает от пустого квиза) и фактическим поведением (гейт разовый, не переживает внутридневное изменение состояния колод).

#### DP-045 · P2 · `app/daily_plan/items/srs.py:196`

- **Кандидат:** `DP-C-073` · линзы-источники: ITEMS-B-11 · скептик: `skeptics/DP-C-073.md`
- **Симптом:** `ignore_daily_budget` печатает в заголовке весь бэклог, которого сессия не выдаст
- **Сценарий отказа:** механизм в коде есть и воспроизводится чтением: `build_srs_item` при `ignore_daily_budget=True` намеренно печатает бюджет-неограниченный бэклог (`raw_backlog + new_pending`), а фактическая выдача карточек в `get_study_items` бюджет всегда применяет и никакого эквивалентного `ignore_daily_budget`-обхода не имеет — сам код `get_study_items` документирует инвариант синхронизации с плиткой, который эта ветка нарушает. Эффект наступает не при любом заходе в эту ветку (если бюджет исчерпан именно через сам `linear_plan/srs` вход, `completed_today` уже станет True и ветка не сработает), а когда бюджет исчерпан через ДРУГОЙ study-surface, использующий те же глобальные счётчики, — это не гипотетика, а прямое следствие того, что `count_new_cards_today`/`count_reviews_today` в `app/srs/counting.py` не фильтруются по source/slot.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/items/srs.py:189-196` — при `total_show<=0 and not completed_today` и `ignore_daily_budget=True`: `raw_backlog = learning_due + review_due; total_show = raw_backlog + new_pending # ignore budgets`. `learning_due`/`review_due` — уже посчитаны БЕЗ бюджета (`count_due_by_states`, строки 175-178), `new_pending` — весь пул NEW-карточек (`count_pending_new`, `app/srs/counting.py:190-213`), тоже без бюджета.
  - `app/daily_plan/items/srs.py:232-234` — заголовок `f'Повторение слов — {total_show}'` печатает это ничем не урезанное число.
  - `app/daily_plan/items/srs.py:262` — URL слота `build_slot_url('/study/cards?source=linear_plan', LinearSlotKind.SRS)` → `?from=linear_plan&slot=srs`, т.е. сессия открывается именно на `/study/cards`.
  - _(ещё 4 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-073.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — `get_study_items` документирует комментарием инвариант «tile count и served queue synced by the same due_budget/new cap», `build_srs_item` его для `ignore_daily_budget=True` явно нарушает (не в CLAUDE.md, а внутри самого кода).

#### DP-046 · P2 · `app/api/daily_plan.py:1010`

- **Кандидат:** `DP-C-076` · линзы-источники: ITEMS-C-02 · скептик: `skeptics/DP-C-076.md`
- **Симптом:** грейдер «Повтори 3 фразы»: пустой ответ засчитывается верным и закрывает `QuizErrorLog`
- **Сценарий отказа:** механизм воспроизведён на реальном коде функции. Сценарий: у пользователя есть нерешённая `QuizErrorLog`-запись A1/A2, чей `correct_answer` — фраза без букв `w`/`s` (например «I love you», «Good morning», «Nice to meet you» и т.п. — распространённый класс английских фраз). Пользователь открывает `/learn/phrase-review/`, отправляет `POST /api/daily-plan/phrase-review/complete` с пустым (или из одних цифр/знаков) ответом на этот пункт. Из-за сломанного regex (`\\w`/`\\s` вместо `\w`/`\s` в raw-строке) оба — пустой ввод и правильная фраза — нормализуются в `''`, `is_correct=True`, ошибка помечается решённой без реальной проверки знания. Баг не привязан к пустому вводу как таковому — сработает на ЛЮБОЙ строке, чья нормализация совпадёт с `''` (пунктуация, цифры), но пустой ответ — тривиальный воспроизводимый случай, ровно как в формулировке кандидата. Severity — P2, не P1: активность необязательная (`section='optional'`, не входит в `required`/`day_secured`), XP за неё не начисляется (только `DailyPlanEvent` + `resolve_quiz_error`), обязательные сценарии (стрик, ранги, закрытие дня) не затронуты. Эффект — тихая порча данных error-review (ошибка помечается решённой без реального разбора) без обхода со стороны пользователя (баг срабатывает независимо от его действий, если ему не повезло с фразой) — это «дыра в гарантиях/расхождение контракта» уровня P2, а не потеря/порча пользовательских данных в P0-смысле и не поломка ключевого сценария в P1-смысле.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:1010` — `value = re.sub(r"[^\\w\\s']", '', str(value or '').casefold())`. Строка **raw**, поэтому `\\w`/`\\s` в исходнике — это два литеральных бэкслеша + буква, а не классы `\w`/`\s`. `re` разбирает получившийся паттерн `[^\\w\\s']` как отрицание набора символов `{\, w, s, '}` (экранированный бэкслеш = буквальный `\`, дальше буквальные `w`, `\`, `s`, `'`). Это **не** «оставить буквы/цифры/пробелы», а «оставить только буквы `w`, `s`, апостроф и бэкслеш» — пробелы и почти все остальные буквы вырезаются.
  - Фактический прогон реальной функции файла: ``` f('Hello world') -> 'w' f('I love you') -> '' f('Good morning') -> '' f('thank you very much') -> '' f('He is happy') -> 's' f('') -> '' ``` Любая фраза без буквы `w` и `s` (без учёта регистра) нормализуется в пустую строку `''` — ровно как пустой ответ.
  - `app/api/daily_plan.py:1037-1041`: ```python answer = answers[index] if index < len(answers) else '' accepted = item.get('accepted_answers') or [item.get('answer', '')] is_correct = _normalise_phrase_answer(answer) in { _normalise_phrase_answer(candidate) for candidate in accepted } ``` Если правильный ответ (`item['answer']`) — фраза без `w`/`s` (например `"I love you"`, `"Good morning"`), множество нормализованных `accepted` содержит `''`. Пустой/отсутствующий пользовательский ответ нормализуется тоже в `''` → `is_correct = True`.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-076.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-047 · P2 · `app/daily_plan/items/phrase_review.py:20`

- **Кандидат:** `DP-C-077` · линзы-источники: ITEMS-C-03 · скептик: `skeptics/DP-C-077.md`
- **Симптом:** та же регексп как ключ дедупа схлопывает 200 фраз в 35 корзин — карточка выдаёт 1–2 задания вместо 3
- **Сценарий отказа:** механизм найден и воспроизведён на реальных данных прода. Вход: список кандидатов (ошибки/фразы из пройденных A1/A2-модулей), среди которых есть ≥3 РАЗНЫХ по смыслу фразы, но ≤2 из них имеют разные `_normalise()`-значения (что статистически часто, т.к. всего ~10 корзин на 35 фраз в измеренной выборке). Неверный выход: `get_phrase_review_items` возвращает 1–2 элемента вместо 3 (`_error_candidates`/`_recent_module_candidates` обрывают набор кандидатов по «дублю», хотя фразы текстуально различны), а `build_phrase_review_item` (`phrase_review.py:203`) всё равно рисует заголовок «Повтори 3 фразы» независимо от фактического `len(items)`.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/items/phrase_review.py:20` — `value = re.sub(r"[^\\w\\s']", '', str(value or '').casefold())`. Строка **raw** (`r"..."`), поэтому `\\w`/`\\s` — это не regex-шорткаты «слово/пробел», а буквально экранированный символ `\` + буква `w` / буква `s`. Итоговый негированный класс `[^\\w\\s']` вычисляется как «убрать все символы, КРОМЕ backslash, буквы `w`, буквы `s` и апострофа» — пробелы, цифры, все остальные буквы (включая гласные, согласные кроме w/s) тоже удаляются.
  - `app/daily_plan/items/phrase_review.py:96,99` (`_error_candidates`) и `:147,150` (`_recent_module_candidates`) и `:162,164,167` (`get_phrase_review_items`) — все три места используют ОДНУ И ТУ ЖЕ `_normalise` как ключ множества `seen_answers`/`seen`, с ранним `break` при достижении `PHRASE_REVIEW_SIZE=3`.
  - Прямой прогон реальной функции `app.daily_plan.items.phrase_review._normalise` (не копии) на 35 реальных фразах из `lessons.content` (A1-модули `home_and_furniture`, `greetings`, `perevod`, `learn_db_prod`, id уроков 16/124/214) дал **всего 10 различных корзин** из 35 usable-фраз, причём одна корзина (`'s'`) содержит 11/35 фраз, другая (`'ss'`) — 8/35. Пример: `'My name is Anna'`, `'I am a student'`, `'I am not busy'` → все нормализуются в `'s'` и считаются дубликатами друг друга.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-077.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — баг локален файлу `phrase_review.py`, не описан ни в одном инварианте CLAUDE.md; расхождения с CLAUDE.md нет, но само поведение (заголовок обещает 3, код может отдать 1) — расхождение контракта UI/данных внутри самого модуля. **Severity:** предлагаю **P2**, а не P0/P1: `phrase_review` — опциональный (`section='optional'`) пункт, не участвует в `day_secured` (который зависит только от `required`), не трогает XP/streak/ранги. Эффект — заметно неверное количество заданий (1–2 вместо 3) без потери данных и без блокировки ключевого сценария; обхода для пользователя нет, но и критичности P1/P0 (порча данных, недостижимый обязательный пункт, дыра в доступе) — тоже нет.

#### DP-048 · P2 · `app/daily_plan/items/challenge.py:81`

- **Кандидат:** `DP-C-080` · линзы-источники: ITEMS-C-07 · скептик: `skeptics/DP-C-080.md`
- **Симптом:** карточка челленджа ведёт на урок, тип которого в 44 % случаев не может выполнить критерий
- **Сценарий отказа:** механизм воспроизводим по коду без допущений о состоянии. Сценарий: сегодня категория `accuracy_focus` (день, для которого `challenge_date.toordinal() % 3 == 1`); следующий урок пользователя на спайне — `type='grammar'` (или `vocabulary`/`reading`/`writing_prompt`/`shadow_reading`/`card`/`listening_immersion`, ~44% уроков спайна). Карточка челленджа (`app/daily_plan/items/challenge.py:81-82`) строит URL именно на этот урок. Пользователь проходит урок на 100% — `LessonProgress`/`LessonAttempt` пишется, но `check_challenge_criteria` (`app/daily_plan/challenge.py:266-288`) фильтрует по `Lessons.type.in_(_ACCURACY_FOCUS_GRADED_TYPES)`, куда `grammar` не входит → `criteria_not_met` → `maybe_auto_complete_challenge` возвращает `None`, бонус-XP (60 для accuracy_focus / 50 для speed_run) не начисляется, `is_completed` в следующей загрузке плана остаётся `False`. Обход есть (тем же днём выполнить другой урок оцениваемого типа — критерий не привязан к конкретному `lesson_id` для этих двух категорий), но карточка не предупреждает и не подсказывает это — пользователь, сделавший ИМЕННО показанный урок, тихо не получает заявленный бонус.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/challenge.py:32-37` — `_seed_today_challenge` всегда создаёт `DailyChallenge` с `lesson_id: Optional[int] = None` (единственное место создания `DailyChallenge` в кодовой базе — `grep "DailyChallenge("` не находит других конструкторов). Значит `info.get('lesson_id')` в билдере **всегда** `None`, ветка ниже — не fallback на редкий случай, а единственный исполняемый путь.
  - `app/daily_plan/items/challenge.py:61-79` — для `category in {speed_run, accuracy_focus}` (ветка `else` на строке 75-76): `lesson_id = next_lesson.id`, где `next_lesson = find_next_lesson_linear(user_id, db)` — **без фильтра по типу урока**. `find_next_lesson_linear` (`app/daily_plan/linear/progression.py:44-54`) отдаёт буквально следующий незавершённый урок спайна `(CEFRLevel.order, Module.number, Lessons.number)`, любого типа.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-080.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — комментарий в `app/daily_plan/items/challenge.py:58` («speed_run / accuracy_focus → the user's next curriculum lesson») декларирует политику как есть, но не учитывает, что `check_challenge_criteria` фильтрует по типу; расхождение внутреннее (комментарий/намерение файла vs фактическая проверяемость), не с CLAUDE.md.

#### DP-049 · P2 · `app/daily_plan/snapshot.py:192`

- **Кандидат:** `DP-C-083` · линзы-источники: ITEMS-C-13 · скептик: `skeptics/DP-C-083.md`
- **Симптом:** перенесённый снапшот тащит вчерашний подзаголовок «Норма дня — N мин»
- **Сценарий отказа:** механизм найден и воспроизводится по коду без дополнительных данных. Сценарий: пользователь строит план в нечётный день месяца (например, 27-е) — свежий `build_reading_item` пишет `subtitle='Норма дня — 5 мин'`, `eta_minutes=5`, `data.gate_seconds=300`. За весь день 27-го активности нет (`has_learning_activity=False`). На 28-е (чётный день, целевая норма меняется на 600с/10мин) `resolve_snapshot_for_today` находит валидный снапшот за 27-е с непустыми items и копирует его вербатим в снапшот на 28-е (`snapshot.py:191-197`). Пользователь открывает план 28-го и видит «Норма дня — 5 мин» и «осталось ~5 мин», хотя реальный гейт (`_read_today`→`is_daily_reading_target_met_today`, вызываемый с сегодняшней датой 28-го) требует уже 10 минут. Пользователь читает 5 минут, ожидая закрытия слота согласно подписи, — слот не закрывается, `day_secured` не наступает по этому пункту, пока не будет прочитано ещё 5 минут. Обход есть (можно дочитать до реального порога), данные не портятся, гонки нет — заметное расхождение отображаемого текста и фактического требования, воспроизводимое каждый раз, когда roll-over срабатывает на стыке дней с разной чётностью (то есть практически при каждом срабатывании roll-over).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/books/reading_session.py:48-62` — `get_daily_reading_target_seconds(today)` чередует норму **по чётности дня месяца**: `return DAILY_READING_TARGET_SECONDS if today.day % 2 == 1 else DAILY_READING_TARGET_SECONDS_LONG` (5 мин на нечётных, 10 мин на чётных числах). Значение зависит от даты и меняется КАЖДЫЙ день (чётность гарантированно флипается при переходе на следующий день).
  - `app/daily_plan/items/reading.py:161-180` — при сборке item'а норма читается на момент постройки: `today_target_seconds = get_daily_reading_target_seconds(get_user_local_date(user_id, db))`, дальше `target_minutes = today_target_seconds // 60` и `subtitle_parts.append(f'Норма дня — {target_minutes} мин')`; `eta_minutes=target_minutes` тоже заморожен в item.
  - `app/daily_plan/snapshot.py:150-197` (`_try_rollover_from_yesterday`) — при откате копирует items **дословно**: `'items': list(y_snap['items'])`, не вызывая `build_reading_item` заново. Дата в снапшоте (`'date': today_local.isoformat()`) обновляется, а вложенные поля item'ов (`subtitle`, `eta_minutes`, `data.gate_seconds`) — нет.
  - `app/daily_plan/snapshot.py:213-231` (`overlay_completion`) — трогает только `completed`/`section`/`eta_minutes` (обнуляет при completed)/`url`; `subtitle` передаётся как есть (`merged = dict(item)`), не пересобирается.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-083.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — `CLAUDE.md` не описывает эту 5/10-альтернацию reading-таргета явно (упомянут только `DAILY_READING_TARGET_SECONDS=300` как «единственное условие»), но код `app/books/reading_session.py` содержит более позднюю логику чередования, которую снапшот-рефриз (`snapshot.py`) не учитывает.

#### DP-050 · P2 · `app/curriculum/routes/grammar_quiz_lessons.py:312`

- **Кандидат:** `DP-C-086` · линзы-источники: ITEMS-D-03 · скептик: `skeptics/DP-C-086.md`
- **Симптом:** гейт XP — липкий `status == 'completed'`, не `passed`: проваленная пересдача начисляет XP и закрывает required-слот
- **Сценарий отказа:** сценарий: юзер прошёл `final_test`-урок X в день 1 (score≥passing, `progress.status='completed'`, XP уже начислен). В день 2 юзер открывает тот же урок повторно (прямой URL, retry не запрещён вне 24ч-лимита неудачных попыток) и проваливает (`score=0`). `update_progress_with_grading` НЕ понижает `status` (он и так был `'completed'`), значит `if progress.status == 'completed'` в роуте истинно → `maybe_award_curriculum_xp(..., score=0)` вызывается впервые за день 2 → `award_linear_slot_xp_idempotent` не дедуплицирует (для дня 2 записи ещё нет) → `award_xp` начисляет `max(1, round(base*0.5*multiplier))` XP за проваленный тест → пишется `StreakEvent(event_type='xp_linear', event_date=день2, details.source='linear_curriculum_final_test')`. На следующем вызове `get_daily_plan`/`compute_plan_steps` в день 2 `_curriculum_done_today` находит этот `StreakEvent` и возвращает `True` ДО проверки score → `build_curriculum_item` отдаёт required curriculum-пункт с `completed=True`, даже если настоящий «следующий» урок спайна в день 2 юзером не тронут. Итог: провальная пересдача старого урока и начисляет XP, и закрывает required curriculum-слот дня — оба эффекта из формулировки кандидата воспроизводятся по коду. Паттерн идентичен во всех 5 XP-гейтах файла (grammar/quiz/final_test/matching/…), не только в `final_test`.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/curriculum/services/progress_service.py:283-287`: ``` if progress: was_completed = progress.status == 'completed' _set_attempt_scores(progress, score) if not was_completed: progress.status = 'completed' if is_completed else 'in_progress' ``` Если урок уже был `completed` в прошлом (`was_completed=True`), `status` НЕ понижается до `in_progress` при провальной пересдаче (`is_completed=False`) — остаётся `'completed'`.
  - `app/curriculum/routes/grammar_quiz_lessons.py:307` (аналогично 697 для final_test): ``` if progress and progress.status == 'completed': ... maybe_award_curriculum_xp(current_user.id, lesson, db_session=db, score=result.get('score')) ``` Условие читает только `progress.status`, не `result.get('score') >= passing_score` и не `completion_result`.
  - `app/achievements/xp_service.py:345`: `awarded = max(1, round(effective_base * multiplier))` — даже при `score=0` начисляется минимум 1 XP (пол-базы: `effective_base = base*(0.5+0/200)=base*0.5`, дальше `max(1, ...)`).
  - `app/daily_plan/linear/xp.py:36-58` — `LESSON_TYPE_TO_SOURCE['final_test'] = 'linear_curriculum_final_test'`, входит в `_CURRICULUM_XP_SOURCES = frozenset(LESSON_TYPE_TO_SOURCE.values())` (`app/daily_plan/items/curriculum.py:38`).
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-086.md`; здесь список усечён по бюджету, а не по значимости)_
- **Второй проход (три независимые линзы):** correctness=SOUND · reproducibility=REPRODUCIBLE · user-impact=P2 → P1 → P2. P1→P2: механизм верен и путь чисто через UI, но направление эффекта — переначисление 6–11 XP, а не потеря; дельта к штатному поведению мала, в проде 0 случаев из 210 попыток.
- **Где расхождение:** код — CLAUDE.md документирует `_curriculum_done_today` как «Primary: StreakEvent(xp_linear) from `maybe_award_curriculum_xp`. Fallback: any LessonProgress(completed)…», то есть сама по себе эта архитектура задокументирована и осознанна; расхождение — в том, что `maybe_award_curriculum_xp` может быть вызван для НЕуспешной попытки из-за липкого `status`, что нигде не описано и противоречит духу score-aware XP («score-aware» задумано штрафовать, а не открывать XP там, где его не должно быть вовсе — CLAUDE.md перечисляет final_test как graded source, обязанный «пробрасывать score», подразумевая гейтинг по score, а не просто по наличию `progress`).

#### DP-051 · P2 · `app/achievements/xp_service.py:232`

- **Кандидат:** `DP-C-087` · линзы-источники: ITEMS-D-04 · скептик: `skeptics/DP-C-087.md`
- **Симптом:** `award_perfect_day_xp_idempotent` — единственный XP-хелпер без savepoint/уникального индекса
- **Сценарий отказа:** механизм полностью соответствует формулировке: среди всех idempotent XP-хелперов проекта (`award_book_chapter_xp_idempotent`, `award_referral_xp_idempotent`, `award_game_xp_idempotent` — advisory lock; `award_linear_slot_xp_idempotent`, `award_curriculum_lesson_xp_idempotent` — savepoint + `IntegrityError` против уникального индекса) только `award_perfect_day_xp_idempotent` не имеет ни того, ни другого. Сценарий вход→неверный выход: пользователь одновременно закрывает два required-слота, оба запроса уходят на разные роуты (например `POST /api/daily-plan/error-review/complete` и сохранение SRS-сессии в `app/study/api_routes.py`), у обоих `compute_day_secured_from_activity(...) is True` на одну и ту же `for_date`. Обе транзакции (READ COMMITTED, отдельные сессии) выполняют `StreakEvent.query.filter_by(event_type='xp_perfect_day', event_date=today).first()` до коммита конкурента — обе видят `already=None`, обе вызывают `award_xp(...)` (двойной бонус XP, до `PERFECT_DAY_BONUS_XP_LINEAR * 2.5 * 2.0 = 125` каждая = 250 за день) и обе вставляют по строке `StreakEvent(event_type='xp_perfect_day', event_date=today)` — ничто в схеме БД это не блокирует. Итог: нарушается задокументированный контракт "Returns XPAward if awarded, None if already awarded today" (docstring :226) — бонус "once per day" выдаётся дважды, `consecutive_perfect_days` дважды инкрементируется на одно и то же значение относительно `probe`-дня. Ограничение: race требует буквально одновременного попадания двух транзакций в окно между SELECT и COMMIT (окно короткое — миллисекунды), но в отличие от гипотетических сценариев здесь есть прямой прецедент в той же кодовой базе: миграция `20260621_idempotency_constraints` была написана именно потому, что тот же паттерн (check-then-insert без индекса) реально проявлялся на `xp_linear` и `xp_curriculum_lesson` под конкурентными запросами — это не теоретическая, а наблюдавшаяся в проекте категория бага, которую почему-то не закрыли для `xp_perfect_day`.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/achievements/xp_service.py:232-238` — `award_perfect_day_xp_idempotent` делает голый check-then-insert: `StreakEvent.query.filter_by(user_id=..., event_type='xp_perfect_day', event_date=for_date).first()`, без `db.session.begin_nested()` и без последующего `except IntegrityError` — в отличие от `award_book_chapter_xp_idempotent` (:440, `_serialize_user_xp(db_obj, _LOCK_NS_BOOK_CHAPTER, user_id)`), `award_referral_xp_idempotent` (:491) и `award_game_xp_idempotent` (:543), которые все зовут `_serialize_user_xp` — `pg_advisory_xact_lock` на (namespace, user_id) — до check-then-insert.
  - `app/achievements/models.py:204-207` — `StreakEvent.__table_args__` содержит только два обычных (не unique) индекса `idx_streak_events_user_date`, `idx_streak_events_user_type`; уникального ограничения на `(user_id, event_type, event_date)` нет.
  - `migrations/versions/20260621_idempotency_constraints.py:3-7` — комментарий миграции прямо формулирует класс проблемы: "check-then-insert had no DB-level guard, unlike book/referral/game XP" — и добавляет частичные уникальные индексы `uq_streak_events_xp_linear_source`, `uq_streak_events_xp_curriculum_lesson` для `xp_linear`/`xp_curriculum_lesson`. Индекса для `xp_perfect_day` в репозитории нет (проверено `grep -rn "xp_perfect_day" migrations/`).
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-087.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md описывает race-safe паттерн (`begin_nested()` + `except IntegrityError`) как обязательный для write_secured_at и как реализованный для linear/curriculum XP, но не упоминает `award_perfect_day_xp_idempotent` вовсе — расхождение в самом коде между сиблинг-хелперами, а не между кодом и документом.

#### DP-052 · P2 · `app/daily_plan/linear/xp.py:216-225`

- **Кандидат:** `DP-C-089` · линзы-источники: ITEMS-D-06 · скептик: `skeptics/DP-C-089.md`
- **Симптом:** `add_study_minutes` — raceable check-then-insert против UNIQUE вне дедуп-savepoint'а; на IntegrityError сессия отравлена
- **Сценарий отказа:** механизм воспроизводим по коду. Сценарий: два конкурентных запроса одного юзера за один local-day, которые оба идут через `award_linear_slot_xp_idempotent` с разными `source` (например, один процесс кредитует `linear_error_review` через `POST /api/daily-plan/error-review/complete`, другой параллельно кредитует `linear_srs_global`/`linear_curriculum_*` через другой эндпоинт), оба проходят проверку `_already_awarded` (разные source → False), оба проходят свой собственный dedup-savepoint (разные source → нет конфликта по `uq_streak_events_xp_linear_source`), затем оба вызывают `add_study_minutes(user_id, when, ...)` — оба видят `row is None` (гонка на SELECT), один `INSERT` побеждает и коммитится/флашится первым, второй ловит `IntegrityError` на общем `(user_id, study_date)` индексе. Эта `IntegrityError` гасится `except Exception: logger.warning(...)` (xp.py:222-223) без `rollback()`, и следующий `db_obj.session.flush()` (xp.py:225) поднимает `PendingRollbackError`. Для вызова через `complete_error_review` (`app/api/daily_plan.py:963`) это исключение ничем не перехвачено → 500 конкретному пользователю, XP этого конкретного вызова и резолв error-ids этого запроса теряются (retriable — при повторной попытке гонки уже не будет, т.к. строка `daily_study_minutes` существует). Для путей через `lessons.py` эффект мягче (широкий `except Exception: db.session.rollback()` вокруг всего блока) — XP просто не засчитывается в этой попытке без 500, но факт «сессия отравлена» и «второй award теряется, хотя первый уже прошёл» подтверждён кодом в обоих случаях. Severity понижена с потенциального P1 до **P2**: воспроизводится только при реальной гонке двух XP-источников одного юзера в одну секунду (низкая вероятность при <10 активных пользователях — см. `product-stage-free-first`), не теряет данные безвозвратно (idempotency per-source сохраняется, retry лечит), и не у всех вызывающих путей даёт 500 — но там, где даёт (`complete_error_review`), это реальный необработанный 500 без отдельного покрытия тестами. Это классическая «гонка / отсутствующая атомарность (upsert)» — прямой пример P2 из брифинга.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/curriculum/models.py:699-721` — `add_study_minutes`: `SELECT ... WHERE user_id=... AND study_date=...` → если `row is None`, создаётся новая строка `DailyStudyMinutes(...)` и `db_session.session.flush()`. Между `SELECT` и `flush()`/`INSERT` нет блокировки и нет `begin_nested()`/upsert (`ON CONFLICT`) — классический check-then-insert. Уникальность держит только `Index('idx_daily_study_minutes_user_date', 'user_id', 'study_date', unique=True)` (`app/curriculum/models.py:691-693`), которая покрывает `(user_id, study_date)`, а не источник — т.е. ЛЮБЫЕ два конкурентных вызова `add_study_minutes` для одного юзера/дня (разные источники: quiz + srs + reading и т.д.) бьются в один и тот же индекс.
  - `app/daily_plan/linear/xp.py:180-211` — сама XP-запись (`award_linear_xp` + `StreakEvent` + `DailyPlanEvent`) уже обёрнута в `with db_obj.session.begin_nested(): ... except IntegrityError: return None` (строки 180, 212-214) — авторы явно знают паттерн «savepoint + IntegrityError» (тот же, что `write_secured_at`).
  - `app/daily_plan/linear/xp.py:216-223` — комментарий подтверждает осознанный вывод `add_study_minutes` за пределы этого savepoint'а: `# Accumulate study minutes for the day (best-effort, outside the dedup savepoint; not part of the uniqueness guarantee).` Вызов обёрнут в `try: ... except Exception: logger.warning(...)` — БЕЗ `db_obj.session.rollback()` в обработчике.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-089.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md документирует паттерн «race-safe insert через `begin_nested()` + `except IntegrityError`» как обязательный для write_secured_at/grant_achievement/survey claim, но `add_study_minutes` из этого паттерна сознательно выведен («best-effort, not part of the uniqueness guarantee») без учёта, что необработанный exception всё равно отравляет остаток сессии — сам код `xp.py:225` этому противоречит.

#### DP-053 · P2 · `app/daily_plan/items/curriculum.py:117-129`

- **Кандидат:** `DP-C-090` · линзы-источники: ITEMS-D-07 · скептик: `skeptics/DP-C-090.md`
- **Симптом:** два сигнала `_curriculum_done_today` с разными правилами: первичный не проверяет проходной балл, фолбэк проверяет
- **Сценарий отказа:** механизм найден и воспроизводится по коду для типов `grammar`/`quiz`/`final_test` (маршруты `grammar_quiz_lessons.py`). Сценарий: пользователь давно прошёл grammar-урок (score ≥ passing, `LessonProgress.status='completed'`, `completed_at`=старая дата). Сегодня он открывает `/lesson/<id>/grammar?retry=true` и отправляет заведомо неверные ответы. `update_progress_with_grading` пересчитывает `score`/`last_score`, но НЕ понижает `status` (sticky-логика), поэтому `progress.status == 'completed'` остаётся истинным → `maybe_award_curriculum_xp` вызывается с текущим (проваленным) `result['score']`, пишет НОВЫЙ `StreakEvent` на сегодняшнюю дату с `details.lesson_id` этого урока и начисляет (уменьшенный, но ненулевой) XP. Далее `_curriculum_done_today` видит этот `StreakEvent` и возвращает `True`; `get_curriculum_lessons_completed_today`/`_get_lesson_completed_today` подтягивают тот же урок как «пройден сегодня» — в `build_curriculum_item` (`app/daily_plan/items/curriculum.py:456-478`) обязательный слот плана дня рисует карточку этого урока с `completed=True`, хотя фактический результат сегодняшней попытки — провал. Fallback-ветка на этот же случай не сработала бы (она смотрит `LessonProgress.completed_at` в сегодняшнем окне, а `completed_at` при sticky-статусе не трогается — привязан к исходной дате прохождения), то есть асимметрия между двумя сигналами реальна и производит наблюдаемый неверный вывод. Оговорка: расхождение проявляется не при любом провале (первая попытка сегодня корректно гейтится — `is_completed` совпадает с `progress.status` при `was_completed=False`), а конкретно при ПОВТОРНОЙ попытке ранее пройденного урока в тот же/другой день — штатный, но не основной путь использования.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/items/curriculum.py:117-129` — primary-ветка `_curriculum_done_today` проверяет только факт существования `StreakEvent(event_type=LINEAR_XP_EVENT_TYPE, source in _CURRICULUM_XP_SOURCES)` за сегодня — score нигде не читается и не сверяется.
  - `app/daily_plan/items/curriculum.py:130-144` — fallback-ветка явно вызывает `_lesson_meets_passing(lesson, score)` для каждой строки `LessonProgress`, то есть заново проверяет проходной балл через `get_lesson_passing_score`.
  - `app/curriculum/services/progress_service.py:283-287`: ``` was_completed = progress.status == 'completed' _set_attempt_scores(progress, score) if not was_completed: progress.status = 'completed' if is_completed else 'in_progress' ``` Если урок уже был `completed` раньше, `progress.status` **не понижается** даже если текущая попытка провалена (`is_completed=False`).
  - `app/curriculum/routes/grammar_quiz_lessons.py:295-311` (grammar), аналогично 533/701/892/1006 (quiz/final_test): гейт перед `maybe_award_curriculum_xp` — `if progress and progress.status == 'completed':`, а НЕ проверка текущего результата (`result.get('passed')`). Из-за sticky-статуса выше это условие истинно и для проваленной повторной попытки старого урока.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-090.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md фиксирует только общий паттерн «primary/fallback» для `_curriculum_done_today`, не описывает sticky-статус `LessonProgress` как источник рассинхрона; сам факт двух разных правил проверки score в коде подтверждён.

#### DP-054 · P2 · `app/daily_plan/linear/xp.py:537`

- **Кандидат:** `DP-C-099` · линзы-источники: ITEMS-D-17 · скептик: `skeptics/DP-C-099.md`
- **Симптом:** blanket-`except` вокруг сборки плана: отравленная сессия рушит `commit()` вызывателя и откатывает уже отданный XP
- **Сценарий отказа:** механизм в коде есть и воспроизведён: `except Exception` на `xp.py:537` не делает `db_session.rollback()`; `get_daily_summary` (без защиты) и код `get_daily_plan_unified` до её внутреннего `try` (без защиты) — оба реальных, недоступных для внутреннего перехвата источника исключения. Сценарий вход → неверный выход: пользователь дергает `/api/complete-session` с `is_linear_plan_srs=true`, `maybe_award_srs_global_xp` успешно флашит XP+`StreakEvent` через savepoint, затем внутри `maybe_award_linear_perfect_day` любой DB-уровневый сбой в `get_daily_plan_unified`/`get_daily_summary` (транзиентная ошибка, дедлок, таймаут, баг в одном из билдеров плана) отравляет сессию; последующий `db.session.commit()` (`api_routes.py:832`) падает, внешний `except` (`api_routes.py:840-845`) делает `db.session.rollback()`, откатывая уже присуждённый SRS-slot XP — но эндпоинт всё равно отвечает `{'success': True, ...}` (строка 870-883), то есть пользователю молча врут об успехе. В `app/api/daily_plan.py` тот же механизм даёт честный, но тоже деструктивный эффект — 500 с откатом уже обработанных `error_ids`.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/xp.py:534-542`: ```python try: plan = get_daily_plan_unified(user_id, tz=tz) summary = get_daily_summary(user_id, tz=tz) except Exception: # noqa: BLE001 — never break caller on plan assembly logger.warning(...) return None ``` Нет `db_session.rollback()` в `except`.
  - `app/telegram/queries.py:1068-1107` (`get_daily_summary`) — чистые ORM-запросы (`LessonProgress.query.filter(...).all()`, `UserGrammarExercise.query...`, `db.session.query(...).scalar()`) без какой-либо защиты/savepoint.
  - `app/daily_plan/service.py:171-177` — `User.query.get(user_id)`, `DailyPlanLog.query.filter_by(...).first()` выполняются ДО внутреннего `try` (`service.py:193`), т.е. их исключение не перехватывается внутренним хендлером `get_daily_plan_unified` и долетает прямо до `xp.py:534`.
  - Сам файл `xp.py:188-191` документирует, что авторы знают об этом классе бага и чинили его именно savepoint'ом: `"Race-safe: do the XP write + ledger insert inside a savepoint so a concurrent award that wins uq_streak_events_xp_linear_source raises IntegrityError here (not in the caller's commit) and the XP increment rolls back with it (audit E-001)."` — `maybe_award_linear_perfect_day` этот приём не применяет.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-099.md`; здесь список усечён по бюджету, а не по значимости)_
- **Второй проход (три независимые линзы):** correctness=PARTIAL · reproducibility=CONDITIONAL · user-impact=P2 → P1 → P2. P1→P2. Формулировку править: причина не в якорном blanket-`except` (он обёрнут вокруг чтения плана), а в том, что многозапросная perfect-day проверка идёт в незакоммиченной транзакции после flush XP без изолирующего savepoint. Триггер — только DBAPI-сбой, не действие пользователя.
- **Где расхождение:** код — тот же файл `xp.py` в комментарии `188-191` формулирует ровно этот принцип (savepoint, чтобы ошибка не долетала до `commit()` вызывающего и не откатывала уже присуждённый XP) и применяет его в `award_linear_slot_xp_idempotent`, но не в `maybe_award_linear_perfect_day` несколькими строками ниже — внутреннее противоречие в пределах одного файла, а не просто общее «так не делают».

#### DP-055 · P2 · `app/daily_plan/tier.py:47`

- **Кандидат:** `DP-C-100` · линзы-источники: ITEMS-E-03 · скептик: `skeptics/DP-C-100.md`
- **Симптом:** «признак сверхусилия» считается по источникам, которые пишет обязательный curriculum-урок
- **Сценарий отказа:** CONFIRMED. Сценарий: юзер выполняет ровно required-минимум каждый день недели; в 3+ дней из 7-дневного окна required-урок спайна (`find_next_lesson_linear`) оказывается типа `dictation`/`audio_fill_blank`/`listening_immersion` (это обычный, регулярно встречающийся Block A-C контент, не редкость). Прохождение этого единственного required-урока пишет ОДИН клик → ДВА `StreakEvent` с `event_type='xp_linear'`: required-source (исключён из `_OPTIONAL_SOURCES`) и `'linear_listening'` (включён). `_count_days_with_optional_completion` засчитывает такой день как день «активности сверх минимума», хотя юзер не сделал ничего дополнительного. При `secured_days>=5` и таких «оптional»-днях `>=3` в окне — `compute_user_tier` возвращает `intensive` (`tier.py:83-92`), увеличивая `required` до 5 пунктов/день для юзера, который никогда не выходил за пределы обязательного минимума. Это прямо противоречит собственному комментарию файла о том, что required-источники исключены «потому что не сигнализируют дополнительное усилие» — `'linear_listening'` фактически required-источник для части лёгких Block A-C уроков, но не исключён.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/tier.py:43-46` — прямой комментарий модуля: «Required-side sources (curriculum, srs:global, book reading) are excluded — they don't signal extra effort», и множество `_OPTIONAL_SOURCES` (`tier.py:47-54`) включает `'linear_listening'`.
  - `app/daily_plan/linear/xp.py:35-36` — типы уроков `dictation`, `audio_fill_blank`, `listening_immersion`, `listening_immersion_quiz` смапплены в `LESSON_TYPE_TO_SOURCE` наравне с любым другим curriculum-уроком → это обычные Block A-C уроки, которые могут быть **следующим уроком спайна** (required-пункт плана), т.к. `find_next_lesson_linear` (используется в `build_required`, `app/daily_plan/items/curriculum.py:445`) не фильтрует по типу урока.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-100.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — противоречие внутри самого `app/daily_plan/tier.py` (комментарий строк 43-46 vs фактическое поведение `'linear_listening'`); прямого пункта CLAUDE.md, фиксирующего инвариант «tier считает только добровольную активность», нет, но CLAUDE.md описывает `_listening` именно как «baseline slot», что подтверждает: сигнал не является чисто добровольным.

#### DP-056 · P2 · `app/study/routes.py:1035`

- **Кандидат:** `DP-C-101` · линзы-источники: ITEMS-E-04 · скептик: `skeptics/DP-C-101.md`
- **Симптом:** `/study/weekly` зовёт `get_daily_plan` с `db.session` вместо `db`
- **Сценарий отказа:** механизм подтверждён и кодом, и живым прогоном: `weekly_plan()` передаёт `db.session` (scoped_session) туда, где нижестоящий код ожидает объект-расширение с атрибутом `.session` (`db.session.query`, `db.session.get`). Каждый вызов `/study/weekly` **гарантированно** ловит `AttributeError` внутри `get_unified_plan(...)` на первой же строке тела `get_daily_plan` (`find_next_lesson_state`). Эффект замаскирован голым `except Exception: pass` в `app/study/routes.py:1038-1039` — роут не падает, но `today_plan` всегда остаётся `None`, и блок `if is_today: ... else: slot_kinds = list(default_slot_kinds)` (строки ~1067 и далее) подставляет статичные дефолты вместо реального плана: `completed_count` всегда `0`, `slot_kinds` — фиксированный список `['curriculum','srs','reading']` вместо фактических слотов дня, `estimated_minutes` — статичная сумма вместо `total_estimated_minutes` из реального плана. Итог: колонка «сегодня» на `/study/weekly` у ВСЕХ пользователей всегда показывает общий прогноз, а не фактический прогресс дня — молча и без исключения.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/study/routes.py:1037` — `today_plan = get_unified_plan(current_user.id, db.session)` (алиас на `app.daily_plan.plan.get_daily_plan`), обёрнуто в `try: ... except Exception: pass` (строки 1036–1039).
  - `app/daily_plan/plan.py:365` — `session = db_session if db_session is not None else db` — раз `db_session` не `None` (пришёл `db.session`), `session` становится тем самым `scoped_session`, а не расширением `db`.
  - `app/daily_plan/plan.py:369` — `next_lesson, blocking_module_id = find_next_lesson_state(user_id, session)` — первый же вызов с этим объектом.
  - `app/daily_plan/linear/progression.py:57-59` — сигнатура `find_next_lesson_state(user_id, db, ...)`, тело использует параметр как расширение: `db.session.query(...)`, `db.session.get(...)` (напр. строки 95, 103, 105, 137).
  - `app/utils/db.py:3` — `db = SQLAlchemy()`; `db.session` — это `self._make_scoped_session(...)` (`flask_sqlalchemy/extension.py`, `SQLAlchemy.__init__`), т.е. `sqlalchemy.orm.scoping.scoped_session`. У `scoped_session` **нет** атрибута `.session` (проверено: `hasattr(scoped_session(...), 'session') == False`).
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-101.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — `get_daily_plan` принимает "session or db" по документированному контракту сигнатуры (`db_session: Any = None`), но нижестоящие функции по всей цепочке (`find_next_lesson_state`, `get_user_level_progress`, `_get_user_focus` и др.) молчаливо требуют именно объект-расширение (`db.session.query`), а не сырую сессию — расхождение внутри самого кода daily_plan, не документа.

#### DP-057 · P2 · `app/daily_plan/linear/plan.py:216`

- **Кандидат:** `DP-C-102` · линзы-источники: ITEMS-E-05 · скептик: `skeptics/DP-C-102.md`
- **Симптом:** порядок по времени суток и `plan_difficulty` достижимы только из мёртвого `get_linear_plan`; живой план часа не читает
- **Сценарий отказа:** механизм существует буквально как описано: и time-of-day реордер, и plan_difficulty-зависимые эффекты (реордер + extension-логика `build_chain`) целиком инкапсулированы в `get_linear_plan`/`build_tomorrow_preview`/`build_chain`, а эта цепочка не имеет ни одного вызывающего в прод-коде — только собственное определение и упоминания «раньше» в комментариях/тестах. Живой путь `get_daily_plan_unified → app.daily_plan.plan.get_daily_plan` берёт из `linear/plan.py` только `get_plan_intensity` (от минут, не от часа). Сценарий: админ ставит `User.plan_difficulty='intensive'` через `/admin/users/<id>/settings` — на реальный дневной план (`GET /api/daily-plan`, dashboard) это не влияет никак; юзер, заходящий в 22:00, получает тот же порядок слотов, что и в 8 утра, хотя CLAUDE.md документирует обратное как активное поведение.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/plan.py:216-243` — `_apply_time_of_day_order(all_slots, baseline_count, user_local_hour, difficulty)`: реордер срабатывает только при `difficulty == 'normal'`, читает `user_local_hour` (evening ≥20 → SRS-first, morning ≤9 → curriculum-first).
  - `app/daily_plan/linear/plan.py:337-347` — единственный вызов `_apply_time_of_day_order` внутри `get_linear_plan`: `difficulty = _get_plan_difficulty(...)`, `user_local_hour = get_user_local_hour(...)`, `all_slots, slot_order_reason = _apply_time_of_day_order(...)`.
  - `grep -rln "get_linear_plan" app tests` → только `app/daily_plan/linear/plan.py` (своё определение), `app/daily_plan/linear/xp.py:515` (комментарий «раньше собирал... get_linear_plan», прошедшее время), `tests/daily_plan/test_perfect_day_unified.py:3` (regression-комментарий о том же), `tests/curriculum/test_sentence_completion.py:348` — тест с этим именем monkeypatch'ит функцию `fake_plan`, саму `get_linear_plan` не вызывает. **Ни одного вызова из прод-кода (routes/services/api) не найдено.**
  - _(ещё 4 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-102.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — раздел «Daily Plan (Unified) → Intelligence» в CLAUDE.md утверждает: «Slot order адаптируется по времени дня (`plan_difficulty='normal'`)» и «`plan_difficulty ENUM('light','normal','intensive')` (light=2, normal=3-4, intensive=forces extensions)» как активное поведение живого плана; фактически это код мёртвой ветки `get_linear_plan`/`build_chain`, недостижимой из `get_daily_plan_unified`.

#### DP-058 · P2 · `app/daily_plan/items/curriculum.py:41`

- **Кандидат:** `DP-C-106` · линзы-источники: ITEMS-E-09 · скептик: `skeptics/DP-C-106.md`
- **Симптом:** `_LESSON_ETA_MINUTES` продублирован в двух модулях; 38.9 % уроков падают на дефолт
- **Сценарий отказа:** механизм воспроизводим по коду без допущений о состоянии. Сценарий: пользователь получает в required/optional урок типа `dictation`/`shadow_reading`/`writing_prompt`/`audio_fill_blank`/`translation`/`sentence_completion`/`collocation_matching` (7 из 17 реально существующих типов, 602/1548 = 38.9% каталога) → `_eta_minutes` не находит ключ в словаре → возвращает дефолт 10 мин вместо реальной оценки для этого типа урока → UI показывает «~10 мин» и в `total_estimated_minutes` дня попадает то же неверное число. Дублирование словаря в `curriculum_slot.py` подтверждено буквально (идентичный код в двух файлах), но живой (используемый `build_required_snapshot`) путь — только копия в `items/curriculum.py`; вторая копия used only via `build_tomorrow_preview`/`chain.py`, у которых `get_linear_plan` не вызывается ни одним живым роутом.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/items/curriculum.py:41-56` и `app/daily_plan/linear/slots/curriculum_slot.py:36-51` — два побайтово идентичных словаря `_LESSON_ETA_MINUTES` (15 ключей) и идентичные функции `_eta_minutes`. Комментарий над вторым экземпляром (`curriculum_slot.py:34-35`): «ETA estimates for each of the 12 curriculum lesson types plus legacy aliases that still appear in content (matching/text/flashcards)» — писан до появления Block A-C типов и с тех пор не обновлялся ни в одной из двух копий.
  - `app/daily_plan/plan_builder.py:45,189` — `from app.daily_plan.items.curriculum import build_curriculum_item`; это единственный источник required-урока в живом пути (`snapshot.py:127` → `build_required_snapshot`). Копия в `curriculum_slot.py` используется через `chain.py`/`get_linear_plan`, который сейчас нигде не вызывается живыми роутами (только упомянут в комментарии `xp.py:515`) — то есть вторая копия практически мёртвая, но сам факт дублирования в коде подтверждён буквально.
  - `app/daily_plan/linear/xp.py:36-62` (`LESSON_TYPE_TO_SOURCE`) — канонический список из 24 типов урока, используемых `_CURRICULUM_LESSON_TYPES` в `items/curriculum.py`.
  - _(ещё 4 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-106.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md не описывает `_LESSON_ETA_MINUTES` вовсе; расхождение внутри самого кода (устаревший словарь vs актуальный список типов Block A-C из `LESSON_TYPE_TO_SOURCE`, который CLAUDE.md перечисляет как «Lesson types (Block A-C)»).


### P3 — детали

#### DP-059 · P3 · `app/daily_plan/items/curriculum.py:534`

- **Кандидат:** `DP-C-060` · линзы-источники: ITEMS-A-09 · скептик: `skeptics/DP-C-060.md`
- **Инвариант:** **INV-20** (уроки заблокированных модулей фильтруются тем же floor'ом `check_prerequisites(min_level_order=…)`, что и спайн). Проставлено на Task 9 по замечанию критика на полноту: разбор инварианта был, ID в находке не стоял.
- **Симптом:** реплика `check_module_access` в очереди не воспроизводит admin-байпас и игнорирует переданный `db` в 3 из 4 правил
- **Сценарий отказа:** CONFIRMED (частично) — severity ниже, чем подразумевает формулировка. 1. **Admin-байпас действительно не воспроизведён** — это настоящее расхождение с докстрингом самой функции ("full rule set is mirrored"). Конкретный сценарий: админ (`current_user.is_admin=True`) без `LessonProgress` в модуле M2 (не первом в уровне), у которого предыдущий модуль M1 < 80% завершён. Прямой переход по URL урока M2 → `check_module_access` → `True` мгновенно (байпас). Тот же урок в очереди «Дальше по курсу» → `_module_accessible_for_user` прогоняет только правила 1-4, все проваливаются → модуль признаётся недоступным → `build_curriculum_queue` (`curriculum.py:672-676`) добавляет `level_id` в `blocked_level_ids` → весь остаток CEFR-уровня выпадает из очереди. Итог: у админа очередь «Дальше по курсу» короче/пустее, чем реально доступный контент — обратный эффект тому, от которого докстринг защищается (dead links), но не он сам, а недосчёт. 2. **«Игнорирует `db` в 3 из 4 правил»** — текстуально верно (это `Model.query`, не аргумент `db`), но в проверенной кодовой базе НЕТ ни одного места, где в `get_daily_plan`/`build_curriculum_queue` передавался бы `db`-объект, отличный от глобального синглтона `app.utils.db.db`. Flask-SQLAlchemy привязывает `Model.query` к сессии того же глобального `db`, поэтому наблюдаемого расхождения данных это не создаёт ни в одном реальном или тестовом пути вызова — это стилистическая непоследовательность (следовало бы для консистентности всюду писать `db.session.query`), а не источник неверного поведения. Итого: реальный баг — только первая половина кандидата (admin-байпас), эффект узкий (только `is_admin` аккаунты, только косметика необязательной секции, `day_secured`/required не затронуты, никакой утечки данных — очередь становится строже, а не слабее).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/curriculum/security.py:230-232` — оригинал: ```python # Temporary admin preview mode: admins can open any curriculum module. if getattr(current_user, 'is_admin', False): return True ``` Это первая проверка в `check_module_access`, безусловный байпас для админов.
  - `app/daily_plan/items/curriculum.py:534-548` — докстринг реплики буквально заявляет полное зеркалирование: *"its full rule set is mirrored here for a given `user_id`"*, и перечисляет 4 правила (explicit prereqs → progress → first module → prev module ≥80%). Admin-байпас в списке не упомянут и нигде в теле функции (`curriculum.py:550-596`) не проверяется — ни `current_user`, ни `User.is_admin` там не читаются вообще (`grep is_admin app/daily_plan/` — 0 совпадений).
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-060.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код (докстринг `_module_accessible_for_user` заявляет "full rule set is mirrored", реализация не включает admin-байпас `check_module_access`).

#### DP-060 · P3 · `CLAUDE.md` (Daily Plan)`

- **Кандидат:** `DP-C-062` · линзы-источники: ITEMS-A-11 · скептик: `skeptics/DP-C-062.md`
- **Симптом:** 4 расхождения документа с кодом: порядок `build_optional`, состав `_OPTIONAL_PRIORITY`, проходной балл, число типов уроков
- **Сценарий отказа:** из 4 заявленных расхождений подтвердились **3**: (1) порядок источников в `build_optional` (не упомянут этап `phrase_review`), (2) состав `_OPTIONAL_PRIORITY` (документ называет несуществующие `listening/speaking/writing`, не называет реальный `word_set_quiz`), (4) число типов уроков в `_SCORE_BASED_LESSON_TYPES` (10 в документе против 15 в коде). Пункт «проходной балл» (`PASSING_SCORE_DEFAULT`/`PASSING_SCORE_DICTATION`) — REFUTED, значения совпадают дословно. Все три подтверждённых расхождения — чистая доку­ментация против кода без наблюдаемого эффекта на поведение системы (документ описывает структуру верно в общих чертах, но неточен в деталях состава/перечня) → severity P3 по определению брифинга («расхождение документа с кодом»).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - 1) **Порядок источников в `build_optional` — расхождение подтверждено.**
  - `CLAUDE.md:45`: «Порядок в `build_optional`: (1) сегодняшние completed curriculum lessons … (2) curriculum-очередь … (3) прочие источники (srs/reading/listening/speaking/writing/ error_review/grammar_review/challenge) — ПОСЛЕ очереди.»
  - `app/daily_plan/plan.py:216-220` — `phrase_review` кандидат добавляется через `_accept(...)` **до** блока curriculum-очереди (строки 249-262) и вообще не упомянут в документированном списке трёх этапов.
  - `app/daily_plan/plan.py:265-271` — цикл `for kind in _OPTIONAL_PRIORITY` идёт третьим этапом, что структурно совпадает с «(3) ПОСЛЕ очереди», но фактический этап-0 (`phrase_review`) документ не называет вовсе, а он стоит перед очередью, а не после completed-карточек и до неё же — реальный порядок: completed-cards (в итоговый список) → phrase_review → curriculum-queue → `_OPTIONAL_PRIORITY`. Документ этот шаг пропускает. 2) **Состав `_OPTIONAL_PRIORITY` — расхождение подтверждено.**
  - `app/daily_plan/plan.py:109-116`: ``` _OPTIONAL_PRIORITY = ( 'srs', 'reading', 'error_review', 'grammar_review', 'word_set_quiz', 'challenge', ) ```
  - `CLAUDE.md:45` называет «прочие источники (srs/reading/listening/speaking/writing/error_review/ grammar_review/challenge)» — `listening`/`speaking`/`writing` в кортеже кода отсутствуют, `word_set_quiz` в документе не упомянут.
  - _(ещё 6 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-062.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** CLAUDE.md (в трёх из четырёх пунктов — код является источником истины, документ устарел/неполон; в пункте «проходной балл» расхождения нет вовсе).

#### DP-061 · P3 · `app/daily_plan/linear/slots/srs_slot.py:153`

- **Кандидат:** `DP-C-068` · линзы-источники: ITEMS-B-06 · скептик: `skeptics/DP-C-068.md`
- **Симптом:** легаси `build_srs_slot` подменяет слот на deck-quiz без проверки наличия колод (второе условие INV-27 отсутствует)
- **Сценарий отказа:** механизм в коде реален: `build_srs_slot` решает подменить слот на deck-quiz по одному условию (тип текущего урока), а отсутствие deck-слов внутри `_build_deck_quiz_slot` не откатывает на настоящий SRS-слот, а маскирует его фиктивным `completed=True` без учёта реальных due-карт. Сценарий (будь путь живым): у юзера следующий curriculum-урок — карточный, колод со словами нет, но есть due SRS-повторы → required SRS-слот в baseline рапортует «Нет слов для квиза в колодах» и `completed=True`, реальные due-карты не появляются и не считаются. Однако весь путь до анкора (`_build_baseline` → `build_chain`/`build_tomorrow_preview` → `get_linear_plan`) не имеет ни одного вызывателя в проде — `get_linear_plan` мёртв, реальный дневной план строится параллельным путём (`plan_builder.py::_srs_item_dict`), где вторая проверка присутствует и работает корректно. Поэтому эффект недостижим для реальных пользователей сегодня; severity понижена до P3 (мёртвый код с латентным дефектом внутри, без наблюдаемого эффекта).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/slots/srs_slot.py:145-149` — `build_srs_slot` решает подмену только по типу урока: `if getattr(curriculum_lesson, 'type', None) in _CARD_LESSON_TYPES: return _build_deck_quiz_slot(user_id, db)` — без проверки `deck_word_count` на этом уровне.
  - `app/daily_plan/linear/slots/srs_slot.py:117-123` — при `deck_word_count <= 0` `_build_deck_quiz_slot` НЕ откатывается к обычному SRS (due-cards), а возвращает фиктивно закрытый слот: `return LinearSlot(kind='srs', title='Нет слов для квиза в колодах', ..., completed=True, data=data)`. Реальные `learning_due`/`review_due` в этой ветке вообще не считаются.
  - Контраст с живым путём — `app/daily_plan/plan_builder.py:199-207`: `if as_deck_quiz: ... if _count_user_deck_quiz_words(user_id, db) <= 0: as_deck_quiz = False` — здесь вторая проверка ЕСТЬ и явно откатывает на настоящий `build_srs_item` с due-картами. Комментарий там же: «a deck quiz only replaces `srs:global` when the user actually has deck words (otherwise the slot would be a dead placeholder)» — то есть у авторов кода есть чёткое понимание инварианта, но в легаси-модуле он не соблюдён.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-068.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md описывает только живой инвариант («SRS deck-quiz подмена... только если у юзера есть deck-слова... без колод — обычный srs:global в required») применительно к `build_required`/`plan_builder.py`, про legacy `linear/chain.py` ничего не говорит; расхождение — внутри самого кода (два модуля с одинаковой задачей реализуют инвариант по-разному), а не между кодом и документом.

#### DP-062 · P3 · `app/daily_plan/plan_builder.py:110`

- **Кандидат:** `DP-C-069` · линзы-источники: ITEMS-B-07 · скептик: `skeptics/DP-C-069.md`
- **Симптом:** `_srs_item_dict` вызывается дважды с идентичными аргументами
- **Сценарий отказа:** механизм найден буквально: когда первый урок в собранной цепочке спайна — `final_test` (`ft_position == 0`), `_srs_item_dict(user_id, db, as_deck_quiz=...)` вызывается ровно с одинаковыми аргументами дважды подряд (первый раз безусловно на строке 89, второй раз внутри ветки на строке ~103), и результат первого вызова нигде не используется — переменная `srs_item` перезаписывается. Сценарий: юзер, у которого следующий урок спайна — `final_test` его текущего модуля (например, после успешного прохождения предпоследнего урока модуля), запрашивает построение required-снапшота (`build_required_snapshot`) → выполняется 2× полный набор SRS-count-запросов (`count_pending_new`, `count_due_by_states` ×2, `count_reviews_today`, `count_new_cards_today`, budget-функции) вместо одного. Наблюдаемого неверного поведения нет — оба вызова читают одно и то же состояние БД в рамках одного запроса и дают идентичный результат, просто лишний раз. Это чистая избыточность (extra DB round-trips), не баг корректности.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/plan_builder.py:89` — безусловный первый вызов: `srs_item = _srs_item_dict(user_id, db, as_deck_quiz=first_is_card)`, где `first_is_card = getattr(first_lesson, 'type', None) in _CARD_LESSON_TYPES` (строки 85–87), а `_CARD_LESSON_TYPES = frozenset({'card', 'flashcards'})` (строка 62).
  - `app/daily_plan/plan_builder.py:93` — `final_test_lesson, ft_position = _find_final_test(curriculum_lessons)`; при `ft_position == 0` по определению `_find_final_test` (строка ~168: `if getattr(lesson, 'type', None) == 'final_test': return lesson, i`) `first_lesson.type == 'final_test'`, которого нет в `_CARD_LESSON_TYPES` — значит `first_is_card` в этой ветке всегда `False`, и первый вызов уже был эквивалентен `as_deck_quiz=False`.
  - `app/daily_plan/plan_builder.py:95-103` — внутри `if final_test_lesson is not None and ft_position == 0:` идёт второй вызов: `srs_item = _srs_item_dict(user_id, db, as_deck_quiz=False)`. Комментарий в коде (строки 99–101) сам признаёт: «the deck-quiz swap (first_is_card) cannot apply because final_test is not a card lesson» — то есть авторы знали, что `as_deck_quiz` в обоих вызовах одинаков, но не убрали первый лишний вызов (просто переприсваивают `srs_item`, результат первого вызова отбрасывается целиком).
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-063 · P3 · `CLAUDE.md`

- **Кандидат:** `DP-C-072` · линзы-источники: ITEMS-B-10 · скептик: `skeptics/DP-C-072.md`
- **Симптом:** значения `get_adaptive_limit_reason()` в документе не совпадают с кодом
- **Сценарий отказа:** механизм найден: `get_adaptive_limit_reason()` фактически возвращает один из 4 accuracy-тиров `{'normal','low','critical','collapse'}` (backlog учитывается отдельно, только как множитель на `new`, но не отражается отдельным reason-лейблом типа `'backlog_reduction'`). Множество значений `{'normal','backlog_reduction','accuracy_low'}`, описанное в CLAUDE.md, нигде в коде не встречается — ни как literal-строка, ни как результат маппинга. Сценарий: разработчик, читающий CLAUDE.md, напишет во фронтенде/тесте `if (srs_limit_reason === 'accuracy_low')` — условие никогда не сработает, потому что реальный payload несёt `'low'`/`'critical'`/`'collapse'`.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `CLAUDE.md:64` — `` sibling `get_adaptive_limit_reason() → {'normal','backlog_reduction','accuracy_low'}` ``.
  - `app/study/services/srs_service.py:192` — `TIER_ORDER: Tuple[str, ...] = ('collapse', 'critical', 'low', 'normal')`.
  - `app/study/services/srs_service.py:197-201` — `TIER_PCT` ключи ровно `'normal'`, `'low'`, `'critical'`, `'collapse'`.
  - `app/study/services/srs_service.py:459-467` — `get_adaptive_limit_reason` возвращает `tier` из `_compute_adaptive_state`, докстрока: `"One of 'normal', 'low', 'critical', 'collapse'."`.
  - `app/daily_plan/items/srs.py:201` — `tier = SRSService.get_adaptive_limit_reason(user_id) # one of normal/low/critical/collapse`.
  - `app/api/daily_plan.py:387-438` и `:492-495` — `srs_limit_reason = SRSService.get_adaptive_limit_reason(user_id)`, далее `if srs_limit_reason != 'normal': payload['srs_limit_reason'] = srs_limit_reason` — сырое значение тира кладётся в payload без какого-либо переименования/маппинга в `'backlog_reduction'`/`'accuracy_low'` где-либо в коде (grep по обоим строкам в `app/` не нашёл ни одного вхождения `backlog_reduction` или `accuracy_low` вне текста CLAUDE.md).
- **Где расхождение:** CLAUDE.md — документ описывает несуществующий набор значений; сам код консистентен сам с собой (сервис, оба вызывающих модуля и inline-комментарий согласны на `normal/low/critical/collapse`).

#### DP-064 · P3 · `app/study/services/srs_service.py:486-487`

- **Кандидат:** `DP-C-074` · линзы-источники: ITEMS-B-12 · скептик: `skeptics/DP-C-074.md`
- **Симптом:** мёртвые локальные `now`/`today_start` с календарной UTC-полночью
- **Сценарий отказа:** обе переменные действительно присваиваются и нигде не читаются дальше в `get_card_counts`, то есть это мёртвый код: на каждый вызов метода тратится один системный вызов времени и объектное присваивание без какого-либо влияния на возвращаемый результат. Функционального эффекта на выдачу нет (все реальные подсчёты идут через `count_due_cards`/`count_new_cards_today`, которые сами инкапсулируют корректный day-boundary), поэтому не P1/P2 — только неиспользуемый код с потенциально вводящей в заблуждение календарной UTC-полночью рядом с методами, которые для аналогичной цели правильно берут `day_to_naive_utc`.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/study/services/srs_service.py:486` — `now = datetime.now(timezone.utc).replace(tzinfo=None)`
  - `app/study/services/srs_service.py:487` — `today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)` — вычисляет календарную UTC-полночь (не user-local через `day_to_naive_utc`, как в соседних методах того же класса на строках 142, 296, 600).
  - Автоматизированный подсчёт вхождений идентификаторов `now`/`today_start` в теле функции (строки 470–540, до следующего `@staticmethod`): `now` встречается 4 раза — из них 2 в докстринге/комментарии («due right now», «due now»), 1 в самом определении (486), 1 в правой части определения `today_start` (487, `now.replace(...)`); `today_start` встречается ровно 1 раз — только в своём определении (487). Ни `now`, ни `today_start` не используются нигде дальше по телу метода: `due_count` считается через `count_due_cards(...)`, `new_count`/`new_cards_today`/`can_study_new`/`nothing_to_study`/`limit_reached` и итоговый `return {...}` не ссылаются ни на одну из этих двух переменных.
- **Где расхождение:** код — сам факт мёртвого кода не противоречит CLAUDE.md (который фиксирует day-anchored конвенцию для *используемых* сравнений в `app/srs/scheduling.py`/`app/srs/counting.py`); здесь переменные просто не участвуют ни в каком сравнении, поэтому расхождения с задокументированным naive-UTC/day-anchored поведением по факту нет.

#### DP-065 · P3 · `app/daily_plan/items/grammar_review.py:104`

- **Кандидат:** `DP-C-079` · линзы-источники: ITEMS-C-06 · скептик: `skeptics/DP-C-079.md`
- **Симптом:** `completion_signal='grammar_exercises'` вне `CompletionSignal` Literal
- **Сценарий отказа:** заявленный факт подтверждён буквально: `'grammar_exercises'` отсутствует в `Literal` `CompletionSignal`, и в отличие от похожего случая в `phrase_review.py:209` (где `# type: ignore[arg-type]` стоит даже на ВАЛИДНОМ значении) здесь несовпадение никак не подавлено — то есть не осознанный `type: ignore`, а недосмотр. Эффекта на рантайм нет: `PlanItem` — обычный dataclass без валидации, значение нигде не сравнивается со списком допустимых сигналов (только читается кодом `kind`), и ни один найденный механизм (ruff, отсутствующий mypy-конфиг) не проверяет `Literal`-типы в CI — так что это чистое расхождение типа/документации без наблюдаемого поведенческого эффекта у пользователя.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/items/__init__.py:40-53` — `CompletionSignal = Literal['lesson_completed', 'srs_xp_earned', 'reading_gate', 'writing_attempt', 'listening_attempt', 'pronunciation_attempt', 'error_review_done', 'challenge_completed', 'phrase_review_done', 'word_set_quiz_done', 'setup_action', 'none']` — `'grammar_exercises'` в списке действительно отсутствует.
  - `app/daily_plan/items/grammar_review.py:104` — `completion_signal='grammar_exercises',` — присвоено БЕЗ `# type: ignore[arg-type]`, в отличие от соседней строки 96 (`section=section, # type: ignore[arg-type]`), то есть несовпадение с Literal не подавлено намеренно, а, похоже, просто не замечено.
  - `app/daily_plan/plan_builder.py:331` — второе место с тем же значением `'completion_signal': 'grammar_exercises'`, но это plain-dict литерал (grammar-prep-перед-final-test item), а не конструктор `PlanItem` — Literal-тип на него вообще не распространяется, поэтому это не тот же самый механизм, но подтверждает, что `'grammar_exercises'` — намеренное, последовательно используемое значение, а не опечатка.
  - `PlanItem` — `@dataclass(frozen=True)` (обычный dataclass, не pydantic) в `app/daily_plan/items/__init__.py:56-70` — Python не проверяет `Literal` в рантайме при создании инстанса, значит несовпадение не бросает исключение и не меняет поведение конструктора.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-079.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-066 · P3 · `app/curriculum/form.py:47`

- **Кандидат:** `DP-C-091` · линзы-источники: ITEMS-D-08 · скептик: `skeptics/DP-C-091.md`
- **Симптом:** `anki_cards`/`checkpoint` остались в choices **мёртвой** `LessonForm` и отсутствуют в `LESSON_TYPE_TO_SOURCE`/`route_map`: живого писателя нет, тип достижим только ручным JSON-импортом
- **Сценарий отказа:** механизм в коде реальный и воспроизводится чисто чтением кода: если урок с `type='anki_cards'` или `type='checkpoint'` попадает в БД через `LessonForm` и оказывается следующим по спайну для какого-то пользователя, `lesson_detail`/`main.py` не находят маршрут рендера (`route_map.get(lesson.type) is None`), пользователь никогда не сможет завершить урок, требуемый curriculum-слот (и весь дальнейший спайн) остаётся недостижим без ручного вмешательства администратора (смена `type` или ручное завершение `LessonProgress`). Кандидат называет только `LESSON_TYPE_TO_SOURCE` — реальная причина шире (тот же пробел продублирован и в `route_map` рендеринга), но итоговый эффект («незакрываемый required-слот») подтверждён и даже хуже описанного: блокируется прогресс по всему курсу, а не только XP/слот за день. Оговорка по вероятности: SQL против прод-копии (`learn_db_prod`) не нашёл ни одного урока с этими типами — сейчас ни один реальный пользователь не задет, дефект «спит» и активируется только если админ вручную выберет `Anki Cards`/`Checkpoint` в форме создания урока (никакой другой писатель контента эти значения не использует — `grep` по `app/curriculum/` не находит других producer'ов, кроме формы).
- **Верификация:** CONFIRMED в части механизма; премисса кандидата («создаются админ-формой») опровергнута вторым проходом, симптом выше переписан под уцелевшую формулировку. Цитаты:
  - `app/curriculum/form.py:41-49` — `LessonForm.type` choices включают `('anki_cards', _l('Anki Cards'))` и `('checkpoint', _l('Checkpoint'))`; форма не имеет allow-list сверх этого набора, ничто не мешает админу сохранить урок с таким `type`.
  - `app/daily_plan/linear/xp.py:36-61` — `LESSON_TYPE_TO_SOURCE` перечисляет ~25 типов, `anki_cards` и `checkpoint` в словаре отсутствуют.
  - `app/daily_plan/items/curriculum.py:38-39` — `_CURRICULUM_LESSON_TYPES = frozenset(LESSON_TYPE_TO_SOURCE)`; этот же frozenset используется как фильтр `Lessons.type.in_(...)` в fallback-запросе `_curriculum_done_today` (строка ~134) и в `get_curriculum_lessons_completed_today` (строка ~215) — урок с `type='anki_cards'`/`'checkpoint'` не попадёт ни в primary (`StreakEvent.details['source']`, тоже производный от `LESSON_TYPE_TO_SOURCE`), ни в fallback ветку «завершён сегодня».
  - `app/daily_plan/linear/progression.py:96-121` (`find_next_lesson_state`) — кандидаты в «следующий урок спайна» отбираются ТОЛЬКО по `(CEFRLevel.order, Module.number, Lessons.number)` и prerequisites; фильтра по `Lessons.type` нет — урок `anki_cards`/`checkpoint`, если он существует в модуле, может стать required-элементом наравне с любым другим типом.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-091.md`; здесь список усечён по бюджету, а не по значимости)_
- **Второй проход (три независимые линзы):** correctness=PARTIAL · reproducibility=CONDITIONAL · user-impact=P3 → P1 → P3. P1→P3. Премисса кандидата неверна: `app/curriculum/form.py` мёртв (0 импортов в `app/`), живая админ-форма поля `type` не имеет, в проде 0 таких уроков. Механизм «тип вне `LESSON_TYPE_TO_SOURCE`» реален, но достижим только ручным JSON-импортом, и отказ там громкий (flash «Неизвестный тип урока»).
- **Где расхождение:** код — в CLAUDE.md нет явного инварианта «каждый `Lessons.type` из формы обязан быть в `LESSON_TYPE_TO_SOURCE`/`route_map`», но общий паттерн раздела Curriculum («Course-content types» в блоке Block A-C) подразумевает, что любой заводимый тип урока проведён через весь конвейер (роутинг + XP + done-today); `anki_cards`/ `checkpoint` — единственные исключения, оставшиеся в форме как нерасчищенный легаси.

#### DP-067 · P3 · `app/daily_plan/linear/xp.py:205`

- **Кандидат:** `DP-C-092` · линзы-источники: ITEMS-D-09 · скептик: `skeptics/DP-C-092.md`
- **Симптом:** `DailyPlanEvent('linear_slot_completed')` — ноль читателей
- **Сценарий отказа:** механизм именно такой: на каждое успешное начисление linear XP (`award_linear_slot_xp_idempotent`, вызывается из `maybe_award_curriculum_xp`, SRS/reading/grammar-review хелперов и т.д.) в таблицу `daily_plan_events` вставляется строка с `event_type='linear_slot_completed'` и `step_kind=<урезанный source>`. Ни один SELECT/query в кодовой базе (продакшн-код, тесты, скрипты, миграции) не фильтрует и не агрегирует по этому `event_type` — данные пишутся, накапливаются в таблице, но нигде не читаются и не влияют на поведение системы. Сценарий вход→выход: пользователь проходит любой linear-slot (например curriculum lesson) → XP начисляется, `StreakEvent` пишется (используется дедупом/streak-логикой), и параллельно пишется `DailyPlanEvent('linear_slot_completed')` → эта вторая запись не читается никаким кодом, то есть является чистым write-only телеметрическим шумом (лишняя строка в таблице на каждое начисление XP, без наблюдаемого эффекта на функциональность).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/xp.py:205-210` — запись события: ```python db_obj.session.add(DailyPlanEvent( user_id=user_id, event_type='linear_slot_completed', plan_date=when, step_kind=step_kind, )) ```
  - `app/daily_plan/models.py:39-53` — `DailyPlanEventType` enum перечисляет `minimum_completed`, `next_step_shown`, `next_step_accepted`, `next_step_dismissed`, `session_ended_at_minimum`, `rival_strip_shown/dismissed`, `steps_taken_while_rival_visible`, `slot_skipped`, `vocab_lookup`, `route_step_added`, `checkpoint_reached` — `linear_slot_completed` в этот список не входит вовсе (пишется как произвольная строка мимо enum-документации).
  - Все обнаруженные читатели `DailyPlanEvent` фильтруют по другим `event_type`: `slot_skipped` (`app/daily_plan/linear/plan.py:132-134,155-157`, `app/daily_plan/skips.py:51`, `app/daily_plan/plan.py:59-61`), `minimum_completed` (`app/daily_plan/milestones.py:62-64`), `route_step_added`/`checkpoint_reached` (`app/daily_plan/route_progress.py:120-177`), H1-события `next_step_shown/accepted/dismissed` и т.д. (`app/api/daily_plan.py:701-751`). Ни один запрос не содержит `event_type == 'linear_slot_completed'`.
  - Поиск `grep -rln "linear_slot_completed" .` (репозиторий целиком, минус `.git/`) вернул единственный файл — `app/daily_plan/linear/xp.py`, то есть строка встречается только в месте записи.
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-068 · P3 · `app/daily_plan/linear/xp.py:68-72`

- **Кандидат:** `DP-C-093` · линзы-источники: ITEMS-D-10 · скептик: `skeptics/DP-C-093.md`
- **Симптом:** 5 мёртвых констант
- **Сценарий отказа:** все пять констант (`_SRS_SOURCES`, `_READING_SOURCES`, `_LISTENING_SOURCES`, `_WRITING_SOURCES`, `_ERROR_REVIEW_SOURCES`) объявлены на строках 68-72 и не имеют ни одного читателя ни в файле объявления, ни где-либо ещё в `app/`. Судя по комментарию над блоком («Minutes credited per slot source…») и по факту, что реальная логика минут вынесена в `_SOURCE_MINUTES`/`_CURRICULUM_MINUTES` двумя строками ниже, это остаток более ранней реализации категоризации источников по типу slot'а (srs/reading/listening/writing/error_review), заменённой на плоский словарь минут — сами наборы-категории остались как неиспользуемый артефакт. Наблюдаемого эффекта на поведение нет (P3, не P0-P2): удаление безопасно, но кандидат как факт мёртвого кода подтверждён буквально — все 5 из 5 без читателей.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/xp.py:68` — `_SRS_SOURCES = {'linear_srs_global', 'linear_book_srs'}` — единственное вхождение имени во всём дереве `app/` (проверено `grep -rn _SRS_SOURCES app/`).
  - `app/daily_plan/linear/xp.py:69` — `_READING_SOURCES = {'linear_book_reading'}` — единственное вхождение.
  - `app/daily_plan/linear/xp.py:70` — `_LISTENING_SOURCES = {...}` — единственное вхождение.
  - `app/daily_plan/linear/xp.py:71` — `_WRITING_SOURCES = {'linear_writing', 'linear_curriculum_use'}` — единственное вхождение.
  - `app/daily_plan/linear/xp.py:72` — `_ERROR_REVIEW_SOURCES = {'linear_error_review'}` — единственное вхождение.
  - Контраст: `app/daily_plan/linear/xp.py:73-74` (`_CURRICULUM_MINUTES`, `_SOURCE_MINUTES`) читаются на `xp.py:184` (`minutes = _SOURCE_MINUTES.get(source)`) и `xp.py:186` (`minutes = _CURRICULUM_MINUTES`) — то есть соседние по блоку константы живые, а именно пять перечисленных в кандидате — нет.
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-069 · P3 · `app/daily_plan/linear/xp.py:462`

- **Кандидат:** `DP-C-095` · линзы-источники: ITEMS-D-12 · скептик: `skeptics/DP-C-095.md`
- **Симптом:** `lesson_id` у listening/writing принимается и не используется
- **Сценарий отказа:** параметр `lesson_id` в обеих функциях принимается (и вызывающий код `app/curriculum/routes/lessons.py` действительно передаёт `lesson.id` на всех 8 call site'ах), но внутри тела функции ни разу не читается: не попадает ни в `extra_details` для `StreakEvent`, ни в `award_linear_xp`. Эффект: аудит-trail (`StreakEvent.details`) для source `linear_listening` / `linear_writing` не содержит, какой именно урок вызвал начисление слота — в отличие от `linear_curriculum_*` source, где `lesson_id` в `details` есть. На корректность начисления XP, идемпотентность (ключ — `(user_id, source, date)`, не зависит от `lesson_id`) и `day_secured` это не влияет — докстринги обеих функций прямо говорят «once per day regardless of which lesson», так что функционально `lesson_id` дню не нужен. Это мёртвый параметр без наблюдаемого поведенческого эффекта — только дыра в диагностируемости (нельзя посмотреть в `StreakEvent.details`, какой урок дал слот-XP за listening/writing, хотя для curriculum-source это возможно).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/xp.py:462-481` — сигнатура `maybe_award_listening_xp(user_id, lesson_id=None, score=None, for_date=None, db_session=None)`, тело: ``` if not is_linear_user(user_id): return None return award_linear_slot_xp_idempotent( user_id, 'linear_listening', for_date, db_session, score=score, ) ``` `lesson_id` не встречается больше нигде в теле функции.
  - `app/daily_plan/linear/xp.py:484-502` — тот же паттерн для `maybe_award_writing_xp(user_id, lesson_id=None, for_date=None, db_session=None)`: тело зовёт `award_linear_slot_xp_idempotent(user_id, 'linear_writing', for_date, db_session)` без `lesson_id`.
  - Контраст: `maybe_award_curriculum_xp` (L229-256) для того же `lesson_id` явно строит `extra = {'lesson_id': int(lesson_id)} if lesson_id is not None else None` и пробрасывает его в `extra_details=extra` → `StreakEvent.details['lesson_id']`. У listening/writing хелперов такого пробрасывания нет — `award_linear_slot_xp_idempotent` вызывается без `extra_details` вовсе.
  - `app/achievements/xp_service.py:581-593` — `award_linear_xp(user_id, source, score=None)` тоже не принимает и не использует `lesson_id`.
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-070 · P3 · `CLAUDE.md`

- **Кандидат:** `DP-C-096` · линзы-источники: ITEMS-D-13 · скептик: `skeptics/DP-C-096.md`
- **Симптом:** 3 ключа LINEAR_XP не описаны (`_dictation`, `_audio_fill_blank`, `_use`)
- **Сценарий отказа:** расхождение реально, но кандидат ошибся в подсчёте. Ключей, не покрытых именно блоком «LINEAR_XP keys» (`CLAUDE.md:35`), не 3, а **5**: `_dictation`, `_audio_fill_blank`, `_use`, а также пропущенные кандидатом `linear_listening` и `linear_writing`. Если же считать «описан» шире — как «упомянут где-либо в CLAUDE.md с суммой» — то полностью недокументированы только **2** ключа (`linear_curriculum_dictation=20`, `linear_curriculum_audio_fill_blank=18`), а `linear_curriculum_use` упомянут по имени без суммы в другом разделе (`CLAUDE.md:125`). Реверсных расхождений (доц → код) — 0. Эффект чисто документационный, поведение кода не затронуто.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/achievements/xp_service.py:36-58` — фактический словарь содержит **21** ключ: `linear_curriculum_card`, `linear_curriculum_vocabulary`, `linear_curriculum_grammar`, `linear_curriculum_quiz`, `linear_curriculum_listening_quiz`, `linear_curriculum_dialogue_completion_quiz`, `linear_curriculum_ordering_quiz`, `linear_curriculum_translation_quiz`, `linear_curriculum_final_test`, `linear_curriculum_reading`, `linear_curriculum_listening_immersion`, `linear_curriculum_dictation=20`, `linear_curriculum_audio_fill_blank=18`, `linear_curriculum_use=25`, `linear_listening=18`, `linear_writing=25`, `linear_srs_global`, `linear_book_srs`, `linear_book_reading`, `linear_error_review`, `linear_grammar_review`.
  - `CLAUDE.md:35` — блок «LINEAR_XP keys» перечисляет/покрывает шорткатами (`_vocabulary`/`_grammar`, `_quiz*`/`_final_test`, `_reading`/`_listening_immersion`) только **16** из 21 ключа. Не покрыты этой строкой: `linear_curriculum_dictation`, `linear_curriculum_audio_fill_blank`, `linear_curriculum_use`, `linear_listening`, `linear_writing` — **5**, а не 3.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-096.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** CLAUDE.md — блок «LINEAR_XP keys» неполон/устарел относительно фактического словаря в `app/achievements/xp_service.py`.

#### DP-071 · P3 · `app/curriculum/service.py:177`

- **Кандидат:** `DP-C-098` · линзы-источники: ITEMS-D-16 · скептик: `skeptics/DP-C-098.md`
- **Симптом:** `complete_lesson` без прод-вызывателей → путь `xp_curriculum_lesson`/30 XP мёртв
- **Сценарий отказа:** механизм воспроизводится по коду напрямую: `complete_lesson` не импортируется и не вызывается ни в одном route/blueprint/service продакшн-кода (только тестами и собственным определением), а единственный продакшн-вызыватель `award_curriculum_lesson_xp_idempotent` (30 XP, событие `xp_curriculum_lesson`) — это сам `complete_lesson`. Сценарий: любой реальный HTTP-запрос завершения урока идёт через `card_lessons.py`/`lessons.py`/`grammar_quiz_lessons.py`/`vocabulary_lessons.py`, ни один из них не достигает `complete_lesson`, → функция и её XP-путь исполняются только в тестах, никогда в проде. Реальные XP за завершение уроков в проде идут через документированный в CLAUDE.md `maybe_award_curriculum_xp` / `LINEAR_XP` (другие источники, другие суммы: `linear_curriculum_card=20`, `_vocabulary`/`_grammar`=18 и т.д.) — `xp_curriculum_lesson=30` не входит в этот список, что подтверждает: это отдельная, не подключённая ветка XP. Понижаю severity до P3 относительно выданной (не P1/P2): пользователи ничего не теряют — реальное начисление XP идёт другим, рабочим путём (`maybe_award_curriculum_xp`), это чистый мёртвый код без наблюдаемого эффекта на прод.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/curriculum/service.py:177` — `def complete_lesson(user_id: int, lesson_id: int, score: float = 100.0) -> Optional[LessonProgress]:` — единственное определение в этом модуле.
  - `app/curriculum/service.py:263-266` — внутри `complete_lesson`: `from app.curriculum.xp import award_curriculum_lesson_xp_idempotent` + вызов `award_curriculum_lesson_xp_idempotent(user_id, lesson_id, get_user_local_date(user_id, db), db_session=db)` — единственный продакшн-вызов этого хелпера в кодовой базе (перепроверено grep'ом, других мест нет).
  - Ни один файл в `app/curriculum/routes/*.py` не импортирует `complete_lesson` из `app.curriculum.service`: `card_lessons.py:18-21` импортирует только `get_card_session_for_lesson, process_card_review_for_lesson`; `lessons.py:27-30` — только `process_final_test_submission, process_grammar_submission, process_quiz_submission`; `api.py:12` — только `get_card_session_for_lesson, get_cards_for_lesson`; `grammar_quiz_lessons.py:21` — только `get_next_lesson, process_quiz_submission`; `vocabulary_lessons.py:26` — только `get_next_lesson`.
  - Полнотекстовый grep `complete_lesson(` по всему `app/` вне определений — 0 совпадений (единственные текстовые упоминания идентификатора `complete_lesson` вне `service.py` — комментарий в `grading.py:50`, докстринги в `xp.py`/`time_utils.py`, и не связанный метод `daily_lessons.py:236`).
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-098.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** CLAUDE.md документирует только `LINEAR_XP`-источники (`app/daily_plan/linear/xp.py`) как актуальный XP-путь для curriculum-уроков; `xp_curriculum_lesson`/`CURRICULUM_LESSON_XP=30` в `app/curriculum/xp.py` нигде в CLAUDE.md не упомянут — согласуется с выводом, что это осиротевшая ветка, не часть документированного контракта.

#### DP-072 · P3 · `app/daily_plan/plan.py:466`

- **Кандидат:** `DP-C-103` · линзы-источники: ITEMS-E-06 · скептик: `skeptics/DP-C-103.md`
- **Симптом:** `plan_intensity`/`total_estimated_minutes` без живых консьюмеров; у graduated/blocked = 0 при 122–137 мин работы
- **Сценарий отказа:** механизм подтверждён буквально: у graduated/blocked-пользователя `total_estimated_minutes=0` и `plan_intensity='light'` в возвращаемом payload, при этом ни один живой код-путь (проверены все текстовые вхождения в `app/`) их не читает — единственное чтение (`study/routes.py:1060`) недостижимо из-за отсутствующего ключа `'slots'`, а hero-виджет и шаблон дублируют вычисление независимо от этих двух полей. Однако именно из-за отсутствия консьюмеров «вводящее в заблуждение значение 0» никогда не попадает пользователю на экран — наблюдаемого эффекта (неверный UI/уведомление) нет, что понижает severity с предполагаемого P1/P2 до P3: мёртвые расчётные поля без наблюдаемого эффекта.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/plan.py:437-441` — `total_estimated_minutes = sum(int(it.get('eta_minutes') or 0) for it in required_dicts if not it.get('completed'))`. Когда `graduated` (строка 397: `required_dicts = []`) или `spine_blocked` (required тоже пуст, см. комментарий строки 410-412 «A blocked spine leaves required empty just like graduation does»), сумма буквально 0 — при этом `optional` в этом же вызове осознанно строится «past the daily budget» (`build_optional(..., graduated=graduated or spine_blocked)`), т.е. реальный доступный контент может быть большим.
  - `app/daily_plan/plan.py:466` — `'plan_intensity': get_plan_intensity(total_estimated_minutes)`; `app/daily_plan/linear/plan.py:60-68` — `if minutes < 15: return 'light'` → для 0 минут вернёт `'light'`.
  - Возвращаемый dict `get_daily_plan` (строки 458-467) не содержит ключа `'slots'` нигде в файле (`grep -n "'slots'" app/daily_plan/plan.py` — 0 совпадений).
  - `app/study/routes.py:1049-1060` — единственное чтение поля `total_estimated_minutes` из этого dict защищено веткой `if today_plan and today_plan.get('slots'):` (строка 1049); поскольку ключа `'slots'` в payload нет, это условие всегда ложно — ветка с `estimated_minutes = today_plan.get('total_estimated_minutes', 0)` (строка 1060) недостижима (мёртвый код), выполняется `else` с `default_estimated`.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-103.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-073 · P3 · `app/words/routes.py:1085`

- **Кандидат:** `DP-C-109` · линзы-источники: ITEMS-E-13 · скептик: `skeptics/DP-C-109.md`
- **Симптом:** `challenge_card` требует `lesson_id`, у всех 84 строк `daily_challenges` он NULL → виджет не рендерится
- **Сценарий отказа:** механизм ровно такой, как описан: `_seed_today_challenge` никогда не заполняет `lesson_id` (комментарий про listening_deep — мёртвый текст, не отражённый кодом), поэтому `get_today_challenge(...).get('lesson_id')` всегда falsy, `challenge_card` всегда `None`, и правая rail-карточка «Бонусная цель дня» в `_dashboard_rail.html` (реально подключённой к `dashboard_unified.html`) не рендерится ни для одного пользователя ни в один день. Сценарий: вход — любой `user_id`, любая `challenge_date`; ожидаемый выход — карточка челленджа с бейджем `×N XP` и CTA на урок; фактический выход — секция полностью отсутствует в DOM, так как `_ch` пуст. Уточнение по scope: это НЕ полная поломка фичи daily-challenge — независимый билдер `app/daily_plan/items/challenge.py:build_challenge_item` использует тот же `get_today_challenge`, но НЕ требует `lesson_id` (резолвит целевой урок сам через fallback на next curriculum/listening lesson) и корректно попадает в секцию `optional` основного плана дня. Ломается конкретно правый rail-виджет на дашборде (второй, отдельный потребитель), а не весь daily-challenge механизм.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/words/routes.py:1085` — `if ch and ch.get('lesson_id'):` вокруг присвоения `challenge_card = {...}`; `challenge_card = None` инициализирован строкой выше и остаётся `None`, если условие не выполнено.
  - `app/daily_plan/challenge.py:31-33` — в `_seed_today_challenge`: `lesson_id: Optional[int] = None` с комментарием `# listening_deep accepts any listening attempt today — no specific lesson required.` — и дальше **никакой** веткой (ни для `speed_run`, ни для `accuracy_focus`, ни для `listening_deep`) `lesson_id` не переприсваивается перед `DailyChallenge(..., lesson_id=lesson_id, ...)` (строки 35-40). Это единственное место в кодовой базе, создающее строки `daily_challenges` (`grep DailyChallenge(` — одно совпадение).
  - `app/templates/components/_dashboard_rail.html:63` — `{% if _ch %}` (`_ch = challenge_card`, строка 17) — вся секция карточки-челленджа скрыта, если `challenge_card is None`.
  - `app/templates/words/dashboard_unified.html:64` — `{% include 'components/_dashboard_rail.html' %}` — виджет реально подключён к рендерящемуся unified-дашборду, не сирота.
  - SQL против `learn_db_prod` (копия прода): `SELECT count(*) AS total, count(lesson_id) AS with_lesson_id FROM daily_challenges;` → `total=84, with_lesson_id=0` — подтверждает, что все 84 сид-строки имеют `lesson_id IS NULL`.
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)


### Опровергнуто скептиками — не переоткрывать без новых фактов

| Кандидат | Якорь | Утверждение финдера | Почему опровергнуто |
|---|---|---|---|
| `DP-C-059` | `app/daily_plan/items/curriculum.py:214` | «первый done-today» (INV-18) выбирается по порядку id, а не по времени | механизм («сортировка по id») в коде действительно есть буквально, но он не приводит к описанному эффекту («неверный якорь по сравнению с временем») в достижимом сценарии. `id` — autoincrement PK, присваиваемый atomically при INSERT в той же транзакции, что и завершение урока; для штатного потока (последовательные HTTP-запросы одного пользователя) он монотонно совпадает с порядком по времени. Паттерн `StreakEvent.id… |
| `DP-C-061` (**INV-22**) | `app/daily_plan/items/curriculum.py:692` | мягкий блок «предыдущий модуль <80%» трактуется как hard-блок и выбрасывает остаток уровня | механизм каскада (680-693) существует, но не производит описанный эффект («ошибочно выбрасывает доступный контент»). Чтобы кандидат подтвердился, нужен сценарий: модуль N блокируется (шаг 4, `has_progress=False`), а более поздний модуль N+k того же уровня у того же пользователя реально доступен (`has_progress=True`). Но доступ к N+k в принципе недостижим без предварительного прохождения цепочки N, N+1, ... (шаг 4 тр… |
| `DP-C-065` | `app/daily_plan/linear/xp.py:326-353` | corrective-fallback `srs:global` срабатывает от счётчиков парного card-урока и запрещён для deck-quiz | механизм, который описывает кандидат («fallback запрещён для deck-quiz»), в коде есть и работает именно так, как заявлено, во всех достижимых путях: unified item-builder (`items/srs.py`) и snapshot-overlay (`snapshot.py`) явно передают `allow_fallback=False`, и докстринг в `xp.py` подробно объясняет зачем. Единственное место, где эта защита реально отсутствует (`linear/slots/srs_slot.py::_build_deck_quiz_slot`), нед… |
| `DP-C-067` | `app/study/services/srs_service.py:530` | баннер `/study/cards` считает лимит по базовому `new_words_per_day`, выдача — по adaptive | механизм расхождения источников (`get_card_counts` считает по базовому, `get_study_items` — по adaptive) в коде реально есть, но описанный эффект («баннер считает неверно») не наступает как пользовательский баг: (1) структурно `adaptive ≤ base` всегда (макс. процент в `TIER_PCT`/`BACKLOG_NEW_PCT` = 1.00), поэтому SSR-гейт `nothing_to_study` никогда не пропускает пользователя дальше adaptive-лимита и никогда ложно не… |
| `DP-C-071` | `app/telegram/queries.py:256` | третье определение «сегодня» (календарная UTC-полночь) + сырой бюджет в Telegram-плане | механизм (третья, календарно-UTC полночь + сырой бюджет без adaptive limits) присутствует буквально в указанных строках, но он мёртв в проде: ни планировщик (`app/telegram/scheduler.py`), ни хендлер бота (`app/telegram/bot.py`) эту функцию не вызывают — оба используют `get_daily_plan_for_telegram`, тонкую обёртку над каноническим `get_daily_plan_unified`. Функция `get_daily_plan` в `app/telegram/queries.py` — вестиг… |
| `DP-C-078` | `app/daily_plan/items/error_review.py:42` | `had_recent_failures` без временного окна: провалы полугодовой давности держат «острый» тир | фактическая посылка (отсутствие временного окна в `had_recent_failures`) верна, но заявленный эффект («бесконечно держит острый тир») не наступает: значение `'required'` из `determine_section` нигде не используется для построения required-секции плана — единственный consumer (`plan.py:308-312`) трактует `'required'` идентично любому не-`'optional'` результату и просто гасит итем (`return None`). «Острого тира» в тек… |
| `DP-C-081` | `app/books/reading_session.py:48` | норма чтения чередует 300/600 с по чётности числа месяца вопреки «300 с — единственное условие» | механизм чередования 300/600 в коде действительно есть, но это не дефект: коммит `57a7a998` явно вводит его как продуманную фичу («чередование 5/10 минут» с автопаузой на границе цели), единый хелпер `get_daily_reading_target_seconds` используется консистентно всеми потребителями (слот плана дня, XP-гейт, баннер, API), и тесты синхронизированы с той же функцией. Формулировка кандидата «вопреки контракту "300 с — еди… |
| `DP-C-082` | `app/daily_plan/items/grammar_review.py:82` | `_stalest_practiced_topic` ранжирует только практикованные темы — новая не всплывёт | заявленный эффект наступает только в узком нелитеральном прочтении («тема, которую юзер не тронул НИ разу ни через standalone, ни через курсовой grammar-урок, при этом уже практиковавший хоть что-то юзер»). Буквальная формулировка кандидата опровергается кодом: (1) `_level_fallback_topic` — специально существующий путь для показа непрактикованной темы при пустой истории; (2) union с `LessonAttempt` заводит новые тем… |
| `DP-C-088` | `app/daily_plan/linear/xp.py:51-61` | 8 типов уроков схлопнуты в один ключ `linear_curriculum_quiz` → 10 уроков за день дают одно начисление | формулировка кандидата фактически неточна (не 8, а 6 типов в этом конкретном бакете) и, что важнее, ложна как общее утверждение: у 26 lesson-type → 14 различных source-ключей, поэтому 10 уроков произвольных разных типов за день почти всегда дадут НЕСКОЛЬКО начислений, а не одно. Узкий реальный эффект — коллапс только внутри 6-элементной quiz-группы — в коде подтверждается (`_already_awarded` дедупит по source, не по… |
| `DP-C-094` | `app/daily_plan/linear/xp.py:194` | savepoint на `db_obj.session`, а `award_xp` пишет в глобальный `db.session` | механизм, который описывает кандидат («savepoint на одной сессии, запись `award_xp` — на другой»), в коде не существует. `db_obj` внутри `award_linear_slot_xp_idempotent` — либо явно переданный вызывающим `db` (всегда тот же модульный синглтон `app.utils.db.db`), либо, при `db_session=None`, тот же самый синглтон через fallback. `award_xp` внутри `with db_obj.session.begin_nested():` тоже делает `from app.utils.db i… |
| `DP-C-097` | `app/daily_plan/linear/xp.py:348` | `is_srs_slot_completed_today` пишет XP из read-пути | механизм побочной записи в read-пути действительно есть буквально, но это не необнаруженный баг, а осознанный, документированный (docstring + отдельный тест-файл со ссылкой на `docs/srs-fix-plan.md` Раздел 8), race-safe (`begin_nested`+`IntegrityError`) и идемпотентный (`_already_awarded` per `(user, date, source)`) компенсирующий механизм для случая «XP-событие потерялось между градацией карточки и завершением сесс… |
| `DP-C-104` | `app/daily_plan/items/srs.py:252` | SRS всегда «~8 мин» независимо от объёма | факт кода подтверждён буквально (ETA действительно фиксированная константа 8, не зависящая от `total_show`), но описанный эффект не является дефектом: это единообразный архитектурный паттерн, применённый ко ВСЕМ билдерам слотов плана дня (reading/listening/writing/speaking/error_review/curriculum/deck-quiz), а не специфичная для SRS ошибка. UI явно маркирует значение как приближение (`~N мин`), и производное `plan_i… |
| `DP-C-105` | `app/daily_plan/linear/plan.py:28` | `SLOT_ESTIMATED_MINUTES` не покрывает 6 из 13 `Kind`, дефолты консьюмеров расходятся (0 vs 10) | заявленная величина «6 из 13» не подтверждается кодом: единственный релевантный enum (`LinearSlotKind`) содержит 8, а не 13 значений, и `SLOT_ESTIMATED_MINUTES` покрывает 7 из них (пропущен только `challenge`). Более того, единственное место, где сумма по этому словарю реально влияет на продовый payload (`build_tomorrow_preview`/`get_linear_plan`), мёртвый код без единого вызова — расхождение дефолтов (`0` в `linear… |
| `DP-C-107` | `app/daily_plan/plan.py:296-320` | у заблокированного `graduated=True` доходит только до `build_srs_item`; очередь курса не строится | наблюдение кандидата о том, что `graduated` физически используется только в одной ветке (`build_srs_item`), верно буквально, но не является причиной отсутствия очереди: очередь гейтится отдельным сигналом (`required_curriculum_lesson_id`/`anchor_lesson`), который для блокированного юзера равен `None` по тому же механизму, что и для настоящего graduated, и для блокированного юзера в этом состоянии не существует НИ ОД… |
| `DP-C-108` | `app/reminders/routes.py:433` | превью «Сегодня в плане:» не различает required/optional и не дедуплицирует curriculum | оба факта в кандидате верны буквально (единый список без пометки бакета; `kind == 'curriculum'` явно исключён из дедупа), но ни один не является дефектом. (1) Отсутствие дедупа для curriculum — намеренное решение с комментарием в исходном коммите: required-урок и уроки continuation-очереди (`build_curriculum_queue`) — гарантированно разные `lesson_id` за счёт `exclude_lesson_ids`, так что показ нескольких curriculum… |

---

## Подзона: API и серверный рендер дашборда (Task 4)

### Таблица «ключ → значение в каждом источнике» (линза A)

Обязательный артефакт линзы A снят **фактическими вызовами** на копии прод-БД: пять источников
(`/api/daily-plan`, `/api/daily-status`, `/api/daily-plan/next-slot`, `/api/daily-plan/continuation`,
контекст SSR-дашборда) для одного и того же пользователя в одном и том же состоянии, на **11 классах
состояний** (норма, середина курса, новый юзер, пауза, graduated, заблокированный спайн, закрытый
день, частично закрытый день, аварийный fallback, клиентский `?tz=`, все значения `srs_limit_reason`).
Полные таблицы по каждому классу — `.ralphex/audit-notes/daily-plan/api-A-payload-divergence.md`.
Ниже — сводный список расхождений; на чистом классе U-NORM расхождений нет вовсе.

| # | Ключ | Кто расходится | Факт | Находка |
|---|---|---|---|---|
| 1 | `day_secured` | next-slot **True** vs остальные 4 **False** | graduated и заблокированный (`required==[]`) при нулевой активности за день | `DP-074` |
| 2 | `day_secured` | next-slot с `?current=<слот>` **True** vs остальные **False** | у next-slot семантика предсказательная («станет закрыт, когда добьёшь текущий слот»), у остальных — фактическая; ключ один и тот же | `DP-075` |
| 3 | «есть ли план» | next-slot и continuation ведут по плану; next-step отвечает `all_done`; три остальных источника — `mode=paused` | пауза видна 3 источникам из 6 | PLAUSIBLE `DP-C-111`; ветка next-step опровергнута (`DP-C-112`) |
| 4 | `_plan_meta.user_id` | `None` на paused- и fallback-ветках, `int` в норме | формально нарушение INV-05 | опровергнуто (`DP-C-009`): на обеих ветках `required` пуст, а `day_secured` там и так не считается по активности |
| 5 | 8 ключей контракта (`graduated`, `blocked_module`, `has_more_optional`, `total_estimated_minutes`, `plan_intensity`, `position`, `progress`, `module_progress`) | есть в норме, отсутствуют в paused и fallback | нарушение INV-39 | `DP-078` |
| 6 | `plan_paused` | только `/api/daily-status` (top-level) | 1 источник из 5 | входит в `DP-078` |
| 7 | `route_state`, `success` | только `/api/daily-plan` | 1 источник из 5 | опровергнуто (`DP-C-119`): служебные ключи, консьюмеров у них нет |
| 8 | `srs_limit_reason` | отдают 2 источника из 5, читают — **0** фронт-консьюмеров | ключ есть, потребителя нет | `DP-100` |
| 9 | `tomorrow_preview` | отсутствует во **всех** 5 источниках, включая закрытый день | INV-41 держится только на бумаге | `DP-023` |
| 10 | `streak`, `summary`, `yesterday` | `/api/daily-status?tz=` двигается клиентским tz, SSR-дашборд — нет | два ответа на один вопрос «какой сегодня день» | `DP-077` |
| 11 | `steps_total` | `0` при `has_next=true` (graduated / заблокированный / paused) | прогресс-бар не рендерится именно там, где он нужен | `DP-101` |
| 12 | «следующий шаг» | next-slot `phrase_review`, continuation `lesson`, next-step `phrase_review` | три независимых движка «что дальше» | наблюдение линзы; отдельной находкой не стало — расхождение объяснимо разной семантикой источников |
| 13 | персистентность состава дня | `daily-plan`/`daily-status`/`dashboard` коммитят снапшот, `next-slot`/`next-step` — нет | состав дня фиксирует случайный первый «пишущий» источник | `DP-076` |
| 14 | `plan_completion` для paused | 5 ключей легаси-формата при `steps_total=0` | — | опровергнут (`DP-C-012`) |

**Проверено, расхождений НЕТ** (важно не меньше найденных): повторный вызов набора без изменения
состояния даёт побайтово тот же результат на всех 11 классах; порядок вызовов (API-первым против
дашборд-первым) результат не двигает; состав `required`/`optional` идентичен во всех трёх
источниках, которые его отдают; `total_estimated_minutes` совпадает с `hero.minutes_left`; двойной
сборки плана в одном запросе нет — каждый источник зовёт сборщик ровно один раз.

### Индекс

| ID | Sev | Файл:строка | Симптом | Вериф. | Расхождение |
|---|---|---|---|---|---|
| DP-074 | P2 | `app/daily_plan/linear/lesson_context.py:180` | next-slot отдаёт `day_secured=true` graduated/blocked-юзеру при нулевой активности, 4 других источника — `false` | CONFIRMED | код |
| DP-075 | P2 | `app/daily_plan/linear/lesson_context.py:168` | `day_secured` в next-slot — предсказание, зависящее от `?current=`, при том же имени ключа, что факт в 4 других источниках | CONFIRMED | код |
| DP-076 | P2 | `app/api/daily_plan.py:606` | next-slot/next-step строят снапшот дня и не коммитят: состав дня определяет первый закоммитивший источник | CONFIRMED | код |
| DP-077 | P2 | `app/api/daily_plan.py:279` | `?tz=` двигает `streak`/`summary`/`yesterday`, а SSR-дашборд `tz` не принимает вовсе | CONFIRMED | код |
| DP-078 | P2 | `app/daily_plan/service.py:183` | paused payload теряет 11 ключей контракта, except-fallback — 8 | CONFIRMED | код |
| DP-079 | P2 | `app/api/daily_plan.py:738` | не-dict JSON-тело (`[1]`/`"s"`/`42`) → `AttributeError` → 500 на 6 POST-эндпоинтах из 8 | CONFIRMED | — |
| DP-080 | P2 | `app/words/routes.py:1810` | `/api/streak/repair-web`: `tz` не валидируется вовсе → 500 на любой неизвестной зоне | CONFIRMED | код |
| DP-081 | P2 | `app/api/daily_plan.py:760-775` | `/events`: три типовые путаницы дают 500 (`plan_date` не строка, `event_type` unhashable, `meta` не dict) | CONFIRMED | — |
| DP-082 | P2 | `app/api/daily_plan.py:48` | валидатор — `ZoneInfo`, потребители — `pytz`: `Factory`/`America/Coyhaique` проходят гейт и роняют обработчик | CONFIRMED | код |
| DP-083 | P2 | `app/api/daily_plan.py:1193` | `/streak/repair`: не-строковый `tz` из тела ломает сам `_validate_timezone` | CONFIRMED | — |
| DP-084 | P2 | `app/__init__.py:328-366` | глобальные JSON-обработчики покрывают только 403/404/500; 405 и werkzeug-400 отдают HTML под `/api/` | CONFIRMED | код |
| DP-085 | P2 | `app/__init__.py:420-430` | аноним на `/api/daily-plan/next-step` и `/api/streak/repair-web` получает 302 HTML вместо 401 JSON | CONFIRMED | код |
| DP-086 | P2 | `app/api/daily_plan.py:944-953` | `error_ids` без ограничения длины: 20 000 id = 20 003 SQL, 12.6 с воркера, HTTP 200 | CONFIRMED | — |
| DP-087 | P2 | `app/api/daily_plan.py:957-963` | пустой POST на `/error-review/complete` даёт +10 XP и `StreakEvent`: у graduated/blocked закрывает день | CONFIRMED | код |
| DP-088 | P2 | `app/api/daily_plan.py:1331-1348` | `/skip-lesson` принимает любой существующий `lesson_id` (INV-37) и сжигает квоту | CONFIRMED | код |
| DP-089 | P2 | `app/api/decorators.py:37-62` | 401 в форме `{success, error, status_code}` расходится с глобальным контрактом (INV-47) | CONFIRMED | код |
| DP-090 | P2 | `app/api/daily_plan.py:812-816` | blanket-`except` вокруг сборки плана отдаёт 400 «не текущий шаг» вместо ошибки БД | CONFIRMED | — |
| DP-091 | P2 | `app/words/routes.py:1722-1727` | `_next_step_from_unified` считает `skipped` выполненным → `all_done:true` при `0/1` и незакрытом дне | CONFIRMED | код |
| DP-092 | P2 | `app/daily_plan/plan.py:78-85` | один слот-пропуск помечает `skipped` все required-слоты того же `kind` — на intensive три сразу | CONFIRMED | код |
| DP-093 | P2 | `app/api/daily_plan.py:58-67` | `_UNIFIED_KIND_TO_PHASE` не знает `grammar_review` (0 route-шагов) и держит 3 несуществующих kind'а | CONFIRMED | код |
| DP-094 | P2 | `app/api/daily_plan.py:488-489` | `/api/daily-plan` объявляет `day_secured=True` и не пишет `secured_at` — третья поверхность закрытия дня | CONFIRMED | код |
| DP-095 | P2 | `app/words/routes.py:1234` | `@module_required('words')` только на `/dashboard`; 18 роутов зоны отдают тот же план и XP без модуля | CONFIRMED | код |
| DP-096 | P2 | `app/api/decorators.py:44-53` | тело эндпоинта исполняется внутри `except Exception` JWT-ветки → 500 маскируется под `401 Invalid or expired token` | CONFIRMED | код |
| DP-097 | P2 | `app/utils/rate_limit_helpers.py:16-18` | ключ лимитера — левый `X-Forwarded-For`, который nginx дописывает, а не перетирает | CONFIRMED | — |
| DP-098 | P2 | `app/api/decorators.py:43` | JWT-ветка зовёт `login_user()` и выдаёт сессионную куку на чистый API-вызов | CONFIRMED | код |
| DP-099 | P2 | `app/api/daily_plan.py:1023` | `/phrase-review/complete` читает flask-сессию → для JWT-клиента недостижим в принципе | CONFIRMED | код |
| DP-100 | P3 | `app/api/daily_plan.py:437` | `srs_limit_reason` есть в 2 источниках из 5 и не читается ни одним консьюмером | CONFIRMED | код |
| DP-101 | P3 | `app/words/routes.py:1705` | `steps_total=0` при `has_next=true` → прогресс-бар не рендерится у graduated/blocked (у paused тот же эффект, но через `has_next=false`) | CONFIRMED | код |
| DP-102 | P3 | `app/api/daily_plan.py:48` | `?tz=` длиной ≥256 → `OSError` мимо `except (KeyError, ValueError)` → 500 на 6 эндпоинтах | CONFIRMED | — |
| DP-103 | P3 | `app/api/daily_plan.py:738,1111,1328` | битый JSON молча становится `{}` и рапортуется как ошибка поля, а не `invalid_json` | CONFIRMED | код |
| DP-104 | P3 | `app/api/daily_plan.py:915-921` | `/api/error-review/summary` — единственный GET зоны без `success` в 200-теле | CONFIRMED | CLAUDE.md |
| DP-105 | P3 | `app/api/daily_plan.py:1361` | `LessonSkip` пишется и жрёт квоту, но его читатели (`linear/slots/curriculum_slot.py`) мертвы: снапшот не перестраивается, план показывает тот же урок | CONFIRMED | код |
| DP-106 | P3 | `app/api/daily_plan.py:748-755` | `/skip-lesson` не гейтится паузой, хотя `slot_skipped` гейтится | CONFIRMED | код |
| DP-107 | P3 | `app/api/daily_plan.py:694-709` | 7 из 9 `event_type` без продюсеров и консьюмеров — csrf-exempt запись под общим rate-limit'ом | CONFIRMED | — |
| DP-108 | P3 | `app/api/daily_plan.py:1056-1075` | `phrase_review_completed` — check-then-insert без уникальности | CONFIRMED | код |
| DP-109 | P3 | `app/words/routes.py:1024-1039` | нормализация completion — доказуемый no-op; INV-16 описывает эффект, которого не бывает | CONFIRMED | код |
| DP-110 | P3 | `app/daily_plan/linear/plan.py:196` | флаг `blocked` в unified не выставляет никто: 8 осиротевших читателей, ветка `_state='blocked'` мертва | CONFIRMED | код |
| DP-111 | P3 | `app/words/routes.py:1144-1156` | graduated видит одновременно «Откройте каталог, чтобы начать обучение» и «Завершите настройку ниже» | CONFIRMED | код |
| DP-112 | P3 | `app/achievements/streak_service.py:202` | `steps_available` — мёртвый элемент кортежа | CONFIRMED | — |
| DP-113 | P3 | `app/templates/partials/unified_daily_plan.html:46-69` | 4 словаря kind'ов, ни один не совпадает с фактическим набором; `word_set_quiz` не описан нигде | CONFIRMED | код |

### P0 — детали

_(находок этого уровня в подзоне нет)_


### P1 — детали

_(находок этого уровня в подзоне нет)_


### P2 — детали

#### DP-074 · P2 · `app/daily_plan/linear/lesson_context.py:180`

- **Кандидат:** `DP-C-110` · линзы-источники: API-A-01 · скептик: `skeptics/DP-C-110.md`
- **Симптом:** next-slot отдаёт `day_secured=true` graduated/blocked-юзеру при нулевой активности, 4 других источника — `false`
- **Сценарий отказа:** механизм есть буквально в коде: `_compute_day_secured` для `required=[]` (graduated/blocked, `app/daily_plan/plan.py:396-407`) возвращает `True` безусловно (`lesson_context.py:178-182`), не проверяя активность, тогда как параллельная и авторитетная реализация того же инварианта — `compute_day_secured_from_activity` (`app/daily_plan/service.py:47-71`) — для того же состояния плана требует `has_learning_activity` и при нулевой активности даёт `False`. Сценарий: graduated-юзер (или юзер с заблокированным спайном) без единой строчки активности за сегодня делает `GET /api/daily-plan/next-slot` (например, с `current=srs` до завершения сессии, либо вообще без параметров) → эндпоинт отвечает `day_secured: true`, тогда как в тот же момент `/api/daily-status`, основной payload `/api/daily-plan`, рендер дашборда и perfect-day-гейт для того же юзера дали бы `day_secured: false`. Оговорка добросовестности: все 3 реально подключённых JS-вызова (`applySrsPlanAwareCompletion`, `applyBookReadingPlanAwareToast`, `applyErrorReviewPlanAwareCompletion`) в нынешнем UI триггерятся уже ПОСЛЕ того, как соответствующее действие записало активность в один из 8 источников `has_learning_activity` — поэтому в проверенных живых сценариях наблюдаемое значение `day_secured` от `next-slot` обычно совпадает с авторитетным. Но сам эндпоинт — публичный `GET`, доступный в любой момент и не проверяющий, что активность действительно записана; расхождение — структурное свойство функции, а не гипотетическое. К данным это не приводит (`write_secured_at` из `next-slot` не вызывается), эффект ограничен UI: ложный редирект на `/dashboard?day_secured=1`, ложный баннер «День сохранён» и снятие плана из отслеживания (`clear()`) до того, как форсированные optional-пункты (SRS/reading/grammar_review) реально пройдены.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/lesson_context.py:178-188` — `_compute_day_secured`: ```python incomplete = [slot for slot in baseline_slots if not slot.get('completed')] if not incomplete: return True ``` `baseline_slots = required` (строка 274: `baseline_slots = required`). Функция не знает про `has_learning_activity` и не принимает `user_id` — при пустом `required` она возвращает `True` безусловно, независимо от какой-либо реальной активности за день.
  - Прямой прогон без БД: ``` $ python3 -c "from app.daily_plan.linear.lesson_context import _compute_day_secured; print(_compute_day_secured([], None, None))" True ```
  - `app/daily_plan/plan.py:396-398` — `if graduated: required_dicts = []`; `spine_blocked` тоже даёт `required=[]` (комментарий строк 405-407: «A blocked spine leaves required empty just like graduation does»). Значит `baseline_slots` в `lesson_context.py` пуст именно для graduated/blocked-юзера — ровно тот кейс, который называет кандидат.
  - _(ещё 4 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-110.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — `app/daily_plan/linear/lesson_context.py` (`_compute_day_secured`) реализует тот же инвариант «day_secured пересчитывается из активности API-слоем», что описан в CLAUDE.md («day_secured. Всегда False на assembly time; API пересчитывает из активности через compute_plan_steps + compute_day_secured_from_activity»), но независимой веткой логики, которая для `required=[]` эту активность не проверяет вовсе.

#### DP-075 · P2 · `app/daily_plan/linear/lesson_context.py:168`

- **Кандидат:** `DP-C-113` · линзы-источники: API-A-04 · скептик: `skeptics/DP-C-113.md`
- **Симптом:** `day_secured` в next-slot — предсказание, зависящее от `?current=`, при том же имени ключа, что факт в 4 других источниках
- **Сценарий отказа:** механизм найден в коде (`_compute_day_secured` игнорирует `has_learning_activity` там, где `compute_day_secured_from_activity` явно её требует), воспроизводится детерминированным сценарием (два реальных эндпоинта, один ключ `day_secured`, противоположные значения для одного пользователя/момента), и ровно 4 независимых места кода экспонируют `day_secured` как факт под тем же именем ключа, как утверждает кандидат. Понижаю до P2 (не P1), поскольку узнаваемый user-visible эффект ограничен подмножеством пользователей (graduated/blocked) и текущие JS call-sites гейтят вызов next-slot реальным сигналом завершения, так что типовой путь не показывает разбежавшийся баннер — но сам HTTP-контракт объективно противоречив и пригоден для будущих регрессий (новый consumer, который наивно доверится `next-slot.day_secured` как факту, получит неверные данные).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/lesson_context.py:173` — docstring `_compute_day_secured`: `"""Predict `day_secured` after this lesson is completed. ..."""` — сам код называет это предсказанием.
  - `app/daily_plan/linear/lesson_context.py:179-186`: ```python incomplete = [slot for slot in baseline_slots if not slot.get('completed')] if not incomplete: return True if slot_param and any(_is_current_slot(s, slot_param, current_lesson_id) for s in incomplete): return len(incomplete) <= 1 return False ``` Результат явно зависит от `slot_param` — параметра `?current=` в next-slot API (`app/api/daily_plan.py:626` — `slot_param=current_kind_raw`, `current_kind_raw = request.args.get('current')`).
  - `app/daily_plan/linear/lesson_context.py:280` (`build_lesson_context`) — `baseline_slots = required` (сырой `plan.get('required')` из `get_daily_plan` — **не** через `compute_plan_steps`/`plan_completion`); при `required == []` (graduated или заблокированный спайн) `_compute_day_secured` возвращает `True` **безусловно**, без проверки реальной активности.
  - _(ещё 5 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-113.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код | CLAUDE.md | код — CLAUDE.md документирует `compute_day_secured_from_activity` как единственный источник реального `day_secured` ("day_secured. Всегда False на assembly time; API пересчитывает из активности через compute_plan_steps + compute_day_secured_from_activity"), но не упоминает, что `next-slot`/`daily_plan_ctx` используют отдельный, менее строгий предиктор под тем же именем поля — расхождение между документированным инвариантом и фактическим кодом `_compute_day_secured`.

#### DP-076 · P2 · `app/api/daily_plan.py:606`

- **Кандидат:** `DP-C-114` · линзы-источники: API-A-05 · скептик: `skeptics/DP-C-114.md`
- **Симптом:** next-slot/next-step строят снапшот дня и не коммитят: состав дня определяет первый закоммитивший источник
- **Сценарий отказа:** механизм ровно такой, как заявлено, и он не гипотетический: разработчики сами описали и залатали его в одном месте (`_render_unified_dashboard`), но `daily_plan_next_slot` (api/daily_plan.py:606, якорь функции — по смыслу верный) и `daily_plan_next_step` (words/routes.py:1680) тот же путь сборки (`get_daily_plan`→`resolve_snapshot_for_today`) не коммитят. Сценарий: пользователь весь день взаимодействует с уроками через deep-link (`?from=linear_plan`) и завершающий экран (`fetchNextSlot`/`next-step`), ни разу не загружая `/dashboard`. Каждый вызов `next-slot`/`next-step` создаёт `DailyPlanLog` строку и пишет в неё свежепостроенный `plan_json` (flush), но транзакция откатывается на teardown запроса — строка не переживает запрос. Если между двумя такими вызовами меняется входное состояние (`find_next_lesson_state`, `compute_user_tier` — тир считается по активности, см. `app/daily_plan/tier.py`), пересчитанный `required` состав может отличаться от предыдущего вызова: «замороженный на день» контракт из docstring `snapshot.py` («Required composition is fixed for the day») не выполняется для этого пользовательского пути — состав фактически фиксируется только тем запросом, который первым дойдёт до `_render_unified_dashboard` (или другого коммитящего пути) и о моменте посещения дашборда никак не привязан к моменту первого ассемблинга дня. Severity — P2, не P1: `day_secured` пересчитывается независимо от факта персиста снапшота (`compute_day_secured_from_activity` читает реальную активность, а не `plan_json`), поэтому закрытие дня/streak/XP не ломается. Ломается более узкая гарантия — «состав required заморожен на день» — и она самовосстанавливается при первом заходе на дашборд (обходной путь есть). Наблюдаемый эффект требует специфичного тайминга (два вызова next-slot/next-step до первого визита в дашборд И изменение входных данных между ними), поэтому не P1.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/snapshot.py:14-16` — docstring: «Writes go through `_get_or_create_log_row` — flush-only, race-safe... Persistence is flush-only... the caller commits.»
  - `app/daily_plan/snapshot.py:107-111` — `_get_or_create_log_row(...)`; при отсутствии валидного снапшота: `log.plan_json = fresh; db.session.flush()` — только flush, без commit.
  - `app/daily_plan/plan.py:399-406` — `get_daily_plan()` (вызывается из `get_daily_plan_unified` и напрямую из `build_lesson_context`) при `not graduated` зовёт `resolve_snapshot_for_today(...)`, то есть пишет снапшот на КАЖДОМ ассемблинге плана.
  - `app/daily_plan/linear/lesson_context.py:230-236` — `build_lesson_context()` вызывает `get_unified_plan(user_id, db)` (алиас `get_daily_plan`), то есть триггерит запись снапшота.
  - `app/api/daily_plan.py:604-655` — `daily_plan_next_slot()` вызывает `build_lesson_context(...)` и сразу `return jsonify(payload)`; ни одного `db.session.commit()` в теле функции (проверено построчно, `grep commit()` в файле даёт совпадения на 96/377/599/856/... — ни одного внутри диапазона 604-655).
  - `app/words/routes.py:1678-1692` — `daily_plan_next_step()` вызывает `get_daily_plan_unified(...)` и делегирует в `_next_step_from_unified`; в диапазоне 1678-1773 нет `db.session.commit()` (греп `commit()` по файлу даёт строки 425/1016/1069/1818 — все вне этого диапазона).
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-114.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — `app/daily_plan/snapshot.py` документирует инвариант «Required composition is fixed for the day», а `daily_plan_next_slot`/`daily_plan_next_step` его нарушают тем же классом бага, который уже явно описан и починен комментарием в соседнем `_render_unified_dashboard`.

#### DP-077 · P2 · `app/api/daily_plan.py:279`

- **Кандидат:** `DP-C-115` · линзы-источники: API-A-06 · скептик: `skeptics/DP-C-115.md`
- **Симптом:** `?tz=` двигает `streak`/`summary`/`yesterday`, а SSR-дашборд `tz` не принимает вовсе
- **Сценарий отказа:** механизм воспроизводим прямо сейчас без специальных условий: авторизованный пользователь открывает `GET /api/daily-status?tz=Pacific/Kiritimati` (UTC+14) и видит `summary`/`yesterday`/`plan.day_secured`, посчитанные с чужой границей суток, тогда как тот же самый пользователь на `GET /dashboard` в той же сессии всегда получает значения, посчитанные строго по `current_user.timezone` — SSR-путь физически не может получить другой `tz`, потому что `request.args` там не читается. Формулировка «двигает» подтверждена буквально: `_user_day_boundaries(tz)` меняет диапазон фильтров запросов в `get_daily_summary`/`get_yesterday_summary`. Оговорка: в текущем фронтенде (JS/templates) нет ни одного вызова, который реально передавал бы отличный от `current_user.timezone` `tz` в эти GET-эндпоинты — расхождение сегодня не проявляется само по себе через штатный UI, но конечный пользователь может вызвать его вручную через URL, и это уже покрыто юнит-тестами как часть контракта API. Write-критичные пути (монета/plan_completed/route-steps) от этой развилки не страдают — они явно защищены отдельной привязкой к `User.timezone`, что и понижает эффект с «порчи данных» до «расхождения отображаемых данных между двумя поверхностями».
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:278` — `tz = _validate_timezone(request.args.get('tz', current_user.timezone or DEFAULT_TZ))`, дальше `plan = get_daily_plan_unified(user_id, tz=tz)`, `summary = get_daily_summary(user_id, tz=tz)`, `yesterday = get_yesterday_summary(user_id, tz=tz)` (строки 282-284) — любой аутентифицированный клиент может передать произвольный IANA tz через query string и сдвинуть границы «сегодня»/«вчера».
  - `app/words/routes.py:1236-1243` — `dashboard()`: `tz = current_user.timezone or DEFAULT_TIMEZONE` — `request.args` вообще не читается в этой функции; `_render_unified_dashboard(tz)` получает только серверное значение.
  - `app/telegram/queries.py:1069` (`get_daily_summary`) и `:1220` (`get_yesterday_summary`) — оба реально используют `tz` для `_user_day_boundaries(tz, ...)`, т.е. параметр не косметический — он двигает границы дня и, соответственно, набор попадающих в выборку записей.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-115.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — раздел CLAUDE.md «User-local date» декларирует `get_user_local_date`/`User.timezone` единственным источником «today» для XP dedup, и код это соблюдает для записи; но для *чтения* (`summary`/`yesterday`/displayed `day_secured` в `/api/daily-status`) API допускает альтернативный источник границы дня через query-param, которого SSR-путь не имеет вовсе — асимметрия между двумя поверхностями одного и того же плана дня.

#### DP-078 · P2 · `app/daily_plan/service.py:183`

- **Кандидат:** `DP-C-116` · линзы-источники: API-A-07 · скептик: `skeptics/DP-C-116.md`
- **Симптом:** paused payload теряет 11 ключей контракта, except-fallback — 8
- **Сценарий отказа:** механизм реален и воспроизводим по коду: paused-payload на якоре `service.py:183` действительно теряет бóльшую часть ключей нормального контракта, и ни один шаблон/сервис не восстанавливает `paused`-специфичный UI на главном дашборде (юзер видит пустой план без объяснения «на паузе»). Но заявленное число **неточное**: относительно нормального payload paused-ветка теряет **11** ключей, а не 8. Число «8» совпадает с другой веткой той же функции — except-fallback (`service.py:212-219`), у которой действительно ровно 8 отсутствующих ключей (`position, progress, module_progress, total_estimated_minutes, plan_intensity, has_more_optional, graduated, blocked_module`). Кандидат смешал две разные ветки под одной цифрой. Эффект некритичный: все известные потребители используют `.get()` с дефолтами, падений (500/крашей шаблона) не найдено — это тихая деградация UX/контракта, не потеря данных.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/plan.py:456-470` — нормальный `unified` payload содержит 13 ключей: `mode, position, progress, module_progress, required, optional, setup, day_secured, total_estimated_minutes, plan_intensity, has_more_optional, graduated, blocked_module`.
  - `app/daily_plan/service.py:183-190` (якорь) — paused-payload содержит ровно 3 ключа: `mode, paused_until, day_secured`. Относительно нормального payload отсутствуют **11**, не 8: `position, progress, module_progress, required, optional, setup, total_estimated_minutes, plan_intensity, has_more_optional, graduated, blocked_module`.
  - `app/daily_plan/service.py:212-219` — соседний except-fallback payload (другая ветка той же функции, другая строка) содержит `mode, required, optional, setup, day_secured` — 5 ключей, отсутствуют **8**: `position, progress, module_progress, total_estimated_minutes, plan_intensity, has_more_optional, graduated, blocked_module`. Именно здесь число «8» точное — но это не paused-ветка, на которую указывает якорь.
  - `app/templates/partials/unified_daily_plan.html:2-10` — реальный контракт потребителя: ровно 9 `unified_plan.get(...)` вызовов (`position, progress, module_progress, required, optional, setup, has_more_optional, day_secured, blocked_module`), все со strict-фолбэками (`or {}` / `or []` / `false`) — падений (`KeyError`/`UndefinedError`) нет ни для paused, ни для fallback payload.
  - _(ещё 4 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-116.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — формулировка кандидата смешивает paused-ветку (11 потерянных ключей) и fallback-ветку (8 потерянных ключей) под одним числом; CLAUDE.md не описывает контракт paused-payload отдельно.

#### DP-079 · P2 · `app/api/daily_plan.py:738`

- **Кандидат:** `DP-C-120` · линзы-источники: API-B-01, API-C-04 · скептик: `skeptics/DP-C-120.md`
- **Симптом:** не-dict JSON-тело (`[1]`/`"s"`/`42`) → `AttributeError` → 500 на 6 POST-эндпоинтах из 8
- **Сценарий отказа:** CONFIRMED, но с исправленным числом. Механизм реален: `request.get_json(silent=True)` возвращает JSON-значение любого типа (не только dict), `or {}` подставляет дефолт только при falsy-значении (`None`, `{}`, `[]`, `""`, `0`), поэтому `[1]`/`"s"`/`42` — все truthy — проходят как есть, и последующий `.get(...)` кидает `AttributeError`, необработанный внутри вьюхи → 500 у клиента. Сценарий: клиент шлёт `POST /api/plan/pause` с `Content-Type: application/json` и телом `42` → `body = 42` → `body.get('days')` → `AttributeError: 'int' object has no attribute 'get'` → 500 (подтверждено прогоном). Но заявленное число «8 из 9» не подтверждается: фактически из 8 POST-роутов в файле поражены **6** (`daily-plan/events`, `daily-plan/error-review/complete`, `plan/pause`, `streak/repair`, `daily-plan/challenge/complete`, `daily-plan/skip-lesson`), а `phrase-review/complete` и `plan/resume` не поражены по описанным выше причинам (session-guard раньше парсинга; тело вообще не читается). Severity понижена с потенциального P1 до P2: это не потеря данных и не постоянная порча состояния — 500 возвращается ДО любых `db.session.add/commit` в каждом поражённом обработчике (проверено по коду выше по потоку), обхода для легитимного клиента нет вреда (все легитимные клиенты шлют dict), но любой сканер/баг в клиентском JS, отправивший не-dict тело, получит непойманное необработанное исключение и шумный traceback в логах вместо чистого `400 invalid_json`.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:738-739` (`record_daily_plan_event`) — `body = request.get_json(silent=True) or {}` → `event_type = body.get('event_type', '')`. Замер: `[1]`/`"s"`/`42` → 500.
  - `app/api/daily_plan.py:944-945` (`complete_error_review`) — `body.get('error_ids')` сразу после парсинга. Замер: 500/500/500.
  - `app/api/daily_plan.py:1111-1112` (`plan_pause`) — `body.get('days')` сразу после парсинга. Замер: 500/500/500.
  - `app/api/daily_plan.py:1193` (`streak_repair`) — `(request.get_json(silent=True) or {}).get('tz', DEFAULT_TZ)` инлайново. Замер: 500/500/500.
  - `app/api/daily_plan.py:1224-1225` (`challenge_complete`) — `body.get('challenge_id')`. Замер: 500/500/500.
  - `app/api/daily_plan.py:1328-1329` (`skip_lesson`) — `body.get('lesson_id')`. Замер: 500/500/500.
  - **Опровергающий факт №1** — `app/api/daily_plan.py:1027-1029` (`complete_phrase_review`): до парсинга тела стоит `items = session.get('daily_phrase_review_items'); if not isinstance(items, list) or not items: return api_error('phrase_review_expired', ..., 400)`. В свежей/нетипичной сессии (нет активного phrase-review) этот guard всегда отсекает запрос раньше `body.get('answers')` кодом `400`, а не `500`. Замер: `[1]`/`"s"`/`42`/`{}` → все 400.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-120.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-080 · P2 · `app/words/routes.py:1810`

- **Кандидат:** `DP-C-122` · линзы-источники: API-B-03, API-E-06 · скептик: `skeptics/DP-C-122.md`
- **Симптом:** `/api/streak/repair-web`: `tz` не валидируется вовсе → 500 на любой неизвестной зоне
- **Сценарий отказа:** механизм найден и воспроизведён по коду и живым прогоном. Сценарий: аутентифицированный клиент шлёт `POST /api/streak/repair-web` с телом `{"tz": "<любая невалидная IANA-зона>"}` (или любой не-IANA строкой — сокращения вида `"GMT+3"`, опечатка, устаревшее имя зоны и т.д.) → `pytz.timezone(tz)` на `streak_service.py:871` бросает `UnknownTimeZoneError` → неперехваченное исключение → в проде `@app.errorhandler(500)` конвертирует его в HTTP 500 с JSON `{'error': 'internal_error'}` для этого пользователя; попытка починить streak проваливается без внятной причины (нет DB-записи о попытке, `apply_paid_repair` до него даже не доходит — данные не портятся, но и монеты/repair не списываются). Фронтенд-вызывающего кода в репозитории не найдено (JS, отправляющий `tz` на этот эндпоинт, не обнаружен ни в `app/static`, ни в `app/templates`) — это ограничивает вероятность естественного триггера от штатного UI, но не опровергает сам дефект: эндпоинт публично адресуем для любого залогиненного пользователя/API-клиента, контракт входа не документирует и не enforce'ит формат `tz`. Severity понижена до P2 (не P1): ключевого пользовательского сценария массово это не ломает (нет находки в UI-коде, что реальные пользователи вообще посылают невалидный `tz`), данные не портятся (коммит происходит только после успешного `apply_paid_repair`, до которого выполнение не доходит), обход тривиален — не слать `tz` вовсе (сработает дефолт) или слать валидную IANA-строку.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/words/routes.py:1810` — `tz = request.json.get('tz', DEFAULT_TIMEZONE) if request.is_json else DEFAULT_TIMEZONE` — значение берётся из тела запроса без какой-либо проверки формата/принадлежности к IANA tz database.
  - `app/words/routes.py:1812` — `missed = find_missed_date(current_user.id, tz=tz)` — сырой `tz` передаётся дальше без нормализации.
  - `app/achievements/streak_service.py:871` — `local_now = datetime.now(pytz.timezone(tz))` — первая же строка `find_missed_date` строит `pytz.timezone(tz)` из непроверенной строки.
  - `pytz.timezone('Not/AZone')` детерминированно бросает `pytz.exceptions.UnknownTimeZoneError` (проверено `python3 -c` вне контекста Flask).
  - В `streak_repair_web` нет `try/except` вокруг вызова `find_missed_date` — исключение всплывает из view-функции необработанным.
  - `app/__init__.py:350-364` — `@app.errorhandler(500)` перехватывает любое неперехваченное исключение из view и для JSON-клиентов (`_wants_json()`) отдаёт `{'success': False, 'error': 'internal_error', ...}` со статусом **500** — то есть в проде эффект именно «500», как заявлено в кандидате.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-122.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — отсутствует валидация пользовательского `tz` перед передачей в `pytz.timezone()`, что нарушает общий паттерн проекта «валидировать пользовательский ввод перед использованием» (см. `validate_enum`/`get_enum_arg` в `app/utils/validators.py` и `app/admin/utils/request_validators.py`), но сам инвариант CLAUDE.md явно для этого эндпоинта не описан.

#### DP-081 · P2 · `app/api/daily_plan.py:760-775`

- **Кандидат:** `DP-C-123` · линзы-источники: API-B-04, API-B-05, API-B-06 · скептик: `skeptics/DP-C-123.md`
- **Симптом:** `/events`: три типовые путаницы дают 500 (`plan_date` не строка, `event_type` unhashable, `meta` не dict)
- **Сценарий отказа:** все три сценария дают неперехваченное исключение (`TypeError`/`TypeError`/`AttributeError`) внутри `record_daily_plan_event`, которое долетает до глобального `@app.errorhandler(500)` и возвращает клиенту 500 вместо ожидаемого `400 invalid_event_type`/аккуратной нормализации даты/меты. Сценарий: `POST /api/daily-plan/events` с телом `{"event_type": ["x"]}` → `TypeError` на `in` (строка 741); `{"event_type": "vocab_lookup", "plan_date": 123}` → `TypeError` в `fromisoformat` (строка 768); `{"event_type": "vocab_lookup", "meta": [1]}` → `AttributeError` на `meta.get()` (строка 775). Это telemetry-эндпоинт (Phase 1 H1 measurement), не участвует в закрытии дня/XP — деградация ограничена шумом в логах/500 у клиента, есть обход (клиент просто не шлёт кривые типы), затрагивает не все сценарии.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:741` — `if event_type not in _CLIENT_EVENTS:` где `_CLIENT_EVENTS` — `set` (строки 699–708). Если `event_type` из тела запроса — unhashable (`list`/`dict`), оператор `in` над `set` бросает `TypeError: unhashable type: 'list'` до входа в `except`-ветки — исключение ничем не перехвачено → 500. Воспроизведено: `[1,2] in {'a','b'}` → `TypeError: cannot use 'list' as a set element (unhashable type: 'list')`.
  - `app/api/daily_plan.py:766-772` — ``` plan_date_str = body.get('plan_date') if plan_date_str: try: plan_date = date_cls.fromisoformat(plan_date_str) ... except ValueError: plan_date = user_today ``` `except` ловит только `ValueError`. Если `plan_date_str` — не строка (например `int`/`list`), `date.fromisoformat(...)` бросает `TypeError`, который не перехватывается и всплывает как 500. Воспроизведено: `date.fromisoformat(12345)` → `TypeError: fromisoformat: argument must be str`.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-123.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-082 · P2 · `app/api/daily_plan.py:48`

- **Кандидат:** `DP-C-124` · линзы-источники: API-B-07 · скептик: `skeptics/DP-C-124.md`
- **Симптом:** валидатор — `ZoneInfo`, потребители — `pytz`: `Factory`/`America/Coyhaique` проходят гейт и роняют обработчик
- **Сценарий отказа:** механизм найден и воспроизведён по коду. Сценарий: аутентифицированный клиент шлёт `GET /api/streak?tz=Factory` (или `America/Coyhaique` — реальная IANA-зона Чили, валидная и для `ZoneInfo`, но отсутствующая в бандле `pytz`). `_validate_timezone` пропускает значение как есть → `get_streak_status(user_id, tz='Factory')` → `find_missed_date` → `pytz.timezone('Factory')` кидает `UnknownTimeZoneError` без перехвата → эндпоинт отдаёт 500 (`app/__init__.py:350` глобальный `errorhandler(500)`) вместо streak-статуса. Тот же механизм частично достижим и из `/api/daily-status` через `process_streak_on_activity:394` (условный, не перехвачен), но не через соседний `auto_heal_streak_on_activity` (тот перехвачен `try/except`). Downgrade до P2, а не P1: `User.timezone` из профиля ограничен белым списком `TIMEZONE_CHOICES` (14 обычных зон, экзотика туда не попадёт), а текущий встроенный JS-клиент не передаёт `?tz=` вовсе — живого пути эксплуатации обычным пользователем через штатный UI не найдено. Но код-контракт объективно нарушен: публичный query-параметр `tz` документирован в докстринге как принимающий таймзону, гейт формально валиден, а часть потребителей падает на валидных значениях — расхождение гарантий, воспроизводимое любым прямым HTTP-вызовом.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:45-51` — гейт `_validate_timezone` валидирует только через `ZoneInfo`.
  - `app/achievements/streak_service.py:871` — `local_now = datetime.now(pytz.timezone(tz))` без try/except внутри `find_missed_date`.
  - `app/achievements/streak_service.py:925` — тот же паттерн без try/except внутри `find_auto_heal_date`.
  - `app/achievements/streak_service.py:1269` — `get_streak_status` безусловно зовёт `find_missed_date(user_id, tz=tz)`.
  - `app/api/daily_plan.py:533-538` — view `streak()` не имеет своего try/except вокруг `get_streak_status(user_id, tz=tz)`.
  - Репро: `pytz.timezone('Factory')` → `pytz.exceptions.UnknownTimeZoneError: 'Factory'`, при этом `ZoneInfo('Factory')` успешен.
- **Где расхождение:** код — два независимых консьюмера таймзоны (`app/telegram/queries.py`/бо́льшая часть `streak_service.py` защищены try/except; `find_missed_date`/`find_auto_heal_date` в том же файле — нет), а гейт-валидатор использует другую библиотеку (`ZoneInfo`), чем незащищённые потребители (`pytz`). В CLAUDE.md конвенция по таймзонам не описана.

#### DP-083 · P2 · `app/api/daily_plan.py:1193`

- **Кандидат:** `DP-C-125` · линзы-источники: API-B-08 · скептик: `skeptics/DP-C-125.md`
- **Симптом:** `/streak/repair`: не-строковый `tz` из тела ломает сам `_validate_timezone`
- **Сценарий отказа:** механизм воспроизводим по коду и живым прогоном интерпретатора. Сценарий: аутентифицированный клиент шлёт `POST /api/streak/repair` с телом `{"tz": null}` (или любым не-строковым значением по ключу `tz`, включая `123`, `[]`, `{}`, `true`) → `.get('tz', DEFAULT_TZ)` возвращает это значение как есть (default в `.get` не срабатывает, т.к. ключ присутствует) → `_validate_timezone` вызывает `ZoneInfo(<не-строка>)` → `TypeError` не пойман (ловятся только `KeyError`/`ValueError`) → исключение всплывает из `streak_repair`, перехватывается только общим `@app.errorhandler(500)`. Результат — вместо документированного поведения «невалидный tz → тихий откат на `DEFAULT_TZ`» клиент получает `500 internal_error`, ремонт стрика для этого запроса не происходит (хотя денежная/купонная операция `apply_paid_repair` в этом сценарии ещё не вызвана — до неё дело не доходит, данные не портятся). Ограничитель серьёзности: обычный клиент (JS `Intl.DateTimeFormat(). resolvedOptions().timeZone`) всегда пришлёт строку, и найденного в репозитории фронтенд-потребителя у этого JSON-эндпоинта нет вовсе — эффект достижим только нестандартным/сторонним клиентом или намеренно неправильным телом запроса, не в штатном UI-сценарии.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:45-51`: ```python def _validate_timezone(tz_name: str) -> str: try: ZoneInfo(tz_name) return tz_name except (KeyError, ValueError): return DEFAULT_TZ ``` Ловит только `KeyError`/`ValueError` — не `TypeError`.
  - `app/api/daily_plan.py:1193`: ```python tz = _validate_timezone((request.get_json(silent=True) or {}).get('tz', DEFAULT_TZ)) ``` `.get('tz', DEFAULT_TZ)` отдаёт дефолт только если ключ `tz` **отсутствует**; если тело — `{"tz": null}` или `{"tz": 123}` (валидный JSON, ключ присутствует), `.get` вернёт `None`/`123` дословно, и в `_validate_timezone` попадёт не-строка.
  - Проверка живым интерпретатором: `ZoneInfo(None)` → `TypeError: expected str, bytes or os.PathLike object, not NoneType`; `ZoneInfo(123)` → аналогичный `TypeError`. Оба не пойманы веткой `except (KeyError, ValueError)`.
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-084 · P2 · `app/__init__.py:328-366`

- **Кандидат:** `DP-C-126` · линзы-источники: API-B-09 · скептик: `skeptics/DP-C-126.md`
- **Симптом:** глобальные JSON-обработчики покрывают только 403/404/500; 405 и werkzeug-400 отдают HTML под `/api/`
- **Сценарий отказа:** механизм отказа существует буквально: `app/__init__.py` регистрирует `errorhandler` только для 403/404/500 (и отдельно `CSRFError`), для 400 и 405 обработчика нет вообще, поэтому Flask/werkzeug отдают дефолтную HTML-страницу под любым путём, включая `/api/*`. Сценарий вход→неверный выход: клиент (JS или внешний API-консьюмер) шлёт POST с невалидным JSON-телом на `/api/words/...` (использует `request.get_json()` без `silent=True` — `app/api/words.py:197` и др.) или дергает существующий `/api/...` роут не тем HTTP-методом — вместо документированного в CLAUDE.md контракта `{'success': False, 'error': <slug>, 'message': ..., 'status': <int>}` получает `text/html` с телом `<!doctype html>...`. Часть фронтенд-кода (`main.js:605`) при этом падает на `response.json()` (SyntaxError), хоть и гасится вышестоящим `.catch`.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/__init__.py:328` — `@app.errorhandler(403)`
  - `app/__init__.py:339` — `@app.errorhandler(404)`
  - `app/__init__.py:350` — `@app.errorhandler(500)`
  - Отсутствуют `@app.errorhandler(400)` и `@app.errorhandler(405)` — grep по всему `app/` не находит ни одного совпадения.
  - Runtime: `POST /api/daily-plan/next-step` → `405 text/html; charset=utf-8`, `b'<!doctype html>...<h1>Method Not Allowed</h1>...'`.
  - Runtime: `GET /api/_probe400` (после `abort(400)`) → `400 text/html; charset=utf-8`, `b'<!doctype html>...<h1>Bad Request</h1>...'` — воспроизводится и с заголовком `Accept: application/json`, т.е. `_wants_json()`-логика (`app/__init__.py:319-326`) в принципе бы сработала, но для 400/405 её некому вызвать — нет обработчика.
- **Где расхождение:** код — CLAUDE.md прямо заявляет «Global HTTP error JSON… для JSON clients (`/api/`, XHR, `Accept: application/json`)» и перечисляет только slugs `forbidden/not_found/internal_error` (403/404/500) — сам документ не обещает 400/405, но заявленный общий принцип «для JSON-клиентов JSON» на практике покрывает не все HTTP-статусы, которые реально возникают под `/api/`.

#### DP-085 · P2 · `app/__init__.py:420-430`

- **Кандидат:** `DP-C-127` · линзы-источники: API-B-10, API-E-05 · скептик: `skeptics/DP-C-127.md`
- **Симптом:** аноним на `/api/daily-plan/next-step` и `/api/streak/repair-web` получает 302 HTML вместо 401 JSON
- **Сценарий отказа:** механизм воспроизведён напрямую через `test_client()`: анонимный (или с истёкшей сессией) запрос к обоим `/api/...` эндпоинтам действительно получает `302 text/html` вместо `401 application/json`, потому что `unauthorized_handler` не использует тот же `_wants_json()`-контракт (`/api/`-префикс, `Accept` header), что 403/404/500-хендлеры. Это подтверждённое расхождение контракта. Severity понижаю до **P2**, а не P1/P0: (1) обход тривиален — фронт всё равно получает `success:false`-подобный сбой без порчи данных, полная перезагрузка страницы уводит на нормальный `/login`; (2) единственный найденный живой consumer (`_daily_plan_progress.html`) ломается только в узком окне «сессия истекла, вкладка осталась открыта» и деградирует лишь косметический виджет прогресса, не блокирует прохождение плана дня; (3) для `repair-web` живого фронтенд-вызова не найдено вовсе (только тесты) — риск чисто теоретический; (4) сами тесты (`tests/test_words_routes.py:850-852`, `:877-880`) уже заранее допускают оба кода ответа, то есть поведение не новое и отчасти осознанно принято, хотя формально по-прежнему нарушает задокументированный в CLAUDE.md JSON-контракт для API-клиентов.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/__init__.py:424-426` — ```python if request.headers.get('X-Requested-With') == 'XMLHttpRequest': return jsonify({'success': False, 'error': 'Authentication required'}), 401 return redirect(url_for('auth.login', next=request.url)) ``` Проверка только по `X-Requested-With`, без `_wants_json()` (`request.path.startswith('/api/')` или `Accept: application/json`), в отличие от `handle_403_error`/`404`/`500` (`app/__init__.py:328-337`).
  - `app/words/routes.py:1678-1679` и `app/words/routes.py:1803-1804` — оба роута голые `@login_required`, никакой собственной проверки Accept/JSON нет, весь путь отказа идёт через глобальный `unauthorized_handler`.
  - `app/templates/components/_daily_plan_progress.html:130-134` — реальный вызов `fetch('/api/daily-plan/next-step', {credentials: 'same-origin', headers: headers})` без `X-Requested-With`; при истёкшей сессии `fetch` сам последует за 302 на HTML `/login`, и `.then(r => r.json())` упадёт с `SyntaxError` на непарсящемся HTML — виджет прогресса плана дня молча ломается вместо явной 401-ошибки.
- **Где расхождение:** код — `_wants_json()` в `app/__init__.py` (используется для 403/404/500) не применён к `login_manager.unauthorized_handler` (401), хотя раздел «API errors» / «Global HTTP error JSON» в CLAUDE.md описывает единый JSON-контракт для `/api/`-клиентов.

#### DP-086 · P2 · `app/api/daily_plan.py:944-953`

- **Кандидат:** `DP-C-128` · линзы-источники: API-B-11 · скептик: `skeptics/DP-C-128.md`
- **Симптом:** `error_ids` без ограничения длины: 20 000 id = 20 003 SQL, 12.6 с воркера, HTTP 200
- **Сценарий отказа:** механизм подтверждён построчно: неограниченный клиентский список → Python-цикл → 1 `SELECT` по PK на каждый id (плюс 1 `UPDATE`-flush на каждый ранее-нерезолвленный id, принадлежащий вызывающему) → линейный по N SQL-трафик без батчинга и без верхней границы. Сценарий: аутентифицированный пользователь шлёт `POST /api/daily-plan/error-review/complete` с `error_ids` из 20 000 произвольных (в т.ч. несуществующих) целых — обработчик не отклоняет запрос, выполняет ≥20 000 отдельных round-trip к БД в рамках одного HTTP-запроса, удерживая соединение из пула на всё это время; конкретные цифры «20 003 SQL / 12.6 с» из формулировки не перепроверены прогоном (нет доступа к нагрузочному стенду), но сам линейный по N механизм без cap — доказан кодом, не предположением. Понижаю severity до **P2**: это деградация производительности/ресурсов на один запрос одного пользователя (не порча данных, не отказ для всех пользователей, есть obvious fix — cap длины), а не P1/P0.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:945` — `raw_ids = body.get('error_ids') or []`: список принимается из JSON-тела без проверки длины.
  - `app/api/daily_plan.py:949-954` — `for raw in raw_ids: ... error_ids.append(int(raw))`: единственная проверка — что элемент приводится к `int`; верхней границы количества элементов нет.
  - `app/api/daily_plan.py:957` — `resolved = resolve_quiz_errors(error_ids, user_id, db, commit=False)` — весь (неограниченный) список идёт дальше как есть.
  - `app/daily_plan/linear/errors.py:243-247` — `for error_id in error_ids: entry = resolve_quiz_error(error_id, user_id, db, commit=False)`: цикл на стороне Python, не batched `IN (...)`-запрос.
  - `app/daily_plan/linear/errors.py:223` — `entry = db.session.get(QuizErrorLog, error_id)`: PK-лукап — отдельный SQL `SELECT` на КАЖДЫЙ id (даже несуществующий — SQLAlchemy не кеширует «не найдено», не только успешные попадания).
  - `app/daily_plan/linear/errors.py:226-231` — при `entry.resolved_at is None` и `commit=False` (именно так вызывается из `resolve_quiz_errors`) выполняется `db.session.flush()` **на каждой** ещё-не-резолвленной строке — то есть на дополнительный `UPDATE` per row поверх `SELECT`.
  - `config/settings.py:203` — `MAX_CONTENT_LENGTH = 16 * 1024 * 1024` (16 МБ) — тело в 20 000 целых чисел JSON (~150 КБ) проходит этот лимит на три порядка ниже потолка; лимита на количество элементов массива нет вовсе.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-128.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (в CLAUDE.md нет явного инварианта про cap на батч-эндпоинты; ближайший смежный паттерн — `chunk_ids` в `app/utils/db_utils.py` для больших `IN()`, который здесь не применён и не мог бы полностью закрыть проблему, так как код итерирует по одному id, а не строит `IN`-запрос).

#### DP-087 · P2 · `app/api/daily_plan.py:957-963`

- **Кандидат:** `DP-C-129` · линзы-источники: API-B-12, API-C-05, API-E-02 · скептик: `skeptics/DP-C-129.md`
- **Симптом:** пустой POST на `/error-review/complete` даёт +10 XP и `StreakEvent`: у graduated/blocked закрывает день
- **Сценарий отказа:** механизм воспроизводится по коду буквально. Сценарий: авторизованный graduated- или заблокированный (`blocked_module_id is not None`) пользователь (у него `required=[]`) шлёт `POST /api/daily-plan/error-review/complete` с телом `{}` (или без тела). `raw_ids=[]` → `error_ids=[]` → `resolved=[]` (ни одна ошибка фактически не резолвнута) → `maybe_award_error_review_xp` всё равно отрабатывает (гейта на `resolved` нет) → +10 XP, `StreakEvent(event_type='xp_linear', details={'source':'linear_error_review'})` пишется идемпотентно на сегодня. При следующем пересчёте (`/api/daily-status`, дашборд) `compute_day_secured_from_activity` видит этот `StreakEvent` как источник 7 `has_learning_activity` и возвращает `day_secured=True` — день закрыт без единого реально пройденного задания. Обычный фронт (`error_review.html:423`) всегда шлёт реальные `ALL_ERROR_IDS`, поэтому штатный UI-путь этот дефект не проявляет — воспроизводится прямым вызовом API (не требует специальных прав, только логин; `@csrf.exempt` + `api_auth_required` — токен CSRF не нужен). Ставлю P2, а не P1: эффект «тихо неверно считает» есть, но требует обхода обычного UI (осознанный вызов API с пустым/произвольным телом), а не наступает при штатном использовании.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:942-946` — тело парсится: `raw_ids = body.get('error_ids') or []`; `body = request.get_json(silent=True) or {}` — на пустом/отсутствующем JSON `raw_ids=[]`, `error_ids=[]`. Никакой проверки `len(error_ids) > 0` или `len(resolved) > 0` перед начислением XP нет.
  - `app/api/daily_plan.py:955-963` — `resolved = resolve_quiz_errors(error_ids, user_id, db, commit=False)` (на пустом списке вернёт `[]`) → безусловно `xp_award = maybe_award_error_review_xp(user_id, db_session=db)`. Вызов XP не гейтится значением `resolved`.
  - `app/daily_plan/linear/errors.py:234-250` — `resolve_quiz_errors` на пустом `error_ids` просто не входит в цикл и возвращает `[]`, без исключения.
  - `app/daily_plan/linear/xp.py:426-436` — `maybe_award_error_review_xp` только проверяет `is_linear_user` (всегда True) и идемпотентность через `award_linear_slot_xp_idempotent(user_id, 'linear_error_review', ...)` — никакой связи с фактически резолвнутыми ошибками.
  - `app/daily_plan/linear/xp.py:64` и `:196-202` — пишет `StreakEvent(event_type=LINEAR_XP_EVENT_TYPE='xp_linear', details={'source': 'linear_error_review', ...})`.
  - `app/achievements/xp_service.py:56` — `'linear_error_review': 10` — подтверждает величину +10 XP.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-129.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — раздел CLAUDE.md про `day_secured`/`compute_day_secured_from_activity` не документирует отсутствие проверки «resolved > 0» перед начислением error_review XP; сам факт, что `xp_linear`-события값 засчитываются как активность, задокументирован и является намеренным (источник 7), но применение его к безусловному error-review-начислению — нет.

#### DP-088 · P2 · `app/api/daily_plan.py:1331-1348`

- **Кандидат:** `DP-C-130` · линзы-источники: API-B-13, API-E-09 · скептик: `skeptics/DP-C-130.md`
- **Симптом:** `/skip-lesson` принимает любой существующий `lesson_id` (INV-37) и сжигает квоту
- **Сценарий отказа:** механизм отказа найден: сервер не сверяет присланный `lesson_id` с каноническим текущим уроком юзера (`find_next_lesson`), а только проверяет существование записи `Lessons` в БД. Сценарий: аутентифицированный юзер (или баг клиента) шлёт `POST /api/daily-plan/skip-lesson {"lesson_id": <id урока из другого, не текущего модуля>}` → эндпоинт создаёт `LessonSkip` для этого урока, отвечает `200 {success: true, next_lesson_id: ...}` и тратит единственную дневную квоту (`DAILY_LESSON_SKIP_QUOTA=1`), при этом реальный текущий требуемый урок плана остаётся неисключённым (его `id` не попадает в `deferred_ids`) и продолжает быть required — юзер в тот же день больше не может отложить его, квота уже сожжена на нерелевантный урок. Важная оговорка: живого фронтенд-вызывающего этот роут в кодовой базе не найдено (только тесты и определение маршрута), поэтому практический вектор эксплуатации — либо ручной вызов API самим юзером (вредит только себе), либо будущий/скрытый клиент. Кросс-юзерного или деструктивного эффекта нет — `user_id` жёстко берётся из `current_user.id`.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:1330-1335`: ```python lesson = db.session.get(Lessons, lesson_id) if lesson is None: return api_error('invalid_lesson', 'Lesson not found', 400) ``` Единственная проверка `lesson_id` — существование строки в `Lessons`. Нет ни одного сравнения `lesson_id` с результатом `find_next_lesson(user_id, db)` (который определён в `app/curriculum/navigation.py:23` и возвращает канонический «следующий урок» юзера) или с любым другим источником «текущего» урока.
  - `app/api/daily_plan.py:1352-1362` — квота считается по количеству строк `LessonSkip` за сегодня для юзера, без фильтра по тому, был ли `lesson_id` реально текущим уроком плана: ```python skips_today = db.session.query(LessonSkip).filter_by( user_id=user_id, skipped_on_date=today, ).count() if skips_today >= DAILY_LESSON_SKIP_QUOTA: return api_error('skip_quota_exhausted', ...) ```
  - Тест `tests/daily_plan/test_skip_lesson_endpoint.py::TestSkipLessonQuota::test_skip_quota_exhausted_after_one_lesson_skip` создаёт **два независимых, произвольных** урока через `_make_lesson()` (модуль `number=99`, уровень со случайным кодом — заведомо не связаны с реальным спайном юзера) и оба успешно проходят через `_post_skip`, второй получает `skip_quota_exhausted` — то есть сам тестовый набор демонстрирует, что эндпоинт одинаково принимает любой существующий `lesson_id`, не только «текущий».
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-130.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код | CLAUDE.md — CLAUDE.md прямо формулирует инвариант «принимает только current curriculum lesson», код его не проверяет.

#### DP-089 · P2 · `app/api/decorators.py:37-62`

- **Кандидат:** `DP-C-131` · линзы-источники: API-B-14, API-E-12 · скептик: `skeptics/DP-C-131.md`
- **Симптом:** 401 в форме `{success, error, status_code}` расходится с глобальным контрактом (INV-47)
- **Сценарий отказа:** код `api_auth_required` реально возвращает ad-hoc словарь с ключом `status_code` (не `status`) и без ключа `message`, что подтверждено и статическим чтением, и живым прогоном test_client. Это расходится и с документированным в CLAUDE.md глобальным контрактом 403/404/500 (`{success, error, message, status}`), и с установленным в проекте helper'ом `api_error()`, чей формат отдельно закреплён тестом `tests/test_api_error_format.py`. Формально глобальный `app.errorhandler` покрывает только 403/404/500 (401 в нём не зарегистрирован), поэтому это не «перехват», а самостоятельный неконсистентный ad-hoc путь — именно то, от чего предостерегает CLAUDE.md («не ad-hoc dicts»). Эффект наблюдаем, но некритичен: как минимум один клиентский обработчик (`linear-daily-plan.js:231`) читает `data.message` и на 401 от decorator'а деградирует до дефолтного текста вместо специфичного (не падает, не ломает функциональность).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/decorators.py:38-42` — `return jsonify({'success': False, 'error': 'User not found', 'status_code': 401}), 401`
  - `app/api/decorators.py:49-53` — `return jsonify({'success': False, 'error': 'Invalid or expired token', 'status_code': 401}), 401`
  - `app/api/decorators.py:58-62` — `return jsonify({'success': False, 'error': 'Authentication required', 'status_code': 401}), 401`
  - Живой прогон: `client.get('/api/daily-status')` → `401 {'error': 'Authentication required', 'status_code': 401, 'success': False}` — ключа `message` нет, вместо `status` — `status_code`.
  - Для сравнения: `app/__init__.py:334` — `jsonify({'success': False, 'error': 'forbidden', 'message': 'Forbidden', 'status': 403})`; `app/api/errors.py:16` — `jsonify({'success': False, 'error': code, 'message': message, 'status': status})`.
  - Потребитель, чувствительный к ключу: `app/static/js/linear-daily-plan.js:231` — `throw new Error(data.message || _t('skip_step_failed', ...))`; на 401 от `/api/daily-plan/skip-lesson` (роут защищён `api_auth_required`, `app/api/daily_plan.py:1298`) `data.message` будет `undefined`, JS уходит на дефолтный текст вместо содержательного сообщения об истёкшей сессии.
- **Где расхождение:** код | CLAUDE.md — секция «API errors»/«Global HTTP error JSON» документирует единый контракт `{success, error, message, status}`, а `app/api/decorators.py` использует другой ad-hoc формат.

#### DP-090 · P2 · `app/api/daily_plan.py:812-816`

- **Кандидат:** `DP-C-144` · линзы-источники: API-C-11 · скептик: `skeptics/DP-C-144.md`
- **Симптом:** blanket-`except` вокруг сборки плана отдаёт 400 «не текущий шаг» вместо ошибки БД
- **Сценарий отказа:** сценарий вход→неверный выход: пользователь шлёт валидный `POST /api/daily-plan/events {event_type:'slot_skipped', step_kind:'srs', reason_text:'not_today'}` (квота пропусков не исчерпана); в этот момент `get_daily_plan` бросает исключение (например, БД временно недоступна, либо баг в одной из подсистем сборки плана). Ожидаемо клиент должен получить `500 internal_error` (через глобальный `handle_500_error`) с сигналом «проблема на сервере, повторить позже» — вместо этого локальный `except Exception: active_items = []` превращает любую такую ошибку в `400 {'error': 'not_current_slot', 'message': 'Можно пропустить только текущий шаг плана'}`. Это (а) однозначно неверное сообщение — план вообще не был собран, слот не идентифицирован, дело не в рассинхронизации клиента; (б) молча теряет диагностику — исключение нигде не логируется, что мешает отличить реальный DB-сбой от штатного отказа при расследовании инцидентов. Данные при этом не портятся: `DailyPlanEvent` не создаётся (ранний `return`), действие просто не засчитывается.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:780-792` — `step_kind` уже провалидирован (`not step_kind or step_kind not in _SKIP_SLOT_KINDS` → ранний `400 invalid_slot_kind`), поэтому к моменту блока ниже `step_kind` **гарантированно непустая** строка из `_SKIP_SLOT_KINDS`.
  - `app/api/daily_plan.py:810-816`: ```python active_slot = None active_index = None try: unified = get_unified_plan(current_user.id, db) or {} active_items = unified.get('required') or [] except Exception: active_items = [] ``` — перехватывается **любое** исключение из `get_unified_plan` (алиас `get_daily_plan` из `app/daily_plan/plan.py`), включая ошибки БД, без логирования.
  - `app/api/daily_plan.py:826-832`: ```python active_kind = active_slot.get('kind') if active_slot else None if active_kind != step_kind: return api_error( 'not_current_slot', 'Можно пропустить только текущий шаг плана', 400, ) ``` — при пустом `active_items` (после `except`) `active_slot=None` → `active_kind=None`, а `step_kind` всегда truthy ⇒ условие `None != step_kind` истинно **безусловно**, и код детерминированно уходит в `400 not_current_slot`.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-144.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-091 · P2 · `app/words/routes.py:1722-1727`

- **Кандидат:** `DP-C-146` · линзы-источники: API-D-02 · скептик: `skeptics/DP-C-146.md`
- **Симптом:** `_next_step_from_unified` считает `skipped` выполненным → `all_done:true` при `0/1` и незакрытом дне
- **Сценарий отказа:** сценарий: required = `[{id:'X', kind:'srs', completed:False, skipped:True, url:'/study?...'}]` (последний непройденный required-пункт скипнут через `POST /api/daily-plan/events {event_type:'slot_skipped', step_kind:'srs', reason_text:'no_time'}`), optional пуст/весь done. `compute_plan_steps` вернёт `plan_completion={'X': False}`, `steps_done=0`, `steps_total=1` — те же цифры уходят в JSON. `_next_step_from_unified._is_done` для того же `item` вернёт `True` (из-за `skipped`), `next_item=None`, `graduated=False` → ответ `{"has_next": false, "all_done": true, "steps_done": 0, "steps_total": 1, ...}`. Одновременно `compute_day_secured_from_activity` для этого же `required` вернёт `False` (пропущенный пункт не в `plan_completion`, значит `all(...)` ломается на нём) — день объективно не закрыт. UI-компонент `_daily_plan_progress.html`, который получает именно этот ответ, покажет пользователю «Шаг 0 из 1» и одновременно кнопку «✨ План выполнен!» — противоречивое и вводящее в заблуждение сообщение о закрытии дня, когда day_secured=False. Данные (XP/streak/day_secured) при этом не портятся — они по-прежнему считаются корректно на dashboard/`/api/daily-status` независимо от этого эндпоинта, поэтому это баг UI-сигнала, а не потери данных; обход есть (dashboard покажет верное состояние).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/words/routes.py` — `_is_done`: ```python def _is_done(item: dict) -> bool: item_id = item.get('id', '') return ( plan_completion.get(item_id, False) or bool(item.get('completed', False)) or bool(item.get('skipped', False)) ) ``` Skip делает элемент «done» для поиска `next_item`; если такой элемент — последний недостающий, `next_item is None` → ветка `all_done: True`.
  - `app/achievements/streak_service.py:178-184` (`_compute_unified_item_completion`) — `plan_completion[item_id] = item.get('completed', False) or summary_kind_done`; `skipped` в этой функции **не участвует**. Тот же `plan_completion` и `steps_done = sum(1 for v in plan_completion.values() if v)` возвращаются в JSON-ответе `_next_step_from_unified` наравне с `all_done`.
  - `app/daily_plan/service.py:44-46` — прямым текстом: «Skipped or blocked required items only affect navigation. They do not represent learning activity and must not satisfy the daily minimum for streak/rank purposes.» — то есть авторы осознанно исключили `skipped` из закрытия дня, но не учли, что `_next_step_from_unified` уже трактует его как «выполнено» в поле `all_done` того же ответа.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-146.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — само поле `all_done` в `_next_step_from_unified` не согласовано с явно задокументированным в `app/daily_plan/service.py` инвариантом «Skipped or blocked required items only affect navigation… must not satisfy the daily minimum»; `_next_step_from_unified` использует `skipped` шире, чем инвариант допускает, — не просто «не блокировать навигацию», а «объявлять весь план завершённым».

#### DP-092 · P2 · `app/daily_plan/plan.py:78-85`

- **Кандидат:** `DP-C-147` · линзы-источники: API-D-03 · скептик: `skeptics/DP-C-147.md`
- **Симптом:** один слот-пропуск помечает `skipped` все required-слоты того же `kind` — на intensive три сразу
- **Сценарий отказа:** механизм воспроизводится по коду без предположений о состоянии. Сценарий: intensive-пользователь (≥3 доступных курс-урока в цепочке) открывает план (`required = [curriculum_1, srs, reading, curriculum_2, curriculum_3]`), жмёт «не сейчас» на текущем (первом) слоте — `POST /api/daily-plan/events {event_type:'slot_skipped', step_kind:'curriculum'}` проходит все проверки (`active_kind == 'curriculum' == step_kind`, quota 0/1) и пишет ОДНУ строку `DailyPlanEvent(step_kind='curriculum')`. На следующем рендере `_get_unified_skipped_kinds` возвращает `{'curriculum'}`, а `_apply_unified_skip_state` помечает `skipped=True` у всех трёх curriculum-элементов required (curriculum_1, curriculum_2, curriculum_3), хотя дневная квота пропусков (`DAILY_SLOT_SKIP_QUOTA=1`) потрачена один раз. Итог — неверный вывод: пользователь получает два лишних «Пропущено — можно вернуться» слота, которые не выбирал, и bonus-раздел (`u_required_settled`) разблокируется после выполнения только `srs`+`reading`, а не всех пяти required-пунктов, задуманных intensive-тиром. `day_secured` этим не искажается (отдельная проверка по реальной активности), поэтому эффект ограничен UI/разблокировкой bonus, а не streak/XP.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/plan_builder.py` — `_TIER_CURRICULUM_COUNT = {'calm': 1, 'normal': 2, 'intensive': 3}`, все три курс-урока добавляются через один и тот же `_curriculum_item_dict` → `build_curriculum_item(..., kind='curriculum', ...)`. Тест `test_intensive_five_items_baseline` фиксирует это буквально: `kinds == ['curriculum', 'srs', 'reading', 'curriculum', 'curriculum']`.
  - `app/daily_plan/plan.py:68-85`: ```python def _apply_unified_skip_state(required_dicts, skipped_kinds): ... for item in required_dicts: if item.get('completed', False): continue kind = item.get('kind', '') if kind in skipped_kinds: item['skipped'] = True ``` Ключ проверки — `kind`, а не `id`/индекс/`lesson_id`. Метод не различает, какой именно из трёх `curriculum`-слотов пометил пользователь.
  - `app/api/daily_plan.py:772-838` — `step_kind` в событии `slot_skipped` берётся из `active_slot.get('kind')` (первый actionable required-item), т.е. пишется буквально `'curriculum'`, без привязки к `lesson_id` конкретного слота.
  - `app/daily_plan/skips.py:13-14` — `DAILY_SLOT_SKIP_QUOTA = 1` — на пользователя доступен ровно один «не сейчас» в день, но при kind-коллизии на intensive этот один клик гасит три required-слота.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-147.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — `_apply_unified_skip_state` был спроектирован в модели «один required-item на kind» (верно для calm/normal вне curriculum и для srs/reading везде), но `plan_builder.py` для intensive-тира сознательно завёл 2-3 required-item с одинаковым `kind='curriculum'` (задокументировано в его же docstring и покрыто тестом), и эти два модуля не были сверены друг с другом.

#### DP-093 · P2 · `app/api/daily_plan.py:58-67`

- **Кандидат:** `DP-C-152` · линзы-источники: API-D-08 · скептик: `skeptics/DP-C-152.md`
- **Симптом:** `_UNIFIED_KIND_TO_PHASE` не знает `grammar_review` (0 route-шагов) и держит 3 несуществующих kind'а
- **Сценарий отказа:** механизм реален и воспроизводим по коду. Сценарий: пользователь проходит модуль, где следующий curriculum-урок — `final_test`, а в модуле есть grammar-урок → required-список получает pre-final-test grammar_review элемент (`plan_builder.py:325`). Пользователь завершает его → `plan_completion[item_id] = True` → `_sync_unified_route_steps` берёт `item.get('kind')` = `'grammar_review'` → `_UNIFIED_KIND_TO_PHASE.get('grammar_review')` возвращает `None` → `if not phase_kind: continue` → `add_route_steps_idempotent` для этого шага не вызывается вовсе — 0 route-шагов вместо ожидаемого веса `PHASE_STEP_WEIGHTS['check']=1` (единственная разумная категория для «повторение/проверка»). Вторая часть кандидата тоже подтверждена: `listening`, `speaking`, `writing` в словаре — мёртвые ключи, ни один текущий unified required/optional билдер такие kind'ы не производит (подтверждено явным комментарием автора в `plan_builder.py:33-38` и полным перебором веток `_build_optional_candidate`). Severity — P2, не P1: эффект ограничен декоративным «route progress»/checkpoint-счётчиком (`/study/stats` progress-bar), не задевает `day_secured`, XP или streak, и сценарий возникает не в каждом плане дня, а только когда grammar_review-элемент реально required (final_test как 1-3-й урок цепочки + наличие grammar-урока в модуле) — но контракт docstring'а («Increment route progress for completed unified-plan required items») нарушается молча, без воркэраунда для конкретного шага.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:58-67` — словарь: `curriculum, srs, reading, listening, speaking, writing, error_review, challenge`. Ключа `grammar_review` нет.
  - `app/api/daily_plan.py:88-93` — `phase_kind = _UNIFIED_KIND_TO_PHASE.get(item.get('kind', '')); if not phase_kind or ...: continue` — для kind не из словаря шаг route-progress тихо пропускается.
  - `app/daily_plan/plan_builder.py:319-325` — в `_grammar_prep_item_dict` формируется required-элемент: `'section': 'required', 'kind': 'grammar_review', ...` — используется в `build_required_snapshot` (строки ~99-121) как шаг «повторение грамматики» ПЕРЕД `final_test`, когда финальный тест — 1-й/2-й/3-й урок цепочки и в модуле есть grammar-урок. Это реальный, часто достижимый required-item (любой модуль с финальным тестом и grammar-уроком).
  - `app/daily_plan/plan_builder.py:33-38` (docstring) — «Skill kinds (listening / speaking / writing) are intentionally absent from required — they had their own slot builders that double-counted... Skill XP awards remain as bonus XP..., but never gate the day.» Прямое авторское подтверждение: 3 kind'а из словаря никогда не встречаются в required.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-152.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — сам факт задокументирован в комментариях кода (`plan_builder.py`), но карта `_UNIFIED_KIND_TO_PHASE` в `daily_plan.py` не была обновлена синхронно при введении `grammar_review` как required-kind'а.

#### DP-094 · P2 · `app/api/daily_plan.py:488-489`

- **Кандидат:** `DP-C-156` · линзы-источники: API-D-12 · скептик: `skeptics/DP-C-156.md`
- **Симптом:** `/api/daily-plan` объявляет `day_secured=True` и не пишет `secured_at` — третья поверхность закрытия дня
- **Сценарий отказа:** механизм ровно такой, как описан: `GET /api/daily-plan` вычисляет и отдаёт `day_secured=True` в JSON, не вызывая `write_secured_at` и ни один из side-effect'ов (rank-up, milestones, achievement/streak-нотификации), которые вызывают два других места (`daily_status()` и рендер дашборда) при том же самом условии. Сценарий: авторизованный пользователь (или любой клиент API) делает `GET /api/daily-plan?tz=...` в день, когда обязательные пункты выполнены; ответ содержит `day_secured: true`, но `DailyPlanLog.secured_at` для этого дня остаётся `NULL`, пока пользователь не откроет дашборд или `/api/daily-status` — до этого момента тир-счётчик, cohort-funnel, activity feed и `days_secured`-виджет в `study/routes.py` не видят этот день закрытым, хотя API уже сообщил `True`. Оговорка: в текущем вебе ни один JS-файл в `app/static/js` или шаблон не дергает голый `GET /api/daily-plan` (только его под-роуты `/events`, `/next-slot`, `/next-step` и т.д.) — эндпоинт живой и публичный (используется тестами, задокументирован докстрингом с параметрами и возвращаемыми полями), но сегодняшний веб-клиент до него не достаёт, поэтому наблюдаемого эффекта в текущем UI нет; риск реализуется для любого стороннего/будущего клиента, который возьмёт это поле за источник истины.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:487-489`: ```python from app.daily_plan.service import compute_day_secured_from_activity plan['day_secured'] = compute_day_secured_from_activity(plan, plan_completion) ``` Дальше в функции `daily_plan()` (до `return jsonify(payload)` на строке 493) нет ни одного вызова `write_secured_at`, `record_plan_completion`, `emit_daily_plan_completed`, `emit_minimum_completed`, `check_immersion_achievement`, `check_plan_streak_milestone_notification` — эндпоинт просто возвращает посчитанное значение и завершается.
  - Для сравнения, `app/api/daily_plan.py:331-383` (`daily_status()`) при `day_secured=True` вызывает: `emit_daily_plan_completed`, `emit_minimum_completed`, `write_secured_at(user_id, today, None)`, `record_plan_completion` (+ `notify_rank_up`), `check_immersion_achievement`, `check_plan_streak_milestone_notification`, затем `db.session.commit()`.
  - `app/words/routes.py:1044-1071` (рендер дашборда) при `_day_secured=True` тоже вызывает `write_secured_at` + `record_plan_completion` (+ `notify_rank_up`) + `db.session.commit()`.
  - `app/daily_plan/service.py:104-137` — `write_secured_at` пишет `DailyPlanLog.secured_at`, единственный путь к этому полю; в `daily_plan()` он не импортируется вообще (в отличие от `daily_status()`, где импорт на строке 332).
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-156.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md фиксирует общий механизм пересчёта («day_secured... API пересчитывает из активности через compute_plan_steps + compute_day_secured_from_activity»), но не документирует, что персист `secured_at` обязателен на каждой поверхности, которая отдаёт это поле; на практике персистят только 2 из 3 мест.

#### DP-095 · P2 · `app/words/routes.py:1234`

- **Кандидат:** `DP-C-158` · линзы-источники: API-E-03 · скептик: `skeptics/DP-C-158.md`
- **Симптом:** `@module_required('words')` только на `/dashboard`; 18 роутов зоны отдают тот же план и XP без модуля
- **Сценарий отказа:** механизм есть и воспроизводим по коду. Сценарий: админ отзывает модуль `words` у пользователя X через `POST /admin/modules/users/<X>/revoke/<words_module_id>` (живой роут, `app/admin/modules.py:172`). После этого `GET /words/dashboard` возвращает 403 (`module_required` сработал) — ожидаемое поведение. Но `GET /api/daily-plan`, `GET /api/daily-status`, `POST /api/daily-plan/challenge/complete` и ещё ~15 роутов в `app/api/daily_plan.py` продолжают работать для того же X: они гейтятся только `@api_auth_required` (аутентификация), не модулем, и отдают тот же `get_daily_plan_unified` payload, а `challenge/complete` дополнительно начисляет бонусный XP. Т.е. отзыв модуля не перекрывает доступ к «плану дня» — контракт «модуль words гейтит зону» держится только на web-роуте `/dashboard`, а не на API, через который тот же функционал полностью доступен. Severity — понижаю до **P2** относительно выданной формулировки (не подтверждаю implicit P1/P0 из-за «module_required только на /dashboard»): `words` — `is_default: True` и выдаётся всем при регистрации (`app/auth/routes.py:381-390`), поэтому в норме 100% юзеров модуль имеют, и для срабатывания дыры нужен целенаправленный admin-отзыв — узкий, но реальный и воспроизводимый сценарий (нет данных о том, использует ли владелец `revoke` в проде — это не решающий фактор для P2 по правилам severity: «дыра в гарантиях, расхождение контрактов» подходит точнее, чем «потеря данных/чужие данные»).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/words/routes.py:1234-1236` — `@words.route('/dashboard')` / `@login_required` / `@module_required('words')` — единственный полностью гейтящийся вход в план дня (плюс ещё 3 роута того же blueprint: `word_list` 1247-1249, `word_detail` 1576-1578, `phrasal_verb_list` 1668-1670 — тоже гейтятся, но это не «план дня»).
  - `app/api/daily_plan.py:270-272` — `@api_daily_plan.route('/daily-status')` / `@api_auth_required` (без module_required) → внутри вызывает `get_daily_plan_unified`.
  - `app/api/daily_plan.py:448-471` — `@api_daily_plan.route('/daily-plan')` / `@api_auth_required` → `plan = get_daily_plan_unified(user_id, tz=tz)` — **тот же payload**, что рендерит гейтящийся `/dashboard`, отдаётся дословно JSON'ом без проверки модуля.
  - `app/api/daily_plan.py:1209-1213` — `@api_daily_plan.route('/daily-plan/challenge/complete', methods=['POST'])` / `@csrf.exempt` / `@api_auth_required`; комментарий в коде на строке ~1271: `# complete_challenge awards bonus XP atomically with the completion row` — XP начисляется без module-проверки.
  - `app/api/decorators.py:17-30` — `api_auth_required` проверяет только JWT/сессию (`current_user.is_authenticated`), про модули ничего не знает.
  - `app/admin/modules.py:172-181` — `revoke_module` реально снимает `UserModule.is_enabled` для конкретного `user_id`/`module_id` — механизм отзыва не гипотетический, кнопка есть в админке.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-158.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — в CLAUDE.md нет явного инварианта «module_required обязателен на API-дубликатах плана дня»; ближайшая параллель — `SEC-001` из `docs/audit/2026-08-08-cross-zone-audit.md` (не читан, только упомянут в CLAUDE.md) про непокрытые гейтом роуты книг — тот же класс проблемы (гейт на части роутов, не на всех, отдающих тот же контент).

#### DP-096 · P2 · `app/api/decorators.py:44-53`

- **Кандидат:** `DP-C-159` · линзы-источники: API-E-04 · скептик: `skeptics/DP-C-159.md`
- **Симптом:** тело эндпоинта исполняется внутри `except Exception` JWT-ветки → 500 маскируется под `401 Invalid or expired token`
- **Сценарий отказа:** механизм ровно такой, как описан. `return f(*args, **kwargs)` физически находится внутри `try`, а `except Exception` — блок без разбора типа, поэтому он перехватывает не только ошибки `verify_jwt_in_request()`/`get_jwt_identity()`, но и ЛЮБОЕ исключение из тела самого эндпоинта. Сценарий: JWT-аутентифицированный клиент (в т.ч. `/api/daily-status`, `/api/daily-plan/next-step` и остальные роуты `app/api/daily_plan.py`) шлёт валидный `Bearer`-токен; внутри обработчика происходит любая непойманная ошибка (баг, недоступная БД, `AttributeError` и т.п.) — клиент получает `401 Invalid or expired token` вместо `500`, что для API-клиента выглядит как «токен истёк», провоцируя бесполезный retry/re-login вместо показа реальной ошибки. `logger.warning(..., exc_info=True)` сохраняет трассировку на сервере, поэтому диагностика по логам возможна, но сама HTTP-семантика и тело ответа неверны. Понижаю до **P2**, а не P1/P0: (1) основной браузерный флоу дашборда/плана дня ходит через session-cookie fallback (вне `try`) — `jwt_token` в `localStorage` нигде не пишется, значит реальные пользователи веб-кабинета этот путь сейчас не задействуют; (2) день не закрывается неверно, XP/streak не искажаются — это чисто транспортный/error-reporting дефект для JWT-клиентов (мобильные/внешние, если появятся) с рабочим обходным путём (session auth) для текущей аудитории.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/decorators.py:33-53`: ```python try: verify_jwt_in_request() user_id = get_jwt_identity() user = db_get_user(user_id) if user is None: return jsonify(...), 401 login_user(user, remember=False) return f(*args, **kwargs) # ← строка 44, тело эндпоинта ВНУТРИ try except Exception as exc: # ← строка 45, ловит и ошибку JWT, и любое исключение из f() logger.warning("JWT verification failed: %s", exc, exc_info=True) return jsonify({'success': False, 'error': 'Invalid or expired token', 'status_code': 401}), 401 ```
  - Эмпирика (реальный прогон через тестовый клиент, `/api/daily-status` — один из декорированных `@api_auth_required` роутов `app/api/daily_plan.py`): ``` STATUS: 401 BODY: {'error': 'Invalid or expired token', 'status_code': 401, 'success': False} ``` при том что брошенное исключение — `RuntimeError("simulated bug in endpoint body")`, никак не связанное с валидностью токена; сам токен валиден (получен только что через `/api/login`).
- **Где расхождение:** код — CLAUDE.md описывает `api_error(code, message, status)` и глобальные `handle_403/404/500_error` как единый контракт ошибок API, но этот декоратор перехватывает исключения ДО того, как они доходят до глобального 500-хендлера, и подменяет их на `401` с посторонним сообщением — расхождение с задокументированным единым error-контрактом именно для JWT-пути.

#### DP-097 · P2 · `app/utils/rate_limit_helpers.py:16-18`

- **Кандидат:** `DP-C-160` · линзы-источники: API-E-07 · скептик: `skeptics/DP-C-160.md`
- **Симптом:** ключ лимитера — левый `X-Forwarded-For`, который nginx дописывает, а не перетирает
- **Сценарий отказа:** механизм подтверждён на всех трёх уровнях (парсер хелпера берёт левый элемент; nginx дописывает, не перетирает; `ProxyFix` не защищает от этого, потому что хелпер читает сырой заголовок в обход исправленного `request.remote_addr`). Эффект — реальный обход rate-limit на `login`/`register`/`reset_request` подделкой `X-Forwarded-For`.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/utils/rate_limit_helpers.py:16-18` — `if request.headers.get('X-Forwarded-For'): return request.headers.get('X-Forwarded-For').split(',')[0].strip()` — берёт САМЫЙ ЛЕВЫЙ элемент цепочки.
  - `nginx/conf.d/app.conf:15` — `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`. `$proxy_add_x_forwarded_for` в nginx — это входящий `X-Forwarded-For` (если есть) **плюс** `,$remote_addr` в конец, то есть именно ДОПИСЫВАНИЕ, а не перетирание — подтверждает вторую половину формулировки кандидата.
  - `app/__init__.py:54-60` — `limiter = Limiter(key_func=get_remote_address_key, default_limits=[...], ...)` — это ДЕФОЛТНЫЙ key_func для всего приложения.
  - `app/__init__.py:88` — `app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)`. Проверил исходник установленного werkzeug: `ProxyFix.__call__` вычисляет `x_for = self._get_real_value(1, environ["HTTP_X_FORWARDED_FOR"])` и подставляет его в `environ["REMOTE_ADDR"]`, но **не трогает** `environ["HTTP_X_FORWARDED_FOR"]` — сырой заголовок остаётся нетронутым и полностью читается через `request.headers.get('X-Forwarded-For')`. Значит, даже с `ProxyFix` установленным, хелпер в `rate_limit_helpers.py` игнорирует уже-исправленный `request.remote_addr` и вместо этого читает необрезанный сырой заголовок, где самый левый элемент — то, что прислал клиент.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-160.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-098 · P2 · `app/api/decorators.py:43`

- **Кандидат:** `DP-C-162` · линзы-источники: API-E-11 · скептик: `skeptics/DP-C-162.md`
- **Симптом:** JWT-ветка зовёт `login_user()` и выдаёт сессионную куку на чистый API-вызов
- **Сценарий отказа:** механизм полный и непрерывный: любой запрос к `/api/daily-plan/*` (и остальным `@api_auth_required` роутам) с `Authorization: Bearer <jwt>` заставляет `login_user()` записать `_user_id`/`_fresh`/`_id` в `flask.session`, что безусловно взводит `session.modified`, а Flask безусловно отдаёт `Set-Cookie` в ответе — без какого-либо кода, который бы это подавлял для API-путей. Сценарий: мобильный/сторонний клиент делает `GET /api/daily-status` только с Bearer-токеном (без намерения работать с куками) — ответ всё равно несёт `Set-Cookie: session=...`, превращая заявленно stateless JWT-путь в побочный stateful Flask-Login логин. Комментарий в докстринге декоратора («Sets current_user in both paths so endpoint code can use current_user.id uniformly») подтверждает, что это осознанный, но небесплатный побочный эффект — `login_user()` был выбран как самый быстрый способ прогреть `current_user`, а не выделенный path без записи в сессию. Понижаю до P2, а не P1/P0: сам daily-plan функционально не ломается (данные корректны, XP/streak/day_secured не затронуты), эффект — контрактное расхождение («JWT — для стейтлес-клиентов») и потенциальный security-смысл (куки, шаренные с браузером/webview, продлевают аутентификацию за пределы времени жизни JWT), но без прямой порчи данных или недоступного обхода.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/decorators.py:32-44` — JWT-ветка: `verify_jwt_in_request()` → `get_jwt_identity()` → `db_get_user(user_id)` → **`login_user(user, remember=False)`** → `return f(*args, **kwargs)`. Вызывается безусловно на КАЖДЫЙ запрос с валидным Bearer-токеном, не только при первом обращении.
  - `flask_login/__init__.py` (`login_user`): `session["_user_id"] = user_id; session["_fresh"] = fresh; session["_id"] = current_app.login_manager._session_identifier_generator()` — прямая мутация `flask.session`.
  - `flask/sessions.py` (`SessionInterface.should_set_cookie`): `return session.modified or (session.permanent and app.config["SESSION_REFRESH_EACH_REQUEST"])`. Поскольку `session["_user_id"] = ...` — это `__setitem__` на `CallbackDict`-based `SecureCookieSession`, он безусловно ставит `session.modified = True`.
  - `flask/sessions.py` (`SecureCookieSessionInterface.save_session`): при `should_set_cookie(...) == True` вызывает `response.set_cookie(name, val, ...)` — реальный `Set-Cookie` в HTTP-ответе.
  - `app/middleware/security.py` — оба `@app.after_request` хука (заголовки безопасности, кэш статик) не трогают `Set-Cookie` и не различают `/api/*` от остального; в `app/__init__.py` тоже нет `after_request`/`teardown_request`, который бы вычищал сессионную куку для API-путей.
- **Где расхождение:** код — докстринг самого декоратора обещает «JWT is checked first, session is the fallback» как два независимых механизма, а по факту JWT-путь создаёт сессионный артефакт как побочный эффект; в CLAUDE.md инвариантов на этот счёт нет.

#### DP-099 · P2 · `app/api/daily_plan.py:1023`

- **Кандидат:** `DP-C-163` · линзы-источники: API-E-13 · скептик: `skeptics/DP-C-163.md`
- **Симптом:** `/phrase-review/complete` читает flask-сессию → для JWT-клиента недостижим в принципе
- **Сценарий отказа:** механизм есть и воспроизводим по коду. Сценарий: JWT-клиент без cookie-jar шлёт `POST /api/daily-plan/phrase-review/complete` с валидным `Authorization: Bearer` и корректным `{"answers": [...]}"` → `api_auth_required` успешно аутентифицирует через JWT-ветку (`app/api/decorators.py:32-44`, включая `login_user(...)`, который не восстанавливает ранее отсутствовавшие данные сессии), но `session.get('daily_phrase_review_items')` пуст, потому что единственный writer этого ключа лежит за чисто cookie-сессионным `@login_required`-роутом, недостижимым для клиента без cookie. Результат — гарантированный `400 phrase_review_expired` на каждый вызов; фича `phrase_review` для такого клиента нефункциональна в принципе, а не в отдельных случаях.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:1014-1017` — `complete_phrase_review` декорирован `@csrf.exempt` + `@api_auth_required`, то есть по документированному контракту декоратора (`app/api/decorators.py:25-27`: «endpoints decorated with @csrf.exempt should only be reachable via JWT in practice (mobile/external clients)») предназначен для JWT-клиентов.
  - `app/api/daily_plan.py:1023-1025` — `items = session.get('daily_phrase_review_items')`; при отсутствии — `400 phrase_review_expired`.
  - `app/curriculum/routes/main.py:328-337` — единственное место записи `session['daily_phrase_review_items'] = items` находится в `phrase_review_session`, декорированной **только** `@login_required` (flask-login), без `@api_auth_required`, без JWT-поддержки.
  - `app/__init__.py:369-377` — `login_manager.user_loader` резолвит пользователя исключительно по `user_id` из cookie-сессии flask-login; `request_loader`, который бы принимал `Authorization: Bearer`, в проекте не определён — `grep` подтверждает: `user_loader`/`request_loader` встречаются только в `app/__init__.py`, и там только `user_loader`.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-163.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — сам `app/api/decorators.py` документирует контракт «`@csrf.exempt` ⇒ JWT/mobile-клиенты», а `phrase-review/complete` этот контракт нарушает (в отличие от соседних POST-роутов в том же файле, включая `complete_error_review`, которые данных из сессии не требуют). В CLAUDE.md этот эндпоинт отдельно не описан. Severity понижена до P2 (не P1): `phrase_review` — опциональный пункт плана дня, не блокирует `required`/`day_secured`; практического JWT-мобильного клиента в репозитории не найдено (нет мобильного приложения, нет тестов, использующих JWT для этого роута), так что для реально существующих пользователей есть полный обход — браузерная сессия работает штатно.


### P3 — детали

#### DP-100 · P3 · `app/api/daily_plan.py:437`

- **Кандидат:** `DP-C-117` · линзы-источники: API-A-08 · скептик: `skeptics/DP-C-117.md`
- **Симптом:** `srs_limit_reason` есть в 2 источниках из 5 и не читается ни одним консьюмером
- **Сценарий отказа:** обе части утверждения проверяются буквально по коду: (1) из 5 файлов, образующих механизм adaptive-tier, верхнеуровневый ключ `srs_limit_reason` пишется только в 2 (`app/api/daily_plan.py:437-438` и `:494-495`); (2) ни один реальный консьюмер (единственный существующий tooltip в `unified_daily_plan.html:401-404`) этот ключ не читает — он читает параллельно вычисленный `reason_hint` из `items/srs.py`. Наблюдаемого вреда для пользователя нет: та же информация (тир adaptive-limit) доходит до UI другим путём (`reason_hint`), так что `srs_limit_reason` — не сломанная, а мёртвая часть контракта API, чей докстринг («used by ... to surface a one-time tooltip») не соответствует фактическому потребителю. Понижаю severity до P3 (мёртвый код / расхождение докстринга с фактическим потреблением, без наблюдаемого эффекта для пользователя) — исходная severity не указана явно, но по критериям брифинга это не P1/P2, т.к. обхода не требуется и ничего не ломается.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - Ровно 5 файлов во всём `app/` упоминают tier/limit-reason механизм: `app/study/services/srs_service.py` (определение), `app/daily_plan/linear/slots/srs_slot.py`, `app/daily_plan/items/srs.py`, `app/api/daily_plan.py`, `app/templates/partials/unified_daily_plan.html`.
  - Ключ верхнего уровня `srs_limit_reason` пишется только в `app/api/daily_plan.py:437-438` (`daily_status`) и `app/api/daily_plan.py:494-495` (`daily_plan`) — 2 из 5 файлов; остальные три оперируют тем же tier под другими именами (`srs_tier`, `reason_hint`).
  - `app/study/services/srs_service.py:459-465` — докстринг `get_adaptive_limit_reason`: *«Used by /api/daily-status and /api/daily-plan to surface a one-time tooltip when the user is below normal»* — заявляет фронтенд-потребление именно этого возвращаемого значения.
  - `app/daily_plan/items/srs.py:201-224` — тот же tier кладётся в `PlanItem.data['reason_hint']` (человекочитаемое сообщение) и `data['srs_tier']`, а не в `srs_limit_reason`.
  - `app/templates/partials/unified_daily_plan.html:401-404` — единственное место, реально рендерящее tooltip про adaptive-tier, читает `_item_data.get('reason_hint')` (вложенный `PlanItem.data` из `items/srs.py`), а не верхнеуровневый payload-ключ `srs_limit_reason`.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-117.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — докстринг `get_adaptive_limit_reason` в `app/study/services/srs_service.py` утверждает использование `/api/daily-status`/`/api/daily-plan` для tooltip, но фактический tooltip в `unified_daily_plan.html` не завязан на добавляемый этими роутами ключ `srs_limit_reason`.

#### DP-101 · P3 · `app/words/routes.py:1705`

- **Кандидат:** `DP-C-118` · линзы-источники: API-A-11 · скептик: `skeptics/DP-C-118.md`
- **Симптом:** `steps_total=0` при `has_next=true` → прогресс-бар не рендерится у graduated/blocked (у paused тот же эффект, но через `has_next=false`)
- **Сценарий отказа:** механизм воспроизводим по коду. Сценарий: graduated-пользователь (или пользователь с заблокированным спайном — `blocking_module_id is not None`), у которого в `optional` есть невыполненный `phrase_review` (`url='/learn/phrase-review/?from=daily_plan'`, единственный сеятель этого литерала в кодовой базе). Клик по «Повтори 3 фразы» → рендерится `base.html` → `{% include '_daily_plan_progress.html' %}` проходит гейт `from=='daily_plan'` → JS дергает `/api/daily-plan/next-step` → получает `has_next:true` (либо через free_study-ветку у graduated, либо через optional-item-ветку у graduated/blocked), но `steps_total:0`, т.к. `required=[]` в обоих случаях → `if (total === 0) return;` обрывает рендер бара до `bar.style.display = 'flex'` — весь `#daily-plan-bar` (точки И кнопка «Следующий шаг») молча не появляется. Для paused эффект тот же (бар не рендерится), но через `has_next:false`, а не `true` — формулировка кандидата для paused неточна в деталях (`has_next` там ложный), однако итоговый наблюдаемый эффект («бар не рендерится») подтверждается и для paused тоже. Severity понижаю до **P3** относительно скрытого ожидания: это чисто косметический артефакт (пропадают декоративные точки-прогресс и кнопка перехода) в компоненте, который и так почти не виден остальным пользователям — контейнер целиком завёрнут в `{% if request.args.get('from') == 'daily_plan' %}`, а единственный живой сеятель этого query-параметра во всей кодовой базе — ссылка `phrase_review`. Основной, повсеместно видимый прогресс-индикатор плана дня — `u_required_total`/`u_required_done` в `app/templates/partials/unified_daily_plan.html:95-244` — уже корректно гейтится `{% if u_required_total > 0 %}` и никак не завязан на этот API; там графики/счётчики для graduated/blocked не ломаются. Данных, XP, streak, day_secured эффект не касается; обход тривиален (страница `/learn/phrase-review/` работает без бара).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/words/routes.py:1705` — `plan_completion, _, steps_done, steps_total = compute_plan_steps(plan, daily_summary)`; `steps_total` идёт в JSON без корректировки под graduated/blocked.
  - `app/achievements/streak_service.py:199-205` — для `mode=='unified'`: `required_items = daily_plan.get('required') or []; steps_total = len(required_items)`.
  - `app/daily_plan/plan.py:382-398` — `graduated = next_lesson is None and blocking_module_id is None and has_completed_history(...)`; `if graduated: required_dicts = []`. `spine_blocked = next_lesson is None and blocking_module_id is not None` — идёт в `else`-ветку, но:
  - `app/daily_plan/plan_builder.py:82-86` — `build_required_snapshot` зовёт `_collect_curriculum_chain` (обёртка над `find_next_lesson_linear`); при блокированном спайне цепочка пуста → `if not curriculum_lessons: return []`. Итог: и graduated, и spine_blocked дают `required=[]`, то есть `steps_total=0` в обоих случаях.
  - `app/words/routes.py:1738-1751` (граница `next_item is None` → `graduated`-ветка) — возвращает `has_next: True, step_type: 'free_study', steps_total: steps_total` (=0 при graduated).
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-118.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — расхождение внутри самого JS-компонента (steps_total не учитывает graduated/blocked при has_next=true), не с CLAUDE.md напрямую; CLAUDE.md описывает только «Next-step API» и не гарантирует поведение `#daily-plan-bar` для этих состояний.

#### DP-102 · P3 · `app/api/daily_plan.py:48`

- **Кандидат:** `DP-C-121` · линзы-источники: API-B-02 · скептик: `skeptics/DP-C-121.md`
- **Симптом:** `?tz=` длиной ≥256 → `OSError` мимо `except (KeyError, ValueError)` → 500 на 6 эндпоинтах
- **Сценарий отказа:** механизм воспроизведён кодом и живым прогоном. Сценарий: юзер, авторизованный по cookie-сессии (обычный браузерный путь), делает `GET /api/daily-summary?tz=` + 256 символов (например `AAAA...A` 256 раз). `_validate_timezone` зовёт `ZoneInfo(tz_name)`, `zoneinfo` пытается открыть файл `tzdata/zoneinfo/<256 симв.>`, ОС возвращает `OSError: [Errno 63] File name too long`, `except (KeyError, ValueError)` его не ловит, исключение всплывает из view, Flask отдаёт 500 вместо ожидаемого fallback на `DEFAULT_TZ`. Аналогично для остальных 5 эндпоинтов. Severity понижена до P3 относительно того, что предложено в кандидате (не указана исходная, но по формулировке похоже на P1/P2): это self-DoS одного запроса одного авторизованного юзера через искусственно длинный query-параметр, не встречающийся ни в одном реальном клиенте (`tz` везде берётся из `Intl.DateTimeFormat().resolvedOptions().timeZone` браузера или из `User.timezone`, оба — короткие каноничные IANA-имена вида `Europe/Istanbul`). Нет порчи данных, нет доступа к чужим данным, обход тривиален (не слать длинный `tz`). Ближе к дыре в валидации входа без наблюдаемого практического эффекта — P3.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:45-51`: ```python def _validate_timezone(tz_name: str) -> str: """Validate timezone string against system database. Returns default if invalid.""" try: ZoneInfo(tz_name) return tz_name except (KeyError, ValueError): return DEFAULT_TZ ``` Перехватывается только `(KeyError, ValueError)`.
  - Живой прогон подтвердил порог ровно 256 символов (не приблизительно, а точно совпадает с формулировкой кандидата «≥256»): ``` 255 → ZoneInfoNotFoundError (подкласс KeyError) — перехвачено, вернуло DEFAULT_TZ 256 → OSError(63, 'File name too long') — НЕ перехвачено ``` Причина: `zoneinfo` резолвит ключ в файловый путь под `tzdata/zoneinfo/<key>` и делает `open()`; на macOS/Linux компонент имени файла ограничен 255 байтами, при превышении ОС бросает `OSError`, а не `ValueError`/`KeyError`. `OSError` не входит в MRO `ValueError` или `KeyError` — исключение не перехватывается, пробрасывается из `_validate_timezone` в вызывающий view.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-121.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-103 · P3 · `app/api/daily_plan.py:738,1111,1328`

- **Кандидат:** `DP-C-132` · линзы-источники: API-B-15 · скептик: `skeptics/DP-C-132.md`
- **Симптом:** битый JSON молча становится `{}` и рапортуется как ошибка поля, а не `invalid_json`
- **Сценарий отказа:** механизм воспроизведён напрямую: во всех трёх эндпоинтах `request.get_json(silent=True) or {}` схлопывает и «нет тела», и «синтаксически битое тело» в один и тот же пустой словарь, после чего код репортит ошибку конкретного поля (`invalid_event_type` / `invalid_days` / `invalid_input`) вместо `invalid_json`, хотя такой код ошибки в проекте существует и используется в `words.py`/`auth.py`/`anki.py`. Сценарий: клиент шлёт `POST /api/daily-plan/plan/pause` с `Content-Type: application/json` и телом `{"days": 3,}` (trailing comma — невалидный JSON) → получает `400 invalid_days` вместо `400 invalid_json`, хотя проблема не в значении `days`, а в том, что тело вообще не распарсилось. Severity понижена относительно интуиции «испорченный JSON» до P3: во всех трёх случаях HTTP-статус остаётся `400`, запрос корректно отклоняется, данные не пишутся и не портятся (собственно кандидат про «потерю данных» не заявляет). Эффект — только неточный `error`-код в JSON-ответе; `grep` по `app/static/js/` не нашёл ни одного клиентского консьюмера, который бы различал `invalid_json` и `invalid_event_type`/`invalid_days`/`invalid_input` в поведении (retry-логика, разные сообщения и т.п.) — расхождение наблюдаемо только при ручной отладке/чтении кода, не в UX.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:734` — `body = request.get_json(silent=True) or {}` в `record_daily_plan_event`; строка 735 `event_type = body.get('event_type', '')`; при битом JSON `event_type=''`, что не входит в `_CLIENT_EVENTS` → строки 740–744 отдают `api_error('invalid_event_type', ...)`, не `invalid_json`. Проверка `if not request.is_json` (строка 732) гейтит только заголовок `Content-Type`, а не валидность самого тела — repro ниже это подтверждает.
  - `app/api/daily_plan.py:1108` — `body = request.get_json(silent=True) or {}` в `plan_pause`; проверки `request.is_json` перед этим нет вообще. Строка 1109 `days = body.get('days')` → `None` при битом JSON → строка 1110 `not isinstance(days, int)` истинно → `api_error('invalid_days', ...)`, не `invalid_json`.
  - `app/api/daily_plan.py:1325` — `body = request.get_json(silent=True) or {}` в `skip_lesson`; строка 1326 `lesson_id = body.get('lesson_id')` → `None` → строка 1328 `not isinstance(lesson_id, int)` истинно → `api_error('invalid_input', ...)`, не `invalid_json`.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-132.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md фиксирует `api_error(code, message, status)` как «единый helper, не ad-hoc dicts» (секция Dashboard & API), но не предписывает конкретный код `invalid_json` для этого случая; расхождение — между `daily_plan.py` и параллельной конвенцией в `words.py`/`auth.py`/`anki.py`, не с CLAUDE.md напрямую.

#### DP-104 · P3 · `app/api/daily_plan.py:915-921`

- **Кандидат:** `DP-C-136` · линзы-источники: API-B-19 · скептик: `skeptics/DP-C-136.md`
- **Симптом:** `/api/error-review/summary` — единственный GET зоны без `success` в 200-теле
- **Сценарий отказа:** факт кода подтверждён буквально: из 8 GET-роутов зоны 7 явно кладут `success: True` в 200-тело, `error_review_summary` — нет. Сценарий: клиент, использующий общий паттерн зоны (`if (!data.success) ...`, как в остальных 7 ручках и в `linear-plan-context.js` для соседних API), на 200-ответе от `/api/error-review/summary` получит `data.success === undefined` — falsy, то есть код трактовал бы валидный успешный ответ как неуспех. Понижаю severity до P3 относительно выданной формулировки: эндпоинт сейчас не имеет ни одного консьюмера в репозитории (JS/шаблоны/тесты) — расхождение контракта реально, но наблюдаемого эффекта на живых сценариях сегодня нет, это латентная ловушка для будущего клиента, а не активный сбой.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:902-921` — тело хендлера: ```python return jsonify({ 'unresolved_count': count_unresolved(user_id, db), 'last_resolved_at': last_resolved.isoformat() if last_resolved is not None else None, 'by_lesson': breakdown['by_lesson'], 'by_topic': breakdown['by_topic'], }) ``` Ключа `success` нет.
  - Для сравнения — все прочие GET зоны явно кладут `'success': True` в корень 200-тела: `app/api/daily_plan.py:415` (`daily_status`, `payload = {'success': True, ...}`), `app/api/daily_plan.py:497` (`daily_plan`, `payload = {'success': True, 'route_state': ..., **plan}`), `app/api/daily_plan.py:531` (`daily_summary`, `jsonify({'success': True, **summary})`), `app/api/daily_plan.py:551` (`streak`, `jsonify({'success': True, **status})`), `app/api/daily_plan.py:599` (`daily_race_status`, `jsonify({'success': True, 'race': standings})`), `app/api/daily_plan.py:661` (`daily_plan_next_slot`, `payload['success'] = True; return jsonify(payload)` — и даже exception-ветка `app/api/daily_plan.py:640` возвращает `{'success': False, ...}`), `app/api/daily_plan.py:709-713` (`daily_plan_continuation`, `jsonify({'success': True, 'steps': ..., ...})`).
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-136.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** CLAUDE.md фиксирует только общий helper для ошибок (`api_error` в `app/api/errors.py`) и глобальный JSON-конверт для 4xx/5xx (`handle_403/404/500_error`), но не декларирует обязательный `success` для 200-тел. Инвариант «`success` в 200» — не документированный в CLAUDE.md, а фактический (де-факто) паттерн внутри самого файла `app/api/daily_plan.py`. Расхождение — код | код (внутренняя несогласованность одного файла), не код | CLAUDE.md.

#### DP-105 · P3 · `app/api/daily_plan.py:1361`

- **Кандидат:** `DP-C-140` · линзы-источники: API-C-02 · скептик: `skeptics/DP-C-140.md`
- **Симптом:** `LessonSkip` пишется и жрёт квоту, но его читатели (`linear/slots/curriculum_slot.py`) мертвы: снапшот не перестраивается, план показывает тот же урок
- **Сценарий отказа:** механизм отказа реален и хуже, чем заявлено: `POST /api/daily-plan/skip-lesson` пишет `LessonSkip`, тратит суточную квоту (1/день) и в своём собственном JSON-ответе честно вычисляет `next_lesson_id`, но это значение никуда не сохраняется. Замороженный required-снапшот (`DailyPlanLog.plan_json`), который реально рендерит дашборд, не инвалидируется и не перестраивается — при повторной загрузке плана пользователь снова видит тот же урок. Сценарий: юзер зовёт `skip-lesson` для `lesson_id=42` → квота 1/1 исчерпана → следующий `GET` дневного плана всё равно отдаёт required-item с тем же `lesson_id=42` (снапшот не менялся). Единственная неточность кандидата — атрибуция: «мёртвый читатель» это не `chain.py` (в нём `LessonSkip` вообще не упоминается ни разу), а `app/daily_plan/linear/slots/curriculum_slot.py::get_deferred_lesson_ids`/`get_skips_used_today` — обе функции читают `LessonSkip`, но не имеют ни одного вызывающего места нигде в `app/`. Дополнительный факт, усиливающий вывод: ни один фронтенд-файл вообще не вызывает `/api/daily-plan/skip-lesson` — единственная skip-кнопка в продукте (`linear-daily-plan.js`) использует параллельный механизм `DailyPlanEvent(slot_skipped)`, который *действительно* читается (`_get_unified_skipped_kinds` в `app/daily_plan/plan.py`) и работает. Поэтому реальный пользователь эффект кандидата испытать не может — эндпоинт `skip-lesson` orphaned end-to-end (мёртвый и на входе, и на выходе), а не просто «читатель мёртв». **Severity:** понижаю с P1 до **P3** — это не «ключевой сценарий ломается у части пользователей»: сам эндпоинт недостижим из UI (грепом подтверждено отсутствие вызовов из `app/static/js` и `app/templates`), так что описанный дефект не проявляется ни у одного реального пользователя через обычный интерфейс — это мёртвая/нефункциональная фича целиком (сервер + отсутствующий клиент), а не тихая порча рабочего сценария.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:1352-1358` — квота считается по `LessonSkip.skipped_on_date == today`, `429 skip_quota_exhausted` при исчерпании — квота реально тратится.
  - `app/api/daily_plan.py:1361-1372` — `LessonSkip` пишется и коммитится.
  - `app/api/daily_plan.py:1376-1383` — `next_lesson_id` вычисляется через `find_next_lesson(..., exclude_lesson_ids=deferred_ids)` **только для JSON-ответа этого запроса**; `DailyPlanLog.plan_json` (замороженный required-снапшот) при этом не трогается.
  - `app/daily_plan/linear/slots/curriculum_slot.py:63-67` — docstring прямо признаёт: *«Current daily-plan skip behavior does not use `LessonSkip` rows; it records `DailyPlanEvent(slot_skipped)` and keeps the curriculum spine intact. This helper is retained only so old rows/tests remain readable.»*
  - `app/daily_plan/snapshot.py:70-108` — `resolve_snapshot_for_today` возвращает существующий `plan_json`, если он валиден (v3), иначе строит/роллит; нигде в цепочке нет обращения к `LessonSkip`, и вызов `skip_lesson()` не инвалидирует `log.plan_json`.
  - `app/static/js/linear-daily-plan.js:206-254` — единственный skip-UI шлёт `event_type:'slot_skipped'` на `/api/daily-plan/events`, не на `/api/daily-plan/skip-lesson`.
- **Где расхождение:** код — CLAUDE.md документирует `skip-lesson` (квота 1, `already_deferred`/`skip_quota_exhausted`/`next_lesson_id`) как рабочий контракт, не упоминая, что он не подключён ни к одному UI-элементу и не влияет на реально показываемый план.

#### DP-106 · P3 · `app/api/daily_plan.py:748-755`

- **Кандидат:** `DP-C-142` · линзы-источники: API-C-08 · скептик: `skeptics/DP-C-142.md`
- **Симптом:** `/skip-lesson` не гейтится паузой, хотя `slot_skipped` гейтится
- **Сценарий отказа:** CONFIRMED (буквально) — механизм отсутствия пауз-гейта в `skip_lesson` реален и воспроизводим прямым чтением кода: `slot_skipped` явно проверяет `is_plan_paused`, `skip_lesson` — нет. Формально кандидат прав. Но у находки нет наблюдаемого эффекта в текущей архитектуре: (1) у роута нет ни одного вызывающего во фронтенде/боте — достижим только прямым HTTP-запросом в обход UI; (2) даже при вызове его единственный побочный эффект — строка `LessonSkip` — не читается нигде, кроме собственных проверок `already_deferred`/`skip_quota_exhausted` этого же роута: реальный `required` unified-плана строится через `resolve_snapshot_for_today` → `build_required_snapshot` → `_collect_curriculum_chain`, которая `LessonSkip` не потребляет вовсе (актуальный механизм отложения — `DailyPlanEvent(slot_skipped)`, что подтверждено докстрингом в `curriculum_slot.py`). Поэтому вызов `skip_lesson` во время паузы не нарушает day_secured, XP, streak или видимый юзеру список required — эффект ограничен инертной строкой в БД и трактой квоты внутри самого же роута. Понижаю severity с подразумеваемого P1/P2 до P3: расхождение паттерна гейтинга между двумя похожими эндпоинтами реально, но затрагивает практически мёртвый код без наблюдаемых последствий.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:751-755` (в `record_daily_plan_event`): `_PAUSE_BLOCKED = {'slot_skipped', 'next_step_accepted', 'session_ended_at_minimum'}` → `if is_plan_paused(current_user): return api_error('plan_paused', ...)`.
  - `app/api/daily_plan.py:1296-1385` (`skip_lesson`): полное тело функции не содержит ни одного упоминания `is_plan_paused`, `plan_paused_until` или импорта `app.daily_plan.service` — гейта нет буквально, чек подтверждён построчным чтением.
  - `app/daily_plan/plan_builder.py:141-160` (`_collect_curriculum_chain`) и `app/daily_plan/linear/progression.py:44-54` (`find_next_lesson_linear`): `exclude_lesson_ids` формируется только из уже отобранных в текущей цепочке лессонов — `LessonSkip` таблица нигде не читается напрямую как источник исключений для реального `required`-снапшота.
  - `app/daily_plan/linear/slots/curriculum_slot.py:62-68`: «Current daily-plan skip behavior does not use `LessonSkip` rows; it records `DailyPlanEvent(slot_skipped)` and keeps the curriculum spine intact. This helper is retained only so old rows/tests remain readable.» — прямое подтверждение из кода, что механизм `LessonSkip` вытеснен `slot_skipped` и является легаси.
  - Полнотекстовый grep `skip-lesson|skip_lesson` по репозиторию не находит ни одного вызова из `app/static/**`, `app/templates/**` или telegram-бота — только сам роут и тесты.
- **Где расхождение:** код — оба эндпоинта живут в одном файле и оба относятся к «Lesson skip» / «Slot-skip helpers» секции CLAUDE.md, но CLAUDE.md не формулирует явного инварианта «все plan-altering действия обязаны гейтиться паузой»; это внутренняя конвенция, введённая комментарием у `_PAUSE_BLOCKED`, которую `skip_lesson` не унаследовал.

#### DP-107 · P3 · `app/api/daily_plan.py:694-709`

- **Кандидат:** `DP-C-143` · линзы-источники: API-C-10 · скептик: `skeptics/DP-C-143.md`
- **Симптом:** 7 из 9 `event_type` без продюсеров и консьюмеров — csrf-exempt запись под общим rate-limit'ом
- **Сценарий отказа:** CONFIRMED с поправками — механизм («мёртвые» client-callable event_type без продюсера/консьюмера, принимаемые тем же csrf-exempt эндпоинтом, что и живые) в коде есть и воспроизводим по коду. Но заявленные детали неточны в обе стороны: (1) фактическое число «мёртвых» (нет ни продюсера, ни консьюмера) — **7 из 9**, а не 6 — кандидат недооценил масштаб (`vocab_lookup` имеет продюсера, но не имеет консьюмера — «полу-мёртвый», не входит в строгую формулировку «ни того, ни другого»); (2) утверждение «без лимита» неверно буквально — эндпоинт защищён дефолтным глобальным rate-limit'ом Flask-Limiter (10000/час, 100/сек на IP) и требует аутентификации, то есть это не анонимная неограниченная запись. Эффект на пользователя/данные отсутствует: лишние `event_type` в whitelist — это остаток удалённой (`UI-031`, next-step баннер) и, судя по всему, никогда не реализованной на фронтенде (`rival_strip_*`) фичи телеметрии Phase-1 H1-эксперимента (см. `docs/decisions/2026-04-18-*.md` — события изначально предназначались для разового ручного SQL-анализа, а не для кодового консьюмера, так что «нет консьюмера в коде» отчасти ожидаемо по дизайну для этого класса телеметрии). Понижаю severity до **P3**: мёртвый/устаревший код и schema drift без наблюдаемого эффекта на данные, XP, streak или безопасность — не P0-P2, как можно было бы прочитать из формулировки «без лимита».
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:699-709` — `_CLIENT_EVENTS` содержит 9 значений: `next_step_shown`, `next_step_accepted`, `next_step_dismissed`, `session_ended_at_minimum`, `rival_strip_shown`, `rival_strip_dismissed`, `steps_taken_while_rival_visible`, `vocab_lookup`, `slot_skipped`.
  - Продюсеры (фронтенд `fetch(...daily-plan/events...)`) найдены ровно у **двух** значений: `slot_skipped` (`app/static/js/linear-daily-plan.js:224`, `app/templates/partials/unified_daily_plan.html:774`) и `vocab_lookup` (`app/templates/curriculum/lessons/text.html:2124`). У остальных **семи** (`next_step_shown/accepted/dismissed`, `session_ended_at_minimum`, `rival_strip_shown/dismissed`, `steps_taken_while_rival_visible`) — ни одного вызова вне тестов во всём `app/`. `rival_strip_dismissed`/`rival_strip_shown` дополнительно проверены на "rival strip"-UI в `app/static/js` и `app/templates` — совпадений 0: UI-фичи, которая бы их эмитила, в кодовой базе нет вовсе.
  - Консьюмеры (бэкенд-чтение `DailyPlanEvent` по этим `event_type`) найдены только для `slot_skipped` (`app/daily_plan/skips.py:45-53`, `app/daily_plan/plan.py:60`). Для остальных восьми значений — ни одного `.filter_by(event_type=...)`/`query(DailyPlanEvent)` с этим типом за пределами тестов. `vocab_lookup` — продюсер есть, консьюмера нет.
  - `@csrf.exempt` подтверждён буквально: `app/api/daily_plan.py:716`.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-143.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-108 · P3 · `app/api/daily_plan.py:1056-1075`

- **Кандидат:** `DP-C-145` · линзы-источники: API-C-13 · скептик: `skeptics/DP-C-145.md`
- **Симптом:** `phrase_review_completed` — check-then-insert без уникальности
- **Сценарий отказа:** CONFIRMED, но с существенной поправкой к формулировке. Часть «check-then-insert без уникальности → две записи» подтверждена буквально: механизм гонки есть, backstop (partial unique index), который для соседних `event_type` в этой же таблице явно существует, для `phrase_review_completed` отсутствует. Сценарий: пользователь на медленной сети дважды тапает «Отправить» (или клиент ретраит запрос) → два конкурентных POST → оба `SELECT` видят `event is None` → оба `INSERT` → в `daily_plan_events` две строки с одинаковыми `(user_id, plan_date, event_type='phrase_review_completed')`. Часть «двойной эффект» — не подтверждена, эффект не наступает: 1. `phrase_review_completed_today()` (`app/daily_plan/items/phrase_review.py:173-184`) читает результат через `.first()` — булева проверка существования, безразлична к числу строк. 2. XP за это событие нигде не начисляется (grep по `app/` не нашёл начисления, привязанного к `phrase_review_completed`/`phrase_review`). 3. `resolve_quiz_error()` (`app/daily_plan/linear/errors.py:215-231`) идемпотентен сам по себе — `if entry.resolved_at is None: entry.resolved_at = ...` — повторный вызов на том же `error_id` (что происходит при двойном POST независимо от гонки на `DailyPlanEvent`) — no-op. Итог: дефект реален (лишняя строка audit/telemetry-таблицы при гонке), но не «двойной эффект» — понижаю severity с предполагаемого P2 до P3 (мёртвая дублирующая строка без наблюдаемых последствий для пользователя/XP/streak).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:1057-1074` — ровно паттерн check-then-insert без блокировки: ```python event = db.session.query(DailyPlanEvent).filter_by( user_id=current_user.id, event_type='phrase_review_completed', plan_date=today, ).first() ... if event is None: db.session.add(DailyPlanEvent(...)) else: event.reason_text = ... ``` Между `SELECT` и `INSERT` нет ни `begin_nested()`, ни `SELECT ... FOR UPDATE`, ни `try/except IntegrityError` — паттерна, которым в этом же файле/проекте защищены `write_secured_at` (`DailyPlanLog`, `uq_daily_plan_log_user_date`), `grant_achievement`, `_get_or_create_prompt` (survey), `TelegramNotificationLog.claim`.
  - `app/daily_plan/models.py:75-78` — `__table_args__` для `DailyPlanEvent` содержит только два обычных (не уникальных) индекса: `idx_daily_plan_events_user_date`, `idx_daily_plan_events_type`. Уникального индекса на `(user_id, event_type, plan_date)` в принципе нет.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-145.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — этот же файл/ таблица `daily_plan_events` в проекте уже трижды получала выделенный partial-unique индекс именно под эту гонку (`minimum_completed`, `route_step_added`, `slot_skipped`), а `phrase_review_completed` такого индекса не получил — расхождение внутри самого кода/истории миграций, не с текстом CLAUDE.md.

#### DP-109 · P3 · `app/words/routes.py:1024-1039`

- **Кандидат:** `DP-C-149` · линзы-источники: API-D-05 · скептик: `skeptics/DP-C-149.md`
- **Симптом:** нормализация completion — доказуемый no-op; INV-16 описывает эффект, которого не бывает
- **Сценарий отказа:** оба цикла нормализации (`required` и `optional`) в `app/words/routes.py` доказуемо не меняют состояние ни при каких входных данных при текущей реализации `_compute_unified_item_completion` и `build_optional`. Условие срабатывания тождественно уже-истинному состоянию (`completed`), а `skipped`/`blocked` в этот момент уже `False`/отсутствуют по построению. Не рантайм-баг (ничего не портит), а мёртвый код с комментарием, описывающим устаревший (удалённый три недели спустя после написания) механизм.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/plan.py:74-85` (`_apply_unified_skip_state`): `if item.get('completed', False): continue` перед `item['skipped'] = True` — skip применяется ТОЛЬКО к ещё не завершённым в рамках текущей сборки итемам. Значит на любом единичном билде плана `completed=True` и `skipped=True` для одного и того же required-item **взаимоисключающи по построению**.
  - `app/achievements/streak_service.py:172-185` (`_compute_unified_item_completion`): для required-items `plan_completion[id] = item['completed'] or summary_kind_done.get(item['kind'], False)`, а `summary_kind_done` содержит единственный ключ `'error_review'`. Но `error_review`-итем **никогда не попадает в required** — единственный конструктор с `kind == 'error_review'` находится в `app/daily_plan/plan.py:308-312` внутри `_build_optional_candidate` и всегда вызывает `build_error_review_item(..., section='optional')`; в `_OPTIONAL_PRIORITY` (строки 106-113) `error_review` тоже только optional. Значит для реальных required-items `summary_kind_done` всегда даёт `False`, и `plan_completion[id] == item['completed']` **тождественно**, без исключений.
  - _(ещё 5 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-149.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — инвариант в CLAUDE.md не упомянут; он живёт только в собственном комментарии кода, который сам и устарел вместе с удалением `'srs'`-фолбэка.

#### DP-110 · P3 · `app/daily_plan/linear/plan.py:196`

- **Кандидат:** `DP-C-150` · линзы-источники: API-D-06 · скептик: `skeptics/DP-C-150.md`
- **Симптом:** флаг `blocked` в unified не выставляет никто: 8 осиротевших читателей, ветка `_state='blocked'` мертва
- **Сценарий отказа:** механизм-сеттер `slot['blocked'] = True` реально существует по указанной строке, но достижим только через `get_linear_plan()`, который сам недостижим ни из одного роута/сервиса продакшна (0 вызывающих). В боевом unified-пайплайне (`app/daily_plan/plan.py` → `unified_daily_plan.html`, `build_lesson_context`) ключ `blocked` никогда не устанавливается в `True`, поэтому ветка `_state == 'blocked'` в шаблоне (строка 344) и условия `not slot.get('blocked')` в `_pick_next_slot` — недостижимый код: они всегда получают `False`/`None`. Сценарий: пользователь пропускает обязательный curriculum-слот в unified-плане → `_apply_unified_skip_state` помечает его `skipped=True`; последующие curriculum-зависимые пункты (`speaking`/`writing`) НЕ получают специфичного `blocked=True` и подсказки «Сначала завершите урок курса» — они просто попадают в generic `_state='locked'` через позиционный `current_idx` (что закрывает функциональную дыру доступа, но подтверждает мёртвость именно `blocked`-ветки и её сообщения). Функционального регресса (утечки доступа, порчи данных) нет — legacy-каскад заменён другим рабочим механизмом (`curriculum_skipped` гейтит continuation-очередь). Severity понижаю до **P3**: это мёртвый код / орфанные читатели с косметическим эффектом (никогда не показываемое сообщение-подсказка), а не сломанный ключевой сценарий.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/plan.py:196` — `slot['blocked'] = True` действительно существует, но живёт внутри `_apply_skipped_slots` (строки 167–199), единственный вызов которой — `app/daily_plan/linear/plan.py:354`, внутри `get_linear_plan()`.
  - `grep -rn "get_linear_plan" app/` → ровно 2 совпадения: определение (`linear/plan.py:299`) и докстринг-упоминание в `linear/xp.py:515` («наборы слотов расходились с unified»). Ни одного вызывающего кода — функция недостижима.
  - `app/daily_plan/plan.py:352-357` — единственный импорт из `linear/plan.py` в реальном оркестраторе: `_get_user_focus, _level_progress_to_dict, _position_from_lesson, get_plan_intensity` — без `get_linear_plan` и без `_apply_skipped_slots`.
  - `app/daily_plan/plan.py:68-84` (`_apply_unified_skip_state`) — единственное реальное место, где к required-item в unified-плане что-то дописывается по skip-событию, и оно пишет только `item['skipped'] = True`; `blocked` там не присваивается нигде.
  - `app/daily_plan/items/__init__.py:57` — `PlanItem` (источник всех `required_dicts`/`optional_dicts` через `to_dict()`) не имеет поля `blocked` вообще.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-150.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — в CLAUDE.md механизм `blocked` для unified-плана не описан вовсе (описан только «Заблокированный спайн ≠ graduated» через отдельный `blocked_module`/`spine_blocked`, что не то же самое поле и работает корректно); расхождения с документом нет, это чисто внутрикодовый мёртвый путь, оставшийся от legacy `linear/plan.py`.

#### DP-111 · P3 · `app/words/routes.py:1144-1156`

- **Кандидат:** `DP-C-151` · линзы-источники: API-D-07, FE-A-01 · скептик: `skeptics/DP-C-151.md`
- **Симптом:** graduated видит одновременно «Откройте каталог, чтобы начать обучение» и «Завершите настройку ниже»
- **Сценарий отказа:** сценарий: юзер прошёл весь курс (`graduated=True`), у него уже выбрана книга для чтения, но она ещё не дочитана до конца. Тогда `required=[]` и `setup=[]`. На странице `/dashboard` (unified) он одновременно видит вверху hero-подзаголовок «Откройте каталог, чтобы начать обучение» (`app/words/routes.py:1156`) и ниже, в секции «Обязательно сегодня», пустое состояние «Завершите настройку ниже, чтобы получить план дня» (`unified_daily_plan.html:510`) — при этом никакой секции настройки на странице нет (`u_setup_footer` пуст), так что указание «ниже» ведёт в никуда. Оба текста ложны для этого юзера: каталог ему открывать незачем (курс пройден), а настраивать нечего (setup пуст). Функционально день всё равно закрывается через optional-активность (`compute_day_secured_from_activity` для graduated), поэтому это чисто текстовое/UX-противоречие без потери функциональности или данных.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/words/routes.py:1156` — `else: subtitle = 'Откройте каталог, чтобы начать обучение'`, срабатывает когда `steps_total` falsy.
  - `app/achievements/streak_service.py:201-205` (unified-ветка `compute_plan_steps`) — `steps_total = len(required_items)`, т.е. `steps_total == 0` ⇔ `unified_plan['required']` пуст — то же самое условие, что использует шаблон.
  - `app/daily_plan/plan.py:388-394` — `graduated = next_lesson is None and blocking_module_id is None and has_completed_history(...)`; при `graduated` `required = []` (строки 396-398).
  - `app/daily_plan/plan.py:323-344` (`build_setup`) — `setup_book` эмитится только если `reading_preference_needs_setup(...)` True; `setup_level` — только если `next_lesson is None and not has_completed_history(...)`. Для graduated `has_completed_history` истинно по определению, значит `setup_level` никогда не появляется. Если у юзера уже есть `UserReadingPreference` на книгу, которая ещё не дочитана (`_book_is_actionable_for_reading` → True), `reading_preference_needs_setup` тоже False → `setup=[]`.
  - `app/templates/partials/unified_daily_plan.html:482-513` — `{% if u_required %}...{% else %}` (пустой `u_required`) при пустом `u_blocked_module` рендерит ровно `Завершите настройку ниже, чтобы получить план дня.` (строка 510), без проверки, есть ли вообще что «завершать».
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-151.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — сама копия двух независимо написанных empty-state текстов (`app/words/routes.py` и `app/templates/partials/unified_daily_plan.html`) не согласована для случая `graduated` без незавершённого setup; в CLAUDE.md этот кейс не описан отдельно.

#### DP-112 · P3 · `app/achievements/streak_service.py:202`

- **Кандидат:** `DP-C-154` · линзы-источники: API-D-10 · скептик: `skeptics/DP-C-154.md`
- **Симптом:** `steps_available` — мёртвый элемент кортежа
- **Сценарий отказа:** во всех 8 продакшн call site'ов возвращаемое значение `steps_available` либо явно отброшено (`_`/`_avail`/`_steps_available`), либо (в `daily_status`) присвоено читаемому имени и затем ни разу не прочитано до конца функции. Внутри самой `compute_plan_steps` промежуточная локальная переменная с тем же именем действительно используется в ветках `steps`/legacy для подсчёта `steps_done`/`steps_total` (`streak_service.py:244-245,276-277`) — это не мёртвый код, это внутренняя механика. Но как **элемент возвращаемого кортежа**, потребляемый вызывающим кодом, он мёртв во всех 8 продакшн-вызовах: сценарий — любой запрос к `/api/daily-status` вычисляет полный dict `steps_available` (до 5+ ключей на каждый required-item плана) и тут же выбрасывает его, не влияя ни на один байт ответа или побочный эффект. Юнит-тесты (`tests/test_daily_mission_api.py:194,209 и т.д.`) действительно читают и ассертят это поле напрямую — но это тестирование контракта самой функции, а не продакшн- потребление; ни один из этих тестов не переживает до слоя API/шаблонов/бота.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/achievements/streak_service.py:192` — докстринг документирует контракт: `Returns (plan_completion, steps_available, steps_done, steps_total)`.
  - `app/achievements/streak_service.py:202,210,218,234-239,268` — во всех 4 форматах плана `steps_available` вычисляется и возвращается третьим... вторым элементом кортежа.
  - `app/words/routes.py:534` — `plan_completion, _avail, _done, _total = compute_plan_steps(...)` — отброшен.
  - `app/words/routes.py:659` — `plan_completion, _steps_available, steps_done, steps_total = compute_plan_steps(...)` — отброшен.
  - `app/words/routes.py:1020` — `plan_completion, _avail, steps_done, steps_total = compute_plan_steps(...)` — отброшен.
  - `app/words/routes.py:1705` — `plan_completion, _, steps_done, steps_total = compute_plan_steps(...)` — отброшен.
  - `app/study/routes.py:623` — `plan_completion, _, _, _ = compute_plan_steps(plan, summary)` — отброшен.
  - `app/daily_plan/linear/xp.py:555` — `plan_completion, _, _, _ = compute_plan_steps(plan, summary)` — отброшен.
  - `app/api/daily_plan.py:479` — `plan_completion, _, _, _ = compute_plan_steps(plan, summary)` — отброшен.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-154.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-113 · P3 · `app/templates/partials/unified_daily_plan.html:46-69`

- **Кандидат:** `DP-C-155` · линзы-источники: API-D-11 · скептик: `skeptics/DP-C-155.md`
- **Симптом:** 4 словаря kind'ов, ни один не совпадает с фактическим набором; `word_set_quiz` не описан нигде
- **Сценарий отказа:** механизм подтверждён чтением кода: `word_set_quiz` — живой kind (есть в каноническом `Kind` Literal, реально создаётся `build_word_set_quiz_item` и попадает в `optional`-секцию), но отсутствует во всех словарях резолюции лейбла/иконки (`kind_section_labels`, `kind_icons`), которые эту секцию рендерят. Эффект наблюдаем и воспроизводим по коду без внешних данных: карточка «Квиз: <название набора>» в блоке «Дальше по курсу» рендерится без eyebrow-лейбла типа (как у «Аудирование», «Грамматика» и т.д.) и без иконки-глифа — просто заголовок + бейдж «Бонус». Функционально карточка не ломается (ссылка, заголовок, подзаголовок на месте), деградация чисто визуальная/косметическая — сама карточка кликабельна и работает. Частичная поправка формулировки кандидата: «4 словаря, ни один не совпадает» — преувеличение для `lesson_kind_labels` (он умышленно индексирован по `lesson_type`, а не по `kind`, и не обязан покрывать `Kind` вовсе — не находка) и для отсутствия `curriculum`/`setup_*` в `kind_section_labels` (у них есть выделенные ветки рендера, отсутствие в общем словаре — по дизайну). Но ядро утверждения — «`word_set_quiz` не описан нигде» — подтверждено буквально: 0 упоминаний в `kind_section_labels`, `kind_icons`, `goal_chip_labels` и во всём каталоге `app/templates/`. Также попутно найдено, что `challenge` отсутствует в `kind_section_labels` (но есть в `kind_icons` — частичное покрытие), что не входит в кандидата, но подтверждает общий паттерн незавершённой синхронизации словарей с `Kind`.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/items/__init__.py:23-35` — `Kind = Literal['curriculum','srs','reading','listening','speaking','writing','error_review','grammar_review','phrase_review','word_set_quiz','challenge','setup_book','setup_level']`.
  - `app/templates/partials/unified_daily_plan.html:46-56` — `kind_section_labels` содержит 8 ключей (`reading,listening,speaking,writing,error_review,srs,grammar_review,phrase_review`); `word_set_quiz` отсутствует.
  - `app/templates/partials/unified_daily_plan.html:58-69` — `kind_icons` содержит 10 ключей (включая `challenge`); `word_set_quiz` отсутствует.
  - `app/templates/partials/unified_daily_plan.html:611-618` (optional-список) — `{% if _kind == 'curriculum' %} ... {% elif _kind in kind_section_labels %} ... {% endif %}` → для `_kind == 'word_set_quiz'` `_label` остаётся `''`, `_kind_glyph = kind_icons.get(_kind, '')` тоже `''`.
  - `app/templates/partials/unified_daily_plan.html:632-634` — `{% if _label %}<span class="plan-item__kind-label">{{ _label }}</span>{% endif %}` — блок с eyebrow-лейблом просто не рендерится.
  - Поля `data.set_icon`/`data.set_accent`, которые `word_set_quiz.py:61-62` кладёт специально для этого вида карточки, нигде в `app/templates/` не читаются (`grep` — 0 совпадений) — они мертвы на уровне рендера.
- **Где расхождение:** код — кандидат не затрагивает задокументированный в CLAUDE.md инвариант (на момент находки ветка `word-sets-quiz` в master не влита и в CLAUDE.md не описана); чинится правкой шаблона.


### Опровергнуто скептиками — не переоткрывать без новых фактов

| Кандидат | Якорь | Утверждение финдера | Почему опровергнуто |
|---|---|---|---|
| `DP-C-112` | `app/words/routes.py:1777` | next-step рапортует `all_done:true` юзеру на паузе и при аварийной сборке | API действительно возвращает поле `all_done: true` в обоих описанных состояниях (технически кандидат не выдумал данные), но описанный эффект — «юзер видит ложное сообщение о завершении плана» — не наступает: единственный код, который читает этот ответ, обрывается по `if (total === 0) return;` раньше, чем доходит до `data.all_done`. Полоса `#daily-plan-bar` остаётся скрытой (`display:none`), никакого UI-сигнала польз… |
| `DP-C-119` | `app/api/daily_plan.py:441,493` | `route_state`/`success`/`plan_paused` присутствуют не во всех источниках плана | `/api/daily-status` и `/api/daily-plan` не являются альтернативными «источниками» одного и того же контракта плана: это два независимо задокументированных (собственные docstring'и) и независимо протестированных эндпоинта с намеренно разными payload-схемами (`plan_paused`-флаг vs `mode`-строка; `route_state` только там, где он реально используется). Ни один консьюмер в кодовой базе не ожидает единообразия этих ключей… |
| `DP-C-133` | `app/api/daily_plan.py:772-777` | `step_kind` любого типа проходит через `str(...)` и ложится в БД | механизм `str(step_kind)[:40]` действительно применяется без проверки типа/enum для телеметрийных event_type, но это не приводит к описанному эффекту (порча данных / нарушение инварианта): (1) обрезка `[:40]` точно совпадает с длиной колонки `String(40)`, INSERT не может упасть; (2) вставка идёт через SQLAlchemy ORM с параметризацией — инъекции нет; (3) единственный путь, где `step_kind` читается обратно и участвует… |
| `DP-C-134` | `app/api/daily_plan.py:623-643` | `/next-slot` не проверяет `current`/`lesson_id`: молчаливая подмена ответа + перечисление названий и URL уроков каталога | эндпоинт валидирует ровно то, что имеет значение: личность пользователя (`@api_auth_required` → `current_user.id`), а сам план всегда его собственный (`get_unified_plan(current_user.id, db)`). `current`/`lesson_id` — это UX-хинт «где я нахожусь в своей же уже видимой на дашборде цепочке», не ключ доступа к чужим или каталожным данным; при некорректном значении срабатывает документированный fallback на первый активны… |
| `DP-C-135` | `app/api/daily_plan.py:1148,1181` | `/plan/pause` и `/resume` отвечают `{'status':'ok'}` — единственные в зоне без `success` | сам факт (pause/resume отвечают `{'status':'ok'}` без `success`) подтверждён буквально, но утверждение «единственные в зоне без ключа `success`» ложно: в том же файле `error_review_summary` (строка ~915) и `challenge_complete` (строка 1206, через `complete_challenge`) тоже отдают JSON без ключа `success`. Уникальность — ядро кандидата — не подтверждается чтением кода. |
| `DP-C-137` | `app/api/daily_plan.py:1038-1041` | `/phrase-review/complete`: не-итерабельный `accepted_answers` → 500, `session.pop` ниже точки падения | заявленный механизм («не-итерабельный `accepted_answers`») требует, чтобы `item['accepted_answers']` мог оказаться нетерируемым значением (int/bool/None-без-fallback и т.п.). Но единственный производитель этого поля, `_candidate()` в `app/daily_plan/items/phrase_review.py`, всегда кладёт туда `list[str]`, и путь построения `item` — детерминирован (`get_phrase_review_items` → `_error_candidates`/`_recent_module_candi… |
| `DP-C-138` | `app/api/daily_plan.py:97-101` | соседние blanket-`except` ведут себя противоположно: один откатывает всю сессию, второй не откатывает ничего перед финальным `commit()` | асимметрия в стиле обработки исключений (одни `except` откатывают, другие только логируют) в коде действительно есть, но заявленный эффект («второй ничего не откатывает перед финальным `commit()`») не воспроизводится: 1. Единственный `commit()`, идущий следом за не-роллбэкающим `except` (строка 320-321 → вызов на 324), — это `db.session.commit()` внутри `_sync_unified_route_steps` (96), но прежде чем до него дойти,… |
| `DP-C-141` | `app/daily_plan/plan.py:74-85` | «не сегодня» по обязательному слоту делает `day_secured` недостижимым весь день | механизма «insurmountable для всего дня» нет. `slot_skipped` — чисто навигационная пометка (снимает блокировку «сначала текущий шаг» для UI, отдаёт `active_slot`), она не устанавливает `completed=False` и не удаляет/не блокирует URL слота. `completed`/`plan_completion`, от которых реально зависит `day_secured`, пересчитываются на каждой сборке плана из настоящей активности (`overlay_completion` → per-kind детектор)… |
| `DP-C-148` | `app/templates/partials/unified_daily_plan.html:265` | required-пункт с `url=None` рисуется как «Начать →» с `href="#"`, ни одна поверхность об этом не сигналит | механизм (`_url = item.get('url') or '#'`) в коде есть, но эффект не наступает: инвариант «`url=None` ⇒ `completed=True`» соблюдён во всех точках, формирующих `required` (снапшот-билдеры, live-оверлей, конкретные item-конструкторы для curriculum/srs/reading/grammar_prep), а `completed=True` уводит рендер в ветку `done`, которая CTA с `_url` не рисует вовсе. `_url or '#'` — защитный фолбэк на недостижимое состояние,… |
| `DP-C-153` | `app/daily_plan/items/error_review.py:121` | optional «Разбор ошибок» не гаснет никогда и в видимой пятёрке запирает всё ниже | «не гаснет никогда» и «запирает всё, что ниже» (в смысле навсегда/без сигнала) не подтверждаются. У пункта действительно нет собственного флага `completed=True`, но функциональный эквивалент completion-сигнала есть: `should_show_error_review` пересчитывается на каждой сборке плана и осознанно убирает пункт из списка сразу после того, как юзер реально прошёл сессию разбора (resolve → cooldown-гейт → пункт исчезает →… |
| `DP-C-161` | `app/__init__.py:54-60` | ни одного `@limiter.limit` во всём `app/`; `memory://` на два воркера; `/events` без капа строк | центральный тезис кандидата («ни одного лимита ⇒ зона плана дня не защищена») перекрыт `default_limits` в `Limiter(...)` (`app/__init__.py:54-61`), который действует глобально на все роуты без явного `limiter.exempt`, а такого exempt для `app/api/daily_plan.py` в коде нет. Отсутствие endpoint-specific `@limiter.limit` — это норма для большинства зон приложения (auth/feedback/telegram/admin-audio — единственные исклю… |

---

## Подзона: Фронтенд плана (Task 5)

### Индекс

| ID | Sev | Файл:строка | Симптом | Вериф. | Расхождение |
|---|---|---|---|---|---|
| DP-114 | P2 | `app/static/js/lesson-completion.js` | единственный из четырёх потребителей `fetchNextSlot`, кто не проверяет `success === false`: серверный сбой рисуется как успешный экран | CONFIRMED | код |
| DP-115 | P2 | `app/templates/components/_daily_plan_progress.html` | «✨ План выполнен!» рисуется одновременно с «Шаг 0 из 1»: `all_done` приходит независимо от `steps_done/steps_total` | CONFIRMED | код |
| DP-116 | P3 | `app/static/js/linear-daily-plan.js` | мёртвый фронт-код: обработчики на data-атрибуты, которых не производит ни один шаблон, шаблон-сирота `_day_secured_banner.html`, мёртвые inline-guard… | CONFIRMED | код |
| DP-117 | P3 | `app/templates/components/_daily_plan_progress.html` | `r.json()` без проверки `r.ok`: любой не-2xx кончается тем, что бар не появляется | CONFIRMED | — |
| DP-118 | P3 | `app/templates/components/_daily_plan_progress.html` | мёртвая JWT-ветка: `localStorage.getItem('jwt_token')` — единственное упоминание во всём `app/` | CONFIRMED | — |

### P0 — детали

_(находок этого уровня в подзоне нет)_


### P1 — детали

_(находок этого уровня в подзоне нет)_


### P2 — детали

#### DP-114 · P2 · `app/static/js/lesson-completion.js`

- **Кандидат:** `DP-C-169` · линзы-источники: FE-B-08 · скептик: `skeptics/DP-C-169.md`
- **Симптом:** единственный из четырёх потребителей `fetchNextSlot`, кто не проверяет `success === false`: серверный сбой рисуется как успешный экран
- **Сценарий отказа:** механизм отказа воспроизводим по коду без предположений о недоступных данных. Сценарий: пользователь заходит на grammar-урок через daily plan (`?from=linear_plan&slot=curriculum`, клиентский `linearPlanContext` активируется независимо от серверного контекста). Если для этого юзера `build_lesson_context` детерминированно бросает исключение (например, специфичное состояние плана — класс багов, для которых в реестре уже есть отдельные находки про `build_lesson_context`/`blocked_module`) — то и на GET-рендере страницы (`_inject_daily_plan_ctx` глотает исключение → рендерится catalog-flow разметка без `[data-plan-cta]`), и на сабмите grammar-урока (`showLessonCompletion({score:...})` без `daily_plan_ctx`) → фолбэк на `ctx.fetchNextSlot()` → `/api/daily-plan/next-slot` падает тем же исключением → `{success:false, day_secured:false, next:null}`, HTTP 200. `lesson-completion.js` не отличает этот payload от валидного: `_renderPlanCtas(undefined, undefined, '/dashboard')` не находит `[data-plan-cta]`-узлов (их нет в DOM) и ничего не создаёт (в отличие от `applySrsPlanAwareCompletion`, у которого есть synthesise-фолбэк), а `_revealCompletion('plan')` выставляет `data-completion-mode="plan"`, что через CSS-правило `lesson_base_template.html:403` скрывает уже отрисованные catalog-CTA. Итог: экран показывает реальную оценку (она пришла из `opts.score`, не пострадала), но без единой кнопки навигации внутри `#lesson-completion` — сбой полностью замаскирован, никакого сообщения об ошибке нет. Разница с тремя siblings — именно отсутствие `data.success === false` проверки, что и есть суть кандидата. Severity понижена до P2 relative к тому, что могло бы быть P1: в шапке страницы всегда остаётся breadcrumb/exit-nav (`components/_lesson_header_nav.html`, `lesson_base_template.html:440`), то есть обход есть (пользователь не заперт на странице намертво), а сам триггер — составной (два независимых вызова `build_lesson_context` должны провалиться одинаково для одного юзера), не гарантированно частый.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:642-643` — на исключении внутри `build_lesson_context` эндпойнт отвечает `return jsonify({'success': False, 'day_secured': False, 'next': None}), 200` — статус 200, не 4xx/5xx.
  - `app/static/js/linear-plan-context.js:221-224` — `fetchNextSlot()` резолвит тело ответа как валидные данные для ЛЮБОГО `resp.ok` (200-299): `if (!resp || !resp.ok) return null; return resp.json()...`. Для описанного выше ответа `resp.ok === true`, значит `{success:false,...}` доходит до вызывающего как обычный объект, не `null`.
  - `app/static/js/linear-plan-context.js:257,370,455` — все три внутренних потребителя единообразно проверяют `if (!data || data.success === false) { return 'standalone'; }` перед тем как трогать DOM.
  - `app/static/js/lesson-completion.js:160-172` — единственная проверка `if (!data) { _revealCompletion('standalone'); return; }`; `data.success` не читается вообще. При `data = {success:false, day_secured:false, next:null}` код идёт дальше: `data.day_secured` ложно → пропуск редиректа; `next = data.next || {} = {}`; `_renderPlanCtas(undefined, undefined, '/dashboard')`; `_revealCompletion('plan')`.
  - `app/__init__.py:482-484` — при исключении в `build_lesson_context` на GET-рендере страницы урока context processor молча возвращает `{}` (не пробрасывает), поэтому `daily_plan_ctx` в шаблоне падает в falsy-ветку.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-169.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — четыре потребителя `fetchNextSlot` заявлены (в docstring `fetchNextSlot`, linear-plan-context.js:188-195) как единообразно возвращающие `null` на сбой, но реально `success:false` доходит как non-null объект, и только 3 из 4 потребителей это учитывают; сам CLAUDE.md данный инвариант не описывает явно.

#### DP-115 · P2 · `app/templates/components/_daily_plan_progress.html`

- **Кандидат:** `DP-C-170` · линзы-источники: FE-B-09 · скептик: `skeptics/DP-C-170.md`
- **Симптом:** «✨ План выполнен!» рисуется одновременно с «Шаг 0 из 1»: `all_done` приходит независимо от `steps_done/steps_total`
- **Сценарий отказа:** механизм найден и воспроизведён прямым запуском продакшн-кода: `all_done` (истина по `_is_done`, которая учитывает `skipped`) и `steps_done`/`steps_total` (истина по `plan_completion`, которая `skipped` игнорирует) — два независимых подсчёта над одним и тем же списком required-items, синхронизированных только для `completed`, но не для `skipped`.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/templates/components/_daily_plan_progress.html:159-163` — при `data.all_done` текст строится из сырых `done`/`total`, а не из фиксированной пары «всё сделано»: ```js if (data.all_done) { textEl.textContent = 'Шаг ' + done + ' из ' + total; // "Шаг 0 из 1" btnEl.textContent = '✨ План выполнен!'; } ```
  - `app/words/routes.py:1720-1726` — `_is_done` в `_next_step_from_unified` засчитывает пункт завершённым по ЛЮБОМУ из трёх сигналов, включая `skipped`: ```python def _is_done(item: dict) -> bool: item_id = item.get('id', '') return ( plan_completion.get(item_id, False) or bool(item.get('completed', False)) or bool(item.get('skipped', False)) ) ``` — и именно эта функция определяет `next_item is None` → `all_done=True` (строка ~1746).
  - `app/achievements/streak_service.py:178-186` (`_compute_unified_item_completion`, тело функции для required-item) считает пункт «done» **только** по `item.get('completed')` или summary-сигналу для `error_review` — `skipped` там не проверяется вообще. Значит `plan_completion[item_id]` остаётся `False`, и `steps_done` (сумма истинных значений `plan_completion`) НЕ увеличивается для пропущенного пункта.
  - _(ещё 4 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-170.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — в CLAUDE.md задокументирован сам механизм слот-скипа (`Slot-skip helpers`, `DAILY_SLOT_SKIP_QUOTA=1`), но нет упоминания, что `skipped` должен (или не должен) отражаться в `plan_completion`/`steps_done`; расхождение — между двумя функциями внутри кода (`_compute_unified_item_completion` vs `_next_step_from_unified._is_done`), а не между кодом и документом.


### P3 — детали

#### DP-116 · P3 · `app/static/js/linear-daily-plan.js`

- **Кандидат:** `DP-C-165` · линзы-источники: FE-A-03, FE-B-03, FE-B-04, FE-B-05, FE-B-06, FE-B-07 · скептик: `skeptics/DP-C-165.md`
- **Симптом:** мёртвый фронт-код: обработчики на data-атрибуты, которых не производит ни один шаблон, шаблон-сирота `_day_secured_banner.html`, мёртвые inline-guard'ы
- **Сценарий отказа:** но частично, не весь файл. Из 418 строк живой (реально подключаемый и достижимый) функционал — только модалка выбора книги (открытие/закрытие, ~строки 20-268 частично). Остальное подтверждённо мертво тремя независимыми механизмами: (1) `data-slot-state="locked"` guard — атрибут не производится нигде в репозитории вообще; (2) chain-growth toast (`_initChainGrowthDetector` и вся инфраструктура `data-linear-slots`/`data-linear-chain-length`) — атрибуты не производятся нигде; (3) day-secured banner init/dismiss и skip-slot-button guard — атрибуты производятся только орфан-шаблоном `_day_secured_banner.html` (и его недостижимой цепочкой `_path*.html`), который не включён ни одним живым route/шаблоном и опирается на `build_dashboard_path`, которую не вызывает ни один view. Сценарий: пользователь никогда не увидит день-secured баннер этого формата и никогда не получит `data-slot-state="locked"` узел — код исполняется вхолостую (querySelector возвращает null, обработчики no-op), наблюдаемого пользовательского эффекта нет — отсюда P3, а не выше.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/static/js/linear-daily-plan.js:1-10` — скрипт подключён один раз, в `app/templates/words/dashboard_unified.html:162`.
  - `app/templates/partials/unified_daily_plan.html` — единственный живой daily-plan партиал (реально `{% include %}`'ится из `dashboard_unified.html:60`) использует СВОИ атрибуты: `data-plan-item`, `data-item-kind`, `data-state`, `data-locked`, `data-skip-kind`, `data-open-book-select` — и свою собственную inline-логику скипа (строки 734-826 того же файла). Ни `data-slot-state`, ни `data-skip-slot-button`, ни `data-linear-slots`, ни `data-linear-day-secured-banner` в этом файле не встречаются.
  - `grep -rn "data-slot-state" app/templates` — **0 совпадений в шаблонах**. Атрибут, который слушает `_findLockedSlot` (`linear-daily-plan.js:199-202`), не производится ни одним файлом в репозитории вообще (не только «живым» — вообще никаким).
  - `grep -rn "data-linear-slots\|data-linear-chain-length" app/templates` — **0 совпадений**. Весь блок `_initChainGrowthDetector`/`_getChainStorageKey` (`linear-daily-plan.js:345-417`, ~70 строк) не имеет продюсера атрибутов вообще.
  - _(ещё 6 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-165.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md фиксирует только удаление `daily-plan-next.js` (`UI-031`) как прецедент похожей чистки; про `_day_secured_banner.html`/path-подсистему в CLAUDE.md ничего нет, расхождения с документом как такового нет — просто неучтённый мёртвый груз с прошлой итерации фичи "path UI".

#### DP-117 · P3 · `app/templates/components/_daily_plan_progress.html`

- **Кандидат:** `DP-C-171` · линзы-источники: FE-B-10 · скептик: `skeptics/DP-C-171.md`
- **Симптом:** `r.json()` без проверки `r.ok`: любой не-2xx кончается тем, что бар не появляется
- **Сценарий отказа:** механизм воспроизводим по коду без гипотез о состоянии. Сценарий: `GET /api/daily-plan/next-step` падает с 500 (любое исключение внутри `get_daily_plan_unified`/`get_daily_summary`) → глобальный `handle_500_error` возвращает `200`-совместимый JSON-объект `{'success': False, 'error': 'internal_error', ...}` со статусом 500, но БЕЗ проверки `r.ok` фронт всё равно вызывает `r.json()`, получает объект без `steps_total`, ветка `total === 0` обрывает выполнение — `#daily-plan-bar` остаётся `display:none`, никакого сообщения или логики отката нет (кроме случая non-JSON тела, где есть только `console.error`, не видимый пользователю). Эффект ограничен декоративным виджетом прогресса на кабинетных страницах (`base.html`) — на day_secured, XP, сам «План дня» это не влияет, поэтому severity низкая.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/templates/components/_daily_plan_progress.html:130-134`: ``` fetch('/api/daily-plan/next-step', { credentials: 'same-origin', headers: headers }) .then(function(r) { return r.json(); }) .then(function(data) { ... }) ``` Нет проверки `r.ok`/`r.status` перед `r.json()`.
  - `app/templates/components/_daily_plan_progress.html:138-140`: ``` var total = data.steps_total || 0; var done = data.steps_done || 0; if (total === 0) return; ``` Любой JSON-ответ без ожидаемых полей молча трактуется как «шагов нет» — бар просто не показывается (`bar.style.display` не выставляется).
  - `app/__init__.py:350-364` (`handle_500_error`) и `:339-348` (`handle_404_error`) — для путей `/api/*` (`_wants_json()` истинно, т.к. `request.path.startswith('/api/')`, `app/__init__.py:318-323`) отдают валидный JSON вида `{'success': False, 'error': 'internal_error', ...}` без полей `steps_total`/`steps_done`. Такой JSON успешно парсится `r.json()`, исключения не будет, `.catch` не сработает — сообщение об ошибке нигде не показывается пользователю.
  - `app/templates/components/_daily_plan_progress.html:177-179` — `.catch` пишет только `console.error('Daily plan bar error:', err)`, никакого UI-фидбека; сработает лишь для не-JSON тела ответа (напр. HTML от gateway 502/504), но и там пользователь ничего не видит.
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-118 · P3 · `app/templates/components/_daily_plan_progress.html`

- **Кандидат:** `DP-C-172` · линзы-источники: FE-B-12 · скептик: `skeptics/DP-C-172.md`
- **Симптом:** мёртвая JWT-ветка: `localStorage.getItem('jwt_token')` — единственное упоминание во всём `app/`
- **Сценарий отказа:** код мёртв в двойном смысле: (1) ни один продюсер в `app/` не кладёт `jwt_token` в `localStorage`, ветка `if (jwtToken)` не выполняется никогда на практике; (2) даже гипотетически заполненный заголовок `Authorization: Bearer …` был бы проигнорирован самим эндпойнтом `/api/daily-plan/next-step`, у которого auth — `@login_required` (сессия), а не `api_auth_required` (JWT+сессия). Это чистый мёртвый код без наблюдаемого эффекта — понижаю до P3 (косметика/мёртвый код), не P1/P2, так как никакого функционального ущерба: `fetch` работает через `credentials: 'same-origin'` и обычную сессионную куку в любом случае.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/templates/components/_daily_plan_progress.html:125-128` — ```js var jwtToken = localStorage.getItem('jwt_token'); if (jwtToken) { headers['Authorization'] = 'Bearer ' + jwtToken; } ``` Ни один JS/HTML файл в проекте не делает `localStorage.setItem('jwt_token', ...)` — ветка `if (jwtToken)` никогда не истинна на практике.
  - `app/words/routes.py:1678-1680` — ```python @words.route('/api/daily-plan/next-step') @login_required def daily_plan_next_step() -> tuple: ``` Эндпоинт, который дергает этот `fetch`, защищён `flask_login.login_required` (сессионные куки), а НЕ `app.api.decorators.api_auth_required` (строки 17-47 там же), который единственный умеет читать `Authorization: Bearer`. Значит даже если бы токен где-то появился в `localStorage`, backend этого конкретного вызова его бы просто проигнорировал (`login_required` не читает заголовок `Authorization`).
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)


### Опровергнуто скептиками — не переоткрывать без новых фактов

| Кандидат | Якорь | Утверждение финдера | Почему опровергнуто |
|---|---|---|---|
| `DP-C-164` | `app/templates/components/_daily_plan_progress.html` | единственный живой консьюмер next-step гейтится `?from=daily_plan`, а план выдаёт `from=linear_plan` | предпосылка кандидата («все URL плана несут `from=linear_plan`») неверна: как минимум один активный (не мёртвый, не флагом отключённый) пункт плана дня — `phrase_review` в `optional`-секции — генерирует URL `?from=daily_plan`, ведущий на страницу, которая расширяет `base.html` и включает именно этот компонент. При клике по этой карточке гейт `request.args.get('from') == 'daily_plan'` проходит, и компонент выполняет… |
| `DP-C-166` | `app/templates/partials/unified_daily_plan.html` | 7 русских литералов вставляются в DOM мимо `window.I18N`; ключ моста `day_done` не читается; порядок подключения скриптов противоречит комментарию | кандидат склеивает три утверждения, ни одно не подтверждается как описано для указанного якоря. (1) Число литералов — 6, не 7 (сам механизм «строки не идут через мост» в этом шаблоне реален, но это не отклонение от местного паттерна: файл нигде не подключён к `window.I18N`, так что «мимо» ключевого моста тут в принципе нечему было бы противоречить — как и `flashcard-session.js`, это самостоятельный неконвертированны… |
| `DP-C-167` | `app/static/js/linear-daily-plan.js` | провал POST `/api/daily-plan/events` при скипе слота полностью молчалив: серверное сообщение об исчерпанной квоте не показывается | механизм показа ошибки существует и корректно связывает серверное сообщение с UI. Ответ 429 не считается `resp.ok`, JSON-тело парсится, `data.message` (ровно тот текст, что вернул `api_error`) используется как текст ошибки, а `.catch` показывает его пользователю через toast и разблокирует кнопку. Ни один из проверенных путей (обычная квота, конкурентная гонка через `IntegrityError`, невалидный slot/reason) не привод… |
| `DP-C-168` | `app/templates/partials/unified_daily_plan.html` | кнопка «Пропустить» отрендерена для `kind='grammar_review'`, который `/events` отвергает 400 — мертва навсегда и молча | кнопка «Пропустить» технически не может отрендериться для `kind='grammar_review'`, потому что (1) grammar_review-item строится ТОЛЬКО для optional-секции (`plan.py:313-314`), никогда для required; (2) весь skip-механизм (аннотация квоты + кнопка в шаблоне) существует только в required-цикле шаблона; optional-цикл кнопки «Пропустить» не рендерит вообще ни для одного kind. Расхождение `_SKIP_SLOT_KINDS` (API действите… |

---

## Подзона: Liveness / мёртвый код (Task 6)

Метод — **три независимых среза**, а не один grep: (1) AST-достижимость из живых корней
(`app.url_map`, CLI, планировщик) плюс строковые `patch("app.daily_plan…")`-цели; (2) живой прогон
приложения с трассировкой импортов и исполнения (4 пользователя, дашборд + API зоны);
(3) grep по имени символа как контроль. Вердикт «мёртв» выносится только при согласии всех трёх.
Полный разбор с поимённым списком вызывателей — `.ralphex/audit-notes/daily-plan/liveness.md`.

| Модуль | Строк | Достижим из живых корней | Импортирован в живом прогоне | Исполнился | Вердикт |
|---|---:|---|---|---|---|
| `app/daily_plan/assembler.py` | 831 | **нет** | **нет** | нет | **мёртв целиком** |
| `app/daily_plan/linear/chain.py` | 530 | **нет** | **нет** | нет | **мёртв целиком** |
| `app/daily_plan/repair_pressure.py` | 144 | **нет** | **нет** | нет | **мёртв целиком** |
| `app/daily_plan/linear/plan.py` | 407 | частично (4 символа из 14) | да (лениво) | да | **жив на 35 %** |
| `app/daily_plan/milestones.py` | 271 | частично (4 из 7) | нет¹ | нет¹ | **жив на 51 %** |
| `app/daily_plan/tier.py` | 154 | да (3/3) | да | да | жив |
| `app/daily_plan/challenge.py` | 418 | да (6/6) | да | да | жив |
| `app/daily_plan/route_progress.py` | 211 | да (6/6) | да | да | жив |

¹ `milestones.py` не подтянулся набором запросов среза 2, потому что оба его живых входа —
**событийные** (закрытие дня, завершение главы). Это не признак смерти — ровно тот случай, ради
которого срез 2 не используется в одиночку. То же — `items/skills.py` (нужен активный челлендж
категории `listening_deep`). Оба **не** записаны в мёртвые.

**Объём мёртвого кода** (AST-спаны, не «на глаз»):

| Корзина | Строк |
|---|---:|
| Модули зоны, мёртвые целиком — 8 файлов (`assembler.py` 831 · `chain.py` 530 · `curriculum_slot.py` 476 · `writing_slot.py` 156 · `listening_slot.py` 153 · `repair_pressure.py` 144 · `speaking_slot.py` 127 · `error_review_slot.py` 75) | **2 492** |
| Мёртвые символы внутри живых модулей зоны (`linear/plan.py` 267 = 65 % файла · `milestones.py` 132 = 48 % · `lesson_context.py` 37 = 11 %) | **436** |
| **Итого внутри зоны** | **2 928 из 11 347 = 25.8 %** |
| «Потребительская тень» вне зоны — ветки, недостижимые из-за мёртвого производителя | **445** |
| **ВСЕГО** | **3 373** |

Порядок будущей чистки (сама чистка в аудит **не входит** и требует подтверждения владельца):
(1) один связный кластер 1 784 строки — `get_linear_plan` + 9 хелперов → `chain.py` → 5 slot-модулей,
ни одного живого входа; (2) `assembler.py` + `repair_pressure.py` — 975 строк; (3) потребительская
тень 445 строк — только после (1) и (2). `DP-120` из списка чистки **исключена**: это не удаление,
а починка (восстановить вызов `check_curriculum_milestones` на живом пути завершения урока).

### Индекс

| ID | Sev | Файл:строка | Симптом | Вериф. | Расхождение |
|---|---|---|---|---|---|
| DP-119 | P3 | `app/daily_plan/assembler.py:1-831` | `assembler.py` (831 строка) удерживается только тестами — прод-вызывателей нет | CONFIRMED | код |
| DP-120 | P3 | `app/daily_plan/milestones.py` | milestone-уведомления о завершении модуля и уровня не выдаются никогда | CONFIRMED | — |
| DP-121 | P3 | `app/daily_plan/linear/slots/` | пять slot-модулей (987 строк) мертвы вместе с `chain.py`; `reading_slot.py` при этом жив — не удалять пакетом | CONFIRMED | — |
| DP-122 | P3 | `app/daily_plan/repair_pressure.py` | модуль мёртв целиком | CONFIRMED | — |
| DP-123 | P3 | `app/daily_plan/linear/chain.py` | «потребительская тень»: 445 строк вне зоны недостижимы из-за мёртвого производителя | CONFIRMED | код |
| DP-124 | P3 | `app/daily_plan/linear/lesson_context.py` | `build_lesson_context_from_plan` — мёртвый двойник живой функции, застрявший на удалённом контракте | CONFIRMED | код |

### P0 — детали

_(находок этого уровня в подзоне нет)_


### P1 — детали

_(находок этого уровня в подзоне нет)_


### P2 — детали

_(находок этого уровня в подзоне нет)_


### P3 — детали

#### DP-119 · P3 · `app/daily_plan/assembler.py:1-831`

- **Кандидат:** `DP-C-173` · линзы-источники: LIVE-01 · скептик: `skeptics/DP-C-173.md`
- **Симптом:** `assembler.py` (831 строка) удерживается только тестами — прод-вызывателей нет
- **Сценарий отказа:** механизм полностью подтверждён по коду: `assembler.py` не импортируется ни одним продакшн-модулем, актуальный unified-оркестратор (`app/daily_plan/plan.py`) построен на независимом наборе item-builders из `app/daily_plan/items/*` и не знает о существовании mission/phase-системы. Тесты держат только отдельные приватные хелперы файла, а не его публичный API — то есть даже тестовое «удержание» частичное. Файл — хвост удалённой mission/phase-цепочки (см. `CLAUDE.md`: «Mission/linear-chain удалены», «мёртвый mission/phase-код удалён (E-008/E-013/E-062/E-063, ~1000 строк)»), который при той чистке не был дорезан. Severity — P3 (мёртвый код без наблюдаемого эффекта на продакшн-поведение; риск — исключительно когнитивная нагрузка на будущих читателей и ложное ощущение живой функциональности).
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/plan.py:1-32` — docstring и импорты продакшн-оркестратора не содержат `assembler`; реальные item-builders берутся из `app/daily_plan/items/*.py`.
  - `app/daily_plan/__init__.py:1-9` — реэкспорт идёт из `app.daily_plan.models`, не из `app.daily_plan.assembler`.
  - Полнорепозиторный grep `from app.daily_plan.assembler import` по `app/` — 0 совпадений (только тестовые файлы импортируют приватные хелперы напрямую).
  - `app/daily_plan/assembler.py:383,572,733` — три публичные функции модуля (`assemble_progress_mission`, `assemble_repair_mission`, `assemble_listening_mission`) не имеют ни одного вызова вне самого файла (внутренний self-call `assemble_repair_mission → assemble_progress_mission` на строке 591 не считается).
- **Где расхождение:** код — `CLAUDE.md` уже декларирует, что mission/phase-код удалён; `assembler.py` — недорезанный остаток, расхождение между формулировкой CLAUDE.md («удалён») и фактическим состоянием репозитория (файл физически присутствует, 831 строка).

#### DP-120 · P3 · `app/daily_plan/milestones.py`

- **Кандидат:** `DP-C-175` · линзы-источники: LIVE-03 · скептик: `skeptics/DP-C-175.md`
- **Симптом:** milestone-уведомления о завершении модуля и уровня не выдаются никогда
- **Сценарий отказа:** механизм найден и воспроизводим по коду: `emit_module_completed`/`emit_level_completed` достижимы только через `check_curriculum_milestones`, которая достижима только через `complete_lesson()` в `app/curriculum/service.py`, а эта функция не вызывается ни одним живым HTTP-роутом, Telegram-хендлером или CLI/скриптом — только юнит-тестами напрямую. Реальное завершение уроков во всех live-роутах (`lessons.py`, `card_lessons.py`, `grammar_quiz_lessons.py`, `vocabulary_lessons.py`) идёт через `ProgressService`/грейдеры, которые про `milestones.py` не знают. Сценарий: пользователь проходит последний урок модуля/уровня через реальный UI → прогресс пишется через `ProgressService` → `check_curriculum_milestones` не вызывается → уведомления «Модуль пройден»/«Уровень N пройден» не создаются никогда, при этом XP/streak/day_secured не затронуты (эмиттеры — orthogonal side-channel, `try/except`-изолированы). Severity — P3, а не выше: по докстрингу самого модуля это «nice-to-have» toast, не влияющий на XP/streak/rank/day_secured/доступ к контенту; отсутствие эффекта никак не отражается на основном цикле обучения, только на отсутствующей плюшке, о которой пользователь и не узнает, что её не хватает.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/milestones.py:172-247` — `check_curriculum_milestones(user_id, lesson_id, db)` — единственная функция, которая вызывает `emit_module_completed` (строка 209) и `emit_level_completed` (строка 244).
  - `app/curriculum/service.py:274-280`: ``` # Module / level milestone emission (off-band notifications). try: from app.daily_plan.milestones import check_curriculum_milestones check_curriculum_milestones(user_id, lesson_id, db) ``` — единственное место в продакшн-коде, откуда `check_curriculum_milestones` вообще достижима.
  - `app/curriculum/service.py:177` — `def complete_lesson(user_id, lesson_id, score=100.0)`, тело которой содержит вышеуказанный вызов.
  - `grep -rn "complete_lesson(" app/ scripts/` (исключая `def complete_lesson`) — 0 совпадений: ни один live-роут, Telegram-хендлер, admin-скрипт или CLI-команда не вызывает эту функцию. Единственные вызовы — из `tests/test_curriculum_service.py`, `tests/curriculum/test_service.py`, `tests/curriculum/test_xp.py`, `tests/test_specific_exception_handlers.py`.
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-121 · P3 · `app/daily_plan/linear/slots/`

- **Кандидат:** `DP-C-176` · линзы-источники: LIVE-04, ITEMS-C-12 · скептик: `skeptics/DP-C-176.md`
- **Симптом:** пять slot-модулей (987 строк) мертвы вместе с `chain.py`; `reading_slot.py` при этом жив — не удалять пакетом
- **Сценарий отказа:** `curriculum_slot.py`, `error_review_slot.py`, `listening_slot.py`, `speaking_slot.py`, `writing_slot.py` (987 строк суммарно) достижимы только через `chain.py:build_chain`, который в свою очередь достижим только через `get_linear_plan` (`app/daily_plan/linear/plan.py:299`) — а у `get_linear_plan` нет ни одного вызова из production-кода (только тесты). Реальный unified-оркестратор (`app/daily_plan/plan.py:get_daily_plan`, вызываемый `get_daily_plan_unified`) берёт из `linear/plan.py` только не относящиеся к chain хелперы. Таким образом весь путь `get_linear_plan → build_chain → {5 модулей}` — orphaned dead code, согласуется с CLAUDE.md («Mission/linear-chain удалены», хотя файлы физически не удалены). `reading_slot.py` действительно жив независимо от `chain.py` (books API, xp.py) — пакетом удалять действительно нельзя. **Уточнение к кандидату (не опровержение):** формулировка не упоминает, что `srs_slot.py` тоже жив независимо от `chain.py` — он напрямую импортируется `app/daily_plan/plan_builder.py:212` и `app/daily_plan/items/srs.py:47,153` (deck-quiz логика unified SRS item builder). Значит живых модулей в пакете не один (`reading_slot`), а два (`reading_slot` + `srs_slot`) — при буквальном исполнении рекомендации «удалить всё кроме reading_slot.py» удаление srs_slot.py сломало бы unified SRS required-slot. Числовой и содержательный костяк кандидата (5 модулей + chain.py мертвы, 987 строк, package-удаление недопустимо) при этом остаётся верным.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/chain.py:22-35` — импортирует все 7 slot-модулей (`curriculum_slot`, `error_review_slot`, `listening_slot`, `reading_slot`, `speaking_slot`, `srs_slot`, `writing_slot`) внутрь `build_chain`.
  - `app/daily_plan/linear/plan.py:107,337,340` — единственные вызовы `build_chain`/`_build_baseline` (из `chain.py`), оба внутри `get_linear_plan`/`build_tomorrow_preview`.
  - `get_linear_plan` (`app/daily_plan/linear/plan.py:299`) не имеет ни одного вызова в `app/` — `grep -rln "get_linear_plan" app/` даёт только сам `plan.py` (определение) и `xp.py` (упоминание в docstring).
  - `app/daily_plan/linear/xp.py:512-516` — docstring `maybe_award_linear_perfect_day` прямо подтверждает миграцию: «Раньше здесь собирался legacy linear-план (`get_linear_plan`) … Бонус считается по … `get_daily_plan_unified`» — то есть последний живой консьюмер уже отключён.
  - `app/daily_plan/plan.py:353` (реальный unified-оркестратор, вызываемый из `get_daily_plan_unified`) импортирует из `linear/plan.py` только `_get_user_focus`, `_level_progress_to_dict`, `_position_from_lesson`, `get_plan_intensity` — мелкие хелперы, не `get_linear_plan`/`build_chain`.
  - `wc -l`: `curriculum_slot.py`=476, `error_review_slot.py`=75, `listening_slot.py`=153, `speaking_slot.py`=127, `writing_slot.py`=156 → сумма ровно **987** строк, совпадает с формулировкой кандидата.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-176.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-122 · P3 · `app/daily_plan/repair_pressure.py`

- **Кандидат:** `DP-C-177` · линзы-источники: LIVE-05 · скептик: `skeptics/DP-C-177.md`
- **Симптом:** модуль мёртв целиком
- **Сценарий отказа:** прод-вызывателей у `calculate_repair_pressure`/`RepairBreakdown` нет ни прямых, ни транзитивных: единственный импортёр (`assembler.py`) сам не имеет ни одного production-импортёра (только докстринг-упоминание в `counting.py` и точечные импорты в тестах несвязанных приватных хелперов того же файла). Сценарий: любое изменение или удаление `repair_pressure.py` не затронет ни один пользовательский сценарий — код физически недостижим из `create_app()`/blueprint-роутов. Severity понижаю до P3 (мёртвый код, не P2) — это в точности категория «дыра в тестовом покрытии / мёртвый код» из брифинга, эффекта на рантайм нет.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/repair_pressure.py:1-141` — весь файл: функция `calculate_repair_pressure` и датакласс `RepairBreakdown`, никаких side-effects при импорте (только вычисления по БД, вызываются из тела функции).
  - `app/daily_plan/assembler.py:15` — `from app.daily_plan.repair_pressure import RepairBreakdown` (только импорт типа).
  - `app/daily_plan/assembler.py:573-575` — `def assemble_repair_mission(user_id, repair_breakdown: RepairBreakdown, ...)` — единственное место использования типа; сама функция нигде не вызывается (0 хитов по репо).
  - `app/srs/counting.py:4` — `mission-plan (`app/daily_plan/assembler.py`), linear-plan` — упоминание в докстринге модуля, не импорт кода; `import app.daily_plan.assembler` в `counting.py` отсутствует.
  - CLAUDE.md, раздел Daily Plan: «Mission/phase-chain удалены» — согласуется с находкой: mission-assembler (и всё, что от него зависит, включая repair-pressure) остался в дереве файлов, но production-путь (`app/daily_plan/plan.py` → `get_daily_plan_unified`) его не подключает.
- **Где расхождение:** — (согласуется с CLAUDE.md: «Mission/phase-chain удалены», расхождения нет — просто хвост удаления не дочищен).

#### DP-123 · P3 · `app/daily_plan/linear/chain.py`

- **Кандидат:** `DP-C-178` · линзы-источники: LIVE-06 · скептик: `skeptics/DP-C-178.md`
- **Симптом:** «потребительская тень»: 445 строк вне зоны недостижимы из-за мёртвого производителя
- **Сценарий отказа:** механизм реален и воспроизводим чтением кода: `chain.py` (продюсер) не имеет ни одного живого пути исполнения (`get_linear_plan` — 0 вызовов), а несколько реально исполняемых веток в файлах вне `app/daily_plan/` (`app/telegram/notifications.py`, `app/words/routes.py`, `app/achievements/streak_service.py`), достижимых из живых точек входа (`telegram/scheduler.py` — крон планировщика, `race/routes.py` — роут `/race`), гейтятся на `plan.get('mode') == 'linear'`, которое никогда не наступает. Сценарий: любой запрос к `/race` или срабатывание утреннего telegram-напоминания выполняет `_get_next_plan_action`/`format_morning_reminder`, доходит до `if mode == 'linear'`, условие всегда `False` — 240 строк кода в этих функциях никогда не исполняются ни при каком состоянии БД. Число «445» самостоятельно не воспроизвёл — строгий подсчёт по найденным веткам даёт 240 строк; если приплюсовать полностью осиротевший `path_view.py` (706 строк, тот же контракт, но независимая причина смерти — отсутствие вызова вовсе), сумма уходит далеко за 445 в другую сторону. Эффект (недостижимый код вне зоны плана дня, причинно связанный со смертью `chain.py`) при этом подтверждён твёрдо.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/chain.py:242-259, 292-354, 427-530` — `build_chain` / `extend_chain_after_activity` / `recompute_continuation_available` / `build_next_slot`: единственная точка входа в файл извне — `get_linear_plan` (`app/daily_plan/linear/plan.py:299`, зовёт `build_chain` на строке 337) и `build_tomorrow_preview` (`plan.py:98`, зовёт `_build_baseline`/`_get_plan_difficulty` из `chain.py`).
  - `grep -rn "get_linear_plan(" app tests` → единственное совпадение — сама сигнатура `app/daily_plan/linear/plan.py:299`. Ноль вызовов где-либо ещё, включая тесты.
  - `app/daily_plan/plan.py:353-357` (реальный `get_daily_plan`, вызываемый из `app/daily_plan/service.py:191`) импортирует из `linear/plan.py` только `_get_user_focus`, `_level_progress_to_dict`, `_position_from_lesson`, `get_plan_intensity` — не `get_linear_plan`.
  - `app/daily_plan/service.py:182-214` — `get_daily_plan_unified` возвращает только `mode: 'paused'` (пауза) или `mode: 'unified'` (делегат `get_daily_plan`). `mode: 'linear'` нигде не производится ни одним живым путём.
  - _(ещё 5 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-178.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md фиксирует, что «Mission/linear-chain удалены» на уровне оркестратора (`app/daily_plan/plan.py`), но не упоминает, что `linear/chain.py` и веера `mode == 'linear'` в `words/routes.py`/`streak_service.py`/ `telegram/notifications.py` остались недочищенными хвостами этого удаления.

#### DP-124 · P3 · `app/daily_plan/linear/lesson_context.py`

- **Кандидат:** `DP-C-179` · линзы-источники: LIVE-07 · скептик: `skeptics/DP-C-179.md`
- **Симптом:** `build_lesson_context_from_plan` — мёртвый двойник живой функции, застрявший на удалённом контракте
- **Сценарий отказа:** механизм в коде есть буквально: функция экспортирована, её докстринг утверждает пользу «в местах, где caller уже получил `get_daily_plan(...)`», но реальный `get_daily_plan` этого контракта не производит (`required`/`optional`, не `slots`/`baseline_slots`) — если бы кто-то в проде попытался использовать функцию так, как описывает докстринг, `plan.get('slots')`/`plan.get('baseline_slots')` всегда были бы `[]`, и `is_daily_plan=True` возвращался бы с `next_slot_url=None`, `day_secured=True` (так как `incomplete=[]` → `True` в `_compute_day_secured`) независимо от реального состояния плана. Сценарий (гипотетический, воспроизводимый по коду): вызов `build_lesson_context_from_plan(get_daily_plan(uid, db), slot_param='curriculum', current_lesson_id=101, dashboard_url=...)` → `day_secured=True`, хотя required-слоты не пройдены. На практике эффект не наблюдаем пользователем — ни один прод-путь функцию не вызывает (единственный consumer — собственные unit-тесты с фиктивным dict старой формы), поэтому это мёртвый код с расхождением контракта, а не активный баг.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/lesson_context.py:314-317` — `build_lesson_context_from_plan` читает `plan.get('slots')` и `plan.get('baseline_slots')`.
  - `app/daily_plan/linear/lesson_context.py:243-260` (живая `build_lesson_context`) читает `plan.get('required')`/`plan.get('optional')` из `get_daily_plan` (unified) — другой контракт, других ключей нет.
  - `app/daily_plan/plan.py:461-462` — `get_daily_plan` реально отдаёт `{'required': required_dicts, 'optional': optional_dicts, ...}`, ключей `slots`/`baseline_slots` в payload нет.
  - `git show 26a6c620 -- app/daily_plan/linear/lesson_context.py`: коммит явно мигрирует ТОЛЬКО `build_lesson_context` с legacy `get_linear_plan` (ключи `slots`/`baseline_slots`) на unified `get_daily_plan` (ключи `required`/`optional`), сообщение коммита — «build_lesson_context переключили на unified get_daily_plan вместо устаревшего get_linear_plan; читает required/optional вместо slots/baseline_slots». `build_lesson_context_from_plan` в этом коммите не тронута и осталась на старом контракте.
  - Все 6 продакшн-вызовов (`app/__init__.py:459`, `app/study/game_routes.py:208`, `app/curriculum/routes/lessons.py:443/681/1942`, `app/curriculum/routes/card_lessons.py:909`, `app/books/api.py:1400`, `app/api/daily_plan.py:621`) импортируют и зовут исключительно `build_lesson_context`. Ни один — `build_lesson_context_from_plan`.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-179.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — `build_lesson_context_from_plan` расходится с описанным в CLAUDE.md контрактом `payload-ключи required/optional` (секция Daily Plan / Optional accumulation), но CLAUDE.md эту функцию не упоминает вовсе; расхождение внутреннее между двумя функциями одного файла, не документ vs код.


### Опровергнуто скептиками — не переоткрывать без новых фактов

| Кандидат | Якорь | Утверждение финдера | Почему опровергнуто |
|---|---|---|---|
| `DP-C-174` | `tests/telegram/test_plan_status.py:150` | тест патчит путь, которого в проде нет (`chain.extend_chain_after_activity`) | заявленный механизм («путь, которого в проде нет») отсутствует: `extend_chain_after_activity` определена в `app/daily_plan/linear/chain.py:292` и успешно резолвится по указанному тестом dotted-path. Кандидат путает это, возможно, с другим наблюдением (например, что `_handle_plan` для `mode='linear'` в `app/telegram/bot.py` не вызывает `format_linear_plan_text`/эти функции напрямую и падает в legacy-fallback ветку, и… |

---

## Подзона: Дыры в покрытии (Task 7)

Прогоны: **A** — `pytest tests/daily_plan --cov=app/daily_plan --cov=app/api` («что покрывает сам
каталог зоны», **47 %**); **B** — A плюс 21 тест-файл зоны вне каталога («что покрыто вообще»,
**55 %**); **C** — добивка эндпоинтов, которых нет в A/B. Отчёт — `docs/audit/2026-08-26-coverage-daily-plan.txt`.
Ловушка для будущих прогонов (не находка): `--cov=app/api/daily_plan.py` молча даёт
`module-not-imported` и 0 строк, точечная форма `--cov=app.api.daily_plan` роняет прогон двойным
импортом SQLAlchemy; рабочая форма — каталог `--cov=app/api`.

**Красные против baseline.** Baseline Task 1 — `2 failed, 402 passed`. Прогон Task 7 —
`3 failed, 401 passed`, на одну красную больше. Аудит кода не трогал; разница объясняется формой
локальной тестовой БД: `test_events.py::test_all_valid_reasons_accepted` краснеет там, где схема
построена миграциями (партиальный индекс `uq_daily_plan_events_slot_skipped` на месте) и зеленеет
там, где схема построена `db.create_all()` из модели, в которой индекс не объявлен. Кандидат
«индекс объявлен только в миграции» **опровергнут** (`DP-C-041`): в проде схему ставит Alembic,
пробел ограничен `TESTING`-конфигурацией по явному дизайну. Практическое следствие для Task 10:
ожидание «ровно 2 red» верно только для create_all-схемы — сверять надо не число, а список имён.

**Эндпоинты без исполнения тела — 6 из 16** (находка `DP-126`). `GET /api/streak` (0 строк тела; в
тестах только неаутентифицированный вызов, 401 срабатывает до тела), `GET /api/error-review/summary`
(0; URL не встречается в `tests/` вовсе), `POST /api/daily-plan/phrase-review/complete` (0; URL не
встречается), `POST /api/streak/repair` (0; тест, который выглядит как его покрытие, бьёт **другой**
роут — `words`-blueprint `/api/streak/repair-web`), `POST /api/daily-plan/error-review/complete`
(6 строк из ~79 — только ранняя 400-ветка), `POST /api/daily-plan/challenge/complete` (5 из ~81).

**Покрытие инвариантов INV-01…INV-47.** Метод — не «есть ли тест с похожим именем», а «краснеет ли
хоть один тест при названной мутации кода, держащего инвариант»:

| Вердикт финдера | Кол-во | Инварианты |
|---|---:|---|
| есть страж | 16 | INV-01, 02, 06, 07, 08, 11, 19, 22, 26, 28, 31, 39, 43, 44, 46, 47 |
| есть страж, но частичный | 2 | INV-05 (только unified-ветка), INV-20 (только без placement-floor) |
| **слабый** (тест есть, названная мутация проходит зелёной) | 18 | INV-03, 04, 12, 14, 17, 18, 24, 25, 27, 30, 34, 35, 36, 37, 38, 40, 42, 45 |
| «нет стража» | 10 | INV-09, 10, 13, 15, 16, 21, 23, 29, 32, 41 |
| факт подтверждён, страж частичный | 1 | INV-33 |

Последняя строка **скептиком опровергнута как находка** (`DP-C-184`): минимум 5 из десяти
перечисленных инвариантов имеют специально написанные зелёные тесты, то есть формулировка «ни
одного краснеющего теста» неверна в предъявленном виде. Таблица оставлена как **измерение
финдера**, а не как подтверждённая находка: пересчитывать её по каждому инварианту заново аудит
не стал — это записано в «сознательные пропуски».

**Тесты-пустышки — предъявленный список не подтвердился.** Просканировано 400 тест-функций каталога
через AST: без ассертов вообще — **0**; патч несуществующего пути — **0** (все 51 уникальная
`patch`-цель резолвится, гипотеза плана не подтвердилась). Два кандидата, которые финдер считал
пустышками, скептик снял: три теста recovery-suggestion всё же проверяют нетривиальный контракт
роута (`DP-C-183`), а патч `chain.extend_chain_after_activity` резолвится по указанному пути
(`DP-C-174`) — «мёртвость» пути к самому патчу отношения не имеет. В реестр из этой линзы прошли
только три находки: `DP-125` (два baseline-красных теста красны из-за календарной полуночи в
сидировании, а не из-за прода), `DP-126` (эндпоинты без исполнения тела) и `DP-127` (удалены 18
файлов тестов `linear/` при сохранённых прод-модулях).

**Граничные состояния из линзы A (Task 2):** graduated — покрыт; paused — покрыт, но не покрыта
**граница** `plan_paused_until == today` (код сравнивает `>`, тесты бьют `+3` и `−1` день);
заблокированный спайн — частично (не покрыты `optional` заблокированного и `required == []` при
блоке); новый юзер — покрыт; юзер без `onboarding_level` — частично; **пустой `required` у graduated
end-to-end — не покрыт нигде**; **fallback-ветка сборки — не покрыта** (ассертится только
`fallback_reason`).

### Индекс

| ID | Sev | Файл:строка | Симптом | Вериф. | Расхождение |
|---|---|---|---|---|---|
| DP-125 | P3 | `tests/daily_plan/test_srs_slot_completion.py:142,170` | два baseline-красных теста сеют карточки по календарной полуночи, а счётчик считает от 02:00 — красное здесь тест, не прод | CONFIRMED | код |
| DP-126 | P3 | `app/api/daily_plan.py:535,904,1017,1187` | 4 эндпоинта зоны не исполняют ни одной строки тела ни в одном тесте, ещё 2 — только раннюю 400-ветку | CONFIRMED | — |
| DP-127 | P3 | `tests/daily_plan/linear/` (удалён в `d197e94a`)` | удалены 18 файлов тестов при сохранённых 12 прод-модулях: 7 модулей не исполняют ни строки тела | CONFIRMED | код |

### P0 — детали

_(находок этого уровня в подзоне нет)_


### P1 — детали

_(находок этого уровня в подзоне нет)_


### P2 — детали

_(находок этого уровня в подзоне нет)_


### P3 — детали

#### DP-125 · P3 · `tests/daily_plan/test_srs_slot_completion.py:142,170`

- **Кандидат:** `DP-C-180` · линзы-источники: DP-COV-02 · скептик: `skeptics/DP-C-180.md`
- **Симптом:** два baseline-красных теста сеют карточки по календарной полуночи, а счётчик считает от 02:00 — красное здесь тест, не прод
- **Сценарий отказа:** механизм найден и воспроизведён напрямую (живой прогон + расчёт границ). Тест засеивает `last_reviewed`/`first_reviewed` от календарной полуночи, а продовый счётчик (`count_reviews_today`/`count_new_cards_today` через `day_to_naive_utc`) считает «сегодня» от 02:00 локального времени пользователя (в тестовом окружении — 02:00 UTC). В итоге сценарий теста (карточка «отревьюена сегодня», пул пуст → должен сработать corrective fallback) не воспроизводится: карточка систематически проваливается в «вчера» по продовой границе суток, `activity <= 0`, `is_srs_slot_completed_today` возвращает `False` вместо ожидаемого `True`. Сама продовая логика 02:00-границы — задокументированное и осознанное поведение (см. `CLAUDE.md` / `time_utils.py`), расхождения между продовыми модулями не обнаружено — красный именно тест, а не прод.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `tests/daily_plan/test_srs_slot_completion.py:142` — `today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)` (аналогично L170 во втором тесте).
  - `tests/daily_plan/test_srs_slot_completion.py:148-150` — карточка сеется с `last_reviewed=today_midnight`, `first_reviewed=today_midnight - timedelta(days=2)`.
  - `app/srs/counting.py:279-284` (внутри `count_reviews_today`) — фильтр требует `UserCardDirection.last_reviewed >= today_start` и `first_reviewed < today_start`, где `today_start = _today_start_naive(...)` (L271) → `day_to_naive_utc(...)` — граница суток в 02:00 по локальному часовому поясу пользователя.
  - `app/utils/time_utils.py:26` — `LEARNING_DAY_START_HOUR = 2`; `app/utils/time_utils.py:118-145` — `day_to_naive_utc` строит `target_local_start` на `time(hour=LEARNING_DAY_START_HOUR)`, то есть 02:00, а не 00:00.
  - `tests/conftest.py:58-62,89-91` — тестовая среда фиксирует `User.timezone` в `'UTC'`, так что граница суток для тестового юзера — ровно `02:00 UTC`, и календарная полночь (00:00 UTC) систематически (примерно 22 часа в сутки, кроме окна 00:00–02:00 UTC) оказывается «вчера» с точки зрения счётчика.
  - _(ещё 1 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-180.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код (тест) — `tests/daily_plan/test_srs_slot_completion.py` не использует `tests/support_dates.py::study_today`-совместимый якорь для `today_midnight` (сам файл уже импортирует `study_today` для `_seed_xp_event`, L22,84, но не переиспользует его — или эквивалентный `day_to_naive_utc` — при построении `today_midnight` для карточек).

#### DP-126 · P3 · `app/api/daily_plan.py:535,904,1017,1187`

- **Кандидат:** `DP-C-181` · линзы-источники: DP-COV-03 · скептик: `skeptics/DP-C-181.md`
- **Симптом:** 4 эндпоинта зоны не исполняют ни одной строки тела ни в одном тесте, ещё 2 — только раннюю 400-ветку
- **Сценарий отказа:** по прямому чтению кода и exhaustive grep по `tests/`: 4 эндпоинта (`streak`, `error_review_summary`, `complete_phrase_review`, `streak_repair`) действительно не исполняют ни одной строки тела ни в одном тесте (для `streak` маршрут технически вызывается, но декоратор `api_auth_required` обрывает выполнение до входа в функцию — то есть тело функции не исполняется), и ещё 2 (`complete_error_review`, `challenge_complete`) покрыты только своей самой ранней 400-веткой валидации. Формулировка кандидата (4 нулевых + 2 частичных) подтверждена полностью, включая ненаписанные в якоре два эндпоинта. Оговорка скептика «реальный `pytest --cov` не прогонялся» снята при сборке реестра: прогоны **A/B/C** выполнены инструментально (`--cov=app/api`, отчёт — `docs/audit/2026-08-26-coverage-daily-plan.txt:208-222`), и построчное исполнение тел этих шести view-функций замерено по AST-диапазонам, а не выведено из grep'а. Числа выше — из этого замера.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/api/daily_plan.py:533-535` — `@api_daily_plan.route('/streak')` → `streak()`. Единственное упоминание маршрута в тестах — `tests/api/test_api_error_format.py:365`, параметр `('/api/streak', 'GET')` в `TestUnauthenticatedApiErrors::test_unauthenticated_returns_401`, вызывается неаутентифицированным `client`. `app/api/decorators.py` возвращает 401 до входа в `streak()` — тело функции (`get_streak_status`, `jsonify`) не выполняется ни разу.
  - `app/api/daily_plan.py:902-919` — `error_review_summary()`. Grep по `error-review/summary` во всём `tests/` не дал ни одного совпадения — маршрут не вызывается вообще.
  - `app/api/daily_plan.py:1014-1087` — `complete_phrase_review()`. Grep по `phrase-review/complete` и `daily_phrase_review_items` во всём `tests/` — ноль совпадений.
  - `app/api/daily_plan.py:1184-1205` — `streak_repair()` на `/streak/repair`. Grep по `/api/streak/repair'` — ноль; единственное похожее совпадение `/api/streak/repair-web` (`tests/test_words_routes.py`) — это другой маршрут в `app/words/routes.py:1803`, не относящийся к `daily_plan.py`.
  - _(ещё 2 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-181.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** — (инвариант `CLAUDE.md` не задет)

#### DP-127 · P3 · `tests/daily_plan/linear/` (удалён в `d197e94a`)`

- **Кандидат:** `DP-C-182` · линзы-источники: DP-COV-04 · скептик: `skeptics/DP-C-182.md`
- **Симптом:** удалены 18 файлов тестов при сохранённых 12 прод-модулях: 7 модулей не исполняют ни строки тела
- **Сценарий отказа:** CONFIRMED, но с поправкой числа. Механизм реален и воспроизведён: `d197e94a` убрал legacy `get_linear_plan`/`build_chain`-цепочку из живого пути (заменил её на unified-ассемблер в `app/daily_plan/plan.py`), но не удалил сами файлы `app/daily_plan/linear/chain.py` и 4 slot-модуля (`error_review_slot`, `listening_slot`, `speaking_slot`, `writing_slot`), и одновременно вычистил все тесты, которые их напрямую дергали. Итог — **5 модулей**, не 7, с буквально нулём исполненных строк тела (`chain.py` + 4 slot-файла), подтверждено и coverage-прогоном, и grep по всему `app/`+`tests/`. `curriculum_slot.py` в прод-пути тоже сирота, но не «0 строк» — его тело исполняет переживший чистку `test_skip_helpers.py`. Счёт «12 прод-модулей» тоже не бьётся: в каталоге 16 непустых файлов (9 верхнего уровня + 7 в `slots/`), из них минимум 11 (`context`, `errors`, `grammar_theory`, `lesson_context`, `models`, `progression`, `xp`, `reading_slot`, `srs_slot`, и частично `plan.py`) имеют подтверждённые живые вызовы из `app/daily_plan/items/*.py`, `app/books/api.py`, `app/api/books*.py`, `app/curriculum/routes/*`. Эффект на пользователей нулевой — живой daily-plan идёт через `items/*.py`, мёртвый код недостижим ни для кого; это чистый мёртвый код + дыра в тестовом покрытии, не функциональный баг.
- **Верификация:** CONFIRMED — скептик, настроенный опровергать, опровергнуть не смог. Цитаты:
  - `app/daily_plan/linear/plan.py:299` `def get_linear_plan(...)` — 0 вызовов во всём `app/` и `tests/` (кроме собственного определения и упоминания в комментарии `tests/daily_plan/test_perfect_day_unified.py:3`, где явно написано «раньше бонус собирал legacy linear-план»). Живой ассемблер — `get_daily_plan` в `app/daily_plan/plan.py:347` — вызывает только 4 конкретных символа из `plan.py` (`_get_user_focus`, `_level_progress_to_dict`, `_position_from_lesson`, `get_plan_intensity`), не `get_linear_plan`.
  - `app/daily_plan/linear/chain.py:427` `def build_chain(...)` — единственный вызов на `app/daily_plan/linear/plan.py:340`, внутри мёртвого `get_linear_plan`. Coverage подтверждает: `chain.py` 274 стейтмента, 241 missing (12% cover), и все missing-диапазоны — это **целиком тела функций** (`47-54`, `61-71`, `89-118`, `130-140`, …, `455-525`); покрыты только строки модуля верхнего уровня и сигнатуры `def`. Ни одной строки тела не исполнено.
  - `app/daily_plan/linear/slots/error_review_slot.py:30` `def build_error_review_slot(...)` — единственный caller `chain.py:216` (мёртвый путь). Coverage: тело `32-61` целиком в missing; в тестах (`grep -rl` по всему `tests/`) ни один файл модуль не импортирует.
  - _(ещё 3 цитат — `.ralphex/audit-notes/daily-plan/skeptics/DP-C-182.md`; здесь список усечён по бюджету, а не по значимости)_
- **Где расхождение:** код — CLAUDE.md прямо документирует замену на unified-путь («Mission/linear-chain удалены») и не утверждает, что `linear/` полностью жив; расхождение только в точных числах кандидата (7→5, 12→16), не в инварианте документа.


### Опровергнуто скептиками — не переоткрывать без новых фактов

| Кандидат | Якорь | Утверждение финдера | Почему опровергнуто |
|---|---|---|---|
| `DP-C-183` | `tests/api/test_daily_plan_api.py:394-408` | три теста recovery-suggestion патчат ровно ту функцию, поведение которой заявлено в их именах | механизм («тесты патчат названную функцию») описан верно, но вывод «тесты ничего не проверяют» опровергается кодом: (1) анкорные тесты реально проверяют нетривиальный контракт роута (условное включение ключа `recovery_suggestion` в payload и проброс полей), регрессия в `app/api/daily_plan.py:439-440` их бы уронила; (2) сама ветвящаяся логика `_get_recovery_suggestion` (no-log / secured / unsecured / mission_type), к… |
| `DP-C-184` | `app/daily_plan/plan.py:412` | десять инвариантов (INV-09/10/13/15/16/21/23/29/32/41) не имеют ни одного краснеющего теста | механизм «ни одного теста-стража» не подтверждается: как минимум 5 из перечисленных в кандидате инвариантов (day_secured=False at assembly, graduated требует обоих условий, дедуп по id, дедуп по lesson_id, tomorrow_preview, а также сопряжённый с ним «build_optional graduated=True для заблокированного» через `_plan_meta.blocked_module_id`) имеют явные, специально написанные и сейчас зелёные unit/API-тесты с докстрока… |

---

## Приложение: PLAUSIBLE (3)

> Скептик не смог **ни подтвердить, ни опровергнуть** по коду: для вердикта нужен факт,
> недоступный read-only чтением (прод-состояние, нагрузочное поведение, поведение внешней
> системы или браузера). В реестр находок не идут и в сводке severity не считаются.

| Кандидат | Якорь | Утверждение | Почему не CONFIRMED |
|---|---|---|---|
| `DP-C-111` | `app/daily_plan/linear/lesson_context.py:256` | пауза невидима next-slot и continuation: оба ведут по плану, пока 3 источника говорят `mode=paused` | механизм для `/next-slot` реален и точно совпадает с якорем: `build_lesson_context` вызывает paused-неосведомлённый `get_daily_plan` вместо `get_daily_plan_unified`, и это достижимо из живого кода (`linear-plan-context.js:fetchNextSlot`, единственный вызывающий `/next-slot` в проде). Конкретный сценарий: юзер открыл SRS/curriculum-слот с `?from=linear_plan` до паузы (или ставит паузу в соседней вкладке во время … |
| `DP-C-139` | `app/achievements/streak_service.py:832-853` | двойная починка серии: две строки `spent_repair` на одну дату, 8 монет вместо 3 | механизм дублирования строки `spent_repair` для одной даты через гонку конкурентных запросов реален и подтверждён кодом (check-then-act без `UniqueConstraint` и без блокировки строки, три независимых entry points на общий `apply_paid_repair`). Но не хватает рантайм-состояния, чтобы подтвердить конкретно заявленный эффект «8 монет вместо 3»: по прочитанной механике `get_repair_cost` симметричная гонка первого в … |
| `DP-C-157` | `config/settings.py:213-219` | `REMEMBER_COOKIE_SAMESITE` не задан: кросс-сайтовый form-POST с `remember_token` проходит на csrf-exempt роуты зоны | цепочка в коде подтверждена полностью и независимо от догадок: отсутствующий `REMEMBER_COOKIE_SAMESITE` действительно приводит к тому, что `remember_token` уходит без атрибута `SameSite` вовсе (не совпадает с explicit `SESSION_COOKIE_SAMESITE='Lax'` у сессионной куки), Flask-Login восстанавливает `current_user` из одной этой куки, а `api_auth_required` пускает такую сессию на 8 `@csrf.exempt` POST-роутов плана дня … |

Что нужно, чтобы закрыть каждую: `DP-C-111` — прогон paused-пользователя через `/next-slot`
и `/continuation` на живом стенде; `DP-C-139` — воспроизведение гонки двух конкурентных
запросов починки серии под нагрузкой; `DP-C-157` — браузерная проверка отправки
`remember_token` кросс-сайтовым form-POST на csrf-exempt роут зоны.

---

## Покрытие и сознательные пропуски

**Без молчаливых усечений:** линза, которая не запускалась, файл, который никто не прочитал, и
проверка, которую заменили рассуждением вместо прогона, записаны здесь явно. Отсутствие находки
в реестре означает «не найдено», только если соответствующая линза действительно запускалась.

| Подзона | Просканировано | Сознательно не покрывалось | Причина |
|---|---|---|---|
| Ядро сборки (Task 2) | 5 линз (A–E) по 12 модулям ядра; 9 граничных веток; все 27 инвариантов зоны ядра получили вердикт; фактический замер числа SQL-запросов на сборку | частота срабатывания находок на живом проде; уровень изоляции транзакций и многопроцессный прогон; конкурентность при замере N+1 | нужен доступ к боевому окружению и нагрузочный стенд; замеры сняты тест-клиентом и объявлены нижней границей |
| Items · linear (Task 3) | 5 линз (A–E) по 10 item builders и `linear/`; пороги, cooldown'ы, XP-дедуп, бюджет и порядок | полный аудит логики разбора ошибок в `linear/errors.py` (651 строка) — просмотрена только по порогам; `lesson_context.py` / `context.py` — по касательной | разбор `errors.py` — самостоятельная зона (error review), не «план дня»; контекст урока — предмет Task 4/5 |
| API и SSR (Task 4) | 5 линз (A–E) по 19 правилам зоны; 11 классов состояния × 5 источников payload; фаззинг тел и query у 9 POST-эндпоинтов; auth-матрица | реальное поведение браузеров по `SameSite` (пробы шли на `werkzeug.test.Client`); наличие внешних (мобильных) клиентов API; параллельный прогон `/phrase-review/complete`; штатная форма `/login` и путь выдачи JWT; нагрузочный прогон | тест-клиент не эмулирует политику кук; часть severity зависит от ответа владельца (есть ли внешние клиенты, поднят ли Redis для лимитера) |
| Фронт (Task 5) | 2 линзы (A, B) по 3 шаблонам и 2 JS: расхождение клиента и сервера, i18n/a11y, fetch-надёжность, мёртвый фронт-код | линзы «C — мёртвый фронт-код» и «D — i18n/a11y» **отдельно не запускались**: их предмет вошёл в A и B (мёртвый код — в B, i18n/a11y — в A). Скелет реестра называл 4 линзы, план — 2; фактически прогнаны 2 с расширенным охватом | реальный рендер в браузере не снимался: все фронт-выводы получены чтением кода. Дефекты, видимые только в браузере, в реестр не попали и попасть не могли |
| Liveness (Task 6) | 3 независимых среза (AST-достижимость, живой прогон с трассировкой, grep) по 8 модулям-кандидатам + 5 модулей `slots/`, всплывших из среза 1; AST-подсчёт объёма мёртвого кода | мёртвые ветки **внутри** живых функций (гранулярность среза — функция); мёртвые модели и миграции зоны; динамическая диспетчеризация `getattr(obj, вычисляемое_имя)`; `app/curriculum/path_view.py:367` (читает `slots`/`baseline_slots`, кто передаёт — не трассировалось) | систематический обход веток требует branch-coverage; `path_view` вне зоны аудита. Ложных «мёртв» из-за динамики не ожидается: все 8 вердиктов подтверждены и grep'ом, и отсутствием в трассировке живого прогона |
| Покрытие (Task 7) | 3 прогона с `term-missing`; матрица по всем 44 файлам зоны + `app/api/daily_plan.py`; разбор тел функций через AST; перепись покрытия всех 16 эндпоинтов; проверка стражей у 47 инвариантов; AST-скан 400 тест-функций; резолв всех 51 patch-цели; 7 граничных состояний | branch coverage (`--cov-branch`); мутационное тестирование; фронтовые тесты (coverage.py не измеряет JS); xdist-прогон; повторная поимённая перепроверка таблицы «нет стража» после того, как скептик снял `DP-C-184` | замер шёл по строкам, «строка исполнена» ≠ «оба исхода `if` пройдены»; `mutmut` в зависимостях нет — все мутации описаны как рассуждение, применимое руками за минуту; параллельный прогон в этом чекауте даёт ложную краснуху из-за устаревших `learn_db_test_gw*` |

### Заранее объявленные пропуски (зафиксировано на Task 1, до сбора)

Эти линзы в брифе аудита отсутствовали. Они перечислены здесь, чтобы их отсутствие в итоговом
реестре нельзя было прочитать как «проверено и чисто». Критик на полноту (Task 9) сверил список
с фактом: **две позиции пришлось снять — линзы, объявленные незапущенными, фактически отработали.**

**Снято критиком — фактически проверено:**

- ~~**CSRF.**~~ Линза E Task 4 прогнала все 19 роутов зоны через колонку `CSRF-XS` (кросс-сайтовый
  POST без токена); 8 `@csrf.exempt` разобраны поимённо, результат — находки по зоне и
  PLAUSIBLE-кандидат `DP-C-157` (`REMEMBER_COOKIE_SAMESITE` не задан). Считать CSRF непроверенным
  здесь — занизить покрытие.
- ~~**Rate-limiting.**~~ Тоже закрыто линзой E: зафиксировано отсутствие собственных
  `@limiter.limit` в зоне, ключ лимита, берущийся из клиентского заголовка, и `memory://`-хранилище,
  не разделяемое между воркерами.

**Подтверждено критиком — действительно не запускалось:**

- **CSP и заголовки безопасности** — вне брифа; 0 вхождений `CSP` во всех заметках. Зона не вносит
  собственных инлайн-скриптов помимо уже учтённых мостом `window.I18N`.
- **Миграции** зоны (`20260524_lesson_skip`, `20260527_slot_skipped_unique_index`,
  `20260420_add_linear_daily_plan` и др.) на корректность up/down не проверялись; 0 вхождений
  `alembic`. Смежный незакрытый вопрос, объявленный ещё на Task 6: остались ли неиспользуемые
  таблицы и колонки от mission/chain.
- **Фоновые процессы — частично** (формулировка уточнена критиком). Планировщик **как производитель
  снапшотов** задет: `core-C` разобрал `app/telegram/scheduler.py:355-410` и зафиксировал, что на
  проде генерация снапшотов оборвалась `2026-08-07`. **Не покрыто:** жизненный цикл фоновых
  сервисов, их деплой, поведение при рестарте воркеров.
- **Нагрузочное поведение.** Числа стоимости сборки (PROBE 18) сняты тест-клиентом в одном процессе
  на почти пустой БД и объявлены нижней границей; на прод не переносятся. Профилирования под
  нагрузкой не было.
- **Браузерный обход.** 0 вхождений `Playwright`/`Selenium`. Фронт проверялся статически и рендером
  шаблонов через тест-клиент (`tools/fe_a_render.py`, 16 HTML-снимков). Дефекты, видимые только в
  браузере, находкой стать не могли — они уходят в PLAUSIBLE.

**Добавлено критиком — не объявлялось заранее и не запускалось:**

- **Логи и наблюдаемость.** Не проверялось, что зона пишет в логи при отказах и попадают ли туда
  идентификаторы пользователя. Причина пропуска: низкая отдача при <10 активных пользователях.
- **Взаимодействие с 60-секундным TTL-кешем `SiteSettings`.** Зона читает фича-флаги
  (`daily_race_enabled`, `streak_shield_enabled`) через per-worker кеш; 0 вхождений
  `get_public_settings` во всех заметках. Причина пропуска: эффект ограничен ≤60 с рассинхрона
  флагов между воркерами, поведенческого следствия для `day_secured` нет.
- **a11y** — линза была объявлена в скелете реестра и в плане Task 5, но не запускалась ни разу.
  **Пропуском не осталась: выполнена на Task 9**, результат — в секции «Догон: линза a11y» выше.

### Открытые хвосты: живой код зоны без содержательного разбора

Критик отделил «не прочитано вообще» (таких файлов — 0) от «объявлено покрытым, разбора нет».
Вторая категория — не сознательный пропуск, а **долг аудита**, и записана отдельно именно поэтому:

| Хвост | Объём | Почему это долг, а не пропуск |
|---|---|---|
| `app/daily_plan/linear/slots/reading_slot.py` | 220 строк | Единственный **живой** модуль `slots/` — 6 внешних прод-вызывателей (`books/api.py:985,1101,1277,1329`, `api/books.py:369`, `api/books_catalog.py:28,133`, `linear/xp.py:396`). Линза C объявила его покрытым, но разобрала только `items/reading.py::_read_today` |
| `app/daily_plan/linear/context.py` | 65 строк | Держит **INV-36** (`LinearSlotKind`, `build_slot_url`, legacy-маппинг `book→reading`), импортируется 10 модулями (`items/curriculum.py:23`, `items/error_review.py:25`, все 7 `slots/*`). Ни одна серверная линза его не открывала; INV-36 в `coverage.md` помечен «СЛАБЫЙ» |
| `app/daily_plan/items/setup.py` | 88 строк | Живой builder двух required-пунктов онбординга (`plan.py:337,343`, `plan_builder.py:262`). Объявлен в «что покрыто» линзы C, ни одна находка и ни один абзац «не дало находки» его не разбирает |
| `app/telegram/queries.py::get_daily_plan_for_telegram` | — | **Второй потребитель payload зоны вне `url_map`.** Сверка расхождений линзы A Task 4 охватила 4 API + SSR-дашборд; телеграм-рендер в неё не входил, хотя расхождение payload — ровно предмет этой линзы |
| `app/daily_plan/linear/grammar_theory.py` | 3 функции из 4 | `items-C` разобрал только `get_theory_for_lesson`; `coverage.md` даёт 0/4 тел функций, покрытых тестами |
| `app/daily_plan/items/skills.py` | 73 строки | Жив по импорт-графу (`items/challenge.py:67` под челленджем категории `listening_deep`), но **не исполнился ни в одном прогоне** — вердикт по одному срезу не выносится |
| `INV-35` | — | Гонка «inline `daily_plan_ctx` из submit-ответа против HTTP round-trip `fetchNextSlot`» названа в плане Task 5 поимённо; `FE-B-08` касается `lesson-completion.js`, но саму гонку ни одна заметка не разбирает |


### Критик-агент на полноту (Task 9)

Отдельный агент прочитал **не находки, а сам аудит**: какие файлы зоны не открыл ни один финдер,
какие эндпоинты не тронуты, какие инварианты остались без линзы, какие заявленные линзы не
запускались. Полный отчёт — `.ralphex/audit-notes/daily-plan/critic-completeness.md` (229 строк).
Метод критика: фактический список файлов (`find app/daily_plan -name '*.py'` → 44 + 7 вне пакета),
счётчики упоминаний **раздельно** по линзам-финдерам и по последующим задачам (иначе `liveness.md`
маскирует непрочитанный финдерами файл), и — обязательно — ручная перепроверка каждого
подозрительного файла: есть ли содержательный разбор или только строка в списке «что покрыто».
Счётчик упоминаний критик сам объявляет прокси, а не доказательством.

**Что критик подтвердил:**

- **Файлов зоны, не прочитанных вообще никем, — 0.** Два файла с нулём упоминаний у финдеров
  (`linear/__init__.py` — 1 строка, `linear/slots/__init__.py` — dataclass `LinearSlot`) прочитаны
  на Task 6.
- **Не тронутых эндпоинтов — 0.** Все 19 правил `url_map` прогнаны линзой E через матрицу
  «аноним / JWT / без модуля / CSRF-XS / лимит / чужой `user_id`» и линзой B через матрицу
  невалидного ввода. Риск был у `/api/streak/repair-web` (его нет в плановом тексте) — закрыт.
- **Инвариантов без линзы — 0 по существу.** Все 47 получили разбор.

**Что критик нашёл — и что с этим сделано:**

| # | Дыра | Решение Task 9 |
|---|---|---|
| K-1 | **Линза a11y не запускалась вовсе** — строка `aria-` встречается **0 раз** во всех заметках аудита (включая 184 скептика и 33 файла второго прохода), при 41 атрибуте `aria-*` и двух `role="progressbar"` в шаблонах зоны. План Task 5 называл обе проверки (`UI-022`, `UI-024`) поимённо; скелет реестра объявлял линзу D | **Новая работа — линза выполнена на Task 9**, результаты ниже. Два «горячих» риска сняты негативным результатом, три кандидата зафиксированы как хвост |
| K-2 | `linear/slots/reading_slot.py` (220 строк) — **единственный живой модуль `slots/`**, 6 внешних прод-вызывателей (`books/api.py`, `api/books.py`, `api/books_catalog.py`, `linear/xp.py`); объявлен покрытым линзой C, фактически разобран только `items/reading.py::_read_today` | Открытый хвост, внесён в «Покрытие и сознательные пропуски» как **непокрытый живой код**, не как пропуск |
| K-3 | `linear/context.py` (65 строк) — держит **INV-36** (`LinearSlotKind`, `build_slot_url`, legacy `book→reading`), импортируется 10 модулями, не открыт ни одной серверной линзой; INV-36 в `coverage.md` помечен «СЛАБЫЙ» | То же — открытый хвост |
| K-4 | `items/setup.py` (88 строк) — живой builder двух required-пунктов онбординга (`plan.py:337,343`), объявлен покрытым, разбора нет | То же — открытый хвост |
| K-5 | `app/telegram/queries.py::get_daily_plan_for_telegram` — **второй потребитель payload зоны вне `url_map`**; сверка расхождений линзы A охватила 4 API + SSR-дашборд, телеграм-рендер в неё не входил | То же — открытый хвост |
| K-6 | Мелочи: `INV-35` (гонка inline `daily_plan_ctx` против `fetchNextSlot`), 3 из 4 функций `linear/grammar_theory.py`, `items/skills.py` (жив по импорт-графу, но не исполнился ни в одном прогоне — нужен активный челлендж `listening_deep`) | Открытые хвосты малого объёма |
| K-7 | **Бухгалтерия:** `INV-20` и `INV-22` разобраны, но без проставленного ID | Проставлено: `INV-20` держит **DP-059** (`_module_accessible_for_user` как реплика маршрутного гейта, `curriculum.py:534`). `INV-22` разбирался кандидатом `DP-C-061` и **опровергнут скептиком** — то есть инвариант проверен и нарушения не найдено; строка в «Опровергнуто скептиками» (`curriculum.py:692`) |
| K-8 | **Заявленные заранее пропуски CSRF и rate-limiting фактически были закрыты** линзой E (31 упоминание CSRF, колонка `CSRF-XS` в матрице 19 роутов; находки по ключу лимита из клиентского заголовка и по отсутствию `@limiter.limit`). Оставить их в списке «не проверялось» — занизить покрытие | Список заранее объявленных пропусков исправлен ниже: CSRF и rate-limiting **сняты** с пометкой, чем именно закрыты |
| K-9 | Формулировка «фоновые процессы не покрываются» неточна: `core-C` разобрал `app/telegram/scheduler.py:355-410` (генерация снапшотов) и зафиксировал, что на проде генерация оборвалась `2026-08-07` | Формулировка уточнена: планировщик **как производитель снапшотов** — задет; жизненный цикл и деплой фоновых сервисов — нет |
| K-10 | Не объявлялись и не запускались: логи/PII, взаимодействие с 60-с TTL-кешем `SiteSettings` | Внесены в сознательные пропуски с причиной |

#### Догон: линза a11y по фронтенду плана (выполнена на Task 9)

Предмет — 3 шаблона и 2 JS зоны. Проверки взяты из `CLAUDE.md` (UI-022, UI-024) и из плана Task 5.

**Два главных риска сняты негативным результатом** — это тоже результат линзы, а не её отсутствие:

- **UI-022 («обновляешь ширину — обновляй `aria-valuenow`») в зоне неприменим.** Оба
  `role="progressbar"` — `unified_daily_plan.html:151` (прогресс модуля, `aria-valuenow="{{ _done }}"`)
  и `:416-417` (прогресс SRS-слота, `aria-valuenow="{{ _srs_done_capped }}"`) — рендерятся сервером
  и живут ровно до перезагрузки страницы. Ни `linear-daily-plan.js`, ни `linear-plan-context.js`,
  ни инлайновый скрипт партиала не трогают ни `style.width`, ни `aria-valuenow`: единственный
  способ обновить прогресс в этом UI — `window.location.reload()` (`linear-daily-plan.js:238`,
  инлайн партиала). Рассинхрона ширины и `aria-valuenow` возникнуть не может.
- **UI-024 («single-select ≠ toggle») в зоне неприменим.** `aria-pressed` во всех трёх шаблонах
  зоны — **0 вхождений**; групп взаимоисключающих кнопок, объявленных тогглами, нет. Три кнопки
  причины пропуска (`plan-item__skip-reason-btn`, `:440-442`) — не single-select: каждая сразу
  отправляет POST и перезагружает страницу, состояния «выбрано» у них нет.

**Три кандидата (в реестр находок НЕ внесены).** Они найдены на Task 9 и **не проходили
адверсариальную верификацию Task 8** — отдельного скептика на них не запускалось. Вносить их в
реестр наравне с 127 находками значило бы смешать два разных стандарта доказательства, а
Task 10 требует «находок без вердикта скептика — ноль». Поэтому они стоят здесь, с готовыми
якорями, как вход для ремедиации или для добора аудита:

| # | Якорь | Симптом | Проверено чтением |
|---|---|---|---|
| A11Y-1 | `app/templates/partials/unified_daily_plan.html:432-438` + инлайн-скрипт `:747-757` | Кнопка «Пропустить» раскрывает блок причин переключением `hidden`, но не имеет ни `aria-expanded`, ни `aria-controls`. Пользователь скринридера нажимает кнопку и не получает никакого сообщения, что ниже появился выбор из трёх причин | `reasonsDiv.hidden = !reasonsDiv.hidden` — единственное, что делает обработчик; атрибуты состояния не выставляются |
| A11Y-2 | `app/templates/partials/unified_daily_plan.html:306-313` | Завершённый пункт плана отличается от незавершённого только `aria-hidden="true"` галочкой и приглушённым стилем — комментарий в шаблоне это прямо и формулирует («The done marker + muted styling are the affordance»). Скринридер читает завершённый пункт так же, как невыполненный. Рядом, в чипах целей (`:205`), нужный паттерн уже применён: `<span class="visually-hidden">— выполнено</span>` | `visually-hidden` встречается в трёх шаблонах зоны **ровно один раз** — в `:205`, и не встречается ни в одном из 5 состояний пункта плана |
| A11Y-3 | `app/templates/words/dashboard_unified.html:148` + `linear-daily-plan.js:33-45` | Модалка выбора книги объявлена `role="dialog" aria-modal="true"`, но управления фокусом нет: при открытии фокус не переносится внутрь, ловушки фокуса нет, при закрытии фокус не возвращается на кнопку-открыватель. `aria-modal="true"` обещает скринридеру, что вне диалога ничего нет, — а Tab уводит на дашборд под ним | `.focus()` в `linear-daily-plan.js` — 0 вхождений; открытие — только `modal.hidden = false` + `setAttribute('aria-hidden','false')`. Escape обработан (`:270-271`) |

Общий вес хвоста — P3-класса: ни один из трёх не ломает `day_secured`, прогресс или данные.

---

## Самосогласованность (Task 9)

Проверяется программой, а не глазами: `.ralphex/audit-notes/daily-plan/tools/check_consistency.py`
(read-only, парсит этот же файл). Она сверяет шесть вещей:

1. числа в шапке «Сводка severity» = суммы по индексам подзон = число секций деталей;
2. каждый ID из индекса имеет ровно одну секцию `#### DP-NNN`, и наоборот — «сирот» нет;
3. severity совпадает в трёх местах: в индексе, в заголовке детали и в секции, где деталь лежит;
4. у каждой находки есть `path:line`, «Сценарий отказа» и «Верификация» с вердиктом;
5. ID сквозные — без дублей и без дыр в нумерации;
6. колонка «Где расхождение» заполнена во всех строках индекса.

```
=== Реестр: 2026-08-26-daily-plan-audit.md ===
подзон: 6 · строк индекса: 127 · секций деталей: 127

Sev     шапка   индекс   детали
P0          0        0        0
P1          4        4        4
P2         71       71       71
P3         52       52       52
ВСЕГО     127      127      127

Подзона                     индекс  детали   шапка
Ядро сборки плана               32      32      32
Item builders и `linear/*       41      41      41
API и серверный рендер да       40      40      40
Фронтенд плана                   5       5       5
Liveness / мёртвый код           6       6       6
Дыры в покрытии                  3       3       3

Колонка «Где расхождение» (индекс): {'код': 88, '—': 32, 'CLAUDE.md': 7}
Вердикты: {'CONFIRMED': 127}

✓ расхождений нет
```

Нумерация `DP-001…DP-127` сквозная, дублей и дыр нет. Вердикт скептика есть у всех 127 находок —
`PLAUSIBLE` в реестре не встречается ни разу (три таких кандидата живут в приложении и в счёт
находок не входят), что и требует Task 10.

**Что скрипт проверить не может** — и это проверено вручную:

- **Содержательное соответствие симптома и сценария отказа.** Скрипт видит, что поле непустое,
  а не что оно осмысленно.
- **Актуальность `path:line`.** Строки верны на HEAD `0b1f8b7f`; после ремедиации они поедут.
- **Три расхождения, найденные при этой сверке и исправленные на Task 9:**
  1. блок «Индекс P1» был вставлен в документ **дважды** подряд (одинаковые 4 строки) — дубликат удалён;
  2. преамбула «Расхождения с `CLAUDE.md`» утверждала «колонка заполнена у **99**, из них **92** —
     код»; фактический подсчёт даёт **95** и **88** (у 32 находок стоит `—`: инвариант не задет) —
     числа исправлены по выводу скрипта;
  3. `INV-20` и `INV-22` были разобраны линзами, но ID в находках не проставлены (замечание K-7
     критика) — проставлены: `INV-20` → `DP-059`, `INV-22` → опровергнутый кандидат `DP-C-061`.

### Продакшн-код не тронут — проверено на Task 9

```
$ git status --short
 M docs/audit/2026-08-08-cross-zone-audit.md
 M docs/audit/2026-08-26-daily-plan-audit.md
 M scripts/clear_missing_word_audio.py
 M tests/scripts/test_audio_ref_walker.py
?? book_translator-master/
?? tests/scripts/test_rewrite_short_vocab_examples.py

$ git diff --stat -- app/ tests/
 tests/scripts/test_audio_ref_walker.py | 40 +++++++++++++++++++++++++++++++++-
 1 file changed, 39 insertions(+), 1 deletion(-)
```

- **`app/` — diff пуст полностью.** Ни одного изменённого продакшн-файла.
- **`tests/` — diff побайтово совпадает** с базисом, снятым до Task 3
  (`.ralphex/audit-notes/daily-plan/git-baseline.md`): тот же единственный файл, те же 39/1 строк.
  Это хвост ремедиации `CNT-003`/`CNT-006` (тесты аудио-скриптов), лежавший в дереве **до** старта
  аудита и к зоне «План дня» отношения не имеющий.
- **Изменены аудитом ровно два файла, оба в `docs/audit/`:** этот реестр и
  `2026-08-26-baseline-daily-plan.txt`. Остальные `M`-строки — то же дерево, что и на Task 1.
  Файлы в `docs/` gitignored, но отслеживаются: правки — `git add -u`, новый файл — `git add -f`.

---

## Verification (Task 10)

Прогон приёмки: **2026-08-28**, последний коммит аудита `967504d6` (приёмка снималась на `c16244d5`, затем Task 11 добавил ссылку в `CLAUDE.md`), ветка `word-sets-quiz`. Все четыре критерия
проверены программами, а не глазами; команды и вывод — ниже.

| Критерий | Как проверено | Статус |
|---|---|---|
| Аудит не изменил продакшн-код | `git diff --name-only 0b1f8b7f..967504d6 -- app/ tests/` — пусто; 8 коммитов аудита трогают 4 файла, все в `docs/`. **Диапазон закрытый, не `HEAD`:** после приёмки на ветку легли `137e98bb`/`6b0a5ba2` (код-ревью фичи наборов слов, к аудиту не относятся), и они `app/`/`tests/` трогают | ✅ |
| Прогоны воспроизводят baseline | `pytest -m smoke` — совпадает точно; `pytest tests/daily_plan` — 2 унаследованные красные, ровно baseline (третья красная отозвана 2026-08-28, разбор ниже) | ✅ |
| У каждой находки есть ID, severity, `path:line`, сценарий отказа, вердикт скептика | `.ralphex/audit-notes/daily-plan/tools/check_consistency.py` перепрогнан на Task 10: 127 находок, вердиктов `CONFIRMED` — 127, находок без вердикта — **0** | ✅ |
| Покрыты все 16 эндпоинтов, 44 Python-файла, 3 шаблона, 2 JS — либо финдером, либо явным пропуском | `.ralphex/audit-notes/daily-plan/tools/check_task10_coverage.py` (новый): непокрытых и необъявленных артефактов — **0** | ✅ |
| Числа в шапке = числа в индексе = число секций деталей | `.ralphex/audit-notes/daily-plan/tools/check_consistency.py`, вывод — в секции «Самосогласованность» | ✅ 127 = 127 = 127, расхождений нет |

### Критерий 1 — продакшн-код не тронут

```
# рабочая копия на момент приёмки, коммит 967504d6
$ git diff --stat -- app/ tests/daily_plan/ tests/api/ tests/study/
(пусто)
$ git status --porcelain -- app/ tests/daily_plan/ tests/api/ tests/study/
(пусто — untracked-файлов зоны тоже нет)
# закреплённый диапазон аудита — воспроизводится в любой момент
$ git diff --name-only 0b1f8b7f..967504d6 -- app/ tests/
(пусто)
$ git diff --stat 0b1f8b7f..967504d6
 docs/audit/2026-08-26-baseline-daily-plan.txt |   90 +
 docs/audit/2026-08-26-coverage-daily-plan.txt |  224 +
 docs/audit/2026-08-26-daily-plan-audit.md     | 2652 +++++++++++++++
 docs/plans/2026-08-26-daily-plan-audit.md     |  172 +
 4 files changed, 3138 insertions(+)
```

Проверка сильнее, чем «diff по рабочей копии пуст»: сверены **все 8 коммитов аудита** от базисного
HEAD `0b1f8b7f` до `967504d6`. Ни один не касается `app/` или `tests/`. Две `M`-строки под `tests/`
в `git status` (`tests/scripts/test_audio_ref_walker.py`, `tests/scripts/test_rewrite_short_vocab_examples.py`)
лежали в дереве до старта аудита — это хвост `CNT-003`/`CNT-006`, зафиксированный в секции
«Состояние рабочей копии» файла `2026-08-26-baseline-daily-plan.txt`.

**Диапазон закреплён явным коммитом, а не `HEAD`.** Аудит занимает `0b1f8b7f..967504d6`; после
приёмки в ту же ветку легли правки код-ревью фичи наборов слов (`137e98bb`), которые трогают `app/`
и `tests/` — в том числе `tests/daily_plan/test_events.py`. Поэтому та же команда с `HEAD` сегодня
вернёт непустой список: это не нарушение критерия аудитом, а более поздняя работа в общей ветке.
Проверять критерий 1 надо по закреплённому диапазону.

### Критерий 2 — прогоны против baseline

```
# прогон приёмки; третья красная позже отозвана — см. «Отозвано (2026-08-28)» ниже
$ python -m pytest tests/daily_plan --tb=line
3 failed, 401 passed, 1 warning in 9.76s        # baseline: 2 failed, 402 passed

$ python -m pytest -m smoke --tb=line
695 passed, 9917 deselected, 1 warning in 17.67s # baseline: 695 passed — совпадает точно
```

Сверка **по именам, а не по числу** (форма проверки предписана самим baseline и секцией «Дыры в
покрытии»):

```
$ diff /tmp/base.txt /tmp/now.txt
0a1
> FAILED tests/daily_plan/test_events.py::TestSlotSkipEndpoint::test_all_valid_reasons_accepted
```

Обе унаследованные красные (`test_srs_slot_completion.py::test_fallback_fires_corrective_award_when_pool_empty`,
`::test_fallback_is_idempotent`) на месте и не изменились. Третья — **та самая, что предсказана на
Task 7**, и её причина установлена, а не предположена:

1. тест шлёт три `slot_skipped` подряд, патчем обнулив квоту (`tests/daily_plan/test_events.py:128-140`);
2. второй POST ловит `IntegrityError` на партиальном уникальном индексе `uq_daily_plan_events_slot_skipped`;
3. `app/api/daily_plan.py:850-853` переводит этот `IntegrityError` в `429 skip_quota_exhausted` — тест ждёт 200 и падает на `reason=too_hard`;
4. индекс объявлен **только в миграции** `20260527_slot_skipped_unique_index.py:33`, в модели `DailyPlanEvent.__table_args__` (`app/daily_plan/models.py:75-78`) его нет ⇒ в `create_all`-БД он отсутствует, в migrated-БД присутствует.

То есть цвет теста определяется **формой локальной тестовой схемы**, а не кодом: `learn_db_test`
между снятием baseline (2026-08-26) и приёмкой (2026-08-28) получил `flask db upgrade`. Кандидат
«индекс только в миграции» разобран и опровергнут скептиком (`DP-C-041`): в проде схему ставит
Alembic, пробел ограничен `TESTING`-конфигурацией по явному дизайну. Аудит к этому непричастен —
критерий 1 показывает нулевой diff по `app/` и `tests/` за все 8 коммитов.

**Что из этого следует для будущих прогонов** (записано, чтобы следующий читатель не искал регрессию
там, где её нет): ожидание «ровно 2 red в `tests/daily_plan`» верно только для `create_all`-схемы.
Сверять надо список имён против `docs/audit/2026-08-08-baseline-pytest.txt`.

**Отозвано (2026-08-28).** Третья красная больше не воспроизводится: код-ревью фичи наборов слов
(`137e98bb`, вне диапазона аудита) переписало `test_all_valid_reasons_accepted` так, что оно чистит
`DailyPlanEvent` между попытками и больше не упирается в партиальный уникальный индекс. Разбор
пунктов 1–4 остаётся верным описанием механизма (индекс живёт только в миграции), но как ожидание
для будущих прогонов он снят — в `tests/daily_plan` снова 2 унаследованные красные.

### Критерий 3 — обязательные поля у каждой находки

`.ralphex/audit-notes/daily-plan/tools/check_consistency.py` перепрогнан на Task 10 (read-only, парсит сам реестр). Проверка 4 в
скрипте требует у **каждой** секции детали одновременно: якорь вида `` `путь:строка` `` (в заголовке
или в теле), подстроку «Сценарий отказа» и «Верификация» с вердиктом `CONFIRMED|PLAUSIBLE`.

```
подзон: 6 · строк индекса: 127 · секций деталей: 127
Sev     шапка   индекс   детали
P0          0        0        0
P1          4        4        4
P2         71       71       71
P3         52       52       52
ВСЕГО     127      127      127
Вердикты: {'CONFIRMED': 127}
✓ расхождений нет
```

Находок без вердикта — **0**, что и требует критерий. `PLAUSIBLE` в реестре не встречается ни разу
(три таких кандидата живут в приложении и в счёт находок не входят).

### Критерий 4 — покрытие артефактов зоны

Новый скрипт `.ralphex/audit-notes/daily-plan/tools/check_task10_coverage.py`. Ключевое в его методе: «покрыт» засчитывается по
заметке **финдера** (`core-*`, `items-*`, `api-*`, `frontend-*`, `liveness.md`, `coverage.md`,
`lenses/**`), а не по упоминанию в реестре — иначе постфактумная строка маскировала бы файл,
которого финдер не открывал. Список эндпоинтов берётся из живого `app.url_map`, а не из плана.

```
=== Python-файлы app/daily_plan (44) ===
  финдер    42
  пропуск    1     # linear/__init__.py — 1 строка докстринга
  реестр     1     # app/daily_plan/__init__.py — разобран в подзоне Liveness (:2183)

(blueprint api_daily_plan: 16 правил, 16 уникальных URL)
=== Эндпоинты api_daily_plan (16) ===
  финдер    16
=== Шаблоны (3) ===   финдер 3
=== JS (2) ===        финдер 2

✓ непокрытых и необъявленных артефактов нет
```

Три файла зоны — пакетные шимы, и для полноты названы здесь поимённо, а не только в отчёте критика
(`.ralphex/` не коммитится, ссылка из реестра туда для стороннего читателя не разрешается):

| Файл | Строк | Статус |
|---|---:|---|
| `app/daily_plan/__init__.py` | 21 | прочитан на Task 6, разобран в подзоне Liveness (`:2183` — реэкспорт идёт из `models`, не из `assembler`); находок нет |
| `app/daily_plan/linear/__init__.py` | 1 | **сознательный пропуск** — одна строка докстринга, содержимого для аудита нет |
| `app/daily_plan/linear/slots/__init__.py` | 35 | прочитан на Task 6 (`liveness.md:374`) — dataclass `LinearSlot`; находок нет |

Отдельно: 16 эндпоинтов blueprint'а `api_daily_plan` покрыты все; три оставшихся правила зоны из
19 (`words`-blueprint: `/api/daily-plan/next-step`, `/api/streak/repair-web`, `/dashboard`) разобраны
линзами Task 4 — критик подтвердил «не тронутых эндпоинтов — 0».

**Чего эта проверка не доказывает.** Скрипт видит, что артефакт **назван** финдером, а не что разбор
был содержательным. Именно поэтому долг аудита вынесен отдельной таблицей «Открытые хвосты: живой
код зоны без содержательного разбора» — 7 позиций, из которых `reading_slot.py` (220 строк),
`linear/context.py` (65) и `items/setup.py` (88) объявлены покрытыми, но разбора не получили.
Критерий 4 они формально проходят, содержательно — нет, и это записано, а не замолчано.
