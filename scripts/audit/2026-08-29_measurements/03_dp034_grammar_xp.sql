SELECT (details->>'xp')::int AS xp_awarded, count(*)
FROM streak_events
WHERE event_type='xp_linear' AND details->>'source'='linear_curriculum_grammar'
GROUP BY 1 ORDER BY 1;

SELECT count(*) AS grammar_awards_total,
       count(*) FILTER (WHERE (details->>'xp')::int = 9)  AS awards_of_9,
       count(*) FILTER (WHERE (details->>'xp')::int = 18) AS awards_of_18
FROM streak_events
WHERE event_type='xp_linear' AND details->>'source'='linear_curriculum_grammar';

-- context: other sources whose award equals exactly half of the LINEAR_XP base
SELECT details->>'source' AS source, (details->>'xp')::int AS xp, count(*)
FROM streak_events
WHERE event_type='xp_linear'
  AND details->>'source' IN ('linear_curriculum_vocabulary','linear_curriculum_use','linear_curriculum_reading')
GROUP BY 1,2 ORDER BY 1,2;
