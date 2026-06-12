"""Tests for LanguageTool grammar feedback on writing lessons."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.curriculum.models import (
    CEFRLevel, Lessons, Module, UserWritingAttempt, save_writing_attempt,
)
from app.utils.languagetool import check_text
from tests.conftest import unique_level_code

LT_URL = 'http://lt.test:8010'

LT_RESPONSE = {
    'matches': [
        {
            'offset': 0,
            'length': 2,
            'message': 'Possible spelling mistake found.',
            'shortMessage': 'Spelling mistake',
            'replacements': [
                {'value': 'He'}, {'value': 'She'}, {'value': 'It'}, {'value': 'We'},
            ],
            'rule': {
                'id': 'MORFOLOGIK_RULE_EN_US',
                'category': {'id': 'TYPOS', 'name': 'Possible Typo'},
            },
        },
        {
            'offset': 3,
            'length': 4,
            'message': 'Subject-verb agreement error.',
            'shortMessage': '',
            'replacements': [],
            'rule': {
                'id': 'AGREEMENT_X',
                'category': {'id': 'GRAMMAR', 'name': 'Grammar'},
            },
        },
    ],
}


def _mock_response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _make_writing_lesson(db_session, *, min_words: int = 5,
                         content_extra: dict | None = None) -> Lessons:
    level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id, number=1, title='M', description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    content = {'prompt': 'Write about your day.', 'min_words': min_words}
    if content_extra:
        content.update(content_extra)
    lesson = Lessons(
        module_id=module.id, number=1, title='Writing', type='writing_prompt',
        content=content,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


@pytest.mark.smoke
class TestCheckText:
    def test_disabled_without_url(self, app):
        with app.app_context():
            app.config['LANGUAGETOOL_URL'] = ''
            assert check_text('He go to school.') is None

    def test_parses_matches(self, app):
        with app.app_context():
            app.config['LANGUAGETOOL_URL'] = LT_URL
            with patch('app.utils.languagetool.requests.post',
                       return_value=_mock_response(LT_RESPONSE)) as mock_post:
                result = check_text('He go to school.')
            app.config['LANGUAGETOOL_URL'] = ''

        assert result is not None
        assert result['error_count'] == 2
        first = result['matches'][0]
        assert first['offset'] == 0
        assert first['length'] == 2
        assert first['category_label'] == 'Орфография'
        assert first['replacements'] == ['He', 'She', 'It']  # cap 3
        second = result['matches'][1]
        assert second['category_label'] == 'Грамматика'
        assert mock_post.call_args.kwargs['data']['language'] == 'en-US'

    def test_server_error_returns_none(self, app):
        with app.app_context():
            app.config['LANGUAGETOOL_URL'] = LT_URL
            with patch('app.utils.languagetool.requests.post',
                       side_effect=requests.ConnectionError('down')):
                result = check_text('He go to school.')
            app.config['LANGUAGETOOL_URL'] = ''
        assert result is None

    def test_malformed_payload_returns_none(self, app):
        with app.app_context():
            app.config['LANGUAGETOOL_URL'] = LT_URL
            with patch('app.utils.languagetool.requests.post',
                       return_value=_mock_response({'software': {}})):
                result = check_text('He go to school.')
            app.config['LANGUAGETOOL_URL'] = ''
        assert result is None

    def test_empty_text_returns_none(self, app):
        with app.app_context():
            app.config['LANGUAGETOOL_URL'] = LT_URL
            assert check_text('   ') is None
            app.config['LANGUAGETOOL_URL'] = ''


@pytest.mark.smoke
class TestSaveWritingAttemptGrammar:
    def test_stores_grammar_fields(self, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        from app.utils.db import db
        attempt = save_writing_attempt(
            test_user.id, lesson.id, 'He go to school.', True, db,
            grammar_check={'error_count': 1, 'matches': [{'offset': 0, 'length': 2}]},
        )
        assert attempt.grammar_error_count == 1
        assert attempt.grammar_matches == [{'offset': 0, 'length': 2}]

    def test_without_check_fields_are_null(self, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        from app.utils.db import db
        attempt = save_writing_attempt(
            test_user.id, lesson.id, 'He go to school.', True, db,
        )
        assert attempt.grammar_error_count is None
        assert attempt.grammar_matches is None


@pytest.mark.smoke
class TestWritingSubmissionGrammar:
    def _submit(self, client, lesson_id: int, text: str):
        from app.curriculum.routes.lessons import _DEFAULT_WRITING_CHECKLIST
        return client.post(
            f'/curriculum/api/lesson/{lesson_id}/submit',
            json={
                'response_text': text,
                'checklist_completed': True,
                'checked_items': _DEFAULT_WRITING_CHECKLIST[:2],
                'lesson_type': 'writing_prompt',
            },
            content_type='application/json',
        )

    def test_grammar_block_in_response(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session, min_words=5)
        _login(client, test_user)
        with patch('app.utils.languagetool.check_text',
                   return_value={'error_count': 2, 'matches': LT_RESPONSE['matches'][:0]}):
            # check_text импортируется внутри обработчика — патчим source-модуль
            resp = self._submit(client, lesson.id, 'one two three four five six')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['grammar']['checked'] is True
        assert data['grammar']['error_count'] == 2

        from app.utils.db import db as _db
        row = (
            _db.session.query(UserWritingAttempt)
            .filter_by(user_id=test_user.id, lesson_id=lesson.id)
            .order_by(UserWritingAttempt.id.desc())
            .first()
        )
        assert row is not None
        assert row.grammar_error_count == 2

    def test_grammar_unavailable_degrades(self, app, db_session, test_user, client):
        lesson = _make_writing_lesson(db_session, min_words=5)
        _login(client, test_user)
        with patch('app.utils.languagetool.check_text', return_value=None):
            resp = self._submit(client, lesson.id, 'one two three four five six')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['grammar']['checked'] is False
        assert data['grammar']['error_count'] is None

        from app.utils.db import db as _db
        row = (
            _db.session.query(UserWritingAttempt)
            .filter_by(user_id=test_user.id, lesson_id=lesson.id)
            .order_by(UserWritingAttempt.id.desc())
            .first()
        )
        assert row is not None
        assert row.grammar_error_count is None

    def test_short_text_no_grammar_block(self, app, db_session, test_user, client):
        # min_words игнорируется ниже B1 (_writing_words_required), поэтому
        # порог задаём через min_sentences — он применяется всегда.
        lesson = _make_writing_lesson(
            db_session, content_extra={'min_sentences': 5},
        )
        _login(client, test_user)
        with patch('app.utils.languagetool.check_text') as mock_check:
            resp = self._submit(client, lesson.id, 'Too short.')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'grammar' not in data
        mock_check.assert_not_called()
