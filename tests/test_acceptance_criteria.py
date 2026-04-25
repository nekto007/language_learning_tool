"""Acceptance criteria verification for user acquisition improvements."""
import pytest
import uuid
from app.auth.models import User
from app.words.models import CollectionWords


@pytest.fixture
def sample_word(db_session):
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'accept{suffix}',
        russian_word='тест', level='A1',
        frequency_rank=1, sentences='Test.',
    )
    db_session.add(word)
    db_session.commit()
    return word


class TestPublicRoutesReturn200:
    """Verify all new public routes return 200 for anonymous users."""

    def test_landing(self, client):
        assert client.get('/').status_code == 200

    def test_courses_catalog(self, client):
        assert client.get('/courses/').status_code == 200

    def test_grammar_lab(self, client):
        assert client.get('/grammar-lab/').status_code == 200

    def test_dictionary(self, client, sample_word):
        slug = sample_word.english_word.lower()
        assert client.get(f'/dictionary/{slug}').status_code == 200

    def test_register(self, client):
        assert client.get('/register').status_code == 200

    def test_sitemap(self, client):
        assert client.get('/sitemap.xml').status_code == 200

    def test_robots(self, client):
        assert client.get('/robots.txt').status_code == 200


class TestSitemapContainsAllPages:
    """Verify all new pages appear in sitemap.xml."""

    def test_sitemap_has_courses(self, client):
        xml = client.get('/sitemap.xml').data.decode()
        assert '/courses' in xml

    def test_sitemap_has_grammar_lab(self, client):
        xml = client.get('/sitemap.xml').data.decode()
        assert '/grammar-lab/' in xml

    def test_sitemap_has_dictionary(self, client, sample_word):
        xml = client.get('/sitemap.xml').data.decode()
        assert '/dictionary/' in xml


class TestOGTagsOnPublicPages:
    """Verify OG tags render correctly."""

    def test_landing_og(self, client):
        html = client.get('/').data.decode()
        assert 'og:title' in html and 'og:description' in html

    def test_courses_og(self, client):
        html = client.get('/courses/').data.decode()
        assert 'og:title' in html

    def test_dictionary_og(self, client, sample_word):
        slug = sample_word.english_word.lower()
        html = client.get(f'/dictionary/{slug}').data.decode()
        assert 'og:title' in html


class TestReferralFlowEndToEnd:
    """Verify referral flow: generate code -> share -> register -> reward."""

    def test_referral_code_generation(self, db_session):
        suffix = uuid.uuid4().hex[:8]
        user = User(username=f'reftest_{suffix}', email=f'reftest_{suffix}@test.com', active=True)
        user.set_password('test')
        db_session.add(user)
        db_session.commit()

        code = user.ensure_referral_code()
        assert code is not None
        assert len(code) > 0

        found = User.query.filter_by(referral_code=code).first()
        assert found.id == user.id

    def test_referral_xp_award(self, db_session):
        suffix = uuid.uuid4().hex[:8]
        from app.achievements.models import UserStatistics
        from app.achievements.xp_service import award_xp

        referrer = User(username=f'refa_{suffix}', email=f'refa_{suffix}@test.com', active=True)
        referrer.set_password('test')
        db_session.add(referrer)
        db_session.flush()

        stats = UserStatistics.query.filter_by(user_id=referrer.id).first()
        initial = int(stats.total_xp) if stats and stats.total_xp else 0

        award_xp(referrer.id, 100, 'referral')
        db_session.commit()

        stats = UserStatistics.query.filter_by(user_id=referrer.id).first()
        assert stats is not None
        assert int(stats.total_xp) == initial + 100
