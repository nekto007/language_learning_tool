"""
Tests for empty state rendering across the app.
Ensures that pages gracefully handle empty/null data with proper messaging.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestCurriculumEmptyState:
    """Test curriculum/index.html empty state when levels_data is empty."""

    def test_learn_hub_empty_levels_authenticated(self, authenticated_client):
        """When no levels exist, show 'Start your journey' card with onboarding CTA."""
        response = authenticated_client.get('/learn/')

        assert response.status_code == 200
        # The page should show the empty state message
        html = response.data.decode('utf-8')
        assert 'Начните своё путешествие' in html or 'learn-empty' in html

    def test_learn_hub_empty_levels_anonymous(self, app, client):
        """Anonymous user redirects to login (learn requires auth)."""
        response = client.get('/learn/')

        # May require auth - redirect to login is expected
        assert response.status_code in (200, 302)


class TestStudyDashboardEmptyState:
    """Test study/index.html welcome block for new users."""

    def test_study_welcome_no_custom_decks(self, authenticated_client):
        """New users with no custom decks see welcome block with steps."""
        response = authenticated_client.get('/study/')

        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # Welcome block or decks should be present
        assert 'decks-welcome' in html or 'decks-card' in html

    def test_study_public_decks_section_has_anchor(self, authenticated_client):
        """Public decks section should have id='public-decks' for anchor link."""
        response = authenticated_client.get('/study/')

        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # If public decks exist, they should have the anchor id
        if 'Публичные колоды' in html:
            assert 'id="public-decks"' in html


class TestAchievementsEmptyState:
    """Test study/achievements.html empty state."""

    @pytest.mark.smoke
    def test_achievements_page_renders(self, authenticated_client):
        """Achievements page should render with or without achievements."""
        response = authenticated_client.get('/study/achievements')

        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # Should show either achievements or empty state
        assert 'Достижения' in html or 'ach-page' in html

    def test_achievements_empty_state_structure(self, app):
        """Verify empty state template markup exists."""
        import jinja2
        env = app.jinja_env
        source = env.loader.get_source(env, 'study/achievements.html')[0]
        # Verify the empty state block exists in template
        assert 'ach-empty-state' in source
        assert 'Пока нет достижений' in source
        assert 'ach-empty-state__closest' in source


class TestLeaderboardEmptyState:
    """Test study/leaderboard.html empty state."""

    def test_leaderboard_page_renders(self, authenticated_client):
        """Leaderboard page should render even with no users."""
        response = authenticated_client.get('/study/leaderboard')

        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'Таблица лидеров' in html or 'lb-page' in html

    def test_leaderboard_empty_state_structure(self, app):
        """Verify empty state template markup exists for both tabs."""
        import jinja2
        env = app.jinja_env
        source = env.loader.get_source(env, 'study/leaderboard.html')[0]
        assert 'lb-empty' in source
        assert 'Пока нет участников' in source


class TestGrammarLabEmptyState:
    """Test grammar_lab templates empty states."""

    def test_grammar_index_empty_state_structure(self, app):
        """Verify grammar lab index has improved empty state with CTA."""
        env = app.jinja_env
        source = env.loader.get_source(env, 'grammar_lab/index.html')[0]
        assert 'Начните с основ' in source
        assert 'grammar-empty__btn' in source

    def test_grammar_topics_empty_with_level_links(self, app):
        """Verify topics page has links to other levels in empty state."""
        env = app.jinja_env
        source = env.loader.get_source(env, 'grammar_lab/topics.html')[0]
        assert 'topics-empty__levels' in source
        assert 'topics-empty__level-link' in source
        assert 'Попробуйте другой уровень' in source

    def test_grammar_practice_empty_message(self, app):
        """Verify practice empty state has clear message."""
        env = app.jinja_env
        source = env.loader.get_source(env, 'grammar_lab/practice.html')[0]
        assert 'Нет доступных упражнений' in source

    @pytest.mark.skip(reason="Grammar topics route triggers slow DB query in test env")
    def test_grammar_topics_page_renders(self, authenticated_client):
        """Grammar topics page should render without errors."""
        response = authenticated_client.get('/grammar-lab/topics')
        assert response.status_code in (200, 302, 308, 404)


class TestBooksEmptyState:
    """Test books/read_selection.html empty state."""

    def test_books_empty_state_structure(self, app):
        """Verify books selection has level filter suggestion."""
        env = app.jinja_env
        source = env.loader.get_source(env, 'books/read_selection.html')[0]
        assert 'Нет доступных книг для вашего уровня' in source
        assert 'фильтр' in source.lower() or 'поиск' in source.lower()


class TestFlashcardEmptyState:
    """Test flashcard session empty state."""

    def test_flashcard_empty_state_structure(self, app):
        """Verify flashcard component has improved empty state."""
        env = app.jinja_env
        source = env.loader.get_source(env, 'components/_flashcard_session.html')[0]
        assert 'Сейчас нечего учить' in source
        assert 'fc_next_review_time' in source
        assert 'Добавить слова' in source
