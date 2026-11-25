"""Read-only index of materials with links to the existing admin editors."""
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode

from flask import Blueprint, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import Integer, String, func, literal, or_, select, union_all
from sqlalchemy.sql import CompoundSelect, Select

from app.admin.utils.decorators import admin_required
from app.admin.utils.request_validators import escape_like
from app.books.models import Book
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.study.models import WordSet
from app.utils.db import db
from app.words.models import Collection, CollectionWords

materials_bp = Blueprint('materials_admin', __name__)
_LEVELS = ('A1', 'A2', 'B1', 'B2', 'C1')
_KINDS = {
    'lesson': 'Урок курса', 'exercise': 'Упражнение Grammar Lab',
    'book': 'Книга', 'word': 'Слово', 'collection': 'Коллекция',
    'word_set': 'Набор слов',  # noqa: RUF001 -- Russian catalog label.
}
_PAGE_SIZE = 24
_MATERIAL_DESTINATIONS = {
    'curriculum_admin.edit_lesson', 'curriculum_admin.view_lesson',
    'grammar_lab_admin.edit_exercise', 'grammar_lab_admin.edit_topic',
    'guided_topics_admin.edit', 'guided_topics_admin.preview', 'guided_topics_admin.publish',
    'book_admin.edit_book', 'book_admin.chapter_list', 'book_admin.edit_chapter',
    'word_admin.edit_translation', 'word_set_admin.word_set_edit', 'collection_admin.edit_collection',
}
_DIRECTORIES = (
    ('Словарь', 'word_admin.word_management', 'Статистика словаря, статусы слов и импорт переводов'),
    ('Наборы слов', 'word_set_admin.word_set_list', 'Настройки наборов и состав слов'),
    ('Коллекции', 'collection_admin.collection_list', 'Редактирование коллекций и их состава'),
    ('Темы словаря', 'topic_admin.topic_list', 'Названия тем и привязанные слова'),
    ('Книги', 'book_admin.books', 'Каталог и редактор карточек книг'),
    ('Книжные курсы', 'admin.book_courses', 'Курсы, модули, уроки и задания по книгам'),
    ('Quiz-колоды', 'admin.quiz_decks_list', 'Настройки колод и состав слов'),
    ('Темы Grammar Lab', 'grammar_lab_admin.topic_list', 'Темы, теория и список упражнений'),
    ('Пошаговые темы', 'guided_topics_admin.index', 'Редактирование и публикация установленных тем Grammar Lab'),
    ('Модули курса', 'admin_curriculum.module_list', 'Уровни, модули и структура курса'),
    ('Сравнения слов', 'word_contrast_admin.word_contrast_index', 'Карточки различий и примеры'),
    ('Культурные заметки', 'admin.cultural_notes_list', 'Редактор заметок курса'),
    ('Спорные ответы', 'answer_disputes_admin.index', 'Очередь обращений и правки ключей'),
)


def _filters(args: Mapping[str, str]) -> dict[str, str | int]:
    term = args.get('q', '').replace('\x00', '').strip()[:160]
    kind = args.get('kind', '')
    level = args.get('level', '').upper()
    page = args.get('page', '')
    page_number = max(1, int(page)) if len(page) <= 9 and page.isascii() and page.isdigit() else 1
    return {
        'q': term,
        'kind': kind if kind in _KINDS else '',
        'level': level if level in _LEVELS else '',
        'page': page_number,
    }


def _query_args(filters: Mapping[str, str | int]) -> dict[str, str | int]:
    return {key: value for key, value in filters.items() if value and (key != 'page' or value != 1)}


def materials_return_url() -> str | None:
    """Rebuild the editor's return destination from catalog parameters only."""
    state = request.args.get('materials_query')
    if state is None or len(state) > 2400:
        return None
    try:
        params = dict(parse_qsl(state, max_num_fields=4))
    except ValueError:
        return None
    return url_for('materials_admin.index', **_query_args(_filters(params)))


@materials_bp.app_context_processor
def _materials_back_link() -> dict[str, str | None]:
    if request.endpoint not in _MATERIAL_DESTINATIONS or not current_user.is_admin:
        return {}
    return {'materials_catalog_back': materials_return_url()}


def _search_id(term: str) -> int | None:
    value = term.removeprefix('#')
    if len(value) <= 10 and value.isascii() and value.isdigit() and int(value) <= 2**31 - 1:
        return int(value)
    return None


def _materials(term: str, kind: str, level: str) -> Select | CompoundSelect:
    lab_text = [GrammarExercise.content[key].as_string()
                for key in ('question', 'sentence', 'statement', 'prompt', 'original', 'instruction')]
    lab_title = func.coalesce(*(func.nullif(value, '') for value in lab_text), literal(''))
    lessons = select(
        literal('lesson').label('kind'), Lessons.id.label('id'), CEFRLevel.code.label('level'),
        Lessons.title.label('title'), Module.title.label('parent_title'), Module.id.label('parent_id'),
        Module.number.label('module_number'), Lessons.number.label('lesson_number'),
        literal(False).label('retired'),
    ).select_from(Lessons).join(Module, Lessons.module_id == Module.id).join(CEFRLevel, Module.level_id == CEFRLevel.id)
    exercises = select(
        literal('exercise').label('kind'), GrammarExercise.id.label('id'), GrammarTopic.level.label('level'),
        lab_title.label('title'), GrammarTopic.title_ru.label('parent_title'), GrammarTopic.id.label('parent_id'),
        literal(None, Integer).label('module_number'), literal(None, Integer).label('lesson_number'),
        GrammarExercise.content['guided_retired'].as_boolean().is_(True).label('retired'),
    ).select_from(GrammarExercise).join(GrammarTopic, GrammarExercise.topic_id == GrammarTopic.id)
    if level:
        lessons = lessons.where(CEFRLevel.code == level)
        exercises = exercises.where(GrammarTopic.level == level)
    item_id = _search_id(term)
    if item_id is not None:
        lessons = lessons.where(Lessons.id == item_id)
        exercises = exercises.where(GrammarExercise.id == item_id)
    elif term:
        pattern = f'%{escape_like(term)}%'
        lessons = lessons.where(or_(*(field.ilike(pattern, escape='\\') for field in (Lessons.title, Module.title))))
        exercise_fields = (GrammarTopic.title_ru, GrammarTopic.title, GrammarTopic.slug, *lab_text)
        exercises = exercises.where(or_(*(field.ilike(pattern, escape='\\') for field in exercise_fields)))
    if kind == 'lesson':
        return lessons
    if kind == 'exercise':
        return exercises
    queries = [] if kind else [lessons, exercises]
    additional = {
        'book': (Book.id, Book.level, Book.title, Book.author, (Book.title, Book.author, Book.slug)),
        'word': (CollectionWords.id, CollectionWords.level, CollectionWords.english_word,
                 CollectionWords.russian_word, (CollectionWords.english_word, CollectionWords.russian_word)),
        'word_set': (WordSet.id, WordSet.level, WordSet.name, literal(None, String), (WordSet.name, WordSet.slug)),
        'collection': (Collection.id, literal(None, String), Collection.name, literal(None, String), (Collection.name,)),
    }
    for entry_kind, (identity, cefr, title, secondary, fields) in additional.items():
        if kind and kind != entry_kind:
            continue
        query = select(
            literal(entry_kind).label('kind'), identity.label('id'), cefr.label('level'), title.label('title'),
            secondary.label('parent_title'), literal(None, Integer).label('parent_id'),
            literal(None, Integer).label('module_number'), literal(None, Integer).label('lesson_number'),
            literal(False).label('retired'),
        )
        if level:
            query = query.where(cefr == level)
        if item_id is not None:
            query = query.where(identity == item_id)
        elif term:
            query = query.where(or_(*(field.ilike(pattern, escape='\\') for field in fields)))
        queries.append(query)
    return queries[0] if len(queries) == 1 else union_all(*queries)


@materials_bp.get('/materials')
@admin_required
def index() -> str:
    filters = _filters(request.args)
    materials = _materials(str(filters['q']), str(filters['kind']), str(filters['level'])).subquery()
    total = db.session.execute(select(func.count()).select_from(materials)).scalar_one()
    pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = min(int(filters['page']), pages)
    filters['page'] = page
    state = _query_args(filters)
    rows = db.session.execute(
        select(materials).order_by(materials.c.level, materials.c.kind.desc(), materials.c.module_number,
                                   materials.c.parent_id, materials.c.lesson_number, materials.c.id)
        .limit(_PAGE_SIZE).offset((page - 1) * _PAGE_SIZE)
    ).mappings().all()

    def page_url(number: int) -> str:
        return url_for('.index', **_query_args({**filters, 'page': number}))

    import_tools = (
        ('Пакеты контента', 'content_packages_admin.index', 'Предпросмотр и публикация ZIP-пакетов'),
        ('Учебный курс', 'admin_curriculum.import_curriculum', 'Импорт структуры и уроков из JSON'),
        ('Упражнения Grammar Lab', 'grammar_lab_admin.import_exercises_json', 'Загрузка упражнений из JSON'),
        ('Переводы слов', 'word_admin.import_translations', 'Импорт переводов с предпросмотром'),  # noqa: RUF001 -- Russian admin label.
    )
    return render_template(
        'admin/materials/index.html', filters=filters, levels=_LEVELS, kinds=_KINDS, rows=rows,
        total=total, page=page, pages=pages, page_url=page_url, materials_query=urlencode(state),
        directories=_DIRECTORIES, import_tools=import_tools,
    )
