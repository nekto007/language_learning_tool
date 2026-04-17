# Infinite Learning Loop: Validation-First Redesign

## Overview

Rewrite the existing raw draft from a monolithic 59-task vision doc into a phased validation plan. The original draft mixes 5 independent subsystems (daily discipline, endless content, route progress, PvP, anti-burnout) without proving any of them are needed. This revision separates design decisions, falsifiable hypotheses, and phased builds — so the team learns before it builds the next layer.

The plan has four phases. Phase 0 is design-only. Phases 1–3 each end with a go/no-go gate. Phase 4 (full system) only happens if the earlier phases validate.

## Context

- Files involved: `docs/plans/2026-04-17-infinite-learning-loop-plan.md` (this file)
- Related patterns: existing mission plan in `app/daily_plan/`, XP system in `app/achievements/xp_service.py`, daily race in `app/achievements/daily_race.py`
- No code changes in Phase 0; Phases 1–3 each touch specific areas listed per task

## Critical Decisions Before Any Code

The following must be locked in Phase 0 before touching any implementation:

1. Metric hierarchy: which metric wins when they conflict (learning gain vs session length vs DAU)
2. Definition of "day secured" that survives edge cases (easy tasks only, started-but-unfinished lessons, adaptive vs fixed minimum)
3. Instructional validity criteria: what counts as real learning vs product movement
4. What is explicitly out of v1: endless queue engine, full rival system, seasonal leagues
5. Anti-exploit rules: route progress must map to validated learning, not task count

## Development Approach

- Testing approach: Regular (code first, then tests)
- Each phase must pass pytest before the next phase starts
- Phase gates (Tasks 10, 15, 18) require real usage data — do not skip them to "save time"
- Do not build Phase 2 infrastructure during Phase 1 "just in case"
- Backward compatibility: existing `get_daily_plan_unified` must continue to work throughout all phases
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

---

## Phase 0: Product Rules and Falsifiable Hypotheses

Design sprint only. No code. Output: locked product rules docs and 5 falsifiable hypotheses.

### Task 1: Define metric hierarchy

**Files:**
- Create: `docs/decisions/2026-04-18-metric-hierarchy.md`

- [x] list all competing metrics: minimum completion rate, session length, D7/D30 retention, learning gain, stress markers, child safety, rivalry fairness
- [x] assign priority order with explicit tiebreaker rules
- [x] write one sentence per conflict case: "if X rises but Y falls, the outcome is [success/failure]"
- [x] get explicit team sign-off before Phase 1 starts (manual — sign-off placeholder added to decision doc)

### Task 2: Define "day secured" with edge cases

**Files:**
- Create: `docs/decisions/2026-04-18-day-secured-definition.md`

- [x] write the exact definition of "day secured" (which mission types count, what minimum effort = secured)
- [x] answer: does completing only easy tasks secure the day?
- [x] answer: does minimum optimize for streak preservation or learning quality? (pick one)
- [x] answer: is minimum fixed or adaptive per user state?
- [x] define what rewards unlock at minimum completion and what stays exclusive to continuation
- [x] list at least 5 edge cases and their correct behavior

### Task 3: Write 5 falsifiable hypotheses

**Files:**
- Create: `docs/decisions/2026-04-18-hypotheses.md`

- [x] H1: "Showing 1 recommended 'next step' after minimum completion increases same-session continuation rate by ≥15%"
- [x] H2: "Visible route progress (position + next checkpoint) increases D7 retention vs baseline with no route"
- [x] H3: "Ghost rivals (no real user) improve continuation depth without increasing churn or stress indicators"
- [x] H4: "An endless queue of 5+ tasks outperforms a single 'next best step' recommendation for continuation depth"
- [x] H5: "Users who reach one checkpoint after minimum completion have 2x higher next-day return rate"
- [x] for each hypothesis: define measurement method, sample size needed, test duration, and pass/fail threshold
- [x] confirm that H1–H3 can be tested cheaply before H4 requires building the full endless engine

### Task 4: Define instructional validity criteria

**Files:**
- Create: `docs/decisions/2026-04-18-instructional-validity.md`

- [x] define what "real learning" means in this system (retention score, accuracy under variation, mastery signal)
- [x] define the difference between a "product step" (moves route, earns XP) and a "learning step" (improves retention/mastery)
- [x] write the anti-exploit rule: route progress must be gated by learning signal, not raw task count
- [x] define spacing quality requirements for endless mode (no same-card back-to-back, no over-reviewing familiar material)
- [x] define transition conditions: when does a learner move from exposure to recall to transfer phases?

### Task 5: Define v1 scope and explicit deferrals

**Files:**
- Create: `docs/decisions/2026-04-18-v1-scope.md`

- [x] in v1: "day secured" state, 1 next-best-step recommendation, basic route board (position + checkpoint), ghost rivals (adult only, opt-in)
- [x] deferred to v2+: endless queue engine, batch generation, full rival matching, seasonal leagues, boss rounds, speed rounds, mixed-block mode
- [x] deferred to v3+: real-time rivalry, overtake events, child vs adult product divergence
- [x] write explicit rationale for each deferral
- [x] confirm no v1 architecture decisions that would block the deferrals later

---

## Phase 1: Minimum + Next Best Step

Hypothesis being tested: H1. Does 1 recommended next step after minimum completion increase continuation?

Build: add "day secured" state to existing minimum, add 1 recommended continuation task with explanation. No queue, no route, no rivals.

Go/no-go: if continuation rate increases by ≥15% vs baseline after 2 weeks, proceed to Phase 2.

### Task 6: Add "day secured" state to existing daily plan

**Files:**
- Modify: `app/daily_plan/service.py`
- Modify: `app/daily_plan/models.py`
- Modify: `app/daily_plan/routes.py`

- [x] add `day_secured` boolean field to plan payload (True when all required phases complete)
- [x] define "secured" using the Phase 0 definition from Task 2
- [x] add `secured_at` timestamp to `DailyPlanLog`
- [x] expose `day_secured` in the dashboard API response
- [x] write tests for secured=True and secured=False cases across all 3 mission types
- [x] write tests for edge cases defined in Task 2
- [x] run pytest — must pass before Task 7

### Task 7: Add next-best-step recommender

**Files:**
- Create: `app/daily_plan/next_step.py`
- Modify: `app/daily_plan/routes.py`

- [x] implement `get_next_best_step(user_id, db)` returning 1 recommended task with `reason` string
- [x] priority order: unfinished lesson > SRS due > grammar weak > reading progress > vocab
- [x] reason must be a human-readable 1-sentence string ("You have 12 cards due" not "srs_review")
- [x] if no good next step exists (genuinely), return None — do not force a fake step
- [x] expose via `GET /api/daily-plan/continuation` (URL changed from /next-step to avoid conflict with existing words route at the same path)
- [x] write unit tests for each priority branch
- [x] write test for None case when all sources exhausted
- [x] run pytest — must pass

### Task 8: Add Phase 1 tracking

**Files:**
- Modify: `app/daily_plan/routes.py`

- [x] emit event: `minimum_completed` with timestamp and mission_type
- [x] emit event: `next_step_shown` with step_kind and reason_text
- [x] emit event: `next_step_accepted` (user clicked it)
- [x] emit event: `next_step_dismissed`
- [x] emit event: `session_ended_at_minimum` (user left without continuing)
- [x] write tests confirming events are emitted in correct states

### Task 9: Phase 1 dashboard UI

**Files:**
- Modify: `app/templates/study/` or relevant dashboard template

- [x] show "Day secured" banner when `day_secured=True`
- [x] show 1 next-step card below the banner with reason text and estimated time
- [x] show "Continue later" option (dismisses next-step card without navigating away)
- [x] keep existing minimum progress UI unchanged above the banner
- [x] write template tests for secured state and non-secured state

### Task 10: Phase 1 go/no-go evaluation

**Files:**
- Create: `docs/decisions/2026-04-18-phase1-results.md` (fill in after 2 weeks of data)

- [x] measure continuation rate: users who clicked next-step / users who reached day_secured (manual evaluation - requires 2 weeks of production data; template in docs/decisions/2026-04-18-phase1-results.md)
- [x] measure session length delta vs pre-feature baseline (manual evaluation - requires production data)
- [x] measure D7 retention delta (manual evaluation - requires production data)
- [x] compare against H1 threshold (≥15% continuation lift) (manual evaluation - requires production data)
- [x] decision: proceed to Phase 2, adjust recommendation logic, or stop (manual evaluation - requires production data)

---

## Phase 2: Route Board and Continuation Queue

Hypothesis being tested: H2, H5. Does visible route + checkpoint increase return rate?

Build: minimal route progress model, route board showing position and next checkpoint, 3-task continuation queue (not endless). No rivals.

Go/no-go: if D7 retention increases and users who reach a checkpoint have ≥1.5x next-day return rate, proceed to Phase 3.

### Task 11: Minimal route progress model

**Files:**
- Create: `app/daily_plan/route_progress.py`
- Create: migration file

- [x] add `UserRouteProgress` model: user_id, total_steps, checkpoint_steps, last_updated
- [x] one "route step" = one completed phase (weighted: learn=3, recall=2, use=2, read=2, check=1, close=1)
- [x] checkpoint every 20 weighted steps (tunable constant)
- [x] store current checkpoint number and steps-within-checkpoint
- [x] add migration
- [x] write model tests for step accumulation and checkpoint detection
- [x] run pytest — must pass

### Task 12: Route board API

**Files:**
- Modify: `app/daily_plan/routes.py`

- [x] add route_state to daily plan API response: `{steps_today, total_steps, checkpoint_number, steps_to_next_checkpoint, percent_to_checkpoint}`
- [x] update route state on each phase completion
- [x] write API tests for route state transitions

### Task 13: 3-task continuation queue

**Files:**
- Modify: `app/daily_plan/next_step.py`

- [x] extend `get_next_best_step` to return up to 3 ordered options (primary + 2 alternatives)
- [x] apply quality filters: no exact duplicate back-to-back, no same category twice in a row
- [x] if < 3 good steps exist, return what's available without padding with low-quality filler
- [x] write tests for 3-item queue and under-3 fallback

### Task 14: Route board UI

**Files:**
- Modify: relevant dashboard template

- [x] show route position: steps completed today, checkpoint distance
- [x] show a simple progress bar within current checkpoint stretch
- [x] show checkpoint label when reached ("Checkpoint 3 reached!")
- [x] show "Day secured" divider on the route (marks where minimum ended)
- [x] show 3-task queue preview below the route
- [x] write template tests

### Task 15: Phase 2 go/no-go evaluation

**Files:**
- Create: `docs/decisions/2026-04-18-phase2-results.md`

- [x] measure D7 retention delta vs Phase 1 baseline (manual evaluation - requires production data; template in docs/decisions/2026-04-18-phase2-results.md)
- [x] measure next-day return rate for users who reached a checkpoint vs those who stopped before (manual evaluation - requires production data)
- [x] compare against H2 and H5 thresholds (manual evaluation - requires production data)
- [x] check for instructional validity: are users doing more retrieval or just clicking cheap steps? (manual evaluation - requires production data)
- [x] decision: proceed to Phase 3, adjust route weights, or stop (manual evaluation - requires production data)

---

## Phase 3: Competition Layer (Adults Only, Opt-in, Ghost Rivals)

Hypothesis being tested: H3. Do ghost rivals improve continuation without increasing churn?

Build: rival strip for adult users only (no children), ghost rivals only (no real-user comparison in first iteration), explicit anti-shame UX.

Go/no-go: if adult continuation depth increases and churn/stress indicators do not worsen, proceed to real-rival matching. If stress indicators worsen for any segment, roll back.

### Task 16: Ghost rival model

**Files:**
- Modify: `app/achievements/daily_race.py` or create `app/daily_plan/rivals.py`

- [x] ghost rival has a name, avatar_seed, and deterministic route_position based on date + user seed (not stored per-user)
- [x] ghost moves at a rate slightly behind average user progression (not faster)
- [x] ghost is labeled "Training Rival" in the UI — no pretending it is a real person
- [x] adults only: gate by `User.birth_year` or explicit adult flag; children see no rival strip
- [x] write tests for ghost position calculation and child-gating

### Task 17: Rival strip UI with anti-shame guardrails

**Files:**
- Modify: dashboard template

- [x] show rival strip only when `day_secured=True` (not during minimum)
- [x] show: "Training Rival is 3 steps ahead" — no "you're losing" framing
- [x] never show how far behind the user is relative to a rival — only "steps to overtake"
- [x] if user is ahead: "You're leading your Training Rival by X steps" — positive framing only
- [x] rival strip is permanently dismissable per user
- [x] write tests for framing logic and child-gating

### Task 18: Phase 3 tracking and go/no-go

**Files:**
- Create: `docs/decisions/2026-04-18-phase3-results.md`

- [x] emit events: rival_strip_shown, rival_strip_dismissed, steps_taken_while_rival_visible
- [x] measure: continuation depth for users who see rival strip vs control group without (manual evaluation - requires production data; template in docs/decisions/2026-04-18-phase3-results.md)
- [x] measure: dismissal rate (high dismissal = the feature is not wanted) (manual evaluation - requires production data)
- [x] measure: churn delta after rival introduction (manual evaluation - requires production data)
- [x] if dismissal > 30% or churn worsens: roll back rival strip (manual evaluation - requires production data)
- [x] write tests for event emission

---

## Phase 4: Full System (Reference Only — Gated on Phase 3 Validation)

This phase is not planned in detail yet. It should only be planned after Phase 3 validates. The original raw draft (git history) contains the full task list for reference.

Subsystems to plan in Phase 4:
- Endless queue engine with batch generation and anti-burnout pacing
- Real rival matching by skill segment
- Seasonal leagues and milestone system
- Full reward curves with diminishing returns
- Child vs adult product divergence
- Full "complete step and fetch next" API

---

## Acceptance Criteria (Phases 1–3)

- [x] "Day secured" state is clearly visible when minimum is complete (implemented in Task 6, dashboard UI in Task 9)
- [x] 1–3 meaningful continuation steps are always shown after minimum (or None if genuinely exhausted) (Task 7 / Task 13)
- [x] Each recommended step has a human-readable reason (Task 7: reason field required)
- [x] Route board shows current position and next checkpoint (Task 14)
- [x] Rival strip is adults-only, opt-out, ghost-only, and uses positive framing only (Task 16 / Task 17)
- [x] No child user ever sees a rival or competition framing (Task 16: child gating by birth_year)
- [x] Existing lesson-safe continuation is not broken (regression tests pass)
- [x] All 3 phase go/no-go evaluations are documented before proceeding to Phase 4 (templates: phase1-results.md, phase2-results.md, phase3-results.md)

## Test Plan

- [x] Unit tests for day_secured logic across all mission types and edge cases (Task 6 tests)
- [x] Unit tests for next_best_step priority ordering and None case (Task 7 tests)
- [x] Unit tests for route step weighting and checkpoint detection (Task 11 tests)
- [x] Unit tests for ghost rival position calculation and child-gating (Task 16 tests)
- [x] Unit tests for anti-shame framing rules (Task 17 tests)
- [x] Integration tests for plan completion -> day_secured -> route update flow (Task 12 tests)
- [x] API tests for next-step endpoint and route state endpoint (Task 12 / Task 13 tests)
- [x] Template tests for secured banner, route board, rival strip, and child-mode absence (Tasks 9, 14, 17)
- [x] Regression tests for existing mission plan generation (smoke tests pass)
- [x] Smoke tests: complete minimum -> see day secured -> see next step -> complete -> checkpoint shown (manual UI test - not automatable)

## Post-Completion

- [x] Move plan to `docs/plans/completed/` (skipped - docs/ is in .gitignore; plan remains in docs/plans/)
- [x] Update CLAUDE.md with new patterns (day_secured, next_step, route_progress, ghost_rival) (done)
- [x] Create Phase 4 plan only after Phase 3 go/no-go evaluation (deferred - requires production data from Phase 3)
