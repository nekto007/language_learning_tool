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

- [ ] write the exact definition of "day secured" (which mission types count, what minimum effort = secured)
- [ ] answer: does completing only easy tasks secure the day?
- [ ] answer: does minimum optimize for streak preservation or learning quality? (pick one)
- [ ] answer: is minimum fixed or adaptive per user state?
- [ ] define what rewards unlock at minimum completion and what stays exclusive to continuation
- [ ] list at least 5 edge cases and their correct behavior

### Task 3: Write 5 falsifiable hypotheses

**Files:**
- Create: `docs/decisions/2026-04-18-hypotheses.md`

- [ ] H1: "Showing 1 recommended 'next step' after minimum completion increases same-session continuation rate by ≥15%"
- [ ] H2: "Visible route progress (position + next checkpoint) increases D7 retention vs baseline with no route"
- [ ] H3: "Ghost rivals (no real user) improve continuation depth without increasing churn or stress indicators"
- [ ] H4: "An endless queue of 5+ tasks outperforms a single 'next best step' recommendation for continuation depth"
- [ ] H5: "Users who reach one checkpoint after minimum completion have 2x higher next-day return rate"
- [ ] for each hypothesis: define measurement method, sample size needed, test duration, and pass/fail threshold
- [ ] confirm that H1–H3 can be tested cheaply before H4 requires building the full endless engine

### Task 4: Define instructional validity criteria

**Files:**
- Create: `docs/decisions/2026-04-18-instructional-validity.md`

- [ ] define what "real learning" means in this system (retention score, accuracy under variation, mastery signal)
- [ ] define the difference between a "product step" (moves route, earns XP) and a "learning step" (improves retention/mastery)
- [ ] write the anti-exploit rule: route progress must be gated by learning signal, not raw task count
- [ ] define spacing quality requirements for endless mode (no same-card back-to-back, no over-reviewing familiar material)
- [ ] define transition conditions: when does a learner move from exposure to recall to transfer phases?

### Task 5: Define v1 scope and explicit deferrals

**Files:**
- Create: `docs/decisions/2026-04-18-v1-scope.md`

- [ ] in v1: "day secured" state, 1 next-best-step recommendation, basic route board (position + checkpoint), ghost rivals (adult only, opt-in)
- [ ] deferred to v2+: endless queue engine, batch generation, full rival matching, seasonal leagues, boss rounds, speed rounds, mixed-block mode
- [ ] deferred to v3+: real-time rivalry, overtake events, child vs adult product divergence
- [ ] write explicit rationale for each deferral
- [ ] confirm no v1 architecture decisions that would block the deferrals later

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

- [ ] add `day_secured` boolean field to plan payload (True when all required phases complete)
- [ ] define "secured" using the Phase 0 definition from Task 2
- [ ] add `secured_at` timestamp to `DailyPlanLog`
- [ ] expose `day_secured` in the dashboard API response
- [ ] write tests for secured=True and secured=False cases across all 3 mission types
- [ ] write tests for edge cases defined in Task 2
- [ ] run pytest — must pass before Task 7

### Task 7: Add next-best-step recommender

**Files:**
- Create: `app/daily_plan/next_step.py`
- Modify: `app/daily_plan/routes.py`

- [ ] implement `get_next_best_step(user_id, db)` returning 1 recommended task with `reason` string
- [ ] priority order: unfinished lesson > SRS due > grammar weak > reading progress > vocab
- [ ] reason must be a human-readable 1-sentence string ("You have 12 cards due" not "srs_review")
- [ ] if no good next step exists (genuinely), return None — do not force a fake step
- [ ] expose via `GET /api/daily-plan/next-step`
- [ ] write unit tests for each priority branch
- [ ] write test for None case when all sources exhausted
- [ ] run pytest — must pass

### Task 8: Add Phase 1 tracking

**Files:**
- Modify: `app/daily_plan/routes.py`

- [ ] emit event: `minimum_completed` with timestamp and mission_type
- [ ] emit event: `next_step_shown` with step_kind and reason_text
- [ ] emit event: `next_step_accepted` (user clicked it)
- [ ] emit event: `next_step_dismissed`
- [ ] emit event: `session_ended_at_minimum` (user left without continuing)
- [ ] write tests confirming events are emitted in correct states

### Task 9: Phase 1 dashboard UI

**Files:**
- Modify: `app/templates/study/` or relevant dashboard template

- [ ] show "Day secured" banner when `day_secured=True`
- [ ] show 1 next-step card below the banner with reason text and estimated time
- [ ] show "Continue later" option (dismisses next-step card without navigating away)
- [ ] keep existing minimum progress UI unchanged above the banner
- [ ] write template tests for secured state and non-secured state

### Task 10: Phase 1 go/no-go evaluation

**Files:**
- Create: `docs/decisions/2026-04-18-phase1-results.md` (fill in after 2 weeks of data)

- [ ] measure continuation rate: users who clicked next-step / users who reached day_secured
- [ ] measure session length delta vs pre-feature baseline
- [ ] measure D7 retention delta
- [ ] compare against H1 threshold (≥15% continuation lift)
- [ ] decision: proceed to Phase 2, adjust recommendation logic, or stop

---

## Phase 2: Route Board and Continuation Queue

Hypothesis being tested: H2, H5. Does visible route + checkpoint increase return rate?

Build: minimal route progress model, route board showing position and next checkpoint, 3-task continuation queue (not endless). No rivals.

Go/no-go: if D7 retention increases and users who reach a checkpoint have ≥1.5x next-day return rate, proceed to Phase 3.

### Task 11: Minimal route progress model

**Files:**
- Create: `app/daily_plan/route_progress.py`
- Create: migration file

- [ ] add `UserRouteProgress` model: user_id, total_steps, checkpoint_steps, last_updated
- [ ] one "route step" = one completed phase (weighted: learn=3, recall=2, use=2, read=2, check=1, close=1)
- [ ] checkpoint every 20 weighted steps (tunable constant)
- [ ] store current checkpoint number and steps-within-checkpoint
- [ ] add migration
- [ ] write model tests for step accumulation and checkpoint detection
- [ ] run pytest — must pass

### Task 12: Route board API

**Files:**
- Modify: `app/daily_plan/routes.py`

- [ ] add route_state to daily plan API response: `{steps_today, total_steps, checkpoint_number, steps_to_next_checkpoint, percent_to_checkpoint}`
- [ ] update route state on each phase completion
- [ ] write API tests for route state transitions

### Task 13: 3-task continuation queue

**Files:**
- Modify: `app/daily_plan/next_step.py`

- [ ] extend `get_next_best_step` to return up to 3 ordered options (primary + 2 alternatives)
- [ ] apply quality filters: no exact duplicate back-to-back, no same category twice in a row
- [ ] if < 3 good steps exist, return what's available without padding with low-quality filler
- [ ] write tests for 3-item queue and under-3 fallback

### Task 14: Route board UI

**Files:**
- Modify: relevant dashboard template

- [ ] show route position: steps completed today, checkpoint distance
- [ ] show a simple progress bar within current checkpoint stretch
- [ ] show checkpoint label when reached ("Checkpoint 3 reached!")
- [ ] show "Day secured" divider on the route (marks where minimum ended)
- [ ] show 3-task queue preview below the route
- [ ] write template tests

### Task 15: Phase 2 go/no-go evaluation

**Files:**
- Create: `docs/decisions/2026-04-18-phase2-results.md`

- [ ] measure D7 retention delta vs Phase 1 baseline
- [ ] measure next-day return rate for users who reached a checkpoint vs those who stopped before
- [ ] compare against H2 and H5 thresholds
- [ ] check for instructional validity: are users doing more retrieval or just clicking cheap steps?
- [ ] decision: proceed to Phase 3, adjust route weights, or stop

---

## Phase 3: Competition Layer (Adults Only, Opt-in, Ghost Rivals)

Hypothesis being tested: H3. Do ghost rivals improve continuation without increasing churn?

Build: rival strip for adult users only (no children), ghost rivals only (no real-user comparison in first iteration), explicit anti-shame UX.

Go/no-go: if adult continuation depth increases and churn/stress indicators do not worsen, proceed to real-rival matching. If stress indicators worsen for any segment, roll back.

### Task 16: Ghost rival model

**Files:**
- Modify: `app/achievements/daily_race.py` or create `app/daily_plan/rivals.py`

- [ ] ghost rival has a name, avatar_seed, and deterministic route_position based on date + user seed (not stored per-user)
- [ ] ghost moves at a rate slightly behind average user progression (not faster)
- [ ] ghost is labeled "Training Rival" in the UI — no pretending it is a real person
- [ ] adults only: gate by `User.birth_year` or explicit adult flag; children see no rival strip
- [ ] write tests for ghost position calculation and child-gating

### Task 17: Rival strip UI with anti-shame guardrails

**Files:**
- Modify: dashboard template

- [ ] show rival strip only when `day_secured=True` (not during minimum)
- [ ] show: "Training Rival is 3 steps ahead" — no "you're losing" framing
- [ ] never show how far behind the user is relative to a rival — only "steps to overtake"
- [ ] if user is ahead: "You're leading your Training Rival by X steps" — positive framing only
- [ ] rival strip is permanently dismissable per user
- [ ] write tests for framing logic and child-gating

### Task 18: Phase 3 tracking and go/no-go

**Files:**
- Create: `docs/decisions/2026-04-18-phase3-results.md`

- [ ] emit events: rival_strip_shown, rival_strip_dismissed, steps_taken_while_rival_visible
- [ ] measure: continuation depth for users who see rival strip vs control group without
- [ ] measure: dismissal rate (high dismissal = the feature is not wanted)
- [ ] measure: churn delta after rival introduction
- [ ] if dismissal > 30% or churn worsens: roll back rival strip
- [ ] write tests for event emission

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

- [ ] "Day secured" state is clearly visible when minimum is complete
- [ ] 1–3 meaningful continuation steps are always shown after minimum (or None if genuinely exhausted)
- [ ] Each recommended step has a human-readable reason
- [ ] Route board shows current position and next checkpoint
- [ ] Rival strip is adults-only, opt-out, ghost-only, and uses positive framing only
- [ ] No child user ever sees a rival or competition framing
- [ ] Existing lesson-safe continuation is not broken
- [ ] All 3 phase go/no-go evaluations are documented before proceeding to Phase 4

## Test Plan

- [ ] Unit tests for day_secured logic across all mission types and edge cases
- [ ] Unit tests for next_best_step priority ordering and None case
- [ ] Unit tests for route step weighting and checkpoint detection
- [ ] Unit tests for ghost rival position calculation and child-gating
- [ ] Unit tests for anti-shame framing rules
- [ ] Integration tests for plan completion -> day_secured -> route update flow
- [ ] API tests for next-step endpoint and route state endpoint
- [ ] Template tests for secured banner, route board, rival strip, and child-mode absence
- [ ] Regression tests for existing mission plan generation (must not break)
- [ ] Smoke tests: complete minimum -> see day secured -> see next step -> complete -> checkpoint shown

## Post-Completion

- [ ] Move plan to `docs/plans/completed/`
- [ ] Update CLAUDE.md with new patterns (day_secured, next_step, route_progress, ghost_rival)
- [ ] Create Phase 4 plan only after Phase 3 go/no-go evaluation
