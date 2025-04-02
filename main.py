#!/usr/bin/env python3
"""
The main module of the program for word processing and learning.
"""
import argparse
import logging
import os
import sys

import click
from flask.cli import cli

from config.settings import (
    COLLECTIONS_TABLE, DB_CONFIG, MAX_PAGES, MEDIA_FOLDER, PHRASAL_VERB_FILE, PHRASAL_VERB_TABLE, TRANSLATE_FILE
)
from app.words.models import CollectionWords as Word
from app.books.models import Book
from app.utils.helpers import setup_logging
from app.nlp.setup import download_nltk_resources, initialize_nltk
from app.nlp.processor import prepare_word_data
from app.web.scraper import WebScraper
from app.repository import DatabaseRepository


logger = logging.getLogger(__name__)


def parse_arguments():
    """
    Parses command line arguments.

    Returns:
        argparse.Namespace: argument object.
    """
    parser = argparse.ArgumentParser(description="Words Processing Tool")

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Command to initialize the database
    subparsers.add_parser("init", help="Initialize database")

    # The command for scraping web pages
    scrape_parser = subparsers.add_parser("scrape", help="Scrape website for words")
    scrape_parser.add_argument("url", help="Base URL to scrape")
    scrape_parser.add_argument("--pages", type=int, default=1, help="Number of pages to scrape")
    scrape_parser.add_argument("--book", required=True, help="Book title")

    # Command to update download status
    update_parser = subparsers.add_parser("update-download", help="Update download status")
    update_parser.add_argument("--table", choices=[COLLECTIONS_TABLE, PHRASAL_VERB_TABLE],
                               default=COLLECTIONS_TABLE, help="Table to update")

    # Command to process a translation file
    translate_parser = subparsers.add_parser("process-translate", help="Process translation file")
    translate_parser.add_argument("--file", default=TRANSLATE_FILE, help="Translation file path")

    # Command to process a phrasal verb file
    phrasal_parser = subparsers.add_parser("process-phrasal", help="Process phrasal verbs file")
    phrasal_parser.add_argument("--file", default=PHRASAL_VERB_FILE, help="Phrasal verbs file path")

    # The command to fix the listening field
    subparsers.add_parser("fix-listening", help="Fix listening field")

    # Command to get a list of words to load
    download_parser = subparsers.add_parser("get-download", help="Get words for download")
    download_parser.add_argument("--pattern", default=None, help="Filter pattern (e.g., 's%')")
    download_parser.add_argument("--output", help="Output file for words list")

    # Command to update word study status
    status_parser = subparsers.add_parser("update-status",
                                          help="Update learning status for words")
    status_parser.add_argument("--status", type=int, required=True,
                               help="Learning status (0=New, 1=Known, 2=Queued, 3=Active, 4=Mastered)")
    status_parser.add_argument("--word", help="Single word to update")
    status_parser.add_argument("--file", help="File with words (one per line)")
    status_parser.add_argument("--pattern", help="SQL LIKE pattern for word selection (e.g., 's%')")

    # Command to display a list of words by status
    list_parser = subparsers.add_parser("list-words",
                                        help="List words by learning status")
    list_parser.add_argument("--status", type=int,
                             help="Learning status (0=New, 1=Known, 2=Queued, 3=Active, 4=Mastered)")
    list_parser.add_argument("--output", help="Output file for word list")

    # Command to display statistics on word statuses
    stats_parser = subparsers.add_parser("status-stats",
                                         help="Show word learning status statistics")
    stats_parser.add_argument("--book", help="Show statistics for specific book")

    # Common arguments
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                        default="INFO", help="Logging level")
    parser.add_argument("--log-file", help="Log to file")

    # No longer needed as we're using PostgreSQL connection parameters from config
    # parser.add_argument("--db", default=DB_FILE, help="Database file path")

    # Command to update book statistics
    update_stats_parser = subparsers.add_parser("update-book-stats",
                                                help="Update book statistics from word links")
    update_stats_parser.add_argument("--book-id", type=int, help="Update statistics for specific book ID")

    return parser.parse_args()


def init_database(_: argparse.Namespace) -> None:
    """
    Initializes the database.

    Args:
        _ (argparse.Namespace): command line arguments (unused).
    """
    logger.info("Initializing PostgreSQL database")

    try:
        # Create a connection to check if we can connect
        repo = DatabaseRepository(DB_CONFIG)
        with repo.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT version()")
                version = cursor.fetchone()[0]
                logger.info(f"Connected to PostgreSQL: {version}")

        # Run schema initialization
        from app.utils.db_init import init_db
        init_db()

        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise


def scrape_website(args: argparse.Namespace) -> None:
    """
    Scrapes a website and saves the words to a database.

    Args:
        args (argparse.Namespace): command line arguments.
    """
    url = args.url
    pages = min(args.pages, MAX_PAGES)  # Limit the number of pages
    book_title = args.book

    logger.info(f"Scraping website: {url}, Pages: {pages}, Book: {book_title}")

    # NLTK initialization
    download_nltk_resources()
    _, brown_words, _ = initialize_nltk()

    # Scraping the Website
    scraper = WebScraper()
    all_words = scraper.process_multiple_pages(url, pages)

    if not all_words:
        logger.error("No words extracted from the website")
        return

    total_words = len(all_words)
    unique_words = len(set(all_words))

    logger.info(f"Extracted {total_words} words, {unique_words} unique")

    # Preparing data for insertion
    word_data = prepare_word_data(all_words, brown_words)

    # Create a book object with statistics
    book = Book(
        title=book_title,
        total_words=total_words,
        unique_words=unique_words
    )

    # Insert into the database
    repo = DatabaseRepository()
    book_id = repo.insert_or_update_book(book)

    if not book_id:
        logger.error("Failed to insert/update book")
        return

    # Updating the book's statistics
    repo.update_book_stats(book_id, total_words, unique_words)

    # Insert words and links
    for english_word, listening, brown, frequency in word_data:
        word = Word(
            english_word=english_word,
            listening=listening,
            brown=brown,
        )
        word_id = repo.insert_or_update_word(word)

        if word_id:
            repo.link_word_to_book(word_id, book_id, frequency)

    logger.info(f"Successfully processed {len(word_data)} words for book '{book_title}'")
    logger.info(f"Book statistics: {total_words} total words, {unique_words} unique words")


def update_download_status(args: argparse.Namespace) -> None:
    """
    Updates the download status of the pronunciation files.

    Args:
        args (argparse.Namespace): command line arguments.
    """
    table_name = args.table

    logger.info(f"Updating download status for table: {table_name}")

    # Define a column with a name depending on the table
    column_name = "english_word" if table_name == COLLECTIONS_TABLE else "phrasal_verb"

    # Status update
    repo = DatabaseRepository()
    updated_count = repo.update_download_status(table_name, column_name, MEDIA_FOLDER)

    logger.info(f"Updated download status for {updated_count} records")


def process_translate_file(args: argparse.Namespace) -> None:
    """
    Processes a file with translations.

    Args:
        args (argparse.Namespace): command line arguments.
    """
    translate_file = args.file

    logger.info(f"Processing translate file: {translate_file}")

    # File processing
    repo = DatabaseRepository()
    processed_count = repo.process_translate_file(translate_file)

    logger.info(f"Processed {processed_count} translations")


def process_phrasal_verb_file(args: argparse.Namespace) -> None:
    """
    Processes a file with phrasal verbs.

    Args:
        args (argparse.Namespace): command line arguments.
    """
    phrasal_verb_file = args.file

    logger.info(f"Processing phrasal verb file: {phrasal_verb_file}")

    # File processing
    repo = DatabaseRepository()
    processed_count = repo.process_phrasal_verb_file(phrasal_verb_file)

    logger.info(f"Processed {processed_count} phrasal verbs")


def fix_listening_field(args: argparse.Namespace) -> None:
    """
    Fixes the listening field.

    Args:
        args (argparse.Namespace): Command line arguments.
    """
    logger.info("Fixing listening field")

    # Get words that need fixing
    repo = DatabaseRepository()
    query = f"""
        SELECT english_word FROM {COLLECTIONS_TABLE}
        WHERE get_download = TRUE AND russian_word IS NOT NULL AND listening LIKE 'http%'
    """
    result = repo.execute_query(query, fetch=True)

    if not result:
        logger.info("No records need fixing")
        return

    # Fix listening field
    from app.audio.manager import AudioManager
    audio_manager = AudioManager()
    count = 0

    for row in result:
        english_word = row[0]
        listening = audio_manager.update_anki_field_format(english_word)

        update_query = f"""
            UPDATE {COLLECTIONS_TABLE}
            SET listening = %s
            WHERE english_word = %s
        """
        repo.execute_query(update_query, (listening, english_word))
        count += 1

    logger.info(f"Fixed listening field for {count} records")


def get_download_words(args: argparse.Namespace) -> None:
    """
    Gets a list of words for download.

    Args:
        args (argparse.Namespace): Command line arguments.
    """
    pattern = args.pattern
    output_file = args.output

    logger.info("Getting words for download")

    # Form query
    query = f"""
        SELECT english_word FROM {COLLECTIONS_TABLE}
        WHERE russian_word IS NOT NULL AND get_download = FALSE
    """

    if pattern:
        query += f" AND english_word LIKE '{pattern}'"

    # Execute query
    repo = DatabaseRepository()
    result = repo.execute_query(query, fetch=True)

    if not result:
        logger.info("No words found for download")
        return

    # Get list of words
    words = [row[0] for row in result]

    # Save to file if specified
    if output_file:
        try:
            with open(output_file, 'w', encoding='utf-8') as file:
                for word in words:
                    file.write(f"{word}\n")
            logger.info(f"Words saved to file: {output_file}")
        except Exception as e:
            logger.error(f"Error saving words to file: {e}")

    logger.info(f"Found {len(words)} words for download")


def update_word_status(args: argparse.Namespace) -> None:
    """
    Updates word learning status in the database.

    Args:
        args (argparse.Namespace): Command line arguments.
    """
    status = args.status
    word = args.word
    pattern = args.pattern
    file_path = args.file

    # Check status validity
    if status not in [Word.STATUS_NEW, Word.STATUS_STUDYING, Word.STATUS_STUDIED]:
        logger.error(f"Invalid status: {status}")
        logger.info(f"Available statuses: {Word.STATUS_LABELS}")
        return

    logger.info(f"Updating word status to: {status} ({Word.STATUS_LABELS[status]})")

    repo = DatabaseRepository()

    # Check and update database schema
    repo.update_schema_if_needed()

    if word:
        # Update status for one word
        if repo.update_word_status_by_english(word, status):
            logger.info(f"Updated status for word '{word}' to {Word.STATUS_LABELS[status]}")
        else:
            logger.error(f"Failed to update status for word '{word}'")

    elif file_path:
        # Update status for words from file
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                words = [line.strip() for line in file if line.strip()]

            if not words:
                logger.warning("No words found in the file")
                return

            updated_count = repo.batch_update_word_status(words, status)
            logger.info(f"Updated status for {updated_count}/{len(words)} words to {Word.STATUS_LABELS[status]}")

        except Exception as e:
            logger.error(f"Error processing file: {e}")

    elif pattern:
        # Update status for words matching pattern
        query = f"""
            SELECT english_word FROM {COLLECTIONS_TABLE}
            WHERE english_word LIKE '{pattern}'
        """
        result = repo.execute_query(query, fetch=True)

        if not result:
            logger.warning(f"No words found matching pattern: {pattern}")
            return

        words = [row[0] for row in result]
        updated_count = repo.batch_update_word_status(words, status)
        logger.info(f"Updated status for {updated_count}/{len(words)} words to {Word.STATUS_LABELS[status]}")

    else:
        logger.error("Please specify a word, file, or pattern")


def list_words_by_status(args: argparse.Namespace) -> None:
    """
    Lists words with specified learning status.

    Args:
        args (argparse.Namespace): Command line arguments.
    """
    status = args.status
    output_file = args.output

    # Check status validity
    if status is not None and status not in [Word.STATUS_NEW, Word.STATUS_STUDYING, Word.STATUS_STUDIED]:
        logger.error(f"Invalid status: {status}")
        logger.info(f"Available statuses: {Word.STATUS_LABELS}")
        return

    status_label = Word.STATUS_LABELS.get(status, "All") if status is not None else "All"
    logger.info(f"Listing words with status: {status_label}")

    repo = DatabaseRepository()

    # Check and update database schema
    repo.update_schema_if_needed()

    if status is not None:
        words = repo.get_words_by_status(status)
    else:
        # Get all words grouped by status
        query = "SELECT * FROM collection_words ORDER BY learning_status, english_word"
        result = repo.execute_query(query, fetch=True)

        if not result:
            logger.warning("No words found")
            return

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

    if not words:
        logger.warning(f"No words found with status: {status_label}")
        return

    # Group words by status for clear output
    words_by_status = {}
    for word in words:
        status_label = word.get_status_label()
        if status_label not in words_by_status:
            words_by_status[status_label] = []
        words_by_status[status_label].append(word.english_word)

    # Output words to screen or file
    output_lines = []
    for status_label, word_list in words_by_status.items():
        header = f"Status: {status_label} ({len(word_list)} words)"
        output_lines.append(header)
        output_lines.append("-" * len(header))

        for word in word_list:
            output_lines.append(word)

        output_lines.append("")  # Empty line between groups

    if output_file:
        try:
            with open(output_file, 'w', encoding='utf-8') as file:
                for line in output_lines:
                    file.write(f"{line}\n")
            logger.info(f"Word list saved to file: {output_file}")
        except Exception as e:
            logger.error(f"Error saving word list to file: {e}")
    else:
        # Output to screen
        for line in output_lines:
            print(line)

    logger.info(f"Total words: {len(words)}")


def show_status_statistics(args: argparse.Namespace) -> None:
    """
    Shows statistics on word learning statuses.

    Args:
        args (argparse.Namespace): Command line arguments.
    """
    logger.info("Collecting word status statistics")

    repo = DatabaseRepository()

    # Check and update database schema
    repo.update_schema_if_needed()

    # Query to count words by status
    query = """
        SELECT learning_status, COUNT(*) as count
        FROM collection_words
        GROUP BY learning_status
        ORDER BY learning_status
    """
    result = repo.execute_query(query, fetch=True)

    if not result:
        logger.warning("No words found in database")
        return

    # Prepare statistics
    total_words = 0
    status_counts = []

    for row in result:
        status = row[0]
        count = row[1]
        total_words += count

        status_label = Word.STATUS_LABELS.get(status, f"Unknown status ({status})")
        status_counts.append((status, status_label, count))

    # Output statistics
    print("\nWord Learning Status Statistics:")
    print("================================")

    for status, label, count in status_counts:
        percentage = (count / total_words) * 100 if total_words > 0 else 0
        print(f"{label}: {count} words ({percentage:.1f}%)")

    print(f"\nTotal words in database: {total_words}")

    if args.book:
        # Statistics for book
        query = f"""
            SELECT cw.learning_status, COUNT(*) as count
            FROM collection_words cw
            JOIN word_book_link wbl ON cw.id = wbl.word_id
            JOIN book b ON wbl.book_id = b.id
            WHERE b.title = %s
            GROUP BY cw.learning_status
            ORDER BY cw.learning_status
        """
        result = repo.execute_query(query, (args.book,), fetch=True)

        if not result:
            logger.warning(f"No words found for book: {args.book}")
            return

        # Prepare statistics for book
        book_total = 0
        book_status_counts = []

        for row in result:
            status = row[0]
            count = row[1]
            book_total += count

            status_label = Word.STATUS_LABELS.get(status, f"Unknown status ({status})")
            book_status_counts.append((status, status_label, count))

        # Output book statistics
        print(f"\nStats for book '{args.book}':")
        print("=" * (18 + len(args.book)))

        for status, label, count in book_status_counts:
            percentage = (count / book_total) * 100 if book_total > 0 else 0
            print(f"{label}: {count} words ({percentage:.1f}%)")

        print(f"\nTotal words in book: {book_total}")


def update_book_statistics(args: argparse.Namespace) -> None:
    """
    Updates statistics for existing books based on word links.

    Args:
        args (argparse.Namespace): Command line arguments.
    """
    book_id = args.book_id

    logger.info("Updating book statistics based on word links")

    repo = DatabaseRepository()

    try:
        if book_id:
            # Update statistics for a specific book
            query = """
                SELECT b.id, b.title, 
                       COUNT(DISTINCT wbl.word_id) as unique_words,
                       SUM(wbl.frequency) as total_words
                FROM book b
                LEFT JOIN word_book_link wbl ON b.id = wbl.book_id
                WHERE b.id = %s
                GROUP BY b.id
            """
            result = repo.execute_query(query, (book_id,), fetch=True)

            if not result or not result[0]:
                logger.error(f"Book with ID {book_id} not found")
                return

            book_data = result[0]
            book_id, title, unique_words, total_words = book_data

            if repo.update_book_stats(book_id, total_words or 0, unique_words or 0):
                logger.info(f"Updated stats for book '{title}': {total_words} total words, {unique_words} unique words")
            else:
                logger.error(f"Failed to update stats for book '{title}'")
        else:
            # Update statistics for all books
            query = """
                SELECT b.id, b.title, 
                       COUNT(DISTINCT wbl.word_id) as unique_words,
                       SUM(wbl.frequency) as total_words
                FROM book b
                LEFT JOIN word_book_link wbl ON b.id = wbl.book_id
                GROUP BY b.id
            """
            result = repo.execute_query(query, fetch=True)

            if not result:
                logger.info("No books found in database")
                return

            updated_count = 0
            for book_data in result:
                book_id, title, unique_words, total_words = book_data

                if repo.update_book_stats(book_id, total_words or 0, unique_words or 0):
                    updated_count += 1
                    logger.info(
                        f"Updated stats for book '{title}': {total_words} total words, {unique_words} unique words")

            logger.info(f"Successfully updated statistics for {updated_count} books")

    except Exception as e:
        logger.error(f"Error updating book statistics: {e}")


def main():
    """
    Main program function.
    """
    # Parse command line arguments
    args = parse_arguments()

    # Set up logging
    setup_logging(args.log_level, args.log_file)

    # Execute command
    try:
        if args.command == "init":
            init_database(args)
        elif args.command == "scrape":
            scrape_website(args)
        elif args.command == "update-download":
            update_download_status(args)
        elif args.command == "process-translate":
            process_translate_file(args)
        elif args.command == "process-phrasal":
            process_phrasal_verb_file(args)
        elif args.command == "fix-listening":
            fix_listening_field(args)
        elif args.command == "get-download":
            get_download_words(args)
        elif args.command == "update-status":
            update_word_status(args)
        elif args.command == "list-words":
            list_words_by_status(args)
        elif args.command == "status-stats":
            show_status_statistics(args)
        elif args.command == "update-book-stats":
            update_book_statistics(args)
        else:
            logger.error(f"Unknown command: {args.command}")
            return 1
    except Exception as e:
        logger.exception(f"Error executing command {args.command}: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())