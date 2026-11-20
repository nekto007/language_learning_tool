# ruff: noqa: RUF001, RUF003
"""Grammar projection is presentation-only; tests never connect to production."""

from copy import deepcopy
import json
from uuid import uuid4

import pytest

from app.api.native_lessons import NativeLessonError, _theory
from tests.api.test_native_lessons import native_context as _native_context, fetch
from tests.api.test_account_deletion import native_app as _native_app
from tests.api.test_native_full_integration import learner


@pytest.fixture
def native_context(monkeypatch):
    return _native_context.__wrapped__(monkeypatch)


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


def fixture_content():
    return {
        "title": "To be",
        "description": "<p>Три формы глагола</p>",
        "rule": "I am; he is; we are.",
        "tldr": "После I — am.",
        "sections": [
            {
                "subtitle": "Утверждение",
                "description": "Выбери форму по подлежащему.",
                "table": [
                    {
                        "pronoun": "I",
                        "verb": "am",
                        "example": "I am at home.",
                        "translation": "Я дома.",
                        "audio": "hidden.mp3",
                    },
                    {"pronoun": "We", "verb": "are", "example": "We are here.", "translation": "Мы здесь."},
                ],
                "rules": [
                    {
                        "rule": "Форма не сокращается в кратком утвердительном ответе.",
                        "examples": [{"english": "Yes, I am.", "russian": "Да."}],
                        "note": "В кратком ответе am остаётся полным.",
                    }
                ],
                "note": "Сокращение I’m допустимо в полном предложении.",
            }
        ],
        "examples": [{"english": "They are ready.", "russian": "Они готовы.", "explanation": "They + are."}],
        "important_notes": ["На русский to be часто не переводится."],
        "summary": "Выбирай am, is или are.",
        "exercises": [{"question": "Hidden exam question", "answer": "hidden-answer-key"}],
        "transcript": "hidden-listening-transcript",
    }


def test_rule_tldr_every_table_cell_and_translations_survive_without_mutation():
    content = fixture_content()
    original = deepcopy(content)
    blocks = _theory(content)
    bodies = "\n".join(block["body"] for block in blocks)
    for text in [
        "I am; he is; we are.",
        "После I — am.",
        "Я дома.",
        "Мы здесь.",
        "Yes, I am.",
        "Они готовы.",
        "They + are.",
        "На русский to be часто не переводится.",
        "В кратком ответе am остаётся полным.",
    ]:
        assert text in bodies
    tables = [block["table"] for block in blocks if block.get("kind") == "table"]
    assert tables == [
        {
            "headers": ["Местоимение", "Глагол", "Пример", "Перевод"],
            "rows": [["I", "am", "I am at home.", "Я дома."], ["We", "are", "We are here.", "Мы здесь."]],
        }
    ]
    examples = [example for block in blocks for example in block.get("examples", [])]
    assert {"english": "They are ready.", "translation": "Они готовы.", "explanation": "They + are."} in examples
    assert content == original
    encoded = json.dumps(blocks)
    assert all(
        value not in encoded
        for value in ["hidden.mp3", "hidden-answer-key", "Hidden exam question", "hidden-listening-transcript"]
    )


def test_structured_blocks_do_not_hide_unique_prose_from_new_clients():
    blocks = _theory(fixture_content())
    table = next(block for block in blocks if block.get("kind") == "table")
    assert "Выбери форму по подлежащему." not in table["body"]
    assert any(block["body"] == "Выбери форму по подлежащему." and block["kind"] == "text" for block in blocks)
    example = next(block for block in blocks if block.get("kind") == "examples" and "They are ready." in block["body"])
    assert "На русский" not in example["body"]


def test_named_columns_preserve_headers_order_and_unlisted_authored_cells():
    blocks = _theory(
        {
            "sections": [
                {
                    "title": "Формы",
                    "table": {
                        "columns": [{"key": "form", "label": "Вид формы"}, {"key": "example", "label": "Образец"}],
                        "rows": [
                            {
                                "form": "am",
                                "example": "I am here.",
                                "translation": "Я здесь.",
                                "audio_url": "/secret.mp3",
                            }
                        ],
                    },
                }
            ]
        }
    )
    assert blocks[0]["table"] == {
        "headers": ["Вид формы", "Образец", "Перевод"],
        "rows": [["am", "I am here.", "Я здесь."]],
    }


def test_author_headers_and_short_rows_are_padded_without_losing_cells():
    block = _theory({"table": {"headers": ["Лицо", "Форма"], "rows": [["I", "am"], ["They"]]}})[0]
    assert block["table"] == {"headers": ["Лицо", "Форма"], "rows": [["I", "am"], ["They", ""]]}
    assert "Лицо · Форма" in block["body"]


def test_wrapped_theory_keeps_english_russian_examples_and_legacy_fields():
    blocks = _theory(
        {
            "grammar_explanation": {
                "rule": "Use an auxiliary.",
                "examples": [{"english": "Do you work?", "russian": "Ты работаешь?"}],
            },
            "examples": [{"sentence": "I do.", "translation": "Да."}],
        }
    )
    visible = "\n".join(block["body"] for block in blocks)
    assert all(value in visible for value in ["Use an auxiliary.", "Do you work?", "Ты работаешь?", "I do.", "Да."])
    assert all(block["title"] and block["body"] for block in blocks)


def test_html_entities_scripts_and_metadata_never_escape_as_markup():
    blocks = _theory(
        {
            "description": "<style>hidden-style</style><script>hidden-script</script><p>I &amp; you<br>Мы &lt;учимся&gt;</p>",
            "table": [{"example": "<b>I am.</b>", "translation": "<p>Я есть.</p>", "audio": "not-visible"}],
        }
    )
    rendered = "\n".join(block["body"] for block in blocks)
    assert "I & you" in rendered and "I am." in rendered and "Я есть." in rendered
    assert all(value not in rendered for value in ["hidden-script", "hidden-style", "<b>", "<p>", "not-visible"])


@pytest.mark.parametrize(
    "content",
    [
        {"sections": [{"description": "x"}] * 101},
        {"table": [["x"]] * 101},
        {"table": [[str(i) for i in range(25)]]},
        {"sections": "malformed"},
    ],
)
def test_oversized_or_malformed_theory_fails_explicitly_instead_of_truncating(content):
    with pytest.raises(NativeLessonError) as failure:
        _theory(content)
    assert failure.value.code == "unsupported_lesson" and failure.value.status == 422


def test_wire_payload_budget_includes_legacy_and_structured_unicode_copies():
    # 100 rows × 1,000 Cyrillic characters is below 200k visible characters,
    # but far above the safe wire size when escaped and repeated as cells.
    with pytest.raises(NativeLessonError):
        _theory({"table": [[str(index), "я" * 1000] for index in range(100)]})


def test_theory_only_native_course_keeps_no_fabricated_score(native_context):
    native_context.lesson.content = fixture_content()
    native_context.lesson.content["exercises"] = []
    lesson = fetch(native_context)
    assert lesson["questions"] == []
    assert any(block.get("kind") == "table" for block in lesson["theory"])
    response = native_context.client.post(
        "/api/native/lessons/42/submit",
        headers=native_context.headers,
        json={"session_token": lesson["session_token"], "answers": {}},
    )
    assert response.status_code == 200
    assert response.json["score"] is None and response.json["total_count"] == 0


def test_read_only_topic_material_does_not_create_learning_records(native_app):
    from app.grammar_lab.models import (
        GrammarTopic,
        GrammarExercise,
        UserGrammarTopicStatus,
        GrammarAttempt,
        UserGrammarExercise,
    )
    from app.study.models import StudySession, NativeLearningRun
    from app.utils.db import db

    user, headers = learner(native_app)
    topic = GrammarTopic(
        slug="material-" + uuid4().hex, title="To be", title_ru="Глагол to be", level="A1", content=fixture_content()
    )
    db.session.add(topic)
    db.session.commit()
    models = [UserGrammarTopicStatus, UserGrammarExercise, GrammarAttempt, StudySession, NativeLearningRun]
    before = [model.query.filter_by(user_id=user.id).count() for model in models]
    response = native_app.test_client().get(f"/api/native/grammar/topics/{topic.id}", headers=headers)
    assert response.status_code == 200, response.json
    value = response.json["topic"]
    assert value["id"] == topic.id and value["exercise_count"] == 0
    assert any(block["kind"] == "table" for block in value["theory"])
    assert [model.query.filter_by(user_id=user.id).count() for model in models] == before
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "Set-Cookie" not in response.headers
    exercise = GrammarExercise(
        topic_id=topic.id,
        exercise_type="fill_blank",
        content={"question": "I ___ here.", "correct_answer": "am"},
        difficulty=1,
    )
    db.session.add(exercise)
    db.session.flush()
    progress = UserGrammarExercise(user_id=user.id, exercise_id=exercise.id)
    progress.session_attempts = 3
    progress.state = "review"
    progress.interval = 20
    db.session.add(progress)
    db.session.commit()
    db.session.refresh(progress)
    before = (progress.session_attempts, progress.state, progress.interval, progress.next_review)
    response = native_app.test_client().get(f"/api/native/grammar/topics/{topic.id}", headers=headers)
    assert response.json["topic"]["exercise_count"] == 1
    db.session.refresh(progress)
    assert (progress.session_attempts, progress.state, progress.interval, progress.next_review) == before


def test_topic_material_hides_nonpublic_levels_and_requires_bearer(native_app):
    from app.grammar_lab.models import GrammarTopic
    from app.utils.db import db

    _user, headers = learner(native_app)
    hidden = GrammarTopic(
        slug="hidden-" + uuid4().hex,
        title="Private",
        title_ru="Закрытая тема",
        level="C2",
        content={"rule": "hidden-rule"},
    )
    db.session.add(hidden)
    db.session.commit()
    client = native_app.test_client()
    assert client.get(f"/api/native/grammar/topics/{hidden.id}", headers=headers).status_code == 404
    assert client.get("/api/native/grammar/topics/2147483647", headers=headers).status_code == 404
    assert client.get(f"/api/native/grammar/topics/{hidden.id}").status_code == 401


@pytest.mark.parametrize("kind", ["fill-in-blank", "transformation"])
def test_simple_grammar_aliases_supported_by_the_grader_are_not_rejected(native_context, kind):
    from tests.api.test_native_lessons import submit

    native_context.lesson.content = {"exercises": [{"type": kind, "prompt": "I ___ ready.", "answer": "am"}]}
    lesson = fetch(native_context)
    assert lesson["questions"][0]["prompt"] == "I ___ ready."
    response = submit(native_context, lesson["session_token"], {"0": "am"})
    assert response.status_code == 200 and response.json["correct_count"] == 1


@pytest.mark.parametrize("kind", ["fill_blank", "fill-blank", "fill_in_blank", "fill-in-blank"])
def test_authored_grammar_choice_is_rendered_and_graded_as_selected_text(native_context, kind):
    from app.api.native_content import grade

    native_context.lesson.content = {
        "exercises": [{"type": kind, "question": "I ___ ready.", "options": ["is", "am", "are"], "answer": "am"}]
    }
    lesson = fetch(native_context)
    question = lesson["questions"][0]
    assert question["input"] == "choice" and {option["label"] for option in question["options"]} == {"is", "am", "are"}
    assert "answer" not in question and "correct_answer" not in question
    selected = next(option["value"] for option in question["options"] if option["label"] == "am")
    result, feedback, _, completed = grade(native_context.lesson, lesson["questions"], {"0": selected}, 70)
    assert result["score"] == 100 and completed
    assert feedback[0]["answer"] == "am"


def test_reorder_tokens_use_native_builder_and_readable_feedback(native_context):
    from app.api.native_content import grade

    native_context.lesson.content = {
        "exercises": [
            {"type": "reorder", "question": "Собери предложение", "words": ["ready", "am", "I"], "answer": "I am ready"}
        ]
    }
    lesson = fetch(native_context)
    question = lesson["questions"][0]
    assert question["input"] == "order"
    positions = {option["label"]: option["value"] for option in question["options"]}
    result, feedback, _, completed = grade(
        native_context.lesson,
        lesson["questions"],
        {"0": json.dumps([positions[word] for word in ["I", "am", "ready"]])},
        70,
    )
    assert result["score"] == 100 and completed
    assert feedback[0]["answer"] == "I am ready"


def test_reorder_invalid_nested_indexes_are_a_client_error_not_a_server_crash(native_context):
    from tests.api.test_native_lessons import submit

    native_context.lesson.content = {
        "exercises": [{"type": "reorder", "question": "Собери предложение", "words": ["I", "am"], "answer": "I am"}]
    }
    lesson = fetch(native_context)
    response = submit(native_context, lesson["session_token"], {"0": '[{"bad":1},"1"]'})
    assert response.status_code == 400 and response.json["error"] == "invalid_input"
    assert native_context.writes == []


@pytest.mark.parametrize(
    ("kind", "content", "answer"),
    [
        ("fill_blank", {"question": "I ___ ready.", "options": ["are", "am", "is"], "correct_answer": "am"}, "am"),
        (
            "multiple_choice",
            {"question": "She ___ here.", "options": ["am", "is", "are"], "correct_answer": "is"},
            "is",
        ),
        (
            "transformation",
            {"question": "Make it negative: I am late.", "correct_answer": "I am not late."},
            "I am not late.",
        ),
        (
            "error_correction",
            {"question": "She are here.", "correct_answer": "is", "full_correct": "She is here."},
            "She is here.",
        ),
        ("translation", {"question": "Я дома.", "correct_answer": "I am at home."}, "I am at home."),
        ("true_false", {"question": "I is ready. — Correct?", "correct_answer": False}, "false"),
        (
            "reorder",
            {"question": "Собери предложение", "words": ["ready", "are", "We"], "correct_answer": "We are ready."},
            "We are ready",
        ),
        (
            "matching",
            {"question": "Подбери формы", "pairs": [{"left": "I", "right": "am"}, {"left": "We", "right": "are"}]},
            None,
        ),
    ],
)
def test_native_lab_all_eight_formats_use_the_existing_grader(native_app, kind, content, answer):
    from app.grammar_lab.models import GrammarTopic, GrammarExercise, GrammarAttempt
    from app.utils.db import db

    user, headers = learner(native_app)
    topic = GrammarTopic(
        slug="format-" + uuid4().hex,
        title="To be",
        title_ru="Глагол to be",
        level="A1",
        content={"rule": "Use am, is or are."},
    )
    db.session.add(topic)
    db.session.flush()
    exercise = GrammarExercise(topic_id=topic.id, exercise_type=kind, content=content, difficulty=1)
    db.session.add(exercise)
    db.session.commit()
    client = native_app.test_client()
    response = client.post(
        "/api/native/activities/grammar_topic/start",
        headers=headers,
        json={"item_id": f"grammar_topic:{topic.id}", "request_id": str(uuid4())},
    )
    assert response.status_code == 200, response.json
    lesson = response.json["lesson"]
    question = lesson["questions"][0]
    assert "correct_answer" not in question and "answer" not in question
    if question["input"] == "choice":
        answer = next(
            option["value"] for option in question["options"] if option["label"] == answer or option["value"] == answer
        )
    elif question["input"] == "match":
        answer = json.dumps({option["value"]: option["value"] for option in question["left_options"]})
    elif question["input"] == "order":
        positions = {option["label"]: option["value"] for option in question["options"]}
        answer = json.dumps([positions[word] for word in answer.split()])
    response = client.post(
        "/api/native/activities/grammar_topic/submit",
        headers=headers,
        json={"session_token": lesson["session_token"], "answers": {"0": answer}},
    )
    assert response.status_code == 200 and response.json["correct_count"] == 1, response.json
    assert GrammarAttempt.query.filter_by(user_id=user.id, exercise_id=exercise.id).count() == 1
    if kind == "matching":
        assert response.json["feedback"][0]["answer"] == "I → am\nWe → are"
        assert response.json["feedback"][0]["expected"] == "I → am\nWe → are"
        assert "{'left':" not in str(response.json["feedback"])


def test_unsupported_activity_projection_does_not_commit_a_broken_run(native_app):
    from app.grammar_lab.models import GrammarTopic, GrammarExercise
    from app.study.models import StudySession, NativeLearningRun
    from app.utils.db import db

    user, headers = learner(native_app)
    topic = GrammarTopic(
        slug="unsupported-" + uuid4().hex,
        title="Malformed import",
        title_ru="Некорректный импорт",
        level="A1",
        content={"rule": "Read the rule."},
    )
    db.session.add(topic)
    db.session.flush()
    db.session.add(
        GrammarExercise(
            topic_id=topic.id,
            exercise_type="future_unsupported",
            content={"question": "Unrenderable.", "correct_answer": "yes"},
            difficulty=1,
        )
    )
    db.session.commit()
    response = native_app.test_client().post(
        "/api/native/activities/grammar_topic/start",
        headers=headers,
        json={"item_id": f"grammar_topic:{topic.id}", "request_id": str(uuid4())},
    )
    assert response.status_code == 422 and response.json["error"] == "unsupported_lesson"
    assert NativeLearningRun.query.filter_by(user_id=user.id).count() == 0
    assert StudySession.query.filter_by(user_id=user.id).count() == 0


def test_matching_course_feedback_uses_labels_and_preserves_server_grade(native_context):
    from app.api.native_content import grade

    native_context.lesson.content = {
        "exercises": [
            {
                "type": "matching",
                "question": "Подбери формы",
                "pairs": [{"left": "I", "right": "am"}, {"left": "We", "right": "are"}],
            }
        ]
    }
    lesson = fetch(native_context)
    result, feedback, _, completed = grade(native_context.lesson, lesson["questions"], {"0": '{"0":"1","1":"0"}'}, 70)
    assert result["score"] == 0 and not completed
    assert feedback[0]["answer"] == "I → are\nWe → am"
    assert feedback[0]["expected"] == "I → am\nWe → are"


@pytest.mark.parametrize(
    "rows", [5, ["malformed row"], [{"type": "reorder", "question": "x", "words": ["", "I"], "answer": "I"}]]
)
def test_malformed_authored_exercises_return_422_without_internal_exception(native_context, rows):
    native_context.lesson.content = {"exercises": rows}
    response = native_context.client.get("/api/native/lessons/42", headers=native_context.headers)
    assert response.status_code == 422 and response.json["error"] == "unsupported_lesson"


@pytest.mark.parametrize("old_version", [None, 1])
def test_old_course_projection_token_fails_before_grading_but_completed_receipt_replays(native_context, old_version):
    from tests.api.test_native_lessons import submit
    from app.api.native_lessons import _signer

    document = fetch(native_context)
    with native_context.app.app_context():
        sealed = _signer().loads(document["session_token"])
        if old_version is None:
            sealed.pop("projection_version")
        else:
            sealed["projection_version"] = old_version
        old_token = _signer().dumps(sealed)
    response = submit(native_context, old_token)
    assert response.status_code == 409 and response.json["error"] == "lesson_changed"
    assert native_context.writes == []
    completed = submit(native_context, document["session_token"])
    assert completed.status_code == 200
    before = len(native_context.writes)
    replay = submit(native_context, old_token)
    assert replay.json == completed.json
    assert len(native_context.writes) == before


@pytest.mark.parametrize("old_version", [None, 1])
def test_old_activity_token_requires_reopen_and_completed_receipt_still_replays(native_app, old_version):
    from app.api.native_activities import _signer
    from app.grammar_lab.models import GrammarTopic, GrammarExercise, GrammarAttempt, UserGrammarExercise
    from app.study.models import NativeLearningRun
    from app.utils.db import db

    user, headers = learner(native_app)
    topic = GrammarTopic(
        slug="version-" + uuid4().hex, title="To be", title_ru="Глагол to be", level="A1", content={"rule": "I + am."}
    )
    db.session.add(topic)
    db.session.flush()
    exercise = GrammarExercise(
        topic_id=topic.id,
        exercise_type="fill_blank",
        content={"question": "I ___ ready.", "correct_answer": "am"},
        difficulty=1,
    )
    db.session.add(exercise)
    db.session.commit()
    client = native_app.test_client()
    start_body = {"item_id": f"grammar_topic:{topic.id}", "request_id": str(uuid4())}
    document = client.post("/api/native/activities/grammar_topic/start", headers=headers, json=start_body).json[
        "lesson"
    ]
    sealed = _signer().loads(document["session_token"])
    if old_version is None:
        sealed.pop("projection_version")
    else:
        sealed["projection_version"] = old_version
    old_token = _signer().dumps(sealed)
    progress = UserGrammarExercise.query.filter_by(user_id=user.id, exercise_id=exercise.id).one()
    before = (progress.state, progress.interval, progress.repetitions, progress.session_attempts)
    old_submit = {"session_token": old_token, "answers": {"0": "am"}}
    response = client.post("/api/native/activities/grammar_topic/submit", headers=headers, json=old_submit)
    assert response.status_code == 409 and response.json["error"] == "lesson_changed"
    db.session.refresh(progress)
    assert (progress.state, progress.interval, progress.repetitions, progress.session_attempts) == before
    assert GrammarAttempt.query.filter_by(user_id=user.id).count() == 0
    reopened = client.post("/api/native/activities/grammar_topic/start", headers=headers, json=start_body)
    assert reopened.status_code == 200
    assert _signer().loads(reopened.json["lesson"]["session_token"])["projection_version"] == 2
    assert NativeLearningRun.query.filter_by(user_id=user.id).count() == 1
    response = client.post(
        "/api/native/activities/grammar_topic/submit",
        headers=headers,
        json={"session_token": reopened.json["lesson"]["session_token"], "answers": {"0": "am"}},
    )
    assert response.status_code == 200 and response.json["correct_count"] == 1
    replay = client.post("/api/native/activities/grammar_topic/submit", headers=headers, json=old_submit)
    assert replay.json == response.json
    assert GrammarAttempt.query.filter_by(user_id=user.id).count() == 1


def test_standalone_seed_question_answer_and_word_examples_are_preserved():
    blocks = _theory(
        {
            "sections": [
                {
                    "subtitle": "Вопрос и ответ",
                    "examples": [
                        {
                            "question": "Do you work?",
                            "answer": "Yes, I do. / No, I do not.",
                            "translation": "Ты работаешь?",
                        },
                        {"word": "every day/week/month", "example": "I walk every day."},
                    ],
                }
            ]
        }
    )
    examples = blocks[0]["examples"]
    assert examples[0] == {
        "english": "Do you work?",
        "translation": "Ты работаешь?",
        "explanation": "Ответ: Yes, I do. / No, I do not.",
    }
    assert examples[1]["english"] == "every day/week/month\nI walk every day."
    for block in blocks:
        assert all(part in block["body"] for example in block["examples"] for part in example.values() if part)


def test_summary_mapping_and_summary_table_wrapper_keep_all_formulas():
    blocks = _theory(
        {
            "summary_table": {
                "affirmative": "Subject + am/is/are",
                "negative": "Subject + am/is/are + not",
                "question": "Am/is/are + subject?",
            }
        }
    )
    assert blocks[0]["table"] == {
        "headers": ["Форма", "Схема"],
        "rows": [
            ["Утверждение", "Subject + am/is/are"],
            ["Отрицание", "Subject + am/is/are + not"],
            ["Вопрос", "Am/is/are + subject?"],
        ],
    }
    wrapped = _theory({"summary_table": {"title": "Краткие формы", "table": [{"subject": "I", "affirmative": "am"}]}})
    assert wrapped[0]["title"] == "Краткие формы"
    assert wrapped[0]["table"]["rows"] == [["I", "am"]]


def test_topic_catalogue_counts_exercises_in_one_query(native_app):
    from sqlalchemy import event
    from app.grammar_lab.models import GrammarTopic, GrammarExercise
    from app.utils.db import db

    _user, headers = learner(native_app)
    expected = {}
    for index in range(4):
        topic = GrammarTopic(
            slug="count-" + uuid4().hex,
            title="To be",
            title_ru="Глагол to be",
            level="A1",
            order=index,
            content={"rule": "I + am."},
        )
        db.session.add(topic)
        db.session.flush()
        expected[topic.id] = index
        for _ in range(index):
            db.session.add(
                GrammarExercise(
                    topic_id=topic.id,
                    exercise_type="fill_blank",
                    content={"question": "I ___ here.", "correct_answer": "am"},
                    difficulty=1,
                )
            )
    db.session.commit()
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if "from grammar_exercises" in " ".join(statement.lower().split()):
            statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", capture)
    try:
        response = native_app.test_client().get("/api/native/grammar/topics", headers=headers)
    finally:
        event.remove(db.engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    counts = {topic["id"]: topic["exercise_count"] for topic in response.json["topics"]}
    assert {key: counts[key] for key in expected} == expected
    assert len(statements) == 1, statements
