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

## Baseline coverage map

- Covered now: dictionary word list 200 plus rendered word content, authenticated word detail 200 plus profile content, public word page 200 plus public content, title, meta description, canonical, OG, and JSON-LD markers.
- Deferred to Task 2: Study API `word_source=word_detail`, SRS due filtering, buried cards, extra study, and API error format.
- Deferred to Task 3: dirty profile data normalization, route filters, authorization boundaries in service data, and confirmed N+1 issues.
- Deferred to Task 4: template escaping, empty states, private controls on public pages, hardcoded public URLs, and broken links.
- Deferred to Task 5: unresolved findings sweep, stale helper/import checks, and regression coverage consolidation.

## Commands

- Task 1 validation passed: `pytest tests/test_words_routes.py tests/test_public_words_seo.py -q`
