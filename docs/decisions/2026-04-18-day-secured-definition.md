# Day Secured — Definition and Edge Cases

Date: 2026-04-18
Status: DRAFT — to be locked before Phase 1 (Task 6) starts

---

## Exact Definition

A day is "secured" when all phases in the user's daily mission with `required=True` have a
completion record in `DailyPlanLog` for the current calendar day (in the user's local timezone).

Formally:

    day_secured = all(phase.required == False or phase.completed for phase in mission.phases)

The secured state is computed at read time from phase completion records; it is NOT stored as a
boolean on `DailyPlanLog` directly (Task 6 adds a `secured_at` timestamp that is written once,
when the final required phase is first marked complete, and never rewritten for the same calendar
day).

"Current calendar day" uses the timezone stored in `User.timezone` (defaulting to UTC). A day
rolls over at midnight local time, not UTC midnight. This prevents users in UTC+5 from having a
day that resets at a different wall-clock time than their experience suggests.

Which mission types count: all three — Progress, Repair, Reading. The secured threshold is always
"complete all required phases of today's selected mission." The mission type does not change the
definition; only the content of the required phases differs.

---

## Does completing only easy tasks secure the day?

Yes — IF those easy tasks are the required phases of the mission the system selected for today.

Rationale: the mission assembler already incorporates user state (repair pressure, weak grammar
points, SRS due load) when selecting and assembling phases. If the system selects a Progress
mission with recall phases, those are not "easy" in any absolute sense — they are the system's
validated minimum for this user today. Overriding that judgment at the "secured" gate would create
a second, unvalidated difficulty filter that undermines the assembler's learning model.

What "easy tasks" protection is NOT provided here: if a user manipulates the system into selecting
trivially low-difficulty content every day, that is an assembler problem (fix the assembler), not
a "secured" gate problem.

Exception: if a required phase has zero items due (e.g., a recall phase with no SRS cards due),
that phase is marked auto-complete by the assembler. Completing zero items does not secure the
day — see edge case 4 below.

---

## Does minimum optimize for streak preservation or learning quality?

Learning quality. Explicitly.

Streak preservation is a secondary benefit of completing the minimum, not the goal. The minimum
is designed so that completing it always delivers a real learning increment — not the smallest
possible interaction that avoids breaking a streak.

Operationally this means:
- Required phases must include at least one active retrieval step (recall, use, or check). A
  minimum that consists only of reading or close-reading phases does not satisfy learning quality.
  The assembler must enforce this; the "secured" gate trusts the assembler has done so.
- The minimum is not calibrated to minimize time-to-secured. It is calibrated to the smallest
  interaction that reliably improves retention for this user's current weak points.
- If a user's only goal is streak preservation, that motivation is acceptable as long as the
  content they complete to secure the day is instructionally valid. The system does not judge
  motivation — it enforces quality of content.

Tiebreaker: if a product decision must choose between "make minimum easier so more users complete
it (higher completion rate)" and "keep minimum at quality threshold (better learning gain)", the
metric hierarchy (learning gain > completion rate) decides: maintain quality, then work on
completion rate separately.

---

## Is minimum fixed or adaptive per user state?

Adaptive — within a bounded range.

The minimum is the set of required phases in today's mission. Because mission selection is
adaptive (mission type and phase composition depend on repair pressure, SRS load, CEFR level, and
last-day type), the minimum effort varies per user and per day.

Bounds:
- Lower bound: at least 1 required phase, and that phase must include active retrieval.
- Upper bound: no more than 4 required phases. Beyond 4, the assembler must mark additional
  phases as required=False (bonus).

The adaptive minimum is computed once per calendar day when the plan is first assembled. It does
not re-adapt mid-day if the user's state changes (e.g., if they complete SRS in a different app
and now have fewer cards due). Adapting mid-session would cause the secured threshold to move
under the user — which breaks the promise of a stable daily goal.

---

## Rewards at Minimum Completion vs Continuation

### Unlocks at minimum completion (day secured):

- Streak increment (the day counts toward the streak)
- Base XP for each completed required phase (per existing XP table: recall=15, learn=40, etc.)
- Streak multiplier applied to base XP
- Rank progress increment (plans_completed_total +1)
- "Day secured" badge shown in dashboard
- Rank-up notification (if threshold crossed)
- Mission badge checks triggered (mission_first, mission_week_perfect, etc.)

### Exclusive to continuation (after secured):

- Bonus XP from optional phases (bonus phase: 20% higher XP rate)
- Consecutive perfect-day multiplier (requires both secured AND continuation past minimum for
  N consecutive days — to be defined precisely in Task 6)
- Route progress advancement (checkpoint rewards, checkpoint notification)
- "Perfect day bonus" 50 XP (requires completing all phases including optional ones)
- Rival strip shown (Phase 3 only)
- Next-best-step queue shown (Phase 1+)

Principle: the day secured state is a real achievement worth celebrating, not a consolation prize.
Continuation rewards must add genuine value — they cannot be so dominant that not continuing feels
like failure.

---

## Edge Cases

### Edge case 1: User completes required phases but app crashes before secured_at is written

Behavior: on next load, the system recomputes day_secured from phase completion records. If all
required phase completion records exist, day_secured=True and secured_at is backfilled to the
timestamp of the last required phase completion record. The streak is not lost.

### Edge case 2: User completes the mission at 23:58 local time; network response arrives at 00:01

Behavior: the completion record timestamp is the server receipt time. If the server receipt is
after midnight local, the day is NOT secured for the previous day. The streak breaks. Rationale:
using server time is the only tamper-resistant option. Client-side timestamps can be manipulated.
This is disclosed to users who experience it as a rare edge case, not a design feature to exploit.

### Edge case 3: User's timezone changes mid-day (travel)

Behavior: the timezone used for day boundary calculation is the one stored at plan assembly time
(beginning of the user's day). Mid-day timezone changes do not retroactively shift the boundary.
The next assembled plan uses the new timezone.

### Edge case 4: A required phase has zero actionable items (e.g., no SRS cards due)

Behavior: the assembler must NOT include this as a required phase. If the assembler detects at
assembly time that a phase would have zero items, it either replaces it with a non-empty phase or
marks it required=False. A required phase with zero items is an assembler bug, not a "secured"
definition problem. The "secured" gate does not auto-complete zero-item phases.

### Edge case 5: User completes the same lesson twice in one day (replay gaming)

Behavior: only the first completion of a given (user_id, lesson_id) pair per day counts toward
phase completion. The lesson_safe flag does not override this; lesson replays within a day do not
generate additional phase completion credits.

### Edge case 6: Mission type switches mid-day (repair_pressure crosses threshold after plan assembled)

Behavior: mid-day mission switching is not allowed. The mission type is locked at assembly time
for the calendar day. Re-assembling mid-day would reset progress and break the secured threshold.
If the user explicitly requests a different mission, the system offers it as a new plan for
tomorrow, not today.

### Edge case 7: User is in cold start (no learning history, onboarding_level='A0')

Behavior: the assembler selects a Progress mission using onboarding_level as the CEFR proxy.
The minimum is the same definition (all required phases complete). Cold-start plans may have
shorter phases, but the "secured" gate applies identically.

### Edge case 8: User completes partial progress on a required phase (e.g., 3 of 10 SRS cards)

Behavior: partial phase completion does NOT secure the day. A phase is complete when 100% of
the items in that phase are completed. If the user leaves mid-phase, the day is not secured.
The dashboard shows phase progress (3/10) to encourage completion, but the secured state does
not change until the phase is fully done.

### Edge case 9: Bonus phase (required=False) accidentally has all items completed before required phases

Behavior: bonus phase completion does not satisfy required phase requirements. Day secured
requires all required=True phases done, regardless of what optional phases were completed first.

### Edge case 10: User has been inactive for >7 days (streak already broken)

Behavior: "day secured" still applies normally. The streak is already 0 or reset. Completing the
minimum today starts a new streak (streak=1). The secured gate does not change based on streak
history.

---

## Team Sign-off

Required before Task 6 (Phase 1 implementation) starts.

- [ ] Igor Korobko — product / engineering lead
