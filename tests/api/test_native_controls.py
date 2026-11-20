from datetime import datetime, timedelta, UTC
from uuid import uuid4
import pytest
from tests.api.test_native_full_integration import native_app, learner


def make_word():
    from app.words.models import CollectionWords
    from app.utils.db import db
    word = CollectionWords(english_word='native '+uuid4().hex[:10],russian_word='проверка',get_download=0,sentences='[{"en":"A local example.","ru":"Пример."}]')
    db.session.add(word);db.session.commit()
    return word


def allow_study(monkeypatch):
    from app.modules.service import ModuleService
    monkeypatch.setattr(ModuleService,'is_module_enabled_for_user',lambda *a: True)


def test_enrollment_creates_both_directions_once_without_reviews_or_xp(native_app,monkeypatch):
    from app.study.models import UserWord,UserCardDirection,QuizDeckWord
    from app.achievements.models import UserStatistics
    from app.utils.db import db
    allow_study(monkeypatch);user,headers=learner(native_app);word=make_word();client=native_app.test_client()
    statistics=UserStatistics(user_id=user.id,total_xp=137,current_level=2)
    db.session.add(statistics);db.session.commit()
    for _ in range(2):
        response=client.post(f'/api/native/vocabulary/{word.id}/study',headers=headers,json={})
        assert response.status_code==200,response.get_json()
        assert response.get_json()==dict(success=True,word_id=word.id,in_study=True)
        assert response.headers['Cache-Control']=='private, no-store'
    owned=UserWord.query.filter_by(user_id=user.id,word_id=word.id).one()
    cards=UserCardDirection.query.filter_by(user_word_id=owned.id).all()
    assert len(cards)==2
    assert all(c.first_reviewed is None and c.state=='new' for c in cards)
    assert not owned.srs_excluded
    db.session.refresh(statistics);assert statistics.total_xp==137
    assert QuizDeckWord.query.filter_by(word_id=word.id,user_word_id=owned.id).count()==1
    response=client.get(f'/api/native/vocabulary/{word.id}',headers=headers)
    assert response.status_code==200,response.get_json()
    assert response.get_json()['in_study'] is True
    assert response.get_json()['english_word']==word.english_word


def test_enrollment_preserves_existing_schedule_and_ownership(native_app,monkeypatch):
    from app.study.models import UserWord,UserCardDirection
    from app.utils.db import db
    from app.srs.cards import ensure_card_directions
    allow_study(monkeypatch);user,headers=learner(native_app);other,_=learner(native_app);word=make_word();client=native_app.test_client()
    owned=UserWord.get_or_create(user.id,word.id);db.session.flush();ensure_card_directions(owned)
    cards=UserCardDirection.query.filter_by(user_word_id=owned.id).all()
    for c in cards:
        c.state='review';c.interval=14;c.repetitions=5;c.first_reviewed=datetime.now(UTC)-timedelta(days=40);c.next_review=datetime.now(UTC)+timedelta(days=14)
    owned.srs_excluded=True;db.session.commit()
    before={c.id:(c.interval,c.repetitions,c.first_reviewed,c.next_review,c.state) for c in cards}
    response=client.post(f'/api/native/vocabulary/{word.id}/study',headers=headers,json={})
    assert response.status_code==200,response.get_json()
    for c in cards:
        db.session.refresh(c);assert (c.interval,c.repetitions,c.first_reviewed,c.next_review,c.state)==before[c.id]
    assert UserWord.query.filter_by(user_id=other.id,word_id=word.id).count()==0


def test_enrollment_rejects_disabled_and_malformed_requests(native_app,monkeypatch):
    from app.modules.service import ModuleService
    from app.study.models import UserWord
    user,headers=learner(native_app);word=make_word();client=native_app.test_client();url=f'/api/native/vocabulary/{word.id}/study'
    for body in [None,[],{'status':3},{'word_id':word.id}]:
        response=client.post(url,headers=headers,json=body)
        assert response.status_code==400,response.get_json()
    monkeypatch.setattr(ModuleService,'is_module_enabled_for_user',lambda *a: False)
    assert client.post(url,headers=headers,json={}).status_code==403
    assert UserWord.query.filter_by(user_id=user.id,word_id=word.id).count()==0


def test_account_controls_require_bearer_even_with_cookie_login(native_app):
    user,_=learner(native_app);client=native_app.test_client()
    with client.session_transaction() as session:
        session['_user_id']=str(user.id);session['_fresh']=True
    for path,body in [('/plan/pause',{'days':3}),('/plan/resume',{}),('/vocabulary/1/study',{})]:
        for headers in [{},{'Authorization':'Bearer invalid'}]:
            response=client.post('/api/native'+path,json=body,headers=headers)
            assert response.status_code in [401,422],(path,response.status_code,response.get_json())


def test_pause_resume_uses_canonical_events_and_validates_days(native_app):
    from app.achievements.models import StreakEvent
    from app.utils.db import db
    user,headers=learner(native_app);client=native_app.test_client()
    for body in [{'days':True},{'days':0},{'days':15},{'days':3,'extra':1},{}]:
        assert client.post('/api/native/plan/pause',headers=headers,json=body).status_code==400
    paused=client.post('/api/native/plan/pause',headers=headers,json={'days':3})
    assert paused.status_code==200,paused.get_json()
    db.session.refresh(user);assert user.plan_paused_until is not None
    assert StreakEvent.query.filter_by(user_id=user.id,event_type='plan_pause').count()==3
    repeated=client.post('/api/native/plan/pause',headers=headers,json={'days':3})
    assert repeated.status_code==200,repeated.get_json()
    assert StreakEvent.query.filter_by(user_id=user.id,event_type='plan_pause').count()==3
    resumed=client.post('/api/native/plan/resume',headers=headers,json={})
    assert resumed.status_code==200,resumed.get_json()
    db.session.refresh(user);assert user.plan_paused_until is None


def test_dictionary_pagination_has_stable_alphabetical_order(native_app):
    from app.words.models import CollectionWords
    from app.utils.db import db
    user,headers=learner(native_app);client=native_app.test_client();prefix='nativesort'+uuid4().hex[:8]
    for suffix in ['Zulu','alpha','Beta']:
        db.session.add(CollectionWords(english_word=prefix+suffix,russian_word='проверка',get_download=0))
    db.session.commit();found=[]
    for page in range(1,4):
        response=client.get('/api/words',headers=headers,query_string={'search':prefix,'per_page':1,'page':page})
        assert response.status_code==200,response.get_json()
        assert response.get_json()['total']==3
        found.extend(w['english_word'] for w in response.get_json()['words'])
    assert found==[prefix+'alpha',prefix+'Beta',prefix+'Zulu']


def test_failed_enrollment_rolls_back_exclusion_and_direction_provisioning(native_app,monkeypatch):
    from app.study.models import UserWord,UserCardDirection
    from app.utils.db import db
    import app.study.deck_utils as decks
    allow_study(monkeypatch);user,headers=learner(native_app);word=make_word();client=native_app.test_client()
    owned=UserWord.get_or_create(user.id,word.id);owned.srs_excluded=True;db.session.flush()
    card=UserCardDirection.get_or_create(owned.id,'eng-rus')
    db.session.commit();owned_id=owned.id
    def fail(*a,**k): raise RuntimeError('Disposable enrollment failure')
    monkeypatch.setattr(decks,'ensure_word_in_default_deck',fail)
    response=client.post(f'/api/native/vocabulary/{word.id}/study',headers=headers,json={})
    assert response.status_code==500,response.get_json()
    db.session.expire_all()
    assert db.session.get(UserWord,owned_id).srs_excluded is True
    assert UserCardDirection.query.filter_by(user_word_id=owned_id).count()==1


def test_enrollment_cannot_create_missing_or_untranslatable_words(native_app,monkeypatch):
    from app.words.models import CollectionWords
    from app.study.models import UserWord
    from app.utils.db import db
    allow_study(monkeypatch);user,headers=learner(native_app);client=native_app.test_client()
    assert client.post('/api/native/vocabulary/2147483647/study',headers=headers,json={}).status_code==404
    word=CollectionWords(english_word='untranslated '+uuid4().hex[:8],russian_word='',get_download=0)
    db.session.add(word);db.session.commit()
    assert client.post(f'/api/native/vocabulary/{word.id}/study',headers=headers,json={}).status_code==422
    assert UserWord.query.filter_by(user_id=user.id,word_id=word.id).count()==0
