---
# Daily Plan: One Daily Slot Skip

## Overview

Corrected 2026-05-25: the skip is a "not now, do another task" action for the
current daily-plan slot. It is not a curriculum lesson deferral and it must not
move the curriculum spine forward by pretending the lesson was completed.

Correct behavior:

- One skip per user-local day.
- The user can skip only the current active daily-plan slot.
- The skipped slot remains visible and executable later the same day.
- `skipped` never counts as `completed`.
- Non-curriculum skips let the user continue to the next available daily task.
- If the skipped slot is backed by a curriculum lesson (`curriculum`,
  `listening`, `speaking`, `writing` with `data.lesson_id`), later
  curriculum-backed slots stay locked until the skipped curriculum lesson is
  actually completed.
- Book/SRS/other non-curriculum slots after the skipped curriculum lesson may
  still be done if they do not violate curriculum progression.

The previous defer-to-tomorrow design below is obsolete historical context. Do
not reintroduce `/api/daily-plan/skip-lesson`, do not use `LessonSkip` rows in
active plan assembly, and do not replace the current curriculum lesson with the
next curriculum lesson.

Active skip state is stored in `DailyPlanEvent(event_type='slot_skipped')`:

- `plan_date=user local date`
- `step_kind=<slot kind>`
- `mission_type=<stable slot key>`
- `reason_text in {'no_time', 'too_hard', 'not_today'}`

Stable slot key:

- Curriculum-backed slots: `lesson:<lesson_id>`
- Other slots: `slot:<index>:<kind>`

The stable key prevents a skipped curriculum lesson from drifting to the next
curriculum lesson after the user later completes the skipped one.

## Context

- Files involved:
  - `app/daily_plan/linear/slots/curriculum_slot.py` — build_curriculum_slot, calls find_next_lesson_linear
  - `app/daily_plan/linear/chain.py` — builds baseline and extension slots
  - `app/curriculum/navigation.py` — find_next_lesson_linear (needs exclude_lesson_ids param)
  - `app/api/daily_plan.py` — new skip-lesson endpoint
  - `app/daily_plan/models.py` — new LessonSkip model
  - `migrations/versions/` — new migration for lesson_skips table
  - `app/templates/` — daily plan template with curriculum slot rendering
- Related patterns:
  - DailyPlanEvent records behavioral events
  - find_next_lesson_linear filters spine by LessonProgress.status != 'completed'
  - get_user_local_date for user-local "today"
  - api_error() for standardized error responses
  - StreakEvent-based completion detection in build_curriculum_slot
- Dependencies: none external

## Development Approach

Historical section below describes the superseded defer-to-tomorrow
implementation. Current production behavior must follow the corrected overview
above.

- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**
- Quota constant DAILY_SKIP_QUOTA = 1 in app/daily_plan/linear/slots/curriculum_slot.py
- Double-skip guard: cannot record a new skip for a lesson already deferred until tomorrow

## Implementation Steps

### Task 1: LessonSkip model + migration

**Files:**
- Modify: `app/daily_plan/models.py`
- Create: `migrations/versions/20260524_lesson_skip.py`

- [x] Add LessonSkip model to app/daily_plan/models.py: fields id, user_id FK, lesson_id FK, skipped_on_date DATE, defer_until_date DATE, created_at DATETIME
- [x] Add UniqueConstraint(user_id, lesson_id, skipped_on_date) to prevent duplicate same-day skips for same lesson
- [x] Generate Alembic migration that creates lesson_skips table with index on (user_id, defer_until_date) for efficient daily lookup
- [x] Verify migration chain consistency (downgrade path: drop table)
- [x] Write tests: model creation, unique constraint violation
- [x] Run pytest — must pass before task 2

### Task 2: Skip helpers + curriculum slot update

**Files:**
- Modify: `app/curriculum/navigation.py`
- Modify: `app/daily_plan/linear/slots/curriculum_slot.py`

- [x] Add DAILY_SKIP_QUOTA = 1 constant near top of curriculum_slot.py
- [x] Add get_deferred_lesson_ids(user_id, today, db) -> set[int] helper: queries LessonSkip where defer_until_date > today
- [x] Add get_skips_used_today(user_id, today, db) -> int helper: counts LessonSkip rows where skipped_on_date == today
- [x] Extend find_next_lesson_linear(user_id, db, exclude_lesson_ids=None) to filter out excluded IDs from the spine query when provided
- [x] In build_curriculum_slot: call get_deferred_lesson_ids and pass result to find_next_lesson_linear as exclude_lesson_ids
- [x] In build_curriculum_slot: add skips_remaining = DAILY_SKIP_QUOTA - get_skips_used_today(...) to slot.data
- [x] In build_curriculum_slot: add skip_allowed = True/False to slot.data (False when quota exhausted or lesson already deferred)
- [x] Write tests: lesson deferred → next lesson returned; quota exhausted → skip_allowed=False in slot data
- [x] Run pytest — must pass before task 3

### Task 3: Skip lesson API endpoint

**Files:**
- Modify: `app/api/daily_plan.py`

- [x] Add POST /api/daily-plan/skip-lesson endpoint (login_required)
- [x] Accept JSON body: {lesson_id: int}
- [x] Validate lesson_id is the current curriculum lesson for this user (call find_next_lesson_linear with deferred exclusions, compare ids); return api_error('invalid_lesson', ..., 400) if mismatch
- [x] Check quota: get_skips_used_today >= DAILY_SKIP_QUOTA → api_error('skip_quota_exhausted', 'Лимит пропусков на сегодня исчерпан', 429)
- [x] Check double-skip guard: lesson already in deferred set → api_error('already_deferred', ..., 400)
- [x] Create LessonSkip(user_id, lesson_id, skipped_on_date=today, defer_until_date=today+1day)
- [x] Commit and return {success: True, skips_remaining: int, next_lesson_id: int or null}
- [x] Write tests: valid skip records row + returns 200; double call same lesson same day returns 400; third skip returns 429
- [x] Run pytest — must pass before task 4

### Task 4: Frontend skip button in daily plan UI

**Files:**
- Modify: template rendering curriculum slots in daily plan (grep 'curriculum' slot kind in app/templates/)

- [x] Find the template rendering curriculum slots in the daily plan
- [x] Add "Пропустить урок" button/link inside the curriculum slot card, visible only when skip_allowed=True in slot data
- [x] Show remaining skips count as small hint text (e.g., "доступен 1 пропуск сегодня")
- [x] On click: POST /api/daily-plan/skip-lesson with lesson_id, then reload the plan section or redirect to refresh slot state
- [x] When skip_allowed=False (quota exhausted): show disabled button with tooltip "Лимит пропусков исчерпан"
- [x] Run pytest -m smoke — must pass before task 5

### Task 5: Verify acceptance criteria

- [ ] Run full test suite: pytest
  - Attempted 2026-05-25: task-specific tests and smoke pass, but full suite has 12 unrelated failures in admin collection template, book course direct test, module content quality, robots, and share buttons.
- [x] Confirm find_next_lesson_linear still passes existing navigation tests with no regressions
- [ ] Confirm migration chain is consistent: flask db upgrade + flask db downgrade + flask db upgrade
  - `flask db heads` confirmed a single head (`20260524_lesson_skip`). Upgrade/downgrade was not run against the local DB in this pass.
- [x] Run smoke test: pytest -m smoke

### Task 6: Update documentation

- [x] Update CLAUDE.md Key Patterns section: add entry for LessonSkip / skip quota pattern
- [ ] Move this plan to docs/plans/completed/
