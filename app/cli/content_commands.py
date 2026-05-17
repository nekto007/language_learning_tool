"""Flask CLI commands for content auditing."""
from __future__ import annotations

import os
from pathlib import Path

import click
from flask import current_app
from flask.cli import with_appcontext

AUDIO_EXPECTED = frozenset({'dictation', 'listening_immersion', 'shadow_reading', 'audio_fill_blank'})

_LOCAL_PREFIX = '/static/'


def _is_local_path(url: str) -> bool:
    return url.startswith('/') and not url.startswith('//')


def _check_local_path(url: str) -> bool:
    """Return True if the local static path resolves to an existing file."""
    static_folder = current_app.static_folder
    if not static_folder:
        return True  # cannot verify without static folder configured
    if url.startswith(_LOCAL_PREFIX):
        relative = url[len(_LOCAL_PREFIX):]
    elif url.startswith('/'):
        relative = url.lstrip('/')
    else:
        return True
    full_path = Path(static_folder) / relative
    return full_path.exists()


def _get_missing_audio_lessons() -> list[dict]:
    """Return lessons with missing, empty, or broken-local audio_url, sorted by module progression."""
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
        elif audio_url and _is_local_path(audio_url) and not _check_local_path(audio_url):
            status = 'broken_local'
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
            'audio_url': audio_url,
            'status': status,
        })

    return missing


def _format_report(lessons: list[dict]) -> str:
    lines = []
    if not lessons:
        lines.append('No lessons with missing or broken audio found.')
        return '\n'.join(lines)

    lines.append(f'Found {len(lessons)} lesson(s) with missing/empty/broken audio_url:\n')
    header = f'{"ID":<6} {"Level":<6} {"Mod":<4} {"Les":<4} {"Type":<25} {"Status":<14} Title'
    lines.append(header)
    lines.append('-' * 90)
    for row in lessons:
        lines.append(
            f'{row["lesson_id"]:<6} {row["level_code"]:<6} {row["module_number"]:<4} '
            f'{row["lesson_number"]:<4} {row["type"]:<25} {row["status"]:<14} {row["title"]}'
        )
    return '\n'.join(lines)


@click.command('content-audit')
@click.argument('topic', type=click.Choice(['audio']))
@click.option('--output', '-o', default=None, help='Write report to this file path instead of stdout.')
@with_appcontext
def content_audit_cmd(topic: str, output: str | None) -> None:
    """Audit content for missing or broken resources. TOPIC: audio."""
    lessons = _get_missing_audio_lessons()
    report = _format_report(lessons)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding='utf-8')
        click.echo(f'Report written to {output}')
    else:
        click.echo(report)


def register_content_commands(app) -> None:
    """Attach content audit commands to the Flask app CLI."""
    app.cli.add_command(content_audit_cmd)
