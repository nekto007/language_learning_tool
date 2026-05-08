"""Flask CLI commands for toggling the linear daily plan feature flag per user."""
from __future__ import annotations

import click
from flask.cli import with_appcontext

from app.auth.models import User
from app.utils.db import db


def _format_linear_plan_status(user_id: int) -> tuple[bool, list[str]]:
    """Build a multi-line status report for the linear daily plan.

    Returns ``(found, lines)`` so callers can set exit codes when the user
    is missing.
    """
    from app.achievements.models import StreakEvent
    from app.daily_plan.linear.errors import count_unresolved
    from app.daily_plan.linear.models import QuizErrorLog, UserReadingPreference
    from app.daily_plan.linear.plan import get_linear_plan
    from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE

    user = db.session.get(User, user_id)
    if user is None:
        return False, [f'User with id={user_id} not found']

    lines: list[str] = []
    lines.append(f'user_id={user.id} username={user.username}')
    lines.append(f'use_linear_plan={bool(user.use_linear_plan)}')

    try:
        plan = get_linear_plan(user.id, db)
    except Exception as exc:  # pragma: no cover - defensive
        plan = None
        lines.append(f'plan_error: {exc!r}')

    if plan is not None:
        slots = plan.get('baseline_slots') or []
        completed = sum(1 for s in slots if s.get('completed'))
        lines.append(
            f'plan: slots={len(slots)} completed={completed} '
            f'day_secured={bool(plan.get("day_secured"))}'
        )
        for s in slots:
            kind = s.get('kind', '?')
            done = 'done' if s.get('completed') else 'pending'
            lines.append(f'  - {kind}: {done}')

    unresolved = count_unresolved(user.id, db)
    lines.append(f'unresolved_errors={unresolved}')

    pref = (
        db.session.query(UserReadingPreference)
        .filter(UserReadingPreference.user_id == user.id)
        .one_or_none()
    )
    if pref is None:
        lines.append('reading_preference: none')
    else:
        title = getattr(getattr(pref, 'book', None), 'title', None) or '?'
        lines.append(f'reading_preference: book_id={pref.book_id} title={title!r}')

    recent = (
        db.session.query(StreakEvent)
        .filter(
            StreakEvent.user_id == user.id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
        )
        .order_by(StreakEvent.created_at.desc())
        .limit(5)
        .all()
    )
    lines.append(f'recent_linear_xp ({len(recent)}):')
    for ev in recent:
        details = ev.details or {}
        source = details.get('source', '?')
        xp = details.get('xp', '?')
        lines.append(f'  - {ev.event_date} {source} xp={xp}')

    last_errors = (
        db.session.query(QuizErrorLog)
        .filter(QuizErrorLog.user_id == user.id)
        .order_by(QuizErrorLog.created_at.desc())
        .limit(5)
        .all()
    )
    lines.append(f'recent_quiz_errors ({len(last_errors)}):')
    for row in last_errors:
        resolved = 'resolved' if row.resolved_at is not None else 'unresolved'
        lines.append(f'  - id={row.id} lesson_id={row.lesson_id} {resolved}')

    return True, lines


def _set_linear_plan_flag(user_id: int, enabled: bool) -> tuple[bool, str]:
    """Flip ``User.use_linear_plan`` for a single user.

    Returns ``(success, message)`` so CLI handlers can print and set exit codes.
    """
    user = db.session.get(User, user_id)
    if user is None:
        return False, f'User with id={user_id} not found'

    previous = bool(user.use_linear_plan)
    user.use_linear_plan = enabled
    db.session.commit()

    state = 'enabled' if enabled else 'disabled'
    if previous == enabled:
        return True, f'use_linear_plan already {state} for user_id={user_id} ({user.username})'
    return True, f'use_linear_plan {state} for user_id={user_id} ({user.username})'


@click.command('linear-plan-enable')
@click.argument('user_id', type=int)
@with_appcontext
def linear_plan_enable_cmd(user_id: int) -> None:
    """Enable the linear daily plan feature flag for a user."""
    ok, message = _set_linear_plan_flag(user_id, enabled=True)
    click.echo(message)
    if not ok:
        raise click.exceptions.Exit(code=1)


@click.command('linear-plan-disable')
@click.argument('user_id', type=int)
@with_appcontext
def linear_plan_disable_cmd(user_id: int) -> None:
    """Disable the linear daily plan feature flag for a user."""
    ok, message = _set_linear_plan_flag(user_id, enabled=False)
    click.echo(message)
    if not ok:
        raise click.exceptions.Exit(code=1)


@click.command('linear-plan-status')
@click.argument('user_id', type=int)
@with_appcontext
def linear_plan_status_cmd(user_id: int) -> None:
    """Print a diagnostic snapshot of the linear daily plan for a user."""
    found, lines = _format_linear_plan_status(user_id)
    for line in lines:
        click.echo(line)
    if not found:
        raise click.exceptions.Exit(code=1)


def register_linear_plan_commands(app) -> None:
    """Attach linear-plan toggle commands to the Flask app CLI."""
    app.cli.add_command(linear_plan_enable_cmd)
    app.cli.add_command(linear_plan_disable_cmd)
    app.cli.add_command(linear_plan_status_cmd)
