# First quiz round and deferred corrections

Owner approved implementation after the child's feedback, 2026-11-22.

## Policy

- Ignore case and punctuation when comparing quiz text. Missing words,
  negation and word order remain meaningful.
- Ordinary course quizzes and grammar: 50%; module final: 75%.
- Finish the entire independent first round, with immediate feedback after
  each answer. Do not demand an immediate correction or interrupt the round
  with forced theory. Final tests have no intermediate feedback or help.
- Save first answers and score. Assisted corrections do not create 100%
  accuracy or a second independent LessonAttempt.
- With mistakes, return to the daily plan: quiz 3 → SRS → reading →
  corrections for quiz 3 → dependent lesson 4. Corrections remain mandatory
  even when the independent score passed. Below 50%, first review relevant
  theory. Already completed lessons are not relocked by a voluntary repeat.
- Mobile sources remain local and ignored by Git.

## Native course API contract: deferred_v1

The rollout is opt-in: `GET /api/native/lessons/<id>?quiz_flow=deferred_v1`.
Final tests never opt into assisted correction. An already pending correction
is returned even without the query parameter. Activities currently keep their
existing compatible retry/check flow; the new course flow is signalled only
by `quiz_phase`.

First document: `quiz_phase: "first"`; existing questions, theory and token.
`POST .../submit` keeps the strict body `{session_token, answers}`. The signed
token determines the phase; do not add a client-supplied quiz_phase.
With mistakes the result has `completed:false, correction_pending:true`.
First score/passed/counts/feedback refer to independent answers. Close the
lesson and refresh the daily plan; do not immediately start corrections.

Pending GET: same lesson ID, `quiz_phase:"correction"`; questions contain
ONLY original wrong IDs (IDs need not be contiguous); no learning_steps.
`correction` metadata:

```
{attempt_id, first_score, first_passed,
 first_correct_count, first_total_count,
 previous_answers: {question_id: original_raw_answer},
 theory_required: bool}
```

Each text question has `correction_help` initially; check feedback returns
updated `correction_help`. The existing check body permits optional
`help_level:0..3` only during correction. Check remains read-only, so network
retries cannot advance assistance or write attempts/XP. Clients persist the
current level and corrected answers in their private account draft.

```
{level, segments:[{text:string, editable:bool}], hint:string, choices:[string]}
```

Segments are word tokens WITHOUT separating whitespace. Join their values
with one space to submit the full answer. Correct tokens are read-only;
editable tokens start with empty text. Preserve punctuation attached to a
token; the grader ignores it. Match/order/choice questions keep existing
controls and get no text segments.

- Level 0: preserve correctly aligned words, leave wrong/missing words empty.
- Level 1: additionally hint the first letter of the next missing word.
- Level 2+: progressively fill incorrect tokens, keeping at least one editable
  token so the learner still answers the learning target. Level 2 fills all
  remaining gaps except that final token, including long failed sentences.
- Level 3: choices apply to the SINGLE remaining editable word, never a whole
  sentence. If more than one gap remains, choices is empty.

Correction submit uses the same URL/body and ALL correction question IDs.
Only an entirely correct correction submission completes the lesson. Response
`score` and `passed` retain the FIRST score; `correct_count`, `total_count`
and `feedback` describe the CORRECTION questions. `completed:true` is the
completion signal, including an originally failed first round. The original
counts are in lesson.correction metadata. Clients must not infer score from
the correction counts. A failed correction submit stays pending.

Daily-plan kind stays `curriculum`; data includes `lesson_id`,
`quiz_phase:"correction"`, `quiz_attempt_id` and pending_count. Use phase /
attempt ID in the screen/draft identity so a cached first result cannot be
reused for corrections. Do not reorder SRS/reading on the client.

Server marker in LessonProgress.data.quiz_correction:
`{version:1, attempt_id, revision, status:pending|completed, first_score,
first_passed, first_correct_count, first_total_count, pending_ids,
first_answers, feedback, created_at}`. Progress stays in_progress until
corrections complete. Content revision, account, token and plan guards apply
to both phases; stale content must never grade against changed questions.
Errors are tagged with the first-round revision and attempt ID. Enrolling
legacy work or starting a changed revision archives older live diagnostics
without claiming they were corrected. Historical logs and answers remain.
Browser autosave/submit, legacy completion services and recovery cannot erase
or bypass a pending native correction; the browser asks to continue in the app.
Existing clients keep their old flow until they opt in. No DB migration is
required; deploy the new server code before rebuilding/installing the clients.

## Implementation tracking

- [x] Shared punctuation/case comparison and 50%/75% policy.
- [x] First/correction server documents, persistence and idempotency.
- [x] Deferred daily-plan ordering and dependency enforcement.
- [x] iOS first-round/correction screens and account draft safety.
- [x] Android first-round/correction screens and account draft safety.
- [x] API/state/UI verification and build artifacts (portrait iPad limitation below).

Backend verification: 333 API/browser/projection/plan checks and 605 isolated
service/PostgreSQL checks passed. All 86 grammar documents, 694 canonical
answers and 52 alternatives also validated against the shared grader.
Passing uses scores with two decimal places (49.75 must not become 50).

Mobile verification: 328 Swift tests, 5 iPhone UI cases and 4 iPad landscape
UI cases passed; both final simulator builds succeeded. Android: 197 unit /
HTTP / Compose checks and 46 emulator executions passed, including phone,
tablet, large system font and tablet landscape. APK and source archive:
`android/Distribution/LLT-English-0.1.0-test.4.apk` and
`android/Distribution/LLT-English-Android-0.1.0-test.4-source.zip`.
Android report: `android/Verification/deferred-20261122/summary.json`.

iPad portrait verification remains limited: XCTest taps/frame coordinates
failed before entering the lesson, including on a fresh simulator. The same
cases passed in landscape; product navigation was not changed to work around
automation. A manual CUA fallback could not open Simulator: the selected
Xcode installation does not contain its Simulator.app GUI. No portrait pass
or physical-device verification is claimed.

Local web restarted and `/health` returned `db:ok,status:ok`. Production
deployment/push were not performed. Mobile sources and artifacts remain
ignored and local.
