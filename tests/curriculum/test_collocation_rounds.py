"""Collocation matching: rounds of six and a first-try score (lesson audit
2026-09-05, A2 / B3, owner decision «XP за правильные ответы»).

Before: twenty pairs in two columns at once; a wrong pick flashed and was
forgotten, the client finalised only with the correct pairs, so every lesson
scored 100 % and the XP was always maximal.
"""
from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from app.curriculum.models import CEFRLevel, LessonAttempt, LessonProgress, Lessons, Module
from app.curriculum.routes.lessons import COLLOCATION_ROUND_SIZE, _collocation_rounds
from tests.conftest import unique_level_code

TEMPLATE = 'app/templates/curriculum/lessons/collocation_matching.html'


@pytest.fixture()
def _module(db_session):
    level = CEFRLevel(code=unique_level_code(), name='Level', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(level_id=level.id, number=1, title='CM Module', description='d',
                    raw_content={'module': {'id': 1}})
    db_session.add(module)
    db_session.commit()
    return module


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _pairs(n: int) -> list[dict]:
    return [{'phrase': f'phrase {i}', 'translation': f'перевод {i}'} for i in range(n)]


def _make_lesson(db_session, module, n: int) -> Lessons:
    lesson = Lessons(module_id=module.id, number=1, title='CM', type='collocation_matching',
                     content={'pairs': _pairs(n)})
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _progress(db_session, user_id, lesson_id):
    db_session.expire_all()
    return LessonProgress.query.filter_by(user_id=user_id, lesson_id=lesson_id).first()


class TestRoundsHelper:

    def test_chunks_of_six_and_no_lonely_last_pair(self):
        assert COLLOCATION_ROUND_SIZE == 6
        assert _collocation_rounds(14) == [[0, 1, 2, 3, 4, 5], [6, 7, 8, 9, 10, 11], [12, 13]]
        assert _collocation_rounds(13) == [[0, 1, 2, 3, 4, 5], [6, 7, 8, 9, 10, 11, 12]]
        assert _collocation_rounds(6) == [[0, 1, 2, 3, 4, 5]]
        assert _collocation_rounds(1) == [[0]]
        assert _collocation_rounds(0) == []


class TestRender:

    def test_rounds_are_rendered_and_translations_stay_inside_their_round(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, 14)
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/collocation-matching').get_data(as_text=True)
        rows = re.findall(r'id="phrase-row-(\d+)" data-round="(\d+)"', html)
        assert [(int(a), int(b)) for a, b in rows] == [(i, i // 6) for i in range(14)]
        trans = re.findall(r'id="trans-(\d+)"\s+type="button"\s+data-index="\d+"\s+data-round="(\d+)"\s+data-translation="([^"]*)"', html)
        assert len(trans) == 14
        by_round: dict[int, set] = {}
        for _, r, text in trans:
            by_round.setdefault(int(r), set()).add(text)
        assert by_round[0] == {f'перевод {i}' for i in range(6)}
        assert by_round[1] == {f'перевод {i}' for i in range(6, 12)}
        assert by_round[2] == {'перевод 12', 'перевод 13'}
        assert 'id="cm-pager"' in html and 'из 3' in html
        assert re.search(r'id="phrase-row-6" data-round="1" hidden', html)
        assert not re.search(r'id="phrase-row-0" data-round="0" hidden', html)

    def test_single_round_has_no_pager(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, 5)
        _login(client, test_user)
        html = client.get(f'/curriculum/lesson/{lesson.id}/collocation-matching').get_data(as_text=True)
        assert 'id="cm-pager"' not in html

    def test_lesson_content_is_not_mutated(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, 8)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/collocation-matching')
        db_session.expire_all()
        assert db_session.get(Lessons, lesson.id).content['pairs'] == _pairs(8)


class TestMissesAreRecordedServerSide:

    def _check(self, client, lesson, idx, answer):
        return client.post(f'/curriculum/api/lesson/{lesson.id}/check-item', json={'index': idx, 'answer': answer})

    def test_wrong_picks_are_counted_and_survive_a_reload(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, 6)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/collocation-matching')
        assert self._check(client, lesson, 3, 'перевод 0').get_json()['correct'] is False
        assert self._check(client, lesson, 3, 'перевод 1').get_json()['correct'] is False
        assert self._check(client, lesson, 3, 'перевод 3').get_json()['correct'] is True
        assert self._check(client, lesson, 0, 'перевод 0').get_json()['correct'] is True
        progress = _progress(db_session, test_user.id, lesson.id)
        assert progress.data['cm_misses'] == {'3': 2}
        client.get(f'/curriculum/lesson/{lesson.id}/collocation-matching')  # reload keeps them
        assert _progress(db_session, test_user.id, lesson.id).data['cm_misses'] == {'3': 2}


class TestFirstTryScore:

    def _submit(self, client, lesson, pairs):
        return client.post(f'/curriculum/api/lesson/{lesson.id}/submit',
                           json={'user_pairs': pairs, 'lesson_type': 'collocation_matching'})

    def test_two_misses_out_of_six_score_67_and_still_complete(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, 6)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/collocation-matching')
        for idx, wrong in ((1, 'перевод 4'), (5, 'перевод 0'), (5, 'перевод 2')):
            client.post(f'/curriculum/api/lesson/{lesson.id}/check-item', json={'index': idx, 'answer': wrong})
        with patch('app.daily_plan.linear.xp.maybe_award_curriculum_xp', return_value=None) as xp:
            resp = self._submit(client, lesson, _pairs(6))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['passed'] is True and data['score'] == 67
        assert data['first_try_items'] == 4 and data['matched_items'] == 6
        assert [m['index'] for m in data['mistakes']] == [1, 5]
        assert data['mistakes'][1]['attempts'] == 3
        assert xp.call_args.kwargs['score'] == 67
        progress = _progress(db_session, test_user.id, lesson.id)
        assert progress.status == 'completed' and progress.score == 67
        attempt = LessonAttempt.query.filter_by(user_id=test_user.id, lesson_id=lesson.id).order_by(LessonAttempt.id.desc()).first()
        assert attempt is not None and [m['phrase'] for m in attempt.mistakes] == ['phrase 1', 'phrase 5']

    def test_clean_run_scores_100(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, 6)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/collocation-matching')
        data = self._submit(client, lesson, _pairs(6)).get_json()
        assert data['score'] == 100 and data['first_try_items'] == 6 and data['mistakes'] == []

    def test_a_terrible_first_try_score_still_completes(self, app, db_session, _module, test_user, client):
        """Owner: the score scales XP, it never blocks completion."""
        lesson = _make_lesson(db_session, _module, 6)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/collocation-matching')
        for idx in range(5):
            client.post(f'/curriculum/api/lesson/{lesson.id}/check-item', json={'index': idx, 'answer': 'перевод 5'})
        with patch('app.daily_plan.linear.xp.maybe_award_curriculum_xp', return_value=None) as xp:
            data = self._submit(client, lesson, _pairs(6)).get_json()
        assert data['score'] == 17 and data['passed'] is True
        assert _progress(db_session, test_user.id, lesson.id).status == 'completed'
        assert xp.call_args.kwargs['score'] == 17

    def test_partial_submit_does_not_complete(self, app, db_session, _module, test_user, client):
        """A crafted POST with two pairs of six is still not a finished lesson."""
        lesson = _make_lesson(db_session, _module, 6)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/collocation-matching')
        data = self._submit(client, lesson, _pairs(2)).get_json()
        assert data['passed'] is False
        assert _progress(db_session, test_user.id, lesson.id).status != 'completed'

    def test_misses_of_the_finished_attempt_do_not_leak_into_the_next(self, app, db_session, _module, test_user, client):
        lesson = _make_lesson(db_session, _module, 6)
        _login(client, test_user)
        client.get(f'/curriculum/lesson/{lesson.id}/collocation-matching')
        client.post(f'/curriculum/api/lesson/{lesson.id}/check-item', json={'index': 0, 'answer': 'перевод 5'})
        assert self._submit(client, lesson, _pairs(6)).get_json()['score'] == 83
        # retake: no misses this time
        client.get(f'/curriculum/lesson/{lesson.id}/collocation-matching?retry=true')
        assert self._submit(client, lesson, _pairs(6)).get_json()['score'] == 100


class TestTemplateSource:

    def test_pager_and_rounds_are_wired(self):
        with open(TEMPLATE, encoding='utf-8') as f:
            src = f.read()
        assert 'function showRound(' in src and 'function _roundDone(' in src
        assert 'id="cm-next-round"' in src
        assert "data-round=\"{{ round_of_phrase[loop.index0] }}\"" in src
        assert 'С первой попытки:' in src
        assert 'shuffled_pairs' in src  # global translation index is unchanged
