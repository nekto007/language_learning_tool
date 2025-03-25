"""
Модели пользователей и схема таблиц пользователей.
"""
import hashlib
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional

from src.db.models import Word

logger = logging.getLogger(__name__)


class UserDBInitializer:
    """Класс для инициализации таблиц пользователей в базе данных."""

    # SQL для создания таблиц пользователей
    CREATE_TABLES_SQL = """
        -- Таблица пользователей
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            email TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        );

        -- Таблица статусов изучения слов для пользователей
        CREATE TABLE IF NOT EXISTS user_word_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            word_id INTEGER NOT NULL,
            status INTEGER NOT NULL DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (word_id) REFERENCES collection_words (id),
            UNIQUE (user_id, word_id)
        );
        
        -- Создание индексов
        CREATE INDEX IF NOT EXISTS idx_user_word_status ON user_word_status(user_id, word_id);
        CREATE INDEX IF NOT EXISTS idx_user_word_status_status ON user_word_status(user_id, status);
    """

    @staticmethod
    def initialize_schema(db_path: str) -> None:
        """
        Инициализирует схему таблиц пользователей в базе данных.

        Args:
            db_path (str): Путь к файлу базы данных.
        """
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()

                # Проверка существования таблицы пользователей
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
                if not cursor.fetchone():
                    logger.info("Creating user tables")
                    cursor.executescript(UserDBInitializer.CREATE_TABLES_SQL)
                    logger.info("User tables created successfully")
                else:
                    logger.info("User tables already exist")

                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error initializing user schema: {e}")
            raise

    @staticmethod
    def update_schema_if_needed(db_path: str) -> None:
        """
        Проверяет и обновляет схему таблиц пользователей при необходимости.

        Args:
            db_path (str): Путь к файлу базы данных.
        """
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()

                # Проверка существования таблицы пользователей
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
                if not cursor.fetchone():
                    logger.info("Creating user tables")
                    cursor.executescript(UserDBInitializer.CREATE_TABLES_SQL)
                else:
                    # Проверка наличия необходимых колонок

                    # Проверка salt в таблице users
                    cursor.execute("PRAGMA table_info(users)")
                    user_columns = [column[1] for column in cursor.fetchall()]

                    if "salt" not in user_columns:
                        logger.info("Adding salt column to users table")
                        cursor.execute("ALTER TABLE users ADD COLUMN salt TEXT DEFAULT ''")

                    # Проверка и обновление индексов
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_user_word_status'")
                    if not cursor.fetchone():
                        logger.info("Creating index idx_user_word_status")
                        cursor.execute("CREATE INDEX idx_user_word_status ON user_word_status(user_id, word_id)")

                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_user_word_status_status'")
                    if not cursor.fetchone():
                        logger.info("Creating index idx_user_word_status_status")
                        cursor.execute("CREATE INDEX idx_user_word_status_status ON user_word_status(user_id, status)")

                conn.commit()
                logger.info("User tables schema updated successfully")
        except sqlite3.Error as e:
            logger.error(f"Error updating user schema: {e}")
            raise

    @staticmethod
    def get_user_statistics(db_path: str, user_id: int) -> Dict[int, int]:
        """
        Получает статистику по статусам изучения слов для пользователя.

        Args:
            db_path (str): Путь к файлу базы данных.
            user_id (int): ID пользователя.

        Returns:
            Dict[int, int]: Словарь {статус: количество слов}.
        """
        stats = {
            Word.STATUS_NEW: 0,
            Word.STATUS_STUDYING: 0,
            Word.STATUS_STUDIED: 0,
        }

        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()

                # Статистика по словам с явным статусом
                cursor.execute("""
                    SELECT status, COUNT(*) as count
                    FROM user_word_status
                    WHERE user_id = ?
                    GROUP BY status
                """, (user_id,))

                for row in cursor.fetchall():
                    status, count = row
                    stats[status] = count

                # Подсчет слов без статуса (считаются как новые)
                cursor.execute("SELECT COUNT(*) FROM collection_words")
                total_words = cursor.fetchone()[0]

                cursor.execute("""
                    SELECT COUNT(DISTINCT word_id) 
                    FROM user_word_status 
                    WHERE user_id = ?
                """, (user_id,))

                words_with_status = cursor.fetchone()[0]
                stats[Word.STATUS_NEW] += total_words - words_with_status

                return stats
        except sqlite3.Error as e:
            logger.error(f"Error getting user statistics: {e}")
            return stats


class User:
    """Модель пользователя для аутентификации и идентификации."""

    def __init__(
            self,
            username: str,
            password_hash: Optional[str] = None,
            salt: Optional[str] = None,
            email: Optional[str] = None,
            created_at: Optional[datetime] = None,
            last_login: Optional[datetime] = None,
            user_id: Optional[int] = None,
            is_admin: bool = False,
    ):
        """
        Инициализация объекта User.

        Args:
            username (str): Имя пользователя
            password_hash (Optional[str], optional): Хеш пароля. По умолчанию None.
            salt (Optional[str], optional): Соль для хеширования. По умолчанию None.
            email (Optional[str], optional): Email пользователя. По умолчанию None.
            created_at (Optional[datetime], optional): Дата создания аккаунта. По умолчанию None.
            last_login (Optional[datetime], optional): Дата последнего входа. По умолчанию None.
            user_id (Optional[int], optional): ID пользователя. По умолчанию None.
        """
        self.id = user_id
        self.username = username
        self.password_hash = password_hash
        self.salt = salt
        self.email = email
        self.created_at = created_at
        self.last_login = last_login
        self.is_admin = is_admin

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'User':
        """
        Создает объект User из словаря.

        Args:
            data (Dict[str, Any]): Словарь с данными пользователя.

        Returns:
            User: Объект User.
        """
        return cls(
            username=data['username'],
            password_hash=data.get('password_hash'),
            salt=data.get('salt'),
            email=data.get('email'),
            created_at=data.get('created_at'),
            last_login=data.get('last_login'),
            user_id=data.get('id'),
            is_admin=bool(data.get('is_admin', 0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Преобразует объект User в словарь.

        Returns:
            Dict[str, Any]: Словарь с данными пользователя.
        """
        result = {'username': self.username}

        if self.id is not None:
            result['id'] = self.id
        if self.password_hash is not None:
            result['password_hash'] = self.password_hash
        if self.salt is not None:
            result['salt'] = self.salt
        if self.email is not None:
            result['email'] = self.email
        if self.created_at is not None:
            result['created_at'] = self.created_at
        if self.last_login is not None:
            result['last_login'] = self.last_login
        if hasattr(self, 'is_admin'):
            result['is_admin'] = self.is_admin

        return result

    @staticmethod
    def hash_password(password: str, salt: Optional[str] = None) -> tuple:
        """
        Хеширует пароль с солью, используя SHA-256.

        Args:
            password (str): Пароль в виде текста
            salt (Optional[str], optional): Соль для хеширования. Если None, генерируется новая.

        Returns:
            tuple: (хешированный_пароль, соль)
        """
        if salt is None:
            salt = os.urandom(32).hex()

        pw_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return pw_hash, salt

    def verify_password(self, password: str, salt: str) -> bool:
        """
        Проверяет пароль сравнивая с хешем.

        Args:
            password (str): Проверяемый пароль
            salt (str): Соль, использованная для хеширования

        Returns:
            bool: True если пароль совпадает, иначе False
        """
        pw_hash, _ = self.hash_password(password, salt)
        return pw_hash == self.password_hash


class UserWordStatus:
    """Модель для отслеживания статуса изучения слова пользователем."""

    def __init__(
            self,
            user_id: int,
            word_id: int,
            status: int = 0,
            last_updated: Optional[datetime] = None,
            status_id: Optional[int] = None,
    ):
        """
        Инициализация объекта UserWordStatus.

        Args:
            user_id (int): ID пользователя
            word_id (int): ID слова
            status (int, optional): Статус изучения. По умолчанию 0.
            last_updated (Optional[datetime], optional): Дата обновления. По умолчанию None.
            status_id (Optional[int], optional): ID записи статуса. По умолчанию None.
        """
        self.id = status_id
        self.user_id = user_id
        self.word_id = word_id
        self.status = status
        self.last_updated = last_updated or datetime.now()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UserWordStatus':
        """
        Создает объект UserWordStatus из словаря.

        Args:
            data (Dict[str, Any]): Словарь с данными статуса.

        Returns:
            UserWordStatus: Объект UserWordStatus.
        """
        return cls(
            user_id=data['user_id'],
            word_id=data['word_id'],
            status=data.get('status', 0),
            last_updated=data.get('last_updated'),
            status_id=data.get('id'),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Преобразует объект UserWordStatus в словарь.

        Returns:
            Dict[str, Any]: Словарь с данными статуса.
        """
        result = {
            'user_id': self.user_id,
            'word_id': self.word_id,
            'status': self.status,
        }

        if self.id is not None:
            result['id'] = self.id
        if self.last_updated is not None:
            result['last_updated'] = self.last_updated

        return result
