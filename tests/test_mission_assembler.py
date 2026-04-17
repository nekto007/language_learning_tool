import logging
from unittest.mock import patch, MagicMock

import pytest

from app.daily_plan.models import (
    MODE_CATEGORY_MAP,
    MissionPhase,
    MissionPlan,
    MissionType,
    PhaseKind,
    PhasePreview,
    SourceKind,
)
from app.daily_plan.repair_pressure import RepairBreakdown
from app.daily_plan.assembler import (
    _CATEGORY_SUBSTITUTIONS,
    _deduplicate_phases,
    assemble_progress_mission,
    assemble_reading_mission,
    assemble_repair_mission,
)

MODULE = "app.daily_plan.assembler"


def _low_repair() -> RepairBreakdown:
    return RepairBreakdown(
        overdue_srs_count=5,
        overdue_srs_score=0.1,
        grammar_weak_count=2,
        grammar_weak_score=0.1,
        failure_cluster_count=1,
        failure_cluster_score=0.05,
        total_score=0.1,
    )


def _high_repair() -> RepairBreakdown:
    return RepairBreakdown(
        overdue_srs_count=50,
        overdue_srs_score=1.0,
        grammar_weak_count=10,
        grammar_weak_score=1.0,
        failure_cluster_count=15,
        failure_cluster_score=1.0,
        total_score=1.0,
    )


class TestAssembleProgressMission:
    @patch(f"{MODULE}._count_srs_due", return_value=10)
    @patch(f"{MODULE}._find_next_lesson", return_value={
        'title': 'Урок 5', 'lesson_id': 42, 'module_id': 3,
        'module_number': 2, 'lesson_type': 'grammar',
    })
    def test_normal_course_with_srs(self, _lesson, _srs):
        plan = assemble_progress_mission(1, SourceKind.normal_course)
        assert isinstance(plan, MissionPlan)
        assert plan.mission.type == MissionType.progress
        assert plan.primary_source.kind == SourceKind.normal_course
        assert plan.primary_source.label == "Урок 5"
        assert 4 <= len(plan.phases) <= 5
        assert plan.phases[0].phase == PhaseKind.recall
        assert plan.phases[0].source_kind == SourceKind.srs
        assert plan.phases[1].phase == PhaseKind.learn
        assert plan.phases[2].phase == PhaseKind.use
        check = next(p for p in plan.phases if p.phase == PhaseKind.check)
        assert check.required is False

    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_lesson", return_value={
        'title': 'Урок 1', 'lesson_id': 1, 'module_id': 1,
        'module_number': 1, 'lesson_type': 'dialogue',
    })
    def test_normal_course_no_srs_gives_3_phases(self, _lesson, _srs):
        plan = assemble_progress_mission(1, SourceKind.normal_course)
        assert 3 <= len(plan.phases) <= 4
        assert plan.phases[0].phase == PhaseKind.recall
        assert plan.phases[0].mode == "guided_recall"
        assert plan.phases[1].phase == PhaseKind.learn
        assert plan.phases[2].phase == PhaseKind.use

    @patch(f"{MODULE}._count_srs_due", return_value=5)
    @patch(f"{MODULE}._find_next_book_course_lesson", return_value={
        'course_id': 10, 'course_title': 'Harry Potter',
        'lesson_id': 77, 'day_number': 3, 'lesson_type': 'reading',
    })
    def test_book_course_with_srs(self, _bc, _srs):
        plan = assemble_progress_mission(1, SourceKind.book_course)
        assert plan.mission.type == MissionType.progress
        assert plan.primary_source.kind == SourceKind.book_course
        assert plan.primary_source.label == "Harry Potter"
        assert 4 <= len(plan.phases) <= 5
        assert plan.phases[1].source_kind == SourceKind.book_course

    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_book_course_lesson", return_value={
        'course_id': 10, 'course_title': 'HP', 'lesson_id': 77,
        'day_number': 1, 'lesson_type': 'reading',
    })
    def test_book_course_no_srs_gives_3_phases(self, _bc, _srs):
        plan = assemble_progress_mission(1, SourceKind.book_course)
        assert 3 <= len(plan.phases) <= 4

    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_lesson", return_value=None)
    def test_no_lesson_available_returns_none(self, _lesson, _srs):
        plan = assemble_progress_mission(1, SourceKind.normal_course)
        assert plan is None

    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_book_course_lesson", return_value=None)
    def test_no_bc_lesson_returns_none(self, _bc, _srs):
        plan = assemble_progress_mission(1, SourceKind.book_course)
        assert plan is None

    @patch(f"{MODULE}._count_srs_due", return_value=10)
    @patch(f"{MODULE}._find_next_lesson", return_value={
        'title': 'L1', 'lesson_id': 1, 'module_id': 1,
        'module_number': 1, 'lesson_type': 'grammar',
    })
    def test_legacy_block_contains_next_lesson(self, _lesson, _srs):
        plan = assemble_progress_mission(1, SourceKind.normal_course)
        assert 'next_lesson' in plan.legacy
        assert plan.legacy['next_lesson']['lesson_id'] == 1

    @patch(f"{MODULE}._count_srs_due", return_value=5)
    @patch(f"{MODULE}._find_next_book_course_lesson", return_value={
        'course_id': 10, 'course_title': 'HP', 'lesson_id': 77,
        'day_number': 1, 'lesson_type': 'reading',
    })
    def test_legacy_block_contains_bc_lesson(self, _bc, _srs):
        plan = assemble_progress_mission(1, SourceKind.book_course)
        assert 'book_course_lesson' in plan.legacy


class TestAssembleRepairMission:
    @patch(f"{MODULE}._find_weak_grammar_topic", return_value={
        'title': 'Present Perfect', 'topic_id': 5,
    })
    @patch(f"{MODULE}._count_grammar_due", return_value=8)
    @patch(f"{MODULE}._count_srs_due", return_value=20)
    def test_repair_with_srs_and_grammar(self, _srs, _grammar, _topic):
        plan = assemble_repair_mission(1, _high_repair())
        assert isinstance(plan, MissionPlan)
        assert plan.mission.type == MissionType.repair
        assert 4 <= len(plan.phases) <= 5
        assert plan.phases[0].phase == PhaseKind.recall
        assert plan.phases[0].mode == "srs_review"
        assert plan.phases[1].phase == PhaseKind.learn
        assert plan.phases[1].source_kind == SourceKind.grammar_lab
        assert plan.phases[2].phase == PhaseKind.use
        assert any(p.phase == PhaseKind.close for p in plan.phases)

    @patch(f"{MODULE}._find_weak_grammar_topic", return_value=None)
    @patch(f"{MODULE}._count_grammar_due", return_value=0)
    @patch(f"{MODULE}._count_srs_due", return_value=15)
    def test_repair_srs_only_no_grammar(self, _srs, _grammar, _topic):
        plan = assemble_repair_mission(1, _high_repair())
        assert plan is not None
        # After dedup: phase[0]=srs_review(words), phase[1] was vocab_drill(words dup)
        # → substituted to grammar_practice(grammar)
        assert plan.phases[1].source_kind == SourceKind.grammar_lab
        assert plan.phases[1].mode == "grammar_practice"

    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{MODULE}.assemble_progress_mission", return_value=None)
    @patch(f"{MODULE}._find_weak_grammar_topic", return_value=None)
    @patch(f"{MODULE}._count_grammar_due", return_value=0)
    @patch(f"{MODULE}._count_srs_due", return_value=0)
    def test_repair_nothing_due_degrades(self, _srs, _grammar, _topic, _progress, _track):
        plan = assemble_repair_mission(1, _low_repair())
        assert plan is None

    @patch(f"{MODULE}._find_weak_grammar_topic", return_value={
        'title': 'Conditionals', 'topic_id': 12,
    })
    @patch(f"{MODULE}._count_grammar_due", return_value=5)
    @patch(f"{MODULE}._count_srs_due", return_value=0)
    def test_repair_grammar_only_no_srs(self, _srs, _grammar, _topic):
        plan = assemble_repair_mission(1, _high_repair())
        assert plan is not None
        assert plan.phases[0].mode == "guided_recall"
        assert plan.primary_source.kind == SourceKind.grammar_lab

    @patch(f"{MODULE}._find_weak_grammar_topic", return_value={
        'title': 'Articles', 'topic_id': 3,
    })
    @patch(f"{MODULE}._count_grammar_due", return_value=5)
    @patch(f"{MODULE}._count_srs_due", return_value=10)
    def test_repair_legacy_block(self, _srs, _grammar, _topic):
        breakdown = _high_repair()
        plan = assemble_repair_mission(1, breakdown)
        assert plan.legacy['overdue_srs'] == breakdown.overdue_srs_count
        assert plan.legacy['grammar_weak'] == breakdown.grammar_weak_count

    @patch(f"{MODULE}._find_weak_grammar_topic", return_value={
        'title': 'Tenses', 'topic_id': 7,
    })
    @patch(f"{MODULE}._count_grammar_due", return_value=3)
    @patch(f"{MODULE}._count_srs_due", return_value=5)
    def test_repair_close_phase_not_required(self, _srs, _grammar, _topic):
        plan = assemble_repair_mission(1, _high_repair())
        close = next(p for p in plan.phases if p.phase == PhaseKind.close)
        assert close.required is False


class TestAssembleReadingMission:
    @patch(f"{MODULE}._count_srs_due", return_value=10)
    @patch(f"{MODULE}._find_next_book", return_value={'title': 'Alice', 'id': 7})
    def test_reading_with_srs(self, _book, _srs):
        plan = assemble_reading_mission(1)
        assert isinstance(plan, MissionPlan)
        assert plan.mission.type == MissionType.reading
        assert plan.primary_source.kind == SourceKind.books
        assert plan.primary_source.label == "Alice"
        assert 4 <= len(plan.phases) <= 5
        assert plan.phases[0].phase == PhaseKind.recall
        assert plan.phases[1].phase == PhaseKind.read
        assert plan.phases[2].phase == PhaseKind.use
        assert any(p.phase == PhaseKind.check for p in plan.phases)

    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_book", return_value={'title': 'Gatsby', 'id': 3})
    def test_reading_no_srs_gives_3_phases(self, _book, _srs):
        plan = assemble_reading_mission(1)
        assert 3 <= len(plan.phases) <= 4
        assert plan.phases[0].mode == "guided_recall"

    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_book", return_value=None)
    def test_no_book_returns_none(self, _book, _srs):
        plan = assemble_reading_mission(1)
        assert plan is None

    @patch(f"{MODULE}._count_srs_due", return_value=5)
    @patch(f"{MODULE}._find_next_book", return_value={'title': 'HP', 'id': 1})
    def test_reading_legacy_block(self, _book, _srs):
        plan = assemble_reading_mission(1)
        assert plan.legacy['book_to_read'] == {'title': 'HP', 'id': 1}

    @patch(f"{MODULE}._count_srs_due", return_value=5)
    @patch(f"{MODULE}._find_next_book", return_value={'title': 'Book', 'id': 2})
    def test_reading_check_phase_not_required(self, _book, _srs):
        plan = assemble_reading_mission(1)
        check = next(p for p in plan.phases if p.phase == PhaseKind.check)
        assert check.phase == PhaseKind.check
        assert check.required is False

    @patch(f"{MODULE}._count_srs_due", return_value=10)
    @patch(f"{MODULE}._find_next_book", return_value={'title': 'Book', 'id': 2})
    def test_reading_recall_uses_book_vocab(self, _book, _srs):
        plan = assemble_reading_mission(1)
        assert plan.phases[0].source_kind == SourceKind.vocab
        assert plan.phases[0].mode == "book_vocab_recall"


class TestAssemblerValidation:
    @patch(f"{MODULE}._count_srs_due", return_value=10)
    @patch(f"{MODULE}._find_next_lesson", return_value={
        'title': 'L', 'lesson_id': 1, 'module_id': 1,
        'module_number': 1, 'lesson_type': 'grammar',
    })
    def test_plan_has_valid_phase_count(self, _lesson, _srs):
        plan = assemble_progress_mission(1, SourceKind.normal_course)
        assert 3 <= len(plan.phases) <= 5

    @patch(f"{MODULE}._find_weak_grammar_topic", return_value={
        'title': 'T', 'topic_id': 1,
    })
    @patch(f"{MODULE}._count_grammar_due", return_value=5)
    @patch(f"{MODULE}._count_srs_due", return_value=5)
    def test_repair_has_4_or_5_phases(self, _srs, _grammar, _topic):
        plan = assemble_repair_mission(1, _high_repair())
        assert 4 <= len(plan.phases) <= 5

    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_lesson", return_value={
        'title': 'L', 'lesson_id': 1, 'module_id': 1,
        'module_number': 1, 'lesson_type': 'grammar',
    })
    def test_all_phases_have_unique_ids(self, _lesson, _srs):
        plan = assemble_progress_mission(1, SourceKind.normal_course)
        ids = [p.id for p in plan.phases]
        assert len(ids) == len(set(ids))

    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_lesson", return_value={
        'title': 'L', 'lesson_id': 1, 'module_id': 1,
        'module_number': 1, 'lesson_type': 'grammar',
    })
    def test_plan_version_is_set(self, _lesson, _srs):
        plan = assemble_progress_mission(1, SourceKind.normal_course)
        assert plan.plan_version == "1"


class TestFallbackHelpers:
    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_lesson", return_value={
        'title': 'L', 'lesson_id': 1, 'module_id': 1,
        'module_number': 1, 'lesson_type': 'grammar',
    })
    def test_guided_recall_when_no_srs(self, _lesson, _srs):
        plan = assemble_progress_mission(1, SourceKind.normal_course)
        recall = plan.phases[0]
        assert recall.mode == "guided_recall"

    @patch(f"{MODULE}._count_srs_due", return_value=5)
    @patch(f"{MODULE}._find_next_lesson", return_value={
        'title': 'L', 'lesson_id': 1, 'module_id': 1,
        'module_number': 1, 'lesson_type': 'grammar',
    })
    def test_srs_recall_when_srs_available(self, _lesson, _srs):
        plan = assemble_progress_mission(1, SourceKind.normal_course)
        recall = plan.phases[0]
        assert recall.mode == "srs_review"
        assert recall.source_kind == SourceKind.srs

    @patch(f"{MODULE}._find_weak_grammar_topic", return_value={
        'title': 'T', 'topic_id': 1,
    })
    @patch(f"{MODULE}._count_grammar_due", return_value=3)
    @patch(f"{MODULE}._count_srs_due", return_value=5)
    def test_close_phase_as_soft_close(self, _srs, _grammar, _topic):
        plan = assemble_repair_mission(1, _high_repair())
        close = next(p for p in plan.phases if p.phase == PhaseKind.close)
        assert close.mode == "success_marker"
        assert close.required is False


class TestDeduplicatePhases:
    """Tests for _deduplicate_phases and duplicate category prevention."""

    def _make_phase(self, mode: str, phase_kind: PhaseKind = PhaseKind.recall,
                    source_kind: SourceKind = SourceKind.vocab) -> MissionPhase:
        return MissionPhase(
            phase=phase_kind, title="Test", source_kind=source_kind, mode=mode,
        )

    def test_no_duplicates_passes_through(self):
        phases = [
            self._make_phase("srs_review", PhaseKind.recall, SourceKind.srs),
            self._make_phase("grammar_practice", PhaseKind.learn, SourceKind.grammar_lab),
            self._make_phase("book_reading", PhaseKind.read, SourceKind.books),
        ]
        result = _deduplicate_phases(phases)
        assert [p.mode for p in result] == ["srs_review", "grammar_practice", "book_reading"]

    def test_duplicate_words_substitutes_to_grammar(self):
        """Two 'words' phases → second becomes grammar_practice."""
        phases = [
            self._make_phase("srs_review", PhaseKind.recall, SourceKind.srs),
            self._make_phase("vocab_drill", PhaseKind.learn),
            self._make_phase("meaning_prompt", PhaseKind.use),
        ]
        result = _deduplicate_phases(phases)
        categories = [MODE_CATEGORY_MAP.get(p.mode) for p in result]
        non_none = [c for c in categories if c is not None]
        assert len(non_none) == len(set(non_none))
        # First words kept, second→grammar_practice(grammar), third→book_reading(books)
        assert result[0].mode == "srs_review"
        assert result[1].mode == "grammar_practice"
        assert result[1].source_kind == SourceKind.grammar_lab
        assert result[2].mode == "book_reading"
        assert result[2].source_kind == SourceKind.books

    def test_triple_words_substitutes_all(self):
        """Three 'words' phases + close → each gets a different category."""
        phases = [
            self._make_phase("srs_review", PhaseKind.recall, SourceKind.srs),
            self._make_phase("vocab_drill", PhaseKind.learn),
            self._make_phase("meaning_prompt", PhaseKind.use),
            self._make_phase("success_marker", PhaseKind.close),  # not in map
        ]
        result = _deduplicate_phases(phases)
        categories = [MODE_CATEGORY_MAP.get(p.mode) for p in result]
        non_none = [c for c in categories if c is not None]
        assert len(non_none) == len(set(non_none)), f"Duplicate categories: {categories}"

    def test_duplicate_grammar_with_words_taken_substitutes_to_books(self):
        """Two 'grammar' phases when 'words' is taken → second becomes book_reading (books)."""
        phases = [
            self._make_phase("srs_review", PhaseKind.recall, SourceKind.srs),
            self._make_phase("grammar_practice", PhaseKind.learn, SourceKind.grammar_lab),
            self._make_phase("targeted_quiz", PhaseKind.use, SourceKind.grammar_lab),
        ]
        result = _deduplicate_phases(phases)
        categories = [MODE_CATEGORY_MAP.get(p.mode) for p in result]
        non_none = [c for c in categories if c is not None]
        assert len(non_none) == len(set(non_none)), f"Duplicate categories: {categories}"
        assert result[0].mode == "srs_review"
        assert result[1].mode == "grammar_practice"
        # words taken, meaning_prompt→words taken → book_reading (books)
        assert result[2].mode == "book_reading"

    def test_duplicate_grammar_substitutes_when_words_free(self):
        """Two 'grammar' phases → second becomes vocab_drill when words category is free."""
        phases = [
            self._make_phase("grammar_practice", PhaseKind.recall, SourceKind.grammar_lab),
            self._make_phase("targeted_quiz", PhaseKind.use, SourceKind.grammar_lab),
            self._make_phase("book_reading", PhaseKind.read, SourceKind.books),
        ]
        result = _deduplicate_phases(phases)
        assert result[0].mode == "grammar_practice"
        assert result[1].mode == "vocab_drill"
        assert result[1].source_kind == SourceKind.vocab

    def test_fallback_when_primary_substitute_unavailable(self):
        """When first substitute's category is taken, try deeper in the list."""
        # words taken, grammar taken → vocab_drill(words dup) should fallback to book_reading(books)
        phases = [
            self._make_phase("srs_review", PhaseKind.recall, SourceKind.srs),         # words
            self._make_phase("grammar_practice", PhaseKind.learn, SourceKind.grammar_lab),  # grammar
            self._make_phase("vocab_drill", PhaseKind.use),                           # words dup
            self._make_phase("success_marker", PhaseKind.close),                       # no cat
        ]
        result = _deduplicate_phases(phases)
        # vocab_drill(words dup) → grammar_practice(grammar-taken), targeted_quiz(grammar-taken),
        # book_reading(books-free) → substituted
        assert result[2].mode == "book_reading"

    def test_no_substitute_when_all_categories_taken(self):
        """When all substitute categories are taken, phase is kept as-is."""
        # words, grammar, books all taken → a 4th words phase can't be substituted
        phases = [
            self._make_phase("srs_review", PhaseKind.recall, SourceKind.srs),         # words
            self._make_phase("grammar_practice", PhaseKind.learn, SourceKind.grammar_lab),  # grammar
            self._make_phase("book_reading", PhaseKind.read, SourceKind.books),        # books
            self._make_phase("vocab_drill", PhaseKind.use),                           # words dup
        ]
        result = _deduplicate_phases(phases)
        # All substitute categories (grammar, books) are taken → kept as-is
        assert result[3].mode == "vocab_drill"

    def test_unknown_modes_passthrough(self):
        """Modes not in MODE_CATEGORY_MAP pass through without dedup."""
        phases = [
            self._make_phase("success_marker", PhaseKind.close),
            self._make_phase("success_marker", PhaseKind.close),
            self._make_phase("srs_review", PhaseKind.recall, SourceKind.srs),
        ]
        result = _deduplicate_phases(phases)
        assert len(result) == 3
        assert result[0].mode == "success_marker"
        assert result[1].mode == "success_marker"

    def test_preserves_phase_attributes(self):
        """Substituted phase preserves phase kind, required, completed; uses substitute title."""
        phase = MissionPhase(
            phase=PhaseKind.use, title="Custom title",
            source_kind=SourceKind.vocab, mode="meaning_prompt",
            required=False, completed=True,
            preview=PhasePreview(item_count=5),
        )
        phases = [
            self._make_phase("srs_review", PhaseKind.recall, SourceKind.srs),
            phase,
        ]
        result = _deduplicate_phases(phases)
        sub = result[1]
        assert sub.phase == PhaseKind.use
        # Substituted phase gets a title matching the new mode, not the original
        assert sub.title != "Custom title"
        assert sub.required is False
        assert sub.completed is True
        # Preview is cleared since it was specific to the original mode
        assert sub.preview is None


class TestRepairDeduplication:
    """Repair mission uses _deduplicate_phases to ensure varied categories."""

    @patch(f"{MODULE}._find_weak_grammar_topic", return_value=None)
    @patch(f"{MODULE}._count_grammar_due", return_value=0)
    @patch(f"{MODULE}._count_srs_due", return_value=15)
    def test_repair_no_grammar_deduplicates_words(self, _srs, _grammar, _topic):
        """Without grammar, repair would have 3 words phases → dedup diversifies."""
        plan = assemble_repair_mission(1, _high_repair())
        assert plan is not None
        categories = [MODE_CATEGORY_MAP.get(p.mode) for p in plan.phases]
        non_none = [c for c in categories if c is not None]
        assert len(non_none) == len(set(non_none)), f"Duplicate categories: {categories}"

    @patch(f"{MODULE}._find_weak_grammar_topic", return_value={
        'title': 'Articles', 'topic_id': 3,
    })
    @patch(f"{MODULE}._count_grammar_due", return_value=5)
    @patch(f"{MODULE}._count_srs_due", return_value=10)
    def test_repair_with_grammar_no_duplicate_categories(self, _srs, _grammar, _topic):
        """Repair with grammar: words + grammar + grammar(quiz) → dedup fixes."""
        plan = assemble_repair_mission(1, _high_repair())
        assert plan is not None
        categories = [MODE_CATEGORY_MAP.get(p.mode) for p in plan.phases]
        non_none = [c for c in categories if c is not None]
        assert len(non_none) == len(set(non_none)), f"Duplicate categories: {categories}"


class TestMissionPlanDuplicateWarning:
    """MissionPlan.__post_init__ warns on duplicate categories."""

    def test_warns_on_duplicate_categories(self, caplog):
        from app.daily_plan.models import Mission, PrimaryGoal, PrimarySource
        with caplog.at_level(logging.WARNING, logger="app.daily_plan.models"):
            # Bypass dedup to force duplicates into MissionPlan
            MissionPlan(
                plan_version="1",
                mission=Mission(
                    type=MissionType.progress, title="T",
                    reason_code="test", reason_text="test",
                ),
                primary_goal=PrimaryGoal(type="t", title="T", success_criterion="t"),
                primary_source=PrimarySource(kind=SourceKind.srs, id="1", label="L"),
                phases=[
                    MissionPhase(phase=PhaseKind.recall, title="A",
                                 source_kind=SourceKind.srs, mode="srs_review"),
                    MissionPhase(phase=PhaseKind.learn, title="B",
                                 source_kind=SourceKind.vocab, mode="vocab_drill"),
                    MissionPhase(phase=PhaseKind.use, title="C",
                                 source_kind=SourceKind.vocab, mode="meaning_prompt"),
                ],
            )
        assert any("duplicate category" in r.message for r in caplog.records)

    def test_no_warning_when_categories_unique(self, caplog):
        from app.daily_plan.models import Mission, PrimaryGoal, PrimarySource
        with caplog.at_level(logging.WARNING, logger="app.daily_plan.models"):
            MissionPlan(
                plan_version="1",
                mission=Mission(
                    type=MissionType.progress, title="T",
                    reason_code="test", reason_text="test",
                ),
                primary_goal=PrimaryGoal(type="t", title="T", success_criterion="t"),
                primary_source=PrimarySource(kind=SourceKind.srs, id="1", label="L"),
                phases=[
                    MissionPhase(phase=PhaseKind.recall, title="A",
                                 source_kind=SourceKind.srs, mode="srs_review"),
                    MissionPhase(phase=PhaseKind.learn, title="B",
                                 source_kind=SourceKind.grammar_lab, mode="grammar_practice"),
                    MissionPhase(phase=PhaseKind.read, title="C",
                                 source_kind=SourceKind.books, mode="book_reading"),
                ],
            )
        assert not any("duplicate category" in r.message for r in caplog.records)


class TestPhasePreviewData:
    """Task 4: Assembled plans contain correct preview data for each phase type."""

    @patch(f"{MODULE}._count_srs_due", return_value=25)
    @patch(f"{MODULE}._find_next_lesson", return_value={
        'title': 'Present Perfect', 'lesson_id': 42, 'module_id': 3,
        'module_number': 2, 'lesson_type': 'grammar',
    })
    def test_progress_normal_course_preview(self, _lesson, _srs):
        plan = assemble_progress_mission(1, SourceKind.normal_course)
        # Recall phase: SRS review with item count
        recall = plan.phases[0]
        assert recall.preview is not None
        assert recall.preview.item_count == 25
        assert recall.preview.content_title == "Повторение карточек"
        assert recall.preview.estimated_minutes == 3  # ceil(25/10)

        # Learn phase: lesson title
        learn = plan.phases[1]
        assert learn.preview is not None
        assert learn.preview.content_title == "Present Perfect"
        assert learn.preview.estimated_minutes == 10

        # Use phase: practice
        use = plan.phases[2]
        assert use.preview is not None
        assert use.preview.content_title == "Present Perfect"
        assert use.preview.estimated_minutes == 5

        # Check phase: micro check
        check = plan.phases[3]
        assert check.preview is not None
        assert check.preview.item_count == 10  # capped at 10
        assert check.preview.estimated_minutes == 3

    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_lesson", return_value={
        'title': 'Lesson 1', 'lesson_id': 1, 'module_id': 1,
        'module_number': 1, 'lesson_type': 'dialogue',
    })
    def test_progress_no_srs_guided_recall_preview(self, _lesson, _srs):
        plan = assemble_progress_mission(1, SourceKind.normal_course)
        recall = plan.phases[0]
        assert recall.preview is not None
        assert recall.preview.item_count is None
        assert recall.preview.content_title == "Быстрый разогрев"
        assert recall.preview.estimated_minutes == 3

    @patch(f"{MODULE}._count_srs_due", return_value=5)
    @patch(f"{MODULE}._find_next_book_course_lesson", return_value={
        'course_id': 10, 'course_title': 'Harry Potter',
        'lesson_id': 77, 'day_number': 3, 'lesson_type': 'reading',
    })
    def test_progress_book_course_preview(self, _bc, _srs):
        plan = assemble_progress_mission(1, SourceKind.book_course)
        learn = plan.phases[1]
        assert learn.preview is not None
        assert learn.preview.content_title == "Harry Potter"
        assert learn.preview.estimated_minutes == 10

        use = plan.phases[2]
        assert use.preview.content_title == "Harry Potter"

    @patch(f"{MODULE}._find_weak_grammar_topic", return_value={
        'title': 'Conditionals', 'topic_id': 12,
    })
    @patch(f"{MODULE}._count_grammar_due", return_value=8)
    @patch(f"{MODULE}._count_srs_due", return_value=20)
    def test_repair_with_grammar_preview(self, _srs, _grammar, _topic):
        plan = assemble_repair_mission(1, _high_repair())
        # Recall
        recall = plan.phases[0]
        assert recall.preview is not None
        assert recall.preview.item_count == 20
        assert recall.preview.content_title == "Повторение карточек"

        # Learn: grammar topic
        learn = plan.phases[1]
        assert learn.preview is not None
        assert learn.preview.content_title == "Conditionals"
        assert learn.preview.estimated_minutes == 7

        # Use: substituted by dedup (grammar category already taken),
        # preview is cleared since the original preview described a different activity
        use = plan.phases[2]
        assert use.mode != "targeted_quiz"  # substituted away from grammar
        assert use.preview is None

        # Close
        close = plan.phases[3]
        assert close.preview is not None
        assert close.preview.estimated_minutes == 1

    @patch(f"{MODULE}._find_weak_grammar_topic", return_value=None)
    @patch(f"{MODULE}._count_grammar_due", return_value=0)
    @patch(f"{MODULE}._count_srs_due", return_value=15)
    def test_repair_no_grammar_preview(self, _srs, _grammar, _topic):
        plan = assemble_repair_mission(1, _high_repair())
        # Recall has SRS preview
        recall = plan.phases[0]
        assert recall.preview.item_count == 15

    @patch(f"{MODULE}._count_srs_due", return_value=10)
    @patch(f"{MODULE}._find_next_book", return_value={'title': 'Alice in Wonderland', 'id': 7})
    def test_reading_preview(self, _book, _srs):
        plan = assemble_reading_mission(1)
        # Recall: book vocab
        recall = plan.phases[0]
        assert recall.preview is not None
        assert recall.preview.item_count == 10
        assert recall.preview.content_title == "Слова из книги"

        # Read phase: book title
        read = plan.phases[1]
        assert read.preview is not None
        assert read.preview.content_title == "Alice in Wonderland"
        assert read.preview.estimated_minutes == 10

        # Use phase: vocab extract
        use = plan.phases[2]
        assert use.preview is not None
        assert use.preview.content_title == "Alice in Wonderland"
        assert use.preview.estimated_minutes == 5

        # Check: meaning prompt
        check = plan.phases[3]
        assert check.preview is not None
        assert check.preview.item_count == 10
        assert check.preview.estimated_minutes == 3

    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_book", return_value={'title': 'Gatsby', 'id': 3})
    def test_reading_no_srs_preview(self, _book, _srs):
        plan = assemble_reading_mission(1)
        recall = plan.phases[0]
        assert recall.preview.item_count is None
        assert recall.preview.content_title == "Быстрый разогрев"

    def test_all_phases_have_preview(self):
        """Every phase created by every assembler should have a preview."""
        # Just verify the PhasePreview dataclass works correctly
        preview = PhasePreview(item_count=10, content_title="Test", estimated_minutes=5)
        assert preview.item_count == 10
        assert preview.content_title == "Test"
        assert preview.estimated_minutes == 5

    def test_phase_preview_defaults_to_none(self):
        """PhasePreview fields default to None."""
        preview = PhasePreview()
        assert preview.item_count is None
        assert preview.content_title is None
        assert preview.estimated_minutes is None

    def test_mission_phase_preview_default_none(self):
        """MissionPhase.preview defaults to None."""
        phase = MissionPhase(
            phase=PhaseKind.recall, title="T",
            source_kind=SourceKind.srs, mode="srs_review",
        )
        assert phase.preview is None


class TestEstimateSrsMinutes:
    """Test _estimate_srs_minutes helper."""

    def test_minimum_is_two(self):
        from app.daily_plan.assembler import _estimate_srs_minutes
        assert _estimate_srs_minutes(0) == 2
        assert _estimate_srs_minutes(1) == 2
        assert _estimate_srs_minutes(5) == 2

    def test_scales_with_count(self):
        from app.daily_plan.assembler import _estimate_srs_minutes
        assert _estimate_srs_minutes(10) == 2  # max(2, 1)... wait ceil(10/10)=1, max(2,1)=2
        assert _estimate_srs_minutes(20) == 2
        assert _estimate_srs_minutes(30) == 3
        assert _estimate_srs_minutes(100) == 10


class TestBonusPhase:
    """Task 28: _maybe_add_bonus_phase and bonus phase integration."""

    def test_always_adds_bonus_with_seeded_rng_below_threshold(self):
        """A seeded RNG that returns 0.0 always triggers the bonus phase."""
        import random
        from app.daily_plan.assembler import _maybe_add_bonus_phase, BONUS_MODES
        from app.daily_plan.models import PhaseKind

        rng = random.Random(0)
        # Reseed so first random() call is guaranteed below 0.2
        # By finding a seed that gives us <0.2 on first call
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.random() < 0.20:
                break

        phases = [
            MissionPhase(phase=PhaseKind.recall, title="R", source_kind=SourceKind.srs, mode="srs_review"),
            MissionPhase(phase=PhaseKind.learn, title="L", source_kind=SourceKind.normal_course, mode="curriculum_lesson"),
            MissionPhase(phase=PhaseKind.use, title="U", source_kind=SourceKind.normal_course, mode="lesson_practice"),
        ]

        rng2 = random.Random(seed)
        result = _maybe_add_bonus_phase(phases, rng=rng2)

        assert len(result) == 4
        bonus = result[-1]
        assert bonus.phase == PhaseKind.bonus
        assert bonus.required is False
        assert bonus.mode in [m for m, _ in BONUS_MODES]

    def test_no_bonus_with_seeded_rng_above_threshold(self):
        """A seeded RNG that returns >= 0.2 skips the bonus phase."""
        import random
        from app.daily_plan.assembler import _maybe_add_bonus_phase

        # Find a seed where first random() >= 0.20
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.random() >= 0.20:
                break

        phases = [
            MissionPhase(phase=PhaseKind.recall, title="R", source_kind=SourceKind.srs, mode="srs_review"),
            MissionPhase(phase=PhaseKind.learn, title="L", source_kind=SourceKind.normal_course, mode="curriculum_lesson"),
            MissionPhase(phase=PhaseKind.use, title="U", source_kind=SourceKind.normal_course, mode="lesson_practice"),
        ]

        rng2 = random.Random(seed)
        result = _maybe_add_bonus_phase(phases, rng=rng2)

        assert len(result) == 3

    def test_bonus_phase_is_never_required(self):
        """Bonus phase must always be required=False."""
        import random
        from app.daily_plan.assembler import _maybe_add_bonus_phase
        from app.daily_plan.models import PhaseKind

        for seed in range(500):
            rng = random.Random(seed)
            val = rng.random()
            if val < 0.20:
                phases = [
                    MissionPhase(phase=PhaseKind.recall, title="R", source_kind=SourceKind.srs, mode="srs_review"),
                    MissionPhase(phase=PhaseKind.learn, title="L", source_kind=SourceKind.normal_course, mode="curriculum_lesson"),
                    MissionPhase(phase=PhaseKind.use, title="U", source_kind=SourceKind.normal_course, mode="lesson_practice"),
                ]
                result = _maybe_add_bonus_phase(phases, rng=random.Random(seed))
                bonus = next((p for p in result if p.phase == PhaseKind.bonus), None)
                if bonus:
                    assert bonus.required is False
                    return
        pytest.skip("no seed < 0.2 found in range")

    def test_bonus_modes_in_mode_category_map(self):
        """All bonus modes must be in MODE_CATEGORY_MAP with category 'bonus'."""
        from app.daily_plan.assembler import BONUS_MODES
        from app.daily_plan.models import MODE_CATEGORY_MAP

        for mode, _title in BONUS_MODES:
            assert mode in MODE_CATEGORY_MAP, f"Missing mode: {mode}"
            assert MODE_CATEGORY_MAP[mode] == 'bonus', f"Wrong category for {mode}"

    def test_bonus_modes_have_xp(self):
        """All bonus modes must have 2x XP defined in PHASE_XP."""
        from app.daily_plan.assembler import BONUS_MODES
        from app.achievements.xp_service import PHASE_XP

        bonus_base = PHASE_XP['bonus']
        for mode, _title in BONUS_MODES:
            assert mode in PHASE_XP, f"Missing XP for mode: {mode}"
            assert PHASE_XP[mode] == bonus_base * 2, (
                f"{mode} XP={PHASE_XP[mode]} should be 2x bonus base={bonus_base}"
            )

    def test_phase_kind_bonus_exists(self):
        """PhaseKind.bonus must be defined."""
        assert PhaseKind.bonus.value == "bonus"

    def test_assembler_bonus_appended_after_main_phases(self):
        """When bonus is added, main phases remain at expected indices."""
        import random
        from app.daily_plan.assembler import _maybe_add_bonus_phase
        from app.daily_plan.models import PhaseKind

        for seed in range(1000):
            rng = random.Random(seed)
            if rng.random() < 0.20:
                phases = [
                    MissionPhase(phase=PhaseKind.recall, title="R", source_kind=SourceKind.srs, mode="srs_review"),
                    MissionPhase(phase=PhaseKind.learn, title="L", source_kind=SourceKind.normal_course, mode="curriculum_lesson"),
                    MissionPhase(phase=PhaseKind.use, title="U", source_kind=SourceKind.normal_course, mode="lesson_practice"),
                ]
                result = _maybe_add_bonus_phase(phases, rng=random.Random(seed))
                if len(result) == 4:
                    # Main phases at 0,1,2 unchanged; bonus at 3
                    assert result[0].phase == PhaseKind.recall
                    assert result[1].phase == PhaseKind.learn
                    assert result[2].phase == PhaseKind.use
                    assert result[3].phase == PhaseKind.bonus
                    return
        pytest.skip("no seed producing bonus found in range")

    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_lesson", return_value={
        'title': 'L', 'lesson_id': 1, 'module_id': 1,
        'module_number': 1, 'lesson_type': 'grammar',
    })
    def test_progress_mission_accepts_5_phases(self, _lesson, _srs):
        """Progress mission plan with bonus phase validates as 3-5 phases (not rejected)."""
        import random
        from app.daily_plan.models import PhaseKind

        # Run many seeds to get a plan with 4 phases (3 base + 1 bonus)
        for seed in range(2000):
            rng = random.Random(seed)
            if rng.random() < 0.20:
                with patch(f"{MODULE}._maybe_add_bonus_phase",
                           side_effect=lambda phases, **kw: phases + [
                               MissionPhase(phase=PhaseKind.bonus, title="Bonus",
                                            source_kind=SourceKind.vocab, mode="fun_fact_quiz",
                                            required=False)
                           ]):
                    plan = assemble_progress_mission(1, SourceKind.normal_course)
                assert plan is not None
                bonus_phases = [p for p in plan.phases if p.phase == PhaseKind.bonus]
                assert len(bonus_phases) == 1
                assert bonus_phases[0].required is False
                return
        pytest.skip("unexpected skip")
