"""Stdlib-only validation of the narrowly reviewed grammar prompt rollout pack."""

from __future__ import annotations

import hashlib
import json

ALLOWED_SOURCES = frozenset(
    {
        "grammar_exercises_extra/grammar_extra_B1_16.json",
        "grammar_exercises_extra/grammar_extra_B2_8.json",
    }
)


class PatchConflict(ValueError):
    """A source or pack differs from the explicitly reviewed state."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PatchConflict(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeDecodeError) as error:
        raise PatchConflict(f"Invalid JSON: {error}") from error


def content_digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def byte_digest(value):
    return hashlib.sha256(value).hexdigest()


def validate_manifest(manifest):
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != 1
        or manifest.get("pack") != "grammar-prompt-constraints-20261120"
        or manifest.get("allowed_fields") != ["instruction", "alternatives"]
    ):
        raise PatchConflict("Unsupported prompt-only manifest")
    sources = manifest.get("sources")
    changes = manifest.get("changes")
    if not isinstance(sources, list) or not isinstance(changes, list) or not changes:
        raise PatchConflict("Missing sources or changes")
    paths = [item.get("path") for item in sources if isinstance(item, dict)]
    if (
        len(paths) != len(sources)
        or any(not isinstance(path, str) for path in paths)
        or len(paths) != len(set(paths))
        or set(paths) != ALLOWED_SOURCES
    ):
        raise PatchConflict("Only the two reviewed source paths are allowed")
    expected_sources = {
        "grammar_exercises_extra/grammar_extra_B1_16.json": ("B1", 16, "conditionals-intro"),
        "grammar_exercises_extra/grammar_extra_B2_8.json": ("B2", 8, "reported-questions"),
    }
    for source in sources:
        identity = (source.get("level"), source.get("module_order"), source.get("grammar_topic_slug"))
        if type(source.get("module_order")) is not int or identity != expected_sources[source["path"]]:
            raise PatchConflict("Source module identity is outside the reviewed pack")
        for side in ("before", "after"):
            value = source.get(f"sha256_{side}")
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise PatchConflict("Invalid source SHA-256")
        if type(source.get("before_final_newline")) is not bool:
            raise PatchConflict("Original newline state must be explicit")
    sources_by_path = {source["path"]: source for source in sources}
    seen = set()
    for change in changes:
        if not isinstance(change, dict) or change.get("source") not in ALLOWED_SOURCES:
            raise PatchConflict("Unreviewed change path")
        identity = (change["source"], change.get("session_number"), change.get("exercise_order"))
        if any(type(value) is not int or value < 1 for value in identity[1:]) or identity in seen:
            raise PatchConflict("Missing or duplicate exercise identity")
        seen.add(identity)
        source = sources_by_path[change["source"]]
        if type(change.get("module_order")) is not int or any(
            change.get(key) != source[key] for key in ("level", "module_order", "grammar_topic_slug")
        ):
            raise PatchConflict("Change module metadata does not match its reviewed source")
        if (
            not isinstance(change.get("exercise_type"), str)
            or change["exercise_type"]
            not in {"fill_blank", "multiple_choice", "true_false", "translation", "error_correction"}
            or type(change.get("difficulty")) is not int
            or not 1 <= change["difficulty"] <= 3
        ):
            raise PatchConflict("Invalid reviewed exercise type/difficulty")
        before, after, fields = change.get("content_before"), change.get("content_after"), change.get("fields")
        if not isinstance(before, dict) or not isinstance(after, dict) or not isinstance(fields, dict):
            raise PatchConflict("Missing before/after content")
        if set(fields) not in ({"instruction"}, {"alternatives"}):
            raise PatchConflict("Only reviewed instruction or narrow alternative exception may change")
        field_name = next(iter(fields))
        if field_name == "alternatives" and (
            identity != ("grammar_exercises_extra/grammar_extra_B2_8.json", 7, 8)
            or change.get("exercise_type") != "error_correction"
            or before.get("sentence") != "My supervisor asked me that I could work overtime the following weekend."
            or before.get("correct_answer") != "My supervisor asked me if I could work overtime the following weekend."
            or before.get("alternatives") != ["if"]
            or after.get("alternatives")
            != ["if", "whether", "My supervisor asked me whether I could work overtime the following weekend."]
        ):
            raise PatchConflict("Unreviewed accepted-alternative exception")
        field = fields[field_name]
        if not isinstance(field, dict):
            raise PatchConflict("Invalid instruction presence metadata")
        for side, content in [("before", before), ("after", after)]:
            if type(field.get(f"{side}_present")) is not bool:
                raise PatchConflict("Field presence must be explicit")
            if (
                field[f"{side}_present"] != (field_name in content)
                or field.get(side) != content.get(field_name)
                or content_digest(content) != change.get(f"sha256_{side}")
            ):
                raise PatchConflict("Instruction metadata or content hash changed")
        neutral_before = {key: value for key, value in before.items() if key != field_name}
        neutral_after = {key: value for key, value in after.items() if key != field_name}
        if neutral_before != neutral_after or before == after:
            raise PatchConflict("Answer-bearing or unrelated content changed")
        instruction = after.get(field_name)
        if field_name == "instruction" and (not isinstance(instruction, str) or not instruction.strip()):
            raise PatchConflict("New instruction must be nonempty text")
    for source in sources:
        if not any(change["source"] == source["path"] for change in changes):
            raise PatchConflict("Source has no reviewed changes")
    return sources, changes
