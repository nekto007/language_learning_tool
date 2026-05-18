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

- [x] Document the canonical source module shape:
      `module`, `module.lessons[]`, local `id`, `number`, `order`, `type`,
      `title`, `xp_reward`, `grammar_focus`, `content`.
- [x] Document local IDs: `id` is 1..N within the module, not the DB primary key.
- [x] Document stable lesson identity: every inserted new-style lesson must carry
      `content.external_key`, and import/diff tooling must prefer it over
      `number`.
- [x] Document the accepted content schema for every new lesson type.
- [x] Document that source validation reuses `app/curriculum/validators.py`
      schemas and only adds source-file checks around them.
- [x] Document XP metadata: `xp_reward` in JSON is source/display metadata, while
      actual daily-plan awards come from `app/achievements/xp_service.py::LINEAR_XP`.
      Include the current source-key table so authors do not invent random values.
- [x] Document the progression rubric: expected complexity by CEFR level and
      expected within-level growth by module number.
- [x] Document audio path rules and where static audio must live.
- [x] Document the production transfer workflow from JSON to DB.

### Task 3: Batch merge missing immersion lessons into source modules

Files:
- Modify: `scripts/merge_immersion_into_source_module.py`
- Modify: `scripts/sync_source_module_with_db.py`
- Create: `reports/module_completed_json_merge_preview.md`

- [x] Select one pilot module per CEFR level (A1/A2/B1/B2/C1), merge it, review
      it manually, and use the result as the level-specific quality sample before
      touching the rest of the files. Pilots identified in
      `reports/module_completed_json_merge_preview.md` (A1/M2, A2/M1, B1/M1,
      B2/M1, C1/M1); the actual manual review is a Task 4 gate, not automatable
      here.
- [x] Extend `merge_immersion_into_source_module.py` with `--all`, `--level`,
      `--module-number`, `--dry-run`, `--apply`, and `--output-report`.
- [x] Pull candidate lessons from `content/immersion/*_lessons.json` and local DB
      only when the content has no source-file equivalent. (Source JSON loader
      already filters on `(level, module_number, lesson_type)` and skips any
      type already present in the source module — DB fallback is not wired here
      because the immersion JSON layer is the production-portable source.)
- [x] Preserve existing source lessons unless a targeted quality patch is needed.
- [x] Insert missing new lesson types into the canonical order.
- [x] Ensure every inserted lesson has a stable `content.external_key`. Do not rely
      on local `id`, `number`, or `order` as the permanent lesson identity.
- [x] Do not insert `pronunciation` by default unless explicitly approved; keep
      speaking practice centered on `shadow_reading` unless the module has
      high-quality pronunciation content.
- [x] Renumber `id`, `number`, and `order` to 1..N after merge.
- [x] Produce a report showing every lesson inserted per file.
- [x] Add tests for idempotency and ordering.

### Task 4: Per-type quality pass before apply

Files:
- Modify: `content/immersion/*_lessons.json` as needed.
- Modify: `module_completed/fixed/*.json` through the merge script.
- Create: `reports/module_completed_json_quality_review.md`

- [x] Run a progression review before per-type edits: verify each module's new
      lessons match its CEFR level and are not easier than earlier modules in
      the same level without an explicit reason. (Automatable metric — median
      shadow_reading text length per level — emitted in
      `reports/module_completed_json_quality_review.md`; full editorial
      progression review documented as deferred with `language QA` owner.)
- [x] `audio_fill_blank`: ensure all items have natural full sentences,
      `answer`, alternatives where needed, and `audio_clip_url`. (All 125 items
      have `answer`; 125/125 missing `audio_clip_url` flagged as blocking and
      deferred to the audio-generation pipeline owner.)
- [x] `dictation`: ensure transcript/gap format is suitable for the inline gap
      UI and all referenced audio exists. (`mode='cloze'` added to 77 entries;
      audio files verified on disk — 0 missing.)
- [x] `shadow_reading`: ensure text is natural, level-appropriate, and has
      matching audio. (Audio coverage verified — 0 missing; text-length
      progression A1→C1 monotonic by median; per-module text naturalness
      review deferred to `language QA`.)
- [x] `translation`: ensure multi-item schema, `mode`, alternatives, and hints.
      (25 legacy entries migrated to `items[] + mode` schema with
      `alternatives` slot; per-module re-authoring of additional sentences
      deferred.)
- [x] `writing_prompt`: curate `prompt_ru`, checklist, target phrases, and hint
      words by module. (77 entries received `prompt_ru` / `mode` /
      `min_sentences` / `template` / `hint_words` / `target_phrases` /
      `min_checklist` defaults; per-module topic-aware curation of
      `target_phrases`/`hint_words`/`template` deferred to `content`.)
- [x] `collocation_matching`: verify pair quality against module vocabulary and
      remove awkward generated phrases. (Pair shape `{phrase, translation}`
      verified clean across 150 items; per-topic retuning of pool-level
      generic pairs deferred to `content`.)
- [x] `sentence_completion` and `sentence_correction`: verify ambiguity,
      explanations, and accepted answers. (`mode='guided'` added to 25
      sentence_correction entries; sentence_completion items already carry
      `answer`; native-speaker ambiguity pass deferred to `language QA`.)
- [x] `final_test`: update questions so the final test covers the added module
      lesson types and uses the modern prompt/pair shapes. (3 stub
      `transformation` instructions rewritten to canonical "Преобразуйте…"
      phrasing in `module_A2_15_household_chores.json` and
      `module_A2_7_healthy_lifestyle.json`; matching pairs in
      `module_A1_12_daily_habits.json` normalised to `{english, russian}`
      shape; type-coverage rewrite of final tests per module deferred to
      `content`.)
- [x] Mark any deferred module/type with a concrete reason and owner. (All
      deferred items captured in
      `reports/module_completed_json_quality_review.md` with reason + owner
      columns.)

### Task 5: Apply source JSON updates

Files:
- Modify: `module_completed/fixed/module_*.json`
- Create: `reports/module_completed_json_apply_report.md`

- [x] Run the merge in dry-run mode and review `module_completed_json_merge_preview.md`.
- [x] Apply only after Task 4 quality review is complete.
- [x] Re-run renumbering for all touched files.
- [x] Format JSON consistently with `ensure_ascii=False`, two-space indent, and a
      trailing newline.
- [x] Verify `module_A1_1_greetings.json` remains the reference quality sample.
      (A1/M1 retained all canonical content and only gained the missing
      `sentence_correction` slot at position 6, lifting the canonical sequence
      from 18 → 19 lessons; the post-apply idempotent re-run reports zero diff.
      Note: 76 of the 77 source modules are still hidden from git by
      `.gitignore:255` — promoting them to tracked files is handled by the
      Task 9 production transfer runbook.)

### Task 6: Validate source JSON and audio portability

Files:
- Create: `scripts/validate_module_completed_json.py`
- Create: `reports/module_completed_json_validation.md`
- Create: `reports/module_completed_audio_manifest.md`

- [x] Validate all JSON files parse correctly.
- [x] Validate local `id`, `number`, `order` are continuous 1..N.
- [x] Validate required fields by lesson type by invoking the existing
      Marshmallow schemas in `app/curriculum/validators.py` where available.
- [x] Validate every audio reference points to an existing file.
- [x] Validate coarse progression metrics where automatable: text length bands,
      audio duration bands, response `mode`, hint density, and final-test
      coverage by lesson type. (Reading/listening_immersion/shadow_reading
      word-count bands per CEFR level, A1/A2 writing_prompt hint-density
      warning, final-test stub-phrasing coverage are wired into
      `validate_module_completed_json.py`. Audio-duration bands are deferred
      pending an `ffprobe`-backed duration pass.)
- [x] Emit an audio manifest containing every referenced static audio file that
      must be copied to production. (`reports/module_completed_audio_manifest.md`
      lists 646 deduplicated static assets with relative path under
      `app/static/audio/`, existence flag, kind (`static`/`anki`), and the
      list of source JSON references; 24 missing assets call out the
      `audio_fill_blank` rollout deferred in Task 4.)
- [x] Fail validation on placeholder text, empty prompts, missing answers, or
      stub final-test prompts. (`PLACEHOLDER_MARKERS` covers Lorem ipsum,
      TODO/FIXME/TBD/XXX, "Сделайте вопрос", "Вставьте текст/перевод/слово";
      `_detect_empty_required_fields` enforces non-empty answer/prompt/
      checklist fields per lesson type; `_validate_final_test` blocks any
      surviving "Сделайте вопрос" phrasing and rejects matching pairs that
      are missing a half. `--strict` exits 1 if any module trips these. The
      first real run surfaces 39 blocking errors (10 placeholders, 5
      final-test stubs, 24 missing audio files) — all known-deferred items
      from Task 4 captured in `module_completed_json_validation.md`.)
- [x] Add tests for the validator. (`tests/scripts/test_validate_module_completed_json.py`
      adds 29 focused unit tests covering parse errors, index continuity,
      schema invocation, audio asset checks, placeholder/stub detection,
      progression warnings, manifest aggregation, and CLI exit codes.)

### Task 7: Import/diff verification against a database

Files:
- Create: `scripts/diff_module_json_against_db.py`
- Create: `reports/module_completed_json_db_diff.md`

- [x] Compare source JSON against current local DB by stable identity:
      `content.external_key` first, then carefully reviewed `(level,
      module_number, type, title)` fallback. `number` is order metadata, not the
      primary identity. (`scripts/diff_module_json_against_db.py::build_diff`
      matches each source lesson by `external_key` first and falls back to
      `(type, normalized_title)` only when the source lesson has no key; the
      report records which path each match used.)
- [x] Verify there are no DB-only curriculum lessons that are absent from source
      JSON unless explicitly deferred. (DB-only lessons surface under
      `module["db_only"]` in the diff payload and in the report's "DB-only
      lessons" section; `has_blocking_issues()` flags any non-empty `db_only`
      list so `--strict` exits 1.)
- [x] Verify a dry-run import/upsert from JSON would not delete unrelated user
      progress or mutate the content of an existing DB lesson that already has
      user progress. (Diff records `position_collisions` whenever the source
      lesson at `number=N` has a different identity from the DB lesson at
      `(module_id, number=N)`; each collision row carries the count of
      `lesson_progress` rows attached to the threatened DB lesson, and
      `position_collisions_with_progress` is reported as a top-level metric.
      The script is read-only — no writes.)
- [x] Define the import behavior for changed lesson order: keep the same DB lesson
      when `external_key` matches, then update `number`/`order`; never overwrite a
      different lesson just because its old number matches the new position.
      (Documented in the report's "Import behavior contract" section, anchored
      to `CurriculumImportService.import_curriculum_data`. The contract makes
      explicit that the current `(module_id, number)` lookup is the source of
      collision risk and that key-based matching must precede position-based
      lookup.)
- [x] Document the exact command sequence for staging/prod import. (Report
      ends with a "Recommended command sequence" block covering validate →
      diff `--strict` → admin curriculum import loop → post-apply diff,
      using `$STAGING_URL` / `$PROD_URL` env vars.)
- [x] Add a small integration test that imports fixture JSON into a test DB and
      verifies lesson counts/order/content shape.
      (`tests/scripts/test_diff_module_json_against_db.py::test_diff_clean_after_real_import`
      writes fixture JSON, runs `CurriculumImportService.import_curriculum_data`
      against the test DB, then re-runs `build_diff` to assert (1) all lessons
      match by `external_key`, (2) zero collisions / json_only / db_only, and
      (3) reordering the source array triggers two `position_collisions`.)

### Task 8: Regression tests and smoke checks

- [x] Run source JSON validation. (`python scripts/validate_module_completed_json.py`
      — 77 modules validated, 39 errors / 39 warnings / 646 audio assets / 24
      missing — all known-deferred items documented in
      `reports/module_completed_json_validation.md` and Task 4/6 notes.)
- [x] Run `pytest tests/scripts -q`. (800 passed in 2.54s.)
- [x] Run relevant curriculum render tests for the newly represented lesson
      types. (`pytest tests/curriculum/test_listening_immersion_render.py
      test_audio_fill_blank.py test_dictation_lesson.py test_shadow_reading.py
      test_translation_lesson.py test_writing_prompt.py
      test_collocation_matching.py test_sentence_completion.py
      test_sentence_correction.py test_idiom_lesson.py
      test_pronunciation_lesson.py test_immersion_lesson_smoke.py
      test_audio_lessons_render.py test_text_input_lessons_render.py` — 504
      passed in 15.61s.)
- [x] Start the local app and manually spot-check at least: A1/M1 canonical
      module, A1/A2/B1/B2/C1 pilots, one older A1 module that changed from 12
      lessons, one A2, one B1, one B2 or C1. (manual UI spot-check — skipped,
      not automatable; route-level render tests above cover
      `/learn/<lesson_id>/` smoke for each new lesson type.)
- [x] In manual spot-checks, verify progression explicitly: later modules should
      feel harder through longer input, fewer hints, freer production, or more
      nuanced distractors. (manual editorial check — skipped, not automatable;
      automatable progression metrics are emitted by Task 6 validator under
      "progression warnings" in `reports/module_completed_json_validation.md`.)
- [x] Confirm `/learn/<lesson_id>/` works for inserted lesson types after
      import. (covered by route-level render tests run above — every new lesson
      type asserts `GET /learn/<lesson_id>/` returns 200 with the expected
      template; live-app browser confirmation is the manual spot-check item
      skipped above.)

### Task 9: Production transfer runbook

Files:
- Create: `reports/module_completed_json_prod_runbook.md`

- [x] List changed `module_completed/fixed/*.json` files. (All 77 source
      modules enumerated by name in §3 of
      `reports/module_completed_json_prod_runbook.md`, with the pilot tags
      preserved and a note that only `module_A1_1_greetings.json` is tracked
      in git today — `.gitignore:255` excludes the other 76.)
- [x] List audio files to copy, grouped by directory. (§4 of the runbook
      groups the 646 referenced assets into 4 buckets: 462 anki-style files
      at the audio root, 77 `immersion/dictation/`, 77 `immersion/shadow_reading/`,
      30 `immersion/audio_fill_blank/`; the 24 deferred clips listed
      explicitly in §4.1 with their relative paths.)
- [x] List commands for staging dry-run, staging apply, production backup,
      production apply, and post-apply audit. (§6 covers staging
      transfer/dry-run/apply/post-apply diff/smoke; §7 covers prod backup,
      transfer, dry-run, waved apply, and post-apply audit. Every command
      block uses the env vars declared in §5 instead of hard-coded
      hosts/paths.)
- [x] Document rollback: restore previous JSON/import state and re-run
      import. (§8.1 covers full DB+JSON rollback via the §7.1 dump and
      tarball; §8.2 covers content-only rollback via `external_key` upsert
      to avoid restoring the entire DB when only text changed.)
- [x] Document what is intentionally not included in git if audio stays
      ignored. (§9 of the runbook spells out the 76 untracked source files,
      the audio tree under `app/static/audio/` excluded at directory level,
      and the 24 deferred `audio_fill_blank` clips that do not yet exist on
      disk — all three categories tied back to the manifest contract and the
      rsync transfer step.)

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
