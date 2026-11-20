#!/usr/bin/env python3
"""Check mobile grammar projection against local authored modules, without a DB.

This verifies preservation of theory, not linguistic correctness or CEFR coverage.
Only explicit theory containers are inspected; exercise keys are never printed.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.native_lessons import _theory, plain

MEDIA = {"audio", "audio_url", "sound", "image", "image_url", "video", "video_url"}
PROSE = (
    "introduction",
    "description",
    "rule",
    "tldr",
    "formula",
    "pattern",
    "structure",
    "content",
    "body",
    "text",
    "usage",
    "important_notes",
    "notes",
    "note",
    "summary",
    "common_mistakes",
    "tips",
)
EXAMPLE = (
    "english",
    "sentence",
    "example",
    "en",
    "text",
    "russian",
    "translation",
    "example_translation",
    "ru",
    "explanation",
    "note",
    "question",
    "answer",
    "word",
)


def scalars(value, path):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() not in MEDIA:
                yield from scalars(child, path + "." + str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from scalars(child, f"{path}[{index}]")
    else:
        text = plain(value)
        if text:
            yield path, text


def expected_theory(source, path="content"):
    """Independent source walk of authored visible theory and every table cell."""
    if not isinstance(source, dict):
        return
    for field in PROSE:
        if field in source:
            yield from scalars(source[field], path + "." + field)
    for index, example in enumerate(source.get("examples") or []):
        prefix = f"{path}.examples[{index}]"
        if isinstance(example, dict):
            for field in EXAMPLE:
                if field in example:
                    yield from scalars(example[field], prefix + "." + field)
        else:
            yield from scalars(example, prefix)
    for field in ("table", "summary_table"):
        if field in source:
            yield from scalars(source[field], path + "." + field)
    for field in ("sections", "rules"):
        for index, child in enumerate(source.get(field) or []):
            if isinstance(child, dict):
                yield from expected_theory(child, f"{path}.{field}[{index}]")
            else:
                yield from scalars(child, f"{path}.{field}[{index}]")
    if isinstance(source.get("grammar_explanation"), dict):
        yield from expected_theory(source["grammar_explanation"], path + ".grammar_explanation")


def source_tables(source):
    if not isinstance(source, dict):
        return
    for field in ("table", "summary_table"):
        value = source.get(field)
        if isinstance(value, dict):
            value = (
                value.get("rows")
                or value.get("table")
                or [v for k, v in value.items() if k not in MEDIA and k != "title"]
            )
        if isinstance(value, list) and value:
            yield value
    for field in ("sections", "rules"):
        for child in source.get(field) or []:
            yield from source_tables(child)
    yield from source_tables(source.get("grammar_explanation"))


def audit_documents(documents):
    lessons = []
    failures = []
    for path, document in documents:
        try:
            module = document.get("module", document)
            source_lessons = module.get("lessons", [])
        except (ValueError, AttributeError) as exc:
            failures.append({"file": str(path), "error": type(exc).__name__})
            continue
        for lesson in source_lessons:
            if lesson.get("type") != "grammar":
                continue
            content = lesson.get("content") or {}
            record = {
                "file": str(path),
                "title": lesson.get("title"),
                "level": module.get("level"),
                "lesson": lesson.get("id") or lesson.get("order"),
            }
            try:
                blocks = _theory(content)
                visible = "\n".join(block["title"] + "\n" + block["body"] for block in blocks)
                expected = list(expected_theory(content))
                missing = [{"field": key, "text": text[:200]} for key, text in expected if text not in visible]
                tables = [block["table"] for block in blocks if block.get("table")]
                expected_rows = sum(len(table) for table in source_tables(content))
                actual_rows = sum(len(table["rows"]) for table in tables)
                invalid = [
                    table["headers"]
                    for table in tables
                    if any(len(row) != len(table["headers"]) for row in table["rows"])
                    or (any(table["headers"]) and len(set(table["headers"])) != len(table["headers"]))
                ]
                wire = len(json.dumps({"success": True, "lesson": {"theory": blocks}}, ensure_ascii=True).encode())
                record.update(
                    blocks=len(blocks),
                    tables=len(tables),
                    table_rows=actual_rows,
                    source_table_rows=expected_rows,
                    checked_fields=len(expected),
                    missing=missing,
                    ambiguous_or_ragged_headers=invalid,
                    payload_bytes=wire,
                )
                if missing or invalid or actual_rows < expected_rows or wire > 500_000:
                    failures.append(record)
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
                failures.append(record)
            lessons.append(record)
    return {
        "scope": "Preservation of authored grammar theory; no linguistic/CEFR certification.",
        "summary": {
            "grammar_lessons": len(lessons),
            "levels": dict(Counter(row.get("level") for row in lessons)),
            "checked_fields": sum(row.get("checked_fields", 0) for row in lessons),
            "tables": sum(row.get("tables", 0) for row in lessons),
            "table_rows": sum(row.get("table_rows", 0) for row in lessons),
            "max_payload_bytes": max((row.get("payload_bytes", 0) for row in lessons), default=0),
            "failures": len(failures),
        },
        "failures": failures,
        "lessons": lessons,
    }


def audit(paths):
    documents = []
    for path in paths:
        documents.append((path, json.loads(path.read_text(encoding="utf-8"))))
    return audit_documents(documents)


def audit_seed(path):
    """Read the static topic literal through AST; never execute a seed script."""
    module = ast.parse(path.read_text(encoding="utf-8"))
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "A1_TOPICS" for target in statement.targets
        ):
            topics = ast.literal_eval(statement.value)
            if not isinstance(topics, list):
                raise ValueError("A1_TOPICS must be a list literal")
            documents = [
                (
                    str(path) + ":" + topic["slug"],
                    {
                        "module": {
                            "level": topic["level"],
                            "lessons": [
                                {
                                    "id": topic["slug"],
                                    "title": topic["title"],
                                    "type": "grammar",
                                    "content": topic["content"],
                                }
                            ],
                        }
                    },
                )
                for topic in topics
            ]
            return audit_documents(documents)
    raise ValueError("Static A1_TOPICS literal not found; seed script was not executed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "module_completed" / "fixed")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=Path, help="Optional standalone A1_TOPICS Python literal; parsed with AST only")
    args = parser.parse_args(argv)
    report = audit(sorted(args.source.glob("*.json")))
    if args.seed:
        report["standalone_seed"] = audit_seed(args.seed)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: value["summary"] if key == "standalone_seed" else value
                for key, value in report.items()
                if key in ("summary", "standalone_seed")
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    valid_seed = not report.get("standalone_seed", {}).get("failures")
    return 0 if report["summary"]["grammar_lessons"] and not report["failures"] and valid_seed else 1


if __name__ == "__main__":
    raise SystemExit(main())
