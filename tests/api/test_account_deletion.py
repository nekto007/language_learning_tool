"""Irreversible account deletion is tested only on a disposable, FK-enforced DB."""
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
import pytest
from tests.api.test_native_full_integration import learner

PREFIX = "/api/mobile/auth/account/deletion"


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    from app import create_app
    from app.utils.db import db
    from config.settings import Config
    class C(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(tmp_path_factory.mktemp("deletion") / "test.db")
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = True
        RATELIMIT_ENABLED = False
        MAIL_SUPPRESS_SEND = True
        SERVER_NAME = "localhost"
        SESSION_COOKIE_DOMAIN = None
        SESSION_COOKIE_SECURE = False
    app = create_app(config_class=C)
    with app.app_context():
        db.create_all()
        assert db.session.execute(db.text("PRAGMA foreign_keys")).scalar() == 1
        yield app
        db.session.remove()
        db.engine.dispose()


@pytest.fixture(autouse=True)
def isolate(native_app):
    from app.auth.mobile_models import MobileAuthThrottle
    from app.auth.account_deletion import AccountDeletionFile, AccountDeletionMail
    from app.utils.db import db
    MobileAuthThrottle.query.delete()
    AccountDeletionFile.query.delete()
    AccountDeletionMail.query.delete()
    db.session.commit()


def begin(app, headers):
    response = app.test_client().post(PREFIX + "/start", headers=headers, json={})
    assert response.status_code == 200, response.json
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "Set-Cookie" not in response.headers
    return response.json


def confirmation(challenge):
    from app.auth.mobile_models import MobileAuthMail
    from app.auth.mobile_mail import cipher
    row = MobileAuthMail.query.filter_by(challenge_id=challenge["challenge_id"]).one()
    return dict(challenge_id=challenge["challenge_id"], confirm=True,
        code=cipher().decrypt(row.encrypted_code.encode()).decode())


def administrator(app):
    from app.utils.db import db
    user, _ = learner(app)
    user.is_admin = True
    user.onboarding_completed = True
    db.session.commit()
    return user


def age_request(identifier, days=8):
    from app.auth.account_deletion import AccountDeletionRequest
    from app.auth.mobile_models import utcnow
    from app.utils.db import db
    row = db.session.get(AccountDeletionRequest,identifier)
    row.requested_at=utcnow()-timedelta(days=days)
    row.earliest_deletion_at=row.requested_at+timedelta(days=7)
    row.latest_deletion_at=row.requested_at+timedelta(days=14)
    db.session.commit()
    return row


def test_start_requires_bearer_and_does_not_delete(native_app):
    from app.auth.models import User
    from app.utils.db import db
    user, headers = learner(native_app)
    uid = user.id
    client = native_app.test_client()
    for path in ["/start", "/confirm"]:
        assert client.post(PREFIX + path, json={}).status_code == 401
        with client.session_transaction() as session:
            session["_user_id"] = user.get_id()
            session["_fresh"] = True
        assert client.post(PREFIX + path, json={}).status_code == 401
    value = begin(native_app, headers)
    assert value["verification"] == "email_code" and "***@" in value["email_hint"]
    assert db.session.get(User, uid) is not None
    assert client.post(PREFIX + "/start", headers=headers, json={"user_id": uid}).status_code == 400


def test_wrong_code_expires_after_five_attempts_and_cannot_delete_other_user(native_app):
    from app.auth.models import User
    from app.auth.mobile_models import MobileAuthChallenge
    from app.utils.db import db
    user, headers = learner(native_app)
    other, other_headers = learner(native_app)
    uid, oid = user.id, other.id
    challenge = begin(native_app, headers)
    body = confirmation(challenge)
    client = native_app.test_client()
    assert client.post(PREFIX + "/confirm", headers=other_headers, json=body).status_code == 400
    bad = dict(body, code="000000" if body["code"] != "000000" else "999999")
    for _ in range(5):
        assert client.post(PREFIX + "/confirm", headers=headers, json=bad).status_code == 400
    assert client.post(PREFIX + "/confirm", headers=headers, json=body).json["error"] == "challenge_expired"
    assert db.session.get(User, uid) and db.session.get(User, oid)
    assert db.session.get(MobileAuthChallenge, body["challenge_id"]).attempts == 5


def test_explicit_confirmation_expiration_and_password_version_are_required(native_app):
    from app.auth.mobile_models import MobileAuthChallenge, utcnow
    from app.utils.db import db
    from flask_jwt_extended import create_access_token
    user, headers = learner(native_app)
    challenge = begin(native_app, headers)
    body = confirmation(challenge)
    client = native_app.test_client()
    for value in [False, "true", 1, None]:
        assert client.post(PREFIX + "/confirm", headers=headers, json=dict(body, confirm=value)).status_code == 400
    row = db.session.get(MobileAuthChallenge, body["challenge_id"])
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    assert client.post(PREFIX + "/confirm", headers=headers, json=body).json["error"] == "challenge_expired"
    row.expires_at = utcnow() + timedelta(minutes=5)
    user.set_password("another-test-only-password")
    db.session.commit()
    fresh = {"Authorization":"Bearer " + create_access_token(identity=str(user.id),additional_claims={"auth_version":user.auth_version()})}
    assert client.post(PREFIX + "/confirm", headers=fresh, json=body).status_code == 400
    assert client.post(PREFIX + "/confirm", headers=headers, json=body).status_code == 401


def test_verified_deletion_cascades_private_data_preserves_shared_words_and_other_accounts(native_app):
    from app.auth.models import User
    from app.auth.mobile_models import MobileAuthChallenge, MobileAuthMail
    from app.study.models import UserWord, UserCardDirection, StudySettings
    from app.words.models import CollectionWords
    from app.notifications.push_models import PushPreference
    from app.reminders.models import ReminderLog
    from app.feedback.models import Feedback, FeedbackReply
    from app.auth.account_deletion import AccountDeletionFile
    from app.utils.db import db
    user, headers = learner(native_app)
    other, other_headers = learner(native_app)
    uid, oid = user.id, other.id
    other.referred_by_id = uid
    word = CollectionWords(english_word="release" + uuid4().hex, russian_word="выпуск")
    db.session.add(word); db.session.flush(); wid = word.id
    owned = UserWord(user_id=uid, word_id=wid)
    retained = UserWord(user_id=oid, word_id=wid)
    db.session.add_all([owned,retained,StudySettings(user_id=uid),PushPreference(user_id=uid),
        ReminderLog(user_id=uid,sent_by=oid,template="test",subject="test",token=uuid4().hex)])
    db.session.flush()
    db.session.add(UserCardDirection(user_word_id=owned.id,direction="eng-rus"))
    feedback = Feedback(user_id=uid,category="bug",message="private message",screenshot_path="feedback/"+uuid4().hex+".png")
    db.session.add(feedback); db.session.flush()
    db.session.add(FeedbackReply(feedback_id=feedback.id,author_user_id=oid,body="test admin response"))
    db.session.commit()
    challenge = begin(native_app,headers); body=confirmation(challenge)
    response = native_app.test_client().post(PREFIX+"/confirm",headers=headers,json=body)
    assert response.status_code == 200, response.json
    assert response.json['status']=='pending_admin_review'
    request_id=response.json['request']['id']
    # Submission never erases the user or their data, even with a valid OTP.
    assert db.session.get(User,uid) is not None
    assert UserWord.query.filter_by(user_id=uid).count()==1
    from app.auth.account_deletion import complete_account_deletion
    age_request(request_id)
    complete_account_deletion(request_id,administrator(native_app))
    assert response.headers["Cache-Control"] == "private, no-store"
    db.session.expire_all()
    assert db.session.get(User,uid) is None
    assert db.session.get(User,oid).referred_by_id is None
    assert db.session.get(CollectionWords,wid)
    assert UserWord.query.filter_by(user_id=oid,word_id=wid).count()==1
    for model in [UserWord,StudySettings,PushPreference,MobileAuthChallenge,ReminderLog,Feedback]:
        assert model.query.filter_by(user_id=uid).count()==0
    assert UserCardDirection.query.count()==0
    assert MobileAuthMail.query.filter_by(challenge_id=body['challenge_id']).count()==0
    assert AccountDeletionFile.query.count()==1
    assert native_app.test_client().post(PREFIX+'/confirm',headers=headers,json=body).status_code==401
    assert native_app.test_client().post(PREFIX+'/start',headers=other_headers,json={}).status_code==200


def test_legacy_account_without_email_can_verify_its_password(native_app):
    from app.auth.models import User
    from app.utils.db import db
    user, headers=learner(native_app);uid=user.id
    user.email=None;db.session.commit()
    challenge=begin(native_app,headers)
    assert challenge['verification']=='password'
    body=dict(challenge_id=challenge['challenge_id'],confirm=True,password='wrong')
    client=native_app.test_client()
    assert client.post(PREFIX+'/confirm',headers=headers,json=body).status_code==400
    body['password']='only-disposable-local-test-password'
    assert client.post(PREFIX+'/confirm',headers=headers,json=body).json['status']=='pending_admin_review'
    assert db.session.get(User,uid) is not None


@pytest.mark.parametrize('success',[True,False])
def test_apple_access_is_revoked_before_account_deletion(native_app,monkeypatch,success):
    from app.auth.models import User
    from app.auth.mobile_models import SocialIdentity
    from app.auth.mobile_mail import cipher
    from app.utils.db import db
    import app.api.mobile_social as social
    import app.auth.account_deletion as erasure
    user,headers=learner(native_app);uid=user.id
    db.session.add(SocialIdentity(user_id=uid,provider='apple',subject='test-'+uuid4().hex,
        encrypted_refresh=cipher().encrypt(b'test-only-refresh').decode()));db.session.commit()
    monkeypatch.setattr(social,'_apple_secret',lambda:'test-only-secret')
    calls=[]
    def post(url,**kwargs):
        calls.append((url,kwargs));return SimpleNamespace(status_code=200 if success else 503)
    monkeypatch.setattr(erasure.requests,'post',post)
    body=confirmation(begin(native_app,headers))
    response=native_app.test_client().post(PREFIX+'/confirm',headers=headers,json=body)
    assert response.status_code==200,response.json
    assert calls==[]
    assert db.session.get(User,uid) is not None
    identifier=response.json['request']['id']
    age_request(identifier)
    from app.api.mobile_auth import AuthProblem
    admin=administrator(native_app)
    if success:
        erasure.complete_account_deletion(identifier,admin)
    else:
        with pytest.raises(AuthProblem) as error:
            erasure.complete_account_deletion(identifier,admin)
        assert error.value.code=='deletion_temporarily_unavailable'
        db.session.rollback()
    assert calls[0][0]=='https://appleid.apple.com/auth/revoke'
    assert calls[0][1]['data']['token']=='test-only-refresh'
    assert calls[0][1]['allow_redirects'] is False
    assert (db.session.get(User,uid) is None)==success


def submit(app,headers):
    response=app.test_client().post(PREFIX+'/confirm',headers=headers,json=confirmation(begin(app,headers)))
    assert response.status_code==200,response.json
    return response.json['request']


def test_request_has_seven_to_fourteen_day_window_can_cancel_and_is_never_automatic(native_app):
    from app.auth.models import User
    from app.auth.account_deletion import complete_account_deletion,process_account_deletion_files,process_account_deletion_mail
    from app.api.mobile_auth import AuthProblem
    from app.utils.db import db
    from datetime import datetime
    user,headers=learner(native_app);uid=user.id
    value=submit(native_app,headers);identifier=value['id'];admin=administrator(native_app)
    dates=[datetime.fromisoformat(value[k].replace('Z','+00:00')) for k in ['requested_at','earliest_deletion_at','latest_deletion_at']]
    assert dates[1]-dates[0]==timedelta(days=7)
    assert dates[2]-dates[0]==timedelta(days=14)
    with pytest.raises(AuthProblem) as early:
        complete_account_deletion(identifier,admin)
    assert early.value.code=='cooling_off_period'
    db.session.rollback()
    age_request(identifier,days=15)
    process_account_deletion_files();process_account_deletion_mail()
    assert db.session.get(User,uid)
    client=native_app.test_client()
    assert client.get(PREFIX+'/current',headers=headers).json['request']['status']=='pending'
    assert client.post(PREFIX+'/cancel',headers=headers,json={'request_id':identifier}).json['request']['status']=='cancelled'
    with pytest.raises(AuthProblem) as cancelled:
        complete_account_deletion(identifier,admin)
    assert cancelled.value.code=='request_not_pending'
    assert db.session.get(User,uid)


def test_tracking_receipt_confirms_completion_without_exposing_personal_data(native_app,monkeypatch):
    from app.auth.account_deletion import complete_account_deletion,process_account_deletion_mail,AccountDeletionMail
    from app.auth.models import User
    from app.auth.mobile_mail import cipher
    from app.utils.email_utils import email_sender
    from app.utils.db import db
    user,headers=learner(native_app);uid=user.id;address=user.email;username=user.username
    value=submit(native_app,headers);identifier=value['id']
    age_request(identifier);complete_account_deletion(identifier,administrator(native_app))
    mail=db.session.get(AccountDeletionMail,identifier)
    assert mail.encrypted_email!=address and cipher().decrypt(mail.encrypted_email.encode()).decode()==address
    client=native_app.test_client();body=dict(request_id=identifier,tracking_token=value['tracking_token'])
    response=client.post(PREFIX+'/status',json=body)
    assert response.status_code==200 and response.json['request']['status']=='completed'
    assert username not in str(response.json) and address not in str(response.json)
    assert client.post(PREFIX+'/status',json=dict(body,tracking_token='a'*64)).status_code==404
    sent=[]
    monkeypatch.setattr(email_sender,'send_email',lambda **kwargs: sent.append(kwargs) or True)
    assert process_account_deletion_mail()==1
    assert len(sent)==1 and sent[0]['to']==address and sent[0]['template']=='account_deleted'
    assert db.session.get(AccountDeletionMail,identifier).encrypted_email is None
    assert db.session.get(User,uid) is None


def test_admin_approval_requires_admin_session_csrf_and_account_name(native_app):
    from app.auth.models import User
    from app.utils.db import db
    user,headers=learner(native_app);uid=user.id;username=user.username
    value=submit(native_app,headers);identifier=value['id'];age_request(identifier)
    client=native_app.test_client();path='/admin/account-deletions/'+identifier+'/complete'
    with client.session_transaction() as session:session['_user_id']=user.get_id();session['_fresh']=True
    from flask import g
    g.pop('_login_user',None)
    csrf_response=client.get('/csrf-token')
    assert csrf_response.status_code==200,(csrf_response.status_code,csrf_response.headers.get('Location'))
    csrf=csrf_response.json['csrf_token']
    assert client.post(path,data=dict(confirmation=username,csrf_token=csrf)).status_code==302
    assert db.session.get(User,uid)
    admin=administrator(native_app)
    with client.session_transaction() as session:session['_user_id']=admin.get_id();session['_fresh']=True
    g.pop('_login_user',None)
    admin_page=client.get('/admin/account-deletions')
    assert admin_page.status_code==200,(admin_page.status_code,admin_page.headers.get('Location'))
    assert client.post(path,data=dict(confirmation=username),headers={'Accept':'application/json'}).status_code==400
    assert db.session.get(User,uid)
    csrf=client.get('/csrf-token').json['csrf_token']
    assert client.post(path,data=dict(confirmation='wrong',csrf_token=csrf)).status_code==400
    assert db.session.get(User,uid)
    assert client.post(path,data=dict(confirmation=username,csrf_token=csrf)).status_code==302
    assert db.session.get(User,uid) is None


def test_file_cleanup_retries_and_does_not_delete_another_users_attachment(native_app,monkeypatch,tmp_path):
    from app.auth.account_deletion import AccountDeletionFile,process_account_deletion_files
    from app.feedback.models import Feedback
    from app.utils.db import db
    import app.feedback.storage as storage
    import app.auth.account_deletion as erasure
    root=tmp_path/'feedback';root.mkdir();private=root/'private.png';private.write_bytes(b'private-test')
    shared=root/'shared.png';shared.write_bytes(b'shared-test')
    monkeypatch.setattr(storage,'UPLOAD_BASE_FOLDER',str(tmp_path))
    monkeypatch.setattr(storage,'FEEDBACK_UPLOAD_FOLDER',str(root))
    user,_=learner(native_app)
    db.session.add_all([Feedback(user_id=user.id,category='bug',message='other users record',screenshot_path='feedback/shared.png'),
        AccountDeletionFile(path='feedback/private.png'),AccountDeletionFile(path='feedback/shared.png'),
        AccountDeletionFile(path='../outside')]);db.session.commit()
    real_unlink=erasure.os.unlink
    def denied(path):
        if str(path)==str(private):raise PermissionError('test')
        return real_unlink(path)
    monkeypatch.setattr(erasure.os,'unlink',denied)
    assert process_account_deletion_files()==2
    assert private.exists() and shared.exists()
    row=db.session.get(AccountDeletionFile,'feedback/private.png');assert row.attempts==1
    row.available_at=erasure.utcnow();db.session.commit()
    monkeypatch.setattr(erasure.os,'unlink',real_unlink)
    assert process_account_deletion_files()==1
    assert not private.exists() and shared.exists()


def test_duplicate_request_preserves_deadline_and_resubmission_invalidates_old_receipt(native_app):
    from app.auth.mobile_models import MobileAuthThrottle
    from app.auth.account_deletion import AccountDeletionRequest
    from app.utils.db import db
    user, headers = learner(native_app)
    original = submit(native_app, headers)
    row = age_request(original['id'], days=2)
    expected = row.response()
    # Clear the test-only 60 second mail cooldown between separate verifications.
    MobileAuthThrottle.query.delete(); db.session.commit()
    duplicate = submit(native_app, headers)
    assert duplicate['id'] == original['id']
    assert duplicate['requested_at'] == expected['requested_at']
    assert duplicate['latest_deletion_at'] == expected['latest_deletion_at']
    client = native_app.test_client()
    assert client.post(PREFIX+'/cancel', headers=headers, json={'request_id':row.id}).status_code == 200
    MobileAuthThrottle.query.delete(); db.session.commit()
    newer = submit(native_app, headers)
    assert newer['id'] != original['id']
    assert AccountDeletionRequest.query.filter_by(user_id=user.id).count() == 1
    assert client.post(PREFIX+'/status', json=dict(request_id=original['id'], tracking_token=original['tracking_token'])).status_code == 404


def test_failed_database_erasure_rolls_back_request_and_user_data(native_app, monkeypatch):
    from app.auth.account_deletion import AccountDeletionRequest, AccountDeletionMail, complete_account_deletion
    from app.auth.models import User
    from app.api.mobile_auth import AuthProblem
    from app.study.models import StudySettings
    from app.utils.db import db
    user, headers = learner(native_app); uid = user.id
    db.session.add(StudySettings(user_id=uid)); db.session.commit()
    value = submit(native_app, headers); age_request(value['id'])
    admin = administrator(native_app)
    original = db.session.execute
    def failing(statement, *args, **kwargs):
        if getattr(statement, 'is_delete', False) and getattr(statement.table, 'name', '') == 'users':
            raise RuntimeError('simulated transaction failure')
        return original(statement, *args, **kwargs)
    monkeypatch.setattr(db.session, 'execute', failing)
    with pytest.raises(AuthProblem):
        complete_account_deletion(value['id'], admin)
    assert db.session.get(User, uid)
    assert StudySettings.query.filter_by(user_id=uid).one()
    assert db.session.get(AccountDeletionRequest, value['id']).status == 'pending'
    assert db.session.get(AccountDeletionMail, value['id']) is None


def test_new_migration_can_round_trip_without_touching_users(tmp_path):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import sqlalchemy as sa
    spec = importlib.util.spec_from_file_location('deletion_migration', Path('migrations/versions/20261118_account_deletion.py'))
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite:///'+str(tmp_path/'migration.sqlite'))
    with engine.begin() as connection:
        connection.exec_driver_sql('PRAGMA foreign_keys=ON')
        connection.exec_driver_sql('CREATE TABLE users (id INTEGER PRIMARY KEY)')
        connection.exec_driver_sql('INSERT INTO users VALUES (101)')
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert set(sa.inspect(connection).get_table_names()) == {'users','account_deletion_requests','account_deletion_mail','account_deletion_files'}
            migration.downgrade()
            assert sa.inspect(connection).get_table_names() == ['users']
            assert connection.exec_driver_sql('SELECT id FROM users').scalar() == 101
    engine.dispose()


def test_support_and_privacy_are_available_signed_out(native_app):
    client = native_app.test_client()
    for path in ['/privacy','/support/mobile']:
        response = client.get(path)
        assert response.status_code == 200
        text = response.get_data(as_text=True)
        assert '14-й' in text and 'администратор' in text
        assert 't.me/llt_englishbot' in text
