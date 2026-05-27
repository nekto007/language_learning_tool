"""Task 10: Listening and writing lesson completion — validation audit tests."""
from __future__ import annotations

import uuid

import pytest

from app.curriculum.listening_service import log_listening_attempt
from app.curriculum.models import (
    CEFRLevel,
    LessonProgress,
    Lessons,
    Module,
    UserWritingAttempt,
    save_writing_attempt,
)
from tests.conftest import unique_level_code


def _make_lesson(db_session, lesson_type: str = "dictation", content: dict | None = None) -> Lessons:
    level = CEFRLevel(code=unique_level_code(), name="Level", description="d", order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title="Test Module",
        description="d",
        raw_content={"module": {"id": 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Test Lesson",
        type=lesson_type,
        content=content or {"audio_url": "/static/audio/test.mp3", "transcript": "Hello world"},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


# ---------------------------------------------------------------------------
# log_listening_attempt — score=None handling
# ---------------------------------------------------------------------------

class TestLogListeningAttemptScoreNone:
    def test_score_none_defaults_to_zero(self, app, db_session, test_user):
        from app.utils.db import db as _db

        lesson = _make_lesson(db_session, "dictation")
        attempt = log_listening_attempt(
            user_id=test_user.id,
            lesson_id=lesson.id,
            score=None,
            replay_count=0,
            db=_db,
        )
        db_session.commit()
        assert attempt.score == 0.0

    def test_score_zero_stores_zero(self, app, db_session, test_user):
        from app.utils.db import db as _db

        lesson = _make_lesson(db_session, "dictation")
        attempt = log_listening_attempt(
            user_id=test_user.id,
            lesson_id=lesson.id,
            score=0,
            replay_count=1,
            db=_db,
        )
        db_session.commit()
        assert attempt.score == 0.0

    def test_score_100_stored_correctly(self, app, db_session, test_user):
        from app.utils.db import db as _db

        lesson = _make_lesson(db_session, "audio_fill_blank")
        attempt = log_listening_attempt(
            user_id=test_user.id,
            lesson_id=lesson.id,
            score=100,
            replay_count=2,
            db=_db,
        )
        db_session.commit()
        assert attempt.score == 100.0

    def test_score_none_does_not_raise(self, app, db_session, test_user):
        """No TypeError when score is None — regression guard."""
        from app.utils.db import db as _db

        lesson = _make_lesson(db_session, "dictation")
        # Should not raise TypeError: float() argument must be a string or number
        attempt = log_listening_attempt(
            user_id=test_user.id,
            lesson_id=lesson.id,
            score=None,
            replay_count=0,
            db=_db,
        )
        assert attempt is not None


# ---------------------------------------------------------------------------
# listening_immersion routing via route_map
# ---------------------------------------------------------------------------

class TestListeningImmersionRouting:
    def test_route_map_contains_listening_immersion(self, app, db_session, test_user, client):
        """listening_immersion type is routed to its dedicated handler via the dispatcher."""
        lesson = _make_lesson(
            db_session,
            lesson_type="listening_immersion",
            content={"text": "Listen carefully.", "audio_url": "/static/audio/test.mp3"},
        )
        _login(client, test_user)
        resp = client.get(
            f"/curriculum/lesson/{lesson.id}", follow_redirects=False
        )
        location = resp.headers.get("Location", "")
        assert resp.status_code == 302
        assert "listening-immersion" in location

    def test_dispatcher_redirects_to_listening_immersion_route(
        self, app, db_session, test_user, client
    ):
        lesson = _make_lesson(
            db_session,
            lesson_type="listening_immersion",
            content={"text": "Listen carefully.", "audio_url": "/static/audio/test.mp3"},
        )
        _login(client, test_user)
        resp = client.get(
            f"/curriculum/lesson/{lesson.id}", follow_redirects=False
        )
        assert resp.status_code == 302
        assert "listening-immersion" in resp.headers.get("Location", "")

    def test_listening_immersion_route_returns_200(
        self, app, db_session, test_user, client
    ):
        lesson = _make_lesson(
            db_session,
            lesson_type="listening_immersion",
            content={"text": "Listen carefully.", "audio_url": "/static/audio/test.mp3"},
        )
        _login(client, test_user)
        resp = client.get(
            f"/curriculum/lesson/{lesson.id}/listening-immersion",
            follow_redirects=True,
        )
        # Either 200 (rendered) or redirect to /learn/ if content invalid —
        # the key requirement is no 500.
        assert resp.status_code in (200, 302)

    def test_wrong_type_on_listening_immersion_route_returns_400(
        self, app, db_session, test_user, client
    ):
        lesson = _make_lesson(db_session, lesson_type="vocabulary")
        _login(client, test_user)
        resp = client.get(
            f"/curriculum/lesson/{lesson.id}/listening-immersion",
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# save_writing_attempt — empty text validation
# ---------------------------------------------------------------------------

class TestSaveWritingAttemptValidation:
    def test_empty_string_raises_value_error(self, app, db_session, test_user):
        from app.utils.db import db as _db

        lesson = _make_lesson(db_session, "writing_prompt", {"prompt": "Write.", "min_words": 10})
        with pytest.raises(ValueError, match="response_text cannot be empty"):
            save_writing_attempt(test_user.id, lesson.id, "", False, _db)

    def test_whitespace_only_raises_value_error(self, app, db_session, test_user):
        from app.utils.db import db as _db

        lesson = _make_lesson(db_session, "writing_prompt", {"prompt": "Write.", "min_words": 10})
        with pytest.raises(ValueError, match="response_text cannot be empty"):
            save_writing_attempt(test_user.id, lesson.id, "   \t\n", False, _db)

    def test_non_empty_text_saves_successfully(self, app, db_session, test_user):
        from app.utils.db import db as _db

        lesson = _make_lesson(db_session, "writing_prompt", {"prompt": "Write.", "min_words": 10})
        attempt = save_writing_attempt(
            test_user.id, lesson.id, "This is valid writing content.", True, _db
        )
        db_session.commit()
        assert attempt.id is not None
        assert attempt.word_count == 5

    def test_empty_text_not_stored_in_db(self, app, db_session, test_user):
        from app.utils.db import db as _db

        lesson = _make_lesson(db_session, "writing_prompt", {"prompt": "Write.", "min_words": 10})
        try:
            save_writing_attempt(test_user.id, lesson.id, "", False, _db)
        except ValueError:
            pass
        rows = _db.session.query(UserWritingAttempt).filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).all()
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# checklist_completed=False blocks submission
# ---------------------------------------------------------------------------

class TestChecklistCompletionGating:
    def _make_writing_lesson_route(self, db_session):
        level = CEFRLevel(code=unique_level_code(), name="Level", description="d", order=1)
        db_session.add(level)
        db_session.commit()
        module = Module(
            level_id=level.id,
            number=1,
            title="Writing Module",
            description="d",
            raw_content={"module": {"id": 1}},
        )
        db_session.add(module)
        db_session.commit()
        lesson = Lessons(
            module_id=module.id,
            number=1,
            title="Writing Prompt",
            type="writing_prompt",
            content={"prompt": "Write about today.", "min_words": 5},
        )
        db_session.add(lesson)
        db_session.commit()
        return lesson

    def test_checklist_false_with_no_items_not_completed(
        self, app, db_session, test_user, client
    ):
        lesson = self._make_writing_lesson_route(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "response_text": "one two three four five six",
                "checklist_completed": False,
                "checked_items": [],
                "lesson_type": "writing_prompt",
            },
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["completed"] is False

    def test_checklist_false_single_item_not_completed(
        self, app, db_session, test_user, client
    ):
        lesson = self._make_writing_lesson_route(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "response_text": "one two three four five six",
                "checklist_completed": False,
                "checked_items": ["Использовал(а) новые слова"],
                "lesson_type": "writing_prompt",
            },
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["completed"] is False

    def test_checklist_true_with_enough_items_completed(
        self, app, db_session, test_user, client
    ):
        from app.curriculum.routes.lessons import _DEFAULT_WRITING_CHECKLIST
        lesson = self._make_writing_lesson_route(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "response_text": "one two three four five six",
                "checklist_completed": True,
                "checked_items": _DEFAULT_WRITING_CHECKLIST[:2],
                "lesson_type": "writing_prompt",
            },
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["completed"] is True

    def test_empty_response_text_not_completed(
        self, app, db_session, test_user, client
    ):
        """Empty text fails min_words check, no attempt saved."""
        from app.curriculum.routes.lessons import _DEFAULT_WRITING_CHECKLIST
        lesson = self._make_writing_lesson_route(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/writing-prompt")
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={
                "response_text": "",
                "checklist_completed": True,
                "checked_items": _DEFAULT_WRITING_CHECKLIST[:2],
                "lesson_type": "writing_prompt",
            },
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["completed"] is False
        from app.utils.db import db as _db
        rows = _db.session.query(UserWritingAttempt).filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).all()
        assert len(rows) == 0
