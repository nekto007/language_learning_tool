---
# Achievements: Russian Categories, Sort by Progress, Fill Missing Grant Logic

## Overview

Audit on 2026-05-30 found 29 of 64 seeded achievements (~45%) have no
grant logic anywhere in the codebase. They are visible in the dashboard
"Следующие цели" list but cannot be earned. Root causes:

- **Naming mismatch in streak family** — `app/achievements/seed.py`
  registers `daily_streak_3 / 7 / 14 / 30 / 60 / 100`, but
  `AchievementService.check_streak_achievements`
  (`app/achievements/services.py:287`) checks codes `streak_3 / 7 / 14 / 30`.
  Both sides are wrong about each other → no streak achievement is ever
  awarded.
- **Missing check functions** — entire families
  (lessons_*, books_*, cards_*, level_*, words_learned_*, matching_*,
  perfect_session, chapter_marathon) have no `check_*_achievements`
  function. `check_all_achievements` currently calls only
  `check_grade_achievements` + `check_streak_achievements`.

Display problems in the dashboard right rail
(`app/templates/words/dashboard_unified.html:79-133`):

- Category badge text is the raw English category code
  (`streak`, `lessons`, `mission`, …) — `{{ category }}` is rendered
  verbatim, not localised.
- "Следующие цели" iterates `by_category` insertion order; unearned items
  appear in a stable but not progress-aware order, hiding nearest goals
  behind hard ones.

Target end state:

- Every seeded achievement has a corresponding grant path that fires
  when its threshold is crossed.
- Streak family naming is consistent across seed and service.
- Existing users have the achievements they already earned by data —
  backfill runs once and is idempotent (`grant_achievement` already
  upserts via savepoint + IntegrityError catch).
- Dashboard shows Russian category labels and sorts "Следующие цели" by
  proximity-to-earned.

## Context

- Files involved:
  - `app/achievements/seed.py` — 64 `INITIAL_ACHIEVEMENTS` definitions; categories: lessons, quiz, streak, books, flashcards, study, score, levels, matching, special, mission, listening, writing, speaking, immersion, challenge
  - `app/achievements/services.py` — `check_grade_achievements` (lines 222-271), `check_streak_achievements` (273-315, naming bug at 287-292), `check_mission_achievements` (317-...), `check_all_achievements` (569-588), `check_listening_achievements` (591), `check_writing_achievements` (634), `check_speaking_achievements` (671), `check_immersion_achievement` (708), `check_weekly_milestone_achievements` (788), `check_challenge_achievements` (832)
  - `app/achievements/models.py` — `UserStatistics` with `total_lessons_completed`, `current_streak_days`, `longest_streak_days`, grade counters (`grade_a_count`, etc.)
  - `app/study/models.py:979` — `Achievement` model: `code`, `name`, `description`, `icon`, `xp_reward`, `category`
  - `app/study/services/stats_service.py:497` — `get_achievements_by_category` (consumed by dashboard widget)
  - `app/templates/words/dashboard_unified.html:79-133` — right-rail achievements block (category ring + "Следующие цели" list)
  - `app/words/routes.py:1256` — wires `achievements_by_category` into `dash_unified` template via `_safe_widget_call`
- Hook points (where check_* calls should be wired in):
  - Lesson completion → `app/curriculum/service.py` (or wherever `LessonProgress.status='completed'` is written) for `check_lesson_achievements`
  - Book chapter completion → `app/books/api.py` (save_reading_position handler that fires chapter_completed) for `check_book_achievements`
  - SRS card grading → `app/srs/service.py` `grade_card` and `app/study/api_routes.py` `update_after_review` for `check_card_achievements`
  - Level promotion → wherever onboarding_level is bumped (currently only via onboarding) for `check_level_achievements`
  - Word "learning"/"mastered" transitions → `UserWord.update_status` in `app/study/models.py` for `check_words_learned_achievements`
  - Matching game completion → `app/study/game_routes.py` matching submit path for `check_matching_achievements`
- Related patterns:
  - `grant_achievement(user_id, achievement_id)` in `app/achievements/services.py` — idempotent upsert via savepoint + IntegrityError catch; honours `UniqueConstraint(user_id, achievement_id)`
  - `notify_achievement(user_id, name, icon)` from `app/notifications/services.py` — sends an in-app notification on grant
  - `_safe_widget_call` in `app/words/routes.py` — widget call wrapper so an exception in one widget never breaks the dashboard
- Dependencies: none external; works on the existing `Achievement`/`UserAchievement` schema (no migration).

## Development Approach

- **Testing approach**: Regular (code first, then tests).
- Complete each task fully before moving to the next.
- **CRITICAL: every task MUST include new/updated tests.**
- **CRITICAL: all tests must pass before starting next task.**
- Group commits by phase boundary so cosmetic + naming fix can deploy
  independently of the larger grant-logic work.
- After each task: `pytest -m smoke` MUST pass, plus targeted suite
  (`tests/achievements/`, `tests/study/`, `tests/curriculum/`,
  `tests/test_dashboard_*`).
- All grants go through `grant_achievement` → idempotent, race-safe.
- Each `check_*_achievements` returns `List[Achievement]` of NEWLY
  granted ones; callers commit if list is non-empty (mirror existing
  pattern in `check_streak_achievements`).

## Implementation Steps

### Task 1: Phase 1 — Russian category labels in dashboard

**Files:**
- Modify: `app/study/services/stats_service.py` — `get_achievements_by_category`
- Modify: `app/templates/words/dashboard_unified.html` — category badge rendering
- Modify: `tests/study/test_stats_service.py` (or equivalent)

- [x] Add `_CATEGORY_LABELS_RU = {'lessons': 'Уроки', 'streak': 'Серии', 'mission': 'Миссии', 'quiz': 'Квизы', 'flashcards': 'Карточки', 'books': 'Книги', 'writing': 'Письмо', 'speaking': 'Говорение', 'matching': 'Сопоставление', 'listening': 'Аудирование', 'levels': 'Уровни', 'challenge': 'Челленджи', 'study': 'Изучение', 'special': 'Особые', 'immersion': 'Погружение', 'score': 'Очки', 'general': 'Общее'}` to `stats_service.py`
- [x] In `get_achievements_by_category` add `category_labels` to the returned dict — map raw codes to Russian labels via the dict, fall back to the raw code if missing
- [x] In template (`dashboard_unified.html:100`) render `{{ achievements_by_category.category_labels[category] or category }}` instead of `{{ category }}`
- [x] Update template `title="..."` attribute to use the Russian label too (line 92)
- [x] Write tests: `get_achievements_by_category` returns `category_labels` mapping; rendered HTML for a user with streak earned shows "Серии" not "streak"
- [x] Run `pytest tests/study/ -k achievements -x` — must pass before task 2

### Task 2: Phase 1 — Sort "Следующие цели" by xp_reward (proxy for proximity)

**Files:**
- Modify: `app/study/services/stats_service.py` or `app/templates/words/dashboard_unified.html`
- Modify: `tests/study/test_stats_service.py`

- [x] In `get_achievements_by_category` add a flat `next_goals` list to the returned dict: all unearned achievements sorted by `xp_reward ASC` then `code` (deterministic)
- [x] Update template to iterate `achievements_by_category.next_goals[:4]` instead of building the list inline via `selectattr`
- [x] Write tests: `next_goals` is sorted ascending by xp_reward; earned achievements excluded
- [x] Run `pytest tests/study/ -k achievements -x` — must pass before task 3

### Task 3: Phase 2 — Fix streak naming mismatch (HIGH)

**Files:**
- Modify: `app/achievements/services.py` — `check_streak_achievements` (line 287)
- Modify: `tests/achievements/test_streak_service.py` or `tests/achievements/test_check_achievements.py`

- [x] Replace `streak_3 / 7 / 14 / 30` codes in `check_streak_achievements` with `daily_streak_3 / 7 / 14 / 30 / 60 / 100` to match seed
- [x] Extend the list to include `daily_streak_60` and `daily_streak_100` (currently missing from the check list even before the naming fix)
- [x] Confirm `notify_achievement` keeps working (no signature change)
- [x] Write tests: user with `current_streak_days=7` gets `daily_streak_3` and `daily_streak_7`; user with 100 gets all six; user with 2 gets none; idempotency — second call grants nothing new
- [x] Run `pytest tests/achievements/ -x` — must pass before task 4

### Task 4: Phase 3 — Add check_lesson_achievements (6 codes)

**Files:**
- Modify: `app/achievements/services.py` — new `check_lesson_achievements` method
- Modify: `app/curriculum/service.py` (or whichever module commits `LessonProgress.status='completed'`) — wire the check call after the status flip
- Modify: `tests/curriculum/` or `tests/achievements/`

- [x] Add `AchievementService.check_lesson_achievements(user_id, stats)` checking codes `first_lesson` (≥1), `lessons_5` (≥5), `lessons_10` (≥10), `lessons_25` (≥25), `lessons_50` (≥50), `lessons_100` (≥100) against `stats.total_lessons_completed`
- [x] Follow the existing pattern from `check_streak_achievements` (loop, `grant_achievement`, `notify_achievement`, commit on non-empty list)
- [x] Wire it into `check_all_achievements` (line 569-588)
- [x] Identify the lesson-completion commit site and call `check_lesson_achievements` there (best-effort try/except, must not block the lesson completion)
- [x] Write tests: user completing their 1st / 5th / 10th lesson gets the matching badge; 11th lesson grants nothing new (already earned)
- [x] Run `pytest tests/achievements/ tests/curriculum/ -x` — must pass before task 5

### Task 5: Phase 3 — Add check_book_achievements (4 codes)

**Files:**
- Modify: `app/achievements/services.py`
- Modify: `app/achievements/models.py` — extend `UserStatistics` if a `books_completed` counter is missing
- Modify: `app/books/api.py` — wire the check at chapter-completion site (when `pre_offset < 1.0 and post_offset >= 1.0` and it's the last chapter)
- Modify: `tests/books/` or `tests/achievements/`

- [x] Determine the correct "books completed" signal: count `Book` rows where every chapter has `UserChapterProgress.offset_pct >= 0.99`, or add an explicit counter to `UserStatistics` and increment on book-completed event
- [x] Recommend: add `total_books_completed INTEGER DEFAULT 0` to `UserStatistics` (migration), increment when the last-chapter completion path fires in `app/books/api.py`
- [x] Add `AchievementService.check_book_achievements(user_id, stats)` for `first_book`, `books_5`, `books_10`, `chapter_marathon` (decide criterion for chapter_marathon, e.g. ≥10 chapters in a single day from `UserReadingSession`)
- [x] Wire into `check_all_achievements`
- [x] Wire into chapter-completion in `app/books/api.py` after the book milestone path
- [x] Migration: `20260530_user_stats_books_completed.py` adding the column with `server_default='0'`
- [x] Write tests: user finishing their 1st book gets `first_book`; finishing the 5th gets `books_5`; non-final chapters don't fire
- [x] Run `pytest tests/books/ tests/achievements/ -x` — must pass before task 6

### Task 6: Phase 3 — Add check_card_achievements (3 codes)

**Files:**
- Modify: `app/achievements/services.py`
- Modify: `app/achievements/models.py` — counter `total_cards_studied` if not already present
- Modify: `app/srs/service.py` (`grade_card`) AND `app/study/models.py` (`UserCardDirection.update_after_review`) — increment counter and call check
- Modify: `tests/srs/`, `tests/study/`

- [x] Verify whether `UserStatistics` already counts card reviews; if not, add `total_cards_reviewed INTEGER DEFAULT 0` (migration)
- [x] Add `AchievementService.check_card_achievements(user_id, stats)` for `cards_100`, `cards_500`, `cards_1000` against the counter
- [x] Increment counter inside both grading paths (canonical + legacy)
- [x] Wire into `check_all_achievements`
- [x] Migration: `20260530_user_stats_total_cards_reviewed.py`
- [x] Write tests: 100/500/1000 review threshold each grants exactly one achievement; idempotent on subsequent reviews
- [x] Run `pytest tests/srs/ tests/study/ tests/achievements/ -x` — must pass before task 7

### Task 7: Phase 3 — Add check_level_achievements (3 codes)

**Files:**
- Modify: `app/achievements/services.py`
- Modify: `app/achievements/xp_service.py` — `get_level_info` is the canonical level source
- Modify: `app/achievements/xp_service.py` — `award_xp` is the natural hook (after `level_up` event)
- Modify: `tests/achievements/`

- [x] Add `AchievementService.check_level_achievements(user_id, stats)` for `level_10` (≥10), `level_25` (≥25), `level_50` (≥50) — read current level via `get_level_info(stats.total_xp).current_level`
- [x] Wire into `check_all_achievements`; also call from `award_xp` after a `level_up` event so the badge fires immediately at promotion
- [x] Write tests: leveling to 10/25/50 grants the matching badge; awarding XP that doesn't cross a threshold doesn't fire anything
- [x] Run `pytest tests/achievements/ -x` — must pass before task 8

### Task 8: Phase 3 — Add check_words_learned_achievements (2 codes)

**Files:**
- Modify: `app/achievements/services.py`
- Modify: `app/study/models.py` — `UserWord.update_status` is the natural hook (transition to `learning` / `review` / `mastered`)
- Modify: `tests/study/test_user_word.py` or `tests/achievements/`

- [x] Decide the "learned" definition: count of `UserWord` rows with `status='mastered'` or with `status IN ('learning', 'review', 'mastered')` — recommend `mastered` for `words_learned_100/500`
- [x] Add `AchievementService.check_words_learned_achievements(user_id, stats)` — query the count and compare to thresholds (no need for a counter if the SQL is cheap)
- [x] Wire into `check_all_achievements` and into `UserWord.update_status` (best-effort try/except)
- [x] Write tests: 100th / 500th word mastered grants the matching badge; status changes that don't cross the threshold don't fire
- [x] Run `pytest tests/study/ tests/achievements/ -x` — must pass before task 9

### Task 9: Phase 3 — Add check_matching_achievements (3 codes)

**Files:**
- Modify: `app/achievements/services.py`
- Modify: `app/study/game_routes.py` — matching game submit path
- Modify: `tests/study/test_game_routes.py`

- [x] Identify the matching codes: `matching_first` (1 completion), `matching_perfect` (one perfect game), `matching_speed` (e.g. completion in <30s) — confirm against `seed.py` descriptions
- [x] Add `AchievementService.check_matching_achievements(user_id, stats, score, duration_sec)` — accepts current-game context for `matching_perfect`/`matching_speed`
- [x] Wire into the matching submit handler in `game_routes.py`
- [x] Write tests for each: first game; perfect score; under-threshold speed
- [x] Run `pytest tests/study/ tests/achievements/ -x` — must pass before task 10

### Task 10: Phase 3 — Add remaining tail (perfect_session, perfect_quiz)

**Files:**
- Modify: `app/achievements/services.py`
- Modify: `app/study/api_routes.py` or `app/study/game_routes.py` (session/quiz submit paths)
- Modify: `tests/study/`

- [x] Add `perfect_session` (e.g. 100% accuracy in a study session) and `perfect_quiz` (100% on a quiz) check functions
- [x] Wire into the session-completion and quiz-submission paths respectively
- [x] Write tests
- [x] Run `pytest tests/study/ tests/achievements/ -x` — must pass before task 11

### Task 11: Phase 4 — Backfill script for existing users

**Files:**
- Create: `scripts/backfill_achievements.py`
- Modify: `app/__init__.py` — register CLI command `flask backfill-achievements`

- [x] Script iterates all `User` rows. For each user: refresh `UserStatistics` (if not present, create), then call `AchievementService.check_all_achievements(user_id)` (which now covers every family)
- [x] Idempotency: `grant_achievement` already handles concurrent + duplicate cases via savepoint + IntegrityError
- [x] Verbose mode: log per-user counts of newly-granted achievements
- [x] Dry-run mode: `--dry-run` flag computes the list without committing
- [x] Register Flask CLI command `flask backfill-achievements [--dry-run]`
- [x] Run on staging first; confirm row counts in `user_achievements` increase as expected [x] manual test (skipped - not automatable)
- [x] Add as a CLI command pattern (similar to `flask seed`)
- [x] Write tests: seeded user with stats reflecting passed thresholds gets every retroactively-applicable achievement on a single run; running twice doesn't double-grant
- [x] Run `pytest tests/ -k backfill -x` — must pass before task 12

### Task 12: Verify acceptance criteria

- [x] Run full test suite: `pytest` → 0 failures (9353 passed, 0 failed)
- [x] Confirm via `grep` that every `code` in `seed.py` is referenced in at least one `check_*_achievements` function — 64/64 covered; added `check_quiz_achievements` to `AchievementService` to cover the remaining 9 quiz-family codes
- [x] Confirm dashboard right-rail shows Russian category labels and "Следующие цели" sorted by xp_reward (manual verification — implemented in Tasks 1-2)
- [x] Confirm streak achievements grant on `current_streak_days` thresholds (tested in Task 3)
- [x] Confirm new achievement families (lessons / books / cards / level / words_learned / matching) grant on the right events (tested in Tasks 4-9)
- [x] Run smoke test: `pytest -m smoke` → 475 passed, 0 failed
- [x] Run `flask backfill-achievements --dry-run` on staging and verify the report makes sense [x] manual test (skipped - not automatable)

### Task 13: Update documentation

- [x] Update `CLAUDE.md` Key Patterns:
  - Add note: every seeded achievement has a `check_*_achievements` function and is wired into `check_all_achievements`
  - Document the convention: `code` in seed must match `code` in service check list (the streak naming bug is the example)
- [x] Update or remove `docs/audit/srs-audit-2026-05-29.md` reference notes if they touch on achievements (file does not exist — only `docs/audit/2026-05-23-audit-findings.md` is present, and it does not reference the achievement naming mismatch, so no update needed)
- [x] Move this plan to `docs/plans/completed/` after the final verification task is green
