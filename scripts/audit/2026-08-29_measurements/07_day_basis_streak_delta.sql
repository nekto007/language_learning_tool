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

CREATE TEMP VIEW repairs AS
  SELECT DISTINCT user_id, event_date AS day FROM streak_events
  WHERE event_type IN ('free_repair','spent_repair','plan_pause','shield_repair');

CREATE TEMP VIEW cal_days AS
  SELECT DISTINCT a.user_id, (a.ts AT TIME ZONE 'UTC' AT TIME ZONE COALESCE(u.timezone,'Europe/Moscow'))::date AS day
  FROM acts a JOIN users u ON u.id=a.user_id
  UNION SELECT user_id, day FROM repairs;

CREATE TEMP VIEW stu_days AS
  SELECT DISTINCT a.user_id, ((a.ts AT TIME ZONE 'UTC' AT TIME ZONE COALESCE(u.timezone,'Europe/Moscow')) - interval '2 hour')::date AS day
  FROM acts a JOIN users u ON u.id=a.user_id
  UNION SELECT user_id, day FROM repairs;

CREATE TEMP VIEW cal_tail AS
  SELECT user_id, count(*) AS streak, max(day) AS anchor FROM (
    SELECT user_id, day, day - (row_number() OVER (PARTITION BY user_id ORDER BY day))::int AS grp
    FROM cal_days) x
  GROUP BY user_id, grp
  HAVING max(day) = (SELECT max(d2.day) FROM cal_days d2 WHERE d2.user_id = x.user_id);

CREATE TEMP VIEW stu_tail AS
  SELECT user_id, count(*) AS streak, max(day) AS anchor FROM (
    SELECT user_id, day, day - (row_number() OVER (PARTITION BY user_id ORDER BY day))::int AS grp
    FROM stu_days) x
  GROUP BY user_id, grp
  HAVING max(day) = (SELECT max(d2.day) FROM stu_days d2 WHERE d2.user_id = x.user_id);

SELECT COALESCE(c.user_id, s.user_id) AS user_id,
       c.anchor AS anchor_calendar, s.anchor AS anchor_study,
       COALESCE(c.streak,0) AS streak_calendar,
       COALESCE(s.streak,0) AS streak_study,
       COALESCE(s.streak,0)-COALESCE(c.streak,0) AS delta
FROM cal_tail c FULL OUTER JOIN stu_tail s ON s.user_id=c.user_id
ORDER BY abs(COALESCE(s.streak,0)-COALESCE(c.streak,0)) DESC, 1;

SELECT count(*) FILTER (WHERE COALESCE(s.streak,0) <> COALESCE(c.streak,0)) AS users_with_streak_delta,
       count(*) AS users_with_any_activity
FROM cal_tail c FULL OUTER JOIN stu_tail s ON s.user_id=c.user_id;
