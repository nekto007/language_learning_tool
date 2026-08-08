"""Regression tests for CNT-001 (cross-zone audit 2026-08-08).

``final_test.html`` posts a matching question twice: ``answer_<i>`` is a display
string, ``pairs_<i>`` is the JSON the grader can validate. There used to be two
independent final-test handlers; only ``final_test_lesson`` read ``pairs_<i>``,
while every first-attempt entry point (daily plan, catalogue, completion URL)
went through ``render_final_test_lesson`` — so a flawless matching answer scored
zero on the first try and correctly on the retry.

The two handlers are now one. These tests pin both entry points to the same
verdict, plus the ``BuildError`` the broken copy raised on exhausted attempts.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.curriculum.models import CEFRLevel, LessonAttempt, Lessons, Module
from tests.conftest import unique_level_code

MATCHING_PAIRS = [
    {'left': '9 o\'clock', 'right': 'AT'},
    {'left': 'Friday', 'right': 'ON'},
]


@pytest.fixture
def matching_final_test(db_session):
    level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
    db_session.add(level)
    db_session.flush()
    module = Module(
        level_id=level.id, number=1, title='M1', description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.flush()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Final Test',
        type='final_test',
        content={
            'test_sections': [{
                'title': 'Prepositions',
                'exercises': [{
                    'type': 'matching',
                    'question': 'Соотнесите время и предлог',
                    'pairs': MATCHING_PAIRS,
                }],
            }],
        },
    )
    db_session.add(lesson)
    db_session.flush()
    return lesson


def _flawless_post_body() -> dict:
    """Exactly what the template posts for a perfectly matched question."""
    return {
        'answer_0': '9 o\'clock → AT; Friday → ON',
        'pairs_0': json.dumps([
            {'left': p['left'], 'right': p['right'], 'correct': True}
            for p in MATCHING_PAIRS
        ]),
    }


class TestFlawlessMatchingScoresFull:
    """Both routes must grade the same submission identically."""

    def test_learn_route_scores_full(self, authenticated_client, matching_final_test):
        response = authenticated_client.post(
            f'/learn/{matching_final_test.id}/',
            data=_flawless_post_body(),
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['score'] == 100
        assert data['passed'] is True
        assert data['feedback']['0']['status'] == 'correct'
        assert data['feedback']['0']['user_pairs'] == [
            {'left': p['left'], 'right': p['right'], 'correct': True}
            for p in MATCHING_PAIRS
        ]

    def test_curriculum_route_scores_full(self, authenticated_client, matching_final_test):
        response = authenticated_client.post(
            f'/curriculum/lesson/{matching_final_test.id}/final_test',
            data=_flawless_post_body(),
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

        assert response.status_code == 200
        assert response.get_json()['score'] == 100

    def test_wrong_matching_still_scores_zero(self, authenticated_client, matching_final_test):
        response = authenticated_client.post(
            f'/learn/{matching_final_test.id}/',
            data={
                'answer_0': '9 o\'clock → ON; Friday → AT',
                'pairs_0': json.dumps([
                    {'left': '9 o\'clock', 'right': 'ON', 'correct': False},
                    {'left': 'Friday', 'right': 'AT', 'correct': False},
                ]),
            },
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['score'] == 0
        assert data['feedback']['0']['status'] == 'incorrect'


class TestExhaustedAttemptsRedirect:
    """The non-XHR branch used to build an endpoint that does not exist."""

    def test_non_xhr_post_over_quota_redirects_instead_of_500(
        self, authenticated_client, db_session, matching_final_test,
    ):
        user_id = authenticated_client.application.test_user.id
        started = datetime.now(timezone.utc).replace(tzinfo=None)
        for n in range(3):
            db_session.add(LessonAttempt(
                user_id=user_id,
                lesson_id=matching_final_test.id,
                attempt_number=n + 1,
                started_at=started,
                completed_at=started,
                score=10.0,
                passed=False,
            ))
        db_session.flush()

        response = authenticated_client.post(
            f'/learn/{matching_final_test.id}/',
            data=_flawless_post_body(),
        )

        assert response.status_code == 302
        assert '/final_test' in response.headers['Location']

    def test_xhr_post_over_quota_returns_429(
        self, authenticated_client, db_session, matching_final_test,
    ):
        user_id = authenticated_client.application.test_user.id
        started = datetime.now(timezone.utc).replace(tzinfo=None)
        for n in range(3):
            db_session.add(LessonAttempt(
                user_id=user_id,
                lesson_id=matching_final_test.id,
                attempt_number=n + 1,
                started_at=started,
                completed_at=started,
                score=10.0,
                passed=False,
            ))
        db_session.flush()

        response = authenticated_client.post(
            f'/learn/{matching_final_test.id}/',
            data=_flawless_post_body(),
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

        assert response.status_code == 429


class TestSingleHandler:
    """The duplicate handler is gone — one implementation, one behaviour."""

    def test_route_delegates_to_the_shared_renderer(self):
        import inspect

        from app.curriculum.routes import grammar_quiz_lessons as mod

        source = inspect.getsource(mod.final_test_lesson)
        assert 'render_final_test_lesson(lesson)' in source
        assert 'process_quiz_submission' not in source
