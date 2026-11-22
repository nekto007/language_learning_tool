"""Reviewed original A1 reading pack and repeatable, non-destructive install."""

import json
import re
from copy import deepcopy
from pathlib import Path

from app.books.models import Book, Chapter
from app.utils.db import db

PACK = Path(__file__).resolve().parents[2] / 'content' / 'a1-readings' / 'a1_readings.json'
TOPICS = Path(__file__).resolve().parents[1] / 'grammar_lab' / 'content' / 'topics'
PERMISSION = 'LLT original A1 reading pack v1; full-text use inside LLT is granted to registered learners.'
FORMATS = {'short_text', 'dialogue', 'story'}


def words(text):
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)


def load_pack(path=None):
    data = json.loads(Path(path if path is not None else PACK).read_text(encoding='utf-8'))
    items = data.get('items')
    if data.get('version') != 1 or not isinstance(items, list) or len(items) != 15:
        raise ValueError('Expected the reviewed 15-material A1 pack, version 1')
    slugs, orders = set(), set()
    for item in items:
        slug = item['slug']
        reading = item['reading']
        if not re.fullmatch(r'llt-a1-reading-\d{2}', slug) or slug in slugs:
            raise ValueError('Duplicate or invalid reading identity')
        slugs.add(slug)
        order = reading['order']
        if type(order) is not int or not 1 <= order <= 15 or order in orders:
            raise ValueError('Duplicate or invalid reading order')
        orders.add(order)
        if reading.get('format') not in FORMATS or reading.get('stage') not in {'start', 'growing', 'confident'}:
            raise ValueError(f'Invalid reading format/stage: {slug}')
        if not 30 <= len(words(item['text'])) <= 200 or '<' in item['text'] or '>' in item['text']:
            raise ValueError(f'Invalid plain reading text: {slug}')
        if not item['title'].strip() or not reading.get('focus'):
            raise ValueError(f'Missing title/focus: {slug}')
        if not 3 <= len(reading['glossary']) <= 5:
            raise ValueError(f'Expected 3-5 vocabulary hints: {slug}')
        if any(not row.get('english') or not row.get('translation') for row in reading['glossary']):
            raise ValueError(f'Invalid vocabulary hint: {slug}')
        for topic in reading['after_topics']:
            if not (TOPICS / f'{topic}.json').is_file():
                raise ValueError(f'Unknown prerequisite: {topic}')
        questions = reading['questions']
        if not 2 <= len(questions) <= 3 or len({q['id'] for q in questions}) != len(questions):
            raise ValueError(f'Expected 2-3 distinct questions: {slug}')
        for question in questions:
            options = question['options']
            ids = {option['id'] for option in options}
            if (len(options) != 3 or len(ids) != 3 or question['correct_option'] not in ids
                    or any(not option['text'].strip() for option in options)
                    or len({option['text'].casefold() for option in options}) != len(options)
                    or not all(question.get(k) for k in ('instruction', 'prompt', 'prompt_translation', 'explanation'))):
                raise ValueError(f'Invalid formative question: {slug}')
    return data


def reading_summary(book):
    """Small catalogue projection; practice hints arrive with chapter content."""
    if not book.is_short_reading:
        return None
    return {key: deepcopy(value) for key, value in book.reading.items() if key not in {'questions', 'glossary'}}


def install_pack(*, apply=False, path=None):
    pack = load_pack(path)
    report = {'applied': apply, 'created': [], 'unchanged': [], 'materials': []}
    existing = {book.slug: book for book in Book.query.filter(Book.slug.in_([x['slug'] for x in pack['items']])).all()}
    # Validate the entire installation before adding anything. Existing rows and
    # all learner progress are preserved; edited editions require explicit review.
    for item in pack['items']:
        book = existing.get(item['slug'])
        if book is not None:
            chapters = Chapter.query.filter_by(book_id=book.id).order_by(Chapter.chap_num).all()
            if (book.permission_document != PERMISSION or len(chapters) != 1
                    or chapters[0].text_raw != item['text'] or book.reading != item['reading']):
                raise ValueError(f'Existing material differs; review it before replacing: {item["slug"]}')
            report['unchanged'].append(item['slug'])
        else:
            report['created'].append(item['slug'])
        report['materials'].append({'slug': item['slug'], 'words': len(words(item['text'])),
                                   'questions': len(item['reading']['questions'])})
    if not apply:
        return report
    try:
        for item in pack['items']:
            if item['slug'] in existing:
                continue
            tokens = words(item['text'])
            book = Book(slug=item['slug'], title=item['title'], author=pack['author'],
                        chapters_cnt=1, lang='en', level='A1', summary=item['reading']['focus'],
                        words_total=len(tokens), unique_words=len({w.casefold() for w in tokens}),
                        is_published=True, is_free_access=True, create_course=False,
                        rights_status='licensed', license_type='LLT original educational material',
                        permission_document=PERMISSION, commercial_use_allowed=True,
                        allowed_text_percent=100, audio_rights_status='none',
                        territory='worldwide', reading=deepcopy(item['reading']))
            db.session.add(book)
            db.session.flush()
            db.session.add(Chapter(book_id=book.id, chap_num=1, title=item['title'], words=len(tokens), text_raw=item['text']))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return report


def register_short_reading_commands(app):
    import click

    @app.cli.command('a1-readings-install')
    @click.option('--pack', 'pack_path', type=click.Path(exists=True, dir_okay=False, path_type=Path),
                  help='Private JSON pack copied separately to the server; never fetched from Git.')
    @click.option('--apply', is_flag=True, help='Install the validated pack; default is a dry run.')
    def install_command(apply, pack_path):
        """Review/install 15 original A1 texts without resetting any progress."""
        try:
            click.echo(json.dumps(install_pack(apply=apply, path=pack_path), ensure_ascii=False, indent=2))
        except FileNotFoundError as error:
            raise click.ClickException('Private reading pack not found. Copy it separately and use --pack PATH.') from error
        except (ValueError, OSError) as error:
            raise click.ClickException(str(error)) from error
