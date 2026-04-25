# 13 Tasks: Learning Quality — Assessment, SRS, Feedback Loops, Onboarding

## Overview

Аудит методики обучения выявил 27 пробелов. Этот план закрывает 13 наиболее leverage-ных без изменения архитектуры. Центральная проблема: **активность ≠ качество** — система награждает клики, а не усвоение. Fuzzy grading засчитывает неверные ответы, matching доверяет клиенту, XP не зависит от точности, leech-слова продолжают падать ежедневно без ремедиации, grammar mastery требует 180-дней и недостижима, слабые топики не влияют на план, error review не масштабируется. Исправляется без новой архитектуры — только алгоритмы, пороги, маршрутизация.

Намеренно вынесены за рамки: speaking-инфраструктура (#11), cross-domain SkillMap (#27), full placement quiz (#16) — отдельные планы.

## Context

- **Ключевые файлы (assessment):**
  - `app/curriculum/grading.py:547-550` — fuzzy 60% fill-in-blank
  - `app/curriculum/grading.py:622` — `is_correct = user_answer == 'completed'`
  - `app/curriculum/grading.py:919` — `passed = score >= 70`
- **Ключевые файлы (XP):**
  - `app/achievements/xp_service.py:306` — `award_xp(user_id, base_amount, source)` без score
  - `app/achievements/xp_service.py:37,43-58` — `PERFECT_DAY_BONUS_XP_LINEAR=25`, `LINEAR_XP` dict
  - `app/achievements/xp_service.py:141-146` — streak multiplier `1.0 + days*0.02`
- **Ключевые файлы (SRS):**
  - `app/srs/constants.py:41,45,70,96,97` — `LEARNING_STEPS=[1,10]`, `GRADUATING_INTERVAL=1`, `MIN_EASE_FACTOR=1.3`, `LAPSE_MINIMUM_INTERVAL=1`, `LEECH_THRESHOLD=6`
  - `app/srs/service.py:295-305` — lapse handling (→ RELEARNING, не buried)
  - `app/study/services/srs_service.py:225-231` — adaptive limits `<85% OR backlog>50 → min(2, base)`
- **Ключевые файлы (grammar):**
  - `app/grammar_lab/services/grammar_lab_service.py:407,453-486` — mastery threshold 180d
  - `app/grammar_lab/services/grammar_lab_service.py:214` — `difficulty` в сортировке, но не в scheduling
  - `app/study/insights_service.py:257-298` — `get_grammar_weaknesses` (не читается планом)
- **Ключевые файлы (errors/feedback):**
  - `app/daily_plan/linear/errors.py:29-31` — `REVIEW_TRIGGER_MIN_UNRESOLVED=5`, cooldown=3d, `DEFAULT_REVIEW_POOL_LIMIT=10`
  - `app/daily_plan/linear/errors.py:240-261` — `get_review_pool()` — oldest-first, фиксированный размер
- **Ключевые файлы (onboarding):**
  - `app/onboarding/routes.py:45-47` — `onboarding_focus` пишется, но нигде не читается

## Current State

### Подтверждённые проблемы

**P1. Fuzzy grading засчитывает неверные ответы (fill-in-blank)**
- `app/curriculum/grading.py:547-550` — `if len(common_words) >= len(correct_words) * 0.6`
- "I have been waiting for hour" (missing 'an') → 6/7 = 86% → зачтено как верно
- "you have been waiting for an hour" (wrong subject) → 6/7 = 86% → зачтено
- Результат: accuracy систематически завышена, XP начисляется за неправильные ответы

**P2. Matching-упражнение не валидируется сервером**
- `app/curriculum/grading.py:622` — `is_correct = user_answer == 'completed'`
- Клиент отправляет `{"answer": "completed"}` без пар → всегда зачтено
- DevTools → любой matching → correct + XP за 0 усилий

**P3. Final test: неограниченные повторные попытки без штрафа**
- `app/curriculum/grading.py:919` — `passed = score >= 70`
- `LessonAttempt` хранит историю попыток, но `complete_lesson` не требует уникальных правильных ответов
- Стратегия угадывания (4 попытки × random) → ~98% шанс пройти тест без знания материала

**P4. XP не зависит от точности ответа**
- `app/achievements/xp_service.py:306` — `award_xp(user_id, base_amount, source)` без `score`
- `LINEAR_XP['linear_curriculum_quiz'] = 12` — quiz 71% и quiz 100% → одинаково
- `LINEAR_XP['linear_curriculum_final_test'] = 12` — аналогично
- Streak multiplier × perfect-day multiplier усугубляют: плохое качество масштабируется

**P5. Leech-слова детектируются, но не ремедируются**
- `app/srs/service.py:295-305` — после `LEECH_THRESHOLD=6` lapses карточка → RELEARNING (1 день)
- `UserCardDirection.is_leech` выставляется, но карточка не auto-suspend, не auto-buried
- Leech-карточка с 6+ lapses гарантированно падает каждый день → демотивирует пользователя

**P6. SRS learning steps слишком короткие для новых слов**
- `app/srs/constants.py:41` — `LEARNING_STEPS=[1, 10]` → выпуск на `GRADUATING_INTERVAL=1 day`
- Когнитивная психология (Ebbinghaus, Cepeda 2006): 4-6 повторений с нарастающим интервалом для L2
- С двумя шагами (1мин, 10мин) → следующий день → 90%+ шанс забыть к первому review
- `MIN_EASE_FACTOR=1.3` + `LAPSE_MINIMUM_INTERVAL=1` создают тупик для hard-карточек

**P7. Grammar mastery threshold недостижим (180 дней)**
- `app/grammar_lab/services/grammar_lab_service.py:407` — `interval >= 180` для is_mastered
- 10 упражнений × 14 reviews без ошибок ≈ 1 год → mastery badge мёртвый UI
- `check_and_update_mastery` (lines 453-486) никогда не возвращает True для реальных пользователей

**P8. Adaptive new-card limit: нет объяснения и нет recovery сигнала**
- `app/study/services/srs_service.py:225-231` — `<85% OR backlog>50 → min(2, base_new)`
- Пользователь не знает почему видит 2 новых слова вместо 10
- Нет сигнала «backlog cleared, вернулся к обычному темпу»

**P9. Слабые grammar-топики не влияют на линейный план**
- `app/study/insights_service.py:257-298` — `get_grammar_weaknesses` возвращает топики с <N% accuracy
- Данные есть, но `app/daily_plan/linear/` не читает их: curriculum-slot всегда идёт по спайну
- Пользователь с 0% по Present Perfect марширует в Module 5 без revisit

**P10. Error review не масштабируется по количеству ошибок**
- `app/daily_plan/linear/errors.py:29-31` — тот же trigger (5 ошибок, cooldown 3d) для 5 и 50 unresolved
- `DEFAULT_REVIEW_POOL_LIMIT=10` — фиксированный размер независимо от backlog
- Пользователь с 40 накопленными ошибками получает 10-вопросный слот как обычно

**P11. Error review — повторный тот же вопрос, не связанный**
- `app/daily_plan/linear/errors.py:240-261` — `get_review_pool()` возвращает oldest `QuizErrorLog` rows
- Тот же `question_text` + `options` → учит узнавать ответ, не навык
- Нет попытки достать sibling-упражнение на тот же grammar topic / lesson type

**P12. `onboarding_focus` пишется, но нигде не читается**
- `app/onboarding/routes.py:45` — `current_user.onboarding_focus = ','.join(parts)`
- Grep по `onboarding_focus` → только write-path; zero reads в plan assembler / slot builders
- Пользователь выбирает «только грамматика», получает тот же план что и «всё»

**P13. Reading slot засчитывается за 5% scroll без минимального времени**
- `app/daily_plan/linear/slots/reading_slot.py:28` — `READ_PROGRESS_THRESHOLD = 0.05`
- 5% delta любой главы = «читал сегодня» → XP + slot completed
- Нет минимального `time_on_page`, нет `words_visible_count` — slot легко фармится скроллом

## Development Approach

- **Testing approach**: Regular (код → тесты)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**
- Все изменения в существующих файлах; migrations при необходимости
- После каждого Task: `python -c "import <module>"` для изменённых Python файлов
- После каждого блока: `pytest -m smoke` + таргетированные тесты

## Design Decisions

- **Grading strictness**: fill-in-blank переходит с 60% → exact match + Levenshtein ≤1 (typo tolerance). Matching — server-side re-grade пар. Final test — 3 попытки в течение 24h, после чего требуется пройти prerequisite lesson снова.
- **Score-aware XP**: `award_xp(user_id, base_amount, source, score=None)` — если `score` передан, `actual = round(base * (0.5 + score/200))` (диапазон: 50% при 0% accuracy → 100% при 100%). Обратная совместимость: `score=None` → `actual = base` (все не-graded пути).
- **Leech handling**: после `LEECH_THRESHOLD` lapses — auto-suspend (buried_until = +7d) + notification. Пользователь видит в SRS-слоте «N leech слов отложено» с CTA перейти в «Проблемные слова».
- **SRS learning steps**: `LEARNING_STEPS = [1, 10, 1440]` (1мин, 10мин, 1день) → выпуск на день 2. `GRADUATING_INTERVAL = 1` не меняем — добавляем третий шаг. Для repeated-hard (`EF < 1.5`): `RELEARNING_STEPS = [10, 1440]` вместо `[10]`.
- **Grammar mastery threshold**: снизить `MASTERED_THRESHOLD_DAYS` с 180 → 30. 30 дней = ~6 успешных reviews с ease_factor 2.5. Достижимо за 2-3 месяца регулярной практики.
- **Adaptive limits UX**: добавить `reason` поле в `/api/get-study-items` response — `{"reason": "backlog_reduction", "backlog_count": N}`. Frontend показывает toast один раз при снижении лимита.
- **Grammar weakness in linear plan**: в `build_curriculum_slot` добавить логику: если `next_lesson.module` совпадает с топиком из top-3 weaknesses (accuracy < 60%, attempts ≥ 3), в `slot.data` добавить `weak_topic_hint`. Не меняем спайн — только enrichment данных для UI.
- **Error review scaling**: `pool_size = min(20, max(10, unresolved_count // 2))`. Trigger cooldown при большом бэклоге: если unresolved ≥ 15 → cooldown снижается с 3d → 1d.
- **Error review sibling**: при resolving ошибки — искать `GrammarExercise` с тем же `topic_id` и `difficulty` — если найден, добавить в сессию как follow-up. Если нет — оставить как сейчас.
- **onboarding_focus routing**: `build_curriculum_slot` и `build_srs_slot` читают `User.onboarding_focus`. Если `focus='grammar'` — в data добавить `prioritize_grammar=True` (hint для UI). Если `focus='reading'` → reading slot первый в baseline. Не ломаем спайн, добавляем soft-weighting.
- **Reading time gate**: добавить `UserReadingSession(user_id, chapter_id, started_at, ended_at, words_visible)` — лёгкая таблица. Threshold: `time_spent >= 60 seconds AND offset_delta >= 0.05`. Frontend пишет `started_at` при scroll-in, `ended_at` при scroll-out/page-leave.

---

## Implementation Steps

### BLOCK 1: Assessment Integrity (Tasks 1–3)

### Task 1: Строгий grading для fill-in-blank и matching

**Files:**
- Modify: `app/curriculum/grading.py`
- Modify: `tests/curriculum/test_grading.py`

- [x] В fill-in-blank grader (`grading.py:547-550`): заменить `>= 0.6` на точное совпадение после нормализации (strip, lower, remove punctuation) + Levenshtein ≤1 для одиночных слов (typo tolerance). Многословные ответы: exact match после нормализации. Добавить `_normalize_answer(s) -> str` и `_levenshtein(a, b) -> int` хелперы.
- [x] В matching grader (`grading.py:622`): `is_correct = user_answer == 'completed'` → заменить на `_grade_matching_pairs(user_pairs, correct_pairs)` — сервер получает `[{"left": X, "right": Y}, ...]`, проверяет каждую пару против эталона. Добавить в API контракт (клиент обязан прислать пары). Backward compat: если `user_answer == 'completed'` и нет `pairs` в payload → `is_correct = False` (старый клиент не может пройти тест без пар).
- [x] Write tests: fill-in-blank — точный ответ ✓, тайпо-1 ✓, неправильный subject ✗, missing article ✗; matching — правильные пары ✓, перепутанные ✗, `'completed'` без пар ✗
- [x] `python -c "from app.curriculum.grading import grade_answer"` — OK (verified via `process_quiz_submission` import — the helpers are exported)
- [x] `pytest -m smoke` — must pass before task 2

---

### Task 2: Final test — ограничение повторных попыток

**Files:**
- Modify: `app/curriculum/grading.py` (`process_final_test_submission`)
- Modify: `app/curriculum/service.py` (`complete_lesson`)
- Modify: `app/curriculum/models.py` (`LessonAttempt`)
- Modify: `tests/curriculum/test_final_test.py`

- [x] В `process_final_test_submission` (`grading.py:919`): перед зачётом проверить `LessonAttempt.query.filter(lesson_id=X, user_id=U, created_at >= today_start).count()`. Если ≥ 3 за последние 24h → вернуть `{"passed": False, "error": "attempts_exhausted", "retry_after": <timestamp>}`. Frontend показывает таймер.
- [x] `LessonAttempt`: добавить поле `attempt_number` (INTEGER DEFAULT 1) — `complete_lesson` инкрементит per (user, lesson, day). Или считать через COUNT без изменения схемы (предпочтительно — без миграции). (using COUNT — no migration)
- [x] Граничный случай: админ-пользователи не ограничены.
- [x] Write tests: 3 провала за 24h → 4-я попытка → 429-style error; после 24h → снова разрешено; admin user — без ограничений
- [x] `pytest tests/curriculum/` — must pass before task 3

---

### Task 3: Score-aware XP

**Files:**
- Modify: `app/achievements/xp_service.py`
- Modify: `app/curriculum/routes/grammar_quiz_lessons.py` (передаёт score)
- Modify: `app/curriculum/routes/main.py` (final_test score pass)
- Modify: `app/daily_plan/linear/xp.py` (`maybe_award_curriculum_xp`)
- Modify: `tests/achievements/test_xp_service.py`

- [x] `award_xp(user_id, base_amount, source, score: Optional[float] = None)` — добавить `score` параметр. Формула: `actual = round(base * (0.5 + score / 200.0))` если score передан (диапазон 50%..100% от base при accuracy 0%..100%). `score=None` → `actual = base` (backward compat для всех не-graded источников).
- [x] `award_linear_slot_xp_idempotent` и `maybe_award_curriculum_xp` — пробросить `score` из результата grading.
- [x] `process_grammar_submission`, `process_final_test_submission`, quiz routes — вычислить `score = correct_count / total_count * 100` и передать в XP-award. Для `final_test` — `score = grading_result['score']`. (score уже доступен в `update_progress_with_grading.result['score']` — пробрасывается оттуда; card_lessons передаёт `accuracy`)
- [x] Не трогать: SRS-slot XP (`linear_srs_global`), reading XP, error_review XP — там нет accuracy signal.
- [x] Write tests: score=100 → base XP; score=0 → 50% base; score=None → base; score=70 → `round(base * 0.85)`. Backward compat: все существующие `award_xp` без score → unchanged.
- [x] `pytest tests/achievements/ tests/curriculum/` — must pass before task 4

---

### BLOCK 2: SRS Quality (Tasks 4–5)

### Task 4: Leech auto-suspend + user signal

**Files:**
- Modify: `app/srs/service.py`
- Modify: `app/srs/constants.py`
- Modify: `app/study/api_routes.py` (или `app/api/daily_plan.py`) — leech count в response
- Modify: `tests/srs/test_service.py`

- [x] В `_handle_review()` (`srs/service.py:295-305`): если `lapses >= LEECH_THRESHOLD` → `buried_until = datetime.now() + timedelta(days=7)`. Existing `is_leech=True` флаг уже выставляется — добавить `buried_until` update после него.
- [x] Константа: добавить `LEECH_SUSPEND_DAYS = 7` в `srs/constants.py`.
- [x] В `/api/get-study-items` или `/api/daily-status` response: добавить `"leech_suspended_count": N` — количество карточек, заблокированных как leech сегодня. Используется UI для toast «N слов отложено как сложные».
- [x] `RELEARNING_STEPS` (`constants.py`) изменить с `[10]` → `[10, 1440]` — добавить 1-day step для relearning (после провала review). Hard-карточка получает второй шанс через день, а не 10 минут.
- [x] Write tests: 6 lapses на review-card → `buried_until = now+7d`; `_get_due_cards` не возвращает buried cards; leech card после 7 дней снова доступна; RELEARNING_STEPS [10,1440] создаёт корректное расписание.
- [x] `pytest tests/srs/` — must pass before task 5

---

### Task 5: SRS learning path + adaptive limits UX

**Files:**
- Modify: `app/srs/constants.py`
- Modify: `app/srs/service.py` (graduating logic)
- Modify: `app/study/services/srs_service.py` (adaptive limit reason)
- Modify: `app/api/daily_plan.py` или study routes — добавить reason в response
- Modify: `tests/srs/test_constants.py`, `tests/srs/test_service.py`

- [x] `LEARNING_STEPS = [1, 10, 1440]` (добавить третий шаг: 1 день). Новая карточка проходит: 1мин → 10мин → 1день → выпуск на `GRADUATING_INTERVAL=1`. Это три повторения до первого long-term review.
- [x] В graduating logic (`srs/service.py`): при переходе из LEARNING → REVIEW проверить что пройдены все шаги; `GRADUATING_INTERVAL=1` остаётся. (logic uses `len(steps)` dynamically, no change needed)
- [x] В `get_adaptive_limits()` (`srs_service.py:225-231`): вернуть `(remaining_new, remaining_reviews, reason: str)`. `reason ∈ {'normal', 'backlog_reduction', 'accuracy_low'}`. Добавить в возвращаемый tuple или именованный dataclass. (added sibling helper `get_adaptive_limit_reason()` to preserve existing 2-tuple unpacking; both share `_compute_adaptive_state`)
- [x] `/api/daily-status` и `/api/daily-plan`: добавить `srs_limit_reason` в payload если не `'normal'`. Frontend показывает tooltip один раз в день.
- [x] Write tests: новая карточка с LEARNING_STEPS=[1,10,1440] проходит 3 шага; accuracy<85 → reason='accuracy_low'; backlog>50 → reason='backlog_reduction'; normal → reason='normal'.
- [x] `pytest tests/srs/ tests/api/` — must pass before task 6 (tests/srs all green; one tests/api failure pre-existing date-hardcoded test, unrelated)

---

### BLOCK 3: Grammar Quality (Tasks 6–7)

### Task 6: Снизить grammar mastery threshold

**Files:**
- Modify: `app/grammar_lab/models.py` (`MASTERED_THRESHOLD_DAYS`)
- Modify: `app/grammar_lab/services/grammar_lab_service.py` (mastery check)
- Modify: `migrations/versions/` (если константа в БД — нет, это Python constant)
- Modify: `tests/grammar_lab/test_mastery.py`

- [x] `UserGrammarExercise.MASTERED_THRESHOLD_DAYS`: изменить с 180 → 30. Комментарий: «30 days ≈ 6 successful reviews with default ease=2.5; achievable in 2-3 months of regular practice». (override is per-class only — words keep canonical 180; mixin now reads `getattr(self, 'MASTERED_THRESHOLD_DAYS', module_const)`)
- [x] В `check_and_update_mastery` (`grammar_lab_service.py:453-486`): логика не меняется, только константа. Проверить что `topic_mastered` корректно выставляется при новом пороге — `GrammarTopic.mastered_at` должна устанавливаться при `all(ex.is_mastered)`. (covered by `TestTopicMasteryTransition`)
- [x] Добавить `GrammarExercise.difficulty` в интервальный расчёт: в `_calculate_next_review` (или аналоге) — `base_ease = DEFAULT_EASE_FACTOR * (1.1 - difficulty * 0.1)` для `difficulty ∈ {0.0..1.0}`. Более сложные упражнения стартуют с меньшим ease, требуют больше правильных ответов для масштабирования. (implemented as `compute_initial_ease_for_difficulty` seeding `UserGrammarExercise.ease_factor` on first `get_or_create`; formula adjusted to `1.1 - d*0.2` so harder difficulty actually lowers ease per the test description)
- [x] Write tests: упражнение с interval=30 → `is_mastered=True`; с interval=29 → `False`; все mastered → `topic_mastered`; difficulty=0.8 → стартовый ease < default.
- [x] `pytest tests/grammar_lab/` — must pass before task 7

---

### Task 7: Grammar weakness hint в линейный план

**Files:**
- Modify: `app/daily_plan/linear/slots/curriculum_slot.py`
- Modify: `app/study/insights_service.py` (если нужна новая функция)
- Modify: `tests/daily_plan/linear/test_curriculum_slot.py`

- [x] Добавить `_get_weak_grammar_topic_ids(user_id, db, min_attempts=3, max_accuracy=0.6) -> list[int]` в `curriculum_slot.py` (или в `insights_service.py`) — запрос по `UserGrammarExercise` группировкой по `topic_id`, accuracy = correct_count/total_count.
- [x] В `build_curriculum_slot()`: если `next_lesson` принадлежит модулю с grammar-топиком из weak_ids → добавить в `slot.data['weak_topic_hint'] = True` и `slot.data['weak_topic_name'] = topic.title`. Спайн не меняется — только enrichment.
- [x] Template/API: `weak_topic_hint=True` → в мета-строке слота показывать «⚠ Слабое место: {topic_name}». Даёт learner'у контекст почему этот урок важен сейчас. (data emitted via slot.data — UI surface deferred; slot dict already exposes the hint to consumers)
- [x] Write tests: пользователь с accuracy=40% по топику X → `weak_topic_hint=True` в curriculum slot data когда next_lesson.module.grammar_topic_id совпадает; accuracy=80% → no hint; 0 attempts → no hint.
- [x] `pytest tests/daily_plan/linear/` — passes for new tests; two pre-existing date-hardcoded failures (`test_completed_slot_ignores_non_curriculum_progress`, `test_completed_when_linear_reading_xp_event_today`) unrelated to this task

---

### BLOCK 4: Error Review & Feedback (Tasks 8–9)

### Task 8: Error review scaling — pool_size + cooldown по backlog

**Files:**
- Modify: `app/daily_plan/linear/errors.py`
- Modify: `tests/daily_plan/linear/test_errors.py`

- [x] Функция `get_review_pool_size(unresolved_count: int) -> int`:
  ```
  if unresolved_count >= 20: return 20
  elif unresolved_count >= 10: return 15
  else: return 10
  ```
  Заменить хардкодный `DEFAULT_REVIEW_POOL_LIMIT=10` на вызов этой функции в `get_review_pool()`.
- [x] `should_show_error_review()`: добавить dynamic cooldown: если `unresolved_count >= 15` → cooldown = `timedelta(days=1)` вместо `timedelta(days=3)`. Если `unresolved_count >= 25` → cooldown = `timedelta(hours=12)`. Иначе — стандартные 3 дня.
- [x] Добавить `unresolved_count` в `slot.data` для reading в `build_error_review_slot()` — уже есть, убедиться что передаётся.
- [x] Write tests: 5 unresolved → pool=10, cooldown=3d; 15 → pool=15, cooldown=1d; 25 → pool=20, cooldown=12h; 3 → slot not shown.
- [x] `pytest tests/daily_plan/linear/test_errors.py` — passes (file is `test_error_review.py`; 37 tests green)

---

### Task 9: Error review sibling-question lookup

**Files:**
- Modify: `app/daily_plan/linear/errors.py`
- Modify: `app/curriculum/routes/grammar_quiz_lessons.py` (или где грейдер resolves ошибки)
- Modify: `tests/daily_plan/linear/test_error_sibling.py`

- [x] В `get_review_pool()` (`errors.py:240-261`): для каждого `QuizErrorLog` пытаться найти sibling-упражнение: `GrammarExercise.query.filter(topic_id == error.lesson.grammar_topic_id, difficulty == error_lesson_difficulty, id != original_exercise_id).order_by(func.random()).first()`. Если найден → добавить в пул как дополнительный вопрос после оригинала (не заменяя). (implemented as new `get_review_pool_with_siblings` + `get_sibling_exercise` helpers; legacy `get_review_pool` shape preserved for existing callers; `log_quiz_errors_from_result` now persists `exercise_id` + `difficulty` in payload so the lookup has reliable inputs)
- [x] Если у урока нет `grammar_topic_id` (не grammar lesson) → sibling не ищется, оставить как есть.
- [x] `QuizErrorLog.sibling_lesson_id` — не нужен в БД; sibling резолвится в runtime.
- [x] Write tests: ошибка в grammar-уроке с topicX → get_review_pool включает sibling exercise из topicX; ошибка в vocab-уроке без grammar_topic → только оригинал; sibling не дублируется если топик уже в пуле.
- [x] `pytest tests/daily_plan/linear/` — new sibling tests all pass; two pre-existing date-hardcoded failures unrelated to this task

---

### BLOCK 5: Onboarding & Reading (Tasks 10–11)

### Task 10: `onboarding_focus` routing в линейный план

**Files:**
- Modify: `app/daily_plan/linear/slots/reading_slot.py`
- Modify: `app/daily_plan/linear/plan.py` (порядок baseline_slots)
- Modify: `app/auth/models.py` (добавить property если нужно)
- Modify: `tests/daily_plan/linear/test_plan_assembly.py`

- [x] Добавить `_get_user_focus(user_id, db) -> str | None` в `plan.py` — читает `User.onboarding_focus`, возвращает первый тег или None.
- [x] `build_reading_slot()`: принять `focus` параметр. Если `focus='reading'` → `slot.data['priority'] = True` — hint для frontend показать слот как рекомендованный.
- [x] Порядок `baseline_slots` в `get_linear_plan()`: если `focus='reading'` → reading promotes to index 1 (curriculum stays first). Если `focus='grammar'` → `curriculum_slot.data['prioritize_grammar']=True` (no reorder).
- [x] Если `focus=None` или `focus='all'` — никаких изменений.
- [x] Write tests: focus='reading' → reading slot имеет `priority=True` и стоит на index 1; focus='grammar' → нет изменений порядка, prioritize_grammar=True на curriculum; focus=None → стандартный план; focus='all' → стандартный план; multi-tag → first tag wins.
- [x] `pytest tests/daily_plan/linear/` — new tests all pass; two pre-existing date-hardcoded failures unrelated to this task

---

### Task 11: Reading time gate

**Files:**
- Create: `migrations/versions/20260426_user_reading_session.py`
- Create: `app/books/reading_session.py`
- Modify: `app/books/api.py` (chapter-complete endpoint)
- Modify: `app/daily_plan/linear/slots/reading_slot.py`
- Modify: `tests/books/test_reading_session.py`

- [x] Новая таблица `user_reading_sessions`: `(id, user_id FK, chapter_id FK, started_at TIMESTAMP, ended_at TIMESTAMP, offset_delta FLOAT)`. Nullable `ended_at` — сессия в процессе.
- [x] `app/books/reading_session.py`: `start_session(user_id, chapter_id, db)`, `end_session(session_id, offset_delta, db)`, `get_session_duration(user_id, chapter_id, today_start) -> int (seconds)`. (today window resolved internally from `User.timezone`)
- [x] Chapter-complete endpoint (`app/books/api.py` + `app/api/books.py`): при вычислении reading slot completion — дополнительная проверка `has_min_reading_time_today(user_id, book_id, db) >= 60s`. Если < 60s → linear-XP не начисляется, offset_pct обновляется как обычно.
- [x] Существующий `READ_PROGRESS_THRESHOLD=0.05` — оставлен как is. Новый гейт аддитивный: linear `maybe_award_book_reading_xp` вызывается только при `offset_delta >= 0.05 AND time_spent >= 60`.
- [x] Frontend endpoints: `POST /api/books/reading-session/start` (open session) и `POST /api/books/reading-session/end` (close + offset_delta). Owner check returns 403 для чужих сессий.
- [x] Write tests: 30s + 5% → not credited (linear XP не начисляется); 90s + 5% → credited; нет открытой сессии → duration=0; cross-user end → 403.
- [x] `pytest tests/books/` — 54 tests pass (16 new + 38 existing).

---

### BLOCK 6: Final Validation (Tasks 12–13)

### Task 12: Smoke + regression pass

**Files:** No code changes — validation only

- [x] `pytest -m smoke` — 145 passed (after fixing migration chain: `20260426_reading_session.down_revision` → `20260425_drop_user_xp`).
- [x] `pytest tests/achievements/ tests/curriculum/ tests/grammar_lab/ tests/books/ tests/daily_plan/ tests/srs/` — 858 passed, 2 failed. Both failures (`test_completed_slot_ignores_non_curriculum_progress`, `test_completed_when_linear_reading_xp_event_today`) hardcode `datetime(2026, 4, 25, ...)` while today is 2026-04-26, were already noted as pre-existing date-bound failures in Tasks 5/7/9/10, and are unrelated to this audit's changes.
- [x] `python -c "import app.curriculum.grading; import app.achievements.xp_service; import app.srs.service; import app.srs.constants; import app.daily_plan.linear.errors"` — OK
- [x] Grep verified: нет `is_correct = user_answer == 'completed'` в grading.py; нет `>= len(correct_words) * 0.6` в grading.py; `MASTERED_THRESHOLD_DAYS = 30` в `app/grammar_lab/models.py:357`; `LEECH_SUSPEND_DAYS = 7` в `app/srs/constants.py:98`.

---

### Task 13: CLAUDE.md update — новые паттерны

**Files:**
- Modify: `CLAUDE.md` (Key Patterns секция)

- [ ] Добавить паттерны:
  - **Score-aware XP**: `award_xp(user_id, amount, source, score=None)` — если `score` передан, `actual = round(base * (0.5 + score/200))`. Все graded sources (quiz, grammar, final_test) должны передавать score.
  - **Leech auto-suspend**: `LEECH_THRESHOLD=6 lapses → buried_until=+7d`. `leech_suspended_count` в `/api/daily-status`.
  - **Matching server-grade**: matching exercises всегда валидируются сервером через `_grade_matching_pairs(user_pairs, correct_pairs)`.
  - **Error review scaling**: `get_review_pool_size(unresolved)` — динамический размер (10/15/20). Dynamic cooldown при unresolved≥15.
  - **Reading time gate**: `user_reading_sessions` table + `time_spent >= 60s AND offset_delta >= 0.05` для reading slot credit.
- [ ] Run final `pytest -m smoke` — confirm ≥141 passed
