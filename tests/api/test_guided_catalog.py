"""Complete authored corpus, transactional imports, history and active queues."""

from copy import deepcopy
from datetime import datetime, timedelta, UTC
from itertools import count
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.grammar_lab.content_catalog import (
    compile_topic, expected_slugs, load_catalog, validate_authored_topic, validate_catalog_answers,
)
from app.grammar_lab.content_install import install_catalog, restore_catalog
from tests.api.test_account_deletion import native_app as _native_app

_case_numbers = count()


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


@pytest.fixture
def catalog_case(native_app, tmp_path):
    from app.curriculum.models import CEFRLevel, Module, Lessons, LessonProgress
    from app.grammar_lab.models import GrammarTopic, GrammarExercise, GrammarAttempt, UserGrammarExercise
    from app.utils.db import db
    from tests.api.test_native_full_integration import learner

    number = next(_case_numbers)
    slug = expected_slugs()[number]
    level = slug.split("-")[0].upper()
    user, headers = learner(native_app)
    cefr = CEFRLevel.query.filter_by(code=level).first()
    if cefr is None:
        cefr = CEFRLevel(code=level, name=level)
        db.session.add(cefr)
        db.session.flush()
    module = Module(level_id=cefr.id, number=900 + number, title="Test module")
    topic = GrammarTopic(slug=slug, level=level, title="Old topic", title_ru="Old topic",
                         content={"rule": "Legacy reference only"})
    db.session.add_all([module, topic])
    db.session.flush()
    lesson = Lessons(module_id=module.id, number=1, order=1, type="grammar", title="Rule",
        grammar_topic_id=topic.id, content={"external_key": "stable-key", "rule": "Old course rule"})
    final = Lessons(module_id=module.id, number=2, order=2, type="final_test", title="Final",
        grammar_topic_id=topic.id, content={"questions": [{"question": "Final remains unchanged"}]})
    old = GrammarExercise(topic_id=topic.id, exercise_type="fill_blank",
                          content={"question": "Old ___ question", "correct_answer": "old"})
    db.session.add_all([lesson, final, old])
    db.session.flush()
    progress = UserGrammarExercise(user_id=user.id, exercise_id=old.id)
    progress.state, progress.interval, progress.correct_count = "review", 30, 5
    progress.first_reviewed = datetime.now(UTC) - timedelta(days=10)
    progress.next_review = datetime.now(UTC) - timedelta(minutes=5)
    attempt = GrammarAttempt(user_id=user.id, exercise_id=old.id, is_correct=True,
        user_answer="old", session_id="before-content-update", source="topic_practice")
    completion = LessonProgress(user_id=user.id, lesson_id=lesson.id, status="completed", score=100,
                                data={"historical": "keep"})
    db.session.add_all([progress, attempt, completion])
    db.session.commit()
    document = {"version": 1, "topic_slug": slug, "title": "Reviewed topic", "goal": "Practise am and is.",
        "steps": [{"id": "first-person", "title": "I + am", "body": "Use am after I. Example: I am ready.", "exercises": [
            {"type": "fill_blank", "instruction": "Complete the gap with one verb.", "question": "I ___ here.",
             "correct_answer": "am", "explanation": "Use am after I."},
            {"type": "multiple_choice", "instruction": "Choose the verb after she.", "question": "She ___ here.",
             "options": ["am", "is", "are"], "correct_answer": "is", "explanation": "Use is after she."}]}]}
    root = tmp_path / "content"
    path = root / ("plurals_demonstratives.json" if slug == "a1-4" else f"topics/{slug}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))
    return SimpleNamespace(app=native_app, user=user, headers=headers, topic=topic, lesson=lesson,
        final=final, old=old, progress=progress, attempt=attempt, completion=completion,
        document=document, root=root, path=path, backup=tmp_path / "backups", slug=slug)


def run(case, apply=False):
    return install_catalog(slugs=[case.slug], root=case.root, apply=apply, backup_dir=case.backup)


def test_all_topics_have_authored_rules_and_gradable_answers():
    documents = load_catalog()
    assert set(documents) == set(expected_slugs()) and len(documents) == 86
    totals = validate_catalog_answers(documents)
    assert totals["steps"] >= 258 and totals["exercises"] >= 516
    for document in documents.values():
        for row in compile_topic(document)["exercises"]:
            assert row["guided_key"] and row["guided_rule_id"] and row["theory_help"]


def test_dry_run_has_no_database_or_filesystem_writes(catalog_case):
    from app.grammar_lab.models import GrammarExercise

    case = catalog_case
    before, total = deepcopy(case.topic.content), GrammarExercise.query.count()
    report = run(case)
    assert not report["applied"] and report["topics_to_update"] == [case.slug]
    assert case.topic.content == before and GrammarExercise.query.count() == total
    assert not case.backup.exists()


def test_import_preserves_history_and_final_but_uses_only_reviewed_bank(catalog_case):
    from app.api.native_grammar_progress import topic_progress
    from app.grammar_lab.models import GrammarExercise

    case = catalog_case
    history = (case.progress.id, case.progress.state, case.progress.interval, case.progress.correct_count,
               case.attempt.id, case.completion.id, deepcopy(case.completion.data))
    previous_final = deepcopy(case.final.content)
    report = run(case, apply=True)
    assert report["created_exercises"] == 2 and report["retired_exercises"] == 1
    assert case.lesson.grammar_topic_id == case.topic.id
    assert case.topic.content["legacy_content"] == {"rule": "Legacy reference only"}
    assert case.lesson.content["external_key"] == "stable-key"
    assert case.lesson.content["learning_steps"] and case.final.content == previous_final
    assert GrammarExercise.query.get(case.old.id).content["guided_retired"]
    assert history == (case.progress.id, case.progress.state, case.progress.interval, case.progress.correct_count,
                       case.attempt.id, case.completion.id, case.completion.data)
    assert topic_progress(case.user.id, [case.topic.id])[case.topic.id] == {
        "theory_completed": True, "practiced_exercises": 0, "correct_exercises": 0, "total_exercises": 2}
    backup = json.loads(Path(report["backup"]).read_text())
    assert backup["before"]["topics"][0]["content"] == {"rule": "Legacy reference only"} and backup["after_digest"]


def test_repeat_install_and_reordering_keep_exercise_ids(catalog_case):
    from app.grammar_lab.models import GrammarExercise

    case = catalog_case
    run(case, apply=True)
    ids, total = list(case.topic.content["guided_exercise_ids"]), GrammarExercise.query.count()
    second = run(case, apply=True)
    assert second["topics_to_update"] == [] and "backup" not in second
    assert case.topic.content["guided_exercise_ids"] == ids and GrammarExercise.query.count() == total
    case.document["steps"][0]["exercises"].reverse()
    case.path.write_text(json.dumps(case.document))
    assert run(case, apply=True)["created_exercises"] == 0
    if case.slug != "a1-4":
        assert case.topic.content["guided_exercise_ids"] == ids[::-1]
    assert case.topic.content["legacy_content"] == {"rule": "Legacy reference only"}


@pytest.mark.parametrize("failure_point", ["_write_backup", "_seal_backup_after"])
def test_failure_before_or_after_mutations_rolls_back_everything(catalog_case, monkeypatch, failure_point):
    import app.grammar_lab.content_install as installer
    from app.grammar_lab.models import GrammarExercise

    case = catalog_case
    before, total = deepcopy(case.topic.content), GrammarExercise.query.count()
    monkeypatch.setattr(installer, failure_point, lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        run(case, apply=True)
    assert case.topic.content == before and GrammarExercise.query.count() == total
    assert not case.old.content.get("guided_retired")


def test_restore_keeps_history_and_refuses_to_overwrite_later_edits(catalog_case):
    from app.grammar_lab.models import GrammarExercise
    from app.utils.db import db

    case = catalog_case
    before = deepcopy(case.topic.content)
    installed = run(case, apply=True)
    new_ids = list(case.topic.content["guided_exercise_ids"])
    assert not restore_catalog(installed["backup"])["applied"]
    case.lesson.content = {**case.lesson.content, "learning_goal": "A newer edit"}
    db.session.commit()
    with pytest.raises(ValueError, match="newer edits"):
        restore_catalog(installed["backup"], apply=True)
    case.lesson.content = {**case.lesson.content, "learning_goal": case.document["goal"]}
    db.session.commit()
    restore_catalog(installed["backup"], apply=True)
    assert case.topic.content == before and not case.old.content.get("guided_retired")
    assert all(GrammarExercise.query.get(key).content["guided_retired"] for key in new_ids)
    assert case.progress.correct_count == 5 and case.completion.status == "completed"


def test_retired_questions_stay_out_of_topic_mixed_due_and_counts(catalog_case):
    from app.grammar_lab.services.grammar_lab_service import GrammarLabService
    from app.srs.service import UnifiedSRSService
    from app.srs.stats_service import SRSStatsService

    case = catalog_case
    run(case, apply=True)
    service = GrammarLabService()
    topic = service.start_topic_practice(case.topic.id, case.user.id)
    assert case.old.id not in topic["all_exercise_ids"] and len(topic["all_exercise_ids"]) == 2
    mixed = service.get_practice_session(case.user.id, topic_ids=[case.topic.id], include_new=True)
    assert case.old.id not in [row["id"] for row in mixed["exercises"]]
    due = UnifiedSRSService().get_due_grammar_exercises(case.user.id, topic_id=case.topic.id)
    assert case.old.id not in [row.exercise_id for row in due]
    assert SRSStatsService().get_grammar_stats(case.user.id, topic_id=case.topic.id)["total"] == 2


def test_cli_is_registered_and_rejects_unknown_scope(native_app):
    runner = native_app.test_cli_runner()
    result = runner.invoke(args=["grammar-guided-install", "--help"])
    assert result.exit_code == 0 and "--apply" in result.output
    assert runner.invoke(args=["grammar-guided-restore", "--help"]).exit_code == 0
    result = runner.invoke(args=["grammar-guided-install", "--topic", "nonexistent"])
    assert result.exit_code != 0 and "Unknown grammar topics" in result.output


@pytest.mark.parametrize("field", ["lesson", "exercise", "ids", "delete"])
def test_same_catalog_digest_cannot_hide_manual_drift(catalog_case, field):
    from app.grammar_lab.models import GrammarExercise
    from app.utils.db import db

    case = catalog_case
    run(case, apply=True)
    exercise = db.session.get(GrammarExercise, case.topic.content["guided_exercise_ids"][0])
    if field == "lesson":
        case.lesson.content = {**case.lesson.content, "learning_goal": "manual change"}
    elif field == "exercise":
        exercise.content = {**exercise.content, "correct_answer": "manual change"}
    elif field == "ids":
        case.topic.content = {**case.topic.content, "guided_exercise_ids": []}
    else:
        db.session.delete(exercise)
    db.session.commit()
    backups = list(case.backup.glob("*.json"))
    with pytest.raises(ValueError, match="drift"):
        run(case, apply=True)
    assert list(case.backup.glob("*.json")) == backups


def test_pilot_preserves_original_keys_when_reordered_but_not_for_changed_targets():
    document = load_catalog(["a1-4"])["a1-4"]
    original = compile_topic(document)
    original_keys = [row["guided_key"] for row in original["exercises"][:3]]
    assert original_keys == ["plural-s:0", "plural-s:1", "plural-s:2"]
    document["steps"][0]["exercises"].reverse()
    reordered = compile_topic(document)
    assert [row["guided_key"] for row in reordered["exercises"][:3]] == original_keys[::-1]
    document["steps"][0]["exercises"][2]["correct_answer"] = "kittens"
    assert compile_topic(document)["exercises"][2]["guided_key"] != "plural-s:0"


def test_in_flight_error_review_rejects_new_lesson_revision(catalog_case):
    from flask import g
    from app.api.native_activities import _validate_error_revision
    from app.api.native_lessons import NativeLessonError
    from app.daily_plan.linear.models import QuizErrorLog
    from app.utils.db import db

    case = catalog_case
    run(case, apply=True)
    revision = case.lesson.content["guided_catalog_digest"]
    error = QuizErrorLog(user_id=case.user.id, lesson_id=case.lesson.id,
                         question_payload={"question_index": 0, "guided_revision": revision})
    db.session.add(error)
    db.session.commit()
    activity = SimpleNamespace(kind="error_review", payload={"source": {
        "error_ids": [error.id], "error_revisions": [revision]}})
    with case.app.test_request_context():
        g._login_user = case.user
        _validate_error_revision(activity, 0)
        case.lesson.content = {**case.lesson.content, "guided_catalog_digest": "new-revision"}
        db.session.commit()
        with pytest.raises(NativeLessonError) as raised:
            _validate_error_revision(activity, 0)
        assert raised.value.code == "lesson_changed" and error.resolved_at is None


def test_rollback_never_rebinds_guided_errors_to_legacy_question_indices(catalog_case):
    from app.daily_plan.linear.errors import count_unresolved, get_review_pool
    from app.daily_plan.linear.models import QuizErrorLog
    from app.utils.db import db

    case = catalog_case
    old_error = QuizErrorLog(user_id=case.user.id, lesson_id=case.lesson.id,
                             question_payload={"question_index": 0, "question_text": "Old question"})
    db.session.add(old_error)
    db.session.commit()
    installed = run(case, apply=True)
    revision = case.lesson.content["guided_catalog_digest"]
    new_error = QuizErrorLog(user_id=case.user.id, lesson_id=case.lesson.id,
        question_payload={"question_index": 0, "question_text": "New question", "guided_revision": revision})
    db.session.add(new_error)
    db.session.commit()
    assert [row.id for row in get_review_pool(case.user.id, db)] == [new_error.id]
    restore_catalog(installed["backup"], apply=True)
    assert count_unresolved(case.user.id, db) == 1
    assert [row.id for row in get_review_pool(case.user.id, db)] == [old_error.id]
    assert new_error.resolved_at is None


def test_restore_rejects_relinking_a_lesson_between_two_selected_topics(catalog_case):
    from app.grammar_lab.models import GrammarTopic
    from app.utils.db import db

    case = catalog_case
    other = GrammarTopic(slug="c1-14", title="Other", title_ru="Other", level="C1", content={"rule": "Old other"})
    db.session.add(other)
    db.session.commit()
    document = {**deepcopy(case.document), "topic_slug": other.slug, "title": "Other"}
    (case.root / "topics" / "c1-14.json").write_text(json.dumps(document))
    installed = install_catalog(slugs=[case.slug, other.slug], root=case.root, apply=True, backup_dir=case.backup)
    case.lesson.grammar_topic_id = other.id
    db.session.commit()
    with pytest.raises(ValueError, match="newer edits"):
        restore_catalog(installed["backup"], apply=True)
    assert case.lesson.grammar_topic_id == other.id


def test_error_review_final_grade_agrees_with_immediate_guided_feedback(catalog_case, monkeypatch):
    from flask import g
    from app.api.native_activities import _document, _grade_activity
    from app.daily_plan.linear.models import QuizErrorLog
    from app.grammar_lab.guided_learning import check_answer
    from app.study.models import StudySession
    from app.utils.db import db

    case = catalog_case
    run(case, apply=True)
    revision = case.lesson.content["guided_catalog_digest"]
    row = case.lesson.content["exercises"][0]
    error = QuizErrorLog(user_id=case.user.id, lesson_id=case.lesson.id,
        question_payload={"question_index": 0, "guided_revision": revision, "guided_key": row["guided_key"]})
    study = StudySession(user_id=case.user.id, session_type="quiz", start_time=datetime.now(UTC))
    db.session.add_all([error, study])
    db.session.commit()
    activity = SimpleNamespace(session_id=study.id, kind="error_review", payload={
        "rows": [row], "source": {"error_ids": [error.id], "sources": ["grammar"], "error_revisions": [revision]},
        "title": "Review", "level": "A1", "theory": [], "day": "2026-11-22"})
    monkeypatch.setattr("app.daily_plan.linear.xp.maybe_award_error_review_xp", lambda *args, **kwargs: None)
    with case.app.test_request_context():
        g._login_user = case.user
        question = _document(activity)["questions"][0]
        assert check_answer(row, question, "AM.")["correct"]
        result = _grade_activity(activity, {"0": "AM."})
        assert result["correct_count"] == 1 and result["feedback"][0]["correct"]
        assert error.resolved_at is not None


@pytest.mark.parametrize("field", ["question", "instruction", "correct_answer", "explanation"])
def test_invalid_exercise_cannot_be_imported(field):
    document = load_catalog(["a1-4"])["a1-4"]
    document["steps"][0]["exercises"][0].pop(field)
    with pytest.raises(ValueError):
        validate_authored_topic(document)
