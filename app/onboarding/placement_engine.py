"""Account-owned placement, without course grades, XP or speaking assessment."""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import random
from typing import Any
from uuid import uuid4

from app.auth.models import User
from app.onboarding.placement_bank import LEVELS, SKILL_LABELS
from app.onboarding.placement_models import PlacementAttempt, PlacementBank, PlacementGuest, utcnow
from app.utils.db import db
from app.utils.normalization import normalize_quiz_answer

CORE = ('grammar', 'vocabulary', 'reading', 'listening')
STARTER_SCOPE = 'starter'
STARTER_QUESTIONS = 10
MODES = {
    'quick': {'title': 'Быстро подобрать старт', 'minutes': '5–7', 'max_questions': 14},  # noqa: RUF001
    'detailed': {'title': 'Проверить знания подробнее', 'minutes': '15–20', 'max_questions': 24},  # noqa: RUF001
}


class PlacementError(Exception):
    def __init__(self, code: str, status: int = 400) -> None:
        self.code, self.status = code, status


def _query(user_id: int | str) -> Any:
    return db.session.query(PlacementAttempt).filter_by(**({'user_id': user_id} if type(user_id) is int else {'guest_key': user_id}))


def _owner(user_id: int | str) -> User | PlacementGuest:
    if isinstance(user_id, str):
        guest = db.session.query(PlacementGuest).filter_by(key=user_id).populate_existing().with_for_update().one_or_none()
        if guest is None or guest.expires_at <= utcnow():
            raise PlacementError('guest_expired', 409)
        return guest
    user = db.session.query(User).filter_by(id=user_id).populate_existing().with_for_update().one_or_none()
    if user is None or not user.is_active:
        raise PlacementError('access_denied', 403)
    return user


def _attempt(user_id: int | str, attempt_id: str) -> PlacementAttempt:
    if not isinstance(attempt_id, str) or len(attempt_id) > 36:
        raise PlacementError('not_found', 404)
    row = _query(user_id).filter_by(id=attempt_id).populate_existing().with_for_update().one_or_none()
    if row is None:
        raise PlacementError('not_found', 404)
    return row


def _items(row: PlacementAttempt) -> dict[str, dict]:
    bank = db.session.get(PlacementBank, row.bank_id)
    if bank is None:
        raise PlacementError('bank_unavailable', 409)
    return {q['id']: q for q in bank.content['items']}


def _issue(state: dict, pool: dict[str, dict], level: str, skill: str) -> None:
    used = {q['id'] for q in state['asked']}
    candidates = [q for q in pool.values() if q['level'] == level and q['skill'] == skill and q['id'] not in used]
    if not candidates:
        raise PlacementError('bank_incomplete', 409)
    question = random.SystemRandom().choice(candidates)
    # Shuffle answer order once; retries/resume must preserve the same layout.
    options = list(question.get('options') or [])
    random.SystemRandom().shuffle(options)
    state['asked'].append({'id': question['id'], 'nonce': str(uuid4()), 'options': options})


def _finish(row: PlacementAttempt, state: dict, pool: dict[str, dict]) -> None:
    domains = []
    weak = []
    for skill in (*CORE, 'writing'):
        answers = [a for a in state['asked'] if pool[a['id']]['skill'] == skill and 'correct' in a]
        domains.append({'id': skill, 'title': SKILL_LABELS[skill], 'total': len(answers),
                        'correct': sum(a['correct'] for a in answers)})
    for answer in state['asked']:
        if not answer.get('correct'):
            question = pool[answer['id']]
            topic = question.get('topic') or SKILL_LABELS[question['skill']]
            if topic not in weak:
                weak.append(topic)
    mapped = {}
    for answer in state['asked']:
        question = pool[answer['id']]
        slug = question.get('topic_slug')
        if not answer.get('correct') and slug and LEVELS.index(question['level']) <= state['candidate']:
            mapped.setdefault(slug, {'slug': slug, 'title': question.get('topic'), 'signals': 0})['signals'] += 1
    row.status = 'completed'
    row.completed_at = utcnow()
    row.result = {'recommended_level': LEVELS[state['candidate']], 'domains': domains,
                  'correct_count': sum(a.get('correct', False) for a in state['asked']),
                  'total': len(state['asked']), 'weak_topics': weak[:8],
                  'review_topics': list(mapped.values()), 'preliminary': True, 'speaking_assessed': False, 'free_writing_assessed': False}


def _next_starter(row: PlacementAttempt, state: dict, pool: dict[str, dict]) -> None:
    """Five short pairs, starting at A1; never interpret one guess as mastery."""
    answered = len(state['asked'])
    if answered % 2:
        _issue(state, pool, LEVELS[state['level']], 'vocabulary')
        return
    passed = all(a['correct'] for a in state['asked'][-2:])
    level = state['level']
    if passed:
        state['candidate'] = max(state['candidate'], level)
    else:
        state['candidate'] = min(state['candidate'], max(0, level - 1))
        state['failed_levels'] = sorted(set(state['failed_levels']) | {level})
    if answered == STARTER_QUESTIONS:
        _finish(row, state, pool)
        return
    state['level'] = (level if level + 1 in state['failed_levels'] else min(level + 1, 4)) if passed else max(0, level - 1)
    _issue(state, pool, LEVELS[state['level']], 'grammar')


def _next(row: PlacementAttempt, state: dict, pool: dict[str, dict]) -> None:
    if state.get('scope') == STARTER_SCOPE:
        _next_starter(row, state, pool)
        return
    answered = len(state['asked'])
    if state['phase'] == 'warmup':
        if answered == 1:
            _issue(state, pool, 'A1', 'vocabulary')
            return
        state.update(phase='core', level=2 if all(a['correct'] for a in state['asked']) else 1, rounds=0)
    elif state['phase'] == 'core' and (answered - 2) % 4 == 0:
        block = state['asked'][-4:]
        passed = sum(a['correct'] for a in block) >= 3 and all(
            a['correct'] for a in block if pool[a['id']]['skill'] in ('reading', 'listening'))
        level = state['level']
        if passed:
            state['candidate'] = max(state['candidate'], level)
        else:
            state['candidate'] = min(state['candidate'], max(0, level - 1))
            state['failed_levels'] = list(set(state['failed_levels']) | {level})
        state['rounds'] += 1
        if state['rounds'] == 3:
            if row.mode == 'quick':
                _finish(row, state, pool)
                return
            state.update(phase='verification', verification_start=answered)
        else:
            state['level'] = (level if level + 1 in state['failed_levels'] else min(level + 1, 4)) if passed else max(0, level - 1)
    if state['phase'] == 'verification':
        done = answered - state['verification_start']
        if done == 10:
            block = state['asked'][-10:]
            passed = sum(a['correct'] for a in block) >= 7 and all(
                any(a['correct'] and pool[a['id']]['skill'] == skill for a in block)
                for skill in ('reading', 'listening', 'writing'))
            if not passed:
                state['candidate'] = max(0, state['candidate'] - 1)
            _finish(row, state, pool)
            return
        skill = (*CORE, 'writing')[done % 5]
        _issue(state, pool, LEVELS[state['candidate']], skill)
    else:
        _issue(state, pool, LEVELS[state['level']], CORE[(answered - 2) % 4])


def projection(row: PlacementAttempt) -> dict:
    """Allowlist only: never serialize the bank or per-answer verdicts."""
    answered = sum('correct' in a for a in row.state['asked'])
    result = {'id': row.id, 'mode': row.mode, 'status': row.status, 'answered': answered,
              'max_questions': MODES[row.mode]['max_questions'], 'result': row.result,
              'applied': row.applied_at is not None,
              'scope': row.state.get('scope'),
              # max_questions remains the legacy quick upper bound so shipped
              # native clients can read imported guest results. Exact UI length:
              'question_count': STARTER_QUESTIONS if row.state.get('scope') == STARTER_SCOPE else MODES[row.mode]['max_questions']}
    if row.status == 'active':
        asked = row.state['asked'][-1]
        q = _items(row)[asked['id']]
        result['question'] = {'id': asked['nonce'], 'skill': q['skill'], 'skill_title': SKILL_LABELS[q['skill']],
            'input': q['input'], 'prompt': q['prompt'], 'options': asked['options'],
            'passage': q.get('passage'), 'audio_url': q.get('audio_url'), 'draft': asked.get('draft', '')}
    return result


def status(user_id: int | str) -> dict:
    active = _query(user_id).filter_by(status='active').first()
    latest = _query(user_id).filter_by(status='completed').order_by(PlacementAttempt.completed_at.desc()).first()
    bank = db.session.query(PlacementBank.id).filter_by(active=True).first()
    user = db.session.get(User, user_id) if type(user_id) is int else None
    return {'success': True, 'available': bank is not None,
            'modes': [{'id': key, **value} for key, value in MODES.items()],
            'active': projection(active) if active else None, 'latest': projection(latest) if latest else None,
            'pending_level': user.placement_pending_level if user else None,
            'pending_on': user.placement_pending_on.isoformat() if user and user.placement_pending_on else None}


def start(user_id: int | str, mode: Any, *, scope: Any = None) -> dict:
    if not isinstance(mode, str) or mode not in MODES:
        raise PlacementError('invalid_mode')
    if scope is not None and (scope != STARTER_SCOPE or mode != 'quick'):
        raise PlacementError('invalid_scope')
    _owner(user_id)
    active = _query(user_id).filter_by(status='active').first()
    if active is not None:
        if active.mode != mode or (scope is not None and active.state.get('scope') != scope):
            raise PlacementError('active_attempt', 409)
        return projection(active)
    bank = db.session.query(PlacementBank).filter_by(active=True).first()
    if bank is None:
        raise PlacementError('bank_unavailable', 409)
    row = PlacementAttempt(id=str(uuid4()), bank_id=bank.id, mode=mode, status='active',
                           **({'user_id': user_id} if type(user_id) is int else {'guest_key': user_id}))
    state = {'version': 1, 'phase': 'warmup', 'candidate': 0, 'failed_levels': [], 'asked': []}
    if scope == STARTER_SCOPE:
        state.update(scope=STARTER_SCOPE, phase='starter', level=0)
    _issue(state, {q['id']: q for q in bank.content['items']}, 'A1', 'grammar')
    row.state = state
    db.session.add(row)
    db.session.flush()
    return projection(row)


def _answer_value(value: Any, dont_know: Any) -> str:
    if type(dont_know) is not bool or not isinstance(value, str) or len(value) > 1000 or '\x00' in value:
        raise PlacementError('invalid_input')
    if dont_know and value != '':
        raise PlacementError('invalid_input')
    if not dont_know and not value.strip():
        raise PlacementError('empty_answer')
    return value


def answer(user_id: int | str, attempt_id: str, question_id: Any, value: Any, dont_know: Any) -> dict:
    _owner(user_id)
    row = _attempt(user_id, attempt_id)
    if row.status == 'abandoned':
        raise PlacementError('attempt_closed', 409)
    value = _answer_value(value, dont_know)
    if not isinstance(question_id, str) or len(question_id) != 36:
        raise PlacementError('invalid_question')
    state = deepcopy(row.state)
    previous = next((a for a in state['asked'] if a['nonce'] == question_id), None)
    if previous is None:
        raise PlacementError('stale_question', 409)
    if 'correct' in previous:
        if previous['answer'] != value or previous['dont_know'] != dont_know:
            raise PlacementError('answer_already_saved', 409)
        return projection(row)  # exact retry after a lost response, including the final answer
    if row.status != 'active' or previous is not state['asked'][-1]:
        raise PlacementError('attempt_closed', 409)
    pool = _items(row)
    q = pool[previous['id']]
    if not dont_know and q['input'] == 'choice' and value not in previous['options']:
        raise PlacementError('invalid_option')
    previous.update(answer=value, dont_know=dont_know,
                    correct=not dont_know and (value == q['answers'][0] if q['input'] == 'choice' else any(
                        normalize_quiz_answer(value) == normalize_quiz_answer(key) for key in q['answers'])))
    previous.pop('draft', None)
    _next(row, state, pool)
    row.state = state
    row.updated_at = utcnow()
    db.session.flush()
    return projection(row)


def save_draft(user_id: int | str, attempt_id: str, question_id: Any, value: Any) -> dict:
    _owner(user_id)
    row = _attempt(user_id, attempt_id)
    if not isinstance(value, str) or len(value) > 1000 or '\x00' in value:
        raise PlacementError('invalid_input')
    state = deepcopy(row.state)
    q = state['asked'][-1]
    if row.status != 'active' or q['nonce'] != question_id or 'correct' in q:
        raise PlacementError('stale_question', 409)
    item = _items(row)[q['id']]
    if item['input'] == 'choice' and value and value not in q['options']:
        raise PlacementError('invalid_option')
    q['draft'] = value
    row.state = state
    row.updated_at = utcnow()
    db.session.flush()
    return projection(row)


def abandon(user_id: int | str, attempt_id: str) -> dict:
    _owner(user_id)
    row = _attempt(user_id, attempt_id)
    if row.status == 'completed':
        raise PlacementError('attempt_closed', 409)
    row.status = 'abandoned'
    row.updated_at = utcnow()
    db.session.flush()
    return {'id': row.id, 'status': row.status}


def adopt_level(user_id: int, attempt_id: str) -> dict:
    user = _owner(user_id)
    if not isinstance(user, User):
        raise PlacementError('registration_required', 401)
    row = _attempt(user_id, attempt_id)
    if row.status != 'completed' or not row.result:
        raise PlacementError('test_not_completed', 409)
    if row.applied_at is None:
        newer = db.session.query(PlacementAttempt.id).filter(
            PlacementAttempt.user_id == user_id, PlacementAttempt.applied_at.isnot(None),
            PlacementAttempt.created_at > row.created_at).first()
        if newer:
            raise PlacementError('newer_result_applied', 409)
        level = row.result['recommended_level']
        # Rebuild only an untouched study day. Once learning activity exists,
        # preserve today's lesson IDs, streak and drafts and start tomorrow.
        from app.utils.activity_tracker import has_learning_activity
        from app.utils.time_utils import get_user_local_day_bounds, study_day_date_for_tz
        start, end = get_user_local_day_bounds(user.id, db)
        studied = has_learning_activity(user.id, start, min(end, utcnow()))
        if not studied:
            user.onboarding_level = level
            user.placement_pending_level = None
            user.placement_pending_on = None
            from app.daily_plan.snapshot import _get_or_create_log_row
            log = _get_or_create_log_row(user.id, study_day_date_for_tz(user.timezone), db)
            log.plan_json = {'placement_rebuild': True}
        else:
            from app.utils.time_utils import study_day_date_for_tz
            user.placement_pending_level = level
            user.placement_pending_on = study_day_date_for_tz(user.timezone) + timedelta(days=1)
        from flask import has_request_context, g
        if has_request_context():
            getattr(g, '_request_cache', {}).clear()
        row.applied_at = utcnow()
        row.result = {**row.result, 'effective_on': user.placement_pending_on.isoformat() if user.placement_pending_on else None}
        db.session.flush()
        from app.onboarding.placement_reviews import seed
        seed(row)
    return {'id': row.id, 'applied': True,
            'level': row.result['recommended_level'],
            'effective_on': row.result.get('effective_on')}


def activate_pending(user: User) -> None:
    """Flush-only; called before assembling a new study day, never reset progress."""
    if not user.placement_pending_level or not user.placement_pending_on:
        return
    from app.utils.time_utils import study_day_date_for_tz
    if user.placement_pending_on > study_day_date_for_tz(user.timezone):
        return
    locked = _owner(user.id)
    if locked.placement_pending_level and locked.placement_pending_on and locked.placement_pending_on <= study_day_date_for_tz(locked.timezone):
        from app.utils.activity_tracker import has_learning_activity
        from app.utils.time_utils import get_user_local_day_bounds
        from app.daily_plan.snapshot import _get_or_create_log_row
        today = study_day_date_for_tz(locked.timezone)
        start, end = get_user_local_day_bounds(locked.id, db)
        if has_learning_activity(locked.id, start, min(end, utcnow())):
            locked.placement_pending_on = today + timedelta(days=1)
            db.session.flush()
            return
        # An explicit new starting level supersedes yesterday's rollover,
        # but only before any activity in this study day.
        log = _get_or_create_log_row(locked.id, today, db)
        log.plan_json = {'placement_rebuild': True}
        locked.onboarding_level = locked.placement_pending_level
        locked.placement_pending_level = None
        locked.placement_pending_on = None
        db.session.flush()
