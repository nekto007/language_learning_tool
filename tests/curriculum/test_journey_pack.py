"""Private outcome import is transactional and never rewrites lessons/progress."""
import json
import uuid

import pytest

from app.curriculum.journey_pack import install_journey_pack
from app.curriculum.models import CEFRLevel, Lessons, Module


def setup_pack(db_session, tmp_path):
    level = CEFRLevel.query.filter_by(code='A1').first()
    if level is None:
        level = CEFRLevel(code='A1', name='Synthetic A1', order=1)
        db_session.add(level)
        db_session.flush()
    owner = Module(level_id=level.id, number=970, title=f'Synthetic {uuid.uuid4().hex[:8]}', raw_content={'preserve': 42})
    db_session.add(owner)
    db_session.commit()
    pack = {'version': 1, 'level': 'A1', 'modules': [
        {'number': owner.number, 'expected_title': owner.title, 'goal': 'A synthetic outcome for a synthetic module.'},
    ]}
    path = tmp_path / 'pack.json'
    path.write_text(json.dumps(pack))
    return owner, pack, path


def test_dry_run_apply_repeat_preserve_other_metadata(db_session, tmp_path):
    owner, _, path = setup_pack(db_session, tmp_path)
    assert install_journey_pack(path)['updated'] == [970]
    assert owner.raw_content == {'preserve': 42}
    assert install_journey_pack(path, apply=True)['updated'] == [970]
    assert owner.raw_content['preserve'] == 42
    assert install_journey_pack(path, apply=True)['unchanged'] == [970]


def test_invalid_later_module_prevents_any_updates(db_session, tmp_path):
    owner, pack, path = setup_pack(db_session, tmp_path)
    pack['modules'].append({'number': 971, 'expected_title': 'Absent', 'goal': 'Another synthetic outcome.'})
    path.write_text(json.dumps(pack))
    with pytest.raises(ValueError, match='missing or title differs'):
        install_journey_pack(path, apply=True)
    db_session.refresh(owner)
    assert owner.raw_content == {'preserve': 42}


def test_changed_outcome_is_not_overwritten_silently(db_session, tmp_path):
    _owner, pack, path = setup_pack(db_session, tmp_path)
    install_journey_pack(path, apply=True)
    pack['modules'][0]['goal'] = 'Another edited synthetic outcome.'
    path.write_text(json.dumps(pack))
    with pytest.raises(ValueError, match='different journey'):
        install_journey_pack(path, apply=True)


def test_label_repair_preserves_lesson_identity_content_and_repeatability(db_session, tmp_path):
    owner, pack, path = setup_pack(db_session, tmp_path)
    lesson = Lessons(module_id=owner.id, number=1, type='sentence_completion', title='Synthetic misleading title',
                     content={'exercises': [{'fixture': 'preserved'}]}, content_version=2)
    db_session.add(lesson)
    db_session.commit()
    identity = lesson.id
    pack['modules'][0]['lesson_labels'] = [{'type': 'sentence_completion',
        'expected_title': lesson.title, 'title': 'Synthetic correct title'}]
    path.write_text(json.dumps(pack))
    assert install_journey_pack(path)['lesson_labels_updated'] == [identity]
    assert lesson.title == 'Synthetic misleading title'
    assert install_journey_pack(path, apply=True)['lesson_labels_updated'] == [identity]
    assert lesson.id == identity and lesson.content_version == 3
    assert lesson.content == {'exercises': [{'fixture': 'preserved'}]}
    assert install_journey_pack(path, apply=True)['lesson_labels_updated'] == []


def test_grammar_cli_accepts_separate_private_content_directory(app, tmp_path, monkeypatch):
    from app.grammar_lab import content_install

    captured = {}
    def dry_run(**kwargs):
        captured.update(kwargs)
        return {'applied': False}
    monkeypatch.setattr(content_install, 'install_catalog', dry_run)
    result = app.test_cli_runner().invoke(args=['grammar-guided-install', '--level', 'A1', '--content-dir', str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert captured['root'] == tmp_path
    assert captured['apply'] is False
    assert len(captured['slugs']) == 16


def test_explicit_grammar_link_preserves_identity_and_refuses_rebinding(db_session, tmp_path):
    from app.grammar_lab.models import GrammarTopic
    owner, pack, path = setup_pack(db_session, tmp_path)
    topic = GrammarTopic.query.filter_by(slug='a1-1').first()
    if topic is None:
        topic = GrammarTopic(slug='a1-1', title='Synthetic grammar', title_ru='Synthetic rule', level='A1')
        db_session.add(topic)
        db_session.flush()
    grammar = Lessons(module_id=owner.id, number=1, type='grammar', title='Synthetic rule', content={})
    db_session.add(grammar)
    db_session.commit()
    identity = grammar.id
    pack['modules'][0]['grammar_topic'] = 'a1-1'
    path.write_text(json.dumps(pack))
    assert install_journey_pack(path)['grammar_links_updated'] == [identity]
    assert grammar.grammar_topic_id is None
    assert install_journey_pack(path, apply=True)['grammar_links_updated'] == [identity]
    assert grammar.id == identity and grammar.grammar_topic_id == topic.id
    assert install_journey_pack(path, apply=True)['grammar_links_updated'] == []
    grammar.grammar_topic_id = topic.id + 100000
    # Keep this a pending local edit; the installer must refuse its rebinding.
    with db_session.no_autoflush, pytest.raises(ValueError, match='link differs'):
        install_journey_pack(path, apply=True)
    db_session.rollback()


def test_guidance_changes_presentation_without_invalidating_active_answers(db_session, test_user, tmp_path):
    from app.curriculum.journey_pack import lesson_guidance
    from app.curriculum.models import LessonProgress

    owner, pack, path = setup_pack(db_session, tmp_path)
    content = {'instruction': 'Synthetic old instruction.', 'items': [{'prompt': 'Hello ___', 'answer': 'world'}]}
    lesson = Lessons(module_id=owner.id, number=1, type='sentence_completion', title='Synthetic task',
                     content=content, content_version=7)
    db_session.add(lesson)
    db_session.flush()
    saved = {'answers': {'0': 'first answer'}, 'quiz_correction': {'status': 'pending', 'attempt_id': 'fixture'}}
    progress = LessonProgress(user_id=test_user.id, lesson_id=lesson.id, status='in_progress', data=saved)
    db_session.add(progress)
    db_session.commit()
    pack['modules'][0]['lesson_guidance'] = [{'type': lesson.type, 'expected_instruction': content['instruction'],
        'instruction': 'Synthetic reviewed instruction.', 'learning_goal': 'Synthetic reviewed goal.'}]
    path.write_text(json.dumps(pack))
    dry = install_journey_pack(path)
    assert dry['lesson_guidance_updated'] == [lesson.id] and dry['backup'] is None
    assert lesson_guidance(lesson) == {}
    applied = install_journey_pack(path, apply=True)
    assert applied['lesson_guidance_updated'] == [lesson.id]
    assert lesson_guidance(lesson) == {'instruction': 'Synthetic reviewed instruction.', 'learning_goal': 'Synthetic reviewed goal.'}
    db_session.refresh(lesson)
    db_session.refresh(progress)
    assert lesson.content == content and lesson.content_version == 7
    assert progress.data == saved and progress.status == 'in_progress'
    backup = __import__('pathlib').Path(applied['backup'])
    assert backup.stat().st_mode & 0o777 == 0o600
    assert json.loads(backup.read_text())['modules'][0]['raw_content'] == {'preserve': 42}
    repeated = install_journey_pack(path, apply=True)
    assert repeated['lesson_guidance_updated'] == [] and repeated['backup'] is None


def test_guidance_refuses_a_different_authored_instruction_before_any_write(db_session, tmp_path):
    owner, pack, path = setup_pack(db_session, tmp_path)
    lesson = Lessons(module_id=owner.id, number=1, type='sentence_completion', title='Synthetic task',
                     content={'instruction': 'A newer reviewed instruction.'})
    db_session.add(lesson)
    db_session.commit()
    pack['modules'][0]['lesson_guidance'] = [{'type': lesson.type, 'expected_instruction': 'Stale original.',
                                            'instruction': 'Synthetic replacement.'}]
    path.write_text(json.dumps(pack))
    with pytest.raises(ValueError, match='authored instruction differs'):
        install_journey_pack(path, apply=True)
    db_session.refresh(owner)
    assert owner.raw_content == {'preserve': 42}


@pytest.mark.parametrize('patch', [
    {'type': 'final_test'}, {'instruction': '<b>markup</b>'}, {'unknown': 'field'},
    {'expected_instruction': None}, {'learning_goal': ' '},
])
def test_guidance_rejects_unreviewed_shapes(db_session, tmp_path, patch):
    owner, pack, path = setup_pack(db_session, tmp_path)
    lesson = Lessons(module_id=owner.id, number=1, type='sentence_completion', title='Synthetic task',
                     content={'instruction': 'Synthetic original.'})
    db_session.add(lesson)
    db_session.commit()
    item = {'type': lesson.type, 'expected_instruction': 'Synthetic original.', 'instruction': 'Synthetic repair.'}
    pack['modules'][0]['lesson_guidance'] = [{**item, **patch}]
    path.write_text(json.dumps(pack))
    with pytest.raises(ValueError, match='invalid lesson guidance'):
        install_journey_pack(path, apply=True)
    db_session.refresh(owner)
    assert owner.raw_content == {'preserve': 42}


def test_guidance_becomes_inert_after_real_content_changes_and_keeps_authored_goal():
    from types import SimpleNamespace
    from app.curriculum.journey_pack import lesson_guidance

    entry = {'version': 1, 'lesson_id': 9, 'expected_instruction': 'Synthetic old.',
             'instruction': 'Synthetic replacement.', 'learning_goal': 'Fallback goal.'}
    lesson = SimpleNamespace(id=9, type='sentence_completion', content={'instruction': 'Synthetic old.', 'learning_goal': 'Authored goal.'},
                             module=SimpleNamespace(raw_content={'module': {'lesson_guidance': {'sentence_completion': entry}}}))
    assert lesson_guidance(lesson) == {'instruction': 'Synthetic replacement.'}
    lesson.content = {'instruction': 'New authored instruction.'}
    assert lesson_guidance(lesson) == {}
    lesson.content = {'instruction': 'Synthetic old.'}
    lesson.id = 10
    assert lesson_guidance(lesson) == {}
