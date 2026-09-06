"""Rendering and selection edge cases for the grammar reminder."""

from types import SimpleNamespace
from unittest.mock import patch

from flask import render_template

from app.curriculum import grammar_digest as gd
from app.curriculum.models import Lessons
from tests.curriculum.test_grammar_digest import _module, _lesson, _topic


def test_anonymous_digest_escapes_all_authored_fields(app, db_session):
    module = _module(db_session)
    grammar = Lessons.query.filter_by(module_id=module.id, type='grammar').one()
    attack = '<img src=x onerror=alert(1)>'
    grammar.title = attack
    grammar.content = {'rule': attack, 'important_notes': [attack],
                       'examples': [{'english': attack, 'russian': attack}]}
    db_session.commit()
    lesson = _lesson(db_session, module, 6)
    with app.test_request_context(), patch.object(gd, '_topic_is_weak') as weak:
        html = render_template('curriculum/lessons/_grammar_digest.html', lesson=lesson)
    weak.assert_not_called()
    assert attack not in html
    assert html.count('&lt;img src=x onerror=alert(1)&gt;') == 5


def test_missing_number_does_not_query_module(app):
    with app.test_request_context(), patch.object(gd, '_module_grammar_lesson') as query:
        assert gd.grammar_digest_for_template(SimpleNamespace(number=None, type='reading', module_id=1)) is None
    query.assert_not_called()


def test_two_grammar_lessons_select_first_by_number(app, db_session):
    module = _module(db_session)
    db_session.add(Lessons(module_id=module.id, number=8, title='Later grammar',
                           type='grammar', content={'rule': 'Later rule'}))
    db_session.commit()
    lesson = _lesson(db_session, module, 10)
    with app.test_request_context():
        digest = gd.build_grammar_digest(lesson)
    assert digest['lesson_number'] == 4


def test_weak_signal_failure_keeps_theory_visible(app, db_session, test_user):
    module = _module(db_session)
    topic = _topic(db_session)
    grammar = Lessons.query.filter_by(module_id=module.id, type='grammar').one()
    grammar.grammar_topic_id = topic.id
    db_session.commit()
    lesson = _lesson(db_session, module, 6)
    with app.test_request_context(), patch.object(gd, '_topic_is_weak', side_effect=RuntimeError('aggregate unavailable')):
        digest = gd.build_grammar_digest(lesson, user_id=test_user.id)
    assert digest['rule'] and digest['weak'] is False
