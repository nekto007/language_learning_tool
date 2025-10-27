"""
Migration: Add parent_deck_id and last_synced_at fields to quiz_decks table

This migration adds synchronization support for deck copying and updates.
"""
import sys
import os

# Add parent directory to path so we can import the app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from sqlalchemy import text

def upgrade():
    """Add parent_deck_id and last_synced_at columns to quiz_decks table"""
    app = create_app()

    with app.app_context():
        try:
            # Check if columns already exist
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('quiz_decks')]

            if 'parent_deck_id' in columns and 'last_synced_at' in columns:
                print("✓ Columns already exist. No migration needed.")
                return

            # Add parent_deck_id column
            if 'parent_deck_id' not in columns:
                print("Adding parent_deck_id column...")
                db.session.execute(text("""
                    ALTER TABLE quiz_decks
                    ADD COLUMN parent_deck_id INTEGER
                """))

                # Add foreign key constraint
                db.session.execute(text("""
                    ALTER TABLE quiz_decks
                    ADD CONSTRAINT fk_quiz_decks_parent
                    FOREIGN KEY (parent_deck_id) REFERENCES quiz_decks(id)
                """))

                # Add index
                db.session.execute(text("""
                    CREATE INDEX ix_quiz_decks_parent_id ON quiz_decks(parent_deck_id)
                """))
                print("✓ parent_deck_id column added")

            # Add last_synced_at column
            if 'last_synced_at' not in columns:
                print("Adding last_synced_at column...")
                db.session.execute(text("""
                    ALTER TABLE quiz_decks
                    ADD COLUMN last_synced_at TIMESTAMP
                """))
                print("✓ last_synced_at column added")

            db.session.commit()
            print("\n✓ Migration completed successfully!")

        except Exception as e:
            db.session.rollback()
            print(f"\n✗ Migration failed: {e}")
            raise


def downgrade():
    """Remove parent_deck_id and last_synced_at columns from quiz_decks table"""
    app = create_app()

    with app.app_context():
        try:
            print("Dropping columns...")

            # Drop index
            db.session.execute(text("DROP INDEX IF EXISTS ix_quiz_decks_parent_id"))

            # Drop foreign key constraint
            db.session.execute(text("""
                ALTER TABLE quiz_decks
                DROP CONSTRAINT IF EXISTS fk_quiz_decks_parent
            """))

            # Drop columns
            db.session.execute(text("ALTER TABLE quiz_decks DROP COLUMN IF EXISTS parent_deck_id"))
            db.session.execute(text("ALTER TABLE quiz_decks DROP COLUMN IF EXISTS last_synced_at"))

            db.session.commit()
            print("✓ Downgrade completed successfully!")

        except Exception as e:
            db.session.rollback()
            print(f"✗ Downgrade failed: {e}")
            raise


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'downgrade':
        downgrade()
    else:
        upgrade()