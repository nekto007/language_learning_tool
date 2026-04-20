"""Flask CLI commands for toggling the linear daily plan feature flag per user."""
from __future__ import annotations

import click
from flask.cli import with_appcontext

from app.auth.models import User
from app.utils.db import db


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


def register_linear_plan_commands(app) -> None:
    """Attach linear-plan toggle commands to the Flask app CLI."""
    app.cli.add_command(linear_plan_enable_cmd)
    app.cli.add_command(linear_plan_disable_cmd)
