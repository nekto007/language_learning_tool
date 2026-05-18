# listening_quiz Inline Audio Audit

## Design Note

listening_quiz exercises store audio as Anki-style bracket notation:
```
    exercises[].audio = "[sound:A1M1L6_ex1.mp3]"
```
The quiz.html template resolves `[sound:NAME]` to `/static/audio/NAME` via
JavaScript regex. This is intentional item-level audio, not lesson-level
`audio_url`. Lesson-level audits (e.g. audit_immersion_data.py) correctly
show 0 audio_url entries for listening_quiz — the design is per-exercise,
not per-lesson.

Files are expected under `app/static/audio/` (direct children) because the
template constructs `/static/audio/{filename}` without any subdirectory.

## Summary

- Total listening_quiz lessons audited: **81**
- Total exercise audio references: **397**
- Files present on disk: **397** / 397
- Files missing: **0**
- Lessons fully OK: **81** / 81
- Lessons with gaps: **0**

## Result

All referenced audio files are present on disk. No generation needed.

## Per-Lesson Detail

| Lesson ID | Title | Refs | Present | Missing | Status |
| --- | --- | --- | --- | --- | --- |
| 8 | Аудирование: Слушаем и понимаем | 6 | 6 | 0 | OK |
| 18 | Аудирование: Предметы и артикли | 6 | 6 | 0 | OK |
| 30 | Урок 6: Listening Quiz | 6 | 6 | 0 | OK |
| 42 | Урок 6: Listening Quiz | 4 | 4 | 0 | OK |
| 54 | Аудирование | 8 | 8 | 0 | OK |
| 66 | Урок 6: Listening Quiz | 8 | 8 | 0 | OK |
| 78 | Lesson 6 | 8 | 8 | 0 | OK |
| 90 | Урок 6: Listening Quiz | 6 | 6 | 0 | OK |
| 102 | Lesson 6 | 8 | 8 | 0 | OK |
| 114 | Урок 6: Listening Quiz | 6 | 6 | 0 | OK |
| 126 | Урок 6: Listening Quiz | 6 | 6 | 0 | OK |
| 138 | Урок 6: Listening Quiz | 4 | 4 | 0 | OK |
| 150 | Урок 6: Listening Quiz | 6 | 6 | 0 | OK |
| 162 | Урок 6: Listening Quiz | 4 | 4 | 0 | OK |
| 174 | Урок 6: Listening Quiz | 4 | 4 | 0 | OK |
| 186 | Урок 6: Listening Quiz | 5 | 5 | 0 | OK |
| 198 | Урок 6: Listening Quiz | 6 | 6 | 0 | OK |
| 210 | Урок 6: Listening Quiz | 5 | 5 | 0 | OK |
| 222 | Lesson 6 | 8 | 8 | 0 | OK |
| 234 | Урок 6: Listening Quiz | 4 | 4 | 0 | OK |
| 246 | Урок 6: Listening Quiz | 4 | 4 | 0 | OK |
| 258 | Урок 6: Listening Quiz | 4 | 4 | 0 | OK |
| 270 | Урок 6: Listening Quiz | 4 | 4 | 0 | OK |
| 282 | Lesson 6 | 8 | 8 | 0 | OK |
| 294 | Урок 6: Listening Quiz | 4 | 4 | 0 | OK |
| 306 | Урок 6: Listening Quiz | 5 | 5 | 0 | OK |
| 318 | Урок 6: Listening Quiz | 4 | 4 | 0 | OK |
| 330 | Урок 6: Listening Quiz | 4 | 4 | 0 | OK |
| 342 | Урок 6: Listening Quiz. | 5 | 5 | 0 | OK |
| 354 | Урок 6: Listening Quiz | 4 | 4 | 0 | OK |
| 366 | Урок 6: Listening Quiz | 8 | 8 | 0 | OK |
| 378 | Урок 6: Listening Quiz. | 4 | 4 | 0 | OK |
| 390 | Урок 6: Listening Quiz | 6 | 6 | 0 | OK |
| 402 | Lesson 6 | 8 | 8 | 0 | OK |
| 414 | Урок 6: Аудирование - Описание друзей | 4 | 4 | 0 | OK |
| 426 | Урок 6: Listening Quiz. | 4 | 4 | 0 | OK |
| 438 | Урок 6: Listening Quiz. | 1 | 1 | 0 | OK |
| 450 | Урок 6: Listening Quiz - Money Matters. | 5 | 5 | 0 | OK |
| 462 | Урок 6: Listening Quiz - Office Conversations. | 5 | 5 | 0 | OK |
| 474 | Урок 6: Listening Quiz | 8 | 8 | 0 | OK |
| 486 | Урок 6: Listening Quiz | 10 | 10 | 0 | OK |
| 498 | Урок 6: Listening Quiz | 10 | 10 | 0 | OK |
| 510 | Урок 6: Listening Quiz | 4 | 4 | 0 | OK |
| 522 | Аудирование: Цвета и this/that/these/those | 8 | 8 | 0 | OK |
| 534 | Урок 6: Listening Quiz | 5 | 5 | 0 | OK |
| 546 | Урок 6: Listening Quiz. | 4 | 4 | 0 | OK |
| 558 | Урок 6: Listening Quiz. | 1 | 1 | 0 | OK |
| 570 | Урок 6: Listening Quiz. | 1 | 1 | 0 | OK |
| 582 | Урок 6: Listening Quiz. | 1 | 1 | 0 | OK |
| 594 | Урок 6: Listening Quiz. | 1 | 1 | 0 | OK |
| 606 | Урок 6: Listening Quiz. | 1 | 1 | 0 | OK |
| 618 | Урок 6: Listening Quiz. | 1 | 1 | 0 | OK |
| 630 | Урок 6: Listening Quiz. | 4 | 4 | 0 | OK |
| 642 | Урок 6: Listening Quiz. | 4 | 4 | 0 | OK |
| 654 | Урок 6: Listening Quiz | 6 | 6 | 0 | OK |
| 666 | Lesson 6 | 8 | 8 | 0 | OK |
| 678 | Lesson 6 | 8 | 8 | 0 | OK |
| 690 | Урок 6: Listening Quiz. | 1 | 1 | 0 | OK |
| 702 | Урок 6: Listening Quiz. | 5 | 5 | 0 | OK |
| 714 | Урок 6: Listening Quiz. | 5 | 5 | 0 | OK |
| 726 | Урок 6: Listening Quiz. | 5 | 5 | 0 | OK |
| 738 | Урок 6: Listening Quiz. | 3 | 3 | 0 | OK |
| 750 | Урок 6: Listening Quiz. | 1 | 1 | 0 | OK |
| 762 | Урок 6: Listening Quiz. | 3 | 3 | 0 | OK |
| 774 | Урок 6: Listening Quiz. | 3 | 3 | 0 | OK |
| 786 | Урок 6: Listening Quiz | 6 | 6 | 0 | OK |
| 798 | Урок 6: Listening Quiz. | 3 | 3 | 0 | OK |
| 810 | Урок 6: Listening Quiz. | 5 | 5 | 0 | OK |
| 822 | Урок 6: Listening Quiz. | 3 | 3 | 0 | OK |
| 834 | Урок 6: Listening Quiz. | 3 | 3 | 0 | OK |
| 846 | Урок 6: Listening Quiz. | 5 | 5 | 0 | OK |
| 858 | Lesson 6 | 8 | 8 | 0 | OK |
| 870 | Урок 6: Listening Quiz. | 5 | 5 | 0 | OK |
| 882 | Урок 6: Listening Quiz | 6 | 6 | 0 | OK |
| 894 | Урок 6: Аудирование - Время дня | 3 | 3 | 0 | OK |
| 906 | Урок 6: Listening Quiz | 6 | 6 | 0 | OK |
| 918 | Урок 6: Listening Quiz. | 3 | 3 | 0 | OK |
| 930 | Урок 6: Listening Quiz. | 5 | 5 | 0 | OK |
| 942 | Урок 6: Listening Quiz. | 4 | 4 | 0 | OK |
| 954 | Урок 6: Listening Quiz. | 4 | 4 | 0 | OK |
| 966 | Урок 6: Listening Quiz | 8 | 8 | 0 | OK |
