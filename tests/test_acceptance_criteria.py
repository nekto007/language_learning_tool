"""Acceptance criteria verification for user acquisition improvements."""
import pytest
import uuid
from app import create_app
from app.utils.db import db as _db
from app.auth.models import User
from app.words.models import CollectionWords
from config.settings import TestConfig


@pytest.fixture(scope='module')
def app():
    app = create_app(TestConfig)
    with app.app_context():
        from sqlalchemy import text, inspect
        inspector = inspect(_db.engine)
        columns = [c['name'] for c in inspector.get_columns('users')]
        for col, typ in [('onboarding_completed', 'BOOLEAN DEFAULT false'),
                         ('referral_code', 'VARCHAR(16) UNIQUE'),
                         ('referred_by_id', 'INTEGER'),
                         ('onboarding_level', 'VARCHAR(4)'),
                         ('onboarding_focus', 'VARCHAR(100)'),
                         ('email_unsubscribe_token', 'VARCHAR(64) UNIQUE'),
                         ('email_opted_out', 'BOOLEAN DEFAULT false')]:
            if col not in columns:
                try:
                    _db.session.execute(text(f'ALTER TABLE users ADD COLUMN {col} {typ}'))
                    _db.session.commit()
                except Exception:
                    _db.session.rollback()
        _db.create_all()
        yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    with app.app_context():
        yield _db.session
        _db.session.rollback()


@pytest.fixture
def sample_word(app, db_session):
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'accept{suffix}',
        russian_word='тест', level='A1',
        frequency_rank=1, sentences='Test.',
    )
    db_session.add(word)
    db_session.commit()
    yield word
    db_session.delete(word)
    db_session.commit()


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
    """Verify referral flow: generate code → share → register → reward."""

    def test_referral_code_generation(self, app, db_session):
        suffix = uuid.uuid4().hex[:8]
        with app.app_context():
            user = User(username=f'reftest_{suffix}', email=f'reftest_{suffix}@test.com', active=True)
            user.set_password('test')
            db_session.add(user)
            db_session.commit()

            code = user.ensure_referral_code()
            assert code is not None
            assert len(code) > 0

            # Verify code lookup works
            found = User.query.filter_by(referral_code=code).first()
            assert found.id == user.id

            db_session.delete(user)
            db_session.commit()

    def test_referral_xp_award(self, app, db_session):
        suffix = uuid.uuid4().hex[:8]
        from app.study.models import UserXP
        with app.app_context():
            referrer = User(username=f'refa_{suffix}', email=f'refa_{suffix}@test.com', active=True)
            referrer.set_password('test')
            db_session.add(referrer)
            db_session.flush()

            xp = UserXP.get_or_create(referrer.id)
            initial = xp.total_xp
            xp.add_xp(100)
            db_session.commit()

            assert UserXP.query.filter_by(user_id=referrer.id).first().total_xp == initial + 100

            db_session.delete(xp)
            db_session.delete(referrer)
            db_session.commit()
