"""Install private module outcomes without replacing lessons or learner progress."""
import json
from copy import deepcopy
from pathlib import Path

import click

from app.curriculum.models import CEFRLevel, Lessons, Module
from app.utils.db import db


def install_journey_pack(path, *, apply=False):
    pack = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(pack, dict):
        raise ValueError('Expected a JSON object')
    rows = pack.get('modules')
    if pack.get('version') != 1 or pack.get('level') != 'A1' or not isinstance(rows, list) or not rows:
        raise ValueError('Expected an A1 journey pack, version 1')
    numbers = set()
    changes = []
    labels = []
    links = []
    report = {'applied': apply, 'updated': [], 'unchanged': [], 'lesson_labels_updated': [], 'grammar_links_updated': []}
    for row in rows:
        number, goal = row.get('number'), row.get('goal')
        if (type(number) is not int or number <= 0 or number in numbers
                or not isinstance(goal, str) or not 10 <= len(goal.strip()) <= 300
                or '<' in goal or '>' in goal):
            raise ValueError('Invalid module identity or plain-language goal')
        numbers.add(number)
        query = Module.query.join(CEFRLevel).filter(CEFRLevel.code == 'A1', Module.number == number)
        module = (query.with_for_update(of=Module) if apply else query).one_or_none()
        if module is None or module.title != row.get('expected_title'):
            raise ValueError(f'Module {number} missing or title differs; review the pack')
        raw = deepcopy(module.raw_content or {})
        if not isinstance(raw, dict) or ('module' in raw and not isinstance(raw['module'], dict)):
            raise ValueError(f'Module {number}: invalid existing metadata; review before replacing')
        target = raw.get('module', raw)
        authored = {'version': 1, 'goal': goal.strip()}
        if target.get('learning_journey') == authored:
            report['unchanged'].append(number)
        elif target.get('learning_journey'):
            raise ValueError(f'Module {number} already has a different journey; review before replacing')
        else:
            target['learning_journey'] = authored
            changes.append((module, raw))
            report['updated'].append(number)
        slug = row.get('grammar_topic')
        if slug is not None:
            from app.grammar_lab.content_catalog import expected_slugs
            from app.grammar_lab.models import GrammarTopic

            if not isinstance(slug, str) or not slug.startswith('a1-') or slug not in expected_slugs():
                raise ValueError(f'Module {number}: invalid reviewed grammar topic')
            topic = GrammarTopic.query.filter_by(slug=slug, level='A1').one_or_none()
            grammar = Lessons.query.filter_by(module_id=module.id, type='grammar').all()
            if (topic is None or len(grammar) != 1
                    or grammar[0].grammar_topic_id not in (None, topic.id)):
                raise ValueError(f'Module {number}: grammar topic missing or link differs; review before replacing')
            if grammar[0].grammar_topic_id is None:
                links.append((grammar[0], topic.id))
                report['grammar_links_updated'].append(grammar[0].id)
        lesson_labels = row.get('lesson_labels', [])
        if not isinstance(lesson_labels, list) or any(not isinstance(label, dict) for label in lesson_labels):
            raise ValueError(f'Module {number}: expected lesson label list')
        kinds = set()
        for label in lesson_labels:
            kind, title, expected = (label.get(key) for key in ('type', 'title', 'expected_title'))
            if (not isinstance(kind, str) or kind in kinds or not kind
                    or any(not isinstance(value, str) or not value.strip() or len(value) > 200
                           or '<' in value or '>' in value for value in (title, expected))):
                raise ValueError(f'Module {number}: invalid lesson label')
            kinds.add(kind)
            matches = Lessons.query.filter_by(module_id=module.id, type=kind).all()
            if len(matches) != 1 or matches[0].title not in (expected, title):
                raise ValueError(f'Module {number}: lesson label differs; review before replacing')
            if matches[0].title != title:
                labels.append((matches[0], title))
                report['lesson_labels_updated'].append(matches[0].id)
    if apply:
        try:
            for module, raw in changes:
                module.raw_content = raw
            for lesson, title in labels:
                lesson.title = title
                lesson.content_version = (lesson.content_version or 1) + 1
            for lesson, topic_id in links:
                lesson.grammar_topic_id = topic_id
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    return report


def register_journey_commands(app):
    @app.cli.command('curriculum-journey-install')
    @click.option('--pack', type=click.Path(exists=True, dir_okay=False), required=True)
    @click.option('--apply', is_flag=True, help='Apply the validated pack. Default is dry run.')
    def install(pack, apply):
        try:
            click.echo(json.dumps(install_journey_pack(pack, apply=apply), ensure_ascii=False, indent=2))
        except (ValueError, KeyError, TypeError) as error:
            raise click.ClickException(str(error)) from error
