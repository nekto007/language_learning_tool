"""Discrete audit bugfixes — regression guards.

Covers the matching.html P0 (whole game was dropped by Jinja) plus the batch of
isolated P1/P2 fixes applied from the frontend audit.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module
from tests.conftest import unique_level_code

pytestmark = pytest.mark.smoke

REPO = Path(__file__).resolve().parent.parent.parent
LESSONS = REPO / 'app' / 'templates' / 'curriculum' / 'lessons'


def _make_matching_lesson(db_session):
    level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(level_id=level.id, number=1, title='M', description='d',
                    raw_content={'module': {'id': 1}})
    db_session.add(module)
    db_session.commit()
    pairs = [
        {'left': 'cat', 'right': 'кот'},
        {'left': 'dog', 'right': 'собака'},
        {'left': 'sun', 'right': 'солнце'},
        {'left': 'moon', 'right': 'луна'},
    ]
    lesson = Lessons(module_id=module.id, number=1, title='Matching',
                     type='matching', content={'pairs': pairs})
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestMatchingLessonP0Renders:
    """P0: the game lived in {% block lesson_script %} (rendered by NOTHING —
    base exposes scripts/extra_js, lesson_base exposes lesson_content). Now it
    lives in {% block scripts %} and must actually reach the page."""

    @patch('app.curriculum.security.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_game_js_reaches_the_page(self, _ml, _mm, db_session, authenticated_client):
        lesson = _make_matching_lesson(db_session)
        resp = authenticated_client.get(f'/learn/{lesson.id}/')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'function initGame' in html
        assert 'const gameConfig' in html
        assert 'async function startGame' in html


class TestTemplatePatchBatch:
    def _src(self, name):
        return (LESSONS / name).read_text(encoding='utf-8')

    def test_grammar_defines_retrylesson(self):
        s = self._src('grammar.html')
        assert 'function retryLesson()' in s
        assert '?reset=true' in s

    def test_grammar_skips_match_in_checkanswers(self):
        s = self._src('grammar.html')
        assert "if (exercise.type === 'match')" in s

    def test_final_test_results_labels_correct_pairs(self):
        assert 'Правильные пары' in self._src('final_test_results.html')

    def test_text_ordering_selector_and_progress_guard(self):
        s = self._src('text.html')
        assert 'button[data-action="submit-ordering-answer"]' in s
        assert 'Math.max(1, documentHeight - windowHeight)' in s

    def test_quiz_dead_block_and_fake_xp_removed(self):
        s = self._src('quiz.html')
        assert 'isPassed = score >= 80' not in s   # dead score>=80 contradiction
        assert 'resultsDiv.innerHTML' not in s      # dead innerHTML builder
        assert '* 10))|int' not in s                # fabricated XP*10 fallback

    def test_dictation_inflight_guard(self):
        s = self._src('dictation.html')
        assert "card.dataset.checking === '1'" in s
        assert 'delete card.dataset.checking' in s


class TestFetchErrorHandlingBatch:
    """A5: lessons must not show 'completed' + XP when the submit fetch failed
    server-side (fetch() resolves on 4xx/5xx), plus a couple isolated P2s."""

    def _src(self, name):
        return (LESSONS / name).read_text(encoding='utf-8')

    def test_collocation_checks_resp_ok(self):
        s = self._src('collocation_matching.html')
        assert 'renderSubmitError' in s
        assert '!resp.ok || data.success === false' in s

    def test_sentence_correction_no_fabricated_summary(self):
        s = self._src('sentence_correction.html')
        assert '_scShowSubmitError' in s
        assert 'if (!data || data.success === false)' in s

    def test_vocabulary_checks_resp_ok(self):
        assert "throw new Error('Save failed" in self._src('vocabulary.html')

    def test_listening_immersion_shows_visible_error(self):
        assert 'li-submit-error' in self._src('listening_immersion.html')

    def test_translation_blur_does_not_burn_attempt(self):
        s = self._src('translation.html')
        assert '_commitOnBlur' in s
        assert 'checkTranslationItem(idx, consume)' in s


class TestAriaLiveResultRegions:
    """A7/A10: result/feedback regions announce to screen readers."""

    def test_shared_completion_block_has_aria_live(self):
        s = (REPO / 'app' / 'templates' / 'lesson_base_template.html').read_text(encoding='utf-8')
        assert 'id="lesson-completion" data-completion-mode="standalone" role="status" aria-live="polite"' in s

    @pytest.mark.parametrize('name,marker', [
        ('dictation.html', 'id="dictation-results" role="status" aria-live="polite"'),
        ('quiz.html', 'class="quiz-results-compact" role="status" aria-live="polite"'),
        ('grammar.html', "'warning'}\" role=\"status\" aria-live=\"polite\""),
        ('final_test.html', 'class="question-feedback" role="status" aria-live="polite"'),
        ('listening_immersion.html', 'id="listening-gate-hint" role="status" aria-live="polite"'),
    ])
    def test_lesson_result_region_aria_live(self, name, marker):
        assert marker in (LESSONS / name).read_text(encoding='utf-8')

    def test_error_review_aria_live(self):
        s = (REPO / 'app' / 'templates' / 'curriculum' / 'error_review.html').read_text(encoding='utf-8')
        assert 'id="error-review-container" role="status" aria-live="polite"' in s


class TestRoutePatchBatch:
    def test_card_examples_projected(self):
        s = (REPO / 'app' / 'curriculum' / 'routes' / 'card_lessons.py').read_text(encoding='utf-8')
        assert "'examples': c.get('examples'" in s

    def test_idiom_grading_failed_guard(self):
        s = (REPO / 'app' / 'curriculum' / 'routes' / 'lessons.py').read_text(encoding='utf-8')
        assert 'Failed to record idiom completion' in s
        assert "result.get('error') == 'grading_failed'" in s


class TestBatch3StateAndA5Tail:
    """A5 tail (quiz/grammar/flashcard) + isolated state-bug P2s."""

    def _lsrc(self, name):
        return (LESSONS / name).read_text(encoding='utf-8')

    def test_quiz_submit_checks_resp_ok(self):
        s = self._lsrc('quiz.html')
        assert "throw new Error('HTTP ' + response.status)" in s
        assert "save_failed" in s

    def test_sentence_completion_restores_grading_shape_on_reload(self):
        assert 'if (Array.isArray(SAVED_STATE.item_results)) {' in self._lsrc('sentence_completion.html')

    def test_grammar_theory_checks_resp_ok(self):
        assert 'HTTP error! status:' in self._lsrc('grammar.html')

    def test_final_test_resume_drops_current_answer(self):
        assert 'this.state.answers[this.state.currentQuestion] = undefined;' in self._lsrc('final_test.html')

    def test_text_restore_single_source(self):
        s = self._lsrc('text.html')
        assert 'setTimeout(restoreSavedAnswers, 500)' not in s
        assert 'Object.keys(_readingAnswers).length > 0' in s

    def test_vocabulary_keydown_guards_editable_target(self):
        assert "t.tagName === 'TEXTAREA'" in self._lsrc('vocabulary.html')

    def test_flashcard_session_expired_and_complete_guards(self):
        s = (REPO / 'app' / 'static' / 'js' / 'flashcard-session.js').read_text(encoding='utf-8')
        assert '_showSessionExpiredMessage' in s
        assert "contentType.includes('application/json')" in s

    def test_card_deck_size_caps_threshold(self):
        s = (REPO / 'app' / 'curriculum' / 'routes' / 'card_lessons.py').read_text(encoding='utf-8')
        assert 'def _lesson_deck_size' in s
        assert 'min_required = min(min_required, deck_size)' in s
