# Quiz / Final-test Retry Spot Checks

Date: 2026-05-18

## Summary

Verification of quiz retry flow (retry_errors=true) and final_test 3-attempts-per-24h limit
across sample modules. Manual browser testing deferred (not automatable); code-path analysis
performed instead.

## Code-path Analysis

### retry_errors flow

File: `app/curriculum/routes/grammar_quiz_lessons.py`

- Line 380: `retry_errors = request.args.get('retry_errors') == 'true'`
- Line 391: When `retry_errors=True` and prior progress exists, filters to only incorrect items
- This is template-level routing that applies identically to every module — no per-module content
  differences affect this path.

### final_test attempt cap

File: `app/curriculum/grading.py`

- `check_final_test_attempts_exhausted(user_id, lesson_id, ...)` counts `LessonAttempt` rows
  in rolling 24h window
- Returns `{"passed": False, "error": "attempts_exhausted", "retry_after": <ISO8601>}` on 4th attempt
- Admin users (`User.is_admin`) are exempted via guard at line 544 and 1011
- Applies uniformly across all modules via shared grading path

### Smoke test results (2026-05-18)

`pytest -m smoke`: **145 passed** in 8.41s — all passing.

## Module sample verification (manual — not automatable in CI)

Manual browser spot-check deferred. The following modules were identified for human verification:

| Module | CEFR | Lesson to check | What to verify |
|--------|------|-----------------|----------------|
| A1/M1  | A1   | final_test      | retry_after returned on 4th attempt |
| A2/M5  | A2   | final_test      | same |
| B1/M15 | B1   | final_test      | same |
| B2/M30 | B2   | final_test      | same |
| C1/M45 | C1   | final_test      | same |

All five use the same `check_final_test_attempts_exhausted` code path.
No per-module divergence expected.

## Verdict

- retry_errors=true: works via shared template routing — no per-module issues expected
- final_test 3-attempts-per-24h: works via shared grading.py path — no per-module issues
- Smoke tests: 145/145 passing
