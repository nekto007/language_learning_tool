---
# Production Security & Stability Hardening

## Overview

Устранение критических проблем безопасности и стабильности перед запуском в продакшн. Фокус: error pages, open redirect, SMTP debug, health check, silent exception handling, unsafe innerHTML, unbounded cache.

## Context

- Files involved: `app/__init__.py`, `app/middleware/security.py`, `app/utils/email_utils.py`, `app/admin/utils/cache.py`, `app/curriculum/middleware.py`, `app/words/routes.py`, `app/curriculum/routes/admin.py`, `app/reminders/routes.py`, JS files with innerHTML, error templates
- Related patterns: security headers already in middleware, CSRF protection enabled, rate limiting configured
- Dependencies: none external

## Development Approach

- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Custom Error Pages (404, 403, 500)

**Files:**
- Create: `app/templates/errors/404.html`
- Create: `app/templates/errors/403.html`
- Create: `app/templates/errors/500.html`
- Modify: `app/__init__.py` (register error handlers)

- [x] Create minimal, user-friendly error templates using existing design-system.css
- [x] Register error handlers for 404, 403, 500 in app factory (return JSON for API requests, HTML for browser)
- [x] Write tests: verify each error code returns correct template and status code
- [x] Run project test suite - must pass before task 2

### Task 2: Fix Open Redirect via request.referrer

**Files:**
- Modify: `app/curriculum/middleware.py`
- Modify: `app/words/routes.py`
- Modify: `app/curriculum/routes/admin.py`
- Modify: `app/reminders/routes.py`

- [x] Replace all `redirect(request.referrer)` with safe alternatives: use `url_for()` fallback or validate referrer against app domain
- [x] Write tests: verify redirect destinations are always internal URLs
- [x] Run project test suite - must pass before task 3

### Task 3: Disable SMTP Debug Logging

**Files:**
- Modify: `app/utils/email_utils.py`

- [x] Change `server.set_debuglevel(1)` to `server.set_debuglevel(0)` (or make configurable via env var, default off)
- [x] Write test: verify debug level is 0 in production config
- [x] Run project test suite - must pass before task 4

### Task 4: Add Health Check Endpoint

**Files:**
- Modify: `app/__init__.py` or create route in appropriate blueprint

- [ ] Add `/health` endpoint that checks DB connectivity and returns JSON status
- [ ] Exempt from authentication and CSRF
- [ ] Write tests: verify endpoint returns 200 with DB up, appropriate error structure
- [ ] Run project test suite - must pass before task 5

### Task 5: Fix Unsafe innerHTML in JavaScript

**Files:**
- Modify: `app/static/js/daily-plan-next.js`
- Modify: `app/static/js/word-translator.js`
- Audit: other JS files with innerHTML

- [ ] Audit all innerHTML assignments - identify which receive user-controlled data
- [ ] Replace unsafe innerHTML with textContent/DOM methods or add escapeHtml() where HTML is needed
- [ ] Write tests: verify escaping works for special characters in relevant templates
- [ ] Run project test suite - must pass before task 6

### Task 6: Audit and Fix Silent Exception Swallowing

**Files:**
- Multiple files (74 files, 326 occurrences of `except Exception`)

- [ ] Audit top-priority files: routes, services, middleware - identify cases that silently swallow errors (pass/continue without logging)
- [ ] Add `logger.exception()` or `logger.error()` to silent handlers (do NOT change control flow, only add logging)
- [ ] Write tests: verify that exceptions in critical paths are logged
- [ ] Run project test suite - must pass before task 7

### Task 7: Bound the Admin Cache

**Files:**
- Modify: `app/admin/utils/cache.py`

- [ ] Add max_size limit (e.g. 100 entries) with LRU eviction
- [ ] Add periodic cleanup of expired entries (not just on access)
- [ ] Write tests: verify cache eviction works when max_size exceeded
- [ ] Run project test suite - must pass before task 8

### Task 8: Verify Acceptance Criteria

- [ ] Run full test suite: `pytest`
- [ ] Verify no new security warnings in test output
- [ ] Manual checklist: hit /nonexistent (404), /health (200), verify no SMTP debug in logs

### Task 9: Update Documentation

- [ ] Update CLAUDE.md if internal patterns changed (health endpoint, error handlers)
- [ ] Move this plan to `docs/plans/completed/`
