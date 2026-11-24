"""Lesson audit item 16: picking a book is the reading goal.

The first book pick turns the daily reading goal on at 5 minutes, so the
reading slot joins the required section; later picks leave an explicit
«по желанию» (0) alone; existing readers get the goal by migration.
"""

from __future__ import annotations

import uuid

import pytest
from bs4 import BeautifulSoup
from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.auth.models import User
from app.books.models import Book, Chapter
from app.daily_plan.items.reading import (
    DEFAULT_READING_GOAL_MINUTES,
    build_reading_item,
    ensure_reading_goal_on_first_book,
    reading_goal_enabled,
)
from app.daily_plan.items.setup import build_setup_book_item
from app.daily_plan.linear.models import UserReadingPreference
from app.daily_plan.snapshot import overlay_completion
from app.modules.models import SystemModule
from app.modules.service import ModuleService
from app.study.models import StudySettings
from app.utils.db import db as real_db


def _book(db_session) -> Book:
    suffix = uuid.uuid4().hex[:8]
    book = Book(title=f'Book {suffix}', author='Author', level='A1', chapters_cnt=1,
                summary='s', rights_status='public_domain')
    db_session.add(book)
    db_session.commit()
    db_session.add(Chapter(book_id=book.id, chap_num=1, title='Chapter 1', words=100, text_raw='Text'))
    db_session.commit()
    return book


class TestHelper:
    def test_sets_default_when_unset(self, app, db_session, test_user):
        assert reading_goal_enabled(test_user.id, real_db) is False
        assert ensure_reading_goal_on_first_book(test_user.id, real_db) is True
        db_session.commit()
        assert StudySettings.query.filter_by(user_id=test_user.id).one().reading_minutes_per_day == DEFAULT_READING_GOAL_MINUTES
        assert reading_goal_enabled(test_user.id, real_db) is True

    def test_explicit_goal_is_kept(self, app, db_session, test_user):
        db_session.add(StudySettings(user_id=test_user.id, new_words_per_day=5, reviews_per_day=20, reading_minutes_per_day=10))
        db_session.commit()
        assert ensure_reading_goal_on_first_book(test_user.id, real_db) is False
        assert StudySettings.query.filter_by(user_id=test_user.id).one().reading_minutes_per_day == 10

    def test_default_is_five_minutes(self):
        assert DEFAULT_READING_GOAL_MINUTES == 5


class TestSelectEndpoint:
    def test_first_pick_turns_the_goal_on(self, app, db_session, test_user, authenticated_client):
        book = _book(db_session)
        resp = authenticated_client.post('/api/books/select', json={'book_id': book.id})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert StudySettings.query.filter_by(user_id=test_user.id).one().reading_minutes_per_day == 5

    def test_switching_books_keeps_an_explicit_opt_out(self, app, db_session, test_user, authenticated_client):
        first, second = _book(db_session), _book(db_session)
        db_session.add(StudySettings(user_id=test_user.id, new_words_per_day=5, reviews_per_day=20, reading_minutes_per_day=0))
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=first.id))
        db_session.commit()
        resp = authenticated_client.post('/api/books/select', json={'book_id': second.id})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert UserReadingPreference.query.filter_by(user_id=test_user.id).one().book_id == second.id
        assert StudySettings.query.filter_by(user_id=test_user.id).one().reading_minutes_per_day == 0


class TestSetupHintAndMigration:
    def test_setup_item_names_the_norm(self):
        assert '5 минут' in build_setup_book_item().subtitle

    def test_dashboard_book_picker_explains_the_first_goal_before_selection(
        self, authenticated_client: FlaskClient, db_session: Session, test_user: User,
    ) -> None:
        words = SystemModule.query.filter_by(code='words').one_or_none()
        if words is None:
            words = SystemModule(code='words', name='Words')
            db_session.add(words)
            db_session.flush()
        ModuleService.grant_module_to_user(test_user.id, words.id)
        _book(db_session)
        response = authenticated_client.get('/dashboard')
        assert response.status_code == 200
        page = BeautifulSoup(response.data, 'html.parser')
        trigger = page.select_one('[data-open-book-select]')
        assert 'первая книга добавит 5 минут чтения в день' in trigger.get_text(' ', strip=True)
        modal = page.select_one(trigger['href'])
        guidance = modal.select_one('#' + modal['aria-describedby'])
        text = guidance.get_text(' ', strip=True)
        assert build_setup_book_item().subtitle in text
        assert 'Уже заданная норма сохраняется.' in text
        assert 'При смене книги сохраняется и выбор «По желанию, без нормы».' in text
        assert guidance.select_one('a')['href'] == '/study/settings#reading_minutes_per_day'

    @pytest.mark.parametrize('section, subtitle', [
        ('optional', 'Можно почитать 5 мин'),
        ('required', 'Норма дня — 5 мин'),
    ])
    def test_reading_book_subtitle_matches_the_plan_section(
        self, db_session: Session, test_user: User, section: str, subtitle: str,
    ) -> None:
        book = _book(db_session)
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=book.id))
        db_session.commit()
        item = build_reading_item(test_user.id, real_db, section=section)
        assert item is not None and item.subtitle == subtitle
        assert item.data['gate_seconds'] == 300 and item.eta_minutes == 5
        if section == 'required':
            overlaid, = overlay_completion(test_user.id, {'items': [item.to_dict()]}, real_db)
            assert overlaid['subtitle'] == subtitle

    def test_short_reading_snapshot_preserves_questions_and_estimated_minutes(
        self, db_session: Session, test_user: User,
    ) -> None:
        book = _book(db_session)
        book.reading = {'format': 'short_text', 'estimated_minutes': 3, 'questions': [{'id': 'question'}]}
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=book.id))
        db_session.commit()
        optional = build_reading_item(test_user.id, real_db, section='optional')
        required = build_reading_item(test_user.id, real_db, section='required')
        overlaid, = overlay_completion(test_user.id, {'items': [required.to_dict()]}, real_db)
        assert optional.subtitle == required.subtitle == overlaid['subtitle'] == 'Прочитай текст и ответь на вопросы: 1'
        assert optional.eta_minutes == required.eta_minutes == overlaid['eta_minutes'] == 3
        assert overlaid['data']['completion_mode'] == 'short_reading'

    def test_migration_chain_and_statements(self):
        from pathlib import Path
        src = Path('migrations/versions/20260906_reading_goal_for_readers.py').read_text(encoding='utf-8')
        assert "down_revision = '20260906_reading_goal_and_pace'" in src
        assert 'INSERT INTO study_settings' in src and 'UPDATE study_settings s SET reading_minutes_per_day = 5' in src
        assert 'EXISTS (SELECT 1 FROM user_reading_preference' in src
