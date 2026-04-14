# Daily Plan Learning Redesign: Mission-First Daily Experience

## Overview

Replace the resource-centric daily plan (5 parallel sections: lesson/grammar/words/books/book_course_practice) with a mission-first model where each day has exactly 1 mission type (Progress/Repair/Reading), 1 primary source, and 3-4 sequential phases.

The current `get_daily_plan_v2()` in `app/telegram/queries.py` builds a flat state machine of 5 independent steps. The new system selects a single mission intent, maps it to canonical learning phases (Recall/Learn/Use/Check), and renders one coherent session instead of a feature showcase.

## Context

- Current daily plan logic: `app/telegram/queries.py` lines 567-1156 (`get_daily_plan_v2()`)
- Current API: `app/api/daily_plan.py` (4 endpoints: daily-status, daily-plan, daily-summary, streak)
- Dashboard route: `app/words/routes.py` lines 149-410
- Dashboard template: `app/templates/dashboard.html` lines 114-397 (step rendering)
- Next-step JS: `app/static/js/daily-plan-next.js` (206 lines)
- Streak integration: `app/achievements/streak_service.py` (`compute_plan_steps()`, `process_streak_on_activity()`)
- No feature flag system exists; only module enablement via `app/modules/service.py`
- Related patterns: dashboard widgets use `_safe_widget_call()` wrapper

## Development Approach

- **Testing approach**: TDD for domain model and selector; regular tests for UI/integration
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: feature-flagged via user setting, old payload preserved in `legacy` block**
- **CRITICAL: fallback to legacy plan when mission cannot be built safely**

## Implementation Steps

### Task 1: Create daily_plan module with domain model

Establish the new `app/daily_plan/` package with pure data classes for mission types, phases, and payload structure. No business logic yet - just the domain vocabulary.

**Files:**
- Create: `app/daily_plan/__init__.py`
- Create: `app/daily_plan/models.py`
- Create: `tests/test_daily_mission_models.py`

- [x] Define `MissionType` enum: `progress`, `repair`, `reading`
- [x] Define `PhaseKind` enum: `recall`, `learn`, `use`, `read`, `check`, `close`
- [x] Define `SourceKind` enum: `normal_course`, `book_course`, `books`, `srs`, `grammar_lab`, `vocab`
- [x] Define `MissionPhase` dataclass: id, phase (PhaseKind), title, source_kind, mode, required, completed
- [x] Define `Mission` dataclass: type, title, reason_code, reason_text
- [x] Define `PrimaryGoal` dataclass: type, title, success_criterion
- [x] Define `PrimarySource` dataclass: kind (SourceKind), id, label
- [x] Define `MissionPlan` dataclass: plan_version, mission, primary_goal, primary_source, phases (list, 3-4), completion, legacy (dict)
- [x] Add validation: MissionPlan enforces 3-4 phases, exactly 1 mission/goal/source
- [x] Write tests for all dataclasses, validation rules, and edge cases (empty phases, >4 phases)
- [x] Run project test suite - must pass before task 2

### Task 2: Add feature flag for mission-based plan

Add a user-level flag to toggle between legacy plan and mission plan. Use existing `User` model preference pattern.

**Files:**
- Modify: `app/models.py` (User model)
- Create: `alembic/versions/xxxx_add_use_mission_plan.py` (migration)
- Create: `tests/test_mission_feature_flag.py`

- [x] Add `use_mission_plan = Column(Boolean, default=False, server_default='false')` to User model
- [x] Create Alembic migration for the new column
- [x] Verify migration chain consistency
- [x] Write tests: flag defaults to False, can be toggled, respects per-user setting
- [x] Run project test suite - must pass before task 3

### Task 3: Implement repair pressure calculator

Build the repair pressure scoring that determines when a Repair mission should override the user's primary track. Pure function, no side effects.

**Files:**
- Create: `app/daily_plan/repair_pressure.py`
- Create: `tests/test_repair_pressure.py`

- [x] Implement `calculate_repair_pressure(user_id, tz)` returning a pressure score (0.0-1.0) and breakdown
- [x] Input signals: overdue SRS count vs threshold, active grammar weak points, recent failure cluster count
- [x] Define `REPAIR_THRESHOLD` constant (e.g. 0.6) above which Repair mission triggers
- [x] Query overdue SRS items from existing SRS tables
- [x] Query grammar weak points from grammar progress tables
- [x] Write tests with mocked DB data: no pressure, moderate pressure, high pressure, edge cases
- [x] Run project test suite - must pass before task 4

### Task 4: Implement mission selector

Rule-based selector that chooses mission type based on user's primary track and repair pressure. Core decision engine.

**Files:**
- Create: `app/daily_plan/mission_selector.py`
- Create: `tests/test_mission_selector.py`

- [x] Implement `detect_primary_track(user_id)` -> SourceKind (normal_course / book_course / books/reading) based on user's active enrollments and progress
- [x] Implement `select_mission(user_id, tz)` -> (MissionType, reason_code, reason_text)
- [x] Selection priority: (1) if repair pressure >= threshold -> Repair; (2) if primary_track is reading -> Reading; (3) else -> Progress
- [x] Add negative conditions: skip mission type if no safe Use phase or no buildable Recall phase for it
- [x] Add stability rule: don't switch Progress mission source within same day (cache or check existing today's plan)
- [x] Cold start handling: default to Progress from default track or simplest Reading
- [x] Write tests for all 3 mission types, priority ordering, cold start, negative conditions
- [x] Run project test suite - must pass before task 5

### Task 5: Build mission assembler (phase builder per mission type)

For each mission type, assemble concrete phases by querying existing content sources and mapping them to canonical learning blocks.

**Files:**
- Create: `app/daily_plan/assembler.py`
- Create: `tests/test_mission_assembler.py`

- [x] Implement `assemble_progress_mission(user_id, primary_source, tz)` -> MissionPlan
  - Recall phase: SRS due items or guided vocab recall
  - Learn phase: next lesson from normal_course or book_course
  - Use phase: applied block from course (practice/quiz items)
  - Check phase (optional): micro-check from course
- [x] Implement `assemble_repair_mission(user_id, repair_breakdown, tz)` -> MissionPlan
  - Recall phase: overdue SRS items
  - Learn phase: target weak grammar point
  - Use phase: targeted quiz
  - Close phase: short success marker
- [x] Implement `assemble_reading_mission(user_id, tz)` -> MissionPlan
  - Recall phase: prior scene/chapter vocabulary
  - Read phase: next reading segment from books
  - Use phase: extract/use vocabulary from reading
  - Check phase (optional): meaning prompt
- [x] Each assembler validates MissionPlan constraints (3-4 phases, single source)
- [x] Add fallback helpers: guided recall when free recall items unavailable, soft close when check source unsafe
- [x] Write tests for each mission type assembly, fallback scenarios, validation failures
- [x] Run project test suite - must pass before task 6

### Task 6: Build mission plan service (orchestrator)

Top-level service that ties selector + assembler + fallback into a single `get_mission_plan()` call.

**Files:**
- Create: `app/daily_plan/service.py`
- Create: `tests/test_daily_mission_service.py`

- [x] Implement `get_mission_plan(user_id, tz)` -> dict (JSON-serializable mission payload)
  - Calls `select_mission()` to pick mission type
  - Calls appropriate `assemble_*_mission()` to build phases
  - Converts MissionPlan to dict matching the v1 payload schema from the product doc
  - Includes `legacy` block with backward-compatible flat keys (next_lesson, grammar_topic, words_due, etc.)
- [x] Implement fallback: if assembly fails or produces invalid plan, return legacy plan from `get_daily_plan_v2()`
- [x] Implement `get_daily_plan_unified(user_id, tz)` that checks `user.use_mission_plan` flag:
  - If True: call `get_mission_plan()`
  - If False: call existing `get_daily_plan_v2()`
- [x] Write tests: happy path for each mission type, fallback on assembly failure, flag routing
- [x] Run project test suite - must pass before task 7

### Task 7: Integrate mission plan into API and dashboard route

Wire the new mission plan service into existing API endpoints and dashboard route, behind the feature flag.

**Files:**
- Modify: `app/api/daily_plan.py`
- Modify: `app/words/routes.py` (dashboard route, next-step endpoint)
- Create: `tests/test_daily_mission_api.py`

- [x] In `app/api/daily_plan.py`: modify `/daily-status` and `/daily-plan` endpoints to call `get_daily_plan_unified()` instead of `get_daily_plan_v2()`
- [x] In `app/words/routes.py`: modify `dashboard()` route to call `get_daily_plan_unified()` and pass mission data to template
- [x] Modify `daily_plan_next_step()` to work with mission phases when flag is on (map phase completion to next phase)
- [x] Ensure `compute_plan_steps()` in streak_service works with both old steps dict and new mission phases
- [x] Write integration tests: API returns mission payload when flag on, legacy payload when flag off
- [x] Run project test suite - must pass before task 8

### Task 8: Build mission-based dashboard UI

Replace the resource checklist in dashboard template with mission-first rendering when flag is active.

**Files:**
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/js/daily-plan-next.js`
- Modify: `app/static/css/design-system.css` (minimal additions for mission UI)
- Create: `tests/test_dashboard_mission_render.py`

- [x] Add conditional block in dashboard.html: if mission plan present, render mission UI; else render legacy steps
- [x] Mission UI shows: mission title + reason line, 3-4 phase cards (sequential, not parallel), one active CTA (current phase), completion statement when done
- [x] Phase cards: show phase title and status (pending/active/completed), hide internal content-type names (no "dialogue_completion_quiz" etc.)
- [x] Update daily-plan-next.js to handle phase-based progression (next phase instead of next step type)
- [x] Motivational wording: no exam/punishment language, check = gentle close, repair = supportive framing
- [x] Write template render tests: mission elements present when flag on, legacy elements when flag off, phase states render correctly
- [x] Run project test suite - must pass before task 9

### Task 9: Update Telegram bot plan formatting

Adapt Telegram bot daily plan display to mission format when flag is active.

**Files:**
- Modify: `app/telegram/queries.py`
- Modify: `app/telegram/bot.py` or relevant handler file
- Create: `tests/test_telegram_mission_format.py`

- [ ] Add `get_daily_plan_for_telegram(user_id, tz)` that returns formatted mission text when flag on, legacy format when off
- [ ] Mission format for Telegram: mission title, reason, numbered phases with status emoji, completion status
- [ ] Ensure backward compatibility: old Telegram message format unchanged when flag off
- [ ] Write tests for both flag states, all 3 mission types formatted correctly
- [ ] Run project test suite - must pass before task 10

### Task 10: Verify acceptance criteria

- [ ] Run full test suite: `pytest`
- [ ] Run smoke tests: `pytest -m smoke`
- [ ] Verify: each daily plan has exactly 1 mission, 1 primary source, 3-4 phases (when flag on)
- [ ] Verify: user does not see site sections as peer-level daily blocks
- [ ] Verify: Progress mission does not mix normal_course + book_course + books
- [ ] Verify: SRS is not identity of the day outside Repair mission
- [ ] Verify: Books do not appear as "another block" inside Progress mission
- [ ] Verify: fallback to legacy plan works when mission cannot be built
- [ ] Verify: old consumers get backward-compatible fields via legacy block
- [ ] Verify: feature flag correctly routes between old and new plan

### Task 11: Update documentation

- [ ] Update CLAUDE.md if daily_plan module introduces new patterns
- [ ] Document mission types, selector rules, and payload schema in code docstrings
- [ ] Move this plan to `docs/plans/completed/`
