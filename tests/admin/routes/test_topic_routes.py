import uuid

from app.words.models import CollectionWords, Topic, TopicWord


class TestTopicWordsRoutes:
    """Tests for admin topic word management routes."""

    def test_bulk_add_words_requires_exact_english_match(
        self,
        admin_client,
        mock_admin_user,
        db_session,
    ):
        suffix = uuid.uuid4().hex[:8]
        exact_text = f'exactword{suffix}'
        partial_text = f'{exact_text}x'
        existing_text = f'existingword{suffix}'

        topic = Topic(name=f'Test Topic {suffix}')
        exact_word = CollectionWords(
            english_word=exact_text,
            russian_word='точное',
            level='A1',
        )
        partial_word = CollectionWords(
            english_word=partial_text,
            russian_word='частичное',
            level='A1',
        )
        existing_word = CollectionWords(
            english_word=existing_text,
            russian_word='существующее',
            level='A1',
        )

        db_session.add_all([topic, exact_word, partial_word, existing_word])
        db_session.flush()
        db_session.add(TopicWord(topic_id=topic.id, word_id=existing_word.id))
        db_session.commit()

        response = admin_client.post(
            f'/admin/topics/{topic.id}/bulk_add_words',
            json={
                'words': [
                    exact_text.upper(),
                    exact_text[:-1],
                    existing_text,
                ]
            },
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload['success'] is True
        assert payload['added'] == 1
        assert payload['existing'] == 1
        assert payload['not_found'] == 1
        assert payload['details']['added'] == [exact_text]
        assert payload['details']['existing'] == [existing_text]
        assert payload['details']['not_found'] == [exact_text[:-1]]

        topic_word_ids = {
            topic_word.word_id
            for topic_word in TopicWord.query.filter_by(topic_id=topic.id).all()
        }
        assert exact_word.id in topic_word_ids
        assert existing_word.id in topic_word_ids
        assert partial_word.id not in topic_word_ids
