"""Two-week product survey: who gets asked, and what an answer becomes."""

from datetime import UTC, datetime, timedelta

import pytest

from app.feedback.models import (
    SURVEY_MAX_PROMPTS,
    SURVEY_MIN_ACCOUNT_AGE_DAYS,
    SURVEY_SNOOZE_DAYS,
    Feedback,
    SurveyPrompt,
)
from app.feedback.survey import (
    build_survey_message,
    record_survey_dismissal,
    should_show_survey,
)


def _naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _age_account(db_session, user, days: int):
    """Backdate registration so the account looks `days` old."""
    user.created_at = _naive_now() - timedelta(days=days)
    db_session.commit()
    return user


class TestShouldShowSurvey:
    def test_fresh_account_is_not_asked(self, db_session, test_user):
        _age_account(db_session, test_user, SURVEY_MIN_ACCOUNT_AGE_DAYS - 1)

        assert should_show_survey(test_user) is False

    def test_two_week_old_account_is_asked(self, db_session, test_user):
        _age_account(db_session, test_user, SURVEY_MIN_ACCOUNT_AGE_DAYS)

        assert should_show_survey(test_user) is True

    def test_long_standing_account_is_asked(self, db_session, test_user):
        # A threshold, not a window: users who registered months ago must still
        # get the invitation, otherwise the survey would launch to nobody.
        _age_account(db_session, test_user, 180)

        assert should_show_survey(test_user) is True

    def test_answered_account_is_never_asked_again(self, db_session, test_user):
        _age_account(db_session, test_user, 30)
        db_session.add(SurveyPrompt(user_id=test_user.id, answered_at=_naive_now()))
        db_session.commit()

        assert should_show_survey(test_user) is False

    def test_first_dismissal_hides_it_for_a_week(self, db_session, test_user):
        _age_account(db_session, test_user, 30)
        db_session.add(SurveyPrompt(
            user_id=test_user.id, dismiss_count=1, dismissed_at=_naive_now(),
        ))
        db_session.commit()

        assert should_show_survey(test_user) is False

    def test_it_returns_once_after_the_snooze(self, db_session, test_user):
        _age_account(db_session, test_user, 30)
        db_session.add(SurveyPrompt(
            user_id=test_user.id,
            dismiss_count=1,
            dismissed_at=_naive_now() - timedelta(days=SURVEY_SNOOZE_DAYS + 1),
        ))
        db_session.commit()

        assert should_show_survey(test_user) is True

    def test_second_dismissal_closes_it_for_good(self, db_session, test_user):
        _age_account(db_session, test_user, 30)
        db_session.add(SurveyPrompt(
            user_id=test_user.id,
            dismiss_count=SURVEY_MAX_PROMPTS,
            dismissed_at=_naive_now() - timedelta(days=365),
        ))
        db_session.commit()

        assert should_show_survey(test_user) is False

    def test_anonymous_is_not_asked(self):
        assert should_show_survey(None) is False


class TestBuildSurveyMessage:
    def test_skipped_questions_are_dropped(self):
        message = build_survey_message({'works': 'Карточки', 'annoys': '', 'missing': None})

        assert 'Что работает хорошо?' in message
        assert 'Карточки' in message
        assert 'Что раздражает' not in message

    def test_empty_answers_produce_nothing(self):
        assert build_survey_message({'works': '   ', 'annoys': '', 'missing': ''}) == ''


class TestSurveyEndpoints:
    def test_submit_creates_a_survey_feedback_thread(
        self, authenticated_client, db_session, test_user,
    ):
        _age_account(db_session, test_user, 30)

        resp = authenticated_client.post('/api/feedback/survey', json={
            'works': 'Повторения удобные',
            'annoys': 'Много кликов',
        })

        assert resp.status_code == 201, resp.data
        row = Feedback.query.get(resp.get_json()['id'])
        assert row.category == 'survey'
        assert row.user_id == test_user.id
        assert 'Повторения удобные' in row.message
        assert 'Много кликов' in row.message

    def test_submitting_closes_the_survey(self, authenticated_client, db_session, test_user):
        _age_account(db_session, test_user, 30)
        authenticated_client.post('/api/feedback/survey', json={'works': 'Всё нравится'})

        assert should_show_survey(test_user) is False

    def test_empty_submission_is_rejected(self, authenticated_client, db_session, test_user):
        _age_account(db_session, test_user, 30)

        resp = authenticated_client.post('/api/feedback/survey', json={
            'works': '', 'annoys': '  ', 'missing': '',
        })

        assert resp.status_code == 400
        # Scoped to this user: a global count would depend on sibling tests
        # being rolled back before this one runs.
        assert Feedback.query.filter_by(
            category='survey', user_id=test_user.id,
        ).count() == 0

    def test_non_string_answer_is_rejected(self, authenticated_client, db_session, test_user):
        _age_account(db_session, test_user, 30)

        resp = authenticated_client.post('/api/feedback/survey', json={'works': 42})

        assert resp.status_code == 400

    def test_dismiss_counts_and_then_silences(self, authenticated_client, db_session, test_user):
        _age_account(db_session, test_user, 30)

        first = authenticated_client.post('/api/feedback/survey/dismiss', json={})
        assert first.status_code == 200
        assert first.get_json()['dismiss_count'] == 1
        assert should_show_survey(test_user) is False

        # Simulate the week passing, then dismiss again — that one is final.
        prompt = SurveyPrompt.query.get(test_user.id)
        prompt.dismissed_at = _naive_now() - timedelta(days=SURVEY_SNOOZE_DAYS + 1)
        db_session.commit()
        assert should_show_survey(test_user) is True

        record_survey_dismissal(test_user.id)
        db_session.commit()
        assert should_show_survey(test_user) is False

    def test_a_json_array_body_is_a_400_not_a_500(
        self, authenticated_client, db_session, test_user,
    ):
        # `get_json() or {}` keeps a non-empty list, which has no `.get`.
        _age_account(db_session, test_user, 30)

        resp = authenticated_client.post(
            '/api/feedback/survey',
            data='[1]',
            content_type='application/json',
        )

        assert resp.status_code == 400

    def test_an_answered_account_cannot_post_again(
        self, authenticated_client, db_session, test_user,
    ):
        # The "at most twice, never again once answered" contract is enforced on
        # the endpoint, not only by whether the dashboard renders the invite.
        _age_account(db_session, test_user, 30)
        db_session.add(SurveyPrompt(user_id=test_user.id, answered_at=_naive_now()))
        db_session.commit()

        resp = authenticated_client.post('/api/feedback/survey', json={'works': 'ещё раз'})

        assert resp.status_code == 409
        assert Feedback.query.filter_by(
            category='survey', user_id=test_user.id,
        ).count() == 0

    def test_a_fresh_account_cannot_post(
        self, authenticated_client, db_session, test_user,
    ):
        _age_account(db_session, test_user, SURVEY_MIN_ACCOUNT_AGE_DAYS - 1)

        resp = authenticated_client.post('/api/feedback/survey', json={'works': 'рано'})

        assert resp.status_code == 409

    def test_dismissal_is_idempotent_under_a_double_click(
        self, authenticated_client, db_session, test_user,
    ):
        # `_get_or_create_prompt` inserts the row; two arrivals must not collide
        # on the survey_prompts primary key.
        _age_account(db_session, test_user, 30)

        first = authenticated_client.post('/api/feedback/survey/dismiss', json={})
        second = authenticated_client.post('/api/feedback/survey/dismiss', json={})

        assert first.status_code == 200
        assert second.status_code == 200
        assert SurveyPrompt.query.get(test_user.id).dismiss_count == 2

    def test_survey_requires_login(self, client):
        resp = client.post('/api/feedback/survey', json={'works': 'x'})

        assert resp.status_code in (302, 401)

    def test_survey_category_is_not_user_submittable(
        self, authenticated_client, db_session, test_user,
    ):
        # The free-form widget must not be able to forge survey answers.
        resp = authenticated_client.post(
            '/api/feedback', json={'category': 'survey', 'message': 'подделка'},
        )

        assert resp.status_code == 400


@pytest.mark.smoke
class TestAdminSeesSurveys:
    def test_admin_list_filters_by_survey_category(self, admin_client):
        # Guards the hardcoded label maps: an unknown category used to raise
        # a KeyError in the admin filter dropdown and 500 the page.
        resp = admin_client.get('/admin/feedback?category=survey')

        assert resp.status_code == 200
