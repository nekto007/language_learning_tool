# 8 Tasks: Entity Consistency — XP, Activity Tracking, Achievements, Lesson Completion

## Overview

Архитектурный аудит всех не-SRS сущностей выявил несколько системных расхождений. Центральная проблема — два параллельных, несвязанных XP-счётчика: `UserXP` (пишется study-сессиями, читается лидербордом) и `UserStatistics.total_xp` (пишется mission/linear plan, читается для расчёта уровня на дашборде). Пользователь проходит карточки — уровень не меняется. Проходит миссии — в лидерборде ничего. Параллельно: `has_activity_today()` и `_count_active_users_in_range()` в admin проверяют разные наборы источников → разные числа DAU, разная логика streak. Также: достижения уязвимы к race condition дублирования, completion урока в curriculum.service.py вызывает неидемпотентный award_xp.

## Context

- **Ключевые файлы:**
  - `app/study/xp_service.py` — устаревший `XPService`, пишет в `UserXP`
  - `app/achievements/xp_service.py` — современный `award_xp`, пишет в `UserStatistics.total_xp`
  - `app/study/services/stats_service.py` — лидерборд, читает `UserXP`
  - `app/words/routes.py:341` — дашборд уровня, читает `UserStatistics.total_xp`
  - `app/study/api_routes.py:544-565` — `complete_session`, вызывает `XPService.award_xp`
  - `app/study/game_routes.py` — matching/quiz game, вызывает `XPService.award_xp`
  - `app/curriculum/service.py:255-257` — `complete_lesson`, вызывает `XPService.award_xp`
  - `app/telegram/queries.py:39-88` — `has_activity_today` (5 источников)
  - `app/admin/main_routes.py:35-114` — `_count_active_users_in_range` (6 источников)
  - `app/achievements/streak_service.py` — streak, читает activity
  - `app/achievements/services.py` — `grant_achievement`, race condition
  - `app/study/models.py` — `UserXP`, `UserAchievement` (UniqueConstraint)
  - `app/achievements/models.py` — `UserStatistics`

- **Паттерны:** `StreakEvent` как dupe-checker, `_safe_widget_call()` в routes, `UniqueConstraint` на UserAchievement

- **Dependencies:** нет внешних; Flask/SQLAlchemy/PostgreSQL

## Current State

### Подтверждённые проблемы аудитом

**P1. Два параллельных XP-счётчика (Critical)**
- `UserXP` (table `user_xp`): пишется через `XPService.award_xp()` из `study/xp_service.py` при завершении карточной сессии (`complete_session`), matching game, quiz game, curriculum `complete_lesson()`
- `UserStatistics.total_xp`: пишется через `award_xp()` из `achievements/xp_service.py` при завершении mission phases и linear plan slots
- Лидерборд читает `UserXP` → mission XP не отражается в лидерборде
- Уровень на дашборде считается из `UserStatistics.total_xp` → study XP не меняет уровень
- Два числа расходятся, растут независимо, нигде не суммируются

**P2. XPService.award_xp не идемпотентен (High)**
- `study/xp_service.py:XPService.award_xp()` — просто `user_xp.add_xp(amount); db.session.commit()`, нет dupe check
- `curriculum/service.py:complete_lesson()` вызывает его без защиты от повторного вызова
- Если `complete_lesson()` вызвать дважды (повторная загрузка страницы, retry), XP дублируется

**P3. Несоответствие источников активности для streak vs DAU (High)**
- `has_activity_today()` в `telegram/queries.py` проверяет: LessonProgress.last_activity, UserGrammarExercise.last_reviewed, UserCardDirection.last_reviewed, UserChapterProgress.updated_at, UserLessonProgress.completed_at (5 источников)
- Admin `_count_active_users_in_range()` использует UNION: lesson_progress, study_sessions, user_grammar_exercises, user_chapter_progress, book_course_enrollments, lesson_attempts (6 источников — нет UserLessonProgress, есть study_sessions + lesson_attempts)
- Streak-сервис использует `_has_activity_in_range()` в `telegram/queries.py` — те же 5 источников
- Пользователь с активностью только в study_sessions не будет засчитан в streak, но войдёт в DAU

**P4. Race condition дублирования достижений (Medium)**
- `grant_achievement()` (или аналог) проверяет `UserAchievement.query.filter_by(user_id, achievement_id).first()` затем insert
- Нет `SELECT FOR UPDATE` → при одновременных запросах два процесса могут вставить дубликат
- `UniqueConstraint` поймает это как IntegrityError, но без обработки это 500 error

**P5. LessonProgress.last_activity — nullable, используется без IS NOT NULL (Medium)**
- В `has_activity_today()` фильтр `LessonProgress.last_activity >= today_start` — если `last_activity IS NULL`, строка отфильтруется, но в принципе NULL-значения могут вызвать неожиданное поведение при сравнении в некоторых ORM-версиях

**P6. UserXP используется для referral XP (Low)**
- `words/routes.py:141` — реферальный бонус пишется в `UserXP`
- Если решить унифицировать XP в P1, referral нужно перевести тоже

## Development Approach

- **Testing approach**: Regular (код → тесты)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**
- P1 — самая большая задача: требует решения о стратегии унификации (см. Design Decisions)
- `python -c "import app.<module>"` после каждого изменённого файла

## Design Decisions

- **XP унификация**: Единый источник истины — `UserStatistics.total_xp`. `UserXP` deprecate: перестать писать в него из новых мест, запустить одноразовую миграцию-синхронизацию (migrate existing `UserXP` total → `UserStatistics.total_xp`). Лидерборд перевести на `UserStatistics.total_xp`. `UserXP` оставить (не удалять) — только исключить из новых вызовов.
- **XP idempotency для curriculum**: `complete_lesson()` должна использовать `StreakEvent` для dedup, аналогично `award_phase_xp_idempotent()`. Ключ: `('xp_curriculum_lesson', lesson_id, date)`.
- **Activity tracking**: Привести `has_activity_today()` и `_has_activity_in_range()` к тому же набору что admin: добавить проверку `StudySession` (сегодняшние сессии) как 6-й источник. `UserLessonProgress` (book courses) оставить — это корректный источник активности.
- **Achievement race condition**: обернуть grant в `try/except IntegrityError` с rollback + return existing; это идемпотентный upsert-паттерн.
- **Referral XP**: перевести на `UserStatistics.total_xp` в той же итерации что и P1.

---

## Implementation Steps

### BLOCK 1: XP Unification (Tasks 1–3)

### Task 1: One-time XP migration — sync UserXP totals → UserStatistics

Синхронизировать накопленный XP из старого счётчика в новый. Делается один раз, через Alembic data-migration.

**Files:**
- Create: `migrations/versions/<rev>_sync_user_xp_to_stats.py`
- Create: `tests/migrations/test_xp_sync.py` (smoke test)

- [x] Alembic revision (data migration, НЕ schema): для каждого `UserXP` row найти или создать `UserStatistics` row, добавить `UserXP.total_xp` к `UserStatistics.total_xp` если еще не синхронизировано
- [x] Добавить sentinel-флаг: колонку `user_xp.synced_to_stats BOOLEAN DEFAULT FALSE` или использовать `UserStatistics.total_xp > 0` как check (проще: просто прибавить, деньги не важны, важна относительность; если уже есть migration, делать один раз через `synced_at`)
- [x] Запустить `alembic upgrade head` в dev, убедиться что данные синхронизированы (skipped - not automatable in this environment; verified via sync helper test)
- [x] Write tests: после миграции `UserStatistics.total_xp >= UserXP.total_xp` для всех users с обеими записями
- [x] Run pytest — must pass before task 2

---

### Task 2: Redirect all XPService.award_xp callers → achievements/xp_service.award_xp

Все места где `UserXP` пополняется — перевести на современный счётчик.

**Files:**
- Modify: `app/study/api_routes.py` (complete_session, ~line 565)
- Modify: `app/study/game_routes.py` (matching game, quiz game)
- Modify: `app/curriculum/service.py` (complete_lesson, ~line 257)
- Modify: `app/words/routes.py` (referral XP, ~line 141)
- Modify: `app/study/services/session_service.py` (award_xp delegate)
- Create: `tests/study/test_xp_unification.py`

- [x] В каждом caller: заменить `XPService.award_xp(user_id, amount)` на `from app.achievements.xp_service import award_xp; award_xp(user_id, amount, source='<context>')`
- [x] `curriculum/service.py:complete_lesson()`: добавить idempotency через StreakEvent — `award_curriculum_lesson_xp_idempotent(user_id, lesson_id, for_date)` в `app/daily_plan/linear/xp.py` или в новом `app/curriculum/xp.py`; функция использует `StreakEvent(event_type='xp_curriculum_lesson', details={'lesson_id': lesson_id})`
- [x] Referral XP: заменить `UserXP.get_or_create; add_xp` на `award_xp(user_id, 100, 'referral')`; commit остаётся у caller
- [x] `study/xp_service.py:XPService` — добавить deprecated warning в `award_xp`; не удалять файл пока все callers не переведены
- [x] Проверить что `session_service.py:award_xp` тоже перенаправляет на новый
- [x] Write tests: после завершения карточной сессии `UserStatistics.total_xp` увеличивается; после curriculum lesson — не дублируется при повторном вызове complete_lesson
- [x] Run pytest — must pass before task 3

---

### Task 3: Redirect leaderboard → UserStatistics.total_xp

Лидерборд должен показывать суммарный XP, а не только study-сессии.

**Files:**
- Modify: `app/study/services/stats_service.py` (get_xp_leaderboard, get_user_xp_rank, get_leaderboard_data)
- Modify: `tests/study/test_stats_service.py`

- [x] `get_xp_leaderboard()`: заменить JOIN с `UserXP` на JOIN с `UserStatistics`, поле `total_xp`
- [x] `get_user_xp_rank()`: заменить `UserXP.query` на `UserStatistics.query.filter_by(user_id=user_id)` для rank calculation
- [x] `get_leaderboard_data()` (если есть, ~line 248 обрабатывает 'all' case): перевести `func.sum(UserXP.xp_amount)` на `UserStatistics.total_xp`
- [x] Убедиться что `StatsService.get_xp_leaderboard()` вызывается из `_get_cached_leaderboard()` в `words/routes.py` — cache автоматически инвалидируется при изменении логики
- [x] Write tests: leaderboard возвращает users отсортированных по `UserStatistics.total_xp`; `get_user_xp_rank` использует `UserStatistics`
- [x] Run pytest — must pass before task 4

---

### BLOCK 2: Activity Tracking Unification (Tasks 4–5)

### Task 4: Create canonical `has_learning_activity` function

Единая функция проверки активности, используемая streak-сервисом, telegram, и admin.

**Files:**
- Create: `app/utils/activity_tracker.py`
- Modify: `app/telegram/queries.py`
- Modify: `app/achievements/streak_service.py` (если использует свою логику)
- Create: `tests/utils/test_activity_tracker.py`

- [x] `has_learning_activity(user_id, start_utc, end_utc, db) -> bool` — проверяет 6 источников: LessonProgress.last_activity, UserGrammarExercise.last_reviewed, UserCardDirection.last_reviewed (через join UserWord), UserChapterProgress.updated_at, UserLessonProgress.completed_at, StudySession (created_at или ended_at за период)
- [x] Все datetime comparisons — явно приводить к naive UTC (`.replace(tzinfo=None)`) если колонки без TZ, или к aware если с TZ — проверить каждую колонку в schemas
- [x] В `telegram/queries.py:has_activity_today()` → заменить тело на `has_learning_activity(user_id, today_start.replace(tzinfo=None), today_end.replace(tzinfo=None), db)` (или через naive conversion внутри функции)
- [x] В `telegram/queries.py:_has_activity_in_range()` → аналогично делегировать на `has_learning_activity`
- [x] Write tests: пользователь с только StudySession активностью → True; пользователь без активности → False; boundary cases (активность ровно в полночь)
- [x] Run pytest — must pass before task 5

---

### Task 5: Align admin DAU with canonical activity function

Admin `_count_active_users_in_range()` должен использовать те же источники.

**Files:**
- Modify: `app/admin/main_routes.py`
- Modify: `tests/admin/`

- [x] Проверить существующую реализацию `_count_active_users_in_range()` — добавить `UserLessonProgress` как 7-й источник в UNION (или удостовериться что StudySession уже покрывает book-course активность)
- [x] `_activity_date_expr(last_activity, completed_at)` — убедиться что COALESCE-логика даёт правильный день; если `completed_at` в другой TZ чем `last_activity` → возможна ошибка определения дня
- [x] Write tests: пользователь с только `UserLessonProgress.completed_at` сегодня → считается в DAU
- [x] Run pytest — must pass before task 6

---

### BLOCK 3: Achievement Safety (Task 6)

### Task 6: Fix race condition in achievement granting

**Files:**
- Modify: `app/achievements/services.py` (grant_achievement или аналог)
- Modify: `tests/achievements/test_services.py`

- [x] Найти функцию которая создаёт `UserAchievement` — grep `UserAchievement(` по app/
- [x] Обернуть вставку в `try/except IntegrityError`: если raised — rollback savepoint, вернуть existing `UserAchievement`; не бросать 500
- [x] Добавить `select_for_update=False` hint или просто обработку IntegrityError (INSERT ... ON CONFLICT DO NOTHING не всегда доступен через ORM без raw SQL)
- [x] Проверить что `notify_in_app_achievements` проверяется ДО создания notification (не после) — gated внутри `create_notification` через `_user_allows`
- [x] Write tests: двойной вызов `grant_achievement` для одного user+achievement → один ряд в БД, нет IntegrityError в ответе
- [x] Run pytest — must pass before task 7

---

### BLOCK 4: Lesson Completion Standardization (Task 7)

### Task 7: Make curriculum complete_lesson idempotent for XP

(Частично покрыто Task 2 — здесь только финальная верификация и тест)

**Files:**
- Modify: `app/curriculum/service.py`
- Create: `app/curriculum/xp.py` (если не создан в Task 2)
- Modify: `tests/curriculum/test_service.py`

- [ ] `complete_lesson(user_id, lesson_id)` вызывает `award_curriculum_lesson_xp_idempotent(user_id, lesson_id, today_date, db)`
- [ ] Идемпотентность: `StreakEvent.query.filter_by(user_id, event_type='xp_curriculum_lesson').filter(details.lesson_id == lesson_id, event_date == today)` → если есть, skip
- [ ] При создании новой StreakEvent — `db.session.flush()` не `commit()` (caller commits)
- [ ] Write tests: первый вызов complete_lesson → XP awarded; второй вызов в тот же день → XP не дублируется; в новый день → XP снова awarded
- [ ] Run pytest — must pass before task 8

---

### BLOCK 5: Final Validation (Task 8)

### Task 8: Full smoke test pass + manual XP verification

**Files:**
- No code changes

- [ ] `pytest -m smoke` — все green
- [ ] `pytest tests/study/` — all pass
- [ ] `pytest tests/achievements/` — all pass
- [ ] `pytest tests/curriculum/` — all pass
- [ ] `pytest tests/admin/` — all pass
- [ ] Manual: зайти как тестовый user, завершить карточную сессию → `UserStatistics.total_xp` увеличился, уровень на дашборде обновился
- [ ] Manual: завершить карточную сессию → лидерборд отражает новый XP
- [ ] Manual: получить достижение дважды быстро (через API) → в БД только одна запись

## Зависимость от Plan 1 (SRS Audit)

Tasks 1–3 этого плана независимы от Plan 1. Task 4-5 (activity tracking) независимы. Task 6-7 независимы. Можно выполнять параллельно с Plan 1 по разным блокам, но не в одних и тех же файлах одновременно.
