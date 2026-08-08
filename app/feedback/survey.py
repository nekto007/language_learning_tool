"""Two-week product survey: when to ask, and how the answers are stored.

The survey is a single, deliberately small ask shown at the moment a learner
closes a study day — the one point in the product where nothing is being
interrupted. It is offered at most twice per account and never again once
answered.

Answers are not a separate entity: they become an ordinary ``Feedback`` row
with category ``survey``, so they inherit the admin queue, the reply thread
and the notification fan-out instead of needing their own screens.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from app.feedback.models import (
    SURVEY_ANSWER_MAX_LENGTH,
    SURVEY_MAX_PROMPTS,
    SURVEY_MIN_ACCOUNT_AGE_DAYS,
    SURVEY_SNOOZE_DAYS,
    SurveyPrompt,
)
from app.utils.db import db

# (payload key, question shown to the learner). Order is the display order and
# the order answers appear in the stored message.
SURVEY_QUESTIONS: Sequence[tuple[str, str]] = (
    ('works', 'Что работает хорошо?'),
    ('annoys', 'Что раздражает или мешает?'),
    ('missing', 'Чего не хватает?'),
)


def _naive_utc(value: datetime | None) -> datetime | None:
    """Normalise to the naive-UTC basis the DateTime columns store.

    ``User.created_at`` is written with an aware default but read back naive,
    so it can be either depending on whether the row was just created.
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def get_prompt(user_id: int) -> SurveyPrompt | None:
    return SurveyPrompt.query.get(user_id)


def should_show_survey(user: Any, now: datetime | None = None) -> bool:
    """Is this learner due to be asked right now?

    True when the account is old enough, the survey has not been answered, and
    the learner has not used up the two offers (the second only after a week's
    pause). Leaving the page is not a dismissal — only the button is.
    """
    if user is None or getattr(user, 'id', None) is None:
        return False

    created_at = _naive_utc(getattr(user, 'created_at', None))
    if created_at is None:
        return False

    moment = _naive_utc(now) or _now()
    if moment - created_at < timedelta(days=SURVEY_MIN_ACCOUNT_AGE_DAYS):
        return False

    prompt = get_prompt(user.id)
    if prompt is None:
        return True
    if prompt.answered_at is not None:
        return False
    if (prompt.dismiss_count or 0) >= SURVEY_MAX_PROMPTS:
        return False

    dismissed_at = _naive_utc(prompt.dismissed_at)
    return dismissed_at is None or moment - dismissed_at >= timedelta(days=SURVEY_SNOOZE_DAYS)


def _get_or_create_prompt(user_id: int) -> SurveyPrompt:
    prompt = get_prompt(user_id)
    if prompt is None:
        prompt = SurveyPrompt(user_id=user_id, dismiss_count=0)
        db.session.add(prompt)
        db.session.flush()
    return prompt


def record_survey_dismissal(user_id: int) -> SurveyPrompt:
    """Count one explicit "not now". Flushes only — caller commits."""
    prompt = _get_or_create_prompt(user_id)
    if prompt.answered_at is None:
        prompt.dismiss_count = (prompt.dismiss_count or 0) + 1
        prompt.dismissed_at = _now()
        db.session.flush()
    return prompt


def mark_survey_answered(user_id: int) -> SurveyPrompt:
    """Close the survey for this account for good. Flushes only."""
    prompt = _get_or_create_prompt(user_id)
    if prompt.answered_at is None:
        prompt.answered_at = _now()
        db.session.flush()
    return prompt


def build_survey_message(answers: dict[str, str]) -> str:
    """Render the filled-in answers as one readable feedback message.

    Empty answers are dropped rather than stored as blank headings — a reader
    should not have to work out which of three questions was skipped.
    """
    parts = []
    for key, question in SURVEY_QUESTIONS:
        text = (answers.get(key) or '').strip()[:SURVEY_ANSWER_MAX_LENGTH]
        if text:
            parts.append(f'{question}\n{text}')
    return '\n\n'.join(parts)
