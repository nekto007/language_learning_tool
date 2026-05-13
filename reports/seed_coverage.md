# Seed Coverage Report

_Generated for Task 3 of `docs/plans/2026-05-11-post-immersion-content-data-plan.md`._

Source files inspected:

- `app/achievements/seed.py` — `INITIAL_ACHIEVEMENTS` list (64 codes total).
- `app/daily_plan/challenge.py` — `_BONUS_XP` dict keyed on
  `CHALLENGE_CATEGORIES` from `app/daily_plan/models.py`.

## Achievements

| domain | codes in seed | status |
| --- | --- | --- |
| Listening | `listening_first`, `listening_week`, `listening_master` | ✅ present |
| Writing | `writing_first`, `writing_streak_3`, `writing_fluent` | ✅ present |
| Speaking | `speaking_first`, `speaking_streak_3`, `speaking_clear` | ✅ present |
| Immersion | `immersion_daily`, `immersion_week` | ✅ present |
| Challenge | `challenge_first`, `challenge_streak_7`, `challenger` | ✅ present |
| Mission (already shipped) | 9 codes including `mission_first`, `mission_progress_5`, `mission_repair_5`, `mission_reading_5`, `mission_week_perfect`, `mission_early_bird`, `mission_night_owl`, `mission_variety_3`, `mission_speed_demon` | ✅ present |

No achievement codes from the immersion roadmap are missing from
`INITIAL_ACHIEVEMENTS`. Per the plan, no re-seeding is needed.

## DailyChallenge Categories

`CHALLENGE_CATEGORIES = ('speed_run', 'accuracy_focus', 'listening_deep')`
(see `app/daily_plan/models.py:230`).

| category | implemented in | bonus XP | status |
| --- | --- | --- | --- |
| `speed_run` | `_validate_speed_run` (challenge.py L280) | 50 | ✅ present |
| `accuracy_focus` | `_validate_accuracy_focus` (challenge.py L235) | 60 | ✅ present |
| `listening_deep` | `_validate_listening_deep` (challenge.py L219) | 40 | ✅ present |

No category mentioned in the plan is missing.

## Conclusion — Missing Seeds

**None.** Both seed surfaces (achievements + daily challenge categories)
are already complete and require no additional seeding work in this plan.