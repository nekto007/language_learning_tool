"""Adversarial review guards for lesson-audit item 8."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from app.curriculum.models import LessonProgress, Lessons
from app.curriculum.routes.grammar_quiz_lessons import _dialogue_lesson_instruction
from app.curriculum.routes.lessons import _coerce_coverage
from tests.curriculum.test_quiz_polish_item8 import (
    _get_quiz,
    _lesson,
    _login,
)


def _ordering_content(translation: str) -> dict:
    return {'exercises': [{
        'type': 'ordering',
        'instruction': 'Расположите слова в правильном порядке',
        'translation': translation,
        'words': ['safe', 'is', 'This'],
        'correct': 'This is safe',
    }]}


def _dialogue_content(instructions: list[str]) -> dict:
    return {'exercises': [{
        'type': 'dialogue_completion',
        'instruction': instruction,
        'dialogue': [
            {'speaker': 'A', 'text': 'Hello!'},
            {'speaker': 'B', 'blank': True},
        ],
        'options': ['Hi!', 'Bye!'],
        'correct': 0,
    } for instruction in instructions]}


class TestUntrustedQuizCopy:

    @pytest.mark.parametrize('lesson_type,content,needle', [
        (
            'ordering_quiz',
            _ordering_content('</p><img src=x onerror=alert(1)>'),
            '&lt;/p&gt;&lt;img src=x onerror=alert(1)&gt;',
        ),
        (
            'dialogue_completion_quiz',
            _dialogue_content(['</span><img src=x onerror=alert(2)>']),
            '&lt;/span&gt;&lt;img src=x onerror=alert(2)&gt;',
        ),
    ])
    def test_translation_and_instruction_are_escaped_without_mutating_content(
        self, app, db_session, test_user, client, lesson_type, content, needle
    ):
        source = deepcopy(content)
        lesson = _lesson(db_session, 'B1', lesson_type, content)
        lesson_id = lesson.id
        _login(client, test_user)

        rendered = _get_quiz(app, client, lesson)

        assert '<img src=x onerror=' not in rendered
        assert needle in rendered
        db_session.expire_all()
        assert db_session.get(Lessons, lesson_id).content == source

    def test_instruction_tie_is_stable_and_helper_is_pure(self):
        first = '</span><b>first</b>'
        second = '<img src=x onerror=second>'
        questions = [
            {'instruction': f'  {first}  ', 'nested': {'kept': [1]}},
            {'instruction': second},
            {'instruction': ''},
        ]
        before = deepcopy(questions)

        instruction, per_item = _dialogue_lesson_instruction(questions)

        assert instruction == first
        assert per_item == ['', second, '']
        assert questions == before


class TestOrderingRevealLifecycle:

    def test_b1_translation_starts_hidden(self, app, db_session, test_user, client):
        translation = 'Это безопасно.'
        lesson = _lesson(db_session, 'B1', 'ordering_quiz', _ordering_content(translation))
        _login(client, test_user)

        rendered = _get_quiz(app, client, lesson)
        question = rendered.split('id="question-0"', 1)[1].split('<script', 1)[0]

        assert 'aria-expanded="false"' in question
        assert 'id="ordering-translation-0" hidden' in question

    def test_retry_hides_translation_until_the_new_answer(self):
        """Auto-reveal from attempt one must not leak into the retry attempt."""
        source = Path('app/templates/curriculum/lessons/quiz.html').read_text(encoding='utf-8')
        retry = source.split('startRetryPhase() {', 1)[1].split('updateProgress() {', 1)[0]
        assert 'hideOrderingTranslation(qIndex)' in retry


class TestShadowAssessmentAdversarial:

    @pytest.mark.parametrize('value', [float('inf'), float('-inf'), '1e309', '-1e309'])
    def test_non_finite_coverage_is_junk_not_full_or_empty(self, value):
        assert _coerce_coverage(value) is None

    def test_repeat_submit_updates_assessment_but_preserves_progress_payload(
        self, app, db_session, test_user, client
    ):
        lesson = _lesson(db_session, 'A2', 'shadow_reading', {
            'audio_url': '/static/audio/test.mp3',
            'text': 'The quick brown fox.',
            'translation': 'Быстрая коричневая лиса.',
        })
        _login(client, test_user)
        url = f'/curriculum/api/lesson/{lesson.id}/submit'

        first = client.post(url, json={
            'self_assessed': True,
            'rating': 'easy',
            'listen_coverage': 0.25,
            'shadow_coverage': 0.5,
            'lesson_type': 'shadow_reading',
        })
        assert first.status_code == 200 and first.get_json()['completed'] is True
        progress = db_session.query(LessonProgress).filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).one()
        progress.data = {**progress.data, 'sentinel': {'keep': True}}
        db_session.commit()

        second = client.post(url, json={
            'self_assessed': True,
            'rating': 'hard',
            'listen_coverage': 9,
            'shadow_coverage': -4,
            'lesson_type': 'shadow_reading',
        })
        assert second.status_code == 200 and second.get_json()['completed'] is True
        db_session.expire_all()
        rows = db_session.query(LessonProgress).filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).all()

        assert len(rows) == 1
        progress = rows[0]
        assert progress.status == 'completed' and progress.score == 100
        assert progress.data['sentinel'] == {'keep': True}
        assert progress.data['shadow_assessment']['rating'] == 'hard'
        assert progress.data['shadow_assessment']['listen_coverage'] == 1.0
        assert progress.data['shadow_assessment']['shadow_coverage'] == 0.0
