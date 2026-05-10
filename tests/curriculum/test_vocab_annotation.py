"""Tests for VocabAnnotation model and annotation API.

Task 37: Vocabulary journal (user word annotations).
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.curriculum.models import VocabAnnotation, get_annotation_for_word, save_annotation
from app.utils.db import db
from app.words.models import CollectionWords


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique() -> str:
    return uuid.uuid4().hex[:12]


def _make_word(db_session) -> CollectionWords:
    word = CollectionWords(
        english_word=f"annword_{_unique()}",
        russian_word="тестовое слово",
        level="B1",
    )
    db_session.add(word)
    db_session.commit()
    return word


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestVocabAnnotationModel:
    def test_model_creates_correctly(self, app, db_session, test_user):
        word = _make_word(db_session)
        annotation = VocabAnnotation(
            user_id=test_user.id,
            word_id=word.id,
            note="my note about this word",
        )
        db_session.add(annotation)
        db_session.commit()

        fetched = db_session.get(VocabAnnotation, annotation.id)
        assert fetched is not None
        assert fetched.user_id == test_user.id
        assert fetched.word_id == word.id
        assert fetched.note == "my note about this word"
        assert fetched.added_at is not None

    def test_repr_contains_key_fields(self, app, db_session, test_user):
        word = _make_word(db_session)
        annotation = VocabAnnotation(
            user_id=test_user.id,
            word_id=word.id,
            note="note",
        )
        db_session.add(annotation)
        db_session.commit()

        r = repr(annotation)
        assert str(test_user.id) in r
        assert str(word.id) in r


class TestGetAnnotationForWord:
    def test_returns_none_when_no_annotation(self, app, db_session, test_user):
        word = _make_word(db_session)
        result = get_annotation_for_word(test_user.id, word.id, db)
        assert result is None

    def test_returns_annotation_when_exists(self, app, db_session, test_user):
        word = _make_word(db_session)
        annotation = VocabAnnotation(
            user_id=test_user.id,
            word_id=word.id,
            note="remembered at party",
        )
        db_session.add(annotation)
        db_session.commit()

        result = get_annotation_for_word(test_user.id, word.id, db)
        assert result is not None
        assert result.note == "remembered at party"

    def test_returns_only_current_users_annotation(self, app, db_session, test_user):
        from app.auth.models import User
        uname = f"other_{_unique()}"
        other = User(
            email=f"{uname}@test.com",
            username=uname,
        )
        other.set_password("testpass")
        db_session.add(other)
        db_session.commit()

        word = _make_word(db_session)
        ann_other = VocabAnnotation(user_id=other.id, word_id=word.id, note="other note")
        db_session.add(ann_other)
        db_session.commit()

        result = get_annotation_for_word(test_user.id, word.id, db)
        assert result is None


class TestSaveAnnotation:
    def test_creates_new_annotation(self, app, db_session, test_user):
        word = _make_word(db_session)
        ann = save_annotation(test_user.id, word.id, "first note", db)
        db_session.commit()

        assert ann.id is not None
        assert ann.note == "first note"

    def test_update_replaces_old_annotation(self, app, db_session, test_user):
        word = _make_word(db_session)
        save_annotation(test_user.id, word.id, "first note", db)
        db_session.commit()

        save_annotation(test_user.id, word.id, "updated note", db)
        db_session.commit()

        rows = db_session.query(VocabAnnotation).filter_by(
            user_id=test_user.id, word_id=word.id
        ).all()
        assert len(rows) == 1
        assert rows[0].note == "updated note"

    def test_different_words_get_separate_annotations(self, app, db_session, test_user):
        word1 = _make_word(db_session)
        word2 = _make_word(db_session)
        save_annotation(test_user.id, word1.id, "note1", db)
        save_annotation(test_user.id, word2.id, "note2", db)
        db_session.commit()

        ann1 = get_annotation_for_word(test_user.id, word1.id, db)
        ann2 = get_annotation_for_word(test_user.id, word2.id, db)
        assert ann1.note == "note1"
        assert ann2.note == "note2"


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class TestSaveWordAnnotationEndpoint:
    def test_save_annotation_returns_ok(self, app, db_session, test_user, client):
        word = _make_word(db_session)
        _login(client, test_user)

        resp = client.post(
            f"/curriculum/api/words/{word.id}/annotation",
            data=json.dumps({"note": "important word"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["note"] == "important word"
        assert data["word_id"] == word.id

    def test_update_replaces_via_api(self, app, db_session, test_user, client):
        word = _make_word(db_session)
        _login(client, test_user)

        client.post(
            f"/curriculum/api/words/{word.id}/annotation",
            data=json.dumps({"note": "first"}),
            content_type="application/json",
        )
        resp = client.post(
            f"/curriculum/api/words/{word.id}/annotation",
            data=json.dumps({"note": "updated"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["note"] == "updated"

        rows = db_session.query(VocabAnnotation).filter_by(
            user_id=test_user.id, word_id=word.id
        ).all()
        assert len(rows) == 1

    def test_empty_note_returns_400(self, app, db_session, test_user, client):
        word = _make_word(db_session)
        _login(client, test_user)

        resp = client.post(
            f"/curriculum/api/words/{word.id}/annotation",
            data=json.dumps({"note": "   "}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_unauthenticated_returns_redirect(self, app, db_session, client):
        word = _make_word(db_session)
        resp = client.post(
            f"/curriculum/api/words/{word.id}/annotation",
            data=json.dumps({"note": "test"}),
            content_type="application/json",
        )
        assert resp.status_code in (302, 401)

    def test_annotation_persisted_after_save(self, app, db_session, test_user, client):
        word = _make_word(db_session)
        _login(client, test_user)

        client.post(
            f"/curriculum/api/words/{word.id}/annotation",
            data=json.dumps({"note": "persisted note"}),
            content_type="application/json",
        )

        # refresh session to verify persistence
        db_session.expire_all()
        ann = get_annotation_for_word(test_user.id, word.id, db)
        assert ann is not None
        assert ann.note == "persisted note"


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

class TestAnnotationTemplate:
    def test_annotation_widget_in_template(self):
        from pathlib import Path
        tpl = (
            Path(__file__).parent.parent.parent
            / "app" / "templates" / "curriculum" / "lessons" / "vocabulary.html"
        ).read_text(encoding="utf-8")

        assert "word-annotation" in tpl
        assert "word-annotation__toggle" in tpl
        assert "word-annotation__input" in tpl
        assert "word-annotation__save" in tpl

    def test_existing_annotation_shown_in_template(self):
        from pathlib import Path
        tpl = (
            Path(__file__).parent.parent.parent
            / "app" / "templates" / "curriculum" / "lessons" / "vocabulary.html"
        ).read_text(encoding="utf-8")

        assert "word.annotation" in tpl
        assert "word-annotation__text" in tpl
