"""
Script to initialize all necessary database tables for the language learning application.
"""
import logging
import os
import sqlite3
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def initialize_database(db_path: str) -> bool:
    """
    Initialize all tables in the database.

    Args:
        db_path: Path to the SQLite database file

    Returns:
        bool: True if initialization was successful, False otherwise
    """
    conn = None
    try:
        # Create database directory if it doesn't exist
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            logger.info(f"Created directory: {db_dir}")

        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Log current database state
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [table[0] for table in cursor.fetchall()]
        logger.info(f"Existing tables: {tables}")

        # Begin transaction
        conn.execute("BEGIN TRANSACTION")

        # 1. Create collection_words table
        logger.info("Creating collection_words table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS collection_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                english_word TEXT UNIQUE NOT NULL,
                russian_word TEXT,
                listening TEXT,
                sentences TEXT,
                level TEXT,
                brown INTEGER DEFAULT 0,
                get_download INTEGER DEFAULT 0,
                learning_status INTEGER DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for collection_words
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_collection_words_english_word ON collection_words(english_word)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_collection_words_learning_status ON collection_words(learning_status)")

        # 2. Create book table
        logger.info("Creating book table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS book (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT UNIQUE NOT NULL,
                total_words INTEGER DEFAULT 0,
                unique_words INTEGER DEFAULT 0,
                scrape_date TIMESTAMP DEFAULT NULL
            )
        """)

        # 3. Create word_book_link table
        logger.info("Creating word_book_link table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS word_book_link (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_id INTEGER NOT NULL,
                book_id INTEGER NOT NULL,
                frequency INTEGER DEFAULT 1,
                FOREIGN KEY (word_id) REFERENCES collection_words (id),
                FOREIGN KEY (book_id) REFERENCES book (id),
                UNIQUE (word_id, book_id)
            )
        """)

        # Create indexes for word_book_link
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_word_book_link_word_id ON word_book_link(word_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_word_book_link_book_id ON word_book_link(book_id)")

        # 4. Create phrasal_verb table
        logger.info("Creating phrasal_verb table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS phrasal_verb (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phrasal_verb TEXT UNIQUE NOT NULL,
                russian_translate TEXT,
                "using" TEXT,
                sentence TEXT,
                word_id INTEGER,
                listening TEXT,
                get_download INTEGER DEFAULT 0,
                FOREIGN KEY (word_id) REFERENCES collection_words (id)
            )
        """)

        # 5. Create users table
        logger.info("Creating users table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                email TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                is_admin INTEGER DEFAULT 0
            )
        """)

        # 6. Create user_word_status table
        logger.info("Creating user_word_status table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_word_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                word_id INTEGER NOT NULL,
                status INTEGER NOT NULL DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (word_id) REFERENCES collection_words (id),
                UNIQUE (user_id, word_id)
            )
        """)

        # Create indexes for user_word_status
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_word_status ON user_word_status(user_id, word_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_word_status_status ON user_word_status(user_id, status)")

        # 7. Create deck table
        logger.info("Creating deck table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deck (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                UNIQUE (user_id, name)
            )
        """)

        # Create index for deck
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_deck_user_id ON deck(user_id)")

        # 8. Create deck_card table
        logger.info("Creating deck_card table...")
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (deck_id) REFERENCES deck (id),
                FOREIGN KEY (word_id) REFERENCES collection_words (id),
                UNIQUE (deck_id, word_id)
            )
        """)

        # Create indexes for deck_card
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_deck_card_deck_id ON deck_card(deck_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_deck_card_word_id ON deck_card(word_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_deck_card_next_review ON deck_card(next_review_date)")

        # 9. Create review_session_log table
        logger.info("Creating review_session_log table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS review_session_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_date DATE NOT NULL,
                cards_reviewed INTEGER DEFAULT 0,
                duration_seconds INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Create index for review_session_log
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_review_session_user_date ON review_session_log(user_id, session_date)")

        # 10. Create card_review_history table
        logger.info("Creating card_review_history table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS card_review_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                review_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                difficulty TEXT,
                time_seconds INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (card_id) REFERENCES deck_card(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Create indexes for card_review_history
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_review_history_card ON card_review_history(card_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_review_history_user ON card_review_history(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_review_history_date ON card_review_history(review_date)")

        # 11. Create deck_settings table
        logger.info("Creating deck_settings table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deck_settings (
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

        # Create index for deck_settings
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_deck_settings_deck_id ON deck_settings(deck_id)")

        # Set schema version (incremented to 4 for the new table)
        cursor.execute("PRAGMA user_version = 4")

        # Commit transaction
        conn.commit()

        # Log successful initialization
        logger.info("Database initialization completed successfully.")

        # Double-check that all tables were created
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables_after = [table[0] for table in cursor.fetchall()]
        tables_after.sort()
        logger.info(f"Tables after initialization: {tables_after}")

        return True

    except Exception as e:
        # Log error and roll back transaction
        logger.error(f"Error initializing database: {e}")
        if conn:
            conn.rollback()
        return False

    finally:
        # Close connection
        if conn:
            conn.close()


def create_main_deck_if_needed(db_path: str, user_id: int = 1) -> bool:
    """
    Create a Main Deck for a user if it doesn't exist.

    Args:
        db_path: Path to the SQLite database file
        user_id: User ID for whom to create the deck

    Returns:
        bool: True if successful, False otherwise
    """
    conn = None
    try:
        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if the user exists
        cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()

        if not user:
            # Create a default user if none exists
            salt = "default_salt"
            password_hash = "default_hash"  # In production, use proper hashing

            cursor.execute("""
                INSERT INTO users (id, username, password_hash, salt, is_admin) 
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, "default_user", password_hash, salt, 1))

            logger.info(f"Created default user with ID {user_id}")

        # Check if Main Deck already exists for the user
        cursor.execute("SELECT id FROM deck WHERE user_id = ? AND name = ?", (user_id, "Main Deck"))
        deck = cursor.fetchone()

        if not deck:
            # Create Main Deck
            cursor.execute("""
                INSERT INTO deck (user_id, name, description)
                VALUES (?, ?, ?)
            """, (user_id, "Main Deck", "Default deck for all new words"))

            deck_id = cursor.lastrowid

            # Create default settings for this deck
            cursor.execute("""
                INSERT INTO deck_settings (deck_id) VALUES (?)
            """, (deck_id,))

            conn.commit()
            logger.info(f"Created Main Deck with ID {deck_id} for user {user_id}")
            return True
        else:
            # Check if settings exist for this deck
            deck_id = deck[0]
            cursor.execute("SELECT id FROM deck_settings WHERE deck_id = ?", (deck_id,))
            settings = cursor.fetchone()

            if not settings:
                # Create default settings if they don't exist
                cursor.execute("""
                    INSERT INTO deck_settings (deck_id) VALUES (?)
                """, (deck_id,))
                conn.commit()
                logger.info(f"Created default settings for existing Main Deck {deck_id}")

            logger.info(f"Main Deck already exists for user {user_id}")
            return True

    except Exception as e:
        logger.error(f"Error creating Main Deck: {e}")
        if conn:
            conn.rollback()
        return False

    finally:
        if conn:
            conn.close()


def create_default_settings_for_existing_decks(db_path: str) -> bool:
    """
    Create default settings for all existing decks that don't have settings.

    Args:
        db_path: Path to the SQLite database file

    Returns:
        bool: True if successful, False otherwise
    """
    conn = None
    try:
        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if deck_settings table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='deck_settings'")
        if not cursor.fetchone():
            logger.warning("deck_settings table doesn't exist. Run initialize_database first.")
            return False

        # Get all decks that don't have settings
        cursor.execute("""
            SELECT d.id FROM deck d 
            LEFT JOIN deck_settings ds ON d.id = ds.deck_id 
            WHERE ds.id IS NULL
        """)

        decks_without_settings = cursor.fetchall()

        if not decks_without_settings:
            logger.info("All decks already have settings")
            return True

        # Create default settings for each deck
        for deck_row in decks_without_settings:
            deck_id = deck_row[0]
            cursor.execute("""
                INSERT INTO deck_settings (deck_id) VALUES (?)
            """, (deck_id,))
            logger.info(f"Created default settings for deck {deck_id}")

        conn.commit()
        logger.info(f"Created default settings for {len(decks_without_settings)} decks")
        return True

    except Exception as e:
        logger.error(f"Error creating default settings: {e}")
        if conn:
            conn.rollback()
        return False

    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        db_file = sys.argv[1]
    else:
        db_file = "data/language_learning.db"

    print(f"Initializing database at: {db_file}")
    if initialize_database(db_file):
        print("Database initialization successful!")

        # Create Main Deck for default user (ID=1)
        if create_main_deck_if_needed(db_file):
            print("Main Deck created or already exists for default user")
        else:
            print("Failed to create Main Deck")

        # Create default settings for all existing decks
        if create_default_settings_for_existing_decks(db_file):
            print("Default settings created for all existing decks")
        else:
            print("Failed to create default settings for existing decks")

        sys.exit(0)
    else:
        print("Database initialization failed!")
        sys.exit(1)