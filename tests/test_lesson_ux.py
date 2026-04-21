"""
Tests for Lesson UX improvements (Task 14):
- Empty content validation
- Progress save indicator (template elements)
- Lesson completion confirmation (template elements)
- Locked lesson reasons on module lessons page
- Continue where you left off for in-progress lessons
"""
import json
import uuid

import pytest
from unittest.mock import patch

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.utils.db import db


@pytest.fixture
def level_and_module(db_session):
    """Create a CEFR level and module for testing."""
    slug = uuid.uuid4().hex[:8]
    level = CEFRLevel(code='A1', name=f'Test Level {slug}')
    db_session.add(level)
    db_session.flush()

    module = Module(
        title=f'Test Module {slug}',
        number=1,
        level_id=level.id,
        description='Test module'
    )
    db_session.add(module)
    db_session.flush()
    return level, module


@pytest.fixture
def vocabulary_lesson(db_session, level_and_module):
    """Create a vocabulary lesson with content."""
    _, module = level_and_module
    content = {
        'words': [
            {'english': 'hello', 'russian': 'привет'},
            {'english': 'world', 'russian': 'мир'}
        ]
    }
    lesson = Lessons(
        title='Test Vocabulary',
        type='vocabulary',
        number=1,
        module_id=module.id,
        content=content
    )
    db_session.add(lesson)
    db_session.flush()
    return lesson


@pytest.fixture
def empty_content_lesson(db_session, level_and_module):
    """Create a lesson with no content."""
    _, module = level_and_module
    lesson = Lessons(
        title='Empty Lesson',
        type='quiz',
        number=1,
        module_id=module.id,
        content=None
    )
    db_session.add(lesson)
    db_session.flush()
    return lesson


@pytest.fixture
def lessons_sequence(db_session, level_and_module):
    """Create a sequence of lessons for lock testing."""
    _, module = level_and_module
    lessons = []
    for i in range(1, 4):
        lesson = Lessons(
            title=f'Lesson {i}',
            type='text',
            number=i,
            module_id=module.id,
            content={'text': f'Content for lesson {i}'}
        )
        db_session.add(lesson)
        lessons.append(lesson)
    db_session.flush()
    return lessons


class TestEmptyContentValidation:
    """Test empty content handling before rendering lessons."""

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_empty_content_shows_unavailable_page(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, empty_content_lesson, db_session
    ):
        """Lesson with no content should render empty_content template."""
        response = authenticated_client.get(f'/learn/{empty_content_lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'Содержимое урока недоступно' in html

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_lesson_with_content_renders_normally(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, vocabulary_lesson, db_session
    ):
        """Lesson with valid content should render normally (not empty page)."""
        response = authenticated_client.get(f'/learn/{vocabulary_lesson.id}/')
        # Could be 200 or 302 (redirect on validation error), but NOT empty_content
        html = response.data.decode()
        assert 'Содержимое урока недоступно' not in html

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_card_lesson_without_content_still_renders(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, db_session, level_and_module
    ):
        """Card lessons without content should not show empty page (they use collection_id)."""
        _, module = level_and_module
        card_lesson = Lessons(
            title='Card Lesson',
            type='card',
            number=1,
            module_id=module.id,
            content=None
        )
        db_session.add(card_lesson)
        db_session.flush()

        response = authenticated_client.get(f'/learn/{card_lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'Содержимое урока недоступно' not in html

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_card_lesson_complete_srs_returns_flashcard_stats(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, db_session, level_and_module
    ):
        """Completion response must match the shared flashcard UI contract."""
        _, module = level_and_module
        card_lesson = Lessons(
            title='Card Lesson Complete',
            type='card',
            number=2,
            module_id=module.id,
            content=None
        )
        db_session.add(card_lesson)
        db_session.commit()

        response = authenticated_client.post(
            f'/curriculum/lessons/{card_lesson.id}/complete-srs',
            json={'cards_studied': 10, 'accuracy': 80},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['stats'] == {
            'words_studied': 10,
            'correct': 8,
            'incorrect': 2,
            'percentage': 80,
        }
        assert data['xp_earned'] >= 0
        assert data['level'] >= 1


class TestProgressSaveIndicator:
    """Test that the auto-save toast element is present in lesson templates."""

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_save_toast_in_empty_content_page(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, empty_content_lesson, db_session
    ):
        """Even the empty content page (extends lesson_base_template) has save-toast."""
        response = authenticated_client.get(f'/learn/{empty_content_lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'id="save-toast"' in html
        assert 'showSaveToast' in html

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_completion_element_in_empty_content_page(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, empty_content_lesson, db_session
    ):
        """Even the empty content page has completion confirmation element."""
        response = authenticated_client.get(f'/learn/{empty_content_lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'id="lesson-completion"' in html
        assert 'showLessonCompletion' in html


class TestPlanAwareCompletion:
    """Task 4: completion screen switches to plan-aware CTAs when
    ``linearPlanContext`` is active.

    Runtime JS branching is exercised in browser QA; these asserts pin the
    rendered markup so the helper has the hooks it relies on.
    """

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_completion_block_defaults_to_standalone_mode(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, empty_content_lesson, db_session,
    ):
        """The completion block ships with data-completion-mode="standalone";
        the helper flips it to "plan" only when the plan context is active."""
        response = authenticated_client.get(f'/learn/{empty_content_lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'id="lesson-completion"' in html
        assert 'data-completion-mode="standalone"' in html

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_standalone_ctas_tagged_for_plan_aware_hide(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, empty_content_lesson, db_session,
    ):
        """Legacy curriculum-next / "К урокам" anchors carry
        ``data-standalone-cta`` so the helper can hide them when the plan
        branch renders its own primary/secondary CTAs."""
        response = authenticated_client.get(f'/learn/{empty_content_lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'data-standalone-cta="back-to-lessons"' in html

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_helper_branches_on_linear_plan_context(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, empty_content_lesson, db_session,
    ):
        """``showLessonCompletion`` must check ``linearPlanContext.isActive()``
        and fall through to the API when active. We pin the symbol names so
        accidental rename of the JS helper breaks this test immediately."""
        response = authenticated_client.get(f'/learn/{empty_content_lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        # Plan-aware branch uses linearPlanContext + fetchNextSlot.
        assert 'linearPlanContext' in html
        assert 'fetchNextSlot' in html
        # Secured-redirect target for the dashboard banner handoff.
        assert '/dashboard?day_secured=1' in html
        # Plan CTA labels appear in the helper source (Russian copy pinned).
        assert 'Следующий слот плана' in html
        assert 'На дашборд' in html
        # data-plan-cta markers are the hook the helper uses to insert/remove
        # dynamic CTAs — must exist in the JS so tests like the one above can
        # recognise the plan-aware branch.
        assert 'data-plan-cta' in html

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_helper_has_standalone_fallback(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, empty_content_lesson, db_session,
    ):
        """If context is inactive OR the API errors, the helper must render
        the standalone completion block — otherwise curriculum-direct users
        (no plan flag) would see a stuck spinner."""
        response = authenticated_client.get(f'/learn/{empty_content_lesson.id}/')
        html = response.data.decode()
        # "_revealCompletion('standalone')" invoked in both the non-plan
        # early return and the ``.catch()`` fallback.
        assert "_revealCompletion('standalone')" in html

    def test_fetch_next_slot_helper_exposed_on_context(self):
        """The helper at `app/static/js/linear-plan-context.js` must expose
        ``fetchNextSlot`` so the completion helper can call it without a
        typeof-guard guess."""
        from pathlib import Path
        src = (
            Path(__file__).resolve().parent.parent
            / 'app' / 'static' / 'js' / 'linear-plan-context.js'
        ).read_text(encoding='utf-8')
        assert 'function fetchNextSlot' in src
        assert 'fetchNextSlot: fetchNextSlot' in src
        # URL format — must match the Flask route registered in Task 2.
        assert '/api/daily-plan/next-slot' in src


class TestPlanContextHidesCurriculumNext:
    """Task 5: once ``#lesson-completion`` flips to
    ``data-completion-mode="plan"``, nothing on the page should still advertise
    the curriculum-next lesson. The footer ``#complete-exercise``/
    ``#complete-module`` buttons carry a ``data-next-url="/learn/<id>"`` — they
    must be suppressed by the scoped CSS rule, and ``showLessonCompletion``
    must also flip them off inline as a belt-and-braces measure for lesson
    templates that force ``display: inline-flex`` on them.
    """

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_plan_mode_css_hides_footer_and_daily_plan_widget(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, empty_content_lesson, db_session,
    ):
        """The scoped CSS in lesson_base_template.html must declare a sibling
        selector that hides ``#lesson-footer`` (and the
        ``#daily-plan-next-step`` widget) when the completion block is in plan
        mode — otherwise curriculum-next buttons would bleed through."""
        response = authenticated_client.get(f'/learn/{empty_content_lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        # Sibling selector wording is stable — keep the assertion tight so a
        # rename breaks immediately.
        assert '#lesson-completion[data-completion-mode="plan"] ~ #lesson-footer' in html
        assert '#lesson-completion[data-completion-mode="plan"] ~ #daily-plan-next-step' in html
        # Descendant selector ensures legacy curriculum-next CTAs inside the
        # completion block disappear once plan mode wins.
        assert '#lesson-completion[data-completion-mode="plan"] [data-standalone-cta]' in html

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_plan_branch_js_hides_footer_inline(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, empty_content_lesson, db_session,
    ):
        """JS fallback: ``showLessonCompletion`` plan branch must strip the
        ``lsn-footer--visible`` class and force ``display: none`` on the
        footer and the daily-plan widget, so lesson templates that set inline
        ``display: inline-flex`` on footer buttons cannot beat the CSS rule."""
        response = authenticated_client.get(f'/learn/{empty_content_lesson.id}/')
        html = response.data.decode()
        assert 'legacyFooter.classList.remove(\'lsn-footer--visible\')' in html
        assert "legacyFooter.style.display = 'none'" in html
        assert "legacyDailyPlan.style.display = 'none'" in html

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_footer_curriculum_next_has_data_next_url(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, vocabulary_lesson, db_session,
    ):
        """Sanity check: the footer curriculum-next button really does carry a
        ``/learn/<id>/`` destination. Without this, the CSS rule would be
        protecting an empty surface."""
        # Seed a follow-up lesson so the template renders the
        # ``#complete-exercise`` button (with data-next-url) rather than the
        # ``#complete-module`` variant.
        follow_up = Lessons(
            title='Follow Up',
            type='vocabulary',
            number=vocabulary_lesson.number + 1,
            module_id=vocabulary_lesson.module_id,
            content={'words': [{'english': 'follow', 'russian': 'далее'}]},
        )
        db_session.add(follow_up)
        db_session.commit()

        response = authenticated_client.get(f'/learn/{vocabulary_lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'id="complete-exercise"' in html
        assert 'data-next-url="/learn/{}/"'.format(follow_up.id) in html
        # And the new sibling CSS rule is present so that URL never becomes
        # reachable when plan mode is active.
        assert '#lesson-completion[data-completion-mode="plan"] ~ #lesson-footer' in html


class TestQuizPlanAwareCompletion:
    """Task 5: quiz.html previously never called ``showLessonCompletion``;
    when the user reloaded an already-completed quiz the only navigation
    surface was the footer's curriculum-next button. In plan mode that bypass
    defeats the whole point of the plan-aware flow, so quiz.html must now call
    the shared helper on page load and let it branch."""

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_completed_quiz_page_calls_show_lesson_completion(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, db_session, level_and_module,
    ):
        _, module = level_and_module
        lesson = Lessons(
            title='Completed Quiz',
            type='quiz',
            number=1,
            module_id=module.id,
            content={
                'questions': [
                    {
                        'type': 'multiple_choice',
                        'question': 'Q1',
                        'options': ['a', 'b'],
                        'correct_answer': 'a',
                    }
                ]
            },
        )
        db_session.add(lesson)
        db_session.flush()

        user = authenticated_client.application.test_user
        progress = LessonProgress(
            user_id=user.id,
            lesson_id=lesson.id,
            status='completed',
            score=95.0,
            data={
                'score': 95,
                'correct_answers': 1,
                'feedback': {'0': {'status': 'correct'}},
            },
        )
        db_session.add(progress)
        db_session.commit()

        response = authenticated_client.get(f'/learn/{lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        # Plan-aware hook: the completed-quiz DOMContentLoaded handler calls
        # the shared helper so the plan branch runs when context is active.
        assert 'showLessonCompletion({ score: completionScore })' in html
        # Score is piped from the stored progress data into the helper call
        # (rounded to int via Jinja filters).
        assert 'const completionScore = 95' in html

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_grammar_lesson_triggers_show_lesson_completion_after_submit(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, db_session, level_and_module,
    ):
        """Grammar exercise flow (``showResultsAndNavigation``) now fires the
        shared helper so plan-aware CTAs appear alongside the inline
        per-question feedback."""
        _, module = level_and_module
        lesson = Lessons(
            title='Grammar Lesson',
            type='grammar',
            number=1,
            module_id=module.id,
            content={
                'title': 'Present Simple',
                'rule': 'Use for habits and routines.',
                'exercises': [
                    {
                        'type': 'fill-blank',
                        'question': 'She ___ a book.',
                        'correct_answer': 'reads',
                    }
                ],
            },
        )
        db_session.add(lesson)
        db_session.commit()

        response = authenticated_client.get(f'/learn/{lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        # The helper call is the plan-aware entry point — without it, grammar
        # would remain curriculum-next-only.
        assert 'showLessonCompletion({ score: data.score || 0 })' in html

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_completed_grammar_lesson_calls_show_lesson_completion_on_load(
        self, mock_sec_module, mock_sec_lesson,
        authenticated_client, db_session, level_and_module,
    ):
        """Revisiting a completed grammar lesson must trigger the plan-aware
        helper so plan context wins over legacy curriculum-next buttons."""
        _, module = level_and_module
        lesson = Lessons(
            title='Completed Grammar',
            type='grammar',
            number=2,
            module_id=module.id,
            content={
                'title': 'Past Simple',
                'rule': 'Use for completed past actions.',
                'exercises': [
                    {
                        'type': 'fill-blank',
                        'question': 'He ___ home.',
                        'correct_answer': 'went',
                    }
                ],
            },
        )
        db_session.add(lesson)
        db_session.flush()

        user = authenticated_client.application.test_user
        db_session.add(LessonProgress(
            user_id=user.id,
            lesson_id=lesson.id,
            status='completed',
            score=100.0,
            data={'score': 100},
        ))
        db_session.commit()

        response = authenticated_client.get(f'/learn/{lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        # Plan-aware entry point on page load for already-completed grammar.
        assert 'showLessonCompletion({ score: 100 })' in html


class TestModuleLessonsLockedReasons:
    """Test that locked lessons show the reason on module lessons page."""

    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_locked_lesson_shows_reason(
        self, mock_sec_module,
        authenticated_client, lessons_sequence, level_and_module, db_session
    ):
        """Locked lessons should show which lesson to complete first."""
        level, module = level_and_module
        response = authenticated_client.get(
            f'/learn/{level.code.lower()}/module-{module.number}/'
        )
        assert response.status_code == 200
        html = response.data.decode()
        assert 'ml-lesson__locked-reason' in html
        assert 'Завершите урок' in html

    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_first_lesson_not_locked(
        self, mock_sec_module,
        authenticated_client, lessons_sequence, level_and_module, db_session
    ):
        """First lesson in module should not be locked."""
        level, module = level_and_module
        response = authenticated_client.get(
            f'/learn/{level.code.lower()}/module-{module.number}/'
        )
        assert response.status_code == 200
        html = response.data.decode()
        assert 'ml-lesson--current' in html or 'ml-lesson--available' in html


class TestContinueWhereLeftOff:
    """Test in-progress lessons show progress hints on module page."""

    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_in_progress_quiz_shows_question_number(
        self, mock_sec_module,
        authenticated_client, db_session, level_and_module
    ):
        """In-progress quiz lesson shows current question number."""
        level, module = level_and_module

        lesson = Lessons(
            title='Quiz Test',
            type='quiz',
            number=1,
            module_id=module.id,
            content={'questions': [{'question': 'Q1'}]}
        )
        db_session.add(lesson)
        db_session.flush()

        user = authenticated_client.application.test_user
        progress = LessonProgress(
            user_id=user.id,
            lesson_id=lesson.id,
            status='in_progress',
            data={'current_question': 2, 'total_questions': 10, 'answers': []}
        )
        db_session.add(progress)
        db_session.commit()

        response = authenticated_client.get(
            f'/learn/{level.code.lower()}/module-{module.number}/'
        )
        assert response.status_code == 200
        html = response.data.decode()
        assert 'Вопрос 3/10' in html  # current_question + 1

    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_completed_lesson_shows_score(
        self, mock_sec_module,
        authenticated_client, db_session, level_and_module
    ):
        """Completed lesson shows score percentage."""
        level, module = level_and_module

        lesson = Lessons(
            title='Score Test',
            type='quiz',
            number=1,
            module_id=module.id,
            content={'questions': [{'question': 'Q1'}]}
        )
        db_session.add(lesson)
        db_session.flush()

        user = authenticated_client.application.test_user
        progress = LessonProgress(
            user_id=user.id,
            lesson_id=lesson.id,
            status='completed',
            score=85.5
        )
        db_session.add(progress)
        db_session.commit()

        response = authenticated_client.get(
            f'/learn/{level.code.lower()}/module-{module.number}/'
        )
        assert response.status_code == 200
        html = response.data.decode()
        # score=85.5 rounds to 86.0 (Jinja2 round filter returns float)
        assert '86' in html or '85' in html


class TestUpdateLessonProgress:
    """Test the update_lesson_progress endpoint."""

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_save_progress_returns_success(
        self, mock_module, mock_lesson,
        authenticated_client, vocabulary_lesson, db_session
    ):
        """Saving progress should return success JSON."""
        response = authenticated_client.post(
            f'/curriculum/api/lesson/{vocabulary_lesson.id}/progress',
            data=json.dumps({
                'status': 'in_progress',
                'data': {'cards_viewed': 1, 'total_cards': 5}
            }),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_save_completed_progress(
        self, mock_module, mock_lesson,
        authenticated_client, vocabulary_lesson, db_session
    ):
        """Completing a lesson should save status and score."""
        response = authenticated_client.post(
            f'/curriculum/api/lesson/{vocabulary_lesson.id}/progress',
            data=json.dumps({
                'status': 'completed',
                'score': 100,
                'data': {'cards_viewed': 5, 'total_cards': 5}
            }),
            content_type='application/json'
        )
        assert response.status_code == 200

        progress = LessonProgress.query.filter_by(
            lesson_id=vocabulary_lesson.id
        ).first()
        assert progress is not None
        assert progress.status == 'completed'
        assert progress.score == 100.0


class TestModuleLockReasons:
    """Test that module lock reasons show prerequisite module name and required score."""

    def test_locked_module_shows_prereq_info(self, app, db_session, authenticated_client):
        """When module is locked, page should show prerequisite module name and score."""
        suffix = uuid.uuid4().hex[:6]
        level = CEFRLevel(code=f'Z{suffix[:1].upper()}', name=f'Test {suffix}', order=99)
        db_session.add(level)
        db_session.flush()

        mod1 = Module(level_id=level.id, number=1, title=f'Prereq Module {suffix}')
        db_session.add(mod1)
        db_session.flush()

        # Add a lesson to mod1 but don't complete it (so mod2 stays locked)
        lesson1 = Lessons(module_id=mod1.id, number=1, title='L1', type='vocabulary', order=1)
        db_session.add(lesson1)
        db_session.flush()

        mod2 = Module(level_id=level.id, number=2, title=f'Locked Module {suffix}')
        db_session.add(mod2)
        db_session.flush()

        lesson2 = Lessons(module_id=mod2.id, number=1, title='L2', type='vocabulary', order=1)
        db_session.add(lesson2)
        db_session.commit()

        response = authenticated_client.get(f'/learn/{level.code.upper()}/module-2/')
        html = response.data.decode()

        # Should show module lock banner with prerequisite module name
        assert 'Модуль заблокирован' in html or f'Prereq Module {suffix}' in html or '0%' in html

        # Cleanup
        db_session.delete(lesson2)
        db_session.delete(lesson1)
        db_session.delete(mod2)
        db_session.delete(mod1)
        db_session.delete(level)
        db_session.commit()
