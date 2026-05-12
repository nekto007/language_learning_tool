---
# Post-Implementation Content & Data Plan: Real English Immersion

## Overview
#50 sequential tasks to make the already implemented immersion features usable with real production data.

#This plan is based on the repository, local database state, and source module files checked on 2026-05-11 after `docs/plans/completed/2026-05-10-daily-plan-100-tasks.md`.

#The implementation layer is mostly already present: models, migrations, routes, templates, validators, XP wiring, achievements, daily challenges, learning goals, plan difficulty, streak shield, custom lists, lesson feedback, and vocabulary metadata fields. This plan therefore focuses on the actual missing layer: content, imports, audits, audio metadata, source backfills, and rollout verification.

## Verified Current State
- Canonical source modules are stored in 'module_completed/fixed/'.
    - 'module_completed/fixed/' currently has 77 JSON modules across A1-C1:
        - A1: 16 modules / 192 lessons
        - A2: 22 modules / 264 lessons
        - B1: 14 modules / 168 lessons
        - B2: 12 modules / 144 lessons
        - C1: 13 modules / 156 lessons
- Every source module has 12 top-level lessons.
- Source lesson types per module currently include: `vocabulary`, `flashcards` x2, `grammar`, `quiz`, `reading`, `listening_quiz`, `dialogue_completion_quiz`, `ordering_quiz`, `translation_quiz`, `listening_immersion`, `final_test`.
- The local DB snapshot checked on 2026-05-11 has 76 modules, so the first audit must reconcile source JSON modules vs DB modules before importing new content.
    - New implemented lesson types currently have zero real lessons in DB:
        - `dictation`: 0
        - `audio_fill_blank`: 0
        - `translation`: 0
        - `sentence_correction`: 0
        - `writing_prompt`: 0
        - `sentence_completion`: 0
        - `collocation_matching`: 0
        - `shadow_reading`: 0
        - `pronunciation`: 0
        - `idiom`: 0
- Existing listening source content is not audio-ready:
  - `listening_immersion`: 77 source lessons, `audio_url` missing in 77/77
  - `listening_quiz`: 77 source lessons, `audio_url` missing in 77/77
- Vocabulary enrichment fields exist but are empty:
  - `collection_words`: 24,853 rows
  - `ipa_transcription`: 0 rows filled
  - `frequency_band`: 0 rows filled
  - `synonyms`: 0 rows filled
  - `antonyms`: 0 rows filled
  - `etymology`: 0 rows filled
  - `word_collocations`: 0 rows
  - `cultural_notes`: 0 rows
- SRS card source tagging exists but is empty:
  - `user_card_directions.source`: 0/142 filled
- Missing repository data/ops structure:
  - No `content/` directory
  - No `reports/` directory
  - No `docs/content/` directory
  - No `docs/runbooks/` directory
  - No generic immersion content importer

## Not Needed In This Plan
- Do not create new models or migrations for the 100-task feature set unless audits prove a specific migration is broken.
- Do not seed listening/writing/speaking/immersion/challenge achievements from scratch; they already exist in `app/achievements/seed.py`.
- Do not create DailyChallenge categories from scratch; `speed_run`, `accuracy_focus`, and `listening_deep` already exist in code.
- Do not backfill user learning defaults as a primary task; `daily_word_goal`, `weekly_lesson_goal`, `plan_difficulty`, and `streak_shield_active` already have server defaults. Only verify them during migration readiness.
- Do not create separate import scripts per lesson type unless the generic importer proves insufficient.

## Required Content Outcome
- Daily plan extension slots must work in every source curriculum module that is present in the target DB:
  - Add at least one listening slot lesson per module: `dictation`
  - Add at least one writing slot lesson per module: `writing_prompt`
  - Add at least one speaking slot lesson per module: `shadow_reading`
- Every implemented new lesson type must have real content across CEFR levels:
  - Full per-module coverage for slot-critical types: `dictation`, `writing_prompt`, `shadow_reading`
  - CEFR seed coverage for feature-specific types: `audio_fill_blank`, `translation`, `sentence_correction`, `sentence_completion`, `collocation_matching`, `pronunciation`, `idiom`
- Existing listening lessons must get usable audio metadata or be explicitly excluded from audio audits.
- Vocabulary UI must show real enriched data for priority words instead of empty optional sections.
- SRS source analytics must stop showing empty source categories.

## Development Approach
- Complete each task fully before moving to the next.
- Every import script must support `--dry-run`, idempotent re-run, and changed-row counts.
- Every import script must include tests.
- Content should be versioned under `content/` and never edited directly in production DB.
- Treat `module_completed/fixed/` as the source of truth for existing module content and `content/immersion/` as the source for additive immersion lessons/audio metadata.
- Run every import against a restored staging copy before production.
- Never overwrite user-generated data without a backup and rollback path.
- No AI mentions in commit messages.

## Implementation Steps

---
### BLOCK A: Scope, Safety, and Baseline Audits (Tasks 1-8)

### Task 1: Create verified immersion data audit

**Files:**
- Create: `scripts/audit_immersion_data.py`
- Output: `reports/immersion_data_audit.md`
- Tests: `tests/scripts/test_audit_immersion_data.py`

- [x] Count lessons by type and CEFR level
- [x] Compare `module_completed/fixed/` source modules against DB modules
- [x] Report modules present in source but missing in DB
- [x] Report modules present in DB but missing in source
- [x] Count modules missing `dictation`, `writing_prompt`, and `shadow_reading`
- [x] Count existing listening lessons missing audio fields
- [x] Count vocabulary metadata coverage
- [x] Count SRS card source coverage
- [x] Add `--format markdown/json`
- [x] Run pytest tests/scripts/

---
### Task 2: Verify migration readiness without adding new schema

**Files:**
- Modify: `tests/migrations/test_migration_chain.py`
- Output: `reports/migration_readiness.md`

- [x] Confirm migration chain has one head
- [x] Confirm new tables exist after upgrade on empty DB
- [x] Confirm user defaults are applied by migrations
- [x] Confirm no duplicate or orphan migration parents
- [x] Do not add backfill scripts unless this audit proves null/default drift
- [x] Run pytest tests/migrations/

---
### Task 3: Verify existing seed coverage

**Files:**
- Inspect: `app/achievements/seed.py`
- Inspect: `app/daily_plan/challenge.py`
- Output: `reports/seed_coverage.md`

- [x] Verify listening achievements exist
- [x] Verify writing achievements exist
- [x] Verify speaking achievements exist
- [x] Verify immersion achievements exist
- [x] Verify challenge achievements exist
- [x] Verify DailyChallenge categories exist
- [x] Document only missing seeds, if any

---
### Task 4: Create data backup and rollback runbook

**Files:**
- Create: `docs/runbooks/immersion-data-rollback.md`

- [x] Document backup commands before imports
- [x] Document table-level restore path for `lessons`, `collection_words`, `word_collocations`, `cultural_notes`, and `user_card_directions`
- [x] Document how to disable newly imported slots by lesson type if needed
- [x] Document how to revert content imports by `external_key`
- [x] Document risks for user-generated attempts and feedback

---
### Task 5: Define module insertion map for all source modules

**Files:**
- Create: `content/immersion/module_insertion_map.csv`
- Output: `reports/module_insertion_map.md`

- [x] Export module id, CEFR level, module number, current lesson count
- [x] Use `module_completed/fixed/` as the canonical module source
- [x] Include source filename for every module
- [x] Define target insertion point for `dictation`
- [x] Define target insertion point for `writing_prompt`
- [x] Define target insertion point for `shadow_reading`
- [x] Ensure new numbering does not break current linear ordering
- [x] Ensure `final_test` remains final or explicitly document exceptions

---
### Task 6: Define production content target matrix

**Files:**
- Create: `docs/content/immersion-content-targets.md`

- [x] Define required per-module coverage for slot-critical lessons
- [x] Define minimum CEFR coverage for non-slot new lesson types
- [x] Define audio quality requirements
- [x] Define vocabulary metadata coverage targets
- [x] Define acceptance criteria for production readiness

---
### Task 7: Create repository content/data structure

**Files:**
- Create: `content/immersion/README.md`
- Create: `content/vocabulary/README.md`
- Create: `reports/.gitkeep`
- Create: `docs/content/README.md`
- Create: `docs/runbooks/README.md`

- [x] Document what belongs in `content/immersion`
- [x] Document what belongs in `content/vocabulary`
- [x] Document report generation conventions
- [x] Document stable id conventions for imports

---
### Task 8: Create production readiness checklist

**Files:**
- Create: `docs/runbooks/immersion-data-readiness.md`

- [x] List import commands in safe execution order
- [x] List required pre-import audits
- [x] List required post-import row-count checks
- [x] List smoke-test URLs per lesson type
- [x] List rollback checkpoints

---
### BLOCK B: Import Foundation and Schemas (Tasks 9-14)

### Task 9: Document current lesson content schemas

**Files:**
- Create: `docs/content/lesson-content-schemas.md`
- Inspect: `app/curriculum/validators.py`
- Inspect: `app/curriculum/routes/lessons.py`

- [x] Document `dictation` schema
- [x] Document `audio_fill_blank` schema
- [x] Document `translation` schema
- [x] Document `sentence_correction` schema
- [x] Document `writing_prompt` schema
- [x] Document `sentence_completion` schema
- [x] Document `collocation_matching` schema
- [x] Document `shadow_reading` schema
- [x] Document `pronunciation` schema
- [x] Document `idiom` schema

---
### Task 10: Build a generic idempotent immersion lesson importer

**Files:**
- Create: `scripts/import_immersion_lessons.py`
- Tests: `tests/scripts/test_import_immersion_lessons.py`

- [x] Read JSON/JSONL lesson data from `content/immersion/`
- [x] Resolve target modules by `module_completed/fixed/` source identity: level + order + title
- [x] Match existing records by stable `external_key` stored in lesson content
- [x] Create new lessons when missing
- [x] Update only imported lessons by default
- [x] Preserve unrelated lesson content and user progress
- [x] Support `--dry-run`
- [x] Support `--level`, `--module-id`, and `--lesson-type` filters
- [x] Run pytest tests/scripts/

---
### Task 11: Add importer validation mode

**Files:**
- Modify: `scripts/import_immersion_lessons.py`
- Tests: `tests/scripts/test_import_immersion_lessons.py`

- [x] Validate content through `LessonContentValidator`
- [x] Validate CEFR level and module references
- [x] Validate referenced module exists in `module_completed/fixed/`
- [x] Validate referenced module exists in target DB or report it as a source/DB mismatch
- [x] Validate lesson numbers are unique inside a module
- [x] Validate required audio fields for audio lesson types
- [x] Validate no imported lesson points to a missing module
- [x] Add clear error report without partial writes

---
### Task 12: Add content gap report generation

**Files:**
- Create: `scripts/report_immersion_gaps.py`
- Output: `reports/immersion_gap_report.md`
- Tests: `tests/scripts/test_report_immersion_gaps.py`

- [x] Report missing slot-critical lesson types per module
- [x] Report source/DB module mismatch from `module_completed/fixed/`
- [x] Report missing CEFR coverage per new lesson type
- [x] Report audio metadata gaps
- [x] Report vocabulary enrichment gaps
- [x] Report SRS source tagging gaps

---
### Task 13: Add content fixture tests for every new lesson type

**Files:**
- Create: `tests/fixtures/immersion_lessons/`
- Tests: `tests/scripts/test_import_immersion_lessons.py`

- [x] Add one valid fixture per new lesson type
- [x] Add invalid fixture examples for required-field failures
- [x] Verify importer rejects invalid content before DB writes
- [x] Verify importer can re-run without duplicates

---
### Task 14: Create staging smoke data set

**Files:**
- Create: `content/immersion/staging_smoke_lessons.json`
- Tests: `tests/scripts/test_import_immersion_lessons.py`

- [x] Include one lesson of every new type
- [x] Include known-small audio URLs or local static paths
- [x] Include examples that exercise grading and completion paths
- [x] Mark staging fixtures with `environment=staging`

---
### BLOCK C: Curriculum Lesson Content (Tasks 15-29)

### Task 15: Export canonical module map

**Files:**
- Create: `scripts/export_curriculum_module_map.py`
- Output: `content/immersion/module_map.csv`
- Tests: `tests/scripts/test_export_curriculum_module_map.py`

- [x] Export all 77 source modules from `module_completed/fixed/`
- [x] Include source filename, source module id, CEFR level, module order, title, and title_en
- [x] Include matching DB module id when present
- [x] Flag source/DB mismatches before content import
- [x] Export current lesson order per module
- [x] Include current `listening_quiz`, `translation_quiz`, and `listening_immersion` lesson ids
- [x] Use this file as the source of truth for content authors

---
### Task 16: Prepare per-module dictation content

**Files:**
- Create: `content/immersion/dictation_lessons.json`

- [x] Add 77 dictation lessons, one per source module
- [x] Include `audio_url`, `transcript`, `hint_chars`, `duration_seconds`
- [x] Keep A1/A2 transcripts short and literal
- [x] Use B1-C1 transcripts with natural connected speech
- [x] Store stable `external_key`

---
### Task 17: Import dictation lessons

**Files:**
- Modify: `content/immersion/dictation_lessons.json`
- Use: `scripts/import_immersion_lessons.py`
- Output: `reports/dictation_import.md`

- [x] Insert dictation after existing `listening_quiz` or before `listening_immersion`
- [x] Preserve current module progression
- [x] Verify one imported dictation lesson for every source module that exists in target DB
- [x] Report skipped source modules that are not present in target DB
- [x] Verify daily plan listening slot can find a dictation in each current module

---
### Task 18: Prepare per-module writing prompt content

**Files:**
- Create: `content/immersion/writing_prompt_lessons.json`

- [x] Add 77 writing prompts, one per source module
- [x] Include `prompt`, `min_words`, `example_response`, and checklist
- [x] Match prompt difficulty to CEFR level
- [x] Keep prompts tied to module vocabulary or grammar
- [x] Store stable `external_key`

---
### Task 19: Import writing prompt lessons

**Files:**
- Use: `scripts/import_immersion_lessons.py`
- Output: `reports/writing_prompt_import.md`

- [x] Insert writing prompts after `translation_quiz` or before module `final_test`
- [x] Verify one imported writing prompt for every source module that exists in target DB
- [x] Report skipped source modules that are not present in target DB
- [x] Verify daily plan writing slot can find a writing lesson in each current module
- [x] Verify submissions create `UserWritingAttempt`

---
### Task 20: Prepare per-module shadow reading content

**Files:**
- Create: `content/immersion/shadow_reading_lessons.json`

- [x] Add 77 shadow reading lessons, one per source module
- [x] Include `audio_url`, `text`, `translation`, and optional `words`
- [x] Reuse existing listening dialogue text where suitable
- [x] Keep text length aligned to CEFR level
- [x] Store stable `external_key`

---
### Task 21: Import shadow reading lessons

**Files:**
- Use: `scripts/import_immersion_lessons.py`
- Output: `reports/shadow_reading_import.md`

- [x] Insert shadow reading near `listening_immersion`
- [x] Verify one imported shadow reading lesson for every source module that exists in target DB
- [x] Report skipped source modules that are not present in target DB
- [x] Verify daily plan speaking slot can find a shadow reading lesson in each current module
- [x] Verify self-assessment completion awards linear XP

---
### Task 22: Prepare audio fill-in-blank CEFR seed

**Files:**
- Create: `content/immersion/audio_fill_blank_lessons.json`

- [x] Add at least 5 lessons per CEFR level, 25 total
- [x] Include `audio_url` and `items`
- [x] Include both free-text and options mode
- [x] Include normalized answers suitable for typo-tolerant grading

---
### Task 23: Prepare standalone translation CEFR seed

**Files:**
- Create: `content/immersion/translation_lessons.json`

- [x] Add at least 5 lessons per CEFR level, 25 total
- [x] Include `russian`, `english`, and optional `hint_words`
- [x] Avoid duplicate content from existing `translation_quiz`
- [x] Tie examples to module vocabulary

---
### Task 24: Prepare sentence correction CEFR seed

**Files:**
- Create: `content/immersion/sentence_correction_lessons.json`

- [x] Add at least 5 lessons per CEFR level, 25 total
- [x] Include `incorrect_sentence`, `correct_sentence`, `error_type`, `explanation`
- [x] Cover article, tense, word order, preposition, and agreement errors
- [x] Add options where helpful for lower levels

---
### Task 25: Prepare sentence completion CEFR seed

**Files:**
- Create: `content/immersion/sentence_completion_lessons.json`

- [x] Add at least 5 lessons per CEFR level, 25 total
- [x] Include `items` with `prompt`, `answer`, and optional `context`
- [x] Use natural sentence endings, not trivia-style answers
- [x] Align prompts to module grammar

---
### Task 26: Prepare pronunciation CEFR seed

**Files:**
- Create: `content/immersion/pronunciation_lessons.json`

- [x] Add at least 5 lessons per CEFR level, 25 total
- [x] Include words, `pronunciation_hint`, and optional `audio_url`
- [x] Prioritize common learner traps and minimal pairs
- [x] Include fallback-friendly words for browsers without speech recognition

---
### Task 27: Prepare collocation matching seed

**Files:**
- Create: `content/immersion/collocation_matching_lessons.json`

- [x] Add at least 5 lessons per CEFR level, 25 total
- [x] Include `pairs` with `phrase` and `translation`
- [x] Reuse collocations from `content/vocabulary/collocations.csv`
- [x] Keep distractors level-appropriate

---
### Task 28: Prepare idiom seed

**Files:**
- Create: `content/immersion/idiom_lessons.json`

- [x] Add B1-C1 idiom content first, minimum 15 lessons total
- [x] Include `phrase`, `meaning`, `example`, and optional `audio_url`
- [x] Avoid obscure idioms without practical learner value
- [x] Mark culturally sensitive items for review

---
### Task 29: Import all CEFR seed lessons and verify counts

**Files:**
- Use: `scripts/import_immersion_lessons.py`
- Output: `reports/cefr_seed_import.md`

- [x] Import `audio_fill_blank`
- [x] Import `translation`
- [x] Import `sentence_correction`
- [x] Import `sentence_completion`
- [x] Import `pronunciation`
- [x] Import `collocation_matching`
- [x] Import `idiom`
- [x] Verify zero duplicate lessons after second import run

---
### BLOCK D: Existing Listening and Audio Enrichment (Tasks 30-34)

### Task 30: Audit existing listening lesson payloads

**Files:**
- Create: `scripts/audit_existing_listening_payloads.py`
- Output: `reports/existing_listening_payloads.md`
- Tests: `tests/scripts/test_audit_existing_listening_payloads.py`

- [x] Inspect all 77 source `listening_immersion` lessons
- [x] Inspect all 77 source `listening_quiz` lessons
- [x] Compare source listening payloads with DB listening payloads
- [x] Report whether usable transcript/text already exists
- [x] Report whether audio should be lesson-level or item-level
- [x] Report lessons that should be excluded from audio requirements

---
### Task 31: Add audio metadata for listening immersion lessons

**Files:**
- Create: `content/immersion/listening_immersion_audio.json`
- Create: `scripts/import_lesson_audio_metadata.py`
- Tests: `tests/scripts/test_import_lesson_audio_metadata.py`

- [x] Add `audio_url` for all 77 source `listening_immersion` lessons or document exclusions
- [x] Add `duration_seconds`
- [x] Add transcript/text normalization if missing
- [x] Import without changing non-audio lesson fields

---
### Task 32: Add audio metadata for listening quiz lessons

**Files:**
- Create: `content/immersion/listening_quiz_audio.json`
- Use: `scripts/import_lesson_audio_metadata.py`

- [x] Add lesson-level or item-level audio refs for all 77 source `listening_quiz` lessons or document exclusions
- [x] Add audio clips only where the quiz template can use them
- [x] Preserve quiz answers and options
- [x] Verify audio metadata does not reshuffle answer semantics

---
### Task 33: Add duration and transcript quality checks

**Files:**
- Modify: `scripts/audit_existing_listening_payloads.py`
- Output: `reports/listening_duration_transcript_audit.md`

- [x] Check `duration_seconds` exists for audio lessons
- [x] Check transcript/text is not empty
- [x] Check transcript length is reasonable for CEFR level
- [x] Check audio duration and transcript length are plausible

---
### Task 34: Extend audio URL verification

**Files:**
- Modify: `app/cli/content_commands.py`
- Tests: `tests/curriculum/test_listening_ui.py`

- [x] Include imported `dictation`, `audio_fill_blank`, and `shadow_reading`
- [x] Keep existing `listening_immersion` audit behavior
- [x] Add broken-local-path detection
- [x] Add report output path support

---
### BLOCK E: Vocabulary Metadata and SRS Data (Tasks 35-44)

### Task 35: Create vocabulary priority resolver

**Files:**
- Create: `scripts/export_vocabulary_priority.py`
- Output: `content/vocabulary/priority_words.csv`
- Tests: `tests/scripts/test_export_vocabulary_priority.py`

- [x] Rank words by curriculum usage
- [x] Rank words by user card usage
- [x] Rank words by CEFR level when available
- [x] Handle current `frequency_rank=0` for all words
- [x] Export priority tiers for staged enrichment

---
### Task 36: Import frequency bands

**Files:**
- Create: `content/vocabulary/frequency_bands.csv`
- Create: `scripts/import_frequency_bands.py`
- Tests: `tests/scripts/test_import_frequency_bands.py`

- [x] Fill `frequency_band` for priority words first
- [x] Use external frequency data or curated CEFR fallback
- [x] Validate only allowed values: 1, 2, 3
- [x] Preserve existing non-null values unless `--force`

---
### Task 37: Import IPA transcriptions

**Files:**
- Create: `content/vocabulary/ipa_transcriptions.csv`
- Create: `scripts/import_ipa_transcriptions.py`
- Tests: `tests/scripts/test_import_ipa_transcriptions.py`

- [x] Fill IPA for priority words first
- [x] Validate IPA formatting
- [x] Avoid adding slashes into stored value if template already wraps it
- [x] Preserve existing non-null values unless `--force`

---
### Task 38: Import synonyms and antonyms

**Files:**
- Create: `content/vocabulary/synonyms_antonyms.csv`
- Create: `scripts/import_synonyms_antonyms.py`
- Tests: `tests/scripts/test_import_synonyms_antonyms.py`

- [x] Fill synonyms for priority words
- [x] Fill antonyms where useful and accurate
- [x] Store values as JSON lists
- [x] Reject malformed list values

---
### Task 39: Import word collocations

**Files:**
- Create: `content/vocabulary/collocations.csv`
- Create: `scripts/import_word_collocations.py`
- Tests: `tests/scripts/test_import_word_collocations.py`

- [ ] Add at least two collocations for priority A2-B2 words where possible
- [ ] Include translation and example
- [ ] Upsert by `word_id + collocation_phrase`
- [ ] Ensure collocation lesson content can reuse this dataset

---
### Task 40: Import etymology notes

**Files:**
- Create: `content/vocabulary/etymology_notes.csv`
- Create: `scripts/import_etymology_notes.py`
- Tests: `tests/scripts/test_import_etymology_notes.py`

- [ ] Add concise notes for priority words
- [ ] Avoid speculative or overly academic notes
- [ ] Preserve existing non-null values unless `--force`
- [ ] Keep notes short enough for vocabulary card UI

---
### Task 41: Import cultural notes

**Files:**
- Create: `content/vocabulary/cultural_notes.csv`
- Create: `scripts/import_cultural_notes.py`
- Tests: `tests/scripts/test_import_cultural_notes.py`

- [ ] Add notes for idioms, phrasal verbs, politeness-sensitive words, and culture-specific usage
- [ ] Include `context`
- [ ] Upsert without duplicating notes
- [ ] Verify notes render in vocabulary lessons

---
### Task 42: Backfill SRS card source tags

**Files:**
- Create: `scripts/backfill_card_sources.py`
- Tests: `tests/scripts/test_backfill_card_sources.py`

- [ ] Fill source for existing 142 `user_card_directions`
- [ ] Infer `lesson_vocab` where linked to curriculum words
- [ ] Infer `book_reading` where linked to book/course imports
- [ ] Leave ambiguous cards as `manual`
- [ ] Add dry-run report and unresolved count

---
### Task 43: Create vocabulary enrichment coverage report

**Files:**
- Create: `scripts/report_vocabulary_enrichment.py`
- Output: `reports/vocabulary_enrichment.md`
- Tests: `tests/scripts/test_report_vocabulary_enrichment.py`

- [ ] Report coverage for IPA
- [ ] Report coverage for frequency bands
- [ ] Report coverage for synonyms/antonyms
- [ ] Report coverage for collocations
- [ ] Report coverage for etymology and cultural notes
- [ ] Break down by CEFR level and priority tier

---
### Task 44: Verify optional vocabulary UI behavior

**Files:**
- Modify: `tests/curriculum/test_vocabulary_lessons.py`
- Modify: `tests/study/test_vocab_map.py`

- [ ] Verify enriched words show all optional sections
- [ ] Verify missing metadata hides optional sections cleanly
- [ ] Verify no empty labels are rendered
- [ ] Verify flashcard session receives frequency data when present

---
### BLOCK F: QA, Rollout, and Operations (Tasks 45-50)

### Task 45: Smoke-test every imported lesson type

**Files:**
- Create: `docs/qa/immersion-lesson-smoke.md`
- Tests: `tests/curriculum/`

- [ ] Open one imported lesson of every new type
- [ ] Submit a passing answer for graded types
- [ ] Submit a failing answer where applicable
- [ ] Verify progress changes correctly
- [ ] Verify next lesson URL works
- [ ] Verify XP source is recorded correctly

---
### Task 46: Smoke-test daily plan extension slots across levels

**Files:**
- Create: `docs/qa/daily-plan-immersion-slots.md`
- Tests: `tests/daily_plan/linear/`

- [ ] Test A1 user current module
- [ ] Test A2 user current module
- [ ] Test B1 user current module
- [ ] Test B2 user current module
- [ ] Test C1 user current module
- [ ] Verify listening slot appears
- [ ] Verify writing slot appears
- [ ] Verify speaking slot appears

---
### Task 47: Verify analytics with real imported lessons

**Files:**
- Create: `scripts/seed_staging_immersion_attempts.py`
- Tests: `tests/study/test_insights_service.py`

- [ ] Seed staging `ListeningAttempt` rows from imported dictation/audio lessons
- [ ] Seed staging `UserWritingAttempt` rows from imported writing prompts
- [ ] Seed staging `PronunciationAttempt` rows from imported pronunciation lessons
- [ ] Verify study dashboard widgets show non-empty data
- [ ] Verify weekly report handles new activity types

---
### Task 48: Verify admin content quality with real data

**Files:**
- Modify: `tests/admin/test_content_quality.py`
- Output: `reports/admin_content_quality.md`

- [ ] Verify content-quality dashboard counts imported lesson types
- [ ] Verify missing-audio counts drop after imports
- [ ] Verify vocabulary enrichment coverage is visible
- [ ] Verify feedback aggregation handles imported lessons

---
### Task 49: Execute staging rollout

**Files:**
- Output: `reports/staging_immersion_rollout.md`

- [ ] Restore fresh staging DB copy
- [ ] Run migration readiness check
- [ ] Run all content imports with `--dry-run`
- [ ] Run all content imports for real
- [ ] Run gap reports after import
- [ ] Run lesson and daily plan smoke tests
- [ ] Record final row counts

---
### Task 50: Execute production rollout checklist

**Files:**
- Output: `reports/production_immersion_rollout.md`

- [ ] Confirm backup exists
- [ ] Run imports in documented order
- [ ] Run post-import audits
- [ ] Verify daily plan for real test users across levels
- [ ] Verify admin content quality dashboard
- [ ] Attach final content/data report to release notes
