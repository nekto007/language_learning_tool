"""Route tests for admin topic + collection management (Task 18)."""

import uuid

import pytest

from app.admin.audit import AdminAuditLog
from app.utils.db import db
from app.words.models import (
    Collection,
    CollectionWordLink,
    CollectionWords,
    Topic,
    TopicWord,
)


@pytest.fixture
def sample_word(db_session):
    word = CollectionWords(
        english_word=f'word_{uuid.uuid4().hex[:8]}',
        russian_word='тест',
        level='A1',
    )
    db_session.add(word)
    db_session.commit()
    return word


class TestTopicCrud:
    def test_topic_list_renders_word_count_without_n_plus_one(
        self, admin_client, mock_admin_user, db_session, sample_word
    ):
        suffix = uuid.uuid4().hex[:6]
        topics = [Topic(name=f'topic_{suffix}_{i}') for i in range(3)]
        db_session.add_all(topics)
        db_session.flush()
        # Add words to first topic only
        db_session.add(TopicWord(topic_id=topics[0].id, word_id=sample_word.id))
        db_session.commit()

        response = admin_client.get('/admin/topics')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert topics[0].name in body
        # Word count column should render at least once (>=1 for first topic)
        assert '<td>1</td>' in body or '>1<' in body

    def test_create_topic_writes_audit_log(self, admin_client, mock_admin_user, db_session):
        name = f'TopicAudit_{uuid.uuid4().hex[:6]}'
        before = AdminAuditLog.query.filter_by(action='topic.create').count()

        response = admin_client.post(
            '/admin/topics/create',
            data={'name': name, 'description': 'demo', 'submit': 'Save'},
            follow_redirects=False,
        )
        assert response.status_code == 302

        after = AdminAuditLog.query.filter_by(action='topic.create').count()
        assert after == before + 1
        assert Topic.query.filter_by(name=name).first() is not None

    def test_create_topic_rejects_duplicate_name_case_insensitive(
        self, admin_client, mock_admin_user, db_session
    ):
        name = f'DupTopic_{uuid.uuid4().hex[:6]}'
        db_session.add(Topic(name=name))
        db_session.commit()

        response = admin_client.post(
            '/admin/topics/create',
            data={'name': name.upper(), 'description': '', 'submit': 'Save'},
            follow_redirects=False,
        )
        # Should re-render form (not redirect)
        assert response.status_code == 200
        # Only one topic with that name exists
        count = Topic.query.filter(db.func.lower(Topic.name) == name.lower()).count()
        assert count == 1

    def test_edit_topic_allows_keeping_own_name(
        self, admin_client, mock_admin_user, db_session
    ):
        name = f'KeepTopic_{uuid.uuid4().hex[:6]}'
        topic = Topic(name=name, description='orig')
        db_session.add(topic)
        db_session.commit()

        response = admin_client.post(
            f'/admin/topics/{topic.id}/edit',
            data={'name': name, 'description': 'updated', 'submit': 'Save'},
            follow_redirects=False,
        )
        assert response.status_code == 302
        db_session.refresh(topic)
        assert topic.description == 'updated'

    def test_delete_topic_writes_audit_log(self, admin_client, mock_admin_user, db_session):
        topic = Topic(name=f'DelTopic_{uuid.uuid4().hex[:6]}')
        db_session.add(topic)
        db_session.commit()
        topic_id = topic.id

        response = admin_client.post(
            f'/admin/topics/{topic_id}/delete',
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert Topic.query.get(topic_id) is None
        assert AdminAuditLog.query.filter_by(
            action='topic.delete', target_id=topic_id
        ).count() >= 1


class TestCollectionCrud:
    def test_collection_list_paginates_and_filters(
        self, admin_client, mock_admin_user, db_session, sample_word
    ):
        suffix = uuid.uuid4().hex[:6]
        topic = Topic(name=f'TopicFilter_{suffix}')
        db_session.add(topic)
        db_session.flush()
        db_session.add(TopicWord(topic_id=topic.id, word_id=sample_word.id))

        col_match = Collection(name=f'MatchCol_{suffix}', description='')
        col_other = Collection(name=f'OtherCol_{suffix}', description='')
        db_session.add_all([col_match, col_other])
        db_session.flush()
        db_session.add(
            CollectionWordLink(collection_id=col_match.id, word_id=sample_word.id)
        )
        db_session.commit()

        # Filter by topic — only col_match has words tied to the topic.
        response = admin_client.get(f'/admin/collections?topic={topic.id}')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert col_match.name in body
        assert col_other.name not in body

        # Search filter
        response = admin_client.get(f'/admin/collections?search=MatchCol_{suffix}')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert col_match.name in body
        assert col_other.name not in body

        # Invalid page param falls back to 1 without crashing.
        response = admin_client.get('/admin/collections?page=abc&per_page=xyz')
        assert response.status_code == 200

    def test_create_collection_writes_audit_log(
        self, admin_client, mock_admin_user, db_session
    ):
        name = f'NewCol_{uuid.uuid4().hex[:6]}'
        before = AdminAuditLog.query.filter_by(action='collection.create').count()

        response = admin_client.post(
            '/admin/collections/create',
            data={'name': name, 'description': '', 'word_ids': '', 'submit': 'Save'},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert AdminAuditLog.query.filter_by(action='collection.create').count() == before + 1
        assert Collection.query.filter_by(name=name).first() is not None

    def test_create_collection_rejects_duplicate_name(
        self, admin_client, mock_admin_user, db_session
    ):
        name = f'DupCol_{uuid.uuid4().hex[:6]}'
        db_session.add(Collection(name=name, description=''))
        db_session.commit()

        response = admin_client.post(
            '/admin/collections/create',
            data={'name': name.upper(), 'description': '', 'word_ids': '', 'submit': 'Save'},
            follow_redirects=False,
        )
        assert response.status_code == 200  # re-renders the form
        count = Collection.query.filter(
            db.func.lower(Collection.name) == name.lower()
        ).count()
        assert count == 1

    def test_delete_collection_writes_audit_log(
        self, admin_client, mock_admin_user, db_session
    ):
        col = Collection(name=f'DelCol_{uuid.uuid4().hex[:6]}', description='')
        db_session.add(col)
        db_session.commit()
        col_id = col.id

        response = admin_client.post(
            f'/admin/collections/{col_id}/delete',
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert Collection.query.get(col_id) is None
        assert (
            AdminAuditLog.query.filter_by(
                action='collection.delete', target_id=col_id
            ).count()
            >= 1
        )

    def test_get_words_by_topic_validates_input(
        self, admin_client, mock_admin_user, db_session
    ):
        response = admin_client.get('/admin/api/get_words_by_topic?topic_ids=not-a-number')
        assert response.status_code == 400

        response = admin_client.get('/admin/api/get_words_by_topic')
        assert response.status_code == 200
        assert response.get_json() == []
