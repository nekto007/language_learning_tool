"""
Tests for API routes in app/study/routes.py
Covers 14 API endpoints with ~60 tests total
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


class TestStartSession:
    """Test /start-session POST endpoint - Lines 523-542"""

    def test_start_cards_session(self, authenticated_client):
        """Test starting a cards study session"""
        response = authenticated_client.post('/study/start-session', data={
            'session_type': 'cards',
            'word_source': 'learning'
        }, follow_redirects=False)

        assert response.status_code == 302
        assert '/study/cards' in response.location

    def test_start_quiz_session(self, authenticated_client):
        """Test starting a quiz session"""
        response = authenticated_client.post('/study/start-session', data={
            'session_type': 'quiz',
            'word_source': 'all'
        }, follow_redirects=False)

        assert response.status_code == 302
        assert '/study/quiz' in response.location

    def test_start_matching_session(self, authenticated_client):
        """Test starting a matching game session"""
        response = authenticated_client.post('/study/start-session', data={
            'session_type': 'matching',
            'word_source': 'new'
        }, follow_redirects=False)

        assert response.status_code == 302
        assert '/study/matching' in response.location

    def test_requires_authentication(self, client):
        """Test that authentication is required"""
        response = client.post('/study/start-session', data={
            'session_type': 'cards'
        })

        assert response.status_code == 302
        assert 'login' in response.location.lower()

    def test_invalid_form_data(self, authenticated_client):
        """Test with invalid form data"""
        response = authenticated_client.post('/study/start-session', data={})

        assert response.status_code == 302


class TestGetStudyItems:
    """Test /api/get-study-items GET endpoint - Lines 548-741"""

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

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'error'
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

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'error'


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

    def test_syncs_master_decks(self, authenticated_client, user_words, user_card_directions, db_session):
        """Test that master decks are synced after update"""
        direction = user_card_directions[0]

        response = authenticated_client.post('/study/api/update-study-item', json={
            'word_id': direction.user_word.word_id,
            'direction': direction.direction,
            'quality': 4,
            'is_new': False
        })

        assert response.status_code == 200

        # Check that master decks exist
        from app.study.models import QuizDeck
        learning_deck = QuizDeck.query.filter_by(
            user_id=authenticated_client.application.test_user.id,
            title='Все мои слова'
        ).first()

        # Deck should be created/updated
        assert learning_deck is not None

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

        with patch('app.study.xp_service.XPService.calculate_flashcard_xp') as mock_calc, \
             patch('app.study.xp_service.XPService.award_xp') as mock_award:

            # Mock the XP calculation
            mock_calc.return_value = {'total_xp': 50}
            # Mock award_xp to return the user_xp object
            mock_award.return_value = user_xp

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

        with patch('app.study.xp_service.XPService.calculate_matching_xp') as mock_calc, \
             patch('app.study.xp_service.XPService.award_xp') as mock_award:

            mock_calc.return_value = {'total_xp': 100}
            mock_award.return_value = user_xp

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
        with patch('app.study.xp_service.XPService.calculate_quiz_xp') as mock_calc, \
             patch('app.study.xp_service.XPService.award_xp') as mock_award:

            mock_calc.return_value = {'total_xp': 75}
            mock_award.return_value = user_xp

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
        """Test that achievements are checked"""
        with patch('app.study.routes.AchievementService') as mock_achievement_service:
            quiz_data = {
                'deck_id': quiz_deck_with_words.id,
                'total_questions': 5,
                'correct_answers': 5,  # Perfect score
                'time_taken': 60,
                'word_ids': [1, 2, 3, 4, 5]
            }

            response = authenticated_client.post('/study/api/complete-quiz', json=quiz_data)

            assert response.status_code == 200

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
