"""JWT/CSRF + real SQLite transaction tests for native session protocol."""
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from flask_login import LoginManager, UserMixin
from sqlalchemy import Column, Integer, String, DateTime, JSON, create_engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

Base = declarative_base()
class Account(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    xp = Column(Integer, default=0)
class Run(Base):
    __tablename__ = 'native_srs_state'
    user_id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False)
    study_day = Column(String(10), nullable=False)
    state = Column(JSON, nullable=False)
    updated_at = Column(DateTime)
class Session(Base):
    __tablename__ = 'study_sessions'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    session_type = Column(String(20))
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    words_studied = Column(Integer, default=0)
    correct_answers = Column(Integer, default=0)
    incorrect_answers = Column(Integer, default=0)
    def complete_session(self): self.end_time = datetime.now()
class Learner(UserMixin):
    id = 7
    active = True
    @property
    def is_active(self): return self.active
    def has_auth_version(self, value): return value == 1

@pytest.fixture
def context(monkeypatch):
    from app import csrf
    from app.api import native_srs as native, decorators
    import app.auth.models as auth
    import app.study.models as models
    from app.achievements import xp_service
    import app.daily_plan.linear.xp as linear
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    session = scoped_session(sessionmaker(bind=engine))
    for cls in (Account, Run, Session): cls.query = session.query_property()
    session.add(Account(id=7)); session.commit()
    monkeypatch.setattr(native, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr(auth,'User',Account)
    monkeypatch.setattr(models,'StudySession',Session)
    monkeypatch.setattr(models,'NativeSRSState',Run,raising=False)
    guard_function=native._guard
    monkeypatch.setattr(native,'_guard',lambda:None)
    monkeypatch.setattr(native,'_day',lambda:'2026-11-16')
    monkeypatch.setattr(native,'_remaining',lambda:0)
    monkeypatch.setattr(native,'_pool',lambda:[{'word_id':1,'direction':'eng-rus','front':'book','back':'книга','examples':'A book.','state':'review','revision':'v1'}])
    monkeypatch.setattr(native,'_pack_pool',lambda items:items)
    def award(uid, amount, source):
        account = session.get(Account,uid); account.xp += amount
        return SimpleNamespace(xp_awarded=amount)
    monkeypatch.setattr(xp_service,'award_xp',award)
    monkeypatch.setattr(linear,'maybe_award_srs_global_xp',lambda *a,**k:None)
    grade_function=native._grade_card
    grades=[]
    def grade(head,rating,sid):
        grades.append((head['word_id'],rating,sid))
        study=session.get(Session,sid);study.words_studied+=1
        if rating>=2:study.correct_answers+=1
        else:study.incorrect_answers+=1
        return (head, 2 if rating==1 else None),None
    monkeypatch.setattr(native,'_grade_card',grade)
    app=Flask(__name__)
    app.config.update(TESTING=True,SECRET_KEY='srs-session-test-only',JWT_SECRET_KEY='srs-jwt-signing-test-only-at-least32',WTF_CSRF_ENABLED=True,RATELIMIT_ENABLED=False)
    csrf.init_app(app);JWTManager(app)
    learner=Learner();login=LoginManager(app);login.user_loader(lambda key:learner if key=='7' else None)
    monkeypatch.setattr(decorators,'db_get_user',lambda uid:learner if uid==7 else None)
    app.register_blueprint(native.api_native_srs,url_prefix='/api/native')
    with app.app_context():token=create_access_token(identity='7',additional_claims={'auth_version':1})
    c=SimpleNamespace(app=app,client=app.test_client(),headers={'Authorization':'Bearer '+token},native=native,db=session,grades=grades,learner=learner,grade_function=grade_function,guard_function=guard_function)
    yield c
    session.remove();engine.dispose()

def start(c, request_id=None):
    return c.client.post('/api/native/srs/session',headers=c.headers,json={'request_id':request_id or str(uuid4())})
def grade(c,run,rating=3,**extra):
    return c.client.post('/api/native/srs/grade',headers=c.headers,json={'session_id':run['session_id'],'step':run['step'],'rating':rating,**extra})

def test_start_resume_and_no_internal_revision(context):
    c=context;one=start(c);two=start(c)
    assert one.status_code==two.status_code==200
    assert one.json==two.json
    assert 'revision' not in one.json['card']
    assert c.db.query(Session).count()==1
    assert one.headers['Cache-Control']=='private, no-store'
    assert 'Set-Cookie' not in one.headers

def test_grade_and_xp_commit_once_with_receipt(context):
    c=context;run=start(c).json
    first=grade(c,run);second=grade(c,run,rating=1)
    assert first.status_code==second.status_code==200
    assert first.json==second.json
    assert first.json['complete'] and first.json['reviewed']==1
    assert c.db.get(Account,7).xp==20
    assert len(c.grades)==1
    assert c.db.get(Session,run['session_id']).words_studied==1
    # A retry still works after completing this plan step elsewhere.
    c.native._guard=lambda:(_ for _ in ()).throw(c.native.NativeLessonError('lesson_locked',403))
    assert grade(c,run).json==first.json

def test_start_idempotency_after_completion(context):
    c=context;rid=str(uuid4());run=start(c,rid).json
    assert grade(c,run).status_code==200
    resumed=start(c,rid).json
    assert resumed['complete']
    assert c.db.query(Session).count()==1

def test_miss_requeues_and_keeps_server_step(context):
    c=context;run=start(c).json
    nxt=grade(c,run,1).json
    assert not nxt['complete'] and nxt['step']==1 and nxt['remaining']==1
    assert nxt['card']['front']=='book'
    assert grade(c,nxt,3).json['complete']
    assert c.db.get(Account,7).xp==25

def test_failure_rolls_back_counter_xp_and_queue(context,monkeypatch):
    c=context;run=start(c).json
    original=c.native._finish
    def fail(row,state):
        original(row,state)
        raise RuntimeError('storage unavailable')
    monkeypatch.setattr(c.native,'_finish',fail)
    response=grade(c,run)
    assert response.status_code==500
    c.db.expire_all()
    assert c.db.get(Account,7).xp==0
    assert c.db.get(Session,run['session_id']).words_studied==0
    assert c.db.get(Run,7).state['step']==0
    monkeypatch.setattr(c.native,'_finish',original)
    assert grade(c,run).json['complete']

@pytest.mark.parametrize('extra',[{'rating':True},{'rating':0},{'rating':4},{'step':True},{'score':100},{'session_id':999}])
def test_invalid_or_foreign_input_cannot_grade(context,extra):
    c=context;run=start(c).json
    response=grade(c,run,**({'rating':extra.pop('rating')} if 'rating' in extra else {}),**extra)
    assert response.status_code in (400,409)
    assert not c.grades

@pytest.mark.parametrize('route,body',[('/srs/session',{'request_id':str(uuid4())}),('/srs/grade',{'session_id':1,'step':0,'rating':3})])
def test_cookie_never_authorizes_csrf_exempt_routes(context,route,body):
    c=context
    with c.client.session_transaction() as value:value['_user_id']='7'
    assert c.client.post('/api/native'+route,json=body).status_code==401
    assert c.client.post('/api/native'+route,headers={'Authorization':'Bearer invalid'},json=body).status_code==401
    assert c.db.query(Session).count()==0

def test_day_change_rejects_old_run(context,monkeypatch):
    c=context;run=start(c).json
    monkeypatch.setattr(c.native,'_day',lambda:'2026-11-17')
    assert grade(c,run).status_code==409
    assert not c.grades
    assert start(c).json['session_id']!=run['session_id']

@pytest.mark.parametrize('code,status',[('plan_paused',403),('lesson_locked',403),('access_denied',403)])
def test_plan_and_module_guards(context,monkeypatch,code,status):
    c=context
    monkeypatch.setattr(c.native,'_guard',lambda:(_ for _ in ()).throw(c.native.NativeLessonError(code,status)))
    assert start(c).status_code==status
    assert not c.grades

def test_revoked_and_inactive_account(context):
    c=context
    c.learner.active=False
    assert start(c).status_code==403
    c.learner.active=True
    with c.app.app_context():token=create_access_token(identity='7',additional_claims={'auth_version':0})
    c.headers={'Authorization':'Bearer '+token}
    assert start(c).status_code==401


def test_srs_slot_xp_waits_for_remaining_pool(context,monkeypatch):
    c=context
    import app.daily_plan.linear.xp as linear
    calls=[]
    monkeypatch.setattr(linear,'maybe_award_srs_global_xp',lambda *a,**k:calls.append(True))
    monkeypatch.setattr(c.native,'_remaining',lambda:4)
    run=start(c).json
    assert grade(c,run).json['complete']
    assert calls==[]


@pytest.mark.parametrize('state,rating,attempts,excluded,stale,new_cap',[
    ('new',1,0,False,False,False),('new',3,0,False,False,False),
    ('learning',1,2,False,False,False),('review',3,0,False,False,False),
    ('new',3,0,False,False,True),('review',3,0,True,False,False),('review',3,0,False,True,False),
])
def test_native_grading_uses_canonical_state_machine_and_limits(context,monkeypatch,state,rating,attempts,excluded,stale,new_cap):
    from unittest.mock import Mock
    from flask import g
    import app.study.models as models
    import app.srs.cards as cards
    import app.srs.counting as counting
    import app.achievements.streak_service as streak
    from app.study.services import SRSService
    from app.srs.service import UnifiedSRSService
    c=context;run=start(c).json
    uw=SimpleNamespace(id=10,srs_excluded=excluded)
    card=SimpleNamespace(first_reviewed=None if state=='new' else datetime(2026,11,15),
        last_reviewed=datetime(2026,11,15),state=state,step_index=0,repetitions=2,interval=2,
        ease_factor=2.5,lapses=0,correct_count=0,incorrect_count=0,session_attempts=attempts,is_buried=False)
    calls=[]
    def update(value,**kwargs):
        calls.append((value,kwargs))
        result=UnifiedSRSService.calculate_sm2_update(rating=value,state=card.state,step_index=card.step_index,
            repetitions=card.repetitions,interval=card.interval,ease_factor=card.ease_factor,lapses=card.lapses)
        for key in ('state','step_index','repetitions','interval','ease_factor','lapses'):setattr(card,key,result[key])
        card.first_reviewed=datetime.now();card.last_reviewed=datetime.now();card.session_attempts+=1
    card.update_after_review=update
    def bury(**kwargs):card.is_buried=True
    card.bury_for_session=bury
    query=Mock();query.filter_by.return_value.with_for_update.return_value.populate_existing.return_value.first.return_value=card
    monkeypatch.setattr(models,'UserCardDirection',SimpleNamespace(query=query))
    monkeypatch.setattr(models.UserWord,'get_or_create',lambda *a:uw)
    monkeypatch.setattr(models.StudySettings,'get_settings',lambda *a,**k:None)
    monkeypatch.setattr(SRSService,'get_adaptive_limits',lambda *a:(0 if new_cap else 100,100))
    monkeypatch.setattr(counting,'count_new_cards_today',lambda *a:0)
    coins=[];monkeypatch.setattr(streak,'earn_daily_coin',lambda *a:coins.append(True))
    head={'word_id':1,'direction':'eng-rus','revision':c.native._revision(card)}
    if stale:head['revision']='other-device'
    with c.app.test_request_context():
        g._login_user=c.learner
        result,notice=c.grade_function(head,rating,run['session_id'])
    if excluded or stale or new_cap:
        assert result is None and notice and not calls and not coins
        assert c.db.get(Session,run['session_id']).words_studied==0
    else:
        assert calls==[(rating,{'context':'study','session_id':run['session_id']})]
        assert c.db.get(Session,run['session_id']).words_studied==1
        assert coins==[True]
        assert result[0]['state']==card.state
        if attempts==2:assert card.is_buried and result[1] is None
        elif state=='new' and rating==1:assert result[1] is not None
        elif state=='review':assert result[1] is None


def test_migration_roundtrip_and_foreign_keys():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import inspect, MetaData, Table, ForeignKey
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).parents[2]/'migrations/versions/20261116_native_srs_state.py'
    spec=importlib.util.spec_from_file_location('native_srs_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine('sqlite://')
    metadata=MetaData()
    Table('users',metadata,Column('id',Integer,primary_key=True))
    Table('study_sessions',metadata,Column('id',Integer,primary_key=True))
    with engine.begin() as connection:
        metadata.create_all(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            schema=inspect(connection)
            assert schema.get_pk_constraint('native_srs_state')['constrained_columns']==['user_id']
            assert {fk['referred_table'] for fk in schema.get_foreign_keys('native_srs_state')}=={'users','study_sessions'}
            migration.downgrade()
            assert 'native_srs_state' not in inspect(connection).get_table_names()
    engine.dispose()


@pytest.mark.parametrize('required,paused,enabled,allowed',[
    ([{'id':'srs','kind':'srs'}],False,True,True),
    ([{'id':'read','kind':'reading'},{'id':'srs','kind':'srs'}],False,True,False),
    ([{'id':'srs','kind':'srs','skipped':True},{'id':'read','kind':'reading'}],False,True,True),
    ([{'id':'srs','kind':'srs','blocked':True}],False,True,False),
    ([{'id':'srs','kind':'srs'}],True,True,False),
    ([{'id':'srs','kind':'srs'}],False,False,False),
])
def test_real_plan_guard_uses_order_pause_and_module(context,monkeypatch,required,paused,enabled,allowed):
    from flask import g
    from app.modules.service import ModuleService
    import app.daily_plan.service as service
    import app.achievements.streak_service as streak
    import app.telegram.queries as summary
    import app.utils.time_utils as times
    c=context
    monkeypatch.setattr(ModuleService,'is_module_enabled_for_user',lambda *a:enabled)
    monkeypatch.setattr(service,'get_daily_plan_unified',lambda *a,**k:{'mode':'paused' if paused else 'unified','required':required,'optional':[]})
    monkeypatch.setattr(streak,'compute_plan_steps',lambda *a:({},0,0))
    monkeypatch.setattr(summary,'get_daily_summary',lambda *a,**k:{})
    monkeypatch.setattr(times,'get_user_timezone_name',lambda *a:'UTC')
    with c.app.test_request_context():
        g._login_user=c.learner
        if allowed:c.guard_function()
        else:
            with pytest.raises(c.native.NativeLessonError):c.guard_function()


def test_empty_pool_persists_a_completed_receipt_without_session_xp(context,monkeypatch):
    c=context
    monkeypatch.setattr(c.native,'_pool',lambda:[])
    request_id=str(uuid4())
    response=start(c,request_id)
    assert response.status_code==200 and response.json['complete']
    c.db.expire_all()
    assert c.db.get(Run,7).state['complete']
    assert c.db.get(Account,7).xp==0
    assert start(c,request_id).json==response.json
