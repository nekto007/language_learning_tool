\pset pager off
-- required reading items in frozen snapshots, joined against per-book access
WITH req AS (
  SELECT d.user_id, d.plan_date, d.secured_at,
         (it->'data'->>'book_id')::int AS book_id
  FROM daily_plan_log d,
       LATERAL jsonb_array_elements(d.plan_json::jsonb -> 'items') it
  WHERE d.plan_json IS NOT NULL
    AND it->>'section' = 'required'
    AND it->>'id' LIKE 'reading:%'
),
acc AS (
  SELECT r.*,
         u.is_admin,
         b.id IS NULL                       AS book_missing,
         b.is_published                     AS book_published,
         b.rights_status,
         b.expiration_date,
         COALESCE(um.is_enabled, false)     AS has_books_module
  FROM req r
  JOIN users u ON u.id = r.user_id
  LEFT JOIN book b ON b.id = r.book_id
  LEFT JOIN user_modules um ON um.user_id = r.user_id
       AND um.module_id = (SELECT id FROM system_modules WHERE code='books')
)
SELECT
  count(*) AS required_reading_user_days,
  count(*) FILTER (WHERE NOT is_admin AND NOT has_books_module
                     AND rights_status <> 'public_domain')     AS unreachable_no_module,
  count(*) FILTER (WHERE NOT is_admin AND book_published IS NOT TRUE) AS unreachable_draft,
  count(*) FILTER (WHERE NOT is_admin AND expiration_date IS NOT NULL
                     AND expiration_date < plan_date)          AS unreachable_expired,
  count(*) FILTER (WHERE book_missing)                          AS book_row_missing
FROM acc;

-- per-user breakdown of the "no books module" case
WITH req AS (
  SELECT d.user_id, d.plan_date, (it->'data'->>'book_id')::int AS book_id
  FROM daily_plan_log d,
       LATERAL jsonb_array_elements(d.plan_json::jsonb -> 'items') it
  WHERE d.plan_json IS NOT NULL AND it->>'section'='required' AND it->>'id' LIKE 'reading:%'
)
SELECT r.user_id, count(*) AS unreachable_days,
       min(r.plan_date) AS first_day, max(r.plan_date) AS last_day
FROM req r
JOIN users u ON u.id = r.user_id
LEFT JOIN book b ON b.id = r.book_id
LEFT JOIN user_modules um ON um.user_id=r.user_id
     AND um.module_id=(SELECT id FROM system_modules WHERE code='books')
WHERE NOT u.is_admin
  AND COALESCE(um.is_enabled,false) = false
  AND COALESCE(b.rights_status,'companion_only') <> 'public_domain'
GROUP BY 1 ORDER BY 2 DESC;

-- how many of those unreachable user-days ended without secured_at
WITH req AS (
  SELECT d.user_id, d.plan_date, d.secured_at, (it->'data'->>'book_id')::int AS book_id
  FROM daily_plan_log d,
       LATERAL jsonb_array_elements(d.plan_json::jsonb -> 'items') it
  WHERE d.plan_json IS NOT NULL AND it->>'section'='required' AND it->>'id' LIKE 'reading:%'
)
SELECT count(*) FILTER (WHERE r.secured_at IS NULL) AS unsecured,
       count(*) FILTER (WHERE r.secured_at IS NOT NULL) AS secured
FROM req r
JOIN users u ON u.id=r.user_id
LEFT JOIN book b ON b.id=r.book_id
LEFT JOIN user_modules um ON um.user_id=r.user_id
     AND um.module_id=(SELECT id FROM system_modules WHERE code='books')
WHERE NOT u.is_admin AND COALESCE(um.is_enabled,false)=false
  AND COALESCE(b.rights_status,'companion_only') <> 'public_domain';

-- catalog fact: any published public-domain book at all?
SELECT count(*) AS published_public_domain_books FROM book WHERE is_published AND rights_status='public_domain';
