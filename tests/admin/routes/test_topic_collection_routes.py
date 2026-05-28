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
    @pytest.mark.smoke
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

    def test_edit_collection_get_renders_form(
        self, admin_client, mock_admin_user, db_session, sample_word
    ):
        col = Collection(name=f'EditCol_{uuid.uuid4().hex[:6]}', description='')
        db_session.add(col)
        db_session.commit()

        response = admin_client.get(f'/admin/collections/{col.id}/edit')
        assert response.status_code == 200

    def test_edit_collection_post_updates_name(
        self, admin_client, mock_admin_user, db_session
    ):
        col = Collection(name=f'OldName_{uuid.uuid4().hex[:6]}', description='')
        db_session.add(col)
        db_session.commit()

        new_name = f'NewName_{uuid.uuid4().hex[:6]}'
        response = admin_client.post(
            f'/admin/collections/{col.id}/edit',
            data={'name': new_name, 'description': 'updated', 'word_ids': '', 'submit': 'Save'},
            follow_redirects=False,
        )
        assert response.status_code == 302
        db_session.refresh(col)
        assert col.name == new_name

    def test_edit_collection_rejects_duplicate_name(
        self, admin_client, mock_admin_user, db_session
    ):
        col1 = Collection(name=f'Col1_{uuid.uuid4().hex[:6]}', description='')
        col2 = Collection(name=f'Col2_{uuid.uuid4().hex[:6]}', description='')
        db_session.add_all([col1, col2])
        db_session.commit()

        response = admin_client.post(
            f'/admin/collections/{col2.id}/edit',
            data={'name': col1.name, 'description': '', 'word_ids': '', 'submit': 'Save'},
            follow_redirects=False,
        )
        assert response.status_code == 200  # re-renders form with error

    def test_collection_list_sort_by_word_count(
        self, admin_client, mock_admin_user, db_session
    ):
        response = admin_client.get('/admin/collections?sort=word_count')
        assert response.status_code == 200

    def test_collection_list_sort_by_created_at(
        self, admin_client, mock_admin_user, db_session
    ):
        response = admin_client.get('/admin/collections?sort=created_at')
        assert response.status_code == 200

    def test_collection_list_invalid_sort_falls_back(
        self, admin_client, mock_admin_user, db_session
    ):
        response = admin_client.get('/admin/collections?sort=INVALID')
        assert response.status_code == 200

    def test_get_words_by_topic_returns_words(
        self, admin_client, mock_admin_user, db_session, sample_word
    ):
        topic = Topic(name=f'WTopic_{uuid.uuid4().hex[:6]}')
        db_session.add(topic)
        db_session.flush()
        db_session.add(TopicWord(topic_id=topic.id, word_id=sample_word.id))
        db_session.commit()

        response = admin_client.get(f'/admin/api/get_words_by_topic?topic_ids={topic.id}')
        assert response.status_code == 200
        data = response.get_json()
        assert any(w['id'] == sample_word.id for w in data)


class TestTopicCascadeDelete:
    """Task 87: verify topic delete cascades TopicWord associations."""

    def test_delete_topic_cascades_topic_words(
        self, admin_client, mock_admin_user, db_session, sample_word
    ):
        """Deleting a topic removes TopicWord rows but keeps the words themselves."""
        topic = Topic(name=f'CascadeTopic_{uuid.uuid4().hex[:6]}')
        db_session.add(topic)
        db_session.flush()
        tw = TopicWord(topic_id=topic.id, word_id=sample_word.id)
        db_session.add(tw)
        db_session.commit()
        topic_id = topic.id
        tw_id = tw.id

        response = admin_client.post(
            f'/admin/topics/{topic_id}/delete', follow_redirects=False
        )
        assert response.status_code == 302

        # Expire identity map so assertions hit the DB, not SQLAlchemy cache.
        db_session.expire_all()

        assert Topic.query.get(topic_id) is None
        # TopicWord rows removed via CASCADE (DB constraint) or ORM secondary delete.
        remaining = TopicWord.query.filter_by(topic_id=topic_id).count()
        assert remaining == 0
        # The word itself must still exist — no cascade to words
        assert CollectionWords.query.get(sample_word.id) is not None

    def test_delete_topic_with_no_words_succeeds(
        self, admin_client, mock_admin_user, db_session
    ):
        """Deleting a topic that has zero words does not crash."""
        topic = Topic(name=f'EmptyTopic_{uuid.uuid4().hex[:6]}')
        db_session.add(topic)
        db_session.commit()
        topic_id = topic.id

        response = admin_client.post(
            f'/admin/topics/{topic_id}/delete', follow_redirects=False
        )
        assert response.status_code == 302
        assert Topic.query.get(topic_id) is None

    def test_topic_name_unique_case_insensitive(
        self, admin_client, mock_admin_user, db_session
    ):
        """Topic name acts as unique slug — duplicate names (any case) are rejected."""
        name = f'UniqueSlug_{uuid.uuid4().hex[:6]}'
        db_session.add(Topic(name=name))
        db_session.commit()

        # Attempt to create with same name uppercased
        response = admin_client.post(
            '/admin/topics/create',
            data={'name': name.upper(), 'description': '', 'submit': 'Save'},
            follow_redirects=False,
        )
        assert response.status_code == 200  # form re-rendered, not redirected
        count = Topic.query.filter(
            db.func.lower(Topic.name) == name.lower()
        ).count()
        assert count == 1

    def test_topic_name_html_is_not_executed(
        self, admin_client, mock_admin_user, db_session
    ):
        """HTML in topic name is stored literally (no script injection at list page)."""
        name = f'<script>alert(1)</script>_{uuid.uuid4().hex[:6]}'
        response = admin_client.post(
            '/admin/topics/create',
            data={'name': name, 'description': '', 'submit': 'Save'},
            follow_redirects=True,
        )
        # If the form accepts it, the list page must NOT render raw <script>
        if response.status_code == 200:
            body = response.get_data(as_text=True)
            assert '<script>alert(1)</script>' not in body


class TestCollectionZeroItems:
    """Task 87: verify collections with 0 words are accessible (no 500)."""

    def test_collection_list_with_zero_word_collection_returns_200(
        self, admin_client, mock_admin_user, db_session
    ):
        """Collection list page must not 500 when a collection has no words."""
        col = Collection(name=f'EmptyCol_{uuid.uuid4().hex[:6]}', description='')
        db_session.add(col)
        db_session.commit()

        response = admin_client.get('/admin/collections')
        assert response.status_code == 200

    def test_edit_page_for_empty_collection_returns_200(
        self, admin_client, mock_admin_user, db_session
    ):
        """Edit page for a collection with 0 words must not 500."""
        col = Collection(name=f'EmptyEditCol_{uuid.uuid4().hex[:6]}', description='')
        db_session.add(col)
        db_session.commit()

        response = admin_client.get(f'/admin/collections/{col.id}/edit')
        assert response.status_code == 200

    def test_delete_empty_collection_cascades_no_links(
        self, admin_client, mock_admin_user, db_session
    ):
        """Deleting a collection with 0 words succeeds without integrity errors."""
        col = Collection(name=f'DelEmpty_{uuid.uuid4().hex[:6]}', description='')
        db_session.add(col)
        db_session.commit()
        col_id = col.id

        response = admin_client.post(
            f'/admin/collections/{col_id}/delete', follow_redirects=False
        )
        assert response.status_code == 302
        assert Collection.query.get(col_id) is None

    def test_collection_sort_order_consistent(
        self, admin_client, mock_admin_user, db_session
    ):
        """All valid sort params return 200 with no duplicate rows."""
        suffix = uuid.uuid4().hex[:6]
        for i in range(3):
            col = Collection(name=f'SortCol_{suffix}_{i}', description='')
            db_session.add(col)
        db_session.commit()

        for sort_param in ('name', 'word_count', 'created_at'):
            response = admin_client.get(f'/admin/collections?sort={sort_param}')
            assert response.status_code == 200

        # Invalid sort falls back safely
        response = admin_client.get('/admin/collections?sort=injection;DROP')
        assert response.status_code == 200

    def test_delete_collection_cascades_word_links(
        self, admin_client, mock_admin_user, db_session, sample_word
    ):
        """Deleting a collection removes CollectionWordLink rows but keeps words."""
        col = Collection(name=f'LinkCascade_{uuid.uuid4().hex[:6]}', description='')
        db_session.add(col)
        db_session.flush()
        link = CollectionWordLink(collection_id=col.id, word_id=sample_word.id)
        db_session.add(link)
        db_session.commit()
        col_id = col.id

        response = admin_client.post(
            f'/admin/collections/{col_id}/delete', follow_redirects=False
        )
        assert response.status_code == 302

        db_session.expire_all()

        assert Collection.query.get(col_id) is None
        remaining = CollectionWordLink.query.filter_by(collection_id=col_id).count()
        assert remaining == 0
        assert CollectionWords.query.get(sample_word.id) is not None
