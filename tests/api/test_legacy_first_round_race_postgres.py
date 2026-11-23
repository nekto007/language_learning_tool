"""A retained browser writer cannot erase a concurrent native first round."""
# ruff: noqa: F811 -- imported pytest fixtures are discovered by name.
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

from flask_login import login_user
from flask import has_request_context, request
import pytest
from sqlalchemy import event

from tests.api.test_quiz_correction_concurrency_postgres import (
    race_course as race_course, postgres_app as postgres_app, document, post,
)


@pytest.mark.parametrize('writer', ['grading', 'complete', 'upsert', 'autosave'])
def test_legacy_writer_rechecks_pending_after_the_native_account_lock(race_course, monkeypatch, writer):
    from app.auth.models import User
    from app.curriculum.models import LessonProgress, LessonAttempt, Lessons
    from app.curriculum.services.progress_service import ProgressService
    from app.curriculum.grading import process_grammar_submission
    from app.daily_plan import quiz_corrections
    from app.utils.db import db

    case = race_course
    db.session.add(LessonProgress(user_id=case.user_id, lesson_id=case.lesson_id,
                                  status='in_progress', score=0, data={}))
    db.session.commit()
    opened = document(case)
    native_locked, legacy_ready, native_finished, mutex = Event(), Event(), Event(), Lock()
    lock_requests = 0

    def is_lock(statement):
        sql = ' '.join(statement.lower().split())
        return 'from users ' in sql and 'for update' in sql

    def before(conn, cursor, statement, parameters, context, executemany):
        nonlocal lock_requests
        if is_lock(statement):
            with mutex:
                lock_requests += 1
                if lock_requests == 2:
                    legacy_ready.set()
        if ('update lesson_progress ' in ' '.join(statement.lower().split())
                and has_request_context() and request.path == '/retained-browser-writer'
                and lock_requests == 1):
            # The old unguarded upsert only reaches a scheduling boundary at
            # its actual write. Let native commit before that stale UPDATE.
            legacy_ready.set()
            assert native_finished.wait(10)

    def after(conn, cursor, statement, parameters, context, executemany):
        if is_lock(statement) and not native_locked.is_set():
            native_locked.set()
            assert legacy_ready.wait(10), 'Legacy writer never reached the competing state'

    original_guard = quiz_corrections.is_pending_correction

    def pending_guard(progress):
        result = original_guard(progress)
        if lock_requests == 1:  # Unprotected legacy code, before this fix.
            legacy_ready.set()
            assert native_finished.wait(10)
        return result

    monkeypatch.setattr(quiz_corrections, 'is_pending_correction', pending_guard)

    def native():
        try:
            response = post(case, opened['session_token'], {'0': 'is', '1': 'are'})
            return response.status_code, response.json
        finally:
            native_finished.set()

    def legacy():
        assert native_locked.wait(10)
        if writer == 'autosave':
            with case.app.test_client() as client:
                with client.session_transaction() as session:
                    session['_user_id'] = case.session_id
                    session['_fresh'] = True
                response = client.post(f'/curriculum/api/lesson/{case.lesson_id}/progress',
                                       json={'status': 'in_progress', 'data': {'answers': {}}})
                return response.json.get('error') if response.status_code == 409 else 'overwrote'
        with case.app.test_request_context('/retained-browser-writer', method='POST'):
            login_user(db.session.get(User, case.user_id))
            lesson = db.session.get(Lessons, case.lesson_id)
            grade = process_grammar_submission(lesson.content['exercises'], {'0': 'am', '1': 'are'})
            try:
                if writer == 'complete':
                    from app.curriculum.service import complete_lesson
                    complete_lesson(case.user_id, case.lesson_id, 100)
                elif writer == 'upsert':
                    ProgressService.create_or_update_progress(case.user_id, case.lesson_id,
                                                               status='completed', score=100, data=grade)
                else:
                    ProgressService.update_progress_with_grading(case.user_id, lesson, grade, 50)
                return 'overwrote'
            except ValueError as error:
                db.session.rollback()
                return str(error)

    engine = db.engine
    db.session.remove()
    event.listen(engine, 'before_cursor_execute', before)
    event.listen(engine, 'after_cursor_execute', after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(native)
            second = pool.submit(legacy)
            result, legacy_result = first.result(timeout=30), second.result(timeout=30)
        assert result[0] == 200 and result[1]['score'] == 50 and result[1]['correction_pending'], result
        assert legacy_result == 'correction_required'
        db.session.remove()
        progress = LessonProgress.query.filter_by(user_id=case.user_id, lesson_id=case.lesson_id).one()
        assert progress.status == 'in_progress' and progress.last_score == 50
        assert progress.data['quiz_correction']['first_answers'] == {'0': 'is', '1': 'are'}
        assert LessonAttempt.query.filter_by(user_id=case.user_id, lesson_id=case.lesson_id).count() == 1
    finally:
        event.remove(engine, 'before_cursor_execute', before)
        event.remove(engine, 'after_cursor_execute', after)
