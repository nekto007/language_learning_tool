# Falsifiable Hypotheses for Infinite Learning Loop

**Status:** Locked for Phase 1 start
**Date:** 2026-04-18

---

## H1: Next-step recommendation increases same-session continuation

Hypothesis: Showing 1 recommended "next step" after minimum completion increases same-session continuation rate by ≥15%.

Definition: Continuation rate = (users who start at least one task after day_secured) / (users who reach day_secured in a session).

Measurement method:
- Instrument next_step_shown, next_step_accepted, session_ended_at_minimum events (Task 8)
- Compare continuation rate in treatment group (sees next-step card) vs control group (sees only "Day secured" banner)
- A/B split: 50/50 random assignment at session start, held per user for test duration

Sample size needed: 200 users per arm (400 total) to detect a 15% lift with 80% power, alpha=0.05, assuming 30% base continuation rate.

Test duration: 2 weeks minimum (captures weekly learning rhythm variation).

Pass threshold: Treatment continuation rate ≥ Control continuation rate + 15 percentage points.

Fail threshold: lift < 10 pp after 3 weeks, or null result with n ≥ 400.

---

## H2: Visible route progress increases D7 retention

Hypothesis: Visible route progress (position + next checkpoint) increases D7 retention vs baseline with no route board.

Definition: D7 retention = fraction of users who log at least one session on day 7 after their first session in the measurement window.

Measurement method:
- Compare D7 for users who see route board (Phase 2 feature) vs Phase 1 baseline (same cohort, pre/post)
- Use pre/post cohort design: Phase 1 cohort = baseline, Phase 2 cohort = treatment
- Track route_state events to confirm users actually saw the board, not just had it enabled

Sample size needed: 300 users per cohort (600 total) to detect a 5pp D7 lift with 80% power, alpha=0.05, assuming 40% base D7 retention.

Test duration: 14 days after cohort entry to measure D7 (so ~3 weeks of enrollment + observation).

Pass threshold: Phase 2 D7 ≥ Phase 1 D7 + 5 percentage points.

Fail threshold: no improvement after 300+ users per cohort, or D7 drops.

---

## H3: Ghost rivals improve continuation depth without increasing churn

Hypothesis: Ghost rivals (no real user) improve continuation depth without increasing churn or stress indicators.

Definition:
- Continuation depth = average number of post-minimum phases completed per secured session
- Churn = user who was active in the prior 7 days and has 0 sessions in the next 7 days
- Stress indicator = rival_strip_dismissed / rival_strip_shown (dismissal rate proxy for stress)

Measurement method:
- Adults only, opt-in treatment group sees rival strip after day_secured
- Control group: same adult population, no rival strip
- A/B split: 50/50 random assignment held per user for test duration
- Track: rival_strip_shown, rival_strip_dismissed, steps_taken_while_rival_visible, session churn flag

Sample size needed: 150 users per arm (300 total adults only) to detect a 0.5 phase/session lift with 80% power; churn comparison requires same 150 per arm.

Test duration: 3 weeks (captures at least 2 weekly cycles and enough churn signal).

Pass threshold: Treatment continuation depth ≥ Control + 0.5 phases/session AND churn delta ≤ 0 AND dismissal rate < 30%.

Fail threshold: dismissal rate > 30%, or churn worsens by > 2pp, or no continuation lift.

---

## H4: Endless queue outperforms single next-step for continuation depth

Hypothesis: An endless queue of 5+ tasks outperforms a single "next best step" recommendation for continuation depth.

Definition: Continuation depth = average number of post-minimum phases completed per secured session.

Measurement method:
- Compare Phase 2 (3-task queue) vs Phase 1 (1-task recommendation) for continuation depth
- Pre/post cohort design: Phase 1 cohort = baseline, Phase 2 cohort = treatment
- Track: phases_completed_post_minimum per session for both cohorts

Sample size needed: 300 users per cohort (same as H2 sample, reuse if overlapping).

Test duration: 2 weeks per cohort (Phase 1 and Phase 2 run sequentially, not simultaneously).

Pass threshold: Phase 2 mean depth ≥ Phase 1 mean depth + 0.5 phases/session.

Fail threshold: no improvement after 300 users, or depth delta < 0.2 phases/session.

Note: H4 requires Phase 2 build (3-task queue) to test. It cannot be tested until Phase 1 validates H1. This is intentional — building the endless engine before proving H1 would be premature. H1 must pass before H4 is even relevant.

---

## H5: Reaching a checkpoint doubles next-day return rate

Hypothesis: Users who reach one checkpoint after minimum completion have 2x higher next-day return rate.

Definition:
- Checkpoint = crossing a 20-weighted-step boundary on the route board
- Next-day return = user opens a session the following calendar day

Measurement method:
- Within-cohort comparison (no separate control group needed): compare next-day return rate for users who reached checkpoint vs users who stopped before checkpoint on the same day
- Track: checkpoint_reached event, session_start events with date grouping
- Control for starting level of engagement (checkpoint-reachers are more engaged by selection; use regression adjustment if possible)

Sample size needed: 100 checkpoint-reachers and 100 non-reachers with matched engagement level. Expect ~30% of secured-day users reach checkpoint, so need ~300 secured-day users to get 100 reachers.

Test duration: 2 weeks (Phase 2 measurement window).

Pass threshold: next-day return rate for checkpoint-reachers ≥ 2x non-reachers (after engagement adjustment).

Fail threshold: ratio < 1.5x after 100+ reachers observed.

---

## Testability Order Confirmation

H1 (next-step recommendation): testable in Phase 1. Requires only a UI card and event tracking. No new models, no queue engine.

H2 (route board): testable in Phase 2. Requires route model and board UI. No rival system.

H3 (ghost rivals): testable in Phase 3. Requires rival strip UI. Depends on route board existing (Phase 2) but not on real rival matching or endless queue.

H4 (endless queue vs single step): testable in Phase 2 using 3-task queue vs Phase 1 baseline. Does NOT require building the full endless queue engine. The 3-task queue in Phase 2 is enough to test the concept.

H5 (checkpoint doubles return): testable in Phase 2 as a within-cohort observation. No additional build required beyond Phase 2 route model.

Conclusion: H1, H2, H3, and H5 all test the core behavioral questions (continuation, retention, rivalry, checkpoint effect) with minimal, incremental builds. H4 can be answered by the Phase 2 3-task queue without building the full endless engine. The full endless engine (Phase 4) is only justified if H4 shows more queue depth is needed beyond 3 tasks.
