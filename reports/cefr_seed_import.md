# CEFR Seed Lesson Import Report

_Task 29 — Post-Immersion Content & Data Plan_
_Date: 2026-05-13_

## Summary

165 CEFR seed lessons imported across 7 new lesson types. All
types cover A1–C1 (5 lessons per level each); idiom covers B1–C1 only.
Second import run confirmed zero duplicates (all 165 rows → noop).

## Import counts (first run)

| lesson_type          | create | update | noop | skip_no_module | errors |
| -------------------- | ------ | ------ | ---- | -------------- | ------ |
| audio_fill_blank     | 25     | 0      | 0    | 0              | 0      |
| translation          | 25     | 0      | 0    | 0              | 0      |
| sentence_correction  | 25     | 0      | 0    | 0              | 0      |
| sentence_completion  | 25     | 0      | 0    | 0              | 0      |
| pronunciation        | 25     | 0      | 0    | 0              | 0      |
| collocation_matching | 25     | 0      | 0    | 0              | 0      |
| idiom                | 15     | 0      | 0    | 0              | 0      |
| **Total**            | **165**| 0      | 0    | 0              | 0      |

## Idempotency check (second run)

| lesson_type          | create | update | noop |
| -------------------- | ------ | ------ | ---- |
| audio_fill_blank     | 0      | 0      | 25   |
| translation          | 0      | 0      | 25   |
| sentence_correction  | 0      | 0      | 25   |
| sentence_completion  | 0      | 0      | 25   |
| pronunciation        | 0      | 0      | 25   |
| collocation_matching | 0      | 0      | 25   |
| idiom                | 0      | 0      | 15   |
| **Total**            | 0      | 0      | **165** |

All entries were noop on the second run — no duplicates created.

## Content placement

Each CEFR seed lesson was placed at the end of module 1–5 of its
respective CEFR level. Lesson numbers are appended after existing
content; no existing lessons were shifted.

- audio_fill_blank lesson IDs: 1230–1254
- translation lesson IDs: 1255–1279
- sentence_correction lesson IDs: 1280–1304
- sentence_completion lesson IDs: 1305–1329
- pronunciation lesson IDs: 1330–1354
- collocation_matching lesson IDs: 1355–1379
- idiom lesson IDs: 1380–1394

## Source files

- `content/immersion/audio_fill_blank_lessons.json` (25 entries)
- `content/immersion/translation_lessons.json` (25 entries)
- `content/immersion/sentence_correction_lessons.json` (25 entries)
- `content/immersion/sentence_completion_lessons.json` (25 entries)
- `content/immersion/pronunciation_lessons.json` (25 entries)
- `content/immersion/collocation_matching_lessons.json` (25 entries)
- `content/immersion/idiom_lessons.json` (15 entries)

## Notes

- Content files were updated before import to add the required
  `module_number` field derived from the existing `lesson_number_hint`
  field. The importer requires `module_number` for module resolution.
- Each file was imported in a separate session to avoid within-batch
  lesson-number conflicts (the planner resolves next_lesson_number
  per-session, not per-batch).
- All entries used stable `external_key` values for idempotent
  re-runs. Keys follow the pattern
  `immersion:<type>:<level>:<nn>:<slug>`.
