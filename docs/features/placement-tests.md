# Optional English placement

The website (`/placement`) and native clients share one diagnostic service. The public landing page offers both modes without registration. Signed-in learners can enter from the homepage invitation, onboarding wizard or profile. It does not submit course lessons or award XP. Speaking and free writing are not assessed.

Two modes are available: quick (14 questions, approximately 5–7 minutes) and detailed (24 questions, approximately 15–20 minutes). Duration is an estimate, with no timer. Both cover grammar, vocabulary, reading and listening. Detailed verification also includes two controlled sentence-writing tasks with authored accepted answers. Results are preliminary starting recommendations, not a certified CEFR assessment.

## Attempts and level changes

A learner may have one active attempt. Starting the same mode resumes it; switching modes requires explicit abandonment. The attempt references an immutable bank version, so publishing a replacement cannot change an in-progress test. Question order and shuffled options are saved. Question IDs are opaque, attempt-local nonces; private bank keys, question levels and per-answer verdicts are not returned.

Answers are final once accepted. Replaying the exact answer returns the current projection, including after the last question; changing an accepted answer returns 409. Drafts only apply to the current question. Clients persist an account-scoped pending answer before sending it, and resend that body after a lost response. Test answers do not enter the general offline course-submission queue. Browser writes require CSRF and bind the page account to the request; native endpoints require a Bearer token.

The recommendation only takes effect after the learner explicitly chooses it. Before any learning activity in the current study day, it applies immediately and rebuilds the untouched snapshot. After learning activity has started, it schedules the change for the next canonical study day. Completed lessons and an already started snapshot are preserved. Activation checks learning activity: if the next day has already started, it postpones the change by another day; otherwise it rebuilds the day's unstarted snapshot instead of rolling yesterday's lessons forward. Completed curriculum progress remains authoritative. Placement is not a way to reset course history.

## Adaptive pilot policy

Two A1 warm-ups precede three four-question blocks (one per core domain). A block passes with at least three correct answers, including reading and listening. Difficulty moves up or down; the result is conservative when a higher block fails. Detailed mode adds ten verification questions at the candidate level: two per domain including controlled writing. Verification requires at least seven correct, with at least one correct reading, listening and writing item; otherwise the candidate decreases one level. A1 is the lower bound, C1 the upper bound.

This rule-based pilot is not a calibrated psychometric model. Bank revisions and aggregate results can support later difficulty calibration. Do not describe the recommendation as a certificate or a measurement of spoken fluency.

## Routes

Browser status and mutations: `/onboarding/placement/v2/status`, `/start`, `/<attempt_id>/answer`, `/draft`, `/apply`, `/abandon`. Native equivalents begin `/api/native/placement/`. All responses are private/no-store. An answer body is `{question_id, answer, dont_know}`; a draft body is `{question_id, answer}`. Apply and abandon take an empty JSON object.

Status exposes `available`, `modes`, `active`, `latest`, `pending_level`, `pending_on`. A projection contains the attempt identity, mode, status, count, optional current question and optional result. A result contains the recommended level, domain counts, weak topics and explicit unassessed-skill flags. An apply receipt includes `effective_on` (null for immediate initial selection).

## Deployment and private bank

Deploy code and run `flask db upgrade` **before** starting the updated web/scheduler processes: the User model gains two nullable columns. Migration head is `20261124_placement_personal`. In addition to banks/attempts, it adds guest identities, invitation preferences and targeted review queues. Attempts have exactly one owner: account or guest. Run the migration before new processes query these fields.

Educational questions and answers are private. They are delivered separately, never committed with code. Install from a private file in the container:

```sh
flask placement-bank-install --pack /app/instance/placement_bank.json
flask placement-bank-install --pack /app/instance/placement_bank.json --apply
```

The first command validates without changing the database. The second stores and activates an immutable SHA-256 version. Repeating it is safe. Existing attempts keep their original bank. Retain old bank rows while attempts reference them. Without an active bank, the chooser explains unavailability and manual level selection remains available.

The validator requires every A1–C1 level and all five domains, enough distinct questions for the worst adaptive path, bounded strings, valid choice keys, reading passages and local listening audio URLs. Minimum total is 120 items (per level: 6 grammar, 6 vocabulary, 5 reading, 5 listening, 2 writing). Audio files must already be deployed; the import validates paths, not remote availability. Do not add speech capture or TTS to this feature.

Tests use synthetic banks. Keep the authored production bank out of public repositories, main native bundles, screenshots and API logs.


## Anonymous ownership and transfer

A guest receives a random HttpOnly/SameSite cookie lasting seven days; only its SHA-256 hash is stored as the database owner. The signed Flask session stores the same token and a separate explicit handoff marker. A fresh browser session can restore the attempt from the durable guest cookie. Full domain results and recommendations are visible before signup.

`POST /placement/continue` requires CSRF and a completed guest result. It directs the learner to registration with a suggested level, or to login when the form selects `destination=login`. Only this explicit handoff authorizes the login signal to move guest attempts into the account. A pre-existing account attempt wins over an incoming active guest attempt. Completed results and accepted answers retain their contents. Claiming does not automatically apply a recommendation. A stale guest tab is rejected after account login.

Guest API writes retain CSRF protection and IP-based limits; native routes remain Bearer-only. Expired identities cannot read or mutate attempts. Run bounded cleanup regularly, for example an hourly invocation of `flask placement-guests-cleanup --apply --limit 5000`. Without `--apply`, it reports counts only. Claimed attempts are not deleted by guest cleanup.

## Voluntary homepage checks

`plan.placement_invitation` is optional. It exposes a stable key, kind (`initial`, `resume`, `result`, `checkpoint`), title, body, CTA and URL. Untested accounts receive an initial card, active attempts resume, and unapplied completed attempts offer their result. After **all** lessons across a CEFR level have actually been completed, a check is recommended without gating the next level or streak. Replaying an old completed lesson does not create another level checkpoint.

Browser/native `POST .../placement/dismiss` accepts `{key}` for the current invitation. Dismissal persists per account. The profile entry remains available, and an active attempt can always be resumed there even after its homepage card is dismissed.

## Targeted follow-up

Private bank items may provide an explicit `topic_slug` for grammar or controlled writing. A failed diagnostic item creates a candidate signal, not a whole-topic mastery verdict. Unmapped vocabulary, reading and listening findings remain informative; they are not converted into invented grammar exercises. Only existing public topics with at least three active exercises and a level no higher than the chosen recommendation qualify.

The next eligible plan includes at most one three-exercise review per day. It uses the canonical grammar graders and native `grammar_review` activity transport; the website uses cookie/CSRF wrappers around the same core. Exact queue ownership, content revisions, plan ordering, pause and nonce checks remain enforced. Completion belongs to that specific review rather than unrelated grammar activity.

The review replaces the last eligible course lesson (or filler) of at least the same ETA. It preserves the first course lesson, SRS and final tests, never increases required item count, and stays first optional when no replacement fits the chosen pace. A required review suppresses misleading weekly pace nudges caused by the substituted course lesson. Three first answers are scored independently of later assistance. Three correct answers retire the candidate; otherwise it returns after two days. This is a small practice check, not CEFR certification. A new applied test supersedes the previous queue once its chosen level takes effect.

Browser review routes: `/placement/review/<review_id>` and CSRF-protected `/onboarding/placement/review/<review_id>/{start,check,submit}`. Native clients use the existing `/api/native/activities/grammar_review/...` routes with the full server-provided item ID. Completed mini-practice has a return-to-plan action and no immediate repeat button.


## Direct public entry

The landing hero has two main actions: **Начать обучение** and **Проверить уровень языка**.
The second opens `/placement?start=1` and immediately starts a ten-question choice-only
screening. There is no mode chooser, passage or audio in this entry. A choice tap submits
that answer and advances; «Не знаю» remains available. The compact result provides one
primary learning/registration CTA and a smaller existing-account login link. Full 14/24
checks remain available in the profile; anonymous advanced access uses `?advanced=1`.

The short scope is `starter`: five grammar/vocabulary pairs beginning at A1. A pair must
have both answers correct to raise the candidate; one-domain success does not promote.
The result is a preliminary starting recommendation about vocabulary and grammar. It
does not infer reading, listening, speaking or free-writing performance. Existing private
banks already have enough distinct choice items; no bank reimport or schema migration is
needed for this change.

Transport: `POST .../placement/start` may add `scope: "starter"` to `mode: "quick"`.
Scope is frozen in attempt state; its projection adds `scope` and exact `question_count=10`.
`max_questions=14` remains the compatible quick upper bound for shipped native clients,
whose result validators accept a completed count below that bound. Comprehensive requests
without a scope retain their original behavior. Existing active long checks are resumed,
with an explicit confirmation offered before replacing them with a short attempt.

On the compact result, «Начать обучение» explicitly selects the shown recommendation
along with transferring the result. After signup/login, that saved consent applies the
level via the canonical adoption service. A novice's onboarding is completed with existing
defaults, so registration proceeds to the daily plan without another level-confirmation
screen. Started days still defer the level change, completed lessons remain authoritative,
and a more recent account result wins. A legacy full-result handoff does not auto-apply.
