"""
Repository for working with PostgreSQL database.
"""
import logging
import psycopg2
from psycopg2.extras import DictCursor
from typing import Any, Dict, List, Optional, Tuple
import os

from config.settings import DB_CONFIG
from app.words.models import PhrasalVerb, CollectionWords as Word
from app.books.models import Book

logger = logging.getLogger(__name__)


class DatabaseRepository:
    """Repository for working with the database."""

    def __init__(self, db_config: Dict = None):
        """
        Initializes the repository.

        Args:
            db_config (Dict, optional): Database configuration.
        """
        self.db_config = db_config or DB_CONFIG

    def get_connection(self):
        """
        Gets a connection to the database.

        Returns:
            Connection: PostgreSQL connection object.
        """
        return psycopg2.connect(**self.db_config)

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
                with conn.cursor() as cursor:
                    cursor.execute(query, parameters)

                    if fetch:
                        return cursor.fetchall()
                    return None
        except psycopg2.Error as e:
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
            INSERT INTO book (title) 
            VALUES (%s)
            ON CONFLICT (title) DO NOTHING
            RETURNING id
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (book.title,))
                    result = cursor.fetchone()

                    if result:
                        return result[0]

                    # If no row was returned, get the existing book id
                    cursor.execute("SELECT id FROM book WHERE title = %s", (book.title,))
                    result = cursor.fetchone()

                    if result:
                        return result[0]
            return 0
        except psycopg2.Error as e:
            logger.error(f"Error inserting/updating book: {e}")
            return 0

    def bulk_insert_or_update_words(self, words_batch):
        """
        Выполняет пакетную вставку или обновление слов.

        Args:
            words_batch: Список объектов Word (CollectionWords)

        Returns:
            Dict[str, int]: Словарь с соответствием {english_word: word_id}
        """
        if not words_batch:
            return {}

        word_id_map = {}
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Подготовка списка английских слов для проверки существования
                    english_words = [word.english_word for word in words_batch]

                    # Получение существующих слов одним запросом
                    placeholders = ','.join(['%s'] * len(english_words))
                    cursor.execute(
                        f"SELECT id, english_word FROM collection_words WHERE english_word IN ({placeholders})",
                        english_words
                    )
                    existing_words = {row[1]: row[0] for row in cursor.fetchall()}

                    # Разделение на новые и существующие слова
                    words_to_insert = []
                    words_to_update = []

                    for word in words_batch:
                        if word.english_word in existing_words:
                            # Слово существует, подготовка к обновлению
                            words_to_update.append((
                                word.listening, word.russian_word, word.sentences,
                                word.level, word.brown, word.get_download,
                                existing_words[word.english_word]
                            ))
                            word_id_map[word.english_word] = existing_words[word.english_word]
                        else:
                            # Новое слово, подготовка к вставке
                            words_to_insert.append((
                                word.english_word, word.listening, word.russian_word,
                                word.sentences, word.level, word.brown, word.get_download
                            ))

                    # Пакетное обновление существующих слов
                    if words_to_update:
                        update_query = """
                            UPDATE collection_words
                            SET listening = COALESCE(%s, listening),
                                russian_word = COALESCE(%s, russian_word),
                                sentences = COALESCE(%s, sentences),
                                level = COALESCE(%s, level),
                                brown = COALESCE(%s, brown),
                                get_download = COALESCE(%s, get_download)
                            WHERE id = %s
                        """
                        cursor.executemany(update_query, words_to_update)

                    # Пакетная вставка новых слов
                    if words_to_insert:
                        insert_query = """
                            INSERT INTO collection_words
                            (english_word, listening, russian_word, sentences, level, brown, get_download)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            RETURNING id, english_word
                        """
                        for word_data in words_to_insert:
                            cursor.execute(insert_query, word_data)
                            id, english_word = cursor.fetchone()
                            word_id_map[english_word] = id

            return word_id_map
        except psycopg2.Error as e:
            logger.error(f"Error bulk inserting/updating words: {e}")
            return word_id_map

    def bulk_link_words_to_book(self, link_data):
        """
        Выполняет пакетную связь слов с книгой.

        Args:
            link_data: Список кортежей (word_id, book_id, frequency)
        """
        if not link_data:
            return

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    query = """
                        INSERT INTO word_book_link
                        (word_id, book_id, frequency)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (word_id, book_id) DO UPDATE
                        SET frequency = word_book_link.frequency + EXCLUDED.frequency
                    """
                    cursor.executemany(query, link_data)
        except psycopg2.Error as e:
            logger.error(f"Error bulk linking words to book: {e}")

    def clear_book_word_links(self, book_id):
        """
        Удаляет все записи word_book_link для указанной книги.
        Используется при повторной обработке книги для избежания дублирования.

        Args:
            book_id: ID книги
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM word_book_link WHERE book_id = %s",
                        (book_id,)
                    )
                    deleted_count = cursor.rowcount
                    logger.info(f"Удалено {deleted_count} старых записей word_book_link для книги {book_id}")
        except psycopg2.Error as e:
            logger.error(f"Error clearing word links for book {book_id}: {e}")

    # Этот метод может быть использован в вашем коде для замены медленного цикла
    def process_batch_from_original_format(self, word_data, book_id, batch_size=500):
        """
        Обрабатывает пакет данных в оригинальном формате и связывает слова с книгой.

        Args:
            word_data: Список кортежей (english_word, listening, brown, frequency)
            book_id: ID книги
            batch_size: Размер пакета для обработки

        Returns:
            int: Количество обработанных слов
        """
        total_processed = 0
        batch_num = 0
        words_batch = []
        frequency_map = {}

        for idx, (english_word, listening, brown, frequency) in enumerate(word_data):
            word = Word(
                english_word=english_word,
                listening=listening,
                brown=brown,
            )
            words_batch.append(word)
            frequency_map[english_word] = frequency

            # Когда набрали полный пакет или это последний элемент
            if len(words_batch) >= batch_size or idx == len(word_data) - 1:
                batch_num += 1
                # Вставляем/обновляем слова пакетом
                word_id_map = self.bulk_insert_or_update_words(words_batch)

                # Подготавливаем данные для связывания
                link_data = []
                for eng_word, word_id in word_id_map.items():
                    if word_id:
                        link_data.append((word_id, book_id, frequency_map[eng_word]))

                # Связываем с книгой
                if link_data:
                    self.bulk_link_words_to_book(link_data)
                    total_processed += len(link_data)


                # Очищаем пакеты для следующей итерации
                words_batch = []
                frequency_map = {}

        return total_processed

    def insert_or_update_word(self, word: Word) -> int:
        """
        Inserts or updates a word in the database.

        Args:
            word (Word): Word object.

        Returns:
            int: ID of the inserted word.
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Check if word exists
                    cursor.execute("SELECT id FROM collection_words WHERE english_word = %s", (word.english_word,))
                    result = cursor.fetchone()

                    if result:
                        word_id = result[0]

                        # Update word (only update non-NULL values)
                        update_query = """
                            UPDATE collection_words
                            SET listening = COALESCE(%s, listening),
                                russian_word = COALESCE(%s, russian_word),
                                sentences = COALESCE(%s, sentences),
                                level = COALESCE(%s, level),
                                brown = COALESCE(%s, brown),
                                get_download = COALESCE(%s, get_download)
                            WHERE id = %s
                        """
                        cursor.execute(
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
                            INSERT INTO collection_words
                            (english_word, listening, russian_word, sentences, level, brown, get_download)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        """
                        cursor.execute(
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
                        result = cursor.fetchone()
                        word_id = result[0] if result else 0

                    return word_id
        except psycopg2.Error as e:
            logger.error(f"Error inserting/updating word: {e}")
            return 0

    def link_word_to_book(self, word_id: int, book_id: int, frequency: int) -> None:
        """
        Links a word to a book.

        Args:
            word_id (int): Word ID.
            book_id (int): Book ID.
            frequency (int): Frequency of the word in the book.
        """
        query = """
            INSERT INTO word_book_link
            (word_id, book_id, frequency)
            VALUES (%s, %s, %s)
            ON CONFLICT (word_id, book_id) DO UPDATE
            SET frequency = %s
        """
        try:
            self.execute_query(query, (word_id, book_id, frequency, frequency))
        except psycopg2.Error as e:
            logger.error(f"Error linking word to book: {e}")

    def insert_or_update_phrasal_verb(self, verb: PhrasalVerb) -> int:
        """
        Inserts or updates a phrasal verb in the database.

        Args:
            verb (PhrasalVerb): Phrasal verb object.

        Returns:
            int: ID of the inserted phrasal verb.
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Check if phrasal verb exists
                    cursor.execute("SELECT id FROM phrasal_verb WHERE phrasal_verb = %s", (verb.phrasal_verb,))
                    result = cursor.fetchone()

                    if result:
                        verb_id = result[0]

                        # Update phrasal verb
                        update_query = """
                            UPDATE phrasal_verb
                            SET russian_translate = COALESCE(%s, russian_translate),
                                "using" = COALESCE(%s, "using"),
                                sentence = COALESCE(%s, sentence),
                                word_id = COALESCE(%s, word_id),
                                listening = COALESCE(%s, listening),
                                get_download = COALESCE(%s, get_download)
                            WHERE id = %s
                        """
                        cursor.execute(
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
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        """
                        cursor.execute(
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
                        result = cursor.fetchone()
                        verb_id = result[0] if result else 0

                    return verb_id
        except psycopg2.Error as e:
            logger.error(f"Error inserting/updating phrasal verb: {e}")
            return 0

    def get_word_by_english(self, english_word: str) -> Optional[Word]:
        """
        Gets a word by its English word.

        Args:
            english_word (str): English word.

        Returns:
            Optional[Word]: Word object or None.
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=DictCursor) as cursor:
                    query = "SELECT * FROM collection_words WHERE english_word = %s"
                    cursor.execute(query, (english_word,))
                    result = cursor.fetchone()

                    if not result:
                        return None

                    return Word.from_dict(dict(result))
        except psycopg2.Error as e:
            logger.error(f"Error getting word: {e}")
            return None

    def get_words_by_filter(self, **filters) -> List[Word]:
        """
        Gets words by filters.

        Args:
            **filters: Filters in key=value format.

        Returns:
            List[Word]: List of Word objects.
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=DictCursor) as cursor:
                    # Build query with filters
                    query = "SELECT * FROM collection_words WHERE 1=1"
                    params = []

                    for key, value in filters.items():
                        if value is not None:
                            query += f" AND {key} = %s"
                            params.append(value)

                    cursor.execute(query, tuple(params))
                    results = cursor.fetchall()

                    if not results:
                        return []

                    return [Word.from_dict(dict(row)) for row in results]
        except psycopg2.Error as e:
            logger.error(f"Error getting words by filter: {e}")
            return []

    def get_words_by_book(self, book_id: int) -> List[Dict[str, Any]]:
        """
        Gets words by book ID with frequency information.

        Args:
            book_id (int): Book ID.

        Returns:
            List[Dict[str, Any]]: List of dictionaries with word information.
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=DictCursor) as cursor:
                    query = """
                        SELECT cw.*, wbl.frequency
                        FROM collection_words cw
                        JOIN word_book_link wbl ON cw.id = wbl.word_id
                        WHERE wbl.book_id = %s
                        ORDER BY wbl.frequency DESC
                    """
                    cursor.execute(query, (book_id,))
                    results = cursor.fetchall()

                    if not results:
                        return []

                    return [dict(row) for row in results]
        except psycopg2.Error as e:
            logger.error(f"Error getting words by book: {e}")
            return []

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
        query = f"SELECT {column_name} FROM {table_name} WHERE (get_download = 0 or get_download isnull)"

        try:
            result = self.execute_query(query, fetch=True)
            if not result:
                return 0

            words = [row[0] for row in result]
            updated_count = 0

            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Check file presence and update status for each word
                    for word in words:
                        word_modified = word.replace(" ", "_").lower()
                        file_path = os.path.join(media_folder, f"pronunciation_en_{word_modified}.mp3")

                        status = 1 if os.path.isfile(file_path) else 0
                        if status == 1:
                            # Update status in database
                            listening = f"[sound:pronunciation_en_{word_modified}.mp3]"
                            update_query = f"UPDATE {table_name} SET get_download = %s, listening = %s WHERE {column_name} = %s"
                            cursor.execute(update_query, (status, listening, word))
                            updated_count += 1

            return updated_count
        except psycopg2.Error as e:
            logger.error(f"Error updating download status: {e}")
            return 0

    def process_translate_file(self, translate_file: str, table_name: str = "collection_words") -> int:
        """
        Processes translation file and updates the database.

        Args:
            translate_file (str): Path to translation file.
            table_name (str, optional): Table name. Defaults to "collection_words".

        Returns:
            int: Number of processed records.
        """
        import os

        if not os.path.exists(translate_file):
            logger.error(f"Translate file not found: {translate_file}")
            return 0

        processed_count = 0

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
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
                                    SET russian_word = %s,
                                        sentences = %s,
                                        level = %s,
                                        listening = %s
                                    WHERE english_word = %s
                                """
                                cursor.execute(
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
            return processed_count
        except (psycopg2.Error, Exception) as e:
            logger.error(f"Error processing translate file: {e}")
            raise

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
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
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
                                cursor.execute("SELECT id FROM collection_words WHERE english_word = %s", (english_word,))
                                result = cursor.fetchone()

                                if not result:
                                    logger.warning(f"Base word not found: {english_word}")
                                    continue

                                word_id = result[0]

                                # Form path to audio file
                                sound_file = phrasal_verb.lower().replace(" ", "_")
                                listening = f"[sound:pronunciation_en_{sound_file}.mp3]"

                                # Insert phrasal verb
                                insert_query = """
                                    INSERT INTO phrasal_verb
                                    (phrasal_verb, russian_translate, "using", sentence, word_id, listening)
                                    VALUES (%s, %s, %s, %s, %s, %s)
                                    ON CONFLICT (phrasal_verb) DO NOTHING
                                """
                                cursor.execute(
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
            return processed_count
        except (psycopg2.Error, Exception) as e:
            logger.error(f"Error processing phrasal verb file: {e}")
            raise

    def update_schema_if_needed(self) -> None:
        """
        Checks and updates database schema if needed.
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Check if learning_status column exists
                    cursor.execute("""
                        SELECT column_name FROM information_schema.columns 
                        WHERE table_name = 'collection_words' AND column_name = 'learning_status'
                    """)
                    result = cursor.fetchone()

                    # If learning_status field is missing, add it
                    if not result:
                        logger.info("Updating database schema: adding learning_status column")
                        cursor.execute("ALTER TABLE collection_words ADD COLUMN learning_status INTEGER DEFAULT 0")
                        cursor.execute(
                            "CREATE INDEX IF NOT EXISTS idx_collection_words_learning_status ON"
                            " collection_words(learning_status)")
                        logger.info("Database schema updated to include learning_status")
        except psycopg2.Error as e:
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
            UPDATE collection_words
            SET learning_status = %s
            WHERE id = %s
        """
        try:
            self.execute_query(query, (status, word_id))
            logger.info(f"Updated learning status for word ID {word_id} to {status}")
            return True
        except psycopg2.Error as e:
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
            UPDATE collection_words
            SET learning_status = %s
            WHERE english_word = %s
        """
        try:
            self.execute_query(query, (status, english_word))
            logger.info(f"Updated learning status for word '{english_word}' to {status}")
            return True
        except psycopg2.Error as e:
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
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=DictCursor) as cursor:
                    query = "SELECT * FROM collection_words WHERE learning_status = %s"
                    cursor.execute(query, (status,))
                    results = cursor.fetchall()

                    if not results:
                        return []

                    return [Word.from_dict(dict(row)) for row in results]
        except psycopg2.Error as e:
            logger.error(f"Error getting words by status: {e}")
            return []

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
                with conn.cursor() as cursor:
                    updated_count = 0

                    # PostgreSQL doesn't support parameterized IN clause directly, so we loop
                    for word in english_words:
                        cursor.execute(
                            "UPDATE collection_words SET learning_status = %s WHERE english_word = %s",
                            (status, word)
                        )
                        updated_count += cursor.rowcount

                logger.info(f"Batch updated learning status to {status} for {updated_count} words")
                return updated_count
        except psycopg2.Error as e:
            logger.error(f"Error batch updating learning status: {e}")
            return 0

    def update_book_stats(self, book_id: int, words_total: int, unique_words: int) -> bool:
        """
        Updates book statistics.

        Args:
            book_id (int): Book ID.
            words_total (int): Total word count.
            unique_words (int): Unique word count.

        Returns:
            bool: True on success, False otherwise.
        """
        query = """
            UPDATE book
            SET words_total = %s, unique_words = %s, created_at = NOW()
            WHERE id = %s
        """
        try:
            self.execute_query(query, (words_total, unique_words, book_id))
            logger.info(f"Updated stats for book ID {book_id}: {words_total} total words, {unique_words} unique words")
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
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=DictCursor) as cursor:
                    query = "SELECT * FROM book WHERE id = %s"
                    cursor.execute(query, (book_id,))
                    result = cursor.fetchone()

                    if not result:
                        return None

                    return Book.from_dict(dict(result))
        except psycopg2.Error as e:
            logger.error(f"Error getting book: {e}")
            return None

    def get_books_with_stats(self) -> List[Dict[str, Any]]:
        """
        Gets a list of all books with their statistics.

        Returns:
            List[Dict[str, Any]]: List of dictionaries with book data.
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=DictCursor) as cursor:
                    query = """
                        SELECT b.id, b.title, b.words_total, b.unique_words, b.created_at,
                            COUNT(DISTINCT wbl.word_id) as linked_words,
                            SUM(wbl.frequency) as word_occurrences
                        FROM book b
                        LEFT JOIN word_book_link wbl ON b.id = wbl.book_id
                        GROUP BY b.id, b.title
                        ORDER BY b.title
                    """
                    cursor.execute(query)
                    results = cursor.fetchall()

                    if not results:
                        return []

                    return [dict(row) for row in results]
        except psycopg2.Error as e:
            logger.error(f"Error getting books with stats: {e}")
            return []
