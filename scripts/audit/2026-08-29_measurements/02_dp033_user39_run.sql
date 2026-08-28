\pset pager off
WITH req AS (
  SELECT DISTINCT d.plan_date
  FROM daily_plan_log d, LATERAL jsonb_array_elements(d.plan_json::jsonb -> 'items') it
  WHERE d.user_id = 39 AND d.plan_json IS NOT NULL
    AND it->>'section'='required' AND it->>'id' LIKE 'reading:%'
),
isl AS (
  SELECT plan_date, plan_date - (row_number() OVER (ORDER BY plan_date))::int AS grp FROM req
)
SELECT min(plan_date) AS run_start, max(plan_date) AS run_end, count(*) AS days_in_run,
       (max(plan_date)-min(plan_date)+1) AS calendar_span
FROM isl GROUP BY grp ORDER BY 3 DESC;

-- does user 39 have the books module at all?
SELECT u.id, u.is_admin, COALESCE(um.is_enabled,false) AS has_books_module
FROM users u LEFT JOIN user_modules um ON um.user_id=u.id
     AND um.module_id=(SELECT id FROM system_modules WHERE code='books')
WHERE u.id=39;
