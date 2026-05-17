# Immersion Lesson Smoke Test Checklist

Automated coverage: `tests/curriculum/test_immersion_lesson_smoke.py`

Run with: `pytest tests/curriculum/test_immersion_lesson_smoke.py -v`

## Lesson types covered

| Type | GET 200 | Pass | Fail | Progress | next_lesson_url | XP source |
|------|---------|------|------|----------|-----------------|-----------|
| dictation | auto | auto | auto | auto | auto | auto |
| audio_fill_blank | auto | auto | auto | auto | auto | auto |
| translation | auto | auto | auto | auto | auto | auto |
| sentence_correction | auto | auto | auto | auto | auto | auto |
| writing_prompt | auto | auto | auto | auto | auto | auto |
| sentence_completion | auto | auto | auto | auto | auto | auto |
| collocation_matching | auto | auto | auto | auto | auto | auto |
| shadow_reading | auto | auto | auto | auto | auto | auto |
| pronunciation | auto | auto | n/a | auto | auto | auto |
| idiom | auto | auto | auto | auto | auto | auto |

## Manual verification checklist

After running content imports, open each lesson type in a browser and verify the UI.

### dictation
- [ ] Audio player renders and plays
- [ ] Replay button tracks replay count (max 3)
- [ ] Word gaps appear inline with the gap text
- [ ] Correct word turns green, wrong word turns red
- [ ] Score badge shows after all gaps are checked
- [ ] Transcript reveals when lesson is failed

### audio_fill_blank
- [ ] Audio player renders for lesson-level URL
- [ ] Input fields appear for each item
- [ ] Submit grades all items and shows per-item feedback
- [ ] Correct answer shown after passing

### translation
- [ ] Russian source text renders
- [ ] Hint word chips appear when hint_words present
- [ ] Clicking a chip inserts word into input
- [ ] Correct answer reveals on wrong submission

### sentence_correction
- [ ] Incorrect sentence renders
- [ ] Multiple choice options appear when options field is populated
- [ ] Explanation text shows after submission

### writing_prompt
- [ ] Prompt text renders
- [ ] Character/word counter updates in real time
- [ ] Checklist items render; require 2+ checked to submit
- [ ] Example response reveals after completion

### sentence_completion
- [ ] Each item prompt renders with an input gap
- [ ] Per-item feedback shows after grading

### collocation_matching
- [ ] Phrase cards and translation cards render
- [ ] Drag-and-drop (or click-to-match) pairs them
- [ ] Score shows after submission

### shadow_reading
- [ ] Audio player renders
- [ ] Text and translation both show
- [ ] Loop toggle works
- [ ] Self-assess button marks complete and shows next_lesson_url

### pronunciation
- [ ] Word list renders with pronunciation hints
- [ ] "Try again" / self-assess fallback shows when speech not supported
- [ ] Finish button completes lesson after all items

### idiom
- [ ] Phrase and meaning render
- [ ] Animated reveal works (CSS transition)
- [ ] Example sentence shows below meaning
- [ ] After last item, Finish button completes lesson

## XP source verification

Run `pytest tests/curriculum/test_immersion_lesson_smoke.py::TestXPSourceMapping -v` to confirm
all ten types are registered in LESSON_TYPE_TO_SOURCE.

| Type | Source key |
|------|-----------|
| dictation | linear_curriculum_dictation |
| audio_fill_blank | linear_curriculum_audio_fill_blank |
| translation | linear_curriculum_quiz |
| sentence_correction | linear_curriculum_quiz |
| writing_prompt | linear_curriculum_use |
| sentence_completion | linear_curriculum_quiz |
| collocation_matching | linear_curriculum_quiz |
| shadow_reading | linear_curriculum_use |
| pronunciation | linear_curriculum_use |
| idiom | linear_curriculum_vocabulary |
