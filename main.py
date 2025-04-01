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
    COLLECTIONS_TABLE, DB_FILE, MAX_PAGES, MEDIA_FOLDER, PHRASAL_VERB_FILE, PHRASAL_VERB_TABLE, TRANSLATE_FILE
)
from app.words.models import CollectionWords as Word
from app.books.models import Book
from app.utils.helpers import setup_logging, create_backup
from app.nlp.setup import download_nltk_resources, initialize_nltk
from app.nlp.processor import prepare_word_data
from app.web.scraper import WebScraper
from app.repository import DatabaseRepository
# from src.audio.forvo_api import ForvoAPIClient
# from src.audio.forvo_downloader import ForvoDownloader
# from src.audio.manager import AudioManager
# from src.db.models import DBInitializer
# from src.db.repository import DatabaseRepository
# from src.web.scraper import WebScraper

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

    # Command to download pronunciations from Forvo
    forvo_parser = subparsers.add_parser("forvo-download", help="Download pronunciations from Forvo")
    forvo_parser.add_argument("--file", required=True, help="File with words or URLs")
    forvo_parser.add_argument("--words", action="store_true", help="File contains words instead of URLs")
    forvo_parser.add_argument("--browser", choices=["safari", "chrome", "firefox"],
                              default="safari", help="Browser to use")
    forvo_parser.add_argument("--delay", type=float, default=3.0,
                              help="Delay between opening URLs (seconds)")
    forvo_parser.add_argument("--max", type=int, default=100,
                              help="Maximum number of URLs to open")

    # Command to create a URL list for Forvo
    forvo_urls_parser = subparsers.add_parser("forvo-urls", help="Generate Forvo URLs from words")
    forvo_urls_parser.add_argument("--input", required=True, help="Input file with words")
    forvo_urls_parser.add_argument("--output", required=True, help="Output file for URLs")

    # Unified command to download pronunciations
    pronun_parser = subparsers.add_parser("download-pronunciations",
                                          help="Get words from database and download pronunciations from Forvo")
    pronun_parser.add_argument("--pattern", default=None, help="Filter pattern (e.g., 's%')")
    pronun_parser.add_argument("--browser", choices=["safari", "chrome", "firefox"],
                               default="safari", help="Browser to use")
    pronun_parser.add_argument("--delay", type=float, default=3.0,
                               help="Delay between opening URLs (seconds)")
    pronun_parser.add_argument("--max", type=int, default=100,
                               help="Maximum number of URLs to open")
    pronun_parser.add_argument("--use-file", action="store_true",
                               help="Use temporary file instead of direct API")
    pronun_parser.add_argument("--update-status", action="store_true",
                               help="Update download status after downloading")
    pronun_parser.add_argument("--update-delay", type=int, default=60,
                               help="Delay in seconds before updating download status")

    # Command to download pronunciations via API
    api_parser = subparsers.add_parser("api-download",
                                       help="Download pronunciations using Forvo API")
    api_parser.add_argument("--api-key", required=True, help="Forvo API key")
    api_parser.add_argument("--pattern", default=None, help="Filter pattern (e.g., 's%')")
    api_parser.add_argument("--language", default="en", help="Language code (default: en)")
    api_parser.add_argument("--format", choices=["mp3", "ogg"], default="mp3", help="Audio format")
    api_parser.add_argument("--skip-existing", action="store_true",
                            help="Skip words with existing pronunciation files")
    api_parser.add_argument("--update-status", action="store_true",
                            help="Update download status after downloading")

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
    parser.add_argument("--db", default=DB_FILE, help="Database file path")

    # Command to update book statistics
    update_stats_parser = subparsers.add_parser("update-book-stats",
                                                help="Update book statistics from word links")
    update_stats_parser.add_argument("--book-id", type=int, help="Update statistics for specific book ID")

    return parser.parse_args()


def init_database(args: argparse.Namespace) -> None:
    """
    Initializes the database.

    Args:
        args (argparse.Namespace): command line arguments.
    """
    db_path = args.db
    logger.info(f"Initializing database: {db_path}")

    # Create a backup if the database already exists
    if os.path.exists(db_path):
        backup_path = create_backup(db_path)
        if backup_path:
            logger.info(f"Created database backup: {backup_path}")

    # Initializing the main tables
    DBInitializer.create_tables(db_path)

    # Check and update the structure if necessary
    DBInitializer.update_schema_if_needed(db_path)

    # Initializing user tables
    from src.user.models import UserDBInitializer
    UserDBInitializer.initialize_schema(db_path)

    logger.info("Database initialized successfully")


def scrape_website(args: argparse.Namespace) -> None:
    """
    Scrapes a website and saves the words to a database.

    Args:
        args (argparse.Namespace): command line arguments.
    """
    url = args.url
    pages = min(args.pages, MAX_PAGES)  # Limit the number of pages
    book_title = args.book
    db_path = args.db

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
    repo = DatabaseRepository(db_path)
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
    db_path = args.db

    logger.info(f"Updating download status for table: {table_name}")

    # Define a column with a name depending on the table
    column_name = "english_word" if table_name == COLLECTIONS_TABLE else "phrasal_verb"

    # Status update
    repo = DatabaseRepository(db_path)
    updated_count = repo.update_download_status(table_name, column_name, MEDIA_FOLDER)

    logger.info(f"Updated download status for {updated_count} records")


def process_translate_file(args: argparse.Namespace) -> None:
    """
    Processes a file with translations.

    Args:
        args (argparse.Namespace): command line arguments.
    """
    translate_file = args.file
    db_path = args.db

    logger.info(f"Processing translate file: {translate_file}")

    # File processing
    repo = DatabaseRepository(db_path)
    processed_count = repo.process_translate_file(translate_file)

    logger.info(f"Processed {processed_count} translations")


def process_phrasal_verb_file(args: argparse.Namespace) -> None:
    """
    Processes a file with phrasal verbs.

    Args:
        args (argparse.Namespace): command line arguments.
    """
    phrasal_verb_file = args.file
    db_path = args.db

    logger.info(f"Processing phrasal verb file: {phrasal_verb_file}")

    # File processing
    repo = DatabaseRepository(db_path)
    processed_count = repo.process_phrasal_verb_file(phrasal_verb_file)

    logger.info(f"Processed {processed_count} phrasal verbs")


def fix_listening_field(args: argparse.Namespace) -> None:
    """
    Fixes the listening field.

    Args:
        args (argparse.Namespace): Command line arguments.
    """
    db_path = args.db

    logger.info("Fixing listening field")

    # Get words that need fixing
    repo = DatabaseRepository(db_path)
    query = f"""
        SELECT english_word FROM {COLLECTIONS_TABLE}
        WHERE get_download = 1 AND russian_word IS NOT NULL AND listening LIKE 'http%'
    """
    result = repo.execute_query(query, fetch=True)

    if not result:
        logger.info("No records need fixing")
        return

    # Fix listening field
    audio_manager = AudioManager()
    count = 0

    for row in result:
        english_word = row[0]
        listening = audio_manager.update_anki_field_format(english_word)

        update_query = f"""
            UPDATE {COLLECTIONS_TABLE}
            SET listening = ?
            WHERE english_word = ?
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
    db_path = args.db
    pattern = args.pattern
    output_file = args.output

    logger.info("Getting words for download")

    # Form query
    query = f"""
        SELECT english_word FROM {COLLECTIONS_TABLE}
        WHERE russian_word IS NOT NULL AND get_download = 0
    """

    if pattern:
        query += f" AND english_word LIKE '{pattern}'"

    # Execute query
    repo = DatabaseRepository(db_path)
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

    # Print list of words
    for word in words:
        print(word)

    logger.info(f"Found {len(words)} words for download")


def forvo_download(args: argparse.Namespace) -> None:
    """
    Downloads pronunciations from Forvo.

    Args:
        args (argparse.Namespace): Command line arguments.
    """
    file_path = args.file
    is_words = args.words
    browser = args.browser
    delay = args.delay
    max_urls = args.max

    logger.info(f"Downloading pronunciations from Forvo using {file_path}")

    # Create downloader
    downloader = ForvoDownloader(
        browser_name=browser,
        delay=delay,
        max_urls=max_urls,
    )

    # Download pronunciations
    if is_words:
        count = downloader.download_from_words_file(file_path)
    else:
        count = downloader.download_from_file(file_path)

    logger.info(f"Successfully opened {count} URLs")


def generate_forvo_urls(args: argparse.Namespace) -> None:
    """
    Generates Forvo URLs based on a list of words.

    Args:
        args (argparse.Namespace): Command line arguments.
    """
    input_file = args.input
    output_file = args.output

    logger.info(f"Generating Forvo URLs from words in {input_file}")

    # Create downloader
    downloader = ForvoDownloader()

    try:
        # Load words from file
        with open(input_file, 'r', encoding='utf-8') as file:
            words = [line.strip() for line in file if line.strip()]

        if not words:
            logger.warning("No words found in input file")
            return

        # Generate URLs
        urls = downloader.generate_urls_for_words(words)

        # Save URLs to file
        success = downloader.save_urls_to_file(urls, output_file)

        if success:
            logger.info(f"Generated and saved {len(urls)} URLs to {output_file}")
        else:
            logger.error("Failed to save URLs to file")

    except Exception as e:
        logger.error(f"Error generating Forvo URLs: {e}")


def download_pronunciations(args: argparse.Namespace) -> None:
    """
    Gets words from database and immediately downloads pronunciations for them from Forvo.

    Args:
        args (argparse.Namespace): Command line arguments.
    """
    db_path = args.db
    pattern = args.pattern
    use_temp_file = args.use_file
    browser = args.browser
    delay = args.delay
    max_urls = args.max

    logger.info("Getting words from database and downloading pronunciations")

    # Form query
    query = f"""
        SELECT english_word FROM {COLLECTIONS_TABLE}
        WHERE russian_word IS NULL AND get_download = 0
    """

    if pattern:
        query += f" AND english_word LIKE '{pattern}'"

    # Execute query
    repo = DatabaseRepository(db_path)
    result = repo.execute_query(query, fetch=True)

    if not result:
        logger.info("No words found for download")
        return

    # Get list of words
    words = [row[0] for row in result]
    logger.info(f"Found {len(words)} words for download")

    # Create downloader
    downloader = ForvoDownloader(
        browser_name=browser,
        delay=delay,
        max_urls=max_urls,
    )

    # Via temporary file or directly
    if use_temp_file:
        # Create temporary file
        import tempfile

        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False) as tmp:
            # Write words to temporary file
            for word in words:
                tmp.write(f"{word}\n")
            tmp_path = tmp.name

        try:
            # Download pronunciations from file
            count = downloader.download_from_words_file(tmp_path)
            logger.info(f"Successfully opened {count} URLs using temporary file")
        finally:
            # Delete temporary file
            import os
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    else:
        # Download pronunciations directly
        urls = downloader.generate_urls_for_words(words)
        count = downloader.download_from_urls(urls)
        logger.info(f"Successfully opened {count} URLs directly")

    # Update download status in database after delay
    if args.update_status and count > 0:
        logger.info(f"Waiting {args.update_delay} seconds before updating download status...")
        import time
        time.sleep(args.update_delay)

        updated_count = repo.update_download_status(COLLECTIONS_TABLE, "english_word", MEDIA_FOLDER)
        logger.info(f"Updated download status for {updated_count} words")


def download_pronunciations_api(args: argparse.Namespace) -> None:
    """
    Gets words from database and downloads pronunciations via Forvo API.

    Args:
        args (argparse.Namespace): Command line arguments.
    """
    db_path = args.db
    pattern = args.pattern
    api_key = args.api_key
    language = args.language
    format = args.format

    if not api_key:
        logger.error("API key is required")
        return

    logger.info("Getting words from database and downloading pronunciations via Forvo API")

    # Form query
    query = f"""
        SELECT english_word FROM {COLLECTIONS_TABLE}
        WHERE russian_word IS NULL AND get_download = 0
    """

    if pattern:
        query += f" AND english_word LIKE '{pattern}'"

    # Execute query
    repo = DatabaseRepository(db_path)
    result = repo.execute_query(query, fetch=True)

    if not result:
        logger.info("No words found for download")
        return

    # Get list of words
    words = [row[0] for row in result]
    logger.info(f"Found {len(words)} words for download")

    # Create API client
    client = ForvoAPIClient(
        api_key=api_key,
        language=language,
        format=format,
        media_folder=MEDIA_FOLDER,
    )

    # Filter words that already have pronunciations
    if args.skip_existing:
        missing_words = client.filter_missing_pronunciations(words)
        skipped_count = len(words) - len(missing_words)
        logger.info(f"Skipped {skipped_count} words with existing pronunciations")
        words = missing_words

    if not words:
        logger.info("No words need downloading")
        return

    # Download pronunciations
    results = client.download_pronunciations_batch(words)

    logger.info(f"Downloaded {len(results)}/{len(words)} pronunciations")

    # Update download status in database
    if args.update_status:
        updated_count = repo.update_download_status(COLLECTIONS_TABLE, "english_word", MEDIA_FOLDER)
        logger.info(f"Updated download status for {updated_count} words")

    # Output failed words
    failed_words = set(words) - set(results.keys())
    if failed_words:
        logger.warning("Failed to download pronunciations for the following words:")
        for word in failed_words:
            logger.warning(f"  - {word}")


def update_word_status(args: argparse.Namespace) -> None:
    """
    Updates word learning status in the database.

    Args:
        args (argparse.Namespace): Command line arguments.
    """
    db_path = args.db
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

    repo = DatabaseRepository(db_path)

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
    db_path = args.db
    status = args.status
    output_file = args.output

    # Check status validity
    if status is not None and status not in [Word.STATUS_NEW, Word.STATUS_KNOWN, Word.STATUS_QUEUED,
                                             Word.STATUS_ACTIVE, Word.STATUS_MASTERED]:
        logger.error(f"Invalid status: {status}")
        logger.info(f"Available statuses: {Word.STATUS_LABELS}")
        return

    status_label = Word.STATUS_LABELS.get(status, "All") if status is not None else "All"
    logger.info(f"Listing words with status: {status_label}")

    repo = DatabaseRepository(db_path)

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
    db_path = args.db

    logger.info("Collecting word status statistics")

    repo = DatabaseRepository(db_path)

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
            WHERE b.title = ?
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
    db_path = args.db
    book_id = args.book_id

    logger.info("Updating book statistics based on word links")

    repo = DatabaseRepository(db_path)

    try:
        if book_id:
            # Update statistics for a specific book
            query = """
                SELECT b.id, b.title, 
                       COUNT(DISTINCT wbl.word_id) as unique_words,
                       SUM(wbl.frequency) as total_words
                FROM book b
                LEFT JOIN word_book_link wbl ON b.id = wbl.book_id
                WHERE b.id = ?
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


@cli.command()
@click.option('--user-id', '-u', type=int, required=True, help='User ID')
@click.option('--name', '-n', required=True, help='Deck name')
@click.option('--description', '-d', default=None, help='Deck description')
def create_deck(user_id, name, description):
    """Create a new deck for a user."""
    from src.srs.service import SRSService

    srs_service = SRSService(DB_FILE)
    deck_id = srs_service.create_custom_deck(user_id, name, description)

    if deck_id:
        click.echo(f"Created deck '{name}' with ID {deck_id} for user {user_id}")
    else:
        click.echo("Failed to create deck")


@cli.command()
@click.option('--user-id', '-u', type=int, required=True, help='User ID')
def list_decks(user_id):
    """List all decks for a user."""
    from src.srs.service import SRSService

    srs_service = SRSService(DB_FILE)
    decks = srs_service.get_decks_with_stats(user_id)

    if not decks:
        click.echo(f"No decks found for user {user_id}")
        return

    click.echo(f"Decks for user {user_id}:")
    for deck in decks:
        click.echo(f"ID: {deck['id']}, Name: {deck['name']}")
        click.echo(f"  Total: {deck['total_cards']}, Due today: {deck['due_today']}, New: {deck['new_cards']}")
        if deck.get('description'):
            click.echo(f"  Description: {deck['description']}")
        click.echo()


@cli.command()
@click.option('--user-id', '-u', type=int, required=True, help='User ID')
@click.option('--deck-id', '-d', type=int, required=True, help='Deck ID')
@click.option('--word-id', '-w', type=int, required=True, help='Word ID')
def add_card(user_id, deck_id, word_id):
    """Add a word to a deck."""
    from src.srs.service import SRSService

    srs_service = SRSService(DB_FILE)

    # Verify deck belongs to user
    deck = srs_service.srs_repo.get_deck_by_id(deck_id)
    if not deck or deck.user_id != user_id:
        click.echo(f"Deck ID {deck_id} not found or does not belong to user {user_id}")
        return

    # Add word to deck
    card_id = srs_service.add_word_to_deck(user_id, word_id, deck_id)

    if card_id:
        click.echo(f"Added word {word_id} to deck {deck_id} (card ID: {card_id})")
    else:
        click.echo(f"Failed to add word {word_id} to deck {deck_id}")


@cli.command()
@click.option('--user-id', '-u', type=int, required=True, help='User ID')
@click.option('--from-status', '-f', type=int, required=True, help='Source status (0-4)')
@click.option('--to-status', '-t', type=int, required=True, help='Target status (0-4)')
def migrate_words(user_id, from_status, to_status):
    """Migrate words from one status to another and update SRS if needed."""
    from src.srs.service import SRSService

    if from_status not in range(0, 5) or to_status not in range(0, 5):
        click.echo("Status must be in range 0-4")
        return

    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Find all words with the source status
        cursor.execute(
            """
            SELECT word_id FROM user_word_status 
            WHERE user_id = ? AND status = ?
            """,
            (user_id, from_status)
        )

        word_ids = [row['word_id'] for row in cursor.fetchall()]

        if not word_ids:
            click.echo(f"No words found with status {from_status} for user {user_id}")
            return

        # Update status for each word
        user_repo = UserRepository(DB_FILE)
        srs_service = SRSService(DB_FILE)

        updated_count = 0
        for word_id in word_ids:
            if user_repo.set_word_status(user_id, word_id, to_status):
                # Handle SRS implications
                srs_service.handle_word_status_change(user_id, word_id, to_status)
                updated_count += 1

        click.echo(f"Updated {updated_count} of {len(word_ids)} words from status {from_status} to {to_status}")

    except sqlite3.Error as e:
        click.echo(f"Database error: {e}")
    finally:
        conn.close()


@cli.command()
def initialize_srs_schema():
    """Initialize the SRS database schema."""
    from src.srs import initialize_schema

    initialize_schema(DB_FILE)
    click.echo("SRS schema initialized")


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
            init_database(args.db)
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
        elif args.command == "forvo-download":
            forvo_download(args)
        elif args.command == "forvo-urls":
            generate_forvo_urls(args)
        elif args.command == "download-pronunciations":
            download_pronunciations(args)
        elif args.command == "api-download":
            download_pronunciations_api(args)
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
