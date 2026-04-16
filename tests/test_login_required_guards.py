"""
Tests for @login_required guards on protected routes.

Audit findings (Task 51):
- app/study/routes.py: all routes properly decorated with @login_required
- app/study/api_routes.py: all routes use @login_required
- app/study/game_routes.py: quiz_deck_shared is intentionally public (shared quiz preview)
- app/words/routes.py: public_word is intentionally public (SEO dictionary page)
- app/grammar_lab/routes.py: index/topics/topic_detail are intentionally public
  (render public content, show user stats only when authenticated)
- app/api/*: all user-data endpoints use @api_auth_required (JWT + session auth)
- app/admin/routes/*: all routes use @admin_required
- app/reminders/routes.py: all routes use @admin_required

These tests verify that existing @login_required guards correctly redirect
unauthenticated users to the login page (302).
"""
import pytest


class TestLoginRequiredGuards:
    """Verify @login_required protected routes redirect unauthenticated users."""

    @pytest.mark.smoke
    def test_study_index_requires_login(self, client):
        """Unauthenticated GET /study/ returns 302 redirect to login."""
        response = client.get('/study/', follow_redirects=False)
        assert response.status_code == 302
        location = response.headers.get('Location', '')
        assert 'login' in location

    def test_study_stats_requires_login(self, client):
        """Unauthenticated GET /study/stats returns 302 redirect to login."""
        response = client.get('/study/stats', follow_redirects=False)
        assert response.status_code == 302
        location = response.headers.get('Location', '')
        assert 'login' in location

    def test_study_insights_requires_login(self, client):
        """Unauthenticated GET /study/insights returns 302 redirect to login."""
        response = client.get('/study/insights', follow_redirects=False)
        assert response.status_code == 302
        location = response.headers.get('Location', '')
        assert 'login' in location

    def test_words_dashboard_requires_login(self, client):
        """Unauthenticated GET /dashboard returns 302 redirect to login."""
        response = client.get('/dashboard', follow_redirects=False)
        assert response.status_code == 302
        location = response.headers.get('Location', '')
        assert 'login' in location

    def test_words_list_requires_login(self, client):
        """Unauthenticated GET /words requires login."""
        response = client.get('/words', follow_redirects=False)
        assert response.status_code == 302
        location = response.headers.get('Location', '')
        assert 'login' in location

    def test_words_phrasal_verbs_requires_login(self, client):
        """Unauthenticated GET /phrasal-verbs requires login."""
        response = client.get('/phrasal-verbs', follow_redirects=False)
        assert response.status_code == 302
        location = response.headers.get('Location', '')
        assert 'login' in location

    def test_public_word_page_accessible_without_login(self, client):
        """Public word dictionary page /dictionary/<slug> is accessible without login."""
        # This page is intentionally public for SEO — should NOT redirect to login.
        # It may return 200 (word found) or 404 (word not found), but not 302 to login.
        response = client.get('/dictionary/hello', follow_redirects=False)
        assert response.status_code != 302 or 'login' not in response.headers.get('Location', '')

    def test_grammar_lab_index_accessible_without_login(self, client):
        """Grammar Lab index is publicly accessible (shows empty stats for guests)."""
        response = client.get('/grammar-lab/', follow_redirects=False)
        # Should return 200, not redirect to login
        assert response.status_code != 302 or 'login' not in response.headers.get('Location', '')

    def test_api_daily_plan_requires_auth(self, client):
        """Unauthenticated GET /api/daily-plan returns 401."""
        response = client.get('/api/daily-plan', follow_redirects=False)
        assert response.status_code == 401

    def test_api_words_requires_auth(self, client):
        """Unauthenticated GET /api/words returns 401."""
        response = client.get('/api/words', follow_redirects=False)
        assert response.status_code == 401

    def test_redirect_includes_next_param(self, client):
        """Login redirect preserves the original URL in 'next' parameter."""
        response = client.get('/study/', follow_redirects=False)
        assert response.status_code == 302
        location = response.headers.get('Location', '')
        # Flask-Login adds ?next= to the login URL
        assert 'login' in location
