"""Tests for scripts/backfill_card_sources.py.

Pure-function tests only — no DB or Flask app required.
DB/integration path is covered by the --no-db guard in main().
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import sys

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from backfill_card_sources import (  # noqa: E402
    BackfillPlan,
    CardRecord,
    Repository,
    SourceChange,
    apply_plan,
    format_report,
    infer_source,
    plan_backfill,
)


# ---------------------------------------------------------------------------
# Fake repository
# ---------------------------------------------------------------------------


class FakeRepository(Repository):
    def __init__(self, cards=None, lesson_vocab_ids=None, book_reading_ids=None):
        self._cards = list(cards or [])
        self._lesson_vocab_ids = set(lesson_vocab_ids or [])
        self._book_reading_ids = set(book_reading_ids or [])
        self._updates: list = []

    def get_cards_without_source(self) -> list:
        return list(self._cards)

    def get_lesson_vocab_word_ids(self) -> set:
        return set(self._lesson_vocab_ids)

    def get_book_reading_word_ids(self) -> set:
        return set(self._book_reading_ids)

    def update_source(self, card_id: int, source: str) -> None:
        self._updates.append((card_id, source))


def _card(card_id: int, word_id: int, direction: str = "eng-rus") -> CardRecord:
    return CardRecord(
        card_id=card_id,
        user_word_id=card_id * 10,
        word_id=word_id,
        direction=direction,
        current_source=None,
    )


# ---------------------------------------------------------------------------
# infer_source
# ---------------------------------------------------------------------------


class TestInferSource:
    def test_lesson_vocab_when_in_lesson_set(self):
        assert infer_source(1, {1, 2}, {3}) == "lesson_vocab"

    def test_book_reading_when_in_book_set_only(self):
        assert infer_source(3, {1, 2}, {3}) == "book_reading"

    def test_manual_when_not_in_either_set(self):
        assert infer_source(99, {1, 2}, {3}) == "manual"

    def test_lesson_vocab_takes_priority_over_book(self):
        assert infer_source(1, {1}, {1}) == "lesson_vocab"

    def test_empty_sets_returns_manual(self):
        assert infer_source(5, set(), set()) == "manual"


# ---------------------------------------------------------------------------
# plan_backfill
# ---------------------------------------------------------------------------


class TestPlanBackfill:
    def test_no_cards_returns_empty_plan(self):
        repo = FakeRepository()
        plan = plan_backfill(repo)
        assert plan.changes == []
        assert plan.errors == []

    def test_card_in_lesson_vocab_gets_lesson_source(self):
        repo = FakeRepository(
            cards=[_card(1, word_id=10)],
            lesson_vocab_ids=[10],
        )
        plan = plan_backfill(repo)
        assert len(plan.changes) == 1
        assert plan.changes[0].inferred_source == "lesson_vocab"
        assert plan.changes[0].action == "update"

    def test_card_in_book_reading_gets_book_source(self):
        repo = FakeRepository(
            cards=[_card(1, word_id=20)],
            book_reading_ids=[20],
        )
        plan = plan_backfill(repo)
        assert plan.changes[0].inferred_source == "book_reading"

    def test_unlinked_card_gets_manual_source(self):
        repo = FakeRepository(cards=[_card(1, word_id=99)])
        plan = plan_backfill(repo)
        assert plan.changes[0].inferred_source == "manual"

    def test_multiple_cards_mixed_sources(self):
        repo = FakeRepository(
            cards=[_card(1, 10), _card(2, 20), _card(3, 99)],
            lesson_vocab_ids=[10],
            book_reading_ids=[20],
        )
        plan = plan_backfill(repo)
        sources = {c.card_id: c.inferred_source for c in plan.changes}
        assert sources[1] == "lesson_vocab"
        assert sources[2] == "book_reading"
        assert sources[3] == "manual"

    def test_lesson_beats_book_for_same_word(self):
        repo = FakeRepository(
            cards=[_card(1, word_id=5)],
            lesson_vocab_ids=[5],
            book_reading_ids=[5],
        )
        plan = plan_backfill(repo)
        assert plan.changes[0].inferred_source == "lesson_vocab"

    def test_counts_all_actions_as_update(self):
        repo = FakeRepository(
            cards=[_card(1, 10), _card(2, 20), _card(3, 99)],
            lesson_vocab_ids=[10],
            book_reading_ids=[20],
        )
        plan = plan_backfill(repo)
        assert plan.counts.get("update", 0) == 3

    def test_source_counts_correct(self):
        repo = FakeRepository(
            cards=[_card(1, 10), _card(2, 20), _card(3, 99)],
            lesson_vocab_ids=[10],
            book_reading_ids=[20],
        )
        plan = plan_backfill(repo)
        sc = plan.source_counts
        assert sc.get("lesson_vocab", 0) == 1
        assert sc.get("book_reading", 0) == 1
        assert sc.get("manual", 0) == 1

    def test_both_directions_same_word_attributed_independently(self):
        cards = [
            _card(1, word_id=10, direction="eng-rus"),
            _card(2, word_id=10, direction="rus-eng"),
        ]
        repo = FakeRepository(cards=cards, lesson_vocab_ids=[10])
        plan = plan_backfill(repo)
        assert all(c.inferred_source == "lesson_vocab" for c in plan.changes)

    def test_large_card_set_all_manual(self):
        cards = [_card(i, word_id=1000 + i) for i in range(50)]
        repo = FakeRepository(cards=cards)
        plan = plan_backfill(repo)
        assert plan.source_counts.get("manual", 0) == 50
        assert plan.counts.get("update", 0) == 50


# ---------------------------------------------------------------------------
# apply_plan
# ---------------------------------------------------------------------------


class TestApplyPlan:
    def test_updates_all_cards(self):
        repo = FakeRepository(
            cards=[_card(1, 10), _card(2, 20)],
            lesson_vocab_ids=[10],
            book_reading_ids=[20],
        )
        plan = plan_backfill(repo)
        count = apply_plan(plan, repo)
        assert count == 2

    def test_correct_sources_written(self):
        repo = FakeRepository(
            cards=[_card(1, 10), _card(2, 99)],
            lesson_vocab_ids=[10],
        )
        plan = plan_backfill(repo)
        apply_plan(plan, repo)
        updates = dict(repo._updates)
        assert updates[1] == "lesson_vocab"
        assert updates[2] == "manual"

    def test_empty_plan_writes_nothing(self):
        repo = FakeRepository()
        plan = BackfillPlan()
        count = apply_plan(plan, repo)
        assert count == 0
        assert repo._updates == []

    def test_apply_returns_count_of_updates(self):
        repo = FakeRepository(cards=[_card(i, i * 10) for i in range(5)])
        plan = plan_backfill(repo)
        count = apply_plan(plan, repo)
        assert count == 5


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    def test_contains_title(self):
        plan = BackfillPlan()
        report = format_report(plan, dry_run=False, elapsed=0.1)
        assert "SRS Card Source Backfill Report" in report

    def test_dry_run_flag_visible(self):
        plan = BackfillPlan()
        report = format_report(plan, dry_run=True, elapsed=0.1)
        assert "dry-run" in report

    def test_live_mode_label(self):
        plan = BackfillPlan()
        report = format_report(plan, dry_run=False, elapsed=0.1)
        assert "live" in report

    def test_all_source_types_mentioned(self):
        repo = FakeRepository(
            cards=[_card(1, 10), _card(2, 20), _card(3, 99)],
            lesson_vocab_ids=[10],
            book_reading_ids=[20],
        )
        plan = plan_backfill(repo)
        report = format_report(plan, dry_run=False, elapsed=0.5)
        assert "lesson_vocab" in report
        assert "book_reading" in report
        assert "manual" in report

    def test_total_rows_written_shown(self):
        repo = FakeRepository(cards=[_card(1, 10)], lesson_vocab_ids=[10])
        plan = plan_backfill(repo)
        report = format_report(plan, dry_run=False, elapsed=0.1)
        assert "Total rows written: 1" in report

    def test_zero_cards_report_valid(self):
        plan = BackfillPlan()
        report = format_report(plan, dry_run=False, elapsed=0.05)
        assert "0" in report

    def test_errors_listed_in_report(self):
        plan = BackfillPlan(errors=["some error occurred"])
        report = format_report(plan, dry_run=False, elapsed=0.1)
        assert "some error occurred" in report

    def test_unresolved_count_shown(self):
        repo = FakeRepository(cards=[_card(1, 99), _card(2, 98)])
        plan = plan_backfill(repo)
        report = format_report(plan, dry_run=False, elapsed=0.1)
        assert "2" in report


# ---------------------------------------------------------------------------
# BackfillPlan.counts and source_counts
# ---------------------------------------------------------------------------


class TestBackfillPlanCounts:
    def test_counts_empty_plan(self):
        plan = BackfillPlan()
        assert plan.counts == {}
        assert plan.source_counts == {}

    def test_counts_single_update(self):
        plan = BackfillPlan(changes=[
            SourceChange(card_id=1, word_id=1, direction="eng-rus",
                         inferred_source="lesson_vocab", action="update"),
        ])
        assert plan.counts == {"update": 1}
        assert plan.source_counts == {"lesson_vocab": 1}

    def test_source_counts_only_updates(self):
        plan = BackfillPlan(changes=[
            SourceChange(card_id=1, word_id=1, direction="eng-rus",
                         inferred_source="manual", action="update"),
            SourceChange(card_id=2, word_id=2, direction="eng-rus",
                         inferred_source="book_reading", action="update"),
        ])
        assert plan.source_counts["manual"] == 1
        assert plan.source_counts["book_reading"] == 1
        assert plan.source_counts.get("lesson_vocab", 0) == 0


# ---------------------------------------------------------------------------
# main --no-db guard
# ---------------------------------------------------------------------------


class TestMainNoDB:
    def test_no_db_exits_zero(self):
        from backfill_card_sources import main
        assert main(["--no-db"]) == 0
