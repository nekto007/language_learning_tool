"""Reading preview uses the course grader on the saved lesson with a separate admin receipt."""
from datetime import timedelta
from typing import Any

from bs4 import BeautifulSoup
from flask import g

from app.admin.audit import AdminAuditLog
from app.achievements.models import StreakEvent, UserStatistics
from app.auth.models import User
from app.curriculum.models import LessonAttempt, LessonProgress
from app.daily_plan.models import DailyPlanLog
from app.utils.db import db
from app.utils.time_utils import get_user_local_date
from tests.api.test_course_receipt_expiry import receipt, sign_in


def test_reading_preview_uses_grader_without_plan_or_learner_writes(
    receipt: dict[str, Any], admin_user: User,  # noqa: F811 -- shared test fixture.
) -> None:
    app, lesson = receipt['app'], receipt['lesson']
    lesson.type = 'reading'
    lesson.content = {
        'text': 'They found an old map.',
        'exercises': [{'type': 'ordering', 'words': ['They', 'found', 'a', 'map', '.'],
                       'correct': 'They found a map.'}],
    }
    admin_user.onboarding_completed = True
    admin_user.plan_paused_until = get_user_local_date(admin_user.id) + timedelta(days=1)
    db.session.commit()
    lesson_id = lesson.id
    base = f'/curriculum/admin/lesson/{lesson_id}'
    preview = base + '/reading-preview'
    native_path = f'/curriculum/api/lesson/{lesson_id}/practice'
    client = app.test_client()
    csrf = sign_in(client, app, admin_user)

    def state() -> tuple[int, ...]:
        return tuple(model.query.count() for model in (
            LessonProgress, LessonAttempt, DailyPlanLog, StreakEvent, UserStatistics, AdminAuditLog,
        ))

    previous = state()
    denied = client.get(native_path)
    assert denied.status_code == 403 and denied.json['error'] == 'plan_paused'
    card = BeautifulSoup(client.get(base + '/view').text, 'html.parser')
    assert card.find('a', string=lambda value: value and 'Открыть как ученик' in value)['href'] == preview
    page = client.get(preview)
    assert page.status_code == 200 and page.headers['Cache-Control'] == 'private, no-store'
    assert 'data-reading-preview="true"' in page.text
    assert 'data-result-plan' not in page.text
    opened = client.get(preview + '/practice')
    assert opened.status_code == 200
    doc = opened.json['lesson']
    assert doc['questions'][0]['input'] == 'order'
    assert list(sorted(option['label'] for option in doc['questions'][0]['options'])) == [
        'They', 'a', 'found', 'map',
    ]
    assert doc['questions'][0]['order_terminal'] == {'value': '4', 'label': '.'}
    body = {'session_token': doc['session_token'], 'question_id': '0'}
    check_path = preview + '/practice/check'
    assert client.post(check_path, json=body | {'answer': '["0","1","2","3","4"]'}).status_code == 400
    for answer, expected in [('["0","1","2","3","4"]', True), ('["1","0","2","3","4"]', False)]:
        checked = client.post(check_path, headers=csrf, json=body | {'answer': answer})
        assert checked.status_code == 200 and checked.json['feedback']['correct'] is expected
    # Even an admin cannot replay a preview receipt into the learner API.
    ordinary_check = client.post(native_path + '/check', headers=csrf, json=body | {'answer': '["0","1","2","3","4"]'})
    ordinary_submit = client.post(native_path + '/submit', headers=csrf,
                                  json={'session_token': doc['session_token'], 'answers': {'0': '["0","1","2","3","4"]'}})
    assert ordinary_check.status_code == ordinary_submit.status_code == 409
    assert client.post(preview + '/practice/submit', headers=csrf, json={}).status_code == 404
    assert state() == previous

    lesson.content = lesson.content | {'text': 'A new version of the reading.'}
    db.session.commit()
    stale = client.post(check_path, headers=csrf, json=body | {'answer': '["0","1","2","3","4"]'})
    assert stale.status_code == 409 and stale.json['error'] == 'lesson_changed'

    learner = app.test_client()
    learner_csrf = sign_in(learner, app, receipt['user'])
    for path in (preview, preview + '/practice'):
        g.pop('_login_user', None)
        assert learner.get(path).status_code == 302
    g.pop('_login_user', None)
    assert learner.post(check_path, headers=learner_csrf, json=body | {'answer': '["0","1","2","3","4"]'}).status_code == 302
    assert state() == previous
