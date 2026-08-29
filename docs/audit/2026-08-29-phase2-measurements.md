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

**После правки:** _(заполняется в Task 2)_

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

**После правки:** _(заполняется в Task 2)_

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

**После правки:** _(заполняется в Task 2)_
