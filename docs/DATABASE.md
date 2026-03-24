# Database

## Introduction

The primary database for this project is **PostgreSQL**. All production and staging deployments are expected to run on PostgreSQL, and the schema, indexing strategy, and migrations are designed around PostgreSQL behavior.

**SQLite is supported only for local development convenience and limited migration/utility scripts.** It should not be treated as the main application datastore for deployed environments.

## Supported Database Engines

- **PostgreSQL (primary):**
  - Required for production deployments.
  - Recommended for local development when you want production-like behavior.
- **SQLite (secondary / limited use):**
  - Acceptable for quick local setup.
  - May be used by one-off migration scripts and local tooling.
  - Not recommended as the primary storage backend.

## Environment Configuration

Use `DATABASE_URL` to configure the database connection:

```bash
# PostgreSQL (primary)
DATABASE_URL=postgresql://user:password@localhost:5432/language_learning

# SQLite (development only)
DATABASE_URL=sqlite:///instance/words.db
```

## Migration Notes

Alembic migrations should be authored and validated against PostgreSQL first. If a migration script is run against SQLite for local workflows, treat that as best-effort compatibility rather than the source of truth.
