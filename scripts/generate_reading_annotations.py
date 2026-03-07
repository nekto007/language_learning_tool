#!/usr/bin/env python3
"""
Generate reading annotations for book course daily lessons using Claude API.

Each reading lesson gets 3-5 annotations: cultural context, lexical notes,
and grammar explanations for phrases/words in the text.

Usage:
  python scripts/generate_reading_annotations.py --course-id=1
  python scripts/generate_reading_annotations.py --course-id=1 --module-id=5
  python scripts/generate_reading_annotations.py --course-id=1 --dry-run
  python scripts/generate_reading_annotations.py --lesson-id=123

Requires: ANTHROPIC_API_KEY environment variable.
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("Error: anthropic package not installed. Run: pip install anthropic")
    sys.exit(1)

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
TEMPERATURE = 0.3
API_DELAY = 1  # seconds between API calls


SYSTEM_PROMPT = """You are an expert English language teacher creating a structured reading lesson scaffold for a book course.

For each text passage, generate a complete lesson scaffold that helps a Russian-speaking student (level B1-B2) engage with the text actively.

The scaffold must include ALL of the following sections:

1. "objectives" — 3 short bullet points in Russian: what the student will do in this lesson (e.g., "познакомитесь с...", "поймёте...", "выучите...")

2. "before_reading" — a reading goal and 2 focus questions:
   - "goal": one sentence in Russian describing what to look for
   - "tasks": 2 questions (in Russian or English) to focus attention during reading

3. "annotations" — 4-6 notes about phrases/words in the text. Each must have:
   - "phrase": exact quote from the text
   - "type": one of "cultural", "lexical", "grammar"
   - "note": explanation in Russian with English equivalent (1-2 sentences)
   - "quick_use": 1-2 example sentences showing how to use this phrase/word

   Selection principles:
   - ~1 cultural, 2-3 lexical (phrases/words), max 1 grammar
   - Each annotation must either remove a comprehension obstacle, teach a useful piece of language, or explain cultural context
   - Do NOT annotate every difficult word — only those with real learning value

4. "reflection" — 1-2 open-ended thinking questions about the text (in English):
   - "question": the question
   - "hint": a short nudge to help the student think (in English)
   - "sample_answer": a model answer (in English, 1-2 sentences)

5. "self_check" — 3 true/false statements about the text (in English):
   - "statement": a claim about the text
   - "answer": true or false
   - "explanation": brief explanation why (in English, 1 sentence)
   Mix of true and false answers. At least one false.

6. "can_do" — 3 short statements in Russian: what the student can now do after completing this lesson

Return ONLY valid JSON object, no markdown, no explanation."""


USER_PROMPT_TEMPLATE = """Here is a reading passage from a book course. Generate a complete lesson scaffold.

Text:
---
{text}
---

Return a JSON object with this structure:
{{
  "objectives": ["...", "...", "..."],
  "before_reading": {{"goal": "...", "tasks": ["...", "..."]}},
  "annotations": [{{"phrase": "...", "type": "cultural|lexical|grammar", "note": "...", "quick_use": ["..."]}}],
  "reflection": [{{"question": "...", "hint": "...", "sample_answer": "..."}}],
  "self_check": [{{"statement": "...", "answer": true, "explanation": "..."}}],
  "can_do": ["...", "...", "..."]
}}"""


def generate_lesson_scaffold(client: anthropic.Anthropic, text: str) -> dict | None:
    """Generate full lesson scaffold for a text passage using Claude API."""
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(text=text[:3000])
            }]
        )

        content = response.content[0].text.strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        scaffold = json.loads(content)

        # Validate structure
        if not isinstance(scaffold, dict):
            print("  ERROR: response is not a dict")
            return None

        required_keys = ('objectives', 'before_reading', 'annotations', 'reflection', 'self_check', 'can_do')
        missing = [k for k in required_keys if k not in scaffold]
        if missing:
            print(f"  ERROR: missing keys: {missing}")
            return None

        # Validate annotations
        for ann in scaffold.get('annotations', []):
            if not all(k in ann for k in ('phrase', 'type', 'note')):
                print(f"  ERROR: annotation missing required fields: {ann}")
                return None
            if ann['type'] not in ('cultural', 'lexical', 'grammar'):
                print(f"  ERROR: invalid type '{ann['type']}'")
                return None

        # Validate self_check
        for item in scaffold.get('self_check', []):
            if not all(k in item for k in ('statement', 'answer', 'explanation')):
                print(f"  ERROR: self_check missing fields: {item}")
                return None

        # Validate reflection
        for item in scaffold.get('reflection', []):
            if not all(k in item for k in ('question', 'hint', 'sample_answer')):
                print(f"  ERROR: reflection missing fields: {item}")
                return None

        return scaffold

    except json.JSONDecodeError as e:
        print(f"  ERROR: JSON parse error: {e}")
        return None
    except anthropic.APIError as e:
        print(f"  ERROR: API error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Generate reading annotations for book course lessons")
    parser.add_argument("--course-id", type=int, help="Book course ID")
    parser.add_argument("--module-id", type=int, help="Specific module ID (optional)")
    parser.add_argument("--lesson-id", type=int, help="Specific daily lesson ID")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be generated without saving")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing annotations")
    args = parser.parse_args()

    if not args.course_id and not args.lesson_id:
        parser.error("--course-id or --lesson-id is required")

    # Import Flask app for DB access
    from app import create_app
    app = create_app()

    with app.app_context():
        from app.curriculum.daily_lessons import DailyLesson
        from app.curriculum.book_courses import BookCourseModule
        from app.utils.db import db

        # Build query for reading lessons
        query = DailyLesson.query.filter(
            DailyLesson.lesson_type.in_([
                'reading', 'reading_assignment', 'reading_passage',
                'reading_part1', 'reading_part2'
            ]),
            DailyLesson.slice_text.isnot(None),
        )

        if args.lesson_id:
            query = query.filter(DailyLesson.id == args.lesson_id)
        else:
            if args.module_id:
                query = query.filter(DailyLesson.book_course_module_id == args.module_id)
            else:
                module_ids = [m.id for m in BookCourseModule.query.filter_by(
                    course_id=args.course_id
                ).all()]
                query = query.filter(DailyLesson.book_course_module_id.in_(module_ids))

        if not args.overwrite:
            query = query.filter(DailyLesson.annotations.is_(None))

        lessons = query.order_by(DailyLesson.id).all()
        print(f"Found {len(lessons)} reading lessons to annotate")

        if not lessons:
            print("Nothing to do.")
            return

        client = anthropic.Anthropic()
        success = 0
        errors = 0

        for i, lesson in enumerate(lessons, 1):
            text_preview = (lesson.slice_text or "")[:80].replace("\n", " ")
            print(f"\n[{i}/{len(lessons)}] Lesson {lesson.id} (day {lesson.day_number}): {text_preview}...")

            scaffold = generate_lesson_scaffold(client, lesson.slice_text)

            if scaffold is None:
                errors += 1
                continue

            print(f"  Generated scaffold:")
            print(f"    Objectives: {len(scaffold.get('objectives', []))}")
            print(f"    Annotations: {len(scaffold.get('annotations', []))}")
            for ann in scaffold.get('annotations', []):
                print(f"      [{ann['type']}] \"{ann['phrase']}\" — {ann['note'][:60]}...")
            print(f"    Reflection: {len(scaffold.get('reflection', []))}")
            print(f"    Self-check: {len(scaffold.get('self_check', []))}")
            print(f"    Can-do: {len(scaffold.get('can_do', []))}")

            if not args.dry_run:
                lesson.annotations = scaffold
                db.session.commit()
                print("  Saved to DB")

            success += 1

            if i < len(lessons):
                time.sleep(API_DELAY)

        print(f"\nDone: {success} OK, {errors} errors out of {len(lessons)} lessons")


if __name__ == "__main__":
    main()
