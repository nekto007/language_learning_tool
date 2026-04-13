"""Tests for share buttons rendering on public pages."""
import pytest
import uuid


@pytest.fixture
def sample_grammar_topic(db_session):
    """Create a sample grammar topic."""
    from app.grammar_lab.models import GrammarTopic
    suffix = uuid.uuid4().hex[:8]
    topic = GrammarTopic(
        slug=f'test-share-{suffix}',
        title=f'Test Share Topic {suffix}',
        title_ru=f'Тестовая тема {suffix}',
        level='B1',
        order=999,
        content={'introduction': 'Test content'},
    )
    db_session.add(topic)
    db_session.commit()
    return topic


class TestShareButtonsOnGrammarTopic:
    """Test share buttons on grammar topic detail page."""

    def test_grammar_topic_has_share_buttons(self, client, sample_grammar_topic):
        response = client.get(f'/grammar-lab/topic/{sample_grammar_topic.id}')
        html = response.data.decode()
        assert 'share-btn' in html

    def test_grammar_topic_has_telegram_share(self, client, sample_grammar_topic):
        response = client.get(f'/grammar-lab/topic/{sample_grammar_topic.id}')
        html = response.data.decode()
        assert 'share-btn--telegram' in html

    def test_grammar_topic_has_whatsapp_share(self, client, sample_grammar_topic):
        response = client.get(f'/grammar-lab/topic/{sample_grammar_topic.id}')
        html = response.data.decode()
        assert 'share-btn--whatsapp' in html

    def test_grammar_topic_has_twitter_share(self, client, sample_grammar_topic):
        response = client.get(f'/grammar-lab/topic/{sample_grammar_topic.id}')
        html = response.data.decode()
        assert 'share-btn--twitter' in html

    def test_grammar_topic_has_copy_button(self, client, sample_grammar_topic):
        response = client.get(f'/grammar-lab/topic/{sample_grammar_topic.id}')
        html = response.data.decode()
        assert 'share-btn--copy' in html


class TestShareJS:
    """Test that share.js is loaded."""

    def test_share_js_included_in_base(self, client):
        response = client.get('/')
        html = response.data.decode()
        assert 'share.js' in html
