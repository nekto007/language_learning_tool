"""Resumable daily-plan flashcards; grading uses the canonical SRS engine."""
from copy import deepcopy
from datetime import datetime, UTC
import hashlib
import json
from uuid import UUID
from sqlalchemy.orm.attributes import flag_modified

from flask import Blueprint, jsonify, request, current_app
from flask_login import current_user

from app import csrf, limiter
from app.api.decorators import api_bearer_required
from app.api.native_lessons import NativeLessonError, native_error, plain, private_response
from app.study.models import StudySettings
from app.utils.db import db
from app.utils.rate_limit_helpers import get_authenticated_user_key

api_native_srs = Blueprint('api_native_srs', __name__)
api_native_srs.after_request(private_response)
api_native_srs.register_error_handler(NativeLessonError, native_error)
MAX_BATCH = 200


def _guard():
    from app.modules.service import ModuleService
    from app.daily_plan.service import get_daily_plan_unified
    from app.achievements.streak_service import compute_plan_steps
    from app.telegram.queries import get_daily_summary
    from app.utils.time_utils import get_user_timezone_name
    if not ModuleService.is_module_enabled_for_user(current_user.id, 'study'):
        raise NativeLessonError('access_denied', 403)
    tz = get_user_timezone_name(current_user.id, db)
    plan = get_daily_plan_unified(current_user.id, tz=tz)
    if plan.get('mode') == 'paused':
        raise NativeLessonError('plan_paused', 403)
    completed, *_ = compute_plan_steps(plan, get_daily_summary(current_user.id, tz=tz))
    required, optional = plan.get('required') or [], plan.get('optional') or []
    done = lambda it: it.get('completed') or completed.get(it.get('id'), False)
    next_item = next((it for it in required if not done(it) and not it.get('skipped') and not it.get('blocked')), None)
    if next_item is None and (not required or all(done(it) or it.get('skipped') for it in required) or plan.get('day_secured')):
        next_item = next((it for it in optional if not done(it)), None)
    skipped_srs = any(it.get('kind') == 'srs' and it.get('skipped') and not it.get('blocked') and not done(it) for it in required)
    if (next_item and next_item.get('id') == 'srs:deck_quiz') or (not skipped_srs and (not next_item or next_item.get('kind') != 'srs' or next_item.get('blocked'))):
        raise NativeLessonError('lesson_locked', 403)


def _day():
    from app.utils.time_utils import get_user_local_date
    return get_user_local_date(current_user.id, db).isoformat()


def _lock_user():
    from app.auth.models import User
    db.session.query(User.id).filter(User.id == current_user.id).with_for_update().one()


def _run():
    from app.study.models import NativeSRSState
    return NativeSRSState.query.filter_by(user_id=current_user.id).populate_existing().first()


def _revision(card):
    if card is None or card.first_reviewed is None:
        return None
    fields = ('last_reviewed', 'state', 'step_index', 'repetitions', 'interval', 'correct_count', 'incorrect_count')
    return hashlib.sha256(json.dumps({k: str(getattr(card, k, None)) for k in fields}, sort_keys=True).encode()).hexdigest()


def _pool():
    from app.study.api_routes import build_study_items_response
    response = build_study_items_response(native_plan=True)
    if isinstance(response, tuple) or response.status_code != 200:
        raise NativeLessonError('server_error', 503)
    return response.get_json()['items'][:MAX_BATCH]


def _pack_pool(items):
    from app.study.models import UserCardDirection, UserWord
    word_ids = [it['word_id'] for it in items]
    rows = UserCardDirection.query.join(UserWord).filter(UserWord.user_id == current_user.id, UserWord.word_id.in_(word_ids)).all() if word_ids else []
    by_key = {(r.user_word.word_id, r.direction): r for r in rows}
    queue, seen = [], set()
    for item in items:
        key = item['word_id'], item['direction']
        if key in seen: continue
        seen.add(key)
        card = by_key.get(key)
        if card is not None: card.session_attempts = 0
        queue.append({'word_id': item['word_id'], 'direction': item['direction'],
            'front': plain(item['word']), 'back': plain(item['translation']),
            'examples': _examples(item.get('examples')), 'audio_url': item.get('audio_url'),
            'state': item.get('state', 'new'), 'revision': _revision(card)})
    return queue


def _examples(value):
    """Return plain bilingual lines without leaking HTML/JSON storage syntax."""
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = value
    if isinstance(parsed, dict):
        parsed = [parsed]
    if isinstance(parsed, list):
        lines = []
        for row in parsed:
            if isinstance(row, dict):
                lines.extend([plain(row.get('en') or row.get('english') or row.get('sentence')),
                              plain(row.get('ru') or row.get('russian') or row.get('translation'))])
            elif isinstance(row, str):
                lines.append(plain(row))
        return '\n'.join(line for line in lines if line).replace('|', '\n')
    return plain(value).replace('|', '\n')


def _with_audio_preference(response: dict) -> dict:
    setting = db.session.query(StudySettings.include_audio).filter_by(user_id=current_user.id).scalar()
    return {**response, 'autoplay_audio': setting is not False}


def _response(run):
    state = run.state
    head = state['queue'][0] if state['queue'] else None
    card = {k: v for k, v in head.items() if k != 'revision'} if head else None
    response = {'success': True, 'session_id': run.session_id, 'step': state['step'], 'card': card,
            'remaining': len(state['queue']), 'reviewed': state['reviewed'], 'remembered': state['remembered'],
            'complete': state['complete'], 'xp_earned': state.get('xp_earned', 0), 'notice': state.get('notice'),
            'statistics': _statistics(state)}
    return response if state.get('lesson_id') is not None else _with_audio_preference(response)


def _round_metadata(queue):
    return {'round_keys': [str(c.get('key') or f"{c['word_id']}:{c['direction']}") for c in queue],
            'round_words': len({c['word_id'] for c in queue}),
            'rating_counts': {'1': 0, '2': 0, '3': 0}, 'reviewed_keys': [], 'reviewed_words': []}


def _record_rating(state, head, rating):
    # Older active sessions keep their legacy summary until the next new run.
    if 'rating_counts' not in state:
        return
    state['rating_counts'][str(rating)] += 1
    key = str(head.get('key') or f"{head['word_id']}:{head['direction']}")
    if key not in state['reviewed_keys']:
        state['reviewed_keys'].append(key)
    if head['word_id'] not in state['reviewed_words']:
        state['reviewed_words'].append(head['word_id'])


def _statistics(state):
    counts = state.get('rating_counts')
    if not counts or sum(counts.values()) != state['reviewed']:
        return None
    return {'unknown': counts['1'], 'hesitant': counts['2'], 'known': counts['3'],
            'unique_cards': len(state['reviewed_keys']), 'unique_words': len(state['reviewed_words']),
            'total_cards': len(state['round_keys']), 'total_words': state['round_words']}


def _remaining():
    from app.srs.counting import count_pending_new, count_due_by_states, get_new_card_budget, get_due_card_budget, split_due_budget
    from app.srs.constants import CardState as CS
    new_budget, reviews = get_new_card_budget(current_user.id, db)
    learning, review = split_due_budget(current_user.id, db,
        learning_due=count_due_by_states(current_user.id, db, states=(CS.LEARNING.value, CS.RELEARNING.value)),
        review_due=count_due_by_states(current_user.id, db, states=(CS.REVIEW.value,)),
        due_budget=get_due_card_budget(current_user.id, db), remaining_reviews=reviews)
    return min(count_pending_new(current_user.id, db), new_budget) + learning + review


def _finish(run, state):
    from app.study.models import StudySession
    from app.study.api_routes import _calculate_flashcard_xp
    from app.achievements.xp_service import award_xp
    from app.daily_plan.linear.xp import maybe_award_srs_global_xp
    session = StudySession.query.filter_by(id=run.session_id, user_id=current_user.id).one()
    if session.end_time is not None: raise NativeLessonError('srs_changed', 409)
    session.complete_session()
    state['complete'] = True
    xp = _calculate_flashcard_xp(session.words_studied or 0, session.correct_answers or 0)['total_xp']
    state['xp_earned'] = award_xp(current_user.id, xp, 'study_cards_session').xp_awarded if xp else 0
    db.session.flush()
    if _remaining() <= 0:
        award = maybe_award_srs_global_xp(current_user.id, db_session=db)
        if award is not None: state['xp_earned'] += award.xp_awarded
    # daily-status sweeps the perfect-day bonus after this transaction commits.


@api_native_srs.route('/srs/session', methods=['POST'])
@csrf.exempt
@api_bearer_required
@limiter.limit('30 per minute', key_func=get_authenticated_user_key)
def start_srs():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'request_id'} or not isinstance(data['request_id'], str):
        raise NativeLessonError('invalid_input')
    try: UUID(data['request_id'])
    except (ValueError, AttributeError): raise NativeLessonError('invalid_input')
    try:
        # Plan/settings assembly may commit: finish it before acquiring locks.
        guard_error = None
        try: _guard()
        except NativeLessonError as error: guard_error = error
        if guard_error is not None and guard_error.code == 'access_denied': raise guard_error
        day = _day()
        items = _pool() if guard_error is None else []
        _lock_user()
        run = _run()
        if run and run.study_day == day and run.state.get('lesson_id') is None:
            if (run.state['start_id'] == data['request_id'] and run.state['complete']) or (not run.state['complete'] and guard_error is None):
                return jsonify(_response(run))
        if guard_error: raise guard_error
        from app.study.models import PLAN_SRS_SESSION_TYPE, NativeSRSState, StudySession
        queue = _pack_pool(items)
        session = StudySession(user_id=current_user.id, session_type=PLAN_SRS_SESSION_TYPE, start_time=datetime.now(UTC))
        db.session.add(session); db.session.flush()
        if run is None:
            run = NativeSRSState(user_id=current_user.id)
            db.session.add(run)
        run.session_id, run.study_day = session.id, day
        state = {'start_id': data['request_id'], 'queue': queue, 'step': 0, 'reviewed': 0,
                 'remembered': 0, 'complete': False, 'xp_earned': 0, 'notice': None,
                 **_round_metadata(queue)}
        run.state = state
        if not queue: _finish(run, state)
        run.state, run.updated_at = state, datetime.now(UTC)
        flag_modified(run, 'state')
        db.session.commit()
        return jsonify(_response(run))
    except NativeLessonError:
        db.session.rollback(); raise
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Native SRS start failed user=%s', current_user.id)
        return jsonify(success=False, error='server_error'), 500


def _grade_card(head, rating, session_id):
    from app.study.models import UserWord, UserCardDirection, StudySession, StudySettings
    from app.srs.cards import ensure_card_directions
    from app.srs.constants import CardState, MAX_SESSION_ATTEMPTS, LEARNING_STEPS, RELEARNING_STEPS
    from app.srs.service import UnifiedSRSService
    from app.srs.counting import count_new_cards_today
    StudySettings.get_settings(current_user.id, lock_for_update=True)
    user_word = UserWord.get_or_create(current_user.id, head['word_id'])
    if user_word.srs_excluded: return None, 'Это слово исключено из повторения.'
    card = UserCardDirection.query.filter_by(user_word_id=user_word.id, direction=head['direction']).with_for_update().populate_existing().first()
    if _revision(card) != head['revision']:
        return None, 'Эта карточка уже изменилась на другом устройстве. Продолжаем со следующей.'
    if card is not None and card.is_buried:
        return None, 'Для этой карточки назначен отдых. Продолжаем.'
    if card is None or card.first_reviewed is None:
        from app.study.services import SRSService
        new_limit, _ = SRSService.get_adaptive_limits(current_user.id)
        if count_new_cards_today(current_user.id, db) >= new_limit:
            return None, 'Лимит новых карточек на сегодня достигнут.'
    if card is None:
        card = next(c for c in ensure_card_directions(user_word) if c.direction == head['direction'])
    before_state, before_step = card.state or CardState.NEW.value, card.step_index or 0
    card.update_after_review(rating, context='study', session_id=session_id)
    session = StudySession.query.filter_by(id=session_id, user_id=current_user.id).one()
    if session.end_time is not None: raise NativeLessonError('srs_changed', 409)
    session.words_studied += 1
    if rating >= 2: session.correct_answers += 1
    else: session.incorrect_answers += 1
    position = UnifiedSRSService.get_requeue_position(rating=rating, state=before_state, step_index=before_step)
    steps = LEARNING_STEPS if card.state == CardState.LEARNING.value else RELEARNING_STEPS
    if card.state in (CardState.LEARNING.value, CardState.RELEARNING.value) and card.step_index < len(steps) and steps[card.step_index] >= 60:
        position = None
    if card.session_attempts >= MAX_SESSION_ATTEMPTS:
        card.bury_for_session(session_duration_hours=4); position = None
    if card.is_buried: position = None
    from app.achievements.streak_service import earn_daily_coin
    earn_daily_coin(current_user.id)
    copy = {**head, 'state': card.state, 'revision': _revision(card)}
    return (copy, position), None


@api_native_srs.route('/srs/grade', methods=['POST'])
@csrf.exempt
@api_bearer_required
@limiter.limit('120 per minute', key_func=get_authenticated_user_key)
def grade_srs():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'session_id', 'step', 'rating'} or any(type(data[k]) is not int for k in data) or data['rating'] not in (1, 2, 3) or data['step'] < 0:
        raise NativeLessonError('invalid_input')
    try:
        guard_error = None
        try: _guard()
        except NativeLessonError as error: guard_error = error
        if guard_error is not None and guard_error.code == 'access_denied': raise guard_error
        day = _day()
        _lock_user()
        run = _run()
        if run is None or run.session_id != data['session_id'] or run.study_day != day or run.state.get('lesson_id') is not None:
            raise NativeLessonError('srs_changed', 409)
        state = deepcopy(run.state)
        if state.get('last_step') == data['step']:
            return jsonify(_with_audio_preference(state['last_response']))
        if guard_error: raise guard_error
        if state['step'] != data['step'] or state['complete'] or not state['queue']:
            raise NativeLessonError('srs_changed', 409)
        head = state['queue'].pop(0)
        result, notice = _grade_card(head, data['rating'], run.session_id)
        state['notice'] = notice
        if result is not None:
            card, position = result
            state['reviewed'] += 1
            state['remembered'] += int(data['rating'] >= 2)
            _record_rating(state, head, data['rating'])
            if position is not None:
                state['queue'].insert(max(0, min(position - 1, len(state['queue']))), card)
        state['step'] += 1
        if not state['queue']: _finish(run, state)
        run.state, run.updated_at = state, datetime.now(UTC)
        response = _response(run)
        state['last_step'], state['last_response'] = data['step'], response
        run.state = deepcopy(state)
        flag_modified(run, 'state')
        db.session.commit()
        return jsonify(response)
    except NativeLessonError:
        db.session.rollback(); raise
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Native SRS grade failed user=%s', current_user.id)
        return jsonify(success=False, error='server_error'), 500
