# Comprehensive Site, Admin & Dashboard Improvements

## Overview
Максимальный план улучшений сайта, охватывающий: админский дашборд с реальными данными и аналитикой, пользовательский UX (пустые состояния, навигация, профиль), информативность дашбордов, и качество контента. Все улучшения основаны на уже существующих данных и сервисах в БД.

## Context
- Files involved: admin routes/templates, user dashboard, study/words/grammar/books templates, base.html, models, services
- Related patterns: existing cache_result decorator, CurriculumCacheService, SRS stats_service, lesson_analytics_service
- Dependencies: Chart.js (already used in admin), existing CSS design-system.css

## Development Approach
- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Admin Dashboard - Real Activity Chart Data

**Files:**
- Modify: `app/admin/main_routes.py`
- Modify: `app/templates/admin/dashboard.html`

- [x] Replace hardcoded chart data with real daily user activity for last 30 days (query User.last_login grouped by date)
- [x] Add daily new registrations line to the activity chart
- [x] Add daily active users (users with LessonProgress or StudySession activity) line
- [x] Display `total_readings` stat that is already fetched but not shown
- [x] Write tests for new dashboard stats queries
- [x] Run project test suite - must pass before task 2

### Task 2: Admin Dashboard - Engagement & Learning Metrics Cards

**Files:**
- Modify: `app/admin/main_routes.py`
- Modify: `app/templates/admin/dashboard.html`

- [x] Add engagement metrics section: DAU/WAU/MAU counts with trend arrows (vs previous period)
- [x] Add learning metrics: total lessons completed today/week, average lesson score, total study sessions today
- [x] Add content metrics: grammar topics count, book courses count with enrollments, active quiz decks
- [x] Add SRS health metrics: total words in SRS (new/learning/review/mastered distribution), total grammar exercises in SRS
- [x] Cache all new metrics with existing `cache_result` decorator (5 min TTL)
- [x] Write tests for engagement/learning metric calculations
- [x] Run project test suite - must pass before task 3

### Task 3: Admin Dashboard - Retention & Referral Analytics

**Files:**
- Modify: `app/admin/main_routes.py`
- Modify: `app/templates/admin/dashboard.html`

- [x] Add retention section: Day 1, Day 7, Day 30 retention rates (users who returned after registration)
- [x] Add streak analytics: users with active streaks, average streak length, streak distribution chart
- [x] Add referral dashboard section: total referrals, top 5 referrers, referral conversion rate (registered -> completed first lesson)
- [x] Add coin economy summary: total coins in circulation, earned vs spent ratio
- [x] Write tests for retention and referral calculations
- [x] Run project test suite - must pass before task 4

### Task 4: Admin Dashboard - Content Quality & Alerts

**Files:**
- Modify: `app/admin/main_routes.py`
- Modify: `app/templates/admin/dashboard.html`

- [x] Integrate `lesson_analytics_service.generate_alerts()` on admin dashboard - show top 5 alerts (low pass rate lessons, high abandonment)
- [x] Add content quality section: lessons with <50% pass rate, lessons with 0 completions, grammar topics with 0 exercises
- [x] Add "problem lessons" table showing lesson_id, type, pass_rate, attempts, module for bottom 10 lessons
- [x] Add system health mini-widget: DB connection status, total errors today (if logging available)
- [x] Write tests for alert generation and content quality queries
- [x] Run project test suite - must pass before task 5

### Task 5: Admin - User Management Improvements

**Files:**
- Modify: `app/admin/routes/user_routes.py`
- Modify: `app/templates/admin/users.html`
- Modify: `app/templates/admin/dashboard.html`

- [x] Add user detail page link from dashboard "last registered" table showing full user profile: modules, lessons completed, words learned, grammar progress, streak, achievements, referrals made
- [x] Add "at risk" users section on dashboard: users inactive 7+ days who previously had 3+ day streaks
- [x] Add user search to admin dashboard (quick search by username/email)
- [x] Add bulk user export (CSV) with key metrics
- [x] Write tests for user detail aggregation and at-risk query
- [x] Run project test suite - must pass before task 6

### Task 6: User Dashboard - Empty States & First-Time UX

**Files:**
- Modify: `app/templates/dashboard.html`
- Modify: `app/words/routes.py`

- [x] Add proper empty state for new users with no modules: show welcome card with "Start learning" CTA linking to onboarding or level selection
- [x] Add empty state for daily plan when no steps configured: explain what daily plan is and how to activate it
- [x] Add contextual tooltips for gamification elements (XP, coins, streak) using title attributes or info icons
- [x] Show "0 coins" state for streak repair with explanation of how to earn coins
- [x] Handle null weekly_challenge gracefully in template (show "No active challenge" card)
- [x] Write tests for dashboard rendering with empty/null data scenarios
- [x] Run project test suite - must pass before task 7

### Task 7: User Dashboard - Progress Analytics Section

**Files:**
- Modify: `app/templates/dashboard.html`
- Modify: `app/words/routes.py`

- [x] Add "This Week" mini-analytics: words reviewed, lessons completed, time spent, accuracy rate (from StudySession and LessonAttempt data)
- [x] Add words SRS distribution mini-chart (new/learning/review/mastered as horizontal stacked bar)
- [x] Add "Continue where you left off" card showing last incomplete lesson with direct link
- [x] Add grammar progress summary: topics started/mastered with percentage
- [x] Write tests for weekly analytics aggregation
- [x] Run project test suite - must pass before task 8

### Task 8: Empty States Across the App

**Files:**
- Modify: `app/templates/curriculum/index.html`
- Modify: `app/templates/curriculum/level_modules.html`
- Modify: `app/templates/study/index.html`
- Modify: `app/templates/study/cards.html`
- Modify: `app/templates/study/achievements.html`
- Modify: `app/templates/study/leaderboard.html`
- Modify: `app/templates/grammar_lab/index.html`
- Modify: `app/templates/grammar_lab/topics.html`
- Modify: `app/templates/grammar_lab/practice.html`
- Modify: `app/templates/books/read_selection.html`

- [ ] Learn hub (`curriculum/index.html`): show "Start your journey" card when levels_data is empty instead of empty divs
- [ ] Study dashboard: improve welcome block for new users with actionable steps (create deck, explore public decks)
- [ ] Flashcards (`study/cards.html`): add "Nothing to study right now" message with next review time and suggestion to add new words
- [ ] Achievements: add "No achievements yet" state with closest achievable badges listed
- [ ] Leaderboard: add "Not ranked yet" state with explanation of how to get ranked
- [ ] Grammar lab index: handle 0/0 levels gracefully, show "Start with basics" CTA
- [ ] Grammar topics: show "No topics for this level" with link to available levels
- [ ] Grammar practice: show "No exercises available" when topic has zero exercises
- [ ] Books selection: show "No books available for your level" with level filter suggestion
- [ ] Write template rendering tests for empty state scenarios
- [ ] Run project test suite - must pass before task 9

### Task 9: Navigation & Information Architecture Improvements

**Files:**
- Modify: `app/templates/base.html`
- Modify: `app/templates/components/_daily_plan_progress.html`

- [ ] Add notification bell icon in navbar showing unread notification count (using existing Notification model)
- [ ] Add badge counts to nav dropdown items: "Words (5 due)" from SRS due count, "Grammar (3 due)" from grammar SRS
- [ ] Make daily plan progress bar clickable (link to dashboard)
- [ ] Add breadcrumbs component to curriculum pages (Level > Module > Lesson)
- [ ] Add "Quick actions" dropdown: "Start daily review", "Continue lesson", "Practice grammar"
- [ ] Write tests for notification count query and breadcrumb generation
- [ ] Run project test suite - must pass before task 10

### Task 10: User Profile & Settings Enhancement

**Files:**
- Modify: `app/auth/routes.py`
- Modify: `app/templates/auth/profile.html`
- Modify: `app/templates/auth/referrals.html`

- [ ] Enhance profile page: add learning stats summary (total words learned, lessons completed, streak record, XP level), add timezone setting, add daily goal setting
- [ ] Add notification preferences section: toggle email reminders, toggle in-app notifications by type
- [ ] Add "Copy to clipboard" button for referral link on referrals page
- [ ] Add referral stats: total referred, active referred users, total XP earned from referrals
- [ ] Add account section: last login date, registration date, account age
- [ ] Write tests for profile stats aggregation and settings save
- [ ] Run project test suite - must pass before task 11

### Task 11: Study Section UX Improvements

**Files:**
- Modify: `app/templates/study/index.html`
- Modify: `app/templates/study/cards.html`
- Modify: `app/templates/study/stats.html`
- Modify: `app/study/routes.py`

- [ ] Add "Study Now" prominent button on study dashboard for most urgent deck (highest due count)
- [ ] Show auto-deck vs custom deck visual distinction (icon/badge)
- [ ] Add daily limit explanation when limit reached in flashcards: show current limit, link to settings to adjust
- [ ] Improve study stats page: add accuracy trend chart (last 30 days), add words mastered over time chart, add study time heatmap (days of week)
- [ ] Add session summary after flashcard session: cards reviewed, accuracy, XP earned, streak status
- [ ] Write tests for study stats data aggregation
- [ ] Run project test suite - must pass before task 12

### Task 12: Grammar Lab UX Improvements

**Files:**
- Modify: `app/templates/grammar_lab/index.html`
- Modify: `app/templates/grammar_lab/topic_detail.html`
- Modify: `app/templates/grammar_lab/practice.html`
- Modify: `app/grammar_lab/routes.py`

- [ ] Add "Recommended next topic" card on grammar index based on user's level and completion
- [ ] Add previous/next topic navigation on topic detail page
- [ ] Add "Jump to exercises" anchor link on long theory pages
- [ ] Show which topic current exercise belongs to during mixed practice
- [ ] Add grammar mastery progress bar per level on index page
- [ ] Write tests for topic recommendation logic and navigation
- [ ] Run project test suite - must pass before task 13

### Task 13: Books & Reading UX Improvements

**Files:**
- Modify: `app/templates/books/read_selection.html`
- Modify: `app/templates/books/read_optimized.html`
- Modify: `app/templates/books/details_optimized.html`
- Modify: `app/books/routes.py`

- [ ] Add reading progress indicator on book selection page (% completed per book)
- [ ] Add "Continue reading" button linking to last read chapter (using UserChapterProgress)
- [ ] Add word frequency info on book words page (how many times word appears)
- [ ] Add fallback icon when book cover image fails to load
- [ ] Add estimated reading time per chapter based on word count
- [ ] Write tests for reading progress calculation and continue-reading logic
- [ ] Run project test suite - must pass before task 14

### Task 14: Lesson UX Improvements

**Files:**
- Modify: `app/curriculum/routes/lessons.py`
- Modify: `app/templates/curriculum/lessons/vocabulary.html`
- Modify: `app/templates/curriculum/lessons/quiz.html`
- Modify: `app/templates/curriculum/module_lessons.html`

- [ ] Add progress save indicator (auto-save notification) in lesson templates
- [ ] Add empty content validation before rendering lesson (show "Lesson content unavailable" instead of crash)
- [ ] Add lesson completion confirmation with grade display and next lesson link
- [ ] Show locked module reasons on module lessons page (prerequisite module name, required score)
- [ ] Add "Continue where you left off" for in-progress lessons (use LessonProgress.data field)
- [ ] Write tests for empty content handling and progress save
- [ ] Run project test suite - must pass before task 15

### Task 15: Verify acceptance criteria

- [ ] Run full test suite (`pytest`)
- [ ] Verify all admin dashboard charts show real data (no hardcoded values)
- [ ] Verify empty states render correctly across all modified pages
- [ ] Verify navigation improvements (notification bell, badges, breadcrumbs) work
- [ ] Run linter if configured

### Task 16: Update documentation

- [ ] Update CLAUDE.md if internal patterns changed
- [ ] Move this plan to `docs/plans/completed/`
