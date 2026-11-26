"""The catalogue can open an accessible lesson outside the learner's current plan step."""
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from flask import g
from flask_jwt_extended import create_access_token

from app.api.native_lessons import _signer
from app.curriculum.models import LessonAttempt, LessonProgress, Lessons
from app.utils.db import db
from tests.api.test_course_receipt_expiry import receipt, sign_in


def test_catalogue_practice_does_not_complete_a_different_plan_step(
    receipt: dict[str, Any],  # noqa: F811 -- shared fixture.
) -> None:
    app, user, web, headers = (receipt[key] for key in ('app', 'user', 'client', 'headers'))
    first, previous = receipt['lesson'], receipt['other_lesson']
    current = Lessons(
        module_id=first.module_id, number=3, order=3, type='reading', title='Third lesson',
        content={'text': 'I will read the map.', 'exercises': [
            {'type': 'ordering', 'words': ['I', 'read', 'maps', '.'], 'correct': 'I read maps.'},
        ]},
    )
    later = Lessons(module_id=first.module_id, number=4, order=4, type='reading',
                    title='Fourth lesson', content=current.content)
    db.session.add_all([current, later, LessonProgress(
        user_id=user.id, lesson_id=previous.id, status='completed', completed_at=datetime.now(UTC) - timedelta(days=2),
    )])
    db.session.commit()
    lesson_id, next_id, first_id = current.id, later.id, first.id
    route = f'/learn/{lesson_id}/'
    endpoint = f'/curriculum/api/lesson/{lesson_id}/practice'

    catalogue = BeautifulSoup(web.get(route).text, 'html.parser').select_one('#guided-practice')
    plan = BeautifulSoup(web.get(route + '?from=linear_plan&slot=curriculum').text, 'html.parser').select_one('#guided-practice')
    assert catalogue['data-course-practice'] == 'true' and 'data-result-plan' not in catalogue.attrs
    assert catalogue['data-course-next'] == f'/learn/{next_id}/'
    assert '/module-' in urlsplit(catalogue.find('a')['href']).path
    assert 'data-result-plan' in plan.attrs and 'data-course-practice' not in plan.attrs
    assert web.get(endpoint).json['error'] == 'lesson_locked'
    assert web.get(f'/curriculum/api/lesson/{next_id}/practice?mode=course').json['error'] == 'lesson_locked'

    doc = web.get(endpoint + '?mode=course')
    assert doc.status_code == 200
    token = doc.json['lesson']['session_token']
    assert _signer().loads(token)['web_course'] is True
    answer = '["0","1","2"]'
    check = {'session_token': token, 'question_id': '0', 'answer': answer}
    body = {'session_token': token, 'answers': {'0': answer}}
    native = app.test_client()
    token_for_api = create_access_token(identity=str(user.id), additional_claims={'auth_version': user.auth_version()})
    bearer = {'Authorization': 'Bearer ' + token_for_api}
    assert native.get(f'/api/native/lessons/{lesson_id}?mode=course', headers=bearer).status_code == 403
    for action, payload in [('check', check), ('submit', body)]:
        native_response = native.post(f'/api/native/lessons/{lesson_id}/{action}', headers=bearer, json=payload)
        assert native_response.status_code == 403

    # Mode is a signed claim, not a query or body override of an older token.
    sealed = _signer().loads(token)
    del sealed['web_course']
    ordinary_token = _signer().dumps(sealed)
    assert web.post(endpoint + '/check?mode=course', headers=headers,
                    json=check | {'session_token': ordinary_token}).status_code == 403
    assert web.post(endpoint + '/submit?mode=course', headers=headers,
                    json=body | {'session_token': ordinary_token}).status_code == 403
    assert web.post(endpoint + '/check', json=check).status_code == 400
    assert web.post(endpoint + '/check', headers=headers, json=check).json['feedback']['correct']
    result = web.post(endpoint + '/submit', headers=headers, json=body)
    assert result.status_code == 200 and result.json['completed']
    assert web.post(endpoint + '/submit', headers=headers, json=body).json == result.json
    assert LessonAttempt.query.filter_by(user_id=user.id, lesson_id=lesson_id).count() == 1
    assert LessonProgress.query.filter_by(user_id=user.id, lesson_id=first_id).first() is None
    assert web.get(f'/curriculum/api/lesson/{first_id}/practice').status_code == 200

    from tests.api.test_native_full_integration import learner

    other, _ = learner(app)
    other.onboarding_completed = True
    db.session.commit()
    second_web = app.test_client()
    other_csrf = sign_in(second_web, app, other)
    g.pop('_login_user', None)
    refused = second_web.post(endpoint + '/submit', headers=other_csrf, json=body)
    assert refused.status_code == 403
