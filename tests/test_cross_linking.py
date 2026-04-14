"""Tests for cross-linking between words and grammar topics."""
import pytest
import uuid
from app.words.models import CollectionWords
from app.grammar_lab.models import GrammarTopic


@pytest.fixture
def cross_link_data(db_session):
    """Create a word and grammar topic at the same level."""
    suffix = uuid.uuid4().hex[:6]
    word = CollectionWords(
        english_word=f'crossword{suffix}',
        russian_word='кроссворд тест',
        level='B2',
        frequency_rank=50,
        sentences=f'Example with crossword{suffix}.',
    )
    topic = GrammarTopic(
        slug=f'cross-topic-{suffix}',
        title=f'Cross Topic {suffix}',
        title_ru=f'Кросс тема {suffix}',
        level='B2',
        order=950,
        content={'introduction': 'Cross link test'},
    )
    db_session.add_all([word, topic])
    db_session.commit()
    return word, topic


class TestWordToGrammarCrossLink:
    """Test that public word page shows grammar topics of same level."""

    def test_word_page_has_grammar_section(self, client, cross_link_data):
        word, topic = cross_link_data
        slug = word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert 'Grammar Lab' in html or 'grammar-lab' in html.lower() or 'Грамматика' in html

    def test_word_page_has_continue_learning(self, client, cross_link_data):
        word, _ = cross_link_data
        slug = word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert 'courses/' in html or 'grammar-lab' in html


class TestGrammarToWordCrossLink:
    """Test that grammar topic page shows vocabulary of same level."""

    def test_grammar_page_has_vocabulary_section(self, client, cross_link_data):
        _, topic = cross_link_data
        response = client.get(f'/grammar-lab/topic/{topic.id}')
        html = response.data.decode()
        assert 'Словарь уровня' in html or 'dictionary/' in html

    def test_grammar_page_has_continue_learning(self, client, cross_link_data):
        _, topic = cross_link_data
        response = client.get(f'/grammar-lab/topic/{topic.id}')
        html = response.data.decode()
        assert 'Курс' in html and topic.level in html
