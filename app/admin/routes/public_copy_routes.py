"""Administrative page copy with private previews and explicit publication."""

import re

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import AnonymousUserMixin, current_user
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.admin.audit import log_admin_action
from app.admin.utils.decorators import admin_required
from app.landing.demo_publication import demos_for_editing, publish_demo, published_demo
from app.landing.previews import PREVIEWS_BY_ID
from app.landing.routes import render_landing
from app.public_copy import (
    MAX_FAQ, PAGES, QUESTION_LIMIT, TEXT_LIMIT, StalePublication, digest, field_limit, publish_copy, published_copy,
)
from app.public_copy_markup import apply_copy, editable_defaults
from app.utils.db import db

public_copy_bp = Blueprint('public_copy_admin', __name__)
_PREVIEW_AGE = 1800
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


@public_copy_bp.after_request
def _private(response: Response) -> Response:
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Robots-Tag'] = 'noindex'
    return response


def _input(value: str) -> str:
    return value.replace('\r\n', '\n').replace('\r', '\n').strip()


def _submitted(page: str, fields: dict) -> dict:
    result = {'text': {key: _input(request.form.get(f'text.{key}', '')) for key in fields}}
    if page == 'home':
        questions = request.form.getlist('question')
        answers = request.form.getlist('answer')
        if len(questions) != len(answers) or len(questions) > MAX_FAQ:
            abort(400)
        result['faq'] = [[_input(q), _input(a)]
                         for q, a in zip(questions, answers, strict=True)]
    return result


def _validate(page: str, document: dict, groups: dict) -> None:
    for title, fields in groups.items():
        for number, (key, _) in enumerate(fields, 1):
            value = document['text'][key]
            if (not value or len(value) > field_limit(key) or _CONTROL.search(value)
                    or (key.startswith('seo.') and '\n' in value)):
                raise ValueError(f'Проверьте поле {number} в разделе «{title}».')
    if page == 'home':
        if not document['faq']:
            raise ValueError('Оставьте хотя бы одну пару вопросов и ответов.')
        for number, (question, answer) in enumerate(document['faq'], 1):
            if (not question or not answer or len(question) > QUESTION_LIMIT or len(answer) > TEXT_LIMIT
                    or '\n' in question or _CONTROL.search(question) or _CONTROL.search(answer)):
                raise ValueError(f'Проверьте вопрос и ответ в паре № {number}.')


def _originals(page: str) -> tuple[str, ...]:
    if page == 'home':
        return render_landing(editorial_preview=True), render_landing(editorial_preview=True, guest_view=False)
    template = 'mobile_support' if page == 'support' else 'privacy'
    return (render_template(f'legal/{template}.html', current_user=AnonymousUserMixin()),)


@public_copy_bp.get('/public-pages')
@admin_required
def index() -> str:
    return render_template('admin/public_copy/index.html', pages=PAGES)


@public_copy_bp.route('/public-pages/<page>', methods=['GET', 'POST'])
@admin_required
def edit(page: str) -> ResponseReturnValue:
    if page not in PAGES:
        abort(404)
    originals = _originals(page)
    try:
        defaults, groups = editable_defaults(page, *originals)
    except (TypeError, ValueError, KeyError):
        current_app.logger.exception('Cannot load editorial layout for %s', page)
        return render_template('admin/public_copy/unavailable.html', page_info=PAGES[page]), 409
    current, revision = published_copy(page, defaults)
    document = current
    preview = signed = error = ''
    changed = []
    faq_changed = False
    status = 200
    if request.method == 'POST':
        document = _submitted(page, defaults['text'])
        action = request.form.get('action', '')
        try:
            if request.form.get('revision') != revision:
                raise StalePublication()
            if page == 'home' and action == 'add':
                if len(document['faq']) >= MAX_FAQ:
                    raise ValueError(f'Можно добавить до {MAX_FAQ} пар.')
                document['faq'].append(['', ''])
            elif page == 'home' and action.startswith('remove.'):
                index = action.removeprefix('remove.')
                if not index.isascii() or not index.isdecimal() or len(index) > 2 or int(index) >= len(document['faq']):
                    abort(400)
                if len(document['faq']) == 1:
                    raise ValueError('Оставьте хотя бы одну пару вопросов и ответов.')
                document['faq'].pop(int(index))
            elif action in ('preview', 'publish'):
                _validate(page, document, groups)
                signer = URLSafeTimedSerializer(current_app.secret_key, salt='admin-public-copy')
                binding = [current_user.id, page, revision, digest(document)]
                if action == 'preview':
                    if document == current:
                        raise ValueError('Изменений нет.')
                    signed = signer.dumps(binding)
                    preview = apply_copy(page, originals[0], document)
                    changed = [(title, number, current['text'][key], document['text'][key])
                               for title, fields in groups.items()
                               for number, (key, _) in enumerate(fields, 1) if current['text'][key] != document['text'][key]]
                    faq_changed = document.get('faq') != current.get('faq')
                else:
                    token = request.form.get('preview_token', '')
                    if len(token) > 1024 or signer.loads(token, max_age=_PREVIEW_AGE) != binding:
                        raise StalePublication()
                    if publish_copy(page, document, revision, defaults):
                        log_admin_action(current_user.id, f'public_copy.publish.{page}', 'public_copy', required=True)
                    db.session.commit()
                    flash('Страница опубликована.', 'success')
                    return redirect(url_for('.edit', page=page), code=303)
            else:
                abort(400)
        except (BadSignature, StalePublication):
            db.session.rollback()
            current, revision = published_copy(page, defaults)
            error, status = 'Предпросмотр истёк или страница изменилась. Проверьте текст и откройте новый предпросмотр.', 409
        except ValueError as exc:
            db.session.rollback()
            error, status = str(exc), 422
        except Exception:
            db.session.rollback()
            raise
    return render_template(
        'admin/public_copy/edit.html', page=page, page_info=PAGES[page], groups=groups, defaults=defaults['text'],
        document=document, old_faq=current.get('faq'), revision=revision, preview=preview, token=signed,
        changed=changed, faq_changed=faq_changed, error=error, text_limit=TEXT_LIMIT, question_limit=QUESTION_LIMIT,
        max_faq=MAX_FAQ, field_limit=field_limit,
    ), status


@public_copy_bp.get('/public-pages/demo')
@admin_required
def demo_index() -> str:
    return render_template('admin/public_copy/demo_index.html', demos=demos_for_editing())


def _demo_document(preview_id: str) -> tuple[dict, int | None]:
    options = [_input(request.form.get(f'option{number}', '')) for number in range(3)]
    choice = request.form.get('correct_option')
    correct = int(choice) if choice in ('0', '1', '2') else None
    return {
        'id': preview_id,
        'prompt': _input(request.form.get('prompt', '')),
        'instruction': _input(request.form.get('instruction', '')),
        'options': options,
        'correct': options[correct] if correct is not None else '',
        'explanation': _input(request.form.get('explanation', '')),
    }, correct


def _validate_demo(document: dict, selected: int | None) -> None:
    for key, limit, label in (('prompt', 250, 'Фраза с пропуском'), ('instruction', 500, 'Инструкция'),  # noqa: RUF001 -- Russian form label.
                              ('explanation', 1000, 'Объяснение')):
        value = document[key]
        if not value or len(value) > limit or _CONTROL.search(value):
            raise ValueError(f'Проверьте поле «{label}».')
    if re.findall(r'_+', document['prompt']) != ['___'] or '\n' in document['prompt']:
        raise ValueError('В одной строке должен быть ровно один пропуск из трёх подчёркиваний.')  # noqa: RUF001 -- Russian validation message.
    options = document['options']
    if (any(not option or len(option) > 120 or '\n' in option or _CONTROL.search(option) for option in options)
            or len({option.casefold() for option in options}) != 3):
        raise ValueError('Введите три разных варианта ответа.')
    if selected is None:
        raise ValueError('Выберите правильный ответ из показанных вариантов.')


@public_copy_bp.route('/public-pages/demo/<preview_id>', methods=['GET', 'POST'])
@admin_required
def edit_demo(preview_id: str) -> ResponseReturnValue:
    if preview_id not in PREVIEWS_BY_ID:
        abort(404)
    current, revision = published_demo(preview_id)
    document = current
    selected = current['options'].index(current['correct'])
    token = error = ''
    status = 200
    if request.method == 'POST':
        document, selected = _demo_document(preview_id)
        action = request.form.get('action')
        try:
            if request.form.get('revision') != revision:
                raise StalePublication()
            if action not in ('preview', 'publish'):
                abort(400)
            _validate_demo(document, selected)
            signer = URLSafeTimedSerializer(current_app.secret_key, salt='admin-landing-demo')
            binding = [current_user.id, preview_id, revision, digest(document)]
            if action == 'preview':
                if document == current:
                    raise ValueError('Изменений нет.')
                token = signer.dumps(binding)
            else:
                signed = request.form.get('preview_token', '')
                if len(signed) > 1024 or signer.loads(signed, max_age=_PREVIEW_AGE) != binding:
                    raise StalePublication()
                if publish_demo(preview_id, document, revision):
                    log_admin_action(current_user.id, f'landing_demo.publish.{preview_id}', 'landing_demo', required=True)
                db.session.commit()
                flash('Упражнение опубликовано.', 'success')
                return redirect(url_for('.edit_demo', preview_id=preview_id), code=303)
        except (BadSignature, StalePublication):
            db.session.rollback()
            current, revision = published_demo(preview_id)
            error, status = 'Предпросмотр истёк или упражнение изменилось. Откройте новый предпросмотр.', 409
        except ValueError as exc:
            db.session.rollback()
            error, status = str(exc), 422
        except Exception:
            db.session.rollback()
            raise
    return render_template('admin/public_copy/demo_edit.html', document=document, current=current, selected=selected,
                           revision=revision, token=token, error=error), status
