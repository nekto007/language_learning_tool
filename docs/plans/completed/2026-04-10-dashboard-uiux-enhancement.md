# Dashboard UI/UX Enhancement - Rich Widgets

## Overview

Enrich the existing dashboard with new data-driven widgets that surface the app's extensive but currently unused analytics services. Add activity heatmap, words at risk, grammar weaknesses, best study time, reading speed trend, streak calendar/milestones, leaderboard, achievement progress, and detailed session stats.

## Context

- Files involved:
  - `app/words/routes.py` (dashboard route, lines 105-305)
  - `app/templates/dashboard.html` (1310 lines, main dashboard template)
  - `app/static/css/design-system.css` (dashboard CSS with `dash-` prefix)
  - `app/study/insights_service.py` (heatmap, best study time, words at risk, grammar weaknesses, reading speed)
  - `app/achievements/streak_service.py` (streak calendar, milestone history)
  - `app/study/services/stats_service.py` (leaderboards, XP rank, achievement rank)
  - `app/study/services/session_service.py` (session stats)
  - `app/srs/stats_service.py` (grammar SRS stats)
  - `app/grammar_lab/services/grammar_lab_service.py` (grammar levels summary)
  - `app/curriculum/services/progress_service.py` (level progress)
- Related patterns: existing `dash-` CSS prefix, CSS variables in design-system.css, data passed via route context dict
- Dependencies: no new external dependencies (charts built with pure CSS/SVG)

## Development Approach

- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- Each widget group is self-contained: route data + template section + CSS
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Activity Heatmap Widget (streak calendar + activity heatmap combined)

**Files:**
- Modify: `app/words/routes.py`
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/css/design-system.css`

- [x] In `dashboard()` route, add calls to `get_activity_heatmap(user_id, days=90)` and `get_streak_calendar(user_id, days=90, tz=tz)` and pass results to template
- [x] Create heatmap widget in template: 90-day grid (13 weeks x 7 days) with color-coded activity intensity cells, month labels, day-of-week labels
- [x] Build heatmap with pure CSS grid (no JS library) - cells colored by activity count using CSS classes (0=empty, 1-2=light, 3-5=medium, 6+=intense)
- [x] Show current streak, longest streak, and total active days as summary stats below heatmap
- [x] Add CSS for `.dash-heatmap`, `.dash-heatmap__grid`, `.dash-heatmap__cell`, intensity levels
- [x] Write tests for route data (mock insights_service calls, verify template context)

### Task 2: Words at Risk + Grammar Weaknesses Widgets

**Files:**
- Modify: `app/words/routes.py`
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/css/design-system.css`

- [x] In route, add calls to `get_words_at_risk(user_id, limit=5)` and `get_grammar_weaknesses(user_id, limit=5)`
- [x] Create "Words at Risk" widget: list of overdue words with word, translation, days overdue badge, and "Review now" link to SRS
- [x] Create "Grammar Weaknesses" widget: list of weak topics with title, accuracy percentage bar, attempt count, and link to practice
- [x] Place both widgets side-by-side in a 2-column grid below the daily plan
- [x] Add CSS for `.dash-risk`, `.dash-risk__item`, `.dash-weakness`, `.dash-weakness__bar`
- [x] Write tests for route data (mock service calls, verify context variables)

### Task 3: Best Study Time + Session Stats Widgets

**Files:**
- Modify: `app/words/routes.py`
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/css/design-system.css`

- [x] In route, add calls to `get_best_study_time(user_id)` and `SessionService.get_session_stats(user_id, days=7)`
- [x] Create "Best Study Time" widget: clock icon with recommended hour, 24-hour mini bar chart showing hourly activity scores
- [x] Create "This Week's Stats" widget: cards showing total sessions, words studied, accuracy percentage, total study time
- [x] Add CSS for `.dash-study-time`, `.dash-study-time__chart`, `.dash-week-stats`
- [x] Write tests for route data

### Task 4: Leaderboard + XP Rank Widget

**Files:**
- Modify: `app/words/routes.py`
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/css/design-system.css`

- [x] In route, add calls to `StatsService.get_xp_leaderboard(limit=5)`, `StatsService.get_user_xp_rank(user_id)`
- [x] Create compact leaderboard widget: top 5 users with avatar placeholder, username, XP, level. Highlight current user's position
- [x] Show user's rank badge if not in top 5 ("You are #12")
- [x] Add CSS for `.dash-leaderboard`, `.dash-leaderboard__row`, `.dash-leaderboard__rank`, `.dash-leaderboard__highlight`
- [x] Write tests for route data

### Task 5: Achievement Progress + Streak Milestones Widget

**Files:**
- Modify: `app/words/routes.py`
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/css/design-system.css`

- [x] In route, add calls to `StatsService.get_achievements_by_category(user_id)` and `get_milestone_history(user_id)`
- [x] Create "Achievements" widget: progress rings per category (e.g., vocabulary, grammar, streak, reading) showing earned/total, with recent unlocks list
- [x] Create "Streak Milestones" widget: timeline showing past milestones (7, 14, 30, 60, 100 days) with earned dates, and next upcoming milestone highlighted
- [x] Add CSS for `.dash-achievements`, `.dash-achievements__ring`, `.dash-milestones`, `.dash-milestones__item`
- [x] Write tests for route data

### Task 6: Reading Speed Trend + Grammar by Level Widget

**Files:**
- Modify: `app/words/routes.py`
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/css/design-system.css`

- [x] In route, add calls to `get_reading_speed_trend(user_id)` and `GrammarLabService.get_levels_summary(user_id)`
- [x] Create "Reading Speed" widget: sparkline trend (CSS-only, using inline bar chart) showing weekly WPM with current vs. starting comparison
- [x] Create "Grammar by Level" widget: horizontal stacked bars for each CEFR level (A1-C2) showing studied/total topics per level
- [x] Add CSS for `.dash-reading-speed`, `.dash-sparkline`, `.dash-grammar-levels`, `.dash-grammar-levels__bar`
- [x] Write tests for route data

### Task 7: Dashboard Layout Reorganization

**Files:**
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/css/design-system.css`

- [x] Reorganize the full dashboard layout into logical sections with clear visual hierarchy:
  - Section 1: Hero (greeting, streak, XP) - keep existing
  - Section 2: Daily Plan - keep existing
  - Section 3: Activity Heatmap (full width)
  - Section 4: Alerts row - Words at Risk + Grammar Weaknesses (2-col)
  - Section 5: Stats row - Best Study Time + This Week's Stats (2-col)
  - Section 6: Progress row - Progress Overview cards + Grammar Levels (2-col)
  - Section 7: Social row - Leaderboard + Achievements (2-col)
  - Section 8: Insights row - Reading Speed + Streak Milestones (2-col)
  - Section 9: Quick Actions - keep existing
- [x] Add section headings with subtle dividers between groups
- [x] Ensure responsive layout: 2-col sections collapse to 1-col on mobile (<=640px)
- [x] Handle empty states gracefully for all new widgets (no data = friendly message, not broken UI)
- [x] Write template rendering tests (authenticated client GET, verify all sections render)

### Task 8: Performance Optimization

**Files:**
- Modify: `app/words/routes.py`

- [x] Profile dashboard route with all new service calls to measure total query time
- [x] Wrap non-critical widget data in try/except so individual widget failures don't crash the dashboard
- [x] Add caching where appropriate (e.g., leaderboard data can be cached for 5 minutes using Flask-Caching or simple dict cache)
- [x] Ensure all new DB queries use appropriate indexes (check that no N+1 queries were introduced)
- [x] Write performance test: dashboard route responds within acceptable time with test data

### Task 9: Verify acceptance criteria

- [x] Run full test suite (`pytest`)
- [x] Verify all new widgets render correctly on desktop and mobile viewports (manual test - skipped, not automatable; CSS uses responsive 2-col->1-col at <=640px)
- [x] Verify empty states for users with no activity data
- [x] Verify test coverage for new route data and template rendering

### Task 10: Update documentation

- [x] Update CLAUDE.md if internal patterns changed
- [x] Move this plan to `docs/plans/completed/`
