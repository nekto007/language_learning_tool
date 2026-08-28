SELECT
  count(*) AS secured_days,
  count(*) FILTER (WHERE se.id IS NULL) AS secured_without_perfect_day,
  count(*) FILTER (WHERE se.id IS NOT NULL) AS secured_with_perfect_day
FROM daily_plan_log d
LEFT JOIN streak_events se
  ON se.user_id = d.user_id AND se.event_date = d.plan_date AND se.event_type = 'xp_perfect_day'
WHERE d.secured_at IS NOT NULL;

SELECT d.user_id, count(*) AS secured_days,
       count(*) FILTER (WHERE se.id IS NULL) AS missing_bonus
FROM daily_plan_log d
LEFT JOIN streak_events se
  ON se.user_id = d.user_id AND se.event_date = d.plan_date AND se.event_type='xp_perfect_day'
WHERE d.secured_at IS NOT NULL
GROUP BY 1 ORDER BY 3 DESC;

SELECT count(*) AS perfect_day_without_secured
FROM streak_events se
LEFT JOIN daily_plan_log d
  ON d.user_id = se.user_id AND d.plan_date = se.event_date AND d.secured_at IS NOT NULL
WHERE se.event_type='xp_perfect_day' AND d.id IS NULL;
