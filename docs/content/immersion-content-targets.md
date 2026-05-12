# Immersion Content Target Matrix

_Authoring contract for Task 6 of `docs/plans/2026-05-11-post-immersion-content-data-plan.md`._

This document is the single acceptance contract used by every importer,
audit, and gap report in the immersion rollout (Tasks 9-50). All target
numbers are derived from the verified state captured on 2026-05-11:

- 77 canonical source modules in `module_completed/fixed/`
  (A1=16, A2=22, B1=14, B2=12, C1=13).
- 76 modules present in the local DB snapshot — the import path must
  reconcile this delta before content goes in.
- 0 lessons for every implemented new lesson type in the DB.
- 0 audio URLs on the 77 source `listening_immersion` and 77
  `listening_quiz` lessons.
- 0 rows filled across all six vocabulary metadata columns
  (`ipa_transcription`, `frequency_band`, `synonyms`, `antonyms`,
  `etymology`, plus `word_collocations` and `cultural_notes`).
- 0/142 `user_card_directions.source` filled.

## 1. Per-Module Coverage — Slot-Critical Lessons

These three lesson types drive the linear daily-plan extension slots
(`listening`, `writing`, `speaking`). The plan must be able to find one
of each in every source module that is present in the target DB.

| Lesson type      | Linear slot kind | XP source                  | Required per module | Insertion anchor                      |
| ---------------- | ---------------- | -------------------------- | ------------------- | -------------------------------------- |
| `dictation`      | `listening`      | `linear_curriculum_dictation`     | 1                   | After `listening_quiz`, before `listening_immersion` |
| `writing_prompt` | `writing`        | `linear_curriculum_use`           | 1                   | After `translation_quiz`, before `final_test`        |
| `shadow_reading` | `speaking`       | `linear_curriculum_use`           | 1                   | Adjacent to `listening_immersion`                    |

Acceptance numbers (all measured by `scripts/audit_immersion_data.py`):

- For every CEFR level, the count of modules with at least one
  `dictation` lesson must equal the source-module count for that level
  (A1=16, A2=22, B1=14, B2=12, C1=13). Same for `writing_prompt` and
  `shadow_reading`.
- For modules present in source but not in DB, the importer skips and
  reports them. The DB-side acceptance count is `min(source, DB)` per
  level — never a hidden zero.
- `final_test` must remain the last lesson of every module unless an
  insertion exception is explicitly recorded in
  `content/immersion/module_insertion_map.csv`.
- No imported slot-critical lesson may share `lesson_number` with any
  existing lesson in the same module (importer rejects collisions).

## 2. CEFR Seed Coverage — Non-Slot Lesson Types

These types do not gate the linear daily plan, but they back vocabulary,
grammar, and pronunciation flows. They need broad CEFR coverage, not
per-module saturation.

| Lesson type            | XP source                                | Minimum per CEFR level | Total minimum | Notes                                              |
| ---------------------- | ---------------------------------------- | ---------------------- | ------------- | -------------------------------------------------- |
| `audio_fill_blank`     | `linear_curriculum_audio_fill_blank`     | 5                      | 25            | Free-text + options mode; typo-tolerant grading    |
| `translation`          | `linear_curriculum_quiz`                 | 5                      | 25            | RU → EN; avoid overlap with `translation_quiz`     |
| `sentence_correction`  | `linear_curriculum_quiz`                 | 5                      | 25            | Cover article / tense / order / preposition / agreement |
| `sentence_completion`  | `linear_curriculum_quiz`                 | 5                      | 25            | Second-half fill-in tied to module grammar         |
| `pronunciation`        | `linear_curriculum_use`                  | 5                      | 25            | Include fallback-friendly words; minimal pairs     |
| `collocation_matching` | `linear_curriculum_quiz`                 | 5                      | 25            | Pull pairs from `content/vocabulary/collocations.csv` |
| `idiom`                | `linear_curriculum_vocabulary`           | B1/B2/C1: ≥5 each      | 15            | A1/A2 not required initially                       |

Acceptance numbers:

- Each non-slot type ships with at least the listed count of valid,
  imported lessons after a second `--dry-run` shows zero pending writes.
- Every imported lesson references a CEFR level whose module exists in
  the target DB.
- Lesson content validates through `LessonContentValidator` before
  insertion. The importer writes nothing on partial failure.

## 3. Audio Quality Requirements

These apply to every lesson type that exposes audio: `listening_quiz`,
`listening_immersion`, `dictation`, `audio_fill_blank`, `shadow_reading`,
and optionally `pronunciation` / `idiom` items.

Required fields per audio lesson:

- `audio_url` — absolute HTTPS URL or a stable repository-relative
  static path (e.g. `/static/audio/…`). The URL must respond `200` with
  `Content-Type: audio/*` when checked by `app/cli/content_commands.py`.
- `duration_seconds` — integer or float seconds; must be plausible for
  the transcript length (heuristic: between transcript word count × 0.25
  and word count × 0.9).
- Transcript / `text` field — non-empty; aligned with the audio content
  (audit only checks presence, not transcription accuracy).

Optional but recommended:

- `voice` or `speaker` tag for content moderation.
- `language` defaulting to `en`.
- Item-level audio refs for `listening_quiz` where the template renders
  per-item clips.

Exclusion rule:

- A lesson may be exempt from audio requirements only if it is listed
  in `content/immersion/listening_audio_exclusions.json` with a written
  reason. Audits then drop it from the missing-audio count instead of
  flagging it.

CEFR transcript length bands (target, not hard cap):

| Level | Words per transcript | Speaking rate target  |
| ----- | -------------------- | --------------------- |
| A1    | 20-50                | ≤110 wpm, literal     |
| A2    | 40-90                | ≤120 wpm, literal     |
| B1    | 70-140               | 120-150 wpm, natural  |
| B2    | 120-200              | 140-170 wpm, natural  |
| C1    | 160-260              | 150-180 wpm, connected |

## 4. Vocabulary Metadata Coverage Targets

Targets apply to the priority tiers exported by
`scripts/export_vocabulary_priority.py` (Task 35). Coverage rolls up
from a tiered backlog rather than the full 24,853-row `collection_words`
table.

| Field                              | Priority tier 1 | Priority tier 2 | Priority tier 3 | Notes                                        |
| ---------------------------------- | --------------- | --------------- | --------------- | -------------------------------------------- |
| `ipa_transcription`                | 100%            | 80%             | 40%             | No surrounding slashes in stored value       |
| `frequency_band` (1 / 2 / 3)       | 100%            | 90%             | 60%             | Values restricted to `{1, 2, 3}`             |
| `synonyms` (JSON list)             | 80%             | 50%             | 20%             | Reject malformed list values                 |
| `antonyms` (JSON list)             | 60%             | 30%             | 10%             | Only where semantically clear                |
| `word_collocations` (≥2 per word)  | 80% for A2-B2   | 50% for A2-B2   | n/a             | Upsert by `word_id + collocation_phrase`     |
| `etymology` (short note)           | 50%             | 20%             | 10%             | Concise; no academic prose                   |
| `cultural_notes`                   | Idioms + phrasal verbs + politeness terms covered first | — | — | Tied to UI render check                      |

Acceptance numbers:

- Tier-1 priority words have **no** empty optional sections in the
  vocabulary card UI for `ipa_transcription` and `frequency_band`.
- Vocabulary lessons hide optional sections cleanly when fields are
  empty (verified by `tests/curriculum/test_vocabulary_lessons.py`).
- `scripts/report_vocabulary_enrichment.py` breaks coverage down by
  CEFR level and priority tier (Task 43).

## 5. SRS Source Tag Coverage

- All 142 existing rows in `user_card_directions` must have a non-null
  `source` after `scripts/backfill_card_sources.py` runs (Task 42).
- Inference order:
  1. `lesson_vocab` when the card links to a curriculum word.
  2. `book_reading` when the card links to a book/course import.
  3. `manual` for ambiguous remainders, with the dry-run report
     listing the unresolved count.
- Future writes set `source` at creation; this matrix tracks only the
  one-time backfill.

## 6. Production-Readiness Acceptance Criteria

A rollout is acceptance-ready when **all** of the following hold:

1. **Slot saturation.**
   - `dictation`, `writing_prompt`, and `shadow_reading` exist in
     every DB-resident source module (per Section 1).
   - The linear daily plan resolves a listening slot, writing slot,
     and speaking slot for at least one current user per CEFR level
     (smoke test in Task 46).
2. **Non-slot seed coverage.**
   - Each of the seven non-slot lesson types reaches its Section 2
     minimum, verified by `scripts/report_immersion_gaps.py`.
3. **Audio integrity.**
   - 0 audio lessons missing `audio_url` outside the documented
     exclusions list (Section 3).
   - 0 broken audio URLs reported by the audio audit CLI command.
4. **Vocabulary enrichment.**
   - Tier-1 priority words hit the Section 4 percentages for IPA and
     frequency band.
   - Vocabulary-lesson UI tests pass with both filled and empty data
     paths.
5. **SRS sourcing.**
   - 0/142 unresolved rows in `user_card_directions.source`.
6. **Idempotency.**
   - Every importer reports `0 changes` on its second consecutive
     `--dry-run` pass against the same data.
7. **Smoke tests.**
   - One imported lesson of every new type opens, submits a passing
     answer, submits a failing answer where applicable, advances
     progress, and records XP under the expected source from
     `LESSON_TYPE_TO_SOURCE` in `app/daily_plan/linear/xp.py`.
8. **Operational readiness.**
   - Staging rollout report (`reports/staging_immersion_rollout.md`)
     exists with final row counts.
   - Backup + rollback runbook
     (`docs/runbooks/immersion-data-rollback.md`) is referenced from
     the release notes.

Failing any of the above blocks production rollout. The block list
above maps 1:1 to Tasks 45-50; nothing else is acceptance-gating.
