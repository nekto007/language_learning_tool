"""Grammar digest before lessons 6+ of a module (app/curriculum/grammar_digest.py)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

from flask import url_for

from app.curriculum import grammar_digest as gd
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from tests.conftest import unique_level_code

GRAMMAR_CONTENT = {
    'rule': 'Наречия частотности показывают, как часто происходит действие.',
    'important_notes': ['⚠️ С обычными глаголами: подлежащее + наречие + глагол', '⚠️ С глаголом BE: подлежащее + BE + наречие', 'третья', 'четвёртая'],
    'sections': [
        {'subtitle': 'Шкала', 'description': '', 'table': [
            {'word': 'always', 'example': 'I always wake up early.', 'translation': 'Я всегда просыпаюсь рано.'},
            {'word': 'usually', 'example': 'I usually drink tea.', 'example_translation': 'Я обычно пью чай.'},
            {'word': 'never', 'example': 'I always wake up early.', 'translation': 'дубль'},
            {'word': 'often', 'example': 'I often drink coffee.', 'translation': 'Я часто пью кофе.'},
            {'word': 'rarely', 'example': 'I rarely watch TV.', 'translation': 'Я редко смотрю телевизор.'},
        ]},
        {'subtitle': 'Позиция', 'rules': ['после подлежащего']},
    ],
    'examples': [],
    'exercises': [],
}

SHADOW_CONTENT = {'audio_url': '/static/audio/test.mp3', 'text': 'The quick brown fox.', 'translation': 'Быстрая лиса.'}


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _module(db_session, *, with_grammar: bool = True) -> Module:
    level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(level_id=level.id, number=1, title='Привычки', description='d', raw_content={'module': {'id': 1}})
    db_session.add(module)
    db_session.commit()
    if with_grammar:
        db_session.add(Lessons(module_id=module.id, number=4, title='Грамматика: Наречия частотности', type='grammar', content=GRAMMAR_CONTENT))
        db_session.commit()
    return module


def _topic(db_session):
    from app.grammar_lab.models import GrammarTopic
    slug = f'digest-topic-{uuid.uuid4().hex[:8]}'
    topic = GrammarTopic()
    topic.slug = slug
    topic.title = f'Topic {slug}'
    topic.title_ru = f'Тема {slug}'
    topic.level = 'A1'
    topic.order = 1
    topic.content = {}
    db_session.add(topic)
    db_session.commit()
    return topic


def _unlock_up_to(db_session, user, module: Module, number: int) -> None:
    """check_lesson_access wants the previous lesson completed: mark everything before ``number`` done."""
    for lesson in Lessons.query.filter(Lessons.module_id == module.id, Lessons.number < number).all():
        db_session.add(LessonProgress(user_id=user.id, lesson_id=lesson.id, status='completed', score=100.0))
    db_session.commit()


def _lesson(db_session, module: Module, number: int, lesson_type: str = 'shadow_reading') -> Lessons:
    lesson = Lessons(module_id=module.id, number=number, title=f'L{number} {uuid.uuid4().hex[:4]}', type=lesson_type, content=SHADOW_CONTENT)
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestExamples:
    def test_table_rows_dedupe_and_cap(self):
        out = gd._examples_from_content(GRAMMAR_CONTENT)
        assert [e['en'] for e in out] == ['I always wake up early.', 'I usually drink tea.', 'I often drink coffee.']
        assert out[1]['ru'] == 'Я обычно пью чай.'  # example_translation fallback

    def test_example_lists_and_empty(self):
        content = {'sections': [{'examples': [{'english': 'He is late.', 'russian': 'Он опаздывает.'}]}]}
        assert gd._examples_from_content(content) == [{'en': 'He is late.', 'ru': 'Он опаздывает.'}]
        assert gd._examples_from_content({}) == []


class TestBuild:
    def test_before_lesson_six_and_on_grammar_itself_nothing(self, app, db_session):
        module = _module(db_session)
        with app.test_request_context():
            assert gd.build_grammar_digest(_lesson(db_session, module, 5)) is None
            assert gd.build_grammar_digest(SimpleNamespace(type='grammar', number=6, module_id=module.id)) is None
            assert gd.build_grammar_digest(None) is None

    def test_module_without_grammar_lesson(self, app, db_session):
        module = _module(db_session, with_grammar=False)
        with app.test_request_context():
            assert gd.build_grammar_digest(_lesson(db_session, module, 6)) is None

    def test_digest_content(self, app, db_session):
        module = _module(db_session)
        lesson = _lesson(db_session, module, 10)
        with app.test_request_context():
            digest = gd.build_grammar_digest(lesson)
        assert digest['title'] == 'Наречия частотности'
        assert digest['rule'].startswith('Наречия частотности')
        assert len(digest['notes']) == gd.MAX_NOTES
        assert len(digest['examples']) == gd.MAX_EXAMPLES
        assert digest['weak'] is False and digest['lesson_number'] == 4
        with app.test_request_context():
            assert digest['theory_url'] == url_for('learn.lesson_by_id', lesson_id=gd._module_grammar_lesson(module.id).id)

    def test_weak_topic_flags_and_a_failing_check_does_not_hide(self, app, db_session, test_user):
        module = _module(db_session)
        lesson = _lesson(db_session, module, 7)
        grammar = gd._module_grammar_lesson(module.id)
        with app.test_request_context():
            with patch.object(gd, '_topic_is_weak', return_value=True):
                assert gd.build_grammar_digest(lesson, user_id=test_user.id)['weak'] is False  # no topic: no signal
            grammar.grammar_topic_id = _topic(db_session).id
            db_session.commit()
            with patch.object(gd, '_topic_is_weak', return_value=True):
                digest = gd.build_grammar_digest(lesson, user_id=test_user.id)
                assert digest['weak'] is True and digest['practice_url']
            with patch.object(gd, '_topic_is_weak', side_effect=RuntimeError('boom')):
                assert gd.build_grammar_digest(lesson, user_id=test_user.id)['weak'] is False
            assert gd.build_grammar_digest(lesson)['weak'] is False  # anonymous: no signal


class TestRender:
    def _open(self, app, client, lesson) -> str:
        with app.test_request_context():
            url = url_for('learn.lesson_by_id', lesson_id=lesson.id)
        resp = client.get(url, follow_redirects=True)
        assert resp.status_code == 200
        return resp.get_data(as_text=True)

    def test_digest_from_lesson_six_only(self, app, db_session, test_user, client):
        module = _module(db_session)
        _login(client, test_user)
        fifth, sixth = _lesson(db_session, module, 5), _lesson(db_session, module, 6)
        _unlock_up_to(db_session, test_user, module, 6)
        assert 'lsn-grammar-digest' not in self._open(app, client, fifth)
        html = self._open(app, client, sixth)
        assert 'lsn-grammar-digest' in html
        assert 'Наречия частотности показывают' in html
        assert 'I always wake up early.' in html
        assert 'Полная теория' in html

    def test_weak_marks_the_block_and_opens_examples(self, app, db_session, test_user, client):
        module = _module(db_session)
        grammar = gd._module_grammar_lesson(module.id)
        grammar.grammar_topic_id = _topic(db_session).id
        db_session.commit()
        _login(client, test_user)
        lesson = _lesson(db_session, module, 8)
        _unlock_up_to(db_session, test_user, module, 8)
        with patch.object(gd, '_topic_is_weak', return_value=True):
            html = self._open(app, client, lesson)
        assert 'lsn-grammar-digest--weak' in html and 'были ошибки' in html
        assert '<details class="lsn-grammar-digest__more" open>' in html
