# Immersion Data Backup and Rollback Runbook

This runbook covers backup procedures before any immersion content import and the rollback paths if an import goes wrong. It is the operational counterpart to the importers under `scripts/import_immersion_lessons.py`, `scripts/import_lesson_audio_metadata.py`, the vocabulary importers in `scripts/import_*.py`, and the SRS card source backfill in `scripts/backfill_card_sources.py`.

Scope of tables managed by immersion imports:

- `lessons` — new lessons inserted by the immersion importer (`dictation`, `audio_fill_blank`, `translation`, `sentence_correction`, `writing_prompt`, `sentence_completion`, `collocation_matching`, `shadow_reading`, `pronunciation`, `idiom`) and audio metadata overwrites on existing `listening_immersion` / `listening_quiz` lessons.
- `collection_words` — vocabulary enrichment fields: `ipa_transcription`, `frequency_band`, `synonyms`, `antonyms`, `etymology`.
- `word_collocations` — collocation rows added per priority word.
- `cultural_notes` — cultural notes attached to priority words.
- `user_card_directions` — `source` column backfill only. User progress fields (`ease_factor`, `interval`, `next_review`, etc.) must never be touched.

User-generated tables (`user_writing_attempts`, `listening_attempts`, `pronunciation_attempts`, `user_reading_sessions`, `lesson_feedback`, `lesson_progress`, `user_lesson_progress`, `quiz_error_log`, `grammar_attempts`, `user_grammar_exercises`, `streak_events`) are NEVER written by import scripts and must NEVER be restored from a backup taken before user activity occurred — see Risks section.

---

## 1. Pre-import backup

Run a full logical backup before every production-affecting import. Backups are required even for `--dry-run` runs that change no rows, because the next step is usually the real run.

Environment variables expected:

- `DATABASE_URL` — production or staging connection string used by Flask.
- `BACKUP_DIR` — directory with enough free space for the full DB dump, e.g. `/var/backups/llt`.

### 1a. Full database snapshot

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR/$TS"

# Custom format dump (parallel restore, table-level restore).
pg_dump --format=custom --no-owner --no-privileges \
  --file "$BACKUP_DIR/$TS/full.dump" \
  "$DATABASE_URL"

# Sanity check.
pg_restore --list "$BACKUP_DIR/$TS/full.dump" | wc -l
```

Record `TS` in the rollout report (`reports/staging_immersion_rollout.md` or `reports/production_immersion_rollout.md`) so the operator knows which dump matches the import.

### 1b. Table-level snapshots (faster restore)

Custom-format dumps support restoring individual tables, but a focused per-table dump is faster to reason about during an emergency. Run after the full snapshot, not instead of it.

```bash
for t in lessons collection_words word_collocations cultural_notes user_card_directions; do
  pg_dump --format=custom --no-owner --no-privileges \
    --table="public.$t" \
    --file "$BACKUP_DIR/$TS/$t.dump" \
    "$DATABASE_URL"
done
```

### 1c. CSV side-export of changed columns only

For vocabulary and SRS source backfills, also export the columns the import will write. This lets us diff before/after without unpacking a binary dump.

```bash
psql "$DATABASE_URL" -c "\copy (
  SELECT id, ipa_transcription, frequency_band, synonyms, antonyms, etymology
  FROM collection_words
) TO '$BACKUP_DIR/$TS/collection_words_enrichment.csv' WITH CSV HEADER"

psql "$DATABASE_URL" -c "\copy (
  SELECT id, source FROM user_card_directions
) TO '$BACKUP_DIR/$TS/user_card_directions_source.csv' WITH CSV HEADER"
```

### 1d. Verify backup is usable

Never trust a backup you haven't read.

```bash
pg_restore --list "$BACKUP_DIR/$TS/full.dump" > "$BACKUP_DIR/$TS/full.toc"
wc -l "$BACKUP_DIR/$TS/full.toc"
```

If `pg_restore --list` fails, abort the import and investigate. Do not proceed with a partial or corrupt backup.

---

## 2. Table-level restore

All restores below assume the dump from step 1 is available at `$BACKUP_DIR/$TS/`. Restores run inside a single transaction so they either fully succeed or fully roll back.

### 2a. Restore `lessons`

`lessons` is the highest-risk table because user progress in `lesson_progress`, `user_lesson_progress`, `lesson_attempts`, and `user_grammar_exercises` references it by id. A full-table restore that does not preserve ids will break those references.

Preferred path — restore only lessons created by the import using their `external_key`:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
DELETE FROM lessons
 WHERE content->>'external_key' LIKE 'immersion:%'
   AND created_at >= now() - interval '24 hours';
COMMIT;
SQL
```

Fallback path — full table restore when imported rows are inseparable from prior bad writes:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "BEGIN; TRUNCATE lessons CASCADE; COMMIT;"
pg_restore --dbname="$DATABASE_URL" --data-only --table=lessons \
  --single-transaction "$BACKUP_DIR/$TS/lessons.dump"
```

`TRUNCATE lessons CASCADE` deletes user progress rows. Use only on staging or with explicit signoff.

### 2b. Restore `collection_words` enrichment columns

We never want to restore the full `collection_words` row because users may have edited the row through admin during the import window. Restore only the enrichment columns from the CSV captured in step 1c.

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<SQL
BEGIN;
CREATE TEMP TABLE cw_restore (
  id INT,
  ipa_transcription TEXT,
  frequency_band SMALLINT,
  synonyms JSONB,
  antonyms JSONB,
  etymology TEXT
);
\copy cw_restore FROM '$BACKUP_DIR/$TS/collection_words_enrichment.csv' WITH CSV HEADER

UPDATE collection_words c
   SET ipa_transcription = r.ipa_transcription,
       frequency_band    = r.frequency_band,
       synonyms          = r.synonyms,
       antonyms          = r.antonyms,
       etymology         = r.etymology
  FROM cw_restore r
 WHERE c.id = r.id;
COMMIT;
SQL
```

### 2c. Restore `word_collocations`

Imported collocations are insert-only and identified by `(word_id, collocation_phrase)`. Roll back by deleting the rows the importer produced:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
DELETE FROM word_collocations
 WHERE source = 'import:immersion'
   AND created_at >= now() - interval '24 hours';
COMMIT;
SQL
```

If the table has no provenance column yet, fall back to a full-table restore:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "BEGIN; TRUNCATE word_collocations; COMMIT;"
pg_restore --dbname="$DATABASE_URL" --data-only --table=word_collocations \
  --single-transaction "$BACKUP_DIR/$TS/word_collocations.dump"
```

### 2d. Restore `cultural_notes`

Same pattern as `word_collocations`. Delete by `(word_id, context)` uniqueness or restore the dump.

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "BEGIN; TRUNCATE cultural_notes; COMMIT;"
pg_restore --dbname="$DATABASE_URL" --data-only --table=cultural_notes \
  --single-transaction "$BACKUP_DIR/$TS/cultural_notes.dump"
```

### 2e. Restore `user_card_directions.source`

Only the `source` column is touched. Restore only that column from the CSV.

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<SQL
BEGIN;
CREATE TEMP TABLE ucd_restore (id INT, source TEXT);
\copy ucd_restore FROM '$BACKUP_DIR/$TS/user_card_directions_source.csv' WITH CSV HEADER

UPDATE user_card_directions u
   SET source = r.source
  FROM ucd_restore r
 WHERE u.id = r.id;
COMMIT;
SQL
```

Never run a full-row restore on `user_card_directions` — it would wipe SM-2 state (`ease_factor`, `interval`, `next_review`, `lapses`, `is_leech`, `buried_until`) for every user who studied during the import.

---

## 3. Disabling newly imported slots by lesson type

If imported content is wrong but not corrupt, prefer disabling over deleting. Disabling preserves user attempts and gives content authors time to fix the data.

### 3a. Soft-disable by `is_active`

```sql
BEGIN;
UPDATE lessons
   SET is_active = FALSE
 WHERE lesson_type IN ('dictation', 'writing_prompt', 'shadow_reading')
   AND content->>'external_key' LIKE 'immersion:%';
COMMIT;
```

Slot assemblers in `app/daily_plan/linear/slots/` filter on `is_active = TRUE`, so disabled lessons disappear from the daily plan without breaking history.

### 3b. Skip a single lesson type at the slot layer

If a whole lesson type needs to be paused without touching the DB, set the appropriate feature flag in `settings.local.json` or via `flask` CLI. The slot assemblers in `app/daily_plan/linear/chain.py` already skip sources with nothing to offer, so removing a lesson type is a config-only change.

### 3c. Audit which slots are affected

```sql
SELECT lesson_type, COUNT(*)
  FROM lessons
 WHERE content->>'external_key' LIKE 'immersion:%'
   AND is_active = FALSE
 GROUP BY 1
 ORDER BY 1;
```

Attach the output to the rollback report.

---

## 4. Revert content imports by `external_key`

Every immersion importer writes a stable `external_key` in `lesson.content` (e.g. `immersion:dictation:a1m01`, `immersion:writing_prompt:b2m07`). This is the canonical revert handle.

### 4a. Dry-run delete

```sql
SELECT id, lesson_type, content->>'external_key' AS external_key, created_at
  FROM lessons
 WHERE content->>'external_key' LIKE 'immersion:%'
   AND created_at >= TIMESTAMP '2026-05-11 00:00:00';
```

Review the list before deleting.

### 4b. Delete imported rows

```sql
BEGIN;
DELETE FROM lessons
 WHERE content->>'external_key' LIKE 'immersion:%'
   AND created_at >= TIMESTAMP '2026-05-11 00:00:00';
COMMIT;
```

CASCADE on `lesson_progress`, `user_lesson_progress`, `lesson_attempts`, `lesson_feedback`, `quiz_error_log` removes user activity tied to those lessons. If you want to keep user activity, soft-disable instead (section 3a).

### 4c. Filter by import batch

If the importer logs a `batch_id` to `reports/<import>.md`, use it to scope the revert:

```sql
DELETE FROM lessons
 WHERE content->>'external_key' LIKE 'immersion:%'
   AND content->>'import_batch_id' = '<batch_id>';
```

### 4d. Revert vocabulary enrichment

Vocabulary imports are column-level UPDATEs, not inserts. Revert by re-importing the pre-import CSV from step 1c with `--force`:

```bash
python scripts/import_frequency_bands.py \
  --csv "$BACKUP_DIR/$TS/collection_words_enrichment.csv" \
  --force --column frequency_band
```

If the importers do not yet support reading the backup CSV directly, restore through section 2b.

### 4e. Revert SRS source tags

```bash
python scripts/backfill_card_sources.py --revert \
  --from "$BACKUP_DIR/$TS/user_card_directions_source.csv"
```

Or restore through section 2e.

---

## 5. Risks for user-generated attempts and feedback

User-generated rows are written outside the import path and cannot be safely restored from a pre-import snapshot. Treat them as append-only.

### 5a. Tables to NEVER restore from a pre-import backup

- `user_writing_attempts`
- `listening_attempts`
- `pronunciation_attempts`
- `user_reading_sessions`
- `lesson_feedback`
- `lesson_progress`, `user_lesson_progress`, `lesson_attempts`
- `quiz_error_log`
- `grammar_attempts`, `user_grammar_exercises`
- `streak_events`
- `user_statistics`
- `daily_plan_log`, `daily_plan_events`
- `notifications`

Restoring any of these to a snapshot taken before user activity will silently delete that activity, wiping streaks, XP, and achievement progress. The only acceptable restore on these tables is point-in-time recovery of the whole DB through WAL replay, which is out of scope for this runbook.

### 5b. Cascade hazards on `lessons` revert

Deleting a row in `lessons` cascades into every table listed in 5a that references it. Before running a `DELETE FROM lessons`:

1. Run the audit query in section 4a.
2. For each `external_key` to be deleted, run:

```sql
SELECT
  (SELECT COUNT(*) FROM lesson_progress WHERE lesson_id = $1)        AS lp,
  (SELECT COUNT(*) FROM user_lesson_progress WHERE lesson_id = $1)   AS ulp,
  (SELECT COUNT(*) FROM lesson_attempts WHERE lesson_id = $1)        AS la,
  (SELECT COUNT(*) FROM lesson_feedback WHERE lesson_id = $1)        AS lf,
  (SELECT COUNT(*) FROM quiz_error_log WHERE lesson_id = $1)         AS qel,
  (SELECT COUNT(*) FROM listening_attempts WHERE lesson_id = $1)     AS lia,
  (SELECT COUNT(*) FROM user_writing_attempts WHERE lesson_id = $1)  AS uwa;
```

If any count is non-zero, soft-disable (section 3a) instead of deleting.

### 5c. Streak and XP side effects

User XP from imported lessons is recorded in `StreakEvent(event_type='xp_linear_*')`. Deleting the source lesson does not delete the StreakEvent (no FK). To keep accounting consistent, treat XP as immutable history — do not retroactively void it after a content rollback.

### 5d. Notifications referencing imported lessons

Notifications generated by `app/notifications/services.py` may carry lesson ids. After a content rollback, dismiss or mark-read affected notifications instead of deleting them:

```sql
UPDATE notifications
   SET dismissed_at = now()
 WHERE payload->>'lesson_id' IN (SELECT id::text FROM <deleted_lesson_ids>);
```

---

## 6. Rollback decision matrix

| Failure mode                                           | Preferred action                              |
|--------------------------------------------------------|-----------------------------------------------|
| Wrong content in 1-2 lessons                            | Edit content via admin, no rollback           |
| Wrong content across one lesson type                    | Soft-disable (3a), fix source JSON, re-import |
| Importer wrote into wrong module                        | Delete by `external_key` (4b)                 |
| Vocabulary enrichment regressed quality                 | Re-import from CSV (4d) or restore (2b)       |
| SRS source backfill labelled wrong cards                | Restore `source` column only (2e)             |
| Migration applied unintended schema changes             | Out of scope — use Alembic downgrade          |
| User progress missing after import                      | STOP — investigate before any restore         |

---

## 7. Post-rollback checks

After every rollback, run:

```bash
python scripts/audit_immersion_data.py --format markdown \
  --output reports/post_rollback_audit.md

pytest -m smoke
```

Attach `reports/post_rollback_audit.md` to the incident notes. Compare the row counts in section 1c CSV against current state to confirm the rollback completed.

---

## 8. Contacts and escalation

- Database backups: ops on-call (see internal runbook index).
- Content authoring: curriculum team.
- Slot assembler regressions: daily-plan code owner (`app/daily_plan/linear/`).
- This runbook lives under `docs/runbooks/` and must be updated whenever an importer changes its `external_key` scheme or adds a new table to the immersion surface.
