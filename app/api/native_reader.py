"""Reader dictionary and private offline-first vocabulary. No client-awarded XP."""
import copy
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from uuid import UUID

from flask import Blueprint, jsonify, request, render_template, redirect, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app import csrf, limiter
from app.api.decorators import api_bearer_required
from app.api.native_lessons import NativeLessonError, native_error, private_response
from app.utils.db import db
from app.utils.rate_limit_helpers import get_authenticated_user_key

api_native_reader = Blueprint('api_native_reader', __name__)
api_native_reader.after_request(private_response)
api_native_reader.register_error_handler(NativeLessonError, native_error)
reader_words = Blueprint('reader_words', __name__)
reader_words.after_request(private_response)


def _key(text):
    return ' '.join(unicodedata.normalize('NFKC', text).lower().replace('’', "'").split())


def _text(value, limit, required=True):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        raise NativeLessonError('invalid_input')
    value = value.strip()
    if required and not value:
        raise NativeLessonError('invalid_input')
    return value


def _integer(value, low=0, high=2147483647):
    if type(value) is not int or not low <= value <= high:
        raise NativeLessonError('invalid_input')
    return value


def _uuid(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise NativeLessonError('invalid_input')


def _date(value, optional=False):
    if value is None and optional:
        return None
    try:
        date = datetime.fromisoformat(_text(value, 64).replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError()
        date = date.astimezone(timezone.utc)
        if date > datetime.now(timezone.utc) + timedelta(days=370):
            raise ValueError()
        return date.isoformat(timespec='seconds').replace('+00:00', 'Z')
    except (ValueError, OverflowError):
        raise NativeLessonError('invalid_input')


def _context(context):
    if not isinstance(context, dict) or not isinstance(context.get('location'), dict):
        raise NativeLessonError('invalid_input')
    location = context['location']
    if set(location) - {'bookID', 'localID', 'title', 'chapter', 'paragraph'}:
        raise NativeLessonError('invalid_input')
    clean = {'title': _text(location.get('title', ''), 300, False)}
    for field in ['bookID', 'chapter', 'paragraph']:
        if location.get(field) is not None:
            clean[field] = _integer(location[field], 0 if field == 'paragraph' else 1)
    # Imported file identities belong to this account, not a server book.
    if location.get('localID') is not None:
        clean['localID'] = _text(location['localID'], 200)
    if clean.get('bookID') is not None:
        from app.books.models import Book
        book = db.session.get(Book, clean['bookID'])
        # Keep only an accessible book identity; saving a user supplied excerpt
        # never grants access to a private or licensed book.
        if book is None or not book.is_published or book.rights_status != 'public_domain':
            clean.pop('bookID')
    result = {'sentence': _text(context.get('sentence'), 1200), 'location': clean,
              'date': _date(context.get('date'))}
    if context.get('translation') is not None:
        result['translation'] = _text(context['translation'], 2400, False)
    return result


def _word(raw):
    if not isinstance(raw, dict):
        raise NativeLessonError('invalid_input')
    english = _text(raw.get('english'), 400)
    if not re.search('[A-Za-z]', english):
        raise NativeLessonError('invalid_input')
    value = {'id': _uuid(raw.get('id')), 'english': english,
             'translation': _text(raw.get('translation'), 400),
             'sentence': _text(raw.get('sentence'), 1200),
             'book': _text(raw.get('book', ''), 300, False),
             'lemma': _key(_text(raw.get('lemma') or english, 400)),
             'addedAt': _date(raw.get('addedAt')), 'dueAt': _date(raw.get('dueAt')),
             'repetitions': _integer(raw.get('repetitions', 0), high=1000000),
             'intervalDays': _integer(raw.get('intervalDays', 0), high=3650),
             'revision': _integer(0 if raw.get('revision') is None else raw['revision']),
             'serverRevision': _integer(0 if raw.get('serverRevision') is None else raw['serverRevision']),
             'status': raw.get('status') or 'studying',
             'updatedAt': _date(raw.get('updatedAt') or raw.get('addedAt'))}
    if value['status'] not in ['studying', 'known']:
        raise NativeLessonError('invalid_input')
    if raw.get('deletedAt') is not None:
        value['deletedAt'] = _date(raw['deletedAt'])
    contexts = raw.get('contexts')
    if contexts is None:
        contexts = [{'sentence': value['sentence'], 'location': {'title': value['book']}, 'date': value['addedAt']}]
    if not isinstance(contexts, list) or not 1 <= len(contexts) <= 30:
        raise NativeLessonError('invalid_input')
    value['contexts'] = [_context(c) for c in contexts]
    variants = raw.get('alternateMeanings') or []
    if not isinstance(variants, list) or len(variants) > 8:
        raise NativeLessonError('invalid_input')
    value['alternateMeanings'] = [_text(v, 400) for v in variants]
    return value


def _semantic(word):
    return hashlib.sha256((_key(word['lemma']) + '\n' + _key(word['translation'])).encode()).hexdigest()


def _public(word):
    return {key: value for key, value in word.items() if not key.startswith('_')}


def _state():
    from app.api.native_srs import _lock_user
    from app.study.models import NativeReaderVocabulary
    _lock_user()
    state = db.session.get(NativeReaderVocabulary, current_user.id)
    if state is None:
        state = NativeReaderVocabulary(user_id=current_user.id, payload={'words': {}}, version=0)
        db.session.add(state)
        db.session.flush()
    return state


def _mirror(state, payload, word):
    from app.study.models import QuizDeck, QuizDeckWord, UserWord, UserCardDirection
    from app.words.models import CollectionWords
    entry = db.session.get(QuizDeckWord, word.get('_deckWord')) if word.get('_deckWord') else None
    if entry is not None and entry.deck.user_id != current_user.id:
        entry = None
    if word.get('deletedAt') or word['status'] == 'known':
        if entry is not None:
            db.session.delete(entry)
            word.pop('_deckWord', None)
        # Undo may exclude only a newly provisioned, never-reviewed reader word.
        if word.get('_createdOwned') and word.get('serverWordID'):
            other_active = any(w['id'] != word['id'] and not w.get('deletedAt') and w.get('status') == 'studying'
                               and w.get('serverWordID') == word['serverWordID'] for w in payload['words'].values())
            owned = UserWord.query.filter_by(user_id=current_user.id, word_id=word['serverWordID']).first()
            if owned and not other_active:
                reviewed = UserCardDirection.query.filter(UserCardDirection.user_word_id == owned.id,
                                                          UserCardDirection.first_reviewed.isnot(None)).first()
                if reviewed is None:
                    owned.srs_excluded = True
        return
    dictionary = CollectionWords.query.filter(func.lower(CollectionWords.english_word) == word['lemma']).first()
    if dictionary is not None:
        from app.srs.cards import ensure_card_directions
        from app.study.deck_utils import ensure_word_in_default_deck
        owned = UserWord.query.filter_by(user_id=current_user.id, word_id=dictionary.id).first()
        if owned is None:
            word['_createdOwned'] = True
        owned = UserWord.get_or_create(current_user.id, dictionary.id)
        owned.srs_excluded = False
        db.session.flush()
        ensure_card_directions(owned, source='book_reading')
        ensure_word_in_default_deck(current_user.id, dictionary.id, owned.id)
        word['serverWordID'] = dictionary.id
    # The legacy deck stores sanitized plain text in shorter fields. Keep the
    # full original meaning and contexts in the private reader collection.
    import bleach
    english = bleach.clean(word['english'],tags=[],strip=True)
    meaning = bleach.clean(word['translation'],tags=[],strip=True)
    if not english or not meaning or len(english) > 200 or len(meaning) > 200:
        return
    deck = db.session.get(QuizDeck, payload.get('deck')) if payload.get('deck') else None
    if deck is None or deck.user_id != current_user.id:
        deck = QuizDeck(user_id=current_user.id, title='Слова из книг', description='Личные слова и контексты из читалки LLT', is_public=False)
        db.session.add(deck); db.session.flush(); payload['deck'] = deck.id
    if entry is None:
        entry = QuizDeckWord(deck_id=deck.id, custom_english=english, custom_russian=meaning, order_index=0)
        db.session.add(entry); db.session.flush(); word['_deckWord'] = entry.id
    entry.custom_english = english; entry.custom_russian = meaning
    entry.custom_sentences = bleach.clean('\n\n'.join(c['sentence'] + ('\n' + c['translation'] if c.get('translation') else '') for c in word['contexts']),tags=[],strip=True)


def _merge(state, payload, incoming, device):
    words = payload['words']
    target = words.get(incoming['id'])
    if target is None and not incoming.get('deletedAt'):
        target = next((w for w in words.values() if not w.get('deletedAt') and _semantic(w) == _semantic(incoming)), None)
    if target is None:
        if len(words) >= 4000:
            raise NativeLessonError('invalid_input', 422)
        target = copy.deepcopy(incoming); target['_receipts'] = {}
        words[target['id']] = target
    receipts = target.setdefault('_receipts', {})
    if receipts.get(device, -1) >= incoming['revision']:
        return target, False
    existing_revision = target.get('serverRevision', 0)
    stale = incoming['serverRevision'] < existing_revision
    contexts = target.get('contexts', []) + incoming['contexts']
    unique = {}
    for context in contexts:
        key = json.dumps([context['sentence'], context['location']], sort_keys=True, ensure_ascii=False)
        unique[key] = context
    private = {k: v for k, v in target.items() if k.startswith('_')}
    identifier = target['id']
    prior = copy.deepcopy(target)
    if not stale or incoming['updatedAt'] >= target['updatedAt']:
        target.update(incoming)
    target['id'] = identifier
    target.update(private)
    target['contexts'] = sorted(unique.values(), key=lambda c: c['date'])[-30:]
    if stale:
        variants = set(prior.get('alternateMeanings', []) + incoming.get('alternateMeanings', []))
        if _key(prior['translation']) != _key(incoming['translation']):
            variants.update([prior['translation'], incoming['translation']])
        target['alternateMeanings'] = sorted(v for v in variants if v != target['translation'])[:8]
        if prior.get('deletedAt'):
            if prior.get('_deletedBy') == device and not incoming.get('deletedAt'):
                target.pop('deletedAt',None)
            else:
                target['deletedAt'] = prior['deletedAt']
    elif not incoming.get('deletedAt'):
        target.pop('deletedAt', None)
    if incoming.get('deletedAt'):
        target['deletedAt'] = incoming['deletedAt']
        target['_deletedBy'] = device
    elif not target.get('deletedAt'):
        target.pop('_deletedBy',None)
    receipts[device] = incoming['revision']
    # Keep replay receipts bounded per word. Reject excessive device churn rather than losing receipts.
    if len(receipts) > 100:
        raise NativeLessonError('invalid_input', 422)
    state.version += 1
    target['serverRevision'] = state.version
    _mirror(state, payload, target)
    return target, True


@api_native_reader.post('/reader/words/sync')
@csrf.exempt
@api_bearer_required
@limiter.limit('120 per minute', key_func=get_authenticated_user_key)
def sync_reader_words():
    from app.modules.service import ModuleService
    if not ModuleService.is_module_enabled_for_user(current_user.id, 'study'):
        raise NativeLessonError('access_denied', 403)
    if request.content_length is not None and request.content_length > 1000000:
        raise NativeLessonError('invalid_input', 413)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) - {'changes', 'cursor', 'device'}:
        raise NativeLessonError('invalid_input')
    changes = body.get('changes')
    if not isinstance(changes, list) or len(changes) > 100:
        raise NativeLessonError('invalid_input')
    cursor = _integer(0 if body.get('cursor') is None else body['cursor'])
    device = _uuid(body.get('device'))
    clean = [_word(w) for w in changes]
    try:
        state = _state(); payload = copy.deepcopy(state.payload)
        accepted = {}; aliases = {}; touched = set()
        for incoming in clean:
            word, _ = _merge(state, payload, incoming, device)
            accepted[incoming['id']] = incoming['revision']; touched.add(word['id'])
            if word['id'] != incoming['id']:
                aliases[incoming['id']] = word['id']
        if len(json.dumps(payload, ensure_ascii=False).encode()) > 15000000:
            raise NativeLessonError('invalid_input', 422)
        state.payload = payload; state.updated_at = datetime.now(timezone.utc)
        response = [_public(word) for word in payload['words'].values()
                    if word.get('serverRevision', 0) > cursor or word['id'] in touched]
        db.session.commit()
        return jsonify(words=response, accepted=accepted, cursor=state.version, aliases=aliases)
    except NativeLessonError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        from flask import current_app
        current_app.logger.exception('Reader vocabulary transaction failed')
        return jsonify(success=False,error='server_error'),500


@api_native_reader.get('/reader/dictionary')
@api_bearer_required
@limiter.limit('120 per minute', key_func=get_authenticated_user_key)
def reader_dictionary():
    from app.words.models import CollectionWords
    try:
        after = int(request.args.get('after', '0')); until = int(request.args.get('until', '0'))
    except ValueError:
        raise NativeLessonError('invalid_input')
    _integer(after); _integer(until)
    maximum = db.session.query(func.max(CollectionWords.id)).scalar() or 0
    until = until or maximum
    if after > until:
        raise NativeLessonError('invalid_input')
    rows = CollectionWords.query.filter(CollectionWords.id > after, CollectionWords.id <= until,
        CollectionWords.russian_word.isnot(None), func.length(func.trim(CollectionWords.russian_word)) > 0).order_by(CollectionWords.id).limit(501).all()
    more = len(rows) > 500; rows = rows[:500]
    cursor = rows[-1].id if more else until
    return jsonify(entries=[{'id':w.id, 'english':w.english_word, 'translation':w.russian_word, 'audio':None} for w in rows], cursor=cursor, until=until, more=more)


@reader_words.get('/reading-vocabulary')
@login_required
def collection():
    from app.study.models import NativeReaderVocabulary
    state = db.session.get(NativeReaderVocabulary, current_user.id)
    words = [] if state is None else [_public(w) for w in state.payload.get('words', {}).values() if not w.get('deletedAt')]
    return render_template('words/reader_vocabulary.html', words=sorted(words, key=lambda w:w['addedAt'], reverse=True))


@reader_words.post('/reading-vocabulary/<word_id>')
@login_required
def update_word(word_id):
    word_id = _uuid(word_id)
    status = request.form.get('status')
    if status not in ['studying', 'known', 'remove']:
        raise NativeLessonError('invalid_input')
    try:
        state = _state(); payload = copy.deepcopy(state.payload)
        word = payload['words'].get(word_id)
        if word is None:
            raise NativeLessonError('not_found', 404)
        if status == 'remove':
            word['deletedAt'] = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
            word['_deletedBy'] = 'web'
        else:
            word['status'] = status;word.pop('deletedAt', None);word.pop('_deletedBy', None)
        state.version += 1;word['serverRevision'] = state.version
        word['updatedAt'] = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        _mirror(state,payload,word);state.payload = payload;db.session.commit()
    except Exception:
        db.session.rollback();raise
    return redirect(url_for('reader_words.collection'))
