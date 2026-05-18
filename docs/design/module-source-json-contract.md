# Module source JSON contract

Authoritative specification for `module_completed/fixed/module_*.json` — the
portable, git-tracked source of truth for curriculum modules. Every module that
ships to production must conform to this contract.

This document is the source-rollout deliverable for Task 2 of
`docs/plans/2026-05-18-module-completed-json-source-rollout.md`. Together with
`content/immersion/README.md` (per-lesson seed files) it defines what authors,
tooling, and importers must agree on.

The companion is the runtime schema in `app/curriculum/validators.py`. The
runtime schema validates lesson `content` after import; this contract validates
the source file as a whole and the surrounding fields (lesson identity, order,
audio refs, progression). Source validators MUST call the runtime schemas
rather than reimplement them.

## 1. File layout

Filename pattern (enforced by tooling):

```
module_completed/fixed/module_<LEVEL>_<ORDER>_<slug>.json
```

* `<LEVEL>` — CEFR code (`A1`, `A2`, `B1`, `B2`, `C1`). Source files do not
  currently cover `C2`.
* `<ORDER>` — 1-based module number within the level. Must match the
  `module.number` (or `module.order` fallback) inside the file.
* `<slug>` — lowercase ASCII slug, words separated by `_`. Stable across edits.

One module per file. One file per `(level, module_number)`.

## 2. Top-level shape

```jsonc
{
  "module": {
    "id": 1,                                  // local 1..N within source export (NOT DB id)
    "number": 1,                              // 1-based module order; preferred identity field
    "order": 1,                               // legacy duplicate of `number`; keep equal
    "title": "Знакомство и приветствия",
    "title_en": "Greetings and Introductions",
    "description": "Научитесь здороваться, ...",
    "level": "A1",
    "input_mode": "selection_only",           // optional UI hint
    "lessons": [ /* see §3 */ ]
  }
}
```

Required keys on `module`: `title`, `title_en`, `description`, `level`,
`number` (or `order`), `lessons`.

`id`, `number`, and `order` are **local** to the file. They are not the DB
primary key and are not the import identity. Tooling resolves the DB module by
`(level, number)`, not by `id`.

## 3. Lesson object

Each entry in `module.lessons[]`:

```jsonc
{
  "id": 9,                       // local 1..N within the module
  "number": 9,                   // local lesson order; must equal `id`
  "order": 9,                    // legacy duplicate of `number`
  "type": "audio_fill_blank",    // canonical lesson type, see §4
  "title": "Аудио: Приветствия и знакомство",
  "title_en": "Audio Fill-in: ...",      // recommended on new-style lessons
  "description": "...",                  // recommended for admin listings
  "xp_reward": 50,                       // see §6
  "grammar_focus": "Восприятие на слух", // free-form summary, optional
  "content": {                           // payload validated by runtime schema
     "external_key": "immersion:audio_fill_blank:A1:01:greetings",
     /* ...type-specific fields, see §5 */
  }
}
```

Mandatory fields on every lesson:

| Field                  | Notes                                                                |
| ---------------------- | -------------------------------------------------------------------- |
| `type`                 | One of the canonical types in §4. Renames break import.              |
| `title`                | Russian title shown in lesson lists.                                 |
| `id` / `number`        | Continuous integers 1..N, matching `lessons[]` index + 1.            |
| `content`              | Object validated by `LessonContentValidator.SCHEMAS[type]`.          |
| `content.external_key` | Required on every new-style lesson, see §7.                          |

Optional but recommended on every lesson: `order` (kept equal to `number` for
backward compat), `xp_reward`, `description`, `grammar_focus`, `title_en`.

`id`, `number`, and `order` are **presentation/order metadata only**. They are
renumbered by `scripts/merge_immersion_into_source_module.py` after merge.
Importers MUST NOT use them as durable identity — see §7.

## 4. Canonical lesson sequence

The expected order in every module is documented in the rollout plan; tooling
enforces it via `CANONICAL_SEQUENCE` in
`scripts/audit_module_completed_json_gaps.py`. Summary:

```
1.  vocabulary               12. dictation
2.  flashcards (first)       13. dialogue_completion_quiz
3.  collocation_matching     14. ordering_quiz
4.  grammar                  15. shadow_reading
5.  sentence_completion      16. flashcards (review)
6.  sentence_correction      17. translation_quiz
7.  quiz (optional)          18. translation
8.  reading                  19. listening_immersion
9.  idiom (B1+ when avail.)  20. writing_prompt
10. listening_quiz           21. final_test
11. audio_fill_blank
```

Required canonical types in every module:

`vocabulary`, `flashcards` (twice), `collocation_matching`, `grammar`,
`sentence_completion`, `sentence_correction`, `reading`, `listening_quiz`,
`audio_fill_blank`, `dictation`, `dialogue_completion_quiz`, `ordering_quiz`,
`shadow_reading`, `translation_quiz`, `translation`, `listening_immersion`,
`writing_prompt`, `final_test`.

Conditional: `quiz` (only when the module already has a grammar practice quiz)
and `idiom` (B1+ where seed content exists). Any module that omits one of
these MUST appear in the audit exemption list with a reason.

`A1/M1` is intentionally exempt from `sentence_correction` (see
`MODULE_TYPE_EXEMPTIONS` in the audit script). Other exemptions require an
explicit entry in `reports/module_completed_json_quality_review.md`.

## 5. Per-type content schemas

The runtime contract lives in `app/curriculum/validators.py`. Source tooling
MUST call `LessonContentValidator.validate(lesson_type, content)` rather than
reimplementing field rules. The map below documents what authors should
write, anchored to that runtime contract.

Legend: ▶ required, · optional, ⚠ source-rollout note.

### vocabulary / flashcards (`VocabularyContentSchema`, `CardContentSchema`)

```jsonc
{
  "external_key": "curriculum:vocabulary:A1:01:greetings",  // ▶
  "vocabulary": [                                            // ▶ one of: vocabulary | words | items | cards
    { "english": "hello", "russian": "привет",
      "pronunciation": "хэлоу",
      "audio": "[sound:pronunciation_en_hello.mp3]",         // legacy Anki ref, OK alongside audio_url
      "example": "Hello, I am Anna.",
      "example_translation": "Привет, я Анна." }
  ],
  "xp_reward": 50                                            // ·
}
```

For `flashcards`, `content.cards[]` is required with `front` + `back`. The
audit script enforces `(vocab_items_min)` per level (§9). Each item should
have an example sentence and an example translation.

### grammar (`GrammarContentSchema`)

Use `rule`/`sections`/`grammar_explanation`/`tldr` for the explanation; use
`exercises` for any inline practice. At least one of the content fields must
be present.

### collocation_matching (`CollocationMatchingContentSchema`)

```jsonc
{
  "external_key": "immersion:collocation_matching:A1:01:greetings_introductions",
  "pairs": [
    { "phrase": "make friends", "translation": "заводить друзей" }
  ]
}
```

⚠ Phrases must come from module vocabulary or natural high-frequency pairings;
do not insert machine-generated stubs.

### sentence_completion (`SentenceCompletionContentSchema`)

```jsonc
{
  "external_key": "immersion:sentence_completion:A1:01:to_be",
  "items": [
    { "prompt": "My name ___ Anna.", "answer": "is", "context": "introducing yourself" }
  ]
}
```

### sentence_correction (`SentenceCorrectionContentSchema`)

Prefer the multi-item shape (`items[]`); legacy single-item top-level fields
are still accepted by the runtime but new content must use `items[]` so the
lesson can carry 4–6 errors with explanations.

```jsonc
{
  "external_key": "immersion:sentence_correction:A1:01:to_be",
  "items": [
    { "incorrect_sentence": "She are happy.",
      "correct_sentence":   "She is happy.",
      "error_type": "subject_verb_agreement",
      "error_type_ru": "Согласование подлежащего и сказуемого",
      "explanation": "Третье лицо единственного числа — is.",
      "translation": "Она счастлива.",
      "options": ["She is happy.", "She am happy.", "She be happy."] }
  ]
}
```

`mode` is a recommended new-style field on the top-level content; see the
runtime docstring for the difficulty ladder.

### quiz / listening_quiz / dialogue_completion_quiz / ordering_quiz / translation_quiz (`QuizContentSchema`)

Use `exercises[]` (preferred) or `questions[]`. Each entry follows
`QuizQuestionSchema`. Listening variants must carry `audio` per item;
dialogue/ordering variants must follow the `dialogue_completion` /
`ordering` question types defined in the runtime schema.

### reading (`TextContentSchema`)

```jsonc
{
  "external_key": "curriculum:reading:A1:01:new_friends",
  "text": "...",            // ▶ string OR structured object
  "exercises": [ ... ],     // · comprehension exercises
  "questions": [ ... ]      // · alias of exercises
}
```

⚠ Text length must meet the level's progression band (§9). Later modules must
not reuse A1-style scripts.

### idiom (`IdiomContentSchema`) — B1+

```jsonc
{
  "external_key": "immersion:idiom:B1:03:break_the_ice",
  "items": [
    { "phrase": "break the ice", "meaning": "начать общение",
      "example": "He told a joke to break the ice.",
      "audio_url": "/static/audio/immersion/idiom/idiom_B1_03_break_the_ice.mp3" }
  ]
}
```

### audio_fill_blank (`AudioFillBlankContentSchema`)

```jsonc
{
  "external_key": "immersion:audio_fill_blank:A1:01:greetings",
  "audio_url": "/static/audio/immersion/audio_fill_blank/afb_A1_01_greetings.mp3",
  "items": [
    { "text_with_gap": "Hello! My ___ is Tom.",
      "answer": "name",
      "options": ["name", "age", "job", "city"],
      "audio_clip_url": "/static/audio/immersion/audio_fill_blank/afb_A1_01_item0.mp3" }
  ]
}
```

Top-level `audio_url` is the umbrella clip. Each item should also carry
`audio_clip_url` so the lesson can play the line in isolation.

### dictation (`DictationContentSchema`)

```jsonc
{
  "external_key": "immersion:dictation:A1:01:greetings",
  "audio_url": "/static/audio/immersion/dictation/dictation_A1_01_greetings.mp3",
  "transcript": "Hello! My name is Anna. ...",
  "audio_text": "Hello! ...",                        // legacy mirror
  "gap_text": "Hello! My {0} is Anna. I {1} from Russia. ...",
  "gaps": [
    { "index": 0, "answer": "name", "hint": "n", "source_word_index": 2 }
  ],
  "hint_chars": 1,
  "duration_seconds": 14,
  "mode": "cloze"                                    // cloze | phrase_cloze | sentence_reconstruction | full_dictation
}
```

`mode` is auto-derived from the presence of `gaps`; setting it explicitly is
recommended for B1+.

### shadow_reading (`ShadowReadingContentSchema`)

```jsonc
{
  "external_key": "immersion:shadow_reading:A1:01:greetings",
  "audio_url": "/static/audio/immersion/shadow_reading/shadow_reading_A1_01_greetings.mp3",
  "text": "Hello! My name is Anna. I am from Russia. Nice to meet you.",
  "translation": "Привет! Меня зовут Анна. Я из России. Приятно познакомиться."
}
```

### translation (`TranslationContentSchema`)

Prefer the multi-item shape. The runtime auto-derives `mode` from
`hint_words` presence, but new content should set `mode` explicitly.

```jsonc
{
  "external_key": "immersion:translation:A1:01:introductions",
  "mode": "guided",                                   // guided | open | rubric
  "items": [
    { "russian": "Меня зовут Анна.",
      "english": "My name is Anna.",
      "hint_words": ["My", "name", "is", "Anna"],
      "alternatives": ["I'm Anna."] }
  ]
}
```

### writing_prompt (`WritingPromptContentSchema`)

```jsonc
{
  "external_key": "immersion:writing_prompt:A1:01:greetings",
  "prompt": "Introduce yourself in 4-5 sentences.",
  "prompt_ru": "Напишите короткое знакомство ... 4–5 предложений.",
  "mode": "guided",                                   // guided | structured | paragraph | opinion | style | rhetoric
  "min_sentences": 4,
  "min_checklist": 3,
  "checklist": [ "Есть приветствие", "Указано имя", ... ],
  "target_phrases": ["My name is", "I am from"],
  "hint_words": ["hello", "name", "age", "country"],
  "example_response": "Hello! My name is Anna. ...",
  "template": "Hello! My name is ___. I am from ___ ..."
}
```

⚠ `prompt_ru` is mandatory for new-style content. Do not machine-translate
blindly; curate by module level.

### listening_immersion (`TextContentSchema` alias)

```jsonc
{
  "external_key": "curriculum:listening_immersion:A1:01:coffee_shop",
  "title": "В кофейне",
  "audio": "[sound:A1_M1_L11_dialogue.mp3]",          // legacy Anki ref
  "audio_url": "/static/audio/A1_M1_L11_dialogue.mp3", // ▶ for runtime player
  "text": "Sarah: Good morning! ...",
  "translation": "Доброе утро! ...",
  "instruction": "Прослушайте диалог несколько раз.",
  "duration_seconds": 54
}
```

### pronunciation (`PronunciationContentSchema`) — opt-in only

Source tooling MUST NOT auto-insert `pronunciation` lessons. Speaking practice
stays centred on `shadow_reading` unless the module already carries curated
pronunciation content.

### final_test (`FinalTestContentSchema`)

Use `test_sections[]` (preferred) or `sections[]`. Each section uses
`exercises[]`/`questions[]` with `QuizQuestionSchema` entries. Cover every
lesson type added to the module; no stub phrasing like «Сделайте вопрос».
Matching pairs must use the display-friendly `english`/`russian` shape.

## 6. XP metadata

`xp_reward` on a lesson is **source/display metadata**. The actual daily-plan
XP award comes from `app/achievements/xp_service.py::LINEAR_XP`, keyed on the
internal source key (not on `xp_reward`).

Source-key table (current values, last verified against `xp_service.py`):

| Source key                                         | XP |
| -------------------------------------------------- | -: |
| `linear_curriculum_card`                           | 20 |
| `linear_curriculum_vocabulary`                     | 18 |
| `linear_curriculum_grammar`                        | 18 |
| `linear_curriculum_quiz`                           | 12 |
| `linear_curriculum_listening_quiz`                 | 12 |
| `linear_curriculum_dialogue_completion_quiz`       | 12 |
| `linear_curriculum_ordering_quiz`                  | 12 |
| `linear_curriculum_translation_quiz`               | 12 |
| `linear_curriculum_final_test`                     | 12 |
| `linear_curriculum_reading`                        | 15 |
| `linear_curriculum_listening_immersion`            | 15 |
| `linear_curriculum_dictation`                      | 20 |
| `linear_curriculum_audio_fill_blank`               | 18 |
| `linear_curriculum_use` (writing/speaking-style)   | 25 |
| `linear_listening`                                 | 18 |
| `linear_writing`                                   | 25 |
| `linear_srs_global`                                |  8 |
| `linear_book_reading`                              | 15 |
| `linear_error_review`                              | 10 |

Rules of thumb for authors:

* Use `xp_reward = 50` for vocabulary/flashcards/reading-style intro lessons.
* Use `xp_reward = 75` for quiz-style lessons.
* Use `xp_reward = 100` for `final_test`.
* New-style immersion lessons inherit the same banding (`xp_reward` 50/75 by
  lesson weight). Do not invent new numbers.

## 7. Lesson identity

Source-local `id` / `number` / `order` are **presentation metadata**. The DB
identity of a lesson is its `lessons.id`; the durable contract between source
JSON and that DB row is `content.external_key`.

`external_key` rules:

* Required on every new-style immersion lesson and on every lesson rewritten
  by the rollout.
* Format: `{source}:{lesson_type}:{level}:{module_number:02d}:{slug}`.
  * `{source}` is `curriculum` for original spine lessons and `immersion` for
    rollout-inserted lessons.
  * `{slug}` is lowercase ASCII, stable across content edits, ≤40 chars.
  * Examples (taken from `module_A1_1_greetings.json`):
    `curriculum:vocabulary:A1:01:greetings`,
    `immersion:audio_fill_blank:A1:01:greetings`,
    `immersion:writing_prompt:A1:01:greetings`.
* CEFR-seed files in `content/immersion/` use `seed` in the module slot —
  for example `audio_fill_blank:B1:seed:weather_forecast`. They map to a
  module via `module_insertion_map.csv` and are never per-module-anchored.
* Never reuse a slug across lessons. Never rename a slug to fix a typo in the
  title; rename the title, not the contract.

Import / diff rules (consumed by `scripts/import_immersion_lessons.py` and
`scripts/diff_module_json_against_db.py`):

1. Match a source lesson to a DB row by `content.external_key`.
2. If `external_key` is absent on both sides, fall back to
   `(level, module_number, lesson_type, title)`. Never to `number` alone.
3. When `external_key` matches, update only the import-owned fields
   (`title`, `type`, `content`, optionally `description`, `number`). Never
   overwrite a different DB row just because its old `number` matches the
   new position.
4. `number`-collision diff signals are non-fatal as long as `external_key`
   resolves; otherwise the diff must surface them for human review before
   apply.

## 8. Audio path rules

Audio refs come in two shapes:

* **Legacy Anki** — `"audio": "[sound:filename.mp3]"`. Allowed on vocabulary
  examples and `listening_immersion` for backward compatibility; the runtime
  resolves them through Anki-style URL helpers.
* **Static** — `"audio_url": "/static/audio/.../filename.mp3"`. Required on
  every audio-bearing lesson type (`dictation`, `audio_fill_blank`,
  `shadow_reading`, `listening_immersion`, `listening_quiz`). The path must
  be repo-relative under `/static/audio/`, no remote URLs, no `..`.

Storage layout:

```
app/static/audio/
  A1M1L6_ex1.mp3                          # legacy per-module clips
  A1_M1_L11_dialogue.mp3                  # legacy immersion dialogues
  immersion/
    audio_fill_blank/afb_<LEVEL>_<MM>_<slug>.mp3
    audio_fill_blank/afb_<LEVEL>_<MM>_item<N>.mp3
    dictation/dictation_<LEVEL>_<MM>_<slug>.mp3
    shadow_reading/shadow_reading_<LEVEL>_<MM>_<slug>.mp3
```

Every JSON `audio_url` must resolve to an existing file on disk. The
audit/validator scripts enforce this; the production runbook (Task 9) uses
the audio manifest in `reports/module_completed_audio_manifest.md`.

Binaries live outside git for now. They are tracked in the manifest and
copied as part of the production transfer step.

## 9. Progression rubric

Within each module the lessons follow §4. Across modules the difficulty has
to grow by CEFR level and by module number. The audit script enforces coarse
minimums; manual review (Task 4) enforces the rest.

Minimum coarse bands (from `PROGRESSION_BANDS` in the audit script):

| Level | reading words ≥ | vocab items ≥ | listening words ≥ |
| ----- | --------------: | ------------: | ----------------: |
| A1    |              60 |             8 |                60 |
| A2    |             110 |            10 |               100 |
| B1    |             180 |            10 |               160 |
| B2    |             260 |            12 |               220 |
| C1    |             330 |            12 |               300 |

Within each level, modules should trend upward on at least two of:
text/audio length, vocabulary density, grammar complexity, reduced hint
density, freer response mode, distractor plausibility. Any exception belongs
in `reports/module_completed_json_quality_review.md` with a reason.

Authoring axes (full list lives in the rollout plan):

* **Vocabulary load** — more words, less concrete, more collocations.
* **Sentence complexity** — short clauses → narratives → reporting/passive.
* **Task openness** — selection/guided → free production with rubrics.
* **Listening/reading length** — grows steadily; later modules do not reuse
  short A1-style scripts.
* **Distractor quality** — plausible near-synonyms at higher levels.
* **Review continuity** — earlier grammar/vocab as background only, not as
  the primary target.

## 10. Source validation

Run order:

1. **`scripts/audit_module_completed_json_gaps.py`** — surveys the whole tree,
   reports missing/duplicate canonical types, invalid `id`/`number`/`order`,
   missing content fields, missing audio refs, and progression-band misses.
2. **`scripts/validate_module_completed_json.py`** *(Task 6, planned)* —
   per-file deep validation that delegates per-type rules to
   `app/curriculum/validators.py::LessonContentValidator` and adds:
   * `id` / `number` / `order` are continuous 1..N;
   * every audio reference resolves to a real file under
     `app/static/audio/`;
   * `external_key` is present and unique across the tree;
   * no placeholder copy (`Сделайте вопрос`, empty `prompt`, etc.).

A source file is only ready to apply when both scripts return zero blocking
errors and a human review (Task 4) has signed off on the new lessons.

## 11. Production transfer workflow

JSON-first. DB is reconciled from JSON, never the other way around.

```
[author edits source JSON] ─┐
                            ▼
                    audit + validate (§10)
                            │
                            ▼
              scripts/merge_immersion_into_source_module.py
                  (pilot → per-level review → batch)
                            │
                            ▼
              scripts/diff_module_json_against_db.py
                  (dry-run against staging DB)
                            │
                            ▼
              scripts/import_immersion_lessons.py
                  (staging apply → re-run dry-run must be 0 changes)
                            │
                            ▼
              audio sync per audio manifest
                  (reports/module_completed_audio_manifest.md)
                            │
                            ▼
                production backup + apply
                            │
                            ▼
                  post-apply audit + rollback drill
```

Staging apply must be idempotent (re-run reports `0 changes`). Production
apply uses the same command sequence with the prod DB URL. The full runbook
lives in `reports/module_completed_json_prod_runbook.md` (Task 9).

Rollback is a JSON revert + re-run of the importer; user progress is never
touched because every lesson identity is anchored on `external_key`.

## 12. Cross-references

* Runtime schema: `app/curriculum/validators.py`
* Per-lesson seed contract: `content/immersion/README.md`
* Canonical sample: `module_completed/fixed/module_A1_1_greetings.json`
* Rollout plan: `docs/plans/2026-05-18-module-completed-json-source-rollout.md`
* Audit script: `scripts/audit_module_completed_json_gaps.py`
* Importer: `scripts/import_immersion_lessons.py`
* XP source keys: `app/achievements/xp_service.py::LINEAR_XP`
* Daily-plan integration: `app/daily_plan/linear/xp.py`
