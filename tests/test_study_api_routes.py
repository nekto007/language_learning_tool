"""
Tests for API routes in app/study/routes.py
Covers 13 API endpoints with ~55 tests total
Focus: SRS logic, daily limits, race conditions, input validation
"""
import pytest
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.study.models import (
    StudySession, StudySettings, UserWord, UserCardDirection,
    QuizDeck, QuizDeckWord, GameScore, QuizResult
)
from app.utils.db import db


class TestGetStudyItems:
    """Test /api/get-study-items GET endpoint - Lines 548-741"""

    @pytest.mark.smoke
    def test_get_items_auto_mode(self, authenticated_client, user_words, user_card_directions, study_settings):
        """Test getting study items in auto mode"""
        response = authenticated_client.get('/study/api/get-study-items?source=auto')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'success'
        assert 'items' in data
        assert 'stats' in data

    def test_get_items_from_deck(self, authenticated_client, quiz_deck_with_words, user_words, study_settings):
        """Test getting study items from specific deck"""
        response = authenticated_client.get(
            f'/study/api/get-study-items?source=deck&deck_id={quiz_deck_with_words.id}'
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'success'

    def test_deck_access_denied(self, authenticated_client, second_user, db_session, study_settings):
        """Test access denied for private deck of another user"""
        # Create deck for second user
        other_deck = QuizDeck(
            title='Private Deck',
            user_id=second_user.id,
            is_public=False
        )
        db_session.add(other_deck)
        db_session.commit()

        response = authenticated_client.get(
            f'/study/api/get-study-items?deck_id={other_deck.id}'
        )

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data['success'] is False
        assert data['error'] == 'deck_not_found'
        assert 'access denied' in data['message'].lower()

    def test_public_deck_accessible(self, authenticated_client, public_quiz_deck, test_words_list, db_session, study_settings):
        """Test that public deck is accessible to any user"""
        # Add words to public deck
        for i, word in enumerate(test_words_list[:3]):
            deck_word = QuizDeckWord(
                deck_id=public_quiz_deck.id,
                word_id=word.id,
                order_index=i
            )
            db_session.add(deck_word)
        db_session.commit()

        response = authenticated_client.get(
            f'/study/api/get-study-items?deck_id={public_quiz_deck.id}'
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] in ['success', 'daily_limit_reached']

    def test_daily_limit_new_cards(self, authenticated_client, user_words, user_card_directions, study_settings, db_session):
        """Test daily limit enforcement for new cards"""
        # Set limit to 0
        study_settings.new_words_per_day = 0
        study_settings.reviews_per_day = 0
        db_session.commit()

        response = authenticated_client.get('/study/api/get-study-items?source=auto')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'daily_limit_reached'
        assert data['items'] == []

    def test_extra_study_bypasses_limits(self, authenticated_client, user_words, study_settings, db_session):
        """Test that extra_study=true bypasses daily limits"""
        # Set limits to 0
        study_settings.new_words_per_day = 0
        study_settings.reviews_per_day = 0
        db_session.commit()

        response = authenticated_client.get('/study/api/get-study-items?source=auto&extra_study=true')

        assert response.status_code == 200
        data = json.loads(response.data)
        # Should return items even with limits at 0
        assert data['status'] == 'success'

    def test_daily_plan_mix_does_not_terminate_on_limit(
        self, authenticated_client, user_words, study_settings, db_session,
    ):
        """Daily-plan sessions must not be cut off mid-flow by the limit banner.

        Regression for bug: passing cards in "Быстрый разогрев" showed the
        "Дневной лимит достигнут" message. Selection by daily limits belongs
        to plan formation — once the session has begun, the API should just
        return whatever items are available and let the frontend show a
        neutral "session complete" state when empty.
        """
        study_settings.new_words_per_day = 0
        study_settings.reviews_per_day = 0
        db_session.commit()

        response = authenticated_client.get(
            '/study/api/get-study-items?source=daily_plan_mix'
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] != 'daily_limit_reached'

    def test_linear_plan_srs_returns_only_due_review_cards(
        self, authenticated_client, user_words, user_card_directions, study_settings,
    ):
        """Linear SRS slot must match dashboard due-count semantics.

        It should not pull adaptive new cards, future review cards, or
        learning cards inside the grace window. The dashboard slot says
        "Повторить N карточек", so the session must contain exactly those
        cards that are due right now.
        """
        from app.daily_plan.linear.slots.srs_slot import count_srs_due_cards
        from app.utils.db import db as real_db

        response = authenticated_client.get(
            '/study/api/get-study-items?source=linear_plan&from=linear_plan&slot=srs'
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'success'
        assert len(data['items']) == count_srs_due_cards(user_words[0].user_id, real_db)
        assert data['items']
        assert {item['state'] for item in data['items']} == {'review'}
        assert all(item['is_new'] is False for item in data['items'])
        assert data['stats']['new_cards_limit'] == data['stats']['new_cards_today']

    def test_linear_plan_srs_respects_remaining_review_budget(
        self, authenticated_client, db_session, test_user, study_settings,
    ):
        """Linear-plan card session size must match the slot's capped due count."""
        from app.daily_plan.linear.slots.srs_slot import count_linear_plan_srs_due_cards
        from app.study.models import UserCardDirection, UserWord
        from app.words.models import CollectionWords

        now = datetime.now(timezone.utc)
        study_settings.reviews_per_day = 50

        for index in range(10):
            word = CollectionWords(
                english_word=f'reviewed_{index}',
                russian_word=f'повтор_{index}',
                level='A1',
            )
            db_session.add(word)
            db_session.flush()

            user_word = UserWord(user_id=test_user.id, word_id=word.id)
            user_word.status = 'review'
            db_session.add(user_word)
            db_session.flush()

            direction = UserCardDirection(
                user_word_id=user_word.id,
                direction='eng-rus',
            )
            direction.state = 'review'
            direction.first_reviewed = now - timedelta(days=10)
            direction.last_reviewed = now - timedelta(minutes=5)
            direction.next_review = now + timedelta(days=1)
            db_session.add(direction)

        for index in range(80):
            word = CollectionWords(
                english_word=f'due_{index}',
                russian_word=f'долг_{index}',
                level='A1',
            )
            db_session.add(word)
            db_session.flush()

            user_word = UserWord(user_id=test_user.id, word_id=word.id)
            user_word.status = 'review'
            db_session.add(user_word)
            db_session.flush()

            direction = UserCardDirection(
                user_word_id=user_word.id,
                direction='eng-rus',
            )
            direction.state = 'review'
            direction.first_reviewed = now - timedelta(days=20)
            direction.last_reviewed = now - timedelta(days=2)
            direction.next_review = now - timedelta(hours=1)
            db_session.add(direction)

        db_session.commit()

        response = authenticated_client.get(
            '/study/api/get-study-items?source=linear_plan&from=linear_plan&slot=srs'
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'success'
        assert count_linear_plan_srs_due_cards(test_user.id, db) == 40
        assert len(data['items']) == 40
        assert data['stats']['reviews_today'] == 10
        assert data['stats']['reviews_limit'] == 50

    def test_prioritizes_due_reviews(self, authenticated_client, user_words, user_card_directions, study_settings):
        """Test that due reviews are prioritized over new cards"""
        response = authenticated_client.get('/study/api/get-study-items?source=auto')

        assert response.status_code == 200
        data = json.loads(response.data)

        if data['items']:
            # Check that there are review items (is_new=False)
            has_reviews = any(not item['is_new'] for item in data['items'])
            # Due reviews should be included
            assert has_reviews or len(data['items']) == 0

    def test_excludes_mastered_words(self, authenticated_client, user_words, user_card_directions, study_settings, db_session):
        """Test that mastered words are excluded from study items"""
        # Mark all words as mastered
        for uw in user_words:
            uw.status = 'mastered'
        db_session.commit()

        response = authenticated_client.get('/study/api/get-study-items?source=auto')

        assert response.status_code == 200
        data = json.loads(response.data)

        # Should only return new items if available
        if data['items']:
            assert all(item['is_new'] for item in data['items'])

    def test_returns_both_directions_for_new_cards(self, authenticated_client, test_words_list, study_settings, db_session):
        """Test that new cards return both eng-rus and rus-eng directions"""
        response = authenticated_client.get('/study/api/get-study-items?source=auto')

        assert response.status_code == 200
        data = json.loads(response.data)

        if data['items']:
            new_items = [item for item in data['items'] if item['is_new']]
            if new_items:
                # Check that there are both directions
                word_ids = {}
                for item in new_items:
                    word_id = item['word_id']
                    if word_id not in word_ids:
                        word_ids[word_id] = []
                    word_ids[word_id].append(item['direction'])

                # At least one word should have both directions
                has_both = any(
                    'eng-rus' in directions and 'rus-eng' in directions
                    for directions in word_ids.values()
                )
                assert has_both or len(new_items) < 2

    def test_stats_included_in_response(self, authenticated_client, study_settings):
        """Test that stats are included in response"""
        response = authenticated_client.get('/study/api/get-study-items?source=auto')

        assert response.status_code == 200
        data = json.loads(response.data)

        assert 'stats' in data
        assert 'new_cards_today' in data['stats']
        assert 'reviews_today' in data['stats']
        assert 'new_cards_limit' in data['stats']
        assert 'reviews_limit' in data['stats']

    def test_requires_authentication(self, client):
        """Test that authentication is required"""
        response = client.get('/study/api/get-study-items')

        assert response.status_code == 302

    def test_invalid_deck_id(self, authenticated_client, study_settings):
        """Test with non-existent deck ID"""
        response = authenticated_client.get('/study/api/get-study-items?deck_id=99999')

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data['success'] is False
        assert data['error'] == 'deck_not_found'

    def test_daily_limit_reached_preserves_business_status(
        self, authenticated_client, user_words, user_card_directions, study_settings, db_session
    ):
        """daily_limit_reached is a business status, not an error — must keep legacy shape."""
        study_settings.new_words_per_day = 0
        study_settings.reviews_per_day = 0
        db_session.commit()

        response = authenticated_client.get('/study/api/get-study-items?source=auto')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'daily_limit_reached'
        assert 'stats' in data
        assert data['items'] == []


class TestGetQuizQuestions:
    def test_linear_plan_deck_quiz_includes_mastered_deck_words(
        self, authenticated_client, quiz_deck_with_words, test_words_list, db_session,
    ):
        user_id = authenticated_client.application.test_user.id
        mastered_ids = [word.id for word in test_words_list[:5]]
        for word_id in mastered_ids:
            user_word = UserWord.get_or_create(user_id, word_id)
            user_word.status = 'mastered'
        db_session.commit()

        response = authenticated_client.get(
            '/study/api/get-quiz-questions?source=linear_plan_deck_quiz&count=30'
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'success'
        question_word_ids = {q['word_id'] for q in data['questions']}
        assert set(mastered_ids).issubset(question_word_ids)


class TestUpdateStudyItem:
    """Test /api/update-study-item POST endpoint - Lines 744-821"""

    def test_update_existing_direction(self, authenticated_client, user_words, user_card_directions, db_session):
        """Test updating an existing card direction"""
        direction = user_card_directions[0]

        response = authenticated_client.post('/study/api/update-study-item', json={
            'word_id': direction.user_word.word_id,
            'direction': direction.direction,
            'quality': 4,
            'is_new': False
        })

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'interval' in data

        # Check that direction was updated
        db_session.refresh(direction)
        assert direction.last_reviewed is not None

    def test_create_new_direction(self, authenticated_client, test_words_list, study_settings, db_session):
        """Test creating a new card direction"""
        word = test_words_list[0]

        response = authenticated_client.post('/study/api/update-study-item', json={
            'word_id': word.id,
            'direction': 'eng-rus',
            'quality': 3,
            'is_new': True
        })

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

        # Check that UserWord and Direction were created
        user_word = UserWord.query.filter_by(
            user_id=authenticated_client.application.test_user.id,
            word_id=word.id
        ).first()
        assert user_word is not None

        direction = UserCardDirection.query.filter_by(
            user_word_id=user_word.id,
            direction='eng-rus'
        ).first()
        assert direction is not None

    def test_daily_limit_race_condition(self, authenticated_client, test_words_list, study_settings, db_session):
        """Test race condition prevention with SELECT FOR UPDATE"""
        # Set limit to 1
        study_settings.new_words_per_day = 1
        db_session.commit()

        word1 = test_words_list[0]
        word2 = test_words_list[1]

        # First card should succeed
        response1 = authenticated_client.post('/study/api/update-study-item', json={
            'word_id': word1.id,
            'direction': 'eng-rus',
            'quality': 3,
            'is_new': True
        })

        assert response1.status_code == 200
        data1 = json.loads(response1.data)
        assert data1['success'] is True

        # Second card should fail (limit exceeded)
        response2 = authenticated_client.post('/study/api/update-study-item', json={
            'word_id': word2.id,
            'direction': 'eng-rus',
            'quality': 3,
            'is_new': True
        })

        # Should return 429 (Too Many Requests) or success: false
        assert response2.status_code in [200, 429]
        data2 = json.loads(response2.data)
        if response2.status_code == 200:
            assert data2['success'] is False
            assert 'daily_limit' in data2.get('error', '').lower()

    def test_quality_scores_0_to_5(self, authenticated_client, user_words, user_card_directions, db_session):
        """Test different quality scores (0-5)"""
        direction = user_card_directions[0]

        for quality in [0, 1, 2, 3, 4, 5]:
            response = authenticated_client.post('/study/api/update-study-item', json={
                'word_id': direction.user_word.word_id,
                'direction': direction.direction,
                'quality': quality,
                'is_new': False
            })

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['success'] is True

    def test_updates_session_statistics(self, authenticated_client, user_words, user_card_directions, study_session, db_session):
        """Test that session statistics are updated"""
        direction = user_card_directions[0]
        initial_words_studied = study_session.words_studied
        initial_correct = study_session.correct_answers

        response = authenticated_client.post('/study/api/update-study-item', json={
            'word_id': direction.user_word.word_id,
            'direction': direction.direction,
            'quality': 4,
            'session_id': study_session.id,
            'is_new': False
        })

        assert response.status_code == 200

        db_session.refresh(study_session)
        assert study_session.words_studied == initial_words_studied + 1
        assert study_session.correct_answers == initial_correct + 1

    def test_incorrect_answer_updates_session(self, authenticated_client, user_words, user_card_directions, study_session, db_session):
        """Test that incorrect answers update session correctly"""
        direction = user_card_directions[0]
        initial_incorrect = study_session.incorrect_answers

        response = authenticated_client.post('/study/api/update-study-item', json={
            'word_id': direction.user_word.word_id,
            'direction': direction.direction,
            'quality': 1,  # Incorrect
            'session_id': study_session.id,
            'is_new': False
        })

        assert response.status_code == 200

        db_session.refresh(study_session)
        assert study_session.incorrect_answers == initial_incorrect + 1

    def test_requires_authentication(self, client):
        """Test that authentication is required"""
        response = client.post('/study/api/update-study-item', json={
            'word_id': 1,
            'direction': 'eng-rus',
            'quality': 3
        })

        assert response.status_code == 302

    def test_invalid_session_id_ignored(self, authenticated_client, user_words, user_card_directions):
        """Test that invalid session ID doesn't cause error"""
        direction = user_card_directions[0]

        response = authenticated_client.post('/study/api/update-study-item', json={
            'word_id': direction.user_word.word_id,
            'direction': direction.direction,
            'quality': 3,
            'session_id': 99999,  # Non-existent
            'is_new': False
        })

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True


class TestCompleteSession:
    """Test /api/complete-session POST endpoint - Lines 824-859"""

    @pytest.mark.smoke
    def test_complete_session_successfully(self, authenticated_client, study_session, db_session):
        """Test successfully completing a session"""
        assert study_session.end_time is None

        response = authenticated_client.post('/study/api/complete-session', json={
            'session_id': study_session.id
        })

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

        db_session.refresh(study_session)
        assert study_session.end_time is not None

    def test_awards_xp_on_completion(self, authenticated_client, study_session, user_xp, db_session):
        """Test that XP is awarded on session completion"""
        initial_xp = user_xp.total_xp

        with patch('app.study.api_routes._calculate_flashcard_xp') as mock_calc, \
             patch('app.achievements.xp_service.award_xp') as mock_award:

            # Mock the XP calculation
            mock_calc.return_value = {'total_xp': 50}
            from app.achievements.xp_service import XPAward
            mock_award.return_value = XPAward(
                xp_awarded=50, multiplier=1.0, new_total_xp=initial_xp + 50,
                previous_level=1, new_level=1, leveled_up=False,
            )

            response = authenticated_client.post('/study/api/complete-session', json={
                'session_id': study_session.id
            })

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['success'] is True
            assert 'xp_earned' in data
            # Verify XP methods were called
            mock_calc.assert_called_once()
            mock_award.assert_called_once()

    def test_invalid_session_id(self, authenticated_client):
        """Test with invalid session ID"""
        response = authenticated_client.post('/study/api/complete-session', json={
            'session_id': 99999
        })

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is False

    def test_cannot_complete_other_users_session(self, authenticated_client, second_user, db_session):
        """Test that users can't complete other users' sessions"""
        other_session = StudySession(
            user_id=second_user.id,
            session_type='cards'
        )
        db_session.add(other_session)
        db_session.commit()

        response = authenticated_client.post('/study/api/complete-session', json={
            'session_id': other_session.id
        })

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is False

    def test_requires_authentication(self, client):
        """Test that authentication is required"""
        response = client.post('/study/api/complete-session', json={
            'session_id': 1
        })

        assert response.status_code == 302

    def test_requires_json_content_type(self, authenticated_client):
        """Test that non-JSON request returns 415"""
        response = authenticated_client.post(
            '/study/api/complete-session',
            data='session_id=1',
            content_type='application/x-www-form-urlencoded'
        )
        assert response.status_code == 415


class TestCompleteMatchingGame:
    """Test /api/complete-matching-game POST endpoint - Lines 1610-1743"""

    def test_complete_game_successfully(self, authenticated_client, test_user, user_xp, db_session):
        """Test successfully completing a matching game"""
        game_data = {
            'difficulty': 'medium',
            'pairs_matched': 8,
            'total_pairs': 8,
            'time_taken': 45,
            'moves': 16,
            'word_ids': [1, 2, 3, 4, 5, 6, 7, 8]
        }

        response = authenticated_client.post('/study/api/complete-matching-game', json=game_data)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'score' in data
        assert data['score'] > 0

    def test_server_side_score_validation(self, authenticated_client, user_xp):
        """Test that score is calculated server-side"""
        game_data = {
            'difficulty': 'medium',
            'pairs_matched': 8,
            'total_pairs': 8,
            'time_taken': 30,
            'moves': 16,
            'word_ids': [1, 2, 3, 4, 5, 6, 7, 8],
            'client_score': 99999  # Try to cheat
        }

        response = authenticated_client.post('/study/api/complete-matching-game', json=game_data)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        # Server should calculate score, not trust client
        assert data['score'] <= 500  # Max score cap

    def test_invalid_game_data_rejected(self, authenticated_client, user_xp):
        """Test that invalid game data is rejected"""
        invalid_data = {
            'difficulty': 'medium',
            'pairs_matched': 10,  # More than total
            'total_pairs': 8,
            'time_taken': 30,
            'moves': 5,  # Impossible (less than pairs * 2)
            'word_ids': []
        }

        response = authenticated_client.post('/study/api/complete-matching-game', json=invalid_data)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'error' in data or 'message' in data

    def test_updates_personal_best(self, authenticated_client, user_xp, db_session):
        """Test that personal best score is updated"""
        game_data = {
            'difficulty': 'hard',
            'pairs_matched': 8,
            'total_pairs': 8,
            'time_taken': 20,
            'moves': 16,
            'word_ids': [1, 2, 3, 4, 5, 6, 7, 8]
        }

        response = authenticated_client.post('/study/api/complete-matching-game', json=game_data)

        assert response.status_code == 200

        # Check that GameScore was created
        score = GameScore.query.filter_by(
            user_id=authenticated_client.application.test_user.id,
            game_type='matching',
            difficulty='hard'
        ).first()

        assert score is not None

    def test_rollback_on_error(self, authenticated_client, user_xp):
        """Test that database rollback happens on error"""
        # Send malformed data
        response = authenticated_client.post('/study/api/complete-matching-game', json={
            'invalid': 'data'
        })

        # Should handle error gracefully
        assert response.status_code in [200, 400]

    def test_awards_xp(self, authenticated_client, user_xp, db_session, test_words_list):
        """Test that XP is awarded for completing game"""
        from app.study.models import UserWord

        # Create user words for the game
        word_ids = []
        for word in test_words_list[:8]:
            user_word = UserWord.query.filter_by(user_id=user_xp.user_id, word_id=word.id).first()
            if not user_word:
                user_word = UserWord(user_id=user_xp.user_id, word_id=word.id)
                user_word.status = 'learning'  # Set status after creation
                db_session.add(user_word)
            word_ids.append(word.id)
        db_session.commit()

        with patch('app.study.game_routes._calculate_matching_xp') as mock_calc, \
             patch('app.achievements.xp_service.award_xp') as mock_award:

            mock_calc.return_value = {'total_xp': 100}
            from app.achievements.xp_service import XPAward
            mock_award.return_value = XPAward(
                xp_awarded=100, multiplier=1.0, new_total_xp=100,
                previous_level=1, new_level=1, leveled_up=False,
            )

            game_data = {
                'difficulty': 'medium',
                'pairs_matched': 8,
                'total_pairs': 8,
                'time_taken': 30,
                'moves': 16,
                'word_ids': word_ids
            }

            response = authenticated_client.post('/study/api/complete-matching-game', json=game_data)

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['success'] is True
            mock_calc.assert_called_once()
            mock_award.assert_called_once()

    def test_requires_authentication(self, client):
        """Test that authentication is required"""
        response = client.post('/study/api/complete-matching-game', json={
            'difficulty': 'medium',
            'pairs_matched': 8,
            'total_pairs': 8,
            'time_taken': 30,
            'moves': 16,
            'word_ids': []
        })

        assert response.status_code == 302


class TestCompleteQuiz:
    """Test /api/complete-quiz POST endpoint - Lines 1746-1845"""

    def test_complete_quiz_successfully(self, authenticated_client, quiz_deck_with_words, user_xp, db_session):
        """Test successfully completing a quiz"""
        quiz_data = {
            'deck_id': quiz_deck_with_words.id,
            'total_questions': 5,
            'correct_answers': 4,
            'time_taken': 120,
            'score': 80  # 4/5 = 80%
        }

        response = authenticated_client.post('/study/api/complete-quiz', json=quiz_data)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'score' in data
        assert 'xp_earned' in data

    def test_creates_quiz_result(self, authenticated_client, quiz_deck_with_words, user_xp, db_session):
        """Test that QuizResult is created"""
        quiz_data = {
            'deck_id': quiz_deck_with_words.id,
            'total_questions': 5,
            'correct_answers': 5,
            'time_taken': 60,
            'word_ids': [1, 2, 3, 4, 5]
        }

        response = authenticated_client.post('/study/api/complete-quiz', json=quiz_data)

        assert response.status_code == 200

        # Check that result was saved
        result = QuizResult.query.filter_by(
            user_id=authenticated_client.application.test_user.id,
            deck_id=quiz_deck_with_words.id
        ).first()

        assert result is not None
        assert result.correct_answers == 5

    def test_updates_deck_statistics(self, authenticated_client, quiz_deck_with_words, user_xp, db_session):
        """Test that deck statistics are updated"""
        from app.study.models import QuizResult

        quiz_data = {
            'deck_id': quiz_deck_with_words.id,
            'total_questions': 5,
            'correct_answers': 4,
            'time_taken': 90,
            'score': 80  # 4/5 = 80%
        }

        response = authenticated_client.post('/study/api/complete-quiz', json=quiz_data)

        assert response.status_code == 200

        # Check that QuizResult was created
        result = QuizResult.query.filter_by(deck_id=quiz_deck_with_words.id).first()
        assert result is not None
        assert result.score_percentage == 80

        # Check that average_score was updated
        db_session.refresh(quiz_deck_with_words)
        assert quiz_deck_with_words.average_score == 80

    def test_awards_xp(self, authenticated_client, quiz_deck_with_words, user_xp):
        """Test that XP is awarded"""
        with patch('app.study.game_routes._calculate_quiz_xp') as mock_calc, \
             patch('app.achievements.xp_service.award_xp') as mock_award:

            mock_calc.return_value = {'total_xp': 75}
            from app.achievements.xp_service import XPAward
            mock_award.return_value = XPAward(
                xp_awarded=75, multiplier=1.0, new_total_xp=75,
                previous_level=1, new_level=1, leveled_up=False,
            )

            quiz_data = {
                'deck_id': quiz_deck_with_words.id,
                'total_questions': 5,
                'correct_answers': 5,
                'time_taken': 60,
                'score': 100
            }

            response = authenticated_client.post('/study/api/complete-quiz', json=quiz_data)

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['success'] is True
            mock_calc.assert_called_once()
            mock_award.assert_called_once()

    def test_checks_achievements(self, authenticated_client, quiz_deck_with_words, user_xp, achievements):
        """Test that achievements are checked on quiz completion"""
        quiz_data = {
            'deck_id': quiz_deck_with_words.id,
            'total_questions': 5,
            'correct_answers': 5,  # Perfect score
            'time_taken': 60,
            'word_ids': [1, 2, 3, 4, 5]
        }

        response = authenticated_client.post('/study/api/complete-quiz', json=quiz_data)

        assert response.status_code == 200

    def test_linear_plan_deck_quiz_awards_srs_slot_xp(
        self, authenticated_client, test_user, user_xp, db_session,
    ):
        from app.achievements.models import StreakEvent
        from app.daily_plan.linear.slots.srs_slot import build_srs_slot
        from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE

        test_user.use_linear_plan = True
        db_session.commit()

        response = authenticated_client.post('/study/api/complete-quiz', json={
            'source': 'linear_plan_deck_quiz',
            'from': 'linear_plan',
            'slot': 'srs',
            'total_questions': 20,
            'correct_answers': 15,
            'time_taken': 180,
            'score': 75,
        })

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

        event = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
            StreakEvent.details['source'].astext == 'linear_srs_global',
        ).first()
        assert event is not None

        lesson = type('LessonStub', (), {'type': 'card'})()
        slot = build_srs_slot(test_user.id, db, curriculum_lesson=lesson)
        assert slot.completed is True
        assert slot.url is None

    def test_invalid_deck_id(self, authenticated_client, user_xp):
        """Test with invalid deck ID"""
        quiz_data = {
            'deck_id': 99999,
            'total_questions': 5,
            'correct_answers': 4,
            'time_taken': 90,
            'word_ids': [1, 2, 3, 4, 5]
        }

        response = authenticated_client.post('/study/api/complete-quiz', json=quiz_data)

        # Should handle gracefully
        assert response.status_code in [200, 404]

    def test_requires_authentication(self, client):
        """Test that authentication is required"""
        response = client.post('/study/api/complete-quiz', json={
            'deck_id': 1,
            'total_questions': 5,
            'correct_answers': 4,
            'time_taken': 90,
            'word_ids': []
        })

        assert response.status_code == 302


class TestLessonModeDailyLimit:
    """Test lesson_mode flag on /api/update-study-item bypasses daily new-card limits."""

    def test_lesson_mode_bypasses_daily_limit(self, authenticated_client, test_words_list, study_settings, db_session):
        """A card graded with lesson_mode=True proceeds past the daily new-card threshold."""
        study_settings.new_words_per_day = 0
        db_session.commit()

        word = test_words_list[0]
        response = authenticated_client.post('/study/api/update-study-item', json={
            'word_id': word.id,
            'direction': 'eng-rus',
            'quality': 3,
            'is_new': True,
            'lesson_mode': True,
        })

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

    def test_generic_free_study_blocked_at_threshold(self, authenticated_client, test_words_list, study_settings, db_session):
        """Without lesson_mode, a brand-new card is blocked when the daily limit is 0."""
        study_settings.new_words_per_day = 0
        db_session.commit()

        word = test_words_list[0]
        response = authenticated_client.post('/study/api/update-study-item', json={
            'word_id': word.id,
            'direction': 'eng-rus',
            'quality': 3,
            'is_new': True,
        })

        assert response.status_code in [200, 429]
        data = json.loads(response.data)
        if response.status_code == 200:
            assert data.get('success') is False
            assert 'daily_limit' in data.get('error', '').lower()
        else:
            assert data.get('error') == 'daily_limit_exceeded'

    def test_lesson_mode_false_still_enforces_limit(self, authenticated_client, test_words_list, study_settings, db_session):
        """Explicitly passing lesson_mode=False still enforces the daily limit."""
        study_settings.new_words_per_day = 0
        db_session.commit()

        word = test_words_list[0]
        response = authenticated_client.post('/study/api/update-study-item', json={
            'word_id': word.id,
            'direction': 'eng-rus',
            'quality': 3,
            'is_new': True,
            'lesson_mode': False,
        })

        assert response.status_code in [200, 429]
        data = json.loads(response.data)
        if response.status_code == 200:
            assert data.get('success') is False
        else:
            assert data.get('error') == 'daily_limit_exceeded'

    def test_lesson_mode_reviews_not_affected(self, authenticated_client, user_words, user_card_directions, study_settings, db_session):
        """Cards that already have first_reviewed set are never blocked by daily new-card limits."""
        from datetime import datetime, timezone
        study_settings.new_words_per_day = 0
        db_session.commit()

        # Mark the direction as already reviewed so is_first_review=False
        direction = user_card_directions[0]
        direction.first_reviewed = datetime.now(timezone.utc)
        db_session.commit()

        response = authenticated_client.post('/study/api/update-study-item', json={
            'word_id': direction.user_word.word_id,
            'direction': direction.direction,
            'quality': 3,
            'is_new': False,
        })

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
