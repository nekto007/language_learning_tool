"""Tests for the onboarding placement test."""
from __future__ import annotations

import uuid

import pytest

from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.onboarding.placement import (
    MAX_QUESTIONS,
    PLACEMENT_LEVELS,
    SESSION_KEY,
    placement_available,
    start_placement,
    submit_placement_answer,
)


@pytest.fixture
def grammar_pool(db_session):
    """4 multiple_choice упражнения на каждом уровне A1–C1."""
    exercises = {}
    for level in PLACEMENT_LEVELS:
        topic = GrammarTopic(
            slug=f'pl-{level.lower()}-{uuid.uuid4().hex[:8]}',
            title=f'Topic {level}',
            title_ru=f'Тема {level}',
            level=level,
            order=1,
        )
        db_session.add(topic)
        db_session.flush()
        exercises[level] = []
        for i in range(4):
            ex = GrammarExercise(
                topic_id=topic.id,
                exercise_type='multiple_choice',
                content={
                    'question': f'{level} question {i}?',
                    'options': ['right', 'wrong1', 'wrong2'],
                    'correct_answer': 'right',
                },
                difficulty=1,
                order=i,
            )
            db_session.add(ex)
            exercises[level].append(ex)
    db_session.commit()
    return exercises


@pytest.mark.smoke
class TestPlacementService:
    def test_unavailable_without_pool(self, db_session):
        assert placement_available() is False

    def test_available_with_pool(self, db_session, grammar_pool):
        assert placement_available() is True

    def test_start_returns_a2_question(self, db_session, grammar_pool):
        session: dict = {}
        payload = start_placement(session)
        assert payload is not None
        assert payload['number'] == 1
        assert payload['max'] == MAX_QUESTIONS
        assert payload['question']['options']
        state = session[SESSION_KEY]
        assert state['levels'] == ['A2']

    def test_correct_answers_climb_to_c1(self, db_session, grammar_pool):
        session: dict = {}
        start_placement(session)
        result = None
        for _ in range(MAX_QUESTIONS):
            state = session.get(SESSION_KEY)
            exercise_id = (state or {'asked': [None]})['asked'][-1]
            result = submit_placement_answer(session, exercise_id, 'right')
            assert result is not None
            if result['done']:
                break
        assert result['done'] is True
        assert result['recommended_level'] == 'C1'
        assert SESSION_KEY not in session

    def test_all_wrong_recommends_a1_with_early_stop(self, db_session, grammar_pool):
        session: dict = {}
        start_placement(session)
        answered = 0
        result = None
        while True:
            state = session.get(SESSION_KEY)
            if state is None:
                break
            result = submit_placement_answer(session, state['asked'][-1], 'wrong1')
            answered += 1
            if result['done']:
                break
        assert result['recommended_level'] == 'A1'
        assert answered < MAX_QUESTIONS  # ранний выход на дне лесенки

    def test_wrong_exercise_id_rejected(self, db_session, grammar_pool):
        session: dict = {}
        start_placement(session)
        assert submit_placement_answer(session, -1, 'right') is None


@pytest.mark.smoke
class TestPlacementRoutes:
    def test_start_without_content_409(self, authenticated_client):
        resp = authenticated_client.post('/onboarding/placement/start')
        assert resp.status_code == 409

    def test_full_flow_over_http(self, authenticated_client, db_session, grammar_pool):
        resp = authenticated_client.post('/onboarding/placement/start')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        question = data['question']
        resp = authenticated_client.post(
            '/onboarding/placement/answer',
            json={'exercise_id': question['id'], 'answer': question['options'][0]},
        )
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_answer_without_start_409(self, authenticated_client, db_session, grammar_pool):
        resp = authenticated_client.post(
            '/onboarding/placement/answer',
            json={'exercise_id': 1, 'answer': 'right'},
        )
        assert resp.status_code == 409
