# Замеры «до/после» — ремедиация «План дня», фаза 2

**Источник данных:** локальная копия боевой БД `learn_db_prod` в контейнере
`language_learning_tool_db` (45 пользователей, 1915 строк `daily_plan_log`,
72 закрытых дня). Все запросы **read-only** — ни одного `UPDATE`/`INSERT`.

**Дата замеров «до»:** 2026-08-29, HEAD `b57b43e5` (то, что развёрнуто на проде).

Замеры «после» дописываются в конце каждого кластера по мере закрытия задач.

---

## Замер (а) — `DP-087`: XP за разбор ошибок без разобранных ошибок

**Что меряем.** Сколько `StreakEvent` источника `linear_error_review` (единственный
писатель — `POST /api/daily-plan/error-review/complete`) не имеют ни одного
`QuizErrorLog`, переведённого в resolved в тот же день. Такое событие = +10 XP и,
у graduated/заблокированного пользователя, закрытие дня без работы.

```sql
SELECT se.user_id, se.event_date,
       (SELECT count(*) FROM quiz_error_log q
         WHERE q.user_id = se.user_id
           AND q.resolved_at IS NOT NULL
           AND q.resolved_at::date = se.event_date) AS resolved_same_day
FROM streak_events se
WHERE se.event_type='xp_linear' AND se.details->>'source'='linear_error_review';
```

| user_id | event_date | разобрано ошибок в тот день |
|---|---|---|
| 1 | 2026-05-08 | **0** |
| 39 | 2026-06-01 | 7 |
| 41 | 2026-06-02 | 15 |
| 41 | 2026-07-01 | 14 |

**Число «до»: 1 из 4 начислений (25%) выдано за нулевую работу.**

Оговорка о точности: событий всего 4, поэтому доля неустойчива. Утверждение,
которое замер подтверждает, — не «четверть начислений фиктивна», а «путь,
запрещаемый правкой, в проде реально пройден как минимум один раз».

**После правки:** `POST /api/daily-plan/error-review/complete` требует непустой
`error_ids`, чьи строки принадлежат вызывающему И имеют `resolved_at` внутри текущего
**учебного** дня (окно — `study_day_bounds_utc`, тот же анкер 02:00, что у остальных
дневных гейтов). Пустое тело, пустой список, чужой id и «свой, но разобранный на
прошлой неделе» → `400`, без `StreakEvent` и без XP.

Правка **вперёд-действующая**: исторические строки не пересчитываются (политика «XP
только вперёд», та же, что в `DP-034`/`DP-035`). Проверка «после» — прогон того же
предиката против нового обработчика:

| путь | до | после |
|---|---|---|
| пустой POST (`{}` / `{'error_ids': []}`) | `200`, +10 XP, `StreakEvent` | `400 no_errors_submitted`, 0 XP |
| чужой `error_id` | `200`, +10 XP | `400 no_errors_resolved`, чужая строка не тронута |
| свой, разобранный неделю назад | `200`, +10 XP | `400 no_errors_resolved` |
| свой неразобранный (настоящая работа) | `200`, +10 XP | `200`, +10 XP (без изменений) |
| повторная отправка тех же id в тот же день | `200` | `200` (ретрай клиента не ломается) |

Из 4 исторических начислений новый гейт отверг бы **1** — ровно ту строку
(user 1, 2026-05-08), у которой в тот день нет ни одной разобранной ошибки; три
остальных (7/15/14 разобранных) проходят. Тест-страж —
`tests/daily_plan/test_day_close_integrity.py::TestErrorReviewRequiresProofOfWork`
(6 тестов: 4 запрещающих + 2 регресс-стража на живой путь).

---

## Замер (б) — `DP-042`: required deck-quiz закрыт без квиза

**Что меряем.** Дни, чей замороженный `plan_json` содержит слот `srs:deck_quiz`;
для каждого — закрыт ли слот (есть `StreakEvent` источника `linear_srs_global`)
и было ли в тот день хоть одна квиз-сессия (`study_sessions.session_type IN
('quiz','quiz_word_set')` — те же `QUIZ_SESSION_TYPES`, которых требует
`_deck_quiz_run_is_real`).

```sql
WITH deck AS (
  SELECT user_id, plan_date, secured_at FROM daily_plan_log
  WHERE plan_json::text LIKE '%srs:deck_quiz%'
)
SELECT d.user_id, d.plan_date, (d.secured_at IS NOT NULL) AS secured,
  EXISTS (SELECT 1 FROM streak_events se
          WHERE se.user_id=d.user_id AND se.event_type='xp_linear'
            AND se.event_date=d.plan_date
            AND se.details->>'source'='linear_srs_global') AS srs_slot_closed,
  (SELECT count(*) FROM study_sessions ss
     WHERE ss.user_id=d.user_id AND ss.session_type IN ('quiz','quiz_word_set')
       AND ss.start_time::date = d.plan_date) AS quiz_sessions_that_day
FROM deck d;
```

| user_id | plan_date | день закрыт | слот закрыт | квиз-сессий в тот день |
|---|---|---|---|---|
| 1 | 2026-06-18 | нет | нет | 0 |
| 8 | 2026-06-23 | нет | нет | 0 |
| 21 | 2026-06-24 | нет | да | 1 |
| 21 | 2026-07-08 | нет | нет | 3 |
| 8 | **2026-07-08** | **да** | **да** | **0** |

**Число «до»: 1 из 2 закрытий слота (50%) получено без квиза — и это ровно тот
единственный день, который был закрыт (`secured_at IS NOT NULL`).**

Разбор этого дня добавляет к находке деталь, которой нет в реестре: у user 8 за
2026-07-08 в `study_sessions` **нет вообще ни одной сессии любого типа**, а
событие `{"xp": 8, "source": "linear_srs_global"}` существует. То есть ключ
записал не «обычная SRS-сессия», а корректирующее начисление fallback-ветки
`is_srs_slot_completed_today` (её вызывает читатель слота `srs:global`). Строгий
гейт deck-quiz читает результат этой ветки постфактум и потому не защищён от неё
`allow_fallback=False`. Правка обязана дать deck-quiz **собственный** ключ, а не
ужесточать fallback.

**После правки:** у слота появился **собственный** сигнал —
`DailyPlanEvent(event_type='deck_quiz_completed', plan_date=<учебный день>)`,
который пишет единственный вызыватель `complete_quiz` (`app/study/game_routes.py`)
за уже существующим гейтом `_deck_quiz_run_is_real` (verified-сессия нужного типа
+ `words_studied > 0`). Оба читателя слота переведены на него:
`_build_deck_quiz_plan_item` (`app/daily_plan/items/srs.py`) и `_is_item_completed`
(`app/daily_plan/snapshot.py`); аргумент `allow_fallback=False` в этих двух
call-site'ах больше не нужен (сама `is_srs_slot_completed_today` не тронута — её
читает слот `srs:global`).

Маркер пишется **до** попытки начисления и независимо от неё: `linear_srs_global`
идемпотентен per day, поэтому у пользователя, уже сдавшего `/study`-сессию, награда
вернула бы `None` — и сигнал, выведенный из награды, пропал бы ровно у того, кто
квиз реально прошёл.

Тот же запрос с добавленной колонкой нового гейта:

| user_id | plan_date | день закрыт | старый гейт | новый гейт | квиз-сессий |
|---|---|---|---|---|---|
| 1 | 2026-06-18 | нет | нет | нет | 0 |
| 8 | 2026-06-23 | нет | нет | нет | 0 |
| 21 | 2026-06-24 | нет | **да** | нет | 1 |
| 21 | 2026-07-08 | нет | нет | нет | 3 |
| 8 | **2026-07-08** | **да** | **да** | **нет** | **0** |

**Число «после»: 0 из 5 дней закрывается слотом без квиза** (было 2 закрытия слота,
из них 1 без единой квиз-сессии — тот самый закрытый день).

Оговорка, важная для деплоя: строк `deck_quiz_completed` в БД **0** — маркеры
начинаются с момента выката. Поэтому у user 21 за 2026-06-24 новый гейт показывает
«не закрыт», хотя квиз-сессия в тот день была: гейт читается только для **текущего**
дня, так что цена ретроспективы — квиз, пройденный в день выката до перезапуска,
придётся пройти заново. Бэкфилл не делается по той же причине, что и в фазе 1:
`study_sessions` не различает прогон плана и обычный `/quiz/deck/<id>`.

Тест-страж — `TestDeckQuizHasOwnCompletionSignal` (4 теста: `linear_srs_global` слот
не закрывает ни в снапшоте, ни в билдере; собственный сигнал закрывает; запись
идемпотентна per day).

---

## Замер (в) — `DP-050`: XP за grammar-урок на проваленной попытке

**Что меряем.** Начисления `linear_curriculum_grammar`, пришедшиеся на попытку с
`passed = false`.

```sql
-- начисления
SELECT user_id, event_date, (details->>'xp')::int FROM streak_events
WHERE event_type='xp_linear' AND details->>'source'='linear_curriculum_grammar';
-- попытки по grammar-урокам
SELECT count(*) FROM lesson_attempts la JOIN lessons l ON l.id=la.lesson_id
WHERE l.type='grammar';
```

Результат: **20 начислений, 0 строк `lesson_attempts` по урокам `type='grammar'`.**
Все 19 строк `lesson_progress` по grammar-урокам имеют
`score = best_score = last_score = 0` при `status='completed'` — это theory-only
уроки, прошедшие мимо грейдера (тот самый профиль `DP-034`, чей XP-скейлер
починен в фазе 1; в таблице видно 18 начислений по 9 XP и два graded — 19 и 10).

**Число «до»: 0 подтверждённых случаев в grammar-ветке.**

Это результат, а не пропуск: дефект в коде воспроизводится (см. baseline,
`grammar_quiz_lessons.py:307` + липкий статус в `progress_service.py:283-286`),
но продакшн-инстансов у него пока нет — до сих пор ни один graded grammar-урок не
пересдавался с провалом. Приёмка `DP-050` опирается на тест-страж, а не на
изменение этого числа.

**Контекст (вне объёма правки).** Тот же липкий-статус паттерн в соседних типах
уроков уже отработал в данных: 47 попыток с `passed=false` лежат на
`lesson_progress.status='completed'` — dictation 43, final_test 3, translation 1.
Гейты тех обработчиков в объём фазы 2 не входят; строка приведена, чтобы при
приёмке было видно, что механизм не гипотетический.

```sql
SELECT l.type,
       count(*) FILTER (WHERE la.passed IS FALSE AND lp.status='completed')
FROM lesson_attempts la JOIN lessons l ON l.id=la.lesson_id
LEFT JOIN lesson_progress lp ON lp.user_id=la.user_id AND lp.lesson_id=la.lesson_id
GROUP BY 1;
```

**После правки:** гейт XP переведён со `status` на результат **этой** попытки —
хелпер `_submission_passed(result)` (`score >= PASSING_SCORE_DEFAULT`) в
`app/curriculum/routes/grammar_quiz_lessons.py`. Правка закрывает **обе** копии
обработчика grammar-урока: `render_grammar_lesson` (диспетчер `/learn/<id>/`) и роут
`grammar_lesson` (`/curriculum/lesson/<id>/grammar`) — разошедшиеся близнецы того же
рода, что `CNT-001`, и правка одной оставила бы дыру во второй. Сведение двух
обработчиков в один в объём фазы 2 не входит (записано как хвост).

Идемпотентность per `(user, date, source)` не менялась: сдача после провала в тот же
день не доплатит, если XP уже выдан, — ожидаемое поведение.

Число «до» = 0, поэтому и «после» = 0: правка запрещает путь, по которому в проде ещё
не ходили. Приёмка — тест-страж `TestGrammarRetakeXpGate` (4 теста, по каждому из двух
URL: проваленная пересдача завершённого урока не платит, сдача — платит). Все четыре
краснеют при откате гейта на `progress.status == 'completed'`.
