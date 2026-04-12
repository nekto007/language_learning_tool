# Language Learning Tool

A Flask web application for English language learning with spaced repetition, structured curriculum, grammar exercises, book integration, and a Telegram bot.

## Requirements

- Python 3.13+
- PostgreSQL 13+ (required for both production and tests — SQLite is NOT supported due to JSONB, array_agg, etc.)
- Redis (optional, for rate-limit storage)

## Quick Start

### Docker (recommended for production)

```bash
cp .env.example .env
# Edit .env with your database credentials and SECRET_KEY

docker compose up -d --build
docker compose exec web flask db upgrade head
docker compose exec web flask seed
docker compose exec web python create_admin.py
```

App available at http://localhost:5000

### Local Development

```bash
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# Edit .env — set POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, SECRET_KEY

flask db upgrade head
flask seed
flask run
```

## Official Entry Points

| Command | Purpose |
|---------|---------|
| `flask run` | Development server |
| `gunicorn run:app` | Production server |
| `flask db upgrade head` | Apply database migrations (the only supported schema management path) |
| `flask seed` | Seed initial data (modules, achievements) — safe to run multiple times |
| `flask warm-cache` | Pre-warm curriculum cache |
| `flask start-bot` | Start Telegram bot polling |

## Testing

**PostgreSQL is required for tests.** Create a test database (name must contain `_test`):

```bash
createdb language_learning_test
```

Set the test DATABASE_URL:

```bash
export TESTING=true
export DATABASE_URL=postgresql://user:password@localhost:5432/language_learning_test
```

Run tests:

```bash
pip install -r requirements-test.txt
pytest tests/ -x --timeout=60
```

### Smoke Path (verify setup from clean environment)

```bash
pip install -r requirements-test.txt
python -c "from app import create_app; create_app()"
pytest tests/ -x --timeout=60
```

## Configuration

All configuration is via environment variables. See `.env.example` for the complete reference.

Required variables: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `SECRET_KEY`

Security notes:
- `SECRET_KEY`: required, used for session signing
- `JWT_SECRET_KEY`: required in production; in development a random key is generated per restart
- Cookie security flags are enabled by default; disabled when `FLASK_ENV=development`

## Project Structure

```
app/                    Application package
  admin/                Admin panel
  api/                  REST API endpoints
  auth/                 Authentication (login, registration, profiles)
  books/                Book management and reader
  curriculum/           Structured curriculum (levels, modules, lessons)
  grammar_lab/          Grammar exercises
  study/                SRS study features, decks, quizzes
  words/                Vocabulary management and dashboard
  telegram/             Telegram bot (aiogram 3.x)
  notifications/        In-app notification system
  achievements/         Achievements and streaks
migrations/             Alembic database migrations
tests/                  Test suite (pytest)
config/                 Application configuration
docs/                   Documentation
```

## Documentation

- [API Reference](docs/API.md)
- [Database](docs/DATABASE.md)

## License

MIT License — see [LICENSE](LICENSE).
