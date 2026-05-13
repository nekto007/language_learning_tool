# Lesson frontend spec — modern lesson UI

This spec is the contract for the redesign of nine lesson templates
(writing_prompt, shadow_reading, audio_fill_blank, translation,
sentence_correction, sentence_completion, pronunciation,
collocation_matching, listening_immersion) against the modern pattern
already established by vocabulary.html / matching.html / dictation.html /
idiom.html.

Submission payloads listed here are **frozen contracts**. They mirror the
field names consumed by the backend submit handlers in
`app/curriculum/routes/lessons.py` (see `_process_*_submission` and
`submit_lesson` dispatcher); any redesign must keep these keys identical.

---

## 1. Shared lesson shell

A single visual scaffold drives every lesson. Reuse the class taxonomy
defined in `app/static/css/design-system.css`. Components below are
mandatory unless marked optional.

### HTML skeleton

```html
<section class="lesson-shell" aria-labelledby="lesson-shell-title">
  <header class="lesson-shell__header">
    <h1 class="lesson-shell__title" id="lesson-shell-title">{{ component_name }}</h1>
    <div class="lesson-shell__meta">
      <span class="lesson-shell__type-icon" aria-hidden="true"><i class="fas fa-..."></i></span>
      <span class="lesson-shell__progress" aria-live="polite">
        <span data-progress-current>1</span> / <span data-progress-total>{{ total }}</span>
      </span>
    </div>
    <div class="lesson-shell__progress-bar" role="progressbar"
         aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
      <span class="lesson-shell__progress-fill" style="width:0%"></span>
    </div>
  </header>

  <div class="lesson-shell__instruction" role="note">
    {{ instruction_text }}
    <!-- optional .lesson-shell__help-toggle -->
  </div>

  <div class="lesson-shell__body">
    <!-- lesson-specific cards (.lesson-shell__card) -->
  </div>

  <div class="lesson-shell__actions">
    <button class="btn btn-primary btn-lg" data-action="primary">…</button>
    <button class="btn btn-outline" data-action="secondary">…</button>
  </div>

  <div class="lesson-shell__result"
       role="status" aria-live="polite" aria-atomic="true" hidden>
    <!-- .result-badge.result-badge--correct | --incorrect | --neutral -->
  </div>
</section>
```

### Class taxonomy (introduced or formalised in Task 2)

- `.lesson-shell` — outer container, max-width 720px, border-radius 1rem,
  soft shadow, padding 1.5rem, centred.
- `.lesson-shell__header` — sticky on scroll, holds title + progress.
- `.lesson-shell__progress` / `.lesson-shell__progress-bar` /
  `.lesson-shell__progress-fill` — counter + visual bar.
- `.lesson-shell__instruction` — subtle background panel, optional
  `.lesson-shell__help-toggle` collapsible.
- `.lesson-shell__body` — column container for lesson-specific cards.
- `.lesson-shell__card` — white background, light border, hover/focus rings.
- `.lesson-shell__actions` — flex row with primary + outline secondary,
  spinner state via `.btn--loading`.
- `.lesson-shell__result` — aria-live region, hidden until populated.
- `.result-badge`, `.result-badge--correct`, `.result-badge--incorrect`,
  `.result-badge--neutral` — single, consistent badge.
- Input states: `.input--correct`, `.input--wrong`, `.input--checking`.
- Option buttons: `.option-btn`, `.option-btn--selected`,
  `.option-btn--correct`, `.option-btn--wrong`.
- Hint chips: `.chip`, `.chip--clickable`.

### Accessibility (applies to all lessons)

- Title is `<h1>` and matches the page heading.
- Progress counter inside an `aria-live="polite"` region.
- Result region is `role="status"` with `aria-live="polite"` and
  `aria-atomic="true"`.
- Inputs are linked to labels via `for=`/`id=`.
- Option buttons get `aria-pressed` toggled on selection; correct/wrong
  states use both colour and an icon.
- All animations respect the global `prefers-reduced-motion` block in
  design-system.css.

### Keyboard map (default)

- `Enter` — primary submit when an input has focus (where applicable;
  multi-input lessons advance to next input first).
- `Esc` — cancel pending state (close help panel, abort speech
  recognition).
- `Tab` — natural focus order; option buttons participate.

### Empty / error states

- If `lesson.content` lacks required fields, the page renders an
  `empty_content.html` partial via the existing route guard — the shell
  is not responsible for empty handling. Per-lesson sections below note
  what the route must guarantee.

---

## 2. Per-lesson specs

Each section names the lesson, its purpose, the `lesson.content` schema
it consumes, the UI it renders, interactions, the submission payload
(frozen), feedback, edge cases, a11y notes, and the keyboard map. Where a
field is "frozen" it means the JS body must serialise it under exactly
that key.

---

### 2.1 writing_prompt

**Purpose:** practise long-form English writing against a prompt and a
self-check list.

**Content schema (read in `writing_prompt_lesson`):**

- `prompt: str` — task statement.
- `min_words: int` (default 50).
- `example_response: str | None` — revealed after success.
- `checklist: list[str]` — optional; default list provided by route.

**UI top-to-bottom:**

1. Shared header (title, type icon, progress 1/1, bar).
2. Task card (`.lesson-shell__card`) showing prompt and "minimum N words"
   meta.
3. Input section: label, autosize `<textarea id="writing-response">`,
   live `data-word-count` meter (`current / min`).
4. Checklist (`.lesson-shell__card`) — checkbox list with the existing
   "min 2 checked" gate; show a hint when the gate is not met.
5. Primary action: "Завершить" → loading state on submit.
6. Result area (`.lesson-shell__result`) with a `.result-badge` and, on
   success, the optional `example_response`.

**Interactions / state machine:**

- `idle` → typing updates word count.
- On submit: validate `count >= min_words` and `checkedItems.length >= 2`.
  Failures stay in `idle` with inline hint (no alert).
- `submitting` → button shows spinner via `.btn--loading`.
- `done` → badge + optional example + next-lesson CTA.

**Submission payload (frozen, POST `/learn/api/lesson/<id>/submit`):**

```json
{
  "response_text": "<string>",
  "checklist_completed": true,
  "checked_items": ["<label>", ...],
  "lesson_type": "writing_prompt"
}
```

Backend reads: `response_text`, `checklist_completed`, `checked_items`.
The redesign keeps these keys unchanged.

**Result UI:** `.result-badge--correct` on `data.completed`, else
`.result-badge--neutral` with the hint copy from the existing template
("Добавьте ещё слов" / "Отметьте пункты проверочного списка").

**Edge cases:** empty `checklist` → route falls back to
`_DEFAULT_WRITING_CHECKLIST` (4 items); UI must show "min 2 checked" no
matter the list length.

**A11y notes:** textarea labelled by visible label; word-count meter is
`aria-live="polite"`; checklist hint is `role="note"` shown when gate
not met.

**Keyboard map:** `Ctrl+Enter` submits from the textarea; `Tab` cycles
through checklist; `Space` toggles a checkbox.

**Gap vs current template:** rewrap in `.lesson-shell`; remove inline
`alert()` calls — surface validation through the inline hint /
`.result-badge--neutral`; convert manual badge `innerHTML` to the
shared `.result-badge` classes; add autosize behaviour to textarea.

---

### 2.2 translation

**Purpose:** translate a Russian sentence into English, with optional
clickable hint words.

**Content schema (read in `translation_lesson`):**

- `russian: str` — source sentence.
- `english: str` — correct answer (server-side only, leaks via result).
- `hint_words: list[str]` (optional).

**UI top-to-bottom:**

1. Shared header.
2. Source card with the Russian sentence and a clear "translate to
   English" label.
3. Optional `.chip.chip--clickable` row of hint words; clicking inserts
   the word at the cursor and marks the chip as used (`.chip--used`).
4. Single-line input (`.lesson-shell__card` wrapping a labelled input
   with `.input--*` states).
5. Primary action: "Проверить".
6. Result region: `.result-badge`, plus correct-answer reveal on miss.

**Interactions:** `Enter` submits; first miss switches the input to
`.input--wrong`, shows `.result-badge--incorrect` plus the canonical
correct answer; user can retry. Success transitions input to
`.input--correct` and reveals the next-lesson CTA.

**Submission payload (frozen):**

```json
{
  "user_answer": "<string>",
  "lesson_type": "translation"
}
```

Backend reads `user_answer`; everything else is server-derived.

**Result UI:** badge state from `data.is_correct`; correct-answer reveal
uses `data.correct_answer`.

**Edge cases:** missing `hint_words` ⇒ section omitted (already handled
in template); user submits empty text ⇒ inline hint inside
`.lesson-shell__result` (not `alert`).

**A11y notes:** chips are `<button type="button">` with
`aria-pressed="false"`; flipped to `aria-pressed="true"` once inserted;
result badge inside the aria-live region.

**Keyboard map:** `Enter` submits; chips reachable via `Tab` and
activated with `Space`/`Enter`.

**Gap vs current template:** replace bespoke `translation-*` classes
with `.lesson-shell__*`, `.chip`, `.input--*`, `.result-badge`; remove
`alert` calls.

---

### 2.3 sentence_completion

**Purpose:** finish a list of partial sentences with one-line answers
per item, graded together.

**Content schema (read in `sentence_completion_lesson`):**

- `items: list[{ prompt: str, answer: str, context?: str }]`.

**UI top-to-bottom:**

1. Shared header (progress `N items`).
2. Per-item card: optional context line, prompt span, inline input with
   `.input--*` states, per-item feedback slot (badge + model answer).
3. Primary action: "Проверить".
4. Result summary card showing `correct / total` + score%, plus
   `.result-badge--correct` or `--incorrect`.

**Interactions:**

- `Enter` in an input advances focus to the next item, or submits when
  on the last one.
- On submit: each item gets a `.result-badge--correct` /
  `--incorrect`; wrong items reveal the model answer inline.

**Submission payload (frozen):**

```json
{
  "answers": ["<string per item>"],
  "lesson_type": "sentence_completion"
}
```

Backend reads `answers` (list aligned with `items`).

**Result UI:** uses `data.item_results[].correct` + `.answer` for
inline reveals; `data.passed`, `data.score`, `data.correct_items`,
`data.total_items` for the summary.

**Edge cases:** empty `items` list ⇒ the route should not reach the
template; handled upstream.

**A11y notes:** each input has a `for=`/`id=` label combining the
context and prompt; the per-item feedback slot is `role="status"`.

**Keyboard map:** as above; `Tab` natural; `Enter` advances/submits.

**Gap vs current template:** rewrap in shell; replace per-item bespoke
classes with `.lesson-shell__card` + `.input--*` + `.result-badge`.

---

### 2.4 sentence_correction

**Purpose:** spot and fix one error in a sentence, either via multiple
choice or free-text.

**Content schema (read in `sentence_correction_lesson`):**

- `incorrect_sentence: str`.
- `correct_sentence: str` (server-side; revealed on miss).
- `error_type: str` — short label.
- `explanation: str` — revealed after grading.
- `options: list[str]` (optional). When present, render `.option-btn`
  group; absent → textarea.

**UI top-to-bottom:**

1. Shared header.
2. Source card: error-type chip + the incorrect sentence.
3. Either `.option-btn` group **or** a textarea (mutually exclusive).
4. Primary action: "Проверить" — disabled until an option is selected
   or the textarea has non-empty content.
5. Result region: `.result-badge`, explanation reveal, correct-sentence
   reveal on miss.

**Interactions:** option mode marks the chosen button with
`.option-btn--selected`. Submit reveals correct/wrong states via
`.option-btn--correct` / `--wrong`. Textarea mode toggles `.input--*`.

**Submission payload (frozen):**

```json
{
  "user_answer": "<string>",
  "lesson_type": "sentence_correction"
}
```

`user_answer` is the option label or the textarea content.

**Result UI:** badge by `data.is_correct`; explanation from
`data.explanation` (falls back to the server-rendered one);
`data.correct_sentence` for the reveal.

**Edge cases:** both options provided + textarea ⇒ template renders the
options branch only (controlled by `if options`); user submits empty ⇒
inline hint, no alert.

**A11y notes:** option buttons get `aria-pressed`; result region is
aria-live; explanation reveal uses
`role="note"`.

**Keyboard map:** `Enter` submits when an option is selected; in
textarea, `Enter` (without Shift) submits.

**Gap vs current template:** rewrap in shell; convert
`sentence-correction-option-btn`/`-input` to `.option-btn` / `.input--*`.

---

### 2.5 shadow_reading

**Purpose:** three-phase listening → read-aloud → self-assess.

**Content schema (read in `shadow_reading_lesson`):**

- `audio_url: str`.
- `text: str` — fallback when `words` empty.
- `translation: str | None`.
- `words: list[{ text: str, start: float, end: float }]` — word-sync
  timestamps.

**UI top-to-bottom:**

1. Shared header (3-step progress chip "Шаг N из 3").
2. Phase 1 card: instructions + `<audio controls>` + "Skip to read"
   secondary + "Loop" toggle.
3. Phase 2 card (locked until phase 1 done): text block with per-word
   spans + optional translation + audio + "Готов(а) к самооценке".
4. Phase 3 card (locked until phase 2 done): self-assess checkbox +
   primary "Завершить" + "Попробуй ещё раз" outline.
5. Result region after submit.

**Interactions:** word-sync highlighting drives `.shadow-word--active`
during phase 2 (uses `data-start` / `data-end` on each span). Loop
toggle persists to localStorage. `Esc` collapses help.

**Submission payload (frozen):**

```json
{
  "self_assessed": true,
  "lesson_type": "shadow_reading"
}
```

Backend reads `self_assessed`.

**Result UI:** `.result-badge--correct` + next-lesson CTA on success.
No miss path — self-assess is honour-system.

**Edge cases:** empty `words` list ⇒ template renders raw `text` only,
no highlighting (already handled).

**A11y notes:** the active word is `aria-current="true"` so screen
readers can follow; phase steppers carry `aria-current="step"`; locked
phases set `aria-disabled="true"`.

**Keyboard map:** `Space` plays/pauses focused audio; `L` toggles loop;
`Enter` advances unlocked phases.

**Gap vs current template:** replace inline `<style>` block with
`.lesson-shell` + a phase-card variant in design-system.css; convert
phase steppers to use shared progress bar.

---

### 2.6 audio_fill_blank

**Purpose:** listen to a master clip (and optional per-item clips) and
fill the gap in each sentence.

**Content schema (read in `_process_audio_fill_blank_submission` /
route):**

- `audio_url: str | None` — master clip (optional).
- `items: list[{ text_with_gap: str, answer: str, options?: list[str],
  audio_clip_url?: str }]`.

**UI top-to-bottom:**

1. Shared header.
2. Master audio card (`.lesson-shell__card`) when `audio_url` present.
3. Per-item card: number badge, optional clip button (circular play),
   the gap text, then either `.option-btn` group or `.input--*`
   text input.
4. Submit row + score badge after grading.

**Interactions:**

- Per-item clip plays inline `<audio>` (preload="none").
- Option mode marks selection (`.option-btn--selected`); after grading,
  buttons set `--correct` / `--wrong` and disable.
- Text mode applies `.input--correct` / `--wrong` and reveals the model
  answer on miss.

**Submission payload (frozen):**

```json
{
  "answers": ["<one per item>"],
  "lesson_type": "audio_fill_blank",
  "replay_count": 0
}
```

Backend reads `answers` (required) and `replay_count` (capped at 3).

**Result UI:** uses `data.item_results[].correct/.answer` for per-item
reveals; `data.score`, `data.passed`, `data.correct_items`,
`data.total_items` for the summary badge.

**Edge cases:** no master audio ⇒ master card omitted (route nullable);
item missing `audio_clip_url` ⇒ clip button hidden.

**A11y notes:** clip buttons get descriptive `aria-label`; option
buttons get `aria-pressed`; per-item feedback inside aria-live.

**Keyboard map:** `Enter` submits when all items have answers; `Space`
plays the focused clip.

**Gap vs current template:** move bespoke `.afb-*` styles into the shell
+ `.option-btn` + `.input--*` + `.result-badge` taxonomy; track and
send `replay_count` (currently always 0 — keep frontend at 0 unless
explicit replay tracking is added).

---

### 2.7 pronunciation

**Purpose:** practise pronunciation of N words; supports Web Speech API
or self-assess fallback.

**Content schema (read in `pronunciation_lesson`):**

- `items: list[{ word: str, pronunciation_hint?: str, audio_url?: str }]`.

**UI top-to-bottom:**

1. Shared header with `N items` progress strip; current-index counter.
2. Per-item card: large word, optional IPA hint, "Послушать" outline
   button + audio element, "Произнести" or "Я сказал(а) вслух" button
   depending on Speech API support, inline result line, self-assess
   fallback area.
3. "Завершить урок" primary button (revealed only when every item is
   marked done).

**Interactions:**

- Speech API: `startRecognition(idx)` sends `recognized_text` +
  `target_word`; on `not-allowed` error fall back to self-assess.
- Self-assess: checkbox toggles a `recognized_text=null,
  self_assessed=true` post.
- Each completed item updates the progress counter and highlights the
  next pending item.

**Submission payloads (frozen):**

Per-item attempt (Speech API):

```json
{
  "lesson_type": "pronunciation",
  "item_index": 0,
  "recognized_text": "<string>",
  "target_word": "<string>"
}
```

Per-item self-assess:

```json
{
  "lesson_type": "pronunciation",
  "item_index": 0,
  "recognized_text": null,
  "target_word": "<string>",
  "self_assessed": true
}
```

Finish:

```json
{
  "lesson_type": "pronunciation",
  "finish": true
}
```

Backend reads `target_word`, `recognized_text`, `self_assessed`,
`finish`. `item_index` is informational only.

**Result UI:** inline per-item badge:
`.result-badge--correct` on match, `.result-badge--neutral` for
self-assess, `.result-badge--incorrect` on mismatch. Final card uses
the shared `.result-badge--correct`.

**Edge cases:** `items` empty ⇒ route guards; missing `audio_url` ⇒
"Послушать" button hidden; Speech API not supported ⇒ self-assess path
only.

**A11y notes:** speak button announces state changes via aria-live
("Слушаю..."); microphone-denied falls back gracefully with a visible
message.

**Keyboard map:** `Space` plays focused audio; `Enter` triggers the
focused primary action.

**Gap vs current template:** unify card variants with `.lesson-shell__card`
plus a `--active` / `--matched` / `--missed` modifier set; remove
inline `<style>` block.

---

### 2.8 collocation_matching

**Purpose:** drag-and-drop / click-to-pair phrase ↔ translation matching.

**Content schema (read in `collocation_matching_lesson`):**

- `pairs: list[{ phrase: str, translation: str }]`.
- `shuffled_pairs: list[{ phrase: str, translation: str }]` — built by
  route via `random.shuffle`.

**UI top-to-bottom:**

1. Shared header.
2. Two-column board (`.lesson-shell__card` per column) with stacked
   `.option-btn` cards.
3. Submit row: "Проверить" disabled until every phrase is paired, plus
   "Сбросить".
4. Result region: score badge + per-pair correct/wrong list +
   next-lesson CTA on pass.

**Interactions:** click a phrase card, then a translation card —
auto-pairs and marks both `.option-btn--selected → --paired`. Reset
clears all pairings.

**Submission payload (frozen):**

```json
{
  "user_pairs": [{ "phrase": "<en>", "translation": "<ru>" }, ...],
  "lesson_type": "collocation_matching"
}
```

Backend reads `user_pairs`; `lesson_type` is not required by
`_process_collocation_matching_submission` but is sent for consistency
with other lessons.

**Result UI:** `data.score`, `data.passed`, `data.correct_items`,
`data.total_items`, `data.pair_results[]`.

**Edge cases:** odd `pairs` (length 1) ⇒ submit auto-enabled once the
single pair is made; reset must clear `matches` and re-enable both
columns.

**A11y notes:** cards are `role="button"` with `aria-pressed`; column
headers labelled; result list uses `role="list"` /
`role="listitem"`.

**Keyboard map:** `Tab` cycles cards; `Enter`/`Space` selects;
`Backspace` deselects.

**Gap vs current template:** rewrap in shell; map
`collocation-card--selected/--paired` to the shared
`.option-btn--selected/--paired` taxonomy.

---

### 2.9 listening_immersion

**Purpose:** dialogue-style audio with optional transcript and
translation, completed by self-assess.

**Current routing:** `LESSON_TYPE_ROUTES` maps `listening_immersion` →
`curriculum_lessons.text_lesson`, which renders `text.html` with
`is_listening_immersion = True`. Task 5 routes it to a dedicated
template `listening_immersion.html` + a new `listening_immersion_lesson`
render function in `vocabulary_lessons.py`.

**Content schema (consumed today from `lesson.content`):**

- `audio: str | None` — filename in `app/static/audio/` or `[sound:...]`
  Anki-style wrapper.
- `audio_url: str | None` — alternative absolute URL (forward-compatible
  field; not all content has it today, so the new template must accept
  either `audio_url` or `audio` and resolve `audio` via
  `url_for('static', filename='audio/' + audio_file)`).
- `text: str` — transcript HTML (already sanitised by route).
- `translation: str | None` — sanitised in route.
- `segments: list[{ start: float, end: float, text: str }]` — optional
  per-segment timestamps if present in the JSON content.
- `level_code: str` — drives is_advanced default (hide transcript on
  B1+).

**UI top-to-bottom:**

1. Shared header.
2. Audio card: `<audio controls>`, speed controls (0.75× / 1× / 1.25× /
   1.5×), optional loop toggle.
3. Transcript card: collapsible (hidden by default on B1+; expanded on
   A0–A2). Show segments inline when present; otherwise plain text.
4. Optional translation card with a show/hide toggle.
5. Self-assess section: checkbox "Я прослушал(а) внимательно".
6. Primary action: "Завершить урок" — disabled until checkbox checked.
7. Result region.

**Interactions:**

- Transcript toggle persists user preference in localStorage by
  `lesson.id`.
- Self-assess checkbox enables submit; submit fires once.

**Submission payload (frozen):**

The existing path uses the progress endpoint for completion
(`/curriculum/api/lesson/<id>/progress`). The new dedicated template
submits through `/curriculum/api/lesson/<id>/submit` to align with the
other lessons:

```json
{
  "self_assessed": true,
  "lesson_type": "listening_immersion"
}
```

Task 5 must add a `_process_listening_immersion_submission` branch (or
reuse `_process_shadow_reading_submission`-style logic) that:

- Marks `LessonProgress` as completed.
- Calls `maybe_award_curriculum_xp` and `maybe_award_listening_xp`
  (already wired via the progress endpoint for the legacy path; the new
  branch must keep both calls).
- Logs a `ListeningAttempt` via `log_listening_attempt`.

If Task 5 instead routes the submit through the progress endpoint, the
payload becomes the standard progress shape — but the redesign must
NOT introduce a new field name.

**Result UI:** `.result-badge--correct` + next-lesson CTA on success.

**Edge cases:** no `audio` / `audio_url` ⇒ route should redirect to
`empty_content.html`; missing `translation` ⇒ section omitted; missing
`segments` ⇒ render plain transcript.

**A11y notes:** audio has a visible label; speed controls are a
`role="radiogroup"`; transcript toggle is `aria-expanded`; checkbox
inside a `<label>`; reduced-motion respected for the reveal animation.

**Keyboard map:** `Space` plays/pauses the audio; `↑/↓` cycle speed
buttons inside the radiogroup; `T` toggles transcript; `Enter`
submits when the gate is met.

**Gap vs current template:** create a dedicated template; remove
`is_listening_immersion` branch from `text.html` (Task 5 cleanup); add
proper self-assess gating; align result region with the shared shell.

---

## 3. Backend payload cross-check

| Lesson | Submit endpoint | Required keys | Verified against |
|---|---|---|---|
| writing_prompt | `/learn/api/lesson/<id>/submit` | `response_text`, `checklist_completed`, `checked_items`, `lesson_type` | `_process_writing_prompt_submission` |
| translation | same | `user_answer`, `lesson_type` | `_process_translation_submission` |
| sentence_completion | same | `answers`, `lesson_type` | `_process_sentence_completion_submission` |
| sentence_correction | same | `user_answer`, `lesson_type` | `_process_sentence_correction_submission` |
| shadow_reading | `/curriculum/api/lesson/<id>/submit` | `self_assessed`, `lesson_type` | `_process_shadow_reading_submission` |
| audio_fill_blank | `/learn/api/lesson/<id>/submit` | `answers`, `lesson_type`, `replay_count?` | `_process_audio_fill_blank_submission` |
| pronunciation | `/curriculum/api/lesson/<id>/submit` | per-item: `target_word`, `recognized_text`, `self_assessed?`, `item_index?`; finish: `finish=true` | `_process_pronunciation_submission` |
| collocation_matching | `/curriculum/api/lesson/<id>/submit` | `user_pairs`, `lesson_type` | `_process_collocation_matching_submission` |
| listening_immersion | (Task 5 wires) | `self_assessed`, `lesson_type` | new branch — must mirror shadow_reading + listening XP wiring |

All keys above already exist in the current backend. The redesign must
not invent new fields. New fields, if needed, require a separate
backend change and are out of scope for this redesign.
