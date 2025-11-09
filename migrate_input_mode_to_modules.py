#!/usr/bin/env python3
"""
Migration: Move input_mode from Lessons to Modules

Adds input_mode column to modules table and removes it from lessons table.
Sets input_mode based on module number:
- Module 1: selection_only
- Module 2: selection_and_ordering
- Modules 3-4: mixed
- Modules 5+: advanced
"""

from app import create_app, db
from app.curriculum.models import Module
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("=" * 80)
    print("MIGRATION: Moving input_mode from Lessons to Modules")
    print("=" * 80)

    try:
        # Step 1: Add input_mode column to modules table
        print("\n[1/3] Adding input_mode column to modules table...")
        with db.engine.begin() as conn:
            conn.execute(text("""
                ALTER TABLE modules
                ADD COLUMN IF NOT EXISTS input_mode VARCHAR(50)
                DEFAULT 'selection_only'
            """))
        print("✓ Column added to modules")

        # Step 2: Update modules with recommended input_modes
        print("\n[2/3] Setting input_mode for existing modules...")

        modules = Module.query.order_by(Module.number).all()

        for module in modules:
            # Determine input_mode based on module number
            if module.number == 1:
                input_mode = 'selection_only'
            elif module.number == 2:
                input_mode = 'selection_and_ordering'
            elif module.number <= 4:
                input_mode = 'mixed'
            else:
                input_mode = 'advanced'

            # Update module
            with db.engine.begin() as conn:
                conn.execute(
                    text("UPDATE modules SET input_mode = :mode WHERE id = :id"),
                    {"mode": input_mode, "id": module.id}
                )

            print(f"  Module #{module.number} '{module.title}' -> {input_mode}")

        print(f"\n✓ Updated {len(modules)} modules")

        # Step 3: Remove input_mode column from lessons table (if exists)
        print("\n[3/3] Removing input_mode column from lessons table...")
        with db.engine.begin() as conn:
            # Check if column exists
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='lessons' AND column_name='input_mode'
            """))

            if result.fetchone():
                conn.execute(text("ALTER TABLE lessons DROP COLUMN IF EXISTS input_mode"))
                print("✓ Column removed from lessons")
            else:
                print("✓ Column does not exist in lessons (skipping)")

        print("\n" + "=" * 80)
        print("✅ MIGRATION COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        print("\nNow lessons will inherit input_mode from their parent module.")

    except Exception as e:
        print(f"\n✗ Error during migration: {e}")
        db.session.rollback()
        raise
