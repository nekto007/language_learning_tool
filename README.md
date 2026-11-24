# Language Learning Tool

A production-deployed English learning platform built with Python and Flask.
Language Learning Tool combines structured lessons, vocabulary review, spaced repetition, grammar practice, and book reading in one application. A daily study plan brings these activities together, helping learners decide what to work on next and track their progress.
**Live application:** https://llt-english.com

## Features

- **Daily study plan** — follow a schedule of lessons, vocabulary reviews, and reading based on your selected study intensity.
- **Structured curriculum** — work through levels, modules, and lessons with progress tracking.
- **Vocabulary practice** — organize words into decks, take quizzes, and review cards with spaced repetition (SRS).
- **Grammar Lab** — study topic explanations, practice exercises, and revisit grammar through spaced repetition.
- **Book reading** — read books in the browser, track reading progress, and explore vocabulary from the text.
- **Telegram companion** — receive study reminders and check your daily plan and statistics from a linked account.

## Tech Stack

| Area | Technologies |
|------|--------------|
| Backend | Python, Flask |
| Web interface | Jinja2 templates, Bootstrap, JavaScript |
| API | REST endpoints built with Flask |
| Database | PostgreSQL, SQLAlchemy |
| Database migrations | Flask-Migrate, Alembic |
| Rate limiting | Flask-Limiter, optional Redis storage |
| Telegram integration | Telegram Bot API via requests |
| Deployment | Docker Compose, Gunicorn |
| Testing and linting | pytest, Ruff |

## Requirements

- Python 3.13+
- PostgreSQL 13+ (required for both production and tests — SQLite is NOT supported due to JSONB, array_agg, etc.)
- Redis (optional, for rate-limit storage)

## Quick Start

### Docker (recommended for production)

```bash
cp .env.example .env
# Edit .env with your database credentials and SECRET_KEY

docker compose up -d --build db web languagetool
docker compose exec web flask db upgrade head
docker compose exec web flask seed
docker compose exec web python create_admin.py
```

App available at http://localhost:5001

### Updating an existing installation

On the server, update the checkout and rebuild the services.

```bash
git pull
docker compose up -d --build
```

Publish learning materials through the admin panel. Under **Контент → Пакеты контента**, upload a ZIP of course module JSON files or individual final tests identified by their existing `external_key`. Review the targets and select **Применить пакет**. The same page links to the import forms for Grammar Lab exercises, dictionary entries, and books.

### Local Development

```bash
python3.13 -m venv .venv
source .venv/bin/activate

pip install -r requirements-test.txt
# On first setup, copy .env.example to .env and fill in your local credentials.
docker compose up -d db

POSTGRES_HOST=127.0.0.1 flask db upgrade head
POSTGRES_HOST=127.0.0.1 flask seed
POSTGRES_HOST=127.0.0.1 flask run --port 5000
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
| `flask answer-review-check` | Send one synthetic translation to the configured OpenAI model and print its verdict |
| `flask answer-review-status` | Show queue counts and manual case IDs. Add `--case ID` to inspect one case privately |

### Reviewing disputed answers

In course quizzes, course grammar lessons and standalone Grammar Lab web practice, a learner can flag an answer immediately after it is marked incorrect. The queue groups equivalent submissions for the same question and grader revision across learners. During the pilot each new case gets a Telegram card with the verdict and its explanation. Cases that need private or stale-content review get a brief case reference. Set `ANSWER_REVIEW_NOTIFY_ALL=false` to return to sending only potential corrections. Previously closed cases are not resent when the setting changes.

Open **Админка → Контент → Спорные ответы** to search the queue, review the original exercise and answer, and preview a change with the same grader learners use. An editor can add an accepted answer, replace a key, send a case for revision or dismiss it. Confirmation applies the preview to its exercise revision. The editor can open the next case immediately. Approval thanks the reporting learners in their notification center. A verified attempt receives credit when the updated grader accepts the disputed answer. Course completion follows the lesson's normal rules.

The administrator can see who reported each case, follow links to their accounts, and grant or revoke the **Модератор** role in a user profile. An active moderator can review disputes and publish curriculum content packages. Reporting accounts and the rest of the admin panel are restricted to administrators. Existing users retain their current access after the migration. Telegram sends the administrator a link to the case. Learner identity stays outside the model request. Older cases without recorded reporters can still be edited.

The scheduler uses `OPENAI_API_KEY` and `OPENAI_MODEL` to review cases. Delivery uses the existing `TELEGRAM_BOT_TOKEN` and the administrator's Telegram link on the site. A reviewed proposal waits in the queue until an active administrator has an active link. Rebuild and recreate both services with `docker compose up -d --build web scheduler`. The web container runs migrations on startup. Run `docker compose exec web flask answer-review-check` to verify model access using the synthetic translation, then check the queue with `docker compose exec web flask answer-review-status`.

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

Optional (content tooling only — not needed to run the app):
- `ANTHROPIC_API_KEY`: required by `scripts/generate_reading_annotations.py`
- `ANTHROPIC_SONNET_MODEL`: model id for that script (default `claude-sonnet-5`)
- That script also needs `pip install anthropic`, which is deliberately not in `requirements.txt`
- `scripts/generate_pilot_audio.py` needs `pip install edge-tts`, also deliberately not in
  `requirements.txt`; its tests skip when the package is absent. Note this is pilot/lesson audio —
  per-word pronunciation clips are human-voiced and never TTS

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
  telegram/             Telegram bot (Bot API via requests)
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
- [Quiz logic](docs/QUIZ_LOGIC.md)

## License

MIT License — see [LICENSE](LICENSE).

## Mobile apps

Исходники приложений iOS и Android пока хранятся только локально и исключены из Git.

## Guided grammar content

Grammar content is stored in the database; pulling code does not install it.
The reviewed A1-C1 catalog contains 86 topics. Validate it before applying:

```bash
docker compose exec web flask grammar-guided-install
docker compose exec web flask grammar-guided-install --apply
```

The installer backs up content, preserves existing IDs and learning history,
and archives the previous exercise bank. Repeating the import does not create
duplicates. `--level A1` or `--topic a1-1` selects a smaller rollout. See
[rollout notes](docs/plans/2026-11-22-guided-grammar-pilot.md).
