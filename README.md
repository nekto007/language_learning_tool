# Language Learning Tool

A tool for effective English language learning. Helps collect words from various texts, manage your vocabulary, and
create Anki flashcards for memorization.

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Flask](https://img.shields.io/badge/Flask-2.0%2B-orange)](https://flask.palletsprojects.com/)
[![SQLite](https://img.shields.io/badge/SQLite-3.0-blue)](https://www.sqlite.org/)

## 🌟 Features

- **Word collection** from texts and web pages with frequency analysis
- **Personal dictionary** with learning progress tracking
- **Audio pronunciation** for each word
- **Anki integration** for spaced repetition learning
- **Multi-user mode** for group work
- **Web interface** for convenient management
- **Statistics tracking** of word learning across different books and sources

## 📋 Contents

- [Installation](#-installation)
- [Usage](#-usage)
- [Key Components](#-key-components)
- [Word Management](#-word-management)
- [Anki Integration](#-anki-integration)
- [Command Line](#-command-line)
- [Database Schema](#-database-schema)
- [Project Structure](#-project-structure)
- [Configuration](#-configuration)
- [Development](#-development)
- [License](#-license)

## 🚀 Installation

### Prerequisites

- Python 3.8+
- pip
- SQLite
- Anki (optional)

### Clone the Repository

```bash
git clone https://github.com/nekto007/language_learning_tool.git

cd language_learning_tool
```

### Create a Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Linux/Mac
venv\Scripts\activate     # On Windows
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Download NLTK Resources

```bash
python -c "import nltk; nltk.download('punkt'); nltk.download('stopwords'); nltk.download('averaged_perceptron_tagger'); nltk.download('wordnet'); nltk.download('words')"
```

### Initialize the Database

```bash
python main.py init
```

## 🎯 Usage

### Launch the Web Interface

```bash
export FLASK_APP=app.py
export FLASK_ENV=development
flask run
```

Open http://127.0.0.1:5000/ in your browser to access the web interface.

### Main Use Cases

1. **Collecting Words from a New Source**
    - Use the scraping command to extract words from a web page
    - View word frequency statistics in the source

2. **Dictionary Management**
    - Mark known words
    - Add new words to the learning queue
    - Track learning progress

3. **Creating Anki Flashcards**
    - Select a group of words to study
    - Export to an Anki deck with audio and examples
    - Import the deck into Anki

## 🔧 Key Components

### Web Interface

Main sections:

- **Dashboard** - general statistics and book list
- **Word List** - view and manage words
- **Word Details** - view additional information about a word

### Progress Tracking System

Each word has one of the following statuses:

- **New (0)** - unprocessed word
- **Queued (1)** - prepared for learning
- **Active (2)** - word in the learning process
- **Learned (3)** - fully learned word

### Book/Source Management

- Words are linked to sources from which they were obtained
- Word frequency is tracked in each source
- Statistics are maintained for each book/source

## 📚 Word Management

### Filtering and Search

- **Status Filter** - display words with a specific status
- **Alphabetical Filter** - filter by first letter
- **Search** - full-text search for English and translated words
- **Book Filter** - display words from a specific book

### Bulk Operations

- **Group Status Change** - simultaneous status change for multiple words
- **Anki Deck Creation** - export selected words to Anki

## 🎴 Anki Integration

### Export to Anki

1. Select words for export on the words page
2. Click "Create Anki Cards"
3. Configure card format and additional parameters
4. Export the deck in .apkg format
5. Import the file into Anki via File -> Import menu

### Card Formats

- **Basic** - English on the front side, translation on the back
- **With Examples** - includes a contextual example of word usage
- **With Pronunciation** - includes an audio file with word pronunciation

## 💻 Command Line

In addition to the web interface, the program has a powerful command line system:

### Text Scraping

```bash
python main.py scrape https://example.com/text --pages 10 --book "Book Title"
```

### Updating Book Statistics

```bash
python main.py update-book-stats
```

### Updating Word Status

```bash
python main.py update-status --status 1 --file known_words.txt
```

### Pronunciation Management

```bash
python main.py download-pronunciations --pattern "a%" --update-status
```

## 📊 Database Schema

Main tables:

- **collections_word** - dictionary of English words
- **book** - texts/books from which words are collected
- **word_book_link** - connections between words and books with frequency
- **user_word_status** - word learning statuses for each user
- **users** - system users

## 📁 Project Structure

```
language_learning_tool/
├── app.py                    # Main Flask application file
├── main.py                   # Command line interface
├── config/                   # Configuration
│   └── settings.py           # Application settings
├── src/                      # Source code
│   ├── db/                   # Database operations
│   │   ├── models.py         # Table and model definitions
│   │   └── repository.py     # Functions for working with the database
│   ├── nlp/                  # Natural language processing
│   │   ├── setup.py          # Configuring NLTK
│   │   └── processor.py      # Text and word processing
│   ├── web/                  # Scraping and web components
│   │   ├── portal.py        
│   │   └── scraper.py        # Functions for retrieving data from web pages
│   ├── audio/                # Audio file management
│   │   ├── forvo_api.py      # Настройка NLTK
│   │   ├── forvo_download.py # Настройка NLTK
│   │   └── manager.py        # Управление аудиофайлами
│   ├── utils/
│   │   └── helpers.py        # Auxiliary functions
│   └── user/                 # User management
│       ├── __init__.py
│       ├── models.py         # Table and model definitions
│       └── repository.py     # Functions for working with the database
└── templates/                # HTML templates for web interface
   ├── base.html              # The base template (already fixed with the copyright year)
   ├── index.html             # Homepage
   ├── login.html             # Login page (now separate)
   ├── register.html          # Registration page (now separate)
   ├── dashboard.html         # User dashboard
   ├── words_list.html        # Words listing page
   └── word_detail.html       # Word detail page
```

## ⚙️ Configuration

Main settings are in the `config/settings.py` file:

- Database path
- Media file paths
- Scraping settings
- NLTK parameters

## 👨‍💻 Development

### Running Tests

```bash
python -m unittest discover tests
```

### Adding New Features

1. Clone the repository
2. Create a new branch `git checkout -b feature/my-feature`
3. Make changes and test
4. Submit a pull request

## 📝 License

This project is distributed under the MIT license. See the [LICENSE](LICENSE) file for details.