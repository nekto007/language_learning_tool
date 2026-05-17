# QA: Daily Plan Extension Slots Across CEFR Levels

## Purpose

Verify that the daily plan linear extension slots for listening, writing,
and speaking appear correctly for users at each CEFR level when the
current module contains the appropriate immersion lessons.

## Slot Types Under Test

| Slot kind  | Lesson types                                      |
|------------|---------------------------------------------------|
| listening  | `dictation`, `audio_fill_blank`, `listening_immersion` |
| writing    | `writing_prompt`, `translation`                   |
| speaking   | `shadow_reading`, `pronunciation`                 |

## CEFR Levels

| Code | Description      | Onboarding level |
|------|------------------|-----------------|
| A1   | Beginner         | A1              |
| A2   | Elementary       | A2              |
| B1   | Intermediate     | B1              |
| B2   | Upper-Intermediate | B2            |
| C1   | Advanced         | C1              |

## Test Matrix

For each CEFR level, the following is verified automatically via
`tests/daily_plan/linear/test_immersion_slots_cefr.py`:

- Listening slot appears when module contains a `dictation` lesson
- Writing slot appears when module contains a `writing_prompt` lesson
- Speaking slot appears when module contains a `shadow_reading` lesson
- All three slots are absent when the current module has no immersion lessons
- Each slot carries `level_code` in its data dict matching the module level
- `day_secured` is not blocked by incomplete extension slots

## Running the Tests

```
pytest tests/daily_plan/linear/test_immersion_slots_cefr.py -v
```

Expected: all tests pass for A1, A2, B1, B2, C1.

## Manual Verification Checklist

Use these steps to spot-check the plan on a staging instance after
importing immersion lessons via `scripts/import_immersion_lessons.py`.

- [ ] Log in as an A1 user whose current module has a dictation lesson
  - Navigate to /daily-plan
  - Confirm listening extension slot appears after completing baseline
  - Click the slot and complete the dictation
  - Confirm slot shows as completed on plan reload

- [ ] Repeat for A2, B1, B2, C1 users

- [ ] Log in as a user whose current module has a writing_prompt lesson
  - Complete baseline
  - Confirm writing extension slot appears
  - Submit writing and confirm UserWritingAttempt is created

- [ ] Log in as a user whose current module has a shadow_reading lesson
  - Complete baseline
  - Confirm speaking extension slot appears
  - Complete self-assessment and confirm LessonProgress is created

- [ ] Verify `day_secured` becomes True after baseline completion
  regardless of whether extension slots are present or completed

## Acceptance Criteria

- All automated tests pass
- No regression in existing listening/writing/speaking slot unit tests
- Extension slots do not appear for modules that have no immersion content
- Slots appear for all five CEFR levels without errors
