# Phase 1 Go/No-Go Evaluation

**Status: PENDING — requires 2 weeks of production data**

## What to measure

### 1. Continuation rate
- Numerator: users who clicked next-step after reaching day_secured
- Denominator: users who reached day_secured
- Events: `next_step_accepted` / (`day_secured` state reached)

### 2. Session length delta
- Compare: average session_length for users with next-step feature vs pre-feature baseline
- Source: `session_ended_at_minimum` event timestamp vs last activity timestamp

### 3. D7 retention delta
- Compare: D7 return rate for users exposed to Phase 1 feature vs matched control (or pre-feature cohort)
- Use: cohort analysis by first_seen_with_feature date

## Pass/fail thresholds (from H1)

| Metric | Pass threshold | Action if not met |
|--------|---------------|-------------------|
| Continuation rate lift | ≥ 15% vs baseline | Adjust recommendation logic or stop |
| Session length | No regression | Investigate and fix |
| D7 retention | No regression | Investigate and fix |

## Decision

Fill in after 2 weeks of data:

- [ ] Continuation rate result: ___% (baseline: __%, lift: __%)
- [ ] Session length result: ___ min (baseline: ___ min)
- [ ] D7 retention result: ___% (baseline: __%)
- [ ] H1 threshold met? Y / N
- [ ] Decision: proceed to Phase 2 / adjust recommendation logic / stop

## Notes

(Add observations here after data collection)
