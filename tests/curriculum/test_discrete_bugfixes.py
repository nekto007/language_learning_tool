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


class TestGrammarA6:
    """A6: grammar no longer dumps the full exercise objects (answer keys +
    explanations) into the page. The client JS carries only each exercise's
    `type`; grading is server-side and explanations come back post-grade."""

    # Sentinels that must never appear on an in-progress page (not visible
    # question text — only answer-key / explanation fields).
    ANS = 'ZZSENTINELANSWER'
    ALT = 'ZZSENTINELALT'
    EXP1 = 'ZZSENTINELEXPLAINONE'
    EXP2 = 'ZZSENTINELEXPLAINTWO'

    def _make(self, db_session):
        level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
        db_session.add(level)
        db_session.commit()
        module = Module(level_id=level.id, number=1, title='M', description='d',
                        raw_content={'module': {'id': 1}})
        db_session.add(module)
        db_session.commit()
        content = {
            'title': 'Present Simple',
            'description': 'A grammar lesson.',
            'exercises': [
                {'type': 'fill_in_blank', 'prompt': 'Fill the blank: ___',
                 'answer': self.ANS, 'alternative_answers': [self.ALT],
                 'explanation': self.EXP1},
                {'type': 'multiple_choice', 'question': 'Pick one:',
                 'options': ['optionAlpha', 'optionBeta'], 'correct_answer': 0,
                 'explanation': self.EXP2},
            ],
        }
        lesson = Lessons(module_id=module.id, number=1, title='GR',
                         type='grammar', content=content)
        db_session.add(lesson)
        db_session.commit()
        return lesson

    @patch('app.curriculum.security.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_answer_keys_not_in_dom_and_js_valid(self, _a, _b, db_session, authenticated_client):
        lesson = self._make(db_session)
        resp = authenticated_client.get(f'/learn/{lesson.id}/', follow_redirects=True)
        assert resp.status_code == 200
        html = resp.data.decode()
        # In-progress page must not leak answers OR explanations anywhere.
        assert self.ANS not in html
        assert self.ALT not in html
        assert self.EXP1 not in html
        assert self.EXP2 not in html
        # The client `const exercises` array must carry only `type`.
        m = re.search(r'const exercises = (\[.*?\]);', html, re.S)
        assert m, 'const exercises array not found'
        arr = m.group(1)
        assert 'type:' in arr
        for leaked in ('answer', 'correct', 'explanation', 'alternative_answers', 'options'):
            assert leaked not in arr, f'{leaked!r} leaked into client exercises array'
        _assert_inline_js_valid(html, 'checkAnswers')

    def test_grader_returns_explanation_in_feedback(self):
        # Server feedback must carry explanation + alternatives so the client can
        # render them post-grade (they are no longer shipped to the page upfront).
        from app.curriculum.grading import process_grammar_submission
        exercises = [{
            'type': 'fill_in_blank', 'prompt': 'x', 'answer': 'am',
            'explanation': self.EXP1, 'alternative_answers': [self.ALT],
        }]
        ok = process_grammar_submission(exercises, {'0': 'am'})['feedback']['0']
        assert ok['status'] == 'correct'
        assert ok['explanation'] == self.EXP1
        assert ok['alternative_answers'] == [self.ALT]
        # Explanation also accompanies an incorrect verdict (server reveals it).
        bad = process_grammar_submission(exercises, {'0': 'wrong'})['feedback']['0']
        assert bad['status'] == 'incorrect'
        assert bad['explanation'] == self.EXP1


class TestMatchingScoreForgery:
    """Matching memory-game completion is server-graded: the client's score and
    'completed' status are not trusted. Completion requires all pairs matched
    plus plausible stats; the score is recomputed server-side."""

    def _make(self, db_session, content=None):
        level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
        db_session.add(level)
        db_session.commit()
        module = Module(level_id=level.id, number=1, title='M', description='d',
                        raw_content={'module': {'id': 1}})
        db_session.add(module)
        db_session.commit()
        lesson = Lessons(module_id=module.id, number=1, title='MG',
                         type='matching', content=(content if content is not None else {}))
        db_session.add(lesson)
        db_session.commit()
        return lesson

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_progress_endpoint_strips_client_score_and_status(self, _a, db_session, authenticated_client):
        # The forgery: POST score:100 + completed straight to the progress endpoint.
        lesson = self._make(db_session)
        r = authenticated_client.post(
            f'/curriculum/api/lesson/{lesson.id}/progress',
            json={'score': 100, 'status': 'completed'},
        )
        assert r.status_code == 200
        from app.curriculum.models import LessonProgress
        prog = LessonProgress.query.filter_by(lesson_id=lesson.id).first()
        # matching is now in _SERVER_GRADED_TYPES → score + completed are stripped.
        assert prog is None or (prog.status != 'completed' and (prog.score or 0) != 100)

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_submit_full_game_server_scores_and_completes(self, _a, db_session, authenticated_client):
        lesson = self._make(db_session)
        r = authenticated_client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={'lesson_type': 'matching', 'difficulty': 'easy',
                  'pairs_matched': 6, 'total_pairs': 6, 'moves': 12, 'time_taken': 30},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data['passed'] is True
        assert data['score'] == 100          # correctness % → XP scaling
        assert data['game_score'] > 0        # server-computed gamey score
        from app.curriculum.models import LessonProgress
        prog = LessonProgress.query.filter_by(lesson_id=lesson.id).first()
        assert prog.status == 'completed' and prog.score == 100

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_submit_rejects_degenerate_stats(self, _a, db_session, authenticated_client):
        # moves < pairs*2 is physically impossible → forgery signature → 400.
        lesson = self._make(db_session)
        r = authenticated_client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={'lesson_type': 'matching', 'difficulty': 'easy',
                  'pairs_matched': 6, 'total_pairs': 6, 'moves': 0, 'time_taken': 0},
        )
        assert r.status_code == 400
        assert r.get_json()['error'] == 'invalid_game_data'
        from app.curriculum.models import LessonProgress
        prog = LessonProgress.query.filter_by(lesson_id=lesson.id).first()
        assert prog is None or prog.status != 'completed'

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_submit_rejects_difficulty_pair_mismatch(self, _a, db_session, authenticated_client):
        # total_pairs is pinned to the declared difficulty (easy=6). A degenerate
        # 1-pair "game" — or easy claiming 8 pairs — is rejected, closing the
        # instant-complete bypass the adversarial review found.
        lesson = self._make(db_session)
        r1 = authenticated_client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={'lesson_type': 'matching', 'difficulty': 'easy',
                  'pairs_matched': 1, 'total_pairs': 1, 'moves': 2, 'time_taken': 0},
        )
        assert r1.status_code == 400 and r1.get_json()['error'] == 'invalid_game_data'
        r2 = authenticated_client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={'lesson_type': 'matching', 'difficulty': 'easy',
                  'pairs_matched': 8, 'total_pairs': 8, 'moves': 16, 'time_taken': 5},
        )
        assert r2.status_code == 400 and r2.get_json()['error'] == 'invalid_game_data'
        from app.curriculum.models import LessonProgress
        prog = LessonProgress.query.filter_by(lesson_id=lesson.id).first()
        assert prog is None or prog.status != 'completed'

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_submit_medium_difficulty_completes_with_matching_count(self, _a, db_session, authenticated_client):
        # Non-easy difficulties still complete when total_pairs matches (medium=8).
        lesson = self._make(db_session)
        r = authenticated_client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={'lesson_type': 'matching', 'difficulty': 'medium',
                  'pairs_matched': 8, 'total_pairs': 8, 'moves': 16, 'time_taken': 40},
        )
        assert r.status_code == 200
        assert r.get_json()['passed'] is True

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_submit_partial_game_not_completed(self, _a, db_session, authenticated_client):
        lesson = self._make(db_session)
        r = authenticated_client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={'lesson_type': 'matching', 'difficulty': 'easy',
                  'pairs_matched': 3, 'total_pairs': 6, 'moves': 10, 'time_taken': 30},
        )
        assert r.status_code == 200
        assert r.get_json()['passed'] is False
        from app.curriculum.models import LessonProgress
        prog = LessonProgress.query.filter_by(lesson_id=lesson.id).first()
        assert prog is None or prog.status != 'completed'

    @patch('app.curriculum.security.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_render_js_valid_and_no_client_scoring(self, _a, _b, db_session, authenticated_client):
        lesson = self._make(db_session, content={'pairs': [
            {'left': 'cat', 'right': 'кот'}, {'left': 'dog', 'right': 'собака'},
        ]})
        resp = authenticated_client.get(f'/learn/{lesson.id}/', follow_redirects=True)
        assert resp.status_code == 200
        html = resp.data.decode()
        # Client no longer computes the score or posts to the progress endpoint.
        assert 'function calculateScore' not in html
        assert '/progress' not in html or 'saveGameResults' in html  # game posts to /submit
        _assert_inline_js_valid(html, 'saveGameResults')


class TestScoreXpFindings:
    """Score/XP correctness batch from the 2026-06-19 audit."""

    def _src(self, name):
        return (LESSONS / name).read_text(encoding='utf-8')

    def test_sentence_completion_forward_on_passed(self):
        s = self._src('sentence_completion.html')
        assert 'const passed = !!data.passed' in s
        # The perfect-only forward gate is gone (it stranded a passing 4/5).
        assert 'if (isPerfect && (data.next_lesson_url' not in s

    def test_sentence_correction_forward_on_passed(self):
        s = self._src('sentence_correction.html')
        assert 'const passed = !!data.passed' in s
        assert 'if (isPerfect && (data.next_lesson_url' not in s
        # Restore replays graded result regardless of IS_COMPLETED (failed run
        # no longer reloads to a blank board) and derives passed from the verdict.
        assert 'if (Array.isArray(SAVED_STATE.item_results))' in s
        assert 'passed: !!SAVED_STATE.passed' in s

    def test_text_no_duplicate_completion_score_id_and_real_score(self):
        s = self._src('text.html')
        # The hidden form input must not steal the banner div's id (duplicate id
        # hid the banner score entirely). Check the actual input attribute form.
        assert 'value="100" id="completion-score"' not in s
        assert 'showLessonCompletion({ score: comprehensionResults.score' in s

    def test_quiz_fabricated_xp_card_removed(self):
        s = self._src('quiz.html')
        # The fabricated "+0" XP stat-card was removed (no points stat, no label).
        assert 'stat-card points' not in s
        assert 'XP получено' not in s

    def test_pronunciation_xp_not_score_scaled(self):
        src = (REPO / 'app' / 'curriculum' / 'routes' / 'lessons.py').read_text(encoding='utf-8')
        m = re.search(r'def _process_pronunciation_submission.*?(?=\n\ndef )', src, re.S)
        assert m, '_process_pronunciation_submission not found'
        body = m.group(0)
        # Honest no-mic self-assess (pron_score 0) must not halve XP.
        assert 'score=pron_score)' not in body
        assert 'db_session=db, score=None)' in body

    def _make_typed(self, db_session, lesson_type, content):
        level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
        db_session.add(level)
        db_session.commit()
        module = Module(level_id=level.id, number=1, title='M', description='d',
                        raw_content={'module': {'id': 1}})
        db_session.add(module)
        db_session.commit()
        lesson = Lessons(module_id=module.id, number=1, title='X',
                         type=lesson_type, content=content)
        db_session.add(lesson)
        db_session.commit()
        return lesson

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_shadow_reading_persists_score_100(self, _a, db_session, authenticated_client):
        lesson = self._make_typed(db_session, 'shadow_reading',
                                  {'text': 'Hello world.', 'audio_url': ''})
        r = authenticated_client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={'lesson_type': 'shadow_reading', 'self_assessed': True},
        )
        assert r.status_code == 200
        from app.curriculum.models import LessonProgress
        prog = LessonProgress.query.filter_by(lesson_id=lesson.id).first()
        # progress.score now matches the banner's 100% (was NULL before).
        assert prog.status == 'completed' and prog.score == 100.0

    @patch('app.curriculum.security.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_sentence_completion_rendered_js_valid(self, _a, _b, db_session, authenticated_client):
        lesson = self._make_typed(db_session, 'sentence_completion', {'items': [
            {'prompt': 'The cat sat on the', 'answer': 'mat'},
            {'prompt': 'She loves to read', 'answer': 'books'},
        ]})
        resp = authenticated_client.get(f'/learn/{lesson.id}/', follow_redirects=True)
        assert resp.status_code == 200
        _assert_inline_js_valid(resp.data.decode(), 'showResults')

    @patch('app.curriculum.security.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_sentence_correction_rendered_js_valid(self, _a, _b, db_session, authenticated_client):
        lesson = self._make_typed(db_session, 'sentence_correction', {'items': [
            {'incorrect_sentence': 'I has a cat.',
             'options': ['I have a cat.', 'I haves a cat.', 'I had a cat have.'],
             'correct_sentence': 'I have a cat.', 'explanation': 'Use have with I.'},
        ]})
        resp = authenticated_client.get(f'/learn/{lesson.id}/', follow_redirects=True)
        assert resp.status_code == 200
        _assert_inline_js_valid(resp.data.decode(), '_scShowSummary')


class TestP3FunctionalFixes:
    """Real functional bugs hiding in the audit's P3 tail (A9/A11/A12)."""

    def _src(self, name):
        return (LESSONS / name).read_text(encoding='utf-8')

    def test_quiz_reorder_normalize_keeps_cyrillic(self):
        # A9: the reorder in-session preview normalizer must not strip Cyrillic
        # (bare \w is ASCII). Both reorder (757) + matching (910) now Cyrillic-aware.
        s = self._src('quiz.html')
        assert s.count('а-яёА-ЯЁ') >= 2

    def test_final_test_word_button_apostrophe_safe(self):
        # A11: read the Jinja-escaped data-word, not an apostrophe-breaking arg.
        s = self._src('final_test.html')
        assert 'addWordToSentence({{ question_index }}, this.dataset.word, this)' in s
        assert "'{{ word }}'" not in s

    def test_grammar_selected_word_apostrophe_safe(self):
        # A11: no inline onclick carrying the raw word (broke on don't / I'm).
        s = self._src('grammar.html')
        assert "removeSelectedWord(${exerciseIndex}, '${word}'" not in s
        assert "removeBtn.addEventListener('click'" in s

    def test_dictation_retry_actually_resets(self):
        # A12: retry must reset progress (?reset=true), not just reload the
        # completed view (which never re-opened a fresh attempt).
        s = self._src('dictation.html')
        assert "searchParams.set('reset','true')" in s
        assert 'onclick="window.location.reload()"' not in s


class TestA8Keyboard:
    """A8: div-as-button controls are keyboard-operable (role=button + tabindex
    + Enter/Space)."""

    def _src(self, name):
        return (LESSONS / name).read_text(encoding='utf-8')

    def test_matching_cards_keyboard(self):
        s = self._src('matching.html')
        assert "cardElement.setAttribute('role', 'button')" in s
        assert 'cardElement.tabIndex = 0' in s
        assert "cardElement.addEventListener('keydown'" in s

    def test_quiz_right_option_keyboard(self):
        s = self._src('quiz.html')
        assert 'role="button" tabindex="0"' in s  # select-right-option div
        # Delegated keydown is gated on role=button so native <button> data-action
        # elements don't double-fire on Enter/Space.
        assert '[data-action][role="button"]' in s

    def test_vocabulary_dropdown_keyboard(self):
        s = self._src('vocabulary.html')
        assert 'role="button" tabindex="0" data-list-id' in s
        assert "item.addEventListener('keydown'" in s

    @patch('app.curriculum.security.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_matching_keydown_js_valid(self, _a, _b, db_session, authenticated_client):
        level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
        db_session.add(level)
        db_session.commit()
        module = Module(level_id=level.id, number=1, title='M', description='d',
                        raw_content={'module': {'id': 1}})
        db_session.add(module)
        db_session.commit()
        lesson = Lessons(module_id=module.id, number=1, title='MG', type='matching',
                         content={'pairs': [{'left': 'cat', 'right': 'кот'},
                                            {'left': 'dog', 'right': 'собака'}]})
        db_session.add(lesson)
        db_session.commit()
        resp = authenticated_client.get(f'/learn/{lesson.id}/', follow_redirects=True)
        assert resp.status_code == 200
        _assert_inline_js_valid(resp.data.decode(), 'function flipCard')
