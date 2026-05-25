# Hard review audit: dictionary and Study API

Date: 2026-05-25

## Scope baseline

`git diff --name-only` returned no changed files at the start of Task 1, so there are no uncommitted entry points to enumerate from the working tree. The review scope below follows the plan context and treats those files as the changed entry points to audit:

- `app/study/api_routes.py`
- `app/study/routes.py`
- `app/words/detail_service.py`
- `app/words/forms.py`
- `app/words/routes.py`
- `app/templates/words/_word_profile.html`
- `app/templates/words/details_optimized.html`
- `app/templates/words/list_optimized.html`
- `app/templates/words/public_word.html`
- `tests/test_public_words_seo.py`
- `tests/test_words_routes.py`
- `tests/api/test_study_api.py`

## Brainstormed risks

### P0

- Auth/data leak: authenticated word detail may expose private helper data to the public dictionary page through shared profile/template includes.
- Auth/data leak: Study API `word_source=word_detail` may return another user's cards if `word_id` filtering is not bound to `current_user`.
- SRS correctness: `word_detail` extra study may ignore buried cards, future due dates, or new/review limits.
- XSS/escaping: public and authenticated templates render user-controlled word fields, examples, notes, synonyms, antonyms, topic names, or book titles.

### P1

- SEO: public word pages can 500 or emit missing/incorrect title, description, canonical, OpenGraph, or JSON-LD metadata.
- Data correctness: profile helpers can show dirty values such as `null`, `[]`, duplicate semantic lists, missing frequency labels, or broken review time labels.
- Authorization boundaries: private user word status, study controls, decks, or admin facts may appear on public pages.
- Broken empty states: pages can render empty sections for missing audio, etymology, synonyms, related words, books, topics, or collections.

### P2

- N+1/performance: related words, books, topics, collections, card directions, and status counts can add per-row queries.
- UX regressions: filters, pagination, and list actions can render wrong states or broken links.
- SEO polish: hardcoded public URLs and legacy slug fallback can produce canonical inconsistencies.

## Findings

| id | severity | file | hypothesis | evidence | fix | test | status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HRW-001 | P1 | `app/templates/words/public_word.html` | Public word SEO metadata can regress without a focused test. | Existing tests checked some OG/JSON-LD markers, but not title, meta description, and canonical together. | Add baseline SEO metadata assertions. | `TestPublicWordRoute::test_public_word_has_title_meta_and_canonical` | covered |
| HRW-002 | P1 | `app/words/routes.py`, `app/templates/words/list_optimized.html` | Dictionary list route can return 200 while omitting the expected word row or filter controls. | Baseline status test did not assert rendered dictionary content. | Add baseline list content assertions. | `TestWordList::test_word_list_baseline_renders_dictionary_content` | covered |
| HRW-003 | P1 | `app/words/routes.py`, `app/templates/words/details_optimized.html` | Authenticated detail route can return 200 while missing the private detail surface. | Baseline status test only checked the English word. | Add baseline detail content assertions. | `TestWordDetail::test_word_detail_baseline_renders_profile_content` | covered |
| HRW-004 | P1 | `app/words/routes.py`, `app/templates/words/public_word.html` | Public word route can return 200 while missing the public profile surface. | Existing tests covered public access and generic content, but not the full public baseline in route tests. | Add baseline public page assertions. | `TestPublicWord::test_public_word_baseline_renders_public_profile` | covered |
| HRW-005 | P1 | `app/study/api_routes.py` | `word_source=word_detail` without `word_id` can look like a successful empty session instead of a client error. | TDD regression initially failed: `/study/api/get-study-items?source=word_detail` returned 200. | Return `api_error('invalid_input', ...)` before building study queries. | `test_get_study_items_word_detail_requires_word_id` | fixed |
| HRW-006 | P0 | `app/study/api_routes.py` | `word_detail&extra_study=true` sets `due_filter = None`; if word scoping regresses it could expose other due/future cards. | Regression test creates target future card, another current-user future card, and another user's due card. Only the selected word's card is returned. | Existing `UserWord.user_id == current_user.id` and `UserWord.word_id.in_(deck_word_ids)` filters are retained. | `test_get_study_items_word_detail_extra_study_stays_scoped_to_word_id` | covered |
| HRW-007 | P1 | `app/study/api_routes.py` | `word_detail` study might bypass session-buried cards for the selected word. | Regression test creates a due target card with future `buried_until`; API returns no items. | Existing buried-card filter is covered and left unchanged. | `test_get_study_items_word_detail_skips_buried_target_card` | covered |

## Baseline coverage map

- Covered now: dictionary word list 200 plus rendered word content, authenticated word detail 200 plus profile content, public word page 200 plus public content, title, meta description, canonical, OG, and JSON-LD markers.
- Covered in Task 2: Study API `word_source=word_detail` missing `word_id`, current-user scoping, `extra_study` future-card behavior, `due_filter = None` scoping, buried cards, and standardized `api_error` format for the confirmed invalid request.
- Deferred to Task 3: dirty profile data normalization, route filters, authorization boundaries in service data, and confirmed N+1 issues.
- Deferred to Task 4: template escaping, empty states, private controls on public pages, hardcoded public URLs, and broken links.
- Deferred to Task 5: unresolved findings sweep, stale helper/import checks, and regression coverage consolidation.

## Commands

- Task 1 validation passed: `pytest tests/test_words_routes.py tests/test_public_words_seo.py -q`
- Task 2 TDD failure reproduced: `pytest tests/api/test_study_api.py -q`
- Task 2 focused validation passed: `pytest tests/api/test_study_api.py -q`

## Task 2 brainstorm: Study API word_detail

- Missing `word_id`: invalid `source=word_detail` request should not silently behave like a successful empty session; it should use the standard `api_error` shape.
- Other user's card: every existing-card query must keep `UserWord.user_id == current_user.id`; tests include another user's due card to guard this boundary.
- Nonexistent word: a positive but nonexistent `word_id` is allowed to return a successful empty item list because there is no card or dictionary word to study.
- Buried card: selected word cards with future `buried_until` must stay hidden in normal and extra study.
- Overdue card: selected overdue review/learning/relearning cards should remain eligible within the current user's scope.
- Future due card: normal word-detail study should not pull cards beyond today's due window; `extra_study=true` may include the selected future card.
- `extra_study=true`: may bypass new/review daily limits and due time for the selected word only; it must not widen the query to all due or future cards.
- New/review limits: normal study still honors daily limits; extra study keeps the existing small extra-study batch limits.
- `due_filter = None`: this is safe only while `deck_word_ids` is non-null and applied to all existing-card queries.
- API errors: confirmed invalid input now returns `api_error('invalid_input', ..., 400)`; business state `daily_limit_reached` intentionally keeps the legacy success response shape.
