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

## Schema Management

**Alembic is the single supported way to create and update the database schema in production.**

```bash
# Create/update schema (the ONLY supported method):
flask db upgrade head

# Seed initial data (modules, achievements):
flask seed

# Create admin user:
python create_admin.py
```

Legacy functions `init_db()` and `create_module_tables()` are deprecated no-ops kept only for backward compatibility. They will be removed in a future release.

In test mode (`TESTING=True`), the app factory calls `db.create_all()` directly so tests don't need to run migrations. This is intentional and does not affect production.

## Migration Notes

Alembic migrations should be authored and validated against PostgreSQL first. If a migration script is run against SQLite for local workflows, treat that as best-effort compatibility rather than the source of truth.
