# Gap Analysis: Daily Plan 100-Tasks + Post-Immersion Content/Data Plans

## Context

Two plans were nominally completed and moved to `docs/plans/completed/`:

1. **`2026-05-10-daily-plan-100-tasks.md`** — 100 implementation tasks (code layer:
   listening, writing, speaking, vocabulary depth, plan intelligence, analytics,
   gamification). All 534 checkboxes marked `[x]`, 0 unchecked.
2. **`2026-05-11-post-immersion-content-data-plan.md`** — 50 content/data tasks
   (audits, importers, content authoring, rollout). All checkboxes marked `[x]`.

The user asked: *what is really shipped vs what is genuinely missing in terms of
content*? This document is a verified gap analysis, not new implementation.

The conclusion below is based on filesystem inspection (no DB access). Items
flagged "unknown" need a DB query to confirm.

---

## Verified State by Layer

### 1. Code layer (100-tasks plan) — ✅ shipped

Confirmed by file presence + CLAUDE.md mentions:

- All new lesson types registered: `dictation`, `audio_fill_blank`, `translation`,
  `sentence_correction`, `writing_prompt`, `sentence_completion`,
  `collocation_matching`, `shadow_reading`, `pronunciation`, `idiom`.
- Models: `ListeningAttempt`, `UserWritingAttempt`, `PronunciationAttempt`,
  `WordCollocation`, `VocabAnnotation`, `CulturalNote`, `UserReadingSession`,
  `QuizErrorLog`, `GrammarTheoryView`, `UserReadingPreference`, `DailyChallenge`,
  `DailyStudyMinutes`, `LessonFeedback`.
- Migrations 20260420 → 20260523 present, single head `20260523_streak_shield`
  (verified by `tests/migrations/test_migration_chain.py`).
- 63 migrations, 0 orphans, 0 duplicates.

**No code gaps observed.**

### 2. Scaffolding layer (post-immersion plan, Tasks 1–14) — ✅ shipped

| Surface | State |
| --- | --- |
| `scripts/` immersion + vocab + audit scripts | 14 scripts present (audit, import, report, backfill, export) |
| `tests/scripts/` | 16 test files |
| `content/immersion/` | 13 JSON + 2 CSV |
| `content/vocabulary/` | 6 CSV + README |
| `reports/` | 15 reports |
| `docs/runbooks/` | 3 files (README, rollback, readiness) |
| `docs/content/` | 3 files (README, immersion-content-targets, lesson-content-schemas) |

### 3. Authored lesson JSON (Tasks 15–29) — ✅ 100% by count

| File | Items | Target | OK |
| --- | --- | --- | --- |
| `dictation_lessons.json` | 77 | 77 | ✅ |
| `writing_prompt_lessons.json` | 77 | 77 | ✅ |
| `shadow_reading_lessons.json` | 77 | 77 | ✅ |
| `audio_fill_blank_lessons.json` | 25 | 25 | ✅ |
| `translation_lessons.json` | 25 | 25 | ✅ |
| `sentence_correction_lessons.json` | 25 | 25 | ✅ |
| `sentence_completion_lessons.json` | 25 | 25 | ✅ |
| `pronunciation_lessons.json` | 25 | 25 | ✅ |
| `collocation_matching_lessons.json` | 25 | 25 | ✅ |
| `idiom_lessons.json` | 15 | 15 | ✅ |
| `listening_immersion_audio.json` | 77 | 77 | ✅ |
| `listening_quiz_audio.json` | 77 | 77 | ✅ |
| `staging_smoke_lessons.json` | 10 | ≥10 | ✅ |

### 4. Lessons imported into DB — ✅ confirmed by reports

Reports show real PostgreSQL lesson IDs assigned:

- `reports/dictation_import.md` — 77 rows, lesson_ids 973–1049, mode `update`
  (idempotent re-run).
- `reports/writing_prompt_import.md` — 77 `create`, lesson_ids 1050–1126.
- `reports/shadow_reading_import.md` — 77 `create`, lesson_ids 1127–1203.
- `reports/cefr_seed_import.md` — 165 lessons across 7 types; second-run zero
  duplicates confirmed.

**Imports against DB really happened.** DB has all 11 new lesson categories.

---

## Verified Gaps

These are real, concrete gaps. Each has a verifiable consequence in product.

### A. Shadow-reading audio MP3s do not exist (BLOCKING for speaking slot)

- `shadow_reading_lessons.json` references
  `/static/audio/immersion/shadow_reading/shadow_reading_<LEVEL>_<NN>_<slug>.mp3`
  in all 77 entries.
- On disk: `app/static/audio/immersion/shadow_reading/` does not exist.
- `find app/static/audio/immersion -path "*shadow*" -name "*.mp3"` → 0 files.
- **Consequence:** every speaking-slot lesson silently fails to load audio.
- **Compare:** dictation has all 77 MP3s on disk
  (`app/static/audio/immersion/dictation/dictation_A1_01_greetings.mp3` etc.).

### B. Listening audio metadata authored but never imported

- `content/immersion/listening_immersion_audio.json` (77 entries, all with
  `needs_audio_file: true`) — no `reports/listening_immersion_audio_import.md`.
- `content/immersion/listening_quiz_audio.json` (77 entries) — same.
- `scripts/import_lesson_audio_metadata.py` exists and is tested, but no apply
  report mentions it ran. Initial audit said 77/77 listening lessons miss audio;
  no post-import audit confirms this dropped to 0.
- **Consequence:** existing listening_immersion / listening_quiz lessons still
  have no `audio_url` in DB — audio buttons in the UI are dead.

### C. Vocabulary enrichment CSVs are severely under-targeted

| CSV | Rows | Target (per plan / `docs/content/immersion-content-targets.md`) | Coverage |
| --- | --- | --- | --- |
| `frequency_bands.csv` | 755 | ~24 853 words | **3.0 %** |
| `ipa_transcriptions.csv` | 279 | priority words | ~1.1 % |
| `synonyms_antonyms.csv` | 136 | priority A2–B2 words | <1 % |
| `etymology_notes.csv` | 179 | priority words | <1 % |
| `collocations.csv` | 89 | ≥2 per priority A2–B2 word (~1 000+) | <10 % |
| `cultural_notes.csv` | 60 | idioms + phrasal verbs + politeness (~500+) | <15 % |

This is the largest substantive gap. It's not a code or wiring issue — it's
author work that hasn't happened.

### D. Vocabulary imports against DB — status unknown

- `reports/vocabulary_enrichment.md` is a placeholder:
  > "This file is a placeholder. Generate the live report against the DB by
  > running `python scripts/report_vocabulary_enrichment.py`."
- All 6 vocab importers exist + are tested, but no apply-mode report exists.
- **Consequence:** even the limited CSV data may not be in production DB.
  Vocabulary UI sections likely render with empty optional blocks.

### E. SRS card-source backfill — status unknown

- `scripts/backfill_card_sources.py` + tests exist.
- The audit reported 0/142 `user_card_directions.source` filled. No
  follow-up report shows the backfill ran.

### F. Staging + production rollout reports are placeholders

Both reports explicitly state "Pending Manual Execution":

- `reports/staging_immersion_rollout.md` lists pg_restore / dry-run / apply
  commands but says "Not yet executed — requires staging server access".
- `reports/production_immersion_rollout.md` — same.

So while imports ran against the local/working DB (lesson_ids 973–1394 prove
that), there's no record of a clean staging rebuild → import → audit sweep, and
no record of a production cutover.

### G. listening_quiz audio is item-level only

Audit metadata for `listening_quiz` carries an `exclusion_reason` field saying
each item already has `[sound:name.mp3]` inline. This is design-intent (the
quiz template resolves these), but it means audits of "lesson-level audio_url"
will continue to show 0 for `listening_quiz` — that's by design, not a bug.
Verify the template path resolution works in production.

---

## What This Means in Practice

If the user runs the product today against the DB that received Block C imports:

- ✅ Dictation listening slot works end-to-end (lessons + MP3s present).
- ❌ Shadow-reading speaking slot loads lessons but cannot play audio.
- ❌ Existing listening_immersion / listening_quiz lessons still show no
  audio button (metadata import unconfirmed).
- ⚠️ Vocabulary lessons render with mostly empty optional sections (synonyms,
  collocations, cultural notes, IPA) because either CSVs are tiny or imports
  never ran.
- ⚠️ SRS analytics show empty `source` column for all 142 existing card
  directions.

---

## Recommended Next Work (Outside Plan-Mode Scope — Just a Punch List)

Priority order, from most user-visible to least:

1. **Generate shadow-reading MP3s.** 77 short clips. Either author with TTS
   (existing `scripts/generate_audio.py` is available) or substitute existing
   listening-immersion audio per module. Until then, the speaking slot is dead.
2. **Run audio-metadata import in apply mode** and re-run
   `scripts/audit_immersion_data.py` to confirm zero listening lessons still
   miss audio. Produce `reports/listening_audio_import.md`.
3. **Run vocabulary enrichment imports** (frequency_bands → IPA → syn/ant →
   etymology → collocations → cultural_notes), then regenerate
   `reports/vocabulary_enrichment.md` with real DB counts.
4. **Run SRS card-source backfill** + capture report.
5. **Expand vocabulary CSVs** to closer to target:
   - frequency_bands.csv → ≥3 000 rows (covers ~12 % of vocab vs 3 %)
   - collocations.csv → ≥500 rows
   - cultural_notes.csv → ≥300 rows
   - IPA / synonyms / etymology → ≥1 000 rows each for priority tier.
6. **Execute staging rollout** per runbook, replace placeholder report content
   with real run logs (timestamps, row counts, audit deltas).
7. **Execute production rollout** + attach report to release notes.

Items 1–4 are 1-day operational work given existing tooling. Item 5 is
content-authoring work (days to weeks depending on quality bar). Items 6–7
require operator access to staging/prod.

---

## Critical Files Referenced

- Plans: `docs/plans/completed/2026-05-10-daily-plan-100-tasks.md`,
  `docs/plans/completed/2026-05-11-post-immersion-content-data-plan.md`
- Importers: `scripts/import_immersion_lessons.py`,
  `scripts/import_lesson_audio_metadata.py`,
  `scripts/import_{frequency_bands,ipa_transcriptions,synonyms_antonyms,word_collocations,etymology_notes,cultural_notes}.py`,
  `scripts/backfill_card_sources.py`
- Audits / reports: `scripts/audit_immersion_data.py`,
  `scripts/report_immersion_gaps.py`,
  `scripts/report_vocabulary_enrichment.py`,
  `scripts/audit_existing_listening_payloads.py`
- Content directories: `content/immersion/`, `content/vocabulary/`,
  `app/static/audio/immersion/`

## Verification (How To Reproduce This Analysis)

```bash
# 1. Lessons authored vs DB-imported
ls -1 content/immersion/*.json | xargs -I{} python -c "import json; d=json.load(open('{}')); print('{}', len(d) if isinstance(d,list) else len(d.get('lessons',[])))"
cat reports/{dictation,writing_prompt,shadow_reading,cefr_seed}_import.md | grep -E 'create:|update:|noop:'

# 2. Audio file presence
find app/static/audio/immersion -name "*.mp3" | awk -F/ '{print $(NF-1)}' | sort | uniq -c

# 3. Vocab CSV row counts
for f in content/vocabulary/*.csv; do echo -n "$f rows="; tail -n +2 "$f" | grep -v '^#' | wc -l; done

# 4. Vocab DB coverage (requires DB)
python scripts/report_vocabulary_enrichment.py --output /tmp/vocab_coverage.md
python scripts/audit_immersion_data.py            # full audit (source + DB)

# 5. SRS source backfill
python scripts/backfill_card_sources.py --dry-run
```

The audit script supports `--no-db` for source-only runs and falls back gracefully when no DB is configured.
