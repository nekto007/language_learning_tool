"""Tests for check_words_learned_achievements (Task 8).

Covers:
- 100th word reaching status='review' grants words_learned_100
- 500th word reaching status='review' grants words_learned_500
- fewer than 100 review words grants nothing
- status changes that don't cross a threshold grant nothing new (idempotency)
- check_all_achievements includes 'words' key
"""
from __future__ import annotations

import uuid

import pytest

from app.achievements.seed import seed_achievements
from app.achievements.services import AchievementService
from app.auth.models import User
from app.study.models import Achievement
from app.utils.db import db


WORDS_BADGE_CODES = {'words_learned_100', 'words_learned_500'}


@pytest.fixture
def words_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'wrd_{suffix}',
        email=f'wrd_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def words_badges(db_session):
    seed_achievements()
    db_session.flush()
    badges = Achievement.query.filter(Achievement.code.in_(WORDS_BADGE_CODES)).all()
    assert len(badges) == len(WORDS_BADGE_CODES), (
        f"Expected {len(WORDS_BADGE_CODES)} badges, got {len(badges)}"
    )
    return {b.code: b for b in badges}


def _add_review_words(db_session, user_id: int, count: int, slot: int = 0):
    """Insert `count` UserWord rows with status='review'.

    Creates the required CollectionWords rows first (respecting the FK), then
    inserts user_words in 'review' state.  `slot` offsets the word_ids so
    multiple calls in one test don't collide.
    """
    from sqlalchemy import text

    # Create collection_words rows via raw SQL to avoid ORM overhead
    for i in range(count):
        idx = slot * 10000 + i
        db_session.execute(
            text(
                "INSERT INTO collection_words (english_word, russian_word, level)"
                " VALUES (:eng, :rus, 'A1')"
                " ON CONFLICT DO NOTHING"
            ),
            {'eng': f'__test_word_{user_id}_{idx}', 'rus': 'тест'},
        )
    db_session.flush()

    for i in range(count):
        idx = slot * 10000 + i
        db_session.execute(
            text(
                "INSERT INTO user_words (user_id, word_id, status, created_at, updated_at)"
                " SELECT :uid, id, 'review', NOW(), NOW()"
                " FROM collection_words"
                " WHERE english_word = :eng"
                " ON CONFLICT (user_id, word_id) DO NOTHING"
            ),
            {'uid': user_id, 'eng': f'__test_word_{user_id}_{idx}'},
        )
    db_session.flush()


class TestCheckWordsLearnedAchievements:

    def test_zero_review_words_grants_nothing(self, db_session, words_user, words_badges):
        result = AchievementService.check_words_learned_achievements(words_user.id)
        assert result == []

    def test_99_review_words_grants_nothing(self, db_session, words_user, words_badges):
        _add_review_words(db_session, words_user.id, 99)
        result = AchievementService.check_words_learned_achievements(words_user.id)
        assert result == []

    def test_100_review_words_grants_words_learned_100(self, db_session, words_user, words_badges):
        _add_review_words(db_session, words_user.id, 100)
        result = AchievementService.check_words_learned_achievements(words_user.id)
        codes = {a.code for a in result}
        assert 'words_learned_100' in codes
        assert 'words_learned_500' not in codes

    def test_499_review_words_grants_only_100(self, db_session, words_user, words_badges):
        _add_review_words(db_session, words_user.id, 499)
        result = AchievementService.check_words_learned_achievements(words_user.id)
        codes = {a.code for a in result}
        assert 'words_learned_100' in codes
        assert 'words_learned_500' not in codes

    def test_500_review_words_grants_both(self, db_session, words_user, words_badges):
        _add_review_words(db_session, words_user.id, 500)
        result = AchievementService.check_words_learned_achievements(words_user.id)
        codes = {a.code for a in result}
        assert 'words_learned_100' in codes
        assert 'words_learned_500' in codes

    def test_idempotent_on_second_call(self, db_session, words_user, words_badges):
        _add_review_words(db_session, words_user.id, 100)
        first = AchievementService.check_words_learned_achievements(words_user.id)
        assert len(first) == 1

        second = AchievementService.check_words_learned_achievements(words_user.id)
        assert second == [], "Second call must not re-grant already-awarded badges"

    def test_adding_501st_word_grants_nothing_new_if_500_already_awarded(
        self, db_session, words_user, words_badges
    ):
        from sqlalchemy import text
        _add_review_words(db_session, words_user.id, 500)
        AchievementService.check_words_learned_achievements(words_user.id)

        # Simulate one more review word (slot=1 avoids colliding with slot=0)
        _add_review_words(db_session, words_user.id, 1, slot=1)

        result = AchievementService.check_words_learned_achievements(words_user.id)
        assert result == []

    def test_learning_status_not_counted(self, db_session, words_user, words_badges):
        from sqlalchemy import text

        # Create 100 collection_words and user_words with 'learning' status
        for i in range(100):
            eng = f'__lrn_{words_user.id}_{i}'
            db_session.execute(
                text(
                    "INSERT INTO collection_words (english_word, russian_word, level)"
                    " VALUES (:eng, 'тест', 'A1') ON CONFLICT DO NOTHING"
                ),
                {'eng': eng},
            )
        db_session.flush()
        for i in range(100):
            eng = f'__lrn_{words_user.id}_{i}'
            db_session.execute(
                text(
                    "INSERT INTO user_words (user_id, word_id, status, created_at, updated_at)"
                    " SELECT :uid, id, 'learning', NOW(), NOW()"
                    " FROM collection_words WHERE english_word = :eng"
                    " ON CONFLICT (user_id, word_id) DO NOTHING"
                ),
                {'uid': words_user.id, 'eng': eng},
            )
        db_session.flush()

        result = AchievementService.check_words_learned_achievements(words_user.id)
        assert result == [], "Words in 'learning' state should not count toward threshold"

    def test_check_all_achievements_includes_words_key(
        self, db_session, words_user, words_badges
    ):
        _add_review_words(db_session, words_user.id, 100)
        result = AchievementService.check_all_achievements(words_user.id)
        assert 'words' in result, "check_all_achievements must include 'words' key"
        codes = {a.code for a in result['words']}
        assert 'words_learned_100' in codes
