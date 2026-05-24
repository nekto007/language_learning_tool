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
