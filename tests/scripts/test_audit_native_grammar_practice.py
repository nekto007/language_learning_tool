"""Exercise audits cover actual widget transport without database reads."""

import json

from scripts import audit_native_grammar_practice as audit


def source(tmp_path, rows):
    path = tmp_path / "grammar.json"
    path.write_text(json.dumps({"level": "A1", "sessions": [{"exercises": rows}]}))
    return path


def test_repeated_order_words_are_valid_and_remain_distinct_token_ids(tmp_path):
    path = source(
        tmp_path,
        [
            {
                "exercise_type": "reorder",
                "order": 1,
                "content": {
                    "question": "Собери предложение",
                    "words": ["is", "he", "He", "?"],
                    "correct_answer": "He is he?",
                },
            }
        ],
    )
    report = audit.audit([path])
    assert report["summary"]["exercises"] == 1 and report["failures"] == []
    indexes = json.loads(audit.order_for(["is", "he", "He", "?"], "He is he?"))
    assert len(indexes) == 4 and set(indexes) == {"0", "1", "2", "3"}


def test_missing_canonical_order_token_is_a_real_audit_failure(tmp_path):
    path = source(
        tmp_path,
        [
            {
                "exercise_type": "reorder",
                "order": 1,
                "content": {
                    "question": "Собери предложение",
                    "words": ["You", "help", "me"],
                    "correct_answer": "I help you.",
                },
            }
        ],
    )
    report = audit.audit([path])
    assert report["summary"]["failures"] == 1
    assert "cannot be assembled" in report["failures"][0]["error"]


def test_duplicate_choice_labels_are_ambiguous_even_if_one_index_is_correct(tmp_path):
    path = source(
        tmp_path,
        [
            {
                "exercise_type": "multiple_choice",
                "order": 1,
                "content": {
                    "question": "I ___ here.",
                    "options": ["am", "am"],
                    "correct_answer": "am",
                },
            }
        ],
    )
    report = audit.audit([path])
    assert report["summary"]["failures"] == 1
    assert "Duplicate visible option labels" in report["failures"][0]["error"]


def test_choice_and_matching_transport_use_existing_grader(tmp_path):
    path = source(
        tmp_path,
        [
            {
                "exercise_type": "multiple_choice",
                "order": 1,
                "content": {
                    "question": "I ___ here.",
                    "options": ["is", "am", "are"],
                    "correct_answer": "am",
                },
            },
            {
                "exercise_type": "matching",
                "order": 2,
                "content": {
                    "question": "Подбери формы",
                    "pairs": [{"left": "I", "right": "am"}, {"left": "We", "right": "are"}],
                },
            },
        ],
    )
    report = audit.audit([path])
    assert report["summary"] == {"exercises": 2, "types": {"multiple_choice": 1, "matching": 1}, "failures": 0}
