# Migration Readiness Report

_Generated for Task 2 of `docs/plans/2026-05-11-post-immersion-content-data-plan.md`._

## Migration Chain

- Total revisions in `migrations/versions/`: **63**
- Number of heads: **1** (asserted in `tests/migrations/test_migration_chain.py::test_single_head`)
- Current head revision: **`20260523_streak_shield`**
- Number of historical roots (`down_revision is None`): 6
  - Roots predate the merge migrations `f1e2d3c4b5a6_merge_all_current_heads`,
    `41c72a04754a_merge_heads`, and `05212962d037_merge_heads_before_profile_settings`
    which unify them into a single linear tail.
- Orphan parents: **none** (`test_no_orphan_parents` passes).
- Duplicate revision IDs across files: **none** (`test_no_duplicate_revisions` passes).

## Required New Tables — Migration Coverage

All immersion / linear-plan / 100-tasks tables that the immersion features
depend on have a `create_table` (or equivalent) call somewhere in the
migration tree. This is verified statically by
`test_new_immersion_tables_have_migrations`.

| table | migration |
| --- | --- |
| `listening_attempts` | `20260511_listening_attempts.py` |
| `user_writing_attempts` | `20260512_user_writing_attempt.py` |
| `pronunciation_attempts` | `20260517_pronunciation_attempt.py` |
| `user_reading_sessions` | `20260426_user_reading_session.py` |
| `user_reading_preference` | `20260420_add_linear_daily_plan.py` |
| `quiz_error_log` | `20260420_add_linear_daily_plan.py` |
| `grammar_theory_view` | `20260420_add_linear_daily_plan.py` |
| `word_collocations` | `20260513_word_collocations.py` |
| `vocab_annotations` | `20260514_vocab_annotation.py` |
| `cultural_notes` | `20260522_cultural_note.py` |
| `daily_challenges` | `20260522_daily_challenge.py` |
| `custom_word_lists` | `20260519_custom_word_list.py` |
| `lesson_feedback` | `20260523_lesson_feedback.py` |
| `user_route_progress` | `20260418_add_user_route_progress.py` |
| `daily_plan_log` | `20260418_add_daily_plan_log.py` |
| `daily_plan_events` | `20260418_add_daily_plan_events.py` |
| `daily_study_minutes` | `20260521_study_minutes.py` |

## Required User Default Columns — Migration Coverage

All four user-default columns referenced by the 100-tasks plan have
`server_default` declared in their migration. Verified statically by
`test_user_default_columns_have_migrations`.

| column | migration | server_default |
| --- | --- | --- |
| `daily_word_goal` | `20260518_learning_goals.py` | `'10'` |
| `weekly_lesson_goal` | `20260518_learning_goals.py` | `'5'` |
| `plan_difficulty` | `20260516_plan_difficulty.py` | `'normal'` |
| `streak_shield_active` | `20260523_streak_shield.py` | `false` |

## Backfill Drift

No null/default drift was detected for any of the four columns:

- Every column was added with `nullable=False, server_default=...`,
  so existing user rows received the documented value at upgrade time.
- New users go through the SQLAlchemy default in `app/auth/models.py`.

**Conclusion:** no additional backfill script is required by this audit.
(Plan rule: "Do not add backfill scripts unless this audit proves null/default drift.")

## Test Results

```
$ pytest tests/migrations/ -q
......                                                                   [100%]
```

6 tests, 0 failures:

- `test_no_orphan_parents`
- `test_single_head`
- `test_user_lesson_progress_migration_present`
- `test_new_immersion_tables_have_migrations` (added by this audit)
- `test_user_default_columns_have_migrations` (added by this audit)
- `test_no_duplicate_revisions` (added by this audit)