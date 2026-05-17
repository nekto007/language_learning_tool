# Staging Immersion Rollout Report

Generated: 2026-05-13

## Status: Pending Manual Execution

This report documents the staging rollout checklist for immersion content imports.
All steps below require a live staging environment and must be executed manually by an operator.

---

## Pre-Rollout Checklist

### Step 1: Restore fresh staging DB copy
- **Action**: `pg_restore -d <staging_db> <backup_file>`
- **Status**: Not yet executed — requires staging server access
- **Expected outcome**: Clean DB with latest schema migrations applied

### Step 2: Run migration readiness check
- **Action**: `pytest tests/migrations/test_migration_chain.py -v`
- **Status**: Not yet executed on staging
- **Expected outcome**: All migration tests pass, single alembic head confirmed

### Step 3: Run all content imports with --dry-run
Commands to execute on staging:
```bash
python scripts/import_immersion_lessons.py --input content/immersion/dictation_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/writing_prompt_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/shadow_reading_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/audio_fill_blank_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/translation_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/sentence_correction_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/sentence_completion_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/pronunciation_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/collocation_matching_lessons.json --dry-run
python scripts/import_immersion_lessons.py --input content/immersion/idiom_lessons.json --dry-run
```
- **Status**: Not yet executed on staging

### Step 4: Run all content imports for real
- Same commands as Step 3, without `--dry-run`
- **Status**: Not yet executed on staging
- **Note**: Verify row counts after each import

### Step 5: Run gap reports after import
```bash
python scripts/report_immersion_gaps.py > reports/immersion_gap_report_post_import.md
python scripts/report_vocabulary_enrichment.py > reports/vocabulary_enrichment_post_import.md
```
- **Status**: Not yet executed on staging

### Step 6: Run lesson and daily plan smoke tests
```bash
pytest tests/curriculum/ -m smoke -v
pytest tests/daily_plan/ -m smoke -v
```
- **Status**: Not yet executed on staging

### Step 7: Record final row counts
Expected SQL queries to run after import:
```sql
SELECT lesson_type, COUNT(*) FROM lessons GROUP BY lesson_type ORDER BY lesson_type;
SELECT COUNT(*) FROM collection_words WHERE ipa_transcription IS NOT NULL;
SELECT COUNT(*) FROM collection_words WHERE frequency_band IS NOT NULL;
SELECT COUNT(*) FROM word_collocations;
SELECT COUNT(*) FROM cultural_notes;
```
- **Status**: Not yet executed on staging

---

## Notes

- All import scripts support `--dry-run` for safe previewing
- All imports are idempotent — safe to re-run
- Rollback path documented in `docs/runbooks/immersion-data-rollback.md`
- Content source files are versioned under `content/` directory
