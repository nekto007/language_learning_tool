"""Lesson audit, item 8: quiz polish.

1. ``ordering_quiz`` shows the authored Russian translation: inline on A0-A2,
   behind a button (auto-revealed after the answer) on B1+.
2. ``dialogue_completion_quiz`` carries one lesson-level instruction; a
   per-item instruction renders only where it differs from it.
3. ``shadow_reading`` persists the self-assessment (rating + listening
   coverage) in ``progress.data`` without touching score, completion or XP.
"""

from __future__ import annotations

import pytest
from flask import url_for

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.routes.grammar_quiz_lessons import (
    DIALOGUE_DEFAULT_INSTRUCTION,
    _dialogue_lesson_instruction,
    _ordering_translation_mode,
    _quiz_display_context,
)
from app.curriculum.routes.lessons import _coerce_coverage, _store_shadow_assessment

ORDERING_TRANSLATION = 'Быстрая лиса прыгает через собаку.'
ORDERING_BUTTON = 'data-action="toggle-ordering-translation"'
LESSON_INSTRUCTION = 'Дополните диалог правильной фразой'
ODD_INSTRUCTION = 'Выберите идиому правильного регистра'


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _level(db_session, code: str) -> CEFRLevel:
    level = db_session.query(CEFRLevel).filter_by(code=code).first()
    if level is None:
        level = CEFRLevel(code=code, name=f'Level {code}', description='d', order=1)
        db_session.add(level)
        db_session.commit()
    return level


def _lesson(db_session, level_code: str, lesson_type: str, content: dict) -> Lessons:
    level = _level(db_session, level_code)
    module = Module(
        level_id=level.id, number=97, title='Item 8 module', description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(module_id=module.id, number=7, title=f'{lesson_type} item 8', type=lesson_type, content=content)
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _ordering_content() -> dict:
    return {'exercises': [{
        'type': 'ordering',
        'instruction': 'Расположите слова в правильном порядке',
        'translation': ORDERING_TRANSLATION,
        'words': ['fox', 'The', 'quick', 'jumps'],
        'correct': 'The quick fox jumps',
    }]}


def _dialogue_content(instructions: list[str]) -> dict:
    return {'exercises': [{
        'type': 'dialogue_completion',
        'instruction': text,
        'dialogue': [{'speaker': 'A', 'text': 'Hello!'}, {'speaker': 'B', 'blank': True}],
        'options': ['Hi there!', 'Goodbye.', 'Never.'],
        'correct': 0,
    } for text in instructions]}


def _get_quiz(app, client, lesson):
    with app.test_request_context():
        url = url_for('curriculum_lessons.quiz_lesson', lesson_id=lesson.id)
    resp = client.get(url)
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Ordering translation
# ---------------------------------------------------------------------------

class TestOrderingTranslationMode:
    @pytest.mark.parametrize('code, expected', [('A0', 'inline'), ('A1', 'inline'), ('A2', 'inline'),
                                                ('B1', 'reveal'), ('C1', 'reveal'), ('', 'reveal')])
    def test_mode_by_level(self, code, expected):
        lesson = type('Lesson', (), {'module': type('M', (), {'level': type('Lv', (), {'code': code})()})()})()
        assert _ordering_translation_mode(lesson) == expected

    def test_missing_relationship_falls_back_to_reveal(self):
        lesson = type('Lesson', (), {'module': None})()
        assert _ordering_translation_mode(lesson) == 'reveal'

    def test_a1_renders_translation_inline(self, app, db_session, test_user, client):
        lesson = _lesson(db_session, 'A1', 'ordering_quiz', _ordering_content())
        _login(client, test_user)
        html = _get_quiz(app, client, lesson)
        assert ORDERING_TRANSLATION in html
        assert ORDERING_BUTTON not in html
        assert 'id="ordering-translation-0" hidden' not in html

    def test_b1_hides_translation_behind_button(self, app, db_session, test_user, client):
        lesson = _lesson(db_session, 'B1', 'ordering_quiz', _ordering_content())
        _login(client, test_user)
        html = _get_quiz(app, client, lesson)
        assert ORDERING_TRANSLATION in html
        assert ORDERING_BUTTON in html
        assert 'id="ordering-translation-0" hidden' in html
        # the answer handler opens the box so the review shows the meaning
        assert 'revealOrderingTranslation(questionIndex);' in html
        # a retry of a failed attempt hides it again (inline mode is left alone)
        retry = html.split('startRetryPhase() {', 1)[1].split('updateProgress() {', 1)[0]
        assert 'hideOrderingTranslation(qIndex);' in retry
        assert "case 'toggle-ordering-translation'" in html

    def test_no_translation_renders_nothing(self, app, db_session, test_user, client):
        content = _ordering_content()
        del content['exercises'][0]['translation']
        lesson = _lesson(db_session, 'A1', 'ordering_quiz', content)
        _login(client, test_user)
        html = _get_quiz(app, client, lesson)
        question = html.split('id="question-0"')[1].split('<script')[0]
        assert 'quiz-ordering-translation' not in question


# ---------------------------------------------------------------------------
# Dialogue instruction
# ---------------------------------------------------------------------------

class TestDialogueInstruction:
    def test_majority_wins_and_items_dedupe(self):
        questions = [{'instruction': LESSON_INSTRUCTION}, {'instruction': ''}, {'instruction': ODD_INSTRUCTION},
                     {'instruction': f'  {LESSON_INSTRUCTION}  '}, {}]
        lesson_instruction, items = _dialogue_lesson_instruction(questions)
        assert lesson_instruction == LESSON_INSTRUCTION
        assert items == ['', '', ODD_INSTRUCTION, '', '']
        # pure: input untouched
        assert questions[1] == {'instruction': ''} and questions[4] == {}

    def test_tie_resolves_to_first_seen(self):
        lesson_instruction, items = _dialogue_lesson_instruction(
            [{'instruction': ODD_INSTRUCTION}, {'instruction': LESSON_INSTRUCTION}])
        assert lesson_instruction == ODD_INSTRUCTION
        assert items == ['', LESSON_INSTRUCTION]

    def test_no_authored_instruction_uses_default(self):
        lesson_instruction, items = _dialogue_lesson_instruction([{'instruction': ''}, {}])
        assert lesson_instruction == DIALOGUE_DEFAULT_INSTRUCTION
        assert items == ['', '']

    def test_display_context_only_for_dialogue_type(self):
        quiz = type('Lesson', (), {'type': 'quiz', 'module': None})()
        ctx = _quiz_display_context(quiz, [{'instruction': ODD_INSTRUCTION}])
        assert ctx['lesson_instruction'] is None and ctx['item_instructions'] is None
        dialogue = type('Lesson', (), {'type': 'dialogue_completion_quiz', 'module': None})()
        ctx = _quiz_display_context(dialogue, [{'instruction': ''}])
        assert ctx['lesson_instruction'] == DIALOGUE_DEFAULT_INSTRUCTION
        assert ctx['item_instructions'] == ['']

    def test_render_header_once_and_odd_item_only(self, app, db_session, test_user, client):
        lesson = _lesson(db_session, 'A1', 'dialogue_completion_quiz',
                         _dialogue_content([LESSON_INSTRUCTION, '', ODD_INSTRUCTION, LESSON_INSTRUCTION]))
        _login(client, test_user)
        html = _get_quiz(app, client, lesson)
        body = html.split('id="question-0"')[0]
        assert body.count(LESSON_INSTRUCTION) == 1  # header only
        questions = html.split('id="question-0"')[1].split('<script')[0]
        assert LESSON_INSTRUCTION not in questions
        assert questions.count('quiz-instruction-text-sm') == 1
        assert ODD_INSTRUCTION in questions

    def test_render_all_empty_uses_default(self, app, db_session, test_user, client):
        lesson = _lesson(db_session, 'A1', 'dialogue_completion_quiz', _dialogue_content(['', '']))
        _login(client, test_user)
        html = _get_quiz(app, client, lesson)
        assert DIALOGUE_DEFAULT_INSTRUCTION in html
        assert 'quiz-instruction-text-sm' not in html.split('id="question-0"')[1].split('<script')[0]

    def test_non_dialogue_quiz_keeps_generic_instruction(self, app, db_session, test_user, client):
        lesson = _lesson(db_session, 'A1', 'ordering_quiz', _ordering_content())
        _login(client, test_user)
        html = _get_quiz(app, client, lesson)
        assert 'Отвечайте на вопросы по одному' in html


# ---------------------------------------------------------------------------
# Shadow reading self-assessment
# ---------------------------------------------------------------------------

class TestCoerceCoverage:
    @pytest.mark.parametrize('value, expected', [
        (None, None), (True, None), ('abc', None), ([], None), (float('nan'), None),
        (float('inf'), None), (float('-inf'), None), ('1e309', None), ('-1e309', None),
        (0.5, 0.5), ('0.734', 0.73), (1.7, 1.0), (-3, 0.0), (0, 0.0),
    ])
    def test_values(self, value, expected):
        assert _coerce_coverage(value) == expected


class TestShadowAssessmentPersisted:
    def _shadow_lesson(self, db_session) -> Lessons:
        return _lesson(db_session, 'A2', 'shadow_reading', {
            'audio_url': '/static/audio/test.mp3',
            'text': 'The quick brown fox jumps over the lazy dog.',
            'translation': 'Быстрая лиса прыгает через ленивую собаку.',
        })

    def test_store_keeps_existing_data_and_drops_junk_rating(self):
        progress = LessonProgress(user_id=1, lesson_id=1, status='in_progress', data={'kept': 1})
        _store_shadow_assessment(progress, {'rating': ['hard'], 'listen_coverage': '2', 'shadow_coverage': 'x'})
        assert progress.data['kept'] == 1
        assessment = progress.data['shadow_assessment']
        assert assessment['rating'] is None
        assert assessment['listen_coverage'] == 1.0
        assert assessment['shadow_coverage'] is None
        assert assessment['assessed_at']

    def test_submit_persists_rating_and_coverage(self, app, db_session, test_user, client):
        lesson = self._shadow_lesson(db_session)
        _login(client, test_user)
        resp = client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={'self_assessed': True, 'rating': 'hard', 'listen_coverage': 0.82,
                  'shadow_coverage': 0.4, 'lesson_type': 'shadow_reading'},
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()['completed'] is True
        progress = db_session.query(LessonProgress).filter_by(user_id=test_user.id, lesson_id=lesson.id).one()
        assert progress.status == 'completed'
        assert progress.score == 100.0  # honor-system score untouched
        assessment = progress.data['shadow_assessment']
        assert assessment['rating'] == 'hard'
        assert assessment['listen_coverage'] == 0.82
        assert assessment['shadow_coverage'] == 0.4

    def test_resubmit_overwrites_without_touching_score(self, app, db_session, test_user, client):
        lesson = self._shadow_lesson(db_session)
        _login(client, test_user)
        for rating in ('easy', 'bogus'):
            resp = client.post(f'/curriculum/api/lesson/{lesson.id}/submit',
                               json={'self_assessed': True, 'rating': rating, 'lesson_type': 'shadow_reading'})
            assert resp.status_code == 200
        progress = db_session.query(LessonProgress).filter_by(user_id=test_user.id, lesson_id=lesson.id).one()
        assert progress.score == 100.0 and progress.status == 'completed'
        assessment = progress.data['shadow_assessment']
        assert assessment['rating'] is None  # junk not stored verbatim
        assert assessment['listen_coverage'] is None

    def test_template_sends_coverage(self):
        from pathlib import Path
        src = Path('app/templates/curriculum/lessons/shadow_reading.html').read_text(encoding='utf-8')
        assert 'listen_coverage: _coverageOf(_phase1Ctrl)' in src
        assert 'shadow_coverage: _coverageOf(_phase2Ctrl)' in src
        assert 'coverage: function() { return coveredRatio; }' in src
