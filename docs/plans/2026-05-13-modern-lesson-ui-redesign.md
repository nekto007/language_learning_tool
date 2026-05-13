# Modern UI redesign for 9 lesson templates

## Overview

Redesign 9 lesson templates (writing_prompt, shadow_reading, audio_fill_blank, translation, sentence_correction, sentence_completion, pronunciation, collocation_matching, listening_immersion) to match the modern style of vocabulary.html / matching.html / dictation.html / idiom.html. Deliverable starts with an explicit per-lesson frontend element spec, then redesigns each template against that spec.

Reference modern pattern (extracted from vocabulary/matching/dictation/idiom):
- Sticky lesson header with title, type icon, progress counter "X / Y" and visual progress bar
- Centered container, max-width ~720px, border-radius 1rem, soft shadow, padding 1.5rem
- Instruction panel with subtle background, optional collapsible help
- Card-style content blocks (white bg, light border, hover/focus rings)
- Unified action bar with btn-lg primary + outline secondary, spinner on async
- Unified result badge (.result-badge--correct/--incorrect), aria-live region
- Unified input states (.input--correct/--wrong/--checking)
- Keyboard support (Enter to submit, Esc to cancel) where applicable

## Context

Files involved:
- Templates to redesign:
  - app/templates/curriculum/lessons/writing_prompt.html
  - app/templates/curriculum/lessons/shadow_reading.html
  - app/templates/curriculum/lessons/audio_fill_blank.html
  - app/templates/curriculum/lessons/translation.html
  - app/templates/curriculum/lessons/sentence_correction.html
  - app/templates/curriculum/lessons/sentence_completion.html
  - app/templates/curriculum/lessons/pronunciation.html
  - app/templates/curriculum/lessons/collocation_matching.html
- listening_immersion: currently routed to text_lesson via app/templates/curriculum/lessons/text.html with is_listening_immersion flag → create dedicated app/templates/curriculum/lessons/listening_immersion.html and route it from app/curriculum/routes/lessons.py (LESSON_TYPE_ROUTES) + add render function in app/curriculum/routes/vocabulary_lessons.py
- Reference templates: vocabulary.html, matching.html, dictation.html, idiom.html
- Shared CSS: app/static/css/design-system.css (extend with lesson-shell tokens if missing)
- Backend submission routes already exist (/curriculum/api/lesson/{id}/submit, /learn/api/lesson/{id}/submit) — payload contracts must stay identical
- Spec doc: docs/design/lesson-frontend-spec.md (new)

Related patterns:
- Submission JS pattern from vocabulary/matching (async fetch + CSRF + result reveal + next-lesson link)
- ListeningAttempt logging from app/curriculum/listening_service.py (already wired for listening_immersion)

Dependencies: none external. Pure template + CSS + vanilla JS.

## Development Approach

- Testing approach: Regular (template edits first, then template-render and JS-payload tests)
- Complete each task fully before moving to the next; do not change submission contract
- Keep payload field names identical so curriculum_lessons backend, ListeningAttempt logging, and XP idempotency keep working
- CRITICAL: every task must include new/updated tests (Jinja render smoke + payload contract)
- CRITICAL: all tests must pass before starting next task
- After every template change, run `pytest tests/curriculum -q` and the relevant slot/route tests

## Implementation Steps

### Task 1: Author the per-lesson frontend element spec

Files:
- Create: docs/design/lesson-frontend-spec.md

- [x] Document the shared lesson shell (header, container, instruction panel, action bar, result badge, input states, a11y) with class names and HTML skeleton
- [x] For each of the 9 lessons, list: purpose, current content schema (fields read from `lesson.content`), visible UI elements top-to-bottom, interactions / state machine, submission payload (frozen contract), result/feedback UI, edge/empty states, a11y notes, keyboard map
- [x] Call out gaps vs current templates for each lesson (what must be added/removed)
- [x] Validate the spec against existing backend submit handlers so no payload field is invented
- [x] Add unit test that asserts the spec file exists and contains a section heading per lesson type (tests/docs/test_lesson_spec_present.py)
- [x] Run pytest tests/docs - must pass before task 2

### Task 2: Shared CSS additions in design-system.css

Files:
- Modify: app/static/css/design-system.css

- [x] Add (if missing) `.lesson-shell`, `.lesson-shell__header`, `.lesson-shell__progress`, `.lesson-shell__body`, `.lesson-shell__actions` classes
- [x] Add `.result-badge`, `.result-badge--correct`, `.result-badge--incorrect`, `.result-badge--neutral`
- [x] Add `.input--correct`, `.input--wrong`, `.input--checking`
- [x] Add `.option-btn`, `.option-btn--selected`, `.option-btn--correct`, `.option-btn--wrong`
- [x] Add `.chip`, `.chip--clickable` for hint chips (translation lesson)
- [x] Honor `prefers-reduced-motion` for any new transitions (rely on global guard at line ~8537)
- [x] Add tests/static/test_design_system_tokens.py asserting new class names are present
- [x] Run pytest tests/static - must pass before task 3

### Task 3: Redesign text-input lessons (writing_prompt, translation, sentence_completion, sentence_correction)

Files:
- Modify: app/templates/curriculum/lessons/writing_prompt.html
- Modify: app/templates/curriculum/lessons/translation.html
- Modify: app/templates/curriculum/lessons/sentence_completion.html
- Modify: app/templates/curriculum/lessons/sentence_correction.html

- [x] Replace bespoke containers with `.lesson-shell` skeleton; keep all `lesson.content.*` reads intact
- [x] writing_prompt: structured task card + live word-count meter + checklist with min-checked gate + textarea with autosize
- [x] translation: source card + clickable hint chips + input with `.input--*` states + result badge with correct-answer reveal
- [x] sentence_completion: per-item card list, inline input, badge per item, summary at end
- [x] sentence_correction: incorrect-sentence card + either option buttons (`.option-btn`) or textarea + explanation reveal
- [x] Keep submission payload identical (verify by reading existing JS and matching field names exactly)
- [x] Tests: extend tests/curriculum/test_*_lesson.py (or add tests/curriculum/test_text_input_lessons_render.py) to assert each template renders with sample content and submits expected JSON payload via a fetched-mock harness
- [x] Run pytest tests/curriculum -q - must pass before task 4

### Task 4: Redesign audio lessons (shadow_reading, audio_fill_blank, pronunciation)

Files:
- Modify: app/templates/curriculum/lessons/shadow_reading.html
- Modify: app/templates/curriculum/lessons/audio_fill_blank.html
- Modify: app/templates/curriculum/lessons/pronunciation.html

- [x] shadow_reading: keep 3-phase Listen → Read-along → Self-assess machine but rewrap in `.lesson-shell`; modernize phase indicator; preserve word-sync highlighting using existing `words[].start/end` schema
- [x] audio_fill_blank: master audio player + per-item cards with optional clip + gap input or `.option-btn` group + per-item result badge; keep `{answers[], lesson_type}` payload
- [x] pronunciation: unified progress strip + per-item card with audio play, Web Speech API path and self-assess fallback path sharing identical card layout; preserve per-item POST and finish POST contracts
- [x] Tests: render smoke + payload contract for each; mock SpeechRecognition where needed; verify ListeningAttempt logging still fires for audio_fill_blank/dictation paths
- [x] Run pytest tests/curriculum -q tests/daily_plan/linear/test_listening_slot.py - must pass before task 5

### Task 5: Redesign collocation_matching + create listening_immersion template

Files:
- Modify: app/templates/curriculum/lessons/collocation_matching.html
- Create: app/templates/curriculum/lessons/listening_immersion.html
- Modify: app/curriculum/routes/lessons.py (route `listening_immersion` to a dedicated handler)
- Modify: app/curriculum/routes/vocabulary_lessons.py (add `listening_immersion_lesson` render function; reuse content sanitization currently in `render_text_lesson` is_listening_immersion branch)

- [x] collocation_matching: rewrap two-column layout in `.lesson-shell`, modernize selection/pairing card states, add submit-disabled until all matched, modernize result summary; keep `{user_pairs[], lesson_type}` payload
- [x] listening_immersion: dedicated template with audio player (uses `lesson.content.audio` / `audio_url`), transcript card with optional `translation` toggle, optional segment timestamps if present, completion via self-assess checkbox; submit payload `{self_assessed: true, lesson_type: 'listening_immersion'}` matches existing progress endpoint expectations
- [x] Route `listening_immersion` away from `text_lesson` to the new dedicated handler; keep `listening_immersion_quiz` untouched
- [x] Migrate the `is_listening_immersion` content path off text.html (routing migrated; dead Jinja branches in text.html are now unreachable and left intact to avoid risk to unrelated text-rendering paths)
- [x] Tests: tests/curriculum/test_listening_immersion_render.py (renders with audio + transcript, submits correct payload, fires maybe_award_listening_xp wiring via existing tests path); update tests/curriculum/test_listening_ui.py if it asserted text.html
- [x] Run pytest tests/curriculum tests/daily_plan/linear -q - must pass before task 6

### Task 6: Verify acceptance criteria

- [ ] Run full pytest suite (`pytest -q`)
- [ ] Run smoke subset (`pytest -m smoke`) to catch blueprint regressions
- [ ] Verify XP wiring untouched: maybe_award_curriculum_xp / maybe_award_listening_xp / maybe_award_writing_xp still fire from the same callsites with unchanged sources
- [ ] Lint pass (`python -m compileall app` and `python -c "import app"`)

### Task 7: Update documentation

- [ ] Update CLAUDE.md "New lesson types (Block A-C)" entry: note dedicated listening_immersion.html template and lesson-shell class taxonomy
- [ ] Cross-link docs/design/lesson-frontend-spec.md from CLAUDE.md
- [ ] Move this plan to docs/plans/completed/
