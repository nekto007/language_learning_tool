-- DP-001 (второй механизм) — на что уходили щиты.
-- READ-ONLY. Запуск:
--   docker exec -i language_learning_tool_db psql -U igor_adm -d learn_db_prod -f - < 09_dp001_shield_repair_order.sql
--
-- Считаем каждое историческое `shield_repair` и спрашиваем, был ли этот щит нужен:
--   (1) на дате щита была реальная активность (щит потрачен на день, который отучили);
--   (2) дату закрыл бы бесплатный авто-хилер (`find_auto_heal_date`, окно offset 1-3,
--       якорь: активность/починка на будущей стороне ИЛИ активность на прошлой).
-- Учебный день — анкер 02:00 локального времени юзера (LEARNING_DAY_START_HOUR).

\pset pager off

CREATE TEMP VIEW acts AS
  SELECT user_id, last_activity AS ts FROM lesson_progress WHERE last_activity IS NOT NULL
  UNION ALL SELECT user_id, last_reviewed FROM user_grammar_exercises WHERE last_reviewed IS NOT NULL
  UNION ALL SELECT uw.user_id, ucd.last_reviewed FROM user_card_directions ucd
            JOIN user_words uw ON uw.id = ucd.user_word_id WHERE ucd.last_reviewed IS NOT NULL
  UNION ALL SELECT user_id, updated_at FROM user_chapter_progress WHERE updated_at IS NOT NULL
  UNION ALL SELECT user_id, (completed_at AT TIME ZONE 'UTC') FROM user_lesson_progress WHERE completed_at IS NOT NULL
  UNION ALL SELECT user_id, start_time FROM study_sessions WHERE start_time IS NOT NULL
  UNION ALL SELECT user_id, created_at FROM streak_events WHERE event_type LIKE 'xp_linear%' AND created_at IS NOT NULL
  UNION ALL SELECT user_id, created_at FROM listening_attempts WHERE created_at IS NOT NULL;

-- Учебные дни с реальной активностью.
CREATE TEMP VIEW stu_days AS
  SELECT DISTINCT a.user_id,
         ((a.ts AT TIME ZONE 'UTC' AT TIME ZONE COALESCE(u.timezone,'Europe/Moscow')) - interval '2 hour')::date AS day
  FROM acts a JOIN users u ON u.id = a.user_id;

-- Любые починки (тем же списком, что `has_repair_for_date`).
CREATE TEMP VIEW repairs AS
  SELECT DISTINCT user_id, event_date AS day FROM streak_events
  WHERE event_type IN ('free_repair','spent_repair','plan_pause','shield_repair');

CREATE TEMP VIEW shields AS
  SELECT user_id, event_date AS day, created_at FROM streak_events WHERE event_type = 'shield_repair';

\echo '=== 1. Сколько щитов всего и у скольких юзеров ==='
SELECT count(*) AS shields_spent, count(DISTINCT user_id) AS users FROM shields;

\echo '=== 2. Щит на дне, который юзер отучил (щит списан впустую) ==='
SELECT count(*) FILTER (WHERE has_activity) AS on_active_day,
       count(*)                              AS total
FROM (SELECT s.user_id, s.day,
             EXISTS (SELECT 1 FROM stu_days d WHERE d.user_id=s.user_id AND d.day=s.day) AS has_activity
      FROM shields s) x;

\echo '=== 3. Покрыл бы бесплатный авто-хилер (offset 1-3 от следующего активного дня) ==='
-- Реконструкция `find_auto_heal_date`: дырка достижима, если до неё <= 3 учебных дней от
-- ближайшего последующего активного дня И якорь есть с любой стороны.
SELECT count(*) FILTER (WHERE free_reachable) AS auto_healable,
       count(*)                                AS total
FROM (
  SELECT s.user_id, s.day,
         (
           -- ближайший активный день ПОСЛЕ дырки не дальше 3 суток => дырка в окне max_days=3
           EXISTS (SELECT 1 FROM stu_days d
                    WHERE d.user_id=s.user_id AND d.day > s.day AND d.day <= s.day + 3)
           AND (
             -- будущая сторона: активность или починка на day+1
             EXISTS (SELECT 1 FROM stu_days d WHERE d.user_id=s.user_id AND d.day = s.day + 1)
             OR EXISTS (SELECT 1 FROM repairs r WHERE r.user_id=s.user_id AND r.day = s.day + 1)
             -- прошлая сторона: реальная активность на day-1
             OR EXISTS (SELECT 1 FROM stu_days d WHERE d.user_id=s.user_id AND d.day = s.day - 1)
           )
         ) AS free_reachable
  FROM shields s) x;

\echo '=== 4. Построчно: каждый щит и вердикт ==='
SELECT s.user_id, s.day,
       EXISTS (SELECT 1 FROM stu_days d WHERE d.user_id=s.user_id AND d.day=s.day) AS day_had_activity,
       EXISTS (SELECT 1 FROM stu_days d WHERE d.user_id=s.user_id AND d.day=s.day-1) AS prev_active,
       EXISTS (SELECT 1 FROM stu_days d WHERE d.user_id=s.user_id AND d.day=s.day+1) AS next_active,
       (SELECT min(d.day - s.day) FROM stu_days d WHERE d.user_id=s.user_id AND d.day > s.day) AS days_to_next_activity
FROM shields s
ORDER BY s.user_id, s.day;
