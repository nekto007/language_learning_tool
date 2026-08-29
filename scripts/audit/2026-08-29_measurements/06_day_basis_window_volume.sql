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

-- 1. Volume of activity landing in the local 00:00-02:00 window (the only window that moves)
SELECT count(*) AS total_activity_rows,
       count(*) FILTER (WHERE EXTRACT(hour FROM (a.ts AT TIME ZONE 'UTC' AT TIME ZONE COALESCE(u.timezone,'Europe/Moscow'))) < 2) AS rows_in_00_02_local,
       count(DISTINCT a.user_id) FILTER (WHERE EXTRACT(hour FROM (a.ts AT TIME ZONE 'UTC' AT TIME ZONE COALESCE(u.timezone,'Europe/Moscow'))) < 2) AS users_touched
FROM acts a JOIN users u ON u.id = a.user_id;

-- 2. Per-user rows in the moving window
SELECT a.user_id, COALESCE(u.timezone,'Europe/Moscow') AS tz, count(*) AS rows_00_02_local
FROM acts a JOIN users u ON u.id=a.user_id
WHERE EXTRACT(hour FROM (a.ts AT TIME ZONE 'UTC' AT TIME ZONE COALESCE(u.timezone,'Europe/Moscow'))) < 2
GROUP BY 1,2 ORDER BY 3 DESC;

-- 3. Days that exist under one basis but not the other (per user): the raw material of a streak shift
WITH d AS (
  SELECT a.user_id,
         (a.ts AT TIME ZONE 'UTC' AT TIME ZONE COALESCE(u.timezone,'Europe/Moscow'))::date AS cal_day,
         ((a.ts AT TIME ZONE 'UTC' AT TIME ZONE COALESCE(u.timezone,'Europe/Moscow')) - interval '2 hour')::date AS study_day
  FROM acts a JOIN users u ON u.id=a.user_id
),
cal AS (SELECT DISTINCT user_id, cal_day AS day FROM d),
stu AS (SELECT DISTINCT user_id, study_day AS day FROM d)
SELECT COALESCE(c.user_id,s.user_id) AS user_id,
       count(*) FILTER (WHERE s.day IS NULL) AS days_only_calendar,
       count(*) FILTER (WHERE c.day IS NULL) AS days_only_study
FROM cal c FULL OUTER JOIN stu s ON s.user_id=c.user_id AND s.day=c.day
GROUP BY 1 HAVING count(*) FILTER (WHERE s.day IS NULL) > 0 OR count(*) FILTER (WHERE c.day IS NULL) > 0
ORDER BY 1;
