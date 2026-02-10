"""
Backfill grammar_topic_id on existing curriculum Lessons.

Matches grammar lessons to GrammarTopics by source_module number.
Run once: python scripts/backfill_grammar_topic_links.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.utils.db import db
from app.curriculum.models import Lessons, Module
from app.grammar_lab.models import GrammarTopic


def backfill():
    app = create_app()
    with app.app_context():
        # Build map: module_number -> GrammarTopic (using source_module from content)
        topics = GrammarTopic.query.all()
        module_to_topic = {}
        for topic in topics:
            source_module = (topic.content or {}).get('source_module')
            if source_module:
                module_to_topic[source_module] = topic

        print(f"Found {len(module_to_topic)} topics with source_module links")

        # Find all grammar lessons without grammar_topic_id
        grammar_lessons = Lessons.query.filter(
            Lessons.type.in_(['grammar', 'grammar_focus']),
            Lessons.grammar_topic_id.is_(None)
        ).all()

        print(f"Found {len(grammar_lessons)} grammar lessons without grammar_topic_id")

        linked = 0
        for lesson in grammar_lessons:
            module = Module.query.get(lesson.module_id)
            if not module:
                continue

            topic = module_to_topic.get(module.number)
            if topic:
                lesson.grammar_topic_id = topic.id
                linked += 1
                print(f"  Linked lesson {lesson.id} (module {module.number}) -> topic {topic.id} ({topic.title})")

        if linked > 0:
            db.session.commit()
            print(f"\nLinked {linked} lessons to grammar topics")
        else:
            print("\nNo lessons to link")


if __name__ == '__main__':
    backfill()
