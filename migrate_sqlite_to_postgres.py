import sqlite3
import psycopg2  # Драйвер для PostgreSQL

# Параметры подключения к PostgreSQL
PG_PARAMS = {
    "dbname": "language_learning_tool",  # Имя вашей базы данных
    "user": "appuser",  # Имя пользователя
    "password": "apppassword",  # Пароль
    "host": "localhost",  # Хост
    "port": "5432"  # Порт, обычно 5432 для PostgreSQL
}

# Подключаемся к SQLite базе (исходная)
sqlite_conn = sqlite3.connect('words.db')
sqlite_cursor = sqlite_conn.cursor()

# Подключаемся к PostgreSQL базе (назначение)
pg_conn = psycopg2.connect(**PG_PARAMS)
pg_cursor = pg_conn.cursor()

try:
    # Получаем данные из SQLite
    sqlite_cursor.execute("SELECT english_word, russian_word, listening, sentences, level FROM collection_words")
    data = sqlite_cursor.fetchall()

    print(f"Found {len(data)} records to transfer")

    # Счетчики для статистики
    updated = 0
    errors = 0

    # Обновляем данные в PostgreSQL
    for english_word, russian_word, listening, sentences, level in data:
        # print(english_word, russian_word, listening, sentences, level)
        try:
            pg_cursor.execute("""
                UPDATE collection_words
                SET russian_word = %s, listening = %s, sentences = %s, level = %s
                WHERE english_word = %s
            """, (russian_word, listening, sentences, level, english_word))

            # Если запись была обновлена (affected rows > 0)
            if pg_cursor.rowcount > 0:
                updated += 1
                print(f"Updated: {english_word} -> {russian_word}")
            # else:
                # print(f"Warning: Word '{english_word}' not found in target database")

        except Exception as row_error:
            errors += 1
            print(f"Error updating {english_word}: {row_error}")

    # Фиксируем изменения
    pg_conn.commit()
    print("\n===== Transfer Summary =====")
    print(f"Total records processed: {len(data)}")
    print(f"Successfully updated: {updated}")
    print(f"Errors: {errors}")
    print("============================")

except Exception as e:
    # Откатываем изменения в случае ошибки
    pg_conn.rollback()
    print(f"Error occurred: {e}")

finally:
    # Закрываем соединения
    sqlite_conn.close()
    pg_conn.close()
    print("Database connections closed")
