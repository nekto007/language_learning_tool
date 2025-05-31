# English Learning App

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-green.svg)
![Flask](https://img.shields.io/badge/flask-2.0+-yellow.svg)
![PostgreSQL](https://img.shields.io/badge/postgresql-13+-blue.svg)

A comprehensive web application for effective English language learning with advanced spaced repetition system, structured curriculum, and mobile support.

## 🌟 Features

### Core Learning Features
- 📚 **Personal vocabulary management** with progress tracking
- 🔄 **Advanced Spaced Repetition System (SRS)** - Anki-style algorithm for optimal memorization
- 📝 **Multiple learning modes**: 
  - Flashcards with audio pronunciation
  - Interactive quizzes
  - Matching exercises
  - Grammar lessons
  - Reading comprehension
- 🎯 **CEFR-aligned curriculum** (A0-C2 levels)
- 📖 **Book integration** - Learn vocabulary in context
- 🎧 **Audio pronunciation** for all words
- 📱 **Anki export** for offline learning

### Curriculum System
- 📐 **Structured learning path** with levels, modules, and lessons
- 📊 **Progress tracking** at lesson, module, and level stages
- 🎮 **Interactive exercises**:
  - Vocabulary cards with SRS
  - Grammar exercises with instant feedback
  - Quiz assessments
  - Matching games
  - Text reading with comprehension
  - Final tests for modules
- 🏆 **Gamification elements** - points, streaks, achievements

### Technical Features
- 🌐 **Multilingual interface** (English/Russian)
- 📱 **Mobile API** for iOS/Android apps
- 🔒 **Enhanced security** with input validation and XSS protection
- ⚡ **Performance optimized** with caching and database indexes
- 📊 **Admin dashboard** for content management
- 🔄 **Real-time progress synchronization**

## 📋 Requirements

- Python 3.8+
- PostgreSQL 13+ (recommended) or SQLite
- Redis (optional, for caching)
- Docker & Docker Compose (for containerized deployment)

## 🚀 Quick Start

### Running with Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/nekto007/english-learning-app.git
cd english-learning-app

# Create .env file from example
cp .env.example .env
# Edit .env with your settings

# Run using Docker Compose
docker-compose up -d

# Run database migrations
docker-compose exec web flask db upgrade

# Create admin user (optional)
docker-compose exec web python create_admin.py
```

The application will be available at http://localhost:5000

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

# Compile translations
pybabel compile -d app/translations

# Run the application
flask run
```

## 🛠️ Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
# Flask Configuration
SECRET_KEY=your-secret-key-change-this-in-production
FLASK_ENV=development  # or production

# Database Configuration
POSTGRES_USER=appuser
POSTGRES_PASSWORD=apppassword
POSTGRES_DB=learn_english_app
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Or for SQLite (development only)
DATABASE_URL=sqlite:///instance/words.db

# Email Configuration (for notifications)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

# Application Settings
BABEL_DEFAULT_LOCALE=en
LANGUAGES=en,ru
MAX_CONTENT_LENGTH=16777216  # 16MB
UPLOAD_FOLDER=app/static/uploads
ALLOWED_EXTENSIONS=txt,pdf,epub,fb2

# Security
SESSION_COOKIE_SECURE=True  # Set to True in production with HTTPS
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE=Lax
PERMANENT_SESSION_LIFETIME=2592000  # 30 days

# Redis Configuration (optional, for caching)
REDIS_URL=redis://localhost:6379/0

# API Settings
API_RATE_LIMIT=100 per hour
API_KEY_EXPIRATION=365  # days

# SRS Settings
SRS_NEW_CARDS_PER_DAY=20
SRS_REVIEW_CARDS_PER_DAY=100
SRS_LEARNING_STEPS=1,10  # minutes
SRS_GRADUATING_INTERVAL=1  # days
SRS_EASY_INTERVAL=4  # days
```

### Production Security Checklist

- [ ] Generate strong `SECRET_KEY`: `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] Use PostgreSQL instead of SQLite
- [ ] Enable HTTPS and set `SESSION_COOKIE_SECURE=True`
- [ ] Configure proper CORS settings for API
- [ ] Set up rate limiting for API endpoints
- [ ] Enable CSRF protection
- [ ] Configure secure headers (CSP, HSTS, etc.)
- [ ] Set up proper logging and monitoring

## 📚 Project Structure

```
english-learning-app/
├── app/                      # Application package
│   ├── __init__.py          # App factory
│   ├── admin/               # Admin panel
│   ├── api/                 # REST API endpoints
│   ├── auth/                # Authentication
│   ├── books/               # Book management
│   ├── curriculum/          # Curriculum system
│   │   ├── models.py       # Database models
│   │   ├── routes/         # Route handlers
│   │   ├── service.py      # Business logic
│   │   └── validators.py   # Input validation
│   ├── study/               # Study features
│   ├── words/               # Vocabulary management
│   ├── static/              # Static files (CSS, JS, images)
│   ├── templates/           # Jinja2 templates
│   └── translations/        # i18n translations
├── migrations/              # Database migrations
├── tests/                   # Test suite
├── docs/                    # Documentation
├── docker-compose.yml       # Docker configuration
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_curriculum.py

# Run with verbose output
pytest -v

# Run only unit tests (fast)
pytest -m "not integration"
```

## 📖 API Documentation

The application provides a REST API for mobile and third-party integrations:

### Authentication
```http
POST /api/auth/login
POST /api/auth/logout
POST /api/auth/refresh
```

### Vocabulary
```http
GET    /api/words
POST   /api/words
GET    /api/words/{id}
PUT    /api/words/{id}
DELETE /api/words/{id}
```

### SRS Mobile Sync
```http
GET  /api/srs/sync
POST /api/srs/review
GET  /api/srs/stats
```

### Curriculum
```http
GET /api/curriculum/levels
GET /api/curriculum/modules/{level_id}
GET /api/curriculum/lessons/{module_id}
GET /api/curriculum/lesson/{lesson_id}
POST /api/curriculum/progress
```

Full API documentation available at `/api/docs` when running in development mode.

## 🚀 Deployment

### Docker Deployment

```bash
# Build and run with Docker Compose
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# View logs
docker-compose logs -f

# Run migrations
docker-compose exec web flask db upgrade

# Create superuser
docker-compose exec web python create_admin.py
```

### Manual Deployment

1. Set up PostgreSQL database
2. Configure Nginx as reverse proxy
3. Use Gunicorn as WSGI server
4. Set up SSL certificates (Let's Encrypt)
5. Configure systemd service
6. Set up monitoring (Prometheus/Grafana)

Example Nginx configuration available in `nginx/app.conf`.

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details.

### Development Setup

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install

# Run linting
flake8 app/
black app/ --check

# Run type checking
mypy app/
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 👥 Authors

- **Igor Korobko** - *Initial work* - [nekto007](https://github.com/nekto007)

## 🙏 Acknowledgments

- Anki SRS algorithm implementation
- Flask community for excellent documentation
- Contributors and testers

## 📞 Support

- 📧 Email: nekto.korobko@gmail.com
- 🐛 Issues: [GitHub Issues](https://github.com/nekto007/english-learning-app/issues)
- 💬 Discussions: [GitHub Discussions](https://github.com/nekto007/english-learning-app/discussions)

---

Made with ❤️ for language learners worldwide