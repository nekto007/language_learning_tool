# Metric Hierarchy — Infinite Learning Loop

Date: 2026-04-18
Status: DRAFT — requires team sign-off before Phase 1 starts

---

## Competing Metrics

Listed in order of descending priority:

1. Learning gain — measurable retention improvement (recall accuracy under spaced repetition, accuracy under variation)
2. Minimum completion rate — percentage of users who complete the required daily minimum
3. D7 retention — 7-day return rate
4. D30 retention — 30-day return rate
5. Session length — time spent per session (secondary signal, can be gamed)
6. Child safety — no competitive framing, no stress induction for underage users (non-negotiable constraint, not a metric to optimize)
7. Rivalry fairness — ghost-only in Phase 3; real rival matching must be skill-segmented
8. Stress markers — user-reported difficulty, churn spikes, dismissal rates

---

## Priority Order with Tiebreaker Rules

Priority 1 (non-negotiable constraints — never sacrifice):
- Child safety: no child ever sees rival framing or competitive UI. If any path violates this, the feature is blocked regardless of any other metric.
- Instructional validity: route progress must map to validated learning steps. Features that move route position without learning signal are rejected.

Priority 2 (primary success metrics — these decide go/no-go):
- Learning gain: retention score improvement must not decrease phase-over-phase.
- Minimum completion rate: if it falls below pre-feature baseline, the feature is rolled back.

Priority 3 (growth metrics — these decide which direction to optimize):
- D7 retention: primary growth signal.
- D30 retention: secondary growth signal; used for Phase 3+ decisions.

Priority 4 (engagement signals — inform but do not override):
- Session length: useful as a supporting signal; a long session with no learning gain is not success.
- Rivalry fairness and ghost behavior: must not degrade engagement for non-rival users.

Priority 5 (health signals — trigger rollback if they worsen):
- Stress markers: if dismissal rate > 30% or churn worsens after feature launch, roll back.

Tiebreaker rule: when two metrics conflict, the higher-priority metric always wins. No exceptions.

---

## Conflict Cases

- If learning gain rises but D7 retention falls: outcome is ambiguous — investigate whether the learning gain is real or an artifact. Do not call it success.
- If D7 retention rises but learning gain falls: outcome is failure — retention without learning is a dark pattern. Roll back the feature.
- If minimum completion rate rises but session length falls: outcome is success — short efficient sessions with completion are the goal.
- If session length rises but minimum completion rate falls: outcome is failure — long sessions without completion signal frustration, not engagement.
- If D7 rises but stress markers worsen: outcome is failure — short-term retention gain driven by anxiety is not the product we are building.
- If rival strip raises continuation depth but dismissal rate exceeds 30%: outcome is failure — a feature most users dismiss is unwanted, regardless of the minority who benefit.
- If child safety constraint is violated by any feature variant: outcome is blocked — no other metric is weighed.
- If instructional validity falls (users earning route progress via cheap steps): outcome is failure — gamification without learning is explicitly out of scope.
- If D30 rises but D7 falls: outcome is ambiguous — may indicate irregular usage patterns; investigate before acting.
- If rivalry fairness degrades for low-skill users (ghost always far ahead): outcome is failure — the rival must be calibrated to stay slightly behind average progression.

---

## Team Sign-off

Required before Phase 1 implementation begins.

- [ ] Igor Korobko — product / engineering lead
