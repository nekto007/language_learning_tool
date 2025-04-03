/*
Выполните этот SQL-скрипт для добавления необходимых таблиц и полей
в базу данных для поддержки функциональности чтения.

Этот файл предоставлен только для справки и должен выполняться
с помощью инструмента миграции базы данных или вручную.
*/

-- Добавляем поле content в таблицу book, если его еще нет
ALTER TABLE book ADD COLUMN IF NOT EXISTS content TEXT;

-- Создаем таблицу reading_progress, если ее еще нет
CREATE TABLE IF NOT EXISTS reading_progress (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id INTEGER NOT NULL REFERENCES book(id) ON DELETE CASCADE,
    position INTEGER DEFAULT 0,
    last_read TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    CONSTRAINT uix_user_book_progress UNIQUE (user_id, book_id)
);

-- Создаем индексы для таблицы reading_progress, если их еще нет
CREATE INDEX IF NOT EXISTS idx_reading_progress_user ON reading_progress (user_id);
CREATE INDEX IF NOT EXISTS idx_reading_progress_book ON reading_progress (book_id);