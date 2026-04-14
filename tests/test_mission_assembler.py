from unittest.mock import patch, MagicMock

import pytest

from app.daily_plan.models import (
    MissionPlan,
    MissionType,
    PhaseKind,
    SourceKind,
)
from app.daily_plan.repair_pressure import RepairBreakdown
from app.daily_plan.assembler import (
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
        assert len(plan.phases) == 4
        assert plan.phases[0].phase == PhaseKind.recall
        assert plan.phases[0].source_kind == SourceKind.srs
        assert plan.phases[1].phase == PhaseKind.learn
        assert plan.phases[2].phase == PhaseKind.use
        assert plan.phases[3].phase == PhaseKind.check
        assert plan.phases[3].required is False

    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_lesson", return_value={
        'title': 'Урок 1', 'lesson_id': 1, 'module_id': 1,
        'module_number': 1, 'lesson_type': 'dialogue',
    })
    def test_normal_course_no_srs_gives_3_phases(self, _lesson, _srs):
        plan = assemble_progress_mission(1, SourceKind.normal_course)
        assert len(plan.phases) == 3
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
        assert len(plan.phases) == 4
        assert plan.phases[1].source_kind == SourceKind.book_course

    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_book_course_lesson", return_value={
        'course_id': 10, 'course_title': 'HP', 'lesson_id': 77,
        'day_number': 1, 'lesson_type': 'reading',
    })
    def test_book_course_no_srs_gives_3_phases(self, _bc, _srs):
        plan = assemble_progress_mission(1, SourceKind.book_course)
        assert len(plan.phases) == 3

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
        assert len(plan.phases) == 4
        assert plan.phases[0].phase == PhaseKind.recall
        assert plan.phases[0].mode == "srs_review"
        assert plan.phases[1].phase == PhaseKind.learn
        assert plan.phases[1].source_kind == SourceKind.grammar_lab
        assert plan.phases[2].phase == PhaseKind.use
        assert plan.phases[3].phase == PhaseKind.close

    @patch(f"{MODULE}._find_weak_grammar_topic", return_value=None)
    @patch(f"{MODULE}._count_grammar_due", return_value=0)
    @patch(f"{MODULE}._count_srs_due", return_value=15)
    def test_repair_srs_only_no_grammar(self, _srs, _grammar, _topic):
        plan = assemble_repair_mission(1, _high_repair())
        assert plan is not None
        assert plan.phases[1].source_kind == SourceKind.vocab
        assert plan.phases[1].mode == "vocab_drill"

    @patch(f"{MODULE}._find_weak_grammar_topic", return_value=None)
    @patch(f"{MODULE}._count_grammar_due", return_value=0)
    @patch(f"{MODULE}._count_srs_due", return_value=0)
    def test_repair_nothing_due_returns_none(self, _srs, _grammar, _topic):
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
        close = plan.phases[-1]
        assert close.phase == PhaseKind.close
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
        assert len(plan.phases) == 4
        assert plan.phases[0].phase == PhaseKind.recall
        assert plan.phases[1].phase == PhaseKind.read
        assert plan.phases[2].phase == PhaseKind.use
        assert plan.phases[3].phase == PhaseKind.check

    @patch(f"{MODULE}._count_srs_due", return_value=0)
    @patch(f"{MODULE}._find_next_book", return_value={'title': 'Gatsby', 'id': 3})
    def test_reading_no_srs_gives_3_phases(self, _book, _srs):
        plan = assemble_reading_mission(1)
        assert len(plan.phases) == 3
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
        check = plan.phases[-1]
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
        assert 3 <= len(plan.phases) <= 4

    @patch(f"{MODULE}._find_weak_grammar_topic", return_value={
        'title': 'T', 'topic_id': 1,
    })
    @patch(f"{MODULE}._count_grammar_due", return_value=5)
    @patch(f"{MODULE}._count_srs_due", return_value=5)
    def test_repair_has_exactly_4_phases(self, _srs, _grammar, _topic):
        plan = assemble_repair_mission(1, _high_repair())
        assert len(plan.phases) == 4

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
        close = plan.phases[-1]
        assert close.phase == PhaseKind.close
        assert close.mode == "success_marker"
        assert close.required is False
