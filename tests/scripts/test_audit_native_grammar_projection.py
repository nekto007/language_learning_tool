"""The corpus audit must detect loss; it never executes Python seed files."""

import json

from scripts import audit_native_grammar_projection as audit


def test_authored_rule_example_and_table_cells_are_checked(tmp_path):
    path = tmp_path / "module.json"
    path.write_text(
        json.dumps(
            {
                "module": {
                    "level": "A1",
                    "lessons": [
                        {
                            "type": "grammar",
                            "title": "To be",
                            "content": {
                                "rule": "I + am",
                                "tldr": "Use am.",
                                "sections": [
                                    {
                                        "table": [
                                            {
                                                "pronoun": "I",
                                                "form": "am",
                                                "example": "I am here.",
                                                "translation": "Я здесь.",
                                            }
                                        ]
                                    }
                                ],
                            },
                        }
                    ],
                }
            }
        )
    )
    report = audit.audit([path])
    assert report["summary"]["grammar_lessons"] == 1
    assert report["summary"]["tables"] == 1 and report["summary"]["table_rows"] == 1
    assert report["summary"]["checked_fields"] == 6 and report["failures"] == []


def test_missing_fields_cannot_pass_the_audit(tmp_path, monkeypatch):
    path = tmp_path / "module.json"
    path.write_text(
        json.dumps(
            {
                "lessons": [
                    {
                        "type": "grammar",
                        "content": {"rule": "AUTHOR_RULE", "sections": [{"table": [{"example": "AUTHOR_EXAMPLE"}]}]},
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(audit, "_theory", lambda content: [{"title": "Rule", "body": "unrelated text"}])
    report = audit.audit([path])
    assert report["summary"]["failures"] == 1
    assert report["failures"][0]["missing"] == [
        {"field": "content.rule", "text": "AUTHOR_RULE"},
        {"field": "content.sections[0].table[0].example", "text": "AUTHOR_EXAMPLE"},
    ]


def test_seed_is_parsed_as_literal_without_running_side_effects(tmp_path):
    sentinel = tmp_path / "must-not-exist"
    path = tmp_path / "seed.py"
    path.write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('unsafe')\nA1_TOPICS = [{{'slug':'to-be','title':'To be','level':'A1','content':{{'rule':'I + am','summary_table':{{'affirmative':'I am'}}}}}}]\n"
    )
    report = audit.audit_seed(path)
    assert report["summary"]["grammar_lessons"] == 1
    assert report["summary"]["tables"] == 1
    assert report["failures"] == []
    assert not sentinel.exists()
