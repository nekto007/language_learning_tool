-- DP-003 / DP-002 / DP-009 — «до»: сколько закрытий дня приземлилось в окно
-- 00:00–02:00 локального времени, то есть туда, где календарный и учебный
-- день расходятся на сутки.
--
-- Дашборд (`_render_unified_dashboard`) писал `plan_date = now(tz).date()`,
-- /api/daily-status — `get_user_local_date` (учебный день). В этом окне два
-- писателя расходились: строка уезжала в завтра.
--
-- read-only.

\echo '== 1. secured_at по часу локального времени юзера =='
SELECT
    EXTRACT(HOUR FROM (l.secured_at AT TIME ZONE 'UTC'
                       AT TIME ZONE COALESCE(u.timezone, 'Europe/Moscow')))::int AS local_hour,
    COUNT(*) AS rows
FROM daily_plan_log l
JOIN users u ON u.id = l.user_id
WHERE l.secured_at IS NOT NULL
GROUP BY 1
ORDER BY 1;

\echo '== 2. закрытия в окне расхождения (00:00-02:00 локально) =='
SELECT
    COUNT(*) FILTER (
        WHERE EXTRACT(HOUR FROM (l.secured_at AT TIME ZONE 'UTC'
              AT TIME ZONE COALESCE(u.timezone, 'Europe/Moscow'))) < 2
    ) AS closed_between_00_and_02,
    COUNT(*) AS closed_total
FROM daily_plan_log l
JOIN users u ON u.id = l.user_id
WHERE l.secured_at IS NOT NULL;

\echo '== 3. строки, где plan_date уже уехал вперёд от учебного дня закрытия =='
SELECT
    l.user_id,
    l.plan_date,
    l.secured_at,
    (
        (l.secured_at AT TIME ZONE 'UTC'
         AT TIME ZONE COALESCE(u.timezone, 'Europe/Moscow'))
        - INTERVAL '2 hours'
    )::date AS study_day_of_secured_at
FROM daily_plan_log l
JOIN users u ON u.id = l.user_id
WHERE l.secured_at IS NOT NULL
  AND l.plan_date <> (
        (l.secured_at AT TIME ZONE 'UTC'
         AT TIME ZONE COALESCE(u.timezone, 'Europe/Moscow'))
        - INTERVAL '2 hours'
      )::date
ORDER BY l.secured_at DESC
LIMIT 50;
