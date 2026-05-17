# Lesson Content Schemas (Immersion Lesson Types)

Canonical source: `app/curriculum/validators.py` — every type listed below is
registered in `LessonContentValidator.SCHEMAS` and validated when a lesson is
saved (admin form, importer, or API write). Submission grading lives in
`app/curriculum/routes/lessons.py` (`_process_*_submission`) and the relevant
graders in `app/curriculum/grading.py`.

Each schema below describes the shape of `Lessons.content` (JSONB) for that
lesson type. Unknown fields are accepted (`Meta.unknown = INCLUDE`) but only
listed fields are guaranteed to drive the UI or grader. The
`import_immersion_lessons.py` (Task 10) writer must also include a stable
`external_key` field at the top of `content` — that key is NOT validated by the
schema, but is required by the importer for idempotency.

CEFR coverage targets, audio quality bars, and per-module coverage rules live
in `docs/content/immersion-content-targets.md`.

---

## dictation

Schema: `DictationContentSchema`

| Field          | Type    | Required | Notes                                             |
|----------------|---------|----------|---------------------------------------------------|
| `audio_url`    | string  | yes      | Public URL or `/static/...` path, non-empty.      |
| `transcript`   | string  | yes      | Reference answer, used by grader.                 |
| `hint_chars`   | int     | no (0)   | Number of leading chars revealed as a hint, >=0.  |

Submission payload: `{ user_text, replay_count?, hint_chars? }`.
Grading: `grade_dictation` — token-level accuracy, pass threshold 80%.
Recommended additions for authors (NOT schema-enforced):
- `duration_seconds` (int) — drives audio length checks in Task 33.
- `external_key` (string) — required for idempotent re-import.

---

## audio_fill_blank

Schemas: `AudioFillBlankContentSchema`, `AudioFillBlankItemSchema`

| Field        | Type             | Required | Notes                                       |
|--------------|------------------|----------|---------------------------------------------|
| `audio_url`  | string           | yes      | Lesson-level audio used as the main clip.   |
| `items`      | list of item     | yes      | At least one item.                          |

Item:

| Field             | Type   | Required | Notes                                              |
|-------------------|--------|----------|----------------------------------------------------|
| `audio_clip_url`  | string | no       | Optional per-item clip, overrides lesson audio.    |
| `text_with_gap`   | string | yes      | Sentence with `___` gap, non-empty.                |
| `answer`          | string | yes      | Canonical answer.                                  |
| `options`         | list   | no       | 2-6 distractors for MC mode; absent => free text.  |

Submission payload: `{ answers: [string, ...], replay_count? }` aligned with
`items` order. Grading: `grade_audio_fill_blank` — per-item Levenshtein
typo-tolerance.

---

## translation

Schema: `TranslationContentSchema` (standalone, not the `translation_quiz` alias).

| Field         | Type   | Required | Notes                                  |
|---------------|--------|----------|----------------------------------------|
| `russian`     | string | yes      | Source sentence in Russian.            |
| `english`     | string | yes      | Reference target sentence.             |
| `hint_words`  | list   | no       | Optional word bank for low-CEFR seeds. |

Submission payload: `{ user_answer }` (max 2000 chars). Grading:
`grade_translation` — strict normalised match, must pass 100%.
Side effect: writes `UserWritingAttempt`.

---

## sentence_correction

Schema: `SentenceCorrectionContentSchema`

| Field                | Type   | Required | Notes                                                 |
|----------------------|--------|----------|-------------------------------------------------------|
| `incorrect_sentence` | string | yes      | What the user sees first.                             |
| `correct_sentence`   | string | yes      | Reference correct version (grader compares to this).  |
| `error_type`         | string | yes      | Free-form label, e.g. `article`, `tense`.             |
| `explanation`        | string | yes      | Shown after submission.                               |
| `options`            | list   | no       | 2-6 options for MC mode on lower CEFR levels.         |

Submission payload: `{ user_answer }` (max 2000 chars). Grading:
`grade_sentence_correction` — strict match, must equal `correct_sentence` after
normalisation. Side effect: writes `UserWritingAttempt`.

---

## writing_prompt

Schema: `WritingPromptContentSchema`

| Field              | Type   | Required | Notes                                                            |
|--------------------|--------|----------|------------------------------------------------------------------|
| `prompt`           | string | yes      | The writing task shown to the user.                              |
| `min_words`        | int    | yes      | Minimum word count to count as completed; must be >=1.           |
| `example_response` | string | no       | Optional reference response, surfaced after completion.          |
| `checklist`        | list   | no       | Self-assess checklist; if absent, route uses a Russian default.  |

Submission payload: `{ response_text, checklist_completed, checked_items: [...] }`.
Completion logic: `word_count >= min_words AND len(checked_items) >= 2`.
Side effect: writes `UserWritingAttempt`. XP via
`maybe_award_writing_xp` (linear, extension-slot only).

---

## sentence_completion

Schemas: `SentenceCompletionContentSchema`, `SentenceCompletionItemSchema`

| Field   | Type           | Required | Notes              |
|---------|----------------|----------|--------------------|
| `items` | list of item   | yes      | At least one item. |

Item:

| Field     | Type   | Required | Notes                                      |
|-----------|--------|----------|--------------------------------------------|
| `prompt`  | string | yes      | First half of the sentence shown to user.  |
| `answer`  | string | yes      | Reference completion.                      |
| `context` | string | no       | Optional context shown beside the prompt.  |

Submission payload: `{ answers: [string, ...] }` aligned with `items` order.
Grading: `grade_sentence_completion` — per-item typo tolerance, pass at 70%.

---

## collocation_matching

Schemas: `CollocationMatchingContentSchema`, `CollocationPairSchema`

| Field   | Type         | Required | Notes              |
|---------|--------------|----------|--------------------|
| `pairs` | list of pair | yes      | At least one pair. |

Pair:

| Field         | Type   | Required | Notes                       |
|---------------|--------|----------|-----------------------------|
| `phrase`      | string | yes      | English collocation.        |
| `translation` | string | yes      | Russian translation.        |

Submission payload: `{ user_pairs: [{phrase, translation}, ...] }`. Grading:
`grade_collocation_matching` — server-side strict equality on the pair set,
pass at 70%. Authors must keep distractors level-appropriate; the importer
should reject duplicate `phrase` values inside a lesson.

---

## shadow_reading

Schema: `ShadowReadingContentSchema`

| Field         | Type   | Required | Notes                                                |
|---------------|--------|----------|------------------------------------------------------|
| `audio_url`   | string | yes      | The model audio the user shadows.                    |
| `text`        | string | yes      | The text the user reads aloud while listening.       |
| `translation` | string | yes      | Russian translation rendered alongside.              |

The route also accepts an optional `words: [...]` array on `content` for
inline glossary chips — not enforced by schema, render-only.

Submission payload: `{ self_assessed: bool }`. Completion is honour-system; XP
fires via `maybe_award_curriculum_xp` when `self_assessed=True`.

---

## pronunciation

Schemas: `PronunciationContentSchema`, `PronunciationItemSchema`

| Field   | Type         | Required | Notes              |
|---------|--------------|----------|--------------------|
| `items` | list of item | yes      | At least one item. |

Item:

| Field                 | Type   | Required | Notes                                                  |
|-----------------------|--------|----------|--------------------------------------------------------|
| `word`                | string | yes      | Target word the user pronounces.                       |
| `pronunciation_hint`  | string | no       | Phonetic hint, e.g. "/ˈθɪŋ/".                          |
| `audio_url`           | string | no       | Reference audio; if absent, browser TTS is used.       |

Submission payload comes in three shapes:
- per-item attempt: `{ target_word, recognized_text }` (Web Speech API).
- self-assessed item: `{ target_word, self_assessed: true }` (browsers without
  speech recognition).
- final: `{ finish: true }` — marks lesson completed and awards XP.

Grading: `grade_pronunciation_match` returns
`{matched: bool, similarity: float}`. Daily rate limit:
`PRONUNCIATION_DAILY_LIMIT` enforced in the route. Side effect:
`PronunciationAttempt` rows via `log_pronunciation_attempt`.

---

## idiom

Schemas: `IdiomContentSchema`, `IdiomItemSchema`

| Field   | Type         | Required | Notes              |
|---------|--------------|----------|--------------------|
| `items` | list of item | yes      | At least one item. |

Item:

| Field        | Type   | Required | Notes                                          |
|--------------|--------|----------|------------------------------------------------|
| `phrase`     | string | yes      | The idiom phrase shown first.                  |
| `meaning`    | string | yes      | Plain-language meaning revealed after tap.     |
| `example`    | string | yes      | Example sentence using the idiom.              |
| `audio_url`  | string | no       | Optional reference audio.                      |

Submission payload: `{ finish: true }` once the user has cycled through all
items. Completion sets `LessonProgress.status='completed'`. No graded score.
Authors should mark culturally sensitive idioms in a sidecar review note (the
schema does not encode this — Task 28).

---

## Author conventions shared by all immersion lesson types

The following fields are NOT schema-enforced but ARE expected by the rest of
the immersion pipeline. Importer (Task 10) and gap report (Task 12) treat them
as authoritative.

| Field            | Where it lives                | Used by                                                   |
|------------------|-------------------------------|-----------------------------------------------------------|
| `external_key`   | top of `Lessons.content`      | Importer idempotency, gap report dedupe.                  |
| `environment`    | top of `Lessons.content`      | Staging-only fixtures; importer filters with `--env`.     |
| `duration_seconds` | top of `Lessons.content`    | Audio quality checks (Task 33), admin content-quality.    |
| `audio_url` (lesson-level) | top of `Lessons.content` | Audio metadata audit (Task 30, 34).                |

Validation always happens through `LessonContentValidator.validate(lesson_type,
content)`. Any new immersion content must round-trip through that call before
hitting the DB.
