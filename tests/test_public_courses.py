"""Tests for public course catalog and level detail pages."""
import pytest
import uuid
from app.curriculum.models import CEFRLevel, Module, Lessons


@pytest.fixture
def sample_level(db_session):
    """Create a sample CEFR level (within PUBLIC_CEFR_CODES) with a module and lesson."""
    suffix = uuid.uuid4().hex[:6]
    code = 'A1'

    level = CEFRLevel(
        code=code,
        name=f'Test Level {suffix}',
        description='A test level for courses',
        order=1,
    )
    db_session.add(level)
    db_session.flush()

    module = Module(
        level_id=level.id,
        number=1,
        title=f'Test Module {suffix}',
    )
    db_session.add(module)
    db_session.flush()

    lesson = Lessons(
        module_id=module.id,
        number=1,
        title=f'Test Lesson {suffix}',
        type='vocabulary',
        order=1,
    )
    db_session.add(lesson)
    db_session.commit()

    return level


class TestPublicCourseCatalog:
    """Test GET /courses public route."""

    @pytest.mark.smoke
    def test_catalog_returns_200(self, client):
        response = client.get('/courses/')
        assert response.status_code == 200

    def test_catalog_no_login_required(self, client):
        response = client.get('/courses/')
        assert response.status_code == 200

    def test_catalog_has_og_tags(self, client):
        response = client.get('/courses/')
        html = response.data.decode()
        assert 'og:title' in html
        assert 'og:description' in html

    def test_catalog_has_json_ld(self, client):
        response = client.get('/courses/')
        html = response.data.decode()
        assert 'application/ld+json' in html
        assert 'ItemList' in html

    def test_catalog_shows_levels(self, client, sample_level):
        response = client.get('/courses/')
        html = response.data.decode()
        assert sample_level.code in html


class TestPublicLevelDetail:
    """Test GET /courses/<level_code> public route."""

    @pytest.mark.smoke
    def test_level_returns_200(self, client, sample_level):
        response = client.get(f'/courses/{sample_level.code}')
        assert response.status_code == 200

    def test_level_no_login_required(self, client, sample_level):
        response = client.get(f'/courses/{sample_level.code}')
        assert response.status_code == 200

    def test_level_404_for_nonexistent(self, client):
        response = client.get('/courses/ZZ')
        assert response.status_code == 404

    @pytest.mark.parametrize('level_code', ['A0', 'C2'])
    def test_unsupported_public_levels_return_404(self, client, level_code):
        response = client.get(f'/courses/{level_code}')
        assert response.status_code == 404

    def test_level_has_og_tags(self, client, sample_level):
        response = client.get(f'/courses/{sample_level.code}')
        html = response.data.decode()
        assert 'og:title' in html
        assert 'og:description' in html

    def test_level_has_json_ld(self, client, sample_level):
        response = client.get(f'/courses/{sample_level.code}')
        html = response.data.decode()
        assert 'application/ld+json' in html
        assert 'Course' in html

    def test_level_shows_modules(self, client, sample_level):
        response = client.get(f'/courses/{sample_level.code}')
        html = response.data.decode()
        assert 'Test Module' in html

    def test_level_has_register_cta(self, client, sample_level):
        response = client.get(f'/courses/{sample_level.code}')
        html = response.data.decode()
        assert 'register' in html.lower()

    def test_level_case_insensitive(self, client, sample_level):
        """Level code lookup should be case-insensitive."""
        response = client.get(f'/courses/{sample_level.code.lower()}')
        assert response.status_code == 200


class TestSitemapCourses:
    """Test that course pages appear in sitemap."""

    def test_sitemap_has_courses(self, client):
        response = client.get('/sitemap.xml')
        xml = response.data.decode()
        assert '/courses' in xml


class TestUnpublishedFilter:
    """Verify public catalog acts as a gate for non-public CEFR codes.

    PUBLIC_CEFR_CODES = ('A1', 'A2', 'B1', 'B2', 'C1') is the "published" gate.
    A0 and C2 are outside this set and must return 404 without any redirect.
    """

    def test_a0_level_not_accessible(self, client):
        response = client.get('/courses/A0', follow_redirects=False)
        assert response.status_code == 404

    def test_c2_level_not_accessible(self, client):
        response = client.get('/courses/C2', follow_redirects=False)
        assert response.status_code == 404

    def test_arbitrary_code_not_accessible(self, client):
        response = client.get('/courses/XX', follow_redirects=False)
        assert response.status_code == 404

    def test_lowercase_a0_not_accessible(self, client):
        """Even after normalization, A0 should return 404."""
        response = client.get('/courses/a0', follow_redirects=False)
        assert response.status_code == 404

    def test_public_code_is_accessible(self, client, sample_level):
        """A1 (a PUBLIC_CEFR_CODE) must return 200 for anonymous user."""
        response = client.get(f'/courses/{sample_level.code}', follow_redirects=False)
        assert response.status_code == 200


class TestAnonymousAccess:
    """Verify anonymous (unauthenticated) users can browse catalog without redirect."""

    def test_catalog_no_redirect(self, client):
        response = client.get('/courses/', follow_redirects=False)
        assert response.status_code == 200

    def test_level_detail_no_redirect(self, client, sample_level):
        response = client.get(
            f'/courses/{sample_level.code}', follow_redirects=False
        )
        assert response.status_code == 200

    def test_catalog_returns_html(self, client):
        response = client.get('/courses/')
        assert 'text/html' in response.content_type

    def test_level_detail_returns_html(self, client, sample_level):
        response = client.get(f'/courses/{sample_level.code}')
        assert 'text/html' in response.content_type


class TestEnrollmentFlow:
    """Verify enrollment CTAs direct anonymous users to registration."""

    def test_catalog_has_register_link(self, client):
        """Catalog banner must contain a link to the registration page."""
        response = client.get('/courses/')
        html = response.data.decode()
        assert '/register' in html

    def test_level_detail_has_register_link(self, client, sample_level):
        """Level hero CTA must link to the registration page."""
        response = client.get(f'/courses/{sample_level.code}')
        html = response.data.decode()
        assert '/register' in html


class TestPreviewContentProtection:
    """Verify course preview shows only lesson titles — no exercise content."""

    def test_preview_shows_lesson_title(self, client, sample_level):
        """Sample lesson titles must appear in the level detail page."""
        response = client.get(f'/courses/{sample_level.code}')
        html = response.data.decode()
        assert 'Test Lesson' in html

    def test_preview_does_not_expose_correct_answer(self, client, sample_level):
        """Raw exercise JSON keys must not appear in the public preview."""
        response = client.get(f'/courses/{sample_level.code}')
        html = response.data.decode()
        assert '"correct_answer"' not in html
        assert '"exercise_type"' not in html

    def test_canonical_url_is_not_hardcoded(self, client, sample_level):
        """Canonical link must not contain a hardcoded domain."""
        response = client.get(f'/courses/{sample_level.code}')
        html = response.data.decode()
        assert 'href="https://llt-english.com' not in html

    def test_catalog_canonical_url_is_not_hardcoded(self, client):
        """Catalog canonical link must not contain a hardcoded domain."""
        response = client.get('/courses/')
        html = response.data.decode()
        assert 'href="https://llt-english.com' not in html
