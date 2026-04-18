# Instructional Validity Criteria

Date: 2026-04-18
Status: LOCKED (required before Phase 1 starts)

---

## 1. What "real learning" means in this system

Real learning = durable change in retrieval ability under variation.

A step counts as a learning step if it produces at least one of:
- A correct recall of a target item after a delay (retrieval practice)
- A correct application of a grammar rule to a novel sentence (not a seen example)
- A correct meaning inference without L1 translation support

Signals that indicate learning occurred:
- SRS card answered correctly at Grade ≥ 3 (SM-2 scale) on first attempt in the session
- Grammar exercise answered correctly on the first attempt for a pattern not seen in the same session
- Reading comprehension question answered correctly without re-reading the passage

Signals that do NOT count as learning:
- A card answered correctly after multiple attempts in the same session
- Completing a lesson phase by tapping through prompts without a recall challenge
- Reviewing a card already at interval > 21 days (over-review; diminishing returns)

Mastery signal: a card or grammar pattern is considered mastered when it achieves interval ≥ 21 days and the last 3 reviews were all Grade ≥ 4.

---

## 2. Product steps vs learning steps

Product step: any completed phase that moves the route counter and earns XP.
- Examples: finishing a close phase, completing a lesson module, dismissing a reading phase

Learning step: a product step that also meets the learning signal criteria above.
- Examples: correct SRS recall on first attempt, novel grammar application

A product step that does not meet the learning signal criteria still earns XP and moves the route, but at a reduced weight (see route weighting in Task 11). The distinction is tracked but not surfaced to the user to avoid creating anxiety around "low-quality" steps.

Ratio goal: at least 60% of a user's route steps should be learning steps. If ratio falls below 40% for a user over a 7-day window, the system should deprioritize cheap steps in the next-best-step recommender.

---

## 3. Anti-exploit rule

Route progress MUST be gated by learning signal, not raw task count.

Specific rules:
1. Completing the same grammar exercise set twice in one day counts as 1 route step, not 2. Repetition within a session has no route value.
2. A lesson phase that was already completed in a prior session and is being replayed (lesson-safe mode re-entry) earns route XP but does NOT advance the route step counter.
3. SRS cards reviewed at ease factor ≥ 2.5 and interval ≥ 14 days count as 0.5 route steps (not 1.0) — the user is maintaining, not learning.
4. Reading phases count as learning steps only when the passage has not been read before in the current calendar week.
5. A "close" phase counts as a product step but contributes 1 route weight unit (lowest tier). It cannot be farmed — closing the same session context twice gives 0 additional route weight.

These rules are enforced at route update time in the backend. The frontend never receives the raw step count, only the weighted totals.

---

## 4. Spacing quality requirements for endless mode

These apply when the continuation queue extends beyond the minimum plan (Phase 2+):

- No same card or grammar pattern twice in the same session, regardless of SRS schedule
- No more than 3 consecutive steps of the same category (e.g., no 4 SRS reviews in a row without a grammar or reading step interleaved)
- Over-reviewed cards (interval > 21 days, last review < 7 days ago) are suppressed from the continuation queue
- New cards (first exposure) cannot appear in the continuation queue within 10 minutes of first introduction — spacing buffer required
- If the SRS queue is exhausted, the system must not inject artificially "recalled" cards to fill the queue. Return fewer steps rather than low-quality filler.
- Reading passages must be selected from content the user has not seen, not re-queued passages. If no new passages exist at the user's level, reading steps are omitted from the queue.

---

## 5. Phase transition conditions

When does a learner move between phases of a learning sequence?

Exposure → Recall:
- Trigger: user has seen the item (card, grammar pattern) at least once in the current module
- Requirement: at least 1 complete session has elapsed since first exposure (no same-session exposure+recall)
- Gate: the item must not be in an "active lesson" context — lesson-safe mode keeps the learner in the exposure stream

Recall → Transfer:
- Trigger: card has been reviewed correctly in at least 3 separate sessions with correct Grade ≥ 3
- Requirement: at least 1 review at interval ≥ 7 days
- Transfer means: the item appears in a grammar exercise in a new sentence context, or in a reading passage the user has not seen

Transfer → Mastery (exit from active queue):
- Trigger: mastery signal met (interval ≥ 21 days, last 3 reviews Grade ≥ 4)
- The item moves out of the active continuation queue and into a maintenance schedule (reviewed at most once per month)

These transitions are implicit in the SRS schedule — the backend does not require a separate state machine. The phase names are used only for logging and for the route step weighting calculation.

---

## Sign-off

Required before Phase 1 implementation starts. Team lead must confirm:
- [ ] Learning signal definitions are aligned with actual SRS grade data we collect
- [ ] Anti-exploit rules are enforceable with current DB schema (no new tables needed for Phase 1)
- [ ] Phase transition conditions match the existing SRS interval progression in `app/words/` and `app/grammar_lab/`
