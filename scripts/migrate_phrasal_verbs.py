#!/usr/bin/env python3
"""
Migration script: Integrate phrasal verbs into CollectionWords table.

This script:
1. Adds new columns to collection_words table (item_type, base_word_id, usage_context)
2. Migrates data from phrasal_verb table to collection_words
3. Sets item_type='word' for existing words
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.utils.db import db
from app.words.models import CollectionWords


def add_columns_if_not_exist():
    """Add new columns to collection_words table if they don't exist."""
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('collection_words')]

    with db.engine.begin() as conn:
        if 'item_type' not in columns:
            print("Adding column: item_type")
            conn.execute(text(
                "ALTER TABLE collection_words ADD COLUMN item_type VARCHAR(20) DEFAULT 'word'"
            ))

        if 'base_word_id' not in columns:
            print("Adding column: base_word_id")
            conn.execute(text(
                "ALTER TABLE collection_words ADD COLUMN base_word_id INTEGER REFERENCES collection_words(id) ON DELETE SET NULL"
            ))

        if 'usage_context' not in columns:
            print("Adding column: usage_context")
            conn.execute(text(
                "ALTER TABLE collection_words ADD COLUMN usage_context TEXT"
            ))

    print("Columns check completed.")


def set_existing_words_type():
    """Set item_type='word' for all existing words that don't have a type."""
    from sqlalchemy import text

    with db.engine.begin() as conn:
        result = conn.execute(text(
            "UPDATE collection_words SET item_type = 'word' WHERE item_type IS NULL"
        ))
        print(f"Updated {result.rowcount} existing words with item_type='word'")


def migrate_phrasal_verbs():
    """Migrate data from phrasal_verb table to CollectionWords using raw SQL."""
    from sqlalchemy import text

    # Get phrasal verbs directly from the old table using raw SQL
    with db.engine.connect() as conn:
        result = conn.execute(text(
            "SELECT id, phrasal_verb, russian_translate, using, sentence, word_id, listening, get_download "
            "FROM phrasal_verb"
        ))
        pvs = result.fetchall()

    migrated = 0
    updated = 0
    skipped = 0

    print(f"Found {len(pvs)} phrasal verbs to migrate...")

    for pv in pvs:
        pv_id, phrasal_verb, russian_translate, using, sentence, word_id, listening, get_download = pv

        # Check if already exists in CollectionWords
        existing = CollectionWords.query.filter_by(
            english_word=phrasal_verb
        ).first()

        if existing:
            # Update existing entry
            existing.item_type = 'phrasal_verb'
            existing.base_word_id = word_id
            existing.usage_context = using
            if not existing.russian_word and russian_translate:
                existing.russian_word = russian_translate
            if not existing.sentences and sentence:
                existing.sentences = sentence
            updated += 1
        else:
            # Determine level from base word or default
            level = 'B1'
            if word_id:
                base = CollectionWords.query.get(word_id)
                if base and base.level:
                    level = base.level

            # Create new entry
            new_word = CollectionWords(
                english_word=phrasal_verb,
                russian_word=russian_translate,
                sentences=sentence,
                listening=listening,
                get_download=get_download or 0,
                item_type='phrasal_verb',
                base_word_id=word_id,
                usage_context=using,
                level=level
            )
            db.session.add(new_word)
            migrated += 1

    db.session.commit()
    print(f"Migration completed: {migrated} new, {updated} updated, {skipped} skipped")
    return migrated, updated


def create_index_if_not_exists():
    """Create index on item_type if it doesn't exist."""
    from sqlalchemy import text

    with db.engine.begin() as conn:
        try:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_collection_words_item_type ON collection_words(item_type)"
            ))
            print("Index created: idx_collection_words_item_type")
        except Exception as e:
            print(f"Index creation skipped (may already exist): {e}")


def verify_migration():
    """Verify migration results."""
    total = CollectionWords.query.count()
    words = CollectionWords.query.filter_by(item_type='word').count()
    phrasal = CollectionWords.query.filter_by(item_type='phrasal_verb').count()
    null_type = CollectionWords.query.filter(CollectionWords.item_type.is_(None)).count()

    print("\n=== Migration Verification ===")
    print(f"Total entries: {total}")
    print(f"Words (item_type='word'): {words}")
    print(f"Phrasal verbs (item_type='phrasal_verb'): {phrasal}")
    print(f"Null type: {null_type}")

    # Sample phrasal verbs
    sample = CollectionWords.query.filter_by(item_type='phrasal_verb').limit(5).all()
    if sample:
        print("\nSample phrasal verbs:")
        for pv in sample:
            print(f"  - {pv.english_word}: {pv.russian_word}")


def main():
    app = create_app()

    with app.app_context():
        print("Starting phrasal verbs migration...")
        print("=" * 50)

        # Step 1: Add columns
        print("\n[Step 1] Adding new columns...")
        add_columns_if_not_exist()

        # Step 2: Set existing words type
        print("\n[Step 2] Setting type for existing words...")
        set_existing_words_type()

        # Step 3: Migrate phrasal verbs
        print("\n[Step 3] Migrating phrasal verbs...")
        migrate_phrasal_verbs()

        # Step 4: Create index
        print("\n[Step 4] Creating index...")
        create_index_if_not_exists()

        # Step 5: Verify
        print("\n[Step 5] Verifying migration...")
        verify_migration()

        print("\n" + "=" * 50)
        print("Migration completed successfully!")


if __name__ == '__main__':
    main()
