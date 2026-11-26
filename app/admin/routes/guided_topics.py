"""Preview and publish one installed Grammar Lab topic from its authored document."""
# ruff: noqa: RUF001 -- editor labels and messages are in Russian.
import json
import logging
from time import time
from typing import Any

from flask import Blueprint, Response, abort, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin.audit import log_admin_action
from app.admin.services.guided_disputes import guided_topic_for_dispute
from app.admin.utils.decorators import content_editor_required
from app.admin.utils.import_helpers import delete_import_data, load_import_data, save_import_data
from app.auth.models import User
from app.curriculum.answer_disputes import AnswerDispute
from app.curriculum.blank_answers import blank_instruction, has_blank_format_conflict
from app.grammar_lab.content_catalog import content_digest, validate_authored_topic
from app.grammar_lab.content_install import install_catalog
from app.grammar_lab.guided_authoring import edited_document, is_guided_content, recover_document
from app.grammar_lab.models import GrammarTopic
from app.utils.db import db

guided_topics_bp = Blueprint('guided_topics_admin', __name__)
logger = logging.getLogger(__name__)
_PREFIX = 'guided-topic-'
_TTL = 1800
_MAX_DOCUMENT = 512_000


def _topic(topic_id: int) -> GrammarTopic:
    topic = GrammarTopic.query.get_or_404(topic_id)
    if not is_guided_content(topic.content):
        abort(404)
    return topic


def _private(template: str, status: int = 200, **context: Any) -> Response:
    topic = context.get('topic')
    response = make_response(render_template(f'admin/guided_topics/{template}.html',
                                             materials_query=_materials_query(),
                                             from_dispute=_from_dispute(topic) if topic is not None else None,
                                             **context), status)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def _materials_query() -> str | None:
    return request.args.get('materials_query') if current_user.is_admin else None


def _from_dispute(topic: GrammarTopic) -> int | None:
    case_id = request.args.get('from_dispute', type=int)
    if case_id is None or not 0 < case_id <= 2**31 - 1:
        return None
    case = db.session.get(AnswerDispute, case_id)
    linked = guided_topic_for_dispute(case) if case is not None else None
    return case_id if linked is not None and linked.id == topic.id else None


def _stage(topic: GrammarTopic, kind: str, payload: dict) -> str:
    return save_import_data({
        'topic_id': topic.id, 'actor': current_user.id, 'kind': kind, 'expires': time() + _TTL, **payload,
    }, prefix=_PREFIX)


def _staged(topic: GrammarTopic, kind: str, token: str) -> dict | None:
    if not token or len(token) > 36:
        return None
    data = load_import_data(token, prefix=_PREFIX)
    if (data and data.get('topic_id') == topic.id and data.get('actor') == current_user.id
            and data.get('kind') == kind and data.get('expires', 0) > time()):
        return data
    return None


def _format_document(document: dict | None) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) if document else ''


def _form(topic: GrammarTopic, document: dict | None, *, error: str = '', source: str | None = None,
          recovery: str = '', draft: str = '', status: int = 200) -> Response:
    learner_instructions = {}
    for step in (document or {}).get('steps', []):
        notes = []
        for row in step['exercises']:
            if has_blank_format_conflict(row) and (shown := blank_instruction(row)) != row['instruction']:
                notes.append((row['question'], shown))
        if notes:
            learner_instructions[step['id']] = notes
    return _private('edit', status, topic=topic, document=document, error=error,
                    source=_format_document(document) if source is None else source, recovery=recovery, draft=draft,
                    learner_instructions=learner_instructions)


def _parse_document(topic: GrammarTopic, value: str) -> dict:
    if len(value.encode('utf-8')) > _MAX_DOCUMENT:
        raise ValueError('Авторский JSON превышает 500 КБ.')
    try:
        document = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(f'Проверьте JSON, строка {error.lineno}, столбец {error.colno}.') from error
    try:
        validate_authored_topic(document)
        encoded = json.dumps(document, allow_nan=False, ensure_ascii=False)
    except TypeError as error:
        raise ValueError('Проверьте типы полей авторского документа.') from error
    if '<' in encoded or '>' in encoded:
        raise ValueError('В авторском тексте используйте обычный текст без HTML.')
    if document['topic_slug'] != topic.slug:
        raise ValueError('Документ относится к другой теме.')
    if len(document['title']) + len('Грамматика: ') > 200:
        raise ValueError('Название слишком длинное для связанного урока.')
    for step in document['steps']:
        for row in step['exercises']:
            if any(key.startswith('guided_') for key in row) or 'theory_help' in row or 'source' in row:
                raise ValueError('Служебные поля упражнений определяются при публикации.')
    return document


def _diff(before: dict, after: dict) -> list[tuple[str, str, str]]:
    changes = []

    def add(label: str, old: Any, new: Any) -> None:
        if old != new:
            changes.append((label, old if isinstance(old, str) else json.dumps(old, ensure_ascii=False, indent=2),
                            new if isinstance(new, str) else json.dumps(new, ensure_ascii=False, indent=2)))

    for key, label in [('title', 'Название темы'), ('goal', 'Цель'), ('version', 'Версия документа')]:
        add(label, before[key], after[key])
    old_steps = {step['id']: step for step in before['steps']}
    new_steps = {step['id']: step for step in after['steps']}
    add('Порядок шагов', list(old_steps), list(new_steps))
    for step_id in dict.fromkeys([*old_steps, *new_steps]):
        old, new = old_steps.get(step_id, {}), new_steps.get(step_id, {})
        label = f'Шаг «{new.get("title", old.get("title", step_id))}»'
        add(f'{label} · название', old.get('title', ''), new.get('title', ''))
        add(f'{label} · теория', old.get('body', ''), new.get('body', ''))
        add(f'{label} · упражнения', old.get('exercises', []), new.get('exercises', []))
    add('Справочные разделы', before.get('reference_sections', []), after.get('reference_sections', []))
    return changes


@guided_topics_bp.get('/grammar-lab/guided')
@content_editor_required
def index() -> Response:
    topics = (GrammarTopic.query.filter(GrammarTopic.content['guided_catalog_digest'].as_string().isnot(None))
              .order_by(GrammarTopic.level, GrammarTopic.order, GrammarTopic.id).all())
    return _private('index', topics=topics)


@guided_topics_bp.get('/grammar-lab/guided/<int:topic_id>')
@content_editor_required
def edit(topic_id: int) -> Response:
    topic = _topic(topic_id)
    draft = request.args.get('draft', '')
    if draft:
        data = _staged(topic, 'preview', draft)
        if data and data['base_digest'] == topic.content['guided_catalog_digest']:
            return _form(topic, data['document'], recovery=data['recovery'], draft=draft)
        return _form(topic, recover_document(topic), error='Черновик устарел. Открыта текущая тема.', status=409)
    return _form(topic, recover_document(topic))


@guided_topics_bp.post('/grammar-lab/guided/<int:topic_id>/preview')
@content_editor_required
def preview(topic_id: int) -> Response:
    topic = _topic(topic_id)
    base = recover_document(topic)
    recovery = request.form.get('recovery', '')
    if (base is None and (data := _staged(topic, 'source', recovery))
            and content_digest(data['document']) == topic.content['guided_catalog_digest']):
        base = data['document']
    mode = request.form.get('mode')
    source = request.form.get('document', '') if mode in ('source', 'recover') else None
    draft = request.form.get('draft', '')
    working = base
    try:
        if request.form.get('base_digest') != topic.content['guided_catalog_digest']:
            raise ValueError('Тема изменилась. Откройте текущую версию заново.')
        if mode == 'recover':
            original = _parse_document(topic, source or '')
            if content_digest(original) != topic.content['guided_catalog_digest']:
                raise ValueError('Документ отличается от установленного исходника.')
            recovery = _stage(topic, 'source', {'document': original})
            return _form(topic, original, recovery=recovery)
        if base is None:
            raise ValueError('Сначала загрузите точный исходник установленной темы.')
        if draft:
            staged = _staged(topic, 'preview', draft)
            if not staged or staged['base_digest'] != topic.content['guided_catalog_digest']:
                raise ValueError('Черновик устарел. Откройте текущую тему заново.')
            working = staged['document']
        if mode == 'source':
            proposed = _parse_document(topic, source or '')
        elif mode == 'fields':
            working = edited_document(working, request.form.get('title', ''), request.form.get('goal', ''),
                                      request.form.getlist('body'))
            proposed = _parse_document(topic, _format_document(working))
        else:
            raise ValueError('Выберите способ редактирования.')
        report = install_catalog(documents={topic.slug: proposed})
        if not report['topics_to_update']:
            return _form(topic, base, error='В документе нет изменений.', recovery=recovery)
        inactive = report['inactive_decisions']
        if inactive:
            case_ids: dict[int, list[int]] = {}
            disputes = AnswerDispute.query.filter(
                AnswerDispute.status == 'applied',
                AnswerDispute.grammar_exercise_id.in_([item['exercise_id'] for item in inactive]),
            ).order_by(AnswerDispute.id).all()
            for dispute in disputes:
                case_ids.setdefault(dispute.grammar_exercise_id, []).append(dispute.id)
            for item in inactive:
                item['dispute_ids'] = case_ids.get(item['exercise_id'], [])
        token = _stage(topic, 'preview', {
            'document': proposed, 'state': report['preview_state'], 'acknowledge': bool(inactive),
            'base_digest': topic.content['guided_catalog_digest'], 'recovery': recovery,
        })
        if draft:
            delete_import_data(draft, prefix=_PREFIX)
        return _private('preview', topic=topic, changes=_diff(base, proposed), report=report, token=token)
    except ValueError as error:
        return _form(topic, working, error=str(error), source=source, recovery=recovery, draft=draft, status=422)


@guided_topics_bp.post('/grammar-lab/guided/<int:topic_id>/publish')
@content_editor_required
def publish(topic_id: int) -> Response:
    topic = _topic(topic_id)
    editor = User.query.filter_by(id=current_user.id).with_for_update(read=True).populate_existing().one_or_none()
    if editor is None or not editor.can_edit_content:
        abort(403)
    token = request.form.get('preview_id', '')
    data = _staged(topic, 'preview', token)
    if not data:
        return _form(topic, recover_document(topic), error='Предпросмотр устарел. Проверьте правку ещё раз.', status=409)
    if data['acknowledge'] and request.form.get('acknowledge_decisions') != 'yes':
        return _form(topic, recover_document(topic), error='Подтвердите изменение решений в предпросмотре.', status=422)

    def audit() -> None:
        log_admin_action(editor.id, 'grammar_topic.publish_guided', target_type='grammar_topic', target_id=topic.id,
                         required=True)

    try:
        if not delete_import_data(token, prefix=_PREFIX):
            raise ValueError('Предпросмотр уже закрыт.')
        install_catalog(documents={topic.slug: data['document']}, apply=True, expected_state=data['state'],
                        before_commit=audit)
    except ValueError:
        db.session.rollback()
        return _form(topic, recover_document(topic), error='Тема или решения изменились. Создайте новый предпросмотр.',
                     status=409)
    except Exception:
        db.session.rollback()
        logger.exception('Guided topic publication failed for topic ID %s', topic_id)
        return _form(topic, recover_document(topic), error='Публикация отменена. Изменения не сохранены.', status=500)
    from app.curriculum.cache import cache

    cache.clear()
    flash('Пошаговая тема опубликована.', 'success')
    return redirect(url_for('.edit', topic_id=topic_id, materials_query=_materials_query(),
                            from_dispute=_from_dispute(topic)), code=303)
