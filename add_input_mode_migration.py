#!/usr/bin/env python3
"""
Migration: Add input_mode field to Lessons table

This field controls the allowed input types for exercises:
- selection_only: Only multiple choice, matching, fill_blank with options
- selection_and_ordering: Above + ordering, word_arrangement
- mixed: Above + fill_blank without options, short_answer
- advanced: All types including translation, transformation
"""

from app import create_app, db
from app.curriculum.models import Lessons
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("Adding input_mode column to lessons table...")

    try:
        # Add column with default value
        with db.engine.begin() as conn:
            conn.execute(text("""
                ALTER TABLE lessons
                ADD COLUMN IF NOT EXISTS input_mode VARCHAR(50)
                DEFAULT 'mixed'
            """))

        print("✓ Column added successfully")

        # Update existing lessons with recommended values based on lesson order
        print("\nUpdating existing lessons with recommended input_modes...")

        lessons = Lessons.query.all()
        for lesson in lessons:
            # Determine input_mode based on lesson number within module
            if lesson.number <= 3:
                input_mode = 'selection_only'
            elif lesson.number <= 7:
                input_mode = 'selection_and_ordering'
            elif lesson.number <= 10:
                input_mode = 'mixed'
            else:
                input_mode = 'advanced'

            # Update via raw SQL to avoid model validation issues
            with db.engine.begin() as conn:
                conn.execute(
                    text("UPDATE lessons SET input_mode = :mode WHERE id = :id"),
                    {"mode": input_mode, "id": lesson.id}
                )

            print(f"  Lesson #{lesson.number} '{lesson.title}' -> {input_mode}")

        print(f"\n✓ Updated {len(lessons)} lessons")
        print("\nMigration completed successfully!")

    except Exception as e:
        print(f"✗ Error during migration: {e}")
        db.session.rollback()
        raise
