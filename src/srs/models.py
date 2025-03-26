"""
Models for Spaced Repetition System using SQLAlchemy ORM.
"""
import enum

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class WordStatus(enum.IntEnum):
    """Enumeration for word learning status."""
    NEW = 0
    STUDYING = 3  # Active learning
    STUDIED = 5  # Learned

    @classmethod
    def label(cls, status: int) -> str:
        """Get human-readable label for status value."""
        labels = {
            cls.NEW: "New",
            cls.STUDYING: "Learning",
            cls.STUDIED: "Learned"
        }
        return labels.get(status, "Unknown")


"""
Models for Spaced Repetition System functionality.
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional
import sqlite3


class DeckSettings:
    """Model for deck-specific SRS settings."""

    def __init__(
            self,
            deck_id: int,
            new_cards_per_day: int = 20,
            reviews_per_day: int = 200,
            learning_steps: str = "1m 10m",
            graduating_interval: int = 1,
            easy_interval: int = 4,
            insertion_order: str = "sequential",
            relearning_steps: str = "10m",
            minimum_interval: int = 1,
            lapse_threshold: int = 8,
            lapse_action: str = "tag",
            new_card_gathering: str = "deck",
            new_card_order: str = "cardType",
            new_review_mix: str = "mix",
            inter_day_order: str = "mix",
            review_order: str = "dueRandom",
            bury_new_related: bool = False,
            bury_reviews_related: bool = False,
            bury_interday: bool = False,
            max_answer_time: int = 60,
            show_answer_timer: bool = True,
            stop_timer_on_answer: bool = False,
            seconds_show_question: float = 0.0,
            seconds_show_answer: float = 0.0,
            wait_for_audio: bool = False,
            answer_action: str = "bury",
            disable_auto_play: bool = False,
            skip_question_audio: bool = False,
            fsrs_enabled: bool = True,
            max_interval: int = 36500,
            starting_ease: float = 2.5,
            easy_bonus: float = 1.3,
            interval_modifier: float = 1.0,
            hard_interval: float = 1.2,
            new_interval: float = 0.0,
            created_at=None,
            updated_at=None,
            settings_id: int = None,
    ):
        """Initialize a DeckSettings object with all SRS parameters."""
        from datetime import datetime

        self.id = settings_id
        self.deck_id = deck_id
        self.new_cards_per_day = new_cards_per_day
        self.reviews_per_day = reviews_per_day
        self.learning_steps = learning_steps
        self.graduating_interval = graduating_interval
        self.easy_interval = easy_interval
        self.insertion_order = insertion_order
        self.relearning_steps = relearning_steps
        self.minimum_interval = minimum_interval
        self.lapse_threshold = lapse_threshold
        self.lapse_action = lapse_action
        self.new_card_gathering = new_card_gathering
        self.new_card_order = new_card_order
        self.new_review_mix = new_review_mix
        self.inter_day_order = inter_day_order
        self.review_order = review_order
        self.bury_new_related = bury_new_related
        self.bury_reviews_related = bury_reviews_related
        self.bury_interday = bury_interday
        self.max_answer_time = max_answer_time
        self.show_answer_timer = show_answer_timer
        self.stop_timer_on_answer = stop_timer_on_answer
        self.seconds_show_question = seconds_show_question
        self.seconds_show_answer = seconds_show_answer
        self.wait_for_audio = wait_for_audio
        self.answer_action = answer_action
        self.disable_auto_play = disable_auto_play
        self.skip_question_audio = skip_question_audio
        self.fsrs_enabled = fsrs_enabled
        self.max_interval = max_interval
        self.starting_ease = starting_ease
        self.easy_bonus = easy_bonus
        self.interval_modifier = interval_modifier
        self.hard_interval = hard_interval
        self.new_interval = new_interval
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    @staticmethod
    def ensure_table_exists(db_connection):
        """
        Ensure that the deck_settings table exists in the database.

        Args:
            db_connection: SQLite database connection

        Returns:
            bool: True if table was created, False if it already existed
        """
        cursor = db_connection.cursor()

        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='deck_settings'")
        if cursor.fetchone() is not None:
            return False

        # Create table if it doesn't exist
        cursor.execute("""
        CREATE TABLE deck_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_id INTEGER NOT NULL UNIQUE,
            new_cards_per_day INTEGER DEFAULT 20,
            reviews_per_day INTEGER DEFAULT 200,
            learning_steps TEXT DEFAULT '1m 10m',
            graduating_interval INTEGER DEFAULT 1,
            easy_interval INTEGER DEFAULT 4,
            insertion_order TEXT DEFAULT 'sequential',
            relearning_steps TEXT DEFAULT '10m',
            minimum_interval INTEGER DEFAULT 1,
            lapse_threshold INTEGER DEFAULT 8,
            lapse_action TEXT DEFAULT 'tag',
            new_card_gathering TEXT DEFAULT 'deck',
            new_card_order TEXT DEFAULT 'cardType',
            new_review_mix TEXT DEFAULT 'mix',
            inter_day_order TEXT DEFAULT 'mix',
            review_order TEXT DEFAULT 'dueRandom',
            bury_new_related INTEGER DEFAULT 0,
            bury_reviews_related INTEGER DEFAULT 0,
            bury_interday INTEGER DEFAULT 0,
            max_answer_time INTEGER DEFAULT 60,
            show_answer_timer INTEGER DEFAULT 1,
            stop_timer_on_answer INTEGER DEFAULT 0,
            seconds_show_question REAL DEFAULT 0.0,
            seconds_show_answer REAL DEFAULT 0.0,
            wait_for_audio INTEGER DEFAULT 0,
            answer_action TEXT DEFAULT 'bury',
            disable_auto_play INTEGER DEFAULT 0,
            skip_question_audio INTEGER DEFAULT 0,
            fsrs_enabled INTEGER DEFAULT 1,
            max_interval INTEGER DEFAULT 36500,
            starting_ease REAL DEFAULT 2.5,
            easy_bonus REAL DEFAULT 1.3,
            interval_modifier REAL DEFAULT 1.0,
            hard_interval REAL DEFAULT 1.2,
            new_interval REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (deck_id) REFERENCES deck(id) ON DELETE CASCADE
        )
        """)

        # Create index for faster lookups
        cursor.execute("CREATE INDEX idx_deck_settings_deck_id ON deck_settings(deck_id)")

        db_connection.commit()
        return True

    @classmethod
    def get_or_create(cls, db_connection, deck_id):
        """
        Get or create deck settings for a specific deck.

        Args:
            db_connection: SQLite database connection
            deck_id: ID of the deck

        Returns:
            DeckSettings: The retrieved or created settings
        """
        from datetime import datetime

        cursor = db_connection.cursor()

        # Ensure table exists
        cls.ensure_table_exists(db_connection)

        # Try to get existing settings
        cursor.execute(
            "SELECT * FROM deck_settings WHERE deck_id = ?",
            (deck_id,)
        )

        result = cursor.fetchone()
        if result:
            # Return existing settings
            settings_dict = {}
            for idx, col in enumerate(cursor.description):
                settings_dict[col[0]] = result[idx]

            # Convert integer boolean fields back to booleans
            boolean_fields = ['bury_new_related', 'bury_reviews_related', 'bury_interday',
                              'show_answer_timer', 'stop_timer_on_answer', 'wait_for_audio',
                              'disable_auto_play', 'skip_question_audio', 'fsrs_enabled']

            for field in boolean_fields:
                if field in settings_dict:
                    settings_dict[field] = bool(settings_dict[field])

            # Handle created_at and updated_at
            created_at = datetime.fromisoformat(settings_dict.get('created_at')) if settings_dict.get(
                'created_at') else None
            updated_at = datetime.fromisoformat(settings_dict.get('updated_at')) if settings_dict.get(
                'updated_at') else None

            # Remove database fields that aren't in constructor
            settings_id = settings_dict.pop('id', None)
            settings_dict.pop('created_at', None)
            settings_dict.pop('updated_at', None)

            return cls(
                deck_id=deck_id,
                created_at=created_at,
                updated_at=updated_at,
                settings_id=settings_id,
                **settings_dict
            )
        else:
            # Create new settings with defaults
            settings = cls(deck_id=deck_id)
            settings.save(db_connection)
            return settings

    def save(self, db_connection):
        """
        Save settings to the database.

        Args:
            db_connection: SQLite database connection
        """
        from datetime import datetime

        cursor = db_connection.cursor()

        # Ensure table exists
        self.ensure_table_exists(db_connection)

        # Prepare data
        data = self.to_dict()

        if self.id:
            # Update existing settings
            columns = []
            values = []

            for key, value in data.items():
                if key != 'id' and key != 'deck_id':
                    if isinstance(value, bool):
                        value = 1 if value else 0
                    columns.append(f"{key} = ?")
                    values.append(value)

            values.append(self.id)

            cursor.execute(
                f"UPDATE deck_settings SET {', '.join(columns)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                tuple(values)
            )
        else:
            # Insert new settings
            keys = []
            placeholders = []
            values = []

            for key, value in data.items():
                if key != 'id':
                    keys.append(key)
                    placeholders.append('?')
                    # Convert boolean to integer
                    if isinstance(value, bool):
                        value = 1 if value else 0
                    values.append(value)

            cursor.execute(
                f"INSERT INTO deck_settings ({', '.join(keys)}) VALUES ({', '.join(placeholders)})",
                tuple(values)
            )

            self.id = cursor.lastrowid
            self.updated_at = datetime.now()

        db_connection.commit()

    def to_dict(self):
        """
        Convert DeckSettings object to a dictionary.

        Returns:
            Dict: Dictionary with settings data
        """
        result = {
            'deck_id': self.deck_id,
            'new_cards_per_day': self.new_cards_per_day,
            'reviews_per_day': self.reviews_per_day,
            'learning_steps': self.learning_steps,
            'graduating_interval': self.graduating_interval,
            'easy_interval': self.easy_interval,
            'insertion_order': self.insertion_order,
            'relearning_steps': self.relearning_steps,
            'minimum_interval': self.minimum_interval,
            'lapse_threshold': self.lapse_threshold,
            'lapse_action': self.lapse_action,
            'new_card_gathering': self.new_card_gathering,
            'new_card_order': self.new_card_order,
            'new_review_mix': self.new_review_mix,
            'inter_day_order': self.inter_day_order,
            'review_order': self.review_order,
            'bury_new_related': self.bury_new_related,
            'bury_reviews_related': self.bury_reviews_related,
            'bury_interday': self.bury_interday,
            'max_answer_time': self.max_answer_time,
            'show_answer_timer': self.show_answer_timer,
            'stop_timer_on_answer': self.stop_timer_on_answer,
            'seconds_show_question': self.seconds_show_question,
            'seconds_show_answer': self.seconds_show_answer,
            'wait_for_audio': self.wait_for_audio,
            'answer_action': self.answer_action,
            'disable_auto_play': self.disable_auto_play,
            'skip_question_audio': self.skip_question_audio,
            'fsrs_enabled': self.fsrs_enabled,
            'max_interval': self.max_interval,
            'starting_ease': self.starting_ease,
            'easy_bonus': self.easy_bonus,
            'interval_modifier': self.interval_modifier,
            'hard_interval': self.hard_interval,
            'new_interval': self.new_interval
        }

        if self.id is not None:
            result['id'] = self.id

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DeckSettings':
        """
        Create a DeckSettings object from a dictionary.

        Args:
            data: Dictionary with settings data

        Returns:
            DeckSettings: Created object
        """
        deck_id = data.pop('deck_id')
        settings_id = data.pop('id', None)

        # Convert integer boolean fields back to booleans
        boolean_fields = ['bury_new_related', 'bury_reviews_related', 'bury_interday',
                          'show_answer_timer', 'stop_timer_on_answer', 'wait_for_audio',
                          'disable_auto_play', 'skip_question_audio', 'fsrs_enabled']

        for field in boolean_fields:
            if field in data:
                data[field] = bool(data[field])

        return cls(deck_id=deck_id, settings_id=settings_id, **data)


class Deck:
    """Model for a deck of flashcards."""

    def __init__(
            self,
            user_id: int,
            name: str,
            description: Optional[str] = None,
            created_at: Optional[datetime] = None,
            updated_at: Optional[datetime] = None,
            deck_id: Optional[int] = None,
    ):
        """
        Initialize a Deck object.

        Args:
            user_id (int): ID of the user who owns the deck
            name (str): Name of the deck
            description (Optional[str], optional): Description of the deck. Defaults to None.
            created_at (Optional[datetime], optional): Creation timestamp. Defaults to None.
            updated_at (Optional[datetime], optional): Last update timestamp. Defaults to None.
            deck_id (Optional[int], optional): ID of the deck. Defaults to None.
        """
        self.id = deck_id
        self.user_id = user_id
        self.name = name
        self.description = description
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Deck':
        """
        Create a Deck object from a dictionary.

        Args:
            data (Dict[str, Any]): Dictionary with deck data

        Returns:
            Deck: Deck object
        """
        return cls(
            user_id=data['user_id'],
            name=data['name'],
            description=data.get('description'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            deck_id=data.get('id'),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert a Deck object to a dictionary.

        Returns:
            Dict[str, Any]: Dictionary with deck data
        """
        result = {
            'user_id': self.user_id,
            'name': self.name,
        }

        if self.id is not None:
            result['id'] = self.id
        if self.description is not None:
            result['description'] = self.description
        if self.created_at is not None:
            result['created_at'] = self.created_at
        if self.updated_at is not None:
            result['updated_at'] = self.updated_at

        return result


class DeckCard:
    """Model for a flashcard in a deck with SRS parameters."""

    def __init__(
            self,
            deck_id: int,
            word_id: int,
            next_review_date: Optional[date] = None,
            last_review_date: Optional[date] = None,
            interval: int = 0,
            repetitions: int = 0,
            ease_factor: float = 2.5,
            lapses: int = 0,
            created_at: Optional[datetime] = None,
            updated_at: Optional[datetime] = None,
            card_id: Optional[int] = None,
    ):
        """
        Initialize a DeckCard object.

        Args:
            deck_id (int): ID of the deck
            word_id (int): ID of the word
            next_review_date (Optional[date], optional): Date for next review. Defaults to None.
            last_review_date (Optional[date], optional): Date of last review. Defaults to None.
            interval (int, optional): Current interval in days. Defaults to 0.
            repetitions (int, optional): Number of consecutive successful reviews. Defaults to 0.
            ease_factor (float, optional): Ease factor for SM-2 algorithm. Defaults to 2.5.
            lapses (int, optional): Number of times the card was forgotten. Defaults to 0.
            created_at (Optional[datetime], optional): Creation timestamp. Defaults to None.
            updated_at (Optional[datetime], optional): Last update timestamp. Defaults to None.
            card_id (Optional[int], optional): ID of the card. Defaults to None.
        """
        self.id = card_id
        self.deck_id = deck_id
        self.word_id = word_id
        self.next_review_date = next_review_date or date.today()
        self.last_review_date = last_review_date
        self.interval = interval
        self.repetitions = repetitions
        self.ease_factor = ease_factor
        self.lapses = lapses
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DeckCard':
        """
        Create a DeckCard object from a dictionary.

        Args:
            data (Dict[str, Any]): Dictionary with card data

        Returns:
            DeckCard: DeckCard object
        """
        return cls(
            deck_id=data['deck_id'],
            word_id=data['word_id'],
            next_review_date=data.get('next_review_date'),
            last_review_date=data.get('last_review_date'),
            interval=data.get('interval', 0),
            repetitions=data.get('repetitions', 0),
            ease_factor=data.get('ease_factor', 2.5),
            lapses=data.get('lapses', 0),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            card_id=data.get('id'),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert a DeckCard object to a dictionary.

        Returns:
            Dict[str, Any]: Dictionary with card data
        """
        result = {
            'deck_id': self.deck_id,
            'word_id': self.word_id,
            'interval': self.interval,
            'repetitions': self.repetitions,
            'ease_factor': self.ease_factor,
            'lapses': self.lapses,
        }

        if self.id is not None:
            result['id'] = self.id
        if self.next_review_date is not None:
            result['next_review_date'] = self.next_review_date
        if self.last_review_date is not None:
            result['last_review_date'] = self.last_review_date
        if self.created_at is not None:
            result['created_at'] = self.created_at
        if self.updated_at is not None:
            result['updated_at'] = self.updated_at

        return result


class ReviewSessionLog:
    """Model for tracking daily review sessions."""

    def __init__(
            self,
            user_id: int,
            session_date: date,
            cards_reviewed: int = 0,
            duration_seconds: Optional[int] = None,
            created_at: Optional[datetime] = None,
            log_id: Optional[int] = None,
    ):
        """
        Initialize a ReviewSessionLog object.

        Args:
            user_id (int): ID of the user
            session_date (date): Date of the session
            cards_reviewed (int, optional): Number of cards reviewed. Defaults to 0.
            duration_seconds (Optional[int], optional): Duration in seconds. Defaults to None.
            created_at (Optional[datetime], optional): Creation timestamp. Defaults to None.
            log_id (Optional[int], optional): ID of the log entry. Defaults to None.
        """
        self.id = log_id
        self.user_id = user_id
        self.session_date = session_date
        self.cards_reviewed = cards_reviewed
        self.duration_seconds = duration_seconds
        self.created_at = created_at or datetime.now()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ReviewSessionLog':
        """
        Create a ReviewSessionLog object from a dictionary.

        Args:
            data (Dict[str, Any]): Dictionary with log data

        Returns:
            ReviewSessionLog: ReviewSessionLog object
        """
        return cls(
            user_id=data['user_id'],
            session_date=data['session_date'],
            cards_reviewed=data.get('cards_reviewed', 0),
            duration_seconds=data.get('duration_seconds'),
            created_at=data.get('created_at'),
            log_id=data.get('id'),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert a ReviewSessionLog object to a dictionary.

        Returns:
            Dict[str, Any]: Dictionary with log data
        """
        result = {
            'user_id': self.user_id,
            'session_date': self.session_date,
            'cards_reviewed': self.cards_reviewed,
        }

        if self.id is not None:
            result['id'] = self.id
        if self.duration_seconds is not None:
            result['duration_seconds'] = self.duration_seconds
        if self.created_at is not None:
            result['created_at'] = self.created_at

        return result

    @property
    def duration_minutes(self) -> int:
        """
        Get the duration in minutes.

        Returns:
            int: Duration in minutes, rounded down
        """
        if self.duration_seconds is None:
            return 0
        return self.duration_seconds // 60

    def increment_reviewed(self, count: int = 1, duration_seconds: int = 0) -> None:
        """
        Increment the number of cards reviewed and optionally add duration.

        Args:
            count (int, optional): Number of cards to add. Defaults to 1.
            duration_seconds (int, optional): Duration to add in seconds. Defaults to 0.
        """
        self.cards_reviewed += count

        if self.duration_seconds is None:
            self.duration_seconds = duration_seconds
        else:
            self.duration_seconds += duration_seconds

    @staticmethod
    def ensure_table_exists(db_connection: sqlite3.Connection) -> bool:
        """
        Ensure that the review_session_log table exists in the database.

        Args:
            db_connection (sqlite3.Connection): Database connection

        Returns:
            bool: True if table was created, False if it already existed
        """
        cursor = db_connection.cursor()

        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='review_session_log'")
        if cursor.fetchone() is not None:
            return False

        # Create table if it doesn't exist
        cursor.execute("""
        CREATE TABLE review_session_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_date DATE NOT NULL,
            cards_reviewed INTEGER DEFAULT 0,
            duration_seconds INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Create index for faster lookups
        cursor.execute("CREATE INDEX idx_review_session_user_date ON review_session_log(user_id, session_date)")

        db_connection.commit()
        return True

    @classmethod
    def get_or_create(cls, db_connection: sqlite3.Connection, user_id: int,
                      session_date: date = None) -> 'ReviewSessionLog':
        """
        Get or create a review session log for a specific user and date.

        Args:
            db_connection (sqlite3.Connection): Database connection
            user_id (int): User ID
            session_date (date, optional): Session date. Defaults to today.

        Returns:
            ReviewSessionLog: The retrieved or created log
        """
        if session_date is None:
            session_date = date.today()

        date_str = session_date.isoformat()
        cursor = db_connection.cursor()

        # Ensure table exists
        cls.ensure_table_exists(db_connection)

        # Try to get existing log
        cursor.execute(
            "SELECT id, cards_reviewed, duration_seconds, created_at FROM review_session_log " +
            "WHERE user_id = ? AND session_date = ?",
            (user_id, date_str)
        )

        row = cursor.fetchone()
        if row:
            # Return existing log
            log_id, cards_reviewed, duration_seconds, created_at = row

            # Parse created_at if it's a string
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    created_at = datetime.now()

            return cls(
                user_id=user_id,
                session_date=session_date,
                cards_reviewed=cards_reviewed or 0,
                duration_seconds=duration_seconds,
                created_at=created_at,
                log_id=log_id
            )
        else:
            # Create new log
            cursor.execute(
                "INSERT INTO review_session_log (user_id, session_date, cards_reviewed) VALUES (?, ?, ?)",
                (user_id, date_str, 0)
            )
            db_connection.commit()

            return cls(
                user_id=user_id,
                session_date=session_date,
                cards_reviewed=0,
                log_id=cursor.lastrowid
            )

    def save(self, db_connection: sqlite3.Connection) -> None:
        """
        Save the log to the database.

        Args:
            db_connection (sqlite3.Connection): Database connection
        """
        cursor = db_connection.cursor()

        # Ensure table exists
        self.ensure_table_exists(db_connection)

        if self.id:
            # Update existing log
            cursor.execute(
                """
                UPDATE review_session_log 
                SET cards_reviewed = ?, duration_seconds = ?
                WHERE id = ?
                """,
                (self.cards_reviewed, self.duration_seconds, self.id)
            )
        else:
            # Insert new log
            date_str = self.session_date.isoformat()
            cursor.execute(
                """
                INSERT INTO review_session_log 
                (user_id, session_date, cards_reviewed, duration_seconds)
                VALUES (?, ?, ?, ?)
                """,
                (self.user_id, date_str, self.cards_reviewed, self.duration_seconds)
            )
            self.id = cursor.lastrowid

        db_connection.commit()

    @classmethod
    def get_user_activity(cls, db_connection: sqlite3.Connection, user_id: int,
                          start_date: date, end_date: date) -> Dict[str, Dict[str, int]]:
        """
        Get user activity data for a date range.

        Args:
            db_connection (sqlite3.Connection): Database connection
            user_id (int): User ID
            start_date (date): Start date (inclusive)
            end_date (date): End date (inclusive)

        Returns:
            Dict[str, Dict[str, int]]: Activity data by date
        """
        # Ensure table exists
        cls.ensure_table_exists(db_connection)

        cursor = db_connection.cursor()
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        # Initialize result with zero values for all dates in range
        result = {}
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.isoformat()
            result[date_str] = {'reviewed': 0, 'minutes': 0}
            current_date += timedelta(days=1)

        # Fetch data
        cursor.execute(
            """
            SELECT 
                session_date, 
                SUM(cards_reviewed) as reviewed,
                SUM(duration_seconds) / 60 as minutes
            FROM review_session_log
            WHERE user_id = ? AND session_date BETWEEN ? AND ?
            GROUP BY session_date
            """,
            (user_id, start_str, end_str)
        )

        # Update result with actual data
        for row in cursor.fetchall():
            date_str = row[0]
            reviewed = row[1] or 0
            minutes = int(row[2] or 0)

            result[date_str] = {
                'reviewed': reviewed,
                'minutes': minutes
            }

        return result

    @classmethod
    def clear_user_activity(cls, db_connection: sqlite3.Connection, user_id: int) -> int:
        """
        Clear all activity for a user.

        Args:
            db_connection (sqlite3.Connection): Database connection
            user_id (int): User ID

        Returns:
            int: Number of records deleted
        """
        # Check if table exists
        cursor = db_connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='review_session_log'")
        if cursor.fetchone() is None:
            return 0

        # Delete records
        cursor.execute("DELETE FROM review_session_log WHERE user_id = ?", (user_id,))
        db_connection.commit()

        return cursor.rowcount

    class CardReviewHistory:
        """Model for tracking individual card review history."""

        def __init__(
                self,
                card_id: int,
                user_id: int,
                review_date: datetime = None,
                difficulty: str = None,
                time_seconds: Optional[int] = None,
                created_at: Optional[datetime] = None,
                history_id: Optional[int] = None,
        ):
            """
            Initialize a CardReviewHistory object.

            Args:
                card_id (int): ID of the card reviewed
                user_id (int): ID of the user who reviewed the card
                review_date (datetime, optional): Date and time of review. Defaults to now.
                difficulty (str, optional): Difficulty rating (again, hard, good, easy). Defaults to None.
                time_seconds (Optional[int], optional): Time spent on this card in seconds. Defaults to None.
                created_at (Optional[datetime], optional): Creation timestamp. Defaults to None.
                history_id (Optional[int], optional): ID of the history entry. Defaults to None.
            """
            self.id = history_id
            self.card_id = card_id
            self.user_id = user_id
            self.review_date = review_date or datetime.now()
            self.difficulty = difficulty
            self.time_seconds = time_seconds
            self.created_at = created_at or datetime.now()

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> 'CardReviewHistory':
            """
            Create a CardReviewHistory object from a dictionary.

            Args:
                data (Dict[str, Any]): Dictionary with history data

            Returns:
                CardReviewHistory: CardReviewHistory object
            """
            return cls(
                card_id=data['card_id'],
                user_id=data['user_id'],
                review_date=data.get('review_date'),
                difficulty=data.get('difficulty'),
                time_seconds=data.get('time_seconds'),
                created_at=data.get('created_at'),
                history_id=data.get('id'),
            )

        def to_dict(self) -> Dict[str, Any]:
            """
            Convert a CardReviewHistory object to a dictionary.

            Returns:
                Dict[str, Any]: Dictionary with history data
            """
            result = {
                'card_id': self.card_id,
                'user_id': self.user_id,
            }

            if self.id is not None:
                result['id'] = self.id
            if self.review_date is not None:
                result['review_date'] = self.review_date
            if self.difficulty is not None:
                result['difficulty'] = self.difficulty
            if self.time_seconds is not None:
                result['time_seconds'] = self.time_seconds
            if self.created_at is not None:
                result['created_at'] = self.created_at

            return result

        @staticmethod
        def ensure_table_exists(db_connection: sqlite3.Connection) -> bool:
            """
            Ensure that the card_review_history table exists in the database.

            Args:
                db_connection (sqlite3.Connection): Database connection

            Returns:
                bool: True if table was created, False if it already existed
            """
            cursor = db_connection.cursor()

            # Check if table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='card_review_history'")
            if cursor.fetchone() is not None:
                return False

            # Create table if it doesn't exist
            cursor.execute("""
            CREATE TABLE card_review_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                review_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                difficulty TEXT,
                time_seconds INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (card_id) REFERENCES deck_card(id) ON DELETE CASCADE
            )
            """)

            # Create indexes for faster lookups
            cursor.execute("CREATE INDEX idx_review_history_card ON card_review_history(card_id)")
            cursor.execute("CREATE INDEX idx_review_history_user ON card_review_history(user_id)")
            cursor.execute("CREATE INDEX idx_review_history_date ON card_review_history(review_date)")

            db_connection.commit()
            return True

        @classmethod
        def add_review(cls, db_connection: sqlite3.Connection, card_id: int, user_id: int,
                       difficulty: str, time_seconds: int = None) -> int:
            """
            Add a new card review history entry.

            Args:
                db_connection (sqlite3.Connection): Database connection
                card_id (int): ID of the card
                user_id (int): ID of the user
                difficulty (str): Difficulty rating
                time_seconds (int, optional): Time spent on this card. Defaults to None.

            Returns:
                int: ID of the new history entry
            """
            # Ensure table exists
            cls.ensure_table_exists(db_connection)

            cursor = db_connection.cursor()

            # Insert new history entry
            cursor.execute(
                """
                INSERT INTO card_review_history 
                (card_id, user_id, review_date, difficulty, time_seconds)
                VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
                """,
                (card_id, user_id, difficulty, time_seconds)
            )

            db_connection.commit()
            return cursor.lastrowid
