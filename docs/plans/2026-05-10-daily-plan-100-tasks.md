---
# 100 Tasks: Daily Plan & Real English Immersion

## Overview
100 sequential tasks to transform the linear daily plan from a curriculum tracker into a full immersion system. Covers four missing skill areas (listening depth, writing practice, speaking/pronunciation, vocabulary depth), intelligence improvements to the daily plan, and supporting analytics and gamification. Each task is self-contained with code and tests.

## Context
- Files involved:
  - `app/daily_plan/linear/` (chain, plan, slots, xp)
  - `app/curriculum/grading.py`, `app/curriculum/validators.py`, `app/curriculum/routes/lessons.py`
  - `app/achievements/xp_service.py`, `app/achievements/services.py`, `app/achievements/seed.py`
  - `app/templates/curriculum/lessons/`, `app/templates/partials/linear_daily_plan.html`
  - `app/srs/`, `app/study/insights_service.py`, `app/words/routes.py`
- Already implemented: curriculum spine, SRS, reading slot, error review, listening_immersion lesson type, mission plan, linear plan infinite chain
- Major gaps: dictation/shadowing exercises, writing evaluation, pronunciation practice, collocation SRS, plan analytics, vocabulary depth (IPA, collocations, synonyms)
- Related patterns: `api_error()`, `chunk_ids()`, `award_xp(score=)`, `StreakEvent` dedup, `_safe_widget_call()`, `grant_achievement()`, `get_user_local_date()`

## Development Approach
- Testing approach: Regular (code first, then tests)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: run `pytest -m smoke` + touched module tests before next task**
- No AI mentions in commit messages; commit message style matches existing history
- Follow established patterns: `api_error()`, `chunk_ids()`, `award_xp(score=)`, `StreakEvent` dedup, `_safe_widget_call()`

## Implementation Steps

---
### BLOCK A: Listening Depth (Tasks 1–15)

### Task 1: Audio speed control in listening lessons

**Files:**
- Modify: `app/templates/curriculum/lessons/text.html`
- Modify: `app/static/css/design-system.css`
- Tests: `tests/curriculum/test_listening_ui.py`

- [x] Add speed selector buttons (0.75x, 1x, 1.25x, 1.5x) to the audio player in listening_immersion template
- [x] Persist selected speed in localStorage key `listening_speed`
- [x] JS: on speed button click, set audio.playbackRate and update active button state
- [x] CSS: `.audio-speed-btn`, `.audio-speed-btn--active` using design-system tokens
- [x] Test: template renders speed buttons; JS module sets playbackRate correctly
- [x] Run pytest -m smoke

---
### Task 2: Transcript toggle in listening lessons

**Files:**
- Modify: `app/templates/curriculum/lessons/text.html`
- Modify: `app/static/css/design-system.css`
- Tests: `tests/curriculum/test_listening_ui.py`

- [x] Add "Показать текст / Скрыть текст" toggle button above the transcript section
- [x] Default state: transcript hidden for B1+ users, shown for A1-A2 (logic already in template — add toggle layer)
- [x] Use CSS `.transcript--hidden` + JS toggle; persist preference in localStorage `transcript_visible`
- [x] Add `.transcript-toggle` button style to design-system.css
- [x] Tests: toggle button renders; default state correct per CEFR level
- [x] Run pytest -m smoke

---
### Task 3: Dictation exercise type — model and validator

**Files:**
- Modify: `app/curriculum/models.py` (add type to Lesson.type enum comment)
- Modify: `app/curriculum/validators.py` (add dictation schema)
- Modify: `app/daily_plan/linear/xp.py` (LESSON_TYPE_TO_SOURCE)
- Modify: `app/achievements/xp_service.py` (LINEAR_XP)
- Tests: `tests/curriculum/test_validators.py`

- [x] Register `dictation` as lesson type: validator schema `{audio_url, transcript, hint_chars (int, default 0)}`
- [x] Add `linear_curriculum_dictation = 20` to `LINEAR_XP` dict in xp_service.py
- [x] Add `'dictation' → 'linear_curriculum_dictation'` to `LESSON_TYPE_TO_SOURCE`
- [x] Tests: valid dictation payload passes; missing audio_url fails; missing transcript fails
- [x] Run pytest tests/curriculum/

---
### Task 4: Dictation backend grader

**Files:**
- Modify: `app/curriculum/grading.py`
- Tests: `tests/curriculum/test_grading.py`

- [x] Add `grade_dictation(user_text: str, transcript: str, hint_chars: int = 0) -> dict` in grading.py
- [x] Normalize both strings (strip, lower, collapse whitespace, remove punctuation except apostrophes)
- [x] Score = word-level accuracy: `correct_words / total_words * 100`; threshold for pass: score >= 80
- [x] Hint chars: if hint_chars > 0 the first N chars of each word are pre-filled on client; don't penalize those
- [x] Tests: exact match → 100%; one wrong word in 5 → 80% (pass); 3 wrong in 5 → 40% (fail); punctuation ignored; hint_chars=3 with first chars correct
- [x] Run pytest tests/curriculum/

---
### Task 5: Dictation lesson template and route handler

**Files:**
- Create: `app/templates/curriculum/lessons/dictation.html`
- Modify: `app/curriculum/routes/lessons.py`
- Modify: `app/static/css/design-system.css`
- Tests: `tests/curriculum/test_dictation_lesson.py`

- [x] Template: audio player (with replay) + text input area + submit button; hint_chars pre-fill first N chars of each word
- [x] "Воспроизвести ещё раз" button with play count tracking (max 3 replays by default)
- [x] On submit: POST to existing `/api/curriculum/grade` with lesson_type=dictation
- [x] Route: recognize dictation type, call grade_dictation, return result including correct_transcript on completion
- [x] CSS: `.dictation-input`, `.dictation-word-result` (correct/wrong highlight) in design-system.css
- [x] Tests: route returns 200 with grade; replay_count tracked; correct transcript shown on completion
- [x] Run pytest tests/curriculum/

---
### Task 6: Audio fill-in-blank exercise type

**Files:**
- Modify: `app/curriculum/validators.py`
- Modify: `app/curriculum/grading.py`
- Create: `app/templates/curriculum/lessons/audio_fill_blank.html`
- Modify: `app/daily_plan/linear/xp.py`, `app/achievements/xp_service.py`
- Tests: `tests/curriculum/test_audio_fill_blank.py`

- [x] Validator schema: `{audio_url, items: [{audio_clip_url?, text_with_gap: str, answer: str, options?: [str]}]}`
- [x] Grader: `grade_audio_fill_blank(user_answers, items)` — per-item Levenshtein ≤1 (same as fill_blank)
- [x] Template: audio clip per item plays automatically; input or multiple choice; show answer on completion
- [x] Register `audio_fill_blank → linear_curriculum_quiz` in LESSON_TYPE_TO_SOURCE (reuse quiz XP = 12)
- [x] Tests: correct answer passes; typo-1 passes; multi-item scoring; options mode vs free-text mode
- [x] Run pytest tests/curriculum/

---
### Task 7: Replay single sentence in listening lessons

**Files:**
- Modify: `app/templates/curriculum/lessons/text.html`
- Tests: `tests/curriculum/test_listening_ui.py`

- [x] If lesson content has `sentences: [{text, start_time, end_time}]`, render per-sentence replay icons
- [x] JS: on click, seek audio to start_time and play to end_time, then pause
- [x] Fallback: if no sentence timestamps, sentence replay icons are hidden (don't break existing content)
- [x] Tests: sentences array present → replay icons rendered; no sentences → no icons; seek logic unit-tested
- [x] Run pytest -m smoke

---
### Task 8: Listening attempt tracking model

**Files:**
- Create: `migrations/versions/20260511_listening_attempts.py`
- Modify: `app/curriculum/models.py`
- Tests: `tests/curriculum/test_listening_attempts.py`

- [x] New model `ListeningAttempt(id, user_id FK, lesson_id FK, score FLOAT, replay_count INT, created_at)` — tracks each dictation/audio_fill_blank submission
- [x] Migration: table creation, FK constraints, index on (user_id, created_at)
- [x] Add `log_listening_attempt(user_id, lesson_id, score, replay_count, db)` helper in a new `app/curriculum/listening_service.py`
- [x] Call from dictation and audio_fill_blank grade routes
- [x] Tests: model persists correctly; duplicate lesson attempts are allowed (each submission = new row)
- [x] Run pytest tests/curriculum/

---
### Task 9: Listening analytics widget on dashboard

**Files:**
- Modify: `app/study/insights_service.py`
- Modify: `app/words/routes.py`
- Modify: `app/templates/study/index.html`
- Tests: `tests/study/test_insights_service.py`

- [x] Add `get_listening_stats(user_id, db) -> dict` in insights_service.py: total dictation lessons, avg score, total replay_count last 7 days
- [x] Wire into dashboard via `_safe_widget_call` in words/routes.py
- [x] Render compact widget card on study index: "Диктанты: N урок, ср. X%"
- [x] Tests: widget returns correct aggregates; empty state returns zeros
- [x] Run pytest -m smoke

---
### Task 10: Listening immersion slot in linear plan

**Files:**
- Create: `app/daily_plan/linear/slots/listening_slot.py`
- Modify: `app/daily_plan/linear/chain.py`
- Modify: `app/templates/partials/linear_daily_plan.html`
- Tests: `tests/daily_plan/linear/test_listening_slot.py`

- [x] `build_listening_slot(user_id, db)` — find next incomplete listening_immersion or dictation lesson in user's current module
- [x] Slot data: `{lesson_id, lesson_title, lesson_type, estimated_minutes: 10}`
- [x] Add to EXTENSION_PRIORITY after reading (curriculum → srs → reading → listening → error_review)
- [x] Template: render listening slot with headphone icon, type badge, estimated time
- [x] XP: reuse `maybe_award_curriculum_xp` — already handles listening_immersion type
- [x] Tests: slot builds correctly; no listening lesson → slot is None; completed lesson skipped; template renders
- [x] Run pytest tests/daily_plan/linear/

---
### Task 11: Daily listening goal (minutes per day)

**Files:**
- Modify: `app/auth/models.py` (add `listening_goal_minutes INT DEFAULT 10`)
- Create: `migrations/versions/20260511_listening_goal.py`
- Modify: `app/api/daily_status.py`
- Tests: `tests/api/test_daily_status.py`

- [x] Add `listening_goal_minutes` field to User model (default 10)
- [x] Compute `listening_minutes_today` in daily-status from ListeningAttempt created_at + estimated duration (lesson.content.get('duration_seconds', 300) / 60)
- [x] Include `{listening_goal_minutes, listening_minutes_today, listening_goal_reached}` in `/api/daily-status` payload
- [x] Tests: goal reached → True; partial → False; goal=0 → always True; no attempts → 0 minutes
- [x] Run pytest tests/api/

---
### Task 12: Listening streak tracking

**Files:**
- Modify: `app/utils/activity_tracker.py`
- Modify: `app/achievements/streak_service.py`
- Tests: `tests/achievements/test_streak_service.py`

- [x] Add `ListeningAttempt` as 8th activity source in `has_learning_activity(user_id, start_utc, end_utc, db)` — only for listening streak, not DAU/WAU/MAU (same pattern as StreakEvent xp_linear for main streak)
- [x] Add `get_listening_streak(user_id, db) -> int` helper in streak_service.py using ListeningAttempt rows
- [x] Expose `listening_streak_days` in `/api/daily-status`
- [x] Tests: 3 consecutive days of ListeningAttempt rows → streak=3; gap → streak resets; no attempts → streak=0
- [x] Run pytest tests/achievements/

---
### Task 13: Listening achievement badges

**Files:**
- Modify: `app/achievements/seed.py`
- Modify: `app/achievements/services.py`
- Tests: `tests/achievements/test_listening_achievements.py`

- [x] Seed 3 new achievements: `listening_first` (first dictation), `listening_week` (7-day listening streak), `listening_master` (avg score ≥ 90% over 10 dictations)
- [x] Add `check_listening_achievements(user_id, db)` in services.py — called after ListeningAttempt creation
- [x] Use `grant_achievement(user_id, achievement_id)` (race-safe upsert)
- [x] Tests: first dictation → listening_first granted; 7-day streak → listening_week; high avg → listening_master
- [x] Run pytest tests/achievements/

---
### Task 14: Listening mission type in mission-based plan

**Files:**
- Modify: `app/daily_plan/assembler.py` (or mission_selector.py)
- Modify: `app/daily_plan/models.py`
- Tests: `tests/daily_plan/test_mission_selector.py`

- [x] Add `MissionType.LISTENING` to the mission types enum
- [x] `assemble_listening_mission(user_id, db)` — phases: 1 recall (SRS warmup), 1 dictation lesson, 1 listening_immersion, 1 check (comprehension quiz)
- [x] `select_mission()` can now return LISTENING when user has unfinished dictation lessons and listening streak < 3
- [x] Mission rotation logic includes LISTENING in rotation cycle
- [x] Tests: LISTENING mission assembles correctly; phases have correct kinds; rotation avoids yesterday's type
- [x] Run pytest tests/daily_plan/

---
### Task 15: Listening slot in linear plan — XP and day_secured integration

**Files:**
- Modify: `app/daily_plan/linear/xp.py`
- Modify: `app/daily_plan/linear/plan.py` (`compute_linear_day_secured`)
- Tests: `tests/daily_plan/linear/test_listening_slot.py`

- [x] Add `maybe_award_listening_xp(user_id, lesson_id, score, for_date, db)` — idempotent via StreakEvent `xp_linear_listening`
- [x] Add `linear_listening = 18` to LINEAR_XP (between curriculum card and SRS)
- [x] `compute_linear_day_secured`: listening slot is NOT a baseline slot — doesn't block day_secured
- [x] Extension slot completion calls maybe_award_listening_xp from the route
- [x] Tests: first award → StreakEvent created; repeat → no-op; day_secured unaffected by listening slot
- [x] Run pytest tests/daily_plan/linear/

---
### BLOCK B: Writing Practice System (Tasks 16–28)

### Task 16: Translation exercise type — validator and grader

**Files:**
- Modify: `app/curriculum/validators.py`
- Modify: `app/curriculum/grading.py`
- Modify: `app/daily_plan/linear/xp.py`, `app/achievements/xp_service.py`
- Tests: `tests/curriculum/test_grading.py`

- [x] Already exists as `translation_quiz` — confirm validator schema and grader work correctly
- [x] Add standalone `translation` lesson type (single sentence, Russian→English, not a quiz): `{russian, english, hint_words?: [str]}`
- [x] Grader: `grade_translation(user_answer, correct_answer)` — exact match after normalize + Levenshtein ≤1 for single-word answers; multi-word: exact only (reuse existing fill_blank grader logic)
- [x] Register `translation → linear_curriculum_quiz` in LESSON_TYPE_TO_SOURCE
- [x] Tests: exact match → correct; typo-1 in single word → correct; wrong word order → incorrect; punctuation ignored
- [x] Run pytest tests/curriculum/

---
### Task 17: Translation lesson template

**Files:**
- Create: `app/templates/curriculum/lessons/translation.html`
- Modify: `app/curriculum/routes/lessons.py`
- Tests: `tests/curriculum/test_translation_lesson.py`

- [x] Template: show Russian sentence, text input for English answer, optional hint_words as draggable chips
- [x] On submit: grade server-side, show correct answer + explanation
- [x] CSS: `.translation-chips` for hint words, `.translation-input--correct/incorrect` feedback states
- [x] Route: handle translation type dispatch
- [x] Tests: template renders; route returns grade; hint_words shown when present
- [x] Run pytest tests/curriculum/

---
### Task 18: Sentence correction exercise type

**Files:**
- Modify: `app/curriculum/validators.py`
- Modify: `app/curriculum/grading.py`
- Create: `app/templates/curriculum/lessons/sentence_correction.html`
- Modify: `app/curriculum/routes/lessons.py`
- Tests: `tests/curriculum/test_sentence_correction.py`

- [x] Validator schema: `{incorrect_sentence: str, correct_sentence: str, error_type: str, explanation: str}`
- [x] Grader: `grade_sentence_correction(user_answer, correct_sentence)` — normalized exact match
- [x] Template: show incorrect sentence with editable inline text area; user types corrected version
- [x] Alternatively: multiple-choice between 4 versions (if `options` field present in content)
- [x] Register `sentence_correction → linear_curriculum_quiz` in LESSON_TYPE_TO_SOURCE
- [x] Tests: correct answer → pass; wrong answer → fail; explanation shown after submit
- [x] Run pytest tests/curriculum/

---
### Task 19: Writing prompt exercise type

**Files:**
- Modify: `app/curriculum/validators.py`
- Create: `app/templates/curriculum/lessons/writing_prompt.html`
- Modify: `app/curriculum/routes/lessons.py`
- Modify: `app/daily_plan/linear/xp.py`, `app/achievements/xp_service.py`
- Tests: `tests/curriculum/test_writing_prompt.py`

- [x] Validator schema: `{prompt: str, min_words: int, example_response?: str, checklist?: [str]}`
- [x] No automatic grading — user self-assesses with checklist checkboxes
- [x] Submit endpoint: save response to UserWritingAttempt, mark as completed after checklist items checked
- [x] Register `writing_prompt → linear_curriculum_use` in LESSON_TYPE_TO_SOURCE; `linear_curriculum_use = 25` in LINEAR_XP
- [x] Template: prompt text, textarea, checklist, example response shown after submit
- [x] Tests: submit saves attempt; checklist completion marks lesson done; example shown after
- [x] Run pytest tests/curriculum/

---
### Task 20: UserWritingAttempt model

**Files:**
- Modify: `app/curriculum/models.py`
- Create: `migrations/versions/20260512_user_writing_attempt.py`
- Tests: `tests/curriculum/test_writing_attempt.py`

- [x] Model: `UserWritingAttempt(id, user_id FK, lesson_id FK, response_text TEXT, word_count INT, checklist_completed BOOLEAN, created_at)`
- [x] Migration: table + indexes on (user_id, created_at), (user_id, lesson_id)
- [x] Helper: `save_writing_attempt(user_id, lesson_id, text, checklist_completed, db)` — compute word_count, create row
- [x] Tests: model saves correctly; word_count computed; multiple attempts per lesson allowed
- [x] Run pytest tests/curriculum/

---
### Task 21: Writing history page

**Files:**
- Modify: `app/study/routes.py` (or create dedicated route)
- Create: `app/templates/study/writing_history.html`
- Modify: `app/templates/study/index.html` (add link)
- Tests: `tests/study/test_writing_history.py`

- [x] Route: `GET /study/writing` — list UserWritingAttempt rows for current user, paginated (20 per page)
- [x] Template: chronological list, show prompt, response preview (first 100 chars), date, word_count
- [x] Filter by lesson type (writing_prompt, translation, sentence_correction)
- [x] Tests: route returns 200; empty state shows "Пока нет записей"; pagination works
- [x] Run pytest tests/study/

---
### Task 22: Writing slot in linear plan

**Files:**
- Create: `app/daily_plan/linear/slots/writing_slot.py`
- Modify: `app/daily_plan/linear/chain.py`
- Modify: `app/templates/partials/linear_daily_plan.html`
- Tests: `tests/daily_plan/linear/test_writing_slot.py`

- [x] `build_writing_slot(user_id, db)` — find next incomplete writing_prompt or translation lesson in user's module
- [x] Slot data: `{lesson_id, lesson_title, lesson_type, estimated_minutes: 8}`
- [x] Add to EXTENSION_PRIORITY after listening
- [x] Template: writing slot with pen icon, type badge, brief prompt preview
- [x] Tests: slot builds; no writing lesson → None; template renders writing slot correctly
- [x] Run pytest tests/daily_plan/linear/

---
### Task 23: Writing streak and achievements

**Files:**
- Modify: `app/achievements/seed.py`
- Modify: `app/achievements/services.py`
- Tests: `tests/achievements/test_writing_achievements.py`

- [x] Seed: `writing_first` (first writing attempt), `writing_streak_3` (3 consecutive days), `writing_fluent` (100 words submitted in one attempt)
- [x] `get_writing_streak(user_id, db)` — consecutive days with UserWritingAttempt rows
- [x] `check_writing_achievements(user_id, db)` — called after writing attempt saved
- [x] Expose `writing_streak_days` in `/api/daily-status`
- [x] Tests: 3 consecutive days → writing_streak_3 granted; 100 words → writing_fluent
- [x] Run pytest tests/achievements/

---
### Task 24: Writing XP integration and plan day_secured

**Files:**
- Modify: `app/daily_plan/linear/xp.py`
- Modify: `app/curriculum/routes/lessons.py` (writing_prompt completion)
- Tests: `tests/daily_plan/linear/test_xp.py`

- [x] Add `maybe_award_writing_xp(user_id, lesson_id, for_date, db)` — idempotent via StreakEvent `xp_linear_writing`
- [x] Call from writing_prompt submit route after successful attempt save
- [x] XP amount: 25 (same as `use` category, fitting for production practice)
- [x] Writing slot is NOT a baseline slot — extension only, doesn't block day_secured
- [x] Tests: award fires on first submit; repeat same day → no-op; day_secured unaffected
- [x] Run pytest tests/daily_plan/linear/

---
### Task 25: Sentence completion exercise type

**Files:**
- Modify: `app/curriculum/validators.py`
- Modify: `app/curriculum/grading.py`
- Create: `app/templates/curriculum/lessons/sentence_completion.html`
- Modify: `app/curriculum/routes/lessons.py`
- Tests: `tests/curriculum/test_sentence_completion.py`

- [x] Validator: `{items: [{prompt: str, answer: str, context?: str}]}` — user fills in second half of sentence
- [x] Grader: per item, exact + Levenshtein ≤1 grading; final score = correct/total * 100
- [x] Template: show prompt + input field; animate correct/wrong per item; show model answer on completion
- [x] Register `sentence_completion → linear_curriculum_quiz` in LESSON_TYPE_TO_SOURCE
- [x] Tests: exact match passes; partial score calculated; all-wrong → score=0
- [x] Run pytest tests/curriculum/

---
### Task 26: Writing accuracy analytics widget

**Files:**
- Modify: `app/study/insights_service.py`
- Modify: `app/words/routes.py`
- Modify: `app/templates/study/index.html`
- Tests: `tests/study/test_insights_service.py`

- [x] `get_writing_stats(user_id, db)` — total attempts, avg word_count per attempt, consecutive writing days
- [x] Render compact dashboard widget: "Письмо: N попыток · avg M слов"
- [x] Widget wrapped in `_safe_widget_call()`
- [x] Tests: correct aggregates; zero writing → zeros in widget
- [x] Run pytest -m smoke

---
### Task 27: Writing plan auto-suggest when writing streak broken

**Files:**
- Modify: `app/daily_plan/next_step.py`
- Tests: `tests/daily_plan/test_next_step.py`

- [x] In `get_next_best_step()`: add writing priority after SRS due — if last UserWritingAttempt > 2 days ago and writing lesson available → suggest writing slot
- [x] NextStep kind='writing', reason='Давно не писал — попробуй продолжить', estimated_minutes=8
- [x] Tests: 3 days without writing → writing step suggested; wrote today → no writing step
- [x] Run pytest tests/daily_plan/

---
### Task 28: Writing self-review checklist improvements

**Files:**
- Modify: `app/templates/curriculum/lessons/writing_prompt.html`
- Modify: `app/curriculum/validators.py`
- Tests: `tests/curriculum/test_writing_prompt.py`

- [x] Default checklist items if none in content: ["Использовал(а) новые слова", "Структура предложений правильная", "Нет пропущенных артиклей", "Нет ошибок во временах"]
- [x] Require at least 2 checklist items checked to submit (prevent trivial completion)
- [x] Show word count live as user types
- [x] Tests: less than 2 items checked → submit blocked; word count updates dynamically
- [x] Run pytest tests/curriculum/

---
### BLOCK C: Vocabulary Depth (Tasks 29–40)

### Task 29: Word collocations model

**Files:**
- Modify: `app/curriculum/models.py`
- Create: `migrations/versions/20260513_word_collocations.py`
- Tests: `tests/curriculum/test_collocations.py`

- [x] Model: `WordCollocation(id, word_id FK → Word, collocation_phrase TEXT, translation TEXT, example TEXT, created_at)` — one word can have many collocations
- [x] Migration: table + index on word_id
- [x] No bulk data import yet — model scaffolding only; manual admin entry or fixture data
- [x] Helper: `get_collocations_for_word(word_id, db) -> list[WordCollocation]`
- [x] Tests: model creates correctly; get_collocations returns empty list for word with no collocations
- [x] Run pytest tests/curriculum/

---
### Task 30: Collocation display in vocabulary lessons

**Files:**
- Modify: `app/templates/curriculum/lessons/vocabulary.html`
- Modify: `app/curriculum/routes/vocabulary_lessons.py`
- Modify: `app/static/css/design-system.css`
- Tests: `tests/curriculum/test_vocabulary_lessons.py`

- [x] In vocabulary lesson route: load collocations for each word in the lesson
- [x] Template: below each word entry, show collocations as compact pills if any exist
- [x] CSS: `.collocation-pill` with subtle background, consistent with design-system tokens
- [x] If no collocations for word: section hidden (don't show empty state per word)
- [x] Tests: word with collocations → pills rendered; word without → no pill section
- [x] Run pytest tests/curriculum/

---
### Task 31: Collocation matching exercise type

**Files:**
- Modify: `app/curriculum/validators.py`
- Modify: `app/curriculum/grading.py`
- Create: `app/templates/curriculum/lessons/collocation_matching.html`
- Modify: `app/curriculum/routes/lessons.py`
- Tests: `tests/curriculum/test_collocation_matching.py`

- [x] Validator: `{pairs: [{phrase: str, translation: str}]}` — match English phrase to Russian translation
- [x] Grader: reuse server-side matching grader `_grade_matching_pairs`
- [x] Template: drag-and-drop cards matching English collocations to Russian meanings; mobile-friendly
- [x] Register `collocation_matching → linear_curriculum_quiz` in LESSON_TYPE_TO_SOURCE
- [x] Tests: all correct pairs → 100%; mixed → partial; wrong answer includes correct answer in response
- [x] Run pytest tests/curriculum/

---
### Task 32: IPA transcription display in vocabulary

**Files:**
- Modify: `app/curriculum/models.py` (note on Word model that ipa field may exist)
- Modify: `app/templates/curriculum/lessons/vocabulary.html`
- Modify: `app/static/css/design-system.css`
- Tests: `tests/curriculum/test_vocabulary_lessons.py`

- [x] Check Word model: if `pronunciation` field exists, check whether it stores IPA or just audio URL
- [x] If pronunciation is audio URL: add separate `ipa_transcription` field (nullable TEXT) — add migration
- [x] Template: display `/ipa_text/` in light gray below the English word if ipa_transcription is not null
- [x] CSS: `.word-ipa` font-style italic, smaller size, color var(--color-text-secondary)
- [x] Tests: word with ipa → transcription shown; word without → no IPA element
- [x] Run pytest tests/curriculum/

---
### Task 33: Synonym and antonym display in vocabulary

**Files:**
- Modify: `app/curriculum/models.py` (add synonyms/antonyms JSON fields to Word if not present)
- Create: `migrations/versions/20260513_word_synonyms.py`
- Modify: `app/templates/curriculum/lessons/vocabulary.html`
- Tests: `tests/curriculum/test_vocabulary_lessons.py`

- [x] Add `synonyms JSON` and `antonyms JSON` nullable columns to Word model (store as list of strings)
- [x] Template: show "Синонимы: word1, word2" and "Антонимы: word1" sections if data exists
- [x] CSS: `.word-synonyms`, `.word-antonyms` compact display
- [x] No bulk data population — scaffold for future content import
- [x] Tests: word with synonyms → rendered; without → hidden; migration runs cleanly
- [x] Run pytest tests/curriculum/

---
### Task 34: Word usage frequency indicator

**Files:**
- Modify: `app/curriculum/models.py` (add `frequency_band` to Word if not present)
- Create: `migrations/versions/20260514_word_frequency_band.py`
- Modify: `app/templates/curriculum/lessons/vocabulary.html`
- Modify: `app/static/css/design-system.css`
- Tests: `tests/curriculum/test_vocabulary_lessons.py`

- [x] Add `frequency_band SMALLINT` (1=top 1000, 2=top 3000, 3=top 10000, NULL=unknown) to Word
- [x] Template: badge "Топ 1000" / "Топ 3000" / "Редкое" with different color per band
- [x] CSS: `.freq-badge--1` (green), `.freq-badge--2` (blue), `.freq-badge--3` (gray)
- [x] SRS card: also show frequency badge on the card front face
- [x] Tests: band 1 → green badge rendered; null band → no badge
- [x] Run pytest tests/curriculum/

---
### Task 35: Example sentence carousel in vocabulary lessons

**Files:**
- Modify: `app/curriculum/models.py` (verify Word.examples field)
- Modify: `app/templates/curriculum/lessons/vocabulary.html`
- Modify: `app/static/css/design-system.css`
- Tests: `tests/curriculum/test_vocabulary_lessons.py`

- [x] If Word has `examples: [{english, russian}]` with more than 2 items, show as scrollable carousel
- [x] Carousel: prev/next buttons, dot indicators, auto-advance every 5s on page idle
- [x] Respect `prefers-reduced-motion`: no auto-advance if reduced motion
- [x] CSS: `.example-carousel`, `.example-slide` transitions using existing design tokens
- [x] Tests: 3+ examples → carousel rendered; 1-2 → static list; reduced-motion → no auto-advance
- [x] Run pytest tests/curriculum/

---
### Task 36: Click-to-define vocabulary in reading passages

**Files:**
- Modify: `app/templates/curriculum/lessons/text.html`
- Modify: `app/static/css/design-system.css`
- Modify: `app/curriculum/routes/lessons.py` (or new API endpoint)
- Tests: `tests/curriculum/test_reading_vocabulary.py`

- [x] In reading/text lessons: wrap words that appear in the course vocabulary in `<span class="vocab-word" data-word-id="X">` during server-side render
- [x] JS: on click, show tooltip with Russian translation + pronunciation audio (fetched from lesson content data)
- [x] Track clicks as reading engagement events (POST to `/api/daily-plan/events` with event_type=vocab_lookup)
- [x] CSS: `.vocab-word` underline dotted; `.vocab-tooltip` popup card
- [x] Tests: vocab words wrapped in spans; click event tracked; tooltip contains translation
- [x] Run pytest tests/curriculum/

---
### Task 37: Vocabulary journal (user word annotations)

**Files:**
- Modify: `app/curriculum/models.py`
- Create: `migrations/versions/20260514_vocab_annotation.py`
- Modify: `app/templates/curriculum/lessons/vocabulary.html`
- Tests: `tests/curriculum/test_vocab_annotation.py`

- [x] Model: `VocabAnnotation(id, user_id FK, word_id FK, note TEXT, added_at)` — user personal notes on words
- [x] UI: small "+" button on each vocabulary word card → inline text input → save annotation via AJAX
- [x] Show existing annotation below word if exists
- [x] Tests: annotation saves; update replaces old annotation; fetch returns user's annotation only
- [x] Run pytest tests/curriculum/

---
### Task 38: Vocabulary mastery map page

**Files:**
- Modify: `app/study/routes.py`
- Create: `app/templates/study/vocab_map.html`
- Modify: `app/templates/study/index.html`
- Tests: `tests/study/test_vocab_map.py`

- [x] Route: `GET /study/vocab-map` — aggregate user's vocabulary by CEFR level, module, and SRS state
- [x] Display a grid of modules, each showing: total words, SRS mastered, in-learning, not-started counts
- [x] Color-coded: green (>80% mastered), yellow (>50%), red (<50%), gray (not started)
- [x] Tests: route returns 200; correct counts per module; empty user → all gray
- [x] Run pytest tests/study/

---
### Task 39: Vocabulary growth chart on dashboard

**Files:**
- Modify: `app/study/insights_service.py`
- Modify: `app/words/routes.py`
- Modify: `app/templates/study/index.html`
- Tests: `tests/study/test_insights_service.py`

- [x] `get_vocabulary_growth(user_id, db, days=30)` — count UserCardDirection rows created per day over last N days
- [x] Return `{dates: [...], counts: [...], total_active: N}` for Chart.js sparkline
- [x] Dashboard widget: small line chart "Словарный запас растёт: +N слов за неделю"
- [x] Tests: correct date-bucketing; total_active matches active card count
- [x] Run pytest tests/study/

---
### Task 40: Word origin notes in vocabulary

**Files:**
- Modify: `app/curriculum/models.py` (add etymology TEXT nullable)
- Create: `migrations/versions/20260515_word_etymology.py`
- Modify: `app/templates/curriculum/lessons/vocabulary.html`
- Tests: `tests/curriculum/test_vocabulary_lessons.py`

- [x] Add `etymology TEXT` nullable field to Word
- [x] Template: show etymology note as collapsible "Происхождение слова" section
- [x] No data population — scaffold for future content; shows only if field is non-null
- [x] Tests: word with etymology → section renders; null → section absent
- [x] Run pytest tests/curriculum/

---
### BLOCK D: Daily Plan Intelligence (Tasks 41–52)

### Task 41: Plan estimated time calculation

**Files:**
- Modify: `app/daily_plan/linear/plan.py`
- Modify: `app/api/daily_plan.py`
- Tests: `tests/daily_plan/linear/test_plan.py`

- [x] Define `SLOT_ESTIMATED_MINUTES = {curriculum: 15, srs: 10, reading: 15, listening: 10, writing: 8, error_review: 12}` in plan.py
- [x] In `get_linear_plan()`: compute `total_estimated_minutes` = sum of estimated_minutes for all incomplete slots
- [x] Include in plan payload and `/api/daily-plan` response
- [x] Tests: all slots incomplete → correct sum; completed slots excluded from total
- [x] Run pytest tests/daily_plan/linear/

---
### Task 42: Plan time display in template

**Files:**
- Modify: `app/templates/partials/linear_daily_plan.html`
- Modify: `app/static/css/design-system.css`
- Tests: `tests/daily_plan/linear/test_plan.py`

- [x] Show "≈ N мин на сегодня" below the plan header
- [x] Show "light" (<15 min), "normal" (15-30), "intensive" (>30) label with colored dot
- [x] CSS: `.plan-time-indicator`, `.plan-intensity--light/normal/intensive`
- [x] Tests: 25 minutes → normal label; 35 → intensive; 10 → light
- [x] Run pytest -m smoke

---
### Task 43: Plan completion heatmap calendar

**Files:**
- Modify: `app/study/routes.py`
- Create: `app/templates/study/plan_calendar.html`
- Modify: `app/templates/study/index.html`
- Tests: `tests/study/test_plan_calendar.py`

- [x] Route: `GET /study/calendar` — query DailyPlanLog last 90 days, return completion data per day
- [x] Render GitHub-style heatmap: 13 weeks × 7 days, colored by completion level (0/partial/full)
- [x] Tooltip on hover: date, slots completed, day_secured status
- [x] Tests: correct day-bucket data; empty days → gray; secured days → full color
- [x] Run pytest tests/study/

---
### Task 44: Weekly plan overview page

**Files:**
- Modify: `app/study/routes.py`
- Create: `app/templates/study/weekly_plan.html`
- Tests: `tests/study/test_weekly_plan.py`

- [x] Route: `GET /study/weekly` — build today + next 6 days plan previews (simplified, just slot types and status)
- [x] Show each day: estimated time, slot types as icons, completion status for past days
- [x] Uses `get_linear_plan()` for today, basic projection for future days (same slots, adjusted for SRS budget)
- [x] Tests: today shown as current; past days show DailyPlanLog data; future days show projected slots
- [x] Run pytest tests/study/

---
### Task 45: Tomorrow's plan preview in day-secured banner

**Files:**
- Modify: `app/daily_plan/linear/plan.py`
- Modify: `app/templates/partials/linear_daily_plan.html`
- Tests: `tests/daily_plan/linear/test_plan.py`

- [ ] When `day_secured=True`, compute a brief preview of tomorrow's expected slots (next lessons in spine + SRS projection)
- [ ] Add `tomorrow_preview: {estimated_minutes, slot_types: [str]}` to plan payload when day_secured
- [ ] Template: in day-secured banner, show "Завтра ≈ N мин" with slot type icons
- [ ] Tests: day_secured=True → tomorrow_preview populated; day_secured=False → no preview
- [ ] Run pytest tests/daily_plan/linear/

---
### Task 46: Slot skip with reason tracking

**Files:**
- Modify: `app/api/daily_plan_events.py`
- Modify: `app/templates/partials/linear_daily_plan.html`
- Tests: `tests/daily_plan/test_events.py`

- [ ] Add "Пропустить" button on each slot (only when slot is current/active)
- [ ] POST to `/api/daily-plan/events` with `event_type=slot_skipped, meta={kind, reason}` — reason is one of: no_time / too_hard / not_today
- [ ] Skip does not mark slot complete; next slot becomes unlocked (relaxed for skipped only)
- [ ] Tests: skip event saved; skipped slot doesn't count for day_secured; reason field validated
- [ ] Run pytest tests/daily_plan/

---
### Task 47: Missed plan recovery suggestion

**Files:**
- Modify: `app/daily_plan/next_step.py`
- Modify: `app/api/daily_status.py`
- Tests: `tests/daily_plan/test_next_step.py`

- [ ] In `/api/daily-status`: if yesterday's plan was incomplete (check DailyPlanLog), add `recovery_suggestion: {missed_kind, action_url}` to payload
- [ ] `NextStep` kind='recovery': "Вчера не завершил(а) — продолжи с SRS"
- [ ] Show recovery hint at top of dashboard when applicable
- [ ] Tests: yesterday incomplete → recovery shown; completed → no recovery; no yesterday plan → no recovery
- [ ] Run pytest tests/daily_plan/

---
### Task 48: Plan pause / vacation mode

**Files:**
- Modify: `app/auth/models.py`
- Create: `migrations/versions/20260516_plan_pause.py`
- Modify: `app/api/daily_status.py`
- Modify: `app/words/routes.py`
- Tests: `tests/api/test_plan_pause.py`

- [ ] Add `plan_paused_until DATE nullable` to User model
- [ ] API: `POST /api/plan/pause {days: 1-14}` — sets plan_paused_until = today + days
- [ ] `POST /api/plan/resume` — clears plan_paused_until
- [ ] During pause: `/api/daily-plan` returns `{mode: 'paused', paused_until: date}` (no slots built)
- [ ] Dashboard shows "Plan paused — resuming {date}" banner instead of slots
- [ ] Streak not broken during pause (paused days treated as streak-neutral, not as gap)
- [ ] Tests: pause set → plan returns paused mode; resume → normal plan; streak unaffected during pause
- [ ] Run pytest tests/api/

---
### Task 49: Plan difficulty mode setting

**Files:**
- Modify: `app/auth/models.py`
- Create: `migrations/versions/20260516_plan_difficulty.py`
- Modify: `app/daily_plan/linear/plan.py`
- Modify: `app/templates/study/settings.html` (or create settings page)
- Tests: `tests/daily_plan/linear/test_plan.py`

- [ ] Add `plan_difficulty ENUM('light', 'normal', 'intensive') DEFAULT 'normal'` to User
- [ ] In `build_chain`: light mode — only 2 baseline slots (curriculum + SRS); normal — standard 4; intensive — standard + 2 extension slots always shown
- [ ] Settings page toggle (or add to existing StudySettings page if one exists)
- [ ] Tests: light → 2 baseline slots; normal → standard; intensive → forces extension slots
- [ ] Run pytest tests/daily_plan/linear/

---
### Task 50: Plan performance analytics route

**Files:**
- Modify: `app/study/routes.py`
- Create: `app/templates/study/plan_stats.html`
- Modify: `app/templates/study/index.html`
- Tests: `tests/study/test_plan_stats.py`

- [ ] Route: `GET /study/plan-stats` — query DailyPlanLog last 30 days; compute completion_rate, avg_slots_completed, day_secured_rate, avg_time_estimate
- [ ] Page: bar chart (slots completed per day), summary stats cards, trend indicators
- [ ] Tests: route 200; correct aggregates; empty history → zeros shown
- [ ] Run pytest tests/study/

---
### Task 51: Adaptive slot order by time-of-day

**Files:**
- Modify: `app/daily_plan/linear/plan.py`
- Tests: `tests/daily_plan/linear/test_plan.py`

- [ ] In `get_linear_plan()`: if user_local_hour ≥ 20 (evening), reorder: SRS first (quickest habit), then curriculum; morning (≤9): curriculum first (fresh brain)
- [ ] Only reorder for `plan_difficulty='normal'`; light/intensive use fixed order
- [ ] Add `slot_order_reason: str` to plan payload for UI tooltip
- [ ] Tests: hour=21 → SRS first; hour=8 → curriculum first; hour=14 → default order; light mode → fixed
- [ ] Run pytest tests/daily_plan/linear/

---
### Task 52: Plan completion celebration screen

**Files:**
- Modify: `app/templates/partials/linear_daily_plan.html`
- Modify: `app/static/css/design-system.css`
- Tests: `tests/daily_plan/linear/test_plan.py`

- [ ] When day_secured=True and all baseline slots complete: show full celebration card (not just banner)
- [ ] Card: XP earned today, streak count, tomorrow preview, motivational message
- [ ] CSS: `.plan-celebration` card with gradient border, entrance animation (confetti-like JS, checks prefers-reduced-motion)
- [ ] Tests: day_secured=True → celebration card rendered; contains XP and streak data
- [ ] Run pytest -m smoke

---
### BLOCK E: Speaking & Pronunciation (Tasks 53–62)

### Task 53: Web Speech API client integration

**Files:**
- Create: `app/static/js/speech_api.js`
- Tests: `tests/study/test_speech_api_ui.py` (integration-level, mock SpeechRecognition)

- [ ] `SpeechAPI` class: `startRecognition(onResult, onError)`, `stopRecognition()`, `isSupported() -> bool`
- [ ] Handles no-support gracefully: if `window.SpeechRecognition` undefined, isSupported() returns false
- [ ] Language: `recognition.lang = 'en-US'`; continuous=false; interimResults=false
- [ ] Module exported as ES module (`export default SpeechAPI`)
- [ ] Tests: mock SpeechRecognition API; startRecognition triggers onResult with transcript; unsupported path triggers onError
- [ ] Run pytest -m smoke (JS unit tests via pytest-js if available, else document as manual test)

---
### Task 54: Shadow reading exercise type

**Files:**
- Modify: `app/curriculum/validators.py`
- Create: `app/templates/curriculum/lessons/shadow_reading.html`
- Modify: `app/curriculum/routes/lessons.py`
- Modify: `app/daily_plan/linear/xp.py`, `app/achievements/xp_service.py`
- Tests: `tests/curriculum/test_shadow_reading.py`

- [ ] Validator: `{audio_url: str, text: str, translation: str}` — user listens then reads aloud
- [ ] Template: Phase 1 listen (audio plays); Phase 2 read-along (text revealed, audio plays again); Phase 3 self-assess checkbox "Я прочитал(а) вслух"
- [ ] No actual recording — honor system self-assessment
- [ ] Register `shadow_reading → linear_curriculum_use` in LESSON_TYPE_TO_SOURCE; XP=25
- [ ] Tests: template renders phases; self-assess checkbox required before submit
- [ ] Run pytest tests/curriculum/

---
### Task 55: Pronunciation exercise type (with Web Speech API)

**Files:**
- Modify: `app/curriculum/validators.py`
- Create: `app/templates/curriculum/lessons/pronunciation.html`
- Modify: `app/curriculum/routes/lessons.py`
- Modify: `app/daily_plan/linear/xp.py`
- Tests: `tests/curriculum/test_pronunciation_lesson.py`

- [ ] Validator: `{items: [{word: str, pronunciation_hint?: str, audio_url?: str}]}`
- [ ] Template: show word + pronunciation hint; "Послушать" button; "Произнести" button (triggers Web Speech API if supported, else skip button)
- [ ] If Web Speech API: record → compare transcript to word using normalized string match → show "Похоже!" or "Попробуй ещё раз"
- [ ] If not supported: show "Скажи вслух" + self-assess button
- [ ] Register `pronunciation → linear_curriculum_use` in LESSON_TYPE_TO_SOURCE; XP=20
- [ ] Tests: no-speech-api path → self-assess shown; word match logic unit-tested
- [ ] Run pytest tests/curriculum/

---
### Task 56: Pronunciation attempt tracking

**Files:**
- Modify: `app/curriculum/models.py`
- Create: `migrations/versions/20260517_pronunciation_attempt.py`
- Tests: `tests/curriculum/test_pronunciation_attempt.py`

- [ ] Model: `PronunciationAttempt(id, user_id FK, word, recognized_text, matched BOOLEAN, created_at)`
- [ ] Helper: `log_pronunciation_attempt(user_id, word, recognized, matched, db)`
- [ ] Called from pronunciation lesson submit endpoint
- [ ] Tests: model saves; matched computed correctly; multiple attempts per word allowed
- [ ] Run pytest tests/curriculum/

---
### Task 57: Pronunciation weakness detection

**Files:**
- Modify: `app/study/insights_service.py`
- Modify: `app/api/daily_status.py`
- Tests: `tests/study/test_insights_service.py`

- [ ] `get_pronunciation_weaknesses(user_id, db, min_attempts=3) -> list[str]` — words with match_rate < 50% over last 30 attempts
- [ ] Expose in `/api/daily-status` as `pronunciation_weak_words: [str]`
- [ ] Tests: words with 1/4 match rate → returned as weak; words with 3/4 → not returned; < min_attempts → excluded
- [ ] Run pytest tests/study/

---
### Task 58: Speaking slot in linear plan

**Files:**
- Create: `app/daily_plan/linear/slots/speaking_slot.py`
- Modify: `app/daily_plan/linear/chain.py`
- Modify: `app/templates/partials/linear_daily_plan.html`
- Tests: `tests/daily_plan/linear/test_speaking_slot.py`

- [ ] `build_speaking_slot(user_id, db)` — find next pronunciation or shadow_reading lesson in user's module
- [ ] Slot data: `{lesson_id, lesson_title, lesson_type, estimated_minutes: 7, speech_api_required: bool}`
- [ ] If no speaking lesson available: None (slot not shown)
- [ ] Template: speaking slot with microphone icon; if speech_api_required and not Chrome → show "Лучше в Chrome"
- [ ] Tests: slot builds; no speaking lesson → None; template note on Chrome
- [ ] Run pytest tests/daily_plan/linear/

---
### Task 59: Speaking streak and achievements

**Files:**
- Modify: `app/achievements/seed.py`
- Modify: `app/achievements/services.py`
- Modify: `app/api/daily_status.py`
- Tests: `tests/achievements/test_speaking_achievements.py`

- [ ] Seed: `speaking_first` (first pronunciation attempt), `speaking_streak_3` (3 consecutive days with pronunciation), `speaking_clear` (10 matched pronunciations)
- [ ] `get_speaking_streak(user_id, db)` — consecutive days with PronunciationAttempt rows
- [ ] `check_speaking_achievements(user_id, db)` — after PronunciationAttempt saved
- [ ] Expose `speaking_streak_days` in `/api/daily-status`
- [ ] Tests: matched pronunciation → speaking_first; 3-day streak → speaking_streak_3
- [ ] Run pytest tests/achievements/

---
### Task 60: Pronunciation score over time widget

**Files:**
- Modify: `app/study/insights_service.py`
- Modify: `app/words/routes.py`
- Modify: `app/templates/study/index.html`
- Tests: `tests/study/test_insights_service.py`

- [ ] `get_pronunciation_stats(user_id, db)` — total attempts, match_rate last 7 days, total words practiced
- [ ] Dashboard widget: "Произношение: N слов · X% совпадений"
- [ ] Widget wrapped in `_safe_widget_call()`
- [ ] Tests: correct aggregates; zero attempts → zeros
- [ ] Run pytest -m smoke

---
### Task 61: Immersion completion achievement

**Files:**
- Modify: `app/achievements/seed.py`
- Modify: `app/achievements/services.py`
- Tests: `tests/achievements/test_immersion_achievement.py`

- [ ] Seed: `immersion_daily` — all 4 skills practiced in one day (listening + writing + speaking + reading)
- [ ] `check_immersion_achievement(user_id, date, db)` — checks ListeningAttempt, UserWritingAttempt, PronunciationAttempt, UserReadingSession all have rows for date
- [ ] Called from day-secured path
- [ ] Tests: all 4 present → granted; only 3 → not granted; granted second time → idempotent
- [ ] Run pytest tests/achievements/

---
### Task 62: Shadowing exercise improvements

**Files:**
- Modify: `app/templates/curriculum/lessons/shadow_reading.html`
- Modify: `app/static/css/design-system.css`
- Tests: `tests/curriculum/test_shadow_reading.py`

- [ ] Add playback loop toggle: repeat audio automatically for shadowing practice
- [ ] Show synchronized text highlight as audio plays (if word timestamps available in content)
- [ ] Add "Попробуй ещё раз" button after self-assess to redo without starting a new lesson
- [ ] CSS: `.shadow-word--active` highlight style
- [ ] Tests: loop toggle state persists; retry resets self-assess; no crash if timestamps absent
- [ ] Run pytest tests/curriculum/

---
### BLOCK F: Personalization & Adaptation (Tasks 63–72)

### Task 63: Learning goals settings page

**Files:**
- Modify: `app/auth/models.py` (add daily_word_goal INT, weekly_lesson_goal INT)
- Create: `migrations/versions/20260518_learning_goals.py`
- Modify: `app/templates/study/settings.html` (or create `app/templates/study/goals.html`)
- Tests: `tests/study/test_learning_goals.py`

- [ ] Add `daily_word_goal INT DEFAULT 10` and `weekly_lesson_goal INT DEFAULT 5` to User
- [ ] Settings form with sliders: daily new words (5/10/15/20), weekly lessons (3/5/7/10)
- [ ] Goals displayed as context in daily plan header: "Цель: 10 слов сегодня"
- [ ] Tests: goals save; displayed in plan header; default values correct
- [ ] Run pytest tests/study/

---
### Task 64: Goal progress tracking in daily status

**Files:**
- Modify: `app/api/daily_status.py`
- Tests: `tests/api/test_daily_status.py`

- [ ] In `/api/daily-status`: compute `words_learned_today` (new SRS cards seen today), `lessons_completed_this_week`
- [ ] Add `goal_progress: {daily_words: {goal, actual, reached}, weekly_lessons: {goal, actual, reached}}` to payload
- [ ] Tests: actual < goal → reached=False; actual >= goal → True; week boundary correct
- [ ] Run pytest tests/api/

---
### Task 65: Focus area override without re-onboarding

**Files:**
- Modify: `app/study/routes.py` (or settings)
- Modify: `app/templates/study/settings.html`
- Tests: `tests/study/test_settings.py`

- [ ] Settings page: "Акцент обучения" dropdown — all / grammar / vocabulary / reading / speaking
- [ ] POST `/study/settings/focus` updates `User.onboarding_focus` in-place
- [ ] Confirm existing `_get_user_focus()` in plan.py reads this field (it does per CLAUDE.md)
- [ ] Tests: focus change reflects in next plan assembly; invalid focus value rejected
- [ ] Run pytest tests/study/

---
### Task 66: Weak area automatic detection in dashboard

**Files:**
- Modify: `app/study/insights_service.py`
- Modify: `app/words/routes.py`
- Modify: `app/templates/study/index.html`
- Tests: `tests/study/test_insights_service.py`

- [ ] `get_weak_areas(user_id, db) -> list[dict]` — combine SRS accuracy, grammar weakness, listening score into top-3 weak areas with kind ('vocabulary', 'grammar', 'listening', 'writing')
- [ ] Dashboard widget: "Слабые места: Грамматика (Past Perfect · 45%)" as actionable chips
- [ ] Each chip links to the relevant exercise or grammar topic page
- [ ] Tests: low SRS accuracy → vocabulary area returned; low grammar → grammar area; correct sort order
- [ ] Run pytest -m smoke

---
### Task 67: Adaptive content difficulty trigger

**Files:**
- Modify: `app/daily_plan/linear/slots/curriculum_slot.py`
- Tests: `tests/daily_plan/linear/test_curriculum_slot.py`

- [ ] If user's last 5 lessons all scored < 60% on quizzes, add `adaptive_hint: 'слишком сложно'` to slot.data
- [ ] If last 5 all scored > 90%, add `adaptive_hint: 'отлично, можно ускорить'`
- [ ] Template: show subtle hint in slot — "Темп можно ускорить" / "Сложный материал — не торопись"
- [ ] Tests: 5 low-score lessons → slow-down hint; 5 high-score → speed-up hint; mixed → no hint
- [ ] Run pytest tests/daily_plan/linear/

---
### Task 68: Custom vocabulary list (user-created collection)

**Files:**
- Modify: `app/study/routes.py`
- Modify: `app/study/models.py` (or create)
- Create: `migrations/versions/20260519_custom_word_list.py`
- Create: `app/templates/study/custom_list.html`
- Tests: `tests/study/test_custom_list.py`

- [ ] Model: `CustomWordList(id, user_id FK, name TEXT, created_at)` + `CustomWordListEntry(id, list_id FK, word TEXT, translation TEXT)`
- [ ] Route: `GET/POST /study/lists` — view and create lists; `GET /study/lists/<id>` — view entries; add/remove words
- [ ] Template: list management UI with add word form
- [ ] Tests: create list; add word; remove word; list owned by other user → 403
- [ ] Run pytest tests/study/

---
### Task 69: Add words from vocabulary lessons to custom list

**Files:**
- Modify: `app/templates/curriculum/lessons/vocabulary.html`
- Modify: `app/curriculum/routes/vocabulary_lessons.py` (add API)
- Tests: `tests/curriculum/test_vocabulary_lessons.py`

- [ ] Add "+" button on each vocabulary word in lesson → dropdown "Добавить в список" showing user's custom lists
- [ ] AJAX: `POST /api/custom-lists/<list_id>/words {word, translation}` — adds entry
- [ ] Visual feedback: button becomes checkmark after add
- [ ] Tests: word added to list; duplicate add → idempotent (no duplicate entry); list selector shows correct user lists
- [ ] Run pytest tests/curriculum/

---
### Task 70: Vocabulary import from plain text

**Files:**
- Modify: `app/study/routes.py`
- Modify: `app/templates/study/custom_list.html`
- Tests: `tests/study/test_custom_list.py`

- [ ] Import form: paste text in format "word - translation" (one per line) or "word|translation"
- [ ] Parser: strip whitespace, handle both ` - ` and `|` delimiters, skip malformed lines
- [ ] Bulk insert with dedup (skip exact duplicates within same list)
- [ ] Show import summary: "Добавлено N слов, пропущено M дублей"
- [ ] Tests: correct parse; duplicates skipped; malformed lines ignored; import count correct
- [ ] Run pytest tests/study/

---
### Task 71: SRS study from custom word lists

**Files:**
- Modify: `app/study/routes.py`
- Modify: `app/templates/study/custom_list.html`
- Tests: `tests/study/test_custom_list.py`

- [ ] Button "Учить список" on custom list page → launches `/study` session with custom list words
- [ ] Create UserCardDirection entries for words in list that don't have them yet
- [ ] Redirect to study session filtered to these cards
- [ ] Tests: cards created for new words; existing cards not duplicated; redirect correct
- [ ] Run pytest tests/study/

---
### Task 72: Vocabulary source tracking

**Files:**
- Modify: `app/curriculum/models.py` (UserCardDirection)
- Create: `migrations/versions/20260520_card_source.py`
- Tests: `tests/curriculum/test_card_source.py`

- [ ] Add `source VARCHAR(50) nullable` to UserCardDirection — e.g., 'lesson_vocab', 'book_reading', 'custom_list', 'manual'
- [ ] Set source when card is created: lesson vocab → 'lesson_vocab'; book → 'book_reading'; custom list → 'custom_list'
- [ ] Show source badge in SRS card during review (subtle icon)
- [ ] Tests: cards get correct source; migration runs cleanly; source badge shown in template
- [ ] Run pytest tests/curriculum/

---
### BLOCK G: Analytics & Insights (Tasks 73–82)

### Task 73: Skills balance radar chart

**Files:**
- Modify: `app/study/insights_service.py`
- Modify: `app/words/routes.py`
- Modify: `app/templates/study/insights.html`
- Tests: `tests/study/test_insights_service.py`

- [ ] `get_skills_balance(user_id, db) -> dict` — scores 0-100 for vocabulary (SRS accuracy), grammar (grammar lab accuracy), reading (reading sessions / week), listening (listening attempts / week), writing (writing attempts / week), speaking (pronunciation match rate)
- [ ] Render Chart.js radar chart on insights page
- [ ] Tests: each skill score computed correctly; zero activity → 0; full activity → near 100
- [ ] Run pytest tests/study/

---
### Task 74: Grammar mastery radar chart

**Files:**
- Modify: `app/study/insights_service.py`
- Modify: `app/templates/study/insights.html`
- Tests: `tests/study/test_insights_service.py`

- [ ] `get_grammar_mastery_by_topic(user_id, db)` — for each GrammarTopic the user has attempted: accuracy %, mastered count, total count
- [ ] Render as chart: horizontal bar chart sorted by accuracy (worst topics first)
- [ ] Highlight topics with < 60% in red
- [ ] Tests: topics returned sorted; mastered_count correct; topics with 0 attempts excluded
- [ ] Run pytest tests/study/

---
### Task 75: Learning velocity trend widget

**Files:**
- Modify: `app/study/insights_service.py`
- Modify: `app/words/routes.py`
- Modify: `app/templates/study/index.html`
- Tests: `tests/study/test_insights_service.py`

- [ ] `get_learning_velocity(user_id, db, weeks=4) -> dict` — weekly word count + lesson count for last 4 weeks
- [ ] Compute trend: is velocity increasing, stable, or declining
- [ ] Dashboard widget: "Темп: +8 слов/нед · ↑ растёт" or "↓ снизился"
- [ ] Tests: correct weekly buckets; trend direction from last 2 weeks comparison
- [ ] Run pytest -m smoke

---
### Task 76: Daily learning minutes tracker

**Files:**
- Modify: `app/curriculum/models.py`
- Create: `migrations/versions/20260521_study_minutes.py`
- Modify: `app/api/daily_status.py`
- Tests: `tests/api/test_daily_status.py`

- [ ] Model: `DailyStudyMinutes(id, user_id FK, study_date DATE, minutes SMALLINT)` — aggregates time on site
- [ ] Track: each lesson_complete adds `estimated_minutes` from slot config; each SRS session adds session duration
- [ ] Add `minutes_studied_today` to `/api/daily-status`
- [ ] Show "Изучал(а) N минут сегодня" in compact form on dashboard header
- [ ] Tests: lesson complete → minutes added; multiple completions accumulate; correct date bucket
- [ ] Run pytest tests/api/

---
### Task 77: Estimated time to next CEFR level

**Files:**
- Modify: `app/study/insights_service.py`
- Modify: `app/templates/study/insights.html`
- Tests: `tests/study/test_insights_service.py`

- [ ] Based on: remaining modules at current level, average lessons/week from recent velocity, lessons/module from curriculum data
- [ ] `get_level_eta(user_id, db) -> {current_level, next_level, weeks_estimate, confidence}` — confidence is 'low'/'medium'/'high' based on how much history user has
- [ ] Show on insights page: "До уровня B1: ~6 недель при текущем темпе"
- [ ] Tests: user with 4 modules/week and 8 remaining → ETA = 2 weeks; < 1 week history → confidence=low
- [ ] Run pytest tests/study/

---
### Task 78: Weekly learning report (dashboard summary)

**Files:**
- Modify: `app/words/routes.py`
- Modify: `app/templates/study/index.html`
- Tests: `tests/study/test_dashboard_weekly.py`

- [ ] On Monday: show "Итоги прошлой недели" card at top of dashboard if user was active last week
- [ ] Card: words learned, lessons completed, days secured, total minutes, vs. previous week
- [ ] Dismissed with one click; dismissed state stored in session (not DB)
- [ ] Tests: Monday → weekly summary shown; already dismissed this week → hidden; no last-week activity → hidden
- [ ] Run pytest tests/study/

---
### Task 79: Accuracy improvement chart

**Files:**
- Modify: `app/study/insights_service.py`
- Modify: `app/templates/study/insights.html`
- Tests: `tests/study/test_insights_service.py`

- [ ] `get_accuracy_trend(user_id, db, days=30) -> {dates, srs_accuracy, quiz_accuracy}` — weekly averages
- [ ] Render dual-line Chart.js chart on insights page
- [ ] Tests: correct weekly averages; missing data weeks → null in series (not 0)
- [ ] Run pytest tests/study/

---
### Task 80: Comprehension score tracking per lesson type

**Files:**
- Modify: `app/curriculum/models.py` (LessonAttempt)
- Modify: `app/study/insights_service.py`
- Tests: `tests/study/test_insights_service.py`

- [ ] Ensure `LessonAttempt.score` is stored per lesson type (quiz, grammar, dictation, final_test all already do this)
- [ ] `get_comprehension_by_type(user_id, db)` — avg score per lesson type over last 30 days
- [ ] Show as mini-table on insights page: "Тест: 82% | Грамматика: 68% | Диктант: 71%"
- [ ] Tests: correct averages per type; type with no attempts → excluded
- [ ] Run pytest tests/study/

---
### Task 81: Time-of-day learning patterns

**Files:**
- Modify: `app/study/insights_service.py`
- Modify: `app/templates/study/insights.html`
- Tests: `tests/study/test_insights_service.py`

- [ ] `get_study_time_distribution(user_id, db)` — count lesson completions by hour-of-day (user local time) over last 30 days
- [ ] Return `{hours: [0..23], counts: [...], peak_hour: N}`
- [ ] Show as bar chart on insights page with peak hour highlight: "Ты обычно учишься в 19:00"
- [ ] Tests: correct hour bucketing in user timezone; peak_hour is argmax of counts
- [ ] Run pytest tests/study/

---
### Task 82: Longest streak record and personal bests page

**Files:**
- Modify: `app/achievements/streak_service.py`
- Modify: `app/templates/study/insights.html`
- Modify: `app/auth/models.py` (add longest_streak_days INT DEFAULT 0)
- Tests: `tests/achievements/test_streak_service.py`

- [ ] Track `longest_streak_days` on UserStatistics or User — update whenever current streak increases
- [ ] Insights page section: "Рекорды — Лучшая серия: N дней · Слов в один день: M · Лучшая неделя: K уроков"
- [ ] Tests: streak update → longest_streak updated if beaten; never decreases; personal best in lessons per week computed correctly
- [ ] Run pytest tests/achievements/

---
### BLOCK H: Content Quality & Gamification (Tasks 83–99)

### Task 83: Daily challenge system

**Files:**
- Modify: `app/curriculum/models.py` (or create DailyChallenge model)
- Create: `migrations/versions/20260522_daily_challenge.py`
- Create: `app/daily_plan/challenge.py`
- Tests: `tests/daily_plan/test_challenge.py`

- [ ] `DailyChallenge(id, challenge_date DATE, lesson_id FK, bonus_xp INT, category)` — one challenge per day, seeded daily
- [ ] `get_today_challenge(user_id, db)` — returns challenge + user completion status
- [ ] Challenge categories: speed_run (complete lesson in <5 min), accuracy_focus (score ≥ 90%), listening_deep (dictation lesson)
- [ ] Tests: challenge seeded for today; completion tracked; same challenge for all users on same day
- [ ] Run pytest tests/daily_plan/

---
### Task 84: Daily challenge UI in linear plan

**Files:**
- Modify: `app/templates/partials/linear_daily_plan.html`
- Modify: `app/words/routes.py`
- Modify: `app/static/css/design-system.css`
- Tests: `tests/daily_plan/test_challenge.py`

- [ ] Show daily challenge card below slots: gold border, "2x XP", challenge description
- [ ] Mark as completed when user completes the challenge lesson with qualifying score
- [ ] CSS: `.daily-challenge-card` with gold border using design tokens
- [ ] Tests: challenge card shown when uncompleted; hidden/greyed when completed; 2x XP display correct
- [ ] Run pytest -m smoke

---
### Task 85: Cultural notes system

**Files:**
- Modify: `app/curriculum/models.py` (add CulturalNote model)
- Create: `migrations/versions/20260522_cultural_note.py`
- Modify: `app/templates/curriculum/lessons/vocabulary.html`
- Tests: `tests/curriculum/test_cultural_note.py`

- [ ] Model: `CulturalNote(id, word_id FK, note TEXT, context VARCHAR(100))` — contextual note about word usage
- [ ] Template: show cultural note as collapsible "Культурный контекст" below word if present
- [ ] Admin: add CulturalNote CRUD to admin panel (list view + inline edit)
- [ ] Tests: word with note → section shown; without → hidden; admin can add note
- [ ] Run pytest tests/curriculum/

---
### Task 86: Content quality dashboard (admin)

**Files:**
- Modify: `app/admin/main_routes.py`
- Create: `app/templates/admin/content_quality.html`
- Tests: `tests/admin/test_content_quality.py`

- [ ] Route: `GET /admin/content-quality` — aggregate per lesson type: % with audio, % with examples, % with IPA, % completed by users
- [ ] Highlight missing content: lessons with no audio, no examples, no vocabulary words
- [ ] Export as CSV (reuse CSV export pattern from CLAUDE.md)
- [ ] Tests: route 200 for admin; 403 for non-admin; aggregates correct
- [ ] Run pytest tests/admin/

---
### Task 87: Missing audio detection and reporting

**Files:**
- Modify: `app/admin/main_routes.py`
- Create: `app/cli/content_commands.py`
- Tests: `tests/admin/test_content_quality.py`

- [ ] CLI: `flask content-audit audio` — list lessons with audio_url that returns 404 or is empty
- [ ] Admin view: table of lessons with missing/broken audio, sorted by module progression
- [ ] Tests: CLI identifies missing audio entries; admin route includes same data
- [ ] Run pytest tests/admin/

---
### Task 88: Idiom lesson type

**Files:**
- Modify: `app/curriculum/validators.py`
- Create: `app/templates/curriculum/lessons/idiom.html`
- Modify: `app/curriculum/routes/lessons.py`
- Modify: `app/daily_plan/linear/xp.py`
- Tests: `tests/curriculum/test_idiom_lesson.py`

- [ ] Validator: `{items: [{phrase: str, meaning: str, example: str, audio_url?: str}]}`
- [ ] Template: present phrase, animated reveal of meaning, example sentence with audio, self-assess "Запомнил(а)"
- [ ] Register `idiom → linear_curriculum_vocabulary` in LESSON_TYPE_TO_SOURCE; XP=18
- [ ] Tests: template renders; self-assess marks complete; multiple items navigate correctly
- [ ] Run pytest tests/curriculum/

---
### Task 89: Lesson content search

**Files:**
- Modify: `app/curriculum/routes/main.py` (or create search route)
- Create: `app/templates/curriculum/search.html`
- Modify: `app/templates/curriculum/base.html` (add search icon)
- Tests: `tests/curriculum/test_search.py`

- [ ] Full-text search over lesson titles, vocabulary words, and grammar topics
- [ ] Route: `GET /curriculum/search?q=` — returns matching lessons grouped by module
- [ ] Uses PostgreSQL `ILIKE` with `%q%` on `Lesson.title` and `Word.english`
- [ ] Tests: query returns relevant lessons; empty query → redirect to curriculum home; XSS safe (uses parameterized queries)
- [ ] Run pytest tests/curriculum/

---
### Task 90: Lesson user feedback collection

**Files:**
- Modify: `app/curriculum/models.py`
- Create: `migrations/versions/20260523_lesson_feedback.py`
- Modify: `app/templates/curriculum/lessons/` (base lesson template if one exists, else each)
- Tests: `tests/curriculum/test_lesson_feedback.py`

- [ ] Model: `LessonFeedback(id, user_id FK, lesson_id FK, rating SMALLINT 1-5, comment TEXT nullable, created_at)` — one per user per lesson
- [ ] Thumbs up/down widget at bottom of each completed lesson
- [ ] Save via `POST /api/curriculum/lessons/<id>/feedback`
- [ ] Admin: content quality dashboard shows avg rating per lesson
- [ ] Tests: feedback saves; duplicate → update not create; admin sees aggregated ratings
- [ ] Run pytest tests/curriculum/

---
### Task 91: Immersion streak (all 4 skills in consecutive days)

**Files:**
- Modify: `app/achievements/streak_service.py`
- Modify: `app/api/daily_status.py`
- Modify: `app/achievements/seed.py`
- Tests: `tests/achievements/test_streak_service.py`

- [ ] `get_immersion_streak(user_id, db)` — consecutive days where user had ListeningAttempt + UserWritingAttempt + PronunciationAttempt (or shadow reading) + UserReadingSession
- [ ] Expose as `immersion_streak_days` in `/api/daily-status`
- [ ] Seed: `immersion_week` achievement (7-day immersion streak)
- [ ] Tests: 3 days all 4 skills → streak=3; day missing writing → streak resets; grant achievement at 7
- [ ] Run pytest tests/achievements/

---
### Task 92: Streak shield (protection for 1 missed day)

**Files:**
- Modify: `app/achievements/streak_service.py`
- Modify: `app/auth/models.py` (add streak_shield_active BOOLEAN DEFAULT FALSE)
- Create: `migrations/versions/20260523_streak_shield.py`
- Modify: `app/templates/study/index.html`
- Tests: `tests/achievements/test_streak_service.py`

- [ ] User earns a streak shield every 7-day milestone (1 shield max, use-once)
- [ ] When streak would be broken (missed day): if `streak_shield_active=True`, keep streak, set shield=False
- [ ] Dashboard: show shield icon when active; "Твоя серия защищена на 1 день"
- [ ] Tests: shield prevents break; second miss → streak breaks; shield not restored without new milestone
- [ ] Run pytest tests/achievements/

---
### Task 93: Weekly milestone rewards

**Files:**
- Modify: `app/achievements/seed.py`
- Modify: `app/achievements/services.py`
- Tests: `tests/achievements/test_weekly_milestones.py`

- [ ] Seed milestone achievements: `week_1` (7 consecutive days), `week_4` (28 days), `week_12` (84 days)
- [ ] Each grants bonus XP on achievement: week_1=100 XP, week_4=500 XP, week_12=2000 XP
- [ ] Notification created on milestone: "Серия N недель! +M XP"
- [ ] Tests: correct trigger at milestone day counts; bonus XP awarded via award_xp; notification created
- [ ] Run pytest tests/achievements/

---
### Task 94: SRS performance by source tag

**Files:**
- Modify: `app/study/services/stats_service.py`
- Modify: `app/templates/study/stats.html`
- Tests: `tests/study/test_stats_service.py`

- [ ] Aggregate UserCardDirection accuracy by `source` field added in Task 72: accuracy per source category
- [ ] Stats page: "Слова из уроков: 78% · Из книг: 65% · Из своих списков: 70%"
- [ ] Tests: correct per-source aggregation; source=None → grouped under 'other'
- [ ] Run pytest tests/study/

---
### Task 95: Challenge streak and leaderboard position

**Files:**
- Modify: `app/daily_plan/challenge.py`
- Modify: `app/templates/partials/linear_daily_plan.html`
- Tests: `tests/daily_plan/test_challenge.py`

- [ ] Track challenge completion streak: consecutive days of completing daily challenge
- [ ] Show in challenge card: "Серия челленджей: 5 дней"
- [ ] Add challenge completions to leaderboard points calculation (bonus 10 pts per challenge)
- [ ] Tests: streak counts; gap resets; leaderboard points include challenge bonus
- [ ] Run pytest tests/daily_plan/

---
### Task 96: Challenge completion achievements

**Files:**
- Modify: `app/achievements/seed.py`
- Modify: `app/achievements/services.py`
- Tests: `tests/achievements/test_challenge_achievements.py`

- [ ] Seed: `challenge_first` (first challenge complete), `challenge_streak_7` (7-day challenge streak), `challenger` (30 challenges completed total)
- [ ] `check_challenge_achievements(user_id, db)` called after challenge completion
- [ ] Tests: first completion → challenge_first; 7-day → challenge_streak_7; 30 total → challenger
- [ ] Run pytest tests/achievements/

---
### Task 97: Notification for plan streak milestones

**Files:**
- Modify: `app/notifications/services.py`
- Modify: `app/daily_plan/service.py` (day secured path)
- Tests: `tests/notifications/test_milestone_notifications.py`

- [ ] When day_secured and streak hits 7/30/100 days: create in-app notification
- [ ] Notification respects `notify_in_app_achievements` user flag
- [ ] Dedup: only create one notification per milestone day (check for existing notification of same type today)
- [ ] Tests: streak=7 → notification created; second day at 7 → no duplicate; flag=False → no notification
- [ ] Run pytest tests/notifications/

---
### Task 98: Telegram bot plan status command

**Files:**
- Modify: `app/telegram/handlers/` (find the relevant handler file)
- Tests: `tests/telegram/test_plan_status.py`

- [ ] Add `/plan` command in Telegram bot: shows today's plan status (slots + completion), streak, and day_secured state
- [ ] Format: clean text with emoji for each slot type; "✅ Завершено" or "⏳ Осталось N"
- [ ] Uses existing `get_linear_plan(user_id, db)` — same data as web
- [ ] Tests: /plan command returns formatted text; user with no plan → "Открой приложение чтобы начать"
- [ ] Run pytest tests/telegram/

---
### Task 99: API rate limiting for pronunciation and writing endpoints

**Files:**
- Modify: `app/api/daily_plan_events.py` (or wherever the new skill endpoints are)
- Modify: `app/curriculum/routes/lessons.py`
- Tests: `tests/api/test_rate_limiting.py`

- [ ] Add rate limit to pronunciation attempt submit: max 100 attempts per user per day (prevents leaderboard abuse)
- [ ] Add rate limit to writing attempt submit: max 50 per user per day
- [ ] Return `api_error('rate_limit_exceeded', 429)` on breach
- [ ] Tests: 101st pronunciation attempt → 429; 51st writing → 429; different users not affected by each other's limits
- [ ] Run pytest tests/api/

---
### Task 100: Final verification + documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: various test files

- [ ] Run full test suite: `pytest`
- [ ] Run `pytest -m smoke`
- [ ] Fix any regressions introduced by previous tasks
- [ ] Update CLAUDE.md with new canonical patterns: `UserWritingAttempt`, `ListeningAttempt`, `PronunciationAttempt`, `get_immersion_streak`, `maybe_award_listening/writing/speaking_xp`, `DailyChallenge`
- [ ] Verify all new endpoints follow `api_error()` pattern
- [ ] Verify all new XP paths use `award_xp(score=...)` where accuracy signal available
- [ ] Move this plan to `docs/plans/completed/`
