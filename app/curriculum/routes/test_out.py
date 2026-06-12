"""Routes: сдача модуля экстерном (test-out)."""
import logging

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from app.curriculum.models import Module
from app.curriculum.routes.lessons import lessons_bp
from app.curriculum.security import check_module_access
from app.curriculum.services.test_out import (
    SESSION_KEY_PREFIX,
    TEST_OUT_MIN_QUESTIONS,
    TEST_OUT_PASSING_SCORE,
    apply_test_out_pass,
    client_questions,
    get_test_out_state,
    grade_test_out,
    questions_by_refs,
    record_test_out_attempt,
    sample_test_refs,
)
from app.utils.db import db

logger = logging.getLogger(__name__)

_REASON_MESSAGES = {
    'module_completed': 'Модуль уже завершён — экстерн не нужен.',
    'already_passed': 'Вы уже сдали этот модуль экстерном.',
    'not_enough_content': 'В модуле недостаточно вопросов для экстерна.',
    'attempts_exhausted': 'Лимит попыток на сегодня исчерпан — попробуйте завтра.',
}


def _module_page_url(module: Module) -> str:
    return url_for(
        'learn.learn_by_module',
        level_code=module.level.code.lower(),
        module_number=module.number,
    )


@lessons_bp.route('/module/<int:module_id>/test-out')
@login_required
def module_test_out(module_id: int):
    """Страница экстерна: вопросы по материалу модуля, порог 80%."""
    module = Module.query.get_or_404(module_id)
    if not check_module_access(module.id):
        flash('Этот модуль пока недоступен.', 'warning')
        return redirect(url_for('learn.learn_index'))

    state = get_test_out_state(current_user.id, module, db)
    if not state['available']:
        flash(_REASON_MESSAGES.get(state['reason'], 'Экстерн недоступен.'), 'info')
        return redirect(_module_page_url(module))

    refs = sample_test_refs(module)
    session[SESSION_KEY_PREFIX + str(module_id)] = refs
    questions = client_questions(questions_by_refs(module, refs))
    return render_template(
        'curriculum/module_test_out.html',
        module=module,
        questions=questions,
        passing_score=TEST_OUT_PASSING_SCORE,
        module_url=_module_page_url(module),
    )


@lessons_bp.route('/api/module/<int:module_id>/test-out', methods=['POST'])
@login_required
def module_test_out_submit(module_id: int):
    """Принять ответы экстерна; при сдаче — mass-complete уроков модуля."""
    module = Module.query.get_or_404(module_id)
    if not check_module_access(module.id):
        return jsonify({'success': False, 'error': 'forbidden'}), 403

    session_key = SESSION_KEY_PREFIX + str(module_id)
    refs = session.get(session_key)
    if not refs:
        return jsonify({'success': False, 'error': 'no_active_test'}), 409

    # Повторная проверка гонок: лимит попыток / уже сдан.
    state = get_test_out_state(current_user.id, module, db)
    if not state['available']:
        session.pop(session_key, None)
        return jsonify({'success': False, 'error': state['reason']}), 409

    data = request.get_json(silent=True) or {}
    answers = data.get('answers')
    if not isinstance(answers, dict):
        return jsonify({'success': False, 'error': 'invalid_input'}), 400

    questions = questions_by_refs(module, refs)
    if len(questions) < TEST_OUT_MIN_QUESTIONS:
        session.pop(session_key, None)
        return jsonify({'success': False, 'error': 'no_active_test'}), 409

    result = grade_test_out(questions, answers)

    try:
        record_test_out_attempt(
            current_user.id, module.id, result['score'], result['passed'], db
        )
        completed_lessons = 0
        if result['passed']:
            completed_lessons = apply_test_out_pass(
                current_user.id, module, result['score'], db
            )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception(
            "test-out persist failed for user %s module %s",
            current_user.id, module_id,
        )
        return jsonify({'success': False, 'error': 'internal_error'}), 500

    session.pop(session_key, None)
    return jsonify({
        'success': True,
        'score': result['score'],
        'passed': result['passed'],
        'correct_answers': result['correct_answers'],
        'total_questions': result['total_questions'],
        'completed_lessons': completed_lessons,
        'module_url': _module_page_url(module),
    })
