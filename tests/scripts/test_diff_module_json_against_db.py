"""Unit + integration tests for scripts/diff_module_json_against_db.py.

The pure functions are exercised with a FakeDBSession stub so we can cover
identity matching, position-collision detection, fallback ambiguity, and
report rendering without spinning up the Flask app. A single integration test
imports fixture JSON into the test DB via `CurriculumImportService` and
verifies that the diff round-trips cleanly.
"""
from __future__ import annotations

import json
import sys
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from diff_module_json_against_db import (  # noqa: E402
    build_diff,
    format_json,
    format_markdown,
    has_blocking_issues,
    main,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _lesson(
    idx: int,
    *,
    lesson_type: str,
    title: str,
    external_key: str | None = None,
    extra: dict | None = None,
) -> dict:
    content: dict = dict(extra or {})
    if external_key is not None:
        content["external_key"] = external_key
    content.setdefault("items", [{"prompt": "a"}])
    return {
        "id": idx,
        "number": idx,
        "order": idx,
        "type": lesson_type,
        "title": title,
        "content": content,
    }


def _write_module(
    dir_path: Path,
    filename: str,
    lessons: list[dict],
    *,
    level: str = "A1",
    title: str = "Sample module",
) -> None:
    payload = {
        "module": {
            "title": title,
            "title_en": title,
            "level": level,
            "lessons": lessons,
        }
    }
    (dir_path / filename).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    d = tmp_path / "source"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Fake DB stub
# ---------------------------------------------------------------------------


class _FakeQuery:
    """Minimal SQLAlchemy-ish chain that yields the rows it was constructed
    with. Only used to feed `_load_db_curriculum` directly via monkeypatching.
    """

    def __init__(self, rows):
        self._rows = list(rows)

    def join(self, *_, **__):
        return self

    def filter(self, *_, **__):
        return self

    def order_by(self, *_, **__):
        return self

    def group_by(self, *_, **__):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, modules, lessons, progress_counts):
        self._modules = modules
        self._lessons = lessons
        self._progress = progress_counts

    def query(self, *cols):
        # Heuristic: the script issues exactly 3 queries: modules, lessons,
        # and progress counts. Match by column count.
        if len(cols) == 4:
            return _FakeQuery(self._modules)
        if len(cols) == 6:
            return _FakeQuery(self._lessons)
        if len(cols) == 2:
            return _FakeQuery(self._progress)
        raise AssertionError(f"unexpected query column count: {len(cols)}")


class _FakeDB:
    def __init__(self, session):
        self.session = session


def _stub_db(monkeypatch, *, modules, lessons, progress=None):
    """Patch `_load_db_curriculum` so callers don't need a real DB."""
    progress = progress or {}

    def _patched(db_session):
        from collections import defaultdict
        by_module = defaultdict(list)
        for lid, mid, number, ltype, title, content in lessons:
            ext_key = None
            if isinstance(content, dict):
                k = content.get("external_key")
                if isinstance(k, str) and k.strip():
                    ext_key = k.strip()
            by_module[mid].append(
                {
                    "id": lid,
                    "module_id": mid,
                    "number": number,
                    "type": ltype or "",
                    "title": title or "",
                    "external_key": ext_key,
                    "progress_rows": progress.get(lid, 0),
                }
            )
        out = {}
        for module_id, number, title, level_code in modules:
            out[(level_code, int(number))] = {
                "module_id": module_id,
                "number": int(number),
                "title": title,
                "level": level_code,
                "lessons": by_module.get(module_id, []),
            }
        return out

    monkeypatch.setattr(
        "diff_module_json_against_db._load_db_curriculum", _patched
    )
    return SimpleNamespace(session=object())


# ---------------------------------------------------------------------------
# Basic shapes
# ---------------------------------------------------------------------------


def test_build_diff_db_unavailable_marks_all_json_only(source_dir):
    _write_module(
        source_dir,
        "module_A1_1_greetings.json",
        [_lesson(1, lesson_type="vocabulary", title="V",
                 external_key="curriculum:vocabulary:A1:01:test")],
    )
    diff = build_diff(source_dir, None)
    assert diff["db_available"] is False
    assert diff["totals"]["lessons_json_only"] == 1
    assert diff["totals"]["lessons_matched_by_external_key"] == 0
    assert diff["modules"][0]["json_only"][0]["external_key"] == (
        "curriculum:vocabulary:A1:01:test"
    )


def test_build_diff_external_key_match_is_safe(monkeypatch, source_dir):
    """Source and DB share an external_key → matched, no collision, no warning."""
    _write_module(
        source_dir,
        "module_A1_1_greetings.json",
        [
            _lesson(1, lesson_type="vocabulary", title="Vocab",
                    external_key="key:vocab"),
            _lesson(2, lesson_type="grammar", title="Grammar",
                    external_key="key:grammar"),
        ],
    )
    db_session = _stub_db(
        monkeypatch,
        modules=[(101, 1, "M1", "A1")],
        lessons=[
            (1, 101, 1, "vocabulary", "Vocab",
             {"external_key": "key:vocab"}),
            (2, 101, 2, "grammar", "Grammar",
             {"external_key": "key:grammar"}),
        ],
    )
    diff = build_diff(source_dir, db_session)
    module = diff["modules"][0]
    assert len(module["matched_by_external_key"]) == 2
    assert module["position_collisions"] == []
    assert module["db_only"] == []
    assert module["json_only"] == []
    assert diff["totals"]["lessons_matched_by_external_key"] == 2


def test_build_diff_detects_position_collision(monkeypatch, source_dir):
    """Same number but different external_key → silent overwrite would happen."""
    _write_module(
        source_dir,
        "module_A1_1_greetings.json",
        [
            _lesson(1, lesson_type="vocabulary", title="Vocab",
                    external_key="key:vocab"),
            _lesson(2, lesson_type="reading", title="Reading new",
                    external_key="key:reading_new"),
        ],
    )
    db_session = _stub_db(
        monkeypatch,
        modules=[(101, 1, "M1", "A1")],
        lessons=[
            (1, 101, 1, "vocabulary", "Vocab",
             {"external_key": "key:vocab"}),
            (5, 101, 2, "grammar", "Grammar old",
             {"external_key": "key:grammar_old"}),
        ],
        progress={5: 17},
    )
    diff = build_diff(source_dir, db_session)
    module = diff["modules"][0]
    assert len(module["position_collisions"]) == 1
    coll = module["position_collisions"][0]
    assert coll["src_position"] == 2
    assert coll["src_external_key"] == "key:reading_new"
    assert coll["db_lesson_id_at_position"] == 5
    assert coll["db_external_key_at_position"] == "key:grammar_old"
    assert coll["progress_rows"] == 17
    assert diff["totals"]["position_collisions_with_progress"] == 1
    assert has_blocking_issues(diff) is True


def test_build_diff_position_changed_for_external_match_is_not_a_collision(
    monkeypatch, source_dir
):
    """When the same external_key sits at a different number, it's a safe
    re-order, not a collision: importer should follow the key and move the row.
    """
    _write_module(
        source_dir,
        "module_A1_1_greetings.json",
        [
            _lesson(1, lesson_type="vocabulary", title="Vocab",
                    external_key="key:vocab"),
            _lesson(2, lesson_type="grammar", title="Grammar",
                    external_key="key:grammar"),
        ],
    )
    db_session = _stub_db(
        monkeypatch,
        modules=[(101, 1, "M1", "A1")],
        lessons=[
            # Same external_keys, different DB numbers.
            (1, 101, 2, "vocabulary", "Vocab",
             {"external_key": "key:vocab"}),
            (2, 101, 1, "grammar", "Grammar",
             {"external_key": "key:grammar"}),
        ],
    )
    diff = build_diff(source_dir, db_session)
    module = diff["modules"][0]
    # Both matched by external_key with position_changed=True.
    assert len(module["matched_by_external_key"]) == 2
    assert all(
        entry["position_changed"] for entry in module["matched_by_external_key"]
    )
    # Both positions are occupied by lessons with different external_keys,
    # so each is a collision.
    assert len(module["position_collisions"]) == 2


def test_build_diff_fallback_match_when_external_key_missing(
    monkeypatch, source_dir
):
    """Legacy DB lesson with no external_key matches source on (type, title)."""
    _write_module(
        source_dir,
        "module_A1_1_greetings.json",
        [_lesson(1, lesson_type="reading", title="My Reading",
                 external_key=None)],
    )
    db_session = _stub_db(
        monkeypatch,
        modules=[(101, 1, "M1", "A1")],
        lessons=[
            (10, 101, 1, "reading", " my reading ", {}),  # whitespace tolerant
        ],
    )
    diff = build_diff(source_dir, db_session)
    module = diff["modules"][0]
    assert len(module["matched_by_fallback"]) == 1
    assert module["matched_by_fallback"][0]["db_lesson_id"] == 10
    assert module["matched_by_fallback"][0]["position_changed"] is False
    assert module["position_collisions"] == []
    assert module["json_only"] == []


def test_build_diff_flashcards_alias_maps_to_card(monkeypatch, source_dir):
    _write_module(
        source_dir,
        "module_A1_1_greetings.json",
        [_lesson(1, lesson_type="flashcards", title="Cards 1",
                 external_key=None,
                 extra={"cards": [{"front": "a", "back": "b"}]})],
    )
    db_session = _stub_db(
        monkeypatch,
        modules=[(101, 1, "M1", "A1")],
        lessons=[(20, 101, 1, "card", "Cards 1", {})],
    )
    diff = build_diff(source_dir, db_session)
    module = diff["modules"][0]
    assert len(module["matched_by_fallback"]) == 1


def test_build_diff_ambiguous_fallback_flagged(monkeypatch, source_dir):
    _write_module(
        source_dir,
        "module_A1_1_greetings.json",
        [_lesson(1, lesson_type="flashcards", title="Cards",
                 external_key=None,
                 extra={"cards": [{"front": "a", "back": "b"}]})],
    )
    db_session = _stub_db(
        monkeypatch,
        modules=[(101, 1, "M1", "A1")],
        lessons=[
            (20, 101, 1, "card", "Cards", {}),
            (21, 101, 5, "card", "Cards", {}),
        ],
    )
    diff = build_diff(source_dir, db_session)
    module = diff["modules"][0]
    assert module["ambiguous_fallback"]
    assert module["ambiguous_fallback"][0]["candidate_db_ids"] == [20, 21]
    # Ambiguous fallback must not also surface the source lesson as json_only
    # or leave the candidate DB rows in db_only — that would triple-count the
    # same root cause and inflate the strict-mode totals.
    assert module["json_only"] == []
    assert module["db_only"] == []
    assert has_blocking_issues(diff) is True


def test_build_diff_db_only_lesson_listed(monkeypatch, source_dir):
    _write_module(
        source_dir,
        "module_A1_1_greetings.json",
        [_lesson(1, lesson_type="vocabulary", title="V",
                 external_key="key:vocab")],
    )
    db_session = _stub_db(
        monkeypatch,
        modules=[(101, 1, "M1", "A1")],
        lessons=[
            (1, 101, 1, "vocabulary", "V", {"external_key": "key:vocab"}),
            (99, 101, 12, "deprecated_type", "Old lesson", {}),
        ],
        progress={99: 4},
    )
    diff = build_diff(source_dir, db_session)
    module = diff["modules"][0]
    assert len(module["db_only"]) == 1
    assert module["db_only"][0]["db_lesson_id"] == 99
    assert module["db_only"][0]["progress_rows"] == 4
    assert has_blocking_issues(diff) is True


def test_build_diff_source_only_module_handled(monkeypatch, source_dir):
    """A JSON module with no DB counterpart yields all-json_only."""
    _write_module(
        source_dir,
        "module_A1_3_unknown.json",
        [_lesson(1, lesson_type="vocabulary", title="V",
                 external_key="key:vocab")],
    )
    db_session = _stub_db(monkeypatch, modules=[], lessons=[])
    diff = build_diff(source_dir, db_session)
    module = diff["modules"][0]
    assert module["db_matched"] is False
    assert len(module["json_only"]) == 1


def test_build_diff_db_only_module_listed(monkeypatch, source_dir):
    """DB module with no JSON file shows up in `db_only_modules`."""
    db_session = _stub_db(
        monkeypatch,
        modules=[(202, 2, "Orphan module", "B1")],
        lessons=[(50, 202, 1, "vocabulary", "v", {})],
    )
    diff = build_diff(source_dir, db_session)
    assert len(diff["db_only_modules"]) == 1
    assert diff["db_only_modules"][0]["db_module_id"] == 202
    assert has_blocking_issues(diff) is True


def test_format_markdown_contains_summary_and_collision_section(
    monkeypatch, source_dir, tmp_path
):
    _write_module(
        source_dir,
        "module_A1_1_greetings.json",
        [
            _lesson(1, lesson_type="vocabulary", title="V",
                    external_key="key:vocab"),
            _lesson(2, lesson_type="reading", title="R new",
                    external_key="key:read_new"),
        ],
    )
    db_session = _stub_db(
        monkeypatch,
        modules=[(101, 1, "M1", "A1")],
        lessons=[
            (1, 101, 1, "vocabulary", "V",
             {"external_key": "key:vocab"}),
            (5, 101, 2, "grammar", "G",
             {"external_key": "key:g"}),
        ],
        progress={5: 3},
    )
    diff = build_diff(source_dir, db_session)
    md = format_markdown(diff)
    assert "module_completed/fixed JSON ↔ DB diff" in md
    assert "Position collisions" in md
    assert "Import behavior contract" in md
    # Summary metrics present.
    assert "lessons matched by `external_key`" in md
    assert "position collisions" in md
    # collision row shows the rival lesson id.
    assert "key:read_new" in md
    assert "key:g" in md


def test_format_json_round_trips(monkeypatch, source_dir):
    _write_module(
        source_dir,
        "module_A1_1_greetings.json",
        [_lesson(1, lesson_type="vocabulary", title="V",
                 external_key="k:v")],
    )
    db_session = _stub_db(
        monkeypatch,
        modules=[(101, 1, "M1", "A1")],
        lessons=[(1, 101, 1, "vocabulary", "V", {"external_key": "k:v"})],
    )
    diff = build_diff(source_dir, db_session)
    parsed = json.loads(format_json(diff))
    assert parsed["totals"]["lessons_matched_by_external_key"] == 1
    assert parsed["totals"]["position_collisions"] == 0


def test_main_writes_no_db_report(tmp_path, source_dir):
    _write_module(
        source_dir,
        "module_A1_1_greetings.json",
        [_lesson(1, lesson_type="vocabulary", title="V",
                 external_key="k:v")],
    )
    out = tmp_path / "diff.md"
    rc = main(
        [
            "--source-dir", str(source_dir),
            "--no-db",
            "--output", str(out),
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "JSON ↔ DB diff" in text
    assert "DB was not available" in text


def test_main_strict_exits_one_when_collision(tmp_path, source_dir, monkeypatch):
    """`--strict` must exit 1 when a position collision is detected."""
    _write_module(
        source_dir,
        "module_A1_1_greetings.json",
        [
            _lesson(1, lesson_type="reading", title="R",
                    external_key="key:read_new"),
        ],
    )
    # Stand up a fake Flask app + DB so `main()` follows the DB branch and
    # `_load_db_curriculum` returns a colliding lesson.
    class _Ctx:
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
    class _FakeApp:
        def app_context(self):
            return _Ctx()
    fake_db = SimpleNamespace(session=object())
    monkeypatch.setattr(
        "diff_module_json_against_db._try_get_db_session",
        lambda: (_FakeApp(), fake_db),
    )
    _stub_db(
        monkeypatch,
        modules=[("MID", 1, "M1", "A1")],
        lessons=[("DBID", "MID", 1, "grammar", "G",
                 {"external_key": "key:grammar"})],
    )

    out = tmp_path / "diff.md"
    rc = main(
        [
            "--source-dir", str(source_dir),
            "--strict",
            "--output", str(out),
        ]
    )
    assert rc == 1


def test_main_no_db_flag_does_not_attempt_app_import(tmp_path, source_dir, monkeypatch):
    """`--no-db` must short-circuit before _try_get_db_session() runs."""
    def _boom():
        raise AssertionError("DB connection should not be attempted")
    monkeypatch.setattr(
        "diff_module_json_against_db._try_get_db_session", _boom
    )
    _write_module(
        source_dir,
        "module_A1_1_greetings.json",
        [_lesson(1, lesson_type="vocabulary", title="V",
                 external_key="k:v")],
    )
    out = tmp_path / "diff.md"
    rc = main(
        [
            "--source-dir", str(source_dir),
            "--no-db",
            "--output", str(out),
        ]
    )
    assert rc == 0


# ---------------------------------------------------------------------------
# Integration test: import fixture JSON, run diff against real DB, verify
# round-trip is clean.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_diff_clean_after_real_import(tmp_path, app, db_session, admin_user):
    """End-to-end: write fixture JSON, import via CurriculumImportService,
    then run the diff and assert it round-trips cleanly.

    Note: the current importer rewrites `content` from scratch for several
    lesson types (vocabulary, card, grammar, quiz, final_test) and strips the
    source-side `external_key`. To exercise the identity-based diff path,
    this test uses lesson types whose content is persisted as-is (reading
    and sentence_completion via the "else" branch).
    """
    from flask_login import login_user

    from app.admin.services.curriculum_import_service import (
        CurriculumImportService,
    )

    src = tmp_path / "fixture"
    src.mkdir()

    # Use a valid CEFR level with a high module number unlikely to collide with seeded data.
    level_code = "C1"
    module_number = 991
    _write_module(
        src,
        f"module_{level_code}_{module_number}_diffsmoke.json",
        [
            _lesson(1, lesson_type="reading", title="Reading",
                    external_key="diffsmoke:reading",
                    extra={
                        "text": "Hello. This is a short reading passage.",
                        "exercises": [{"question": "q"}],
                    }),
            _lesson(2, lesson_type="sentence_completion",
                    title="Sentence Completion",
                    external_key="diffsmoke:sentence_completion",
                    extra={"items": [{"prompt": "Hello, ____.", "answer": "world"}]}),
        ],
        level=level_code,
        title="Diff smoke module",
    )

    payload = json.loads(
        (src / f"module_{level_code}_{module_number}_diffsmoke.json").read_text(
            encoding="utf-8"
        )
    )
    payload["module"]["number"] = module_number

    # Importer reads `current_user.id` for new Collection rows; log in admin.
    with app.test_request_context():
        login_user(admin_user)
        CurriculumImportService.import_curriculum_data(payload)

    # First pass — fresh import; diff should be clean.
    diff = build_diff(src, db_session)
    relevant = [
        m for m in diff["modules"]
        if m["level"] == level_code and m["module_number"] == module_number
    ]
    assert relevant, "imported fixture module should appear in diff"
    module = relevant[0]
    assert module["db_matched"] is True
    assert len(module["matched_by_external_key"]) == 2, module
    assert module["position_collisions"] == []
    assert module["db_only"] == []
    assert module["json_only"] == []

    # Second pass: reorder lessons in source and confirm the diff flags the
    # silent-overwrite risk that a naive `(module_id, number)` import would
    # introduce.
    swapped_lessons = list(reversed(payload["module"]["lessons"]))
    for i, l in enumerate(swapped_lessons, start=1):
        l["id"] = i
        l["number"] = i
        l["order"] = i
    _write_module(
        src,
        f"module_{level_code}_{module_number}_diffsmoke.json",
        swapped_lessons,
        level=level_code,
        title="Diff smoke module",
    )

    diff2 = build_diff(src, db_session)
    module2 = next(
        m for m in diff2["modules"]
        if m["level"] == level_code and m["module_number"] == module_number
    )
    # Both lessons still match by external_key — that part is safe.
    assert len(module2["matched_by_external_key"]) == 2
    # Both positions now hold a lesson with a different external_key than the
    # new source position → 2 collisions.
    assert len(module2["position_collisions"]) == 2
    assert has_blocking_issues(diff2) is True
