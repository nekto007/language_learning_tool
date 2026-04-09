"""
Import a book course from JSON export into the current database.
Handles word_id remapping: matches words by english_word text.
Missing words are skipped (logged).

Usage:
    python scripts/import_book_course.py <json_file> [--dry-run] [--force]

Example:
    python scripts/import_book_course.py exports/course_2_export.json --dry-run
    python scripts/import_book_course.py exports/course_2_export.json

Flags:
    --dry-run   Show what would happen without writing to DB
    --force     Delete existing course with same slug before importing
"""
import sys
import os
import json
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db

app = create_app()


def build_word_map(words_needed: list[str]) -> tuple[dict[str, int], list[str]]:
    """Map english_word texts to prod word_ids. Match only by english_word.
    Returns (map, missing_list)."""
    if not words_needed:
        return {}, []

    unique_words = list(set(w.lower().strip() for w in words_needed if w))
    word_map = {}

    for i in range(0, len(unique_words), 500):
        batch = unique_words[i:i+500]
        placeholders = ",".join(f":w{j}" for j in range(len(batch)))
        params = {f"w{j}": w for j, w in enumerate(batch)}
        rows = db.session.execute(db.text(f"""
            SELECT id, LOWER(english_word) FROM collection_words
            WHERE LOWER(english_word) IN ({placeholders})
        """), params).fetchall()
        for row in rows:
            word_map[row[1]] = row[0]

    missing = [w for w in unique_words if w not in word_map]
    return word_map, missing


def find_book_id(title: str, author: str) -> Optional[int]:
    """Find book by title/author in prod DB."""
    row = db.session.execute(db.text(
        "SELECT id FROM book WHERE LOWER(title) = LOWER(:title)"
    ), {"title": title}).fetchone()
    if row:
        return row[0]
    # Try partial match
    row = db.session.execute(db.text(
        "SELECT id FROM book WHERE LOWER(title) LIKE :pattern"
    ), {"pattern": f"%{title.lower()[:30]}%"}).fetchone()
    return row[0] if row else None


def find_chapter_ids(book_id: int) -> dict[int, int]:
    """Map chap_num -> chapter.id for a book."""
    rows = db.session.execute(db.text(
        "SELECT chap_num, id FROM chapter WHERE book_id = :bid"
    ), {"bid": book_id}).fetchall()
    return {r[0]: r[1] for r in rows}


def import_course(data: dict, dry_run: bool = False, force: bool = False) -> None:
    """Import a book course from exported data."""
    with app.app_context():
        course_data = data["course"]
        slug = course_data["slug"]

        # Safety check: don't run on test DB accidentally
        db_url = str(db.engine.url)
        print(f"Target DB: {db_url}")

        # Check if course already exists (may be multiple from failed attempts)
        existing_all = db.session.execute(db.text(
            "SELECT id FROM book_courses WHERE slug = :slug ORDER BY id"
        ), {"slug": slug}).fetchall()
        existing = existing_all[0] if existing_all else None

        if existing:
            if force and not dry_run:
                all_orphan_task_ids = []
                all_orphan_block_ids = []
                for ex_row in existing_all:
                    cid = ex_row[0]
                    print(f"Deleting existing course '{slug}' (id={cid})...")
                    # Collect orphan task IDs
                    task_rows = db.session.execute(db.text("""
                        SELECT dl.task_id FROM daily_lessons dl
                        JOIN book_course_modules bcm ON dl.book_course_module_id = bcm.id
                        WHERE bcm.course_id = :cid AND dl.task_id IS NOT NULL
                    """), {"cid": cid}).fetchall()
                    all_orphan_task_ids.extend(r[0] for r in task_rows)

                    # Collect orphan block IDs
                    block_rows = db.session.execute(db.text("""
                        SELECT block_id FROM book_course_modules
                        WHERE course_id = :cid AND block_id IS NOT NULL
                    """), {"cid": cid}).fetchall()
                    all_orphan_block_ids.extend(r[0] for r in block_rows)

                    # Delete course (cascades to modules, lessons, slice_vocab)
                    db.session.execute(db.text(
                        "DELETE FROM book_courses WHERE id = :id"
                    ), {"id": cid})

                # Delete orphan tasks
                if all_orphan_task_ids:
                    db.session.execute(db.text(
                        f"DELETE FROM task WHERE id IN ({','.join(str(i) for i in all_orphan_task_ids)})"
                    ))
                    print(f"  Deleted {len(all_orphan_task_ids)} orphan tasks")

                # Delete orphan blocks and their vocab/chapters
                if all_orphan_block_ids:
                    bid_list = ",".join(str(b) for b in all_orphan_block_ids)
                    db.session.execute(db.text(f"DELETE FROM block_vocab WHERE block_id IN ({bid_list})"))
                    db.session.execute(db.text(f"DELETE FROM block_chapter WHERE block_id IN ({bid_list})"))
                    db.session.execute(db.text(f"DELETE FROM block WHERE id IN ({bid_list})"))
                    print(f"  Deleted {len(all_orphan_block_ids)} orphan blocks")

                # Reset sequences to avoid PK conflicts with leftover values
                db.session.execute(db.text(
                    "SELECT setval('task_id_seq', COALESCE((SELECT MAX(id) FROM task), 1))"
                ))
                db.session.execute(db.text(
                    "SELECT setval('block_id_seq', COALESCE((SELECT MAX(id) FROM block), 1))"
                ))
                db.session.flush()
            elif force and dry_run:
                ids = [r[0] for r in existing_all]
                print(f"[DRY RUN] Would delete {len(ids)} existing course(s) '{slug}' (ids={ids})")
            else:
                print(f"Course '{slug}' already exists (id={existing[0]}). Use --force to replace.")
                sys.exit(1)

        # 1. Find book in prod
        book_id = find_book_id(course_data["_book_title"], course_data["_book_author"])
        if not book_id:
            print(f"Book not found: '{course_data['_book_title']}' by {course_data['_book_author']}")
            print("Import the book first, then retry.")
            sys.exit(1)
        print(f"Found book: id={book_id} ('{course_data['_book_title']}')")

        # Clean up any orphan blocks for this book that conflict with import
        if force and not dry_run:
            existing_blocks = db.session.execute(db.text(
                "SELECT id, block_num FROM block WHERE book_id = :bid"
            ), {"bid": book_id}).fetchall()
            if existing_blocks:
                bid_list = ",".join(str(b[0]) for b in existing_blocks)
                db.session.execute(db.text(f"DELETE FROM block_vocab WHERE block_id IN ({bid_list})"))
                db.session.execute(db.text(f"DELETE FROM block_chapter WHERE block_id IN ({bid_list})"))
                db.session.execute(db.text(f"DELETE FROM block WHERE id IN ({bid_list})"))
                print(f"  Cleaned up {len(existing_blocks)} existing blocks for book_id={book_id}")
                db.session.flush()

        chapter_map = find_chapter_ids(book_id)
        print(f"Found {len(chapter_map)} chapters for book {book_id}")

        # 2. Build word map (match by english_word only)
        all_words_needed = []
        for sv in data.get("slice_vocabulary", []):
            if sv.get("_english_word"):
                all_words_needed.append(sv["_english_word"])
        for bv in data.get("block_vocabulary", []):
            if bv.get("_english_word"):
                all_words_needed.append(bv["_english_word"])

        word_map, missing_words = build_word_map(all_words_needed)
        print(f"Word mapping: {len(word_map)} found, {len(missing_words)} missing")
        if missing_words:
            print(f"  Missing words (will be skipped): {missing_words[:20]}{'...' if len(missing_words) > 20 else ''}")

        if dry_run:
            print("\n[DRY RUN] Would create:")
            print(f"  1 book_course")
            print(f"  {len(data['modules'])} modules")
            print(f"  {len(data['lessons'])} lessons")
            tasks_count = sum(1 for l in data['lessons'] if l.get('_task'))
            print(f"  {tasks_count} tasks")
            sv_ok = sum(1 for sv in data.get('slice_vocabulary', [])
                       if sv.get('_english_word', '').lower().strip() in word_map)
            sv_total = len(data.get('slice_vocabulary', []))
            print(f"  {sv_ok}/{sv_total} slice_vocabulary entries (rest skipped — missing words)")
            bv_ok = sum(1 for bv in data.get('block_vocabulary', [])
                       if bv.get('_english_word', '').lower().strip() in word_map)
            bv_total = len(data.get('block_vocabulary', []))
            print(f"  {bv_ok}/{bv_total} block_vocabulary entries")
            return

        # 3. Create course (preserve original ID if possible)
        course_insert_cols = [
            "book_id", "slug", "title", "description", "level",
            "difficulty_score", "estimated_duration_weeks", "total_modules",
            "author_info", "literary_themes", "language_features",
            "cultural_context", "is_active", "is_featured",
            "requires_prerequisites", "prerequisites",
        ]
        original_id = course_data.get("id")
        if original_id and force:
            # Check if original ID is free (was deleted by --force or never existed)
            id_taken = db.session.execute(db.text(
                "SELECT 1 FROM book_courses WHERE id = :id"
            ), {"id": original_id}).fetchone()
            if not id_taken:
                course_insert_cols.insert(0, "id")
        params = {col: course_data.get(col) for col in course_insert_cols}
        params["book_id"] = book_id
        # JSON fields need explicit casting
        for json_col in ["author_info", "literary_themes", "language_features", "cultural_context", "prerequisites"]:
            if params[json_col] is not None:
                params[json_col] = json.dumps(params[json_col]) if isinstance(params[json_col], (dict, list)) else params[json_col]

        cols_str = ", ".join(course_insert_cols)
        vals_str = ", ".join(f":{c}" for c in course_insert_cols)
        new_course_id = db.session.execute(db.text(f"""
            INSERT INTO book_courses ({cols_str}) VALUES ({vals_str}) RETURNING id
        """), params).scalar()
        # Reset sequence to max(id) so next auto-ID doesn't conflict
        db.session.execute(db.text(
            "SELECT setval('book_courses_id_seq', (SELECT MAX(id) FROM book_courses))"
        ))
        print(f"Created course: id={new_course_id}")

        # 4. Create blocks + modules
        old_module_to_new = {}  # old_module_id -> new_module_id
        old_block_to_new = {}   # old_block_id -> new_block_id

        for mod in data["modules"]:
            # Create block if needed
            new_block_id = None
            old_block_id = mod.get("block_id")
            if old_block_id and old_block_id not in old_block_to_new:
                chap_nums = mod.get("_block_chapter_nums", [])
                block_num = mod.get("_block_num", mod.get("module_number", 1))
                grammar_key = mod.get("_block_grammar_key", "")
                focus_vocab = mod.get("_block_focus_vocab", "")
                new_block_id = db.session.execute(db.text("""
                    INSERT INTO block (book_id, block_num, grammar_key, focus_vocab)
                    VALUES (:book_id, :block_num, :grammar_key, :focus_vocab) RETURNING id
                """), {
                    "book_id": book_id,
                    "block_num": block_num,
                    "grammar_key": grammar_key or "",
                    "focus_vocab": focus_vocab or "",
                }).scalar()
                old_block_to_new[old_block_id] = new_block_id

                # Link block to chapters via block_chapter
                for cnum in chap_nums:
                    ch_id = chapter_map.get(cnum)
                    if ch_id:
                        db.session.execute(db.text("""
                            INSERT INTO block_chapter (block_id, chapter_id)
                            VALUES (:bid, :cid)
                        """), {"bid": new_block_id, "cid": ch_id})
            elif old_block_id:
                new_block_id = old_block_to_new[old_block_id]

            # Create module
            mod_cols = [
                "course_id", "block_id", "module_number", "title", "description",
                "start_position", "end_position", "estimated_reading_time",
                "learning_objectives", "vocabulary_focus", "grammar_focus",
                "literary_elements", "lessons_data", "difficulty_level",
                "order_index", "is_locked",
            ]
            mod_params = {col: mod.get(col) for col in mod_cols}
            mod_params["course_id"] = new_course_id
            mod_params["block_id"] = new_block_id
            # JSON fields
            for json_col in ["learning_objectives", "vocabulary_focus", "grammar_focus", "literary_elements", "lessons_data"]:
                v = mod_params.get(json_col)
                if v is not None and isinstance(v, (dict, list)):
                    mod_params[json_col] = json.dumps(v)

            m_cols_str = ", ".join(mod_cols)
            m_vals_str = ", ".join(f":{c}" for c in mod_cols)
            new_mod_id = db.session.execute(db.text(f"""
                INSERT INTO book_course_modules ({m_cols_str}) VALUES ({m_vals_str}) RETURNING id
            """), mod_params).scalar()
            old_module_to_new[mod["id"]] = new_mod_id

        print(f"Created {len(old_module_to_new)} modules, {len(old_block_to_new)} blocks")

        # lesson_type -> task_type mapping
        LESSON_TYPE_TO_TASK_TYPE = {
            "comprehension_mcq": "reading_mcq",
            "phrase_cloze": "open_cloze",
            "language_focus": "grammar_sheet",
            "module_test": "final_test",
            "context_review": "reading_mcq",
            "guided_retelling": "reading_mcq",
            "vocabulary": "reading_mcq",
            "reading": "reading_mcq",
        }

        # 5. Create tasks + lessons
        old_lesson_to_new = {}  # old_lesson_id -> new_lesson_id

        for lesson in data["lessons"]:
            # Create task first if exists
            new_task_id = None
            task_data = lesson.get("_task")
            if task_data:
                payload = task_data.get("payload")
                payload_json = json.dumps(payload) if isinstance(payload, (dict, list)) else payload
                # Use exported task_type, or derive from lesson_type
                task_type = task_data.get("task_type")
                if not task_type:
                    lesson_type = lesson.get("lesson_type", "reading")
                    task_type = LESSON_TYPE_TO_TASK_TYPE.get(lesson_type, "reading_mcq")
                # block_id left NULL — book course tasks are linked via daily_lessons.task_id,
                # not via block. Also avoids unique constraint (block_id, task_type).
                new_task_id = db.session.execute(db.text("""
                    INSERT INTO task (task_type, payload)
                    VALUES (:task_type, CAST(:payload AS jsonb)) RETURNING id
                """), {
                    "task_type": task_type,
                    "payload": payload_json,
                }).scalar()

            # Map chapter_id
            new_chapter_id = None
            chap_num = lesson.get("_chapter_num")
            if chap_num:
                new_chapter_id = chapter_map.get(chap_num)

            # Map module_id
            new_module_id = old_module_to_new.get(lesson["book_course_module_id"])
            if not new_module_id:
                print(f"  WARNING: Module mapping missing for lesson {lesson['id']}")
                continue

            # Create lesson
            les_cols = [
                "book_course_module_id", "slice_number", "day_number",
                "slice_text", "word_count", "start_position", "end_position",
                "chapter_id", "lesson_type", "task_id", "audio_url", "annotations",
            ]
            les_params = {col: lesson.get(col) for col in les_cols}
            les_params["book_course_module_id"] = new_module_id
            les_params["chapter_id"] = new_chapter_id
            les_params["task_id"] = new_task_id
            # annotations is JSONB
            ann = les_params.get("annotations")
            if ann is not None and isinstance(ann, (dict, list)):
                les_params["annotations"] = json.dumps(ann)

            l_cols_str = ", ".join(les_cols)
            l_vals_str = ", ".join(
                f"CAST(:{c} AS jsonb)" if c == "annotations" else f":{c}"
                for c in les_cols
            )
            new_les_id = db.session.execute(db.text(f"""
                INSERT INTO daily_lessons ({l_cols_str}) VALUES ({l_vals_str}) RETURNING id
            """), les_params).scalar()
            old_lesson_to_new[lesson["id"]] = new_les_id

        print(f"Created {len(old_lesson_to_new)} lessons")

        # 5b. Remap daily_lesson_id references inside modules' lessons_data
        remapped_count = 0
        for mod in data["modules"]:
            new_mod_id = old_module_to_new.get(mod["id"])
            if not new_mod_id:
                continue
            ld = mod.get("lessons_data")
            if not ld or not isinstance(ld, dict):
                continue
            lessons_list = ld.get("lessons", [])
            changed = False
            for item in lessons_list:
                old_dl_id = item.get("daily_lesson_id")
                if old_dl_id and old_dl_id in old_lesson_to_new:
                    item["daily_lesson_id"] = old_lesson_to_new[old_dl_id]
                    changed = True
            if changed:
                db.session.execute(db.text("""
                    UPDATE book_course_modules
                    SET lessons_data = CAST(:ld AS jsonb)
                    WHERE id = :mid
                """), {"ld": json.dumps(ld), "mid": new_mod_id})
                remapped_count += 1

        if remapped_count:
            print(f"Remapped daily_lesson_id in lessons_data for {remapped_count} modules")

        # 6. Slice vocabulary (with word remapping)
        sv_created = 0
        sv_skipped = 0
        for sv in data.get("slice_vocabulary", []):
            english = (sv.get("_english_word") or "").lower().strip()
            new_word_id = word_map.get(english)
            if not new_word_id:
                sv_skipped += 1
                continue

            new_lesson_id = old_lesson_to_new.get(sv["daily_lesson_id"])
            if not new_lesson_id:
                sv_skipped += 1
                continue

            db.session.execute(db.text("""
                INSERT INTO slice_vocabulary
                    (daily_lesson_id, word_id, frequency_in_slice, is_new,
                     context_sentence, custom_translation, priority, unit_type, note)
                VALUES (:dl_id, :wid, :freq, :is_new, :ctx, :custom, :pri, :ut, :note)
            """), {
                "dl_id": new_lesson_id,
                "wid": new_word_id,
                "freq": sv.get("frequency_in_slice", 1),
                "is_new": sv.get("is_new", False),
                "ctx": sv.get("context_sentence"),
                "custom": sv.get("custom_translation"),
                "pri": sv.get("priority", 0),
                "ut": sv.get("unit_type"),
                "note": sv.get("note"),
            })
            sv_created += 1

        print(f"Slice vocabulary: {sv_created} created, {sv_skipped} skipped")

        # 7. Block vocabulary (with word remapping)
        bv_created = 0
        bv_skipped = 0
        for bv in data.get("block_vocabulary", []):
            english = (bv.get("_english_word") or "").lower().strip()
            new_word_id = word_map.get(english)
            if not new_word_id:
                bv_skipped += 1
                continue

            old_block_id = bv.get("block_id")
            new_block_id = old_block_to_new.get(old_block_id)
            if not new_block_id:
                bv_skipped += 1
                continue

            db.session.execute(db.text("""
                INSERT INTO block_vocab (block_id, word_id, freq)
                VALUES (:bid, :wid, :freq)
            """), {
                "bid": new_block_id,
                "wid": new_word_id,
                "freq": bv.get("freq", 1),
            })
            bv_created += 1

        print(f"Block vocabulary: {bv_created} created, {bv_skipped} skipped")

        # Commit
        db.session.commit()
        print(f"\nImport complete! New course id={new_course_id}")
        print(f"Access at: /books/courses/{course_data['slug']}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    json_file = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv

    if not os.path.exists(json_file):
        print(f"File not found: {json_file}")
        sys.exit(1)

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("_export_meta", {})
    print(f"Importing: {data['course']['title']}")
    print(f"Exported: {meta.get('exported_at', 'unknown')} from {meta.get('source_db', 'unknown')}")
    if dry_run:
        print("[DRY RUN MODE]\n")

    import_course(data, dry_run=dry_run, force=force)


if __name__ == "__main__":
    main()
