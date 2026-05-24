# Admin Module Inventory (LOC + relations)

Snapshot taken during Task 1 of `docs/plans/2026-05-24-admin-full-audit.md` on 2026-05-24.
LOC values come from `wc -l`. Numbers are approximate (include blank lines and comments) and serve as a triage map for the upcoming audit tasks.

## Top-level admin package (`app/admin/`)

| File | LOC | Notes |
|---|---:|---|
| `__init__.py` | 83 | `register_admin_routes()` mounts every sub-blueprint. |
| `audit.py` | 63 | `AdminAuditLog` model + `log_admin_action()` helper. |
| `book_courses.py` | 1586 | Legacy "book courses" routes attached to `admin` blueprint via `register_book_course_routes`. Candidate for split (Task 10 / Task 27). |
| `curriculum.py` | 865 | Cultural notes + curriculum view-functions attached to `admin` blueprint. Overlaps with `routes/curriculum_routes.py` (Task 12). |
| `form.py` | 276 | WTForms used by admin. |
| `main_routes.py` | 1435 | Dashboard/stats/cache/content-quality. To be split in Task 7. |
| `main_routes.py.backup` | 3170 | **Dead file — delete in Task 27.** |
| `modules.py` | 259 | Module CRUD/grant attached to `admin` blueprint. |
| `quiz_decks.py` | 415 | Quiz deck admin routes. |
| `secret_store.py` | 78 | Helpers for sensitive settings. |
| `site_settings.py` | 145 | `SiteSettings` model + `get_site_setting` / `set_site_setting` + defaults seeding. |

## Sub-blueprint routes (`app/admin/routes/`)

| Blueprint | File | LOC |
|---|---|---:|
| `activity_admin` | `activity_routes.py` | 102 |
| `audio_admin` | `audio_routes.py` | 292 |
| `audit_admin` | `audit_routes.py` | 122 |
| `book_admin` | `book_routes.py` | 734 |
| `collection_admin` | `collection_routes.py` | 160 |
| `admin_curriculum` | `curriculum_routes.py` | 260 |
| `grammar_lab_admin` | `grammar_lab_routes.py` | 729 |
| `seo_admin` | `seo_routes.py` | 355 |
| `settings_admin` | `settings_routes.py` | 73 |
| `system_admin` | `system_routes.py` | 121 |
| `topic_admin` | `topic_routes.py` | 186 |
| `user_admin` | `user_routes.py` | 250 |
| `word_admin` | `word_routes.py` | 374 |

## Services (`app/admin/services/`)

| Service | LOC | Heavy paths |
|---|---:|---|
| `activity_feed_service.py` | 263 | Aggregates events across 5 sources (Task 19). |
| `audio_management_service.py` | 362 | Long-running audio operations (Task 14). |
| `book_processing_service.py` | 284 | Upload/parse pipeline (Task 10). |
| `cohort_service.py` | 311 | Funnel + cohort retention (Task 19). |
| `curriculum_import_service.py` | 706 | Largest service. JSON import + validation (Task 12). |
| `gsc_service.py` | 170 | Google Search Console OAuth + fetch (Task 15). |
| `linear_plan_metrics.py` | 426 | Linear plan rollout metrics (Task 21). |
| `seo_audit_service.py` | 278 | Internal SEO crawl + per-worker cache (Task 15 / Task 26). |
| `system_service.py` | 239 | Cache clear / DB init helpers (Task 17). |
| `user_management_service.py` | 405 | User CRUD + pagination (Task 9). |
| `word_management_service.py` | 910 | Largest service. Bulk word ops + CSV (Task 11). |

## Utils (`app/admin/utils/`)

| File | LOC | Notes |
|---|---:|---|
| `cache.py` | 105 | In-memory TTL cache (Task 26). |
| `decorators.py` | 106 | `admin_required`, `handle_admin_errors`, `cache_result`, and (added in Task 1) `admin_audit_required`. |
| `export_helpers.py` | 187 | `_sanitize_csv_cell` + streaming CSV (Task 11 / Task 20). |
| `import_helpers.py` | 81 | CSV import helpers (Task 11). |

## Templates (`app/templates/admin/`)

Total ~29k lines across 60+ HTML files. Largest:

| Template | LOC |
|---|---:|
| `books/add.html` | 648 |
| `books/index.html` | 609 |
| `topics/words.html` | 612 |
| `modules/list.html` | 611 |
| `modules/edit.html` | 569 |
| `collections/form.html` | 519 |
| `seo/index.html` | 389 |
| `dashboard.html` | 423 |

Sub-directories: `activity/`, `audio/`, `audit/`, `book_courses/`, `books/`, `collections/`, `curriculum/`, `grammar_lab/`, `modules/`, `quiz_decks/`, `reminders/`, `seo/`, `settings/`, `system/` (file), `topics/`, `words/`, plus root-level files (`base.html`, `components.html`, `dashboard.html`, `users.html`, `user_detail.html`, `linear_plan_user.html`, `stats.html`, `database.html`, `content_quality.html`, `cultural_note_form.html`, `cultural_notes_list.html`).

## Tests (`tests/admin/`)

| File | LOC | Covers |
|---|---:|---|
| `test_activity_metrics.py` | 378 | Activity service / feed |
| `test_audit.py` | 99 | `AdminAuditLog` + `log_admin_action` |
| `test_batch_operations.py` | 151 | Word bulk operations |
| `test_cohort_service.py` | 283 | Funnel + retention |
| `test_content_quality.py` | 821 | Content quality dashboard |
| `test_dashboard_stats.py` | 1114 | Dashboard / stats |
| `test_dau_wau_cache.py` | 87 | DAU/WAU/MAU caching |
| `test_gsc.py` | 423 | GSC OAuth + fetch |
| `test_linear_plan_metrics.py` | 515 | Linear plan metrics service |
| `test_linear_plan_user_inspector.py` | 114 | Per-user inspector |
| `test_settings_routes.py` | 158 | Settings routes |
| `test_site_settings.py` | 105 | `SiteSettings` helpers |
| `test_task3_admin_audit_csrf.py` | 180 | CSRF coverage |
| `test_user_list_pagination.py` | 81 | User list pagination |
| `test_user_management_detail.py` | 277 | User detail page |
| `routes/test_audio_routes.py` | 356 | Audio admin routes |
| `routes/test_book_routes.py` | 438 | Book admin routes |
| `routes/test_curriculum_routes.py` | 471 | Curriculum admin routes |
| `routes/test_grammar_lab_routes.py` | 219 | Grammar Lab admin routes |
| `routes/test_system_routes.py` | 222 | System admin routes |
| `routes/test_topic_routes.py` | 69 | Topic admin routes |
| `routes/test_user_routes.py` | 46 | User admin routes |
| `routes/test_word_routes.py` | 290 | Word admin routes |
| `services/test_audio_management_service.py` | 411 | Audio service |
| `services/test_book_processing_service.py` | 232 | Book processing service |
| `services/test_curriculum_import_service.py` | 588 | Curriculum import service |
| `services/test_system_service.py` | 143 | System service |
| `services/test_user_management_service.py` | 409 | User management service |
| `services/test_word_management_service.py` | 772 | Word management service |

## Missing coverage flagged for later tasks

- No dedicated test file for `app/admin/routes/activity_routes.py`, `audit_routes.py`, `collection_routes.py`, `seo_routes.py`, `settings_routes.py` (settings_routes is partially covered by `test_settings_routes.py` which targets blueprint endpoints, but not the audit-log path).
- No dedicated test file for `app/admin/services/activity_feed_service.py`, `cohort_service.py`, `gsc_service.py`, `linear_plan_metrics.py`, `seo_audit_service.py` is missing (cohort is partially covered by `test_cohort_service.py`; the rest are validated through their consumer routes only).
- `app/admin/book_courses.py`, `modules.py`, `quiz_decks.py`, `curriculum.py`, `secret_store.py`, `form.py` have no dedicated test files and their endpoints are not in the inventory of admin tests.

These gaps are picked up explicitly by Tasks 4 (audit coverage), 13 (Grammar Lab), 15 (SEO/GSC), 18 (Topics/Collections), 19 (Activity/Cohort), 21 (Linear plan metrics) and 29 (coverage gap analysis).
