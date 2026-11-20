"""Source audits distinguish structural consistency from pedagogical claims."""

import json

from scripts import audit_mobile_grammar_content as audit


def module(folder, *, name="module_A1_1_fixture.json", recap=None):
    folder.mkdir(exist_ok=True)
    data = {
        "module": {
            "level": "A1",
            "order": 1,
            "id": 1,
            "title": "Fixture",
            "lessons": [
                {
                    "id": 1,
                    "type": "grammar",
                    "title": "A rule",
                    "content": {
                        "external_key": "fixture:grammar",
                        "rule": "A clear rule",
                        "tldr": recap if recap is not None else ["A rule: <em>I am ready.</em>"],
                    },
                }
            ],
        }
    }
    (folder / name).write_text(json.dumps(data))


def extra(folder, rows):
    folder.mkdir(exist_ok=True)
    (folder / "grammar_extra_A1_1.json").write_text(
        json.dumps({"sessions": [{"session_number": 1, "exercises": rows}]})
    )


def test_empty_source_fails_instead_of_reporting_success(tmp_path):
    result = audit.audit_sources(tmp_path)
    assert result["passed"] is False
    assert result["errors"][0]["code"] == "no_module_sources"


def test_inventory_is_explicitly_not_a_semantic_or_cefr_certificate(tmp_path):
    module(tmp_path)
    result = audit.audit_sources(tmp_path)
    assert result["passed"] and result["lesson_count"] == 1
    assert result["module_count_by_level"] == {"A1": 1}
    assert result["database_access"] is False
    assert result["semantic_accuracy_certified"] is False
    assert result["official_cefr_completeness_certified"] is False


def test_empty_em_markup_is_an_error_but_heading_only_recap_is_advisory(tmp_path):
    module(tmp_path, recap=["A rule: <em></em>", "<strong>Another heading</strong>"])
    result = audit.audit_sources(tmp_path)
    assert result["passed"] is False
    assert any(x["code"] == "empty_recap_markup" for x in result["errors"])
    assert any(x["code"] == "heading_only_recap" for x in result["warnings"])


def test_duplicate_module_identity_is_reported_even_if_filenames_differ(tmp_path):
    module(tmp_path)
    module(tmp_path, name="module_A1_1_another.json")
    result = audit.audit_sources(tmp_path)
    assert any(x["code"] == "duplicate_module_identity" for x in result["errors"])


def test_duplicate_options_and_missing_choice_keys_are_reported(tmp_path):
    source = tmp_path / "modules"
    extras = tmp_path / "extras"
    module(source)
    extra(
        extras,
        [
            {
                "order": 1,
                "exercise_type": "multiple_choice",
                "content": {"question": "Choose", "correct_answer": "am", "options": ["am", "Am.", "is"]},
            },
            {
                "order": 2,
                "exercise_type": "multiple_choice",
                "content": {"question": "Choose", "correct_answer": "were", "options": ["am", "is", "are"]},
            },
        ],
    )
    result = audit.audit_sources(source, extras)
    assert result["extra_exercises"] == 2
    assert {x["code"] for x in result["errors"]} == {"duplicate_options", "choice_key_not_in_options"}


def test_false_expected_answer_is_not_missing_and_real_grader_runs_in_memory(tmp_path):
    source = tmp_path / "modules"
    extras = tmp_path / "extras"
    module(source)
    extra(
        extras,
        [
            {
                "order": 1,
                "exercise_type": "true_false",
                "content": {
                    "statement": "I is ready is correct.",
                    "correct_answer": False,
                    "explanation": "I takes am.",
                },
            },
            {
                "order": 2,
                "exercise_type": "fill_blank",
                "content": {
                    "question": "I ___ here.",
                    "correct_answer": "am",
                    "alternatives": ["I am here."],
                    "explanation": "I takes am.",
                },
            },
        ],
    )
    result = audit.audit_sources(source, extras, grade=True)
    assert result["passed"], result["errors"]
    assert result["graded_answers"] == 3 and result["extra_alternatives"] == 1


def test_absent_requested_extra_sources_are_an_error(tmp_path):
    module(tmp_path)
    result = audit.audit_sources(tmp_path, tmp_path / "absent")
    assert result["passed"] is False
    assert any(x["code"] == "no_extra_sources" for x in result["errors"])


def test_cli_does_not_rewrite_sources_and_report_records_read_only_scope(tmp_path):
    module(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    output = tmp_path / "audit.json"
    assert audit.main(["--source-dir", str(tmp_path), "--skip-extras", "--output", str(output)]) == 0
    for name, data in before.items():
        assert (tmp_path / name).read_bytes() == data
    assert json.loads(output.read_text())["scope"] == "local_source_only"
