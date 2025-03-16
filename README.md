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

## 🐳 Docker Installation

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/)

# Update packages
```bash
sudo apt update && sudo apt upgrade -y
```

# Install Docker if not installed
```bash
sudo apt install -y apt-transport-https ca-certificates curl software-properties-common
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add - -
sudo add-apt-repository “deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable”
sudo apt update
sudo apt install -y docker-ce
```

# Install Docker Compose
```bash
sudo curl -L “https://github.com/docker/compose/releases/download/v2.12.2/docker-compose-$(uname -s)-$(uname -m)” -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

# Add the current user to the docker group to run without sudo
```bash
sudo usermod -aG docker $USER
```

# Reboot the session for the changes to take effect
```bash
newgrp docker
```

### Quick Start with Docker

1. **Clone the repository**

```bash
git clone https://github.com/nekto007/language_learning_tool.git
cd language_learning_tool
```

1. **Create environment file**

Create a .env file with environment variables:

```bash
cat > .env << 'EOF'
# Flask application settings
FLASK_APP=app.py
FLASK_ENV=production
FLASK_DEBUG=0
SECRET_KEY=change_this_to_a_long_random_string

# Path settings
DATABASE_PATH=/app/data/language_learning.db
MEDIA_PATH=/app/media

# API settings for word pronunciation (if used)
FORVO_API_KEY=your_forvo_api_key

# Other settings
ALLOWED_HOSTS=localhost,127.0.0.1,example.com
EOF
```

2. **Build and run with Docker Compose**

```bash
docker-compose up -d
```

3. **Access the application**

- Web Interface: http://127.0.0.1
- Direct access to Flask: http://127.0.0.1:5001

### Using Command Line Tools Inside Docker

You can run the command line tools inside the Docker container:

```bash
# Scrape text from a webpage
docker-compose exec web python main.py scrape https://example.com/text --pages 10 --book "Book Title"

# Update book statistics
docker-compose exec web python main.py update-book-stats

# Update word status
docker-compose exec web python main.py update-status --status 1 --file known_words.txt

# Download pronunciations
docker-compose exec web python main.py download-pronunciations --pattern "a%" --update-status
```

### Production Deployment

For production deployment:

1. **Update Nginx configuration** with your domain:
   - Edit `nginx/conf.d/app.conf` and replace `server_name 127.0.0.1;` with your domain
   - Uncomment and configure HTTPS section if needed

2. **Set up SSL certificates** for HTTPS:
   - Place your SSL certificates in the `nginx/ssl` directory
   - Configure the HTTPS section in Nginx configuration

3. **Update environment variables** for production:
   - Set a strong random SECRET_KEY
   - Set FLASK_ENV=production

### Managing Containers

```bash
# Start containers
docker-compose up -d

# Stop containers
docker-compose down

# View logs
docker-compose logs

# Follow logs in real-time
docker-compose logs -f

# Restart containers
docker-compose restart
```

### Database Management

The SQLite database is stored outside the container in the `data` directory, making it persistent and easily backed up.

```bash
# Create backup
cp data/language_learning.db data/language_learning_backup_$(date +%Y%m%d).db

# Restore from backup
cp data/language_learning_backup_20250316.db data/language_learning.db
```

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