"""In-place prompt rollout is tested only against a disposable SQLite database."""

from copy import deepcopy
from pathlib import Path

import pytest

from app.cli.grammar_prompts import grammar_prompts_command, load_manifest, patch_prompts
from app.grammar_lab.models import GrammarExercise, GrammarTopic, UserGrammarExercise
from app.utils.db import db
from tests.api.test_account_deletion import native_app as _native_app
from tests.api.test_native_full_integration import learner

ROOT = Path(__file__).parents[2]
PACK = ROOT / "MOBILE_GRAMMAR_EXERCISE_PROMPTS_20261120.json"


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


@pytest.fixture
def pack(native_app):
    db.session.rollback()
    UserGrammarExercise.query.delete()
    GrammarExercise.query.delete()
    GrammarTopic.query.delete()
    db.session.commit()
    document = load_manifest(PACK)
    # Small focused subset still uses the real per-source identity contract.
    document["changes"] = [
        next(change for change in document["changes"] if change["source"] == source["path"])
        for source in document["sources"]
    ] + [next(change for change in document["changes"] if "alternatives" in change["fields"])]
    return document


def seeded(pack):
    topics = {}
    for source in pack["sources"]:
        topic = GrammarTopic(
            slug=f"{source['level'].lower()}-{source['module_order']}",
            level=source["level"],
            title="Disposable practice",
            title_ru="Проверка",
            content={"theory": "Keep rules"},
        )
        db.session.add(topic)
        db.session.flush()
        topics[source["path"]] = topic
    result = []
    for change in pack["changes"]:
        exercise = GrammarExercise(
            topic_id=topics[change["source"]].id,
            exercise_type=change["exercise_type"],
            order=change["exercise_order"],
            difficulty=change["difficulty"],
            content={**deepcopy(change["content_before"]), "source": "json_import"},
        )
        db.session.add(exercise)
        result.append(exercise)
    db.session.commit()
    return result


def test_default_preflight_and_missing_targets_are_read_only(native_app, pack):
    report = patch_prompts(db.session, pack)
    assert len(report.unavailable) == 2 and not report.applied and not report.updates
    assert GrammarTopic.query.count() == GrammarExercise.query.count() == 0
    with pytest.raises(ValueError, match="unavailable"):
        patch_prompts(db.session, pack, apply=True)
    assert GrammarExercise.query.count() == 0


def test_full_80_row_rollout_is_idempotent_and_preserves_ids_answers_order_and_srs(native_app, pack):
    pack = load_manifest(PACK)
    rows = seeded(pack)
    user, _ = learner(native_app)
    progress = UserGrammarExercise(user_id=user.id, exercise_id=rows[0].id)
    progress.state, progress.interval, progress.repetitions = "review", 23, 7
    db.session.add(progress)
    db.session.commit()
    before = [(row.id, row.order, row.difficulty, row.exercise_type, row.content["correct_answer"]) for row in rows]
    initial = deepcopy(rows[0].content)
    report = patch_prompts(db.session, pack)
    assert len(report.updates) == 80 and not report.applied
    assert rows[0].content == initial
    applied = patch_prompts(db.session, pack, apply=True)
    assert applied.applied and len(applied.updates) == 80
    assert before == [
        (row.id, row.order, row.difficulty, row.exercise_type, row.content["correct_answer"]) for row in rows
    ]
    replay = patch_prompts(db.session, pack, apply=True)
    assert not replay.updates and len(replay.unchanged) == 80
    db.session.refresh(progress)
    assert (progress.exercise_id, progress.state, progress.interval, progress.repetitions) == (
        rows[0].id,
        "review",
        23,
        7,
    )
    assert all(
        row.content == {**change["content_after"], "source": "json_import"}
        for row, change in zip(rows, pack["changes"], strict=True)
    )
    assert all(topic.content == {"theory": "Keep rules"} for topic in GrammarTopic.query.all())


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "drift",
        "unmanaged",
        "wrong_type",
        "wrong_level",
        "wrong_slug",
        "wrong_order",
        "wrong_difficulty",
    ],
)
def test_last_target_conflict_refuses_entire_pack_without_partial_first_update(native_app, pack, fault):
    rows = seeded(pack)
    first_before = deepcopy(rows[0].content)
    last = rows[-1]
    if fault == "missing":
        db.session.delete(last)
    elif fault == "duplicate":
        db.session.add(
            GrammarExercise(
                topic_id=last.topic_id,
                exercise_type=last.exercise_type,
                order=last.order,
                difficulty=last.difficulty,
                content=deepcopy(last.content),
            )
        )
    elif fault == "drift":
        last.content = {**last.content, "explanation": "Later teacher correction"}
    elif fault == "unmanaged":
        last.content = {**last.content, "source": "manual"}
    elif fault == "wrong_type":
        last.exercise_type = "translation"
    elif fault == "wrong_level":
        last.topic.level = "C1"
    elif fault == "wrong_slug":
        last.topic.slug = "custom-reported-questions"
    elif fault == "wrong_order":
        last.order = 99
    elif fault == "wrong_difficulty":
        last.difficulty = 1 if last.difficulty != 1 else 2
    db.session.commit()
    report = patch_prompts(db.session, pack)
    assert report.unavailable or report.conflicts
    with pytest.raises(ValueError, match="refused"):
        patch_prompts(db.session, pack, apply=True)
    assert db.session.get(GrammarExercise, rows[0].id).content == first_before


def test_content_match_never_falls_back_to_order_or_question(native_app, pack):
    rows = seeded(pack)
    # Same source order and visible question, but an unreviewed accepted answer.
    rows[-1].content = {**rows[-1].content, "alternatives": ["that"]}
    db.session.commit()
    assert patch_prompts(db.session, pack).unavailable
    with pytest.raises(ValueError, match="refused"):
        patch_prompts(db.session, pack, apply=True)


def test_second_preflight_refreshes_orm_identity_instead_of_overwriting_a_later_edit(native_app, pack):
    rows = seeded(pack)
    patch_prompts(db.session, pack)
    # Simulate a database edit while the caller still holds the old ORM object.
    later = {**rows[-1].content, "hint": "Newer manually reviewed hint"}
    db.session.execute(
        GrammarExercise.__table__.update().where(GrammarExercise.id == rows[-1].id).values(content=later)
    )
    db.session.commit()
    with pytest.raises(ValueError, match="refused"):
        patch_prompts(db.session, pack, apply=True)
    assert db.session.get(GrammarExercise, rows[-1].id).content == later
    assert "instruction" not in db.session.get(GrammarExercise, rows[0].id).content


def test_commit_failure_rolls_back_all_content_changes(native_app, pack, monkeypatch):
    rows = seeded(pack)
    before = [deepcopy(row.content) for row in rows]

    def fail_commit():
        db.session.flush()
        raise RuntimeError("Injected database commit failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="Injected"):
        patch_prompts(db.session, pack, apply=True)
    assert [row.content for row in rows] == before


def test_apply_refuses_unrelated_pending_changes(native_app, pack):
    rows = seeded(pack)
    rows[0].difficulty = 3
    with pytest.raises(ValueError, match="unrelated pending"):
        patch_prompts(db.session, pack, apply=True)
    db.session.rollback()
    assert "instruction" not in rows[0].content


def test_cli_defaults_to_read_only_and_reports_exact_targets(native_app, pack, tmp_path):
    rows = seeded(pack)
    path = tmp_path / "pack.json"
    import json

    path.write_text(json.dumps(pack))
    report_path = tmp_path / "report.json"
    runner = native_app.test_cli_runner()
    result = runner.invoke(grammar_prompts_command, [str(path), "--report", str(report_path)])
    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert len(json.loads(report_path.read_text())["updates"]) == 3
    assert "instruction" not in rows[0].content
    result = runner.invoke(grammar_prompts_command, [str(path), "--apply"])
    assert result.exit_code == 0, result.output
    assert "APPLIED" in result.output and rows[0].content.get("instruction")
