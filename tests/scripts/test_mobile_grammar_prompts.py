"""Exact local source patching and visible constraints; no database or network."""

from copy import deepcopy
import html
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.api.native_content import _question
from app.grammar_lab.models import GrammarExercise
from app.grammar_lab.prompt_manifest import PatchConflict as ManifestConflict, content_digest, validate_manifest
from app.grammar_lab.services.grader import GrammarExerciseGrader
from scripts import patch_mobile_grammar_prompts as patch

ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "MOBILE_GRAMMAR_EXERCISE_PROMPTS_20261120.json"


def manifest():
    return patch.parse_json(MANIFEST.read_bytes())


@pytest.fixture
def source_pack(tmp_path):
    pack = manifest()
    # Portable tiny sources retain the real reviewed changes, without requiring
    # ignored lesson JSON files to exist in a clean checkout.
    pack["changes"] = [
        next(change for change in pack["changes"] if change["source"] == source["path"]) for source in pack["sources"]
    ]
    for source in pack["sources"]:
        change = next(change for change in pack["changes"] if change["source"] == source["path"])
        document = {
            "level": source["level"],
            "module_id": source["module_order"],
            "grammar_topic_slug": source["grammar_topic_slug"],
            "untouched": "Keep me",
            "sessions": [
                {
                    "session_number": change["session_number"],
                    "exercises": [
                        {
                            "order": change["exercise_order"],
                            "exercise_type": change["exercise_type"],
                            "difficulty": change["difficulty"],
                            "content": deepcopy(change["content_before"]),
                        }
                    ],
                }
            ],
        }
        raw = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
        after = deepcopy(document)
        after["sessions"][0]["exercises"][0]["content"] = deepcopy(change["content_after"])
        after_raw = (json.dumps(after, ensure_ascii=False, indent=2) + "\n").encode()
        source["sha256_before"], source["sha256_after"] = patch.byte_digest(raw), patch.byte_digest(after_raw)
        source["before_final_newline"] = True
        path = tmp_path / source["path"]
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
    return tmp_path, pack


def test_local_patch_is_dry_by_default_idempotent_and_exactly_reversible(source_pack):
    root, pack = source_pack
    originals = {source["path"]: (root / source["path"]).read_bytes() for source in pack["sources"]}
    plan = patch.build_plan(root, pack)
    assert all(item.before != item.after for item in plan)
    assert all((root / name).read_bytes() == raw for name, raw in originals.items())
    backup = patch.apply_plan(plan)
    assert Path(backup).is_dir()
    assert all(item.before == item.after for item in patch.build_plan(root, pack))
    assert patch.apply_plan(patch.build_plan(root, pack)) is None
    patch.apply_plan(patch.build_plan(root, pack, rollback=True))
    assert all((root / name).read_bytes() == raw for name, raw in originals.items())
    assert all("instruction" not in change["content_before"] for change in pack["changes"])


@pytest.mark.parametrize(
    "tamper",
    ["last_file_drift", "duplicate_json_key", "symlink", "wrong_key", "new_field", "missing_presence", "outside_path"],
)
def test_entire_pack_rejects_drift_or_unreviewed_changes_before_any_write(source_pack, tamper):
    root, pack = source_pack
    first = root / pack["sources"][0]["path"]
    last = root / pack["sources"][-1]["path"]
    original = first.read_bytes()
    if tamper == "last_file_drift":
        last.write_text(last.read_text() + " ")
    elif tamper == "duplicate_json_key":
        last.write_text('{"sessions":[],"sessions":[]}')
    elif tamper == "symlink":
        last.unlink()
        last.symlink_to(first)
    elif tamper == "outside_path":
        pack["sources"][-1]["path"] = "../elsewhere.json"
    else:
        change = pack["changes"][-1]
        if tamper == "wrong_key":
            change["content_after"]["correct_answer"] = "WRONG"
            change["sha256_after"] = content_digest(change["content_after"])
        elif tamper == "new_field":
            change["content_after"]["new_answer"] = "WRONG"
            change["sha256_after"] = content_digest(change["content_after"])
        else:
            del change["fields"]["instruction"]["before_present"]
    with pytest.raises(patch.PatchConflict):
        patch.build_plan(root, pack)
    assert first.read_bytes() == original


def test_write_failure_rolls_back_owned_prior_writes(source_pack, monkeypatch):
    root, pack = source_pack
    plan = patch.build_plan(root, pack)
    original_write = patch._atomic_write
    calls = 0

    def fail_second(path, raw):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("Injected second-file write failure")
        original_write(path, raw)

    monkeypatch.setattr(patch, "_atomic_write", fail_second)
    with pytest.raises(OSError, match="Injected"):
        patch.apply_plan(plan)
    assert all(item.path.read_bytes() == item.before for item in plan)


def test_concurrent_source_change_after_preflight_refuses_all_writes(source_pack):
    root, pack = source_pack
    plan = patch.build_plan(root, pack)
    plan[-1].path.write_bytes(plan[-1].before + b" ")
    with pytest.raises(patch.PatchConflict, match="after preflight"):
        patch.apply_plan(plan)
    assert plan[0].path.read_bytes() == plan[0].before


def test_pack_has_only_79_instruction_changes_and_one_reviewed_alternative_expansion():
    pack = manifest()
    validate_manifest(pack)
    prompts = [change for change in pack["changes"] if set(change["fields"]) == {"instruction"}]
    assert len(prompts) == 79
    assert len(pack["changes"]) == 80
    for change in prompts:
        assert {key: value for key, value in change["content_before"].items() if key != "instruction"} == {
            key: value for key, value in change["content_after"].items() if key != "instruction"
        }
        assert change["fields"]["instruction"]["before_present"] is False
    alternative = next(change for change in pack["changes"] if "alternatives" in change["fields"])
    assert alternative["content_before"]["correct_answer"] == alternative["content_after"]["correct_answer"]
    exercise = SimpleNamespace(exercise_type="error_correction", content=alternative["content_after"])
    grader = GrammarExerciseGrader()
    for answer in ["if", "whether", exercise.content["correct_answer"], exercise.content["alternatives"][-1]]:
        assert grader.grade(exercise, answer)["is_correct"], answer
    for answer in ["that", "when", alternative["content_before"]["sentence"]]:
        assert not grader.grade(exercise, answer)["is_correct"], answer
    bad = deepcopy(pack)
    bad_change = next(change for change in bad["changes"] if "alternatives" in change["fields"])
    bad_change["content_after"]["alternatives"].append("that")
    bad_change["fields"]["alternatives"]["after"].append("that")
    bad_change["sha256_after"] = content_digest(bad_change["content_after"])
    with pytest.raises(ManifestConflict, match="Unreviewed"):
        validate_manifest(bad)


def _web_html(exercises):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is needed to execute the actual web renderer")
    script = r"""
const fs=require('fs'),vm=require('vm');
const context={document:{getElementById:()=>({innerHTML:'',addEventListener(){},style:{}}),addEventListener(){},querySelector:()=>null},exercises:[],topicId:null,sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},console};
vm.createContext(context); vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const rows=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(rows.map(row=>context.renderExercise(row))));
"""
    result = subprocess.run(
        [node, "-e", script, str(ROOT / "app/static/js/grammar/practice.js")],
        input=json.dumps(exercises),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_every_new_constraint_is_visible_in_actual_native_and_web_prompt_surfaces():
    rows = []
    constraints = []
    for change in manifest()["changes"]:
        if "instruction" not in change["fields"]:
            continue
        content = change["content_after"]
        exercise = SimpleNamespace(
            id=len(rows) + 1,
            topic_id=1,
            order=change["exercise_order"],
            difficulty=change["difficulty"],
            exercise_type=change["exercise_type"],
            content=content,
        )
        rows.append(GrammarExercise.to_dict(exercise, hide_answer=True))
        constraints.append(content["instruction"])
        lesson = SimpleNamespace(id=1, type="grammar", content={}, module=None)
        projected = _question(lesson, {**content, "type": change["exercise_type"]}, 0)
        assert projected["instruction"] == content["instruction"]
        source = content.get("question") or content.get("sentence") or content.get("statement")
        assert projected["prompt"] == source
        assert "correct_answer" not in projected and "alternatives" not in projected
    rendered = _web_html(rows)
    for row, constraint, markup in zip(rows, constraints, rendered, strict=True):
        assert constraint in html.unescape(markup)
        source = row.get("sentence") or row.get("statement") or row.get("question")
        assert source in html.unescape(markup)
        if row["exercise_type"] == "error_correction":
            assert "Найдите и исправьте ошибку:" not in markup


def test_new_web_instruction_is_escaped_without_hiding_the_source_phrase():
    [markup] = _web_html(
        [{"exercise_type": "fill_blank", "instruction": '<img src=x onerror="bad()"> &', "question": "I ___ here."}]
    )
    assert "<img src=x" not in markup and "&lt;img" in markup
    assert "I ___ here." in markup


def test_shared_validator_rejects_mismatched_change_module_and_duplicate_json_keys():
    pack = manifest()
    pack["changes"][0]["module_order"] = 999
    with pytest.raises(ManifestConflict, match="module metadata"):
        validate_manifest(pack)
    with pytest.raises(patch.PatchConflict, match="Duplicate JSON key"):
        patch.parse_json('{"pack": "first", "pack": "second"}')


@pytest.mark.parametrize(
    "corrupt",
    ["schema_bool", "change_level", "change_module_float", "difficulty_bool", "difficulty_string", "type_list"],
)
def test_shared_validator_rejects_malformed_identity_types(corrupt):
    pack = manifest()
    if corrupt == "schema_bool":
        pack["schema_version"] = True
    elif corrupt == "change_level":
        pack["changes"][0]["level"] = "C1"
    elif corrupt == "change_module_float":
        pack["changes"][0]["module_order"] = 16.0
    elif corrupt == "difficulty_bool":
        pack["changes"][0]["difficulty"] = True
    elif corrupt == "difficulty_string":
        pack["changes"][0]["difficulty"] = "1"
    else:
        pack["changes"][0]["exercise_type"] = []
    with pytest.raises(ManifestConflict):
        validate_manifest(pack)
