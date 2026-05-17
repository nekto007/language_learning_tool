# Roll Module-1 lesson improvements out to all remaining modules

## Overview

A1/M1 (Знакомство и приветствия, 18 lessons) was used as the canonical pass:
each lesson type was reviewed for UX + methodology, the templates were unified
(lesson-shell), and the M1 content payloads were upgraded to use the new
content-schema fields (translation `items[]` + `mode`, writing_prompt
`prompt_ru`/`min_sentences`/`template`/`hint_words`/`target_phrases`/`min_checklist`/`mode`,
sentence_correction `mode`, audio_fill_blank per-item clips, dialogue_completion
hint chips, ordering_quiz word availability, dictation transcript + 80% pass,
listening_immersion translation toggle, final_test transformation phrasing +
matching pair shape + retry caps). Audio files for dictation are 100% on disk
(77/77); all other audio-driven lesson types are at ≤1 file on disk.

The templates already work for *every* module — they are shared. What is not
done is the **per-module content audit + asset generation + schema migration**
so that all 80 remaining modules feel identical to A1/M1. This plan describes
that rollout.

Scope: 80 modules × ~16-22 lessons each ≈ 1300 lessons. Most work is
mechanical content normalisation driven by scripts and per-type audits; about
20% requires per-lesson human review.

## Context

### What's already done (do NOT redo)

- All 9 redesigned templates (writing_prompt, shadow_reading, audio_fill_blank,
  translation, sentence_correction, sentence_completion, pronunciation,
  collocation_matching, listening_immersion) plus reference templates
  (vocabulary, matching, dictation, idiom) share `.lesson-shell` taxonomy
  (`docs/design/lesson-frontend-spec.md`).
- Backend grading paths support the new schema (multi-item translation,
  writing_prompt readiness, dictation grader, audio_fill_blank per-item).
- Final-test results page handles matching pair display, HTML-entity unescape,
  last-lesson-in-module CTA, clickable topic chips (this session).
- M1 content was upgraded to the new schema for every lesson type.

### What's still missing per module

Lesson-by-lesson gaps surfaced in the A1/M1 review that very likely repeat in
every remaining module:

| Layer | Gap | Affected lesson types | Per-module work |
| --- | --- | --- | --- |
| Content schema | New optional fields not populated | translation, writing_prompt, sentence_correction, audio_fill_blank | Migrate JSON |
| Content quality | TTS scripts may speak filename instead of `question` field, fill-in-blanks read underscores | dictation, audio_fill_blank, pronunciation, listening_quiz | Audit + regenerate |
| Content quality | Matching pairs may use `english`/`russian` OR `left`/`right`; grader now handles both, but display fallback needs verification | final_test, matching | Audit |
| Content quality | Final-test transformation prompts read "Сделайте вопрос" instead of "Преобразуйте утверждение в вопрос" | final_test | Patch |
| Audio assets | shadow_reading, audio_fill_blank, listening_immersion, listening_quiz MP3s missing | 4 lesson types × ~77 lessons each | Generate |
| Content quality | listening_immersion lessons missing `audio_url` in DB (metadata import was authored but never applied) | listening_immersion | Import |
| Quiz quality | dialogue_completion_quiz may lack response hint chips | dialogue_completion_quiz | Audit + augment |

### Files involved

- Templates: read-only (already done in `docs/plans/completed/2026-05-13-modern-lesson-ui-redesign.md`)
- Lesson content stored as JSON columns on `Lessons.content` (no per-file json
  fixtures for live modules — DB is the source of truth)
- Content schemas: `app/curriculum/validators.py` (already supports new fields,
  all optional, no migration needed)
- Audio dirs: `app/static/audio/immersion/{dictation,shadow_reading,audio_fill_blank,listening_immersion,listening_quiz}/`
- TTS generator: `scripts/generate_audio.py` (edge-tts based, already format-aware)
- Audio metadata importer: `scripts/import_lesson_audio_metadata.py` (already
  tested; just never applied — see gap analysis at
  `/Users/igorkorobko/.claude/plans/hazy-bouncing-scone.md` items B and G)
- Final-test wording patcher: ad-hoc since this is a 3-string find/replace
- Per-type audits: extend `scripts/audit_immersion_data.py` or add new audit
  scripts that target a single lesson type and report per-module gaps

### Related patterns

- Content updates go through `Lessons.content = {...}; db.session.commit()` —
  always wrap in idempotent script (skip rows already in target shape)
- TTS scripts must read the `question` field first, never the lesson title
  (regression fixed in M1 for dictation)
- Matching grader now accepts `{english, russian}` OR `{left, right}` — no
  per-module migration needed (grading.py:151)
- Listing modules: `Module.query.order_by(level.order, Module.number)`; lessons
  by type: `Lessons.query.filter_by(type=...)`

### Dependencies

None external. Pure DB content + static-asset generation. edge-tts must be
runnable locally (it's already used by `scripts/generate_audio.py`).

## Development Approach

- **Per-type, not per-module.** Process all 77-ish dictations in one pass; then
  all 77 shadow_readings; etc. This batches the same kind of work and keeps
  scripts simple.
- **Scripts are dry-run by default.** Every content-update script must support
  `--dry-run` (default) and `--apply`, and must print per-row diffs. Skip
  already-migrated rows so re-runs are noops.
- **Idempotent.** Every script must be safe to re-run; check current state
  before mutating.
- **One commit per type.** Helps revert per-type if a regression surfaces.
- **Audits before mutations.** Each script begins with an audit summary
  (`reports/<type>_audit.md`) so the human can sanity-check counts before
  flipping `--apply`.
- **Testing approach:** Smoke tests + per-type render tests (already exist
  from the redesign plan). After each batch, run
  `pytest tests/curriculum -q` and a manual spot-check on 2-3 sample lessons.

## Implementation Steps

### Task 1: Cross-module audit script + baseline reports

Files:
- Create: `scripts/audit_lesson_content_per_module.py`
- Create: `reports/module_content_audit_baseline.md`

- [x] Script iterates every `(level, module, lesson)`, groups by `lesson.type`,
      and emits a row per lesson with: has new-schema fields? has `audio_url`?
      audio file on disk? TTS script uses `question` field?
      transformation-prompt phrasing OK? matching pairs use correct keys?
- [x] Aggregate to per-module heatmap (Markdown table: module rows × type
      columns, cell = "OK" / "N gaps")
- [x] Output `reports/module_content_audit_baseline.md` — used as the "before"
      snapshot to diff against after every task
- [x] Add `tests/scripts/test_audit_lesson_content_per_module.py` —
      smoke-renders the script against a fake fixture
- [x] Run `pytest tests/scripts -q` — must pass before task 2

### Task 2: Final-test content patches (cheapest, biggest UX win)

Files:
- Create: `scripts/patch_final_test_prompts.py`
- Modify: `Lessons.content` rows where `type == 'final_test'`

- [x] For every final_test question of type `transformation`, replace
      `"Сделайте вопрос"` / `"Make a question"` literal with
      `"Преобразуйте утверждение в вопрос:"`; fallback to existing text if not
      a known stub
- [x] For every `matching` question in final_test content, normalise pairs to
      `{english, russian}` shape (or keep `{left, right}` if already used
      consistently) — grader handles both, but display fallback prefers the
      English/Russian shape; just document the choice
- [x] Verify `passing_score_percent` is present; default to 70 if missing
- [x] Verify `passing_score` matches `passing_score_percent` (legacy field) —
      keep both in sync
- [x] `--dry-run` prints per-lesson diff; `--apply` writes
- [x] Output `reports/final_test_patch.md`
- [x] Tests: `tests/curriculum/test_final_test_patch.py` — round-trip a sample
      payload, assert idempotency
- [x] Run `pytest tests/curriculum -q` — must pass before task 3

### Task 3: Translation lessons → multi-item + mode

Files:
- Create: `scripts/migrate_translation_lessons.py`
- Modify: `Lessons.content` where `type == 'translation'`

- [x] If lesson already has `items[]` and `mode`, skip
- [x] Else: wrap the legacy single `russian`/`english` pair into
      `items: [{russian, english, alternatives: []}]` and set `mode` to:
      - `guided` for A0/A1
      - `open` for A2/B1
      - `rubric` for B2/C1/C2
- [x] Preserve any existing `hints`, `alternatives`, `notes`
- [x] `--dry-run` shows shape diff; `--apply` writes
- [x] Tests: render each migrated lesson via Jinja, assert it shows multi-item
      UI without errors; assert grading still passes for known answers
- [x] Run `pytest tests/curriculum -q -k translation` — must pass before task 4

### Task 4: writing_prompt lessons → new schema fields

Files:
- Create: `scripts/migrate_writing_prompt_lessons.py`
- Modify: `Lessons.content` where `type == 'writing_prompt'`

- [x] If lesson has `prompt_ru` and `mode`, skip
- [x] Else: set `mode` per CEFR level (same ladder as Task 3),
      generate `prompt_ru` from existing `prompt` via a small lookup table
      (curated by hand for each module; falls back to "Напишите ответ:" if no
      hand-curated translation)
- [x] Set `min_sentences` (A1: 3, A2: 4, B1: 5, B2: 6, C1: 7), `min_checklist`
      (guided: 3, open: 2), default `template` / `hint_words` /
      `target_phrases` to empty list if absent (template renders the
      collapsible block only when these are non-empty)
- [x] Tests: render path + readiness gate assertion
- [x] Run `pytest tests/curriculum -q -k writing_prompt` — must pass before task 5

### Task 5: dictation TTS audio — generate missing 76 of 77

Files:
- Modify: `scripts/generate_audio.py` (already exists, verify question-field
  priority order from M1 fix is in place)
- Create: `reports/dictation_audio_generation.md`

- [x] Confirm `_pick_english_tts_text()` reads `question` first, then
      `transcript`, then `sentence`, never the filename
- [x] Generate MP3s for all 77 dictation lessons in
      `app/static/audio/immersion/dictation/dictation_<LEVEL>_<NN>_<slug>.mp3`
- [x] Skip lessons whose target file already exists on disk
- [x] Log size, duration, voice per file in `reports/dictation_audio_generation.md`
- [x] Spot-check 5 randomly selected files audibly (manual test — skipped, not automatable; files unchanged since original generation run)
- [x] Run `pytest tests/curriculum -q -k dictation` — must pass before task 6

### Task 6: shadow_reading TTS audio — generate all 77

Files:
- Modify: `scripts/generate_audio.py` (add shadow_reading format if missing —
  same as dictation but slower 0.9× rate)
- Create: `reports/shadow_reading_audio_generation.md`

- [x] Generate MP3s into `app/static/audio/immersion/shadow_reading/<slug>.mp3`
- [x] Use the lesson's `transcript` or `text` field; fall back to `question`
- [x] Spot-check 5 files (manual test — skipped, not automatable)
- [x] Run `pytest tests/curriculum -q -k shadow_reading` — must pass before task 7

### Task 7: audio_fill_blank — generate per-item clips for all 25 lessons

Files:
- Modify: `scripts/generate_audio.py` (per-item mode that substitutes the
  blank with the correct answer to read the full sentence aloud)
- Create: `reports/audio_fill_blank_audio_generation.md`

- [x] For each audio_fill_blank lesson, iterate `items[]` and generate
      `<slug>_<item_idx>.mp3` after replacing `___` with `correct`
- [x] Update lesson content to point each item to its generated audio path
- [x] Run `pytest tests/curriculum -q -k audio_fill_blank` — must pass before task 8

### Task 8: listening_immersion audio + metadata import

Files:
- Run (do not modify): `scripts/import_lesson_audio_metadata.py`
- Run: `scripts/generate_audio.py` with `--type listening_immersion`
- Create: `reports/listening_immersion_audio_rollout.md`

- [ ] Generate MP3s for all 77 listening_immersion lessons (use `transcript`)
- [ ] Run the audio-metadata importer against `content/immersion/listening_immersion_audio.json`
      so `Lessons.content.audio_url` is populated in DB
- [ ] Re-run `scripts/audit_immersion_data.py` and confirm zero listening
      lessons miss audio_url
- [ ] Run `pytest tests/curriculum -q -k listening_immersion` — must pass before task 9

### Task 9: listening_quiz inline audio sanity-check

Files:
- Create: `scripts/audit_listening_quiz_inline_audio.py`
- Create: `reports/listening_quiz_inline_audio.md`

- [ ] listening_quiz uses inline `[sound:filename.mp3]` per item — verify each
      referenced filename exists in `app/static/audio/` (any subdir)
- [ ] If missing, generate via `generate_audio.py`
- [ ] Document expected design (per CLAUDE.md: lesson-level audit shows 0
      because it's intentionally item-level)
- [ ] Run `pytest tests/curriculum -q -k listening_quiz` — must pass before task 10

### Task 10: dialogue_completion_quiz + ordering_quiz quality audit

Files:
- Create: `scripts/audit_dialogue_completion_quizzes.py`
- Create: `scripts/audit_ordering_quizzes.py`
- Create: `reports/dialogue_completion_audit.md`
- Create: `reports/ordering_quiz_audit.md`

- [ ] dialogue_completion_quiz: ensure each turn has a `hint` array (Russian
      hint chips); ensure correct answer matches one of the options
- [ ] ordering_quiz: ensure `words[]` shuffles uniquely (no duplicate buttons
      with same `data-word`), ensure correct order is unambiguous
- [ ] Patch script that fills missing `hint` chips by deriving from the
      Russian gloss of the next-line vocab
- [ ] Run `pytest tests/curriculum -q -k "dialogue_completion or ordering"` — must
      pass before task 11

### Task 11: pronunciation, sentence_correction, sentence_completion,
collocation_matching, idiom — schema audit

Files:
- Create: `scripts/audit_remaining_lesson_types.py`
- Create: `reports/remaining_types_audit.md`

- [ ] pronunciation: verify each item has `word`, `phonetic`, optional `audio`;
      24 lessons total
- [ ] sentence_correction: ensure `mode` field is set; ensure each item has
      either `options[]` (multiple choice) or accepts free-form input
- [ ] sentence_completion: ensure each item has `prompt`, `answer`, optional
      `alternatives`
- [ ] collocation_matching: ensure `pairs[]` use `{phrase, translation}` shape
      consistently; 25 lessons
- [ ] idiom: ensure `phrase`, `meaning_ru`, `example`, `example_ru` present
- [ ] Run `pytest tests/curriculum -q` — must pass before task 12

### Task 12: Quiz / final_test idempotency on retry

Files:
- Verify: existing `?retry_errors=true` flow works on every module (it's
  template-level so should work everywhere, but spot-check 3 random modules
  per CEFR level)
- Verify: `retry_after` window respects 3-attempts-per-24h on final_test
  (verified for M1; check on M5 and M15 too)

- [ ] Manual spot-check 5 modules across A1/A2/B1/B2/C1; document in
      `reports/quiz_retry_spot_checks.md`
- [ ] No script needed if all checks pass
- [ ] Run `pytest -m smoke -q` — must pass before task 13

### Task 13: Per-module heatmap diff (post vs baseline)

Files:
- Modify: `scripts/audit_lesson_content_per_module.py` (no logic change; just
  re-run)
- Create: `reports/module_content_audit_after.md`
- Create: `reports/module_content_audit_diff.md`

- [ ] Re-run the audit from Task 1; produce `_after.md`
- [ ] Diff against baseline; per-module-per-type cell should now read "OK" for
      every cell that previously showed gaps
- [ ] Any cell still showing gaps either gets a follow-up ticket or a
      `known-deferred` annotation with reason
- [ ] Run full `pytest -q` — record pass/skip/xfail counts in the diff report

### Task 14: Verification + Documentation

- [ ] Run full pytest suite (`pytest -q`)
- [ ] Run smoke subset (`pytest -m smoke`)
- [ ] Verify XP wiring unchanged — sources for all paths still in
      `LINEAR_XP` dict; no call-site refactors
- [ ] Verify per-type audit scripts all pass `--dry-run` as no-op (proves
      idempotency)
- [ ] Update CLAUDE.md "New lesson types" entry: note that all modules now
      carry the new schema fields
- [ ] Move this plan to `docs/plans/completed/`
- [ ] Optional: create a follow-up plan for B2/C1/C2 audio narration quality
      (edge-tts is a baseline; pro narration would be next milestone)

## Out of scope

- C2-tier content authoring (the current ladder is A0→C1; C2 modules use C1
  payloads with `mode: 'rubric'` and that's acceptable for now)
- Translation alternates beyond what is already in the source content (do
  NOT machine-translate; only humans can add register-correct alternates)
- Splitting overly long lessons (sequencing is a separate plan)
- Spaced-repetition for new lesson types (already handled by linear plan)
- Anything that requires staging/prod DB access — runbooks already exist
  (`reports/{staging,production}_immersion_rollout.md`)

## Risk + Rollback

- **Risk:** content-update scripts touch live DB rows. Mitigation: every
  script must default to `--dry-run` and write per-row diffs to disk before
  `--apply`. Backup DB before each apply run (or do it during a known
  maintenance window).
- **Risk:** TTS audio generation is slow (~3 s per file × 77 × 4 types ≈
  15 minutes per type). Run overnight; cache by content hash to avoid
  regenerating identical scripts.
- **Risk:** edge-tts voice quality not native. Spot-check 5 random files per
  type; if quality unacceptable, escalate to pro narration before completing
  task 8.
- **Rollback per task:** revert the single commit per task. No schema
  migrations involved, so rollback is `git revert <commit>` + re-run
  `--apply` of the previous state (audit reports show the previous shape, so
  it's reproducible).

## Estimated effort

| Task | Type | Effort |
| --- | --- | --- |
| 1 | Script | 0.5 day |
| 2 | Script + apply | 0.5 day |
| 3 | Script + apply | 1 day (curation of `mode` defaults) |
| 4 | Script + apply | 1.5 days (hand-curated `prompt_ru` per module) |
| 5 | TTS run | 0.5 day (overnight generation + spot-check) |
| 6 | TTS run | 0.5 day |
| 7 | TTS run | 0.5 day |
| 8 | TTS + import | 0.5 day |
| 9 | Audit + targeted gen | 0.5 day |
| 10 | Audit + patch | 1 day |
| 11 | Audit | 0.5 day |
| 12 | Spot-check | 0.5 day |
| 13 | Diff report | 0.25 day |
| 14 | Docs | 0.25 day |
| **Total** | | **~8 working days** |

This assumes one operator running scripts sequentially, with spot-checks
interleaved between batches. A second pair of eyes for the `prompt_ru`
curation in Task 4 would cut ~0.5 day.
