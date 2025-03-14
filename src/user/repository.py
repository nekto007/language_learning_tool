"""
User-related repository functions for database operations.
"""
import logging
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.db.models import Word
from src.user.models import User

logger = logging.getLogger(__name__)


class UserRepository:
    """Repository for user-related database operations."""

    def __init__(self, db_path: str):
        """
        Initialize the user repository.

        Args:
            db_path (str): Path to the database file.
        """
        self.db_path = db_path

    def get_connection(self) -> sqlite3.Connection:
        """
        Get a database connection.

        Returns:
            sqlite3.Connection: Database connection object.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable dictionary access by column name
        return conn

    def execute_query(
            self, query: str, parameters: Tuple = (), fetch: bool = False
    ) -> Optional[List[sqlite3.Row]]:
        """
        Execute a SQL query.

        Args:
            query (str): SQL query.
            parameters (Tuple, optional): Query parameters. Defaults to ().
            fetch (bool, optional): Whether to fetch results. Defaults to False.

        Returns:
            Optional[List[sqlite3.Row]]: Query results or None.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, parameters)

                if fetch:
                    return cursor.fetchall()
                return None
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            raise

    def initialize_schema(self) -> None:
        """
        Initialize the user-related database schema if needed.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Check if users table exists
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
                if not cursor.fetchone():
                    logger.info("Creating users table")

                    # Create users table
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS users (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            username TEXT UNIQUE NOT NULL,
                            password_hash TEXT NOT NULL,
                            salt TEXT NOT NULL,
                            email TEXT UNIQUE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            last_login TIMESTAMP
                        )
                    ''')

                    # Create user_word_status table
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS user_word_status (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            word_id INTEGER NOT NULL,
                            status INTEGER NOT NULL DEFAULT 0,
                            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (user_id) REFERENCES users (id),
                            FOREIGN KEY (word_id) REFERENCES collections_word (id),
                            UNIQUE (user_id, word_id)
                        )
                    ''')

                    # Create indexes
                    cursor.execute(
                        "CREATE INDEX IF NOT EXISTS idx_user_word_status ON user_word_status(user_id, word_id)")
                    cursor.execute(
                        "CREATE INDEX IF NOT EXISTS idx_user_word_status_status ON user_word_status(user_id, status)")

                    conn.commit()
                    logger.info("User schema initialized successfully")

        except sqlite3.Error as e:
            logger.error(f"Error initializing user schema: {e}")
            raise

    def create_user(self, username: str, password: str, email: Optional[str] = None) -> Optional[int]:
        """
        Create a new user.

        Args:
            username (str): Username
            password (str): Plain password
            email (Optional[str], optional): Email. Defaults to None.

        Returns:
            Optional[int]: User ID if successful, None otherwise.
        """
        try:
            # Check if username already exists
            check_query = "SELECT id FROM users WHERE username = ?"
            result = self.execute_query(check_query, (username,), fetch=True)

            if result:
                logger.warning(f"Username '{username}' already exists")
                return None

            # Hash password
            pw_hash, salt = User.hash_password(password)

            # Insert user
            query = """
                INSERT INTO users (username, password_hash, salt, email, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """
            self.execute_query(query, (username, pw_hash, salt, email))

            # Get user ID
            id_query = "SELECT id FROM users WHERE username = ?"
            result = self.execute_query(id_query, (username,), fetch=True)

            if result and result[0]:
                return result[0]['id']
            return None

        except sqlite3.Error as e:
            logger.error(f"Error creating user: {e}")
            return None

    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """
        Authenticate a user.

        Args:
            username (str): Username
            password (str): Plain password

        Returns:
            Optional[User]: User object if authentication succeeds, None otherwise.
        """
        try:
            # Get user data
            query = ("SELECT id, username, password_hash, salt, email, created_at, last_login FROM "
                     "users WHERE username = ?")
            result = self.execute_query(query, (username,), fetch=True)

            if not result:
                logger.warning(f"User '{username}' not found")
                return None

            user_data = result[0]

            # Verify password
            pw_hash, _ = User.hash_password(password, user_data['salt'])
            if pw_hash != user_data['password_hash']:
                logger.warning(f"Invalid password for user '{username}'")
                return None

            # Update last login time
            update_query = "UPDATE users SET last_login = datetime('now') WHERE id = ?"
            self.execute_query(update_query, (user_data['id'],))

            # Create User object
            user = User(
                username=user_data['username'],
                password_hash=user_data['password_hash'],
                email=user_data['email'],
                created_at=user_data['created_at'],
                last_login=datetime.now(),
                user_id=user_data['id'],
            )

            return user

        except sqlite3.Error as e:
            logger.error(f"Error authenticating user: {e}")
            return None

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """
        Get a user by ID.

        Args:
            user_id (int): User ID

        Returns:
            Optional[User]: User object if found, None otherwise.
        """
        try:
            query = "SELECT id, username, password_hash, email, created_at, last_login FROM users WHERE id = ?"
            result = self.execute_query(query, (user_id,), fetch=True)

            if not result:
                return None

            user_data = result[0]

            return User(
                username=user_data['username'],
                password_hash=user_data['password_hash'],
                email=user_data['email'],
                created_at=user_data['created_at'],
                last_login=user_data['last_login'],
                user_id=user_data['id'],
            )

        except sqlite3.Error as e:
            logger.error(f"Error getting user by ID: {e}")
            return None

    def set_word_status(self, user_id: int, word_id: int, status: int) -> bool:
        """
        Set a word's learning status for a user.

        Args:
            user_id (int): User ID
            word_id (int): Word ID
            status (int): Learning status

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            # Check if record exists
            check_query = "SELECT id FROM user_word_status WHERE user_id = ? AND word_id = ?"
            result = self.execute_query(check_query, (user_id, word_id), fetch=True)

            if result:
                # Update existing record
                query = """
                    UPDATE user_word_status
                    SET status = ?, last_updated = datetime('now')
                    WHERE user_id = ? AND word_id = ?
                """
                self.execute_query(query, (status, user_id, word_id))
            else:
                # Insert new record
                query = """
                    INSERT INTO user_word_status (user_id, word_id, status, last_updated)
                    VALUES (?, ?, ?, datetime('now'))
                """
                self.execute_query(query, (user_id, word_id, status))

            return True

        except sqlite3.Error as e:
            logger.error(f"Error setting word status: {e}")
            return False

    def set_word_status_by_english(self, user_id: int, english_word: str, status: int) -> bool:
        """
        Set a word's learning status by its English text for a user.

        Args:
            user_id (int): User ID
            english_word (str): English word
            status (int): Learning status

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            # Get word ID
            word_query = "SELECT id FROM collections_word WHERE english_word = ?"
            word_result = self.execute_query(word_query, (english_word,), fetch=True)

            if not word_result:
                logger.warning(f"Word '{english_word}' not found")
                return False

            word_id = word_result[0]['id']

            # Set word status
            return self.set_word_status(user_id, word_id, status)

        except sqlite3.Error as e:
            logger.error(f"Error setting word status by English: {e}")
            return False

    def get_word_status(self, user_id: int, word_id: int) -> Optional[int]:
        """
        Get a word's learning status for a user.

        Args:
            user_id (int): User ID
            word_id (int): Word ID

        Returns:
            Optional[int]: Status if found, None otherwise.
        """
        try:
            query = "SELECT status FROM user_word_status WHERE user_id = ? AND word_id = ?"
            result = self.execute_query(query, (user_id, word_id), fetch=True)

            if result:
                return result[0]['status']
            return None

        except sqlite3.Error as e:
            logger.error(f"Error getting word status: {e}")
            return None

    def get_words_by_status(self, user_id: int, status: Optional[int] = None) -> List[Dict]:
        """
        Get words by learning status for a user.

        Args:
            user_id (int): User ID
            status (Optional[int], optional): Learning status. Defaults to None (all statuses).

        Returns:
            List[Dict]: List of word dictionaries with status information.
        """
        try:
            if status is not None:
                query = """
                    SELECT cw.*, uws.status
                    FROM collections_word cw
                    JOIN user_word_status uws ON cw.id = uws.word_id
                    WHERE uws.user_id = ? AND uws.status = ?
                    ORDER BY cw.english_word
                """
                result = self.execute_query(query, (user_id, status), fetch=True)
            else:
                query = """
                    SELECT cw.*, uws.status
                    FROM collections_word cw
                    JOIN user_word_status uws ON cw.id = uws.word_id
                    WHERE uws.user_id = ?
                    ORDER BY uws.status, cw.english_word
                """
                result = self.execute_query(query, (user_id,), fetch=True)

            if not result:
                return []

            words = []
            for row in result:
                word_dict = dict(row)
                words.append(word_dict)

            return words

        except sqlite3.Error as e:
            logger.error(f"Error getting words by status: {e}")
            return []

    def get_all_words_with_status(self, user_id: int) -> List[Dict]:
        """
        Get all words with their learning status for a user.
        If a word doesn't have a status set, it will be considered as STATUS_NEW (0).

        Args:
            user_id (int): User ID

        Returns:
            List[Dict]: List of word dictionaries with status information.
        """
        try:
            query = """
                SELECT cw.*, COALESCE(uws.status, 0) as status
                FROM collections_word cw
                LEFT JOIN user_word_status uws ON cw.id = uws.word_id AND uws.user_id = ?
                ORDER BY COALESCE(uws.status, 0), cw.english_word
            """
            result = self.execute_query(query, (user_id,), fetch=True)

            if not result:
                return []

            words = []
            for row in result:
                word_dict = dict(row)
                words.append(word_dict)

            return words

        except sqlite3.Error as e:
            logger.error(f"Error getting all words with status: {e}")
            return []

    def get_status_statistics(self, user_id: int) -> Dict[int, int]:
        """
        Get word learning status statistics for a user.

        Args:
            user_id (int): User ID

        Returns:
            Dict[int, int]: Dictionary mapping status to count.
        """
        try:
            # Words with explicit status
            query = """
                SELECT status, COUNT(*) as count
                FROM user_word_status
                WHERE user_id = ?
                GROUP BY status
            """
            result = self.execute_query(query, (user_id,), fetch=True)

            stats = {
                Word.STATUS_NEW: 0,
                Word.STATUS_QUEUED: 0,
                Word.STATUS_ACTIVE: 0,
                Word.STATUS_MASTERED: 0,
            }

            if result:
                for row in result:
                    stats[row['status']] = row['count']

            # Count words without explicit status (considered as STATUS_NEW)
            total_query = "SELECT COUNT(*) as count FROM collections_word"
            total_result = self.execute_query(total_query, fetch=True)

            explicit_query = """
                SELECT COUNT(*) as count 
                FROM (
                    SELECT DISTINCT word_id 
                    FROM user_word_status 
                    WHERE user_id = ?
                )
            """
            explicit_result = self.execute_query(explicit_query, (user_id,), fetch=True)

            if total_result and explicit_result:
                total_words = total_result[0]['count']
                explicit_words = explicit_result[0]['count']
                stats[Word.STATUS_NEW] += (total_words - explicit_words)

            return stats

        except sqlite3.Error as e:
            logger.error(f"Error getting status statistics: {e}")
            return {
                Word.STATUS_NEW: 0,
                Word.STATUS_QUEUED: 0,
                Word.STATUS_ACTIVE: 0,
                Word.STATUS_MASTERED: 0,
            }

    def batch_update_word_status(self, user_id: int, english_words: List[str], status: int) -> int:
        """
        Batch update word statuses for a user.

        Args:
            user_id (int): User ID
            english_words (List[str]): List of English words
            status (int): Learning status

        Returns:
            int: Number of words updated.
        """
        if not english_words:
            return 0

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                updated_count = 0

                # Get word IDs
                placeholders = ', '.join(['?'] * len(english_words))
                word_query = f"SELECT id, english_word FROM collections_word WHERE english_word IN ({placeholders})"
                cursor.execute(word_query, english_words)
                words = cursor.fetchall()

                if not words:
                    return 0

                # Update word statuses
                for word in words:
                    word_id = word['id']

                    # Check if record exists
                    cursor.execute(
                        "SELECT id FROM user_word_status WHERE user_id = ? AND word_id = ?",
                        (user_id, word_id)
                    )
                    result = cursor.fetchone()

                    if result:
                        # Update existing record
                        cursor.execute(
                            """
                            UPDATE user_word_status
                            SET status = ?, last_updated = datetime('now')
                            WHERE user_id = ? AND word_id = ?
                            """,
                            (status, user_id, word_id)
                        )
                    else:
                        # Insert new record
                        cursor.execute(
                            """
                            INSERT INTO user_word_status (user_id, word_id, status, last_updated)
                            VALUES (?, ?, ?, datetime('now'))
                            """,
                            (user_id, word_id, status)
                        )

                    updated_count += 1

                conn.commit()
                logger.info(f"Batch updated {updated_count} word statuses for user {user_id}")
                return updated_count

        except sqlite3.Error as e:
            logger.error(f"Error batch updating word statuses: {e}")
            return 0
