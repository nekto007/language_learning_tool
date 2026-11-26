"""Navigation between a verified dispute and the topic it cites."""

from copy import deepcopy
from uuid import uuid4

import pytest
from flask import Flask, g
from flask.testing import FlaskClient

from app.auth.models import User
from app.curriculum.answer_disputes import AnswerDispute, AnswerDisputeReport
from app.curriculum.models import Lessons
from app.grammar_lab.content_install import install_catalog
from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.utils.db import db
from tests.admin.test_guided_topic_editor import INDEX, _field, _fields, _page, installed_topic
from tests.api.test_course_receipt_expiry import sign_in

DISPUTES = '/admin/answer-disputes'


def _case(row: dict, *, exercise_id: int | None = None, lesson_id: int | None = None,
          reporter_id: int | None = None) -> AnswerDispute:
    case = AnswerDispute(grammar_exercise_id=exercise_id, lesson_id=lesson_id, question_id='0',
                         question_revision='1' * 64, grader_version=1, status='pending',
                         normalized_answer_hash=uuid4().hex * 2,
                         evidence={'row': deepcopy(row), 'question': {'prompt': row.get('question', '')},
                                   'answer': 'A synthetic answer.'})
    db.session.add(case)
    db.session.flush()
    if reporter_id is not None:
        db.session.add(AnswerDisputeReport(dispute_id=case.id, user_id=reporter_id))
    db.session.commit()
    return case


@pytest.mark.parametrize('source', ['lab', 'course'])
def test_moderator_guided_links_through_editor_preview_publish_and_revocation(
    app: Flask, admin_client: FlaskClient, admin_user: User, test_user: User,
    installed_topic: tuple[GrammarTopic, Lessons, Lessons, dict],  # noqa: F811
    source: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    topic, lesson, _, document = installed_topic
    test_user.is_moderator = True
    db.session.commit()
    exercise = db.session.get(GrammarExercise, topic.content['guided_exercise_ids'][0])
    case = (_case(exercise.content, exercise_id=exercise.id, reporter_id=admin_user.id) if source == 'lab' else
            _case(lesson.content['exercises'][0], lesson_id=lesson.id, reporter_id=admin_user.id))
    case_path = f'{DISPUTES}/{case.id}'
    topic_path = f'{INDEX}/{topic.id}'
    link = f'{topic_path}?from_dispute={case.id}'
    moderator = app.test_client()
    sign_in(moderator, app, test_user)
    dispute = _page(moderator.get(case_path))
    assert dispute.select_one('#dispute-guided-topic')['href'] == link
    assert not dispute.select_one('#learners-heading, .disputes-reporters, a[href*="/admin/users/"]')
    assert admin_user.username not in dispute.get_text()

    other = GrammarTopic(slug='a1-7', title='Synthetic other', title_ru='Synthetic other', level='A1', content={})
    db.session.add(other)
    db.session.commit()
    other_doc = {**deepcopy(document), 'topic_slug': other.slug, 'title': 'Other installed theme'}
    install_catalog(documents={other.slug: other_doc}, apply=True)
    assert not _page(moderator.get(f'{INDEX}/{other.id}?from_dispute={case.id}')).select_one('#guided-dispute-back')
    assert not _page(moderator.get(topic_path + '?from_dispute=https://example.invalid')).select_one('#guided-dispute-back')

    editor = _page(moderator.get(link))
    assert editor.select_one('#guided-dispute-back')['href'] == case_path
    form = editor.select_one('.guided-main-form')
    assert form['action'] == f'{topic_path}/preview?from_dispute={case.id}'
    csrf = _field(editor, 'csrf_token')
    invalid = _page(moderator.post(form['action'], data=_fields(topic, document, csrf_token=csrf, goal=' ')), 422)
    assert invalid.select_one('#guided-dispute-back')['href'] == case_path
    body = _fields(topic, document, csrf_token=csrf, goal='A new synthetic objective.')
    staged = _page(moderator.post(form['action'], data=body))
    assert staged.select_one('#guided-dispute-back')['href'] == case_path
    draft = _page(moderator.get(staged.select_one('a[href*="draft="]')['href']))
    assert draft.select_one('#guided-dispute-back')['href'] == case_path
    assert draft.select_one('#guided-goal').text == body['goal']

    publish = staged.select_one(f'form[action^="{topic_path}/publish"]')['action']
    token = _field(staged, 'preview_id')
    posted = moderator.post(publish, data={'csrf_token': _field(staged, 'csrf_token'), 'preview_id': token})
    assert posted.status_code == 303 and posted.location == link
    published = _page(moderator.get(posted.location))
    assert published.select_one('#guided-dispute-back')['href'] == case_path
    assert _page(moderator.get(case_path)).select_one('#dispute-guided-topic')['href'] == link

    sign_in(admin_client, app, admin_user)
    old = _page(admin_client.get(case_path))
    source_link = (f'/admin/grammar-lab/exercises/{exercise.id}/edit' if source == 'lab'
                   else f'/curriculum/admin/lesson/{lesson.id}/view')
    assert old.select_one(f'.disputes-detail-head a[href="{source_link}"]')
    assert old.select_one('#learners-heading')

    sign_in(moderator, app, test_user)
    editor = _page(moderator.get(link))
    csrf = _field(editor, 'csrf_token')
    preview = _page(moderator.post(form['action'],
                                  data=_fields(topic, document, csrf_token=csrf, goal='Another synthetic objective.')))
    moderator_csrf, preview_id = _field(preview, 'csrf_token'), _field(preview, 'preview_id')
    sign_in(admin_client, app, admin_user)
    user_page = _page(admin_client.get(f'/admin/users/{test_user.id}'))
    role_url = f'/admin/users/{test_user.id}/moderator'
    role_form = user_page.select_one(f'form[action="{role_url}"]')
    assert admin_client.post(role_url, data={'csrf_token': _field(role_form, 'csrf_token'),
                                            'is_moderator': '0'}).status_code == 303
    g.pop('_login_user', None)
    g.pop('csrf_token', None)
    assert moderator.get(link).status_code in (302, 403)
    assert moderator.get(case_path).status_code in (302, 403)
    assert moderator.post(publish, data={'csrf_token': moderator_csrf, 'preview_id': preview_id}).status_code in (302, 403)
    assert topic.content['learning_goal'] == body['goal']


@pytest.mark.parametrize('reason', ['ordinary-lab', 'retired-lab', 'duplicate', 'reference-quiz', 'mismatched-digest'])
def test_never_link_a_dispute_without_exact_guided_ownership(
    app: Flask, test_user: User, installed_topic: tuple[GrammarTopic, Lessons, Lessons, dict],  # noqa: F811
    reason: str,
) -> None:
    topic, lesson, final, _ = installed_topic
    test_user.is_moderator = True
    exercise = db.session.get(GrammarExercise, topic.content['guided_exercise_ids'][0])
    sample = deepcopy(exercise.content)
    if reason == 'retired-lab':
        exercise.content = {**exercise.content, 'guided_retired': True}
        case = _case(sample, exercise_id=exercise.id)
    elif reason == 'ordinary-lab':
        exercise.content = {'question': 'Ordinary'}
        case = _case(exercise.content, exercise_id=exercise.id)
    elif reason == 'duplicate':
        topic.content = {**topic.content, 'exercises': [*topic.content['exercises'], sample]}
        case = _case(sample, exercise_id=exercise.id)
    elif reason == 'reference-quiz':
        final.type = 'quiz'
        final.content = {'questions': [sample], 'guided_catalog_digest': topic.content['guided_catalog_digest']}
        case = _case(sample, lesson_id=final.id)
    else:
        lesson.content = {**lesson.content, 'guided_catalog_digest': 'different'}
        case = _case(sample, lesson_id=lesson.id)
    moderator = app.test_client()
    sign_in(moderator, app, test_user)
    assert not _page(moderator.get(f'{DISPUTES}/{case.id}')).select_one('#dispute-guided-topic')
    assert not _page(moderator.get(f'{INDEX}/{topic.id}?from_dispute={case.id}')).select_one('#guided-dispute-back')
