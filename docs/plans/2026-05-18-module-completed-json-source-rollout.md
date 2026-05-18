# Roll high-quality lesson additions into `module_completed/fixed` JSON

## Overview

The 2026-05-18 module-improvements rollout was DB-first: it audited and patched
`Lessons.content`, generated audio, and produced reports. That improved the local
runtime state, but it did **not** make `module_completed/fixed/*.json` the portable
source of truth for production transfer.

This plan closes that gap. The deliverable is a complete, production-transferable
set of source module JSON files under `module_completed/fixed/`, with the missing
high-quality lesson types added to each module using
`module_A1_1_greetings.json` as the canonical reference.

Primary outcome:
- `module_completed/fixed/module_*.json` contains the upgraded lesson sequence and
  content payloads.
- Each file can be reviewed, committed, copied, and imported without relying on
  local DB-only mutations.
- Audio references in JSON point to existing static assets and are covered by an
  asset manifest.

Scope: all current source modules in `module_completed/fixed/` (A1, A2, B1, B2,
C1). A1/M1 is the canonical sample and should be used as the quality bar, not
blindly overwritten.

## Context

### Why this is a separate plan

The previous completed plan explicitly stated that live lesson content lived in
`Lessons.content` and that the DB was the source of truth. That was useful for
runtime behavior, but it is inconvenient for production transfer because local DB
updates and ignored audio/report files do not travel cleanly through git.

This plan supersedes the previous plan only for **portable JSON source-of-truth**
work. The previous plan remains the history for DB/content/audio rollout work;
this plan defines the source-file artifact that should be reviewed and moved to
production.

For this plan, `module_completed/fixed/` becomes the portable source layer for
curriculum modules. DB state may be used for reconciliation, but JSON files are
the artifact that must end up correct.

### Current observed state

Snapshot from disk on 2026-05-18:

| Metric | Value |
| --- | --- |
| Source files in `module_completed/fixed/` | 77 |
| Files with 18 lessons | 1 |
| Files with 12 lessons | 76 |
| Already-canonical candidate | `module_A1_1_greetings.json` |
| Needs-work files | every other source module |

Current lesson-type distribution across source JSON files:

| lesson type | count |
| --- | ---: |
| `vocabulary` | 77 |
| `flashcards` | 154 |
| `grammar` | 77 |
| `reading` | 77 |
| `listening_quiz` | 77 |
| `dialogue_completion_quiz` | 77 |
| `ordering_quiz` | 77 |
| `translation_quiz` | 77 |
| `listening_immersion` | 77 |
| `final_test` | 77 |
| `quiz` | 76 |
| `audio_fill_blank` | 1 |
| `collocation_matching` | 1 |
| `dictation` | 1 |
| `sentence_completion` | 1 |
| `shadow_reading` | 1 |
| `translation` | 1 |
| `writing_prompt` | 1 |

These numbers must be refreshed by Task 1 and written to
`reports/module_completed_json_gap_report.md`; the table above is only the
initial planning snapshot.

- Existing helper scripts already point in the right direction:
  - `scripts/merge_immersion_into_source_module.py`
  - `scripts/sync_source_module_with_db.py`
  - `scripts/audit_immersion_data.py`
  - `scripts/report_immersion_gaps.py`
- The previous DB/audio rollout produced useful source material:
  - `content/immersion/*_lessons.json`
  - `content/immersion/listening_immersion_audio.json`
  - generated audio under `app/static/audio/...`
  - audit reports under `reports/`

### Target lesson sequence

Use this sequence as the default canonical order. Some lesson types are optional
only when the source content genuinely does not exist for that level/module; every
exception must be documented in the final report.

1. `vocabulary`
2. first `flashcards` / `card`
3. `collocation_matching`
4. `grammar`
5. `sentence_completion`
6. `sentence_correction`
7. `quiz` if the module already has a grammar practice quiz
8. `reading`
9. `idiom` for B1+ modules where idiom content exists
10. `listening_quiz`
11. `audio_fill_blank`
12. `dictation`
13. `dialogue_completion_quiz`
14. `ordering_quiz`
15. `shadow_reading`
16. second `flashcards` / `card`
17. `translation_quiz`
18. `translation`
19. `listening_immersion`
20. `writing_prompt`
21. `final_test`

A1/M1 may remain at 18 lessons if some intermediate slots are intentionally not
used. The goal is not an identical count everywhere; the goal is a complete,
high-quality pedagogical sequence with no missing intended slots.

### Progression model

Do not copy A1/M1 difficulty into every module. A1/M1 is the structural and UX
reference; content difficulty must grow by CEFR level and within each level by
module order.

The source JSON should show progression along these axes:
- **Vocabulary load:** more words, less concrete vocabulary, more collocations
  and register-sensitive phrases as modules advance.
- **Sentence complexity:** A1 starts with short single-clause sentences; A2 adds
  routine past/future and connectors; B1 adds narrative/opinion paragraphs; B2
  adds abstraction, reporting, passive, conditionals, and nuance; C1 adds
  synthesis, register, idioms, and argumentative/professional language.
- **Task openness:** early modules use selection/guided formats and visible
  hints; later modules reduce hints, require freer production, and use stricter
  rubrics.
- **Listening/reading length:** audio/text length and density should increase
  gradually. Later modules should not reuse short A1-style scripts.
- **Distractor quality:** higher levels need plausible distractors and near
  synonyms, not obvious wrong options.
- **Review continuity:** later modules may reuse earlier grammar/vocabulary as
  background, but the main target should be the current module's skill.

Minimum progression ladder:

| Level band | Expected content difficulty |
| --- | --- |
| A1 early | survival phrases, `be`, present simple basics, concrete nouns, short prompts, heavy scaffolding |
| A1 late / A2 early | routines, basic past/future, simple comparisons, short dialogues, guided production |
| A2 late | travel/shopping/social scenarios, longer dialogues, more connectors, fewer hints |
| B1 | narratives, opinions, modals, conditionals, paragraph writing, mixed review |
| B2 | abstract topics, argumentation, reported speech, passive, nuanced collocations, open/rubric tasks |
| C1 | register control, idioms, synthesis, professional/academic framing, longer and denser input |

Within each level, modules should trend upward on at least two measurable
dimensions: text/audio length, vocabulary density, grammar complexity, reduced
hint density, freer response mode, or distractor plausibility. Any exception must
be documented in `reports/module_completed_json_quality_review.md`.

## Quality Bar

No placeholder lessons. Every inserted or rewritten lesson must be reviewable by
a learner and useful on its own.

Quality requirements by type:
- `collocation_matching`: phrases must come from module vocabulary or natural
  high-frequency pairings; shape is `{phrase, translation}`.
- `reading`: text length, vocabulary band, grammar density, and comprehension
  prompts must match the module level; later modules should use denser texts and
  less translation scaffolding than earlier modules.
- `sentence_completion`: prompts must be CEFR-appropriate and accept
  alternatives where natural.
- `sentence_correction`: every item needs an explanation and `mode`; avoid
  ambiguous corrections.
- `audio_fill_blank`: each item has a full natural sentence, correct answer,
  alternatives where useful, and `audio_clip_url`.
- `dictation`: use `audio_text`, transcript/gap text where supported, and an
  existing MP3 path.
- `shadow_reading`: use natural text at the module's CEFR level, with
  translation and audio.
- `translation`: use multi-item `items[]`, `mode`, alternatives, and hints where
  helpful.
- `writing_prompt`: curated `prompt_ru`, `min_sentences`, checklist, target
  phrases, and hint words. Do not machine-translate blindly.
- `listening_immersion`: `audio_url`, transcript, translation, and duration
  metadata if available.
- `final_test`: cover the added module skills; no stub phrasing like
  "Сделайте вопрос"; matching pairs use a display-friendly shape.

## Development Approach

- **JSON-first.** Update `module_completed/fixed/*.json`; then reconcile DB from
  JSON, not the other way around.
- **Stable lesson identity before renumbering.** Source-local `id`/`number`/`order`
  are presentation/order fields, not import identity. Import/diff tooling must
  key lessons by stable `content.external_key` or an explicit source key; changing
  `number` must not silently mutate an existing DB lesson that has user progress.
- **Dry-run by default.** All scripts must support `--dry-run` and `--apply`.
- **Pilot before bulk.** Complete one representative module per CEFR level
  (A1/A2/B1/B2/C1) before batch-applying the rest.
- **Batchable but reviewable.** Generate per-module diffs and a report before
  applying.
- **Human quality gate.** Scripts may insert structured lessons, but ambiguous
  text, writing prompts, translation alternatives, and final-test coverage need
  manual review.
- **Reuse existing validators.** New source validators should call
  `app/curriculum/validators.py` schemas and add only source-specific checks
  (ordering, audio refs, placeholders, progression, DB diff).
- **Idempotent.** Re-running the merge/renumber/validate scripts should produce
  no changes after a successful apply.
- **Portable assets.** Audio files referenced by JSON need either tracked files,
  a manifest, or a documented copy step for production.

## Implementation Steps

### Task 0: Reconcile A1/M1 canonical reference

Files:
- Create: `reports/module_completed_a1m1_reconciliation.md`
- Modify only if drift exists: `module_completed/fixed/module_A1_1_greetings.json`

- [x] Compare `module_completed/fixed/module_A1_1_greetings.json` against the
      current local DB lessons for A1/M1.
- [x] Check all content-sensitive fields from the previous rollout:
      translation `items[]` + `mode`, writing_prompt `prompt_ru` /
      `min_sentences` / `template` / `hint_words` / `target_phrases` /
      `min_checklist` / `mode`, sentence_correction `mode`,
      audio_fill_blank item audio, dictation gap/transcript fields,
      final_test transformation phrasing and matching pair shape.
- [x] If DB and JSON differ, dump the approved DB shape back into the source JSON
      before treating A1/M1 as the canonical reference.
- [x] Preserve source-local lesson IDs as 1..N and ensure every new-style lesson
      has a stable `content.external_key`.
- [x] Document any intentional drift and the reason. No later task may use A1/M1
      as a reference until this report is complete.

### Task 1: Baseline audit of source JSON vs canonical target

Files:
- Create: `scripts/audit_module_completed_json_gaps.py`
- Create: `reports/module_completed_json_gap_report.md`

- [x] Read every `module_completed/fixed/module_*.json`.
- [x] Recompute and report the current-state survey: file count, lesson-count
      buckets, lesson-type Counter, already-canonical modules, and needs-work
      modules.
- [x] Compare each module's lesson sequence against the canonical target and
      A1/M1 reference.
- [x] Report missing lesson types, duplicate types, invalid order/id/number
      fields, missing content fields, and missing audio references.
- [x] Report progression gaps: A1-style content reused in higher levels, modules
      whose text/audio length drops sharply without reason, overly guided tasks
      in B2/C1, or missing current-module grammar/vocabulary focus.
- [x] Compare against local DB lessons where available and mark DB-only lessons
      that are absent from source JSON. (DB path implemented in
      `audit_module_completed_json_gaps._audit_db`; when run with `--no-db` the
      report records `db_error`. Local DB run is left to operators.)
- [x] Output a per-module heatmap and a per-file action list.
- [x] Add tests for the audit script using small fixture modules.

### Task 2: Define source JSON contract and import expectations

Files:
- Create: `docs/design/module-source-json-contract.md`
- Modify: `content/immersion/README.md`

- [ ] Document the canonical source module shape:
      `module`, `module.lessons[]`, local `id`, `number`, `order`, `type`,
      `title`, `xp_reward`, `grammar_focus`, `content`.
- [ ] Document local IDs: `id` is 1..N within the module, not the DB primary key.
- [ ] Document stable lesson identity: every inserted new-style lesson must carry
      `content.external_key`, and import/diff tooling must prefer it over
      `number`.
- [ ] Document the accepted content schema for every new lesson type.
- [ ] Document that source validation reuses `app/curriculum/validators.py`
      schemas and only adds source-file checks around them.
- [ ] Document XP metadata: `xp_reward` in JSON is source/display metadata, while
      actual daily-plan awards come from `app/achievements/xp_service.py::LINEAR_XP`.
      Include the current source-key table so authors do not invent random values.
- [ ] Document the progression rubric: expected complexity by CEFR level and
      expected within-level growth by module number.
- [ ] Document audio path rules and where static audio must live.
- [ ] Document the production transfer workflow from JSON to DB.

### Task 3: Batch merge missing immersion lessons into source modules

Files:
- Modify: `scripts/merge_immersion_into_source_module.py`
- Modify: `scripts/sync_source_module_with_db.py`
- Create: `reports/module_completed_json_merge_preview.md`

- [ ] Select one pilot module per CEFR level (A1/A2/B1/B2/C1), merge it, review
      it manually, and use the result as the level-specific quality sample before
      touching the rest of the files.
- [ ] Extend `merge_immersion_into_source_module.py` with `--all`, `--level`,
      `--module-number`, `--dry-run`, `--apply`, and `--output-report`.
- [ ] Pull candidate lessons from `content/immersion/*_lessons.json` and local DB
      only when the content has no source-file equivalent.
- [ ] Preserve existing source lessons unless a targeted quality patch is needed.
- [ ] Insert missing new lesson types into the canonical order.
- [ ] Ensure every inserted lesson has a stable `content.external_key`. Do not rely
      on local `id`, `number`, or `order` as the permanent lesson identity.
- [ ] Do not insert `pronunciation` by default unless explicitly approved; keep
      speaking practice centered on `shadow_reading` unless the module has
      high-quality pronunciation content.
- [ ] Renumber `id`, `number`, and `order` to 1..N after merge.
- [ ] Produce a report showing every lesson inserted per file.
- [ ] Add tests for idempotency and ordering.

### Task 4: Per-type quality pass before apply

Files:
- Modify: `content/immersion/*_lessons.json` as needed.
- Modify: `module_completed/fixed/*.json` through the merge script.
- Create: `reports/module_completed_json_quality_review.md`

- [ ] Run a progression review before per-type edits: verify each module's new
      lessons match its CEFR level and are not easier than earlier modules in
      the same level without an explicit reason.
- [ ] `audio_fill_blank`: ensure all items have natural full sentences,
      `answer`, alternatives where needed, and `audio_clip_url`.
- [ ] `dictation`: ensure transcript/gap format is suitable for the inline gap
      UI and all referenced audio exists.
- [ ] `shadow_reading`: ensure text is natural, level-appropriate, and has
      matching audio.
- [ ] `translation`: ensure multi-item schema, `mode`, alternatives, and hints.
- [ ] `writing_prompt`: curate `prompt_ru`, checklist, target phrases, and hint
      words by module.
- [ ] `collocation_matching`: verify pair quality against module vocabulary and
      remove awkward generated phrases.
- [ ] `sentence_completion` and `sentence_correction`: verify ambiguity,
      explanations, and accepted answers.
- [ ] `final_test`: update questions so the final test covers the added module
      lesson types and uses the modern prompt/pair shapes.
- [ ] Mark any deferred module/type with a concrete reason and owner.

### Task 5: Apply source JSON updates

Files:
- Modify: `module_completed/fixed/module_*.json`
- Create: `reports/module_completed_json_apply_report.md`

- [ ] Run the merge in dry-run mode and review `module_completed_json_merge_preview.md`.
- [ ] Apply only after Task 4 quality review is complete.
- [ ] Re-run renumbering for all touched files.
- [ ] Format JSON consistently with `ensure_ascii=False`, two-space indent, and a
      trailing newline.
- [ ] Verify `module_A1_1_greetings.json` remains the reference quality sample.

### Task 6: Validate source JSON and audio portability

Files:
- Create: `scripts/validate_module_completed_json.py`
- Create: `reports/module_completed_json_validation.md`
- Create: `reports/module_completed_audio_manifest.md`

- [ ] Validate all JSON files parse correctly.
- [ ] Validate local `id`, `number`, `order` are continuous 1..N.
- [ ] Validate required fields by lesson type by invoking the existing
      Marshmallow schemas in `app/curriculum/validators.py` where available.
- [ ] Validate every audio reference points to an existing file.
- [ ] Validate coarse progression metrics where automatable: text length bands,
      audio duration bands, response `mode`, hint density, and final-test
      coverage by lesson type.
- [ ] Emit an audio manifest containing every referenced static audio file that
      must be copied to production.
- [ ] Fail validation on placeholder text, empty prompts, missing answers, or
      stub final-test prompts.
- [ ] Add tests for the validator.

### Task 7: Import/diff verification against a database

Files:
- Create: `scripts/diff_module_json_against_db.py`
- Create: `reports/module_completed_json_db_diff.md`

- [ ] Compare source JSON against current local DB by stable identity:
      `content.external_key` first, then carefully reviewed `(level,
      module_number, type, title)` fallback. `number` is order metadata, not the
      primary identity.
- [ ] Verify there are no DB-only curriculum lessons that are absent from source
      JSON unless explicitly deferred.
- [ ] Verify a dry-run import/upsert from JSON would not delete unrelated user
      progress or mutate the content of an existing DB lesson that already has
      user progress.
- [ ] Define the import behavior for changed lesson order: keep the same DB lesson
      when `external_key` matches, then update `number`/`order`; never overwrite a
      different lesson just because its old number matches the new position.
- [ ] Document the exact command sequence for staging/prod import.
- [ ] Add a small integration test that imports fixture JSON into a test DB and
      verifies lesson counts/order/content shape.

### Task 8: Regression tests and smoke checks

- [ ] Run source JSON validation.
- [ ] Run `pytest tests/scripts -q`.
- [ ] Run relevant curriculum render tests for the newly represented lesson
      types.
- [ ] Start the local app and manually spot-check at least:
      - A1/M1 canonical module
      - the A1/A2/B1/B2/C1 pilot modules
      - one older A1 module that changed from 12 lessons
      - one A2 module
      - one B1 module
      - one B2 or C1 module
- [ ] In manual spot-checks, verify progression explicitly: later modules should
      feel harder through longer input, fewer hints, freer production, or more
      nuanced distractors.
- [ ] Confirm `/learn/<lesson_id>/` works for inserted lesson types after import.

### Task 9: Production transfer runbook

Files:
- Create: `reports/module_completed_json_prod_runbook.md`

- [ ] List changed `module_completed/fixed/*.json` files.
- [ ] List audio files to copy, grouped by directory.
- [ ] List commands for staging dry-run, staging apply, production backup,
      production apply, and post-apply audit.
- [ ] Document rollback: restore previous JSON/import state and re-run import.
- [ ] Document what is intentionally not included in git if audio stays ignored.

## Definition of Done

- Every module JSON under `module_completed/fixed/` has the intended upgraded
  lesson sequence.
- A1/M1 has been reconciled against DB and is a real canonical reference, not an
  assumed one.
- One pilot module per CEFR level has passed manual quality review before bulk
  apply.
- No module still has missing canonical lesson slots unless explicitly documented
  as deferred.
- A1/M1 remains the reference file and the rest of the modules match its quality
  bar, adjusted for CEFR level.
- Every inserted new-style lesson has a stable `content.external_key`, and the
  import/diff runbook does not treat `number` as identity.
- The final quality report documents CEFR/module progression and has no
  unexplained cases where later modules are easier than earlier ones.
- `reports/module_completed_json_validation.md` has zero blocking errors.
- `reports/module_completed_json_db_diff.md` shows source JSON and DB are in
  sync, or lists only approved deferred differences.
- `reports/module_completed_audio_manifest.md` contains every audio asset needed
  for production.
- The production runbook is clear enough to apply without relying on local DB
  memory.

## Out of Scope

- Rewriting the frontend templates; they were handled in the modern lesson UI
  plan.
- Inventing C2-specific content if current source modules stop at C1.
- Replacing edge-tts with professional narration.
- Changing user progress, XP rules, or lesson unlock rules.
- Pushing code or content to remote.

## Risks and Mitigations

- **Risk:** mechanical merge creates low-quality filler lessons.  
  Mitigation: Task 4 is mandatory and blocks apply.

- **Risk:** JSON source diverges from DB again.  
  Mitigation: add DB diff script and make it part of the runbook.

- **Risk:** audio files are ignored by git and omitted from production transfer.  
  Mitigation: produce an explicit audio manifest and decide whether to track,
  package, or copy assets separately.

- **Risk:** import by lesson number overwrites existing lessons unexpectedly.  
  Current import code may resolve a lesson by `module_id + number`; after inserting
  new lessons in the middle, that can silently mutate the content behind an
  existing DB primary key with user progress attached. Mitigation: define and
  implement stable identity via `content.external_key` / source key before any
  production import; dry-run diff must flag every number-based collision.

## Estimated Effort

| Task | Type | Effort |
| --- | --- | --- |
| 0 | A1/M1 DB ↔ JSON reconciliation | 0.5 day |
| 1 | Audit script + report | 0.5 day |
| 2 | Contract documentation | 0.5 day |
| 3 | Pilot + batch merge tooling | 1.5 days |
| 4 | Human content quality pass | 2-4 days |
| 5 | Apply source JSON updates | 0.5 day |
| 6 | Validation + audio manifest | 0.75 day |
| 7 | DB diff/import verification | 0.75 day |
| 8 | Tests + manual spot-check | 0.5 day |
| 9 | Production runbook | 0.25 day |
| **Total** | | **~7.75-9.75 working days** |
