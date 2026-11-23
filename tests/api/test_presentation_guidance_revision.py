"""Reviewed task wording does not invalidate independent/correction documents."""
import pytest

from tests.api.test_quiz_corrections import (
    course as _course, document, native_app as _native_app, submit, progress_and_attempts,
)


@pytest.fixture(scope='module')
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


@pytest.fixture
def course(native_app, monkeypatch):
    case = _course.__wrapped__(native_app, monkeypatch)
    from app.utils.db import db
    case[2].type = 'sentence_completion'
    case[2].content = {'instruction': 'Synthetic stale instruction.', 'items': [
        {'prompt': 'Say ___', 'answer': 'hello'}, {'prompt': 'Say ___', 'answer': 'goodbye'}]}
    db.session.commit()
    return case


@pytest.mark.parametrize('phase', ['first', 'correction'])
def test_active_document_survives_metadata_wording_update(course, phase):
    from app.utils.db import db
    first = document(course)
    if phase == 'correction':
        result = submit(course, first, {'0': 'wrong', '1': 'goodbye'})
        assert result.status_code == 200 and result.json['score'] == 50
    opened = first if phase == 'first' else document(course)
    lesson = course[2]
    original_content = dict(lesson.content)
    lesson.module.raw_content = {'module': {'lesson_guidance': {'sentence_completion': {
        'version': 1, 'lesson_id': lesson.id, 'expected_instruction': 'Synthetic stale instruction.',
        'instruction': 'Synthetic reviewed instruction.', 'learning_goal': 'Synthetic reviewed goal.',
    }}}}
    db.session.commit()
    updated = document(course)
    assert updated['instruction'] == 'Synthetic reviewed instruction.'
    assert updated['learning_goal'] == 'Synthetic reviewed goal.'
    assert updated['content_revision'] == opened['content_revision']
    assert lesson.content == original_content and updated['quiz_phase'] == phase
    if phase == 'correction':
        assert updated['correction']['attempt_id'] == opened['correction']['attempt_id']
    answers = {'0': 'hello', **({'1': 'goodbye'} if phase == 'first' else {})}
    result = submit(course, opened, answers)
    assert result.status_code == 200 and result.json['completed'], result.json
    assert result.json['score'] == (100 if phase == 'first' else 50)
    progress, attempts = progress_and_attempts(course)
    assert progress.status == 'completed' and len(attempts) == 1
