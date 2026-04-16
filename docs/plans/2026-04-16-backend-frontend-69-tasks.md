---
# Backend & Frontend: 69 Improvement Tasks

## Overview
Comprehensive improvement plan covering security hardening, test coverage expansion, backend code quality, frontend accessibility, performance optimization, and monitoring. Tasks are organized by priority: security/critical first, then high-impact backend, then frontend, then operational concerns. Each task is scoped to 1-3 files.

## Context
- Files involved: app/** (all blueprints), templates/**, static/css/design-system.css, tests/**, config/settings.py, migrations/versions/**
- Related patterns: db_session savepoint pattern for tests, _safe_widget_call() for dashboard widgets, get_daily_plan_unified() pipeline, _count_active_users_in_range()
- Dependencies: existing Flask, SQLAlchemy, Alembic, pytest stack — no new framework dependencies required for most tasks

## Development Approach
- **Testing approach**: Regular — implement, then write/update tests for that task
- **CRITICAL: every task that changes Python code must include updated/new tests**
- **CRITICAL: all tests must pass before starting next task**
- Run `pytest -m smoke` after each task as the baseline gate

## Implementation Steps

### Task 1: Add request.is_json guards to all API routes

**Files:**
- Modify: `app/api/daily_plan.py`
- Modify: `app/study/api_routes.py`
- Modify: `app/study/game_routes.py`
- Modify: `app/curriculum/routes/vocabulary_lessons.py`

- [x] grep all files for `request.json.get` without preceding `request.is_json` check
- [x] wrap each such block: `if not request.is_json: return jsonify({'error': 'Content-Type must be application/json'}), 415`
- [x] write tests for 415 responses on affected endpoints
- [x] run pytest -m smoke

### Task 2: Standardize API error response format

**Files:**
- Create: `app/api/errors.py`
- Modify: `app/api/daily_plan.py`, `app/api/auth.py`, `app/api/books.py`

- [x] define `api_error(code: str, message: str, status: int) -> tuple` helper in errors.py
- [x] replace ad-hoc error dicts across API modules with this helper
- [x] write tests asserting consistent error shape (keys: error, message, status)
- [x] run pytest -m smoke

### Task 3: Fix open redirect vulnerability in auth routes

**Files:**
- Modify: `app/auth/routes.py`

- [x] locate all `redirect(request.args.get('next'))` patterns
- [x] add `is_safe_url(next_url)` check using urllib.parse (compare netloc to request.host)
- [x] write test: passing external URL as `next` must redirect to home instead
- [x] run pytest -m smoke

### Task 4: Invalidate password reset tokens after single use

**Files:**
- Modify: `app/auth/models.py` (if token model exists) or `app/auth/routes.py`

- [x] read current password reset flow; identify how tokens are stored/checked
- [x] add `used_at` timestamp to token model (or mark token invalid in DB on use)
- [x] create migration for schema change
- [x] write test: using same token twice must return 400/404 on second use
- [x] run pytest -m smoke

### Task 5: Log failed login attempts

**Files:**
- Modify: `app/auth/routes.py`

- [x] locate login POST handler
- [x] add `logger.warning('failed login attempt: user=%s ip=%s', username, request.remote_addr)` on auth failure
- [x] write test asserting the log entry is emitted (use caplog)
- [x] run pytest -m smoke

### Task 6: Fix innerHTML XSS risks — replace with textContent

**Files:**
- Modify: `app/templates/words/list_optimized.html`
- Modify: `app/templates/study/topics.html`
- Modify: `app/templates/study/deck_edit.html`

- [x] grep templates for `.innerHTML =` assignments
- [x] replace each with `.textContent =` where the value is plain text
- [x] for cases that must render HTML, add DOMPurify.sanitize() wrapper
- [x] manually verify changed pages render correctly
- [x] run pytest -m smoke

### Task 7: Replace bare `except Exception` with specific exception types

**Files:**
- Modify: `app/words/routes.py`
- Modify: `app/study/api_routes.py`
- Modify: `app/study/game_routes.py`
- Modify: `app/curriculum/service.py`
- Modify: `app/achievements/services.py`

- [x] grep all five files for `except Exception`
- [x] replace with `except (IntegrityError, OperationalError)` or relevant SQLAlchemy/KeyError types per context
- [x] add `logger.exception(...)` in each catch block (captures full traceback)
- [x] write tests for each replaced exception path
- [x] run pytest -m smoke

### Task 8: Add 404, 500, 403 custom error handlers

**Files:**
- Modify: `app/__init__.py` or `app/errors.py`
- Create: `app/templates/errors/404.html`, `app/templates/errors/500.html`, `app/templates/errors/403.html`

- [x] register `@app.errorhandler(404)`, `@app.errorhandler(500)`, `@app.errorhandler(403)` in app factory
- [x] create minimal templates inheriting base.html with friendly message and home link
- [x] write tests: hit non-existent route -> 404 with custom template; trigger abort(403) -> custom page
- [x] run pytest -m smoke

### Task 9: Add composite DB indexes for high-traffic queries

**Files:**
- Create: `migrations/versions/YYYYMMDD_add_composite_indexes.py`
- Modify: relevant model files (identify from grep of `filter_by(user_id=` patterns)

- [x] grep codebase for `.filter_by(user_id=` and `.filter(*.user_id ==` to identify hot columns
- [x] create Alembic migration adding `Index('idx_lessonprogress_user_lesson', 'user_id', 'lesson_id')` and similar
- [x] verify migration chain consistency (alembic heads shows single head)
- [x] write test that migration applies/reverts cleanly
- [x] run pytest -m smoke

### Task 10: Add explicit DB session rollback in multi-step service methods

**Files:**
- Modify: `app/study/services/deck_service.py`
- Modify: `app/auth/routes.py` (registration flow)
- Modify: `app/words/routes.py` (bulk word add)

- [x] read each file; locate multi-step db.session.add/flush/commit sequences
- [x] wrap in `try/except` with `db.session.rollback()` in except clause
- [x] write tests that simulate IntegrityError mid-operation and verify rollback leaves DB clean
- [x] run pytest -m smoke

### Task 11: Add type hints to service layer public methods

**Files:**
- Modify: `app/curriculum/service.py`
- Modify: `app/study/services/deck_service.py`
- Modify: `app/daily_plan/service.py`

- [x] read each file; add `-> ReturnType` and `param: Type` annotations to all public functions
- [x] ensure no `Any` is used unless necessary
- [x] run `python -c "import app.curriculum.service"` to confirm no import errors
- [x] run pytest -m smoke (type hints don't require new tests, just verify nothing broke)

### Task 12: Remove unused imports and dead code

**Files:**
- Modify: all Python files with unused imports (identify via `python -m py_compile` and flake8)

- [x] run `python -m flake8 app/ --select=F401,F811 --count` to list unused imports
- [x] remove each unused import
- [x] run `python -m py_compile` on changed files
- [x] run pytest -m smoke

### Task 13: Replace magic numbers with named constants

**Files:**
- Modify: `config/settings.py`
- Modify: `app/curriculum/models.py`
- Modify: `app/achievements/models.py`

- [x] grep for hardcoded integers/strings used as thresholds (300, 3600, 180, 0.6, 70)
- [x] define named constants in settings.py (REPAIR_PRESSURE_THRESHOLD, SRS_MASTERED_DAYS, etc.)
- [x] update all usages to reference constants
- [x] run pytest -m smoke

### Task 14: Add `joinedload` to fix N+1 queries in study routes

**Files:**
- Modify: `app/study/routes.py`
- Modify: `app/curriculum/routes/main.py`

- [x] read study/routes.py; identify loops that issue per-iteration DB queries
- [x] add `options(joinedload(Model.relationship))` to the initial query
- [x] verify query count reduction with SQLAlchemy echo=True in test
- [x] write performance regression test (query count must be < 5 for deck listing)
- [x] run pytest -m smoke

### Task 15: Implement chunk_ids utility for large IN() clauses

**Files:**
- Create: `app/utils/db_utils.py`
- Modify: `app/curriculum/service.py`
- Modify: `app/repository.py` (if exists)

- [x] create `chunk_ids(ids: list, chunk_size: int = 1000) -> Generator` in db_utils.py
- [x] replace `Model.query.filter(Model.id.in_(all_ids))` patterns with chunked version using union_all
- [x] write unit test for chunk_ids (empty list, list <1000, list >1000)
- [x] run pytest -m smoke

### Task 16: Add ARIA attributes to interactive UI components

**Files:**
- Modify: templates with modals, dropdowns, toggle buttons (identify from grep for `<button`, `<dialog`, `<details`)

- [x] grep templates for `<button` missing `aria-label`
- [x] grep templates for modal divs missing `role="dialog"` and `aria-modal="true"`
- [x] grep for accordion/toggle missing `aria-expanded`
- [x] add missing attributes
- [x] run pytest -m smoke

### Task 17: Add viewport meta tag to all base templates

**Files:**
- Modify: `app/templates/base.html`
- Modify: any other base templates (landing, legal, onboarding)

- [x] grep all base templates for `<meta name="viewport"`
- [x] add `<meta name="viewport" content="width=device-width, initial-scale=1">` where missing — already present in base.html and admin/base.html; all other templates extend one of these; error templates also have it directly
- [x] run pytest -m smoke

### Task 18: Add pagination to word list and study card endpoints

**Files:**
- Modify: `app/words/routes.py`
- Modify: `app/study/routes.py`

- [x] identify endpoints that return unbounded result sets
- [x] add `page` and `per_page` query params (default per_page=50, max=200)
- [x] return `{'items': [...], 'total': N, 'page': P, 'pages': TP}` shape
- [x] update relevant templates to use paginated API (or add frontend paging)
- [x] write tests for page=1, page=2, per_page clamping
- [x] run pytest -m smoke

### Task 19: Add /health endpoint

**Files:**
- Create: `app/health.py`
- Modify: `app/__init__.py`

- [x] create blueprint with GET /health that checks db.session.execute('SELECT 1') and returns `{'status': 'ok', 'db': 'ok'}` or 503
- [x] register blueprint in app factory
- [x] write test: GET /health returns 200 with expected JSON
- [x] run pytest -m smoke

### Task 20: Add response compression middleware

**Files:**
- Modify: `requirements.txt`
- Modify: `app/__init__.py`

- [x] add `Flask-Compress` to requirements.txt
- [x] enable in app factory: `Compress(app)` with COMPRESS_MIMETYPES including application/json
- [x] write test: large JSON response has Content-Encoding: gzip header
- [x] run pytest -m smoke

### Task 21: Add structured logging with JSON formatter

**Files:**
- Modify: `config/logging_config.py` or `app/__init__.py`
- Modify: `requirements.txt`

- [x] add `python-json-logger` to requirements.txt
- [x] configure root logger to use JsonFormatter in production mode (LOG_FORMAT=json env var)
- [x] verify log output is valid JSON in test environment
- [x] run pytest -m smoke

### Task 22: Duplicate detection — catch IntegrityError on word/topic insert

**Files:**
- Modify: `app/words/routes.py`
- Modify: `app/grammar_lab/routes.py` (topic insert)

- [x] locate db.session.add() calls that could hit unique constraint
- [x] wrap in `except IntegrityError` and return `{'error': 'duplicate_entry', 'field': 'word'}` with 409
- [x] write test: inserting duplicate word returns 409 with error key
- [x] run pytest -m smoke

### Task 23: Add per-record error reporting to batch admin operations

**Files:**
- Modify: `app/admin/book_courses.py`
- Modify: `app/admin/routes/book_routes.py`

- [x] read current batch import logic; identify where all-or-nothing behavior exists
- [x] change to collect `errors = []` per-record, continue processing, return `{'success': N, 'errors': [...]}`
- [x] write test: batch with 1 invalid record returns partial success + error list
- [x] run pytest -m smoke

### Task 24: Add validate_enum decorator for status fields

**Files:**
- Create: `app/utils/validators.py`
- Modify: routes accepting `status` or `state` string params

- [x] define `validate_enum(value: str, enum_cls: Type[Enum]) -> bool` in validators.py
- [x] apply to endpoints accepting lesson status, SRS state, etc.
- [x] write tests: invalid enum value returns 400; valid value passes
- [x] run pytest -m smoke

### Task 25: Add slow query logging for queries > 100ms

**Files:**
- Modify: `config/settings.py`
- Modify: `app/__init__.py`

- [x] add SQLAlchemy event listener `before_cursor_execute` / `after_cursor_execute` that logs elapsed time if > 100ms
- [x] configure threshold via SLOW_QUERY_MS env var (default 100)
- [x] write test: artificially slow query triggers log entry (use monkeypatch on time.time)
- [x] run pytest -m smoke

### Task 26: Add unit tests for daily_plan service pipeline

**Files:**
- Create: `tests/daily_plan/test_service.py`

- [x] write tests for `select_mission()`: repair_pressure >= 0.6 -> Repair mission
- [x] write tests for `assemble_progress_mission()`: cold start with onboarding_level
- [x] write tests for `assemble_repair_mission()`: 0 SRS + 0 grammar degrades to progress
- [x] write tests for fallback to legacy plan on assembly error
- [x] run pytest -m smoke

### Task 27: Add unit tests for curriculum service

**Files:**
- Create: `tests/curriculum/test_service.py`

- [x] write tests for module access check logic
- [x] write tests for lesson ordering and availability
- [x] write tests for CEFR level calculation
- [x] run pytest -m smoke

### Task 28: Add unit tests for achievement streak service

**Files:**
- Create: `tests/achievements/test_streak_service.py`

- [x] write tests for streak calculation with timezone edge cases
- [x] write tests for streak recovery purchase flow
- [x] write tests for streak freeze handling
- [x] run pytest -m smoke

### Task 29: Add API integration tests for /api/daily_plan endpoints

**Files:**
- Create: `tests/api/test_daily_plan_api.py`

- [x] test GET /api/daily_plan/today: authenticated user returns plan
- [x] test GET /api/daily_plan/today: unauthenticated returns 401
- [x] test timezone validation: invalid tz returns 400
- [x] test: empty user (no progress) returns cold-start plan
- [x] run pytest -m smoke

### Task 30: Add API integration tests for study card endpoints

**Files:**
- Create: `tests/api/test_study_api.py`

- [x] test start card session: valid lesson_id -> 200 with card data
- [x] test start card session: invalid lesson_id -> 404
- [x] test submit card answer: correct/incorrect responses
- [x] test: missing JSON content-type -> 415
- [x] run pytest -m smoke

### Task 31: Add parametrized edge case tests for SRS service

**Files:**
- Modify: `tests/grammar_lab/test_grammar_srs.py` (or create)

- [x] test review with 0 items due
- [x] test review with all items overdue
- [x] test first review (never reviewed before)
- [x] test interval calculation at mastery boundary
- [x] run pytest -m smoke

### Task 32: Fix missing template variables causing 500 errors on edge routes

**Files:**
- Modify: relevant route files (identify from manual QA of routes with optional query params)

- [x] grep templates for `{{ variable }}` without `| default(...)` on non-guaranteed vars
- [x] grep route handlers for `render_template(...)` missing context vars defined in template
- [x] add `.get()` with defaults or Jinja `default` filter
- [x] write tests that hit each fixed route with minimal context
- [x] run pytest -m smoke

### Task 33: Add smoke markers to key happy-path tests for new tests added in this plan

**Files:**
- Modify: new test files from tasks 26-31

- [x] add `@pytest.mark.smoke` to one happy-path test per new file
- [x] verify `pytest -m smoke` runs new tests
- [x] run pytest -m smoke

### Task 34: Add admin audit log for destructive admin actions

**Files:**
- Create: `app/admin/audit.py`
- Modify: `app/admin/book_courses.py`, `app/admin/main_routes.py`

- [x] create `AdminAuditLog` SQLAlchemy model (id, admin_id, action, target_type, target_id, created_at)
- [x] create migration for new table
- [x] wrap delete-user, modify-content admin actions with `log_admin_action(admin_id, action, target)`
- [x] write test: deleting resource creates audit log entry
- [x] run pytest -m smoke

### Task 35: Validate redirect `next` parameter domain (extend to curriculum routes)

**Files:**
- Modify: `app/curriculum/routes/main.py`
- Modify: `app/study/routes.py`

- [x] grep all route files for `request.args.get('next')` or `request.args.get('redirect')`
- [x] apply the `is_safe_url` helper from task 3 to all occurrences — all usages already use get_safe_redirect_url; curriculum/study routes have no next-param redirects
- [x] write tests for each new application — added TestWordsRouteNextParamProtection and static analysis test in tests/test_open_redirect.py
- [x] run pytest -m smoke

### Task 36: Add rate limiting to registration and password reset endpoints

**Files:**
- Modify: `app/auth/routes.py`

- [x] verify Flask-Limiter is installed and configured in app factory
- [x] add `@limiter.limit("5 per minute")` to POST /register
- [x] add `@limiter.limit("3 per hour")` to POST /password-reset
- [x] write test: exceeding limit returns 429
- [x] run pytest -m smoke

### Task 37: Add bleach sanitization to user-provided text fields before storage

**Files:**
- Modify: `requirements.txt`
- Modify: `app/study/api_routes.py` (note field)
- Modify: `app/words/routes.py` (definition/example fields)

- [x] add `bleach` to requirements.txt
- [x] identify all endpoints that persist user-provided free text
- [x] apply `bleach.clean(value, tags=[], strip=True)` before db.session.add
- [x] write test: storing `<script>` in note field saves sanitized text
- [x] run pytest -m smoke

### Task 38: Move hardcoded DEFAULT_TIMEZONE to config

**Files:**
- Modify: `config/settings.py`
- Modify: `app/api/daily_plan.py`
- Modify: `app/utils/template_utils.py`

- [ ] add `DEFAULT_TIMEZONE = os.getenv('DEFAULT_TIMEZONE', 'Europe/Moscow')` to settings
- [ ] grep all files for hardcoded `'Europe/Moscow'` string
- [ ] replace each with `current_app.config['DEFAULT_TIMEZONE']` or import from settings
- [ ] run pytest -m smoke

### Task 39: Add graceful 404 for missing book/lesson content

**Files:**
- Modify: `app/books/routes.py`
- Modify: `app/curriculum/routes/main.py`

- [ ] locate `.first()` queries without `.first_or_404()` on resource lookups
- [ ] replace with `.first_or_404()` or add explicit `if not resource: abort(404)`
- [ ] write tests: requesting non-existent book/lesson returns 404, not 500
- [ ] run pytest -m smoke

### Task 40: Add pagination meta to admin user list endpoint

**Files:**
- Modify: `app/admin/main_routes.py`

- [ ] read current user list query; if loading all users, add `.paginate(page, per_page=50)`
- [ ] pass pagination object to template; add prev/next controls in admin template
- [ ] write test: page=1 returns first 50 users; page=2 returns next batch
- [ ] run pytest -m smoke

### Task 41: Fix missing `db.session.rollback()` in registration flow on duplicate email

**Files:**
- Modify: `app/auth/routes.py`

- [ ] read registration handler; locate `db.session.add(user)` flow
- [ ] add IntegrityError catch for duplicate email with rollback and user-friendly error
- [ ] write test: registering duplicate email returns 400 with 'email_taken' error
- [ ] run pytest -m smoke

### Task 42: Add study session completion event logging

**Files:**
- Modify: `app/study/routes.py` or `app/study/services/stats_service.py`

- [ ] identify where study sessions are marked complete
- [ ] add `logger.info('study_session_complete user=%s lesson=%s duration=%s', ...)` with structured fields
- [ ] run pytest -m smoke

### Task 43: Add request ID middleware

**Files:**
- Create: `app/middleware/request_id.py`
- Modify: `app/__init__.py`

- [ ] create before_request hook that sets `g.request_id = uuid4().hex`
- [ ] create after_request hook that adds `X-Request-ID` header to response
- [ ] include request_id in all logger calls via `extra={'request_id': g.request_id}`
- [ ] write test: response includes X-Request-ID header
- [ ] run pytest -m smoke

### Task 44: Add caching to leaderboard and DAU/WAU queries

**Files:**
- Modify: `app/words/routes.py` (leaderboard if not cached)
- Modify: `app/admin/main_routes.py` (_count_active_users_in_range)

- [ ] read current caching for leaderboard; verify TTL=5min via _get_cached_leaderboard()
- [ ] add caching (TTL=10min) to DAU/WAU UNION query using Flask-Caching
- [ ] write test: second call within TTL hits cache (mock db query count)
- [ ] run pytest -m smoke

### Task 45: Add cache invalidation on user progress update

**Files:**
- Modify: `app/study/services/stats_service.py`
- Modify: `app/curriculum/services/curriculum_cache_service.py`

- [ ] identify what caches store per-user data
- [ ] add cache.delete(key) calls after progress-mutating operations
- [ ] write test: updating progress then fetching stats returns fresh data not stale cache
- [ ] run pytest -m smoke

### Task 46: Add .env.example update with all current environment variables

**Files:**
- Modify: `.env.example`

- [ ] grep config/settings.py for all `os.getenv(` calls
- [ ] compare found keys with entries in .env.example
- [ ] add any missing keys with descriptions (# comment)
- [ ] remove obsolete keys no longer referenced
- [ ] run pytest -m smoke (no code change, just verify nothing broke)

### Task 47: Fix grammar topic unique slug constraint — friendly error

**Files:**
- Modify: `app/grammar_lab/routes.py`

- [ ] read grammar topic creation handler
- [ ] wrap db.session.commit() in IntegrityError catch for slug uniqueness
- [ ] return 409 `{'error': 'slug_taken'}` with suggestion to append suffix
- [ ] write test: creating topic with duplicate slug returns 409
- [ ] run pytest -m smoke

### Task 48: Add test for correct DAU/WAU calculation via UNION 6 tables

**Files:**
- Create: `tests/admin/test_activity_metrics.py`

- [ ] write test that inserts activity records in each of the 6 tables
- [ ] call `_count_active_users_in_range()` and verify count is correct
- [ ] write test: user active in multiple tables counted once
- [ ] run pytest -m smoke

### Task 49: Add test coverage for notification creation service

**Files:**
- Create: `tests/notifications/test_services.py`

- [ ] test notification created when user preference flag is True
- [ ] test notification NOT created when flag is False
- [ ] test notification dropdown content rendered via textContent (not innerHTML)
- [ ] run pytest -m smoke

### Task 50: Validate datetime input parameters in routes

**Files:**
- Modify: `app/api/daily_plan.py`
- Modify: any routes accepting `date` or `start_date` params

- [ ] grep routes for `request.args.get('date')` usage
- [ ] add try/except around `datetime.fromisoformat(raw)` with 400 on ValueError
- [ ] write test: malformed date param returns 400
- [ ] run pytest -m smoke

### Task 51: Add missing `@login_required` guards

**Files:**
- Modify: routes identified by grep for `@bp.route` without preceding `@login_required`

- [ ] grep all blueprint route files for routes missing auth decorators (focus on study, words, grammar_lab)
- [ ] add `@login_required` where the route serves user-specific data
- [ ] write test: unauthenticated GET to protected route returns 302 to login
- [ ] run pytest -m smoke

### Task 52: Add test for SRS review with 0 items (edge case)

**Files:**
- Modify: `tests/grammar_lab/test_grammar_srs.py`

- [ ] add test: `get_due_items(user_id)` with no due items returns empty list not None
- [ ] add test: submitting review with empty due items returns appropriate response
- [ ] run pytest -m smoke

### Task 53: Fix template variable defaults for optional context vars

**Files:**
- Modify: templates that use optional context variables without `| default()`

- [ ] grep templates for `{{ [a-z_]+ }}` patterns (single variable without filter)
- [ ] identify which of these are sometimes absent from render context
- [ ] add `| default('')` or `| default(none)` appropriately
- [ ] run pytest -m smoke

### Task 54: Add unit tests for words score/ranking service

**Files:**
- Modify or create: `tests/words/test_word_scorer.py`

- [ ] verify 100% coverage already exists (per memory: word_scorer 14->100%)
- [ ] if gaps found, add missing edge case tests
- [ ] add smoke marker to one test
- [ ] run pytest -m smoke

### Task 55: Add test for repair mission degradation edge case

**Files:**
- Modify: `tests/daily_plan/test_service.py` (from task 26)

- [ ] test: Repair mission with 0 SRS and 0 grammar returns Progress mission (not None)
- [ ] test: assembler failure emits warning log (use caplog)
- [ ] run pytest -m smoke

### Task 56: Verify migration chain has single head

**Files:**
- Examine: `migrations/versions/`

- [ ] run `alembic heads` and verify single head exists
- [ ] if multiple heads, create merge migration: `alembic merge heads -m "merge_heads"`
- [ ] run `alembic check` to verify chain
- [ ] write CI test: `alembic check` exits 0
- [ ] run pytest -m smoke

### Task 57: Add Alembic docstrings to recent migration files

**Files:**
- Modify: `migrations/versions/*.py` (last 10 by mtime)

- [ ] read each migration file
- [ ] add module-level docstring: what schema change and why
- [ ] no test needed (documentation only)
- [ ] run pytest -m smoke

### Task 58: Add test for open redirect prevention (from task 3)

**Files:**
- Modify: `tests/auth/test_auth_routes.py`

- [ ] add test: login with `next=https://evil.com` redirects to home not evil.com
- [ ] add test: login with `next=/study/` redirects correctly
- [ ] run pytest -m smoke

### Task 59: Add missing type hints to daily_plan module

**Files:**
- Modify: `app/daily_plan/service.py`
- Modify: `app/daily_plan/level_utils.py`
- Modify: `app/daily_plan/mission_types.py` (if exists)

- [ ] read each file; annotate all public function signatures
- [ ] verify `python -c "import app.daily_plan.service"` succeeds
- [ ] run pytest -m smoke

### Task 60: Add frontend form validation for study session settings

**Files:**
- Modify: `app/templates/study/session_settings.html` (or equivalent)
- Modify: relevant JS

- [ ] read template; identify form fields with only HTML5 validation
- [ ] add JS validation with visual error messages (using existing CSS error classes)
- [ ] test: submitting empty required field shows inline error without page reload
- [ ] run pytest -m smoke

### Task 61: Add test for admin audit log (from task 34)

**Files:**
- Modify: `tests/admin/test_audit.py`

- [ ] test: admin delete user action creates AdminAuditLog record
- [ ] test: audit log entry includes admin_id, action string, timestamp
- [ ] run pytest -m smoke

### Task 62: Add gzip test for health endpoint and API response

**Files:**
- Modify: `tests/test_health.py` or `tests/api/test_compression.py`

- [ ] test: GET /health with Accept-Encoding: gzip returns compressed response
- [ ] test: large GET /api/... response has Content-Encoding: gzip header
- [ ] run pytest -m smoke

### Task 63: Add test for batch admin operations partial success

**Files:**
- Create: `tests/admin/test_batch_operations.py`

- [ ] test: batch import with 1 valid + 1 invalid record returns `{'success': 1, 'errors': [...]}`
- [ ] test: batch with all valid records returns `{'success': N, 'errors': []}`
- [ ] run pytest -m smoke

### Task 64: Fix notification dropdown to consistently use textContent not innerHTML

**Files:**
- Modify: templates containing notification dropdown JS

- [ ] grep JS in templates for notification rendering with innerHTML
- [ ] replace with DOM API (createElement + textContent)
- [ ] run pytest -m smoke

### Task 65: Add test for duplicate email registration (from task 41)

**Files:**
- Modify: `tests/auth/test_auth_routes.py`

- [ ] add test: POST /register with existing email returns 400 and error key 'email_taken'
- [ ] add test: DB session is clean after duplicate registration attempt
- [ ] run pytest -m smoke

### Task 66: Add test for pagination on word list endpoint (from task 18)

**Files:**
- Create: `tests/words/test_pagination.py`

- [ ] test: GET /words?page=1&per_page=10 returns 10 items with total count
- [ ] test: GET /words?page=99 returns empty items list not 500
- [ ] test: per_page > 200 is clamped to 200
- [ ] run pytest -m smoke

### Task 67: Add test for slow query logger (from task 25)

**Files:**
- Create: `tests/test_slow_query_logging.py`

- [ ] mock time.time to make query appear to take 200ms
- [ ] assert logger emits 'slow_query' level warning
- [ ] run pytest -m smoke

### Task 68: Run full test suite and verify coverage >= 60%

**Files:**
- No file changes

- [ ] run `pytest --tb=short -q`
- [ ] run `pytest --cov=app --cov-report=term-missing -q`
- [ ] document final pass/fail count and coverage %
- [ ] if coverage < 60%, identify the largest uncovered modules and file follow-up tasks

### Task 69: Update CLAUDE.md with new patterns from this plan

**Files:**
- Modify: `CLAUDE.md`

- [ ] add entry: `api_error()` helper in app/api/errors.py for standardized errors
- [ ] add entry: `is_safe_url()` in app/utils/validators.py for redirect validation
- [ ] add entry: `chunk_ids()` in app/utils/db_utils.py for large IN() queries
- [ ] add entry: AdminAuditLog pattern for admin mutations
- [ ] move this plan to `docs/plans/completed/`
- [ ] run pytest -m smoke
