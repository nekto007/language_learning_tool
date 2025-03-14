# Database Schema

Language Learning Tool uses SQLite for data storage. This document describes the database structure, tables, and their relationships.

## Contents

- [Database Diagram](#database-diagram)
- [Tables](#tables)
  - [collections_word](#collections_word)
  - [book](#book)
  - [word_book_link](#word_book_link)
  - [phrasal_verb](#phrasal_verb)
  - [users](#users)
  - [user_word_status](#user_word_status)
- [Indexes](#indexes)
- [Constraints](#constraints)
- [Migrations](#migrations)
- [SQL Queries](#sql-query-examples)

## Database Diagram

```
+-------------------+      +----------------+      +----------------+
|  collections_word |      | word_book_link |      |      book      |
+-------------------+      +----------------+      +----------------+
| id                |<--+  | id             |  +-->| id             |
| english_word      |   |  | word_id        |--+   | title          |
| russian_word      |   +--| book_id        |      | total_words    |
| listening         |      | frequency      |      | unique_words   |
| sentences         |      +----------------+      | scrape_date    |
| level             |                              +----------------+
| brown             |                                      ^
| get_download      |      +----------------+              |
| learning_status   |      | phrasal_verb   |              |
+-------------------+      +----------------+              |
        ^                  | id             |              |
        |                  | phrasal_verb   |              |
        |                  | russian_transl |              |
        +----------------->| using          |              |
                           | sentence       |              |
                           | word_id        |              |
                           | listening      |              |
                           | get_download   |              |
                           +----------------+              |
                                                           |
+-------------------+      +----------------+              |
|       users       |      | user_word_stat |              |
+-------------------+      +----------------+              |
| id                |<--+  | id             |              |
| username          |   |  | user_id        |--+           |
| password_hash     |   +--| word_id        |  |           |
| salt              |      | status         |  |           |
| email             |      | last_updated   |  |           |
| created_at        |      +----------------+  |           |
| last_login        |                          |           |
+-------------------+                          |           |
                                               v           |
                                      +-------------------+|
                                      |  collections_word |+
                                      +-------------------+
```

## Tables

### collections_word

Stores basic information about words.

| Field          | Type     | Description                     | Note                    |
|----------------|----------|---------------------------------|-------------------------|
| id             | INTEGER  | Primary key                     | AUTOINCREMENT           |
| english_word   | TEXT     | English word                    | UNIQUE, NOT NULL        |
| russian_word   | TEXT     | Russian translation             | Can be NULL             |
| listening      | TEXT     | Link to audio pronunciation     | Can be NULL             |
| sentences      | TEXT     | Example sentences               | Can be NULL             |
| level          | TEXT     | Difficulty level (A1, B2, etc.) | Can be NULL             |
| brown          | INTEGER  | Presence in Brown corpus (0/1)  | DEFAULT 0               |
| get_download   | INTEGER  | Audio file presence (0/1)       | DEFAULT 0               |
| learning_status| INTEGER  | Learning status                 | DEFAULT 0               |

### book

Stores information about books/sources.

| Field          | Type      | Description                  | Note                    |
|----------------|-----------|------------------------------|-------------------------|
| id             | INTEGER   | Primary key                  | AUTOINCREMENT           |
| title          | TEXT      | Book title                   | UNIQUE, NOT NULL        |
| total_words    | INTEGER   | Total word count             | DEFAULT 0               |
| unique_words   | INTEGER   | Unique word count            | DEFAULT 0               |
| scrape_date    | TIMESTAMP | Scraping date                | Can be NULL             |

### word_book_link

Links words with books and stores frequency information.

| Field          | Type     | Description                  | Note                     |
|----------------|----------|------------------------------|--------------------------|
| id             | INTEGER  | Primary key                  | AUTOINCREMENT            |
| word_id        | INTEGER  | Word ID                      | NOT NULL, FOREIGN KEY    |
| book_id        | INTEGER  | Book ID                      | NOT NULL, FOREIGN KEY    |
| frequency      | INTEGER  | Word frequency in the book   | DEFAULT 1                |

### phrasal_verb

Stores information about phrasal verbs.

| Field              | Type     | Description                  | Note                     |
|--------------------|----------|------------------------------|--------------------------|
| id                 | INTEGER  | Primary key                  | AUTOINCREMENT            |
| phrasal_verb       | TEXT     | Phrasal verb                 | UNIQUE, NOT NULL         |
| russian_translate  | TEXT     | Russian translation          | Can be NULL              |
| using              | TEXT     | Usage examples               | Can be NULL              |
| sentence           | TEXT     | Example sentences            | Can be NULL              |
| word_id            | INTEGER  | Base word ID                 | FOREIGN KEY              |
| listening          | TEXT     | Link to audio pronunciation  | Can be NULL              |
| get_download       | INTEGER  | Audio file presence (0/1)    | DEFAULT 0                |

### users

Stores information about users.

| Field          | Type      | Description                  | Note                     |
|----------------|-----------|------------------------------|--------------------------|
| id             | INTEGER   | Primary key                  | AUTOINCREMENT            |
| username       | TEXT      | Username                     | UNIQUE, NOT NULL         |
| password_hash  | TEXT      | Password hash                | NOT NULL                 |
| salt           | TEXT      | Salt for hashing             | NOT NULL                 |
| email          | TEXT      | Email address                | UNIQUE                   |
| created_at     | TIMESTAMP | Creation date                | DEFAULT CURRENT_TIMESTAMP|
| last_login     | TIMESTAMP | Last login date              | Can be NULL              |

### user_word_status

Stores learning status of words for each user.

| Field          | Type      | Description                  | Note                     |
|----------------|-----------|------------------------------|--------------------------|
| id             | INTEGER   | Primary key                  | AUTOINCREMENT            |
| user_id        | INTEGER   | User ID                      | NOT NULL, FOREIGN KEY    |
| word_id        | INTEGER   | Word ID                      | NOT NULL, FOREIGN KEY    |
| status         | INTEGER   | Learning status              | NOT NULL, DEFAULT 0      |
| last_updated   | TIMESTAMP | Update date                  | DEFAULT CURRENT_TIMESTAMP|

## Indexes

- `idx_collections_word_english_word` - index on `english_word` field in `collections_word` table
- `idx_collections_word_learning_status` - index on `learning_status` field in `collections_word` table
- `idx_user_word_status` - index on field pair `(user_id, word_id)` in `user_word_status` table
- `idx_user_word_status_status` - index on fields `(user_id, status)` in `user_word_status` table

## Constraints

- `UNIQUE (word_id, book_id)` in `word_book_link` table - prohibits duplication of word-book relationships
- `UNIQUE (user_id, word_id)` in `user_word_status` table - prohibits duplication of word statuses for users

## Migrations

When updating the database schema, migrations are used. Example migration to add the `learning_status` field:

```sql
-- update_schema.sql
ALTER TABLE collections_word ADD COLUMN learning_status INTEGER DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_collections_word_learning_status ON collections_word(learning_status);
PRAGMA user_version = 2;  -- Increment schema version
```

Applying migration:

```bash
sqlite3 your_database.db < update_schema.sql
```

## SQL Query Examples

### Getting words with translation, sorted by status for a user

```sql
SELECT cw.*, COALESCE(uws.status, 0) as status
FROM collections_word cw
LEFT JOIN user_word_status uws ON cw.id = uws.word_id AND uws.user_id = ?
WHERE cw.russian_word IS NOT NULL
ORDER BY COALESCE(uws.status, 0), cw.english_word
```

### Getting words from a book by frequency

```sql
SELECT cw.*, wbl.frequency
FROM collections_word cw
JOIN word_book_link wbl ON cw.id = wbl.word_id
WHERE wbl.book_id = ?
ORDER BY wbl.frequency DESC
```

### Word statistics by status for a user

```sql
SELECT COALESCE(uws.status, 0) as status, COUNT(*) as count
FROM collections_word cw
LEFT JOIN user_word_status uws ON cw.id = uws.word_id AND uws.user_id = ?
GROUP BY COALESCE(uws.status, 0)
```

### Updating book statistics

```sql
WITH book_stats AS (
  SELECT
    SUM(wbl.frequency) AS total_words,
    COUNT(DISTINCT wbl.word_id) AS unique_words
  FROM word_book_link wbl
  WHERE wbl.book_id = ?
)
UPDATE book
SET
  total_words = (SELECT total_words FROM book_stats),
  unique_words = (SELECT unique_words FROM book_stats),
  scrape_date = CURRENT_TIMESTAMP
WHERE id = ?
```

### Word search

```sql
SELECT cw.*, COALESCE(uws.status, 0) as status
FROM collections_word cw
LEFT JOIN user_word_status uws ON cw.id = uws.word_id AND uws.user_id = ?
WHERE (cw.english_word LIKE ? OR cw.russian_word LIKE ?)
ORDER BY cw.english_word
```