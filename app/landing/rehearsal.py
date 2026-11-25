"""Private, browser-local progress for the public rehearsal."""

from datetime import UTC, datetime, timedelta

from flask import Response, abort, after_this_request, current_app, make_response, render_template, request
from flask.blueprints import BlueprintSetupState
from flask_login import current_user, user_logged_in, user_logged_out
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.landing import landing_bp
from app.landing.rehearsal_content import published_rehearsal
from app.landing.rehearsal_intents import offer_intent, requests_larger
from app.public_copy import digest

_PATH = '/rehearsal/clothing/'
_COOKIE = 'llt_rehearsal_clothing'
_COOKIE_AGE = 30 * 24 * 3600
_DELAY = timedelta(days=3)


def _now() -> datetime:
    return datetime.now(UTC)


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt='rehearsal-clothing-v1')


def _owner() -> str:
    return f'user:{current_user.get_id()}' if current_user.is_authenticated else 'guest'


def _read_progress() -> dict:
    raw = request.cookies.get(_COOKIE, '')
    try:
        payload = _signer().loads(raw, max_age=_COOKIE_AGE)
        if payload['owner'] == _owner():
            return payload
    except (BadSignature, KeyError, TypeError):
        pass
    return {'owner': _owner(), 'finished': []}


def _clear_progress_on_auth(sender: object, **kwargs: object) -> None:
    @after_this_request
    def clear_cookie(response: Response) -> Response:
        response.delete_cookie(_COOKIE, path=_PATH)
        return response


@landing_bp.record_once
def _register_auth_boundary(state: BlueprintSetupState) -> None:
    user_logged_in.connect(_clear_progress_on_auth, sender=state.app, weak=False)
    user_logged_out.connect(_clear_progress_on_auth, sender=state.app, weak=False)


@landing_bp.route(_PATH, methods=['GET', 'POST'])
def clothing_rehearsal() -> Response:
    document, edition = published_rehearsal()
    if not document:
        abort(404)

    progress = _read_progress()
    if progress.get('edition') != edition:
        progress.update(edition=edition, stage='write', hint=False, misunderstood=False, asked_repeat=False,
                        seller_turn='offer')
    finished = progress['finished']
    now = _now()
    due = datetime.fromtimestamp(finished[0]['at'], UTC) + _DELAY if finished else None
    waiting = bool(len(finished) == 1 and now < due)
    complete = len(finished) >= 2
    round_name = 'shoes' if finished else 'jacket'
    scene = document[round_name]
    repeat = entry = seller = ''
    outcome = finished[-1]['outcome'] if finished else ''
    status = 200
    if request.method == 'POST':
        if waiting or complete or request.form.get('state') != digest(progress):
            status = 409
        else:
            action = request.form.get('action')
            reply = request.form.get('reply', '').strip()
            entry = reply[:240]
            if progress['stage'] == 'write' and action == 'hint':
                progress['hint'] = True
            elif progress['stage'] == 'write' and action == 'reply' and len(reply) <= 240:
                if offer_intent(entry) == 'repeat':
                    progress['asked_repeat'] = True
                    entry = ''
                elif requests_larger(entry, round_name, scene['accepted']):
                    progress['stage'] = 'choose'
                    entry = ''
                elif entry:
                    progress['misunderstood'] = True
                    repeat, seller = entry, scene['clarification']
                else:
                    status = 422
            elif progress['stage'] == 'choose':
                intent = action if action in ('accept', 'decline') else None
                if action == 'offer_reply' and 0 < len(reply) <= 240:
                    intent = offer_intent(entry)
                if intent in ('accept', 'decline', 'try'):
                    finished.append({'at': int(now.timestamp()), 'hint': progress['hint'],
                                     'misunderstood': progress['misunderstood'],
                                     'asked_repeat': progress['asked_repeat'], 'quick_choice': action != 'offer_reply',
                                     'outcome': intent, 'edition': edition})
                    seller = scene[f'{intent}_reply']
                    progress.update(stage='write', hint=False, misunderstood=False, asked_repeat=False,
                                    seller_turn='offer')
                    waiting, complete = len(finished) == 1, len(finished) == 2
                elif intent == 'repeat':
                    progress['asked_repeat'] = True
                    entry = ''
                elif intent in ('color', 'other_color'):
                    progress['seller_turn'] = f'{intent}_reply'
                    entry = ''
                elif action == 'offer_reply' and 0 < len(reply) <= 240:
                    progress['misunderstood'] = True
                    repeat, seller = entry, scene['clarification']
                else:
                    status = 422
            else:
                status = 422
    if not seller:
        if waiting or complete:
            if finished[-1]['edition'] == edition:
                finished_scene = document['shoes' if complete else 'jacket']
                seller = finished_scene[f'{outcome}_reply']
        else:
            seller = scene[progress['seller_turn']] if progress['stage'] == 'choose' else scene['opening']
    comparable = complete and finished[0]['edition'] == finished[1]['edition']
    response = make_response(render_template(
        'rehearsal/clothing.html', scene=scene, seller=seller, repeat=repeat, entry=entry, state=digest(progress),
        progress=progress, waiting=waiting, complete=complete, comparable=comparable, status=status,
    ), status)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Robots-Tag'] = 'noindex'
    if request.method == 'POST' and status == 200:
        response.set_cookie(_COOKIE, _signer().dumps(progress), max_age=_COOKIE_AGE, path=_PATH, httponly=True,
                            secure=current_app.config['SESSION_COOKIE_SECURE'], samesite='Lax')
    return response
