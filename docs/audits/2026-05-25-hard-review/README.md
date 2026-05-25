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
| HRW-008 | P1 | `app/words/detail_service.py` | Dirty synonym/antonym lists can render duplicate chips after placeholder cleanup. | TDD regression showed `normalise_word_list(['learn', 'learn', 'Learn'])` returned duplicates. | Deduplicate normalized list values case-insensitively while preserving first display text. | `TestWordProfileDataNormalization::test_normalise_word_list_removes_placeholders_and_duplicates` | fixed |
| HRW-009 | P1 | `app/words/detail_service.py` | Imported frequency bands can arrive as string values and display as unknown. | TDD regression showed `frequency_band_label('2')` returned `Не указана`. | Coerce band values to `int` before label lookup and fall back safely for invalid values. | `TestWordProfileDataNormalization::test_frequency_band_label_handles_missing_and_string_values` | fixed |
| HRW-010 | P0 | `app/words/detail_service.py`, `app/words/routes.py` | Public word profile helper can expose non-public related forms through shared base/phrasal data. | Regression test creates an A1 public word with a C2 phrasal variant; the public page must not render the C2 form. | Add `public_only` profile filtering for base words and phrasal variants; call it from the public route. | `TestPublicWord::test_public_word_does_not_expose_private_profile_data` | fixed |
| HRW-011 | P1 | `app/templates/words/public_word.html`, `app/words/routes.py` | Public word SEO can emit production hardcoded canonical/JSON-LD URLs and entity-escaped JSON-LD values on staging/custom domains. | TDD regression showed `SITE_URL=https://staging.llt-english.com` was ignored and JSON-LD preserved `"` as `&#34;`. | Build canonical URLs from `SITE_URL` plus `url_for`, and serialize JSON-LD values with `tojson`. | `TestPublicWordRoute::test_public_word_has_title_meta_canonical_and_no_private_controls`, `TestPublicWordRoute::test_public_word_json_ld_preserves_unescaped_text_values` | fixed |
| HRW-012 | P0 | `app/templates/words/details_optimized.html`, `app/templates/words/list_optimized.html`, `app/templates/words/public_word.html` | Audio filenames are interpolated into inline JavaScript string literals; a quote in stored audio metadata can break out after HTML entity decoding. | TDD regression rendered `playAudio('/static/audio/bad&#39;);alert(1);//.mp3')`. | Pass audio URLs through `tojson` in single-quoted event attributes. | `test_public_word_audio_url_uses_json_encoded_handler_argument`, `test_word_list_audio_url_uses_json_encoded_handler_argument`, `test_word_detail_audio_url_uses_json_encoded_handler_argument` | fixed |
| HRW-013 | P1 | `app/templates/words/public_word.html` | Public word page can expose private word-detail CTAs to authenticated visitors, making the SEO route render different private controls. | Regression asserts public word HTML does not contain `/words/<id>`, status controls, or `startLearningWord`. | Render the public word template with `public_base.html` and public registration CTAs consistently. | `TestPublicWordRoute::test_public_word_has_title_meta_canonical_and_no_private_controls`, `TestPublicWordRoute::test_public_word_hides_empty_profile_sections_audio_and_private_controls` | fixed |
| HRW-014 | P2 | `app/words/routes.py`, `app/words/forms.py` | The current word-list default sort can regress to raw frequency ordering or invalid `sort` values can bypass the recommended fallback. | Current route/form diff introduces `recommended`; without a route assertion, the default and invalid fallback behavior is easy to drift. | Keep `recommended` as the default and invalid-sort fallback, ordering by CEFR level then frequency. | `TestWordList::test_word_list_default_and_invalid_sort_use_recommended_level_order` | covered |

## Baseline coverage map

- Covered now: dictionary word list 200 plus rendered word content, authenticated word detail 200 plus profile content, public word page 200 plus public content, title, meta description, canonical, OG, and JSON-LD markers.
- Covered in Task 2: Study API `word_source=word_detail` missing `word_id`, current-user scoping, `extra_study` future-card behavior, `due_filter = None` scoping, buried cards, and standardized `api_error` format for the confirmed invalid request.
- Deferred to Task 3: dirty profile data normalization, route filters, authorization boundaries in service data, and confirmed N+1 issues.
- Covered in Task 4: template escaping for word/profile/book/related text, empty states for missing semantic fields/audio/books/related words, private controls on public word pages, hardcoded public word canonical URLs, and inline audio handler escaping.
- Covered in Task 5: unresolved findings sweep, stale helper/import checks, and regression coverage consolidation for the current recommended word-list sort.

## Commands

- Task 1 validation passed: `pytest tests/test_words_routes.py tests/test_public_words_seo.py -q`
- Task 2 TDD failure reproduced: `pytest tests/api/test_study_api.py -q`
- Task 2 focused validation passed: `pytest tests/api/test_study_api.py -q`
- Task 3 TDD failure reproduced: `pytest tests/test_words_routes.py::TestWordProfileDataNormalization tests/test_words_routes.py::TestPublicWord::test_public_word_does_not_expose_private_profile_data -q`
- Task 3 focused regression validation passed: `pytest tests/test_words_routes.py::TestWordProfileDataNormalization tests/test_words_routes.py::TestWordList::test_combined_search_type_level_and_pagination_filters_results tests/test_words_routes.py::TestPublicWord::test_public_word_does_not_expose_private_profile_data -q`
- Task 3 validation passed: `pytest tests/test_words_routes.py -q`
- Task 4 TDD failures reproduced: `pytest tests/test_public_words_seo.py::TestPublicWordRoute::test_public_word_has_title_meta_canonical_and_no_private_controls tests/test_public_words_seo.py::TestPublicWordRoute::test_public_word_json_ld_preserves_unescaped_text_values tests/test_public_words_seo.py::TestPublicWordRoute::test_public_word_audio_url_uses_json_encoded_handler_argument tests/test_words_routes.py::TestWordList::test_word_list_audio_url_uses_json_encoded_handler_argument tests/test_words_routes.py::TestWordDetail::test_word_detail_audio_url_uses_json_encoded_handler_argument -q`
- Task 4 focused regression validation passed: `pytest tests/test_public_words_seo.py::TestPublicWordRoute::test_public_word_has_title_meta_canonical_and_no_private_controls tests/test_public_words_seo.py::TestPublicWordRoute::test_public_word_json_ld_preserves_unescaped_text_values tests/test_public_words_seo.py::TestPublicWordRoute::test_public_word_audio_url_uses_json_encoded_handler_argument tests/test_words_routes.py::TestWordList::test_word_list_audio_url_uses_json_encoded_handler_argument tests/test_words_routes.py::TestWordDetail::test_word_detail_audio_url_uses_json_encoded_handler_argument -q`
- Task 4 escaping/empty-state validation passed: `pytest tests/test_public_words_seo.py::TestPublicWordRoute::test_public_word_escapes_profile_and_related_word_text tests/test_public_words_seo.py::TestPublicWordRoute::test_public_word_hides_empty_profile_sections_audio_and_private_controls tests/test_words_routes.py::TestWordList::test_word_list_escapes_word_and_book_text tests/test_words_routes.py::TestWordDetail::test_word_detail_escapes_profile_related_and_book_text tests/test_words_routes.py::TestWordDetail::test_word_detail_hides_empty_profile_audio_books_and_related_sections -q`
- Task 4 validation passed: `pytest tests/test_public_words_seo.py tests/test_words_routes.py -q`
- Task 5 helper/template usage check passed: `rg -n "normalise_word_list|frequency_band_label|build_word_profile|build_word_study_summary|get_related_words|word_profile_|public_only|canonical_url|meta_description|recommended" app tests docs/audits/2026-05-25-hard-review/README.md`
- Task 5 import check passed: `python -c "import app.words.detail_service; import app.words.routes; import app.study.api_routes"`
- Task 5 focused regression validation passed: `pytest tests/test_words_routes.py::TestWordList::test_word_list_default_and_invalid_sort_use_recommended_level_order -q`
- Task 5 validation passed: `pytest tests/test_words_routes.py tests/test_public_words_seo.py -q`

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

## Task 3 brainstorm: words service/forms/routes data correctness

- Dirty optional text: `None`, whitespace, `null`, `none`, `undefined`, `nan`, `[]`, `{}`, and `-` should not render as meaningful usage context or etymology.
- Dirty semantic lists: synonyms and antonyms may arrive as JSON arrays, comma/semicolon strings, placeholders, or duplicate values with different casing.
- Frequency labels: missing frequency band should render `Не указана`; numeric strings from import/forms should map to the same labels as integers.
- Review labels: missing, overdue, same-day, tomorrow, near-future, and later review timestamps need stable Russian labels.
- Semantic hints: role nouns such as `student`/`teacher` should still produce useful common-mistake and related-word hints after cleanup.
- Missing media and metadata: no audio, no level, no frequency, and no book/topic/collection relations should produce empty facts rather than dirty placeholder text.
- Query-string routes: combined search, type, level, sort, page, and per-page filters should keep the intended result set and avoid 500s.
- Authorization boundaries: public word pages must not render private status blocks, `/words/<id>` links, admin facts, or non-public related forms from the shared profile helper.
- N+1 review: word list uses set-based joins/subqueries for user status, decks, mastered state, and next review; detail pages load one source word, and related-word candidate queries use `selectinload` for topics, collections, base word, and phrasal variants. No new per-row N+1 defect was confirmed in Task 3.

## Task 4 brainstorm: templates XSS, UX, and SEO

- English word: rendered in page titles, hero headings, breadcrumbs, links, OG, and JSON-LD; must stay escaped in HTML and correctly serialized in JSON-LD.
- Translation: rendered in hero blocks, profile translations, related-word cards, and meta descriptions; HTML-like translations must not become markup.
- Usage context and etymology: shared profile template renders these as prose; dirty HTML-like strings should be escaped and missing values should hide the section.
- Synonyms and antonyms: rendered as chips; tags, SVG payloads, and duplicate/dirty values must not become executable markup.
- User notes: not rendered by the reviewed word templates; no Task 4 template surface found.
- Book titles: private detail/list templates render book titles and status titles; malicious titles must be escaped.
- Topic names: related-word scoring uses topic relations, but the reviewed templates render reason labels rather than raw topic names.
- Audio metadata: `listening` is stored data and was used inside inline JavaScript string literals; quote payloads can break handlers if not JSON-encoded.
- Empty states: missing audio, synonyms, antonyms, etymology, books, and related words should avoid broken empty sections; private detail should show an explicit related-word empty message.
- SEO/private UI: public word pages need canonical URLs from configured `SITE_URL`, valid JSON-LD, and no `/words/<id>` private controls.

## Task 5 brainstorm: unresolved findings and stale code

- HRW-001 through HRW-004 are baseline coverage findings and remain covered by route/SEO assertions; no code fix is pending.
- HRW-005, HRW-008, HRW-009, HRW-010, HRW-011, HRW-012, and HRW-013 are fixed and each row links to a regression test.
- HRW-006 and HRW-007 are high-risk Study API boundaries that were covered without a new code change; the tests still document the expected scoping and buried-card behavior.
- No false-positive P0/P1 finding remains unresolved after the sweep.
- The `rg` pass over profile helpers, public-only flags, canonical/meta variables, and the new `recommended` sort found active references only; no stale helper, duplicate branch, or stale import needed removal.
- The only extra consolidation coverage needed in this pass is HRW-014, which locks the current default/invalid word-list sort behavior to the recommended CEFR-first ordering.
