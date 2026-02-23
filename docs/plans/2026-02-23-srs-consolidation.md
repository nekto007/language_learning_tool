# SRS Stats Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate 8 duplicated SRS state-counting implementations by introducing SRSFieldsMixin + unified count_srs_states utility + consolidated SRSStatsService.

**Architecture:** A mixin provides classify()/is_due/is_mastered on both UserCardDirection and UserGrammarExercise. A pure function `count_srs_states()` replaces all inline counting loops. SRSStatsService becomes the single entry point for all SRS statistics, with methods moved from GrammarSRS and StatsService.

**Tech Stack:** Python 3, Flask, SQLAlchemy (no migrations needed — same columns, just shared via mixin)

---

### Task 1: Create SRSFieldsMixin

**Files:**
- Create: `app/srs/mixins.py`
- Test: `tests/test_srs_mixins.py`

**Step 1: Write tests for classify(), is_due, is_mastered**

```python
# tests/test_srs_mixins.py
"""Tests for SRSFieldsMixin."""
import pytest
from datetime import datetime, timezone, timedelta
from app.srs.mixins import SRSFieldsMixin


class FakeSRSItem(SRSFieldsMixin):
    """Fake model for testing mixin methods."""
    def __init__(self, state='new', interval=0, next_review=None,
                 correct_count=0, incorrect_count=0):
        self.state = state
        self.interval = interval
        self.next_review = next_review
        self.correct_count = correct_count
        self.incorrect_count = incorrect_count


class TestClassify:
    def test_new_state(self):
        item = FakeSRSItem(state='new')
        assert item.classify() == 'new'

    def test_none_state(self):
        item = FakeSRSItem(state=None)
        assert item.classify() == 'new'

    def test_learning_state(self):
        item = FakeSRSItem(state='learning')
        assert item.classify() == 'learning'

    def test_relearning_state(self):
        item = FakeSRSItem(state='relearning')
        assert item.classify() == 'learning'

    def test_review_not_mastered(self):
        item = FakeSRSItem(state='review', interval=30)
        assert item.classify() == 'review'

    def test_review_mastered(self):
        item = FakeSRSItem(state='review', interval=180)
        assert item.classify() == 'mastered'

    def test_review_mastered_above_threshold(self):
        item = FakeSRSItem(state='review', interval=365)
        assert item.classify() == 'mastered'

    def test_review_zero_interval(self):
        item = FakeSRSItem(state='review', interval=0)
        assert item.classify() == 'review'

    def test_review_none_interval(self):
        item = FakeSRSItem(state='review', interval=None)
        assert item.classify() == 'review'


class TestIsDue:
    def test_new_is_always_due(self):
        item = FakeSRSItem(state='new')
        assert item.is_due is True

    def test_past_review_is_due(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        item = FakeSRSItem(state='review', next_review=past)
        assert item.is_due is True

    def test_future_review_not_due(self):
        future = datetime.now(timezone.utc) + timedelta(days=1)
        item = FakeSRSItem(state='review', next_review=future)
        assert item.is_due is False

    def test_none_next_review_is_due(self):
        item = FakeSRSItem(state='review', next_review=None)
        assert item.is_due is True


class TestIsMastered:
    def test_review_above_threshold(self):
        item = FakeSRSItem(state='review', interval=180)
        assert item.is_mastered is True

    def test_review_below_threshold(self):
        item = FakeSRSItem(state='review', interval=30)
        assert item.is_mastered is False

    def test_learning_never_mastered(self):
        item = FakeSRSItem(state='learning', interval=200)
        assert item.is_mastered is False
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_srs_mixins.py -v`
Expected: FAIL (ImportError — module doesn't exist yet)

**Step 3: Write SRSFieldsMixin implementation**

```python
# app/srs/mixins.py
"""
SRS Fields Mixin — shared SRS behavior for UserCardDirection and UserGrammarExercise.

Both models have 100% identical SRS fields. This mixin provides shared
classification logic so state-counting code exists in one place.
"""
from datetime import datetime, timezone

from app.srs.constants import MASTERED_THRESHOLD_DAYS, MATURE_THRESHOLD_DAYS


class SRSFieldsMixin:
    """
    Mixin providing SRS classification methods.

    Expects the consuming model to have these columns:
        state, interval, next_review, correct_count, incorrect_count
    """

    def classify(self) -> str:
        """
        Classify this SRS item into a display category.

        Returns one of: 'new', 'learning', 'review', 'mastered'
        """
        state = self.state or 'new'
        if state == 'new':
            return 'new'
        if state in ('learning', 'relearning'):
            return 'learning'
        if state == 'review':
            if self.interval and self.interval >= MASTERED_THRESHOLD_DAYS:
                return 'mastered'
            return 'review'
        return 'new'

    @property
    def is_due(self) -> bool:
        """Check if this item is due for review."""
        state = self.state or 'new'
        if state == 'new':
            return True
        if not self.next_review:
            return True
        nr = self.next_review
        if nr.tzinfo is None:
            nr = nr.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= nr

    @property
    def is_mastered(self) -> bool:
        """Check if this item has reached mastered threshold."""
        return (self.state == 'review'
                and self.interval is not None
                and self.interval >= MASTERED_THRESHOLD_DAYS)

    @property
    def accuracy(self) -> float:
        """Calculate accuracy percentage."""
        total = (self.correct_count or 0) + (self.incorrect_count or 0)
        if total == 0:
            return 0.0
        return round((self.correct_count or 0) / total * 100, 1)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_srs_mixins.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add app/srs/mixins.py tests/test_srs_mixins.py
git commit -m "feat(srs): SRSFieldsMixin с classify/is_due/is_mastered"
```

---

### Task 2: Create count_srs_states utility

**Files:**
- Create: `app/srs/utils.py`
- Test: `tests/test_srs_utils.py`

**Step 1: Write tests for count_srs_states**

```python
# tests/test_srs_utils.py
"""Tests for SRS utility functions."""
import pytest
from datetime import datetime, timezone, timedelta
from app.srs.mixins import SRSFieldsMixin
from app.srs.utils import count_srs_states, count_srs_states_with_accuracy


class FakeSRSItem(SRSFieldsMixin):
    def __init__(self, state='new', interval=0, next_review=None,
                 correct_count=0, incorrect_count=0):
        self.state = state
        self.interval = interval
        self.next_review = next_review
        self.correct_count = correct_count
        self.incorrect_count = incorrect_count


class TestCountSrsStates:
    def test_empty_list(self):
        result = count_srs_states([])
        assert result == {
            'new_count': 0, 'learning_count': 0,
            'review_count': 0, 'mastered_count': 0,
            'total': 0, 'due_today': 0,
        }

    def test_all_new(self):
        items = [FakeSRSItem(state='new') for _ in range(3)]
        result = count_srs_states(items)
        assert result['new_count'] == 3
        assert result['due_today'] == 3
        assert result['total'] == 3

    def test_mixed_states(self):
        now = datetime.now(timezone.utc)
        items = [
            FakeSRSItem(state='new'),
            FakeSRSItem(state='learning', next_review=now - timedelta(hours=1)),
            FakeSRSItem(state='review', interval=30, next_review=now - timedelta(hours=1)),
            FakeSRSItem(state='review', interval=200, next_review=now + timedelta(days=5)),
            FakeSRSItem(state='relearning', next_review=now + timedelta(hours=1)),
        ]
        result = count_srs_states(items)
        assert result['new_count'] == 1
        assert result['learning_count'] == 2  # learning + relearning
        assert result['review_count'] == 1
        assert result['mastered_count'] == 1
        assert result['total'] == 5
        assert result['due_today'] == 3  # new + learning(past) + review(past)

    def test_none_state_counted_as_new(self):
        items = [FakeSRSItem(state=None)]
        result = count_srs_states(items)
        assert result['new_count'] == 1


class TestCountSrsStatesWithAccuracy:
    def test_accuracy_calculation(self):
        items = [
            FakeSRSItem(state='review', interval=30, correct_count=8, incorrect_count=2),
            FakeSRSItem(state='review', interval=30, correct_count=10, incorrect_count=0),
        ]
        result = count_srs_states_with_accuracy(items)
        assert result['accuracy'] == 90.0  # 18/20

    def test_zero_attempts(self):
        items = [FakeSRSItem(state='new')]
        result = count_srs_states_with_accuracy(items)
        assert result['accuracy'] == 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_srs_utils.py -v`
Expected: FAIL (ImportError)

**Step 3: Write count_srs_states implementation**

```python
# app/srs/utils.py
"""
SRS utility functions — the single source of truth for state counting.

All services that need SRS state breakdowns should call these functions
instead of implementing their own counting loops.
"""
from datetime import datetime, timezone
from typing import Dict, Iterable


def count_srs_states(records: Iterable, now: datetime = None) -> Dict[str, int]:
    """
    Count SRS items by category.

    Args:
        records: Iterable of objects with SRSFieldsMixin (classify(), is_due)
        now: Optional timestamp for due calculation (defaults to utcnow)

    Returns:
        Dict with new_count, learning_count, review_count, mastered_count, total, due_today
    """
    if now is None:
        now = datetime.now(timezone.utc)

    new_count = 0
    learning_count = 0
    review_count = 0
    mastered_count = 0
    due_today = 0

    for record in records:
        category = record.classify()
        if category == 'new':
            new_count += 1
            due_today += 1
        elif category == 'learning':
            learning_count += 1
            if record.is_due:
                due_today += 1
        elif category == 'review':
            review_count += 1
            if record.is_due:
                due_today += 1
        elif category == 'mastered':
            mastered_count += 1
            if record.is_due:
                due_today += 1

    return {
        'new_count': new_count,
        'learning_count': learning_count,
        'review_count': review_count,
        'mastered_count': mastered_count,
        'total': new_count + learning_count + review_count + mastered_count,
        'due_today': due_today,
    }


def count_srs_states_with_accuracy(records: Iterable, now: datetime = None) -> Dict:
    """
    Count SRS states and also compute overall accuracy.

    Returns:
        Dict with all count_srs_states keys + accuracy (float 0-100)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Materialize to iterate twice
    records_list = list(records)
    result = count_srs_states(records_list, now)

    total_correct = sum(getattr(r, 'correct_count', 0) or 0 for r in records_list)
    total_incorrect = sum(getattr(r, 'incorrect_count', 0) or 0 for r in records_list)
    total_attempts = total_correct + total_incorrect

    result['accuracy'] = round(total_correct / total_attempts * 100, 1) if total_attempts > 0 else 0

    return result
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_srs_utils.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add app/srs/utils.py tests/test_srs_utils.py
git commit -m "feat(srs): count_srs_states() — единая утилита подсчёта"
```

---

### Task 3: Adopt SRSFieldsMixin in models

**Files:**
- Modify: `app/study/models.py` — UserCardDirection (line 317)
- Modify: `app/grammar_lab/models.py` — UserGrammarExercise (line 307)

**Step 1: Add mixin to UserCardDirection**

In `app/study/models.py`, add import and mixin inheritance:

```python
# Add import at top
from app.srs.mixins import SRSFieldsMixin

# Change class definition (line 317):
class UserCardDirection(SRSFieldsMixin, db.Model):
```

Remove the existing `is_mastered` and `accuracy` properties from UserCardDirection if they exist (they don't currently, but UserGrammarExercise has them).

**Step 2: Add mixin to UserGrammarExercise**

In `app/grammar_lab/models.py`, add import and mixin inheritance:

```python
# Add import at top
from app.srs.mixins import SRSFieldsMixin

# Change class definition (line 307):
class UserGrammarExercise(SRSFieldsMixin, db.Model):
```

Remove the duplicated properties from UserGrammarExercise that are now in the mixin:
- Remove `is_due` property (lines 394-403) — provided by mixin
- Remove `is_mastered` property (lines 421-424) — provided by mixin
- Remove `accuracy` property (lines 426-432) — provided by mixin
- Keep `is_mature` (line 417-419) — only in this model, uses different threshold
- Keep `is_buried` — different from mixin, not in mixin scope

Also remove the class constants that are now in the mixin/constants:
- Remove `MATURE_THRESHOLD_DAYS = 21` (line 318)
- Remove `MASTERED_THRESHOLD_DAYS = 180` (line 319)

Note: UserWord also has MASTERED_THRESHOLD_DAYS (line 183). Keep it there since UserWord is not an SRS item (it doesn't have state/interval fields).

**Step 3: Verify both models compile**

Run: `python -c "from app.study.models import UserCardDirection; print('OK')"`
Run: `python -c "from app.grammar_lab.models import UserGrammarExercise; print('OK')"`

**Step 4: Run full test suite to verify no regressions**

Run: `pytest --tb=short -q`
Expected: Same 6 pre-existing failures, no new failures

**Step 5: Commit**

```bash
git add app/study/models.py app/grammar_lab/models.py
git commit -m "refactor: UserCardDirection и UserGrammarExercise наследуют SRSFieldsMixin"
```

---

### Task 4: Refactor SRSStatsService to use count_srs_states

**Files:**
- Modify: `app/srs/stats_service.py`

**Step 1: Refactor get_words_stats to use count_srs_states**

Replace the manual counting loop (lines 93-126) with a call to `count_srs_states()`. The query logic stays — only the counting changes.

```python
from app.srs.utils import count_srs_states, count_srs_states_with_accuracy

# In get_words_stats, after building base_query and fetching cards:
cards = base_query.all()
return count_srs_states(cards)
```

**Step 2: Refactor get_grammar_stats to use count_srs_states**

Replace manual counting loop (lines 176-207). Need to handle the case where exercises have no progress record (treat as 'new' SRS items).

Create a wrapper class or handle None progress:

```python
# For exercises without progress, create placeholder objects
class NewPlaceholder(SRSFieldsMixin):
    """Represents an exercise with no user progress (= new)."""
    state = 'new'
    interval = 0
    next_review = None
    correct_count = 0
    incorrect_count = 0

# Build list: progress records for started exercises + placeholders for new ones
items = []
for exercise_id in exercise_ids:
    progress = progress_map.get(exercise_id)
    if progress:
        items.append(progress)
    else:
        items.append(NewPlaceholder())

return count_srs_states(items)
```

**Step 3: Verify compilation and tests**

Run: `python -c "from app.srs.stats_service import SRSStatsService; print('OK')"`
Run: `pytest tests/test_unified_srs_grammar.py -v --tb=short`
Expected: PASS

**Step 4: Commit**

```bash
git add app/srs/stats_service.py
git commit -m "refactor: SRSStatsService использует count_srs_states()"
```

---

### Task 5: Move grammar stats methods to SRSStatsService

**Files:**
- Modify: `app/srs/stats_service.py` — add get_grammar_stats_batch, get_grammar_user_stats
- Modify: `app/grammar_lab/services/grammar_srs.py` — remove get_topic_stats, get_topics_stats_batch, get_user_stats
- Modify: `app/grammar_lab/services/grammar_lab_service.py` — update callers

**Step 1: Move get_topics_stats_batch to SRSStatsService**

Port `GrammarSRS.get_topics_stats_batch()` (grammar_srs.py:152-224) to `SRSStatsService.get_grammar_stats_batch()`, using `count_srs_states_with_accuracy()` instead of inline loop.

```python
# In SRSStatsService:
@staticmethod
def get_grammar_stats_batch(user_id: int, topic_ids: List[int]) -> Dict[int, Dict]:
    """Batch SRS stats for multiple grammar topics. 2 queries instead of 2*N."""
    if not topic_ids:
        return {}

    empty_stats = {
        'new_count': 0, 'learning_count': 0, 'review_count': 0,
        'mastered_count': 0, 'total': 0, 'due_today': 0, 'accuracy': 0,
    }

    exercises = GrammarExercise.query.filter(
        GrammarExercise.topic_id.in_(topic_ids)
    ).all()

    if not exercises:
        return {tid: dict(empty_stats) for tid in topic_ids}

    exercises_by_topic = {}
    all_exercise_ids = []
    for ex in exercises:
        exercises_by_topic.setdefault(ex.topic_id, []).append(ex.id)
        all_exercise_ids.append(ex.id)

    progress_records = UserGrammarExercise.query.filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.exercise_id.in_(all_exercise_ids)
    ).all()
    progress_map = {p.exercise_id: p for p in progress_records}

    result = {}
    for tid in topic_ids:
        ex_ids = exercises_by_topic.get(tid, [])
        if not ex_ids:
            result[tid] = dict(empty_stats)
            continue

        items = []
        for eid in ex_ids:
            progress = progress_map.get(eid)
            items.append(progress if progress else _NewPlaceholder())

        result[tid] = count_srs_states_with_accuracy(items)

    return result
```

**Step 2: Move get_user_stats to SRSStatsService**

Port `GrammarSRS.get_user_stats()` (grammar_srs.py:226-321) to `SRSStatsService.get_grammar_user_stats()`, using `count_srs_states_with_accuracy()` for the counting parts. Keep the domain-specific logic (topics_started, by_level) but delegate counting.

**Step 3: Remove from GrammarSRS**

Delete `get_topic_stats()`, `get_topics_stats_batch()`, `get_user_stats()` from `grammar_srs.py`. Keep only:
- `process_exercise_answer()` — SRS state machine delegation
- `get_or_create_topic_status()` — topic status CRUD
- `complete_theory()` — mark theory as done
- `add_xp()` — add XP to topic

**Step 4: Update grammar_lab_service.py callers**

Replace:
- `self.srs.get_topics_stats_batch(user_id, topic_ids)` → `srs_stats_service.get_grammar_stats_batch(user_id, topic_ids)` (line 129)
- `self.srs.get_topic_stats(user_id, topic_id)` → `srs_stats_service.get_grammar_stats(user_id, topic_id=topic_id)` (lines 236, 368)
- `self.srs.get_user_stats(user_id)` → `srs_stats_service.get_grammar_user_stats(user_id)` (line 489)

Note: The `accuracy` field was in grammar stats but not in the unified format. `count_srs_states_with_accuracy()` provides it. Ensure callers get the same dict keys.

**Step 5: Update get_levels_summary inline counting**

Replace inline mastered count in `grammar_lab_service.py:get_levels_summary()` (lines 198-203) with `SRSStatsService.get_grammar_stats(user_id, level=level)`.

**Step 6: Verify and test**

Run: `python -c "from app.grammar_lab.services.grammar_lab_service import GrammarLabService; print('OK')"`
Run: `pytest tests/test_grammar_lab_services.py -v --tb=short`
Run: `pytest tests/test_unified_srs_grammar.py -v --tb=short`
Expected: PASS (may need test updates for new call paths)

**Step 7: Commit**

```bash
git add app/srs/stats_service.py app/grammar_lab/services/grammar_srs.py app/grammar_lab/services/grammar_lab_service.py
git commit -m "refactor: перенос grammar stats из GrammarSRS в SRSStatsService"
```

---

### Task 6: Replace word stats duplication in StatsService and routes

**Files:**
- Modify: `app/study/services/stats_service.py` — replace get_user_word_stats
- Modify: `app/words/routes.py` — replace inline mastered count
- Modify: `app/study/routes.py` — replace SQL CASE with SRSStatsService call

**Step 1: Replace StatsService.get_user_word_stats**

Replace the method body (stats_service.py:73-108) to delegate to `SRSStatsService.get_words_stats()`:

```python
@staticmethod
def get_user_word_stats(user_id: int) -> Dict:
    """Get user's word learning statistics."""
    from app.srs.stats_service import srs_stats_service
    stats = srs_stats_service.get_words_stats(user_id)
    # Map to expected format (legacy callers expect 'new', not 'new_count')
    return {
        'new': stats['new_count'],
        'learning': stats['learning_count'],
        'review': stats['review_count'],
        'mastered': stats['mastered_count'],
        'total': stats['total'],
    }
```

**Step 2: Replace words/routes.py inline mastered count**

Replace lines 55-78 in `words/routes.py` (the status_counts + mastered_count queries) with:

```python
from app.srs.stats_service import srs_stats_service
stats = srs_stats_service.get_words_stats(current_user.id)
words_stats = {
    'new': stats['new_count'],
    'learning': stats['learning_count'],
    'review': stats['review_count'],
    'mastered': stats['mastered_count'],
}
words_total = stats['total']
words_in_progress = stats['learning_count'] + stats['review_count']
```

**Step 3: Replace study/routes.py SQL CASE**

Replace the SQL CASE block (study/routes.py:147-198) with a SRSStatsService call.

Add a new method `get_words_deck_stats_batch(user_id, deck_ids)` to SRSStatsService that returns per-deck stats efficiently. It should:
1. Load all UserCardDirection records for the user's words in any of the given decks
2. Group by deck_id
3. Call classify() on each and count

```python
# In study/routes.py, replace SQL CASE block:
if my_decks:
    deck_ids = [d.id for d in my_decks]
    deck_stats = srs_stats_service.get_words_deck_stats_batch(current_user.id, deck_ids)
    # Convert to template format
    for deck_id, stats in deck_stats.items():
        deck_stats[deck_id] = {
            'new': stats['new_count'],
            'learning': stats['learning_count'],
            'review': stats['review_count'],
            'mastered': stats['mastered_count'],
        }
```

Note: The SQL CASE version also filters by `next_review <= end_of_today` for non-new cards. The new method must preserve this "available to study today" filtering behavior.

**Step 4: Replace DeckService inline counting**

In `app/study/services/deck_service.py:get_deck_statistics()` (lines 116-151), the counting loop uses `user_word.status` instead of `UserCardDirection.state`. This is a different concern (UserWord-level vs card-level). For now, refactor to use `count_srs_states()` on the card directions of each deck word, or delegate to the new `get_words_deck_stats_batch()` single-deck version.

**Step 5: Verify and test**

Run: `pytest tests/test_stats_service.py tests/test_session_stats_services.py -v --tb=short`
Run: `pytest tests/test_grammar_lab_services.py -v --tb=short`
Run: `pytest --tb=short -q`
Expected: PASS (may need to update test mocks/assertions for new call paths)

**Step 6: Commit**

```bash
git add app/study/services/stats_service.py app/words/routes.py app/study/routes.py app/study/services/deck_service.py app/srs/stats_service.py
git commit -m "refactor: word stats — все пути через SRSStatsService"
```

---

### Task 7: Update tests for new call paths

**Files:**
- Modify: `tests/test_grammar_lab_services.py` — update tests calling removed GrammarSRS methods
- Modify: `tests/test_stats_service.py` — update StatsService.get_user_word_stats tests
- Modify: `tests/test_session_stats_services.py` — update mock paths

**Step 1: Update grammar_lab_services tests**

Tests that call `srs.get_topic_stats()` and `srs.get_user_stats()` (lines 409-477) should now either:
- Test via `SRSStatsService` directly, or
- Mock `SRSStatsService` where GrammarLabService delegates

**Step 2: Update stats_service tests**

Tests for `get_user_word_stats` (test_stats_service.py:155+) now test a delegation method. Either:
- Test the delegation (mock SRSStatsService)
- Or test end-to-end (preferred — verifies the mapping)

**Step 3: Run full test suite**

Run: `pytest --tb=short -q`
Expected: Same 6 pre-existing failures, no new failures

**Step 4: Commit**

```bash
git add tests/
git commit -m "test: обновление тестов после консолидации SRS stats"
```

---

### Task 8: Cleanup — remove dead code and hardcoded values

**Files:**
- Modify: `app/grammar_lab/models.py` — remove MASTERED_THRESHOLD_DAYS if now unused
- Modify: `app/study/routes.py` — replace any remaining `interval < 180` with constants
- Modify: `app/admin/services/user_management_service.py` — fix outdated status='mastered' check

**Step 1: Grep for remaining hardcoded 180**

Run: `grep -rn "180" app/ --include="*.py" | grep -i interval`

Replace any remaining hardcoded threshold values with constants from `app/srs/constants.py`.

**Step 2: Fix admin user_management_service**

If it still checks for `status='mastered'`, update it to use SRSStatsService or at minimum use the constant.

**Step 3: Run final test suite**

Run: `pytest --tb=short -q`
Expected: Same 6 pre-existing failures

**Step 4: Final commit**

```bash
git add -A
git commit -m "cleanup: удалены хардкод-пороги и мёртвый код после SRS-консолидации"
```

---

## Summary of Changes

| Before | After |
|--------|-------|
| 8 places with state counting | 1 utility function (`count_srs_states`) |
| No shared base for SRS fields | `SRSFieldsMixin` on both models |
| Stats in GrammarSRS, StatsService, routes | All in `SRSStatsService` |
| Hardcoded `>= 180` in 6 files | `MASTERED_THRESHOLD_DAYS` from constants |
| Accuracy only in grammar | `count_srs_states_with_accuracy` available to all |

## Verification Checklist

- [ ] `pytest` passes with no new failures
- [ ] `/study/` page shows correct deck stats
- [ ] `/words/dashboard` shows correct mastered count
- [ ] `/grammar/` shows correct topic stats
- [ ] `/api/srs-stats` returns correct data
- [ ] `/api/grammar-stats` returns correct data
