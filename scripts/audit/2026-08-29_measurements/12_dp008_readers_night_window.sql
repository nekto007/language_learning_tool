-- DP-008 / DP-010 / DP-012 / DP-022 / DP-026 — «до»: сколько данных лежит под
-- учебной датой, до которой календарный читатель не дотягивается.
--
-- Писатели (XP-события, DailyStudyMinutes, DailyPlanLog.plan_date, кохорта
-- гонки) ключуются `get_user_local_date` — учебный день с границей 02:00.
-- Читатели брали календарную дату (часть от клиентского `?tz=`, часть от
-- собственного pytz-стека). Всё, что записано между 00:00 и 02:00 локального
-- времени, лежит под ВЧЕРАШНЕЙ датой, а календарный читатель спрашивает про
-- сегодняшнюю — и не находит ничего. Расхождение не самокорректируется.
--
-- read-only.

\echo '== 1. XP-события (DP-008): распределение по локальному часу записи =='
SELECT
    EXTRACT(HOUR FROM (e.created_at AT TIME ZONE 'UTC'
                       AT TIME ZONE COALESCE(u.timezone, 'Europe/Moscow')))::int AS local_hour,
    COUNT(*) AS events
FROM streak_events e
JOIN users u ON u.id = e.user_id
WHERE e.event_type IN (
        'xp_phase', 'xp_perfect_day', 'xp_surprise', 'xp_linear',
        'xp_curriculum_lesson', 'xp_book_chapter', 'xp_referral', 'xp_game'
      )
GROUP BY 1
ORDER BY 1;

\echo '== 2. XP-события в окне расхождения 00:00-02:00 (не видны виджету «XP сегодня») =='
SELECT
    COUNT(*) AS events_in_window,
    COUNT(DISTINCT e.user_id) AS users_affected
FROM streak_events e
JOIN users u ON u.id = e.user_id
WHERE e.event_type IN (
        'xp_phase', 'xp_perfect_day', 'xp_surprise', 'xp_linear',
        'xp_curriculum_lesson', 'xp_book_chapter', 'xp_referral', 'xp_game'
      )
  AND EXTRACT(HOUR FROM (e.created_at AT TIME ZONE 'UTC'
                         AT TIME ZONE COALESCE(u.timezone, 'Europe/Moscow'))) < 2;

\echo '== 3. Те же события, у которых event_date РАЗОШЛАСЬ с календарной датой записи =='
-- Именно эти строки календарный читатель не найдёт никогда: они записаны
-- под учебным днём D, а виджет весь следующий календарный день спрашивает D+1.
SELECT
    e.user_id,
    e.event_type,
    e.event_date AS written_under,
    (e.created_at AT TIME ZONE 'UTC'
       AT TIME ZONE COALESCE(u.timezone, 'Europe/Moscow'))::date AS calendar_date
FROM streak_events e
JOIN users u ON u.id = e.user_id
WHERE e.event_type IN (
        'xp_phase', 'xp_perfect_day', 'xp_surprise', 'xp_linear',
        'xp_curriculum_lesson', 'xp_book_chapter', 'xp_referral', 'xp_game'
      )
  AND e.event_date <> (e.created_at AT TIME ZONE 'UTC'
                       AT TIME ZONE COALESCE(u.timezone, 'Europe/Moscow'))::date
ORDER BY e.created_at DESC
LIMIT 50;

\echo '== 4. DailyStudyMinutes (DP-010): строк всего =='
SELECT COUNT(*) AS rows, COUNT(DISTINCT user_id) AS users FROM daily_study_minutes;

\echo '== 5. Кохорты гонки (DP-012): сколько дат на юзера =='
SELECT
    p.user_id,
    COUNT(DISTINCT r.race_date) AS distinct_race_dates,
    COUNT(*)                    AS participant_rows
FROM daily_race_participants p
JOIN daily_races r ON r.id = p.race_id
GROUP BY 1
ORDER BY 2 DESC
LIMIT 20;

\echo '== 6. Незакрытые дни (DP-022): база, на которой два читателя расходились =='
SELECT
    COUNT(*) FILTER (WHERE secured_at IS NULL)     AS unsecured_days,
    COUNT(*) FILTER (WHERE secured_at IS NOT NULL) AS secured_days
FROM daily_plan_log;
