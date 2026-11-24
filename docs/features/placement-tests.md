# Optional English placement

The website (`/placement`) and native clients share one account-owned diagnostic service. The onboarding wizard and profile link to it. It does not submit course lessons or award XP. Speaking and free writing are not assessed.

Two modes are available: quick (14 questions, approximately 5–7 minutes) and detailed (24 questions, approximately 15–20 minutes). Duration is an estimate, with no timer. Both cover grammar, vocabulary, reading and listening. Detailed verification also includes two controlled sentence-writing tasks with authored accepted answers. Results are preliminary starting recommendations, not a certified CEFR assessment.

## Attempts and level changes

A learner may have one active attempt. Starting the same mode resumes it; switching modes requires explicit abandonment. The attempt references an immutable bank version, so publishing a replacement cannot change an in-progress test. Question order and shuffled options are saved. Question IDs are opaque, attempt-local nonces; private bank keys, question levels and per-answer verdicts are not returned.

Answers are final once accepted. Replaying the exact answer returns the current projection, including after the last question; changing an accepted answer returns 409. Drafts only apply to the current question. Clients persist an account-scoped pending answer before sending it, and resend that body after a lost response. Test answers do not enter the general offline course-submission queue. Browser writes require CSRF and bind the page account to the request; native endpoints require a Bearer token.

The recommendation only takes effect after the learner explicitly chooses it. For an unonboarded account, it sets the initial level. For an established account, it schedules a starting-level change for the next canonical study day. Applying it does not delete completed lessons or change today's snapshot. Activation checks learning activity: if the next day has already started, it postpones the change by another day; otherwise it rebuilds the day's unstarted snapshot instead of rolling yesterday's lessons forward. Completed curriculum progress remains authoritative. Placement is not a way to reset course history.

## Adaptive pilot policy

Two A1 warm-ups precede three four-question blocks (one per core domain). A block passes with at least three correct answers, including reading and listening. Difficulty moves up or down; the result is conservative when a higher block fails. Detailed mode adds ten verification questions at the candidate level: two per domain including controlled writing. Verification requires at least seven correct, with at least one correct reading, listening and writing item; otherwise the candidate decreases one level. A1 is the lower bound, C1 the upper bound.

This rule-based pilot is not a calibrated psychometric model. Bank revisions and aggregate results can support later difficulty calibration. Do not describe the recommendation as a certificate or a measurement of spoken fluency.

## Routes

Browser status and mutations: `/onboarding/placement/v2/status`, `/start`, `/<attempt_id>/answer`, `/draft`, `/apply`, `/abandon`. Native equivalents begin `/api/native/placement/`. All responses are private/no-store. An answer body is `{question_id, answer, dont_know}`; a draft body is `{question_id, answer}`. Apply and abandon take an empty JSON object.

Status exposes `available`, `modes`, `active`, `latest`, `pending_level`, `pending_on`. A projection contains the attempt identity, mode, status, count, optional current question and optional result. A result contains the recommended level, domain counts, weak topics and explicit unassessed-skill flags. An apply receipt includes `effective_on` (null for immediate initial selection).

## Deployment and private bank

Deploy code and run `flask db upgrade` **before** starting the updated web/scheduler processes: the User model gains two nullable columns. Migration head is `20261124_placement_tests`. New tables are `placement_banks` and `placement_attempts`.

Educational questions and answers are private. They are delivered separately, never committed with code. Install from a private file in the container:

```sh
flask placement-bank-install --pack /app/instance/placement_bank.json
flask placement-bank-install --pack /app/instance/placement_bank.json --apply
```

The first command validates without changing the database. The second stores and activates an immutable SHA-256 version. Repeating it is safe. Existing attempts keep their original bank. Retain old bank rows while attempts reference them. Without an active bank, the chooser explains unavailability and manual level selection remains available.

The validator requires every A1–C1 level and all five domains, enough distinct questions for the worst adaptive path, bounded strings, valid choice keys, reading passages and local listening audio URLs. Minimum total is 120 items (per level: 6 grammar, 6 vocabulary, 5 reading, 5 listening, 2 writing). Audio files must already be deployed; the import validates paths, not remote availability. Do not add speech capture or TTS to this feature.

Tests use synthetic banks. Keep the authored production bank out of public repositories, main native bundles, screenshots and API logs.
