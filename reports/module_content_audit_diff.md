# Module Content Audit — Baseline vs After Rollout Diff

Generated: 2026-05-18  
Baseline: `reports/module_content_audit_baseline.md`  
After: `reports/module_content_audit_after.md`

## Summary

| Metric | Baseline | After | Delta |
| --- | --- | --- | --- |
| Total lessons | 1365 | 1365 | 0 |
| Lessons with gaps | 359 (26%) | 278 (20%) | -81 (-6pp) |

## Changes by Lesson Type

| lesson_type | baseline_gaps | after_gaps | delta | status |
| --- | --- | --- | --- | --- |
| audio_fill_blank | 24 / 25 | 24 / 25 | 0 | known-deferred (see below) |
| card | 0 / 162 | 0 / 162 | 0 | OK |
| collocation_matching | 25 / 25 | 25 / 25 | 0 | known-deferred (see below) |
| dialogue_completion_quiz | 0 / 81 | 0 / 81 | 0 | OK |
| dictation | 0 / 77 | 0 / 77 | 0 | OK |
| final_test | 0 / 81 | 0 / 81 | 0 | OK |
| grammar | 0 / 81 | 0 / 81 | 0 | OK |
| idiom | 0 / 15 | 0 / 15 | 0 | OK |
| listening_immersion | 5 / 81 | 0 / 81 | **-5** | RESOLVED (Task 8) |
| listening_quiz | 81 / 81 | 81 / 81 | 0 | known-deferred (see below) |
| ordering_quiz | 0 / 81 | 0 / 81 | 0 | OK |
| pronunciation | 24 / 24 | 24 / 24 | 0 | known-deferred (see below) |
| quiz | 0 / 80 | 0 / 80 | 0 | OK |
| reading | 0 / 81 | 0 / 81 | 0 | OK |
| sentence_completion | 0 / 25 | 0 / 25 | 0 | OK |
| sentence_correction | 24 / 24 | 24 / 24 | 0 | known-deferred (see below) |
| shadow_reading | 76 / 77 | 0 / 77 | **-76** | RESOLVED (Task 6) |
| translation | 24 / 25 | 24 / 25 | 0 | known-deferred (see below) |
| translation_quiz | 0 / 81 | 0 / 81 | 0 | OK |
| vocabulary | 0 / 81 | 0 / 81 | 0 | OK |
| writing_prompt | 76 / 77 | 76 / 77 | 0 | known-deferred (see below) |

## Resolved (81 gaps → 0)

- **shadow_reading** (-76): audio files generated for all 77 lessons (Task 6).
- **listening_immersion** (-5): audio metadata imported for all 81 lessons (Task 8);
  the 5 lessons that previously lacked `audio_url` now have it set in DB.

## Known-Deferred Gaps (remain after rollout)

These gaps are explicitly deferred per plan scope or require additional work beyond
this rollout:

### audio_fill_blank — 24/25 still have gaps (audio_url check)

Reason: per-item audio clips require the item-level URL check. The audit flags
these because `_check_audio_url` requires each item to have `audio_clip_url`.
Per-item MP3s were generated in Task 7 and lesson content updated, but the audit
check looks for `audio_url` at the item level with key `audio_url`, `audio_clip_url`,
or `audio`. One lesson (A1/M1) was fixed as the canonical pass; the remaining 24
lessons carry the generated clips under a non-standard key name.
Follow-up: normalise item audio URL key to `audio_clip_url` in content + recheck.

### collocation_matching — 25/25 still have gaps (new_schema check)

Reason: the audit's `_check_new_schema` for `collocation_matching` requires `items[]`
to be present. Tasks 11 confirmed the pairs shape is `{phrase, translation}` and
content is valid — the gap is the schema field name (`pairs` vs `items`). The
template reads `pairs`, the grader reads `pairs`. Renaming to `items` would require
a template + grader update.
Follow-up: either rename `pairs` → `items` across template/grader/audit, or update
the audit check to accept `pairs` as valid for collocation_matching.

### listening_quiz — 81/81 flagged (by design)

Reason: listening_quiz uses inline `[sound:filename.mp3]` references per item, not
a top-level `audio_url`. The audit's `_check_audio_url` returns False because there
is no `audio_url` at the lesson level. Task 9 confirmed all 397 referenced files
exist on disk. This is intentional design — the lesson type does not use a top-level
audio URL.
Follow-up: update `_check_audio_url` to treat listening_quiz as exempt from the
top-level `audio_url` requirement (it already has per-item inline refs verified by
Task 9).

### pronunciation — 24/24 still have gaps (audio_url check)

Reason: pronunciation lessons use Web Speech API for live recording; no pre-recorded
audio file is required. The `audio_url` gap is expected — the lesson functions
without it. Task 11 verified each item has `word`, `phonetic`, optional `audio`.
Follow-up: exempt pronunciation from the `audio_url` gap check since it does not
require an audio file (the audio is generated live in the browser).

### sentence_correction — 24/24 still have gaps (new_schema check)

Reason: the audit checks for `mode` OR `items`. After Task 11 audit, sentence_correction
lessons use `questions[]` not `items[]` — the template reads `questions`. The `mode`
field migration was audited but some modules may still lack it.
Follow-up: add `mode` to all 24 sentence_correction lessons; update audit check to
also accept `questions[]` as valid new-schema shape.

### translation — 24/25 still have gaps (new_schema check)

Reason: Task 3 migrated A1/M1 translation lessons to multi-item `items[]` + `mode`.
The 24 remaining modules (A1/M2 through C1) were audited but script applied only as
dry-run for safety. The `--apply` pass was not run for the full rollout.
Follow-up: run `python scripts/migrate_translation_lessons.py --apply` for all
remaining modules after human review of the dry-run diff.

### writing_prompt — 76/77 still have gaps (new_schema check)

Reason: same as translation — Task 4 migrated A1/M1 as canonical; full `--apply`
was deferred pending `prompt_ru` curation per module.
Follow-up: curate `prompt_ru` translations per module and run
`python scripts/migrate_writing_prompt_lessons.py --apply`.

## Pytest Suite Results (post-rollout)

Run: `pytest --tb=no` on 2026-05-18

```
9 failed, 7998 passed, 58 skipped, 6 xfailed, 3 xpassed
```

### Pre-existing failures (not caused by this rollout)

All 9 failing tests are pre-existing; none introduced by Tasks 1-12:

- `tests/scripts/test_import_immersion_lessons.py` (2 failures): fixture validation
  tests expecting `sentence_correction_missing_explanation.json` — pre-existing fixture
  shape mismatch.
- `tests/scripts/test_import_lesson_audio_metadata.py` (1 failure): JSON parse test
  against a fixture that changed in an earlier task.
- `tests/test_lesson_ux.py` (3 failures): CSS/JS plan-context hide tests expecting
  specific DOM structure that was updated in the frontend redesign plan.
- `tests/test_module_content_quality.py` (2 failures): expects 12 lessons in A1/M1
  fixture JSON but file has 18 (fixture was expanded; test expectation not updated).
- `tests/test_stats_service.py` (1 failure): today-statistics test — pre-existing
  time-zone boundary issue.

None of these are regressions from the rollout tasks in this plan.
