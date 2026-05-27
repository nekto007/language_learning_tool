---
# Глобальный аудит сайта: баги и улучшения для пользователей

## Overview
Сквозной аудит всего приложения по 14 направлениям. Каждая таска — аудит конкретного
модуля или среза с немедленным исправлением найденных проблем и обновлением тестов.
Цель: устранить баги, улучшить UX, убрать N+1 запросы, закрыть дыры в безопасности,
добавить недостающее покрытие тестами.

## Context
- Files involved: все blueprints (app/), app/templates/ (243 шаблона), app/static/js/ (16 файлов), tests/ (357 файлов)
- Related patterns: api_error, chunk_ids, _safe_widget_call, award_xp, has_learning_activity, get_safe_redirect_url
- Dependencies: pytest, SQLAlchemy, Flask-WTF (CSRF), Flask-Limiter, Flask-Login, Flask-JWT-Extended

## Development Approach
- **Testing approach**: Regular — сначала фикс, потом тест
- Каждая таска = audit findings → fixes → tests
- Перед каждой таской: grep импортов, проверка edge cases
- **CRITICAL: каждая таска MUST включать новые/обновлённые тесты**
- **CRITICAL: pytest -x должен проходить до начала следующей таски**
- Smoke-тесты: pytest -m smoke после каждой группы из 10 тасок

## Implementation Steps

### Task 1: Auth — валидация входных данных и брутфорс-защита

**Files:**
- Modify: `app/auth/routes.py`
- Modify: `tests/auth/test_auth_routes.py`

- [x] Проверить что login/register валидируют длину полей (email ≤254, password ≤128)
- [x] Убедиться что rate limit на /login и /register активен (не только дефолтный)
- [x] Проверить что неверный пароль не раскрывает существование email через разные сообщения
- [x] Проверить что reset-password токен инвалидируется после использования
- [x] Написать/обновить тесты для брутфорс-сценариев и валидации полей
- [x] run pytest tests/auth/ -x

### Task 2: Auth — redirect safety и сессии

**Files:**
- Modify: `app/auth/routes.py`
- Modify: `tests/auth/test_auth_routes.py`

- [x] Убедиться что все ?next= редиректы идут через get_safe_redirect_url (нет open redirect)
- [x] Проверить что после logout сессия полностью очищается (нет утечки данных)
- [x] Проверить что remember_me токен не даёт обойти is_active check
- [x] Проверить что JWT refresh endpoint инвалидирует старый токен
- [x] Тесты для open redirect и сессионных edge cases
- [x] run pytest tests/auth/ -x

### Task 3: Onboarding — flow completeness и edge cases

**Files:**
- Modify: `app/onboarding/routes.py`
- Modify: `tests/test_onboarding*.py`

- [x] Проверить что повторный заход на onboarding routes после completion корректно редиректит
- [x] Убедиться что незаполненный onboarding_level не ломает find_next_lesson
- [x] Проверить что пропуск шагов onboarding не оставляет User в невалидном состоянии
- [x] Проверить timezone и birth_year не принимают мусорные значения
- [x] Тесты для incomplete/skip/retry сценариев onboarding
- [x] run pytest tests/ -k onboarding -x

### Task 4: Daily Plan — сборка плана и edge cases

**Files:**
- Modify: `app/daily_plan/plan.py`
- Modify: `app/daily_plan/service.py`
- Modify: `tests/daily_plan/`

- [x] Проверить поведение get_daily_plan_unified когда нет ни одного доступного урока
- [x] Убедиться что plan_paused_until в прошлом не блокирует план навсегда
- [x] Проверить что total_estimated_minutes не отрицательный при пустых слотах
- [x] Проверить что compute_day_secured_from_activity не падает при пустом плане
- [x] Тесты для empty-plan, paused, и no-lessons-available сценариев
- [x] run pytest tests/daily_plan/ -x

### Task 5: Daily Plan — skip lesson и квота

**Files:**
- Modify: `app/api/daily_plan.py`
- Modify: `app/daily_plan/models.py`
- Modify: `tests/daily_plan/`

- [x] Убедиться что POST /api/daily-plan/skip-lesson возвращает 400 для невалидного lesson_id
- [x] Проверить что already_deferred корректно возвращается при повторном skip
- [x] Убедиться что skip_quota_exhausted корректно считает по user-local date
- [x] Проверить что slot_skipped event не дублируется при concurrent requests
- [x] Тесты для quota edge cases и concurrent skip attempts
- [x] run pytest tests/daily_plan/ -x

### Task 6: Daily Plan — /api/daily-status payload correctness

**Files:**
- Modify: `app/api/daily_plan.py`
- Modify: `tests/api/test_daily_plan_api.py`

- [x] Проверить что leech_suspended_count всегда число (не None)
- [x] Убедиться что srs_limit_reason присутствует только когда != 'normal'
- [x] Проверить что tomorrow_preview не включает suspended/unavailable уроки
- [x] Убедиться что recovery suggestion корректен когда yesterday_plan отсутствует в БД
- [x] Тесты для каждого поля payload при различных состояниях пользователя
- [x] run pytest tests/api/ -x

### Task 7: Curriculum — доступ к урокам и prerequisites

**Files:**
- Modify: `app/curriculum/security.py`
- Modify: `app/curriculum/routes/main.py`
- Modify: `tests/curriculum/`

- [x] Проверить что check_module_access правильно различает API vs HTML запросы
- [x] Убедиться что прямой URL урока без LessonProgress не создаёт дублирующих записей
- [x] Проверить что guest/anonymous запрос на /curriculum/* получает 401, не 500
- [x] Убедиться что prerequisites check не падает когда prerequisites пустой список
- [x] Тесты для direct URL access без prerequisites
- [x] run pytest tests/curriculum/ -x

### Task 8: Curriculum — grading edge cases

**Files:**
- Modify: `app/curriculum/grading.py`
- Modify: `tests/curriculum/test_grading.py`

- [x] Проверить fill-in-blank с unicode символами (диакритика, кириллица)
- [x] Убедиться что _levenshtein не применяется к пустой строке
- [x] Проверить matching когда user_pairs частично заполнен (не все пары)
- [x] Убедиться что score 0 при пустом ответе (не None/error)
- [x] Проверить что грейдер не падает при None в content полях
- [x] Тесты для unicode, empty answer, partial matching edge cases
- [x] run pytest tests/curriculum/test_grading.py -x

### Task 9: Curriculum — final test attempt limit и LessonAttempt

**Files:**
- Modify: `app/curriculum/routes/lessons.py`
- Modify: `tests/curriculum/test_final_test.py`

- [x] Убедиться что process_final_test_submission правильно считает rolling 24h
- [x] Проверить что admin bypass (is_admin=True) работает корректно
- [x] Убедиться что попытка #4 возвращает retry_after в правильном формате (ISO timestamp)
- [x] Проверить что attempts_exhausted не создаёт LessonAttempt запись
- [x] Тесты для 3-attempt limit, admin bypass, retry_after calculation
- [x] run pytest tests/curriculum/ -x

### Task 10: Curriculum — listening и writing lessons completion

**Files:**
- Modify: `app/curriculum/routes/vocabulary_lessons.py`
- Modify: `app/curriculum/listening_service.py`
- Modify: `tests/curriculum/`

- [x] Проверить что log_listening_attempt не падает при score=None
- [x] Убедиться что listening_immersion корректно роутится через LESSON_TYPE_ROUTES
- [x] Проверить что save_writing_attempt не сохраняет пустой response_text
- [x] Убедиться что checklist_completed=False блокирует submission корректно
- [x] Тесты для listening/writing completion и validation
- [x] run pytest tests/curriculum/ -x

### Task 11: SRS — due card counting и budget

**Files:**
- Modify: `app/srs/counting.py`
- Modify: `tests/srs/test_counting.py`

- [x] Проверить что count_due_cards корректен при word_ids=[] (пустой список)
- [x] Убедиться что get_new_card_budget не возвращает отрицательные значения
- [x] Проверить naive-UTC convention: нет tz-aware datetime в srs queries
- [x] Убедиться что chunk_ids используется для больших word_ids списков
- [x] Тесты для empty budgets, large id lists, timezone boundary
- [x] run pytest tests/srs/ -x

### Task 12: SRS — grading и leech logic

**Files:**
- Modify: `app/srs/service.py`
- Modify: `tests/srs/test_srs_service.py`

- [x] Проверить что leech suspend после LEECH_THRESHOLD=6 работает атомарно
- [x] Убедиться что RELEARNING_STEPS=[10, 1440] применяются в правильном порядке
- [x] Проверить что buried карточки не появляются в due list даже при force-refresh
- [x] Убедиться что ease_factor не уходит ниже MIN_EASE_FACTOR при many lapses
- [x] Тесты для leech threshold, relearning steps, buried cards
- [x] run pytest tests/srs/ -x

### Task 13: SRS — lesson-safe flag и daily limits

**Files:**
- Modify: `app/curriculum/routes/card_lessons.py`
- Modify: `tests/srs/`

- [x] Проверить что lesson_safe=true корректно обходит только global new-card limit
- [x] Убедиться что без lesson_safe флага free study уважает daily limits
- [x] Проверить что параллельные запросы с lesson_safe не создают дублирующих карточек
- [x] Тесты для lesson_safe bypass и free-study limit enforcement
- [x] run pytest tests/srs/ tests/curriculum/ -x

### Task 14: Books — reading progress и compute_book_progress_percent

**Files:**
- Modify: `app/books/progress.py`
- Modify: `tests/books/test_progress.py`

- [x] Проверить что compute_book_progress_percent возвращает 0.0 при 0 глав
- [x] Убедиться что max_partial_of_incomplete не суммируется неправильно при multiple incomplete
- [x] Проверить что прогресс не превышает 100% при edge cases
- [x] Убедиться что progress recalculation thread-safe (нет dirty reads)
- [x] Тесты для 0 chapters, all-complete, partial-complete, >100% guard
- [x] run pytest tests/books/ -x

### Task 15: Books — reading session start/end и time gate

**Files:**
- Modify: `app/books/reading_session.py`
- Modify: `app/books/api.py`
- Modify: `tests/books/`

- [x] Проверить что end_session(session_id) возвращает 403 для чужой сессии
- [x] Убедиться что start_session не создаёт дублирующих сессий для одной главы
- [x] Проверить что has_min_reading_time_today >= 60s правильно агрегирует multiple sessions
- [x] Убедиться что offset_delta < 0 не ломает агрегацию
- [x] Тесты для ownership check, duplicate sessions, negative offset
- [x] run pytest tests/books/ -x

### Task 16: Books — book catalog и доступ

**Files:**
- Modify: `app/books/routes.py`
- Modify: `tests/books/test_routes.py`

- [x] Проверить что неавторизованный пользователь не видит premium книги
- [x] Убедиться что chapter pagination работает при chapter_index=0 и last chapter
- [x] Проверить что book detail page не падает для книги без chapters
- [x] Убедиться что книга с is_published=False недоступна через прямой URL
- [x] Тесты для access control, empty chapters, unpublished books
- [x] run pytest tests/books/ -x

### Task 17: Words — word detail и translation lookup

**Files:**
- Modify: `app/words/routes.py`
- Modify: `app/words/detail_service.py`
- Modify: `tests/words/`

- [x] Проверить что /words/<word_id> возвращает 404 для несуществующего word_id
- [x] Убедиться что translation lookup не раскрывает внутренние ошибки через 500
- [x] Проверить что ipa_transcription=None не ломает шаблон
- [x] Убедиться что synonyms/antonyms=None рендерятся как пустой список (не "None")
- [x] Тесты для 404, None fields, translation failure graceful degradation
- [x] run pytest tests/words/ -x

### Task 18: Words — collocation и vocabulary depth fields

**Files:**
- Modify: `app/words/routes.py`
- Modify: `tests/words/`

- [x] Проверить что WordCollocation query не падает при word без collocations
- [x] Убедиться что VocabAnnotation AJAX save возвращает 400 для пустой note
- [x] Проверить что frequency_band=None не ломает UI (нет KeyError)
- [x] Убедиться что etymology с HTML-тегами санируется перед рендерингом
- [x] Тесты для empty collocations, annotation validation, HTML sanitization
- [x] run pytest tests/words/ -x

### Task 19: Words — import preview и confirm performance

**Files:**
- Modify: `app/words/routes.py`
- Modify: `tests/words/test_import.py`

- [x] Убедиться что bulk import preview использует chunk_ids для >1000 слов
- [x] Проверить что повторный import одного слова не создаёт дубликатов
- [x] Убедиться что import с невалидным CSV не падает с 500
- [x] Проверить что import limit MAX_EXPORT_ROWS=10000 применяется на import тоже
- [x] Тесты для large import, duplicate prevention, invalid CSV
- [x] run pytest tests/words/ -x

### Task 20: Grammar Lab — exercise validation и cascade

**Files:**
- Modify: `app/grammar_lab/content_validator.py`
- Modify: `app/grammar_lab/routes.py`
- Modify: `tests/grammar_lab/`

- [x] Проверить что validate_exercise_content поднимает ValueError для всех неверных типов
- [x] Убедиться что удаление GrammarExercise каскадно удаляет UserGrammarExercise
- [x] Проверить что routes возвращают 400 (не 500) при невалидном exercise content
- [x] Убедиться что grammar SRS не создаёт сессий для несуществующих упражнений
- [x] Тесты для validation errors, cascade delete, 400 responses
- [x] run pytest tests/grammar_lab/ -x

### Task 21: Grammar Lab — mastery и difficulty seeding

**Files:**
- Modify: `app/grammar_lab/models.py`
- Modify: `app/grammar_lab/grammar_srs.py`
- Modify: `tests/grammar_lab/`

- [x] Проверить что MASTERED_THRESHOLD_DAYS=30 применяется к UserGrammarExercise (не 180)
- [x] Убедиться что compute_initial_ease_for_difficulty не уходит ниже MIN_EASE при difficulty=1.0
- [x] Проверить что get_or_create не создаёт дубликатов при concurrent requests
- [x] Тесты для mastery threshold, ease seeding, concurrent get_or_create
- [x] run pytest tests/grammar_lab/ -x

### Task 22: Achievements — grant_achievement race safety

**Files:**
- Modify: `app/achievements/services.py`
- Modify: `tests/achievements/`

- [x] Проверить что grant_achievement при IntegrityError возвращает existing record (не None)
- [x] Убедиться что проверка ачивки check_immersion_achievement корректна для timezone edge
- [x] Проверить что check_challenge_achievements не дублирует ачивки при retry
- [x] Убедиться что check_listening/writing/speaking achievements не падают при 0 attempts
- [x] Тесты для race condition, timezone boundary, zero-attempt edge cases
- [x] run pytest tests/achievements/ -x

### Task 23: Achievements — XP award и idempotency

**Files:**
- Modify: `app/achievements/xp_service.py`
- Modify: `tests/achievements/test_xp_service.py`

- [x] Проверить что award_xp с score=0 даёт 50% base (не 0)
- [x] Убедиться что award_game_xp_idempotent с неверным session_id возвращает None
- [x] Проверить что streak multiplier корректно капируется на 2.0
- [x] Убедиться что consecutive perfect-day multipliers не применяются при broken streak
- [x] Тесты для score=0/100, wrong session_id, multiplier cap, broken streak
- [x] run pytest tests/achievements/ -x

### Task 24: Streak — has_learning_activity и все источники

**Files:**
- Modify: `app/utils/activity_tracker.py`
- Modify: `tests/test_activity_tracker.py`

- [x] Проверить что все 8 источников активности учитываются
- [x] Убедиться что has_learning_activity не падает при start_utc > end_utc
- [x] Проверить что StreakEvent с xp_linear% корректно матчит LIKE pattern
- [x] Убедиться что streak shield применяется до increment (не после)
- [x] Тесты для all 8 sources, invalid date range, shield application order
- [x] run pytest tests/ -k streak -x

### Task 25: Streak — get_immersion_streak и 4 skill check

**Files:**
- Modify: `app/achievements/streak_service.py`
- Modify: `tests/achievements/test_streak_service.py`

- [x] Проверить что get_immersion_streak правильно требует ВСЕ 4 skill в один день
- [x] Убедиться что отсутствие одного skill обнуляет consecutive count
- [x] Проверить что immersion_week achievement не дублируется при повторном check
- [x] Убедиться что get_listening/writing/speaking_streak корректно считает consecutive days
- [x] Тесты для 4-skill requirement, streak break, duplicate achievement prevention
- [x] run pytest tests/achievements/ -x

### Task 26: Notifications — создание и user preferences

**Files:**
- Modify: `app/notifications/services.py`
- Modify: `app/notifications/routes.py`
- Modify: `tests/test_notifications.py`

- [x] Проверить что создание notification уважает все preference flags
- [x] Убедиться что notification dropdown рендерится через textContent (нет innerHTML XSS)
- [x] Проверить что mark-as-read не позволяет чужому пользователю помечать чужие уведомления
- [x] Убедиться что bulk mark-all-read использует user_id из сессии (не из body)
- [x] Тесты для preference flags, XSS prevention, ownership check
- [x] run pytest tests/ -k notification -x

### Task 27: Daily Race — matchmaking и ghost participants

**Files:**
- Modify: `app/achievements/daily_race.py`
- Modify: `tests/test_daily_race.py`

- [x] Проверить что get_or_create_race не создаёт дублирующих участников при concurrent requests
- [x] Убедиться что ghost points не хранятся в БД (только вычисляются)
- [x] Проверить что adult-gate (birth_year check) корректно работает при birth_year=None
- [x] Убедиться что route_position (0-100) не выходит за границы
- [x] Тесты для concurrent race creation, null birth_year, position bounds
- [x] run pytest tests/ -k daily_race -x

### Task 28: Study — deck management и card ownership

**Files:**
- Modify: `app/study/deck_routes.py`
- Modify: `tests/study/test_study_deck_routes.py`

- [x] Проверить что GET /study/deck/<id> возвращает 404 для несуществующего deck
- [x] Убедиться что чужой пользователь не может edit/delete чужой deck
- [x] Проверить что удаление deck каскадно удаляет DeckCard и QuizResult
- [x] Убедиться что deck без карточек не крашит quiz start
- [x] Тесты для 404, ownership, cascade delete, empty deck quiz
- [x] run pytest tests/study/ -x

### Task 29: Study — game routes и score submission

**Files:**
- Modify: `app/study/game_routes.py`
- Modify: `tests/study/`

- [x] Проверить что score submit не принимает score > 100 или < 0
- [x] Убедиться что game session не переиспользуется чужим пользователем
- [x] Проверить что award_game_xp_idempotent вызывается с verified session_id
- [x] Убедиться что game result page не падает при deleted deck
- [x] Тесты для score bounds, session ownership, deleted-deck result
- [x] run pytest tests/study/ -x

### Task 30: Study — insights и analytics widgets

**Files:**
- Modify: `app/study/insights_service.py`
- Modify: `tests/study/`

- [x] Проверить что get_skills_balance возвращает dict с 6 ключами всегда (нет KeyError)
- [x] Убедиться что get_listening/writing/pronunciation_stats не падают при 0 attempts
- [x] Проверить что все виджеты обёрнуты в _safe_widget_call (нет необёрнутых вызовов)
- [x] Убедиться что Chart.js данные sanitized перед вставкой в шаблон
- [x] Тесты для empty stats, missing widget graceful failure
- [x] run pytest tests/study/ -x

### Task 31: Study — SRS stats и leaderboard

**Files:**
- Modify: `app/study/services/stats_service.py`
- Modify: `app/words/routes.py` (leaderboard caching)
- Modify: `tests/study/`

- [x] Проверить что _get_cached_leaderboard не возвращает stale data после user XP change
- [x] Убедиться что leaderboard правильно читает UserStatistics.total_xp (не legacy UserXP)
- [x] Проверить что stats_service не падает при User без UserStatistics row
- [x] Убедиться что get_level_info(0) возвращает level=1 (не level=0)
- [x] Тесты для missing UserStatistics, level=0 guard, cache staleness
- [x] run pytest tests/study/ -x

### Task 32: API — стандартизация ошибок через api_error

**Files:**
- Modify: `app/api/errors.py`
- Modify: `app/api/daily_plan.py`, `app/api/books.py`, `app/api/words.py`
- Modify: `tests/api/test_api_error_format.py`

- [x] Проверить что все API endpoints используют api_error вместо ad-hoc dict ответов
- [x] Убедиться что status codes консистентны (400 для валидации, 403 для доступа, 404 для not found)
- [x] Проверить что 500 ошибки не утекают stack traces в production
- [x] Убедиться что error response всегда имеет поля code, message
- [x] Тесты для каждого error scenario в ключевых API endpoints
- [x] run pytest tests/api/ -x

### Task 33: API — CSRF и аутентификация

**Files:**
- Modify: `app/api/auth.py`
- Modify: `app/__init__.py`
- Modify: `tests/api/`

- [x] Проверить что все мутирующие API endpoints (POST/PUT/DELETE) защищены CSRF или JWT
- [x] Убедиться что @csrf.exempt применён только там, где есть JWT проверка
- [x] Проверить что JWT expired token возвращает 401 с понятным сообщением
- [x] Убедиться что refresh endpoint не принимает access token вместо refresh token
- [x] Тесты для CSRF missing, expired JWT, wrong token type
- [x] run pytest tests/api/ -x

### Task 34: API — rate limiting coverage

**Files:**
- Modify: `app/curriculum/rate_limiter.py`
- Modify: `app/__init__.py`
- Modify: `tests/test_rate_limiting.py`

- [x] Проверить что submission endpoints (grading, SRS review) имеют tight rate limits
- [x] Убедиться что rate limit storage настроен на Redis в production (не memory)
- [x] Проверить что rate limit response имеет Retry-After header
- [x] Убедиться что admin endpoints имеют отдельный rate limit (не shared с user endpoints)
- [x] Тесты для rate limit headers, storage fallback
- [x] run pytest tests/test_rate_limiting.py -x

### Task 35: Security — file upload validation

**Files:**
- Modify: `app/utils/file_security.py`
- Modify: `app/uploads/routes.py`
- Modify: `tests/`

- [x] Проверить что file upload проверяет magic bytes, не только extension
- [x] Убедиться что filename sanitized перед сохранением (path traversal prevention)
- [x] Проверить что upload size limit enforced (не только config, но и код)
- [x] Убедиться что служебные файлы (.env, .py) не могут быть загружены
- [x] Тесты для magic bytes, path traversal, size limit, forbidden extensions
- [x] run pytest tests/ -k upload -x

### Task 36: Security — XSS prevention в templates

**Files:**
- Modify: `app/templates/` (поиск |safe фильтров)
- Modify: `tests/test_bleach_sanitization.py`

- [x] Grep все |safe usage в шаблонах и убедиться что каждый оправдан
- [x] Проверить что user-supplied контент (заметки, аннотации) не рендерится с |safe
- [x] Убедиться что etymology и description поля Word sanitized через bleach
- [x] Проверить что notification dropdown использует textContent везде (не innerHTML)
- [x] Тесты для XSS через annotation, word description, notification
- [x] run pytest tests/test_bleach_sanitization.py -x

### Task 37: Security — SQL injection и ORM safety

**Files:**
- Modify: `app/admin/routes/` (поиск raw SQL)
- Modify: `tests/`

- [x] Grep text() usage и убедиться что все параметры bindparam'ы, не f-strings
- [x] Проверить admin search endpoints на ORM filter injection
- [x] Убедиться что CSV export _sanitize_csv_cell применяется ко всем полям
- [x] Проверить что admin user search не раскрывает hashed passwords через API
- [x] Тесты для parametrized queries, CSV injection, password leakage
- [x] run pytest tests/ -k security -x

### Task 38: Security — headers и CSP

**Files:**
- Modify: `app/middleware/security.py`
- Modify: `tests/`

- [x] Убедиться что CSP header включает nonce для inline scripts
- [x] Проверить что HSTS header с preload для production
- [x] Убедиться что X-Content-Type-Options: nosniff присутствует
- [x] Проверить что Referrer-Policy header выставлен
- [x] Тесты для всех security headers
- [x] run pytest tests/ -k security -x

### Task 39: Admin — user management security

**Files:**
- Modify: `app/admin/routes/user_routes.py`
- Modify: `app/admin/services/user_management_service.py`
- Modify: `tests/admin/test_admin_users.py`

- [x] Убедиться что все user-management endpoints защищены admin_required
- [x] Проверить что изменение is_admin флага логируется через AdminAuditLog
- [x] Убедиться что admin не может деактивировать свой собственный аккаунт
- [x] Проверить что user export sanitizes поля через _sanitize_csv_cell
- [x] Тесты для admin self-deactivation prevention, audit logging
- [x] run pytest tests/admin/ -x

### Task 40: Admin — SiteSettings validation

**Files:**
- Modify: `app/admin/site_settings.py`
- Modify: `app/admin/routes/settings_routes.py`
- Modify: `tests/admin/test_admin_settings.py`

- [x] Убедиться что validate_setting_value вызывается перед set_site_setting везде
- [x] Проверить что SettingValidationError возвращает 400 (не 500)
- [x] Убедиться что ensure_defaults_seeded идемпотентен при concurrent startup
- [x] Проверить что GSC токены не утекают в error messages
- [x] Тесты для validation errors, concurrent seeding, token leakage
- [x] run pytest tests/admin/test_admin_settings.py -x

### Task 41: Admin — audit log completeness

**Files:**
- Modify: `app/admin/routes/` (поиск destructive operations без audit)
- Modify: `app/admin/utils/decorators.py`
- Modify: `tests/admin/test_audit.py`

- [x] Grep все DELETE/dangerous POST endpoints и проверить наличие AdminAuditLog
- [x] Убедиться что @admin_audit_required не создаёт audit row при 4xx/5xx
- [x] Проверить что audit log UI корректно отображает target_id=None
- [x] Убедиться что audit log не утекает sensitive данные (passwords, tokens) в details
- [x] Тесты для missing audit on destructive ops, null target_id, sensitive data filtering
- [x] run pytest tests/admin/test_audit.py -x

### Task 42: Admin — dashboard N+1 queries

**Files:**
- Modify: `app/admin/main_routes.py`
- Modify: `app/admin/routes/dashboard_routes.py`
- Modify: `tests/admin/test_admin_dashboard.py`

- [x] Профилировать dashboard queries через SQLAlchemy echo
- [x] Убедиться что DAU/WAU/MAU использует UNION query (не 7 отдельных)
- [x] Проверить что _count_active_users_in_range не делает N+1 для каждого дня
- [x] Убедиться что dashboard cache работает (нет cache miss на каждый request)
- [x] Тесты для query count bounded, cache hit
- [x] run pytest tests/admin/test_admin_dashboard.py -x

### Task 43: Admin — cohort и funnel data correctness

**Files:**
- Modify: `app/admin/services/cohort_service.py`
- Modify: `tests/admin/test_cohort.py`

- [x] Проверить что funnel steps монотонно невозрастающие (каждый шаг ≤ предыдущего)
- [x] Убедиться что все datetime сравнения naive UTC (нет tz-aware mix)
- [x] Проверить что retention calculation корректна при 0 users в cohort
- [x] Убедиться что days/weeks параметры валидируются (нет SQL injection через них)
- [x] Тесты для monotonic funnel, zero-cohort, parameter validation
- [x] run pytest tests/admin/test_cohort.py -x

### Task 44: Admin — book management и sync

**Files:**
- Modify: `app/curriculum/book_courses.py`
- Modify: `app/admin/routes/book_routes.py`
- Modify: `tests/admin/`

- [x] Убедиться что sync_book_course_from_book не перезатирает title/description
- [x] Проверить что book delete каскадно обрабатывает связанные BookCourse
- [x] Убедиться что book slug unique constraint выдаёт понятную ошибку (не 500)
- [x] Проверить что audio file upload для book chapter проверяет MIME type
- [x] Тесты для sync fields, cascade delete, slug conflict
- [x] run pytest tests/admin/ -x

### Task 45: Admin — curriculum import preview

**Files:**
- Modify: `app/admin/services/curriculum_import_service.py`
- Modify: `tests/admin/`

- [x] Убедиться что import preview не создаёт DB записей (только preview)
- [x] Проверить что batch DB lookups используют chunk_ids
- [x] Убедиться что невалидный JSON не вызывает 500 (graceful 400)
- [x] Проверить что import подтверждение идемпотентно при двойном submit
- [x] Тесты для preview-no-write, invalid JSON, double submit
- [x] run pytest tests/admin/ -x

### Task 46: Frontend — dashboard UX

**Files:**
- Modify: `app/templates/words/dashboard_unified.html`
- Modify: `app/templates/partials/unified_daily_plan.html`
- Modify: `app/static/css/design-system.css`

- [x] Проверить что skeleton loaders не остаются видимыми после загрузки данных
- [x] Убедиться что .btn--loading класс применяется на все кнопки с network requests
- [x] Проверить что empty state показывается когда план пустой (не blank screen)
- [x] Убедиться что day_secured визуально отражается в UI (нет de-sync с payload)
- [x] Проверить что dashboard не крашит JS при null значениях в plan payload
- [x] run pytest -m smoke -x

### Task 47: Frontend — lesson shell и progress indicators

**Files:**
- Modify: `app/templates/curriculum/lessons/`
- Modify: `app/static/css/design-system.css`

- [x] Проверить что .lesson-shell__progress обновляется при переходе между шагами
- [x] Убедиться что .result-badge[--correct|--incorrect] не остаётся видимым после retry
- [x] Проверить что .input--checking состояние не зависает при network error
- [x] Убедиться что prefers-reduced-motion корректно подавляет все анимации уроков
- [x] Проверить что lesson completion не отправляется дважды при double-click
- [x] run pytest -m smoke -x

### Task 48: Frontend — mobile responsiveness

**Files:**
- Modify: `app/templates/` (mobile-specific issues)
- Modify: `app/static/css/design-system.css`
- Modify: `app/static/js/mobile-reader.js`

- [x] Проверить что dashboard читаем на 375px (iPhone SE)
- [x] Убедиться что lesson shell не overflow на мобильных
- [x] Проверить что audio controls доступны на mobile (не скрыты CSS)
- [x] Убедиться что collocation_matching drag-and-drop работает на touch
- [x] Проверить что modal окна не выходят за экран на small screens
- [x] run pytest -m smoke -x

### Task 49: Frontend — Web Speech API fallback

**Files:**
- Modify: `app/static/js/speech_api.js`
- Modify: `app/templates/curriculum/lessons/pronunciation.html`

- [x] Проверить что self-assess fallback показывается когда Web Speech API недоступен
- [x] Убедиться что микрофон permission denied обрабатывается (не пустой экран)
- [x] Проверить что speech recognition не стартует при prefers-reduced-motion
- [x] Убедиться что pronunciation attempt записывается даже при self-assess
- [x] Тесты для fallback path, permission denied, self-assess recording
- [x] run pytest tests/curriculum/ -k pronunciation -x

### Task 50: Frontend — JS error handling в daily-plan-next.js

**Files:**
- Modify: `app/static/js/daily-plan-next.js`
- Modify: `app/static/js/unified-js.js`

- [x] Проверить что network errors при plan fetch показывают retry кнопку (не blank)
- [x] Убедиться что JSON parse error не крашит весь план (graceful fallback)
- [x] Проверить что skip-lesson request показывает loading state во время ожидания
- [x] Убедиться что continuation endpoint failure не блокирует основной план
- [x] Тесты для network error UI, JSON parse failure
- [x] run pytest -m smoke -x

### Task 51: Reader — книжный ридер и progress sync

**Files:**
- Modify: `app/static/js/reader.js`
- Modify: `app/books/api.py`
- Modify: `tests/books/`

- [x] Проверить что reading progress sync не дублируется при rapid scroll
- [x] Убедиться что reading session end вызывается при page unload (не только explicit)
- [x] Проверить что reader не теряет позицию при tab switch + return
- [x] Убедиться что offset_delta всегда 0..1 (не > 1 при fast read)
- [x] Тесты для scroll dedup, unload handler, offset bounds
- [x] run pytest tests/books/ -x

### Task 52: Email — templates и deliverability

**Files:**
- Modify: `app/templates/emails/`
- Modify: `app/utils/email_utils.py`
- Modify: `tests/`

- [x] Проверить что email templates корректно рендерятся при None значениях
- [x] Убедиться что unsubscribe link в каждом marketing email
- [x] Проверить что email sending ошибки логируются (не тихо игнорируются)
- [x] Убедиться что DEBUG smtp не используется в production конфиге
- [x] Тесты для None values in templates, error logging
- [x] run pytest tests/ -k email -x

### Task 53: Telegram — webhook security и idempotency

**Files:**
- Modify: `app/telegram/routes.py`
- Modify: `tests/telegram/`

- [x] Проверить что webhook endpoint проверяет X-Telegram-Bot-Api-Secret-Token
- [x] Убедиться что повторная обработка одного update_id идемпотентна
- [x] Проверить что TelegramUser linking не позволяет hijack чужого аккаунта
- [x] Убедиться что webhook не раскрывает bot token через error messages
- [x] Тесты для secret token check, idempotency, account linking security
- [x] run pytest tests/telegram/ -x

### Task 54: SEO — sitemap и canonical correctness

**Files:**
- Modify: `app/seo/routes.py`
- Modify: `tests/test_landing_improvements.py`

- [x] Проверить что sitemap не включает noindex страницы
- [x] Убедиться что canonical URL использует url_for(_external=True) (нет hardcoded domain)
- [x] Проверить что sitemap lastmod дата корректна (не future date)
- [x] Убедиться что robots.txt не блокирует /curriculum/ и /study/ routes
- [x] Тесты для noindex exclusion, canonical format, lastmod validity
- [x] run pytest tests/ -k seo -x

### Task 55: Landing — page performance и SEO meta

**Files:**
- Modify: `app/landing/routes.py`
- Modify: `app/templates/landing/`
- Modify: `tests/test_landing_improvements.py`

- [x] Проверить что og:image присутствует и указывает на реальный файл
- [x] Убедиться что title и meta description уникальны для каждой страницы
- [x] Проверить что landing page не делает N+1 запросов к БД
- [x] Убедиться что landing page работает для anonymous users (нет current_user зависимостей)
- [x] Тесты для meta completeness, anonymous access, query count
- [x] run pytest tests/test_landing_improvements.py -x

### Task 56: Health check и monitoring

**Files:**
- Modify: `app/health.py`
- Modify: `tests/`

- [x] Проверить что /health endpoint проверяет DB connectivity
- [x] Убедиться что /health не требует аутентификации (доступен для load balancer)
- [x] Проверить что health response содержит version/timestamp
- [x] Убедиться что DB connection timeout не вешает /health на 30с
- [x] Тесты для DB-down scenario, response format, auth bypass
- [x] run pytest tests/ -k health -x

### Task 57: Migrations — chain consistency и idempotency

**Files:**
- Modify: `migrations/`
- Modify: `tests/migrations/test_migration_chain.py`

- [ ] Проверить migration chain (нет gaps, нет branching)
- [ ] Убедиться что все CASCADE migrations идемпотентны (повторный запуск безопасен)
- [ ] Проверить что migration для streak_shield column имеет корректный DEFAULT
- [ ] Убедиться что alembic downgrade не ломает данные для последних 5 миграций
- [ ] run pytest tests/migrations/ -x

### Task 58: Performance — N+1 в curriculum routes

**Files:**
- Modify: `app/curriculum/routes/main.py`
- Modify: `app/curriculum/routes/lessons.py`
- Modify: `tests/curriculum/`

- [ ] Профилировать /curriculum/ page (joinedload для Module+Lesson+Topic)
- [ ] Убедиться что lesson page не делает отдельный query для каждого связанного объекта
- [ ] Проверить что curriculum cache (app/curriculum/cache.py) используется в hot paths
- [ ] Убедиться что cache invalidation происходит при admin content edit
- [ ] Тесты для query count на curriculum page
- [ ] run pytest tests/curriculum/ -x

### Task 59: Performance — N+1 в words и books routes

**Files:**
- Modify: `app/words/routes.py`
- Modify: `app/books/routes.py`
- Modify: `tests/`

- [ ] Проверить что word list page использует joinedload для translations
- [ ] Убедиться что book catalog не делает N+1 для chapter counts
- [ ] Проверить что UserWord query использует bulk load (не per-word)
- [ ] Убедиться что chunk_ids используется для bulk word lookups
- [ ] Тесты для query count bounds на list pages
- [ ] run pytest tests/words/ tests/books/ -x

### Task 60: Performance — caching strategy

**Files:**
- Modify: `app/words/routes.py` (_get_cached_leaderboard)
- Modify: `app/admin/services/seo_audit_service.py`
- Modify: `app/__init__.py` (_inject_site_settings)

- [ ] Проверить что leaderboard cache правильно инвалидируется при XP update
- [ ] Убедиться что SEO audit cache key включает version (для cross-worker invalidation)
- [ ] Проверить что _inject_site_settings не делает DB query на каждый request
- [ ] Убедиться что curriculum cache не растёт бесконечно (есть TTL или eviction)
- [ ] Тесты для cache invalidation, TTL expiry
- [ ] run pytest -m smoke -x

### Task 61: SiteSettings — feature flags и race-safe

**Files:**
- Modify: `app/admin/site_settings.py`
- Modify: `tests/admin/test_admin_settings.py`

- [ ] Проверить что daily_race_enabled flag корректно gate'ит DailyRace endpoint
- [ ] Убедиться что streak_shield_enabled flag корректно gate'ит shield logic
- [ ] Проверить что get_site_setting не делает DB query при уже seeded значении
- [ ] Убедиться что concurrent set_site_setting не создаёт duplicate rows
- [ ] Тесты для feature flag gating, concurrent set
- [ ] run pytest tests/admin/test_admin_settings.py -x

### Task 62: Word of Day и public widgets

**Files:**
- Modify: `app/words/routes.py` (word of day logic)
- Modify: `tests/test_word_of_day.py`

- [ ] Проверить что word of day консистентен в течение дня (нет per-request randomness)
- [ ] Убедиться что word of day работает для anonymous users
- [ ] Проверить что word без translations не ломает word of day
- [ ] Убедиться что word of day не возвращает suspended/deleted words
- [ ] Тесты для daily consistency, anonymous access, no-translation word
- [ ] run pytest tests/test_word_of_day.py -x

### Task 63: Referral система и idempotency

**Files:**
- Modify: `app/auth/routes.py` (referral handling)
- Modify: `app/achievements/xp_service.py` (award_referral_xp_idempotent)
- Modify: `tests/auth/`

- [ ] Проверить что referral XP начисляется только один раз per referee
- [ ] Убедиться что referral link URL использует url_for(_external=True)
- [ ] Проверить что невалидный referral code не ломает registration
- [ ] Убедиться что самореферрал (referrer == referee) блокируется
- [ ] Тесты для idempotency, invalid code, self-referral prevention
- [ ] run pytest tests/auth/ -x

### Task 64: Plan pause/resume и streak neutrality

**Files:**
- Modify: `app/api/daily_plan.py` (pause/resume endpoints)
- Modify: `app/daily_plan/service.py`
- Modify: `tests/daily_plan/`

- [ ] Проверить что POST /api/plan/pause принимает только валидные date параметры
- [ ] Убедиться что paused дни не ломают streak (streak_neutral)
- [ ] Проверить что resume до paused_until даты корректно работает
- [ ] Убедиться что plan_paused_until в прошлом не блокирует план
- [ ] Тесты для pause validation, streak neutrality, early resume
- [ ] run pytest tests/daily_plan/ -x

### Task 65: DailyChallenge — completion и achievements

**Files:**
- Modify: `app/daily_plan/challenge.py`
- Modify: `tests/`

- [ ] Проверить что get_today_challenge возвращает None корректно (не 500) когда нет challenge
- [ ] Убедиться что challenge completion не дублируется при retry
- [ ] Проверить что bonus_xp начисляется только при реальном completion (не при view)
- [ ] Убедиться что challenge_streak_7 achievement проверяется корректно
- [ ] Тесты для no-challenge day, duplicate prevention, streak check
- [ ] run pytest tests/ -k challenge -x

### Task 66: Milestones и next_step continuation

**Files:**
- Modify: `app/daily_plan/milestones.py`
- Modify: `app/daily_plan/next_step.py`
- Modify: `tests/daily_plan/`

- [ ] Проверить что get_next_best_step возвращает [] (не None) когда нечего делать
- [ ] Убедиться что NextStep.estimated_minutes всегда положительное число
- [ ] Проверить что priority ordering стабильна при одинаковых условиях
- [ ] Убедиться что GET /api/daily-plan/continuation не падает при новом пользователе
- [ ] Тесты для empty result, estimated_minutes bounds, new user
- [ ] run pytest tests/daily_plan/ -x

### Task 67: Grammar weakness hint и curriculum item enrichment

**Files:**
- Modify: `app/daily_plan/items/curriculum.py`
- Modify: `tests/daily_plan/`

- [ ] Проверить что _get_weak_grammar_topic_ids не падает при 0 attempts
- [ ] Убедиться что weak_topic_hint=True не меняет spine (только enrichment)
- [ ] Проверить что min_attempts=3 threshold корректно фильтрует новых пользователей
- [ ] Убедиться что max_accuracy=0.6 граница корректно вычисляется
- [ ] Тесты для zero attempts, spine invariance, threshold boundary
- [ ] run pytest tests/daily_plan/ -x

### Task 68: Error review — scaling и pool

**Files:**
- Modify: `app/daily_plan/linear/errors.py`
- Modify: `tests/daily_plan/`

- [ ] Проверить что get_review_pool_size возвращает корректные значения для граничных случаев
- [ ] Убедиться что dynamic cooldown правильно применяется (≥15/≥25 unresolved)
- [ ] Проверить что get_sibling_exercise не возвращает оригинальное упражнение
- [ ] Убедиться что log_quiz_errors_from_result пишет exercise_id и difficulty
- [ ] Тесты для pool size boundaries, sibling exclusion, error logging
- [ ] run pytest tests/daily_plan/ -x

### Task 69: Curriculum XP — idempotency и for_date

**Files:**
- Modify: `app/curriculum/xp.py`
- Modify: `app/daily_plan/linear/xp.py`
- Modify: `tests/`

- [ ] Проверить что award_curriculum_lesson_xp_idempotent flush only (не commit)
- [ ] Убедиться что for_date использует get_user_local_date (не UTC now)
- [ ] Проверить что повторный complete_lesson не дублирует StreakEvent
- [ ] Убедиться что maybe_award_listening/writing_xp корректно проверяют idempotency key
- [ ] Тесты для flush-only, date source, duplicate prevention
- [ ] run pytest tests/ -k xp -x

### Task 70: Rank system — check_rank_up и notifications

**Files:**
- Modify: `app/achievements/ranks.py`
- Modify: `app/achievements/services.py`
- Modify: `tests/achievements/`

- [ ] Проверить что check_rank_up не дублирует notification при concurrent requests
- [ ] Убедиться что get_user_rank возвращает Novice при plans_completed=0
- [ ] Проверить что rank notification создаётся через notifications/services.py (с preference check)
- [ ] Убедиться что rank fields (plans_completed_total, current_rank) корректно обновляются
- [ ] Тесты для zero plans, concurrent rank-up, notification preference
- [ ] run pytest tests/achievements/ -x

### Task 71: BookCourse — enrollment и progress

**Files:**
- Modify: `app/curriculum/routes/book_courses.py`
- Modify: `app/curriculum/routes/book_courses_api.py`
- Modify: `tests/`

- [ ] Проверить что enrollment idempotent (повторный enroll не создаёт дублей)
- [ ] Убедиться что chapter completion XP не начисляется дважды
- [ ] Проверить что book course progress корректен при removed chapter
- [ ] Убедиться что unenrollment cascade обрабатывает все связанные записи
- [ ] Тесты для idempotent enrollment, removed chapter, unenrollment
- [ ] run pytest tests/ -k book_course -x

### Task 72: Comprehension generator и lesson content quality

**Files:**
- Modify: `app/curriculum/services/comprehension_generator.py`
- Modify: `app/curriculum/services/task_generators.py`
- Modify: `tests/curriculum/`

- [ ] Проверить что generator не падает при None в lesson content полях
- [ ] Убедиться что generated content проходит validate_exercise_content
- [ ] Проверить что generator не создаёт duplicate вопросы для одного текста
- [ ] Убедиться что block_schema_importer корректно handles unknown lesson types
- [ ] Тесты для None content, validation pass, dedup, unknown types
- [ ] run pytest tests/curriculum/ -x

### Task 73: Audio — файлы и endpoints

**Files:**
- Modify: `app/admin/routes/audio_routes.py`
- Modify: `app/admin/services/audio_management_service.py`
- Modify: `tests/admin/`

- [ ] Проверить что audio upload проверяет MIME type (audio/mpeg, audio/wav only)
- [ ] Убедиться что audio delete каскадно убирает ссылки из lesson content
- [ ] Проверить что audio streaming endpoint имеет Range header support
- [ ] Убедиться что служебные audio файлы недоступны без авторизации
- [ ] Тесты для MIME check, cascade delete, range requests
- [ ] run pytest tests/admin/ -x

### Task 74: Reminders — delivery и preferences

**Files:**
- Modify: `app/reminders/routes.py`
- Modify: `tests/`

- [ ] Проверить что reminder delivery уважает user timezone
- [ ] Убедиться что unsubscribe через email link работает без authentication
- [ ] Проверить что reminder не отправляется suspended/deleted users
- [ ] Убедиться что reminder frequency не превышает configured rate
- [ ] Тесты для timezone delivery, unsubscribe, suspended user skip
- [ ] run pytest tests/ -k reminder -x

### Task 75: Modules — feature gates и activation

**Files:**
- Modify: `app/modules/routes.py`
- Modify: `app/modules/decorators.py`
- Modify: `tests/`

- [ ] Проверить что @feature_gate decorator правильно проверяет UserModule status
- [ ] Убедиться что деактивированный модуль недоступен через прямой URL
- [ ] Проверить что module activation не создаёт дублирующих UserModule записей
- [ ] Убедиться что modules page корректна для пользователя без активных модулей
- [ ] Тесты для feature gate, direct URL block, duplicate activation
- [ ] run pytest tests/ -k module -x

### Task 76: Public courses — catalog и доступ

**Files:**
- Modify: `app/curriculum/routes/public.py`
- Modify: `tests/test_public_courses.py`

- [ ] Проверить что публичный каталог не раскрывает unpublished courses
- [ ] Убедиться что anonymous user может просматривать catalog (не 302 на login)
- [ ] Проверить что enrollment из public catalog работает для new users
- [ ] Убедиться что course preview не раскрывает premium content
- [ ] Тесты для unpublished filter, anonymous access, enrollment flow
- [ ] run pytest tests/test_public_courses.py -x

### Task 77: Admin SEO — GSC OAuth и audit

**Files:**
- Modify: `app/admin/services/gsc_service.py`
- Modify: `app/admin/routes/seo_routes.py`
- Modify: `tests/admin/test_admin_gsc.py`

- [ ] Проверить что GSC OAuth callback проверяет state parameter (CSRF)
- [ ] Убедиться что gsc_refresh_token хранится зашифрованным (не plaintext)
- [ ] Проверить что /admin/seo/disconnect очищает оба GSC ключа
- [ ] Убедиться что fetch_gsc_data gracefully handles expired refresh token
- [ ] Тесты для state CSRF check, disconnect cleanup, expired token
- [ ] run pytest tests/admin/test_admin_gsc.py -x

### Task 78: Levelup celebration и UI feedback

**Files:**
- Modify: `app/templates/` (levelup UI)
- Modify: `tests/test_levelup_celebration.py`

- [ ] Проверить что level-up notification показывается только один раз (не при каждом reload)
- [ ] Убедиться что confetti respects prefers-reduced-motion
- [ ] Проверить что get_level_info корректна при total_xp=0 (level=1)
- [ ] Убедиться что level-up не дублируется при concurrent XP awards
- [ ] Тесты для one-time display, motion preference, zero XP, concurrent
- [ ] run pytest tests/test_levelup_celebration.py -x

### Task 79: Dashboard badges showcase

**Files:**
- Modify: `app/templates/` (badges)
- Modify: `tests/test_dashboard_badges_showcase.py`

- [ ] Проверить что badges отображаются корректно при 0 achievements
- [ ] Убедиться что badge tooltip не использует innerHTML (XSS safe)
- [ ] Проверить что locked badges не показывают progress для других пользователей
- [ ] Убедиться что badge count на dashboard консистентен с actual UserAchievement count
- [ ] Тесты для zero badges, tooltip XSS, count consistency
- [ ] run pytest tests/test_dashboard_badges_showcase.py -x

### Task 80: Словарный запас — deck select modal

**Files:**
- Modify: `app/static/js/deck-select-modal.js`
- Modify: `app/templates/`

- [ ] Проверить что modal закрывается при нажатии Escape
- [ ] Убедиться что поиск по decks не делает запрос при каждом keypress (debounce)
- [ ] Проверить что empty search result показывает empty state (не blank)
- [ ] Убедиться что modal не накапливает event listeners при повторном открытии
- [ ] Тесты для keyboard accessibility, debounce, empty state
- [ ] run pytest -m smoke -x

### Task 81: Compression и static assets

**Files:**
- Modify: `app/__init__.py` (Compress config)
- Modify: `tests/test_compression.py`

- [ ] Убедиться что gzip сжатие включено для HTML, JSON, CSS, JS
- [ ] Проверить что ETag headers присутствуют для static files
- [ ] Убедиться что Cache-Control headers корректны (immutable для versioned assets)
- [ ] Проверить что компрессия не применяется к уже сжатым форматам (jpg, mp3)
- [ ] run pytest tests/test_compression.py -x

### Task 82: Request ID tracking и logging

**Files:**
- Modify: `app/middleware/request_id.py`
- Modify: `app/__init__.py`

- [ ] Проверить что X-Request-ID header присутствует в каждом response
- [ ] Убедиться что request_id передаётся в error logs
- [ ] Проверить что request_id из входящего header принимается (не перезатирается)
- [ ] Убедиться что request_id UUID формат валидируется (нет injection)
- [ ] Тесты для header presence, log correlation, input validation
- [ ] run pytest tests/ -k request_id -x

### Task 83: Admin activity feed — aggregation correctness

**Files:**
- Modify: `app/admin/services/activity_feed_service.py`
- Modify: `tests/admin/`

- [ ] Проверить что get_recent_events правильно агрегирует все 5 источников
- [ ] Убедиться что outer joins не создают дублирующих строк при multiple achievements
- [ ] Проверить что xp_awarded считает из details['xp'] (не coins_delta)
- [ ] Убедиться что pagination (limit/offset) корректна при смешанных источниках
- [ ] Тесты для all 5 sources, outer join dedup, xp reading, pagination
- [ ] run pytest tests/admin/ -x

### Task 84: Admin system — cache management

**Files:**
- Modify: `app/admin/routes/system_routes.py`
- Modify: `app/admin/services/system_service.py`
- Modify: `tests/admin/`

- [ ] Проверить что cache clear endpoint защищён admin_required и audit logged
- [ ] Убедиться что partial cache clear (по ключу) корректно работает
- [ ] Проверить что system health показывает реальный DB pool status
- [ ] Убедиться что 5xx counter корректно инкрементируется при 500 ошибках
- [ ] Тесты для auth check, audit logging, counter increment
- [ ] run pytest tests/admin/ -x

### Task 85: Admin grammar lab — quiz management

**Files:**
- Modify: `app/admin/routes/grammar_lab_routes.py`
- Modify: `tests/admin/`

- [ ] Проверить что bulk delete упражнений каскадно удаляет UserGrammarExercise
- [ ] Убедиться что quiz edit с невалидным content возвращает 400 (не 500)
- [ ] Проверить что grammar quiz import валидирует все обязательные поля
- [ ] Убедиться что difficulty поле принимает только 0..1 range
- [ ] Тесты для cascade delete, validation errors, difficulty bounds
- [ ] run pytest tests/admin/ -x

### Task 86: Admin word management — bulk operations

**Files:**
- Modify: `app/admin/routes/word_routes.py`
- Modify: `app/admin/services/word_management_service.py`
- Modify: `tests/admin/`

- [ ] Проверить что bulk word delete корректно обрабатывает WordCollocation и UserWord
- [ ] Убедиться что collocation add/remove логируется через AdminAuditLog
- [ ] Проверить что word frequency_band update принимает только 1,2,3 или NULL
- [ ] Убедиться что admin word search с SQL-символами не ломается
- [ ] Тесты для bulk delete, audit log, frequency bounds, search sanitization
- [ ] run pytest tests/admin/ -x

### Task 87: Admin topic/collection management

**Files:**
- Modify: `app/admin/routes/topic_routes.py`
- Modify: `app/admin/routes/collection_routes.py`
- Modify: `tests/admin/`

- [ ] Проверить что удаление topic каскадно обрабатывает связанные lessons
- [ ] Убедиться что collection sort order уникален (нет дублирующих positions)
- [ ] Проверить что topic slug уникален и sanitized
- [ ] Убедиться что collection с 0 items доступна (не 500)
- [ ] Тесты для cascade delete, sort dedup, slug uniqueness, empty collection
- [ ] run pytest tests/admin/ -x

### Task 88: Admin quiz decks — управление

**Files:**
- Modify: `app/admin/quiz_decks.py`
- Modify: `tests/admin/`

- [ ] Проверить что quiz deck export корректен при 0 карточек
- [ ] Убедиться что deck import валидирует формат перед записью
- [ ] Проверить что clone deck создаёт deep copy (не shallow reference)
- [ ] Убедиться что public deck флаг не позволяет видеть admin-only decks
- [ ] Тесты для empty export, import validation, clone, visibility
- [ ] run pytest tests/admin/ -x

### Task 89: NLP и text processing

**Files:**
- Modify: `app/` (NLP-related files)
- Modify: `tests/test_nlp_processor.py`

- [ ] Проверить что NLP processor graceful при импорте модели (нет crash при отсутствии)
- [ ] Убедиться что NLP обработка ограничена по времени (timeout)
- [ ] Проверить что результат NLP кешируется (нет повторной обработки)
- [ ] Убедиться что NLP не применяется к пустому тексту
- [ ] run pytest tests/test_nlp_processor.py -x

### Task 90: Feedback система — маршруты и хранение

**Files:**
- Modify: `app/feedback/`
- Modify: `app/admin/routes/feedback_routes.py`
- Modify: `app/templates/admin/feedback/`
- Modify: `app/templates/components/_feedback_widget.html`
- Modify: `migrations/versions/20260527_feedback.py`
- Modify: `tests/test_feedback.py`

- [ ] Проверить что feedback widget корректно отображается и отправляет данные
- [ ] Убедиться что feedback submission валидирует входные данные (нет пустых submissions)
- [ ] Проверить что admin может просматривать и обрабатывать feedback
- [ ] Убедиться что feedback migration chain консистентна
- [ ] Тесты для feedback submission, validation, admin view
- [ ] run pytest tests/test_feedback.py -x

### Task 91: Общая регрессия и smoke suite

**Files:**
- Modify: `tests/conftest.py` (если нужны фиксы)
- Modify: `pytest.ini`

- [ ] Запустить полный pytest -m smoke и исправить все провалившиеся тесты
- [ ] Убедиться что все новые тесты из тасок 1-90 помечены @pytest.mark.smoke где применимо
- [ ] Проверить что db_session fixture использует savepoint pattern (не DELETE cleanup)
- [ ] Убедиться что нет test isolation нарушений (порядок запуска не влияет)
- [ ] Запустить pytest --tb=short и убедиться что 0 failures, 0 errors
- [ ] run pytest -x

### Task 92: Документация и CLAUDE.md обновление

**Files:**
- Modify: `CLAUDE.md`

- [ ] Добавить в CLAUDE.md все новые паттерны открытые в ходе аудита
- [ ] Обновить описания изменённых key patterns
- [ ] Проверить что CLAUDE.md не содержит устаревших ссылок на удалённый код
- [ ] run pytest -m smoke -x (финальная верификация)

### Task 93: Verify acceptance criteria

- [ ] run pytest (полный suite) — 0 failures
- [ ] run pytest -m smoke — все проходят < 30s
- [ ] Проверить что нет новых TODO/FIXME без owner
- [ ] Проверить git log на наличие всех тасок как отдельных коммитов
