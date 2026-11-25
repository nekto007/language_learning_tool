"""Reviewed original A1 reading pack and repeatable, non-destructive install."""
# ruff: noqa: RUF001 -- Russian validation messages for authors.

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


class InvalidFormativeQuestion(ValueError):
    """An invalid practice question in a short reading."""


def words(text):
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)


def _valid_text(value: object, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and '\0' not in value


def validate_reading_item(item: dict) -> None:
    """Validate a single authored reading, shared by the pack and the editor."""
    if not isinstance(item, dict):
        raise ValueError('Ожидаются данные одного короткого чтения.')
    slug = item.get('slug')
    reading = item.get('reading')
    if (slug is not None and not _valid_text(slug, 100)) or not isinstance(reading, dict):
        raise ValueError('Проверьте адрес и настройки короткого чтения.')
    if not isinstance(reading.get('format'), str) or reading['format'] not in FORMATS:
        raise ValueError('Неизвестный формат короткого чтения.')
    eta = reading.get('estimated_minutes', 3)
    if type(eta) is not int or not 1 <= eta <= 120:
        raise ValueError('Укажите время чтения от 1 до 120 минут.')
    text = item.get('text')
    if not _valid_text(text, 8000) or not 30 <= len(words(text)) <= 200 or '<' in text or '>' in text:
        raise ValueError('Введите от 30 до 200 слов обычным текстом, без HTML.')
    if not _valid_text(item.get('title'), 255) or not _valid_text(reading.get('focus'), 1000):
        raise ValueError('Проверьте название чтения и его учебную цель.')
    glossary = reading.get('glossary')
    if not isinstance(glossary, list) or not 3 <= len(glossary) <= 5 or not all(
        isinstance(row, dict) and _valid_text(row.get('english'), 255) and _valid_text(row.get('translation'), 255)
        for row in glossary
    ):
        raise ValueError('Заполните от трёх до пяти пар слово — перевод.')
    topics = reading.get('after_topics', [])
    if not isinstance(topics, list) or any(
        not isinstance(topic, str) or not re.fullmatch(r'[a-z0-9-]+', topic) or not (TOPICS / f'{topic}.json').is_file()
        for topic in topics
    ):
        raise ValueError('В настройках указана неизвестная предварительная тема.')
    questions = reading.get('questions')
    if not isinstance(questions, list) or not 2 <= len(questions) <= 3:
        raise ValueError('Заполните два или три вопроса с разными идентификаторами.')
    question_ids = set()
    for question in questions:
        if not isinstance(question, dict) or not _valid_text(question.get('id'), 100) or question['id'] in question_ids:
            raise ValueError('Проверьте идентификаторы вопросов. Они должны различаться.')
        question_ids.add(question['id'])
        options = question.get('options')
        if not isinstance(options, list) or len(options) != 3 or not all(
            isinstance(option, dict) and _valid_text(option.get('id'), 100) and _valid_text(option.get('text'), 500)
            for option in options
        ):
            raise InvalidFormativeQuestion(f'Вопрос {len(question_ids)} — заполните три варианта.')
        ids = {option['id'] for option in options}
        correct = question.get('correct_option')
        if (len(ids) != 3 or not isinstance(correct, str) or correct not in ids
                or len({option['text'].strip().casefold() for option in options}) != 3
                or not all(_valid_text(question.get(key), 2000)
                           for key in ('instruction', 'prompt', 'prompt_translation', 'explanation'))):
            raise InvalidFormativeQuestion(f'Вопрос {len(question_ids)} — проверьте поля, варианты и ключ.')


def load_pack(path=None):
    data = json.loads(Path(path if path is not None else PACK).read_text(encoding='utf-8'))
    items = data.get('items')
    if data.get('version') != 1 or not isinstance(items, list) or len(items) != 15:
        raise ValueError('Expected the reviewed 15-material A1 pack, version 1')
    slugs, orders = set(), set()
    for item in items:
        try:
            validate_reading_item(item)
        except InvalidFormativeQuestion as exc:
            raise ValueError(f'Invalid formative question: {item.get("slug")}') from exc
        slug, order = item.get('slug'), item['reading'].get('order')
        if (not isinstance(slug, str) or not re.fullmatch(r'llt-a1-reading-\d{2}', slug)
                or type(order) is not int or not 1 <= order <= 15
                or item['reading'].get('stage') not in ('start', 'growing', 'confident')):
            raise ValueError('Invalid A1 pack identity, order or stage')
        if slug in slugs or order in orders:
            raise ValueError(f'Duplicate reading identity or order: {slug}')
        slugs.add(slug)
        orders.add(order)
    return data


def reading_summary(book):
    """Small catalogue projection; practice hints arrive with chapter content."""
    if not book.is_short_reading:
        return None
    return {key: deepcopy(value) for key, value in book.reading.items() if key not in {'questions', 'glossary'}}


def reading_catalogue_order():
    """Put short materials in learning order before paginating a catalogue."""
    from sqlalchemy import case

    short = Book.reading['format'].as_string().in_(sorted(FORMATS))
    return (
        case((short, 0), else_=1),
        case((short, Book.reading['order'].as_integer()), else_=0),
        Book.title.asc(), Book.id.asc(),
    )


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
