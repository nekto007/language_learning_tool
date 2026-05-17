# content/immersion

Source-of-truth content for the immersion rollout described in
`docs/plans/2026-05-11-post-immersion-content-data-plan.md`. Everything
in this directory is treated as data — it is reviewed by humans, versioned
in git, and applied to the database **only** by the idempotent importers
under `scripts/import_immersion_lessons.py` and
`scripts/import_lesson_audio_metadata.py`.

Companion documents:

- `docs/content/immersion-content-targets.md` — acceptance contract
  (per-module slot saturation, CEFR seed minimums, audio quality
  requirements).
- `docs/content/lesson-content-schemas.md` — payload schemas per lesson
  type (created in Task 9).
- `docs/runbooks/immersion-data-rollback.md` — backup and rollback
  procedure that must be run before any production import.
- `reports/module_insertion_map.md` — narrative for the CSV anchor map.

## What belongs here

| File                                      | Purpose                                                              | Owner       |
| ----------------------------------------- | -------------------------------------------------------------------- | ----------- |
| `module_insertion_map.csv`                | Canonical insertion anchors per source module for slot-critical lessons. | Content     |
| `module_map.csv`                          | Source-to-DB module identity export from `scripts/export_curriculum_module_map.py`. | Generated   |
| `dictation_lessons.json`                  | Per-module dictation lessons (77 rows, one per source module).       | Content     |
| `writing_prompt_lessons.json`             | Per-module writing prompts (77 rows).                                | Content     |
| `shadow_reading_lessons.json`             | Per-module shadow reading lessons (77 rows).                         | Content     |
| `audio_fill_blank_lessons.json`           | CEFR seed for `audio_fill_blank` (≥5 per level).                     | Content     |
| `translation_lessons.json`                | Standalone translation seed (≥5 per level).                          | Content     |
| `sentence_correction_lessons.json`        | Sentence-correction seed (≥5 per level).                             | Content     |
| `sentence_completion_lessons.json`        | Sentence-completion seed (≥5 per level).                             | Content     |
| `pronunciation_lessons.json`              | Pronunciation seed (≥5 per level).                                   | Content     |
| `collocation_matching_lessons.json`       | Collocation-matching seed; pairs sourced from `content/vocabulary/collocations.csv`. | Content |
| `idiom_lessons.json`                      | B1-C1 idiom seed (≥15 total).                                        | Content     |
| `listening_immersion_audio.json`          | Audio metadata overlay for the 77 existing `listening_immersion` lessons. | Content     |
| `listening_quiz_audio.json`               | Audio metadata overlay for the 77 existing `listening_quiz` lessons. | Content     |
| `listening_audio_exclusions.json`         | Explicitly excluded lessons + reason; audits drop these from missing-audio counts. | Content     |
| `staging_smoke_lessons.json`              | Smoke fixtures marked `environment=staging`; never imported to prod. | Content     |

Anything else (drafts, working CSVs, raw exports) lives outside the repo.
Do not check in scratch files here — the importers will refuse files they
do not recognize.

## What does NOT belong here

- Audio binaries (`.mp3`, `.wav`, `.m4a`). Only metadata referencing
  `audio_url` belongs in JSON. Audio files live in static storage and
  are referenced by stable HTTPS or repo-relative `/static/audio/...`
  paths verified by `app/cli/content_commands.py`.
- User-generated data (`UserWritingAttempt`, `ListeningAttempt`,
  `PronunciationAttempt`, `UserReadingSession`). User tables are
  never seeded from this directory in production.
- Database dumps or migration SQL — those belong with Alembic.
- Vocabulary metadata (IPA, frequency bands, synonyms, etymology,
  collocations, cultural notes). Those live in `content/vocabulary/`.

## File format conventions

All lesson files are JSON arrays. Each element is one lesson object that
the importer maps to a `lessons` row plus its `content` JSON payload.

Required top-level keys on every lesson:

| Key            | Type    | Description                                                                 |
| -------------- | ------- | --------------------------------------------------------------------------- |
| `external_key` | string  | Stable id used for idempotent upsert. **Never reuse across lessons.**       |
| `level`        | string  | CEFR level (`A1` / `A2` / `B1` / `B2` / `C1`).                              |
| `module_number`| integer | 1-based module order within the level. Matches `module_insertion_map.csv`.  |
| `lesson_type`  | string  | One of the implemented types listed in the section above.                   |
| `title`        | string  | Russian title shown in lesson lists.                                        |
| `title_en`     | string  | English working title for content review.                                   |
| `content`      | object  | Lesson payload validated by `LessonContentValidator`.                       |

Optional but recommended:

- `lesson_number` — explicit insertion index. Omit to let the importer
  resolve it from `module_insertion_map.csv`.
- `description` — short human summary used in admin listings.
- `tags` — list of strings for content reporting.
- `environment` — `staging` to keep the fixture out of production
  imports (used only in `staging_smoke_lessons.json`).

## Stable id (`external_key`) conventions

`external_key` is the only thing that makes the importer idempotent. It
must be deterministic, human-readable, and globally unique across all
immersion content. Choose the key once, never rename it.

Format:

```
{lesson_type}:{level}:{module_number:02d}:{slug}
```

Examples:

- `dictation:A1:01:greetings` — per-module dictation, A1 module 1.
- `writing_prompt:B2:07:work_email` — per-module writing prompt.
- `shadow_reading:C1:13:negotiation` — per-module shadow reading.
- `audio_fill_blank:B1:seed:weather_forecast` — CEFR seed (no
  per-module anchor; use `seed` in the module slot).
- `idiom:C1:seed:break_the_ice` — idiom seed.

Slug rules:

- Lowercase ASCII, words separated by `_`. No accents, no spaces.
- Stable across content edits — never rename the slug to fix a typo
  in the title. The slug is the durable contract with the DB row.
- Short. Aim for ≤40 characters total.

Per-module lesson keys (slot-critical types) **must** match the
`(level, module_number)` from `module_insertion_map.csv`. The importer
will reject mismatches before writing.

CEFR-seed keys use `seed` in the module slot to make grep'ing for
non-per-module lessons trivial.

## Workflow

1. Author edits the JSON file directly. PR review is the content
   review.
2. Run the local validator:
   ```bash
   python scripts/import_immersion_lessons.py --dry-run \
     content/immersion/<file>.json
   ```
   The script exits non-zero on any validator failure and writes
   nothing.
3. Apply to staging:
   ```bash
   python scripts/import_immersion_lessons.py content/immersion/<file>.json
   ```
4. Re-run with `--dry-run`. The second run must report `0 changes` —
   that is the idempotency contract from
   `docs/content/immersion-content-targets.md` Section 6.
5. Capture row counts and diffs in `reports/<lesson_type>_import.md`.

## Cross-references

- Importer: `scripts/import_immersion_lessons.py`
- Audit: `scripts/audit_immersion_data.py` → `reports/immersion_data_audit.md`
- Gap report: `scripts/report_immersion_gaps.py` → `reports/immersion_gap_report.md`
- Audio audit: `scripts/audit_existing_listening_payloads.py` →
  `reports/existing_listening_payloads.md`
- Acceptance contract: `docs/content/immersion-content-targets.md`
- Rollback: `docs/runbooks/immersion-data-rollback.md`
