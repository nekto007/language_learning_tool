# API Documentation

Language Learning Tool provides a set of API endpoints for programmatic interaction with the system. These APIs can be used for integration with other applications or for creating custom clients.

## Contents

- [Authentication](#authentication)
- [API for Working with Words](#api-for-working-with-words)
- [API for Exporting to Anki](#api-for-exporting-to-anki)
- [API for Working with Books](#api-for-working-with-books)
- [Response Formats](#response-formats)
- [Error Handling](#error-handling)
- [Usage Examples](#usage-examples)

## Authentication

All API requests require authentication. Session authentication is used, so you must first log in through the web interface or the login API endpoint.

### Login

```
POST /api/login
```

**Request Parameters:**

| Parameter | Type | Description |
|----------|-----|----------|
| username | string | Username |
| password | string | Password |

**Request Example:**

```json
{
  "username": "user123",
  "password": "password123"
}
```

**Response Example:**

```json
{
  "success": true,
  "user_id": 1,
  "username": "user123"
}
```

## API for Working with Words

### Getting a List of Words

```
GET /api/words
```

**Request Parameters:**

| Parameter | Type | Description | Required |
|----------|-----|----------|--------------|
| status | int | Filter by status | No |
| book_id | int | Filter by book | No |
| letter | string | Filter by first letter | No |
| search | string | Search query | No |
| page | int | Page number (default 1) | No |
| per_page | int | Number of words per page (default 50) | No |

**Response Example:**

```json
{
  "words": [
    {
      "id": 1,
      "english_word": "example",
      "russian_word": "пример",
      "status": 2,
      "get_download": 1,
      "sentences": "This is an example sentence.<br>Это пример предложения."
    },
    {
      "id": 2,
      "english_word": "language",
      "russian_word": "язык",
      "status": 3,
      "get_download": 1,
      "sentences": "I speak multiple languages.<br>Я говорю на нескольких языках."
    }
  ],
  "total": 150,
  "page": 1,
  "per_page": 50,
  "total_pages": 3
}
```

### Getting Word Information

```
GET /api/words/{word_id}
```

**Response Example:**

```json
{
  "id": 1,
  "english_word": "example",
  "russian_word": "пример",
  "listening": "[sound:pronunciation_en_example.mp3]",
  "sentences": "This is an example sentence.<br>Это пример предложения.",
  "level": "A1",
  "brown": 1,
  "get_download": 1,
  "status": 2,
  "books": [
    {
      "id": 3,
      "title": "Sample Book",
      "frequency": 5
    }
  ]
}
```

### Updating Word Status

```
POST /api/update-word-status
```

**Request Parameters:**

| Parameter | Type | Description | Required |
|----------|-----|----------|--------------|
| word_id | int | Word ID | Yes |
| status | int | New status | Yes |

**Request Example:**

```json
{
  "word_id": 1,
  "status": 3
}
```

**Response Example:**

```json
{
  "success": true
}
```

### Batch Status Update

```
POST /api/batch-update-status
```

**Request Parameters:**

| Parameter | Type | Description | Required |
|----------|-----|----------|--------------|
| word_ids | array | Array of word IDs | Yes |
| status | int | New status | Yes |

**Request Example:**

```json
{
  "word_ids": [1, 2, 3, 4, 5],
  "status": 2
}
```

**Response Example:**

```json
{
  "success": true,
  "updated_count": 5,
  "total_count": 5
}
```

## API for Exporting to Anki

### Exporting Words to an Anki Deck

```
POST /api/export-anki
```

**Request Parameters:**

| Parameter | Type | Description | Required |
|----------|-----|----------|--------------|
| deckName | string | Deck name | Yes |
| cardFormat | string | Card format (basic, reversed, cloze) | Yes |
| includePronunciation | boolean | Include pronunciation | No |
| includeExamples | boolean | Include examples | No |
| updateStatus | boolean | Update status to "Active" | No |
| wordIds | array | Array of word IDs | Yes |

**Request Example:**

```json
{
  "deckName": "English Words",
  "cardFormat": "basic",
  "includePronunciation": true,
  "includeExamples": true,
  "updateStatus": true,
  "wordIds": [1, 2, 3, 4, 5]
}
```

**Response:**

On success, the API returns an .apkg file for download.

## API for Working with Books

### Getting a List of Books

```
GET /api/books
```

**Response Example:**

```json
{
  "books": [
    {
      "id": 1,
      "title": "Sample Book",
      "total_words": 1500,
      "unique_words": 350,
      "scrape_date": "2023-01-15T14:30:45"
    },
    {
      "id": 2,
      "title": "Another Book",
      "total_words": 2700,
      "unique_words": 520,
      "scrape_date": "2023-02-20T09:15:30"
    }
  ]
}
```

### Getting Book Information

```
GET /api/books/{book_id}
```

**Response Example:**

```json
{
  "id": 1,
  "title": "Sample Book",
  "total_words": 1500,
  "unique_words": 350,
  "scrape_date": "2023-01-15T14:30:45",
  "word_stats": {
    "new": 120,
    "known": 180,
    "queued": 25,
    "active": 15,
    "mastered": 10
  }
}
```

## Response Formats

All API endpoints return data in JSON format. If the request is successful, an object with the requested data is returned.

## Error Handling

In case of an error, the API returns an object with information about the error:

```json
{
  "success": false,
  "error": "Error message",
  "status_code": 400
}
```

Possible HTTP response codes:

| Code | Description |
|-----|----------|
| 200 | OK - Request completed successfully |
| 400 | Bad Request - Invalid request format |
| 401 | Unauthorized - Authentication required |
| 403 | Forbidden - Insufficient permissions |
| 404 | Not Found - Resource not found |
| 500 | Internal Server Error - Internal server error |

## Usage Examples

### Getting a List of Words with "Queued" Status

**Request:**

```
GET /api/words?status=2
```

### Searching for the Word "language"

**Request:**

```
GET /api/words?search=language
```

### Changing the Status of Multiple Words

**Request:**

```
POST /api/batch-update-status
Content-Type: application/json

{
  "word_ids": [10, 11, 12],
  "status": 3
}
```

### Exporting Words to Anki

**Request:**

```
POST /api/export-anki
Content-Type: application/json

{
  "deckName": "English - Advanced Level",
  "cardFormat": "basic",
  "includePronunciation": true,
  "includeExamples": true,
  "updateStatus": true,
  "wordIds": [25, 26, 27, 28, 29]
}
```

### Getting Book Statistics

**Request:**

```
GET /api/books/5
```