"""Flask CLI commands for content auditing."""
from __future__ import annotations

import click
from flask.cli import with_appcontext

AUDIO_EXPECTED = frozenset({'dictation', 'listening_immersion', 'shadow_reading', 'audio_fill_blank'})


def _get_missing_audio_lessons() -> list[dict]:
    """Return lessons with missing or empty audio_url, sorted by module progression."""
    from app.curriculum.models import CEFRLevel, Lessons, Module
    from app.utils.db import db

    rows = (
        db.session.query(Lessons, Module, CEFRLevel)
        .outerjoin(Module, Module.id == Lessons.module_id)
        .outerjoin(CEFRLevel, CEFRLevel.id == Module.level_id)
        .order_by(CEFRLevel.order, Module.number, Lessons.number)
        .all()
    )

    missing = []
    for lesson, module, level in rows:
        content = lesson.content or {}
        audio_url = content.get('audio_url', '')

        if lesson.type in AUDIO_EXPECTED and not audio_url:
            status = 'missing'
        elif 'audio_url' in content and not content['audio_url']:
            status = 'empty'
        else:
            continue

        missing.append({
            'lesson_id': lesson.id,
            'title': lesson.title,
            'type': lesson.type,
            'module_id': module.id if module else None,
            'module_number': module.number if module else 0,
            'module_title': module.title if module else '',
            'level_code': level.code if level else '',
            'level_order': level.order if level else 0,
            'lesson_number': lesson.number,
            'status': status,
        })

    return missing


@click.command('content-audit')
@click.argument('topic', type=click.Choice(['audio']))
@with_appcontext
def content_audit_cmd(topic: str) -> None:
    """Audit content for missing or broken resources. TOPIC: audio."""
    lessons = _get_missing_audio_lessons()
    if not lessons:
        click.echo('No lessons with missing audio found.')
        return

    click.echo(f'Found {len(lessons)} lesson(s) with missing/empty audio_url:\n')
    click.echo(f'{"ID":<6} {"Level":<6} {"Mod":<4} {"Les":<4} {"Type":<25} {"Status":<8} Title')
    click.echo('-' * 80)
    for row in lessons:
        click.echo(
            f'{row["lesson_id"]:<6} {row["level_code"]:<6} {row["module_number"]:<4} '
            f'{row["lesson_number"]:<4} {row["type"]:<25} {row["status"]:<8} {row["title"]}'
        )


def register_content_commands(app) -> None:
    """Attach content audit commands to the Flask app CLI."""
    app.cli.add_command(content_audit_cmd)
