"""Tests for grammar_lab routes: HTML pages and JSON API endpoints."""
import uuid
import pytest
from unittest.mock import patch, MagicMock

from app.grammar_lab.models import GrammarTopic, GrammarExercise, UserGrammarExercise


@pytest.fixture
def grammar_topic(db_session):
    slug = f"test-topic-{uuid.uuid4().hex[:8]}"
    topic = GrammarTopic(
        slug=slug,
        title="Present Perfect",
        title_ru="Настоящее совершённое",
        level="B1",
        order=1,
        content={
            "introduction": "The present perfect is used for actions connected to the present.",
            "sections": [{"subtitle": "Formation", "description": "have/has + V3"}],
        },
        estimated_time=15,
        difficulty=2,
    )
    db_session.add(topic)
    db_session.commit()
    return topic


@pytest.fixture
def grammar_exercise(db_session, grammar_topic):
    exercise = GrammarExercise(
        topic_id=grammar_topic.id,
        exercise_type="fill_blank",
        content={
            "question": "I ___ (to be) a student.",
            "correct_answer": "am",
            "options": ["am", "is", "are", "be"],
            "explanation": "With pronoun I, use am",
        },
        difficulty=1,
        order=1,
    )
    db_session.add(exercise)
    db_session.commit()
    return exercise


# ==================== HTML Pages (Public) ====================


class TestIndex:
    """GET /grammar-lab/"""

    @pytest.mark.smoke
    def test_index_anonymous(self, client, db_session):
        resp = client.get("/grammar-lab/")
        assert resp.status_code == 200

    def test_index_authenticated(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/")
        assert resp.status_code == 200


class TestTopics:
    """GET /grammar-lab/topics and /grammar-lab/topics/<level>"""

    @pytest.mark.smoke
    def test_topics_list(self, client, db_session):
        resp = client.get("/grammar-lab/topics")
        assert resp.status_code == 200

    def test_topics_by_level(self, client, db_session):
        resp = client.get("/grammar-lab/topics/B1")
        assert resp.status_code == 200

    def test_topics_authenticated(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/topics")
        assert resp.status_code == 200


class TestTopicDetail:
    """GET /grammar-lab/topic/<id>"""

    @pytest.mark.smoke
    def test_topic_detail_exists(self, client, db_session, grammar_topic):
        resp = client.get(f"/grammar-lab/topic/{grammar_topic.id}")
        assert resp.status_code == 200
        assert b"Present Perfect" in resp.data

    def test_topic_detail_missing_redirects(self, client, db_session):
        resp = client.get("/grammar-lab/topic/999999")
        assert resp.status_code == 302
        assert "/grammar-lab/topics" in resp.headers["Location"]

    def test_topic_detail_authenticated(self, authenticated_client, db_session, grammar_topic):
        resp = authenticated_client.get(f"/grammar-lab/topic/{grammar_topic.id}")
        assert resp.status_code == 200


# ==================== HTML Pages (Auth Required) ====================


class TestPractice:
    """GET /grammar-lab/practice and /grammar-lab/practice/topic/<id>"""

    def test_practice_requires_auth(self, client):
        resp = client.get("/grammar-lab/practice")
        assert resp.status_code in (302, 401)

    @pytest.mark.smoke
    def test_practice_mixed_authenticated(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/practice")
        assert resp.status_code == 200

    def test_practice_topic_specific(self, authenticated_client, db_session, grammar_topic, grammar_exercise):
        resp = authenticated_client.get(f"/grammar-lab/practice/topic/{grammar_topic.id}")
        assert resp.status_code == 200

    def test_practice_missing_topic_redirects(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/practice/topic/999999")
        assert resp.status_code == 302


class TestStats:
    """GET /grammar-lab/stats"""

    def test_stats_requires_auth(self, client):
        resp = client.get("/grammar-lab/stats")
        assert resp.status_code in (302, 401)

    @pytest.mark.smoke
    def test_stats_authenticated(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/stats")
        assert resp.status_code == 200


# ==================== JSON API Endpoints ====================


class TestApiTopics:
    """GET /grammar-lab/api/topics"""

    def test_api_topics_requires_auth(self, client):
        resp = client.get("/grammar-lab/api/topics")
        assert resp.status_code in (302, 401)

    @pytest.mark.smoke
    def test_api_topics(self, authenticated_client, db_session, grammar_topic):
        resp = authenticated_client.get("/grammar-lab/api/topics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_api_topics_filter_level(self, authenticated_client, db_session, grammar_topic):
        resp = authenticated_client.get("/grammar-lab/api/topics?level=B1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)


class TestApiLevels:
    """GET /grammar-lab/api/levels"""

    def test_api_levels_requires_auth(self, client):
        resp = client.get("/grammar-lab/api/levels")
        assert resp.status_code in (302, 401)

    def test_api_levels(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/api/levels")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)


class TestApiTopicDetail:
    """GET /grammar-lab/api/topic/<id>"""

    def test_api_topic_detail_requires_auth(self, client, grammar_topic):
        resp = client.get(f"/grammar-lab/api/topic/{grammar_topic.id}")
        assert resp.status_code in (302, 401)

    @pytest.mark.smoke
    def test_api_topic_detail(self, authenticated_client, db_session, grammar_topic):
        resp = authenticated_client.get(f"/grammar-lab/api/topic/{grammar_topic.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["title"] == "Present Perfect"

    def test_api_topic_detail_not_found(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/api/topic/999999")
        assert resp.status_code == 404


class TestApiTopicExercises:
    """GET /grammar-lab/api/topic/<id>/exercises"""

    def test_api_exercises_requires_auth(self, client, grammar_topic):
        resp = client.get(f"/grammar-lab/api/topic/{grammar_topic.id}/exercises")
        assert resp.status_code in (302, 401)

    def test_api_exercises(self, authenticated_client, db_session, grammar_topic, grammar_exercise):
        resp = authenticated_client.get(f"/grammar-lab/api/topic/{grammar_topic.id}/exercises")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert "correct_answer" not in data[0]

    def test_api_exercises_topic_not_found(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/api/topic/999999/exercises")
        assert resp.status_code == 404


class TestApiStartPractice:
    """POST /grammar-lab/api/topic/<id>/start-practice"""

    def test_start_practice_requires_auth(self, client, grammar_topic):
        resp = client.post(f"/grammar-lab/api/topic/{grammar_topic.id}/start-practice")
        assert resp.status_code in (302, 401)

    def test_start_practice(self, authenticated_client, db_session, grammar_topic, grammar_exercise):
        resp = authenticated_client.post(f"/grammar-lab/api/topic/{grammar_topic.id}/start-practice")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "exercises" in data or "session_id" in data


class TestApiSubmitAnswer:
    """POST /grammar-lab/api/exercise/<id>/submit"""

    def test_submit_requires_auth(self, client, grammar_exercise):
        resp = client.post(
            f"/grammar-lab/api/exercise/{grammar_exercise.id}/submit",
            json={"answer": "am"},
        )
        assert resp.status_code in (302, 401)

    @pytest.mark.smoke
    def test_submit_answer(self, authenticated_client, db_session, grammar_exercise):
        resp = authenticated_client.post(
            f"/grammar-lab/api/exercise/{grammar_exercise.id}/submit",
            json={"answer": "am"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "is_correct" in data

    def test_submit_missing_answer(self, authenticated_client, db_session, grammar_exercise):
        resp = authenticated_client.post(
            f"/grammar-lab/api/exercise/{grammar_exercise.id}/submit",
            json={},
        )
        assert resp.status_code == 400

    def test_submit_no_json_body(self, authenticated_client, db_session, grammar_exercise):
        resp = authenticated_client.post(
            f"/grammar-lab/api/exercise/{grammar_exercise.id}/submit",
            content_type="application/json",
            data="{}",
        )
        assert resp.status_code == 400


class TestApiCompleteTheory:
    """POST /grammar-lab/api/topic/<id>/complete-theory"""

    def test_complete_theory_requires_auth(self, client, grammar_topic):
        resp = client.post(f"/grammar-lab/api/topic/{grammar_topic.id}/complete-theory")
        assert resp.status_code in (302, 401)

    @pytest.mark.smoke
    def test_complete_theory(self, authenticated_client, db_session, grammar_topic):
        resp = authenticated_client.post(f"/grammar-lab/api/topic/{grammar_topic.id}/complete-theory")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "status" in data or "xp" in data or "theory_completed" in data


class TestApiCreatePracticeSession:
    """POST /grammar-lab/api/practice/session"""

    def test_create_session_requires_auth(self, client):
        resp = client.post("/grammar-lab/api/practice/session", json={})
        assert resp.status_code in (302, 401)

    def test_create_session(self, authenticated_client, db_session, grammar_topic, grammar_exercise):
        resp = authenticated_client.post(
            "/grammar-lab/api/practice/session",
            json={"topic_ids": [grammar_topic.id], "count": 5},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "exercises" in data or "session_id" in data

    def test_create_session_empty_body(self, authenticated_client, db_session):
        resp = authenticated_client.post(
            "/grammar-lab/api/practice/session",
            json={},
        )
        assert resp.status_code == 200


class TestApiStats:
    """GET /grammar-lab/api/stats"""

    def test_api_stats_requires_auth(self, client):
        resp = client.get("/grammar-lab/api/stats")
        assert resp.status_code in (302, 401)

    @pytest.mark.smoke
    def test_api_stats(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)


class TestApiRecommendations:
    """GET /grammar-lab/api/recommendations"""

    def test_recommendations_requires_auth(self, client):
        resp = client.get("/grammar-lab/api/recommendations")
        assert resp.status_code in (302, 401)

    def test_recommendations(self, authenticated_client, db_session, grammar_topic):
        resp = authenticated_client.get("/grammar-lab/api/recommendations")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_recommendations_with_limit(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/api/recommendations?limit=3")
        assert resp.status_code == 200


class TestApiDueTopics:
    """GET /grammar-lab/api/due-topics"""

    def test_due_topics_requires_auth(self, client):
        resp = client.get("/grammar-lab/api/due-topics")
        assert resp.status_code in (302, 401)

    def test_due_topics_raises_missing_method(self, authenticated_client, db_session):
        with pytest.raises(AttributeError, match="get_due_topics"):
            authenticated_client.get("/grammar-lab/api/due-topics")


class TestApiSrsStats:
    """GET /grammar-lab/api/srs-stats"""

    def test_srs_stats_requires_auth(self, client):
        resp = client.get("/grammar-lab/api/srs-stats")
        assert resp.status_code in (302, 401)

    def test_srs_stats(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/api/srs-stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "new_count" in data or "total" in data

    def test_srs_stats_by_topic(self, authenticated_client, db_session, grammar_topic):
        resp = authenticated_client.get(f"/grammar-lab/api/srs-stats?topic_id={grammar_topic.id}")
        assert resp.status_code == 200

    def test_srs_stats_by_level(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/api/srs-stats?level=B1")
        assert resp.status_code == 200


class TestApiTopicsSrsStats:
    """GET /grammar-lab/api/topics-srs-stats"""

    def test_topics_srs_stats_requires_auth(self, client):
        resp = client.get("/grammar-lab/api/topics-srs-stats")
        assert resp.status_code in (302, 401)

    def test_topics_srs_stats(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/api/topics-srs-stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_topics_srs_stats_by_level(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/api/topics-srs-stats?level=B1")
        assert resp.status_code == 200


class TestApiExerciseSrsInfo:
    """GET /grammar-lab/api/exercise/<id>/srs-info"""

    def test_srs_info_requires_auth(self, client, grammar_exercise):
        resp = client.get(f"/grammar-lab/api/exercise/{grammar_exercise.id}/srs-info")
        assert resp.status_code in (302, 401)

    def test_srs_info_new_exercise(self, authenticated_client, db_session, grammar_exercise):
        resp = authenticated_client.get(f"/grammar-lab/api/exercise/{grammar_exercise.id}/srs-info")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["state"] == "new"
        assert data["ease_factor"] == 2.5

    def test_srs_info_with_progress(self, authenticated_client, db_session, grammar_exercise, test_user):
        progress = UserGrammarExercise(user_id=test_user.id, exercise_id=grammar_exercise.id)
        progress.state = "learning"
        progress.interval = 1
        db_session.add(progress)
        db_session.commit()

        resp = authenticated_client.get(f"/grammar-lab/api/exercise/{grammar_exercise.id}/srs-info")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["state"] == "learning"

    def test_srs_info_exercise_not_found(self, authenticated_client, db_session):
        resp = authenticated_client.get("/grammar-lab/api/exercise/999999/srs-info")
        assert resp.status_code == 404
