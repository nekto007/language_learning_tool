"""
Repository for SRS (Spaced Repetition System) functionality.
"""
import logging
import sqlite3
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

from src.db.models import Word
from src.srs.models import Deck, DeckCard, ReviewSessionLog

logger = logging.getLogger(__name__)


class SRSRepository:
    """Repository for SRS database operations."""

    def __init__(self, db_path: str):
        """
        Initialize the SRS repository.

        Args:
            db_path (str): Path to SQLite database
        """
        self.db_path = db_path

    def initialize_schema(self) -> None:
        """Initialize SRS database schema."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Create deck table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS deck (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        description TEXT,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    );
                """)

                # Create deck_card table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS deck_card (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        deck_id INTEGER NOT NULL,
                        word_id INTEGER NOT NULL,
                        next_review_date DATE,
                        last_review_date DATE,
                        interval INTEGER DEFAULT 0,
                        repetitions INTEGER DEFAULT 0,
                        ease_factor REAL DEFAULT 2.5,
                        lapses INTEGER DEFAULT 0,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (deck_id) REFERENCES deck(id),
                        FOREIGN KEY (word_id) REFERENCES collection_words(id),
                        UNIQUE (deck_id, word_id)
                    );
                """)

                # Create review_session_log table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS review_session_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        session_date DATE NOT NULL,
                        cards_reviewed INTEGER NOT NULL DEFAULT 0,
                        duration_seconds INTEGER,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        UNIQUE (user_id, session_date)
                    );
                """)

                # Create indexes
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_deck_user_id ON deck(user_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_deck_card_deck_id ON deck_card(deck_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_deck_card_word_id ON deck_card(word_id);")
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_deck_card_next_review_date ON deck_card(next_review_date);")

                conn.commit()
                logger.info("SRS schema initialized")
        except sqlite3.Error as e:
            logger.error(f"Error initializing SRS schema: {e}")
            raise

    # === Deck Operations ===

    def create_deck(self, user_id: int, name: str, description: Optional[str] = None) -> int:
        """
        Create a new deck.

        Args:
            user_id (int): User ID
            name (str): Deck name
            description (Optional[str], optional): Deck description. Defaults to None.

        Returns:
            int: ID of the created deck
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO deck (user_id, name, description)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, name, description)
                )
                conn.commit()
                return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Error creating deck: {e}")
            raise

    def get_deck_by_id(self, deck_id: int) -> Optional[Deck]:
        """
        Get a deck by ID.

        Args:
            deck_id (int): Deck ID

        Returns:
            Optional[Deck]: Deck object if found, None otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM deck WHERE id = ?", (deck_id,))
                row = cursor.fetchone()

                if row:
                    return Deck.from_dict(dict(row))
                return None
        except sqlite3.Error as e:
            logger.error(f"Error getting deck: {e}")
            raise

    def get_decks_by_user(self, user_id: int) -> List[Deck]:
        """
        Get all decks for a user.

        Args:
            user_id (int): User ID

        Returns:
            List[Deck]: List of Deck objects
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM deck WHERE user_id = ? ORDER BY name",
                    (user_id,)
                )
                rows = cursor.fetchall()
                return [Deck.from_dict(dict(row)) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Error getting decks: {e}")
            raise

    def get_main_deck(self, user_id: int) -> Optional[Deck]:
        """
        Get the main deck for a user.

        Args:
            user_id (int): User ID

        Returns:
            Optional[Deck]: Main deck if found, None otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM deck WHERE user_id = ? AND name = ? LIMIT 1",
                    (user_id, "Основная колода")
                )
                row = cursor.fetchone()
                if row:
                    return Deck.from_dict(dict(row))
                return None
        except sqlite3.Error as e:
            logger.error(f"Error getting main deck: {e}")
            raise

    def update_deck(self, deck_id: int, name: Optional[str] = None, description: Optional[str] = None) -> bool:
        """
        Update a deck.

        Args:
            deck_id (int): Deck ID
            name (Optional[str], optional): New deck name. Defaults to None.
            description (Optional[str], optional): New deck description. Defaults to None.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                update_fields = []
                params = []

                if name is not None:
                    update_fields.append("name = ?")
                    params.append(name)

                if description is not None:
                    update_fields.append("description = ?")
                    params.append(description)

                if not update_fields:
                    return True

                update_fields.append("updated_at = CURRENT_TIMESTAMP")
                params.append(deck_id)

                query = f"UPDATE deck SET {', '.join(update_fields)} WHERE id = ?"
                cursor.execute(query, params)
                conn.commit()

                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error updating deck: {e}")
            raise

    def delete_deck(self, deck_id: int) -> bool:
        """
        Delete a deck.

        Args:
            deck_id (int): Deck ID

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # First delete all cards in the deck
                cursor.execute("DELETE FROM deck_card WHERE deck_id = ?", (deck_id,))

                # Then delete the deck
                cursor.execute("DELETE FROM deck WHERE id = ?", (deck_id,))
                conn.commit()

                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error deleting deck: {e}")
            raise

    # === Card Operations ===

    def create_card(
            self,
            deck_id: int,
            word_id: int,
            next_review_date: Optional[date] = None,
            last_review_date: Optional[date] = None,
            interval: int = 0,
            repetitions: int = 0,
            ease_factor: float = 2.5,
            lapses: int = 0
    ) -> int:
        """
        Create a new card in a deck.

        Args:
            deck_id (int): Deck ID
            word_id (int): Word ID
            next_review_date (Optional[date], optional): Next review date. Defaults to None.
            last_review_date (Optional[date], optional): Last review date. Defaults to None.
            interval (int, optional): Interval in days. Defaults to 0.
            repetitions (int, optional): Number of successful repetitions. Defaults to 0.
            ease_factor (float, optional): Ease factor. Defaults to 2.5.
            lapses (int, optional): Number of lapses. Defaults to 0.

        Returns:
            int: Card ID
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Format dates as strings
                next_review_str = next_review_date.isoformat() if next_review_date else date.today().isoformat()
                last_review_str = last_review_date.isoformat() if last_review_date else None

                cursor.execute(
                    """
                    INSERT INTO deck_card (
                        deck_id, word_id, next_review_date, last_review_date,
                        interval, repetitions, ease_factor, lapses
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        deck_id, word_id, next_review_str, last_review_str,
                        interval, repetitions, ease_factor, lapses
                    )
                )
                conn.commit()
                return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Error creating card: {e}")
            raise

    def get_card_by_id(self, card_id: int) -> Optional[DeckCard]:
        """
        Get a card by ID.

        Args:
            card_id (int): Card ID

        Returns:
            Optional[DeckCard]: Card object if found, None otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM deck_card WHERE id = ?", (card_id,))
                row = cursor.fetchone()

                if row:
                    card_dict = dict(row)

                    # Convert date strings to date objects
                    if card_dict.get('next_review_date'):
                        card_dict['next_review_date'] = date.fromisoformat(card_dict['next_review_date'])
                    if card_dict.get('last_review_date'):
                        card_dict['last_review_date'] = date.fromisoformat(card_dict['last_review_date'])

                    return DeckCard.from_dict(card_dict)
                return None
        except sqlite3.Error as e:
            logger.error(f"Error getting card: {e}")
            raise

    def get_card_by_deck_and_word(self, deck_id: int, word_id: int) -> Optional[DeckCard]:
        """
        Get a card by deck and word IDs.

        Args:
            deck_id (int): Deck ID
            word_id (int): Word ID

        Returns:
            Optional[DeckCard]: Card object if found, None otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM deck_card WHERE deck_id = ? AND word_id = ?",
                    (deck_id, word_id)
                )
                row = cursor.fetchone()

                if row:
                    card_dict = dict(row)

                    # Convert date strings to date objects
                    if card_dict.get('next_review_date'):
                        card_dict['next_review_date'] = date.fromisoformat(card_dict['next_review_date'])
                    if card_dict.get('last_review_date'):
                        card_dict['last_review_date'] = date.fromisoformat(card_dict['last_review_date'])

                    return DeckCard.from_dict(card_dict)
                return None
        except sqlite3.Error as e:
            logger.error(f"Error getting card: {e}")
            raise

    def get_cards_by_deck(self, deck_id: int) -> List[DeckCard]:
        """
        Get all cards in a deck.

        Args:
            deck_id (int): Deck ID

        Returns:
            List[DeckCard]: List of Card objects
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM deck_card WHERE deck_id = ?", (deck_id,))
                rows = cursor.fetchall()

                cards = []
                for row in rows:
                    card_dict = dict(row)

                    # Convert date strings to date objects
                    if card_dict.get('next_review_date'):
                        card_dict['next_review_date'] = date.fromisoformat(card_dict['next_review_date'])
                    if card_dict.get('last_review_date'):
                        card_dict['last_review_date'] = date.fromisoformat(card_dict['last_review_date'])

                    cards.append(DeckCard.from_dict(card_dict))

                return cards
        except sqlite3.Error as e:
            logger.error(f"Error getting cards: {e}")
            raise

    def get_cards_due(self, deck_id: int, due_date: date = None) -> List[Dict[str, Any]]:
        """
        Get cards due for review by a certain date.

        Args:
            deck_id (int): Deck ID
            due_date (date, optional): Due date. Defaults to today.

        Returns:
            List[Dict[str, Any]]: List of card data with word information
        """
        if due_date is None:
            due_date = date.today()

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT dc.*, cw.english_word, cw.russian_word, cw.sentences, cw.get_download
                    FROM deck_card dc
                    JOIN collection_words cw ON dc.word_id = cw.id
                    WHERE dc.deck_id = ? AND dc.next_review_date <= ?
                    ORDER BY dc.next_review_date
                    """,
                    (deck_id, due_date.isoformat())
                )
                rows = cursor.fetchall()

                cards = []
                for row in rows:
                    card_dict = dict(row)

                    # Convert date strings to date objects
                    if card_dict.get('next_review_date'):
                        card_dict['next_review_date'] = date.fromisoformat(card_dict['next_review_date'])
                    if card_dict.get('last_review_date'):
                        card_dict['last_review_date'] = date.fromisoformat(card_dict['last_review_date'])

                    cards.append(card_dict)

                return cards
        except sqlite3.Error as e:
            logger.error(f"Error getting due cards: {e}")
            raise

    def update_card(
            self,
            card_id: int,
            next_review_date: Optional[date] = None,
            last_review_date: Optional[date] = None,
            interval: Optional[int] = None,
            repetitions: Optional[int] = None,
            ease_factor: Optional[float] = None,
            lapses: Optional[int] = None
    ) -> Optional[DeckCard]:
        """
        Update a card's SRS parameters.

        Args:
            card_id (int): Card ID
            next_review_date (Optional[date], optional): Next review date. Defaults to None.
            last_review_date (Optional[date], optional): Last review date. Defaults to None.
            interval (Optional[int], optional): Interval in days. Defaults to None.
            repetitions (Optional[int], optional): Number of successful repetitions. Defaults to None.
            ease_factor (Optional[float], optional): Ease factor. Defaults to None.
            lapses (Optional[int], optional): Number of lapses. Defaults to None.

        Returns:
            Optional[DeckCard]: Updated card object if successful, None otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                update_fields = []
                params = []

                if next_review_date is not None:
                    update_fields.append("next_review_date = ?")
                    params.append(next_review_date.isoformat())

                if last_review_date is not None:
                    update_fields.append("last_review_date = ?")
                    params.append(last_review_date.isoformat())

                if interval is not None:
                    update_fields.append("interval = ?")
                    params.append(interval)

                if repetitions is not None:
                    update_fields.append("repetitions = ?")
                    params.append(repetitions)

                if ease_factor is not None:
                    update_fields.append("ease_factor = ?")
                    params.append(ease_factor)

                if lapses is not None:
                    update_fields.append("lapses = ?")
                    params.append(lapses)

                if not update_fields:
                    return self.get_card_by_id(card_id)

                update_fields.append("updated_at = CURRENT_TIMESTAMP")
                params.append(card_id)

                query = f"UPDATE deck_card SET {', '.join(update_fields)} WHERE id = ?"
                cursor.execute(query, params)
                conn.commit()

                if cursor.rowcount > 0:
                    return self.get_card_by_id(card_id)
                return None
        except sqlite3.Error as e:
            logger.error(f"Error updating card: {e}")
            raise

    def delete_card(self, card_id: int) -> bool:
        """
        Delete a card.

        Args:
            card_id (int): Card ID

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM deck_card WHERE id = ?", (card_id,))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error deleting card: {e}")
            raise

    # === Statistics and Session Logging ===

    def log_review_session(
            self,
            user_id: int,
            session_date: date,
            cards_reviewed: int,
            duration_seconds: Optional[int] = None
    ) -> int:
        """
        Log a review session.

        Args:
            user_id (int): User ID
            session_date (date): Session date
            cards_reviewed (int): Number of cards reviewed
            duration_seconds (Optional[int], optional): Session duration in seconds. Defaults to None.

        Returns:
            int: ID of the log entry
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Check if entry exists for this date
                cursor.execute(
                    "SELECT id, cards_reviewed FROM review_session_log WHERE user_id = ? AND session_date = ?",
                    (user_id, session_date.isoformat())
                )
                existing = cursor.fetchone()

                if existing:
                    # Update existing entry
                    log_id, existing_count = existing
                    cursor.execute(
                        """
                        UPDATE review_session_log 
                        SET cards_reviewed = ?, duration_seconds = ?
                        WHERE id = ?
                        """,
                        (existing_count + cards_reviewed, duration_seconds, log_id)
                    )
                    conn.commit()
                    return log_id
                else:
                    # Create new entry
                    cursor.execute(
                        """
                        INSERT INTO review_session_log (user_id, session_date, cards_reviewed, duration_seconds)
                        VALUES (?, ?, ?, ?)
                        """,
                        (user_id, session_date.isoformat(), cards_reviewed, duration_seconds)
                    )
                    conn.commit()
                    return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Error logging review session: {e}")
            raise

    def get_review_sessions(self, user_id: int, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get review sessions for a user.

        Args:
            user_id (int): User ID
            days (int, optional): Number of days to retrieve. Defaults to 30.

        Returns:
            List[Dict[str, Any]]: List of session data
        """
        start_date = (date.today() - timedelta(days=days)).isoformat()

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM review_session_log
                    WHERE user_id = ? AND session_date >= ?
                    ORDER BY session_date
                    """,
                    (user_id, start_date)
                )
                rows = cursor.fetchall()

                sessions = []
                for row in rows:
                    session_dict = dict(row)
                    session_dict['session_date'] = date.fromisoformat(session_dict['session_date'])
                    sessions.append(session_dict)

                return sessions
        except sqlite3.Error as e:
            logger.error(f"Error getting review sessions: {e}")
            raise

    def get_user_streak(self, user_id: int) -> int:
        """
        Get the current learning streak for a user.

        Args:
            user_id (int): User ID

        Returns:
            int: Number of consecutive days with reviews
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                today = date.today()
                streak = 0

                # Check if there's a session today
                cursor.execute(
                    "SELECT COUNT(*) FROM review_session_log WHERE user_id = ? AND session_date = ?",
                    (user_id, today.isoformat())
                )
                has_today = cursor.fetchone()[0] > 0

                if has_today:
                    streak = 1
                    check_date = today - timedelta(days=1)
                else:
                    # If no session today, check if there was one yesterday
                    yesterday = today - timedelta(days=1)
                    cursor.execute(
                        "SELECT COUNT(*) FROM review_session_log WHERE user_id = ? AND session_date = ?",
                        (user_id, yesterday.isoformat())
                    )
                    has_yesterday = cursor.fetchone()[0] > 0

                    if not has_yesterday:
                        return 0

                    streak = 1
                    check_date = yesterday - timedelta(days=1)

                # Check previous days
                while True:
                    cursor.execute(
                        "SELECT COUNT(*) FROM review_session_log WHERE user_id = ? AND session_date = ?",
                        (user_id, check_date.isoformat())
                    )
                    has_session = cursor.fetchone()[0] > 0

                    if not has_session:
                        break

                    streak += 1
                    check_date -= timedelta(days=1)

                return streak
        except sqlite3.Error as e:
            logger.error(f"Error calculating user streak: {e}")
            return 0

    def get_deck_statistics(self, deck_id: int) -> Dict[str, int]:
        """
        Get statistics for a deck.

        Args:
            deck_id (int): Deck ID

        Returns:
            Dict[str, int]: Dictionary with statistics
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                today = date.today().isoformat()

                # Get total cards
                cursor.execute("SELECT COUNT(*) FROM deck_card WHERE deck_id = ?", (deck_id,))
                total_cards = cursor.fetchone()[0]

                # Get cards due today
                cursor.execute(
                    "SELECT COUNT(*) FROM deck_card WHERE deck_id = ? AND next_review_date <= ?",
                    (deck_id, today)
                )
                due_today = cursor.fetchone()[0]

                # Get new cards (not reviewed yet)
                cursor.execute(
                    "SELECT COUNT(*) FROM deck_card WHERE deck_id = ? AND interval = 0 AND repetitions = 0 LIMIT 30",
                    (deck_id,)
                )
                new_cards = cursor.fetchone()[0]

                # Get learning cards (repetitions > 0, next_review_date > today)
                cursor.execute(
                    "SELECT COUNT(*) FROM deck_card WHERE deck_id = ? AND repetitions > 0 AND next_review_date > ?",
                    (deck_id, today)
                )
                learning_cards = cursor.fetchone()[0]

                # Get learned cards (repetitions >= 7)
                cursor.execute(
                    "SELECT COUNT(*) FROM deck_card WHERE deck_id = ? AND repetitions >= 7",
                    (deck_id,)
                )
                learned_cards = cursor.fetchone()[0]

                return {
                    'total_cards': total_cards,
                    'due_today': due_today,
                    'new_cards': new_cards,
                    'learning_cards': learning_cards,
                    'learned_cards': learned_cards,
                }
        except sqlite3.Error as e:
            logger.error(f"Error getting deck statistics: {e}")
            return {
                'total_cards': 0,
                'due_today': 0,
                'new_cards': 0,
                'learning_cards': 0,
                'learned_cards': 0,
            }

    def get_deck_card_counts(self, deck_id: int, new_cards_per_day: int = 30) -> Dict[str, int]:
        """
        Get card counts by category (new, learning, review) for a deck.

        Args:
            deck_id (int): Deck ID
            new_cards_per_day (int): Maximum new cards per day

        Returns:
            Dict[str, int]: Dictionary with counts for each category
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                today = date.today().isoformat()

                # Count new cards (limit by new_cards_per_day)
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM deck_card 
                    WHERE deck_id = ? AND repetitions = 0
                    LIMIT ?
                    """,
                    (deck_id, new_cards_per_day)
                )
                new_count = cursor.fetchone()[0]

                # Count cards in learning (repetitions > 0, next_review_date > today)
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM deck_card 
                    WHERE deck_id = ? 
                    AND repetitions > 0 
                    AND next_review_date > ?
                    """,
                    (deck_id, today)
                )
                learning_count = cursor.fetchone()[0]

                # Count cards to review (next_review_date <= today)
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM deck_card 
                    WHERE deck_id = ? 
                    AND next_review_date <= ?
                    """,
                    (deck_id, today)
                )
                review_count = cursor.fetchone()[0]

                return {
                    'new': new_count,
                    'learning': learning_count,
                    'review': review_count
                }
        except sqlite3.Error as e:
            logger.error(f"Error getting card counts: {e}")
            return {'new': 0, 'learning': 0, 'review': 0}

    def get_cards_by_deck_filtered(
            self, deck_id: int, filters: Dict[str, Any], limit: Optional[int] = None
    ) -> List[DeckCard]:
        """
        Get filtered cards from a deck.

        Args:
            deck_id (int): Deck ID
            filters (Dict[str, Any]): Filter conditions
                - repetitions: Equal to value
                - repetitions_gt: Greater than value
                - next_review_date_gt: Review date greater than value
                - next_review_date_lte: Review date less than or equal to value
            limit (Optional[int]): Maximum number of cards to return

        Returns:
            List[DeckCard]: List of filtered Card objects
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                query = "SELECT * FROM deck_card WHERE deck_id = ?"
                params = [deck_id]

                # Add filter conditions
                if 'repetitions' in filters:
                    query += " AND repetitions = ?"
                    params.append(filters['repetitions'])

                if 'repetitions_gt' in filters:
                    query += " AND repetitions > ?"
                    params.append(filters['repetitions_gt'])

                if 'next_review_date_gt' in filters:
                    query += " AND next_review_date > ?"
                    params.append(filters['next_review_date_gt'])

                if 'next_review_date_lte' in filters:
                    query += " AND next_review_date <= ?"
                    params.append(filters['next_review_date_lte'])

                # Add limit
                if limit is not None:
                    query += " LIMIT ?"
                    params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()

                cards = []
                for row in rows:
                    card_dict = dict(row)

                    # Convert date strings to date objects
                    if card_dict.get('next_review_date'):
                        card_dict['next_review_date'] = date.fromisoformat(card_dict['next_review_date'])
                    if card_dict.get('last_review_date'):
                        card_dict['last_review_date'] = date.fromisoformat(card_dict['last_review_date'])

                    cards.append(DeckCard.from_dict(card_dict))

                return cards
        except sqlite3.Error as e:
            logger.error(f"Error getting filtered cards: {e}")
            raise

    def get_user_activity_heatmap(self, user_id: int, days: int = 365) -> Dict[str, int]:
        """
        Get user activity heatmap data for visualization.

        Args:
            user_id (int): User ID
            days (int): Number of days to retrieve (default: 365)

        Returns:
            Dict[str, int]: Dictionary with day index -> cards reviewed
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Calculate start date (days ago from today)
                end_date = date.today()
                start_date = end_date - timedelta(days=days)

                # Get activity data
                cursor.execute(
                    """
                    SELECT session_date, cards_reviewed 
                    FROM review_session_log
                    WHERE user_id = ? AND session_date >= ?
                    ORDER BY session_date
                    """,
                    (user_id, start_date.isoformat())
                )
                rows = cursor.fetchall()

                # Convert to dict with day index (0-364) as key
                result = {}
                for row in rows:
                    session_date = date.fromisoformat(row['session_date'])
                    day_index = (session_date - start_date).days
                    if 0 <= day_index < days:
                        result[str(day_index)] = row['cards_reviewed']

                return result
        except sqlite3.Error as e:
            logger.error(f"Error getting user activity heatmap: {e}")
            return {}

    def get_detailed_user_statistics(self, user_id: int) -> Dict[str, Any]:
        """
        Get detailed user statistics including streaks and averages.

        Args:
            user_id (int): User ID

        Returns:
            Dict[str, Any]: Dictionary with detailed statistics
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Get activity data for the last 365 days
                today = date.today()
                start_date = today - timedelta(days=365)
                cursor.execute(
                    """
                    SELECT session_date, cards_reviewed, duration_seconds
                    FROM review_session_log
                    WHERE user_id = ? AND session_date >= ?
                    ORDER BY session_date
                    """,
                    (user_id, start_date.isoformat())
                )
                rows = cursor.fetchall()

                # Process activity data
                total_cards = 0
                active_days = 0
                longest_streak = 0
                current_streak = 0
                current_streak_active = False
                daily_streak = 0
                cards_today = 0
                minutes_today = 0

                # Process each day's data
                day_data = {}
                for row in rows:
                    session_date = date.fromisoformat(row['session_date'])
                    cards = row['cards_reviewed']
                    duration = row['duration_seconds'] or 0

                    # Add to day_data
                    day_str = session_date.isoformat()
                    if day_str in day_data:
                        day_data[day_str]['cards'] += cards
                        day_data[day_str]['duration'] += duration
                    else:
                        day_data[day_str] = {'cards': cards, 'duration': duration}

                    # Update today's stats
                    if session_date == today:
                        cards_today += cards
                        minutes_today += duration / 60

                # Sort dates
                sorted_dates = sorted(day_data.keys())
                if sorted_dates:
                    # Calculate active days
                    active_days = len(sorted_dates)

                    # Calculate streaks
                    date_set = set(sorted_dates)
                    streak = 0

                    # Calculate current streak
                    check_date = today
                    while check_date.isoformat() in date_set:
                        current_streak += 1
                        check_date -= timedelta(days=1)

                    # Calculate longest streak
                    for i, day_str in enumerate(sorted_dates):
                        day = date.fromisoformat(day_str)

                        # Check if this day continues a streak
                        prev_day = day - timedelta(days=1)
                        if prev_day.isoformat() in date_set:
                            streak += 1
                        else:
                            streak = 1  # Start of a new streak

                        longest_streak = max(longest_streak, streak)

                    # Calculate total cards
                    total_cards = sum(data['cards'] for data in day_data.values())

                # Calculate averages
                days_elapsed = (today - start_date).days + 1  # Include today
                days_learned_percent = round((active_days / days_elapsed) * 100) if days_elapsed > 0 else 0
                daily_average = round(total_cards / days_elapsed) if days_elapsed > 0 else 0

                # Get heatmap data
                heatmap = self.get_user_activity_heatmap(user_id)

                return {
                    'total_cards': total_cards,
                    'active_days': active_days,
                    'days_elapsed': days_elapsed,
                    'days_learned_percent': days_learned_percent,
                    'longest_streak': longest_streak,
                    'current_streak': current_streak,
                    'daily_average': daily_average,
                    'cards_today': cards_today,
                    'minutes_today': round(minutes_today),
                    'heatmap': heatmap,
                    'year': today.year
                }
        except sqlite3.Error as e:
            logger.error(f"Error getting detailed user statistics: {e}")
            return {
                'total_cards': 0,
                'active_days': 0,
                'days_elapsed': 365,
                'days_learned_percent': 0,
                'longest_streak': 0,
                'current_streak': 0,
                'daily_average': 0,
                'cards_today': 0,
                'minutes_today': 0,
                'heatmap': {},
                'year': today.year
            }