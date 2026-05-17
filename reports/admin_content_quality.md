# Admin Content Quality Dashboard Verification (Task 48)

## Summary

All four verification areas confirmed working as of 2026-05-13.

## 1. Content-Quality Dashboard Counts Imported Lesson Types

Route: GET /admin/content-quality
Function: get_content_quality_detail() in app/admin/main_routes.py

All ten new lesson types appear in the `by_type` table when lessons exist in the DB:
- dictation
- audio_fill_blank
- translation
- sentence_correction
- writing_prompt
- sentence_completion
- collocation_matching
- shadow_reading
- pronunciation
- idiom

Each row contains: type, total, with_audio, with_ipa, with_examples, completed,
audio_pct, ipa_pct, examples_pct, completion_pct, avg_rating, feedback_count.

## 2. Missing-Audio Counts Drop After Imports

Audio-expected types (dictation, listening_immersion, shadow_reading, audio_fill_blank):
- Lessons WITHOUT audio_url are listed in `missing_audio` and counted in `missing_audio_count`.
- Lessons WITH a populated audio_url are excluded from `missing_audio`.
- Non-audio types (writing_prompt, translation, etc.) never appear in `missing_audio` regardless of content.

Practical effect: after running the content import scripts, the missing_audio_count in the
top-level dashboard cards drops proportionally to the fraction of lessons that received audio_url.

## 3. Vocabulary Enrichment Coverage Visible

The dashboard shows `ipa_pct` and `examples_pct` for vocabulary lessons:
- `with_ipa` increments for vocabulary lessons whose collection contains at least one word
  with a non-null `ipa_transcription`.
- `with_examples` increments for lessons whose collection contains at least one word
  with a non-null `sentences` field.

Additional enrichment fields (frequency_band, synonyms, antonyms, etymology) are stored in
CollectionWords and accessible for future dashboard widgets, but are not yet separately
surfaced in the per-type table.

## 4. Feedback Aggregation Handles Imported Lessons

LessonFeedback rows for any lesson type are aggregated into the `avg_rating` and
`feedback_count` fields on the corresponding by_type row:
- `avg_rating` = average of per-lesson averages (rounded to 1 decimal)
- `feedback_count` = number of lessons in the type that have at least one feedback row
- Lessons with no feedback show avg_rating = null, feedback_count = 0

Tested for: dictation, shadow_reading, writing_prompt, audio_fill_blank, pronunciation,
idiom, sentence_correction, sentence_completion, collocation_matching, translation.

## Test Coverage

File: tests/admin/test_content_quality.py

New test classes added in Task 48:
- TestImportedLessonTypesCounted (6 tests)
- TestMissingAudioCountDrops (7 tests, parametrized over 4 audio types × 2 directions)
- TestVocabularyEnrichmentVisible (6 tests)
- TestFeedbackAggregationImportedLessons (6 tests, parametrized over 7 lesson types)

Total: 68 tests, 68 passed, 0 failed.
