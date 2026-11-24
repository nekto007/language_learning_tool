"""Validate and install a private, immutable diagnostic bank (no corpus in Git)."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import click
from flask.cli import with_appcontext

from app.onboarding.placement_models import PlacementBank
from app.utils.db import db

LEVELS = ('A1', 'A2', 'B1', 'B2', 'C1')
SKILLS = ('grammar', 'vocabulary', 'reading', 'listening', 'writing')
# Three repeated core blocks + detailed verification; A1 also has a warm-up.
MIN_ITEMS = {'grammar': 6, 'vocabulary': 6, 'reading': 5, 'listening': 5, 'writing': 2}
SKILL_LABELS = {'grammar': 'Грамматика', 'vocabulary': 'Словарь', 'reading': 'Чтение',
                'listening': 'Аудирование', 'writing': 'Письменные задания'}


def _string(value: Any, maximum: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def validate_bank(pack: Any) -> dict:
    if not isinstance(pack, dict) or set(pack) != {'schema_version', 'label', 'items'}:
        raise ValueError('Expected schema_version, label and items')
    if type(pack['schema_version']) is not int or pack['schema_version'] != 1 or not _string(pack['label'], 120):
        raise ValueError('Unsupported schema or label')
    items = pack['items']
    if not isinstance(items, list) or not 120 <= len(items) <= 1000:
        raise ValueError('Bank must have 120-1000 items')
    seen: set[str] = set()
    counts: Counter = Counter()
    for row in items:
        if not isinstance(row, dict) or set(row) - {'id', 'level', 'skill', 'input', 'prompt', 'options', 'answers', 'passage', 'audio_url', 'topic'}:
            raise ValueError('Invalid item fields')
        key = row.get('id')
        if not _string(key, 100) or not re.fullmatch(r'[a-zA-Z0-9_-]+', key) or key in seen:
            raise ValueError('Invalid or duplicate item ID')
        seen.add(key)
        skill, level = row.get('skill'), row.get('level')
        if skill not in SKILLS or level not in LEVELS or not _string(row.get('prompt'), 1500):
            raise ValueError(f'Invalid skill, level or prompt: {key}')
        if 'topic' in row and not _string(row['topic'], 200):
            raise ValueError(f'Invalid topic: {key}')
        answers = row.get('answers')
        if not isinstance(answers, list) or not 1 <= len(answers) <= 20 or not all(_string(a, 1000) for a in answers):
            raise ValueError(f'Invalid answers: {key}')
        if skill == 'writing':
            if row.get('input') != 'text' or row.get('options') or row.get('audio_url') or row.get('passage'):
                raise ValueError(f'Writing must be a bounded text task: {key}')
        else:
            options = row.get('options')
            if row.get('input') != 'choice' or not isinstance(options, list) or not 3 <= len(options) <= 6:
                raise ValueError(f'Choice items require 3-6 options: {key}')
            if not all(_string(o, 500) for o in options) or len(set(options)) != len(options) or len(answers) != 1 or answers[0] not in options:
                raise ValueError(f'Invalid choice key: {key}')
        if skill == 'reading':
            if not _string(row.get('passage'), 8000) or row.get('audio_url'):
                raise ValueError(f'Reading needs its passage: {key}')
        elif row.get('passage'):
            raise ValueError(f'Passage not allowed for {skill}: {key}')
        if skill == 'listening':
            audio = row.get('audio_url')
            if not _string(audio, 500) or not re.fullmatch(r'/static/audio/[A-Za-z0-9_./-]+\.(mp3|m4a|wav)', audio) or '..' in audio:
                raise ValueError(f'Listening requires a local audio URL: {key}')
        elif row.get('audio_url'):
            raise ValueError(f'Audio only allowed for listening: {key}')
        counts[(level, skill)] += 1
    for level in LEVELS:
        for skill in SKILLS:
            if counts[(level, skill)] < MIN_ITEMS[skill]:
                raise ValueError(f'Need at least {MIN_ITEMS[skill]} items for {level}/{skill}')
    return pack


def bank_digest(pack: dict) -> str:
    return hashlib.sha256(json.dumps(pack, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


@click.command('placement-bank-install')
@click.option('--pack', type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option('--apply', is_flag=True, help='Install and activate this immutable bank.')
@with_appcontext
def install_bank(pack: Path, apply: bool) -> None:
    """Dry-run by default. Existing attempts keep their original bank."""
    if pack.stat().st_size > 4_000_000:
        raise click.ClickException('Pack exceeds 4 MB')
    try:
        document = validate_bank(json.loads(pack.read_text(encoding='utf-8')))
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    digest = bank_digest(document)
    row = db.session.get(PlacementBank, digest)
    changed = row is None or not row.active
    if apply and changed:
        # Serialize publisher updates without holding any learner/attempt lock.
        if db.engine.dialect.name == 'postgresql':
            db.session.execute(db.text('SELECT pg_advisory_xact_lock(624117024)'))
        row = db.session.get(PlacementBank, digest)
        db.session.query(PlacementBank).filter_by(active=True).update({'active': False})
        db.session.flush()
        if row is None:
            row = PlacementBank(id=digest, label=document['label'], content=document, active=True)
            db.session.add(row)
        else:
            row.active = True
        db.session.commit()
    click.echo(json.dumps({'applied': bool(apply), 'changed': changed, 'bank_id': digest,
                           'items': len(document['items']), 'levels': list(LEVELS)}, ensure_ascii=False, indent=2))
