# Existing Listening Lesson Payload Audit

## listening_immersion

- Total source lessons: 77
- Needs lesson-level audio: True
- Needs item-level audio: False

### By CEFR Level
- A1: 16 lessons
- A2: 22 lessons
- B1: 14 lessons
- B2: 12 lessons
- C1: 13 lessons

### Audio Style Distribution
- placeholder-lesson: 77

### Average Text Length by Level (chars)
- A1: 600
- A2: 830
- B1: 1145
- B2: 1776
- C1: 2325

### Summary
- Lessons with no audio (real or placeholder): 0
- Lessons excludable from audio requirement: 77
- Exclusion reason: listening_immersion lessons with `text` can render as read-along without audio.

## listening_quiz

- Total source lessons: 77
- Needs lesson-level audio: False
- Needs item-level audio: True

### By CEFR Level
- A1: 16 lessons
- A2: 22 lessons
- B1: 14 lessons
- B2: 12 lessons
- C1: 13 lessons

### Audio Style Distribution
- placeholder-item: 77

### Summary
- Lessons with no audio (real or placeholder): 0
- Lessons excludable from audio requirement: 0
- Exclusion reason: listening_quiz requires item-level audio to function; no exclusions possible without transcript backfill.

## Source vs DB Comparison

### listening_immersion
- Source: 77  |  DB: 81  |  Match: False
  - DB audio style `placeholder-lesson`: 81
  - DB lessons with text content: 81

### listening_quiz
- Source: 77  |  DB: 81  |  Match: False
  - DB audio style `placeholder-item`: 81
  - DB lessons with text content: 0

## Recommendations

- **listening_immersion**: All 77 lessons have `text` + `translation` — usable as read-along today. Replace `[sound:...]` placeholders with real hosted audio URLs before enabling audio playback.
- **listening_quiz**: Audio is item-level (`exercises[].audio`). All 77 use `[sound:...]` placeholders. Without real audio these lessons cannot present the listening stimulus; add transcripts to exercises as a fallback or replace placeholders with real audio.
- Placeholder format `[sound:filename.mp3]` is an Anki-style reference that requires a CDN/storage mapping before it can be played in-browser.