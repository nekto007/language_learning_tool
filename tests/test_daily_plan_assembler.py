"""Tests for app/daily_plan/assembler.py — level-aware cold start and edge cases."""
from unittest.mock import MagicMock, patch, ANY

import pytest

ASSEMBLER_MOD = "app.daily_plan.assembler"


# ---------------------------------------------------------------------------
# assemble_repair_mission — normal (non-degenerate) path
# ---------------------------------------------------------------------------


class TestAssembleRepairMissionNormalPath:
    """assemble_repair_mission when SRS > 0 or grammar_due > 0 (no degradation)."""

    @patch(f"{ASSEMBLER_MOD}._find_weak_grammar_topic")
    @patch(f"{ASSEMBLER_MOD}._count_grammar_due", return_value=3)
    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=10)
    def test_returns_repair_plan_with_grammar_topic(self, _srs, _gram, mock_topic):
        from app.daily_plan.assembler import assemble_repair_mission
        from app.daily_plan.models import MissionType, SourceKind, PhaseKind
        from app.daily_plan.repair_pressure import RepairBreakdown

        mock_topic.return_value = {'title': 'Past Simple', 'topic_id': 7}
        breakdown = RepairBreakdown(
            overdue_srs_count=10, overdue_srs_score=0.5,
            grammar_weak_count=3, grammar_weak_score=0.3,
            failure_cluster_count=1, failure_cluster_score=0.1,
            total_score=0.65,
        )

        result = assemble_repair_mission(1, breakdown)

        assert result is not None
        assert result.mission.type == MissionType.repair
        assert 4 <= len(result.phases) <= 5
        assert any(p.phase == PhaseKind.close for p in result.phases)
        assert result.primary_source.kind == SourceKind.srs
        assert result.legacy['grammar_topic'] == {'title': 'Past Simple', 'topic_id': 7}

    @patch(f"{ASSEMBLER_MOD}._find_weak_grammar_topic", return_value=None)
    @patch(f"{ASSEMBLER_MOD}._count_grammar_due", return_value=5)
    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    def test_returns_repair_plan_without_grammar_topic(self, _srs, _gram, _topic):
        from app.daily_plan.assembler import assemble_repair_mission
        from app.daily_plan.models import MissionType, SourceKind, PhaseKind
        from app.daily_plan.repair_pressure import RepairBreakdown

        breakdown = RepairBreakdown(
            overdue_srs_count=0, overdue_srs_score=0.0,
            grammar_weak_count=5, grammar_weak_score=0.5,
            failure_cluster_count=2, failure_cluster_score=0.2,
            total_score=0.65,
        )

        result = assemble_repair_mission(1, breakdown)

        assert result is not None
        assert result.mission.type == MissionType.repair
        assert 4 <= len(result.phases) <= 5
        # When grammar_topic is None and srs_due=0, primary source falls back to vocab
        assert result.primary_source.kind == SourceKind.vocab
        # After dedup: phase[0]=guided_recall(words), phase[1] was vocab_drill(words dup)
        # → substituted to grammar_practice(grammar) to avoid duplicate category
        learn_phase = result.phases[1]
        assert learn_phase.mode == "grammar_practice"

    @patch(f"{ASSEMBLER_MOD}._find_weak_grammar_topic", return_value=None)
    @patch(f"{ASSEMBLER_MOD}._count_grammar_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=20)
    def test_srs_only_recall_phase_uses_srs_review_mode(self, _srs, _gram, _topic):
        from app.daily_plan.assembler import assemble_repair_mission
        from app.daily_plan.models import PhaseKind
        from app.daily_plan.repair_pressure import RepairBreakdown

        breakdown = RepairBreakdown(
            overdue_srs_count=20, overdue_srs_score=0.8,
            grammar_weak_count=0, grammar_weak_score=0.0,
            failure_cluster_count=0, failure_cluster_score=0.0,
            total_score=0.4,
        )

        result = assemble_repair_mission(1, breakdown)

        assert result is not None
        recall = result.phases[0]
        assert recall.phase == PhaseKind.recall
        assert recall.mode == "srs_review"


# ---------------------------------------------------------------------------
# assemble_reading_mission
# ---------------------------------------------------------------------------


class TestAssembleReadingMission:
    """Tests for assemble_reading_mission() — book reading track."""

    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._find_next_book")
    def test_returns_none_when_no_book(self, mock_book, _srs):
        from app.daily_plan.assembler import assemble_reading_mission

        mock_book.return_value = None
        result = assemble_reading_mission(1)
        assert result is None

    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._find_next_book")
    def test_returns_3_phases_when_no_srs(self, mock_book, _srs):
        from app.daily_plan.assembler import assemble_reading_mission
        from app.daily_plan.models import MissionType, SourceKind, PhaseKind

        mock_book.return_value = {'id': 3, 'title': 'Alice in Wonderland'}
        result = assemble_reading_mission(1)

        assert result is not None
        assert result.mission.type == MissionType.reading
        assert 3 <= len(result.phases) <= 4
        assert result.phases[0].phase == PhaseKind.recall
        assert result.phases[1].phase == PhaseKind.read
        assert result.phases[2].phase == PhaseKind.use
        assert result.primary_source.kind == SourceKind.books
        assert result.primary_source.id == '3'

    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=5)
    @patch(f"{ASSEMBLER_MOD}._find_next_book")
    def test_returns_4_phases_when_srs_due(self, mock_book, _srs):
        from app.daily_plan.assembler import assemble_reading_mission
        from app.daily_plan.models import PhaseKind

        mock_book.return_value = {'id': 3, 'title': 'Alice in Wonderland'}
        result = assemble_reading_mission(1)

        assert result is not None
        assert 4 <= len(result.phases) <= 5
        check = next(p for p in result.phases if p.phase == PhaseKind.check)
        assert check.required is False
        # Recall mode uses book_vocab_recall when SRS > 0
        assert result.phases[0].mode == "book_vocab_recall"

    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._find_next_book")
    def test_legacy_block_contains_book(self, mock_book, _srs):
        from app.daily_plan.assembler import assemble_reading_mission

        mock_book.return_value = {'id': 7, 'title': 'Crime and Punishment'}
        result = assemble_reading_mission(1)

        assert result is not None
        assert result.legacy == {'book_to_read': {'id': 7, 'title': 'Crime and Punishment'}}


def _mock_module(module_id: int = 10, number: int = 1) -> MagicMock:
    m = MagicMock()
    m.id = module_id
    m.number = number
    return m


def _mock_lesson(lesson_id: int = 42, module_id: int = 10, title: str = "Lesson 1") -> MagicMock:
    lesson = MagicMock()
    lesson.id = lesson_id
    lesson.module_id = module_id
    lesson.title = title
    lesson.type = "vocabulary"
    lesson.number = 1
    return lesson


# ---------------------------------------------------------------------------
# _find_next_lesson — cold start behaviour
# ---------------------------------------------------------------------------


class TestFindNextLessonColdStart:
    """Tests that verify _find_next_lesson() uses level-aware module selection
    when the user has no completed lessons (cold start)."""

    def _run(
        self,
        user_id: int,
        level_code: str,
        level_order: int,
        expected_lesson_id: int = 42,
    ) -> dict:
        """Helper: configure mocks and call _find_next_lesson."""
        from app.daily_plan.assembler import _find_next_lesson

        mock_module = _mock_module(module_id=10)
        mock_lesson = _mock_lesson(lesson_id=expected_lesson_id, module_id=10)

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value=level_code) as mock_gcl,
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=level_order) as mock_cto,
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
            patch(f"{ASSEMBLER_MOD}.Lessons") as mock_lessons_cls,
        ):
            # Cold start: no completed lesson
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = None

            # Module cold-start query chain: .join().filter().order_by().all()
            q = MagicMock()
            mock_module_cls.query.join.return_value = q
            q.filter.return_value.order_by.return_value.all.return_value = [mock_module]
            # Support the no-filter path (when order == -1, CEFR code not found)
            q.order_by.return_value.all.return_value = [mock_module]

            # Module.query.get for module metadata
            mock_module_cls.query.get.return_value = mock_module

            # Lesson query
            mock_lessons_cls.query.filter_by.return_value.order_by.return_value.first.return_value = mock_lesson

            result = _find_next_lesson(user_id=user_id)

            return {
                "result": result,
                "mock_gcl": mock_gcl,
                "mock_cto": mock_cto,
                "q": q,
            }

    def test_cold_start_b1_onboarding_calls_level_utils(self):
        """Cold start with onboarding B1 → get_user_current_cefr_level called,
        and module query uses the returned level order."""
        out = self._run(user_id=7, level_code="B1", level_order=4)
        out["mock_gcl"].assert_called_once_with(7, ANY)
        out["mock_cto"].assert_called_once_with("B1", ANY)
        assert out["result"] is not None
        assert out["result"]["lesson_id"] == 42

    def test_cold_start_no_onboarding_returns_a0_lesson(self):
        """Cold start with no onboarding → level_code='A0', order=0,
        still returns a lesson."""
        out = self._run(user_id=1, level_code="A0", level_order=0)
        out["mock_gcl"].assert_called_once_with(1, ANY)
        assert out["result"] is not None
        assert out["result"]["lesson_id"] == 42

    def test_cold_start_c1_onboarding_returns_lesson(self):
        """Cold start with C1 onboarding → level_code='C1', order=6,
        returns a lesson from the C1+ module."""
        out = self._run(user_id=3, level_code="C1", level_order=6)
        out["mock_gcl"].assert_called_once_with(3, ANY)
        out["mock_cto"].assert_called_once_with("C1", ANY)
        assert out["result"] is not None

    def test_cold_start_unknown_level_skips_cefr_filter(self):
        """When _cefr_code_to_order returns -1 (e.g. 'A0' not in DB), filter is
        skipped and the unfiltered module query is used."""
        out = self._run(user_id=2, level_code="A0", level_order=-1)
        out["mock_gcl"].assert_called_once_with(2, ANY)
        out["mock_cto"].assert_called_once_with("A0", ANY)
        assert out["result"] is not None
        assert out["result"]["lesson_id"] == 42
        # The filter must NOT have been called — verifies the no-filter code path.
        out["q"].filter.assert_not_called()

    def test_cold_start_returns_none_when_no_module_found(self):
        """Cold start → no module found at user's level → returns None."""
        from app.daily_plan.assembler import _find_next_lesson

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value="C2"),
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=7),
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
        ):
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = None
            q = MagicMock()
            mock_module_cls.query.join.return_value = q
            q.filter.return_value.order_by.return_value.all.return_value = []

            result = _find_next_lesson(user_id=5)
            assert result is None

    def test_cold_start_skips_empty_module_and_returns_next(self):
        """Cold start → first eligible module has no lessons (empty); second has a lesson.
        Must skip the empty module and return the lesson from the next one."""
        from app.daily_plan.assembler import _find_next_lesson

        empty_module = _mock_module(module_id=10, number=1)
        populated_module = _mock_module(module_id=20, number=2)
        populated_lesson = _mock_lesson(lesson_id=77, module_id=20, title="First real lesson")

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value="A1"),
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=1),
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
            patch(f"{ASSEMBLER_MOD}.Lessons") as mock_lessons_cls,
        ):
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = None

            q = MagicMock()
            mock_module_cls.query.join.return_value = q
            q.filter.return_value.order_by.return_value.all.return_value = [empty_module, populated_module]

            mock_lessons_cls.query.filter_by.return_value.order_by.return_value.first.side_effect = [
                None,            # empty_module has no lessons
                populated_lesson,  # populated_module has a lesson
            ]

            result = _find_next_lesson(user_id=9)

        assert result is not None
        assert result["lesson_id"] == 77
        assert result["module_id"] == 20


class TestFindNextLessonWithProgress:
    """Tests for _find_next_lesson() when user has prior lesson progress."""

    def test_returns_none_when_all_lessons_completed(self):
        """User has completed lessons but no next lesson exists (all curriculum done).
        Must return None — NOT fall through to cold start."""
        from app.daily_plan.assembler import _find_next_lesson

        mock_last = MagicMock()
        mock_last.lesson_id = 99
        mock_lesson = _mock_lesson(lesson_id=99, module_id=10)
        mock_lesson.number = 1
        mock_module = _mock_module(module_id=10, number=5)
        mock_module.level_id = 3

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.Lessons") as mock_lessons_cls,
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
            patch(f"{ASSEMBLER_MOD}.CEFRLevel") as mock_cefr_cls,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value="B2"),
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=5),
        ):
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = mock_last
            mock_lessons_cls.query.get.return_value = mock_lesson
            mock_module_cls.query.get.return_value = mock_module

            # Column comparisons (Lessons.number > x, Module.number > x, CEFRLevel.order > x)
            # are evaluated before .filter() is called; configure __gt__ to avoid TypeError.
            mock_lessons_cls.number.__gt__ = MagicMock(return_value=MagicMock())
            mock_module_cls.number.__gt__ = MagicMock(return_value=MagicMock())
            mock_cefr_cls.order.__gt__ = MagicMock(return_value=MagicMock())

            # effective_level_order=5 == current_level.order=6? No: 5 < 6, so no level jump.
            mock_current_level = MagicMock()
            mock_current_level.order = 6
            mock_cefr_cls.query.get.return_value = mock_current_level

            # No next lesson in same module
            mock_lessons_cls.query.filter.return_value.order_by.return_value.first.return_value = None
            # No next modules in same level
            mock_module_cls.query.filter.return_value.order_by.return_value.all.return_value = []
            # No higher CEFR levels (production code calls .all(), not .first())
            mock_cefr_cls.query.filter.return_value.order_by.return_value.all.return_value = []

            result = _find_next_lesson(user_id=42)

            assert result is None

    def test_progress_a2_with_c1_onboarding_jumps_to_c1(self):
        """User has A2 progress but C1 onboarding level.
        Effective level (C1, order=6) > current module level (A2, order=2).
        Must jump to the first C1 module lesson, not the next A2 lesson."""
        from app.daily_plan.assembler import _find_next_lesson

        mock_last = MagicMock()
        mock_last.lesson_id = 99
        mock_a2_lesson = _mock_lesson(lesson_id=99, module_id=10)
        mock_a2_lesson.number = 5
        mock_a2_module = _mock_module(module_id=10, number=3)
        mock_a2_module.level_id = 2
        mock_a2_level = MagicMock()
        mock_a2_level.order = 2  # A2 order

        mock_c1_module = _mock_module(module_id=30, number=1)
        mock_c1_lesson = _mock_lesson(lesson_id=77, module_id=30, title="C1 Lesson")

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.Lessons") as mock_lessons_cls,
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
            patch(f"{ASSEMBLER_MOD}.CEFRLevel") as mock_cefr_cls,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value="C1"),
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=6),
        ):
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = mock_last
            mock_lessons_cls.query.get.return_value = mock_a2_lesson
            # Module.query.get: first call is for the progress lesson's module (id=10),
            # second is for the found lesson's module (id=30).
            mock_module_cls.query.get.side_effect = [mock_a2_module, mock_c1_module]
            mock_cefr_cls.query.get.return_value = mock_a2_level  # current module's CEFR level
            # CEFRLevel.order >= effective_level_order is a column expression — configure __ge__.
            mock_cefr_cls.order.__ge__ = MagicMock(return_value=MagicMock())

            # Level-jump path: Module.query.join(CEFRLevel).filter(...).order_by(...).all()
            jump_q = MagicMock()
            mock_module_cls.query.join.return_value = jump_q
            jump_q.filter.return_value.order_by.return_value.all.return_value = [mock_c1_module]

            # User has NO completed lessons in the C1 module (pure onboarding scenario).
            mock_lp.query.join.return_value.filter.return_value.order_by.return_value.first.return_value = None

            # First lesson in the C1 module
            mock_lessons_cls.query.filter_by.return_value.order_by.return_value.first.return_value = mock_c1_lesson

            result = _find_next_lesson(user_id=55)

        assert result is not None
        assert result["lesson_id"] == 77
        assert result["module_id"] == 30

    def test_cefr_jump_falls_back_to_sequential_when_target_level_absent(self):
        """User has A2 progress but C1 onboarding level.
        The curriculum only contains content up to B2 — no C1 modules exist.
        Must fall back to the normal sequential scan (next A2 lesson) instead of
        returning None and triggering legacy fallback."""
        from app.daily_plan.assembler import _find_next_lesson

        mock_last = MagicMock()
        mock_last.lesson_id = 99
        mock_a2_lesson = _mock_lesson(lesson_id=99, module_id=10)
        mock_a2_lesson.number = 5
        mock_a2_module = _mock_module(module_id=10, number=3)
        mock_a2_module.level_id = 2
        mock_a2_level = MagicMock()
        mock_a2_level.order = 2  # A2

        # Next lesson in the same A2 module
        mock_next_a2_lesson = _mock_lesson(lesson_id=100, module_id=10, title="A2 Lesson 6")
        mock_next_a2_lesson.number = 6

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.Lessons") as mock_lessons_cls,
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
            patch(f"{ASSEMBLER_MOD}.CEFRLevel") as mock_cefr_cls,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value="C1"),
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=6),
        ):
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = mock_last
            mock_lessons_cls.query.get.return_value = mock_a2_lesson
            # Module.query.get: first for progress module (id=10), second for found lesson (id=10)
            mock_module_cls.query.get.side_effect = [mock_a2_module, mock_a2_module]
            mock_cefr_cls.query.get.return_value = mock_a2_level  # A2 order=2 < effective 6 → jump path

            mock_cefr_cls.order.__ge__ = MagicMock(return_value=MagicMock())
            mock_lessons_cls.number.__gt__ = MagicMock(return_value=MagicMock())

            # Level-jump path: no C1 modules in curriculum — eligible_modules is empty
            jump_q = MagicMock()
            mock_module_cls.query.join.return_value = jump_q
            jump_q.filter.return_value.order_by.return_value.all.return_value = []

            # Sequential scan: next lesson exists in the same A2 module
            mock_lessons_cls.query.filter.return_value.order_by.return_value.first.return_value = mock_next_a2_lesson

            result = _find_next_lesson(user_id=55)

        assert result is not None, "must not return None when C1 is absent — should continue from A2"
        assert result["lesson_id"] == 100
        assert result["module_id"] == 10

    def test_cefr_jump_falls_back_to_sequential_when_target_modules_have_no_lessons(self):
        """User has A2 progress but C1 onboarding level.
        C1 modules exist in the curriculum but are all empty shells (no lessons).
        Must fall back to the sequential scan (next A2 lesson) instead of returning None."""
        from app.daily_plan.assembler import _find_next_lesson

        mock_last = MagicMock()
        mock_last.lesson_id = 99
        mock_a2_lesson = _mock_lesson(lesson_id=99, module_id=10)
        mock_a2_lesson.number = 5
        mock_a2_module = _mock_module(module_id=10, number=3)
        mock_a2_module.level_id = 2
        mock_a2_level = MagicMock()
        mock_a2_level.order = 2  # A2

        mock_c1_shell = _mock_module(module_id=40, number=1)  # C1 module with no lessons

        mock_next_a2_lesson = _mock_lesson(lesson_id=101, module_id=10, title="A2 Lesson 6")
        mock_next_a2_lesson.number = 6

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.Lessons") as mock_lessons_cls,
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
            patch(f"{ASSEMBLER_MOD}.CEFRLevel") as mock_cefr_cls,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value="C1"),
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=6),
        ):
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = mock_last
            mock_lessons_cls.query.get.return_value = mock_a2_lesson
            mock_module_cls.query.get.side_effect = [mock_a2_module, mock_a2_module]
            mock_cefr_cls.query.get.return_value = mock_a2_level  # A2 order=2 < effective 6 → jump path

            mock_cefr_cls.order.__ge__ = MagicMock(return_value=MagicMock())
            mock_lessons_cls.number.__gt__ = MagicMock(return_value=MagicMock())

            # Level-jump path: one C1 module exists but has no lessons
            jump_q = MagicMock()
            mock_module_cls.query.join.return_value = jump_q
            jump_q.filter.return_value.order_by.return_value.all.return_value = [mock_c1_shell]

            # No user progress in the C1 module
            mock_lp.query.join.return_value.filter.return_value.order_by.return_value.first.return_value = None
            # C1 module has no first lesson — empty shell (both .filter_by().first() and
            # .filter_by().order_by().first() must return None for the empty-shell check)
            mock_lessons_cls.query.filter_by.return_value.first.return_value = None
            mock_lessons_cls.query.filter_by.return_value.order_by.return_value.first.return_value = None

            # Sequential scan: next lesson exists in the same A2 module
            mock_lessons_cls.query.filter.return_value.order_by.return_value.first.return_value = mock_next_a2_lesson

            result = _find_next_lesson(user_id=55)

        assert result is not None, "must not return None when target-level modules are empty shells"
        assert result["lesson_id"] == 101
        assert result["module_id"] == 10

    def test_cefr_jump_returns_none_when_all_target_lessons_completed(self):
        """User has A2 progress with C1 onboarding.
        C1 modules exist and have lessons, but all C1 lessons are already completed.
        Must return None (caller falls back to legacy) instead of regressing to A2 lessons."""
        from app.daily_plan.assembler import _find_next_lesson

        mock_last = MagicMock()
        mock_last.lesson_id = 99
        mock_a2_lesson = _mock_lesson(lesson_id=99, module_id=10)
        mock_a2_lesson.number = 5
        mock_a2_module = _mock_module(module_id=10, number=3)
        mock_a2_module.level_id = 2
        mock_a2_level = MagicMock()
        mock_a2_level.order = 2  # A2

        mock_c1_module = _mock_module(module_id=40, number=1)
        # C1 module has a lesson, but all are already completed for this user.
        mock_c1_lesson = _mock_lesson(lesson_id=200, module_id=40)

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.Lessons") as mock_lessons_cls,
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
            patch(f"{ASSEMBLER_MOD}.CEFRLevel") as mock_cefr_cls,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value="C1"),
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=6),
            patch(f"{ASSEMBLER_MOD}._next_unfinished_lesson_in_module", return_value=None),
        ):
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = mock_last
            mock_lessons_cls.query.get.return_value = mock_a2_lesson
            mock_module_cls.query.get.return_value = mock_a2_module
            mock_cefr_cls.query.get.return_value = mock_a2_level

            mock_cefr_cls.order.__ge__ = MagicMock(return_value=MagicMock())

            # Level-jump: one C1 module exists with actual lessons
            jump_q = MagicMock()
            mock_module_cls.query.join.return_value = jump_q
            jump_q.filter.return_value.order_by.return_value.all.return_value = [mock_c1_module]

            # The C1 module has content (filter_by check returns a lesson)
            mock_lessons_cls.query.filter_by.return_value.first.return_value = mock_c1_lesson

            result = _find_next_lesson(user_id=55)

        assert result is None, "must return None when target-level modules have content but all lessons done"

    def test_progress_skips_empty_same_level_module(self):
        """User has A1 progress. Next module in same level is empty;
        the one after it has a lesson. Must skip the empty module."""
        from app.daily_plan.assembler import _find_next_lesson

        mock_last = MagicMock()
        mock_last.lesson_id = 5
        mock_lesson = _mock_lesson(lesson_id=5, module_id=10)
        mock_lesson.number = 3
        mock_m1 = _mock_module(module_id=10, number=1)
        mock_m1.level_id = 1
        mock_a1_level = MagicMock()
        mock_a1_level.order = 1

        mock_m2 = _mock_module(module_id=20, number=2)  # empty
        mock_m3 = _mock_module(module_id=30, number=3)  # has lessons
        mock_lesson_m3 = _mock_lesson(lesson_id=88, module_id=30, title="M3 Lesson")

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.Lessons") as mock_lessons_cls,
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
            patch(f"{ASSEMBLER_MOD}.CEFRLevel") as mock_cefr_cls,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value="A1"),
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=1),
        ):
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = mock_last
            mock_lessons_cls.query.get.return_value = mock_lesson
            # Module.query.get: first for progress module (id=10), second for found lesson module (id=30)
            mock_module_cls.query.get.side_effect = [mock_m1, mock_m3]
            mock_cefr_cls.query.get.return_value = mock_a1_level  # A1 order=1, == effective → no jump

            mock_lessons_cls.number.__gt__ = MagicMock(return_value=MagicMock())
            mock_module_cls.number.__gt__ = MagicMock(return_value=MagicMock())

            # No prior progress in any of the next modules (M2, M3).
            mock_lp.query.join.return_value.filter.return_value.order_by.return_value.first.return_value = None

            # No next lesson in same module (M1) — via .filter()
            mock_lessons_cls.query.filter.return_value.order_by.return_value.first.return_value = None
            # _next_unfinished_lesson_in_module uses filter_by for modules with no prior progress:
            # M2 empty → None, M3 has lesson → mock_lesson_m3
            mock_lessons_cls.query.filter_by.return_value.order_by.return_value.first.side_effect = [
                None,           # first lesson in M2 (empty)
                mock_lesson_m3, # first lesson in M3
            ]
            # Same-level next modules: M2, M3
            mock_module_cls.query.filter.return_value.order_by.return_value.all.return_value = [mock_m2, mock_m3]

            result = _find_next_lesson(user_id=7)

        assert result is not None
        assert result["lesson_id"] == 88
        assert result["module_id"] == 30

    def test_progress_skips_empty_next_level_module(self):
        """User has completed the last A1 module. First B1 module is empty;
        second B1 module has a lesson. Must skip the empty module."""
        from app.daily_plan.assembler import _find_next_lesson

        mock_last = MagicMock()
        mock_last.lesson_id = 5
        mock_lesson = _mock_lesson(lesson_id=5, module_id=10)
        mock_lesson.number = 3
        mock_a1_module = _mock_module(module_id=10, number=5)
        mock_a1_module.level_id = 1
        mock_a1_level = MagicMock()
        mock_a1_level.order = 1

        mock_b1_level = MagicMock()
        mock_b1_level.id = 2
        mock_b1_module1 = _mock_module(module_id=20, number=1)  # empty
        mock_b1_module2 = _mock_module(module_id=30, number=2)  # has lesson
        mock_b1_lesson = _mock_lesson(lesson_id=99, module_id=30, title="B1 Lesson")

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.Lessons") as mock_lessons_cls,
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
            patch(f"{ASSEMBLER_MOD}.CEFRLevel") as mock_cefr_cls,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value="A1"),
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=1),
        ):
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = mock_last
            mock_lessons_cls.query.get.return_value = mock_lesson
            # Module.query.get: first for progress module (id=10), second for found lesson (id=30)
            mock_module_cls.query.get.side_effect = [mock_a1_module, mock_b1_module2]
            mock_cefr_cls.query.get.return_value = mock_a1_level  # A1 order=1, == effective → no jump

            mock_lessons_cls.number.__gt__ = MagicMock(return_value=MagicMock())
            mock_module_cls.number.__gt__ = MagicMock(return_value=MagicMock())
            mock_cefr_cls.order.__gt__ = MagicMock(return_value=MagicMock())

            # No prior progress in any of the B1 modules.
            mock_lp.query.join.return_value.filter.return_value.order_by.return_value.first.return_value = None

            # No next lesson in same module
            mock_lessons_cls.query.filter.return_value.order_by.return_value.first.return_value = None
            # No more A1 modules
            mock_module_cls.query.filter.return_value.order_by.return_value.all.return_value = []
            # Higher CEFR levels (now uses .all() — only B1 here)
            mock_cefr_cls.query.filter.return_value.order_by.return_value.all.return_value = [mock_b1_level]
            # B1 modules: first empty, second has lesson
            mock_module_cls.query.filter_by.return_value.order_by.return_value.all.return_value = [
                mock_b1_module1, mock_b1_module2,
            ]
            # Lessons in B1 modules via filter_by chain (no-prior-progress path in helper):
            # first None (empty module), then mock_b1_lesson
            mock_lessons_cls.query.filter_by.return_value.order_by.return_value.first.side_effect = [
                None,         # first B1 module is empty
                mock_b1_lesson,  # second B1 module has a lesson
            ]

            result = _find_next_lesson(user_id=8)

        assert result is not None
        assert result["lesson_id"] == 99
        assert result["module_id"] == 30

    def test_cefr_jump_resumes_from_last_completed_not_first_lesson(self):
        """User completed C1 lessons 1-3, then completed an A2 lesson (backslidng).
        Effective level = C1 (highest completed), last_completed module = A2.
        Must resume from C1 lesson 4, NOT restart at C1 lesson 1."""
        from app.daily_plan.assembler import _find_next_lesson

        mock_last = MagicMock()
        mock_last.lesson_id = 10  # an A2 lesson
        mock_a2_lesson = _mock_lesson(lesson_id=10, module_id=5)
        mock_a2_lesson.number = 2
        mock_a2_module = _mock_module(module_id=5, number=1)
        mock_a2_module.level_id = 2
        mock_a2_level = MagicMock()
        mock_a2_level.order = 2

        mock_c1_module = _mock_module(module_id=30, number=1)
        # Last completed C1 lesson
        mock_last_c1_progress = MagicMock()
        mock_last_c1_progress.lesson_id = 73
        mock_c1_completed = _mock_lesson(lesson_id=73, module_id=30, title="C1 Lesson 3")
        mock_c1_completed.number = 3
        # Next C1 lesson to do
        mock_c1_next = _mock_lesson(lesson_id=74, module_id=30, title="C1 Lesson 4")
        mock_c1_next.number = 4

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.Lessons") as mock_lessons_cls,
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
            patch(f"{ASSEMBLER_MOD}.CEFRLevel") as mock_cefr_cls,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value="C1"),
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=6),
        ):
            # Last completed overall: the A2 lesson
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = mock_last
            # Last completed in the C1 module: lesson 3
            mock_lp.query.join.return_value.filter.return_value.order_by.return_value.first.return_value = mock_last_c1_progress

            # Lesson/module lookups
            mock_lessons_cls.query.get.side_effect = [mock_a2_lesson, mock_c1_completed]
            mock_module_cls.query.get.side_effect = [mock_a2_module, mock_c1_module]
            mock_cefr_cls.query.get.return_value = mock_a2_level
            mock_cefr_cls.order.__ge__ = MagicMock(return_value=MagicMock())
            mock_lessons_cls.number.__gt__ = MagicMock(return_value=MagicMock())
            mock_lessons_cls.module_id.__eq__ = MagicMock(return_value=MagicMock())

            # Level-jump path: eligible_modules = [mock_c1_module]
            jump_q = MagicMock()
            mock_module_cls.query.join.return_value = jump_q
            jump_q.filter.return_value.order_by.return_value.all.return_value = [mock_c1_module]

            # Next lesson after C1 lesson 3 → C1 lesson 4
            mock_lessons_cls.query.filter.return_value.order_by.return_value.first.return_value = mock_c1_next

            result = _find_next_lesson(user_id=77)

        assert result is not None
        assert result["lesson_id"] == 74, "should resume from lesson 4, not restart at lesson 1"
        assert result["module_id"] == 30

    def test_progress_skips_entirely_empty_intermediate_level(self):
        """User finishes last A1 module. B1 level exists but has NO modules at all.
        C1 level has content. Must skip B1 entirely and reach C1."""
        from app.daily_plan.assembler import _find_next_lesson

        mock_last = MagicMock()
        mock_last.lesson_id = 5
        mock_lesson = _mock_lesson(lesson_id=5, module_id=10)
        mock_lesson.number = 3
        mock_a1_module = _mock_module(module_id=10, number=5)
        mock_a1_module.level_id = 1
        mock_a1_level = MagicMock()
        mock_a1_level.order = 1

        mock_b1_level = MagicMock()
        mock_b1_level.id = 2
        mock_c1_level = MagicMock()
        mock_c1_level.id = 3
        mock_c1_module = _mock_module(module_id=40, number=1)
        mock_c1_lesson = _mock_lesson(lesson_id=77, module_id=40, title="C1 Lesson")

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.Lessons") as mock_lessons_cls,
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
            patch(f"{ASSEMBLER_MOD}.CEFRLevel") as mock_cefr_cls,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value="A1"),
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=1),
        ):
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = mock_last
            mock_lessons_cls.query.get.return_value = mock_lesson
            mock_module_cls.query.get.side_effect = [mock_a1_module, mock_c1_module]
            mock_cefr_cls.query.get.return_value = mock_a1_level  # A1 order=1, == effective → no jump

            mock_lessons_cls.number.__gt__ = MagicMock(return_value=MagicMock())
            mock_module_cls.number.__gt__ = MagicMock(return_value=MagicMock())
            mock_cefr_cls.order.__gt__ = MagicMock(return_value=MagicMock())

            # No prior progress in any higher-level modules.
            mock_lp.query.join.return_value.filter.return_value.order_by.return_value.first.return_value = None

            # No next lesson in same module
            mock_lessons_cls.query.filter.return_value.order_by.return_value.first.return_value = None
            # No more A1 modules
            mock_module_cls.query.filter.return_value.order_by.return_value.all.return_value = []
            # Higher CEFR levels: B1 (empty) then C1
            mock_cefr_cls.query.filter.return_value.order_by.return_value.all.return_value = [
                mock_b1_level, mock_c1_level,
            ]
            # Module listing per level: B1 has no modules, C1 has one
            mock_module_cls.query.filter_by.return_value.order_by.return_value.all.side_effect = [
                [],               # B1 has no modules at all
                [mock_c1_module], # C1 has one module
            ]
            # Lesson in C1 module via filter_by (no-prior-progress path in helper)
            mock_lessons_cls.query.filter_by.return_value.order_by.return_value.first.return_value = mock_c1_lesson

            result = _find_next_lesson(user_id=9)

        assert result is not None
        assert result["lesson_id"] == 77
        assert result["module_id"] == 40

    def test_same_level_backfill_resumes_from_prior_progress(self):
        """User completed the last lesson of M1. M2 (same A1 level) was unlocked early
        via the 80% rule and the user already finished lessons 1-2 there.
        After backfilling M1, daily plan must resume at M2 lesson 3, not restart M2."""
        from app.daily_plan.assembler import _find_next_lesson

        mock_last = MagicMock()
        mock_last.lesson_id = 5
        mock_lesson_m1 = _mock_lesson(lesson_id=5, module_id=10)
        mock_lesson_m1.number = 3
        mock_m1 = _mock_module(module_id=10, number=1)
        mock_m1.level_id = 1
        mock_a1_level = MagicMock()
        mock_a1_level.order = 1

        mock_m2 = _mock_module(module_id=20, number=2)

        # Last completed lesson in M2 (user was there before backfilling M1)
        mock_lp_m2 = MagicMock()
        mock_lp_m2.lesson_id = 50
        mock_m2_completed = _mock_lesson(lesson_id=50, module_id=20)
        mock_m2_completed.number = 2

        # Next lesson in M2: lesson 3
        mock_m2_next = _mock_lesson(lesson_id=51, module_id=20, title="M2 Lesson 3")
        mock_m2_next.number = 3

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.Lessons") as mock_lessons_cls,
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
            patch(f"{ASSEMBLER_MOD}.CEFRLevel") as mock_cefr_cls,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value="A1"),
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=1),
        ):
            # Last overall completed: M1 lesson
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = mock_last
            # Last completed in M2 via join path (called by _next_unfinished_lesson_in_module)
            mock_lp.query.join.return_value.filter.return_value.order_by.return_value.first.return_value = mock_lp_m2

            mock_lessons_cls.query.get.side_effect = [mock_lesson_m1, mock_m2_completed]
            # Module.query.get: M1 (progress lookup), then M2 (for the returned lesson's module)
            mock_module_cls.query.get.side_effect = [mock_m1, mock_m2]
            mock_cefr_cls.query.get.return_value = mock_a1_level  # A1 order=1 == effective → no jump

            mock_lessons_cls.number.__gt__ = MagicMock(return_value=MagicMock())
            mock_module_cls.number.__gt__ = MagicMock(return_value=MagicMock())

            # No next lesson in M1 (same module), then next after M2 lesson 2 → mock_m2_next
            mock_lessons_cls.query.filter.return_value.order_by.return_value.first.side_effect = [
                None,        # no next lesson in M1
                mock_m2_next,  # lesson after completed M2 lesson 2
            ]
            # Same-level next modules: M2 only
            mock_module_cls.query.filter.return_value.order_by.return_value.all.return_value = [mock_m2]

            result = _find_next_lesson(user_id=9)

        assert result is not None
        assert result["lesson_id"] == 51, "should resume from M2 lesson 3, not restart at M2 lesson 1"
        assert result["module_id"] == 20


# ---------------------------------------------------------------------------
# _find_next_book_course_lesson — empty lessons warning
# ---------------------------------------------------------------------------


class TestFindNextBookCourseLessonEmptyWarning:
    def test_no_enrollment_returns_none(self):
        """When user has no active book course enrollment, returns None immediately."""
        from app.daily_plan.assembler import _find_next_book_course_lesson

        with patch(f"{ASSEMBLER_MOD}.BookCourseEnrollment") as mock_bce:
            mock_bce.query.filter_by.return_value.first.return_value = None
            result = _find_next_book_course_lesson(user_id=1)

        assert result is None

    def test_empty_lessons_logs_warning(self, caplog):
        """When enrollment exists but course has no lessons, a warning is logged."""
        import logging
        from app.daily_plan.assembler import _find_next_book_course_lesson

        mock_enrollment = MagicMock()
        mock_enrollment.id = 99
        mock_enrollment.course_id = 5

        # Mock db.session.query() chain used for completed_ids
        mock_db = MagicMock()
        mock_db.session.query.return_value.filter.return_value.all.return_value = []

        with (
            patch(f"{ASSEMBLER_MOD}.BookCourseEnrollment") as mock_bce,
            patch(f"{ASSEMBLER_MOD}.DailyLesson") as mock_dl,
            patch(f"{ASSEMBLER_MOD}.BookCourseModule"),
            patch(f"{ASSEMBLER_MOD}.db", mock_db),
        ):
            mock_bce.query.filter_by.return_value.first.return_value = mock_enrollment

            # Empty lesson list
            mock_dl.query.join.return_value.filter.return_value.order_by.return_value.all.return_value = []

            with caplog.at_level(logging.WARNING, logger="app.daily_plan.assembler"):
                result = _find_next_book_course_lesson(user_id=1)

            assert result is None
            assert any("no lessons found" in r.message for r in caplog.records)
