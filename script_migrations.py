"""
Скрипт для выполнения миграции таблицы collections_word в collection_words
и добавления полей created_at, updated_at.
"""
import logging
import os
import sqlite3
from datetime import datetime
import traceback

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger()


def execute_migration(db_path):
    """
    Выполняет миграцию таблицы collections_word в collection_words и
    добавляет поля created_at и updated_at.

    Args:
        db_path: путь к файлу базы данных

    Returns:
        bool: True, если миграция успешна, False в случае ошибки
    """
    conn = None
    try:
        logger.info(f"Starting migration for database: {db_path}")

        # Проверка существования файла БД
        if not os.path.exists(db_path):
            logger.error(f"Database file not found: {db_path}")
            return False

        # Подключение к БД
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # ВАЖНО: Проверяем точные имена таблиц в базе данных
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        all_tables = [table[0] for table in cursor.fetchall()]
        logger.info(f"All tables in database: {all_tables}")

        # Проверка необходимости миграции - используем правильные имена таблиц
        old_table = "collections_word"  # Это исходная таблица
        new_table = "collection_words"  # Это целевая таблица

        old_table_exists = old_table in all_tables
        new_table_exists = new_table in all_tables

        logger.info(f"Old table '{old_table}' exists: {old_table_exists}")
        logger.info(f"New table '{new_table}' exists: {new_table_exists}")

        if not old_table_exists and not new_table_exists:
            logger.info("Neither old nor new table exists. No migration needed.")
            return True

        if not old_table_exists and new_table_exists:
            logger.info("New table already exists. Checking columns...")

            # Проверяем наличие столбцов created_at и updated_at
            cursor.execute(f"PRAGMA table_info({new_table})")
            columns = [column[1] for column in cursor.fetchall()]

            columns_to_add = []
            if "created_at" not in columns:
                columns_to_add.append("created_at")
            if "updated_at" not in columns:
                columns_to_add.append("updated_at")

            if not columns_to_add:
                logger.info("All required columns exist. No migration needed.")
                return True

            # Добавляем недостающие столбцы
            try:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Используем безопасный метод: сначала добавляем столбцы без DEFAULT, затем обновляем данные
                conn.execute("BEGIN TRANSACTION")
                for column in columns_to_add:
                    cursor.execute(f"ALTER TABLE {new_table} ADD COLUMN {column} DATETIME")
                    logger.info(f"Added column {column} to {new_table}")

                # Обновляем все записи текущей датой
                if columns_to_add:
                    update_parts = [f"{col} = '{current_time}'" for col in columns_to_add]
                    cursor.execute(f"UPDATE {new_table} SET {', '.join(update_parts)}")
                    logger.info(f"Updated {cursor.rowcount} rows with timestamps")

                conn.commit()
                logger.info("Successfully added missing timestamp columns")
                return True
            except Exception as e:
                conn.rollback()
                logger.error(f"Error adding columns: {e}")
                logger.error(traceback.format_exc())
                return False

        if old_table_exists and new_table_exists:
            logger.warning(f"Both old table '{old_table}' and new table '{new_table}' exist. Inconsistent state.")
            return False

        # Если мы здесь, значит нужно выполнить полную миграцию
        logger.info(f"Starting full migration from {old_table} to {new_table}")

        try:
            # Выводим структуру существующей таблицы для отладки
            cursor.execute(f"PRAGMA table_info({old_table})")
            columns_info = cursor.fetchall()
            column_names = [col[1] for col in columns_info]
            logger.info(f"Current {old_table} columns: {column_names}")

            # Начинаем транзакцию
            conn.execute("BEGIN TRANSACTION")

            # 1. Создаем новую таблицу со всеми нужными столбцами
            cursor.execute(f"""
                CREATE TABLE {new_table} (
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

            # 2. Копируем данные - исправляем ошибку с несоответствием столбцов
            if "learning_status" in column_names:
                # Если в старой таблице есть learning_status
                cursor.execute(f"""
                    INSERT INTO {new_table} (
                        id, english_word, russian_word, listening, sentences, level, brown, get_download, learning_status
                    )
                    SELECT 
                        id, english_word, russian_word, listening, sentences, level, brown, get_download, learning_status
                    FROM {old_table}
                """)
            else:
                # Если в старой таблице нет learning_status, устанавливаем значение по умолчанию
                cursor.execute(f"""
                    INSERT INTO {new_table} (
                        id, english_word, russian_word, listening, sentences, level, brown, get_download, learning_status
                    )
                    SELECT 
                        id, english_word, russian_word, listening, sentences, level, brown, get_download, 0
                    FROM {old_table}
                """)

            rows_copied = cursor.rowcount
            logger.info(f"Copied {rows_copied} rows to new table")

            # 3. Создаем индексы
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_collection_words_english_word ON {new_table}(english_word)")
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_collection_words_learning_status ON {new_table}(learning_status)")

            # 4. Обновляем связанные таблицы
            # 4.1 Проверяем и обновляем word_book_link
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='word_book_link'")
            if cursor.fetchone():
                cursor.execute("""
                    CREATE TABLE word_book_link_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        word_id INTEGER NOT NULL,
                        book_id INTEGER NOT NULL,
                        frequency INTEGER DEFAULT 1,
                        FOREIGN KEY (word_id) REFERENCES collection_words (id),
                        FOREIGN KEY (book_id) REFERENCES book (id),
                        UNIQUE (word_id, book_id)
                    )
                """)

                cursor.execute("INSERT INTO word_book_link_new SELECT * FROM word_book_link")
                cursor.execute("DROP TABLE word_book_link")
                cursor.execute("ALTER TABLE word_book_link_new RENAME TO word_book_link")

                # Восстанавливаем индексы
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_word_book_link_word_id ON word_book_link(word_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_word_book_link_book_id ON word_book_link(book_id)")

            # 4.2 Проверяем и обновляем phrasal_verb
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='phrasal_verb'")
            if cursor.fetchone():
                cursor.execute("""
                    CREATE TABLE phrasal_verb_new (
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

                cursor.execute("INSERT INTO phrasal_verb_new SELECT * FROM phrasal_verb")
                cursor.execute("DROP TABLE phrasal_verb")
                cursor.execute("ALTER TABLE phrasal_verb_new RENAME TO phrasal_verb")

            # 4.3 Проверяем и обновляем user_word_status
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_word_status'")
            if cursor.fetchone():
                cursor.execute("""
                    CREATE TABLE user_word_status_new (
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

                cursor.execute("INSERT INTO user_word_status_new SELECT * FROM user_word_status")
                cursor.execute("DROP TABLE user_word_status")
                cursor.execute("ALTER TABLE user_word_status_new RENAME TO user_word_status")

                # Восстанавливаем индексы
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_word_status ON user_word_status(user_id, word_id)")
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_user_word_status_status ON user_word_status(user_id, status)")

            # 4.4 Проверяем и обновляем deck_card
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='deck_card'")
            if cursor.fetchone():
                # Определяем структуру таблицы deck_card
                cursor.execute("PRAGMA table_info(deck_card)")
                columns = [column[1] for column in cursor.fetchall()]

                # Готовим список столбцов для новой таблицы
                column_defs = []
                column_list = []

                # Базовые столбцы, которые должны быть
                column_defs.append("id INTEGER PRIMARY KEY AUTOINCREMENT")
                column_defs.append("deck_id INTEGER NOT NULL")
                column_defs.append("word_id INTEGER NOT NULL")
                column_list.append("id")
                column_list.append("deck_id")
                column_list.append("word_id")

                # Дополнительные столбцы, которые могут быть
                optional_columns = [
                    "next_review_date", "last_review_date", "interval",
                    "repetitions", "ease_factor", "lapses",
                    "created_at", "updated_at"
                ]

                for col in optional_columns:
                    if col in columns:
                        column_type = "DATE" if "date" in col else "INTEGER" if col in ["interval", "repetitions",
                                                                                        "lapses"] else "REAL" if col == "ease_factor" else "DATETIME"
                        default = ""
                        if col == "interval" or col == "repetitions" or col == "lapses":
                            default = "DEFAULT 0"
                        elif col == "ease_factor":
                            default = "DEFAULT 2.5"

                        column_defs.append(f"{col} {column_type} {default}")
                        column_list.append(col)

                # Добавляем внешние ключи и ограничения уникальности
                column_defs.append("FOREIGN KEY (deck_id) REFERENCES deck (id)")
                column_defs.append("FOREIGN KEY (word_id) REFERENCES collection_words (id)")
                column_defs.append("UNIQUE (deck_id, word_id)")

                # Создаем новую таблицу
                create_table_sql = f"""
                CREATE TABLE deck_card_new (
                    {','.join(column_defs)}
                )
                """
                cursor.execute(create_table_sql)

                # Копируем данные
                column_list_str = ','.join(column_list)
                cursor.execute(f"INSERT INTO deck_card_new ({column_list_str}) SELECT {column_list_str} FROM deck_card")

                # Заменяем таблицу
                cursor.execute("DROP TABLE deck_card")
                cursor.execute("ALTER TABLE deck_card_new RENAME TO deck_card")

                # Создаем индексы
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_deck_card_deck_id ON deck_card(deck_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_deck_card_word_id ON deck_card(word_id)")
                if "next_review_date" in columns:
                    cursor.execute(
                        "CREATE INDEX IF NOT EXISTS idx_deck_card_next_review ON deck_card(next_review_date)")

            # 5. Удаляем старую таблицу
            cursor.execute(f"DROP TABLE {old_table}")

            # 6. Обновляем версию схемы
            cursor.execute("PRAGMA user_version")
            current_version = cursor.fetchone()[0]
            cursor.execute(f"PRAGMA user_version = {current_version + 1}")

            conn.commit()
            logger.info("Migration completed successfully!")
            return True

        except Exception as e:
            conn.rollback()
            error_msg = str(e)
            logger.error(f"Error during migration: {error_msg}")
            logger.error(traceback.format_exc())
            return False

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Unexpected error: {error_msg}")
        logger.error(traceback.format_exc())
        return False
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        database_path = sys.argv[1]
        result = execute_migration(database_path)
        if result:
            print("Migration completed successfully!")
            sys.exit(0)
        else:
            print("Migration failed! Check the log for details.")
            sys.exit(1)
    else:
        print("Usage: python script_migrations.py <path_to_database>")
        sys.exit(1)