#!/usr/bin/env python3
"""
Run Telegram token migration

This script:
1. Reads the SQL migration file
2. Executes it against the database
3. Verifies the migration succeeded

Usage:
    python migrations/run_telegram_migration.py
"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app import create_app
from app.utils.db import db


def run_migration():
    """Run the Telegram token migration"""
    app = create_app()

    migration_file = Path(__file__).parent / 'migrate_to_new_telegram_tokens.sql'

    if not migration_file.exists():
        print(f"❌ Migration file not found: {migration_file}")
        sys.exit(1)

    print(f"📁 Reading migration file: {migration_file}")
    with open(migration_file, 'r') as f:
        sql = f.read()

    with app.app_context():
        print("🔄 Running migration...")
        try:
            # Execute the migration
            db.session.execute(db.text(sql))
            db.session.commit()
            print("✅ Migration completed successfully!")

            # Verify the migration
            print("\n📊 Verification:")

            # Check if telegram_tokens table exists
            result = db.session.execute(db.text(
                "SELECT COUNT(*) FROM telegram_tokens"
            ))
            token_count = result.scalar()
            print(f"  - telegram_tokens table exists with {token_count} rows")

            # Check if telegram_api_token column was removed
            result = db.session.execute(db.text("""
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_name = 'users'
                AND column_name = 'telegram_api_token'
            """))
            column_exists = result.scalar()

            if column_exists == 0:
                print("  - telegram_api_token column successfully removed from users table ✅")
            else:
                print("  - ⚠️  WARNING: telegram_api_token column still exists in users table")

            print("\n🎉 Migration complete! All Telegram integrations should regenerate tokens.")
            print("   Use POST /telegram/generate-token endpoint to create new tokens.")

        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Migration failed: {e}")
            sys.exit(1)


if __name__ == '__main__':
    run_migration()
