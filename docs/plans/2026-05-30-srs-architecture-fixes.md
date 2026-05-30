---
# SRS Architecture: Unify Grading, Counting, and Card Creation

## Overview

Address the architectural fragmentation documented in
`docs/audit/srs-audit-2026-05-29.md`. The SRS system has two SM-2
implementations diverging in `ease_factor` increment + `first_reviewed`
write, three uncorrelated due-card counters disagreeing on what "due"
means, four hardcoded `ease_factor=2.5` constants, and an `update`
write-path that commits inside the helper — breaking composable
transactions.

Target end state:

- Single canonical SM-2 grader: `UnifiedSRSService.grade_card` correctly
  writes `first_reviewed`, does not commit internally, and is the only
  way the application updates `UserCardDirection` review fields.
- Single canonical due-card counter: `app/srs/counting.py` functions are
  the only "what's due" source — `SRSService.get_card_counts`,
  `BookSRSIntegration._filter_due_cards`, and
  `BookSRSIntegration.get_due_cards_count` route through the same logic
  with state-based filtering (`card.state != CardState.NEW.value`) and
  the same `now` cutoff instead of the legacy `end_of_today` window or
  the `repetitions == 0` proxy.
- All `UserCardDirection` creation paths use `DEFAULT_EASE_FACTOR` from
  `app/srs/constants.py` instead of hardcoded `2.5`, create both
  directions (`eng-rus` + `rus-eng`), and flush rather than commit.
- All grading callers are responsible for their own commits — no helper
  inside the SRS stack issues `db.session.commit()`.

H1 from the audit ("leech auto-suspend missing") is already resolved
and is not part of this plan.

## Context

- Files involved:
  - `app/srs/service.py` — `UnifiedSRSService.grade_card`, `calculate_sm2_update`, `_handle_new/learning/review/relearning`
  - `app/srs/counting.py` — `count_due_cards`, `count_new_cards_today`, `count_reviews_today`, `get_new_card_budget`
  - `app/srs/constants.py` — `DEFAULT_EASE_FACTOR`, `LEARNING_STEPS`, `LEECH_THRESHOLD`
  - `app/study/models.py` — `UserCardDirection.update_after_review`, `_handle_new_card`, `_handle_learning_card`, `_handle_review_card`, `_handle_relearning_card`
  - `app/study/services/srs_service.py` — `SRSService.get_card_counts`, `get_adaptive_limits`
  - `app/curriculum/services/srs_service.py` — `get_cards_for_lesson`, `create_srs_session_for_lesson`
  - `app/curriculum/services/book_srs_integration.py` — `_filter_due_cards`, `get_due_cards_count`, `process_card_grade`, `_get_or_create_card_direction`, `create_srs_session_for_lesson`
  - `app/curriculum/routes/srs_api.py` — `/api/v1/srs/due-count`
  - `app/curriculum/routes/card_lessons.py` — card creation (~line 129; eng-rus only — bug)
  - `app/books/vocab_pull.py` — `queue_vocab_as_srs` (hardcoded 2.5)
  - `app/auth/models.py` — `is_already_known` path (hardcoded 2.5, but writes `first_reviewed` correctly)
  - `app/study/routes.py` — uses `SRSService.get_card_counts` for dashboard/study widgets
  - `app/study/api_routes.py`, `app/study/game_routes.py`, `app/curriculum/card_service.py` — call `update_after_review`
  - `app/daily_plan/assembler.py` — `_has_guided_recall_content` uses legacy counter
- Related patterns:
  - `count_due_cards`, `get_new_card_budget` in `app/srs/counting.py` are the canonical due/budget functions.
  - `CardState` enum in `app/srs/constants.py` is the canonical NEW/LEARNING/REVIEW/RELEARNING marker.
  - Naive-UTC convention: `UserCardDirection.next_review/first_reviewed/last_reviewed` are naive `DateTime`; compare against `datetime.now(timezone.utc).replace(tzinfo=None)`.
  - `StreakEvent`-based XP idempotency in `app/daily_plan/linear/xp.py`.
- Dependencies: none external.

## Development Approach

- **Testing approach**: Regular (code first, then tests).
- Complete each task fully before moving to the next.
- **CRITICAL: every task MUST include new/updated tests.**
- **CRITICAL: all tests must pass before starting next task.**
- Each phase is one or more tasks. Phase boundaries map to commit
  boundaries so the audit's HIGH issues are fixed in early commits and
  can be deployed independently of the larger refactor.
- After each task: `pytest -m smoke` MUST pass, plus the targeted suite
  for the area touched (`tests/srs/`, `tests/study/`, `tests/curriculum/`,
  `tests/daily_plan/`).

## Implementation Steps

### Task 1: Phase 0 — Fix `first_reviewed` in canonical grade_card (H2)

**Files:**
- Modify: `app/srs/service.py`
- Modify: `tests/srs/test_srs_service.py` (or add new test file)

- [x] In `UnifiedSRSService.grade_card`, set `card.first_reviewed = datetime.now(timezone.utc).replace(tzinfo=None)` when the card has no prior `first_reviewed` (state was NEW), before the SM-2 update is applied
- [x] Verify `last_reviewed` is also naive-UTC (audit flagged `datetime.now(timezone.utc)` directly — fix to `.replace(tzinfo=None)`)
- [x] Confirm `count_new_cards_today` in `app/srs/counting.py` now sees canonical-graded NEW→REVIEW cards (existing test counts NEW cards via `first_reviewed`)
- [x] Write tests: NEW card graded via canonical path → `first_reviewed` is set; `count_new_cards_today` returns 1 after one canonical grade
- [x] Run `pytest tests/srs/ tests/curriculum/ -x` — must pass before task 2

### Task 2: Phase 1.a — Remove internal commit from grade_card (M1)

**Files:**
- Modify: `app/srs/service.py`
- Modify: `app/curriculum/routes/srs_api.py` (the only canonical caller — must add explicit commit)
- Modify: `tests/curriculum/` or `tests/srs/`

- [x] Replace `db.session.commit()` inside `grade_card` with `db.session.flush()`
- [x] Update the caller in `app/curriculum/routes/srs_api.py` to commit at the end of the request, after XP + notifications + plan recalc
- [x] Document the contract change at the top of `grade_card`: "caller commits"
- [x] Write tests: grading + XP + plan_secured fired in a single transaction; simulated exception after grade rolls back grading too
- [x] Run `pytest tests/srs/ tests/curriculum/ -x` — must pass before task 3

### Task 3: Phase 1.b — Add missing ease_factor increment to legacy path (M2)

**Files:**
- Modify: `app/study/models.py`
- Modify: `tests/study/test_user_card_direction.py` (or equivalent)

- [x] In `_handle_new_card` when rating=KNOW (NEW → REVIEW): `self.ease_factor = min(MAX_EASE_FACTOR, self.ease_factor + EF_INCREASE_EASY)`
- [x] In `_handle_learning_card` graduation (last learning step → REVIEW): same increment
- [x] Reuse `MAX_EASE_FACTOR` and `EF_INCREASE_EASY` from `app/srs/constants.py` (do not redeclare local copies)
- [x] Write tests: NEW + KNOW raises ease_factor by +0.15 (capped at MAX); LEARNING graduation raises by +0.15
- [x] Run `pytest tests/study/ tests/srs/ -x` — must pass before task 4

### Task 4: Phase 1.c — Set first_reviewed in legacy update_after_review (consistency)

**Files:**
- Modify: `app/study/models.py`
- Modify: `tests/study/`

- [x] Verify `first_reviewed` set logic remains correct in legacy path after the changes from task 3 (legacy already sets it; just regression-test)
- [x] Write tests: legacy `update_after_review` on NEW card → `first_reviewed` set; subsequent grades do not overwrite it
- [x] Run `pytest tests/study/ -x` — must pass before task 5

### Task 5: Phase 2.a — Replace SRSService.get_card_counts with canonical counter (H3)

**Files:**
- Modify: `app/study/services/srs_service.py`
- Modify: `app/study/routes.py` (dashboard widget + study page)
- Modify: `app/daily_plan/assembler.py` (`_has_guided_recall_content`, M5)
- Modify: `tests/study/`, `tests/daily_plan/`

- [x] Replace internal cutoff `end_of_today` with `now` (naive UTC)
- [x] Add state filter: `UserCardDirection.state.in_([LEARNING, RELEARNING, REVIEW])` — exclude NEW
- [x] Add buried filter: `(buried_until IS NULL) | (buried_until <= now)`
- [x] OR — replace the whole function with delegation to `count_due_cards(user_id, db)` plus the UI-specific shape adapter (return the same dict the routes expect)
- [x] Change `_has_guided_recall_content` in `app/daily_plan/assembler.py` to call `count_due_cards`
- [x] Write tests: NEW cards (just created) NOT counted; cards due tomorrow NOT counted; cards due in 1 minute counted; buried cards NOT counted
- [x] Run `pytest tests/study/ tests/daily_plan/ -x` — must pass before task 6

### Task 6: Phase 2.b — Fix `repetitions == 0` proxy in book and curriculum SRS (H4, B5)

**Files:**
- Modify: `app/curriculum/services/book_srs_integration.py`
- Modify: `app/curriculum/services/srs_service.py`
- Modify: `app/curriculum/routes/srs_api.py` (the `/due-count` endpoint also uses the proxy)
- Modify: `tests/curriculum/`

- [x] In `_filter_due_cards`: replace `card.repetitions == 0` test with `card.state == CardState.NEW.value`
- [x] In `get_cards_for_lesson`: same — replace `d.repetitions == 0` filter with `d.state == CardState.NEW.value`
- [x] In `get_due_cards_count`: same fix; also normalise to naive-UTC datetime convention (`datetime.now(timezone.utc).replace(tzinfo=None)`)
- [x] In `get_due_cards_count`: add `UserWord.status.in_(['new', 'learning', 'review'])` filter to match canonical counter behaviour
- [x] Write tests: card with `state=REVIEW, repetitions=0` (post-lapse) NOT counted as new; card with `state=NEW, repetitions=0` correctly counted as new
- [x] Run `pytest tests/curriculum/ -x` — must pass before task 7

### Task 7: Phase 3.a — Fix card_lessons.py to create both directions (M3)

**Files:**
- Modify: `app/curriculum/routes/card_lessons.py`
- Modify: `tests/curriculum/test_card_lessons.py`

- [x] At the card-creation site (~line 129), loop over both directions (`eng-rus` and `rus-eng`) when inserting `UserCardDirection`
- [x] Use `DEFAULT_EASE_FACTOR` (from `app/srs/constants.py`) instead of relying on the column default
- [x] Set `state=CardState.NEW.value` explicitly so the canonical counter logic picks it up
- [x] Write tests: completing a card lesson creates both `eng-rus` AND `rus-eng` rows; second invocation idempotent (no duplicates)
- [x] Run `pytest tests/curriculum/ tests/srs/ -x` — must pass before task 8

### Task 8: Phase 3.b — Replace hardcoded 2.5 with DEFAULT_EASE_FACTOR (L1)

**Files:**
- Modify: `app/curriculum/services/book_srs_integration.py`
- Modify: `app/books/vocab_pull.py`
- Modify: `app/auth/models.py`
- Modify: `tests/books/`, `tests/auth/`

- [x] In `_get_or_create_card_direction` (`book_srs_integration.py:~330`): replace `2.5` with `DEFAULT_EASE_FACTOR`
- [x] In `queue_vocab_as_srs` (`vocab_pull.py:~127`): same replacement
- [x] In `is_already_known` path (`auth/models.py:~196`): same replacement
- [x] Also covered `UserCardDirection.__init__` default in `study/models.py:403` (same L1 hardcode)
- [x] Write tests: each path uses constant; bumping `DEFAULT_EASE_FACTOR` in the test pushes the seeded value through (parameterised constant assertion)
- [x] Run `pytest tests/ -x` — must pass before task 9

### Task 9: Phase 4 — Remove mid-request commits from SRS helpers (L2)

**Files:**
- Modify: `app/curriculum/services/srs_service.py` (`get_cards_for_lesson` ~line 104, `create_srs_session_for_lesson`)
- Modify: `app/curriculum/services/book_srs_integration.py` (`create_srs_session_for_lesson` ~line 121)
- Modify: all callers — add commits at request boundary
- Modify: `tests/curriculum/`

- [x] Replace `db.session.commit()` with `db.session.flush()` inside the helpers
- [x] Identify all callers via grep (`grep -rn create_srs_session_for_lesson app/`) and ensure each commits at the route handler boundary
- [x] Document caller-commits contract in docstrings
- [x] Write tests: exception after `get_cards_for_lesson` rolls back the created `UserCardDirection` rows (verify with `db.session.rollback()` + recount)
- [x] Run `pytest tests/curriculum/ -x` — must pass before task 10

### Task 10: Phase 5.a — Add XP hook to book SRS grading (M4)

**Files:**
- Modify: `app/curriculum/services/book_srs_integration.py`
- Modify: `app/daily_plan/linear/xp.py` (may need new source key)
- Modify: `tests/curriculum/`

- [x] Decide whether book SRS gets its own XP key (`linear_book_srs`) or shares `linear_srs_global` — recommend separate key so the SRS slot's daily idempotency is not consumed by book practice
- [x] In `process_card_grade`: after `update_after_review` returns successfully, call the new XP awarder (best-effort try/except, do not block grading on XP failure)
- [x] Add idempotency via `StreakEvent(event_type='xp_linear', source='linear_book_srs')` per `(user, date)`
- [x] Write tests: grading book card credits XP once per day; second grade same day does not double-credit
- [x] Run `pytest tests/curriculum/ tests/daily_plan/ -x` — must pass before task 11

### Task 11: Phase 5.b — Evaluate SRS XP for matching/word-scramble games (L3)

**Files:**
- Modify: `app/study/game_routes.py`
- Modify: `tests/study/`

- [x] Decide: should matching/word-scramble outside the linear plan SRS slot credit `linear_srs_global`? Audit recommends evaluating, not necessarily implementing.
- [x] If yes: gate by minimum-card-count + accuracy threshold, then call `maybe_award_srs_global_xp`; if no, document the intentional gap inline.
- [x] Write tests for whichever decision lands
- [x] Run `pytest tests/study/ -x` — must pass before task 12

### Task 12: Phase 6 — Unify legacy callers onto canonical grade_card (HIGH, deferred)

**Files:**
- Modify: `app/study/api_routes.py` (~line 575)
- Modify: `app/study/game_routes.py` (~line 696)
- Modify: `app/curriculum/card_service.py` (~line 443)
- Modify: `app/curriculum/services/srs_service.py` (~line 247)
- Modify: `app/curriculum/services/book_srs_integration.py` (~line 471)
- Modify: `tests/` — broad coverage

- [ ] Treat as a high-risk migration. Recommendation: do NOT replace `update_after_review` calls outright. Instead refactor `update_after_review` to delegate to `UnifiedSRSService.calculate_sm2_update` internally so both surfaces share one SM-2 engine
- [ ] Keep `update_after_review` as a thin wrapper that also updates `UserWord` aggregate counters (those are not part of canonical `grade_card`)
- [ ] Write tests: parameterised grading scenarios (NEW+KNOW, LEARNING+DONT_KNOW, REVIEW+KNOW, RELEARNING+DONT_KNOW, leech threshold) — verify legacy and canonical produce identical SM-2 fields
- [ ] Run full `pytest` — must pass before task 13

### Task 13: Verify acceptance criteria

- [ ] Run full test suite: `pytest` → 0 failures
- [ ] Confirm `count_new_cards_today` correctly tracks cards graded via the canonical path (regression for H2)
- [ ] Confirm `count_due_cards` and `SRSService.get_card_counts` return identical due counts for the same user state (regression for H3 / M5)
- [ ] Confirm canonical and legacy grading paths produce byte-identical SM-2 fields for the parameterised scenarios from task 12
- [ ] Run smoke test: `pytest -m smoke`
- [ ] Manually verify dashboard SRS counter on staging — no overcounting, no NULL hide-outs

### Task 14: Update documentation

- [ ] Update `CLAUDE.md` Key Patterns section:
  - Update "Canonical SRS counting" pattern to mention that `SRSService.get_card_counts` now delegates to `count_due_cards`
  - Add "Canonical SRS grading" pattern documenting `UnifiedSRSService.grade_card` as the single SM-2 implementation
  - Note: `update_after_review` is retained as a UserWord-counter wrapper around `calculate_sm2_update`, not an independent SM-2 implementation
- [ ] Move `docs/audit/srs-audit-2026-05-29.md` to `docs/audit/completed/` (or annotate inline) indicating which findings landed in which task
- [ ] Move this plan to `docs/plans/completed/` after the final verification task is green
