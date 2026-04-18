# Phase 2 Go/No-Go Evaluation

**Status: PENDING — requires production data after Phase 2 rollout**

## Hypotheses being tested

- H2: Visible route progress (position + next checkpoint) increases D7 retention vs baseline with no route
- H5: Users who reach one checkpoint after minimum completion have 2x higher next-day return rate

## What to measure

### 1. D7 retention delta vs Phase 1 baseline
- Compare: D7 return rate for users with route board vs Phase 1 cohort (next-step only, no route)
- Source: cohort analysis by first_seen_with_route_board date
- Exclude: users who never reached day_secured (they never saw the route board)

### 2. Next-day return rate: checkpoint-reachers vs stopped-before-checkpoint
- Numerator: users who reached ≥1 checkpoint that session, returned next day
- Denominator: users who reached day_secured but stopped before first checkpoint, returned next day
- Source: `UserRouteProgress.checkpoint_number` at session end, next-day login
- Threshold: checkpoint-reachers must have ≥1.5x next-day return rate

### 3. Instructional validity check
- Query: for users who added route steps, what is the breakdown by phase category?
  - High-quality: learn, recall, use
  - Lower-quality: close, check (fast completions)
- If >60% of incremental steps are close/check: route weights need adjustment
- Source: phase completion events tagged with phase_kind

## Pass/fail thresholds (from H2 and H5)

| Metric | Pass threshold | Action if not met |
|--------|---------------|-------------------|
| D7 retention lift vs Phase 1 | ≥ any positive lift (no regression) | Investigate route board UX |
| Checkpoint next-day return rate | ≥ 1.5x vs stopped-before-checkpoint | Adjust checkpoint distance (shorten from 20 to 15 steps) |
| Instructional validity | ≥ 40% of route steps are learn/recall/use | Reweight step values, penalise cheap close/check steps |

## Decision

Fill in after production data collection:

- [ ] D7 retention result: ___% (Phase 1 baseline: __%, delta: +/-__%)
- [ ] Next-day return rate (checkpoint-reachers): __% vs stopped-before: __% (ratio: __x)
- [ ] Instructional validity: __% of route steps are learn/recall/use
- [ ] H2 threshold met? Y / N
- [ ] H5 threshold met? Y / N
- [ ] Instructional validity acceptable? Y / N
- [ ] Decision: proceed to Phase 3 / adjust route weights / stop

## Notes

(Add observations here after data collection)
