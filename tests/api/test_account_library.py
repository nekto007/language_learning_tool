from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from tests.api.test_native_full_integration import native_app, learner


def book(chapters=2, level='B2', **kw):
    from app.books.models import Book, Chapter
    from app.utils.db import db
    value=Book(title='History '+uuid4().hex[:8], author='Author', level=level,
               chapters_cnt=chapters, rights_status=kw.pop('rights_status','public_domain'),
               is_published=kw.pop('is_published',True), **kw)
    db.session.add(value);db.session.flush()
    rows=[Chapter(book_id=value.id,chap_num=n,title=f'Chapter {n}',text_raw='Body',words=1) for n in range(1,chapters+1)]
    db.session.add_all(rows);db.session.commit()
    return value,rows


def progress(user,chapter,offset=0.2,days=0):
    from app.books.models import UserChapterProgress
    from app.utils.db import db
    db.session.add(UserChapterProgress(user_id=user.id,chapter_id=chapter.id,offset_pct=offset,
        updated_at=datetime.now(timezone.utc)-timedelta(days=days)))
    db.session.commit()


@pytest.fixture(autouse=True)
def levels(monkeypatch):
    monkeypatch.setattr('app.api.books_catalog.get_user_current_cefr_level',lambda *a:'A1')
    monkeypatch.setattr('app.api.books_catalog._level_window_codes',lambda *a:['A0','A1','A2'])


def test_account_history_includes_completed_and_out_of_window_with_shared_progress_math(native_app):
    from app.utils.db import db
    from app.daily_plan.linear.models import UserReadingPreference
    from app.books.reading_session import CHAPTER_COMPLETION_THRESHOLD
    user,headers=learner(native_app);client=native_app.test_client()
    reading,ch=book();done,dc=book(level='A1');selected,_=book(level='C1')
    progress(user,ch[0],CHAPTER_COMPLETION_THRESHOLD,days=1);progress(user,ch[1],0.25)
    for row in dc:progress(user,row,CHAPTER_COMPLETION_THRESHOLD)
    db.session.add(UserReadingPreference(user_id=user.id,book_id=selected.id));db.session.commit()
    response=client.get('/api/books/catalog?include_library=1',headers=headers)
    assert response.status_code==200,response.get_json()
    data=response.get_json();history={entry['book']['id']:entry for entry in data['library_books']}
    assert set(history)=={reading.id,done.id,selected.id}
    assert history[reading.id]['progress']['progress_pct']==62
    assert history[reading.id]['progress']['current_chapter']==2
    assert history[reading.id]['progress']['is_completed'] is False
    assert history[done.id]['progress']['is_completed'] is True
    assert history[done.id]['progress']['progress_pct']==100
    assert history[selected.id]['progress']['is_selected'] is True
    assert history[selected.id]['progress']['current_chapter']==1
    assert history[selected.id]['progress']['last_read'] is None
    assert done.id not in {b['id'] for b in data['books']}
    assert reading.id not in {b['id'] for b in data['books']}
    assert response.headers['Cache-Control']=='private, no-store'
    old=client.get('/api/books/catalog',headers=headers).get_json()
    assert 'library_books' not in old
    assert old['books']==data['books']


def test_history_is_private_and_honors_drafts_and_rights(native_app):
    user,headers=learner(native_app);other,foreign=learner(native_app);client=native_app.test_client()
    visible,ch=book();draft,dh=book(is_published=False);private,ph=book(rights_status='licensed');others,oh=book()
    for row in [ch[0],dh[0],ph[0]]:progress(user,row)
    progress(other,oh[0])
    response=client.get('/api/books/catalog?include_library=1',headers=headers)
    assert {x['book']['id'] for x in response.get_json()['library_books']}=={visible.id}
    other_data=client.get('/api/books/catalog?include_library=1',headers=foreign).get_json()
    assert {x['book']['id'] for x in other_data['library_books']}=={others.id}
    assert client.get('/api/books/catalog?include_library=1').status_code==401


def test_history_sort_uses_last_read_and_query_count_does_not_grow_per_book(native_app):
    from sqlalchemy import event
    from app.utils.db import db
    user,headers=learner(native_app);client=native_app.test_client()
    first,ch=book();progress(user,ch[0],days=2)
    def query():
        statements=[]
        def record(*a):statements.append(a[2])
        event.listen(db.engine,'before_cursor_execute',record)
        try:
            response=client.get('/api/books/catalog?include_library=1',headers=headers)
            assert response.status_code==200,response.get_json()
            assert all('chapter.text_raw' not in sql.lower() for sql in statements)
            return response.get_json(),len(statements)
        finally:event.remove(db.engine,'before_cursor_execute',record)
    _,before=query()
    created=[]
    for i in range(10):
        value,ch=book();progress(user,ch[0],days=1);created.append(value.id)
    latest,ch=book();progress(user,ch[0])
    data,after=query()
    assert after<=before+1,(before,after)
    assert data['library_books'][0]['book']['id']==latest.id
    assert data['library_books'][-1]['book']['id']==first.id
    assert len(data['library_books'])==12
