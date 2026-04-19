# 19 Tasks: Dashboard Compact Redesign & Block Restructure

## Overview

Comprehensive restructure of the dashboard page. The current layout mixes three parallel progression systems (today XP / mission level / rank), four redundant progress indicators on the mission plan, and eight full-width sections that push primary actions below the fold. This plan collapses duplicates, moves secondary data to dedicated pages, and leaves a focused "daily ritual + plan + social context" dashboard. All changes stay within the existing Flask/Jinja2/SQLAlchemy stack.

## Context

- Files involved: `app/templates/dashboard.html` (main template + inline `<style>` block 1819–5473), `app/static/css/design-system.css`, `app/words/routes.py` (dashboard route, widget loaders), `app/daily_plan/service.py` (plan payload), `app/study/routes.py` (stats/insights pages), `app/achievements/` (daily_race, streak_service), `tests/test_dashboard_mission_render.py`, `tests/test_dashboard_routes.py`
- Related patterns: dashboard widgets loaded via `_safe_widget_call()` in `app/words/routes.py`, plan rendering branches by `mission_plan` presence vs legacy, `dash-*` CSS classes, `MODE_CATEGORY_MAP` in `app/daily_plan/models.py`
- Dependencies: none external; all within existing stack
- Feature flags: `User.use_mission_plan` (keep legacy branch untouched)

## Development Approach

- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**
- No changes to legacy (`use_mission_plan=false`) branch — it stays as-is until separate deprecation

## Implementation Steps

---

### BLOCK 1: Compact Hero + Zero-state + Gamification Moves (Tasks 1-4)

### Task 1: Compact hero layout

Collapse the current sprawling hero (greeting + streak + yesterday + today-XP + rank + bg-shapes) into a focused "daily ritual" card: greeting + streak + CTA, nothing else. Max-width ~720px, centered, one light gradient instead of two decorative shapes. `yesterday`, `today_xp`, `rank`, `mission_level_info` are removed from hero (their moves/deletions handled in later tasks).

**Files:**
- Modify: `app/templates/dashboard.html` (hero section lines 44–159)
- Modify: `app/templates/dashboard.html` (inline CSS for `.dash-hero*`, `.dash-shape*`)

- [x] Reduce `.dash-hero` to `max-width: 720px`, `margin: 0 auto`, single linear-gradient background (remove `dash-shape--1/--2` shapes entirely, keep `.dash-hero__bg` as subtle gradient layer)
- [x] Remove `dash-yesterday` block from hero markup
- [x] Remove `dash-xp-bar` block from hero markup (today_xp daily goal bar — replaced by mission XP widget that moves into plan card)
- [x] Remove `dash-rank` block from hero markup (moves to Social section) — temporarily rendered standalone below hero so existing rank tests keep passing until Task 13 folds it into Social
- [x] Ensure greeting title + streak render on one visual row (flex layout: greeting left, streak right)
- [x] Write tests: `test_hero_compact_layout_renders` — assert hero contains greeting + streak only, no yesterday/xp-bar/rank markers
- [x] Run project test suite — must pass before task 2 (file-only tests pass; DB-bound render tests require Postgres not available locally — rely on CI)

### Task 2: Hero streak — 3 states + flash overlay

Simplify the 5-branch streak conditional (`streak_repaired`, `can_repair && streak>0`, `can_repair && streak==0`, `streak>0`, else) into 3 clean states. Move `streak_repaired` celebration to a flash overlay reusing the `dash-xp-levelup` mechanism.

**Files:**
- Modify: `app/templates/dashboard.html` (streak conditional block)
- Modify: `app/templates/dashboard.html` (inline CSS for `.dash-streak*`, add `.dash-streak-flash` overlay)
- Modify: `app/static/js/` (add auto-dismiss for streak flash if not already handled by level-up JS)

- [x] Replace 5 branches with 3: (a) `streak > 0` → fire + days + coins, (b) `can_repair && streak == 0` → recovery block, (c) `streak == 0` → "Сегодня начни заново" message
- [x] Remove contradictory branch `can_repair && streak > 0`
- [x] Show `share-button` whenever `streak >= 7` (not only on milestone days). Keep `milestone-badge` only on milestone hit (7/14/30/60/100)
- [x] Move `streak_repaired` rendering out of hero inline into a fixed-position flash overlay (`dash-streak-flash`), auto-dismiss after 2500 ms, reuse `dash-xp-levelup` animation
- [x] Write tests: rendering matrix for (streak=0, streak=1, streak=7, streak=14, can_repair states, repaired state) — assert correct blocks/classes present
- [x] Run project test suite — must pass before task 3 (file-only tests pass; DB-bound render tests require Postgres not available locally — rely on CI)

### Task 3: Hero CTA with 6 scenarios

Add a single-line CTA below the streak that points the user to their next action. Resolves to 6 different states based on plan progress and daily budget.

**Files:**
- Modify: `app/templates/dashboard.html` (hero: add CTA block)
- Modify: `app/words/routes.py` (route: compute `hero_cta` dict with `title`, `url`, `kind`)
- Modify: `app/daily_plan/service.py` (helper: resolve next phase + review budget availability)

- [x] Add `_resolve_hero_cta(user, mission_plan, plan_completion, settings)` helper returning `{kind: 'start'|'continue'|'extra'|'done'|'fallback'|'onboarding', title: str, url: str|None}`
- [x] CTA rules: plan not started → `Начать: {first_phase.title}` → phase URL; mid-plan → `Продолжить: {next_phase.title}` → phase URL; done + remaining review budget + due cards → `Ещё тренировка: Карточки →` → `/study/cards?from=daily_plan`; done otherwise → `🏁 План готов — до завтра!` (no link); mission_plan missing (legacy/fallback) → `Открыть план →` (anchor `#dash-plan`); zero-state → handled by Task 4 (not via CTA)
- [x] "Remaining review budget + due cards" check: reuse `_get_remaining_card_budget()` (added in 2026-04-19 daily-plan fix) + `_count_srs_due()`
- [x] Render CTA as `<a class="dash-hero__cta">` or `<span>` (static for `done`-no-link case)
- [x] Write tests: assert correct CTA rendered for each of the 6 scenarios; verify URL targets
- [x] Run project test suite — must pass before task 4 (file-only CTA tests pass; DB-bound render tests require Postgres not available locally — rely on CI)

### Task 4: Zero-state = fullscreen welcome

When the user has zero activity across the board, hide the entire normal dashboard and render only the welcome card fullscreen-style. Currently welcome-card shows AFTER the hero, duplicating the "start learning" signal.

**Files:**
- Modify: `app/templates/dashboard.html` (top-level guard around hero + sections + welcome)
- Modify: `app/templates/dashboard.html` (inline CSS for `.dash-welcome--fullscreen`)

- [x] Compute `is_zero_state = (words_total == 0 and grammar_studied == 0 and books_reading == 0 and courses_enrolled == 0)` in the route (or template)
- [x] When `is_zero_state`: render only `.dash-welcome--fullscreen` card (no hero, no race, no plan, no sections). Card centered vertically, larger icon, CTA to onboarding/catalog
- [x] When not `is_zero_state`: hide the welcome card entirely (hero CTA handles non-zero resumption)
- [x] Write tests: zero-state user renders only welcome markup; non-zero user renders hero + sections; welcome-card never appears in non-zero state
- [x] Run project test suite — must pass before task 5 (file-only tests pass; DB-bound render tests require Postgres not available locally — rely on CI)

---

### BLOCK 2: Daily Plan Simplification (Tasks 5-9)

### Task 5: Single progress indicator = roadmap only

Remove 3 of the 4 redundant progress indicators on the mission plan. The visual roadmap (nodes + connectors + start/finish markers + route-tokens) becomes the single source of progress truth.

**Files:**
- Modify: `app/templates/dashboard.html` (mission plan progress bar lines ~362–381; roadmap finish-marker label lines ~622–628; route-board lines ~716–765)
- Modify: `app/templates/dashboard.html` (inline CSS: cleanup `.dash-roadmap__marker-distance` if unused)

- [x] Remove the linear `0/3` progress-bar block rendered above phase cards
- [x] Remove the `.dash-roadmap__marker-distance` span showing "{N} шагов до финиша" on the finish marker (keep the marker icon itself)
- [x] Remove the Route board checkpoint bar + "day secured" marker + "checkpoint reached" label on dashboard (will live in `/study/stats` per Task 16)
- [x] Keep: roadmap track (nodes + connectors + start/finish markers), route-tokens (rivals positions), swipe-hint
- [x] Write tests: assert only one progress indicator container in rendered dashboard (no `dash-plan__progress-bar`, no `dash-roadmap__marker-distance`, no `dash-route-board`)
- [x] Run project test suite — must pass before task 6 (file-only tests pass; DB-bound render tests require Postgres not available locally — rely on CI)

### Task 6: Mission header simplification

Strip the mission header of redundant copy (eyebrow + reason). Keep title + track-badge + goal-badge only.

**Files:**
- Modify: `app/templates/dashboard.html` (mission header lines ~323–361)

- [x] Remove `.dash-mission__eyebrow` ("ГЛАВНАЯ МИССИЯ ДНЯ")
- [x] Remove the `m.reason_text` line (duplicates title wording)
- [x] Keep: `m.title`, track-badge (source kind label), goal-badge (primary_goal.title)
- [x] Tighten spacing to match compact hero style
- [x] Write tests: assert eyebrow and reason_text not present in rendered plan header; title + both badges present
- [x] Run project test suite — must pass before task 7 (file-only tests pass; DB-bound render tests require Postgres not available locally — rely on CI)

### Task 7: Move Mission XP widget into plan card

The standalone `dash-xp` widget that lives right after the hero moves inside the plan card, directly under the mission header, full-width. Its semantics (mission-based XP, level, streak multiplier) belong in the plan context.

**Files:**
- Modify: `app/templates/dashboard.html` (remove widget at lines ~160–176, insert new position inside plan card)
- Modify: `app/templates/dashboard.html` (inline CSS: adapt `.dash-xp` styles for in-card layout)

- [x] Remove `.dash-xp` block from current position (below hero, above welcome)
- [x] Render new `.dash-mission__xp` block inside `.dash-plan` after the header row, before phase cards / roadmap
- [x] Layout: level (left) + XP progress bar (center, flex-grow) + multiplier (right). Full width of plan card
- [x] Keep existing `data-xp-*` hooks so `xp_level_up` JS animation still targets it
- [x] Remove `.dash-xp-levelup` overlay positioning tied to hero; keep the overlay itself centered on viewport
- [x] Write tests: assert XP widget renders inside `.dash-plan`, not above it; level-up overlay still present on `xp_level_up` flag
- [x] Run project test suite — must pass before task 8 (file-only tests pass; DB-bound render tests require Postgres not available locally — rely on CI)

### Task 8: Remove stale plan banners

Delete three banner/strip blocks that overlap the hero CTA + roadmap signal: day-secured banner, 3-step continuation queue, ghost rival strip.

**Files:**
- Modify: `app/templates/dashboard.html` (day-secured + 3-step queue lines ~767–790; ghost rival strip lines ~791–808)
- Modify: `app/words/routes.py` (stop computing `rival_strip` payload unless still used elsewhere)

- [x] Remove `.dash-day-secured` banner and its surrounding `{% if m_day_secured %}` block
- [x] Remove the 3-task continuation queue block (populated by `/api/daily-plan/continuation`)
- [x] Remove the ghost rival strip block (`rival_strip` template variable)
- [x] If `rival_strip` is not used anywhere else, remove its computation from `app/words/routes.py` dashboard route
- [x] Leave `/api/daily-plan/continuation` endpoint untouched for now (may have other consumers); only drop its frontend rendering
- [x] Write tests: assert these markers do not appear regardless of `m_day_secured`, `continuation_queue`, `rival_strip` values
- [x] Run project test suite — must pass before task 9 (file-only tests pass; DB-bound render tests require Postgres not available locally — rely on CI)

### Task 9: Completion summary — verify preserved

No code changes; this task is a sanity check that Task 8 did not accidentally remove the `completion_summary` block (which stays rendered when `m_all_done`).

**Files:**
- Read-only verification: `app/templates/dashboard.html` (completion summary lines ~383–501)

- [x] Manual verification: completion summary renders when `m_all_done = true` (verified by file-level assertions on template structure + existing runtime tests in `tests/test_dashboard_completion_summary.py::TestCompletionSummaryTemplate::test_summary_present_when_all_done` / `test_summary_absent_when_not_all_done`)
- [x] Write tests: assert `completion_summary` block renders on all-done plan; does not render on partial plan (added `TestCompletionSummaryPreserved` file-level tests in `tests/test_dashboard_mission_render.py` verifying the template guard, markup, card variants, share button, fallback elif, and block ordering are intact after Task 8)
- [x] Run project test suite — must pass before task 10 (new 6 file-only tests pass locally; DB-bound runtime tests require Postgres not available locally — rely on CI)

---

### BLOCK 3: Activity / Attention / Progress Compact (Tasks 10-12)

### Task 10: Activity block compact + yesterday summary moved in

Shrink the Activity heatmap to 30 days, collapse streak stats to one line, and add the `yesterday_summary` (moved from hero) as a thin line above the heatmap.

**Files:**
- Modify: `app/templates/dashboard.html` (activity section lines ~1373–1452)
- Modify: `app/templates/dashboard.html` (inline CSS for `.dash-heatmap*`)
- Modify: `app/words/routes.py` (heatmap builder: limit to last 30 days instead of 90)

- [x] Add `yesterday_summary` rendering at the top of the Activity section as a one-liner: "Вчера: N уроков · M слов · X/Y грамматика" (hide block entirely when `has_activity == false`)
- [x] Reduce heatmap to 30 days: update route's heatmap query + pad computation + month label logic
- [x] Collapse streak stats from 3 cards to one line: `🔥 текущая: N · лучшая: M · всего активных: K`
- [x] Write tests: yesterday-summary renders when present, hides when no activity; heatmap has ≤ 30 cells + pad; streak stats one-line markup
- [x] Run project test suite — must pass before task 11 (file-only tests pass; DB-bound render tests require Postgres not available locally — rely on CI)

### Task 11: Alerts → accordion collapsed by default

Wrap the words-at-risk + grammar-weaknesses block in `<details>` summary that shows counts. Expanded body keeps existing list rendering. Hide block entirely when both lists empty.

**Files:**
- Modify: `app/templates/dashboard.html` (alerts section lines ~1454–1506)
- Modify: `app/templates/dashboard.html` (inline CSS: `.dash-alerts__accordion` styles)

- [x] Wrap contents in `<details class="dash-alerts__accordion">` (no `open` attribute — collapsed by default)
- [x] `<summary>`: `⚠️ {N} слов под угрозой · {M} слабые темы` (localized plural forms). Use existing `words_at_risk|length` and `grammar_weaknesses|length`
- [x] When both collections empty: do not render the section at all (remove current `dash-empty` fallback — positive silence is fine; no need for "отличная работа" message)
- [x] Write tests: both-empty renders nothing; non-empty renders collapsed details with correct count summary; existing list markup preserved inside (added `tests/test_dashboard_alerts_accordion.py` with 10 file-only tests covering both-empty, singular/few/many plurals, separator, inner markup preservation, and collapsed default)
- [x] Run project test suite — must pass before task 12 (file-only tests pass; DB-bound render tests require Postgres not available locally — rely on CI)

### Task 12: Progress overview only — remove Grammar Levels

Remove the Grammar Levels breakdown (A0–C2 progress bars) from dashboard; keep the 4-card Progress Overview with `onboarding_focus` reordering.

**Files:**
- Modify: `app/templates/dashboard.html` (progress section lines ~1562–1646)
- Modify: `app/words/routes.py` (stop computing `grammar_levels_summary` widget for dashboard; keep function if used in `/grammar_lab`)

- [x] Remove `.dash-grammar-levels` markup entirely from dashboard
- [x] Keep `.dash-progress-overview` 4-card grid with reordering
- [x] Remove `grammar_levels_summary` from dashboard route render context (keep the widget function itself if used on `/grammar_lab` page)
- [x] Write tests: dashboard does not render `.dash-grammar-levels`; 4-card overview renders with correct ordering for each `onboarding_focus` value (added `tests/test_dashboard_progress_overview.py` with 11 file-level tests covering removed markup, removed context key, removed template classes, and ordering for default/grammar/reading/vocabulary/unknown focus)
- [x] Run project test suite — must pass before task 13 (new 11 file-only tests pass; DB-bound render tests require Postgres not available locally — rely on CI)

---

### BLOCK 4: Social 3-col + Race split + Removed sections (Tasks 13-16)

### Task 13: Social section — 3-column layout with Rank

Rebuild the Social section as 3 columns: Rank card (moved from hero) | XP Leaderboard | Achievements. On mobile stack to single column.

**Files:**
- Modify: `app/templates/dashboard.html` (social section lines ~1648–1728)
- Modify: `app/templates/dashboard.html` (inline CSS for `.dash-social-row`, `.dash-rank*` in new context)

- [ ] Move `.dash-rank` markup from hero removal (Task 1) into Social as first column. Enlarge: show icon + display_name + `plans_completed/next_threshold` + progress bar (for max rank: "Максимальный титул")
- [ ] Restructure `.dash-social-row` to 3 equal columns (CSS grid: `grid-template-columns: 1fr 1fr 1fr`)
- [ ] Mobile (<= 768px): stack columns vertically with full width
- [ ] Keep existing XP leaderboard and Achievements markup intact inside their columns
- [ ] Write tests: social row has 3 children (rank, leaderboard, achievements) when data present; rank card renders in social, not in hero
- [ ] Run project test suite — must pass before task 14

### Task 14: Daily race → compact strip + /race page

Replace the large daily-race section on dashboard with a compact strip, and create a dedicated `/race` page that holds the full race UX (3-tasks, nudge, leaderboard, rivals above/below, finished state).

**Files:**
- Create: `app/templates/race/today.html` (full race page)
- Create: route in `app/achievements/daily_race_routes.py` or reuse existing blueprint
- Modify: `app/templates/dashboard.html` (race section lines ~200–298 → compact strip)
- Modify: `app/words/routes.py` (dashboard route: no longer needs rival_above/rival_below/etc. full payload; a lean version is sufficient)

- [ ] Create `GET /race` route returning `today.html` with full race payload (same shape as current `daily_race` dict)
- [ ] Move the 3-tasks block, nudge callout, full `.dash-race__board` leaderboard, rival_above/below tasks, CTA button to `/race/today.html`
- [ ] On dashboard, render compact strip only: `🏁 Место {rank}/{total} · {score} очк · Подробнее →` linking to `/race`. Use existing `dash-race__badge` color classes for the place number
- [ ] Finished state: compact strip shows `🏆 {rank}-е место · {score} очк · Итоги →` linking to `/race` (page shows summary message inside)
- [ ] Route-tokens on the roadmap stay (positional rivals). No changes to `dash-route-tokens`
- [ ] Write tests: dashboard renders compact strip when `daily_race` present; `/race` page renders 3-tasks + full leaderboard; finished race strip shows rank + score
- [ ] Run project test suite — must pass before task 15

### Task 15: Remove Stats / Insights / Quick Actions sections from dashboard

Delete three sections that now live on dedicated pages or are redundant with in-block CTAs.

**Files:**
- Modify: `app/templates/dashboard.html` (Stats section lines ~1507–1561; Insights section lines ~1730–1796; Quick Actions section lines ~1798–1816)
- Modify: `app/templates/dashboard.html` (inline CSS: remove styles for `.dash-study-time*`, `.dash-week-stats*`, `.dash-reading-speed*`, `.dash-sparkline*`, `.dash-milestones*`, `.dash-quick*` if unused elsewhere)
- Modify: `app/words/routes.py` (stop computing widgets only used by these sections)

- [ ] Delete Section 5 (Stats: Best Study Time + This Week's Stats). Add one link at the bottom of Activity section: `Подробная статистика →` → `/study/stats`
- [ ] Delete Section 8 (Insights: Reading Speed + Streak Milestones). Add one link near Social or Progress: `Аналитика обучения →` → `/study/insights`
- [ ] Delete Section 9 (Quick Actions) entirely
- [ ] Remove `best_study_time`, `session_stats`, `reading_speed_trend`, `milestone_history` widget calls from `app/words/routes.py` dashboard route (keep the widget functions themselves — they'll be called by `/study/stats` and `/study/insights`)
- [ ] Write tests: dashboard does not render `.dash-study-time`, `.dash-week-stats`, `.dash-reading-speed`, `.dash-milestones`, `.dash-quick`; links to stats/insights pages present
- [ ] Run project test suite — must pass before task 16

### Task 16: Enrich /study/stats and /study/insights with moved blocks

The blocks removed from dashboard in Task 15 + Task 5 need a home. Add them to `/study/stats` and `/study/insights` routes.

**Files:**
- Modify: `app/templates/study/stats.html` (add sections)
- Modify: `app/templates/study/insights.html` (add sections)
- Modify: `app/study/routes.py` (stats + insights views: populate new widget data)

- [ ] `/study/stats`: add Best Study Time chart, This Week's Stats card grid, Route Board Checkpoint bar (long-term H5 progress). Reuse existing CSS classes from dashboard inline CSS (move to `design-system.css` or page-local stylesheet)
- [ ] `/study/insights`: add Reading Speed sparkline + delta, Streak Milestones timeline (7/14/30/60/100 days)
- [ ] Widget data: call the same widget functions (`stats_service.get_best_study_time`, etc.) previously used on dashboard
- [ ] Ensure each page is accessible via `_external` URL and renders correctly when data empty (show existing empty-state messages)
- [ ] Write tests: `/study/stats` renders with Best Study Time + Week Stats + Route Board; `/study/insights` renders with Reading Speed + Milestones
- [ ] Run project test suite — must pass before task 17

---

### BLOCK 5: Mobile + Tests + Ship (Tasks 17-19)

### Task 17: Mobile responsiveness audit

Walk through the new compact dashboard on mobile widths (320px / 375px / 414px / 640px) and tablet (768px) to catch layout issues introduced by the restructure.

**Files:**
- Modify: `app/templates/dashboard.html` (inline CSS mobile media queries; adjust any new selectors)

- [ ] Hero: confirms one-row greeting + streak layout breaks gracefully on narrow screens (stack greeting/streak on < 400px)
- [ ] Plan card: mission XP widget stacks level/progress/multiplier on < 640px
- [ ] Social: 3-column grid collapses to 1 column on <= 768px
- [ ] Race strip: text + "Подробнее →" stays on one line or wraps cleanly
- [ ] Activity streak one-liner wraps to 2 lines on < 400px (acceptable)
- [ ] Roadmap: already fixed to horizontal scroll on mobile in 2026-04-19 commit — verify no regressions
- [ ] Write tests: optional visual regression / CSS tests if the project uses them; otherwise manual QA notes in plan document
- [ ] Run project test suite — must pass before task 18

### Task 18: Update dashboard render tests

`tests/test_dashboard_mission_render.py` and `tests/test_dashboard_routes.py` assert on markers that either move or disappear. Update assertions to match new structure.

**Files:**
- Modify: `tests/test_dashboard_mission_render.py`
- Modify: `tests/test_dashboard_routes.py`

- [ ] Remove assertions on removed markers: `dash-plan__progress-bar`, `dash-roadmap__marker-distance`, `dash-route-board`, `dash-day-secured`, `dash-rival-strip`, `dash-study-time`, `dash-week-stats`, `dash-reading-speed`, `dash-milestones`, `dash-quick`, `dash-grammar-levels`
- [ ] Add assertions on new locations: `.dash-plan .dash-xp` (mission XP inside plan), `.dash-social-row > .dash-rank` (rank in social), `.dash-alerts__accordion` (alerts accordion), compact race strip
- [ ] Add zero-state tests: full rendering hidden, only `.dash-welcome--fullscreen` present
- [ ] Add CTA tests: matrix of 6 scenarios (start / continue / extra / done / fallback / zero-state)
- [ ] Run project test suite — must pass before task 19

### Task 19: Smoke + acceptance

Wrap up with smoke tests covering the 4 dashboard states the redesign needs to handle.

**Files:**
- Modify: `tests/test_dashboard_mission_render.py` (add smoke markers)
- Modify: `tests/test_dashboard_routes.py` (if needed)

- [ ] Smoke: zero-state user (all counters 0) → only welcome-card
- [ ] Smoke: mid-plan user (streak > 0, mission in progress) → hero CTA points to next phase; roadmap single progress indicator; social 3 cols
- [ ] Smoke: plan-done user (`m_all_done`) → completion summary present; hero CTA: `🏁 План готов` or `Ещё тренировка: Карточки →` depending on remaining budget
- [ ] Smoke: legacy user (`use_mission_plan=false`) → legacy plan layout unchanged (no regression)
- [ ] Mark all new smoke tests with `@pytest.mark.smoke`
- [ ] Final: `pytest -m smoke` green, `pytest` green, manual QA on staging
- [ ] Move this plan to `docs/plans/completed/` after acceptance

---

## Acceptance Criteria

- Hero occupies ≤ 25% of viewport height on desktop (target; currently ~50%)
- Zero-state user sees only welcome-card (no hero, no race, no plan, no sections)
- Mission plan progress is visible in exactly **one** place (roadmap)
- All moved elements preserve their data (yesterday, rank, mission-XP render in new locations, nothing is silently dropped)
- Removed blocks are accessible via links to `/study/stats`, `/study/insights`, `/race`, `/grammar_lab`
- Legacy `use_mission_plan=false` branch is **not** regressed
- All existing `tests/test_dashboard_*` assertions pass (after updates in Task 18)

## Out of Scope / Backlog

These surfaced during brainstorming but need separate work:

1. **Phase structure variety** — current missions always follow recall→learn→use→check. Need a separate brainstorm on alternative phase sequences so days don't feel identical even when the lesson changes.
2. **Curriculum continuity A1→C2** — verify `_find_next_lesson` progresses on completion; audit lesson coverage across all CEFR levels; possibly LLM-generated lessons to fill C1/C2 gaps.
3. **Adaptive limits fix** — `SRSService.get_adaptive_limits()` hard-caps `new_words_per_day` at 2 when `backlog > 50` or `accuracy < 85`. Needs decision: remove entirely, soften thresholds, or keep but surface the override to the user.
4. **Repair trigger threshold** — `REPAIR_THRESHOLD = 0.6` cannot be reached by overdue SRS alone (weighted component caps at 0.5). Missions with heavy overdue backlog but no grammar issues incorrectly stay in Progress mission.

These are tracked here but implemented under separate plans.
