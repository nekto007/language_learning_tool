#!/usr/bin/env python3
"""Export Module 1 lessons to CSV"""

import csv
import json
from app import create_app, db
from app.curriculum.models import Module, Lessons

app = create_app()

with app.app_context():
    # Get first module
    module = Module.query.order_by(Module.number).first()

    if not module:
        print("No modules found!")
        exit(1)

    print(f"Exporting lessons from: {module.title} (ID: {module.id})")

    # Get all lessons for this module
    lessons = Lessons.query.filter_by(module_id=module.id).order_by(Lessons.order, Lessons.number).all()

    # Prepare CSV file
    filename = f'module_{module.number}_lessons.csv'

    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = [
            'ID',
            'Number',
            'Order',
            'Title',
            'Type',
            'Description',
            'Collection ID',
            'Book ID',
            'Min Cards Required',
            'Min Accuracy Required',
            'Has Content',
            'Content Keys',
            'Content Structure',
            'Content Version',
            'Created At',
            'Updated At'
        ]

        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for lesson in lessons:
            # Extract content keys
            content_keys = ''
            content_structure = ''
            if lesson.content and isinstance(lesson.content, dict):
                content_keys = ', '.join(lesson.content.keys())
                # Create a structure overview
                structure = {}
                for key, value in lesson.content.items():
                    if isinstance(value, list):
                        structure[key] = f'list[{len(value)}]'
                    elif isinstance(value, dict):
                        structure[key] = f'dict[{len(value)}]'
                    else:
                        structure[key] = type(value).__name__
                content_structure = json.dumps(structure, ensure_ascii=False)

            writer.writerow({
                'ID': lesson.id,
                'Number': lesson.number,
                'Order': lesson.order,
                'Title': lesson.title,
                'Type': lesson.type,
                'Description': lesson.description or '',
                'Collection ID': lesson.collection_id or '',
                'Book ID': lesson.book_id or '',
                'Min Cards Required': lesson.min_cards_required,
                'Min Accuracy Required': lesson.min_accuracy_required,
                'Has Content': 'Yes' if lesson.content else 'No',
                'Content Keys': content_keys,
                'Content Structure': content_structure,
                'Content Version': lesson.content_version,
                'Created At': lesson.created_at.strftime('%Y-%m-%d %H:%M:%S') if lesson.created_at else '',
                'Updated At': lesson.updated_at.strftime('%Y-%m-%d %H:%M:%S') if lesson.updated_at else ''
            })

    print(f"✓ Exported {len(lessons)} lessons to {filename}")
