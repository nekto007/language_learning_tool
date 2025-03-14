"""
Repository for working with SQLite database.
"""
import logging
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from config.settings import DB_FILE
from src.db.models import Book, PhrasalVerb, Word

logger = logging.getLogger(__name__)


class DatabaseRepository:
    """Repository for working with the database."""

    def __init__(self, db_path: str = DB_FILE):
        """
        Initializes the repository.

        Args:
            db_path (str, optional): Path to the database file.
        """
        self.db_path = db_path

    def get_connection(self) -> sqlite3.Connection:
        """
        Gets a connection to the database.

        Returns:
            sqlite3.Connection: Connection object.
        """
        return sqlite3.connect(self.db_path)

    def execute_query(
            self, query: str, parameters: Tuple = (), fetch: bool = False
    ) -> Optional[List[Tuple]]:
        """
        Executes an SQL query.

        Args:
            query (str): SQL query.
            parameters (Tuple, optional): Query parameters.
            fetch (bool, optional): Flag to return results. Defaults to False.

        Returns:
            Optional[List[Tuple]]: Query results or None.
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

    def insert_or_update_book(self, book: Book) -> int:
        """
        Inserts or updates a book in the database.

        Args:
            book (Book): Book object.

        Returns:
            int: ID of the inserted book.
        """
        query = """
            INSERT OR IGNORE INTO book (title) VALUES (?)
        """
        self.execute_query(query, (book.title,))

        # Get book ID
        query = "SELECT id FROM book WHERE title = ?"
        result = self.execute_query(query, (book.title,), fetch=True)

        if result and result[0]:
            return result[0][0]
        return 0

    def insert_or_update_word(self, word: Word) -> int:
        """
        Inserts or updates a word in the database.

        Args:
            word (Word): Word object.

        Returns:
            int: ID of the inserted word.
        """
        # Check if word exists
        check_query = "SELECT id FROM collections_word WHERE english_word = ?"
        result = self.execute_query(check_query, (word.english_word,), fetch=True)

        if result and result[0]:
            word_id = result[0][0]

            # Update word
            update_query = """
                UPDATE collections_word
                SET listening = COALESCE(?, listening),
                    russian_word = COALESCE(?, russian_word),
                    sentences = COALESCE(?, sentences),
                    level = COALESCE(?, level),
                    brown = COALESCE(?, brown),
                    get_download = COALESCE(?, get_download)
                WHERE id = ?
            """
            self.execute_query(
                update_query,
                (
                    word.listening,
                    word.russian_word,
                    word.sentences,
                    word.level,
                    word.brown,
                    word.get_download,
                    word_id,
                ),
            )
        else:
            # Insert new word
            insert_query = """
                INSERT INTO collections_word
                (english_word, listening, russian_word, sentences, level, brown, get_download)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            self.execute_query(
                insert_query,
                (
                    word.english_word,
                    word.listening,
                    word.russian_word,
                    word.sentences,
                    word.level,
                    word.brown,
                    word.get_download,
                ),
            )

            # Get ID of the new word
            result = self.execute_query(
                "SELECT id FROM collections_word WHERE english_word = ?",
                (word.english_word,),
                fetch=True,
            )
            word_id = result[0][0] if result and result[0] else 0

        return word_id

    def link_word_to_book(self, word_id: int, book_id: int, frequency: int) -> None:
        """
        Links a word to a book.

        Args:
            word_id (int): Word ID.
            book_id (int): Book ID.
            frequency (int): Frequency of the word in the book.
        """
        query = """
            INSERT OR REPLACE INTO word_book_link
            (word_id, book_id, frequency)
            VALUES (?, ?, ?)
        """
        self.execute_query(query, (word_id, book_id, frequency))

    def insert_or_update_phrasal_verb(self, verb: PhrasalVerb) -> int:
        """
        Inserts or updates a phrasal verb in the database.

        Args:
            verb (PhrasalVerb): Phrasal verb object.

        Returns:
            int: ID of the inserted phrasal verb.
        """
        # Check if phrasal verb exists
        check_query = "SELECT id FROM phrasal_verb WHERE phrasal_verb = ?"
        result = self.execute_query(check_query, (verb.phrasal_verb,), fetch=True)

        if result and result[0]:
            verb_id = result[0][0]

            # Update phrasal verb
            update_query = """
                UPDATE phrasal_verb
                SET russian_translate = COALESCE(?, russian_translate),
                    "using" = COALESCE(?, "using"),
                    sentence = COALESCE(?, sentence),
                    word_id = COALESCE(?, word_id),
                    listening = COALESCE(?, listening),
                    get_download = COALESCE(?, get_download)
                WHERE id = ?
            """
            self.execute_query(
                update_query,
                (
                    verb.russian_translate,
                    verb.using,
                    verb.sentence,
                    verb.word_id,
                    verb.listening,
                    verb.get_download,
                    verb_id,
                ),
            )
        else:
            # Insert new phrasal verb
            insert_query = """
                INSERT INTO phrasal_verb
                (phrasal_verb, russian_translate, "using", sentence, word_id, listening, get_download)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            self.execute_query(
                insert_query,
                (
                    verb.phrasal_verb,
                    verb.russian_translate,
                    verb.using,
                    verb.sentence,
                    verb.word_id,
                    verb.listening,
                    verb.get_download,
                ),
            )

            # Get ID of the new phrasal verb
            result = self.execute_query(
                "SELECT id FROM phrasal_verb WHERE phrasal_verb = ?",
                (verb.phrasal_verb,),
                fetch=True,
            )
            verb_id = result[0][0] if result and result[0] else 0

        return verb_id

    def get_word_by_english(self, english_word: str) -> Optional[Word]:
        """
        Gets a word by its English word.

        Args:
            english_word (str): English word.

        Returns:
            Optional[Word]: Word object or None.
        """
        query = "SELECT * FROM collections_word WHERE english_word = ?"
        result = self.execute_query(query, (english_word,), fetch=True)

        if not result:
            return None

        # Convert result row to dictionary
        columns = [
            'id', 'english_word', 'russian_word', 'listening',
            'sentences', 'level', 'brown', 'get_download'
        ]
        data = dict(zip(columns, result[0]))

        return Word.from_dict(data)

    def get_words_by_filter(self, **filters) -> List[Word]:
        """
        Gets words by filters.

        Args:
            **filters: Filters in key=value format.

        Returns:
            List[Word]: List of Word objects.
        """
        # Build query with filters
        query = "SELECT * FROM collections_word"
        params = []

        for key, value in filters.items():
            if value is not None:
                query += f" AND {key} = ?"
                params.append(value)

        result = self.execute_query(query, tuple(params), fetch=True)

        if not result:
            return []

        # Convert results to Word objects
        columns = [
            'id', 'english_word', 'russian_word', 'listening',
            'sentences', 'level', 'brown', 'get_download'
        ]

        words = []
        for row in result:
            data = dict(zip(columns, row))
            words.append(Word.from_dict(data))

        return words

    def get_words_by_book(self, book_id: int) -> List[Dict[str, Any]]:
        """
        Gets words by book ID with frequency information.

        Args:
            book_id (int): Book ID.

        Returns:
            List[Dict[str, Any]]: List of dictionaries with word information.
        """
        query = """
            SELECT cw.*, wbl.frequency
            FROM collections_word cw
            JOIN word_book_link wbl ON cw.id = wbl.word_id
            WHERE wbl.book_id = ?
            ORDER BY wbl.frequency DESC
        """
        result = self.execute_query(query, (book_id,), fetch=True)

        if not result:
            return []

        # Convert results to dictionaries
        columns = [
            'id', 'english_word', 'russian_word', 'listening',
            'sentences', 'level', 'brown', 'get_download', 'frequency'
        ]

        return [dict(zip(columns, row)) for row in result]

    def update_download_status(self, table_name: str, column_name: str, media_folder: str) -> int:
        """
        Updates download status based on file presence in folder.

        Args:
            table_name (str): Table name.
            column_name (str): Column name with word/phrase name.
            media_folder (str): Path to media files folder.

        Returns:
            int: Number of updated records.
        """
        import os

        # Get list of words/phrases for which files are not downloaded
        query = f"SELECT {column_name} FROM {table_name} WHERE get_download = 0"
        result = self.execute_query(query, fetch=True)

        if not result:
            return 0

        words = [row[0] for row in result]
        updated_count = 0

        # Check file presence and update status
        for word in words:
            word_modified = word.replace(" ", "_").lower()
            file_path = os.path.join(media_folder, f"pronunciation_en_{word_modified}.mp3")

            status = 1 if os.path.isfile(file_path) else 0

            # Update status in database
            update_query = f"UPDATE {table_name} SET get_download = ? WHERE {column_name} = ?"
            self.execute_query(update_query, (status, word))

            if status == 1:
                updated_count += 1

        return updated_count

    def process_translate_file(self, translate_file: str, table_name: str = "collections_word") -> int:
        """
        Processes translation file and updates the database.

        Args:
            translate_file (str): Path to translation file.
            table_name (str, optional): Table name. Defaults to "collections_word".

        Returns:
            int: Number of processed records.
        """
        import os

        if not os.path.exists(translate_file):
            logger.error(f"Translate file not found: {translate_file}")
            return 0

        processed_count = 0

        try:
            with open(translate_file, "r", encoding="utf-8") as file:
                for line in file:
                    line = line.strip()
                    if not line:
                        continue

                    parts = line.split(";")

                    if len(parts) == 5:
                        english_word, russian_translate, english_sentence, russian_sentence, level = parts

                        # Form path to audio file
                        sound_file = english_word.replace(" ", "_").lower()
                        listening = f"[sound:pronunciation_en_{sound_file}.mp3]"

                        # Update information in database
                        update_query = f"""
                            UPDATE {table_name}
                            SET russian_word = ?,
                                sentences = ?,
                                level = ?,
                                listening = ?
                            WHERE english_word = ?
                        """
                        self.execute_query(
                            update_query,
                            (
                                russian_translate,
                                f"{english_sentence}<br>{russian_sentence}",
                                level,
                                listening,
                                english_word.lower(),
                            ),
                        )

                        processed_count += 1
                    else:
                        logger.warning(f"Invalid line format: {line}")
        except Exception as e:
            logger.error(f"Error processing translate file: {e}")
            raise

        return processed_count

    def process_phrasal_verb_file(self, phrasal_verb_file: str) -> int:
        """
        Processes phrasal verb file and updates the database.

        Args:
            phrasal_verb_file (str): Path to phrasal verb file.

        Returns:
            int: Number of processed records.
        """
        import os

        if not os.path.exists(phrasal_verb_file):
            logger.error(f"Phrasal verb file not found: {phrasal_verb_file}")
            return 0

        processed_count = 0

        try:
            with open(phrasal_verb_file, "r", encoding="utf-8") as file:
                for line in file:
                    line = line.strip()
                    if not line:
                        continue

                    parts = line.split(";")

                    if len(parts) == 5:
                        phrasal_verb, russian_translate, using, english_sentence, russian_sentence = parts

                        # Get base verb (first word)
                        english_word = phrasal_verb.split(" ")[0]

                        # Get base verb ID
                        query = "SELECT id FROM collections_word WHERE english_word = ?"
                        result = self.execute_query(query, (english_word,), fetch=True)

                        if not result:
                            logger.warning(f"Base word not found: {english_word}")
                            continue

                        word_id = result[0][0]

                        # Form path to audio file
                        sound_file = phrasal_verb.lower().replace(" ", "_")
                        listening = f"[sound:pronunciation_en_{sound_file}.mp3]"

                        # Insert phrasal verb
                        insert_query = """
                            INSERT OR IGNORE INTO phrasal_verb
                            (phrasal_verb, russian_translate, "using", sentence, word_id, listening)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """
                        self.execute_query(
                            insert_query,
                            (
                                phrasal_verb,
                                russian_translate,
                                using,
                                f"{english_sentence}<br>{russian_sentence}",
                                word_id,
                                listening,
                            ),
                        )

                        processed_count += 1
                    else:
                        logger.warning(f"Invalid line format: {line}")
        except Exception as e:
            logger.error(f"Error processing phrasal verb file: {e}")
            raise

        return processed_count

    def update_schema_if_needed(self) -> None:
        """
        Checks and updates database schema if needed.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Check schema version
                cursor.execute("PRAGMA user_version")
                # current_version = cursor.fetchone()[0]

                # Check for new learning_status field
                cursor.execute("PRAGMA table_info(collections_word)")
                columns = [column[1] for column in cursor.fetchall()]

                # If learning_status field is missing, add it
                if "learning_status" not in columns:
                    logger.info("Updating database schema: adding learning_status column")
                    cursor.execute("ALTER TABLE collections_word ADD COLUMN learning_status INTEGER DEFAULT 0")
                    cursor.execute(
                        "CREATE INDEX IF NOT EXISTS idx_collections_word_learning_status ON"
                        " collections_word(learning_status)")
                    cursor.execute("PRAGMA user_version = 2")
                    logger.info("Database schema updated to version 2")

                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error checking/updating schema: {e}")

    def update_word_status(self, word_id: int, status: int) -> bool:
        """
        Updates word learning status.

        Args:
            word_id (int): Word ID.
            status (int): New learning status.

        Returns:
            bool: True on success, False otherwise.
        """
        query = """
            UPDATE collections_word
            SET learning_status = ?
            WHERE id = ?
        """
        try:
            self.execute_query(query, (status, word_id))
            logger.info(f"Updated learning status for word ID {word_id} to {status}")
            return True
        except sqlite3.Error as e:
            logger.error(f"Error updating learning status: {e}")
            return False

    def update_word_status_by_english(self, english_word: str, status: int) -> bool:
        """
        Updates word learning status by its English value.

        Args:
            english_word (str): English word.
            status (int): New learning status.

        Returns:
            bool: True on success, False otherwise.
        """
        query = """
            UPDATE collections_word
            SET learning_status = ?
            WHERE english_word = ?
        """
        try:
            self.execute_query(query, (status, english_word))
            logger.info(f"Updated learning status for word '{english_word}' to {status}")
            return True
        except sqlite3.Error as e:
            logger.error(f"Error updating learning status: {e}")
            return False

    def get_words_by_status(self, status: int) -> List[Word]:
        """
        Gets words by learning status.

        Args:
            status (int): Learning status.

        Returns:
            List[Word]: List of Word objects.
        """
        query = "SELECT * FROM collections_word WHERE learning_status = ?"
        result = self.execute_query(query, (status,), fetch=True)

        if not result:
            return []

        # Convert results to Word objects
        columns = [
            'id', 'english_word', 'russian_word', 'listening',
            'sentences', 'level', 'brown', 'get_download', 'learning_status'
        ]

        words = []
        for row in result:
            # Handle case when learning_status column is missing in result
            if len(row) == 8:
                row = row + (0,)  # Add default value for learning_status

            data = dict(zip(columns, row))
            words.append(Word.from_dict(data))

        return words

    def batch_update_word_status(self, english_words: List[str], status: int) -> int:
        """
        Batch updates learning status for a list of words.

        Args:
            english_words (List[str]): List of English words.
            status (int): New learning status.

        Returns:
            int: Number of updated words.
        """
        if not english_words:
            return 0

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                updated_count = 0

                # Update status for each word
                for word in english_words:
                    cursor.execute(
                        "UPDATE collections_word SET learning_status = ? WHERE english_word = ?",
                        (status, word)
                    )
                    updated_count += cursor.rowcount

                conn.commit()

                logger.info(f"Batch updated learning status to {status} for {updated_count} words")
                return updated_count
        except sqlite3.Error as e:
            logger.error(f"Error batch updating learning status: {e}")
            return 0

    def update_book_stats(self, book_id: int, total_words: int, unique_words: int) -> bool:
        """
        Updates book statistics.

        Args:
            book_id (int): Book ID.
            total_words (int): Total word count.
            unique_words (int): Unique word count.

        Returns:
            bool: True on success, False otherwise.
        """
        query = """
            UPDATE book
            SET total_words = ?, unique_words = ?, scrape_date = datetime('now')
            WHERE id = ?
        """
        try:
            self.execute_query(query, (total_words, unique_words, book_id))
            logger.info(f"Updated stats for book ID {book_id}: {total_words} total words, {unique_words} unique words")
            return True
        except Exception as e:
            logger.error(f"Error updating book stats: {e}")
            return False

    def get_book_by_id(self, book_id: int) -> Optional[Book]:
        """
        Gets a book by ID.

        Args:
            book_id (int): Book ID.

        Returns:
            Optional[Book]: Book object or None if book not found.
        """
        query = "SELECT * FROM book WHERE id = ?"
        result = self.execute_query(query, (book_id,), fetch=True)

        if not result:
            return None

        # Convert result row to dictionary
        columns = [
            'id', 'title', 'total_words', 'unique_words', 'scrape_date'
        ]
        data = dict(zip(columns, result[0]))

        return Book.from_dict(data)

    def get_books_with_stats(self) -> List[Dict[str, Any]]:
        """
        Gets a list of all books with their statistics.

        Returns:
            List[Dict[str, Any]]: List of dictionaries with book data.
        """
        query = """
            SELECT b.id, b.title, b.total_words, b.unique_words, b.scrape_date,
                   COUNT(DISTINCT wbl.word_id) as linked_words,
                   SUM(wbl.frequency) as word_occurrences
            FROM book b
            LEFT JOIN word_book_link wbl ON b.id = wbl.book_id
            GROUP BY b.id, b.title
            ORDER BY b.title
        """
        result = self.execute_query(query, fetch=True)

        if not result:
            return []

        # Convert results to dictionaries
        books = []
        for row in result:
            book = {
                'id': row[0],
                'title': row[1],
                'total_words': row[2],
                'unique_words': row[3],
                'scrape_date': row[4],
                'linked_words': row[5],
                'word_occurrences': row[6]
            }
            books.append(book)

        return books
