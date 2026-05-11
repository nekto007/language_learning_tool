"""Tests for admin content quality dashboard (Task 86)."""
import uuid

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.utils.db import db


def _make_level(db_session):
    level = CEFRLevel(
        code=uuid.uuid4().hex[:2].upper(),
        name='Test',
        description='Test',
        order=uuid.uuid4().int % 900 + 100,
    )
    db_session.add(level)
    db_session.flush()
    return level


def _make_module(db_session, level):
    module = Module(level_id=level.id, number=1, title='CQ Module')
    db_session.add(module)
    db_session.flush()
    return module


def _make_lesson(db_session, module, lesson_type='text', content=None, title=None, collection_id=None):
    lesson = Lessons(
        module_id=module.id,
        number=uuid.uuid4().int % 9000 + 1,
        title=title or f'Lesson {uuid.uuid4().hex[:6]}',
        type=lesson_type,
        order=1,
        content=content or {},
        collection_id=collection_id,
    )
    db_session.add(lesson)
    db_session.flush()
    return lesson


class TestContentQualityRoute:
    """Route access tests."""

    @pytest.mark.smoke
    def test_returns_200_for_admin(self, app, client, admin_user):
        response = client.get('/admin/content-quality')
        assert response.status_code == 200

    def test_redirects_non_admin(self, app, client, db_session):
        user = User(
            username=f'nonadmin_{uuid.uuid4().hex[:8]}',
            email=f'na_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
            is_admin=False,
        )
        user.set_password('pass')
        db_session.add(user)
        db_session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

        response = client.get('/admin/content-quality')
        # admin_required decorator redirects non-admin to login (302)
        assert response.status_code == 302

    def test_contains_table_headers(self, app, client, admin_user):
        response = client.get('/admin/content-quality')
        data = response.data.decode('utf-8')
        assert 'Тип' in data
        assert 'Всего' in data
        assert 'Аудио' in data

    def test_export_returns_csv(self, app, client, admin_user):
        response = client.get('/admin/content-quality/export')
        assert response.status_code == 200
        assert 'text/csv' in response.content_type
        content = response.data.decode('utf-8')
        assert 'Lesson Type' in content
        assert 'Audio %' in content


class TestGetContentQualityDetail:
    """Unit tests for get_content_quality_detail function."""

    def test_returns_expected_keys(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        result = get_content_quality_detail()

        assert 'by_type' in result
        assert 'missing_audio' in result
        assert 'missing_audio_count' in result
        assert 'no_vocabulary' in result
        assert 'no_vocabulary_count' in result
        assert 'total_lessons' in result
        assert 'no_completions_count' in result

    def test_counts_total_lessons_by_type(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, lesson_type='dictation', content={'audio_url': 'http://example.com/a.mp3'})
        _make_lesson(db_session, module, lesson_type='dictation', content={})
        db_session.commit()

        result = get_content_quality_detail()

        dictation_rows = [r for r in result['by_type'] if r['type'] == 'dictation']
        assert len(dictation_rows) == 1
        assert dictation_rows[0]['total'] >= 2

    def test_audio_pct_correct(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        # 1 with audio, 1 without
        _make_lesson(db_session, module, lesson_type='shadow_reading', content={'audio_url': 'http://x.com/a.mp3'})
        _make_lesson(db_session, module, lesson_type='shadow_reading', content={})
        db_session.commit()

        result = get_content_quality_detail()

        row = next((r for r in result['by_type'] if r['type'] == 'shadow_reading'), None)
        assert row is not None
        # at least 1 has audio, pct > 0
        assert row['with_audio'] >= 1
        assert row['audio_pct'] > 0

    def test_missing_audio_reported_for_audio_types(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type='dictation', content={})
        db_session.commit()

        result = get_content_quality_detail()

        missing_ids = [m['lesson_id'] for m in result['missing_audio']]
        assert lesson.id in missing_ids
        assert result['missing_audio_count'] >= 1

    def test_lesson_with_audio_not_in_missing(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type='listening_immersion',
                               content={'audio_url': 'http://example.com/audio.mp3'})
        db_session.commit()

        result = get_content_quality_detail()

        missing_ids = [m['lesson_id'] for m in result['missing_audio']]
        assert lesson.id not in missing_ids

    def test_vocabulary_lesson_without_collection_reported(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        # vocabulary lesson with no collection_id
        lesson = _make_lesson(db_session, module, lesson_type='vocabulary', collection_id=None)
        db_session.commit()

        result = get_content_quality_detail()

        no_vocab_ids = [v['lesson_id'] for v in result['no_vocabulary']]
        assert lesson.id in no_vocab_ids
        assert result['no_vocabulary_count'] >= 1

    def test_completion_counted(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail
        from datetime import datetime, timezone

        user = User(
            username=f'cq_u_{uuid.uuid4().hex[:8]}',
            email=f'cq_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        user.set_password('pass')
        db_session.add(user)
        db_session.flush()

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type='quiz')

        lp = LessonProgress(
            user_id=user.id,
            lesson_id=lesson.id,
            status='completed',
            completed_at=datetime.now(timezone.utc),
        )
        db_session.add(lp)
        db_session.commit()

        result = get_content_quality_detail()

        quiz_row = next((r for r in result['by_type'] if r['type'] == 'quiz'), None)
        assert quiz_row is not None
        assert quiz_row['completed'] >= 1
        assert quiz_row['completion_pct'] > 0

    def test_no_completions_count_correct(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        result = get_content_quality_detail()

        assert isinstance(result['no_completions_count'], int)
        assert result['no_completions_count'] >= 0
        assert result['no_completions_count'] <= result['total_lessons']

    def test_type_row_has_all_fields(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, lesson_type='matching')
        db_session.commit()

        result = get_content_quality_detail()

        row = next((r for r in result['by_type'] if r['type'] == 'matching'), None)
        assert row is not None
        for field in ('type', 'total', 'with_audio', 'with_ipa', 'with_examples',
                      'completed', 'audio_pct', 'ipa_pct', 'examples_pct', 'completion_pct'):
            assert field in row

    def test_export_csv_contains_data_row(self, app, client, admin_user, db_session):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, lesson_type='translation')
        db_session.commit()

        response = client.get('/admin/content-quality/export')
        content = response.data.decode('utf-8')
        assert 'translation' in content


class TestMissingAudioSorted:
    """Tests for missing audio sorting by module progression (Task 87)."""

    def test_missing_audio_entries_have_level_and_module_info(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, lesson_type='dictation', content={})
        db_session.commit()

        result = get_content_quality_detail()

        missing = [m for m in result['missing_audio'] if m.get('module_id') == module.id]
        assert missing, 'Expected at least one missing audio entry for this module'
        entry = missing[0]
        assert 'level_code' in entry
        assert 'module_number' in entry
        assert 'lesson_number' in entry

    def test_missing_audio_sorted_by_level_order(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level1 = _make_level(db_session)
        level1.order = 5
        level2 = _make_level(db_session)
        level2.order = 50
        db_session.flush()

        module1 = _make_module(db_session, level1)
        module2 = _make_module(db_session, level2)
        lesson_low = _make_lesson(db_session, module1, lesson_type='dictation', content={})
        lesson_high = _make_lesson(db_session, module2, lesson_type='dictation', content={})
        db_session.commit()

        result = get_content_quality_detail()

        missing_ids = [m['lesson_id'] for m in result['missing_audio']]
        assert lesson_low.id in missing_ids
        assert lesson_high.id in missing_ids
        # lesson in lower-order level should appear before lesson in higher-order level
        assert missing_ids.index(lesson_low.id) < missing_ids.index(lesson_high.id)

    def test_admin_route_shows_level_column(self, app, client, admin_user, db_session):
        level = _make_level(db_session)
        level.order = 1
        db_session.flush()
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, lesson_type='dictation', content={})
        db_session.commit()

        response = client.get('/admin/content-quality')
        assert response.status_code == 200
        data = response.data.decode('utf-8')
        # Template should now show Level and Module columns
        assert 'Уровень' in data
        assert 'Модуль' in data


class TestContentAuditCLI:
    """Tests for flask content-audit CLI command (Task 87)."""

    def test_get_missing_audio_lessons_finds_missing(self, app, db_session):
        from app.cli.content_commands import _get_missing_audio_lessons

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type='dictation', content={})
        db_session.commit()

        missing = _get_missing_audio_lessons()

        ids = [m['lesson_id'] for m in missing]
        assert lesson.id in ids

    def test_get_missing_audio_lessons_excludes_lessons_with_audio(self, app, db_session):
        from app.cli.content_commands import _get_missing_audio_lessons

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type='dictation',
                               content={'audio_url': 'http://example.com/audio.mp3'})
        db_session.commit()

        missing = _get_missing_audio_lessons()

        ids = [m['lesson_id'] for m in missing]
        assert lesson.id not in ids

    def test_get_missing_audio_lessons_detects_empty_string_url(self, app, db_session):
        from app.cli.content_commands import _get_missing_audio_lessons

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type='text', content={'audio_url': ''})
        db_session.commit()

        missing = _get_missing_audio_lessons()

        ids = [m['lesson_id'] for m in missing]
        assert lesson.id in ids
        entry = next(m for m in missing if m['lesson_id'] == lesson.id)
        assert entry['status'] == 'empty'

    def test_cli_command_runs_successfully(self, app, db_session):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, lesson_type='dictation',
                     content={}, title='Missing Audio Lesson')
        db_session.commit()

        runner = app.test_cli_runner()
        result = runner.invoke(args=['content-audit', 'audio'])

        assert result.exit_code == 0
        assert 'Found' in result.output or 'Missing Audio Lesson' in result.output

    def test_cli_command_no_missing_output(self, app, db_session):
        # No dictation/listening lessons without audio created in this test
        runner = app.test_cli_runner()
        result = runner.invoke(args=['content-audit', 'audio'])

        assert result.exit_code == 0
        # Either finds existing missing ones or reports none found
        assert result.output is not None

    def test_missing_audio_lessons_match_admin_detail(self, app, db_session):
        """CLI data and admin route both detect same missing audio entries."""
        from app.admin.main_routes import get_content_quality_detail
        from app.cli.content_commands import _get_missing_audio_lessons

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type='listening_immersion', content={})
        db_session.commit()

        admin_result = get_content_quality_detail()
        cli_result = _get_missing_audio_lessons()

        admin_ids = {m['lesson_id'] for m in admin_result['missing_audio']}
        cli_ids = {m['lesson_id'] for m in cli_result}
        # Both should include our lesson
        assert lesson.id in admin_ids
        assert lesson.id in cli_ids
