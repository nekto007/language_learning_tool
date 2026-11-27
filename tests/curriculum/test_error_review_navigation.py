"""The error-review links lead to the actual public rule and source lesson."""

from typing import Any
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup

from app.achievements.models import StreakEvent
from app.curriculum.models import Lessons, Module
from app.daily_plan.linear.errors import log_quiz_error
from app.grammar_lab.models import GrammarTopic
from app.utils.db import db
from tests.api.test_course_receipt_expiry import receipt


def make_topic(level: str = 'A1') -> GrammarTopic:
    topic = GrammarTopic(level=level, order=1, slug='review-' + uuid4().hex[:12],
                         title='Synthetic reading rule', title_ru='Synthetic reading rule',
                         content={'introduction': 'A synthetic note about this rule.'})
    db.session.add(topic)
    db.session.flush()
    return topic


def add_error(user_id: int, lesson_id: int) -> Any:
    return log_quiz_error(user_id, lesson_id, {'question_index': 0, 'question_type': 'multiple_choice',
                         'question_text': 'Which word fits?', 'options': ['Rain', 'Bus'],
                         'user_answer': 'Bus', 'correct_answer': 'Rain'}, db)


@pytest.mark.parametrize('mode', ['direct', 'module', 'missing', 'private-direct', 'private-module', 'ambiguous'])
def test_rule_and_original_lesson_follow_real_routes(receipt: dict[str, Any], mode: str) -> None:  # noqa: F811
    client, student, lesson, other = (receipt[key] for key in ('client', 'user', 'lesson', 'other_lesson'))
    topic = make_topic('C2' if mode.startswith('private') else 'A1')
    if mode.endswith('direct'):
        lesson.grammar_topic = topic
    elif mode.endswith('module') or mode == 'ambiguous':
        other.type = 'grammar'
        other.grammar_topic = topic
        if mode == 'ambiguous':
            another = make_topic()
            db.session.add(Lessons(module_id=lesson.module_id, number=3, order=3,
                                   type='language_focus', title='Another rule', grammar_topic_id=another.id))
    add_error(student.id, lesson.id)
    db.session.commit()

    response = client.get('/learn/error-review/')
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    card = soup.select_one('.er-theory-card')
    source = card.select_one('.er-theory-lesson-list a')
    assert source['href'] == f'/learn/{lesson.id}/'
    assert 'К исходному уроку' in source.get_text()  # noqa: RUF001 -- Russian UI label.
    assert client.get(source['href']).status_code == 200

    full = card.select_one('a.er-theory-card__link')
    if mode in {'direct', 'module'}:
        assert full['href'] == f'/grammar-lab/topic/{topic.slug}'
        assert client.get(full['href']).status_code == 200
    else:
        assert full is None
        assert 'A synthetic note about this rule.' not in card.get_text()
        if mode.startswith('private'):
            assert client.get(f'/grammar-lab/topic/{topic.slug}').status_code == 404
            assert 'Synthetic reading rule' not in soup.select_one('.er-page').get_text()


def test_source_link_respects_current_course_access(receipt: dict[str, Any]) -> None:  # noqa: F811
    client, student, other = receipt['client'], receipt['user'], receipt['other_lesson']
    assert client.get(f'/learn/{other.id}/').status_code == 302
    add_error(student.id, other.id)
    db.session.commit()
    soup = BeautifulSoup(client.get('/learn/error-review/').data, 'html.parser')
    assert other.title in soup.select_one('.er-theory-lesson-list').get_text()
    assert soup.select_one('.er-theory-lesson-list a') is None


def test_empty_one_and_completed_queue_keep_one_completion(receipt: dict[str, Any]) -> None:  # noqa: F811
    client, student, lesson = receipt['client'], receipt['user'], receipt['lesson']
    review = '/learn/error-review/'
    done = '/api/daily-plan/error-review/complete'
    empty = BeautifulSoup(client.get(review).data, 'html.parser')
    assert empty.select_one('.er-empty a')['href'] == '/dashboard'
    assert empty.select_one('.er-theory-cta') is None
    error = add_error(student.id, lesson.id)
    db.session.commit()
    assert BeautifulSoup(client.get(review).data, 'html.parser').select_one('.er-theory-cta')
    for _ in range(2):
        response = client.post(done, headers=receipt['headers'], json={'error_ids': [error.id, error.id]})
        assert response.status_code == 200, response.json
        assert error.resolved_at is not None
    awards = StreakEvent.query.filter_by(user_id=student.id, event_type='xp_linear').all()
    assert len(awards) == 1
    assert BeautifulSoup(client.get(review).data, 'html.parser').select_one('.er-empty a')['href'] == '/dashboard'


def test_inferred_theory_stays_with_its_own_module(receipt: dict[str, Any]) -> None:  # noqa: F811
    client, student, first, original = (receipt[key] for key in ('client', 'user', 'lesson', 'other_lesson'))
    first_topic, second_topic = make_topic(), make_topic()
    original.type, original.grammar_topic = 'grammar', first_topic
    another_module = Module(level_id=first.module.level_id, number=2, title='Second module')
    db.session.add(another_module)
    db.session.flush()
    second = Lessons(module_id=another_module.id, number=1, order=1, type='quiz',
                     title='Second exercise', content=first.content)
    rule = Lessons(module_id=another_module.id, number=2, order=2, type='grammar',
                   title='Second rule', grammar_topic=second_topic)
    db.session.add_all([second, rule])
    db.session.flush()
    for lesson in (first, second):
        add_error(student.id, lesson.id)
    db.session.commit()
    html = BeautifulSoup(client.get('/learn/error-review/').data, 'html.parser')
    first_card, second_card = html.select('.er-theory-card')
    assert first_card.select_one('.er-theory-card__link')['href'] == f'/grammar-lab/topic/{first_topic.slug}'
    assert second_card.select_one('.er-theory-card__link')['href'] == f'/grammar-lab/topic/{second_topic.slug}'
    assert first.title in first_card.select_one('.er-theory-lesson-list').get_text()
    assert second.title in second_card.select_one('.er-theory-lesson-list').get_text()
    assert second.title not in first_card.select_one('.er-theory-lesson-list').get_text()
