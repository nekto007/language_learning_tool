# Production Immersion Rollout Report

Generated: 2026-05-13

## Status: Pending Manual Execution

This report documents the production rollout checklist for immersion content imports.
All steps below require production server access and must be executed by an authorized operator.

---

## Pre-Rollout Requirements

- Staging rollout completed and verified (see `reports/staging_immersion_rollout.md`)
- All pytest suites passing on the target branch
- Backup confirmed and stored in safe location

---

## Step 1: Confirm Backup Exists

```bash
# PostgreSQL backup
pg_dump <production_db> -F c -f backups/pre_immersion_import_$(date +%Y%m%d_%H%M%S).dump

# Verify backup
pg_restore --list backups/pre_immersion_import_*.dump | head -20

# Document backup path and size
ls -lh backups/pre_immersion_import_*.dump
```

Tables most affected by this rollout:
- `lessons` (new rows added)
- `collection_words` (ipa, frequency_band, synonyms, antonyms, etymology updated)
- `word_collocations` (new rows added)
- `cultural_notes` (new rows added)
- `user_card_directions` (source field backfilled)

---

## Step 2: Run Imports in Documented Order

Execute in this order. Use `--dry-run` first, then for real.

### Dry-run pass

```bash
# Slot-critical types first
python scripts/import_immersion_lessons.py --input content/immersion/dictation_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/writing_prompt_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/shadow_reading_lessons.json --dry-run

# CEFR seed types
python scripts/import_immersion_lessons.py --input content/immersion/audio_fill_blank_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/translation_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/sentence_correction_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/sentence_completion_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/pronunciation_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/collocation_matching_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/idiom_lessons.json --dry-run

# Vocabulary enrichment
python scripts/import_frequency_bands.py --input content/vocabulary/frequency_bands.csv --dry-run
python scripts/import_ipa_transcriptions.py --input content/vocabulary/ipa_transcriptions.csv --dry-run
python scripts/import_synonyms_antonyms.py --input content/vocabulary/synonyms_antonyms.csv --dry-run
python scripts/import_word_collocations.py --input content/vocabulary/collocations.csv --dry-run
python scripts/import_etymology_notes.py --input content/vocabulary/etymology_notes.csv --dry-run
python scripts/import_cultural_notes.py --input content/vocabulary/cultural_notes.csv --dry-run

# SRS source backfill
python scripts/backfill_card_sources.py --dry-run
```

### Production pass (remove --dry-run)

Same commands as above, without `--dry-run`. Record output from each command.

---

## Step 3: Run Post-Import Audits

```bash
python scripts/audit_immersion_data.py --format markdown > reports/immersion_data_audit_post_import.md
python scripts/report_immersion_gaps.py > reports/immersion_gap_report_post_import.md
python scripts/report_vocabulary_enrichment.py > reports/vocabulary_enrichment_post_import.md
python scripts/audit_existing_listening_payloads.py > reports/listening_payloads_post_import.md
```

Expected SQL verification queries:
```sql
SELECT lesson_type, COUNT(*) FROM lessons GROUP BY lesson_type ORDER BY lesson_type;

-- Slot-critical coverage
SELECT m.level, COUNT(DISTINCT l.module_id) AS modules_with_dictation
FROM lessons l
JOIN modules m ON m.id = l.module_id
WHERE l.lesson_type = 'dictation'
GROUP BY m.level ORDER BY m.level;

-- Vocabulary enrichment
SELECT
  COUNT(*) FILTER (WHERE ipa_transcription IS NOT NULL) AS ipa_filled,
  COUNT(*) FILTER (WHERE frequency_band IS NOT NULL) AS freq_filled,
  COUNT(*) FILTER (WHERE synonyms IS NOT NULL) AS synonyms_filled,
  COUNT(*) FILTER (WHERE antonyms IS NOT NULL) AS antonyms_filled,
  COUNT(*) FILTER (WHERE etymology IS NOT NULL) AS etymology_filled
FROM collection_words;

SELECT COUNT(*) FROM word_collocations;
SELECT COUNT(*) FROM cultural_notes;

-- SRS source coverage
SELECT source, COUNT(*) FROM user_card_directions GROUP BY source ORDER BY source;
```

---

## Step 4: Verify Daily Plan for Real Test Users Across Levels

For each test user account representing A1, A2, B1, B2, C1:

1. Log in as test user
2. Navigate to `/daily-plan`
3. Verify that extension slots appear for listening, writing, and speaking
4. Click through to one dictation lesson and verify audio player renders
5. Click through to one writing prompt and verify submission creates UserWritingAttempt
6. Click through to one shadow reading and verify self-assess completes the lesson

Check URLs:
```
/daily-plan
/curriculum/lessons/<dictation_lesson_id>
/curriculum/lessons/<writing_prompt_lesson_id>
/curriculum/lessons/<shadow_reading_lesson_id>
```

---

## Step 5: Verify Admin Content Quality Dashboard

1. Log in as admin
2. Navigate to `/admin/content-quality`
3. Verify:
   - Dictation, writing_prompt, shadow_reading appear in lesson type breakdown
   - Missing-audio count reflects only genuinely missing items
   - Vocabulary enrichment coverage percentages are non-zero
   - Feedback aggregation includes imported lesson IDs

---

## Step 6: Attach Final Content/Data Report to Release Notes

Compile final report covering:

- Total lessons imported per type
- Total vocabulary words enriched per field
- Total word collocations added
- Total cultural notes added
- SRS source backfill coverage
- Any known gaps or exclusions

File the report as an attachment to the release notes for this sprint.

---

## Rollback Path

If any import causes unexpected issues, refer to `docs/runbooks/immersion-data-rollback.md` for:

- Table-level restore from backup
- Selective delete by `external_key`
- How to disable newly imported lesson types from daily plan slots

---

## Notes

- All import scripts are idempotent — safe to re-run without duplicates
- Staging results are pre-validated; production should match
- Content source files are versioned under `content/` and `content/vocabulary/`
- No user-generated data (attempts, progress, feedback) is modified by these imports
