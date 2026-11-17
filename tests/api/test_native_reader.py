from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from test_native_full_integration import native_app, learner


def word(**values):
    now=datetime.now(timezone.utc).isoformat()
    value=dict(id=str(uuid4()),english='hooting',translation='уханье',lemma='hoot',sentence='A hooting noise.',book='Book',addedAt=now,dueAt=now,updatedAt=now,repetitions=0,intervalDays=0,revision=1,serverRevision=0,status='studying')
    value.update(values);return value


def sync(client,headers,changes,device,cursor=0):
    return client.post('/api/native/reader/words/sync',headers=headers,json=dict(changes=changes,device=device,cursor=cursor))


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    from app.modules.service import ModuleService
    monkeypatch.setattr(ModuleService,'is_module_enabled_for_user',lambda *a: True)


def test_sync_is_private_idempotent_and_account_isolated(native_app):
    from app.study.models import NativeReaderVocabulary,QuizDeckWord
    user,headers=learner(native_app);other,other_headers=learner(native_app);client=native_app.test_client();value=word();device=str(uuid4())
    for _ in range(2):
        response=sync(client,headers,[value],device)
        assert response.status_code==200,response.get_json()
        assert response.headers['Cache-Control']=='private, no-store'
        assert response.json['cursor']==1
        assert response.json['words'][0]['english']=='hooting'
        assert not any(k.startswith('_') for k in response.json['words'][0])
    assert sync(client,other_headers,[],str(uuid4())).json['words']==[]
    assert len(NativeReaderVocabulary.query.filter_by(user_id=user.id).one().payload['words'])==1
    assert sync(client,{},[value],device).status_code==401


def test_same_meaning_merges_contexts_but_distinct_senses_stay_separate(native_app):
    _,headers=learner(native_app);client=native_app.test_client();a=word();b=word(english='hooted',sentence='An owl hooted.')
    first=sync(client,headers,[a],str(uuid4())).json
    response=sync(client,headers,[b],str(uuid4()))
    assert response.status_code==200,response.get_json()
    assert response.json['aliases'][b['id']]==a['id']
    assert len(response.json['words'])==1
    assert len(response.json['words'][0]['contexts'])==2
    c=word(translation='насмешки')
    assert len(sync(client,headers,[c],str(uuid4())).json['words'])==2


def test_conflicting_meanings_and_delete_cannot_resurrect_stale_word(native_app):
    _,headers=learner(native_app);client=native_app.test_client();a=word();device=str(uuid4())
    first=sync(client,headers,[a],device).json
    b=deepcopy(first['words'][0]);b.update(translation='крики',revision=2)
    sync(client,headers,[b],str(uuid4()))
    stale=deepcopy(a);stale.update(translation='уханье совы',revision=3)
    conflict=sync(client,headers,[stale],device)
    assert conflict.status_code==200,conflict.json
    assert conflict.json['words'][0]['alternateMeanings']
    deleted=conflict.json['words'][0];deleted.update(deletedAt=a['updatedAt'],revision=4)
    result=sync(client,headers,[deleted],device)
    assert result.status_code==200,result.json
    stale['revision']=5
    result=sync(client,headers,[stale],str(uuid4()))
    assert result.json['words'][0].get('deletedAt')
    restored=result.json['words'][0];restored.pop('deletedAt');restored['revision']=6
    assert not sync(client,headers,[restored],device).json['words'][0].get('deletedAt')


def test_invalid_batch_rolls_back_and_cookie_cannot_replace_bearer(native_app):
    from app.study.models import NativeReaderVocabulary
    user,headers=learner(native_app);client=native_app.test_client();device=str(uuid4())
    for changes in [[word(revision=True)],[word(contexts=[])],[word(),word(english='')]]:
        response=sync(client,headers,changes,device)
        assert response.status_code==400,response.json
    assert NativeReaderVocabulary.query.filter_by(user_id=user.id).first() is None
    with client.session_transaction() as session: session['_user_id']=user.get_id();session['_fresh']=True
    assert sync(client,{},[],device).status_code==401
    assert client.post('/words/reading-vocabulary/'+str(uuid4()),data={'status':'known'}).status_code in [302,400]
    assert NativeReaderVocabulary.query.filter_by(user_id=user.id).first() is None


def test_mirroring_preserves_existing_srs_schedule_and_xp(native_app):
    from app.study.models import UserWord,UserCardDirection
    from app.achievements.models import UserStatistics
    from app.words.models import CollectionWords
    from app.utils.db import db
    from app.srs.cards import ensure_card_directions
    user,headers=learner(native_app);client=native_app.test_client()
    entry=CollectionWords(english_word='reader'+uuid4().hex,russian_word='слово',get_download=0)
    db.session.add(entry);db.session.flush()
    owned=UserWord.get_or_create(user.id,entry.id);db.session.flush();ensure_card_directions(owned)
    cards=UserCardDirection.query.filter_by(user_word_id=owned.id).all()
    for card in cards: card.state='review';card.interval=14;card.repetitions=8;card.first_reviewed=datetime.now(timezone.utc)
    stats=UserStatistics(user_id=user.id,total_xp=137,current_level=2);db.session.add(stats);db.session.commit()
    before={c.id:(c.interval,c.repetitions,c.state,c.first_reviewed) for c in cards}
    value=word(english=entry.english_word,lemma=entry.english_word)
    result=sync(client,headers,[value],str(uuid4()))
    assert result.status_code==200,result.json
    for card in cards:
        db.session.refresh(card);assert (card.interval,card.repetitions,card.state,card.first_reviewed)==before[card.id]
    db.session.refresh(stats);assert stats.total_xp==137
    assert result.json['words'][0]['serverWordID']==entry.id


def test_dictionary_snapshot_does_not_absorb_later_insertions(native_app):
    from app.words.models import CollectionWords
    from app.utils.db import db
    _,headers=learner(native_app);client=native_app.test_client()
    for i in range(502): db.session.add(CollectionWords(english_word='pack'+uuid4().hex,russian_word='слово',get_download=0))
    db.session.commit()
    first=client.get('/api/native/reader/dictionary',headers=headers)
    assert first.status_code==200,first.json
    assert first.json['more'] and len(first.json['entries'])==500
    late=CollectionWords(english_word='later'+uuid4().hex,russian_word='позже',get_download=0);db.session.add(late);db.session.commit()
    tail=client.get('/api/native/reader/dictionary',headers=headers,query_string={'after':first.json['cursor'],'until':first.json['until']})
    assert tail.status_code==200,tail.json
    assert not tail.json['more']
    assert late.id not in [e['id'] for e in tail.json['entries']]
    assert tail.headers['Cache-Control']=='private, no-store'


def test_web_collection_is_escaped_private_and_status_requires_csrf(native_app):
    from flask import g
    from app.utils.db import db
    user,headers=learner(native_app);client=native_app.test_client();value=word(translation='<script>alert(1)</script>')
    assert sync(client,headers,[value],str(uuid4())).status_code==200
    user.onboarding_completed=True;db.session.commit()
    with client.session_transaction() as session: session['_user_id']=user.get_id();session['_fresh']=True
    g.pop('_login_user',None)
    page=client.get('/words/reading-vocabulary')
    assert page.status_code==200,page.location
    assert b'&lt;script&gt;' in page.data and b'<script>alert(1)</script>' not in page.data
    from app.study.models import QuizDeckWord
    legacy = QuizDeckWord.query.filter_by(custom_english='hooting').order_by(QuizDeckWord.id.desc()).first()
    assert '<script>' not in legacy.custom_russian
    assert legacy.custom_sentences == value['sentence']
    assert page.headers['Cache-Control']=='private, no-store'
    response=client.post('/words/reading-vocabulary/'+value['id'],data={'status':'known'},headers={'Accept':'application/json'})
    assert response.status_code==400,response.location
    csrf=client.get('/csrf-token').json['csrf_token']
    response=client.post('/words/reading-vocabulary/'+value['id'],data={'status':'known','csrf_token':csrf})
    assert response.status_code==302,response.json
    synced=sync(client,headers,[],str(uuid4())).json
    assert synced['words'][0]['status']=='known'


def test_reader_migration_round_trip():
    from pathlib import Path
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import sqlalchemy as sa
    path=Path(__file__).parents[2]/'migrations/versions/20261117_reader_vocabulary.py'
    spec=importlib.util.spec_from_file_location('reader_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    engine=sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
        module.op=Operations(MigrationContext.configure(connection));module.upgrade()
        assert 'native_reader_vocabulary' in sa.inspect(connection).get_table_names()
        module.downgrade();assert 'native_reader_vocabulary' not in sa.inspect(connection).get_table_names()


def test_undo_removes_only_unreviewed_reader_provisioning(native_app):
    from app.words.models import CollectionWords
    from app.study.models import UserWord,UserCardDirection,QuizDeckWord
    from app.utils.db import db
    user,headers=learner(native_app);client=native_app.test_client();device=str(uuid4())
    entry=CollectionWords(english_word='undoreader'+uuid4().hex,russian_word='слово',get_download=0);db.session.add(entry);db.session.commit()
    a=word(english=entry.english_word,lemma=entry.english_word)
    reply=sync(client,headers,[a],device);assert reply.status_code==200,reply.json
    owned=UserWord.query.filter_by(user_id=user.id,word_id=entry.id).one()
    assert not owned.srs_excluded
    assert UserCardDirection.query.filter_by(user_word_id=owned.id).count()==2
    deleted=reply.json['words'][0];deleted.update(deletedAt=a['updatedAt'],revision=2)
    reply=sync(client,headers,[deleted],device);assert reply.status_code==200,reply.json
    db.session.refresh(owned);assert owned.srs_excluded
    assert QuizDeckWord.query.filter_by(custom_english=entry.english_word).count()==0
    restored=reply.json['words'][0];restored.pop('deletedAt');restored['revision']=3
    assert sync(client,headers,[restored],device).status_code==200
    db.session.refresh(owned);assert not owned.srs_excluded


def test_mirror_failure_rolls_back_entire_private_collection(native_app,monkeypatch):
    import app.api.native_reader as reader
    from app.study.models import NativeReaderVocabulary,QuizDeck
    user,headers=learner(native_app);client=native_app.test_client()
    original=reader._mirror
    def fail(*args):
        original(*args)
        raise RuntimeError('Disposable mirror failure')
    monkeypatch.setattr(reader,'_mirror',fail)
    reply=sync(client,headers,[word()],str(uuid4()))
    assert reply.status_code==500,reply.json
    assert NativeReaderVocabulary.query.filter_by(user_id=user.id).count()==0
    assert QuizDeck.query.filter_by(user_id=user.id).count()==0


def test_same_device_can_undo_before_delete_acknowledgement_arrives(native_app):
    _,headers=learner(native_app);client=native_app.test_client();device=str(uuid4());a=word()
    first=sync(client,headers,[a],device).json['words'][0]
    removed=deepcopy(first);removed.update(revision=2,deletedAt=a['updatedAt'])
    assert sync(client,headers,[removed],device).status_code==200
    # The device still knows the older server revision when the user taps Undo.
    restored=deepcopy(first);restored['revision']=3
    reply=sync(client,headers,[restored],device)
    assert reply.status_code==200,reply.json
    assert not reply.json['words'][0].get('deletedAt')
