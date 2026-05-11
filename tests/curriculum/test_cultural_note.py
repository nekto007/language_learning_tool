"""Tests for CulturalNote model and get_cultural_notes_for_word helper.

Task 85: Cultural notes system.
"""
from __future__ import annotations

import uuid

from app.curriculum.models import CulturalNote, get_cultural_notes_for_word
from app.utils.db import db
from app.words.models import CollectionWords


def _make_word(db_session) -> CollectionWords:
    word = CollectionWords(
        english_word=f"testword_{uuid.uuid4().hex[:12]}",
        russian_word="тестовое слово",
        level="B1",
    )
    db_session.add(word)
    db_session.commit()
    return word


class TestCulturalNoteModel:
    def test_model_creates_correctly(self, app, db_session):
        word = _make_word(db_session)
        note = CulturalNote(
            word_id=word.id,
            note="In British English this word is considered formal.",
            context="British English",
        )
        db_session.add(note)
        db_session.commit()

        fetched = db_session.get(CulturalNote, note.id)
        assert fetched is not None
        assert fetched.word_id == word.id
        assert fetched.note == "In British English this word is considered formal."
        assert fetched.context == "British English"

    def test_model_without_context(self, app, db_session):
        word = _make_word(db_session)
        note = CulturalNote(
            word_id=word.id,
            note="Often used in colloquial speech.",
        )
        db_session.add(note)
        db_session.commit()

        fetched = db_session.get(CulturalNote, note.id)
        assert fetched.context is None

    def test_created_at_set_automatically(self, app, db_session):
        word = _make_word(db_session)
        note = CulturalNote(word_id=word.id, note="Test note.")
        db_session.add(note)
        db_session.commit()

        fetched = db_session.get(CulturalNote, note.id)
        assert fetched.created_at is not None

    def test_repr_contains_key_fields(self, app, db_session):
        word = _make_word(db_session)
        note = CulturalNote(word_id=word.id, note="Test.", context="Formal")
        db_session.add(note)
        db_session.commit()

        r = repr(note)
        assert str(word.id) in r
        assert "Formal" in r

    def test_get_cultural_notes_returns_empty_for_word_without_notes(self, app, db_session):
        word = _make_word(db_session)
        result = get_cultural_notes_for_word(word.id, db)
        assert result == []

    def test_get_cultural_notes_returns_all_for_word(self, app, db_session):
        word = _make_word(db_session)
        n1 = CulturalNote(word_id=word.id, note="Note A", context="Context A")
        n2 = CulturalNote(word_id=word.id, note="Note B")
        db_session.add_all([n1, n2])
        db_session.commit()

        result = get_cultural_notes_for_word(word.id, db)
        assert len(result) == 2
        notes_text = {n.note for n in result}
        assert "Note A" in notes_text
        assert "Note B" in notes_text

    def test_get_cultural_notes_does_not_return_other_words_notes(self, app, db_session):
        word1 = _make_word(db_session)
        word2 = _make_word(db_session)
        db_session.add(CulturalNote(word_id=word1.id, note="Word1 note"))
        db_session.add(CulturalNote(word_id=word2.id, note="Word2 note"))
        db_session.commit()

        result = get_cultural_notes_for_word(word1.id, db)
        assert len(result) == 1
        assert result[0].note == "Word1 note"

    def test_multiple_notes_per_word_allowed(self, app, db_session):
        word = _make_word(db_session)
        for i in range(4):
            db_session.add(CulturalNote(word_id=word.id, note=f"Note {i}"))
        db_session.commit()

        result = get_cultural_notes_for_word(word.id, db)
        assert len(result) == 4


class TestCulturalNoteAdmin:
    def test_admin_list_route_returns_200(self, app, client, db_session):
        from app.auth.models import User
        admin_user = db_session.query(User).filter_by(is_admin=True).first()
        if admin_user is None:
            admin_user = User(
                email=f"admin_{uuid.uuid4().hex[:8]}@test.com",
                username=f"admin_{uuid.uuid4().hex[:8]}",
                is_admin=True,
                onboarding_completed=True,
            )
            admin_user.set_password("adminpass")
            db_session.add(admin_user)
            db_session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.get('/admin/cultural-notes')
        assert response.status_code == 200

    def test_admin_add_note(self, app, client, db_session):
        from app.auth.models import User
        admin_user = db_session.query(User).filter_by(is_admin=True).first()
        if admin_user is None:
            admin_user = User(
                email=f"admin_{uuid.uuid4().hex[:8]}@test.com",
                username=f"admin_{uuid.uuid4().hex[:8]}",
                is_admin=True,
                onboarding_completed=True,
            )
            admin_user.set_password("adminpass")
            db_session.add(admin_user)
            db_session.commit()

        word = _make_word(db_session)

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        with client.application.test_request_context():
            from flask_wtf.csrf import generate_csrf
            token = generate_csrf()

        response = client.post('/admin/cultural-notes/add', data={
            'word_id': word.id,
            'note': 'Admin-added note',
            'context': 'Formal',
            'csrf_token': token,
        }, follow_redirects=True)
        assert response.status_code == 200

        note = db_session.query(CulturalNote).filter_by(word_id=word.id).first()
        assert note is not None
        assert note.note == 'Admin-added note'
        assert note.context == 'Formal'
