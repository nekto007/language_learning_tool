"""Recap rollout touches exact theory fields only, on disposable SQLite."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.cli.grammar_recaps import grammar_recaps_command, load_manifests, patch_recaps
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.grammar_lab.models import GrammarExercise, GrammarTopic, UserGrammarExercise
from app.utils.db import db
from tests.api.test_account_deletion import native_app as _native_app
from tests.api.test_native_full_integration import learner

ROOT = Path(__file__).parents[2]


@pytest.fixture(scope='module')
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


@pytest.fixture
def entries(native_app):
    # This module has its own disposable database, never the configured real DB.
    db.session.rollback()
    UserGrammarExercise.query.delete()
    GrammarExercise.query.delete()
    GrammarTopic.query.delete()
    Lessons.query.delete()
    Module.query.delete()
    CEFRLevel.query.delete()
    db.session.commit()
    reviewed = load_manifests([ROOT / 'MOBILE_GRAMMAR_RECAPS_20261120.json'])
    return [entry for entry in reviewed if len(entry['changes']) == 1][:2]


def seeded(entries, *, wrapper=False, mirror=True):
    result = []
    for entry in entries:
        level = CEFRLevel.query.filter_by(code=entry['level']).first()
        if not level:
            level = CEFRLevel(code=entry['level'], name='Disposable level')
            db.session.add(level)
            db.session.flush()
        module = Module(level_id=level.id, number=entry['module_order'], title='Disposable module')
        db.session.add(module)
        db.session.flush()
        content = {'external_key': entry['lesson_external_key'], 'rule': 'Preserve existing rule', 'exercises': [{'id': 'keep', 'correct_answer': 'unchanged'}]}
        for change in entry['changes']:
            # The first two actual A1 entries only replace tldr.
            assert change['path'] == ['tldr']
            content['tldr'] = deepcopy(change['before'])
        if wrapper:
            content = {'external_key': content.pop('external_key'), 'grammar_explanation': content, 'xp_reward': 8}
        lesson = Lessons(module_id=module.id, number=7, order=7, title='Disposable grammar', type='grammar', content=content)
        db.session.add(lesson)
        topic = None
        if mirror:
            topic = GrammarTopic(slug=f"{entry['level'].lower()}-{entry['module_order']}", level=entry['level'], title='Disposable mirror', title_ru='Тест', content=deepcopy(content))
            db.session.add(topic)
        db.session.flush()
        result.append((lesson, topic))
    db.session.commit()
    return result


def test_default_preflight_is_read_only_and_reports_missing(native_app, entries):
    report = patch_recaps(db.session, entries)
    assert len(report.unavailable) == 2 and len(report.skipped) == 2
    assert not report.applied and not report.updates
    assert Lessons.query.count() == GrammarTopic.query.count() == 0
    with pytest.raises(ValueError, match='unavailable'):
        patch_recaps(db.session, entries, apply=True)


def test_apply_is_idempotent_and_preserves_exercises_and_progress(native_app, entries):
    rows = seeded(entries)
    topic = rows[0][1]
    exercise = GrammarExercise(topic_id=topic.id, exercise_type='fill_blank', content={'question': 'I ___ here.', 'correct_answer': 'am'})
    db.session.add(exercise)
    db.session.commit()
    user, _ = learner(native_app)
    progress = UserGrammarExercise(user_id=user.id, exercise_id=exercise.id)
    progress.state, progress.interval, progress.repetitions = 'review', 19, 4
    db.session.add(progress)
    db.session.commit()
    before = [deepcopy(row.content) for row, _ in rows]
    report = patch_recaps(db.session, entries)
    assert len(report.updates) == 4 and not report.applied
    assert [row.content for row, _ in rows] == before
    report = patch_recaps(db.session, entries, apply=True)
    assert report.applied and len(report.updates) == 4
    again = patch_recaps(db.session, entries, apply=True)
    assert not again.updates and len(again.unchanged) == 4
    for (lesson, mirror), entry in zip(rows, entries, strict=True):
        assert lesson.content['tldr'] == mirror.content['tldr'] == entry['changes'][0]['after']
        assert lesson.content['exercises'] == [{'id': 'keep', 'correct_answer': 'unchanged'}]
        assert lesson.content_version == 1
    db.session.refresh(progress)
    assert (progress.state, progress.interval, progress.repetitions) == ('review', 19, 4)
    assert db.session.get(GrammarExercise, exercise.id).content['correct_answer'] == 'am'


def test_explicit_wrapper_is_patched_and_outer_metadata_kept(native_app, entries):
    rows = seeded(entries, wrapper=True)
    patch_recaps(db.session, entries, apply=True)
    assert rows[0][0].content['grammar_explanation']['tldr'] == entries[0]['changes'][0]['after']
    assert rows[0][0].content['xp_reward'] == 8


def test_equal_dual_copies_both_update_but_divergent_copies_conflict(native_app, entries):
    rows = seeded(entries)
    lesson = rows[0][0]
    lesson.content = {**lesson.content, 'grammar_explanation': {'tldr': deepcopy(lesson.content['tldr'])}}
    db.session.commit()
    patch_recaps(db.session, entries, apply=True)
    assert lesson.content['tldr'] == lesson.content['grammar_explanation']['tldr']
    lesson.content = {**lesson.content, 'grammar_explanation': {'tldr': ['newer manual edit']}}
    db.session.commit()
    assert patch_recaps(db.session, entries).conflicts
    with pytest.raises(ValueError, match='conflicts'):
        patch_recaps(db.session, entries, apply=True)


@pytest.mark.parametrize('edit', ['missing_key', 'wrong_key', 'wrong_module', 'wrong_level'])
def test_identity_requires_exact_external_key_and_module_context(native_app, entries, edit):
    rows = seeded(entries, mirror=False)
    lesson = rows[0][0]
    if edit == 'missing_key':
        content = deepcopy(lesson.content)
        del content['external_key']
        lesson.content = content
    elif edit == 'wrong_key':
        lesson.content = {**lesson.content, 'external_key': 'wrong:key'}
    elif edit == 'wrong_module':
        lesson.module.number += 100
    else:
        lesson.module.level.code = 'C1'
    db.session.commit()
    assert patch_recaps(db.session, entries).unavailable
    with pytest.raises(ValueError, match='unavailable'):
        patch_recaps(db.session, entries, apply=True)


def test_drift_in_last_mirror_prevents_first_lesson_update(native_app, entries):
    rows = seeded(entries)
    original = deepcopy(rows[0][0].content)
    rows[-1][1].content = {**rows[-1][1].content, 'tldr': ['Teacher correction']}
    db.session.commit()
    report = patch_recaps(db.session, entries)
    assert report.conflicts and report.updates
    with pytest.raises(ValueError, match='conflicts'):
        patch_recaps(db.session, entries, apply=True)
    db.session.expire_all()
    assert rows[0][0].content == original


def test_optional_missing_mirrors_are_skipped_without_creating_topics(native_app, entries):
    seeded(entries, mirror=False)
    report = patch_recaps(db.session, entries, apply=True)
    assert report.applied and len(report.skipped) == 2 and len(report.updates) == 2
    assert GrammarTopic.query.count() == 0


def test_storage_failure_rolls_back_every_theory_update(native_app, entries, monkeypatch):
    rows = seeded(entries)
    before = [deepcopy(lesson.content) for lesson, _ in rows]
    def fail_commit():
        db.session.flush()
        raise RuntimeError('simulated commit failure')
    with monkeypatch.context() as context:
        context.setattr(db.session, 'commit', fail_commit)
        with pytest.raises(RuntimeError, match='simulated'):
            patch_recaps(db.session, entries, apply=True)
    db.session.expire_all()
    assert [lesson.content for lesson, _ in rows] == before


def test_cli_writes_honest_dry_run_report_and_does_not_mutate(native_app, entries, tmp_path):
    seeded(entries)
    manifest = json.loads((ROOT / 'MOBILE_GRAMMAR_RECAPS_20261120.json').read_text())
    manifest['entries'] = entries
    source = tmp_path / 'manifest.json'
    source.write_text(json.dumps(manifest))
    output = tmp_path / 'report.json'
    # Register locally until parent integrates this command into the app factory.
    native_app.cli.add_command(grammar_recaps_command)
    result = native_app.test_cli_runner().invoke(args=['grammar-recaps', str(source), '--report', str(output)])
    assert result.exit_code == 0, result.output
    assert 'DRY RUN: 4 rows to patch' in result.output
    assert json.loads(output.read_text())['applied'] is False
    assert len(patch_recaps(db.session, entries).updates) == 4
    result = native_app.test_cli_runner().invoke(args=['grammar-recaps', str(source), '--apply'])
    assert result.exit_code == 0, result.output
    assert 'APPLIED' in result.output


def test_duplicate_manifest_and_forbidden_field_are_rejected_before_queries(native_app, entries):
    with pytest.raises(ValueError, match='Duplicate'):
        load_manifests([ROOT / 'MOBILE_GRAMMAR_RECAPS_20261120.json'] * 2)
    entries[0]['changes'].append({'path': ['exercises'], 'before': [], 'after': []})
    with pytest.raises(ValueError, match='Unreviewed'):
        patch_recaps(db.session, entries, apply=True)


def _put(container, path, value):
    key = path[0]
    if isinstance(container, list):
        while len(container) <= key:
            container.append(None)
    if len(path) == 1:
        container[key] = deepcopy(value)
        return
    child = container.get(key) if isinstance(container, dict) else container[key]
    if child is None:
        child = [] if type(path[1]) is int else {}
        container[key] = child
    _put(child, path[1:], value)


@pytest.mark.parametrize('level,number', [('A2', 10), ('B1', 16), ('B1', 17), ('B2', 8)])
def test_reviewed_complex_theory_paths_patch_without_guessing_key_indexes(native_app, entries, level, number):
    all_entries = load_manifests([ROOT / 'MOBILE_GRAMMAR_RECAPS_20261120.json', ROOT / 'MOBILE_GRAMMAR_RECAP_EXAMPLES_20261120.json'])
    entry = next(entry for entry in all_entries if entry['level'] == level and entry['module_order'] == number)
    content = {'external_key': entry['lesson_external_key'], 'preserve': {'nested': [42]}}
    for change in entry['changes']:
        _put(content, change['path'], change['before'])
    level_row = CEFRLevel(code=level, name='Disposable complex fixture')
    db.session.add(level_row)
    db.session.flush()
    module = Module(level_id=level_row.id, number=number, title='Review')
    db.session.add(module)
    db.session.flush()
    lesson = Lessons(module_id=module.id, number=7, type='grammar', title='Review', content=deepcopy(content))
    topic = GrammarTopic(slug=f'{level.lower()}-{number}', level=level, title='Review', title_ru='Проверка', content=deepcopy(content))
    db.session.add_all([lesson, topic])
    db.session.commit()
    report = patch_recaps(db.session, [entry], apply=True)
    assert report.applied and len(report.updates) == 2
    assert lesson.content == topic.content
    assert lesson.content['preserve'] == {'nested': [42]}
    for change in entry['changes']:
        value = lesson.content
        for key in change['path']:
            value = value[key]
        assert value == change['after']
    if (level, number) == ('B1', 16):
        assert ':15:' in entry['lesson_external_key']
        assert module.number == 16


def test_unrelated_pending_changes_are_not_committed(native_app, entries):
    rows = seeded(entries)
    rows[0][0].title = 'Unsaved admin change'
    with pytest.raises(ValueError, match='unrelated pending'):
        patch_recaps(db.session, entries, apply=True)
    db.session.rollback()
    assert rows[0][0].title == 'Disposable grammar'


def test_description_alias_is_explicit_and_only_for_lab_mirrors():
    from app.cli.grammar_recaps import _patched_content
    changes = [{'path': ['description'], 'before': 'Old description', 'after': 'Reviewed description'}]
    mirror = {'introduction': 'Old description', 'keep': 42}
    result, paths = _patched_content(mirror, changes, topic_mirror=True)
    assert result == {'introduction': 'Reviewed description', 'keep': 42}
    assert paths == [['introduction']]
    with pytest.raises(ValueError, match='missing'):
        _patched_content(mirror, changes)
    already, paths = _patched_content({'introduction': 'Reviewed description'}, changes, topic_mirror=True)
    assert already['introduction'] == 'Reviewed description' and not paths


@pytest.mark.parametrize('content', [
    {'introduction': 'Edited by teacher'},
    {'description': 'Edited by teacher', 'introduction': 'Old description'},
    {'description': 'Old description', 'introduction': 'Edited by teacher'},
    {'introduction': 'Old description', 'grammar_explanation': {'introduction': 'Edited by teacher'}},
    {'description': 'Old description', 'grammar_explanation': {'introduction': 'Reviewed description'}},
    {'introduction': 'Old description', 'grammar_explanation': {'description': 'Edited by teacher'}},
])
def test_mirror_alias_never_hides_drift_or_divergent_root_wrapper_copies(content):
    from app.cli.grammar_recaps import _patched_content
    changes = [{'path': ['description'], 'before': 'Old description', 'after': 'Reviewed description'}]
    with pytest.raises(ValueError):
        _patched_content(content, changes, topic_mirror=True)


def test_identical_description_and_introduction_mirror_copies_patch_together():
    from app.cli.grammar_recaps import _patched_content
    content = {'description': 'Old', 'introduction': 'Old', 'grammar_explanation': {'description': 'Old', 'introduction': 'Old'}}
    result, paths = _patched_content(content, [{'path': ['description'], 'before': 'Old', 'after': 'New'}], topic_mirror=True)
    assert len(paths) == 4
    assert result == {'description': 'New', 'introduction': 'New', 'grammar_explanation': {'description': 'New', 'introduction': 'New'}}


def test_explicit_manifest_kind_is_kept_instead_of_inferred_from_evidence():
    advanced = load_manifests([ROOT / 'MOBILE_GRAMMAR_ADVANCED_RECAPS_20261120.json'])
    assert all(entry['_patch_kind'] == 'advanced_recaps' for entry in advanced)
    existing = load_manifests([ROOT / 'MOBILE_GRAMMAR_RECAP_EXAMPLES_20261120.json'])
    assert all(entry['_patch_kind'] == 'reviewed_advanced' for entry in existing)


def test_all_advanced_topics_roll_out_exactly_with_all_nested_paths(native_app, entries):
    reviewed = load_manifests([ROOT / 'MOBILE_GRAMMAR_ADVANCED_RECAPS_20261120.json'])
    assert len(reviewed) == 15
    assert sum(entry.get('theory_only', False) for entry in reviewed) == 4
    rows = []
    for entry in reviewed:
        level = CEFRLevel.query.filter_by(code=entry['level']).first()
        if level is None:
            level = CEFRLevel(code=entry['level'], name='Disposable advanced level')
            db.session.add(level)
            db.session.flush()
        module = Module(level_id=level.id, number=entry['module_order'], title='Disposable advanced module')
        db.session.add(module)
        db.session.flush()
        content = {'external_key': entry['lesson_external_key'], 'preserve': {'exercise_ids': [123]}}
        for change in entry['changes']:
            _put(content, change['path'], change['before'])
        lesson = Lessons(module_id=module.id, number=7, type='grammar', title='Advanced fixture', content=deepcopy(content))
        topic = GrammarTopic(slug=f"{entry['level'].lower()}-{entry['module_order']}", level=entry['level'], title='Advanced fixture', title_ru='Проверка', content=deepcopy(content))
        db.session.add_all([lesson, topic])
        rows.append((lesson, topic, entry))
    db.session.commit()
    ids = [(lesson.id, topic.id) for lesson, topic, _ in rows]
    report = patch_recaps(db.session, reviewed, apply=True)
    assert report.applied and len(report.updates) == 30
    for lesson, topic, entry in rows:
        assert lesson.content == topic.content
        assert lesson.content['preserve'] == {'exercise_ids': [123]}
        for change in entry['changes']:
            value = lesson.content
            for key in change['path']:
                value = value[key]
            assert value == change['after']
    again = patch_recaps(db.session, reviewed, apply=True)
    assert not again.updates and len(again.unchanged) == 30
    assert ids == [(lesson.id, topic.id) for lesson, topic, _ in rows]
