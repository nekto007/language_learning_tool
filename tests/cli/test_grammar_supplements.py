"""Supplemental content rollout is additive, atomic and read-only by default."""

from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.cli.grammar_supplements import import_supplements, load_pack, validate_pack
from app.grammar_lab.models import GrammarExercise, GrammarTopic, UserGrammarExercise
from app.utils.db import db
from tests.api.test_account_deletion import native_app as _native_app
from tests.api.test_native_full_integration import learner


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


@pytest.fixture
def pack():
    value = load_pack(Path(__file__).parents[2] / "MOBILE_GRAMMAR_SUPPLEMENTS_20261120.json")
    value = deepcopy(value)
    for topic in value["topics"]:
        topic["slug"] += "-" + uuid4().hex[:8]
    return value


def save(tmp_path, pack):
    path = tmp_path / "supplements.json"
    path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    return path


def counts():
    return GrammarTopic.query.count(), GrammarExercise.query.count()


def test_cli_defaults_to_dry_run_and_does_not_create_rows(native_app, tmp_path, pack):
    before = counts()
    result = native_app.test_cli_runner().invoke(args=["grammar-supplements", str(save(tmp_path, pack))])
    assert result.exit_code == 0, result.output
    assert "DRY RUN: topics +2, exercises +40" in result.output
    assert "No database changes" in result.output
    assert counts() == before


def test_apply_twice_keeps_identical_ids_and_progress(native_app, pack):
    report = import_supplements(db.session, pack, apply=True)
    assert report.topics_to_create == 2 and report.exercises_to_create == 40
    slugs = [topic["slug"] for topic in pack["topics"]]
    topics = GrammarTopic.query.filter(GrammarTopic.slug.in_(slugs)).all()
    exercises = GrammarExercise.query.filter(GrammarExercise.topic_id.in_([row.id for row in topics])).all()
    ids = sorted(row.id for row in exercises)
    user, _ = learner(native_app)
    progress = UserGrammarExercise(user_id=user.id, exercise_id=ids[0])
    progress.state, progress.interval, progress.repetitions = "review", 17, 4
    db.session.add(progress)
    db.session.commit()
    before = counts()
    report = import_supplements(db.session, pack, apply=True)
    assert report.topics_to_create == report.exercises_to_create == 0
    assert report.topics_unchanged == 2 and report.exercises_unchanged == 40
    assert (
        sorted(row.id for row in GrammarExercise.query.filter(GrammarExercise.topic_id.in_([row.id for row in topics])))
        == ids
    )
    assert counts() == before
    db.session.refresh(progress)
    assert (progress.state, progress.interval, progress.repetitions) == ("review", 17, 4)


def test_any_unmanaged_topic_conflict_prevents_all_writes(native_app, pack):
    db.session.add(
        GrammarTopic(
            slug=pack["topics"][1]["slug"],
            title="Existing teacher material",
            title_ru="Свой материал",
            level="A2",
            content={},
        )
    )
    db.session.commit()
    before = counts()
    with pytest.raises(ValueError, match="unmanaged"):
        import_supplements(db.session, pack, apply=True)
    db.session.rollback()
    assert counts() == before
    assert GrammarTopic.query.filter_by(slug=pack["topics"][0]["slug"]).first() is None


def test_edited_owned_exercise_is_never_overwritten(native_app, pack):
    import_supplements(db.session, pack, apply=True)
    topic = GrammarTopic.query.filter_by(slug=pack["topics"][0]["slug"]).one()
    exercise = GrammarExercise.query.filter_by(topic_id=topic.id).first()
    exercise.content = {**exercise.content, "explanation": "Teacher correction that must survive"}
    db.session.commit()
    before = counts()
    with pytest.raises(ValueError):
        import_supplements(db.session, pack, apply=True)
    db.session.rollback()
    assert counts() == before
    assert db.session.get(GrammarExercise, exercise.id).content["explanation"] == "Teacher correction that must survive"


def test_extra_exercise_on_existing_topic_is_not_deleted(native_app, pack):
    import_supplements(db.session, pack, apply=True)
    topic = GrammarTopic.query.filter_by(slug=pack["topics"][0]["slug"]).one()
    exercise = GrammarExercise(
        topic_id=topic.id, exercise_type="fill_blank", content={"question": "I ___ here.", "correct_answer": "am"}
    )
    db.session.add(exercise)
    db.session.commit()
    before = counts()
    with pytest.raises(ValueError, match="Unmanaged exercise"):
        import_supplements(db.session, pack, apply=True)
    db.session.rollback()
    assert counts() == before and db.session.get(GrammarExercise, exercise.id)


def test_flush_error_rolls_back_new_topics_and_exercises(native_app, pack, monkeypatch):
    before = counts()
    original = db.session.flush
    calls = 0

    def failing_flush(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated storage failure")
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(db.session, "flush", failing_flush)
        with pytest.raises(RuntimeError, match="storage failure"):
            import_supplements(db.session, pack, apply=True)
    db.session.rollback()
    assert counts() == before


def test_cli_apply_makes_read_only_mobile_rules_available(native_app, tmp_path, pack):
    result = native_app.test_cli_runner().invoke(args=["grammar-supplements", str(save(tmp_path, pack)), "--apply"])
    assert result.exit_code == 0, result.output
    assert "APPLIED: topics +2, exercises +40" in result.output
    _, headers = learner(native_app)
    topic = GrammarTopic.query.filter_by(slug=pack["topics"][0]["slug"]).one()
    response = native_app.test_client().get(f"/api/native/grammar/topics/{topic.id}", headers=headers)
    assert response.status_code == 200, response.json
    assert response.json["topic"]["exercise_count"] == 20
    assert response.json["topic"]["theory"]


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_slug",
        "duplicate_key",
        "duplicate_order",
        "unknown_type",
        "negative_difficulty",
        "invalid_level",
        "reserved_marker",
        "missing_answer",
        "bool_schema",
    ],
)
def test_invalid_whole_pack_is_rejected_before_writes(native_app, pack, change):
    before = counts()
    if change == "duplicate_slug":
        pack["topics"][1]["slug"] = pack["topics"][0]["slug"]
    elif change == "duplicate_key":
        pack["topics"][1]["exercises"][1]["key"] = pack["topics"][1]["exercises"][0]["key"]
    elif change == "duplicate_order":
        pack["topics"][1]["exercises"][1]["order"] = pack["topics"][1]["exercises"][0]["order"]
    elif change == "unknown_type":
        pack["topics"][1]["exercises"][0]["exercise_type"] = "unknown-grader"
    elif change == "negative_difficulty":
        pack["topics"][1]["exercises"][0]["difficulty"] = -1
    elif change == "invalid_level":
        pack["topics"][1]["level"] = "C2"
    elif change == "reserved_marker":
        pack["topics"][1]["content"]["_llt_supplement"] = {}
    elif change == "missing_answer":
        del pack["topics"][1]["exercises"][0]["content"]["correct_answer"]
    else:
        pack["schema_version"] = True
    with pytest.raises(ValueError):
        import_supplements(db.session, pack, apply=True)
    db.session.rollback()
    assert counts() == before


def test_file_loader_rejects_nonfinite_json_numbers(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version":1,"topics":[],"something":NaN}')
    with pytest.raises(ValueError, match="Non-finite"):
        load_pack(path)


@pytest.mark.parametrize(
    "change",
    [
        "kind_list",
        "options_scalar",
        "options_duplicate",
        "answer_not_option",
        "pairs_scalar",
        "pairs_duplicate",
        "words_scalar",
        "words_incomplete",
        "alternatives_scalar",
        "expected_mapping",
    ],
)
def test_unrenderable_or_ungradable_exercise_shape_is_rejected(native_app, pack, change):
    before = counts()
    exercises = pack["topics"][1]["exercises"]
    choice = next(row for row in exercises if row["exercise_type"] == "multiple_choice")
    matching = next(row for row in exercises if row["exercise_type"] == "matching")
    reorder = next(row for row in exercises if row["exercise_type"] == "reorder")
    if change == "kind_list":
        exercises[0]["exercise_type"] = []
    elif change == "options_scalar":
        choice["content"]["options"] = "not a list"
    elif change == "options_duplicate":
        choice["content"]["options"] = ["one", "one"]
    elif change == "answer_not_option":
        choice["content"]["correct_answer"] = "not-an-offered-choice"
    elif change == "pairs_scalar":
        matching["content"]["pairs"] = "not pairs"
    elif change == "pairs_duplicate":
        matching["content"]["pairs"] = [matching["content"]["pairs"][0]] * 2
    elif change == "words_scalar":
        reorder["content"]["words"] = "not words"
    elif change == "words_incomplete":
        reorder["content"]["words"] = ["another", "answer"]
    elif change == "alternatives_scalar":
        exercises[0]["content"]["alternatives"] = "not a list"
    else:
        exercises[0]["content"]["correct_answer"] = {"bad": "shape"}
    with pytest.raises(ValueError):
        import_supplements(db.session, pack, apply=True)
    db.session.rollback()
    assert counts() == before


def test_loader_rejects_duplicate_object_keys(tmp_path):
    path = tmp_path / "ambiguous.json"
    path.write_text('{"schema_version":1,"schema_version":2,"topics":[]}')
    with pytest.raises(ValueError, match="Duplicate JSON"):
        load_pack(path)
