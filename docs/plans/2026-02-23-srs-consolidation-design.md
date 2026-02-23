# SRS Stats Consolidation Design

**Date:** 2026-02-23
**Status:** Approved

## Problem

SRS state counting logic (new/learning/review/mastered) is duplicated in 8 places across the codebase. Each implements the same classification pattern independently, making it error-prone and hard to maintain.

### Duplication Map

| File | Method | Model |
|------|--------|-------|
| `srs/stats_service.py` | get_words_stats, get_grammar_stats | Words + Grammar |
| `grammar_lab/services/grammar_srs.py` | get_topic_stats, get_topics_stats_batch, get_user_stats | Grammar |
| `grammar_lab/services/grammar_lab_service.py` | get_levels_summary (inline count) | Grammar |
| `study/routes.py` | SQL CASE in my-decks route | Words |
| `study/services/stats_service.py` | get_user_word_stats | Words |
| `study/services/deck_service.py` | get_deck_statistics (inline loop) | Words |
| `words/routes.py` | dashboard mastered count | Words |
| `admin/services/user_management_service.py` | get_user_statistics | Words (outdated) |

### Root Cause

UserCardDirection and UserGrammarExercise have 100% identical SRS fields but no shared base class. Each service re-implements the same `state + interval → category` logic.

## Solution: SRSFieldsMixin + Unified SRSStatsService

### 1. SRSFieldsMixin (`app/srs/mixins.py`)

Mixin providing:
- `classify() → 'new' | 'learning' | 'review' | 'mastered'`
- `is_due` property (next_review <= now or state == new)
- `is_mastered` property (state == review and interval >= 180)
- Class constants: `MASTERED_THRESHOLD_DAYS`, `MATURE_THRESHOLD_DAYS`

Both UserCardDirection and UserGrammarExercise inherit this mixin. No migration needed — columns stay identical.

### 2. count_srs_states utility (`app/srs/utils.py`)

Pure function that accepts any iterable of SRSFieldsMixin objects:

```python
def count_srs_states(records, now=None) -> dict:
    """Returns {new_count, learning_count, review_count, mastered_count, total, due_today}"""

def count_srs_states_with_accuracy(records, now=None) -> dict:
    """Same + accuracy from correct_count/incorrect_count."""
```

### 3. Unified SRSStatsService (`app/srs/stats_service.py`)

Single service for all SRS statistics:

**Words:**
- `get_words_stats(user_id, deck_id=None, word_ids=None)` — refactored to use count_srs_states
- `get_words_deck_stats(user_id)` — replaces SQL CASE from study/routes.py

**Grammar:**
- `get_grammar_stats(user_id, topic_id=None, level=None)` — refactored
- `get_grammar_stats_batch(user_id, topic_ids)` — moved from GrammarSRS
- `get_grammar_user_stats(user_id)` — moved from GrammarSRS

**General:**
- `get_user_overview(user_id)` — existing
- `get_grammar_topics_stats(user_id, level=None)` — existing

### 4. Removals

| Remove | Replace with |
|--------|-------------|
| GrammarSRS.get_topic_stats() | SRSStatsService.get_grammar_stats(topic_id=...) |
| GrammarSRS.get_topics_stats_batch() | SRSStatsService.get_grammar_stats_batch() |
| GrammarSRS.get_user_stats() | SRSStatsService.get_grammar_user_stats() |
| StatsService.get_user_word_stats() | SRSStatsService.get_words_stats() |
| SQL CASE in study/routes.py | SRSStatsService.get_words_deck_stats() |
| Inline count in words/routes.py | SRSStatsService.get_words_stats() |
| Inline count in grammar_lab_service.py | SRSStatsService methods |
| DeckService inline count | count_srs_states() utility |

## Files Changed

**New:**
- `app/srs/mixins.py`
- `app/srs/utils.py`

**Models (mixin adoption, no migration):**
- `app/study/models.py`
- `app/grammar_lab/models.py`

**Services (consolidation):**
- `app/srs/stats_service.py`
- `app/grammar_lab/services/grammar_srs.py`
- `app/grammar_lab/services/grammar_lab_service.py`
- `app/study/services/stats_service.py`
- `app/study/services/deck_service.py`

**Routes:**
- `app/study/routes.py`
- `app/words/routes.py`

**Tests:**
- Update: `test_grammar_lab_services.py`, `test_stats_service.py`, `test_session_stats_services.py`
- Add: `test_srs_utils.py`

## Migrations

None required. Mixin declares identical columns — database schema unchanged.

## Risks

- **Circular imports:** SRSStatsService imports grammar models. Mitigate with lazy imports where needed.
- **Performance:** Replacing SQL CASE with Python-side counting may be slower for very large datasets. Accept for now; optimize later if profiling shows issues.
- **Test coverage:** All callers must be tested after migration.
