"""Tests for Legal blueprint: privacy policy page."""
import pytest


class TestPrivacyPolicy:
    def test_privacy_returns_200(self, client):
        response = client.get('/privacy')
        assert response.status_code == 200

    def test_privacy_contains_title(self, client):
        response = client.get('/privacy')
        html = response.data.decode('utf-8')
        assert 'Политика конфиденциальности' in html

    def test_privacy_contains_key_sections(self, client):
        response = client.get('/privacy')
        html = response.data.decode('utf-8')
        assert 'Какие данные мы собираем' in html
        assert 'Хранение и защита данных' in html
        assert 'Ваши права' in html

    def test_privacy_link_in_footer(self, client):
        """Footer on any page should contain link to privacy policy."""
        response = client.get('/')
        html = response.data.decode('utf-8')
        assert '/privacy' in html


class TestGoogleAnalyticsConfig:
    def test_no_analytics_when_not_configured(self, client):
        """When GOOGLE_ANALYTICS_ID is empty, no gtag script should appear."""
        response = client.get('/privacy')
        html = response.data.decode('utf-8')
        assert 'googletagmanager.com/gtag' not in html

    def test_no_verification_when_not_configured(self, client):
        """When GOOGLE_SITE_VERIFICATION is empty, no verification meta tag."""
        response = client.get('/privacy')
        html = response.data.decode('utf-8')
        assert 'google-site-verification' not in html
