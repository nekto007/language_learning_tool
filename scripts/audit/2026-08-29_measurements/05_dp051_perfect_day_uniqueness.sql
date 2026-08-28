SELECT count(*) AS duplicate_perfect_day_pairs FROM (
  SELECT user_id, event_date FROM streak_events WHERE event_type='xp_perfect_day'
  GROUP BY 1,2 HAVING count(*) > 1
) x;
SELECT indexname FROM pg_indexes WHERE tablename='streak_events' AND indexdef ILIKE '%perfect%';
