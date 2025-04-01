# English Learning App

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-green.svg)
![Flask](https://img.shields.io/badge/flask-2.0+-yellow.svg)

A modern web application for effective English language learning with a spaced repetition system.

## 🌟 Features

- 📚 **Personal vocabulary** with learning progress tracking
- 🔄 **Spaced repetition system** Anki-style for effective memorization
- 📝 **Various learning modes**: flashcards, quizzes
- 🎯 **Difficulty levels** (A1-C2) according to CEFR
- 🎧 **Audio pronunciation integration**
- 📱 **Export to Anki** for mobile learning
- 🌐 **Multilingual interface** (Russian and English)
- 📖 **Book integration** for learning words in context

## 📋 Requirements

- Python 3.8+
- SQLite
- python-dotenv

## 🚀 Quick Start

### Running with Docker (recommended)

```bash
# Clone the repository
git clone https://github.com/nekto007/language_learning_tool.git
cd language_learning_tool

# Create .env file from example
cp .env.example .env
# Edit .env with your settings

# Run using Docker Compose
docker-compose up -d
```

After launching, the application will be available at http://localhost:5000

### Manual Installation

```bash
# Clone the repository
git clone https://github.com/nekto007/english-learning-app.git
cd english-learning-app

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file from example
cp .env.example .env
# Edit .env with your settings

# Initialize the database
flask db upgrade

# Run the application
flask run
```

## 🛠️ Configuration

Application configuration is managed through environment variables or a `.env` file. Copy `.env.example` to `.env` and configure the following parameters:

```
# Application security
# Generate a strong key with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=your-strong-random-secret-key-here

# Database settings
DATABASE_URL=sqlite:///words.db
# For production environments, PostgreSQL or MySQL is recommended:
# DATABASE_URL=postgresql://user:password@localhost/dbname

# File storage paths
MEDIA_FOLDER=app/static/audio/
TRANSLATE_FILE=translate_gpt.txt
PHRASAL_VERB_FILE=phrasal_verb.txt

# Web request settings
USER_AGENT=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36
REQUEST_TIMEOUT=10

# Application limits
MAX_RETRIES=3
MAX_PAGES=1000
MAX_CONTENT_LENGTH=16777216  # 16MB

# Cookie settings
REMEMBER_COOKIE_DAYS=30

# Language settings
BABEL_DEFAULT_LOCALE=en

# Environment (development/production)
FLASK_ENV=development
```

### Enhanced Security for Production

For production environments, it's recommended to:

1. Set `FLASK_ENV=production`
2. Use PostgreSQL instead of SQLite
3. Generate a strong `SECRET_KEY` and store it securely
4. Use HTTPS with secure cookie settings

## 📚 Documentation

- [User Manual](docs/user_manual.md)
- [Technical Documentation](docs/technical_docs.md)
- [API Documentation](docs/api.md)

## 🧪 Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app
```

## 🤝 Contributing

We welcome contributions to the project! Please refer to the [contribution guidelines](CONTRIBUTING.md) for more information.

## 📜 License

This project is distributed under the [MIT](LICENSE) license.

## 📞 Contact

If you have questions or suggestions, please create an issue in this repository.