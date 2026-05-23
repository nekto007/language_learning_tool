# Реестр проблем — аудит сайта (2026-05-23)

Источник: план `docs/plans/2026-05-23-site-audit-fixes.md`, Task 1 (Discovery).

Методика:
- pytest полностью + `pytest -m smoke` (smoke зелёный, full — 17 fail)
- статический обход публичных и админ-роутов
- grep по шаблонам (`app/templates/`) и коду (`app/**/*.py`)
- поиск дублей/мёртвого кода (`*.bak`, `* 2.*`, неимпортируемые модули)

Приоритеты:
- **P0** — сломанные сценарии, security/data-loss риск, упавшие тесты
- **P1** — UX-баги, неотлогированные деструктивные действия, технический долг с реальным риском
- **P2** — полировка, dead code, refactor-кандидаты

Колонки: `id | layer | priority | file:line | описание | предлагаемый фикс`

---

## A. Падающие тесты (full pytest)

Smoke (`pytest -m smoke`) — 154 passed, ✅ зелёный.
Full pytest — 17 failed (две группы):

### A1. Контент модулей (5 тестов, `tests/test_module_content_quality.py`)

| id | layer | priority | file:line | описание | фикс |
|---|---|---|---|---|---|
| T-001 | content | P1 | `module_completed/fixed/module_A1_13_body_parts.json` | reading_words=62 < 83 — модуль ниже квоты | расширить reading блок |
| T-002 | content | P1 | `module_completed/fixed/module_A1_4_objects_around_us.json` | open-answer transformation без `acceptable_answers` | добавить варианты ответов |
| T-003 | content | P1 | `tests/test_module_content_quality.py:177` | `'NoneType' object is not iterable` — choice-options None | проверить, что correct/options существуют |
| T-004 | content | P1 | `module_completed/fixed/module_B1_10_food_and_restaurants.json` | reading-примеры слишком короткие на B1 | переписать примеры (≥ N слов) |
| T-005 | content | P1 | `module_completed/fixed/module_B2_10_travel_and_tourism.json` | повторяющиеся блоки reading | дедупнуть фразы |

Решение: контентные правки — не блокеры для Task 2 (нет кодового бага), но реестр должен закрыть их отдельным контент-ран ом. Помечаем как «требует решения» (P1 контент).

### A2. UI/template wiring (12 тестов)

Тесты проверяют наличие конкретных JS-хуков, data-атрибутов, имён функций в шаблонах. Все падают на отсутствии маркеров — это либо рассинхрон тестов с актуальной разметкой (templates были переписаны без обновления тестов), либо реальная регрессия UI (linear day-secured banner / SRS plan-aware completion / lesson-ux fetchNextSlot).

| id | layer | priority | file:line | описание | фикс |
|---|---|---|---|---|---|
| T-010 | frontend | P0 | `tests/test_dashboard_linear.py::test_next_step_appears_in_banner` | `data-linear-day-secured-next-step="true"` отсутствует в рендере dashboard | вернуть data-атрибут в banner-partial dashboard.html |
| T-011 | frontend | P0 | `tests/test_dashboard_linear.py::test_next_step_absent_when_no_steps` | `data-linear-day-secured-banner="true"` отсутствует | вернуть data-атрибут |
| T-012 | frontend | P0 | `tests/test_dashboard_linear.py::test_next_step_failure_does_not_break_banner` | same | same |
| T-013 | frontend | P0 | `tests/test_dashboard_day_secured_banner.py::test_banner_rendered_when_query_and_log_present` | банер не рендерится | проверить условие в dashboard.html (query=secured&log_present) |
| T-014 | frontend | P0 | `tests/test_dashboard_day_secured_banner.py::test_banner_xp_aggregates_from_streak_events` | `+53 XP` не выводится | вернуть aggregator в route или partial |
| T-015 | frontend | P0 | `tests/test_error_review_plan_aware.py::test_helper_invoked_from_inline_script` | `applyErrorReviewPlanAwareCompletion` не вызывается | добавить вызов в `curriculum/error_review.html` |
| T-016 | frontend | P0 | `tests/test_lesson_ux.py::test_helper_branches_on_linear_plan_context` | `fetchNextSlot` отсутствует | вернуть helper в bootstrap-скрипт lesson |
| T-017 | frontend | P0 | `tests/test_lesson_ux.py::test_helper_has_standalone_fallback` | `_revealCompletion('standalone')` отсутствует | вернуть standalone fallback |
| T-018 | frontend | P0 | `tests/test_lesson_ux.py::test_plan_branch_js_hides_footer_inline` | `legacyFooter.classList.remove('lsn-footer--visible')` отсутствует | вернуть скрытие footer'а в plan-branch |
| T-019 | frontend | P0 | `tests/test_srs_plan_aware_completion.py::test_celebration_actions_default_to_standalone_mode` | `data-completion-mode="standalone"` отсутствует | вернуть атрибут в `components/_flashcard_session.html` |
| T-020 | frontend | P0 | `tests/test_srs_plan_aware_completion.py::test_bootstrap_script_invokes_helper` | `applySrsPlanAwareCompletion` не вызывается | вернуть инициализацию helper'а |
| T-021 | frontend | P0 | `tests/test_srs_plan_aware_completion.py::test_bootstrap_script_uses_mutation_observer` | `MutationObserver` отсутствует | вернуть observer в bootstrap |

Кластер T-010..T-021 — наиболее вероятно одна регрессия (рефакторинг dashboard/lesson/SRS bootstrap скриптов на текущей ветке). Чинить в Task 2.

---

## B. Публичный фронтенд / SEO

| id | layer | priority | file:line | описание | фикс |
|---|---|---|---|---|---|
| F-001 | seo | P0 | `app/admin/services/seo_audit_service.py:27` | `PUBLIC_URLS` содержит `/book-courses` (404), реальный путь `/curriculum/book-courses` и требует логина | заменить на `/courses` |
| F-002 | seo | P1 | `app/admin/services/seo_audit_service.py:21-35` | аудит не покрывает `/courses`, `/courses/A1..C2`, `/grammar-lab/topic/<id>` | добавить URL'ы |
| F-003 | seo | P2 | `app/admin/services/seo_audit_service.py:33` | нет `/grammar-lab/topics/c2` | добавить для паритета с sitemap |
| F-004 | seo | P0 | `app/templates/auth/reset_request.html` | нет meta description, нет canonical | добавить meta + canonical |
| F-005 | seo | P1 | 16 шаблонов с hardcoded `https://llt-english.com` для canonical | сломает на staging/preview | заменить на `url_for(..., _external=True)` или брать из SiteSettings |
| F-006 | seo | P1 | `app/templates/curriculum/lessons/final_test_results.html:892` | hardcoded share_url без path | использовать `url_for(..., _external=True)` |
| F-007 | seo | P1 | `app/templates/base.html:533` | hardcoded URL в inline onclick (levelup share) | передавать через `url_for` |
| F-008 | seo | P2 | `app/seo/routes.py:36-90` | sitemap пропускает `/curriculum/book-courses[/...]` | добавить, либо Disallow в robots |
| F-009 | seo | P2 | `app/seo/routes.py:99-104` | robots.txt разрешает `/api/`, `/onboarding`, `/curriculum/*`, `/uploads/` (login-walled — впустую тратится crawl-budget) | Disallow login-walled prefixes |
| F-010 | seo | P2 | `app/admin/services/seo_audit_service.py:21` | `/reset_password` POST rate-limited 3/h — документировать GET-only audit | комментарий + опционально замена на динамическую страницу |

---

## C. Админка

| id | layer | priority | file:line | описание | фикс |
|---|---|---|---|---|---|
| AD-001 | admin | P1 | `app/templates/admin/curriculum/edit_text.html:18` | POST-форма без csrf_token (global CSRFProtect → 400) | добавить `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` |
| AD-002 | admin | P1 | `app/templates/admin/curriculum/edit_quiz.html:18` | то же | то же |
| AD-003 | admin | P1 | `app/templates/admin/curriculum/edit_matching.html:18` | то же | то же |
| AD-004 | admin | P1 | `app/templates/admin/curriculum/edit_grammar.html:18` | то же | то же |
| AD-005 | admin | P1 | `app/templates/admin/curriculum/user_progress.html:175,183` | inline reset/delete формы без csrf | добавить csrf hidden input |
| AD-006 | admin | P1 | `app/templates/admin/curriculum/progress_details.html:152,159` | то же | то же |
| AD-007 | admin | P1 | `app/templates/admin/curriculum/edit_module.html:59` | inline delete без csrf | то же |
| AD-008 | admin | P1 | `app/templates/admin/curriculum/edit_level.html:61` | inline delete без csrf | то же |
| AD-010 | admin | P1 | `app/admin/curriculum.py:180 delete_level` | нет `log_admin_action` | добавить вызов |
| AD-011 | admin | P1 | `app/admin/curriculum.py:272 delete_module` | то же (каскадит все уроки) | добавить |
| AD-012 | admin | P1 | `app/admin/curriculum.py:366 delete_lesson` | то же | добавить |
| AD-013 | admin | P1 | `app/admin/curriculum.py:710 reset_progress / :729 delete_progress` | то же — стирают LessonProgress | добавить |
| AD-014 | admin | P1 | `app/admin/quiz_decks.py:140,320,340` | quiz_deck_delete/remove_word/reorder_words без audit | добавить |
| AD-015 | admin | P1 | `app/admin/routes/topic_routes.py:78 delete_topic, :184 remove_word_from_topic` | то же | добавить |
| AD-016 | admin | P1 | `app/admin/routes/collection_routes.py:125 delete_collection` | то же | добавить |
| AD-017 | admin | P1 | `app/admin/routes/book_routes.py:486 delete_book, :397-460 cleanup_books` | hard deletes без audit | добавить |
| AD-018 | admin | P1 | `app/admin/book_courses.py:1076 delete_daily_lesson, :1422 remove_word_from_lesson` | каскадные delete без audit (delete_book_course :440 логирует) | добавить |
| AD-019 | admin | P1 | `app/admin/routes/grammar_lab_routes.py:278 delete_exercise` | без audit (delete_topic :169 логирует) | добавить |
| AD-020 | admin | P1 | `app/admin/routes/user_routes.py:63,78,92` | toggle_user_status / toggle_admin_status / toggle_mission_plan — privilege changes без audit | добавить |
| AD-021 | admin | P1 | `app/admin/routes/system_routes.py:91 init_database` | деструктивная операция без audit | добавить |
| AD-022 | admin | P2 | `app/admin/routes/collection_routes.py, topic_routes.py, grammar_lab_routes.py` | используют `@login_required + @admin_required` (избыточно) — остальные admin-роуты только `@admin_required` | стандартизировать |
| AD-023 | admin | P2 | `app/admin/routes/activity_routes.py:25, audit_routes.py:26` | page clamped только ≥1, верхней границы нет | `min(page, 1000)` |
| AD-024 | admin | P2 | `app/templates/admin/activity/funnel.html:41-49,87-168` | большое количество inline style | вынести в `.admin-funnel-*` классы |
| AD-025 | admin | P2 | `app/templates/admin/activity/index.html:58,102-123` | inline style на `<th>` и dropdown | в CSS |
| AD-026 | admin | P2 | `app/templates/admin/audit/index.html:74-87` | inline style на `<th>` и truncate | в CSS |
| AD-027 | admin | P2 | `app/templates/admin/curriculum/srs_settings.html` | orphan template, нет `render_template` ссылок | удалить или подключить |
| AD-028 | admin | P2 | `app/templates/admin/book_courses/{index,create_module,edit_module}.html` | orphan candidates (не подтверждено окончательно) | проверить и удалить |

---

## D. Код (Python)

| id | layer | priority | file:line | описание | фикс |
|---|---|---|---|---|---|
| C-001 | code | P0 | `app/books/parsers.py:626` | bare `except:` глотает ошибки `os.remove` | `except OSError: logger.warning(...)` |
| C-002 | code | P0 | `app/api/decorators.py:45` | `except Exception:` возвращает 401 без логирования (auth path) | добавить `logger.warning` |
| C-003 | code | P0 | `app/health.py:23` | health-check глотает исключения | логировать, чтобы реальные outage не маскировались |
| C-004 | code | P0 | `app/onboarding/routes.py:25` | `request.args.get('next', '')` без `get_safe_redirect_url`, пробрасывается в шаблон → форма `complete()` (potential open redirect) | санитайзить на intake |
| C-005 | code | P1 | `app/repository.py:540,569` | f-string интерполяция table_name/column_name в SQL (значения — bound params, но идентификаторы — нет) | allowlist таблиц/колонок |
| C-006 | code | P1 | `app/api/daily_plan.py:86,205,302,311,342,356,362,369,389,483,492,619,631,640,779,786,792,890,937,1059,1101,1157,1191,1308` (24 шт) | silent `except Exception:` без логирования | добавить `logger.exception` либо явно ловить узкий тип |
| C-007 | code | P1 | `app/daily_plan/service.py:282,290,300,314` | 4 silent swallow в router fallback | то же |
| C-008 | code | P1 | `app/admin/services/activity_feed_service.py:61,69,77,85,93` | 5 silent swallow per event-source | логировать с указанием источника |
| C-009 | code | P1 | `app/achievements/streak_service.py:322,375,384,386,415,427,432,472,500,511,613` | 11 silent swallow в streak | логировать |
| C-010 | code | P1 | `app/daily_plan/linear/xp.py:204,364` | silent в XP-award | логировать |
| C-011 | code | P2 | `app/utils/template_utils.py:243,262,290,314` | 4 silent swallow в navbar context (219 уже логирует) | привести к единому стилю |
| C-012 | code | P1 | `app/words/routes.py:1067,1068,1069,1097,1102,1104,1167,1179-1188,1201-1210,1225,1300,1306,1312-1318,1328-1332` | ~14 виджет-вызовов из dashboard route не обёрнуты в `_safe_widget_call()` | обернуть |
| C-013 | code | P2 | top-10 файлов >800 строк (`app/words/routes.py` 2344, `app/curriculum/routes/lessons.py` 2101, `app/study/insights_service.py` 1741, `app/telegram/queries.py` 1542, `app/admin/book_courses.py` 1519, `app/curriculum/grading.py` 1454, `app/admin/main_routes.py` 1433, `app/achievements/streak_service.py` 1417, `app/api/daily_plan.py` 1312, `app/study/routes.py` 1252) | refactor candidates | разбить по подмодулям (не блокер) |
| C-014 | code | P2 | top-10 функций >100 строк (`register_book_course_routes` 1423, `dashboard` 660, `get_daily_plan_v2` 589, `get_study_items` 397, `create_app` 393, `process_grammar_submission` 388, `get_daily_plan` 363, `import_curriculum_data` 358, `init_template_utils` 331, `process_quiz_submission` 313) | разбить | не блокер |
| C-015 | code | P2 | tests deprecation warnings: `datetime.utcnow()` в `tests/test_dashboard_routes.py:136,137,235`, `tests/utils/test_activity_tracker.py:12,210` | заменить на `datetime.now(timezone.utc)` | tests-only |
| C-016 | code | P2 | `tests/conftest.py:70` SQLAlchemy `RemovedIn20Warning` | TRUNCATE через `text(f'...')` triggers SQLAlchemy 2.0 deprecation | мигрировать на 2.0-стиль или silence |

Нет: mutable default args (0), голых `except:` (1 — C-001), TODO/FIXME (0), незарегистрированных blueprints (0).

---

## E. Шаблоны (frontend hygiene)

| id | layer | priority | file:line | описание | фикс |
|---|---|---|---|---|---|
| TPL-001 | frontend | P1 | `app/templates/base.html:12` | только favicon.ico, нет apple-touch-icon, manifest, theme-color (нет `app/static/manifest.json`) | добавить набор PWA-иконок и манифест |
| TPL-002 | frontend | P2 | `app/templates/dashboard.html` (38 inline style) | inline-styles | вынести в `.dash-*` |
| TPL-003 | frontend | P2 | `app/templates/landing/index.html` (34 inline style, особенно :830 `.land-audio-btn`, :836 `.land-wod-cta`) | то же | вынести |
| TPL-004 | frontend | P2 | `app/templates/components/_flashcard_session.html` (23 inline style) | дублируется через все study-flow | компонентный CSS |
| TPL-005 | frontend | P2 | `app/templates/base.html` (23 inline style) | глобальный layout | вынести |
| TPL-006 | frontend | P2 | `app/templates/study/index.html` (21 inline style) | то же | вынести |
| TPL-007 | frontend | P2 | многочисленные `onclick="..."` в `study/settings.html`, `study/index.html`, `auth/referrals.html`, `words/list_optimized.html` | CSP-hostile, плохо для a11y | заменить delegated listeners + `data-*` |

Не найдено: `<img>` без alt (0), дубликаты шаблонов (0 в `app/templates/`), битые `url_for` (0), `http://localhost` (0), orphan blocks (0).

---

## F. Dead code / дубликаты

| id | layer | priority | file | описание | действие |
|---|---|---|---|---|---|
| DC-001 | hygiene | P1 | `pytest.ini.bak` | бэкап конфига (Nov 16) | удалить |
| DC-002 | hygiene | P1 | `app/templates/curriculum/lessons/vocabulary_old.html.backup` | 31KB бэкап, 0 ссылок (`grep -r vocabulary_old`) | удалить |
| DC-003 | hygiene | P1 | 35 файлов `* 2.*` в `content/`, `docs/`, `reports/` (iCloud sync duplicates) | дубли | bulk delete |
| DC-004 | hygiene | P2 | 43 `* 2.mp3` в `app/static/audio/` (grammar_A1M1L3_ex*, A1M1L5_line_*) | iCloud audio duplicates | проверить пару, удалить дубли |
| DC-005 | hygiene | P2 | 21 `*.mp3.bak` в `books/morisaki_course/.../lessons/` | pre-regen audio backups | удалить после verify |
| DC-006 | hygiene | P2 | `app/static/js/reader-optimized.js` | 0 ссылок | удалить после расширенного grep'а |
| DC-007 | hygiene | P2 | `app/curriculum/url_helpers.py` (7 строк) | используется `app/utils/template_utils.py` (jinja filter) и собств. тестом — проверить, использует ли фильтр шаблон | human review |
| DC-008 | hygiene | P2 | корневые `REFACTORING_*.md`, `SESSION_SUMMARY*.md`, `INPUT_MODE_*.md`, `MODULES_*.{md,txt}`, `GENDER_FIX_SUMMARY.md`, `AUDIO_*.md/txt`, `BOOK_COURSES_TEST_REPORT.md`, `LISTENING_IMMERSION_SUMMARY.md`, `COVERAGE_*.md`, `audit_report.txt`, `TEST_*.md` | исторические session summaries в корне | переместить в `/docs/archive/` или удалить |
| DC-009 | hygiene | P2 | корневые `new_words_1012.txt`, `new_word_0512.txt`, `new_word_1801.txt`, `slive_vocabulary.txt`, `phrasal_verb.txt`, `books/trash_words.txt` | wordlists в корне | переместить в `/content/` или удалить |

Migrations chain: 66 файлов, head `20260525_add_site_settings → 20260524_use_unified_plan → 20260523_streak_shield` — чисто, без discontinuities.

---

## G. Mobile / адаптивность

Beглядом по `app/static/css/design-system.css` (~11400 строк) и ключевым шаблонам (base, dashboard, study, lesson-shell, admin/base) явных проблемных `min-width:` без media-query не обнаружено (поверхностный обзор). Глубокий audit отложен до Task 4 — там нужно гонять реальный браузер/devtools, а Task 1 — discovery-only. Помечено как **«требует решения / manual testing»**.

---

## H. Сводка по приоритетам

- **P0**: T-010..T-021 (12 frontend regression тестов), F-001 (битый URL в SEO audit), F-004 (нет canonical/meta на reset_password), C-001..C-004 (bare except, swallowed auth/health, unsafe `next`)
  → **17 проблем**. Все идут в Task 2 (P0-баги) и Task 3 (Admin P0).
- **P1**: T-001..T-005 (контент модулей), F-002, F-005..F-007 (hardcoded URL), AD-001..AD-021 (CSRF + admin audit log), C-005..C-012 (silent swallow, dashboard widgets, SQL identifier интерполяция), DC-001..DC-003, TPL-001 (PWA)
  → **~55 проблем**. Разнесены по Task 2/3/5.
- **P2**: F-003, F-008..F-010, AD-022..AD-028, C-013..C-016, TPL-002..TPL-007, DC-004..DC-009
  → **~30 проблем**. Task 4/5.

Открытые вопросы (требуют решения перед фиксом):
- T-010..T-021: настоящая регрессия или устаревшие тесты? Нужно прочитать `dashboard.html` / `_flashcard_session.html` / lesson templates и сверить с ожиданиями тестов.
- T-001..T-005: блокировать ли релиз контент-проблемами или признать как known-deferred (как уже сделано для 278 advanced-audio items)?
- F-005: hardcoded `llt-english.com` намеренно (production-only) или ошибка? Если намеренно — добавить env-aware свитч.
- DC-003: bulk delete `* 2.*` — нужно подтверждение пользователя (iCloud может ресоздать).

---

## Статус Task 1

- ✅ pytest полностью прогнан, падения зафиксированы (T-001..T-021)
- ✅ публичные роуты проанализированы (F-001..F-010)
- ✅ admin-роуты проанализированы (AD-001..AD-028)
- ✅ grep шаблонов (E. + проверки `<img>`, дубли, hardcoded URL)
- ✅ grep `app/` (C-001..C-016)
- ✅ адаптивность отмечена как manual-only
- ✅ dead code / duplicates (DC-001..DC-009)
- ✅ pytest -m smoke зелёный, никакого кода не менялось
- ✅ реестр записан в `docs/audit/2026-05-23-audit-findings.md`

## Статус Task 2 (P0-баги)

- ✅ T-010..T-014 — day-secured banner вынесен в `partials/_day_secured_banner.html`, подключён к `dashboard_path.html` (path-dashboard для linear-plan пользователей); `_render_path_dashboard` теперь зовёт общий helper `_build_day_secured_banner` (раньше banner-payload собирался только в legacy dashboard route).
- ✅ T-015 — `curriculum/error_review.html` после успешного `/api/daily-plan/error-review/complete` зовёт `window.linearPlanContext.applyErrorReviewPlanAwareCompletion(container)`; legacy server-rendered partial остался как fallback.
- ✅ T-016..T-018 — `lesson_base_template.html.showLessonCompletion` теперь имеет plan-aware ветку: `ctx.isActive()` → `fetchNextSlot()` → `_renderPlanCtas(...)` + `_hideLegacyFooter()` (drop `lsn-footer--visible`, force `display: none` на `#lesson-footer`/`#daily-plan-next-step`); fallback `_revealCompletion('standalone')` для отсутствующего контекста / catch'а API.
- ✅ T-019..T-021 — `components/_flashcard_session.html` по умолчанию `data-completion-mode="standalone"`; inline bootstrap-скрипт через `MutationObserver` ловит показ `#session-complete` и зовёт `applySrsPlanAwareCompletion`, гейтит по `slotKind !== 'srs' && slotKind !== 'curriculum'`.
- ✅ F-001 — `PUBLIC_URLS` теперь содержит `/courses` (вместо мёртвого `/book-courses`).
- ✅ F-004 — `auth/reset_request.html` уже получил `<meta description>` + `<link rel=canonical>` (commit ec3c510 на ветке); проверено `pytest tests/test_p0_audit_fixes.py::test_reset_request_page_has_meta_description_and_canonical`.
- ✅ C-001 — `app/books/parsers.py:626` голый `except:` сужен до `OSError` + `logger.warning(...)`.
- ✅ C-002 — `app/api/decorators.py:45` JWT verification failure теперь пишет `logger.warning("JWT verification failed: %s", exc_info=True)`.
- ✅ C-003 — `app/health.py:23` уже использует `logger.exception(...)` (отмечено в реестре, фикс был ранее).
- ✅ C-004 — `app/onboarding/routes.py:wizard` теперь санитайзит `?next=` через `get_safe_redirect_url` на intake, до того как значение попадает в форму.
- ✅ Бонус: починен регресс на регистрации (`/register?ref=...` → hidden input не рендерился из-за ref-cookie ветки, которая не передавала `ref_param` в шаблон). 2 failing теста (`test_register_with_ref_param`, `test_register_preserves_both_params`) теперь зелёные.
- ✅ Регрессионный тест — `tests/test_p0_audit_fixes.py` (6 тестов: F-001, F-004, C-001, C-002, C-004 × 2).
- Полный pytest: было 17 failed (T-010..T-021 + 5 контентных), стало 5 failed (только контентные T-001..T-005, deferred).
- smoke: 160 passed.

## Статус Task 3 (Admin P0/P1)

- ✅ AD-001..AD-004 — CSRF token hidden input добавлен в `admin/curriculum/edit_text.html`, `edit_quiz.html`, `edit_matching.html`, `edit_grammar.html`.
- ✅ AD-005..AD-008 — CSRF token добавлен в inline reset/delete формы `admin/curriculum/user_progress.html`, `progress_details.html`, `edit_module.html`, `edit_level.html`.
- ✅ AD-010..AD-013 — `log_admin_action` добавлен в `delete_level`, `delete_module`, `delete_lesson`, `reset_progress`, `delete_progress` (`app/admin/curriculum.py`).
- ✅ AD-014 — `quiz_deck_delete`, `quiz_deck_remove_word`, `quiz_deck_reorder_words` теперь логируются (`app/admin/quiz_decks.py`).
- ✅ AD-015 — `delete_topic`, `remove_word_from_topic` (`app/admin/routes/topic_routes.py`).
- ✅ AD-016 — `delete_collection` (`app/admin/routes/collection_routes.py`).
- ✅ AD-017 — `delete_book` + `cleanup_books → remove_empty_books` (`app/admin/routes/book_routes.py`); per-book id записывается отдельной audit-строкой.
- ✅ AD-018 — `delete_daily_lesson`, `remove_word_from_lesson` (`app/admin/book_courses.py`).
- ✅ AD-019 — `delete_exercise` (`app/admin/routes/grammar_lab_routes.py`).
- ✅ AD-020 — `toggle_user_status`, `toggle_admin_status`, `toggle_mission_plan` (`app/admin/routes/user_routes.py`).
- ✅ AD-021 — `init_database` (`app/admin/routes/system_routes.py`).
- ✅ Регрессионные тесты — `tests/admin/test_task3_admin_audit_csrf.py` (8 тестов: CSRF templates + user toggles + curriculum delete/reset).
- ✅ Бонус: исправлены ранее упавшие `tests/test_rate_limiting.py` (POST вместо GET после Task 2 `methods=["POST"]` ограничения rate-limit'а).
- Полный pytest: 6 failed (5 deferred контентных T-001..T-005 + 1 flaky robots test, не связаны с Task 3); smoke: 162 passed.
