# Immersion Data Production Readiness Checklist

Operational checklist for the immersion content rollout described in
`docs/plans/2026-05-11-post-immersion-content-data-plan.md` (Tasks 9-50).
This runbook is the entry point an on-call engineer uses when staging or
production is about to receive an immersion import batch.

Scope:

- All importers under `scripts/import_*.py` and
  `scripts/backfill_card_sources.py`.
- Content fixtures under `content/immersion/` and `content/vocabulary/`.
- Reports written to `reports/`.
- Acceptance contract: `docs/content/immersion-content-targets.md`.

Companion runbook: `docs/runbooks/immersion-data-rollback.md`
(backup + rollback procedure — referenced from every step below).

---

## 0. Preconditions

Before running any command in this checklist, confirm:

- `DATABASE_URL` points at the intended environment (staging or
  production). Echo it once and verify the host before continuing.
- `BACKUP_DIR` is set and has free space for a full dump plus per-table
  dumps (see rollback runbook §1).
- `FLASK_APP=app` is exported.
- The current branch matches the release tag. Imports must not race a
  schema migration deploy.
- A clean `git status` on the deploy host (no local edits to content
  fixtures or scripts).
- Migration chain is green:
  `pytest tests/migrations/test_migration_chain.py` returns 0 and
  `reports/migration_readiness.md` is current.
- Latest seed coverage report (`reports/seed_coverage.md`) shows no
  missing achievement or challenge seeds.

If any precondition fails, stop and resolve before backing up.

---

## 1. Import commands in safe execution order

Run the commands in this exact order. Each step must finish (and its
verification must pass) before the next starts. Every importer supports
`--dry-run` and is idempotent — always do a `--dry-run` pass first.

### 1a. Take a backup

Follow `docs/runbooks/immersion-data-rollback.md` §1 in full
(full dump, per-table dumps, CSV side-export, verify). Record the
backup timestamp `TS` — the rollout report needs it.

### 1b. Baseline audit (read-only)

```bash
python scripts/audit_immersion_data.py --format markdown \
  --output reports/immersion_data_audit.md
```

Read the report. Confirm the source/DB module reconciliation matches
what the importers expect (Tasks 1, 15). If the source/DB delta has
changed since the plan was written, stop and update
`content/immersion/module_insertion_map.csv` before any write.

### 1c. Curriculum lesson imports — slot-critical, per module

Order matters: slot-critical types ship before non-slot types so the
linear daily plan can already resolve `listening`, `writing`, and
`speaking` slots after the first batch.

```bash
# Dry-run pass for every slot-critical type.
python scripts/import_immersion_lessons.py \
  --file content/immersion/dictation_lessons.json --dry-run
python scripts/import_immersion_lessons.py \
  --file content/immersion/writing_prompt_lessons.json --dry-run
python scripts/import_immersion_lessons.py \
  --file content/immersion/shadow_reading_lessons.json --dry-run

# Real pass — only after every dry-run reports zero errors.
python scripts/import_immersion_lessons.py \
  --file content/immersion/dictation_lessons.json \
  --report reports/dictation_import.md
python scripts/import_immersion_lessons.py \
  --file content/immersion/writing_prompt_lessons.json \
  --report reports/writing_prompt_import.md
python scripts/import_immersion_lessons.py \
  --file content/immersion/shadow_reading_lessons.json \
  --report reports/shadow_reading_import.md
```

Verification after each real pass:

- The importer's report lists `changed_rows >= 0` and `errors = 0`.
- Re-running the same command with `--dry-run` reports `0 changes`.
- `python scripts/report_immersion_gaps.py` shows the type's
  per-module saturation matches the contract in
  `docs/content/immersion-content-targets.md` §1.

### 1d. Curriculum lesson imports — non-slot CEFR seeds

```bash
for f in audio_fill_blank translation sentence_correction \
         sentence_completion pronunciation collocation_matching idiom; do
  python scripts/import_immersion_lessons.py \
    --file content/immersion/${f}_lessons.json --dry-run
done

for f in audio_fill_blank translation sentence_correction \
         sentence_completion pronunciation collocation_matching idiom; do
  python scripts/import_immersion_lessons.py \
    --file content/immersion/${f}_lessons.json \
    --report reports/cefr_seed_import.md
done
```

Verification:

- Each type meets its Section 2 minimum in
  `docs/content/immersion-content-targets.md` (≥5 per CEFR level for
  most, ≥5 each for B1/B2/C1 for `idiom`).
- A second `--dry-run` reports `0 changes` for every file.

### 1e. Audio metadata imports

```bash
python scripts/import_lesson_audio_metadata.py \
  --file content/immersion/listening_immersion_audio.json --dry-run
python scripts/import_lesson_audio_metadata.py \
  --file content/immersion/listening_quiz_audio.json --dry-run

python scripts/import_lesson_audio_metadata.py \
  --file content/immersion/listening_immersion_audio.json
python scripts/import_lesson_audio_metadata.py \
  --file content/immersion/listening_quiz_audio.json
```

Verification:

- `flask content audit-audio` (extended in Task 34) reports `0`
  missing-audio lessons outside
  `content/immersion/listening_audio_exclusions.json`.

### 1f. Vocabulary enrichment imports

Order chosen so cheaper / safer fields land first.

```bash
python scripts/import_frequency_bands.py \
  --csv content/vocabulary/frequency_bands.csv --dry-run
python scripts/import_ipa_transcriptions.py \
  --csv content/vocabulary/ipa_transcriptions.csv --dry-run
python scripts/import_synonyms_antonyms.py \
  --csv content/vocabulary/synonyms_antonyms.csv --dry-run
python scripts/import_word_collocations.py \
  --csv content/vocabulary/collocations.csv --dry-run
python scripts/import_etymology_notes.py \
  --csv content/vocabulary/etymology_notes.csv --dry-run
python scripts/import_cultural_notes.py \
  --csv content/vocabulary/cultural_notes.csv --dry-run

# Real pass once every dry-run is clean.
python scripts/import_frequency_bands.py    --csv content/vocabulary/frequency_bands.csv
python scripts/import_ipa_transcriptions.py --csv content/vocabulary/ipa_transcriptions.csv
python scripts/import_synonyms_antonyms.py  --csv content/vocabulary/synonyms_antonyms.csv
python scripts/import_word_collocations.py  --csv content/vocabulary/collocations.csv
python scripts/import_etymology_notes.py    --csv content/vocabulary/etymology_notes.csv
python scripts/import_cultural_notes.py     --csv content/vocabulary/cultural_notes.csv
```

Verification:

- `python scripts/report_vocabulary_enrichment.py \
   --output reports/vocabulary_enrichment.md` shows tier-1 priority
  words at the targets in
  `docs/content/immersion-content-targets.md` §4.

### 1g. SRS source backfill

```bash
python scripts/backfill_card_sources.py --dry-run
python scripts/backfill_card_sources.py
```

Verification:

- The dry-run report shows `unresolved = 0`. Ambiguous cards are
  labelled `manual`, not left null.

### 1h. Post-import audit

```bash
python scripts/audit_immersion_data.py --format markdown \
  --output reports/immersion_data_audit.md
python scripts/report_immersion_gaps.py \
  --output reports/immersion_gap_report.md
```

Both reports must satisfy the acceptance contract in
`docs/content/immersion-content-targets.md` §6 before the rollout is
considered done.

---

## 2. Required pre-import audits

Run these audits before any write. They are the gate for §1.

| Audit                                                | Command                                                                       | Pass criterion                                                       |
| ---------------------------------------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Migration chain readiness                            | `pytest tests/migrations/test_migration_chain.py`                             | Exit 0; one head; new tables present.                                |
| Seed coverage (achievements + challenges)            | `cat reports/seed_coverage.md`                                                | No missing seeds. Regenerate if older than the current release tag.  |
| Source/DB module reconciliation                      | `python scripts/audit_immersion_data.py --format markdown ...`                | Source-only and DB-only module lists are empty or explicitly handled in `module_insertion_map.csv`. |
| Insertion map current                                | `git status content/immersion/module_insertion_map.csv`                       | Clean; matches the latest source modules.                            |
| Acceptance contract version                          | `git log -1 docs/content/immersion-content-targets.md`                        | Matches release tag. No uncommitted edits.                           |
| Backup verified                                      | `pg_restore --list "$BACKUP_DIR/$TS/full.dump" \| wc -l`                       | Non-zero line count; rollback runbook §1d passed.                    |
| Importer fixture tests                               | `pytest tests/scripts/`                                                       | Exit 0. Every importer's fixture round-trips cleanly.                |
| Smoke suite (full app)                               | `pytest -m smoke`                                                             | Exit 0.                                                              |

If any audit fails, fix the root cause before re-running. Never bypass
an audit — the importers and rollback steps assume each precondition
holds.

---

## 3. Required post-import row-count checks

Capture row counts immediately after each batch in §1. Record them in
the rollout report (`reports/staging_immersion_rollout.md` or
`reports/production_immersion_rollout.md`).

```sql
-- Per new lesson type — must hit the Section 1 / Section 2 minimums.
SELECT lesson_type, COUNT(*) AS cnt
  FROM lessons
 WHERE lesson_type IN (
   'dictation', 'writing_prompt', 'shadow_reading',
   'audio_fill_blank', 'translation', 'sentence_correction',
   'sentence_completion', 'collocation_matching', 'pronunciation',
   'idiom'
 )
 GROUP BY 1 ORDER BY 1;

-- Per-module saturation for slot-critical types — one row per module
-- present in DB, expect at least one of each per row.
SELECT m.cefr_level, COUNT(DISTINCT m.id) AS modules,
       SUM(CASE WHEN d.id IS NOT NULL THEN 1 ELSE 0 END) AS with_dictation,
       SUM(CASE WHEN w.id IS NOT NULL THEN 1 ELSE 0 END) AS with_writing,
       SUM(CASE WHEN s.id IS NOT NULL THEN 1 ELSE 0 END) AS with_shadow
  FROM modules m
  LEFT JOIN lessons d ON d.module_id = m.id AND d.lesson_type = 'dictation'
  LEFT JOIN lessons w ON w.module_id = m.id AND w.lesson_type = 'writing_prompt'
  LEFT JOIN lessons s ON s.module_id = m.id AND s.lesson_type = 'shadow_reading'
 GROUP BY m.cefr_level ORDER BY m.cefr_level;

-- Audio metadata gaps.
SELECT lesson_type, COUNT(*) AS missing_audio
  FROM lessons
 WHERE lesson_type IN ('listening_immersion', 'listening_quiz',
                       'dictation', 'audio_fill_blank', 'shadow_reading')
   AND (content->>'audio_url' IS NULL OR content->>'audio_url' = '')
 GROUP BY 1 ORDER BY 1;

-- Vocabulary enrichment coverage.
SELECT
  COUNT(*) FILTER (WHERE ipa_transcription IS NOT NULL) AS ipa,
  COUNT(*) FILTER (WHERE frequency_band   IS NOT NULL) AS freq,
  COUNT(*) FILTER (WHERE synonyms          IS NOT NULL) AS syn,
  COUNT(*) FILTER (WHERE antonyms          IS NOT NULL) AS ant,
  COUNT(*) FILTER (WHERE etymology         IS NOT NULL) AS etym
FROM collection_words;

SELECT COUNT(*) AS collocations FROM word_collocations;
SELECT COUNT(*) AS cultural_notes FROM cultural_notes;

-- SRS source tagging — must be 0 unresolved.
SELECT source, COUNT(*) FROM user_card_directions GROUP BY 1 ORDER BY 1;
SELECT COUNT(*) AS unresolved_source FROM user_card_directions
 WHERE source IS NULL;
```

Acceptance:

- New lesson type counts ≥ the minimums in
  `docs/content/immersion-content-targets.md` §1-2.
- `missing_audio = 0` outside documented exclusions
  (`content/immersion/listening_audio_exclusions.json`).
- `unresolved_source = 0`.
- Vocabulary enrichment ratios match the tier-1 targets reported by
  `scripts/report_vocabulary_enrichment.py`.

Save each query's output (psql `\g | tee`) to the rollout report.

---

## 4. Smoke-test URLs per lesson type

After §1 finishes, open one imported lesson of every type as a test
user (one per CEFR level when feasible) and verify the lesson renders,
grades, advances progress, and records XP under the expected source
from `LESSON_TYPE_TO_SOURCE` in `app/daily_plan/linear/xp.py`.

URL template (all curriculum lesson routes live under `/curriculum/`):

| Lesson type            | URL pattern                                                | XP source                            | Pass-answer check          |
| ---------------------- | ---------------------------------------------------------- | ------------------------------------ | -------------------------- |
| `dictation`            | `/curriculum/lesson/<lesson_id>/dictation`                 | `linear_curriculum_dictation`        | ≥80% word accuracy         |
| `audio_fill_blank`     | `/curriculum/lesson/<lesson_id>/audio-fill-blank`          | `linear_curriculum_audio_fill_blank` | Levenshtein typo tolerance |
| `translation`          | `/curriculum/lesson/<lesson_id>/translation`               | `linear_curriculum_quiz`             | Exact match + Lev≤1        |
| `sentence_correction`  | `/curriculum/lesson/<lesson_id>/sentence-correction`       | `linear_curriculum_quiz`             | Choose correct sentence    |
| `writing_prompt`       | `/curriculum/lesson/<lesson_id>/writing-prompt`            | `linear_curriculum_use`              | ≥min_words, ≥2 checklist   |
| `sentence_completion`  | `/curriculum/lesson/<lesson_id>/sentence-completion`       | `linear_curriculum_quiz`             | Second-half fill-in        |
| `collocation_matching` | `/curriculum/lesson/<lesson_id>/collocation-matching`      | `linear_curriculum_quiz`             | All pairs matched          |
| `shadow_reading`       | `/curriculum/lesson/<lesson_id>/shadow-reading`            | `linear_curriculum_use`              | Self-assess submit         |
| `pronunciation`        | `/curriculum/lesson/<lesson_id>/pronunciation`             | `linear_curriculum_use`              | Web Speech or self-assess  |
| `idiom`                | `/curriculum/lesson/<lesson_id>/idiom`                     | `linear_curriculum_vocabulary`       | Self-assess submit         |

Daily-plan slot smoke (one user per CEFR level, A1 → C1):

- `GET /api/daily-plan` returns `mode = 'linear'` and resolves a
  listening, writing, and speaking slot referencing imported lessons.
- `GET /api/daily-status` reports `srs_limit_reason` and the linear
  `chain_meta` consistent with the imported lessons.
- Completing a slot writes a `StreakEvent(event_type LIKE 'xp_linear%')`
  and increments `UserStatistics.total_xp`.

For graded types: submit one passing answer and one failing answer.
Both should round-trip without 500s. Failing answers must surface in
`quiz_error_log` where the lesson type writes to it (curriculum quiz
paths), and must not award XP for the failed attempt.

Record the lesson ids used for smoke in the rollout report. The
`docs/qa/immersion-lesson-smoke.md` template (Task 45) is the canonical
place to log these.

---

## 5. Rollback checkpoints

The rollout is a series of checkpoints. Each one is a known-good state
the rollback runbook can restore in isolation.

| Checkpoint | Restored to       | Restore path                                           | Triggers                                                            |
| ---------- | ----------------- | ------------------------------------------------------ | ------------------------------------------------------------------- |
| C0         | Pre-import        | Rollback runbook §1 backup `$TS` (full dump).          | Any §1 step fails before §1c finishes its first real write.         |
| C1         | After §1c         | Soft-disable slot-critical lessons (rollback §3a) or delete by `external_key` (rollback §4b). | Slot saturation fails post-§1c (`with_dictation`/`with_writing`/`with_shadow` short of contract). |
| C2         | After §1d         | Delete CEFR seed lessons by `external_key` (rollback §4b). User attempts on seeded lessons keep their rows but cascade-detached lessons → use soft-disable instead when attempts > 0. | Non-slot seed counts wrong or fixtures rejected post-import.        |
| C3         | After §1e         | Re-run audio metadata import with corrected JSON; do not touch `lessons` rows otherwise. Audio-only fields are overwriteable. | Audio audit reports missing or broken URLs outside the exclusions list. |
| C4         | After §1f         | Re-import vocabulary CSVs from the §1a backup (rollback §4d) or restore enrichment columns (rollback §2b). | Tier-1 enrichment percentages regress; malformed JSON detected in synonyms/antonyms. |
| C5         | After §1g         | Restore `source` column from CSV side-export (rollback §2e) or run `backfill_card_sources.py --revert`. | SRS source tagging mislabels a known card cohort.                   |
| C6         | After §1h         | Acceptance gate. If §1h fails, recover the affected checkpoint above. The full backup at `$TS` is the last-resort fallback. | Acceptance contract §6 not met.                                     |

Rules:

- **Never** restore user-generated tables from `$TS` (see rollback
  runbook §5a). The checkpoints above only touch the import surface.
- Prefer soft-disable over delete whenever a lesson already has
  `lesson_progress`, `user_lesson_progress`, `lesson_attempts`, or
  `lesson_feedback` rows.
- Record the checkpoint reached, the failure mode, and the chosen
  rollback path in the rollout report before re-attempting the import.

---

## 6. Sign-off

A rollout is signed off when every box below is checked in the rollout
report:

- [ ] Pre-import backup `$TS` captured and verified (rollback §1).
- [ ] All audits in §2 passed.
- [ ] All imports in §1 ran in order with `--dry-run` clean before real
      writes.
- [ ] Row-count queries in §3 recorded and within acceptance.
- [ ] Smoke URLs in §4 returned 200 and exercised pass/fail paths.
- [ ] Acceptance contract `docs/content/immersion-content-targets.md`
      §6 satisfied.
- [ ] No user-generated table touched outside the documented import
      surface.
- [ ] Rollback checkpoints in §5 logged; no open checkpoints awaiting
      rollback.

Cross-references:

- `docs/runbooks/immersion-data-rollback.md` — backup and rollback.
- `docs/content/immersion-content-targets.md` — acceptance contract.
- `content/immersion/module_insertion_map.csv` — module-by-module
  insertion anchors.
- `reports/` — rollout, audit, and gap reports referenced above.
