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

from sqlalchemy.exc import IntegrityError

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
    """Race-safe upsert, same shape as ``grant_achievement``/``write_secured_at``.

    Dismiss and submit can arrive together (two tabs, a double click); a bare
    SELECT-then-INSERT lets both see ``None`` and the loser dies on the
    ``survey_prompts`` primary key.
    """
    prompt = get_prompt(user_id)
    if prompt is not None:
        return prompt
    try:
        with db.session.begin_nested():
            prompt = SurveyPrompt(user_id=user_id, dismiss_count=0)
            db.session.add(prompt)
            db.session.flush()
        return prompt
    except IntegrityError:
        pass
    # Lost the race: the winner has committed by the time the constraint fired,
    # so the row is visible now. If it still is not (the winner rolled back
    # instead), create it ourselves — returning None here would surface as an
    # AttributeError in the caller.
    prompt = get_prompt(user_id)
    if prompt is not None:
        return prompt
    # Savepoint here too: a third writer can land between the re-fetch above
    # and this insert, and an IntegrityError escaping a race-safe helper would
    # poison the caller's whole transaction.
    try:
        with db.session.begin_nested():
            prompt = SurveyPrompt(user_id=user_id, dismiss_count=0)
            db.session.add(prompt)
            db.session.flush()
        return prompt
    except IntegrityError:
        prompt = get_prompt(user_id)
        if prompt is None:
            raise
        return prompt


def record_survey_dismissal(user_id: int) -> SurveyPrompt:
    """Count one explicit "not now". Flushes only — caller commits."""
    prompt = _get_or_create_prompt(user_id)
    if prompt.answered_at is None:
        prompt.dismiss_count = (prompt.dismiss_count or 0) + 1
        prompt.dismissed_at = _now()
        db.session.flush()
    return prompt


def claim_survey_answer(user_id: int) -> bool:
    """Close the survey and report whether *this* call was the one that closed it.

    ``should_show_survey`` is a read: two submits from two tabs can both pass it
    before either writes, and then both create a ``Feedback`` thread. The claim
    is a conditional UPDATE — under READ COMMITTED the loser blocks on the row
    lock, re-evaluates ``answered_at IS NULL`` after the winner commits, and
    matches nothing. Only the winner may go on to create the thread.

    Flushes only — the caller commits (and must roll back on failure, which
    releases the claim along with everything else).
    """
    _get_or_create_prompt(user_id)
    updated = (
        db.session.query(SurveyPrompt)
        .filter(SurveyPrompt.user_id == user_id, SurveyPrompt.answered_at.is_(None))
        .update({SurveyPrompt.answered_at: _now()}, synchronize_session=False)
    )
    db.session.flush()
    return bool(updated)


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
