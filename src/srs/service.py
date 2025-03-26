"""
Service layer for SRS (Spaced Repetition System) functionality.
Implements the SM-2 algorithm for spaced repetition.
"""
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from src.db.models import Word
from src.srs.models import Deck, DeckCard
from src.srs.repository import SRSRepository
from src.user.repository import UserRepository

logger = logging.getLogger(__name__)


class SRSService:
    """Service for SRS (Spaced Repetition System) logic."""

    # Default settings
    NEW_CARDS_PER_DAY = 10
    LEARNED_THRESHOLD = 7  # Number of successful repetitions to mark as learned

    def __init__(self, db_path: str):
        """
        Initialize the SRS service.

        Args:
            db_path (str): Path to SQLite database
        """
        self.srs_repo = SRSRepository(db_path)
        self.user_repo = UserRepository(db_path)

    # === Deck Management ===

    def get_or_create_main_deck(self, user_id: int) -> Deck:
        """
        Get or create the main deck for a user.

        Args:
            user_id (int): User ID

        Returns:
            Deck: Main deck object
        """
        main_deck = self.srs_repo.get_main_deck(user_id)

        if main_deck is None:
            deck_id = self.srs_repo.create_deck(
                user_id=user_id,
                name="Основная колода",
                description="Автоматически созданная основная колода для изучения слов"
            )
            main_deck = self.srs_repo.get_deck_by_id(deck_id)

        return main_deck

    def get_decks_with_stats(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Get all decks for a user with statistics.

        Args:
            user_id (int): User ID

        Returns:
            List[Dict[str, Any]]: List of deck data with statistics
        """
        decks = self.srs_repo.get_decks_by_user(user_id)
        result = []

        for deck in decks:
            stats = self.srs_repo.get_deck_statistics(deck.id)
            deck_dict = deck.to_dict()
            deck_dict.update(stats)
            result.append(deck_dict)

        return result

    def create_custom_deck(self, user_id: int, name: str, description: Optional[str] = None) -> int:
        """
        Create a custom deck.

        Args:
            user_id (int): User ID
            name (str): Deck name
            description (Optional[str], optional): Deck description. Defaults to None.

        Returns:
            int: Deck ID
        """
        return self.srs_repo.create_deck(user_id, name, description)

    # === Card Management ===

    def create_card(self, deck_id: int, word_id: int) -> int:
        """
        Create a new card in a deck.

        Args:
            deck_id (int): Deck ID
            word_id (int): Word ID

        Returns:
            int: Card ID
        """
        # Check if card already exists
        existing_card = self.srs_repo.get_card_by_deck_and_word(deck_id, word_id)
        if existing_card:
            return existing_card.id

        # Create new card with default SRS parameters
        today = date.today()
        return self.srs_repo.create_card(
            deck_id=deck_id,
            word_id=word_id,
            next_review_date=today,  # Due today (new card)
            interval=0,
            repetitions=0,
            ease_factor=2.5
        )

    """
    Updated methods for SRSService class to properly handle word status.
    Add or replace these methods in your service.py file.
    """

    def add_word_to_deck(self, user_id: int, word_id: int, deck_id: Optional[int] = None) -> int:
        """
        Add a word to a deck and update its status.

        Args:
            user_id (int): User ID
            word_id (int): Word ID
            deck_id (Optional[int], optional): Deck ID. If None, adds to main deck. Defaults to None.

        Returns:
            int: Card ID
        """
        if deck_id is None:
            main_deck = self.get_or_create_main_deck(user_id)
            deck_id = main_deck.id

        # Create the card in the deck (original functionality)
        card_id = self.create_card(deck_id, word_id)

        try:
            # Обновление глобального статуса слова в таблице collection_words
            import sqlite3
            from config.settings import DB_FILE
            from src.db.models import Word

            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()

                # Проверяем текущий глобальный статус
                cursor.execute(
                    "SELECT learning_status FROM collection_words WHERE id = ?",
                    (word_id,)
                )
                result = cursor.fetchone()

                if result and result[0] == Word.STATUS_NEW:  # Если статус "Новое"
                    # Обновляем статус на "Активное"
                    cursor.execute(
                        """
                        UPDATE collection_words 
                        SET learning_status = ? 
                        WHERE id = ?
                        """,
                        (Word.STATUS_STUDYING, word_id)
                    )
                    logger.info(f"Updated word {word_id} global status from New to Active")

                # Проверяем, существует ли таблица user_word_status
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_word_status'")
                if cursor.fetchone():
                    # Проверяем, есть ли запись для этого слова у данного пользователя
                    cursor.execute(
                        """
                        SELECT status FROM user_word_status 
                        WHERE user_id = ? AND word_id = ?
                        """,
                        (user_id, word_id)
                    )
                    user_status = cursor.fetchone()

                    if user_status:
                        # Если запись существует и статус "Новое", обновляем его
                        if user_status[0] == Word.STATUS_NEW:
                            cursor.execute(
                                """
                                UPDATE user_word_status 
                                SET status = ?, last_updated = CURRENT_TIMESTAMP 
                                WHERE user_id = ? AND word_id = ?
                                """,
                                (Word.STATUS_STUDYING, user_id, word_id)
                            )
                            logger.info(f"Updated word {word_id} user status from New to Active for user {user_id}")
                    else:
                        # Если записи нет, создаем новую со статусом "Активное"
                        cursor.execute(
                            """
                            INSERT INTO user_word_status (user_id, word_id, status, last_updated) 
                            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                            """,
                            (user_id, word_id, Word.STATUS_STUDYING)
                        )
                        logger.info(
                            f"Created new user status record for word {word_id} with Active status for user {user_id}")

                conn.commit()
        except Exception as e:
            logger.error(f"Error updating word status when adding to deck: {e}")

        return card_id

    def sync_word_status(self, user_id: int) -> Dict[str, Any]:
        """
        Synchronize word status with deck card status.
        Updates any words that are in decks but still have "New" status.

        Args:
            user_id (int): User ID

        Returns:
            Dict[str, Any]: Results with counts of updated words
        """
        # Get all decks for the user
        decks = self.srs_repo.get_decks_by_user(user_id)
        if not decks:
            return {
                'success': True,
                'updated_count': 0,
                'message': 'No decks found for the user'
            }

        # Get all cards in all user's decks
        word_ids_to_update = set()

        for deck in decks:
            # Get all cards in this deck
            cards = self.srs_repo.get_cards_by_deck(deck.id)
            for card in cards:
                # Get the associated word
                word = self.user_repo.get_word(card.word_id)
                if word and word.status == Word.STATUS_NEW:
                    word_ids_to_update.add(word.id)

        # Update all the word statuses
        updated_count = 0
        for word_id in word_ids_to_update:
            self.user_repo.set_word_status(user_id, word_id, Word.STATUS_STUDYING)
            updated_count += 1

        return {
            'success': True,
            'updated_count': updated_count,
            'message': f'Successfully updated {updated_count} words to Active status'
        }

    def remove_word_from_deck(self, card_id: int) -> bool:
        """
        Remove a word from a deck.

        Args:
            card_id (int): Card ID

        Returns:
            bool: True if successful, False otherwise
        """
        return self.srs_repo.delete_card(card_id)

    def move_word_to_deck(self, card_id: int, new_deck_id: int) -> bool:
        """
        Move a word from one deck to another.

        Args:
            card_id (int): Card ID
            new_deck_id (int): New deck ID

        Returns:
            bool: True if successful, False otherwise
        """
        card = self.srs_repo.get_card_by_id(card_id)
        if not card:
            return False

        # Create card in new deck
        self.create_card(new_deck_id, card.word_id)

        # Delete card from old deck
        self.srs_repo.delete_card(card_id)

        return True

    def get_word_decks(self, user_id: int, word_id: int) -> List[Dict[str, Any]]:
        """
        Get all decks containing a word.

        Args:
            user_id (int): User ID
            word_id (int): Word ID

        Returns:
            List[Dict[str, Any]]: List of deck data
        """
        all_decks = self.srs_repo.get_decks_by_user(user_id)
        result = []

        for deck in all_decks:
            card = self.srs_repo.get_card_by_deck_and_word(deck.id, word_id)
            if card:
                deck_dict = deck.to_dict()
                deck_dict['card_id'] = card.id
                result.append(deck_dict)

        return result

    # === Review Session Management ===

    def get_cards_for_review(self, deck_id: int, limit_new: bool = True) -> List[Dict[str, Any]]:
        """
        Get cards due for review today.

        Args:
            deck_id (int): Deck ID
            limit_new (bool, optional): Whether to limit new cards per day. Defaults to True.

        Returns:
            List[Dict[str, Any]]: List of cards for review
        """
        today = date.today()
        cards = self.srs_repo.get_cards_due(deck_id, today)

        # Separate new and review cards
        new_cards = [c for c in cards if c['interval'] == 0 and c['repetitions'] == 0]
        review_cards = [c for c in cards if c['interval'] > 0 or c['repetitions'] > 0]

        # Limit new cards if needed
        if limit_new and len(new_cards) > self.NEW_CARDS_PER_DAY:
            new_cards = new_cards[:self.NEW_CARDS_PER_DAY]

        # Combine and return
        return review_cards + new_cards

    def process_review(
            self,
            card_id: int,
            user_id: int,
            difficulty: str,
            same_session_review: bool = True
    ) -> Dict[str, Any]:
        """
        Process a review response using the SM-2 algorithm.

        Args:
            card_id (int): Card ID
            user_id (int): User ID
            difficulty (str): Response difficulty ('again', 'hard', 'good', 'easy')

        Returns:
            Dict[str, Any]: Updated card data
        """
        card = self.srs_repo.get_card_by_id(card_id)
        if not card:
            raise ValueError(f"Card with ID {card_id} not found")

        today = date.today()

        # Apply SM-2 algorithm based on difficulty
        if difficulty == 'again':
            # User couldn't recall the word - reset progress
            card.repetitions = 0
            card.interval = 0  # Show again today
            card.lapses += 1
            card.ease_factor = max(1.3, card.ease_factor - 0.2)  # Decrease EF but maintain minimum threshold

        elif difficulty == 'hard':
            # User recalled with significant difficulty
            card.repetitions += 1
            if card.interval == 0:
                card.interval = 1  # First successful review - schedule for tomorrow
            else:
                # Apply smaller interval growth for 'hard' responses
                card.interval = max(1, int(card.interval * 1.2))
            card.ease_factor = max(1.3, card.ease_factor - 0.15)  # Slightly decrease ease factor

        elif difficulty == 'good':
            # Standard successful recall - normal progression
            card.repetitions += 1
            if card.interval == 0:
                card.interval = 1  # First successful review - schedule for tomorrow
            elif card.interval == 1:
                card.interval = 3  # Second successful review - schedule for 3 days later
            else:
                # Standard interval calculation using current ease factor
                card.interval = int(card.interval * card.ease_factor)
            # Ease factor remains unchanged for 'good' responses

        elif difficulty == 'easy':
            # User recalled very easily - accelerated progression
            card.repetitions += 1
            if card.interval == 0:
                card.interval = 2  # First successful review but easy - schedule for 2 days later
            elif card.interval == 1:
                card.interval = 4  # Second successful review but easy - schedule for 4 days later
            else:
                # Apply bonus multiplier for 'easy' responses
                card.interval = int(card.interval * card.ease_factor * 1.3)  # 30% bonus
            card.ease_factor = min(card.ease_factor + 0.15, 2.5)  # Increase ease factor with upper limit

        # Set next review date
        if card.interval == 0:
            # Show again in the same session or today
            if same_session_review:
                # For same-session review, the frontend will handle the timing
                # The backend just marks it as due today
                card.next_review_date = today
            else:
                # If not doing same-session review, still make it due today
                # but don't show it again immediately in the current session
                card.next_review_date = today
        else:
            card.next_review_date = today + timedelta(days=card.interval)
        card.last_review_date = today

        # Update card in database
        updated_card = self.srs_repo.update_card(
            card_id=card.id,
            next_review_date=card.next_review_date,
            last_review_date=card.last_review_date,
            interval=card.interval,
            repetitions=card.repetitions,
            ease_factor=card.ease_factor,
            lapses=card.lapses
        )

        # Log the review session
        self.srs_repo.log_review_session(user_id, today, 1)

        # Check if card should be marked as learned
        if card.repetitions >= self.LEARNED_THRESHOLD:
            deck = self.srs_repo.get_deck_by_id(card.deck_id)
            if deck:
                # Update word status to "Learned"
                self.user_repo.set_word_status(user_id, card.word_id, Word.STATUS_STUDIED)

        # Return card data
        return updated_card.to_dict() if updated_card else {}

    # === Word Status Integration ===

    def handle_word_status_change(self, user_id: int, word_id: int, new_status: int) -> None:
        """
        Handle word status changes.

        Args:
            user_id (int): User ID
            word_id (int): Word ID
            new_status (int): New status
        """
        main_deck = self.get_or_create_main_deck(user_id)

        if new_status == Word.STATUS_STUDYING:
            # Add to main deck
            self.add_word_to_deck(user_id, word_id, main_deck.id)

        elif new_status == Word.STATUS_STUDIED:
            # Mark as learned in database but keep in deck
            # (could remove from deck depending on requirements)
            pass

    # === Statistics ===

    def get_user_statistics(self, user_id: int) -> Dict[str, Any]:
        """
        Get learning statistics for a user.

        Args:
            user_id (int): User ID

        Returns:
            Dict[str, Any]: Dictionary with statistics
        """
        # Get current streak
        streak = self.srs_repo.get_user_streak(user_id)

        # Get recent sessions (last 30 days)
        sessions = self.srs_repo.get_review_sessions(user_id, 30)

        # Total cards reviewed in last 30 days
        total_reviewed = sum(s['cards_reviewed'] for s in sessions)

        # Calculate cards per day (average)
        avg_per_day = total_reviewed / 30 if total_reviewed > 0 else 0

        # Get word counts by status
        status_counts = self.user_repo.get_status_statistics(user_id)

        return {
            'streak': streak,
            'total_reviewed_30d': total_reviewed,
            'avg_per_day': avg_per_day,
            'status_counts': status_counts,
            'review_history': sessions
        }

    def get_deck_card_counts(self, deck_id: int) -> Dict[str, int]:
        """
        Get card counts by category for a deck.
        Only counts cards that are due today or earlier.

        Args:
            deck_id (int): Deck ID

        Returns:
            Dict[str, int]: Dictionary with counts for each category
        """
        today = date.today()

        # Get all cards in the deck
        cards = self.srs_repo.get_cards_by_deck(deck_id)

        # Initialize counters
        new_count = 0
        learning_count = 0
        review_count = 0

        for card in cards:
            # Skip cards that are scheduled for future dates
            if card.next_review_date and card.next_review_date > today:
                continue

            # Count cards based on their status
            if card.interval == 0 and card.repetitions == 0:
                new_count += 1
            elif card.repetitions > 0 and card.repetitions < self.LEARNED_THRESHOLD:
                learning_count += 1
            else:
                review_count += 1

        return {
            'new': new_count,
            'learning': learning_count,
            'review': review_count
        }

    def get_filtered_cards(self, deck_id: int, filter_type: str) -> List[DeckCard]:
        """
        Get filtered cards from a deck based on specified filter type.

        Args:
            deck_id (int): Deck ID
            filter_type (str): Type of filter ('new', 'learning', 'review')

        Returns:
            List[DeckCard]: List of filtered cards
        """
        today = date.today()

        if filter_type == 'new':
            return self.srs_repo.get_cards_by_deck_filtered(
                deck_id,
                filters={'repetitions': 0},
                limit=self.NEW_CARDS_PER_DAY
            )
        elif filter_type == 'learning':
            # Only cards that are in learning phase AND due today
            return self.srs_repo.get_cards_by_deck_filtered(
                deck_id,
                filters={
                    'repetitions_gt': 0,
                    'next_review_date_lte': today.isoformat()
                }
            )
        elif filter_type == 'review':
            return self.srs_repo.get_cards_by_deck_filtered(
                deck_id,
                filters={'next_review_date_lte': today.isoformat()}
            )
        else:
            # Default: return all cards
            return self.srs_repo.get_cards_by_deck(deck_id)

    def get_total_card_counts(self, user_id: int) -> Dict[str, int]:
        """
        Get total card counts by category across all decks.

        Args:
            user_id (int): User ID

        Returns:
            Dict[str, int]: Dictionary with total counts for each category
        """
        decks = self.srs_repo.get_decks_by_user(user_id)

        total_new = 0
        total_learning = 0
        total_review = 0

        for deck in decks:
            counts = self.get_deck_card_counts(deck.id)
            total_new += counts['new']
            total_learning += counts['learning']
            total_review += counts['review']

        return {
            'total_new': total_new,
            'total_learning': total_learning,
            'total_review': total_review
        }

    def get_all_deck_cards(self, deck_id: int) -> List[Dict[str, Any]]:
        """
        Get all cards from a deck, regardless of review schedule.
        Used for extra review sessions.

        Args:
            deck_id (int): Deck ID

        Returns:
            List[Dict[str, Any]]: List of cards with complete data
        """
        try:
            # Get all cards in the deck - ensure we're getting everything
            cards = self.srs_repo.get_cards_by_deck(deck_id)

            logger.info(f"Found {len(cards)} cards in deck {deck_id} for extra session")

            if not cards:
                logger.warning(f"No cards found in deck {deck_id} for extra session")
                return []

            # Process cards to add word data
            result = []
            for card in cards:
                # Convert card to dictionary
                if hasattr(card, 'to_dict'):
                    card_dict = card.to_dict()
                else:
                    card_dict = dict(vars(card))

                # Get word data directly from database to ensure it works
                try:
                    import sqlite3
                    from config.settings import DB_FILE

                    conn = sqlite3.connect(DB_FILE)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()

                    cursor.execute(
                        "SELECT * FROM collection_words WHERE id = ?",
                        (card.word_id,)
                    )

                    word_data = cursor.fetchone()
                    conn.close()

                    if word_data:
                        word_dict = dict(word_data)
                        logger.info(f"Found word data for word_id {card.word_id}: {word_dict.get('english_word')}")
                    else:
                        word_dict = {'english_word': f'Word {card.word_id}', 'russian_word': ''}
                        logger.warning(f"No word data found for word_id {card.word_id}")
                except Exception as e:
                    logger.error(f"Error getting word data via direct DB access: {e}")
                    word_dict = {'english_word': f'Word {card.word_id}', 'russian_word': ''}

                # Add word data to card dictionary
                card_dict.update({
                    'english_word': word_dict.get('english_word', ''),
                    'russian_word': word_dict.get('russian_word', ''),
                    'sentences': word_dict.get('sentences', ''),
                    'get_download': word_dict.get('get_download', 0)
                })

                result.append(card_dict)

            logger.info(f"Processed {len(result)} cards with word data for extra session")
            return result
        except Exception as e:
            logger.error(f"Error getting all deck cards: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def get_detailed_user_statistics(self, user_id: int) -> Dict[str, Any]:
        """
        Get detailed user statistics for UI display.

        Args:
            user_id (int): User ID

        Returns:
            Dict[str, Any]: Dictionary with detailed statistics
        """
        # Get detailed statistics from repository
        detailed_stats = self.srs_repo.get_detailed_user_statistics(user_id)

        # Get basic statistics
        basic_stats = self.get_user_statistics(user_id)

        # Merge stats
        stats = {**basic_stats, **detailed_stats}

        return stats
