# Ремедиация аудита «План дня» — фаза 1 (2026-08-29)

## Overview

Первая фаза ремедиации реестра `docs/audit/2026-08-26-daily-plan-audit.md` (127 находок).
В объём входят **16 находок**: все **4 P1**, кластер **«граница суток»** (11 находок ядра, одна
первопричина — два базиса дня в одном коде) и **`DP-051`** как обязательное предусловие к `DP-035`.

Остальные 111 находок остаются открытыми в реестре и **в этот заход не берутся** — список
следующих кандидатов в Post-Completion. Аудит в этом плане **не переоткрывается**: если находка
не воспроизводится на HEAD, это фиксируется в реестре как «отозвана с причиной», а не
переисследуется заново.

**Два решения владельца, принятые до старта** (влияют на объём):

1. **Границу суток чиним глобально.** `_user_day_boundaries` (календарная полночь) переводится на
   учебный день 02:00 **во всех ~20 точках вызова**, включая телеграм-планировщик и `get_current_streak`,
   а не только в streak-починке. Цена — сдвиг окон уведомлений и возможное изменение текущего
   значения `streak` у существующих юзеров; это измеряется до правки, а не после.
2. **XP — только вперёд.** Исторические недоплаты (`DP-034`: ~20 начислений по 9 вместо 18;
   `DP-035`: 30 закрытых дней без бонуса 25 XP) **не добираются**: ни SQL, ни backfill-скрипта.
   Чиним код, историю не трогаем.

### Объём: находка → что делаем

| ID | Sev | Первопричина | Задача |
|---|---|---|---|
| `DP-001` | P1 | три базиса суток в `process_streak_on_activity` + порядок починок | Task 2, Task 3 |
| `DP-033` | P1 | required-слот чтения строится без гейта доступа к книге | Task 4 |
| `DP-034` | P1 | вычищенный антифродом `score` доезжает до скейлера как `0.0` | Task 5 |
| `DP-051` | P2 | `award_perfect_day_xp_idempotent` — единственный XP-хелпер без savepoint | Task 6 (предусловие) |
| `DP-035` | P1 | perfect-day начисляется только из слот-обработчиков, «подметальщика» нет | Task 6 |
| `DP-002`, `DP-009`, `DP-027` | P2/P3 | snapshot: окно и докстринги на календарной полуночи | Task 7 |
| `DP-003` | P2 | SSR-дашборд пишет `secured_at` по календарной дате | Task 7 |
| `DP-008`, `DP-010`, `DP-012`, `DP-026` | P2/P3 | читатели дат на разных базисах | Task 8 |
| `DP-013`, `DP-022` | P2/P3 | контракт `tz` на call-site; две реализации «вчера не закрыто» | Task 8 |
| `DP-011` | P2 | смена `User.timezone` переигрывает прошлые идемпотентные ключи | Task 8 (решение: чинить или зафиксировать) |

## Context

**Базис.** Ветка `daily-plan-remediation` от `word-sets-quiz@54f90e64` (текущий HEAD), не от `master`:
на ней живёт фича наборов слов, на ней снят аудит, и на ней уже лежат две смежные правки из
код-ревью — гейт черновика в `app/api/books_catalog.py` (короткий репро `DP-033`) и предписание
`DP-125` в `tests/daily_plan/test_srs_slot_completion.py`. Альтернатива (резать от `master`)
потеряла бы обе и потребовала бы разрешать конфликт при мерже наборов слов.

**Реестр и его строки.** `path:line` в реестре снят на `0b1f8b7f`; ветка ушла вперёд, строки
сдвинулись. Механизмы всех 4 P1 перепроверены на HEAD `54f90e64` при составлении этого плана и
воспроизводятся; актуальные якоря — в теле задач ниже.

**Ключевые файлы зоны правки**

- Границы суток: `app/utils/time_utils.py` (`LEARNING_DAY_START_HOUR=2`, `_study_day_date`,
  `get_user_local_date`, `get_user_local_day_bounds`, `day_to_naive_utc`),
  `app/telegram/queries.py:22` (`_user_day_boundaries` — календарная полночь, **корень кластера**)
- Streak: `app/achievements/streak_service.py` (`process_streak_on_activity:282`,
  `find_missed_date:856`, `find_auto_heal_date:905`, `auto_heal_streak_on_activity:966`,
  `apply_shield_repair:820`)
- Чтение: `app/daily_plan/items/reading.py:50` (`_book_is_actionable_for_reading`),
  `app/daily_plan/plan_builder.py` (`_reading_item_dict`), `app/daily_plan/snapshot.py`
  (`overlay_completion`, `_is_item_completed`), гейт — `app/books/access.py::can_user_access_book`
- XP: `app/curriculum/routes/lessons.py:315-400` (theory-only ветка),
  `app/daily_plan/linear/xp.py:229` (`maybe_award_curriculum_xp`), `:505`
  (`maybe_award_linear_perfect_day`), `app/achievements/xp_service.py:212`
  (`award_perfect_day_xp_idempotent`), `:297` (`apply_score_to_base`)
- Писатели `secured_at`: `app/api/daily_plan.py:332-370` (`daily_status`),
  `app/words/routes.py:1046-1065` (`_render_unified_dashboard`)

**Радиус глобальной унификации 02:00 — 20 call-sites `_user_day_boundaries`/`has_activity_today`:**

| Файл | Точки | Что сдвинется |
|---|---|---|
| `app/telegram/queries.py` | `:43,97,275,487,1070,1220,1284` | окно «сегодня» для `get_current_streak`, дневной сводки, слова дня, вчерашнего среза |
| `app/telegram/scheduler.py` | `:276,292,304,334` | гейты «занимался ли сегодня» для morning/nudge/evening-уведомлений |
| `app/achievements/streak_service.py` | `:316,874,890,928,932,947,955,1277` | `real_activity`, `find_missed_date`, `find_auto_heal_date`, статус серии |

Админские DAU/WAU/MAU (`app/admin/main_routes.py`, `dashboard_routes.py`) этих хелперов **не**
используют и остаются на прежнем базисе — историческая сопоставимость метрик не ломается.

**Внешние факты, обязательные к учёту**

- Учебный день с 02:00 — **осознанное решение владельца**, а не баг: цель ремедиации привести к
  нему остальной код, а не наоборот.
- Локальная `learn_db_prod` — **копия боевых данных**: любые замеры только read-only, никаких
  write-проверок «на живых».
- `docs/` и `scripts/` в `.gitignore`, но отслеживаются: правки — `git add -u`, новый файл — `git add -f`.
- Коммиты — без упоминаний AI/Claude/Co-Authored-By.
- `pytest tests/daily_plan` на HEAD даёт **0 падений** (не 2, как в baseline аудита: `3fd29d85`
  применило предписание `DP-125`). Сверять надо со свежим baseline из Task 1, а не с числами реестра.

## Development Approach

- **Testing approach: TDD для всех P1** — сначала падающий регресс-тест, воспроизводящий сценарий
  отказа из тела находки, потом фикс. Для P2/P3 кластера — обычный порядок, но тест-страж обязателен:
  находка, закрытая без теста, считается незакрытой.
- **Каждая задача заканчивается прогоном** `pytest tests/daily_plan -q` + `pytest -m smoke -q`;
  переход к следующей задаче — только при нуле новых падений против baseline Task 1.
- Порядок задач жёсткий там, где есть зависимость: Task 2 (фундамент дня) → Task 3 (порядок починок,
  читает те же функции); Task 6 начинается с `DP-051`, потому что фикс `DP-035` добавляет два новых
  вызывателя незащищённому от гонки хелперу.
- **Инкрементальные коммиты по находке или связной группе**, сообщение вида `fix(daily-plan): <ID> — <суть>`.
- **YAGNI:** никаких новых слоёв и абстракций «на будущее». Единственная новая сущность за весь
  план — канонический хелпер окна учебного дня, и он вводится потому, что его отсутствие и есть
  первопричина кластера.
- **Не расширять объём.** Смежные находки, попадающиеся под руку (`DP-020` — 366 итераций в
  `get_current_streak`, `DP-082` — `pytz` против `ZoneInfo` в валидаторе), **не чинятся**: они
  остаются в реестре, в коде помечать их TODO не нужно.
- Замеры «до/после» по копии прода делаются read-only SQL и записываются в
  `docs/audit/2026-08-29-remediation-measurements.md` — иначе утверждение «починили» ничем не
  отличается от «изменили код».

## Implementation Steps

### Task 1: Базис ремедиации и замер «до»

**Files:**
- Create: `docs/audit/2026-08-29-baseline-remediation.txt`
- Create: `docs/audit/2026-08-29-remediation-measurements.md`

- [x] создать ветку `daily-plan-remediation` от `word-sets-quiz@54f90e64`
- [x] снять baseline: полный `pytest -q` (список FAILED nodeid), `pytest tests/daily_plan -q`,
      `pytest -m smoke -q`, `ruff check .` — всё в `2026-08-29-baseline-remediation.txt`; это
      единственный эталон «известно-красного» для всего плана
- [x] read-only замер «до» по копии прода, три числа из тел находок — воспроизвести и записать:
      (а) `DP-033` — сколько юзеро-дней держат недостижимый `reading:*` в required (реестр: user 39,
      55 дней подряд); (б) `DP-034` — сколько начислений `linear_curriculum_grammar` равны 9
      (реестр: 18 из 20); (в) `DP-035` — сколько `daily_plan_log.secured_at IS NOT NULL` без парного
      `streak_events.event_type='xp_perfect_day'` (реестр: 30 из 72)
- [x] **замер риска глобального перехода на 02:00** (следствие решения владельца): для каждого юзера
      посчитать `get_current_streak` на календарной полуночи и на учебном дне и выписать расхождения;
      отдельно — сколько активностей в проде попадает в окно 00:00–02:00 локального времени. Если
      расхождение затрагивает > 1 юзера, зафиксировать числа в измерениях **до** правки, чтобы
      «серия изменилась» не выглядело регрессией на приёмке
- [x] перечитать на HEAD тела 16 находок объёма и выписать актуальные `path:line` (строки реестра
      сняты на `0b1f8b7f`)

### Task 2: `DP-001` (фундамент) — единый учебный день во всех окнах активности

**Files:**
- Modify: `app/utils/time_utils.py`, `app/telegram/queries.py`, `app/achievements/streak_service.py`,
  `app/telegram/scheduler.py` (пятый ходок по дням — считал `check_date` от UTC-календаря)
- Create: `tests/daily_plan/test_study_day_bounds.py`

- [x] написать падающие тесты **до** правки: активность в 00:30 локального времени принадлежит
      **предыдущему** учебному дню одновременно в `get_user_local_date` (уже так) и в
      `has_activity_today`/`find_missed_date` (сейчас — нет); юзер, занимавшийся в 01:00, не должен
      объявляться пропустившим предыдущий день
- [x] ввести **один** канонический хелпер окна учебного дня в `app/utils/time_utils.py` —
      `study_day_bounds_utc(tz_name, offset_days=0) -> (start_utc, end_utc)`, анкер
      `LEARNING_DAY_START_HOUR`; он обязан согласовываться с уже существующими
      `get_user_local_day_bounds` и `day_to_naive_utc` (те же сутки, другой формат возврата),
      а не становиться четвёртым независимым вариантом
- [x] `_user_day_boundaries` в `app/telegram/queries.py:22` сделать **тонкой обёрткой** над новым
      хелпером: имя и сигнатура сохраняются (20 call-sites не трогаются), меняется только базис.
      Политику фолбэка (`UnknownTimeZoneError` → `DEFAULT_TZ`) сохранить дословно и покрыть тестом —
      расхождение `pytz`/`ZoneInfo` (`DP-082`) в этот заход **не чинить**
- [x] в `process_streak_on_activity` (`app/achievements/streak_service.py:282`) свести все три базиса
      к `User.timezone`: `user_today`, `real_activity` и `find_missed_date`/`get_streak_status`/
      `auto_heal_streak_on_activity` должны получать **одну** зону и **одну** границу дня.
      Клиентский `?tz=` (`app/api/daily_plan.py:278`) перестаёт влиять на выбор чинимой даты —
      оставить его только там, где он влияет на отображение
- [x] переписать комментарий `streak_service.py:310-313`: в нём **ложное** утверждение «Activity
      window is keyed on User.timezone (same basis as user_today)» — зона общая, база суток разная.
      Комментарий обязан описывать новое, фактическое состояние
- [x] прогнать телеграм-тесты отдельно (`pytest tests/telegram -q`): у планировщика четыре гейта
      «занимался ли сегодня» переезжают на новый базис — это ожидаемое изменение поведения,
      но оно должно быть зелёным и осознанным, а не случайным
- [x] записать замер «после» по расхождению `streak` из Task 1 в файл измерений

### Task 3: `DP-001` (второй механизм) — порядок починок серии

**Files:**
- Modify: `app/achievements/streak_service.py`
- Modify: `tests/achievements/` (тест на порядок починок; файл выбрать по фактической раскладке)

- [x] тест «до»: дырка на offset 1–3, у юзера активен щит **и** доступен бесплатный авто-хилер →
      сейчас списывается щит; после фикса щит остаётся, дырка закрывается бесплатно
      (`tests/achievements/test_streak_repair_order.py::TestFreeHealerGoesFirst` — 3 теста,
      краснели до правки, зелёные после)
- [x] переставить щит **за** `auto_heal_streak_on_activity` (`:404-410`) либо проверять
      `find_auto_heal_date` перед списанием: сейчас щит стоит первым (`:363-391`, гейт — только
      `real_activity`), пишет `StreakEvent('shield_repair')`, а `has_repair_for_date` считает его
      починкой, из-за чего авто-хилер больше не видит эту дату
      → выбран перенос блока: порядок стал «бесплатная починка за план → авто-хилер → щит»,
      комментарий у блока объясняет, почему щит последний
- [x] проверить, что `apply_shield_repair` по-прежнему срабатывает на offset 4–7, куда авто-хилер
      (`max_days=3`) не дотягивается — щит не должен стать недостижимым
      (`TestShieldStillReachable` — offset 5, offset 7 и «дырки нет»; все три зелёные и до, и после)
- [x] замер «после»: доля щитов, списанных на днях с активностью, по копии прода (реестр: 6 из 11)
      → «до» воспроизведено дословно (6/11 у 3 юзеров); из 11 списаний **10** под новым порядком
      не состоялись бы, 1 (user 1, 2026-06-26, следующая сессия через 28 дней) — целевое
      использование щита. Секция (е) в `docs/audit/2026-08-29-remediation-measurements.md`,
      скрипт `scripts/audit/2026-08-29_measurements/09_dp001_shield_repair_order.sql`

### Task 4: `DP-033` — гейт доступа к книге в required-слоте чтения

**Files:**
- Modify: `app/daily_plan/items/reading.py`, `app/daily_plan/snapshot.py`
- Create: `tests/daily_plan/test_reading_slot_access_gate.py`

- [x] тесты «до», три состояния: `licensed`-книга с истёкшим `expiration_date`; снятый у юзера
      модуль `books`; `is_published=False` — во всех трёх сейчас в `required` попадает слот чтения,
      ведущий в 403/404, и `day_secured` недостижим весь день
      (`tests/daily_plan/test_reading_slot_access_gate.py::TestBuilderGate` — 3 теста краснели
      до правки; плюс 2 стража на нерегрессию: доступная public-domain книга слот даёт,
      админ по-прежнему читает свой черновик)
- [x] `_book_is_actionable_for_reading` (`app/daily_plan/items/reading.py:50`) дополнить
      `can_user_access_book(user, book)` и проверкой черновика — тем же гейтом, что уже стоит на
      роутах ридера (`app/books/access.py`). Следствие бесплатно: `reading_preference_needs_setup`
      начинает возвращать True → план показывает карточку `setup_book` вместо мёртвого слота
      → вынесено в `book_access_ok_for_reading(user_id, book, db)`, чтобы снапшот звал тот же гейт
- [x] **отдельно — заморозка снапшота.** Гейт в билдере закрывает только новый день; книга, к
      которой доступ пропал **в течение** дня, остаётся в замороженном `required`. В
      `overlay_completion` (`app/daily_plan/snapshot.py`) добавить самопочинку: required-слот
      чтения, чья книга стала недоступна, **исключается** из required с warning-логом.
      Пометить его `completed=True` нельзя — это фальшивый кредит и ложный perfect-day
      → `_reading_book_unreachable`; исчезнувшая строка книги считается недостижимой так же,
      а ошибка проверки оставляет пункт (транзиентный сбой не вправе молча резать required)
- [x] закрыть подслучай, который реестр отдельно называет тянущим на P0: у юзера без модуля `books`
      и при пустом каталоге public-domain **каждая** книга даёт 403, переписать preference нечем.
      После правки план в этом состоянии обязан отдавать закрываемый день (required без чтения),
      а не незакрываемый (`TestNoAccessibleBooksAtAll` — краснел до правки)
- [x] тест на самопочинку: слот в снапшоте + доступ отозван в середине дня → `day_secured`
      достижим по остальным required (`TestSnapshotSelfHeal` — 5 тестов, 4 краснели до правки)
- [x] замер «после»: у юзера из замера (а) Task 1 слот чтения больше не появляется в required
      → `user_id=39`: билдер отдаёт `None`, `overlay_completion` выбрасывает слот из **0 из 47**
      замороженных дней v3, остальные 5 (v2) пересобираются под гейтом. Скрипт
      `scripts/audit/2026-08-29_measurements/10_after_dp033_reading_gate.py`, секция (а) измерений

### Task 5: `DP-034` — theory-only grammar платит полные 18 XP

**Files:**
- Modify: `app/curriculum/routes/lessons.py`
- Create/Modify: тест в `tests/curriculum/` на XP theory-only урока

- [x] тест «до»: завершение theory-only grammar-урока (нет секции `exercises`) начисляет
      `linear_curriculum_grammar` = **9**, ожидается **18**
      → `tests/curriculum/test_theory_only_xp_scaling.py`, 3 из 8 тестов краснели ровно так:
      `assert 9 >= 18` и `assert 0.0 is None` на аргументе скейлера
- [x] фикс в `app/curriculum/routes/lessons.py`: там, где `score` **сознательно вычищен**
      антифродом (`_is_grammar_theory_only`, `_SCORE_STRIP_ONLY_TYPES`), в
      `maybe_award_curriculum_xp` передавать `score=None`, а не `progress.score`. `None` по
      контракту `apply_score_to_base` (`app/achievements/xp_service.py:297`) даёт базовую сумму;
      `0.0` — половину. Якорь: `lessons.py:388`
      → флаг `_is_score_strip_type` поднят выше XP-блока (у него теперь два потребителя, а не
      один), XP-вызовы получают `_xp_score = None if _is_score_strip_type else progress.score`
- [x] проверить три соседних call-site с тем же паттерном — `lessons.py:393`, `:415`,
      `app/curriculum/service.py:232`: у каждого выяснить, реальный ли там грейд или тот же
      дефолт колонки `0.0`, и починить те, где дефолт
      → (1) `maybe_award_listening_xp` — **тот же дефект** (`listening_immersion_quiz` получал
      `0.0`), починен; (2) `process_lesson_completion` — дефекта нет, уже гейтился тем же флагом;
      (3) `complete_lesson` — дефекта нет: его XP-путь `award_curriculum_lesson_xp_idempotent`
      не принимает `score` вовсе (плоские 30 XP), прод-вызывателей у функции нет. Оба «нет»
      закреплены тестами в классе `TestNeighbouringScoreCallSites`
- [x] тест-страж на **не**регрессию скейлера: exercise-backed grammar с реальным score
      по-прежнему масштабируется (не «всё стало базовым»)
      → `test_exercise_backed_grammar_still_scales_by_real_score` (score 60.0 доезжает как 60.0)
      + `test_graded_type_still_reaches_process_lesson_completion`
- [x] исторические 20 начислений по 9 XP **не трогаем** (решение владельца: только вперёд) —
      записать это в реестр в статус находки, чтобы следующий читатель не искал backfill
      → секция «Статус ремедиации» в теле `DP-034` (`docs/audit/2026-08-26-daily-plan-audit.md`)
      + пары «до/после» в `docs/audit/2026-08-29-remediation-measurements.md`, секция (б)

### Task 6: `DP-051` → `DP-035` — perfect-day получает подметальщика

**Files:**
- Modify: `app/achievements/xp_service.py`, `app/api/daily_plan.py`, `app/words/routes.py`
- Modify: `tests/daily_plan/test_perfect_day_unified.py`

- [x] **сначала `DP-051`** (предусловие, не «заодно»): `award_perfect_day_xp_idempotent`
      (`app/achievements/xp_service.py:212`) — единственный XP-хелпер с голым check-then-insert.
      Обернуть вставку в `begin_nested()` + `except IntegrityError` по образцу `grant_achievement`;
      проверить, есть ли уникальность на `(user_id, event_type, event_date)` в `StreakEvent`, и если
      нет — решить, добавлять ли partial unique index миграцией (тогда миграция входит в задачу).
      Без этого шага фикс `DP-035` добавляет два новых конкурирующих вызывателя незащищённому хелперу
- [x] тест «до» для `DP-035`: день закрыт последним действием через standalone grammar-lab
      (`grammar_lab_service.submit_answer`) или book-SRS — `day_secured=True`, `xp_perfect_day` нет
      ни в этом запросе, ни в следующем `GET /api/daily-status`
- [x] добавить вызов `maybe_award_linear_perfect_day` в **оба** писателя `secured_at`, рядом с уже
      живущими там подметальщиками (`record_plan_completion`, `emit_daily_plan_completed`,
      `check_immersion_achievement`): `app/api/daily_plan.py:332-370` и
      `app/words/routes.py:1046-1065`. Идемпотентность обеспечивает сам хелпер — специальных
      флагов не заводить
- [x] тест: два подряд `GET /api/daily-status` на закрытом дне дают ровно одно начисление 25 XP
- [x] тест: paused-день и день с пустым `required` у **не**-graduated юзера бонуса не получают
      (правило допуска уже зашито в `maybe_award_linear_perfect_day:544-553` — не сломать его)
- [x] замер «после»: новые закрытые дни в проде получают `xp_perfect_day`; исторические 30 дней
      остаются без бонуса сознательно

### Task 7: Кластер границы суток — писатели дат

**Files:**
- Modify: `app/daily_plan/snapshot.py`, `app/words/routes.py`
- Modify: `tests/daily_plan/test_snapshot_v2.py`

- [ ] `DP-003` — `_render_unified_dashboard` (`app/words/routes.py:1056`) пишет
      `write_secured_at(user_id, datetime.now(tz).date())`, то есть по **календарной** дате:
      закрытие дня между 00:00 и 02:00 уезжает в завтра. Заменить на `get_user_local_date(user_id, db)` —
      тот же источник, что у остальных дедуп-ключей. Тест: закрытие в 00:30 пишет `secured_at`
      на текущий учебный день
- [ ] `DP-002`/`DP-009` — `_local_date_start_naive_utc` (`app/daily_plan/snapshot.py:196`) строит
      окно от `time.min`, тогда как дата приходит уже учебная: перевести анкер на
      `LEARNING_DAY_START_HOUR` (переиспользовать хелпер из Task 2, не писать четвёртую копию)
- [ ] `DP-027` — докстринги `app/daily_plan/snapshot.py:4-5` описывают границу «полночь»;
      привести к фактическому поведению
- [ ] тест на roll-over снапшота через границу 02:00: перенос вчерашнего снапшота не должен
      срабатывать дважды и не должен пропускать день

### Task 8: Кластер границы суток — читатели дат

**Files:**
- Modify: `app/words/routes.py`, `app/api/daily_plan.py`, `app/daily_plan/next_step.py`

- [ ] `DP-008` — «XP сегодня» на дашборде (`app/words/routes.py:1108-1109`) считается по
      календарному дню вопреки контракту `get_today_xp`; перевести на учебный день
- [ ] `DP-010` — `add_study_minutes(when=...)` (`app/api/daily_plan.py:196-216`) получает учебный
      день, а сравнивается с иными базисами; свести
- [ ] `DP-012` — дашбордная карточка гонки (`app/words/routes.py:715-721`) считает дату кохорты
      иначе, чем `/api/daily-race`: юзер видит на дашборде и в API разные гонки. Свести на общий
      источник даты
- [ ] `DP-026` — `goal_progress.daily_words` считается от 02:00, `weekly_lessons` — от иной границы
      (`app/api/daily_plan.py:139-152`)
- [ ] `DP-013` — контракт докстринга «`tz` must match the timezone used to derive `target_date`»
      нарушен на call-site (`app/api/daily_plan.py:368`); после Task 2 это должно стать
      автоматически верным — **проверить и зафиксировать тестом**, а не считать закрытым по факту
- [ ] `DP-022` — две несогласованные реализации «вчера не закрыто» (pytz-ветка в
      `app/api/daily_plan.py:117` против ZoneInfo в `app/daily_plan/next_step.py`): оставить одну
- [ ] `DP-011` — **решение, а не автоматический фикс.** Идемпотентные ключи `(user, дата, source)`
      пересчитываются из текущего `User.timezone`, поэтому смена зоны переигрывает прошлое. Полный
      фикс требует хранить дату на момент записи и выходит за рамки фазы. Выбрать: (а) закрыть
      малым средством, если оно есть; (б) явно оставить открытым и записать в реестр причину.
      Не оставлять молча
- [ ] тест-страж на общий базис: один сценарий, который дёргает дашборд, `/api/daily-status` и
      `/api/daily-plan` для юзера в 00:30 локального времени и требует **одинаковой** «сегодняшней»
      даты во всех трёх

### Task 9: Документация

**Files:**
- Modify: `CLAUDE.md`, `docs/audit/2026-08-26-daily-plan-audit.md`

- [ ] внести в `CLAUDE.md` семь документарных расхождений `CM-1…CM-7` по формулировкам, уже
      предложенным в реестре (`tomorrow_preview`, порядок `get_next_best_step`, перечни
      `build_optional`/`_OPTIONAL_PRIORITY`/`_SCORE_BASED_LESSON_TYPES`, значения
      `get_adaptive_limit_reason`, недостающие ключи `LINEAR_XP`, осиротевший `xp_curriculum_lesson`,
      паттерн `success` в 200-телах)
- [ ] внести `CM-8…CM-10`: «mission/linear-chain **отключены**, а не удалены» — 2 615 строк
      физически на месте и удерживаются тестами; и `CM-11` — константа называется
      `DAILY_LESSON_SKIP_QUOTA`, а не `DAILY_SKIP_QUOTA`
- [ ] обновить раздел Daily Plan под фактически внесённые изменения: единый базис 02:00 во всех
      окнах активности, гейт доступа в required-слоте чтения, perfect-day как подметальщик на
      обоих писателях `secured_at`
- [ ] в реестре аудита завести секцию «Статус ремедиации (фаза 1)»: по каждой из 16 находок —
      ✅/🟡/отложено, коммит и тест-страж; для `DP-034`/`DP-035` явно записать «история не
      добирается — решение владельца»

### Task 10: Приёмка

- [ ] `pytest tests/daily_plan -q` и `pytest -m smoke -q` — **0 падений**
- [ ] полный `pytest -q` — список FAILED **не длиннее** baseline Task 1; сверка по именам, а не по числу
- [ ] `ruff check .` ≤ baseline Task 1
- [ ] у каждой из 16 находок есть тест-страж, краснеющий при откате фикса — проверить выборочным
      откатом минимум по одному тесту на каждый P1
- [ ] `docs/audit/2026-08-29-remediation-measurements.md` содержит пары «до/после» по трём
      прод-замерам Task 1 и по расхождению `streak` из глобального перехода на 02:00
- [ ] `git log --oneline` фазы: коммиты по находкам, ни одного упоминания AI/Claude

## Post-Completion (вручную, вне чекбоксов)

- **Открыто после фазы 1: 111 находок.** Следующие связные кластеры, в порядке отдачи:
  1. **Контракт API** — `DP-079`/`DP-081`/`DP-083`/`DP-102` (не-dict тело → 500 на 6 POST из 8),
     `DP-084`/`DP-085` (405 и werkzeug-400 отдают HTML под `/api/`, аноним получает 302 вместо 401).
  2. **Auth-гейты** — `DP-095` (`@module_required('words')` только на `/dashboard`, 18 роутов зоны
     отдают тот же план без модуля), `DP-096` (тело эндпоинта исполняется внутри `except` JWT-ветки),
     `DP-098` (JWT-ветка выдаёт сессионную куку).
  3. **Заморозка снапшота** — `DP-005` (удалённый админом урок делает день незакрываемым),
     `DP-041`, `DP-044`: тот же класс, что закрытый в Task 4 `DP-033`, и правильнее чинить одним
     механизмом самопочинки.
  4. **Optional-очередь** — `DP-036` (шаблон рендерит 5 из 12–15, «Показать ещё» = `reload()`),
     `DP-038`, `DP-039`.
- **Мёртвый код — 2 928 строк в зоне (25.8%)**, отдельная задача и отдельное подтверждение
  владельца. Порядок из реестра: связный кластер 1 784 строки (`get_linear_plan` → `chain.py` →
  5 slot-модулей), затем `assembler.py` + `repair_pressure.py` (975), затем потребительская тень
  (240). `DP-120` из списка удаления **исключена** — это починка (восстановить вызов
  `check_curriculum_milestones`), а не удаление. Подходит агент `dead-code-cleaner`.
- **3 PLAUSIBLE** требуют живого стенда: пауза против `/next-slot`, гонка двойной починки серии,
  `REMEMBER_COOKIE_SAMESITE` в браузере.
- **Долг самого аудита** — 7 позиций живого кода, объявленных покрытыми без разбора
  (`reading_slot.py` 220 строк, `linear/context.py`, `items/setup.py`, телеграм-рендер payload):
  либо доразобрать, либо оставить с явной пометкой.