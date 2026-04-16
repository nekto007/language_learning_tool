"""
Tests for grammar topic slug uniqueness constraint handling.

Covers:
- Creating a topic with a duplicate slug returns 409 with 'slug_taken' error
- Successful topic creation returns 201
"""

import uuid
import pytest

from app.grammar_lab.models import GrammarTopic
from app.utils.db import db


@pytest.fixture
def auth_client(app, client, test_user):
    """Return authenticated client (regular user)."""
    from flask_login import login_user
    with app.test_request_context():
        login_user(test_user)
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_user.id)
        sess['_fresh'] = True
    return client


@pytest.fixture
def existing_topic(db_session):
    """Pre-insert a grammar topic to test duplicate slug detection."""
    unique = uuid.uuid4().hex[:8]
    slug = f'duplicate-slug-{unique}'
    topic = GrammarTopic(
        slug=slug,
        title='Existing Topic',
        title_ru='Существующая тема',
        level='A1',
        order=0,
        content={},
        estimated_time=10,
        difficulty=1,
    )
    db_session.add(topic)
    db_session.commit()
    return topic


@pytest.mark.smoke
def test_create_topic_duplicate_slug_returns_409(app, auth_client, existing_topic):
    """Creating a grammar topic with a duplicate slug returns 409 with 'slug_taken'."""
    response = auth_client.post(
        '/grammar-lab/api/topics',
        json={
            'slug': existing_topic.slug,
            'title': 'Another Topic',
            'title_ru': 'Другая тема',
            'level': 'A1',
        },
        content_type='application/json',
    )
    assert response.status_code == 409
    data = response.get_json()
    assert data['error'] == 'slug_taken'
    assert 'suggestion' in data


def test_create_topic_duplicate_slug_suggestion_appends_suffix(app, auth_client, existing_topic):
    """Suggestion for a duplicate slug appends '_2'."""
    response = auth_client.post(
        '/grammar-lab/api/topics',
        json={
            'slug': existing_topic.slug,
            'title': 'Duplicate',
            'level': 'A1',
        },
        content_type='application/json',
    )
    assert response.status_code == 409
    data = response.get_json()
    assert data['suggestion'] == f'{existing_topic.slug}_2'


def test_create_topic_success_returns_201(app, auth_client, db_session):
    """Creating a topic with a new slug returns 201."""
    unique = uuid.uuid4().hex[:8]
    response = auth_client.post(
        '/grammar-lab/api/topics',
        json={
            'slug': f'new-topic-{unique}',
            'title': 'Brand New Topic',
            'title_ru': 'Новая тема',
            'level': 'B1',
        },
        content_type='application/json',
    )
    assert response.status_code == 201
    data = response.get_json()
    assert data['slug'] == f'new-topic-{unique}'


def test_create_topic_missing_slug_returns_400(app, auth_client):
    """Omitting slug returns 400."""
    response = auth_client.post(
        '/grammar-lab/api/topics',
        json={'title': 'No Slug Topic'},
        content_type='application/json',
    )
    assert response.status_code == 400


def test_create_topic_wrong_content_type_returns_415(app, auth_client):
    """Non-JSON content type returns 415."""
    response = auth_client.post(
        '/grammar-lab/api/topics',
        data='slug=test&title=Test',
    )
    assert response.status_code == 415
