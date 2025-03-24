"""
Repository for working with SQLite database.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union, cast

from config.settings import DB_FILE
from src.db.models import Book, PhrasalVerb, Word

logger = logging.getLogger(__name__)


class DatabaseRepository:
    """Repository for working with the database."""

    def __init__(self, db_path: str = DB_FILE):
        """
        Initializes the repository.

        Args:
            db_path: Path to the database file.
        """
        self.db_path = db_path

    @contextmanager
    def get_connection(self) -> Iterator[sqlite3.Connection]:
        """
        Context manager for database connections.

        Yields:
            Database connection object.
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            yield conn
        except sqlite3.Error as e:
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if conn:
                conn.close()

    def execute_query(
            self, query: str, parameters: Union[Tuple, List] = (), fetch: bool = False,
            fetch_one: bool = False, as_dict: bool = False
    ) -> Optional[List[Union[Tuple, Dict[str, Any]]]]:
        """
        Executes an SQL query with error handling and connection management.

        Args:
            query: SQL query string.
            parameters: Query parameters.
            fetch: Whether to fetch results.
            fetch_one: Whether to fetch a single result.
            as_dict: Whether to return results as dictionaries.

        Returns:
            Query results or None.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, parameters)

                if fetch_one:
                    result = cursor.fetchone()
                    if result and as_dict:
                        return [dict(result)]
                    return [result] if result else None

                if fetch:
                    results = cursor.fetchall()
                    if as_dict:
                        return [dict(row) for row in results]
                    return list(results)

                conn.commit()
                return None
        except sqlite3.Error as e:
            logger.error(f"Database error in execute_query: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Parameters: {parameters}")
            raise

    def execute_script(self, script: str) -> None:
        """
        Executes an SQL script.

        Args:
            script: SQL script to execute.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.executescript(script)
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database error in execute_script: {e}")
            logger.error(f"Script: {script}")
            raise

    def insert_or_update_book(self, book: Book) -> int:
        """
        Inserts or updates a book in the database.

        Args:
            book: Book object.

        Returns:
            ID of the inserted/updated book.
        """
        try:
            # Try to insert first
            query = "INSERT OR IGNORE INTO book (title) VALUES (?)"
            self.execute_query(query, (book.title,))

            # Get the book ID
            query = "SELECT id FROM book WHERE title = ?"
            result = self.execute_query(query, (book.title,), fetch_one=True)

            if result and result[0]:
                book_id = result[0][0]

                # Update stats if provided
                if book.total_words or book.unique_words:
                    update_query = """
                        UPDATE book
                        SET total_words = COALESCE(?, total_words),
                            unique_words = COALESCE(?, unique_words),
                            scrape_date = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """
                    self.execute_query(
                        update_query,
                        (book.total_words, book.unique_words, book_id)
                    )

                return book_id

            return 0
        except sqlite3.Error as e:
            logger.error(f"Error in insert_or_update_book: {e}")
            raise

    def insert_or_update_word(self, word: Word) -> int:
        """
        Inserts or updates a word in the database.

        Args:
            word: Word object.

        Returns:
            ID of the inserted/updated word.
        """
        try:
            # Check if word exists
            check_query = "SELECT id FROM collections_word WHERE english_word = ?"
            result = self.execute_query(check_query, (word.english_word,), fetch_one=True)

            if result and result[0]:
                word_id = result[0][0]

                # Update existing word
                update_query = """
                    UPDATE collections_word
                    SET russian_word = COALESCE(?, russian_word),
                        listening = COALESCE(?, listening),
                        sentences = COALESCE(?, sentences),
                        level = COALESCE(?, level),
                        brown = COALESCE(?, brown),
                        get_download = COALESCE(?, get_download),
                        learning_status = COALESCE(?, learning_status)
                    WHERE id = ?
                """
                self.execute_query(
                    update_query,
                    (
                        word.russian_word,
                        word.listening,
                        word.sentences,
                        word.level,
                        word.brown,
                        word.get_download,
                        word.learning_status,
                        word_id,
                    )
                )

                return word_id
            else:
                # Insert new word
                insert_query = """
                    INSERT INTO collections_word
                    (english_word, listening, russian_word, sentences, level, brown, get_download, learning_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                        word.learning_status,
                    )
                )

                # Get ID of the new word
                result = self.execute_query(
                    "SELECT id FROM collections_word WHERE english_word = ?",
                    (word.english_word,),
                    fetch_one=True
                )

                return result[0][0] if result and result[0] else 0
        except sqlite3.Error as e:
            logger.error(f"Error in insert_or_update_word: {e}")
            raise

    def link_word_to_book(self, word_id: int, book_id: int, frequency: int = 1) -> bool:
        """
        Links a word to a book or updates the frequency if link exists.

        Args:
            word_id: Word ID.
            book_id: Book ID.
            frequency: Frequency of the word in the book.

        Returns:
            True if successful, False otherwise.
        """
        try:
            query = """
                INSERT INTO word_book_link (word_id, book_id, frequency)
                VALUES (?, ?, ?)
                ON CONFLICT(word_id, book_id) 
                DO UPDATE SET frequency = frequency + ?
            """
            self.execute_query(query, (word_id, book_id, frequency, frequency))
            return True
        except sqlite3.Error as e:
            logger.error(f"Error in link_word_to_book: {e}")
            return False

    def insert_or_update_phrasal_verb(self, verb: PhrasalVerb) -> int:
        """
        Inserts or updates a phrasal verb in the database.

        Args:
            verb: PhrasalVerb object.

        Returns:
            ID of the inserted/updated phrasal verb.
        """
        try:
            # Check if phrasal verb exists
            check_query = "SELECT id FROM phrasal_verb WHERE phrasal_verb = ?"
            result = self.execute_query(check_query, (verb.phrasal_verb,), fetch_one=True)

            if result and result[0]:
                verb_id = result[0][0]

                # Update existing phrasal verb
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
                    )
                )

                return verb_id
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
                    )
                )

                # Get ID of the new phrasal verb
                result = self.execute_query(
                    "SELECT id FROM phrasal_verb WHERE phrasal_verb = ?",
                    (verb.phrasal_verb,),
                    fetch_one=True
                )

                return result[0][0] if result and result[0] else 0
        except sqlite3.Error as e:
            logger.error(f"Error in insert_or_update_phrasal_verb: {e}")
            raise

    def get_word_by_english(self, english_word: str) -> Optional[Word]:
        """
        Gets a word by its English word.

        Args:
            english_word: English word.

        Returns:
            Word object or None.
        """
        query = "SELECT * FROM collections_word WHERE english_word = ?"
        result = self.execute_query(query, (english_word,), fetch_one=True, as_dict=True)

        if not result:
            return None

        return Word.from_dict(result[0])

    def get_words_by_filter(self, **filters) -> List[Word]:
        """
        Gets words by filters.

        Args:
            **filters: Filters in key=value format.

        Returns:
            List of Word objects.
        """
        # Build query with filters
        query_parts = ["SELECT * FROM collections_word"]
        params = []

        for key, value in filters.items():
            if value is not None:
                query_parts.append(f" AND {key} = ?")
                params.append(value)

        query = " ".join(query_parts)
        result = self.execute_query(query, params, fetch=True, as_dict=True)

        if not result:
            return []

        return [Word.from_dict(data) for data in result]

    def get_words_by_book(self, book_id: int, limit: int = 0, offset: int = 0) -> List[Dict[str, Any]]:
        """
        Gets words by book ID with frequency information.

        Args:
            book_id: Book ID.
            limit: Maximum number of results to return (0 for all).
            offset: Number of results to skip.

        Returns:
            List of dictionaries with word information.
        """
        query = """
            SELECT cw.*, wbl.frequency, COALESCE(uws.status, 0) AS status
            FROM collections_word cw
            JOIN word_book_link wbl ON cw.id = wbl.word_id
            LEFT JOIN user_word_status uws ON cw.id = uws.word_id
            WHERE wbl.book_id = ?
            ORDER BY wbl.frequency DESC
        """

        params = [book_id]

        if limit > 0:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        result = self.execute_query(query, params, fetch=True, as_dict=True)

        if not result:
            return []

        return cast(List[Dict[str, Any]], result)

    def update_download_status(self, table_name: str, column_name: str, media_folder: str) -> int:
        """
        Updates download status based on file presence in folder.

        Args:
            table_name: Table name.
            column_name: Column name with word/phrase name.
            media_folder: Path to media files folder.

        Returns:
            Number of updated records.
        """
        # Validate media folder exists
        if not os.path.isdir(media_folder):
            logger.error(f"Media folder not found: {media_folder}")
            return 0

        # Get list of words/phrases for which files are not downloaded
        query = f"SELECT id, {column_name} FROM {table_name} WHERE get_download = 0"
        results = self.execute_query(query, fetch=True)

        if not results:
            return 0

        updated_count = 0

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Check file presence and update status in batches
            for row in results:
                item_id, word = row
                word_modified = str(word).replace(" ", "_").lower()
                file_path = os.path.join(media_folder, f"pronunciation_en_{word_modified}.mp3")

                status = 1 if os.path.isfile(file_path) else 0

                if status == 1:
                    cursor.execute(
                        f"UPDATE {table_name} SET get_download = ? WHERE id = ?",
                        (status, item_id)
                    )
                    updated_count += 1

            conn.commit()

        logger.info(f"Updated download status for {updated_count} items in {table_name}")
        return updated_count

    def process_translate_file(self, translate_file: str, table_name: str = "collections_word") -> int:
        """
        Processes translation file and updates the database.

        Args:
            translate_file: Path to translation file.
            table_name: Table name.

        Returns:
            Number of processed records.
        """
        if not os.path.exists(translate_file):
            logger.error(f"Translate file not found: {translate_file}")
            return 0

        processed_count = 0
        batch_size = 100
        current_batch = []

        try:
            with open(translate_file, "r", encoding="utf-8") as file, self.get_connection() as conn:
                cursor = conn.cursor()

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

                        current_batch.append((
                            russian_translate,
                            f"{english_sentence}<br>{russian_sentence}",
                            level,
                            listening,
                            english_word.lower()
                        ))

                        # Execute updates in batches
                        if len(current_batch) >= batch_size:
                            cursor.executemany(
                                f"""
                                UPDATE {table_name}
                                SET russian_word = ?,
                                    sentences = ?,
                                    level = ?,
                                    listening = ?
                                WHERE english_word = ?
                                """,
                                current_batch
                            )
                            processed_count += len(current_batch)
                            current_batch = []
                    else:
                        logger.warning(f"Invalid line format: {line}")

                # Process any remaining items
                if current_batch:
                    cursor.executemany(
                        f"""
                        UPDATE {table_name}
                        SET russian_word = ?,
                            sentences = ?,
                            level = ?,
                            listening = ?
                        WHERE english_word = ?
                        """,
                        current_batch
                    )
                    processed_count += len(current_batch)

                conn.commit()

        except Exception as e:
            logger.error(f"Error processing translate file: {e}")
            raise

        logger.info(f"Processed {processed_count} translations from {translate_file}")
        return processed_count

    def process_phrasal_verb_file(self, phrasal_verb_file: str) -> int:
        """
        Processes phrasal verb file and updates the database.

        Args:
            phrasal_verb_file: Path to phrasal verb file.

        Returns:
            Number of processed records.
        """
        if not os.path.exists(phrasal_verb_file):
            logger.error(f"Phrasal verb file not found: {phrasal_verb_file}")
            return 0

        processed_count = 0
        verbs_to_insert = []

        try:
            # First, read all lines and prepare data
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

                        # Form path to audio file
                        sound_file = phrasal_verb.lower().replace(" ", "_")
                        listening = f"[sound:pronunciation_en_{sound_file}.mp3]"

                        verbs_to_insert.append({
                            'phrasal_verb': phrasal_verb,
                            'english_word': english_word,
                            'russian_translate': russian_translate,
                            'using': using,
                            'sentence': f"{english_sentence}<br>{russian_sentence}",
                            'listening': listening
                        })
                    else:
                        logger.warning(f"Invalid line format: {line}")

            # Now, process all verbs in a single transaction
            with self.get_connection() as conn:
                cursor = conn.cursor()

                for verb_data in verbs_to_insert:
                    # Get base verb ID
                    cursor.execute(
                        "SELECT id FROM collections_word WHERE english_word = ?",
                        (verb_data['english_word'],)
                    )
                    word_row = cursor.fetchone()

                    if not word_row:
                        logger.warning(f"Base word not found: {verb_data['english_word']}")
                        continue

                    word_id = word_row[0]

                    # Insert phrasal verb
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO phrasal_verb
                        (phrasal_verb, russian_translate, "using", sentence, word_id, listening)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            verb_data['phrasal_verb'],
                            verb_data['russian_translate'],
                            verb_data['using'],
                            verb_data['sentence'],
                            word_id,
                            verb_data['listening']
                        )
                    )

                    if cursor.rowcount > 0:
                        processed_count += 1

                conn.commit()

        except Exception as e:
            logger.error(f"Error processing phrasal verb file: {e}")
            raise

        logger.info(f"Processed {processed_count} phrasal verbs from {phrasal_verb_file}")
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
                current_version = cursor.fetchone()[0]
                logger.info(f"Current database schema version: {current_version}")

                # Apply migrations based on version
                if current_version < 3:
                    from src.db.models import DBInitializer
                    DBInitializer.update_schema_if_needed(self.db_path)

        except sqlite3.Error as e:
            logger.error(f"Error checking/updating schema: {e}")
            raise

    def update_word_status(self, word_id: int, status: int) -> bool:
        """
        Updates word learning status.

        Args:
            word_id: Word ID.
            status: New learning status.

        Returns:
            True on success, False otherwise.
        """
        try:
            query = """
                UPDATE collections_word
                SET learning_status = ?
                WHERE id = ?
            """
            self.execute_query(query, (status, word_id))
            logger.debug(f"Updated learning status for word ID {word_id} to {status}")
            return True
        except sqlite3.Error as e:
            logger.error(f"Error updating learning status: {e}")
            return False

    def update_word_status_by_english(self, english_word: str, status: int) -> bool:
        """
        Updates word learning status by its English value.

        Args:
            english_word: English word.
            status: New learning status.

        Returns:
            True on success, False otherwise.
        """
        try:
            query = """
                UPDATE collections_word
                SET learning_status = ?
                WHERE english_word = ?
            """
            self.execute_query(query, (status, english_word))
            logger.debug(f"Updated learning status for word '{english_word}' to {status}")
            return True
        except sqlite3.Error as e:
            logger.error(f"Error updating learning status: {e}")
            return False

    def get_words_by_status(self, status: int, limit: int = 0, offset: int = 0) -> List[Word]:
        """
        Gets words by learning status.

        Args:
            status: Learning status.
            limit: Maximum number of results to return (0 for all).
            offset: Number of results to skip.

        Returns:
            List of Word objects.
        """
        query = "SELECT * FROM collections_word WHERE learning_status = ?"
        params = [status]

        if limit > 0:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        result = self.execute_query(query, params, fetch=True, as_dict=True)

        if not result:
            return []

        return [Word.from_dict(data) for data in result]

    def batch_update_word_status(self, english_words: List[str], status: int) -> int:
        """
        Batch updates learning status for a list of words.

        Args:
            english_words: List of English words.
            status: New learning status.

        Returns:
            Number of updated words.
        """
        if not english_words:
            return 0

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                updated_count = 0

                # Process in batches of 100
                batch_size = 100
                for i in range(0, len(english_words), batch_size):
                    batch = english_words[i:i + batch_size]

                    # Create placeholders for SQL query
                    placeholders = ','.join(['?'] * len(batch))
                    query = f"""
                        UPDATE collections_word 
                        SET learning_status = ? 
                        WHERE english_word IN ({placeholders})
                    """

                    cursor.execute(query, [status] + batch)
                    updated_count += cursor.rowcount

                conn.commit()

                logger.info(f"Batch updated learning status to {status} for {updated_count} words")
                return updated_count
        except sqlite3.Error as e:
            logger.error(f"Error batch updating learning status: {e}")
            return 0

    def update_book_stats(self, book_id: int, total_words: int = 0, unique_words: int = 0) -> bool:
        """
        Updates book statistics.

        Args:
            book_id: Book ID.
            total_words: Total word count.
            unique_words: Unique word count.

        Returns:
            True on success, False otherwise.
        """
        try:
            query = """
                UPDATE book
                SET total_words = ?, unique_words = ?, scrape_date = datetime('now')
                WHERE id = ?
            """
            self.execute_query(query, (total_words, unique_words, book_id))
            logger.info(f"Updated stats for book ID {book_id}: {total_words} total words, {unique_words} unique words")
            return True
        except Exception as e:
            logger.error(f"Error updating book stats: {e}")
            return False

    def calculate_book_stats(self, book_id: int) -> Dict[str, int]:
        """
        Calculates book statistics from word-book links.

        Args:
            book_id: Book ID.

        Returns:
            Dictionary with total_words and unique_words.
        """
        try:
            query = """
                SELECT 
                    COUNT(DISTINCT word_id) as unique_words,
                    SUM(frequency) as total_words
                FROM word_book_link
                WHERE book_id = ?
            """
            result = self.execute_query(query, (book_id,), fetch_one=True, as_dict=True)

            if result:
                stats = {
                    'total_words': result[0].get('total_words', 0) or 0,
                    'unique_words': result[0].get('unique_words', 0) or 0
                }
                return stats

            return {'total_words': 0, 'unique_words': 0}
        except sqlite3.Error as e:
            logger.error(f"Error calculating book stats: {e}")
            return {'total_words': 0, 'unique_words': 0}

    def get_book_by_id(self, book_id: int) -> Optional[Book]:
        """
        Gets a book by ID.

        Args:
            book_id: Book ID.

        Returns:
            Book object or None if book not found.
        """
        query = "SELECT * FROM book WHERE id = ?"
        result = self.execute_query(query, (book_id,), fetch_one=True, as_dict=True)

        if not result:
            return None

        return Book.from_dict(result[0])

    def get_books_with_stats(self) -> List[Dict[str, Any]]:
        """
        Gets a list of all books with their statistics.

        Returns:
            List of dictionaries with book data.
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
        result = self.execute_query(query, fetch=True, as_dict=True)

        if not result:
            return []

        return cast(List[Dict[str, Any]], result)

    def get_books(self) -> List[Book]:
        """
        Gets a list of all books.

        Returns:
            List of Book objects.
        """
        query = "SELECT * FROM book ORDER BY title"
        result = self.execute_query(query, fetch=True, as_dict=True)

        if not result:
            return []

        return [Book.from_dict(data) for data in result]

    def search_words(self, search_term: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Searches for words by partial match in English or Russian.

        Args:
            search_term: Search term.
            limit: Maximum number of results.

        Returns:
            List of word dictionaries.
        """
        search_param = f"%{search_term}%"
        query = """
            SELECT * FROM collections_word 
            WHERE english_word LIKE ? OR russian_word LIKE ?
            ORDER BY learning_status, english_word
            LIMIT ?
        """
        result = self.execute_query(query, (search_param, search_param, limit), fetch=True, as_dict=True)

        if not result:
            return []

        return cast(List[Dict[str, Any]], result)
