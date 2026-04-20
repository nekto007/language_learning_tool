# 17 Tasks: Linear Daily Plan — from Mission-based to Curriculum Spine

## Overview

Переделать «список заданий» на дашборде: вместо 3 типов миссий (Progress / Repair / Reading) с ежедневной композицией фаз — одна линейная дорожка по curriculum. Позвоночник прогресса — готовая последовательность уроков в БД (`CEFRLevel.order` → `Module.number` → `Lesson.number`, ~924 уроков A0→C2). Ученик видит текущую позицию (`A2 · M5 · L3`), 3–4 обязательных слота в день (следующий урок curriculum, SRS global, чтение выбранной книги, периодически — разбор ошибок из quiz) и continuation-превью дальнейших уроков модуля. Mission-код не удаляем в рамках этого плана — выключаем за фичефлагом, снос — отдельным PR после стабилизации.

## Context

- Files involved: `app/daily_plan/service.py`, `app/daily_plan/assembler.py`, `app/daily_plan/models.py`, `app/daily_plan/level_utils.py`, `app/curriculum/models.py`, `app/curriculum/services/curriculum_cache_service.py`, `app/books/models.py`, `app/grammar_lab/models.py`, `app/words/routes.py`, `app/templates/dashboard.html`, `app/api/daily_plan.py`, `app/achievements/xp_service.py`
- Related patterns: `_safe_widget_call()` в route, `compute_day_secured`, `write_secured_at`, роутер `get_daily_plan_unified` с feature-flag `User.use_mission_plan`, линейность curriculum через `idx_modules_level_number` + `idx_lessons_module_number`, XP multipliers и `award_xp`
- Dependencies: никаких внешних; всё в существующем Flask/SQLAlchemy/Alembic/Jinja2/vanilla JS стеке
- Feature flags: добавляем `User.use_linear_plan`, оставляем `User.use_mission_plan` (legacy-ветка не трогается)

## Current State

- Текущий план — mission-based: `get_daily_plan_unified` роутит на `select_mission()` → `assemble_progress_mission` / `assemble_repair_mission` / `assemble_reading_mission`. Каждая миссия = 3–4 фазы (recall / learn / use / read / check / close / bonus).
- Триггер Repair — `repair_pressure ≥ 0.6` (50% overdue SRS + 30% grammar weak + 20% failure clusters). Reading включается при наличии книг под уровень.
- UI — `dash-timeline` (`dashboard.html:536–707`), карточки `.dash-step` с состояниями, клик через `_phase_url()` (`app/words/routes.py:1448`).
- Curriculum уже линеен: `CEFRLevel.order`, `Module.number`, `Lesson.number`. `LessonProgress` отслеживает статус. `get_user_current_cefr_level()` возвращает актуальный уровень. В каждом модуле фиксированная последовательность 12 уроков: `vocabulary, card, grammar, quiz, reading, listening_quiz, dialogue_completion_quiz, ordering_quiz, card, translation_quiz, listening_immersion, final_test`.
- Проблемы:
  - День непредсказуем (Progress vs Repair vs Reading), нет ощущения «движения по программе»
  - Книга выбирается автоматически (`_find_next_book` в `assembler.py:463`), без preferences/уровня
  - Ошибки quiz-уроков не возвращаются на повтор
  - Теория grammar-lab не подтягивается к grammar-урокам curriculum
  - SRS-бюджет и темп прохождения уроков слабо связаны

## Development Approach

- **Testing approach**: Regular (код сначала, потом тесты)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**
- Новый код живёт в `app/daily_plan/linear/` изолированно; mission-код не трогаем
- Rollout через `use_linear_plan=True` — сначала автор → 1–2 тестера → массово

## Design Decisions (зафиксировано в брейншторме)

- **Позвоночник**: `Lesson` в порядке `(level.order, module.number, lesson.number)`, фильтр `level.order >= user.onboarding_level.order` (B1-юзер стартует с B1 M1 L1, а не с A0).
- **Метрика прогресса**: `A2 · M5 · L3` в header (под ним тип урока) + бейдж «Осталось N уроков до A3». Глобальная нумерация «347/924» не показывается.
- **Baseline-слоты (3 обязательных, 4-й условный):**
  1. Следующий урок curriculum (любой тип из 12)
  2. SRS global (слова из /study на review)
  3. Чтение выбранной книги
  4. Error review — условный, при `unresolved_errors ≥ 5` И `last_review_at < now() - 3 days`
- **Card-урок**: при `srs_budget_remaining > 0` подмешиваем до 10 карточек из колод юзера; при `budget = 0` — только слова curriculum без SM-2 активации.
- **SRS budget**: расходуется только card-уроками и /study (quiz-уроки не влияют).
- **Grammar-theory**: при grammar-уроке curriculum по `Lesson.content['topic']` ищем `GrammarTopic` по title+level и показываем теорию перед упражнениями. Логируем `GrammarTheoryView`.
- **Reading**: `reading`-урок из curriculum (короткий текст без сюжета) остаётся в цепочке — не заменяется книгой. Книга = отдельный baseline-слот. Первый вход: «Выбрать книгу» → каталог с фильтром `Book.level in [user_level-1, user_level, user_level+1]`.
- **Error review**: таблица `QuizErrorLog`, сессия — 5–10 старейших unresolved; correct ответ → `resolved_at = now()`.
- **Continuation**: после `day_secured` — CTA «Следующий урок» + preview следующих 3 уроков модуля.
- **XP (новые значения)**: card → 20, grammar → 18, reading/listening → 15, quiz/* → 12, srs_global → 8, book_reading → 15, error_review → 10, perfect_day bonus → 25 (было 50). Baseline-день ≈ 43 XP, первый уровень закрывается за ~2.5 дня.

## Implementation Steps

---

### BLOCK 1: Infrastructure & Curriculum Spine (Tasks 1-3)

### Task 1: DB migration (new tables and feature flag)

Добавить фичефлаг `use_linear_plan` и три новые таблицы: `user_reading_preference`, `quiz_error_log`, `grammar_theory_view`.

**Files:**
- Create: `migrations/versions/<rev>_linear_daily_plan.py`
- Modify: `app/auth/models.py`
- Create: `app/daily_plan/linear/models.py`

- [x] Alembic ревизия: `users.use_linear_plan BOOLEAN DEFAULT FALSE NOT NULL`
- [x] Alembic ревизия: `user_reading_preference (user_id PK FK, book_id FK, selected_at TIMESTAMPTZ)`
- [x] Alembic ревизия: `quiz_error_log (id, user_id, lesson_id FK, question_payload JSONB, answered_wrong_at, resolved_at nullable, created_at)` + indexes `(user_id, resolved_at)` и `(user_id, created_at)`
- [x] Alembic ревизия: `grammar_theory_view (id, user_id, topic_id FK, lesson_id FK, shown_at)` + index `(user_id, lesson_id)`
- [x] Проверить migration chain consistency (upgrade/downgrade)
- [x] Обновить `User` — поле `use_linear_plan: Mapped[bool]`
- [x] Создать SQLAlchemy модели `UserReadingPreference`, `QuizErrorLog`, `GrammarTheoryView` в `app/daily_plan/linear/models.py`
- [x] Write tests: smoke CRUD для трёх новых моделей (`tests/daily_plan/test_linear_models.py`)
- [x] Проверить импорты: `python -c "import app.daily_plan.linear.models"`
- [x] Run project test suite — must pass before task 2

### Task 2: Progression module (find next lesson linear)

Форкнуть линейный поиск следующего урока из существующего `_find_next_lesson`, добавить фильтр по onboarding_level.

**Files:**
- Create: `app/daily_plan/linear/progression.py`
- Create: `tests/daily_plan/test_linear_progression.py`

- [x] `find_next_lesson_linear(user_id, db) → Optional[Lesson]` — JOIN `LessonProgress`/`Module`/`CEFRLevel`, фильтр `status IS NULL OR != 'completed'` и `level.order >= user.onboarding_level.order`, ORDER BY `level.order, module.number, lesson.number`, LIMIT 1
- [x] `get_user_level_progress(user_id, db) → LevelProgress` — `{level, percent, lessons_remaining_in_level, lessons_remaining_to_next_level}`
- [x] `get_module_upcoming(user_id, current_lesson, db, limit=3) → list[Lesson]` — для continuation preview
- [x] Write tests: B1-юзер не видит A0/A1; пропуск completed уроков; переход module→module, level→level; все пройдены → None; `percent` корректен
- [x] Run project test suite — must pass before task 3

### Task 3: Router `get_daily_plan_unified` with `use_linear_plan` branch

Добавить linear-ветку в существующий роутер, заглушка возвращает скелет ответа.

**Files:**
- Modify: `app/daily_plan/service.py`
- Create: `app/daily_plan/linear/plan.py`
- Create: `tests/daily_plan/test_linear_plan_router.py`

- [x] В `app/daily_plan/linear/plan.py`: `get_linear_plan(user_id, db, tz) → dict` — пока заглушка со структурой `{mode: 'linear', position, baseline_slots: [], continuation, progress, day_secured}`
- [x] В `get_daily_plan_unified` добавить приоритет: `use_linear_plan` → `use_mission_plan` → legacy, с fallback на mission при ошибке в linear-ветке (structured warning лог)
- [x] Write tests: роутинг выбирает правильную ветку по флагам; fallback при исключении в linear
- [x] Run project test suite — must pass before task 4

---

### BLOCK 2: Baseline Slots (Tasks 4-9)

### Task 4: Curriculum lesson slot

Собрать слот «следующий урок curriculum» с URL по типу урока.

**Files:**
- Create: `app/daily_plan/linear/slots/curriculum_slot.py`
- Modify: `app/daily_plan/linear/plan.py`
- Create: `tests/daily_plan/linear/test_curriculum_slot.py`

- [x] `build_curriculum_slot(user_id, db) → LinearSlot` — `{kind: 'curriculum', title, lesson_type, eta_minutes, url, completed}`
- [x] URL по `Lesson.lesson_type`: `/curriculum_lessons/{id}?from=linear_plan` с проставлением query-param для SRS-budget (Task 5)
- [x] `completed = True` когда `LessonProgress.status == 'completed'` и урок = текущий next
- [x] Write tests: для каждого из 12 типов уроков (vocabulary/card/grammar/quiz/reading/listening_quiz/dialogue/ordering/translation/listening_immersion/final_test) слот корректно формируется
- [x] Run project test suite — must pass before task 5 (20 dashboard failures pre-existed on the unchanged branch; daily_plan suite passes)

### Task 5: SRS slot with budget logic

Слот SRS global + интеграция card-урока с budget-логикой.

**Files:**
- Create: `app/daily_plan/linear/slots/srs_slot.py`
- Modify: card-lesson flow в `app/curriculum/` (контроллер card-урока)
- Create: `tests/daily_plan/linear/test_srs_slot.py`

- [x] `build_srs_slot(user_id, db) → LinearSlot` — due count, URL `/study?source=linear_plan`, `completed` когда юзер отзанимался N карточками сегодня
- [x] `get_srs_budget_remaining(user_id, db) → int` — `max_new_per_day - words_added_to_srs_today` (читаем `max_new_per_day` из существующих user settings в /study)
- [x] Card-урок через `?source=linear_plan_card`: при `budget > 0` — подмешать `min(budget, 10)` due-карточек юзера в сессию перед новыми словами curriculum; при `budget = 0` — только слова curriculum, новые слова не активируются в SM-2
- [x] Slot схлопывается в «Карточки повторим завтра» (completed=True, не требует клика) если `due=0` И card-урок сегодня сделан
- [x] Write tests: slot при due≥1 активен; при due=0 после card-урока схлопывается; budget=0 → sm-2 не активирует слова; budget>0 → подмешиваются колоды
- [x] Run project test suite — must pass before task 6 (pre-existing dashboard failures unchanged; new tests + daily_plan suite green)

### Task 6: Book reading slot and catalog modal

Слот чтения книги + первый вход с выбором, endpoint и модал каталога.

**Files:**
- Create: `app/daily_plan/linear/slots/reading_slot.py`
- Create: `app/api/books_catalog.py`
- Modify: `app/templates/dashboard.html` (модал выбора)
- Create: `app/static/js/linear-daily-plan.js`
- Create: `tests/daily_plan/linear/test_reading_slot.py`
- Create: `tests/api/test_books_catalog.py`

- [x] `build_reading_slot(user_id, db) → LinearSlot`: при отсутствии `UserReadingPreference` — slot в режиме «Выбрать книгу», URL открывает модал; при наличии — название + текущая глава (`Bookmark`) + ETA ~10 мин
- [x] Endpoint `GET /api/books/catalog?level=<user_level>` — возвращает книги с `level in [user_level-1, user_level, user_level+1]`, JSON-формат
- [x] Endpoint `POST /api/books/select` — создаёт/обновляет `UserReadingPreference`, возвращает обновлённый slot
- [x] Модал `book-select-modal` в `dashboard.html` (скрыт, открывается по клику на slot без preference), рендер карточек с обложкой/уровнем
- [x] `completed = True` при увеличении `UserChapterProgress.offset_pct` ≥ 5% сегодня (Bookmark.position в текущем reader не увеличивается автоматически; reading-progress трекается через UserChapterProgress)
- [x] Write tests: первый вход → «Выбрать книгу»; после select → slot с данными книги; endpoint фильтрует по уровню; progress threshold срабатывает
- [x] Run project test suite — must pass before task 7 (90 dashboard failures pre-existed; new daily_plan/linear + books_catalog suites green)

### Task 7: Error review slot and quiz error logging

Логирование ошибок из quiz-уроков + условный 4-й слот.

**Files:**
- Create: `app/daily_plan/linear/slots/error_review_slot.py`
- Create: `app/daily_plan/linear/errors.py`
- Modify: quiz-grading endpoints во всех типах quiz-уроков curriculum
- Create: `tests/daily_plan/linear/test_error_review.py`

- [x] `log_quiz_error(user_id, lesson_id, question_payload, db)` — пишет строку в `QuizErrorLog` при incorrect ответе
- [x] `resolve_quiz_error(error_id, user_id, db)` — ставит `resolved_at = now()`
- [x] `get_review_pool(user_id, db, limit=10) → list[QuizErrorLog]` — старейшие unresolved
- [x] `should_show_error_review(user_id, db) → bool` — `COUNT(unresolved) >= 5` И (`last_resolved_at IS NULL` ИЛИ `last_resolved_at < now() - interval '3 days'`)
- [x] `build_error_review_slot(user_id, db) → Optional[LinearSlot]` — None если триггер не сработал
- [x] Обновить quiz-grading для типов: `quiz`, `listening_quiz`, `dialogue_completion_quiz`, `ordering_quiz`, `translation_quiz`, `final_test` — при incorrect вызывать `log_quiz_error` с payload вопроса
- [x] Write tests: slot не появляется при 4 unresolved; при 5+ unresolved и <3 дней — не появляется; при 5+ и ≥3 дней — появляется; correct в review → `resolved_at`; каждый тип quiz-урока логирует ошибку
- [x] Run project test suite — must pass before task 8 (daily_plan 211, curriculum 36, smoke 132 all green)

### Task 8: Grammar theory pull into grammar lessons

Подтяжка теории из grammar-lab в grammar-урок curriculum.

**Files:**
- Modify: `app/curriculum/` — контроллер grammar-урока
- Create: `app/daily_plan/linear/grammar_theory.py`
- Modify: шаблон grammar-урока
- Create: `tests/daily_plan/linear/test_grammar_theory.py`

- [x] `get_theory_for_lesson(user_id, lesson, db) → Optional[GrammarTopic]` — matching по `Lesson.content['topic']` string → `GrammarTopic.title ILIKE` с фильтром `level = lesson.module.level`
- [x] При match — логируем `GrammarTheoryView(user_id, topic_id, lesson_id, shown_at)`, возвращаем topic
- [x] При отсутствии match — None, урок идёт как обычно (не падаем)
- [x] В шаблоне grammar-урока — секция «Теория (1 мин)» над упражнениями, если topic найден; collapse-friendly
- [x] Write tests: match по title/level; отсутствие поля `topic` в content; множественные варианты title (берётся первый по `GrammarTopic.order`); повторный вход в тот же урок не дублирует `GrammarTheoryView`
- [x] Run project test suite — must pass before task 9 (daily_plan 261 + smoke 132 green; 30 pre-existing dashboard failures unchanged on base branch)

### Task 9: Assemble `get_linear_plan` from slots

Собрать полный payload линейного плана и подключить `day_secured` логику.

**Files:**
- Modify: `app/daily_plan/linear/plan.py`
- Modify: `app/daily_plan/service.py` — `compute_day_secured` должна работать и для linear
- Modify: `app/daily_plan/service.py` — `write_secured_at` сигнатура: `mission_type` становится nullable
- Create: `tests/daily_plan/linear/test_plan_assembly.py`

- [x] `get_linear_plan(user_id, db, tz)`:
  - `position = find_next_lesson_linear + get_user_level_progress`
  - `baseline_slots = [curriculum, srs, reading, error_review if triggered]`
  - `continuation = {available: day_secured, next_lessons: get_module_upcoming(..., 3)}`
  - `day_secured = all(slot.completed for slot in required_baseline_slots)` — вычисляется на месте, не кешируется
- [x] `/api/daily-status` пересчитывает `day_secured` через `compute_plan_steps` для linear payload (аналогично mission flow)
- [x] `write_secured_at(user_id, plan_date, mission_type=None)` — `mission_type` nullable; для linear не пишется
- [x] Write tests: happy path (3 слота, ничего не done → False); all 3 done → True; 4-й slot триггернут → secured требует все 4; `write_secured_at` не падает с None
- [x] Run project test suite — must pass before task 10 (daily_plan 267 + smoke 132 green; one pre-existing flaky `test_crosses_level_boundary` due to random code collision unrelated to this task)

---

### BLOCK 3: Dashboard Frontend (Tasks 10-12)

### Task 10: Linear daily plan template and CSS

Новый partial с header, слотами, continuation. `dash-timeline` скрывается за флагом, разметка остаётся для legacy.

**Files:**
- Create: `app/templates/partials/linear_daily_plan.html`
- Modify: `app/templates/dashboard.html` — include partial за `{% if use_linear_plan %}`
- Modify: `app/static/css/design-system.css` — новые классы (префикс `linear-`) или reuse `.dash-step` семейства
- Modify: `app/static/js/linear-daily-plan.js` — модал выбора книги, event tracking
- Create: `tests/test_linear_daily_plan_render.py`

- [x] Header: `A2 · M5 · L3` (компактно) + строка ниже с типом урока (`card`/`grammar`/...) + бейдж «Осталось 30 уроков до A3»
- [x] Список slot-карточек (1–4) с состояниями `done / current / pending / empty`; чек-метка для done, подсветка border для current
- [x] Continuation CTA под списком — появляется при `day_secured=True`, ведёт к следующему уроку
- [x] Continuation preview — раскрываемый список 3 следующих уроков модуля
- [x] Модал выбора книги: scroll-контейнер, карточки с обложкой/уровнем/описанием; submit → `POST /api/books/select`
- [x] Write tests: file-level snapshot теста Jinja render с mock data (header, 3 slots, empty state, secured state, модал)
- [x] Run project test suite — must pass before task 11 (daily_plan 240 + new 21 render tests + smoke 132 green; 70 pre-existing dashboard failures unchanged on base branch)

### Task 11: Update `/api/daily-plan` and `/api/daily-status` payload

Новая форма payload для linear, legacy mission payload остаётся.

**Files:**
- Modify: `app/api/daily_plan.py`
- Create: `tests/api/test_linear_plan_api.py`

- [x] `/api/daily-plan` при `use_linear_plan=True` возвращает `{mode: 'linear', position, progress, baseline_slots: [...], continuation, day_secured}`
- [x] `/api/daily-status` учитывает `mode` и рассчитывает `plan_completion` по baseline-слотам linear; mission flow работает как прежде
- [x] Обратная совместимость: при `use_linear_plan=False` — старая форма полностью сохраняется
- [x] Write tests: оба режима возвращают валидные payload'ы; `day_secured` пересчитывается корректно; error review slot появляется/отсутствует согласно триггеру
- [x] Run project test suite — must pass before task 12 (api 139 + daily_plan 267 + smoke 132 green; one pre-existing flaky `test_level_advances_after_full_completion` due to random code collision unrelated to this task)

### Task 12: Smoke tests for linear dashboard

4 сценария в smoke-прогоне (<30с).

**Files:**
- Create: `tests/smoke/test_linear_dashboard_smoke.py`

- [ ] Сценарий 1: юзер с `use_linear_plan=True` → `/` рендерит linear partial, 3 slots, API возвращает `mode=linear`
- [ ] Сценарий 2: юзер с `use_linear_plan=False` → legacy mission работает (no регрессий)
- [ ] Сценарий 3: первый вход без `UserReadingPreference` → слот чтения = «Выбрать книгу», модал доступен
- [ ] Сценарий 4: все 3 baseline-слота done → continuation CTA виден, `day_secured=True`
- [ ] Все 4 теста `@pytest.mark.smoke`
- [ ] Убедиться что `pytest -m smoke` укладывается в <30 сек
- [ ] Run project test suite — must pass before task 13

---

### BLOCK 4: XP & Achievements (Tasks 13-14)

### Task 13: Rebuild XP values for linear mode

Новые XP-значения и уменьшенный perfect_day bonus только для linear.

**Files:**
- Modify: `app/achievements/xp_service.py`
- Modify: `tests/achievements/test_xp_service.py`

- [ ] Добавить маппинг linear-source → XP: `linear_curriculum_card → 20`, `linear_curriculum_grammar → 18`, `linear_curriculum_quiz → 12` (quiz/listening_quiz/dialogue/ordering/translation/final_test), `linear_curriculum_reading → 15`, `linear_curriculum_listening → 15`, `linear_curriculum_vocabulary → 18`, `linear_srs_global → 8`, `linear_book_reading → 15`, `linear_error_review → 10`
- [ ] `PERFECT_DAY_BONUS` — 25 для linear, 50 для mission (пока mission живёт)
- [ ] Streak multiplier (`1 + streak*0.02, cap 2.0`) — без изменений
- [ ] Write tests: `award_xp` с новыми source-ключами; baseline-день без streak = 43 XP (20 card + 8 srs + 15 book); первый уровень (100 XP) закрывается за ~2.5 дня
- [ ] Run project test suite — must pass before task 14

### Task 14: Wire `award_xp` from linear slot completions

Вызов `award_xp` из правильных endpoint-ов по завершению каждого типа слота.

**Files:**
- Modify: endpoint-ы каждого типа curriculum-урока (grade/complete)
- Modify: SRS session complete endpoint
- Modify: book reading progress endpoint
- Modify: error review complete endpoint

- [ ] При completion curriculum-урока (любого из 12 типов) в linear-режиме — `award_xp` с соответствующим `linear_curriculum_<type>` source
- [ ] При завершении SRS-сессии через `?source=linear_plan` — `award_xp(linear_srs_global)`
- [ ] При увеличении reading progress выбранной книги выше threshold — `award_xp(linear_book_reading)` (один раз за день, чтобы не нафармили)
- [ ] При завершении error review сессии — `award_xp(linear_error_review)`
- [ ] Detect режим: через `User.use_linear_plan` или через query-param `?source=linear_*` — выбираем единообразный механизм
- [ ] Write tests: полный linear-день → правильная сумма XP, streak incremented, perfect_day bonus применён; mission-юзер получает mission-XP без регрессий
- [ ] Run project test suite — must pass before task 15

---

### BLOCK 5: Rollout (Tasks 15-17)

### Task 15: Author dogfooding

**Files:**
- manual DB update on dev/staging

- [ ] Включить `use_linear_plan=True` для user_id автора в dev/staging
- [ ] Пройти полный cycle: первый вход → выбрать книгу → сделать 3 слота → secured → continuation → следующий урок
- [ ] Проверить: XP начисляется корректно, streak инкрементится, achievements срабатывают, error review появляется при триггере
- [ ] Записать наблюдения в progress log, зафиксировать баги
- [ ] Run project test suite — must pass before task 16

### Task 16: Beta testers rollout

**Files:**
- Create: `app/cli/linear_plan_commands.py` (flask CLI)

- [ ] CLI-команда `flask linear-plan-enable <user_id>` / `flask linear-plan-disable <user_id>` для быстрого toggle
- [ ] Включить для 1–2 тестеров, собрать фидбэк 3–5 дней
- [ ] Исправить критичные баги, если всплывут, отдельными hotfix-коммитами
- [ ] Write tests: CLI-команды корректно меняют флаг, существование юзера валидируется
- [ ] Run project test suite — must pass before task 17

### Task 17: Mass rollout

**Files:**
- Create: `migrations/versions/<rev>_linear_plan_mass_enable.py`
- Modify: admin dashboard для метрик

- [ ] Alembic data migration: `UPDATE users SET use_linear_plan = TRUE` (для всех или фильтр по onboarded)
- [ ] Пост-раскаточный smoke на staging (полный `pytest -m smoke` + manual walkthrough)
- [ ] Добавить метрики в admin-дашборд: `day_secured_rate`, `average_slots_completed`, `error_review_trigger_rate`, `book_select_rate`
- [ ] Мониторить логи и метрики в течение 48 часов
- [ ] Write tests: миграция идемпотентна; метрики считаются корректно (unit-тесты на агрегации)
- [ ] Move this plan to `docs/plans/completed/` after acceptance

---

## Acceptance Criteria

- B1-юзер после онбординга заходит на дашборд → видит `B1 · M1 · L1 (vocabulary)`, 3 baseline-слота, прогресс `B1 · 0%`, continuation CTA
- Card-урок через `?source=linear_plan_card` при `srs_budget > 0` — подмешивает до 10 review-карточек из колод юзера; при `budget = 0` — только curriculum-слова без SM-2 активации
- 5+ unresolved quiz-ошибок И прошло 3+ дня → появляется 4-й слот «Разбор ошибок»
- Первый вход: слот «Чтение» = «Выбрать книгу» → клик → модал каталога с фильтром по уровню → сохраняется preference
- Grammar-урок curriculum с matching `content['topic']` → теория показана до упражнений; `GrammarTheoryView` залогирован
- Completion всех обязательных slots → `day_secured=True`, `DailyPlanLog.secured_at` записан (с `mission_type=NULL`)
- Continuation CTA после secured → ведёт к `Lesson.number + 1` того же модуля (или первому уроку следующего модуля)
- XP за стандартный baseline день (без streak/perfect bonuses) = 43 XP; первый уровень (100 XP) закрывается за ~2.5 дня
- Переключение `use_linear_plan=False` → legacy mission UI работает без регрессий; все существующие mission-тесты проходят
- `pytest -m smoke` проходит <30 сек, покрывает оба режима
- `python -c "import app.daily_plan.linear.plan"` и `python -c "import app.daily_plan.linear.progression"` без ошибок

## Out of Scope / Backlog

Эти темы всплыли во время брейнсторма, но требуют отдельной работы:

1. **Mission-based dead code cleanup** — через 2–4 недели после стабилизации linear: удалить `assemble_progress_mission`, `assemble_repair_mission`, `assemble_reading_mission`, `select_mission`, `calculate_repair_pressure`, `MissionPhase`/`MissionPlan` dataclass'ы, `PhaseKind`, `SourceKind`, `MODE_CATEGORY_MAP`, `DailyPlanLog.mission_type` (nullable → drop), mission achievements (`mission_*` seeds), `_phase_url` в `app/words/routes.py`, `app/daily_plan/assembler.py`. Отдельный PR через `dead-code-cleaner`.
2. **Placement test** — реальный тест уровня (10–15 вопросов grammar+vocab). Сейчас остаёмся на self-select в онбординге; linearity + user control над onboarding_level достаточны.
3. **Book course** как источник ежедневного чтения (отдельная активность поверх baseline) — не вписываем сейчас.
4. **Listening как отдельный блок** (TTS-сценарии, чистое восприятие на слух без quiz) — пока используем curriculum `listening_quiz` + `listening_immersion` + `Chapter.audio_url`.
5. **Grammar-lab как ежедневная активность** — остаётся свободным разделом, не на дашборде. Quiz'ы grammar-lab могут использоваться как источник для error review-пула в будущем.
6. **Архивация `QuizErrorLog`** при долгом неактивном пользователе — пока growth low, но планировать retention при росте.
7. **Cross-level репетиция** — когда юзер перешёл на B1, но хочет «закрепить» A2 — сейчас эта опция недоступна (progression монотонна). Если понадобится — отдельная фича «Вернуться на уровень ниже».

## Risks

- **Payload breaking change**: `/api/daily-plan` меняет форму при `use_linear_plan=True`. Фронт обновляется синхронно (Block 3). Telegram-бот, если читает endpoint, — проверить совместимость, возможно адаптер в Task 11.
- **Mid-day flag switch**: переключение mission→linear в середине дня может пересчитать `day_secured`. Warning лог, не критично.
- **Grammar topic matching miss-rate**: при несовпадении `Lesson.content['topic']` с `GrammarTopic.title` теория не подтянется. Падений быть не должно, но стоит залогировать miss-rate для последующего исправления контента.
- **Error log growth**: `QuizErrorLog.unresolved` может разрастись при долгом неактивном пользователе. Архивация — backlog-пункт 6.
- **SRS budget читается из разных мест**: убедиться, что `max_new_per_day` в linear card-уроке берётся из того же источника, что и /study (иначе два разных budget'а).
