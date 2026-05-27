"""Tests for the idiom lesson type — Task 88."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.validators import LessonContentValidator
from app.daily_plan.linear.xp import LESSON_TYPE_TO_SOURCE
from tests.conftest import unique_level_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_idiom_lesson(db_session, items=None) -> Lessons:
    if items is None:
        items = [
            {
                'phrase': 'Break a leg',
                'meaning': 'Good luck',
                'example': 'Break a leg at your performance tonight!',
            },
            {
                'phrase': 'Hit the nail on the head',
                'meaning': 'To describe exactly what is causing a situation or problem',
                'example': "You've hit the nail on the head — that's exactly the issue.",
                'audio_url': '/static/audio/idiom_test.mp3',
            },
        ]
    level = CEFRLevel(code=unique_level_code(), name='Level', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='Test Module',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Idiom Test',
        type='idiom',
        content={'items': items},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _read_template() -> str:
    p = (
        Path(__file__).parent.parent.parent
        / 'app'
        / 'templates'
        / 'curriculum'
        / 'lessons'
        / 'idiom.html'
    )
    return p.read_text(encoding='utf-8')


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------

class TestIdiomValidator:
    def test_valid_payload_passes(self):
        ok, err, data = LessonContentValidator.validate(
            'idiom',
            {
                'items': [
                    {
                        'phrase': 'Break a leg',
                        'meaning': 'Good luck',
                        'example': 'Break a leg tonight!',
                    }
                ]
            },
        )
        assert ok is True
        assert err is None
        assert len(data['items']) == 1

    def test_missing_phrase_fails(self):
        with pytest.raises(Exception):
            LessonContentValidator.validate(
                'idiom',
                {'items': [{'meaning': 'Good luck', 'example': 'Break a leg!'}]},
            )

    def test_missing_meaning_fails(self):
        with pytest.raises(Exception):
            LessonContentValidator.validate(
                'idiom',
                {'items': [{'phrase': 'Break a leg', 'example': 'Break a leg!'}]},
            )

    def test_missing_example_fails(self):
        with pytest.raises(Exception):
            LessonContentValidator.validate(
                'idiom',
                {'items': [{'phrase': 'Break a leg', 'meaning': 'Good luck'}]},
            )

    def test_empty_items_fails(self):
        with pytest.raises(Exception):
            LessonContentValidator.validate('idiom', {'items': []})

    def test_audio_url_optional(self):
        ok, _, data = LessonContentValidator.validate(
            'idiom',
            {
                'items': [
                    {
                        'phrase': 'Break a leg',
                        'meaning': 'Good luck',
                        'example': 'Break a leg!',
                        'audio_url': '/audio/test.mp3',
                    }
                ]
            },
        )
        assert ok is True
        assert data['items'][0]['audio_url'] == '/audio/test.mp3'

    def test_multiple_items_pass(self):
        ok, _, data = LessonContentValidator.validate(
            'idiom',
            {
                'items': [
                    {'phrase': 'Break a leg', 'meaning': 'Good luck', 'example': 'Ex 1'},
                    {'phrase': 'Hit the sack', 'meaning': 'Go to bed', 'example': 'Ex 2'},
                ]
            },
        )
        assert ok is True
        assert len(data['items']) == 2


# ---------------------------------------------------------------------------
# XP mapping tests
# ---------------------------------------------------------------------------

class TestIdiomXPMapping:
    def test_idiom_maps_to_linear_curriculum_vocabulary(self):
        assert LESSON_TYPE_TO_SOURCE.get('idiom') == 'linear_curriculum_vocabulary'

    def test_linear_curriculum_vocabulary_xp_is_18(self):
        from app.achievements.xp_service import LINEAR_XP
        assert LINEAR_XP.get('linear_curriculum_vocabulary') == 18


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

class TestIdiomTemplate:
    def test_template_exists(self):
        tpl = _read_template()
        assert len(tpl) > 100

    def test_phrase_rendered(self):
        tpl = _read_template()
        assert 'idiom-phrase' in tpl
        assert 'item.phrase' in tpl

    def test_meaning_block_present(self):
        tpl = _read_template()
        assert 'idiom-meaning-block' in tpl
        assert 'item.meaning' in tpl

    def test_example_block_present(self):
        tpl = _read_template()
        assert 'idiom-example' in tpl
        assert 'item.example' in tpl

    def test_reveal_button_present(self):
        tpl = _read_template()
        assert 'reveal-btn-' in tpl
        assert 'revealMeaning(' in tpl

    def test_self_assess_checkbox_present(self):
        tpl = _read_template()
        assert 'self-cb-' in tpl
        assert 'onSelfAssessChange(' in tpl
        assert 'type="checkbox"' in tpl

    def test_finish_button_present(self):
        tpl = _read_template()
        assert 'finish-btn' in tpl
        assert 'finishLesson()' in tpl

    def test_multiple_items_loop(self):
        tpl = _read_template()
        assert 'for item in items' in tpl

    def test_audio_conditional_rendering(self):
        tpl = _read_template()
        assert "item.get('audio_url')" in tpl

    def test_meaning_reveal_animation(self):
        tpl = _read_template()
        assert 'idiom-meaning-block--revealed' in tpl

    def test_item_done_tracking(self):
        tpl = _read_template()
        assert 'itemDone' in tpl
        assert 'markItemDone' in tpl

    def test_progress_label_present(self):
        tpl = _read_template()
        assert 'progress-label' in tpl
        assert 'current-idx' in tpl


# ---------------------------------------------------------------------------
# Route tests — GET
# ---------------------------------------------------------------------------

class TestIdiomRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        lesson = _make_idiom_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f'/curriculum/lesson/{lesson.id}/idiom')
        assert resp.status_code == 200

    def test_get_creates_in_progress_record(self, app, db_session, test_user, client):
        lesson = _make_idiom_lesson(db_session)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/idiom')
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == 'in_progress'

    def test_lesson_detail_redirects_to_idiom_route(self, app, db_session, test_user, client):
        lesson = _make_idiom_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f'/curriculum/lesson/{lesson.id}', follow_redirects=False)
        assert resp.status_code == 302
        assert 'idiom' in resp.headers.get('Location', '')

    def test_wrong_type_redirects(self, app, db_session, test_user, client, test_lesson_vocabulary):
        _login(client, test_user)
        resp = client.get(f'/curriculum/lesson/{test_lesson_vocabulary.id}/idiom')
        assert resp.status_code in (302, 400)


# ---------------------------------------------------------------------------
# Route tests — POST submit
# ---------------------------------------------------------------------------

class TestIdiomSubmit:
    def _submit(self, client, lesson_id: int, finish: bool = False):
        return client.post(
            f'/curriculum/api/lesson/{lesson_id}/submit',
            json={'lesson_type': 'idiom', 'finish': finish},
            content_type='application/json',
        )

    def test_finish_true_returns_completed(self, app, db_session, test_user, client):
        lesson = _make_idiom_lesson(db_session)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/idiom')
        resp = self._submit(client, lesson.id, finish=True)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['completed'] is True

    def test_finish_false_not_completed(self, app, db_session, test_user, client):
        lesson = _make_idiom_lesson(db_session)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/idiom')
        resp = self._submit(client, lesson.id, finish=False)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['completed'] is False

    def test_finish_marks_lesson_completed(self, app, db_session, test_user, client):
        lesson = _make_idiom_lesson(db_session)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/idiom')
        self._submit(client, lesson.id, finish=True)
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == 'completed'

    def test_unauthenticated_submit_redirects(self, app, db_session, client):
        lesson = _make_idiom_lesson(db_session)
        resp = client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={'lesson_type': 'idiom', 'finish': True},
        )
        assert resp.status_code in (302, 401, 403)
