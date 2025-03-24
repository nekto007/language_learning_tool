"""
Определение моделей базы данных и схемы таблиц.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Dict, Optional

logger = logging.getLogger(__name__)


class DBInitializer:
    """Класс для инициализации и обновления схемы базы данных."""

    # SQL для создания основных таблиц
    CREATE_TABLES_SQL: ClassVar[str] = """
        -- Таблица книг
        CREATE TABLE IF NOT EXISTS book (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT UNIQUE NOT NULL,
            total_words INTEGER DEFAULT 0,
            unique_words INTEGER DEFAULT 0,
            scrape_date TIMESTAMP DEFAULT NULL
        );

        -- Таблица для слов
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
        );

        -- Таблица связи слов с книгами
        CREATE TABLE IF NOT EXISTS word_book_link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            frequency INTEGER DEFAULT 1,
            FOREIGN KEY (word_id) REFERENCES collection_words (id),
            FOREIGN KEY (book_id) REFERENCES book (id),
            UNIQUE (word_id, book_id)
        );

        -- Таблица фразовых глаголов
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
        );
        
        -- Создание индексов
        CREATE INDEX IF NOT EXISTS idx_collection_words_english_word ON collection_words(english_word);
        CREATE INDEX IF NOT EXISTS idx_collection_words_learning_status ON collection_words(learning_status);
        CREATE INDEX IF NOT EXISTS idx_word_book_link_word_id ON word_book_link(word_id);
        CREATE INDEX IF NOT EXISTS idx_word_book_link_book_id ON word_book_link(book_id);
    """

    # SQL для обновления статистики книг
    UPDATE_BOOK_STATS_SQL: ClassVar[str] = """
        WITH book_stats AS (
            SELECT
                b.id,
                SUM(wbl.frequency) AS total_words,
                COUNT(DISTINCT wbl.word_id) AS unique_words
            FROM book b
            LEFT JOIN word_book_link wbl ON b.id = wbl.book_id
            GROUP BY b.id
        )
        UPDATE book
        SET
            total_words = COALESCE((SELECT bs.total_words FROM book_stats bs WHERE bs.id = book.id), 0),
            unique_words = COALESCE((SELECT bs.unique_words FROM book_stats bs WHERE bs.id = book.id), 0),
            scrape_date = CURRENT_TIMESTAMP
        WHERE EXISTS (SELECT 1 FROM book_stats bs WHERE bs.id = book.id);
    """

    @staticmethod
    def create_tables(db_path: str) -> None:
        """
        Создает необходимые таблицы в базе данных, если они не существуют.

        Args:
            db_path: Путь к файлу базы данных.
        """
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()

                # Проверка версии схемы
                cursor.execute("PRAGMA user_version")
                current_version = cursor.fetchone()[0]
                logger.info(f"Current database schema version: {current_version}")

                # Создание таблиц
                cursor.executescript(DBInitializer.CREATE_TABLES_SQL)

                # Если это первичная инициализация, устанавливаем версию схемы
                if current_version == 0:
                    cursor.execute("PRAGMA user_version = 1")
                    logger.info("Database schema initialized to version 1")

                conn.commit()
                logger.info("Database tables created successfully")
        except sqlite3.Error as e:
            logger.error(f"Error creating database tables: {e}")
            raise

    @staticmethod
    def update_schema_if_needed(db_path: str) -> None:
        """
        Проверяет и обновляет схему базы данных при необходимости.

        Args:
            db_path: Путь к файлу базы данных.
        """
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()

                # Проверка версии схемы
                cursor.execute("PRAGMA user_version")
                current_version = cursor.fetchone()[0]

                # Применяем миграции в зависимости от текущей версии схемы
                if current_version < 1:
                    logger.info("Applying migration to version 1")
                    # Создание основных таблиц
                    cursor.executescript(DBInitializer.CREATE_TABLES_SQL)
                    cursor.execute("PRAGMA user_version = 1")

                if current_version < 2:
                    logger.info("Applying migration to version 2")
                    # Добавление поля learning_status, если его нет
                    cursor.execute("PRAGMA table_info(collection_words)")
                    columns = [column[1] for column in cursor.fetchall()]

                    if "learning_status" not in columns:
                        cursor.execute("ALTER TABLE collection_words ADD COLUMN learning_status INTEGER DEFAULT 0")
                        cursor.execute(
                            "CREATE INDEX IF NOT EXISTS idx_collection_words_learning_status ON "
                            "collection_words(learning_status)")

                    cursor.execute("PRAGMA user_version = 2")

                if current_version < 3:
                    logger.info("Applying migration to version 3")
                    # Добавление полей статистики книг, если их нет
                    cursor.execute("PRAGMA table_info(book)")
                    columns = [column[1] for column in cursor.fetchall()]

                    if "total_words" not in columns:
                        cursor.execute("ALTER TABLE book ADD COLUMN total_words INTEGER DEFAULT 0")

                    if "unique_words" not in columns:
                        cursor.execute("ALTER TABLE book ADD COLUMN unique_words INTEGER DEFAULT 0")

                    if "scrape_date" not in columns:
                        cursor.execute("ALTER TABLE book ADD COLUMN scrape_date TIMESTAMP DEFAULT NULL")

                    cursor.execute("PRAGMA user_version = 3")

                conn.commit()
                logger.info(f"Database schema updated to version {cursor.execute('PRAGMA user_version').fetchone()[0]}")

        except sqlite3.Error as e:
            logger.error(f"Error updating schema: {e}")
            raise

    @staticmethod
    def update_book_stats(db_path: str, book_id: Optional[int] = None) -> None:
        """
        Обновляет статистику для книг на основе связей с словами.

        Args:
            db_path: Путь к файлу базы данных.
            book_id: ID конкретной книги или None для всех книг.
        """
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()

                if book_id is not None:
                    # Обновление статистики для конкретной книги
                    cursor.execute("""
                        WITH book_stats AS (
                            SELECT
                                COUNT(DISTINCT wbl.word_id) as unique_words,
                                SUM(wbl.frequency) as total_words
                            FROM word_book_link wbl
                            WHERE wbl.book_id = ?
                        )
                        UPDATE book
                        SET
                            total_words = COALESCE((SELECT total_words FROM book_stats), 0),
                            unique_words = COALESCE((SELECT unique_words FROM book_stats), 0),
                            scrape_date = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (book_id, book_id))

                    rows_updated = cursor.rowcount
                    logger.info(f"Updated statistics for book ID {book_id}: {rows_updated} rows affected")

                else:
                    # Обновление статистики для всех книг
                    cursor.executescript(DBInitializer.UPDATE_BOOK_STATS_SQL)
                    logger.info("Updated statistics for all books")

                conn.commit()

        except sqlite3.Error as e:
            logger.error(f"Error updating book statistics: {e}")
            raise


@dataclass
class Book:
    """Модель книги."""

    title: str
    id: Optional[int] = None
    total_words: int = 0
    unique_words: int = 0
    scrape_date: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Book:
        """
        Создает объект Book из словаря.

        Args:
            data: Словарь с данными книги.

        Returns:
            Объект Book.
        """
        return cls(
            title=data['title'],
            id=data.get('id'),
            total_words=data.get('total_words', 0),
            unique_words=data.get('unique_words', 0),
            scrape_date=data.get('scrape_date')
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Преобразует объект Book в словарь.

        Returns:
            Словарь с данными книги.
        """
        result = {
            'title': self.title,
            'total_words': self.total_words,
            'unique_words': self.unique_words
        }
        if self.id is not None:
            result['id'] = self.id
        if self.scrape_date is not None:
            result['scrape_date'] = self.scrape_date
        return result


@dataclass
class Word:
    """Модель слова."""

    # Константы для статусов изучения
    STATUS_NEW: ClassVar[int] = 0  # Необработанное слово
    STATUS_STUDYING: ClassVar[int] = 1  # В процессе изучения
    STATUS_STUDIED: ClassVar[int] = 2  # Полностью изучено
    STATUS_ACTIVE: ClassVar[int] = 3  # Активное изучение (для совместимости)

    STATUS_LABELS: ClassVar[Dict[int, str]] = {
        STATUS_NEW: "New",
        STATUS_STUDYING: "Studying",
        STATUS_STUDIED: "Studied",
        STATUS_ACTIVE: "Active",
    }

    english_word: str
    listening: Optional[str] = None
    russian_word: Optional[str] = None
    sentences: Optional[str] = None
    level: Optional[str] = None
    brown: int = 0
    get_download: int = 0
    learning_status: int = field(default=STATUS_NEW)
    id: Optional[int] = None
    status: int = 0  # Статус для пользовательского контекста

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Word:
        """
        Создает объект Word из словаря.

        Args:
            data: Словарь с данными слова.

        Returns:
            Объект Word.
        """
        return cls(
            english_word=data['english_word'],
            listening=data.get('listening'),
            russian_word=data.get('russian_word'),
            sentences=data.get('sentences'),
            level=data.get('level'),
            brown=data.get('brown', 0),
            get_download=data.get('get_download', 0),
            learning_status=data.get('learning_status', Word.STATUS_NEW),
            id=data.get('id'),
            status=data.get('status', 0),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Преобразует объект Word в словарь.

        Returns:
            Словарь с данными слова.
        """
        result = {
            'english_word': self.english_word,
            'brown': self.brown,
            'get_download': self.get_download,
            'learning_status': self.learning_status,
            'status': self.status,
        }

        if self.id is not None:
            result['id'] = self.id
        if self.listening is not None:
            result['listening'] = self.listening
        if self.russian_word is not None:
            result['russian_word'] = self.russian_word
        if self.sentences is not None:
            result['sentences'] = self.sentences
        if self.level is not None:
            result['level'] = self.level

        return result

    def get_status_label(self) -> str:
        """
        Возвращает текстовую метку для статуса изучения.

        Returns:
            Метка статуса.
        """
        return self.STATUS_LABELS.get(self.learning_status, "Неизвестный статус")


@dataclass
class PhrasalVerb:
    """Модель фразового глагола."""

    phrasal_verb: str
    russian_translate: Optional[str] = None
    using: Optional[str] = None
    sentence: Optional[str] = None
    word_id: Optional[int] = None
    listening: Optional[str] = None
    get_download: int = 0
    id: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PhrasalVerb:
        """
        Создает объект PhrasalVerb из словаря.

        Args:
            data: Словарь с данными фразового глагола.

        Returns:
            Объект PhrasalVerb.
        """
        return cls(
            phrasal_verb=data['phrasal_verb'],
            russian_translate=data.get('russian_translate'),
            using=data.get('using'),
            sentence=data.get('sentence'),
            word_id=data.get('word_id'),
            listening=data.get('listening'),
            get_download=data.get('get_download', 0),
            id=data.get('id'),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Преобразует объект PhrasalVerb в словарь.

        Returns:
            Словарь с данными фразового глагола.
        """
        result = {
            'phrasal_verb': self.phrasal_verb,
            'get_download': self.get_download,
        }

        if self.id is not None:
            result['id'] = self.id
        if self.russian_translate is not None:
            result['russian_translate'] = self.russian_translate
        if self.using is not None:
            result['using'] = self.using
        if self.sentence is not None:
            result['sentence'] = self.sentence
        if self.word_id is not None:
            result['word_id'] = self.word_id
        if self.listening is not None:
            result['listening'] = self.listening

        return result
