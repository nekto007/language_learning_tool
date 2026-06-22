"""Discrete audit bugfixes — regression guards.

Covers the matching.html P0 (whole game was dropped by Jinja) plus the batch of
isolated P1/P2 fixes applied from the frontend audit.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def _assert_inline_js_valid(html, must_contain):
    """node --check the first inline (non-src) <script> that contains a marker.

    Catches dangling/orphaned JS (e.g. an object literal + `)` with no opening
    `(`) that a presence-only template assertion would miss. Skips when node is
    unavailable.
    """
    scripts = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S)
    target = next((s for s in scripts if must_contain in s), None)
    assert target, f'inline script containing {must_contain!r} not found'
    node = shutil.which('node')
    if not node:
        import pytest as _pt
        _pt.skip('node not available for JS syntax check')
    f = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
    f.write(target)
    f.close()
    try:
        r = subprocess.run([node, '--check', f.name], capture_output=True, text=True)
        assert r.returncode == 0, f'inline JS has a syntax error:\n{r.stderr}'
    finally:
        os.unlink(f.name)

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
        # Regression guard: the game <script> MUST close. A missing </script>
        # makes the browser parse the page markup (nav/footer) as JS — a fatal
        # SyntaxError that kills the whole game. The slice from the game config
        # to the next </script> must contain no page markup.
        start = html.index('const gameConfig')
        seg = html[start:html.index('</script>', start)]
        assert '<nav' not in seg and '<script' not in seg, 'game <script> not closed'


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


class TestStudyMatchingGameJsValid:
    """/study/matching is a STANDALONE game (study/matching.html), separate from
    the curriculum matching lesson. Its game JS had an orphaned debug call (an
    object literal + `);` with no opening `(`) that broke the whole page with
    `expected expression, got ')'`. node --check the rendered game script."""

    def test_study_matching_inline_js_parses(self, authenticated_client, study_settings):
        resp = authenticated_client.get('/study/matching')
        assert resp.status_code == 200
        _assert_inline_js_valid(resp.data.decode(), 'difficultyMultiplier')


class TestAudioFillBlankA6:
    """A6: audio_fill_blank no longer ships answers in the DOM; per-item checking
    is server-side via /check-item, which reveals the answer only when correct or
    on the final try."""

    def _make(self, db_session):
        level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
        db_session.add(level)
        db_session.commit()
        module = Module(level_id=level.id, number=1, title='M', description='d',
                        raw_content={'module': {'id': 1}})
        db_session.add(module)
        db_session.commit()
        content = {'items': [
            {'answer': 'cat', 'options': ['cat', 'dog', 'sun']},
            {'answer': 'moon'},
        ]}
        lesson = Lessons(module_id=module.id, number=1, title='AFB',
                         type='audio_fill_blank', content=content)
        db_session.add(lesson)
        db_session.commit()
        return lesson

    @patch('app.curriculum.security.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_answer_not_in_dom_and_js_valid(self, _a, _b, db_session, authenticated_client):
        lesson = self._make(db_session)
        resp = authenticated_client.get(f'/learn/{lesson.id}/', follow_redirects=True)
        assert resp.status_code == 200
        html = resp.data.decode()
        # The canonical answers must NOT be markered in the DOM.
        assert 'data-answer="cat"' not in html
        assert 'data-answer="moon"' not in html
        _assert_inline_js_valid(html, 'checkInputAnswer')

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_check_item_hides_pending_reveals_on_correct_or_final(
        self, _a, db_session, authenticated_client,
    ):
        lesson = self._make(db_session)

        def post(idx, ans, final):
            return authenticated_client.post(
                f'/curriculum/api/lesson/{lesson.id}/check-item',
                json={'index': idx, 'answer': ans, 'final': final},
            ).get_json()

        # wrong, not final → answer is NOT leaked
        r = post(0, 'dog', False)
        assert r['correct'] is False and 'answer' not in r
        # correct → answer returned
        r = post(0, 'cat', False)
        assert r['correct'] is True and r['answer'] == 'cat'
        # wrong but final try → answer revealed for the correction block
        r = post(1, 'zzz', True)
        assert r['correct'] is False and r['answer'] == 'moon'


class TestTranslationA6:
    """A6: translation no longer ships english/alternatives in the DOM; per-item
    checking is server-side via the shared check-item endpoint."""

    def _make(self, db_session):
        level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
        db_session.add(level)
        db_session.commit()
        module = Module(level_id=level.id, number=1, title='M', description='d',
                        raw_content={'module': {'id': 1}})
        db_session.add(module)
        db_session.commit()
        content = {'items': [
            {'russian': 'кот', 'english': 'cat', 'alternatives': ['the cat']},
            {'russian': 'луна', 'english': 'moon'},
        ]}
        lesson = Lessons(module_id=module.id, number=1, title='TR',
                         type='translation', content=content)
        db_session.add(lesson)
        db_session.commit()
        return lesson

    @patch('app.curriculum.security.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_answer_not_in_dom_and_js_valid(self, _a, _b, db_session, authenticated_client):
        lesson = self._make(db_session)
        resp = authenticated_client.get(f'/learn/{lesson.id}/', follow_redirects=True)
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'data-answer=' not in html
        assert 'data-alternatives=' not in html
        _assert_inline_js_valid(html, 'checkTranslationItem')

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_check_item_grades_translation(self, _a, db_session, authenticated_client):
        lesson = self._make(db_session)

        def post(idx, ans, final):
            return authenticated_client.post(
                f'/curriculum/api/lesson/{lesson.id}/check-item',
                json={'index': idx, 'answer': ans, 'final': final},
            ).get_json()

        # wrong, not final → no leak
        r = post(0, 'dog', False)
        assert r['correct'] is False and 'answer' not in r
        # accepted alternative grades correct
        r = post(0, 'the cat', False)
        assert r['correct'] is True and r['answer'] == 'cat'
        # wrong, final → revealed
        r = post(1, 'zzz', True)
        assert r['correct'] is False and r['answer'] == 'moon'


class TestSentenceCorrectionA6:
    """A6: sentence_correction (multi-item option-select) no longer ships
    correct_sentence/explanation in the DOM; each pick is graded server-side."""

    def _make(self, db_session):
        level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
        db_session.add(level)
        db_session.commit()
        module = Module(level_id=level.id, number=1, title='M', description='d',
                        raw_content={'module': {'id': 1}})
        db_session.add(module)
        db_session.commit()
        content = {'items': [
            {
                'incorrect_sentence': 'I has a cat.',
                'options': ['I have a cat.', 'I haves a cat.',
                            'I had a cat have.', 'I a cat have.'],
                'correct_sentence': 'I have a cat.',
                'explanation': 'Use "have" with the subject "I".',
            },
            {
                'incorrect_sentence': 'She go home.',
                'options': ['She goes home.', 'She going home.',
                            'She gone home.', 'She go to home.'],
                'correct_sentence': 'She goes home.',
                'explanation': 'Third person singular adds -es.',
            },
        ]}
        lesson = Lessons(module_id=module.id, number=1, title='SC',
                         type='sentence_correction', content=content)
        db_session.add(lesson)
        db_session.commit()
        return lesson

    @patch('app.curriculum.security.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_answer_not_in_dom_and_js_valid(self, _a, _b, db_session, authenticated_client):
        lesson = self._make(db_session)
        resp = authenticated_client.get(f'/learn/{lesson.id}/', follow_redirects=True)
        assert resp.status_code == 200
        html = resp.data.decode()
        # The correct option / explanation must not be embedded as data-attrs.
        assert 'data-correct=' not in html
        assert 'data-explanation=' not in html
        # And the canonical answer text itself must not leak via attributes.
        # (It appears once as a visible <button> option, which is expected;
        #  what matters is no data-* attribute reveals WHICH option is right.)
        _assert_inline_js_valid(html, '_scCheckItem')

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_check_item_grades_sentence_correction(self, _a, db_session, authenticated_client):
        lesson = self._make(db_session)

        def post(idx, ans, final):
            return authenticated_client.post(
                f'/curriculum/api/lesson/{lesson.id}/check-item',
                json={'index': idx, 'answer': ans, 'final': final},
            ).get_json()

        # wrong, not final → no leak of answer or explanation
        r = post(0, 'I haves a cat.', False)
        assert r['correct'] is False and 'answer' not in r and 'explanation' not in r
        # correct pick → answer + explanation revealed
        r = post(0, 'I have a cat.', False)
        assert r['correct'] is True
        assert r['answer'] == 'I have a cat.'
        assert r['explanation'] == 'Use "have" with the subject "I".'
        # wrong, final → revealed for the correction block
        r = post(1, 'She going home.', True)
        assert r['correct'] is False
        assert r['answer'] == 'She goes home.'
        assert r['explanation'] == 'Third person singular adds -es.'

    def test_retry_clears_revealed_answer(self):
        """Retrying a given-up item must drop its revealed answer so
        _scSaveState does not re-persist it for a now-pending item (which
        would re-ship the answer into SAVED_STATE on the next load)."""
        src = (LESSONS / 'sentence_correction.html').read_text(encoding='utf-8')
        m = re.search(r'function _scRetryGivenUp\(\)\s*\{(.*?)\n\}', src, re.S)
        assert m, '_scRetryGivenUp function not found'
        body = m.group(1)
        assert 'delete _scRevealed[i]' in body, (
            '_scRetryGivenUp must delete _scRevealed[i] when resetting an item '
            'to pending — otherwise the answer leaks back into the snapshot.'
        )
        # And the snapshot writer must only persist the answer behind the
        # _scRevealed guard (never for an unconditional/pending item).
        save = re.search(r'async function _scSaveState\(\)\s*\{(.*?)\n\}', src, re.S)
        assert save and 'if (_scRevealed[i])' in save.group(1), (
            '_scSaveState must gate correctSentence persistence on _scRevealed[i].'
        )


class TestCollocationMatchingA6:
    """A6: collocation_matching (a matching game) no longer embeds the
    phrase→translation answer key in the DOM; each pair is graded server-side."""

    def _make(self, db_session):
        level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
        db_session.add(level)
        db_session.commit()
        module = Module(level_id=level.id, number=1, title='M', description='d',
                        raw_content={'module': {'id': 1}})
        db_session.add(module)
        db_session.commit()
        content = {'pairs': [
            {'phrase': 'make a decision', 'translation': 'принять решение'},
            {'phrase': 'take a break', 'translation': 'сделать перерыв'},
            {'phrase': 'pay attention', 'translation': 'обратить внимание'},
        ]}
        lesson = Lessons(module_id=module.id, number=1, title='CM',
                         type='collocation_matching', content=content)
        db_session.add(lesson)
        db_session.commit()
        return lesson

    @patch('app.curriculum.security.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_answer_key_not_in_dom_and_js_valid(self, _a, _b, db_session, authenticated_client):
        lesson = self._make(db_session)
        resp = authenticated_client.get(f'/learn/{lesson.id}/', follow_redirects=True)
        assert resp.status_code == 200
        html = resp.data.decode()
        # The phrase→translation mapping must not be embedded anywhere.
        assert 'correctTranslation' not in html
        # In-progress page ships NO completed mapping.
        assert 'const completedPairs = [];' in html
        _assert_inline_js_valid(html, 'tryPair')

    def test_source_grades_server_side(self):
        s = (LESSONS / 'collocation_matching.html').read_text(encoding='utf-8')
        # phraseData must carry only the phrase (no answer field).
        assert 'correctTranslation' not in s
        # tryPair must go through the server check, not a local comparison.
        assert 'async function tryPair' in s
        assert '_serverCheckPair(' in s
        assert 'check-item' in s

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_check_item_grades_pairs(self, _a, db_session, authenticated_client):
        lesson = self._make(db_session)

        def post(idx, ans, final=False):
            return authenticated_client.post(
                f'/curriculum/api/lesson/{lesson.id}/check-item',
                json={'index': idx, 'answer': ans, 'final': final},
            ).get_json()

        # correct pair → correct, answer echoed
        r = post(0, 'принять решение')
        assert r['correct'] is True and r['answer'] == 'принять решение'
        # wrong pair, not final → no answer leaked
        r = post(0, 'сделать перерыв')
        assert r['correct'] is False and 'answer' not in r
        # another correct pair
        r = post(2, 'обратить внимание')
        assert r['correct'] is True
        # A6 blocker guard: the collocation client never sends final=true and
        # has no give-up UX, so the endpoint must NOT honor it — otherwise a
        # crafted {index,final:true} would dump the whole answer key.
        r = post(1, 'мимо', final=True)
        assert r['correct'] is False and 'answer' not in r
