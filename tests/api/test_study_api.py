"""Integration tests for study card API endpoints.

Covers:
- GET /curriculum/api/lesson/<id>/card/session: authenticated user with valid card lesson -> 200
- GET /curriculum/api/lesson/<id>/card/session: non-existent lesson -> 400 (Invalid lesson)
- POST /study/api/update-study-item: submit correct and incorrect card answers
- POST /study/api/complete-session: missing JSON content-type -> 415
"""
import uuid
import pytest
from unittest.mock import patch, MagicMock


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def card_lesson(db_session, test_module):
    """Create a card-type lesson for SRS tests."""
    from app.curriculum.models import Lessons
    lesson = Lessons(
        module_id=test_module.id,
        number=99,
        title='Test Card Lesson',
        type='card',
        order=10,
        content={'words': []}
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


@pytest.fixture
def user_word(db_session, test_user):
    """Create a word and UserWord record for the test user."""
    from app.words.models import CollectionWords
    from app.study.models import UserWord
    word = CollectionWords(
        english_word=f'hello_{uuid.uuid4().hex[:6]}',
        russian_word='привет',
        level='A1',
    )
    db_session.add(word)
    db_session.flush()
    uw = UserWord(user_id=test_user.id, word_id=word.id)
    db_session.add(uw)
    db_session.commit()
    return word


# ── Card session (curriculum) ────────────────────────────────────────────────

@pytest.mark.smoke
def test_card_session_valid_lesson(authenticated_client, card_lesson):
    """Valid card lesson returns 200 with session data."""
    mock_session = {
        'cards': [],
        'total_cards': 0,
        'due_count': 0,
    }
    with patch('app.curriculum.security.check_lesson_access', return_value=True), \
         patch('app.curriculum.routes.api.get_card_session_for_lesson', return_value=mock_session):
        response = authenticated_client.get(
            f'/curriculum/api/lesson/{card_lesson.id}/card/session'
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert 'session' in data


def test_card_session_nonexistent_lesson(authenticated_client):
    """Non-existent lesson_id returns error response (400), not 500."""
    # lesson_id that doesn't exist in the DB
    response = authenticated_client.get('/curriculum/api/lesson/999999/card/session')
    # The handler returns 400 for invalid/missing lesson
    assert response.status_code in (400, 403, 404)
    data = response.get_json()
    assert data['success'] is False


def test_card_session_wrong_lesson_type(authenticated_client, test_lesson_vocabulary):
    """Vocabulary-type lesson (not card) returns 400 Invalid lesson."""
    with patch('app.curriculum.security.check_lesson_access', return_value=True), \
         patch('app.curriculum.routes.api.get_card_session_for_lesson', return_value={}):
        response = authenticated_client.get(
            f'/curriculum/api/lesson/{test_lesson_vocabulary.id}/card/session'
        )

    assert response.status_code == 400
    data = response.get_json()
    assert data['success'] is False
    assert 'Invalid lesson' in data.get('error', '')


def test_card_session_unauthenticated(client, card_lesson):
    """Unauthenticated request is redirected to login (302)."""
    response = client.get(f'/curriculum/api/lesson/{card_lesson.id}/card/session')
    assert response.status_code in (302, 401)


# ── Submit card answer (study SRS flashcards) ───────────────────────────────

def test_submit_card_answer_missing_json(authenticated_client):
    """POST /study/api/update-study-item without JSON returns 400."""
    response = authenticated_client.post(
        '/study/api/update-study-item',
        data='word_id=1&quality=3',
        content_type='application/x-www-form-urlencoded'
    )
    assert response.status_code == 415
    data = response.get_json()
    assert data['success'] is False


def test_submit_card_answer_missing_word_id(authenticated_client):
    """POST /study/api/update-study-item with JSON but missing word_id returns 400."""
    response = authenticated_client.post(
        '/study/api/update-study-item',
        json={'quality': 3, 'direction': 'eng-rus'}
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data['success'] is False
    assert 'word_id' in data.get('error', '')


def test_submit_card_answer_correct(authenticated_client, user_word):
    """Correct card answer (quality >= 2) is recorded successfully."""
    with patch('app.achievements.streak_service.earn_daily_coin'):
        response = authenticated_client.post(
            '/study/api/update-study-item',
            json={
                'word_id': user_word.id,
                'direction': 'eng-rus',
                'quality': 3,
            }
        )
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert 'card_id' in data


def test_submit_card_answer_incorrect(authenticated_client, user_word):
    """Incorrect card answer (quality=1) is recorded and returns 200."""
    with patch('app.achievements.streak_service.earn_daily_coin'):
        response = authenticated_client.post(
            '/study/api/update-study-item',
            json={
                'word_id': user_word.id,
                'direction': 'eng-rus',
                'quality': 1,
            }
        )
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True


# ── Complete session ─────────────────────────────────────────────────────────

def test_complete_session_missing_content_type(authenticated_client):
    """POST /study/api/complete-session without JSON content-type returns 415."""
    response = authenticated_client.post(
        '/study/api/complete-session',
        data='session_id=1',
        content_type='application/x-www-form-urlencoded'
    )
    assert response.status_code == 415


def test_complete_session_invalid_session(authenticated_client):
    """POST /study/api/complete-session with non-existent session returns graceful response."""
    response = authenticated_client.post(
        '/study/api/complete-session',
        json={'session_id': 999999}
    )
    # Should not crash — returns 200 with success=False or success=True with zero stats
    assert response.status_code == 200


# ── Get study items ──────────────────────────────────────────────────────────

def test_get_study_items_authenticated(authenticated_client):
    """Authenticated GET /study/api/get-study-items returns 200 with items list."""
    response = authenticated_client.get('/study/api/get-study-items')
    assert response.status_code == 200
    data = response.get_json()
    assert 'items' in data
    assert isinstance(data['items'], list)


def test_get_study_items_unauthenticated(client):
    """Unauthenticated GET /study/api/get-study-items redirects to login."""
    response = client.get('/study/api/get-study-items')
    assert response.status_code in (302, 401)


def test_get_study_items_invalid_deck(authenticated_client):
    """GET /study/api/get-study-items with non-existent deck_id returns standardized api_error."""
    response = authenticated_client.get('/study/api/get-study-items?deck_id=999999')
    assert response.status_code == 404
    data = response.get_json()
    assert data['success'] is False
    assert data['error'] == 'deck_not_found'
