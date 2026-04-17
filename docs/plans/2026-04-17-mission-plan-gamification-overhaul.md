# 30 Tasks: Mission Daily Plan - Gamification & UX Overhaul

## Overview

Comprehensive improvement of the mission-based daily plan: phase deduplication, visual roadmap UI, explicit task previews, title/rank system, daily-plan-specific badges, friendly races, XP progression, and gamification polish. All changes are within the existing Flask/Jinja2/PostgreSQL stack.

## Context

- Files involved: `app/daily_plan/` (models, assembler, service, mission_selector), `app/achievements/` (models, services, streak_service, seed), `app/words/routes.py` (dashboard route), `app/templates/dashboard.html`, `app/static/css/design-system.css`, `app/api/daily_plan.py`
- Related patterns: mission phases are in-memory dataclasses, completion derived from daily_summary, streak coins/events in DB, achievements seeded via seed.py
- Dependencies: none external; all within existing stack

## Development Approach

- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

---

### BLOCK 1: Phase Deduplication & Task Variety (Tasks 1-3)

### Task 1: Activity category registry

Centralize mode-to-category mapping in `app/daily_plan/models.py` so assembler, streak_service, and routes all share one source of truth. Currently `_MODE_DONE_CHECK` in streak_service.py and `_phase_url()` in routes duplicate this knowledge.

**Files:**
- Modify: `app/daily_plan/models.py`
- Modify: `app/achievements/streak_service.py` (replace `_MODE_DONE_CHECK` with import)
- Modify: `app/words/routes.py` (use registry in `_phase_url`)

- [x] Add `MODE_CATEGORY_MAP: dict[str, str]` to `models.py` mapping every mode to its activity category (words, lesson, grammar, books, book_course)
- [x] Refactor `_MODE_DONE_CHECK` in streak_service to import from registry
- [x] Refactor `_phase_url` in routes to use registry for category grouping
- [x] Write tests: verify registry covers all modes, streak_service and routes use it correctly
- [x] Run project test suite - must pass before task 2

### Task 2: Phase deduplication in assembler

Prevent two phases with the same activity category from appearing in one plan. When assembler would create a duplicate category, substitute with an alternative phase type.

**Files:**
- Modify: `app/daily_plan/assembler.py`
- Modify: `app/daily_plan/models.py` (add validation)

- [x] Add `_deduplicate_phases(phases)` function in assembler that detects same-category phases and replaces the second with a different activity
- [x] Define fallback substitution rules: if words appears twice, swap second to grammar_practice or mini_quiz; if lesson appears twice, swap to vocab_drill
- [x] Add `MissionPlan.__post_init__` validation: warn (structured log) if duplicate categories slip through
- [x] Update `assemble_repair_mission` to use deduplication before returning
- [x] Write tests: plan with would-be-duplicate produces varied categories; fallback works when primary substitute unavailable
- [x] Run project test suite - must pass before task 3

### Task 3: Mission type rotation - no same type two days in a row

Add lightweight persistence to track yesterday's mission type and bias selector away from repeating it.

**Files:**
- Modify: `app/daily_plan/mission_selector.py`
- Modify: `app/achievements/models.py` (add field to StreakEvent or new lightweight table)

- [x] Store `last_mission_type` in StreakEvent details or a new `daily_plan_log` table (one row per user per date)
- [x] If needed, create Alembic migration for the new column/table
- [x] In `select_mission()`, when repair is not triggered (pressure < 0.6), prefer a different type than yesterday's if alternatives are viable
- [x] Write tests: selector avoids yesterday's type when alternatives exist; repair still wins when pressure is high
- [x] Run project test suite - must pass before task 4

---

### BLOCK 2: Explicit Task Display & Previews (Tasks 4-7)

### Task 4: Phase preview data - show what the user will actually do

Enrich each MissionPhase with preview metadata: item count, content title, estimated minutes.

**Files:**
- Modify: `app/daily_plan/models.py` (add `preview` field to MissionPhase)
- Modify: `app/daily_plan/assembler.py` (populate preview during assembly)

- [x] Add `PhasePreview` dataclass: `item_count: int | None`, `content_title: str | None`, `estimated_minutes: int | None`
- [x] Add `preview: PhasePreview | None` field to `MissionPhase`
- [x] In each assembler function, query actual counts: SRS due count for recall, lesson title for learn, topic name for grammar, book title for read
- [x] Write tests: assembled plans contain correct preview data for each phase type
- [x] Run project test suite - must pass before task 5

### Task 5: Phase detail cards in template

Replace the current minimal phase cards with rich cards showing preview info: what exactly the user will do, how many items, estimated time.

**Files:**
- Modify: `app/templates/dashboard.html` (phase card section)
- Modify: `app/words/routes.py` (pass preview data to template)
- Modify: `app/daily_plan/service.py` (serialize preview in `_mission_plan_to_dict`)

- [x] Serialize `PhasePreview` in `_mission_plan_to_dict`
- [x] Pass preview data through dashboard route context
- [x] Update phase card template: show item count badge, content title, estimated time chip
- [x] Add "What you'll do" subtitle text per phase type (e.g., "Review 12 words", "Lesson: Present Perfect")
- [x] Write tests: API returns preview data; dashboard renders preview elements
- [x] Run project test suite - must pass before task 6

### Task 6: Phase-specific icons and color coding

Give each phase kind a distinct color and icon set instead of current monochrome numbered cards.

**Files:**
- Modify: `app/templates/dashboard.html` (icon/color mapping)
- Modify: `app/static/css/design-system.css` (phase color classes)

- [x] Define color palette per PhaseKind: recall=blue, learn=green, use=purple, read=amber, check=orange, close=gold
- [x] Add CSS classes `dash-step--recall`, `dash-step--learn`, etc. with accent colors, left border, icon background
- [x] Replace emoji-only icons with SVG or CSS-drawn icons for each phase
- [x] Write tests: template renders correct CSS class per phase type
- [x] Run project test suite - must pass before task 7

### Task 7: Animated phase transitions

Add micro-animations when phases complete: checkmark animation, progress bar fill, next phase highlight pulse.

**Files:**
- Modify: `app/static/css/design-system.css` (animations)
- Modify: `app/templates/dashboard.html` (JS for dynamic updates)

- [x] Add CSS keyframes: `phase-complete` (scale+fade checkmark), `phase-activate` (pulse glow on current), `progress-fill` (smooth width transition)
- [x] Add JS on dashboard: when returning from a phase (`?from=daily_plan`), detect newly completed phase and trigger animation
- [x] Completed phases slide up slightly and dim; current phase expands
- [x] Write tests: CSS classes and data attributes are present for animation hooks
- [x] Run project test suite - must pass before task 8

---

### BLOCK 3: Visual Roadmap UI (Tasks 8-11)

### Task 8: Roadmap layout - path with connected nodes

Replace the current vertical card list with a visual "learning path" roadmap: nodes connected by lines/curves, showing a journey from start to finish.

**Files:**
- Modify: `app/templates/dashboard.html` (new roadmap HTML structure)
- Modify: `app/static/css/design-system.css` (roadmap CSS)

- [x] Create `dash-roadmap` container with `dash-roadmap__node` elements connected by `dash-roadmap__connector` lines
- [x] Each node is circular/hexagonal, showing phase icon and number
- [x] Connectors are CSS-drawn (border/pseudo-element) lines between nodes
- [x] Layout: alternating left-right zigzag pattern on mobile, horizontal on desktop
- [x] Write tests: roadmap HTML structure renders correct number of nodes matching phases
- [x] Run project test suite - must pass before task 9

### Task 9: Roadmap node states

Each node has visual states: completed (filled, green, checkmark), current (pulsing, enlarged, glowing), upcoming (dimmed, locked appearance), bonus (sparkle effect for optional phases).

**Files:**
- Modify: `app/static/css/design-system.css` (node state styles)
- Modify: `app/templates/dashboard.html` (state classes)

- [x] CSS classes: `dash-roadmap__node--done`, `--current`, `--upcoming`, `--bonus`
- [x] Done nodes: solid fill, checkmark overlay, completed connector turns solid
- [x] Current node: 1.2x scale, box-shadow glow, subtle pulse animation
- [x] Upcoming nodes: gray fill, dashed connector, slightly transparent
- [x] Optional/bonus phases get sparkle border (dashed gold)
- [x] Write tests: node state classes match phase completion status
- [x] Run project test suite - must pass before task 10

### Task 10: Roadmap start and finish markers

Add decorative start flag and finish line markers at the beginning and end of the roadmap. Finish marker changes appearance when all phases complete.

**Files:**
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/css/design-system.css`

- [x] Add start marker node (flag icon) before first phase
- [x] Add finish marker node (trophy icon) after last phase
- [x] When all done: finish node bursts with confetti-style CSS animation, trophy turns gold
- [x] When not all done: finish node shows target with distance ("2 steps to go")
- [x] Write tests: start/finish markers render; finish state changes when all_done
- [x] Run project test suite - must pass before task 11

### Task 11: Mobile-responsive roadmap

Ensure roadmap looks good and is usable on mobile screens (primary use case).

**Files:**
- Modify: `app/static/css/design-system.css` (media queries)

- [x] Mobile (< 640px): vertical serpentine layout, nodes are 48px circles, full-width info cards expand on tap
- [x] Tablet (640-1024px): horizontal scroll with snap points
- [x] Desktop (> 1024px): horizontal layout, all nodes visible
- [x] Touch targets minimum 44px; swipe hint on mobile for horizontal layouts
- [x] Write tests: CSS media query breakpoints exist for roadmap classes
- [x] Run project test suite - must pass before task 12

---

### BLOCK 4: Title & Rank System (Tasks 12-15)

### Task 12: Title/rank model and migration

Create a rank system where users earn titles based on cumulative daily plan completions (e.g., "Novice" -> "Explorer" -> "Scholar" -> "Master" -> "Legend").

**Files:**
- Create: `app/achievements/ranks.py`
- Modify: `app/achievements/models.py` (add rank fields to UserStatistics)
- Create: Alembic migration

- [x] Define `RANK_THRESHOLDS` list: [(0, "Novice"), (7, "Explorer"), (21, "Student"), (50, "Expert"), (100, "Master"), (200, "Legend"), (365, "Grandmaster")]
- [x] Add `plans_completed_total` and `current_rank` columns to UserStatistics
- [x] Create `get_user_rank(plans_completed)` function returning rank name, next rank threshold, progress percentage
- [x] Create Alembic migration
- [x] Write tests: rank calculation at each threshold boundary, edge cases (0, exact threshold, between thresholds)
- [x] Run project test suite - must pass before task 13

### Task 13: Rank progression logic

Increment plan completion counter when all required phases are done. Detect rank-ups and create notification.

**Files:**
- Modify: `app/achievements/streak_service.py` (hook into daily completion)
- Modify: `app/achievements/ranks.py` (rank-up detection)
- Modify: `app/notifications/services.py` (rank-up notification)

- [x] In `earn_daily_coin()` (or a new `record_plan_completion()`), increment `plans_completed_total` and check for rank-up
- [x] `check_rank_up(user_id)`: compare old rank vs new rank, return rank-up info if changed
- [x] On rank-up: create notification "You earned the title: {rank_name}!"
- [x] Write tests: completing a plan increments counter; crossing threshold triggers rank-up; notification created
- [x] Run project test suite - must pass before task 14

### Task 14: Rank display on dashboard

Show current rank badge on the dashboard header near the user's name/avatar area.

**Files:**
- Modify: `app/templates/dashboard.html` (rank badge)
- Modify: `app/words/routes.py` (pass rank data)
- Modify: `app/static/css/design-system.css` (rank badge styles)

- [x] Add rank badge component: colored pill with rank icon and title
- [x] Show rank progress bar: "14/21 days to next rank"
- [x] Each rank has a unique color and icon
- [x] Write tests: dashboard renders rank badge with correct rank name; progress shows correct numbers
- [x] Run project test suite - must pass before task 15

### Task 15: Rank history and profile display

Show rank progression history and current rank on the user's profile/stats page.

**Files:**
- Modify: `app/achievements/ranks.py` (rank history query)
- Modify: relevant profile template
- Modify: `app/static/css/design-system.css`

- [x] Query StreakEvents to reconstruct rank-up dates
- [x] Show timeline of rank achievements with dates
- [x] Current rank displayed prominently with days-at-rank counter
- [x] Write tests: rank history returns correct progression; profile template renders rank section
- [x] Run project test suite - must pass before task 16

---

### BLOCK 5: Daily Plan Badges (Tasks 16-19)

### Task 16: Mission-specific badge definitions

Add new achievements specifically for daily plan missions: first mission complete, 5 progress missions, 5 repair missions, 5 reading missions, perfect week (7 days), early bird (before 9am), night owl (after 10pm).

**Files:**
- Modify: `app/achievements/seed.py` (new badge definitions)
- Create: Alembic migration (if needed for new seed data)

- [x] Add badge definitions: `mission_first`, `mission_progress_5`, `mission_repair_5`, `mission_reading_5`, `mission_week_perfect`, `mission_early_bird`, `mission_night_owl`, `mission_variety_3` (all 3 types in one week), `mission_speed_demon` (all phases done in < 30 min)
- [x] Each badge has: code, name (Russian), description, icon, points, category='mission'
- [x] Write seed migration or update existing seed function
- [x] Write tests: all new badges are seeded correctly with unique codes
- [x] Run project test suite - must pass before task 17

### Task 17: Mission badge check logic

Implement checking logic that evaluates whether mission-specific badges should be awarded after plan completion.

**Files:**
- Modify: `app/achievements/services.py` (new check method)
- Modify: `app/achievements/streak_service.py` (call badge check on completion)

- [x] Add `check_mission_achievements(user_id, mission_type, completion_time)` method
- [x] Check first completion, type counts, perfect week, time-of-day badges
- [x] For speed_demon: compare first and last phase completion timestamps
- [x] For variety: query last 7 days of mission types
- [x] Hook into plan completion flow in streak_service
- [x] Write tests: each badge condition triggers correctly; no double-award
- [x] Run project test suite - must pass before task 18

### Task 18: Badge award animation on dashboard

When user returns to dashboard after earning a new badge, show a celebratory popup/toast.

**Files:**
- Modify: `app/templates/dashboard.html` (badge popup)
- Modify: `app/words/routes.py` (detect new badges)
- Modify: `app/static/css/design-system.css` (popup styles)

- [x] Track `unseen_badges` - badges awarded since last dashboard visit
- [x] Render badge popup: icon, name, description, points earned, dismiss button
- [x] CSS animation: slide-in from top, gold shimmer border, auto-dismiss after 5s
- [x] Mark badges as seen after display
- [x] Write tests: unseen badges detected; popup HTML rendered when badges exist; seen badges not re-shown
- [x] Run project test suite - must pass before task 19

### Task 19: Badge showcase on dashboard

Add a badges section to the dashboard showing recently earned badges and total badge count with a "View all" link.

**Files:**
- Modify: `app/templates/dashboard.html` (badges showcase section)
- Modify: `app/words/routes.py` (query recent badges)
- Modify: `app/static/css/design-system.css`

- [x] Add `dash-badges` section after the roadmap: last 3-5 badges as circular icons
- [x] Show total count: "12 of 35 badges earned"
- [x] Unearned badges shown as grayed-out silhouettes (teaser)
- [x] "View all badges" link to full achievements page
- [x] Write tests: badges section renders with correct count; recent badges display
- [x] Run project test suite - must pass before task 20

---

### BLOCK 6: Friendly Races (Tasks 20-23)

### Task 20: Daily race model

Create a lightweight daily race system where users are matched into small groups (3-5) and compete on daily plan points.

**Files:**
- Create: `app/achievements/daily_race.py` (model + service)
- Modify: `app/achievements/models.py` (or new file for race models)
- Create: Alembic migration

- [x] `DailyRace` model: id, race_date, created_at
- [x] `DailyRaceParticipant` model: race_id, user_id, points (default 0), finished_at, rank
- [x] Points use existing `_MISSION_PHASE_POINTS` from words/routes.py
- [x] Index on (user_id, race_date) for fast lookups
- [x] Write tests: models create correctly; unique constraint per user per date
- [x] Run project test suite - must pass before task 21

### Task 21: Race matchmaking

Match users into daily race groups based on similar streak length and activity level. Run matchmaking when a user first visits their dashboard each day.

**Files:**
- Modify: `app/achievements/daily_race.py` (matchmaking logic)

- [x] `get_or_create_race(user_id, date)`: if user already in a race today, return it; otherwise find/create a race with open slots
- [x] Matchmaking criteria: similar streak_days range (+-10), similar plans_completed range (+-20); if no match found, create new race
- [x] Race capacity: 3-5 participants
- [x] If fewer than 3 humans available, fill with "ghost" participants (bot names with typical point patterns)
- [x] Write tests: matchmaking creates races, respects capacity, fills with ghosts, returns existing race on second call
- [x] Run project test suite - must pass before task 22

### Task 22: Race progress tracking

Update race points in real-time as users complete phases. Show live standings.

**Files:**
- Modify: `app/achievements/daily_race.py` (point updates)
- Modify: `app/achievements/streak_service.py` (hook point updates)
- Modify: `app/api/daily_plan.py` (race status endpoint)

- [x] `update_race_points(user_id, date, points)`: update participant points
- [x] Hook into phase completion detection: when `compute_plan_steps` detects a newly done phase, award points
- [x] Ghost participants accumulate points gradually throughout the day (calculated, not stored)
- [x] API endpoint `GET /api/daily-race`: return current race standings
- [x] Write tests: points update correctly; ghost points are time-based; API returns standings
- [x] Run project test suite - must pass before task 23

### Task 23: Race display on dashboard

Show the race widget on the dashboard: mini leaderboard with 3-5 participants, user's position highlighted.

**Files:**
- Modify: `app/templates/dashboard.html` (race widget)
- Modify: `app/words/routes.py` (pass race data)
- Modify: `app/static/css/design-system.css` (race widget styles)

- [x] `dash-race` widget: compact leaderboard showing avatar/initials, name, points, position
- [x] Current user row highlighted with accent color
- [x] Position indicators: 1st=gold, 2nd=silver, 3rd=bronze
- [x] When race complete (all participants finished or day ends): show final results with "You placed Nth!" message
- [x] Motivational nudge: "You're 8 points behind 1st - complete the next phase to catch up!"
- [x] Write tests: race widget renders with correct participant count; user highlighted; position badges correct
- [x] Run project test suite - must pass before task 24

---

### BLOCK 7: XP & Daily Progression (Tasks 24-27)

### Task 24: XP system model

Add an XP (experience points) system tied to daily plan activities. XP accumulates and drives level progression independently from streak.

**Files:**
- Modify: `app/achievements/models.py` (add XP fields to UserStatistics)
- Create: `app/achievements/xp_service.py`
- Create: Alembic migration

- [ ] Add `total_xp`, `current_level` columns to UserStatistics
- [ ] Define XP awards: phase completion (by type), perfect day bonus (all phases), streak multiplier (1.0 + streak_days * 0.02, max 2.0), first-of-day bonus
- [ ] Define level thresholds: exponential curve (level N requires N*100 XP from previous level)
- [ ] `award_xp(user_id, amount, source)` function with multiplier application
- [ ] `get_level_info(total_xp)` returning current level, XP in level, XP to next level, percentage
- [ ] Write tests: XP awards calculate correctly with multipliers; level thresholds correct; edge cases at level boundaries
- [ ] Run project test suite - must pass before task 25

### Task 25: XP award integration

Hook XP awards into phase completion and daily plan finish events.

**Files:**
- Modify: `app/achievements/xp_service.py`
- Modify: `app/achievements/streak_service.py` (call XP on completion)

- [ ] On phase completion: award XP based on phase type (recall=15, learn=40, use=35, read=30, check=25, close=10)
- [ ] On all-phases-done: bonus 50 XP ("Perfect day")
- [ ] Apply streak multiplier to all awards
- [ ] Detect level-up, create notification
- [ ] Write tests: XP awarded on phase completion; bonus on full completion; level-up detected; multiplier applied
- [ ] Run project test suite - must pass before task 26

### Task 26: XP and level display on dashboard

Show XP bar, current level, and XP gains on the dashboard.

**Files:**
- Modify: `app/templates/dashboard.html` (XP widget)
- Modify: `app/words/routes.py` (pass XP data)
- Modify: `app/static/css/design-system.css`

- [ ] `dash-xp` widget near top of dashboard: level badge, XP progress bar, "Level 14 - 340/500 XP"
- [ ] XP gain indicators on completed phase cards: "+40 XP" floating text
- [ ] Streak multiplier displayed: "x1.28 streak bonus active"
- [ ] Level-up celebration: golden flash overlay when user levels up
- [ ] Write tests: XP widget renders with correct level and progress; gain indicators appear on completed phases
- [ ] Run project test suite - must pass before task 27

### Task 27: Daily bonus and perfect day mechanics

Reward daily consistency with escalating bonuses: consecutive perfect days multiply XP and unlock special badges.

**Files:**
- Modify: `app/achievements/xp_service.py` (bonus logic)
- Modify: `app/achievements/streak_service.py` (track perfect days)

- [ ] Track `consecutive_perfect_days` in StreakEvent details or UserStatistics
- [ ] Bonus XP: 2 perfect days = 1.2x, 3 = 1.5x, 5 = 2.0x, 7+ = 2.5x (on top of streak multiplier)
- [ ] Show "Perfect day streak: 4 days! Tomorrow: 2.0x bonus" on completion banner
- [ ] Missing one day resets perfect streak but not the regular streak
- [ ] Write tests: perfect day counter increments; bonus multipliers correct; reset on missed day; stacks with streak multiplier
- [ ] Run project test suite - must pass before task 28

---

### BLOCK 8: Gamification Polish & Extras (Tasks 28-30)

### Task 28: Daily surprise/bonus phase

Randomly (20% chance) append a bonus "surprise" phase to the plan: could be a mini-game, a fun fact quiz, or a review challenge with extra XP.

**Files:**
- Modify: `app/daily_plan/assembler.py` (bonus phase logic)
- Modify: `app/daily_plan/models.py` (add bonus phase kinds)

- [ ] Add `PhaseKind.bonus` value
- [ ] Add bonus modes: `fun_fact_quiz`, `speed_review`, `word_scramble`
- [ ] In each assembler, after building main phases, roll 20% chance to append bonus phase (required=False)
- [ ] Bonus phase awards 2x XP if completed
- [ ] Visual indicator: sparkle/star marker on the roadmap node
- [ ] Write tests: bonus phase appears ~20% of time (test with seeded random); bonus is never required; correct modes assigned
- [ ] Run project test suite - must pass before task 29

### Task 29: Mission completion summary screen

After completing all phases, show a rich summary: XP earned, badges unlocked, race position, rank progress, streak status - all in one celebratory view.

**Files:**
- Modify: `app/templates/dashboard.html` (completion summary)
- Modify: `app/words/routes.py` (compile summary data)
- Modify: `app/static/css/design-system.css`

- [ ] `dash-completion-summary` section replacing the current simple "All done" banner
- [ ] Show: total XP earned today, new badges (if any), race position, rank progress bar, streak flame with day count
- [ ] Animated entrance: cards flip in one by one
- [ ] "Share" button generating a shareable image/text of today's results
- [ ] Motivational closing message varying by mission type and performance
- [ ] Write tests: summary renders with correct XP total; badges section shows when badges earned; race position displayed
- [ ] Run project test suite - must pass before task 30

### Task 30: Weekly progress digest widget

Show a weekly overview widget on the dashboard: which days had completed plans, total XP for the week, mission type distribution, and weekly challenge progress.

**Files:**
- Modify: `app/templates/dashboard.html` (weekly digest widget)
- Modify: `app/words/routes.py` (query weekly data)
- Modify: `app/achievements/weekly_challenge.py` (integrate with mission data)
- Modify: `app/static/css/design-system.css`

- [ ] `dash-weekly` widget: 7-day grid (Mon-Sun) with colored dots per day (green=complete, yellow=partial, gray=missed)
- [ ] Weekly XP total with comparison to previous week: "+120 XP vs last week"
- [ ] Mission type pie/bar: how many progress/repair/reading missions this week
- [ ] Weekly challenge progress bar integrated into the widget
- [ ] Write tests: weekly widget renders correct day states; XP comparison calculates correctly; mission type counts match
- [ ] Run project test suite - must pass before final verification


### BLOCK 9: Route Board, Rivals, and Lesson-Safe Flow (Tasks 33-36)

### Task 33: Replace step list with a route board metaphor

Reframe the daily plan as a route made of checkpoints instead of a flat list of cards. The user should feel they are moving along a path, not just clicking through isolated tasks.

**Files:**
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/css/design-system.css`
- Modify: `app/words/routes.py`

- [ ] Introduce a `dash-route` container that renders the mission plan as a connected route with start, checkpoints, and finish
- [ ] Map mission phases to route checkpoints: `recall`, `learn`, `use`, `check`, optional `close`
- [ ] Define route progress weights per phase (for example: recall 15, learn 40, use 30, check 15) so the route supports partial movement, not only discrete step jumps
- [ ] Preserve existing completion logic, but render it through route semantics rather than stacked cards
- [ ] Add route metadata to the dashboard context: total checkpoints, current checkpoint index, finish state
- [ ] Add a compact fallback layout for low-density mode (single-column mobile route, no horizontal overflow for MVP)
- [ ] Write tests: dashboard renders route container and correct number of checkpoints for a mission plan
- [ ] Run project test suite - must pass before task 34

### Task 34: Add rival tokens to the route

Show the user token and the nearest rival tokens directly on the route so progress feels spatial. Do not show a full leaderboard-only abstraction as the primary UI.

**Files:**
- Modify: `app/words/routes.py` (route-position payload)
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/css/design-system.css`

- [ ] Extend `daily_race` payload with route-relative positions, not just rank/score
- [ ] Add `route_position` (0-100 scale) for the current user and each rival based on completed phases plus partial progress inside the active phase
- [ ] Show the current user token plus the nearest rivals on the route itself
- [ ] Only render nearby rivals on the track: one ahead, one behind, optional leader marker
- [ ] Use the route itself as the primary race UI; keep the leaderboard secondary and compact
- [ ] Keep bot rivals only as fallback for low-population/testing scenarios, clearly labeled as training
- [ ] Write tests: route payload includes route positions; dashboard renders user token and rival tokens
- [ ] Run project test suite - must pass before task 35

### Task 35: Overtake and checkpoint animations

Make route movement legible and satisfying. Completing a checkpoint should move the user token forward and visually indicate overtakes without adding noisy effects.

**Files:**
- Modify: `app/static/css/design-system.css`
- Modify: `app/templates/dashboard.html`

- [ ] Add token movement animation for checkpoint completion
- [ ] Add overtaking animation when the user passes a rival token
- [ ] Add checkpoint activation/completion animation for current and newly completed route points
- [ ] Add explicit "checkpoint reached" and "overtake achieved" states that can be triggered after return from a plan step (`?from=daily_plan`)
- [ ] Add finish-state animation that is calmer than full-screen celebration and fits both kids and adults
- [ ] Write tests: dashboard includes animation hook classes/data attributes for route movement and overtakes
- [ ] Run project test suite - must pass before task 36

### Task 36: Do not interrupt a started lesson with daily limits

If the user has already entered a lesson through the daily plan, the lesson must be finishable. Global daily new-card limits may gate entry to new free SRS, but must not break an already started lesson flow.

**Files:**
- Modify: `app/curriculum/routes/card_lessons.py`
- Modify: `app/templates/components/_flashcard_session.html`
- Modify: `app/study/api_routes.py`
- Modify: `app/static/js/flashcard-session.js`

- [ ] Define a lesson-safe grading mode for card lessons that bypasses global new-card blocking once the lesson has started
- [ ] Ensure lesson card sessions pass an explicit flag to grading/fetch APIs so they are not treated like generic free-study SRS
- [ ] Keep daily limits for general SRS entry points (`Разогрев серии`, free study, deck study) intact
- [ ] Add frontend handling so lesson sessions never show misleading session-expired copy for limit responses
- [ ] Add a product rule in mission assembly: if `Главный шаг миссии` resolves to a card-based lesson, either collapse the separate recall phase or relabel it so the user does not experience two visually identical card blocks in a row
- [ ] Write tests: started lesson can continue past daily new-card threshold; generic free-study still stops at the threshold
- [ ] Run project test suite - must pass before final verification

---

### Task 37: Verify acceptance criteria

- [ ] Run full test suite: `pytest`
- [ ] Run smoke tests: `pytest -m smoke`
- [ ] Verify test coverage meets 80%+ for new files
- [ ] Verify no duplicate activity categories in any assembled mission plan
- [ ] Verify roadmap renders correctly in dashboard template tests

### Task 38: Update documentation

- [ ] Update CLAUDE.md: add daily plan gamification patterns (XP, ranks, races, badges)
- [ ] Update CLAUDE.md: document new models (DailyRace, rank fields, XP fields)
- [ ] Move this plan to `docs/plans/completed/`

---