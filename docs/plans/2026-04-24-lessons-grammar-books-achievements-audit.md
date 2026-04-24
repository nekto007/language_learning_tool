# 16 Tasks: Cross-Domain Gaps — Lessons, Grammar, Books, Achievements

## Overview

По итогам глубокого аудита четырёх доменов (уроки, грамматика, книги, достижения/XP) найдены системные пробелы: XP-экcплойты через неидемпотентные пути (book_chapter, referral, matching/quiz games, grammar_lab↔curriculum), рассогласование дат у curriculum lesson XP (UTC vs local), пропуск module-unlock-валидации, orphan-миграция для `user_lesson_progress`, три разных алгоритма «next lesson», отсутствие `record_plan_completion` для linear-plan, grammar-ошибки не попадают в `QuizErrorLog`, BookCourse не синхронизируется с Book, математика reading-%-прогресса занижает реальное значение, легаси `UserXP`/`study/xp_service.py` всё ещё активны. Исправляется без новых фич — только унификация, идемпотентность, удаление дубликатов.

## Context

- **Ключевые файлы (lessons):**
  - `app/curriculum/service.py` — `complete_lesson()` (UTC-наивная дата)
  - `app/curriculum/routes/card_lessons.py` — `complete_srs_session()` (user-tz дата)
  - `app/curriculum/routes/main.py` — `lesson_by_id()` без unlock-валидации
  - `app/curriculum/routes/grammar_quiz_lessons.py` — `process_grammar_submission()` без error-log
  - `app/curriculum/xp.py` — `award_curriculum_lesson_xp_idempotent()`
  - `app/daily_plan/linear/xp.py`, `app/daily_plan/linear/progression.py`
  - `migrations/versions/d35366cf95ab_*.py` — orphan user_lesson_progress
- **Ключевые файлы (grammar):**
  - `app/grammar_lab/services/grammar_lab_service.py:submit_answer` (XP через `srs.add_xp`)
  - `app/grammar_lab/services/grader.py`, `app/grammar_lab/models.py`
  - `app/grammar_public/` — пустой blueprint (только `__pycache__`)
  - `app/daily_plan/linear/errors.py` — `log_quiz_errors_from_result`
  - `app/admin/routes/grammar_lab_routes.py` — без audit log
- **Ключевые файлы (books):**
  - `app/books/api.py` — три `db.session.commit()` в одном chapter-complete endpoint
  - `app/books/routes.py` — reader, book_list, суммация offset_pct
  - `app/books/processors.py` — переобработка книги, UPSERT без DELETE старых word_book_link
  - `app/curriculum/book_courses.py` — BookCourse (рассинхронизирован с Book)
  - `app/daily_plan/linear/slots/reading_slot.py`
- **Ключевые файлы (achievements):**
  - `app/achievements/xp_service.py` — `award_xp()`, `PERFECT_DAY_BONUS_*`
  - `app/achievements/streak_service.py` — `process_streak_on_activity()`, `record_plan_completion()`
  - `app/achievements/ranks.py`, `app/achievements/daily_race.py`, `app/achievements/seed.py`
  - `app/study/xp_service.py` — legacy `XPService.award_xp()` (DeprecationWarning)
  - `app/utils/activity_tracker.py` — `has_learning_activity()` (6 источников)
  - `app/words/routes.py` — referral XP path
  - `app/study/game_routes.py` — matching/quiz XP path
- **Паттерны:** `StreakEvent(event_type='xp_*')` dedup, `grant_achievement()` race-safe upsert, `api_error()`, `_safe_widget_call()`
- **Dependencies:** нет внешних; всё внутри Flask/SQLAlchemy/PostgreSQL

## Current State

### Проблемы, подтверждённые аудитом

**P1. XP double-award для book_chapter (idempotency gap)**
- `app/books/api.py:901-907` — `book_chapter` XP начисляется без `StreakEvent` dedup
- Только `linear_book_reading` (строки 914-929) защищён через `maybe_award_book_reading_xp()` → `StreakEvent(event_type='xp_linear', source='linear_book_reading')`
- Endpoint выполняет три `db.session.commit()` подряд (строки 894, 907, 929) — partial failure → несогласованное состояние
- Concurrent tabs: оба запроса читают `was_incomplete=True` → оба коммитят `book_chapter` XP

**P2. Referral и game XP не идемпотентны**
- `app/words/routes.py` — `_award_xp_unified(referred_by_id, 100, 'referral')` без `StreakEvent`
- `app/auth/routes.py` — дублирует referral `grant_achievement()`
- `app/study/game_routes.py` — matching/quiz games вызывают `award_xp()` без dedup, полагаясь на HTTP-идемпотентность клиента
- Повторная отправка запроса → двойное начисление XP

**P3. Двойной XP-путь для grammar-упражнений**
- `app/grammar_lab/services/grammar_lab_service.py:402-403` — `srs.add_xp()` при `submit_answer`
- `app/daily_plan/linear/xp.py:42,46` — `LINEAR_XP['linear_curriculum_grammar']=18` через `maybe_award_curriculum_xp`
- Если grammar-упражнение одновременно — часть curriculum-lesson (FK `Lessons.grammar_topic_id`) и открыто отдельно в grammar_lab, оба пути начисляют XP без координации

**P4. Дата curriculum lesson XP несовместима между путями**
- `app/curriculum/service.py:complete_lesson()` передаёт `date.today()` (UTC-naive по серверу)
- `app/curriculum/routes/card_lessons.py:complete_srs_session()` использует timezone-aware дату пользователя
- `award_curriculum_lesson_xp_idempotent()` дедуплит по `(user_id, date, lesson_id)` — разные даты → дедуп не срабатывает → двойной XP в полночь по timezone

**P5. Grammar ошибки не попадают в QuizErrorLog**
- `app/curriculum/routes/grammar_quiz_lessons.py:105-146` — `process_grammar_submission()` не вызывает `log_quiz_errors_from_result()`
- Linear error-review slot (`app/daily_plan/linear/errors.py`) покрывает только `Lessons.type='quiz'`, grammar-ошибки отсутствуют

**P6. Module unlock не валидируется в lesson_by_id**
- `app/curriculum/routes/main.py:260-336` — `lesson_by_id()` рендерит урок без проверки `Module.check_prerequisites()`
- Прямой URL `/learn/{lesson_id}/` позволяет обойти checkpoint и final_test

**P7. Orphan миграция + три таблицы прогресса**
- `migrations/versions/d35366cf95ab_*.py` ссылается на таблицу `user_lesson_progress`, которая отсутствует в моделях
- Параллельно существуют `LessonProgress`, `LessonAttempt`, `UserChapterProgress` — неясно, кто источник истины при resume-from-dashboard

**P8. Три разных алгоритма «next lesson»**
- `app/daily_plan/linear/progression.py:find_next_lesson_linear()` — игнорирует checkpoint-логику
- `app/daily_plan/service.py` (mission assembler) — свой алгоритм
- `app/curriculum/service.py:get_user_active_lessons()` — третий
- Пользователь видит разные «следующий урок» в dashboard / linear / resume

**P9. Linear plan не увеличивает `plans_completed_total`**
- `app/achievements/streak_service.py:349-358` — `record_plan_completion()` вызывается только для mission/legacy плана (через `steps_done >= steps_total` для миссии)
- `app/daily_plan/linear/` не вызывает `record_plan_completion()` — линейные пользователи не продвигаются по рангам

**P10. `has_learning_activity()` не покрывает linear-only активность**
- `app/utils/activity_tracker.py:35-118` — 6 источников (LessonProgress, UserGrammarExercise, UserCardDirection.last_reviewed, UserChapterProgress, UserLessonProgress, StudySession)
- Linear user, работающий только через `/api/*` (без `StudySession`), может не создать активности → streak сбрасывается

**P11. Book ↔ BookCourse рассинхронизация**
- `app/books/routes.py:62-160` — `edit_book_content()` обновляет Book.chapters_cnt, но не пересчитывает связанные `BookCourse` объекты
- `Book.create_course` флаг есть, но нет cascade-update

**P12. Reading progress % занижает реальное значение**
- `app/books/routes.py:279-286, 630-641` — `sum(offset_pct) / total_chapters` = для 50% главы 1 + 100% главы 2 из 10 = 15% вместо 20%
- Метрика не отражает реальное продвижение

**P13. Orphan word_book_link при переобработке**
- `app/books/processors.py:776-779` — UPSERT при импорте, но нет DELETE старых связей
- Переобработка → накапливаются связи слов, которых больше нет в книге → искажение `unique_words`

**P14. Grammar orphans и validation gaps**
- `app/grammar_lab/models.py:106,275-307` — FK с `ondelete='CASCADE'` на уровне модели, но миграции без `CASCADE` — потенциальные orphans
- `content` JSONB без schema-validator — `correct_answer` может отсутствовать, grader вернёт `is_correct=False` на любой ответ

**P15. Dead code / legacy**
- `app/study/xp_service.py` — 320 строк с `DeprecationWarning`, `UserXP` model в БД, legacy writer'ы по коду
- `app/grammar_public/` — пустой blueprint (только `__pycache__`)
- `app/books/routes.py:397-424` — `/reader-v2` endpoint, `317-319` — old-style books block
- `SRSService.update_card_after_review()` уже удалён в предыдущем плане, но похожий legacy-шум остался в xp_service

## Development Approach

- **Testing approach**: Regular (код → тесты)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**
- Все изменения в существующих файлах; новых модулей нет (кроме мелких helper-ов при необходимости)
- После каждого Task: `python -c "import <module>"` для изменённых Python файлов
- После каждого блока: `pytest -m smoke` + таргетированные тесты

## Design Decisions

- **Canonical idempotency via StreakEvent**: все write-пути XP (book_chapter, referral, matching, quiz_game) должны дедуплиться через `StreakEvent(event_type='xp_*', details={...})` по натуральному ключу (user_id, date, event_type, dedup_key). Повторная операция — no-op.
- **Unified transaction boundary**: endpoint с несколькими XP-наградами использует одну транзакцию (`db.session.commit()` только в конце). Partial-failure недопустим.
- **Canonical date для lesson XP**: `app/curriculum/service.py:complete_lesson()` переходит на timezone-aware дату пользователя (как в `card_lessons.py`). Источник — `User.timezone` или `datetime.now(ZoneInfo(user.timezone)).date()`. `award_curriculum_lesson_xp_idempotent()` принимает `for_date` — это и есть источник dedup-ключа.
- **Grammar errors в QuizErrorLog**: `process_grammar_submission()` вызывает `log_quiz_errors_from_result()` с question_payload, сопоставимым с quiz-форматом. Dedup по `question_payload['question_index']` уже работает.
- **Module unlock validation**: `lesson_by_id()` проверяет `lesson.module.check_prerequisites(user)` перед render; при неудаче — redirect на module с flash-сообщением.
- **«Next lesson» single source**: `app/daily_plan/linear/progression.py:find_next_lesson_linear()` — канонический. Mission assembler и `get_user_active_lessons()` делегируют в неё (или используют ту же сигнатуру).
- **Linear plan_completed_total**: добавить `record_plan_completion()` вызов в точку завершения linear-плана — когда все required slots в `day_secured=True`. Флаг в `DailyPlanLog` или отдельный event для дедупа.
- **has_learning_activity источники**: добавить `StreakEvent(event_type='xp_linear')` за дату как дополнительный источник (linear-activity = есть XP event за день).
- **Book ↔ BookCourse sync**: `edit_book_content()` триггерит пересчёт привязанных BookCourse (chapter count, content hash). Если `Book.create_course=True` → `update_book_course_from_book()`.
- **Reading progress %**: `chapters_completed_count + partial_current_chapter / total_chapters`, где `partial_current_chapter = offset_pct` только текущей главы.
- **word_book_link cleanup**: `reprocess_book()` делает `DELETE FROM word_book_link WHERE book_id = ?` перед UPSERT новых связей.
- **Grammar validation**: `GrammarExercise.validate_content()` метод проверяет наличие `correct_answer` в зависимости от `exercise_type`. Вызывается в `__init__` и на import.
- **Dead code policy**: удалить `app/grammar_public/` целиком (GREP показывает 0 ссылок), удалить `/reader-v2` и old-style blocks, удалить `UserXP` модель после проверки 0 writer'ов через grep, удалить `study/xp_service.py`.
- **Миграции**: удалить `d35366cf95ab` (если таблица действительно orphan) или восстановить `user_lesson_progress` как alias. Решение по результатам grep — если модель нужна, сохранить и добавить в models; иначе — downgrade + удалить миграцию.

---

## Implementation Steps

### BLOCK 1: XP Idempotency Hardening (Tasks 1–4)

### Task 1: Idempotent `book_chapter` XP + single-transaction chapter-complete

**Files:**
- Modify: `app/books/api.py`
- Modify: `app/achievements/xp_service.py` (если нужно добавить helper)
- Modify: `tests/books/test_api.py` (или `tests/test_books_api.py`)

- [x] В `app/books/api.py` progress-update endpoint: обернуть все XP-начисления в одну транзакцию — единственный `db.session.commit()` в конце; убрать промежуточные commit'ы (строки 894, 907 оставить только финальный на 929)
- [x] Ввести `award_book_chapter_xp_idempotent(user_id, book_id, chapter_id, xp, db, for_date)` в `app/achievements/xp_service.py` — дедуп через `StreakEvent(event_type='xp_book_chapter', details={'book_id': ..., 'chapter_id': ...})`. Flush без commit — caller коммитит.
- [x] Заменить inline-`_award_xp_unified(..., 'book_chapter')` (строка 904) на вызов нового helper-а
- [x] Concurrency: `SELECT ... FOR UPDATE` на `UserChapterProgress` при обновлении `offset_pct` в двух вкладках → первый запрос лочит строку, второй ждёт → race устранён
- [x] Write tests: повторный POST на ту же главу в тот же день не даёт второго XP; partial failure на linear_book_reading обёрнут в savepoint и не откатывает book_chapter XP (single-transaction assertion на исходнике)
- [x] `python -c "from app.books.api import *"` — проходит
- [x] Run pytest — must pass before task 2

---

### Task 2: Idempotent referral and game XP

**Files:**
- Modify: `app/words/routes.py` (referral XP)
- Modify: `app/auth/routes.py` (referral XP)
- Modify: `app/study/game_routes.py` (matching, quiz games)
- Modify: `app/achievements/xp_service.py` (helpers)
- Modify: `tests/test_referrals.py`, `tests/test_study_games.py`

- [x] Ввести `award_referral_xp_idempotent(referrer_id, referee_id, xp, db)` — dedup через `StreakEvent(event_type='xp_referral', details={'referee_id': ...})`. Раз навсегда — не по дате.
- [x] Заменить ручные `_award_xp_unified(..., 'referral')` в `app/words/routes.py` и `app/auth/routes.py` на новый helper
- [x] Ввести `award_game_xp_idempotent(user_id, game_session_id, game_type, xp, db, for_date)` — dedup через `StreakEvent(event_type='xp_game', details={'session_id': ..., 'game_type': ...})`
- [x] Заменить `award_xp(user_id, xp, 'study_matching_game')` и `'study_quiz_game'` на новый helper с session_id из game-логики
- [x] Write tests: повторный POST на reward referral не даёт double-XP; повторная отправка matching/quiz result не даёт double-XP; новая сессия game → новый XP
- [x] Run pytest — must pass before task 3

---

### Task 3: Grammar_lab ↔ curriculum XP coordination

**Files:**
- Modify: `app/grammar_lab/services/grammar_lab_service.py`
- Modify: `app/daily_plan/linear/xp.py` (если нужно)
- Modify: `tests/grammar_lab/test_service.py`

- [x] В `grammar_lab_service.submit_answer()` (строки 402-403): проверить `user.use_linear_plan` — если linear, XP начисляет только linear-путь (для grammar через `maybe_award_curriculum_xp` при завершении lesson). grammar_lab submit в linear режиме → `srs.add_xp` не вызывается, только SRS update.
- [x] В legacy (mission/пустой) режиме `grammar_lab.submit_answer` продолжает начислять XP как сейчас (это standalone grammar практика вне curriculum)
- [x] Документировать в docstring `submit_answer`: XP зависит от mode user'а
- [x] Write tests: linear user — submit_answer не увеличивает XP напрямую; mission/legacy user — XP начисляется; при наличии curriculum-контекста XP приходит через linear_curriculum_grammar, не дважды
- [x] Run pytest — must pass before task 4

---

### Task 4: Unified date for curriculum lesson XP

**Files:**
- Modify: `app/curriculum/service.py`
- Modify: `app/curriculum/xp.py` (если нужно)
- Modify: `app/utils/time_utils.py` (если helper для user-tz нужен)
- Modify: `tests/curriculum/test_xp.py`

- [x] В `app/curriculum/service.py:complete_lesson()`: вместо `date.today()` использовать дату пользователя — если `user.timezone` задан, `datetime.now(ZoneInfo(user.timezone)).date()`, иначе UTC-date
- [x] Если нет helper-а — добавить `get_user_local_date(user) -> date` в `app/utils/time_utils.py`; вызвать его в `complete_lesson()` и `card_lessons.complete_srs_session()` — одна функция для обоих путей (card_lessons already uses it via `get_linear_event_local_date`, which now delegates to the canonical helper)
- [x] Write tests: пользователь с timezone `America/New_York` в 23:30 EDT = UTC next-day → `complete_lesson` использует EDT-дату; повторный вызов в UTC next-day дедуплит корректно
- [x] Run pytest — must pass before task 5

---

### BLOCK 2: Grammar & Access Control (Tasks 5–6)

### Task 5: Log grammar errors into QuizErrorLog

**Files:**
- Modify: `app/curriculum/routes/grammar_quiz_lessons.py`
- Modify: `app/daily_plan/linear/errors.py` (если contract нужно расширить)
- Modify: `tests/curriculum/test_grammar_quiz_lessons.py`

- [ ] В `process_grammar_submission()` (строки 105-146): собрать `errors_payload` в формате, совместимом с `log_quiz_errors_from_result` (список `{question_index, question_payload, user_answer, correct_answer}`)
- [ ] Вызвать `log_quiz_errors_from_result(user_id, lesson_id, errors_payload, db)` после grading
- [ ] Если contract не подходит (grammar — не quiz) → расширить `log_quiz_errors_from_result` на `question_type ∈ {'quiz', 'grammar'}` с общим dedup-ключом
- [ ] Убедиться, что `should_show_error_review()` корректно учитывает grammar-ошибки в счётчике unresolved
- [ ] Write tests: grammar submission с 2 неверными ответами → 2 строки в `QuizErrorLog`; resolve через повторное прохождение сбрасывает `answered_wrong_at → resolved_at`
- [ ] Run pytest — must pass before task 6

---

### Task 6: Module unlock validation in `lesson_by_id`

**Files:**
- Modify: `app/curriculum/routes/main.py`
- Modify: `app/curriculum/models.py` (если `check_prerequisites` нужно доработать)
- Modify: `tests/curriculum/test_routes.py`

- [ ] В `lesson_by_id()` (строки 260-336 `main.py`): после загрузки lesson вызвать `lesson.module.check_prerequisites(current_user)`; если False → `flash('Module is locked')` + redirect на `url_for('curriculum.module_view', module_id=...)`
- [ ] Отдельный decorator `@require_lesson_access` — инкапсулирует валидацию, применим ко всем route'ам, которые загружают lesson по id (включая quiz, grammar, card, reading, final_test)
- [ ] Применить decorator ко всем relevant route'ам в `app/curriculum/routes/*.py`
- [ ] Write tests: prerequisite не удовлетворён → redirect + flash; admin user обходит проверку; final_test блокируется если предыдущие уроки не завершены
- [ ] Run pytest — must pass before task 7

---

### BLOCK 3: Progress Tracking & Navigation (Tasks 7–8)

### Task 7: Clean up orphan `user_lesson_progress` migration

**Files:**
- Investigate: `migrations/versions/d35366cf95ab_*.py`
- Possibly modify: `app/models/`
- Possibly delete: orphan migration
- Modify: `tests/test_migrations.py` (если есть migration chain check)

- [ ] Grep: есть ли `user_lesson_progress` таблица в текущей БД (проверить через `alembic current` и introspection); есть ли модель с такой `__tablename__`
- [ ] Если таблица реально используется (например, book-course lessons) — добавить модель `UserLessonProgress` в `app/models/` и документировать её роль vs `LessonProgress`
- [ ] Если таблица неиспользуемая — создать downgrade-миграцию с `DROP TABLE user_lesson_progress IF EXISTS` и удалить `d35366cf95ab`
- [ ] Проверить migration chain: `alembic history` — нет orphan'ов, все revisions связаны
- [ ] Write tests: migration chain integrity check (если нет — добавить базовый smoke)
- [ ] Run pytest — must pass before task 8

---

### Task 8: Unify «next lesson» navigation

**Files:**
- Modify: `app/daily_plan/linear/progression.py`
- Modify: `app/daily_plan/service.py` (mission assembler)
- Modify: `app/curriculum/service.py` (`get_user_active_lessons`)
- Modify: `tests/daily_plan/test_progression.py`

- [ ] Сделать `app/daily_plan/linear/progression.py:find_next_lesson_linear()` канонической функцией; переименовать в `find_next_lesson(user_id, db)` и переместить в `app/curriculum/navigation.py` (новый модуль) или оставить где есть с переименованием
- [ ] Mission assembler (`app/daily_plan/service.py`) и `get_user_active_lessons()` делегируют в `find_next_lesson()`; убрать дубликаты алгоритма
- [ ] Учесть checkpoint-логику в едином алгоритме: если предыдущий checkpoint не пройден (score < threshold), следующий модуль не доступен
- [ ] Write tests: linear/mission/dashboard возвращают одинаковый next_lesson для одного пользователя; checkpoint failed → next_lesson = checkpoint, а не next module lesson
- [ ] Run pytest — must pass before task 9

---

### BLOCK 4: Rank & Streak Coverage for Linear (Tasks 9–10)

### Task 9: `record_plan_completion` for linear plan

**Files:**
- Modify: `app/daily_plan/linear/xp.py` или `app/daily_plan/linear/plan.py`
- Modify: `app/achievements/streak_service.py` (если helper нужно расширить)
- Modify: `tests/daily_plan/test_linear_completion.py`

- [ ] Ввести `maybe_record_linear_plan_completion(user_id, plan, plan_completion, for_date, db)` — если `compute_day_secured_from_activity(plan, plan_completion) == True`, вызвать `record_plan_completion(user_id, db)` и `check_rank_up(user_id, db)`
- [ ] Dedup через `StreakEvent(event_type='linear_plan_completed', details={'date': ...})` — один раз в день
- [ ] Вызвать helper в `/api/daily-status` при обнаружении `day_secured=True` (там где уже `write_secured_at`)
- [ ] Write tests: linear user завершает 3 required slot — `plans_completed_total` инкрементится на 1; повторный вызов API — не инкрементит; rank_up триггерится при переходе порога
- [ ] Run pytest — must pass before task 10

---

### Task 10: `has_learning_activity` source expansion for linear

**Files:**
- Modify: `app/utils/activity_tracker.py`
- Modify: `tests/test_activity_tracker.py`

- [ ] Добавить 7-й источник: `StreakEvent.query.filter(StreakEvent.user_id == user_id, StreakEvent.event_type.like('xp_linear%'), StreakEvent.event_date >= start_utc, StreakEvent.event_date < end_utc).exists()`
- [ ] Убедиться, что DAU/WAU/MAU (`_active_user_ids_for_date`) остаётся согласованным — либо синхронно добавить туда же, либо документировать расхождение (DAU = 7 source, streak = 7 sources с +StreakEvent)
- [ ] Write tests: linear user делает только `/api/*` calls → `has_learning_activity=True` если есть `xp_linear` event за дату; нет events → False; legacy источники продолжают работать
- [ ] Run pytest — must pass before task 11

---

### BLOCK 5: Books & Grammar Data Integrity (Tasks 11–13)

### Task 11: CASCADE for grammar exercises + content schema validation

**Files:**
- Create: `migrations/versions/YYYYMMDD_grammar_exercise_cascade.py`
- Modify: `app/grammar_lab/models.py`
- Modify: `app/grammar_lab/content_validator.py` (новый)
- Modify: `tests/grammar_lab/test_content_validation.py`

- [ ] Создать миграцию: `ALTER TABLE user_grammar_exercises DROP CONSTRAINT ... ADD CONSTRAINT ... FOREIGN KEY (exercise_id) REFERENCES grammar_exercises(id) ON DELETE CASCADE` (аналогично для `grammar_attempts`)
- [ ] Создать `app/grammar_lab/content_validator.py` — `validate_exercise_content(exercise_type, content) -> None | raise ValueError`; проверяет наличие `correct_answer` для типов `fill_blank`, `multiple_choice`, `reorder`, `transformation`, `error_correction`, `matching`, `true_false`
- [ ] Вызвать validator в `GrammarExercise.__init__` и на import (`curriculum_import_service.py`)
- [ ] Write tests: exercise без `correct_answer` → `ValueError`; delete exercise → cascade удаляет `user_grammar_exercises` и `grammar_attempts`; import broken exercise → validation ошибка
- [ ] Run pytest — must pass before task 12

---

### Task 12: Book ↔ BookCourse sync + word_book_link cleanup

**Files:**
- Modify: `app/books/routes.py` — `edit_book_content()`
- Modify: `app/books/processors.py` — reprocess_book
- Modify: `app/curriculum/book_courses.py` — add `sync_from_book()`
- Modify: `tests/books/test_sync.py`

- [ ] В `edit_book_content()`: после успешного save Book, если `Book.create_course=True` → `sync_book_course_from_book(book_id, db)` пересчитывает связанные BookCourse: chapters, titles, content hash
- [ ] В `reprocess_book()` (или аналогичный путь): перед UPSERT `word_book_link` → `DELETE FROM word_book_link WHERE book_id = :book_id`
- [ ] Write tests: edit Book.title → BookCourse.title обновлён; reprocess Book → старые word_book_link удалены, остаются только актуальные; `unique_words_count` корректно пересчитывается
- [ ] Run pytest — must pass before task 13

---

### Task 13: Reading progress % correction

**Files:**
- Modify: `app/books/routes.py` — `read_selection` и book detail
- Modify: `app/books/services.py` (новая функция `compute_book_progress_percent`)
- Modify: `tests/books/test_progress.py`

- [ ] Ввести `compute_book_progress_percent(user_id, book_id, db) -> float`:
  - `completed_chapters = count(UserChapterProgress WHERE user=X, book=Y, offset_pct >= 1.0)`
  - `current_chapter_partial = max(offset_pct for incomplete chapters) or 0`
  - `progress = (completed_chapters + current_chapter_partial) / total_chapters`
- [ ] Заменить inline `sum(offset_pct) / total_chapters` в `app/books/routes.py:279-286, 630-641` на новую функцию
- [ ] Write tests: 2/10 глав completed + 50% главы 3 → (2 + 0.5) / 10 = 25% (не 15%); 0 completed → 0%; все 10 → 100%
- [ ] Run pytest — must pass before task 14

---

### BLOCK 6: Dead Code Removal (Tasks 14–15)

### Task 14: Remove legacy UserXP and `study/xp_service.py`

**Files:**
- Modify/Delete: `app/study/xp_service.py`
- Modify: `app/study/services/session_service.py` (убрать `UserXP.get_or_create`)
- Modify: `app/study/services/stats_service.py`
- Modify: `app/models/` — удалить `UserXP` model (осторожно!)
- Create: `migrations/versions/YYYYMMDD_drop_user_xp_table.py`
- Modify: tests

- [ ] Grep: `UserXP`, `user_xp` — ноль производственных writer'ов (только legacy shim); ноль читателей вне deprecated модуля
- [ ] Удалить `app/study/xp_service.py` полностью (класс `XPService` с 320 строк — методы `calculate_quiz_xp`, `check_quiz_achievements` и пр.)
- [ ] В `session_service.py` и `stats_service.py`: убрать `UserXP.get_or_create()` возврат из `award_xp`-shim; вернуть что-то совместимое (либо dict, либо `UserStatistics`)
- [ ] Удалить `UserXP` model из `app/models/`
- [ ] Создать миграцию: `DROP TABLE user_xp` (после проверки что миграция `20260424_sync_user_xp_to_stats` уже применена везде)
- [ ] Write tests: smoke тесты XP-путей проходят без UserXP; `assert not hasattr(app.study, 'xp_service')` (или import fails)
- [ ] Run pytest — must pass before task 15

---

### Task 15: Remove empty blueprints and legacy reader

**Files:**

[//]: # (- Delete: `app/grammar_public/` &#40;целиком&#41;)
- Modify: `app/__init__.py` (unregister blueprint)
- Modify: `app/books/routes.py` — удалить `/reader-v2` и old-style blocks
- Modify: templates (если legacy reader-v2 template есть)
- Modify: tests

[//]: # (- [ ] Grep: `grammar_public` — ноль ссылок &#40;кроме `__init__.py`&#41;; удалить `app/grammar_public/` директорию целиком)
- [ ] В `app/__init__.py`: убрать `register_blueprint(grammar_public_bp)` и import
- [ ] В `app/books/routes.py:397-424`: удалить `/reader-v2` endpoint если ноль ссылок; grep templates на `reader-v2` URL
- [ ] В `app/books/routes.py:317-319`: удалить old-style blocks (книги без `content` field)

[//]: # (- [ ] Write tests: `app.url_map` не содержит `grammar_public.*` и `reader-v2` routes; старые URL'ы возвращают 404)
- [ ] Run pytest — must pass before task 16

---

### BLOCK 7: Final Validation (Task 16)

### Task 16: Full smoke test pass and regression check

**Files:**
- No code changes — validation only

- [ ] `pytest -m smoke` — все smoke тесты зелёные
- [ ] `pytest tests/achievements/ tests/curriculum/ tests/grammar_lab/ tests/books/ tests/daily_plan/` — все доменные тесты зелёные
- [ ] `alembic history` — migration chain без orphan'ов; `alembic upgrade head` на чистой БД проходит
- [ ] `python -m py_compile` на всех изменённых файлах
- [ ] Grep на: `UserXP`, `grammar_public`, `reader-v2`, `SRSService.update_card_after_review`, `study.xp_service` — все должны быть 0 (или только в changelog/docs)
- [ ] Manual smoke: linear user завершает день → `plans_completed_total` увеличен, rank обновлён, streak сохранён; curriculum lesson в полночь не даёт double-XP; chapter completion с race в двух вкладках — один XP; grammar error попадает в error-review; locked module по прямой URL блокируется
- [ ] Update `MEMORY.md` если нужно зафиксировать новые canonical-пути (e.g. `find_next_lesson`, `compute_book_progress_percent`)
