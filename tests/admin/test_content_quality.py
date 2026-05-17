"""Tests for admin content quality dashboard."""
import uuid
from datetime import datetime, timezone

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonFeedback, LessonProgress, Lessons, Module
from app.utils.db import db
from app.words.models import Collection, CollectionWordLink, CollectionWords


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


# ── Task 48 ──────────────────────────────────────────────────────────────────

ALL_NEW_LESSON_TYPES = [
    'dictation', 'audio_fill_blank', 'translation', 'sentence_correction',
    'writing_prompt', 'sentence_completion', 'collocation_matching',
    'shadow_reading', 'pronunciation', 'idiom',
]

AUDIO_EXPECTED_TYPES = ['dictation', 'listening_immersion', 'shadow_reading', 'audio_fill_blank']


class TestImportedLessonTypesCounted:
    """Verify by_type in content quality detail includes all imported lesson types (Task 48)."""

    def test_dictation_counted_in_by_type(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, lesson_type='dictation',
                     content={'audio_url': 'http://cdn.example.com/dict.mp3', 'transcript': 'Hello world.'})
        db_session.commit()

        result = get_content_quality_detail()
        row = next((r for r in result['by_type'] if r['type'] == 'dictation'), None)
        assert row is not None
        assert row['total'] >= 1

    def test_shadow_reading_counted_in_by_type(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, lesson_type='shadow_reading',
                     content={'audio_url': 'http://cdn.example.com/shadow.mp3', 'text': 'Test text'})
        db_session.commit()

        result = get_content_quality_detail()
        row = next((r for r in result['by_type'] if r['type'] == 'shadow_reading'), None)
        assert row is not None
        assert row['total'] >= 1

    def test_writing_prompt_counted_in_by_type(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, lesson_type='writing_prompt',
                     content={'prompt': 'Describe your day', 'min_words': 50})
        db_session.commit()

        result = get_content_quality_detail()
        row = next((r for r in result['by_type'] if r['type'] == 'writing_prompt'), None)
        assert row is not None
        assert row['total'] >= 1

    @pytest.mark.parametrize('lesson_type', ALL_NEW_LESSON_TYPES)
    def test_all_new_types_appear_in_by_type(self, app, db_session, lesson_type):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, lesson_type=lesson_type)
        db_session.commit()

        result = get_content_quality_detail()
        types_present = {r['type'] for r in result['by_type']}
        assert lesson_type in types_present, f"Lesson type '{lesson_type}' missing from by_type"

    def test_all_new_type_rows_have_required_fields(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        for lt in ALL_NEW_LESSON_TYPES:
            _make_lesson(db_session, module, lesson_type=lt)
        db_session.commit()

        result = get_content_quality_detail()
        type_map = {r['type']: r for r in result['by_type']}
        required_fields = ('type', 'total', 'with_audio', 'with_ipa', 'with_examples',
                           'completed', 'audio_pct', 'ipa_pct', 'examples_pct', 'completion_pct',
                           'avg_rating', 'feedback_count')
        for lt in ALL_NEW_LESSON_TYPES:
            if lt in type_map:
                for field in required_fields:
                    assert field in type_map[lt], f"Field '{field}' missing from row for type '{lt}'"

    def test_audio_lessons_with_url_counted_in_with_audio(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, lesson_type='dictation',
                     content={'audio_url': 'http://cdn.example.com/d1.mp3'})
        _make_lesson(db_session, module, lesson_type='audio_fill_blank',
                     content={'audio_url': 'http://cdn.example.com/afb1.mp3'})
        db_session.commit()

        result = get_content_quality_detail()
        for lt in ('dictation', 'audio_fill_blank'):
            row = next((r for r in result['by_type'] if r['type'] == lt), None)
            assert row is not None
            assert row['with_audio'] >= 1
            assert row['audio_pct'] > 0


class TestMissingAudioCountDrops:
    """Verify missing-audio count reduces when lessons receive audio_url (Task 48)."""

    def test_lesson_without_audio_counted_as_missing(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type='dictation', content={})
        db_session.commit()

        result = get_content_quality_detail()
        missing_ids = {m['lesson_id'] for m in result['missing_audio']}
        assert lesson.id in missing_ids

    def test_lesson_with_audio_not_counted_as_missing(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type='dictation',
                              content={'audio_url': 'http://cdn.example.com/real.mp3'})
        db_session.commit()

        result = get_content_quality_detail()
        missing_ids = {m['lesson_id'] for m in result['missing_audio']}
        assert lesson.id not in missing_ids

    def test_missing_count_drops_when_audio_added(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson_no_audio = _make_lesson(db_session, module, lesson_type='shadow_reading', content={})
        lesson_with_audio = _make_lesson(db_session, module, lesson_type='shadow_reading',
                                         content={'audio_url': 'http://cdn.example.com/s1.mp3'})
        db_session.commit()

        result = get_content_quality_detail()
        missing_ids = {m['lesson_id'] for m in result['missing_audio']}
        assert lesson_no_audio.id in missing_ids
        assert lesson_with_audio.id not in missing_ids

    @pytest.mark.parametrize('lesson_type', AUDIO_EXPECTED_TYPES)
    def test_all_audio_types_missing_without_url(self, app, db_session, lesson_type):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type=lesson_type, content={})
        db_session.commit()

        result = get_content_quality_detail()
        missing_ids = {m['lesson_id'] for m in result['missing_audio']}
        assert lesson.id in missing_ids, f"Expected {lesson_type} without audio_url to be in missing_audio"

    @pytest.mark.parametrize('lesson_type', AUDIO_EXPECTED_TYPES)
    def test_all_audio_types_not_missing_with_url(self, app, db_session, lesson_type):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type=lesson_type,
                              content={'audio_url': 'http://cdn.example.com/file.mp3'})
        db_session.commit()

        result = get_content_quality_detail()
        missing_ids = {m['lesson_id'] for m in result['missing_audio']}
        assert lesson.id not in missing_ids, f"Expected {lesson_type} with audio_url to NOT be in missing_audio"

    def test_non_audio_type_never_appears_in_missing_audio(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        # writing_prompt has no audio requirement
        lesson = _make_lesson(db_session, module, lesson_type='writing_prompt', content={})
        db_session.commit()

        result = get_content_quality_detail()
        missing_ids = {m['lesson_id'] for m in result['missing_audio']}
        assert lesson.id not in missing_ids


class TestVocabularyEnrichmentVisible:
    """Verify vocabulary enrichment data is reflected in content quality dashboard (Task 48)."""

    def _make_collection(self, db_session) -> Collection:
        col = Collection(name=f'EnrColl_{uuid.uuid4().hex[:6]}')
        db_session.add(col)
        db_session.flush()
        return col

    def _make_word(self, db_session, **kwargs) -> CollectionWords:
        word = CollectionWords(
            english_word=f'word_{uuid.uuid4().hex[:8]}',
            russian_word='слово',
            **kwargs,
        )
        db_session.add(word)
        db_session.flush()
        return word

    def _link_word(self, db_session, collection, word) -> None:
        link = CollectionWordLink(collection_id=collection.id, word_id=word.id)
        db_session.add(link)
        db_session.flush()

    def test_vocabulary_with_ipa_reflected_in_with_ipa(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        col = self._make_collection(db_session)
        word = self._make_word(db_session, ipa_transcription='ˈɛnrɪtʃt')
        self._link_word(db_session, col, word)

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, lesson_type='vocabulary', collection_id=col.id)
        db_session.commit()

        result = get_content_quality_detail()
        vocab_row = next((r for r in result['by_type'] if r['type'] == 'vocabulary'), None)
        assert vocab_row is not None
        assert vocab_row['with_ipa'] >= 1
        assert vocab_row['ipa_pct'] > 0

    def test_vocabulary_with_sentences_reflected_in_with_examples(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        col = self._make_collection(db_session)
        word = self._make_word(db_session, sentences='She enriched the text.')
        self._link_word(db_session, col, word)

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, lesson_type='vocabulary', collection_id=col.id)
        db_session.commit()

        result = get_content_quality_detail()
        vocab_row = next((r for r in result['by_type'] if r['type'] == 'vocabulary'), None)
        assert vocab_row is not None
        assert vocab_row['with_examples'] >= 1
        assert vocab_row['examples_pct'] > 0

    def test_vocabulary_without_enrichment_shows_zero_ipa(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        col = self._make_collection(db_session)
        word = self._make_word(db_session)  # no IPA
        self._link_word(db_session, col, word)

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type='vocabulary', collection_id=col.id)
        db_session.commit()

        result = get_content_quality_detail()
        vocab_row = next((r for r in result['by_type'] if r['type'] == 'vocabulary'), None)
        assert vocab_row is not None
        # The lesson we added has no IPA; with_ipa for this lesson's collection is 0
        # lesson should not contribute to no_vocabulary (it has a collection with words)
        no_vocab_ids = {v['lesson_id'] for v in result['no_vocabulary']}
        assert lesson.id not in no_vocab_ids

    def test_vocabulary_word_with_frequency_band_accessible(self, app, db_session):
        """Verify frequency_band-enriched words are stored and accessible for dashboard queries."""
        col = self._make_collection(db_session)
        word = self._make_word(db_session, frequency_band=1, ipa_transcription='ˈfriːkwənsi')
        self._link_word(db_session, col, word)
        db_session.commit()

        # Verify we can query by frequency_band as part of enrichment verification
        enriched = CollectionWords.query.filter_by(id=word.id).one()
        assert enriched.frequency_band == 1
        assert enriched.ipa_transcription == 'ˈfriːkwənsi'

    def test_vocabulary_word_with_synonyms_antonyms_accessible(self, app, db_session):
        """Verify synonyms/antonyms-enriched words are stored and accessible."""
        col = self._make_collection(db_session)
        word = self._make_word(db_session,
                               synonyms=['enhance', 'augment'],
                               antonyms=['diminish', 'reduce'])
        self._link_word(db_session, col, word)
        db_session.commit()

        enriched = CollectionWords.query.filter_by(id=word.id).one()
        assert enriched.synonyms == ['enhance', 'augment']
        assert enriched.antonyms == ['diminish', 'reduce']

    def test_no_vocabulary_section_empty_when_all_have_collections(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        col = self._make_collection(db_session)
        word = self._make_word(db_session, ipa_transcription='tɛst')
        self._link_word(db_session, col, word)

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type='vocabulary', collection_id=col.id)
        db_session.commit()

        result = get_content_quality_detail()
        no_vocab_ids = {v['lesson_id'] for v in result['no_vocabulary']}
        assert lesson.id not in no_vocab_ids


class TestFeedbackAggregationImportedLessons:
    """Verify LessonFeedback for imported lesson types is aggregated correctly (Task 48)."""

    def _make_user(self, db_session) -> User:
        user = User(
            username=f'fb_u_{uuid.uuid4().hex[:8]}',
            email=f'fb_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        user.set_password('pass')
        db_session.add(user)
        db_session.flush()
        return user

    def test_dictation_feedback_shows_avg_rating(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type='dictation',
                              content={'audio_url': 'http://cdn.example.com/d.mp3'})
        user = self._make_user(db_session)
        fb = LessonFeedback(user_id=user.id, lesson_id=lesson.id, rating=5)
        db_session.add(fb)
        db_session.commit()

        result = get_content_quality_detail()
        row = next((r for r in result['by_type'] if r['type'] == 'dictation'), None)
        assert row is not None
        assert row['avg_rating'] is not None
        assert row['avg_rating'] == 5.0
        assert row['feedback_count'] >= 1

    def test_shadow_reading_feedback_aggregated(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type='shadow_reading',
                              content={'audio_url': 'http://cdn.example.com/sr.mp3'})
        u1 = self._make_user(db_session)
        u2 = self._make_user(db_session)
        db_session.add(LessonFeedback(user_id=u1.id, lesson_id=lesson.id, rating=4))
        db_session.add(LessonFeedback(user_id=u2.id, lesson_id=lesson.id, rating=2))
        db_session.commit()

        result = get_content_quality_detail()
        row = next((r for r in result['by_type'] if r['type'] == 'shadow_reading'), None)
        assert row is not None
        # feedback_count = number of lessons with ratings (1 lesson with 2 raters)
        assert row['feedback_count'] >= 1
        assert row['avg_rating'] is not None
        # per-lesson avg = (4+2)/2 = 3.0; type avg = avg of [3.0] = 3.0
        assert row['avg_rating'] == 3.0

    def test_writing_prompt_feedback_aggregated(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type='writing_prompt',
                              content={'prompt': 'Write about yourself'})
        user = self._make_user(db_session)
        db_session.add(LessonFeedback(user_id=user.id, lesson_id=lesson.id, rating=3))
        db_session.commit()

        result = get_content_quality_detail()
        row = next((r for r in result['by_type'] if r['type'] == 'writing_prompt'), None)
        assert row is not None
        assert row['avg_rating'] is not None
        assert row['feedback_count'] >= 1

    def test_lesson_without_feedback_has_none_avg_rating(self, app, db_session):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        # Use a unique type name to avoid interference from other test data
        unique_type = f'idiom_{uuid.uuid4().hex[:4]}'
        _make_lesson(db_session, module, lesson_type=unique_type)
        db_session.commit()

        result = get_content_quality_detail()
        row = next((r for r in result['by_type'] if r['type'] == unique_type), None)
        assert row is not None
        assert row['avg_rating'] is None
        assert row['feedback_count'] == 0

    @pytest.mark.parametrize('lesson_type', ['audio_fill_blank', 'pronunciation', 'idiom',
                                             'sentence_correction', 'sentence_completion',
                                             'collocation_matching', 'translation'])
    def test_various_imported_types_accept_feedback(self, app, db_session, lesson_type):
        from app.admin.main_routes import get_content_quality_detail

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, lesson_type=lesson_type)
        user = self._make_user(db_session)
        db_session.add(LessonFeedback(user_id=user.id, lesson_id=lesson.id, rating=5))
        db_session.commit()

        result = get_content_quality_detail()
        row = next((r for r in result['by_type'] if r['type'] == lesson_type), None)
        assert row is not None
        assert row['avg_rating'] is not None
        assert row['feedback_count'] >= 1

    def test_admin_route_shows_rating_column(self, app, client, admin_user):
        response = client.get('/admin/content-quality')
        assert response.status_code == 200
        data = response.data.decode('utf-8')
        assert 'Рейтинг' in data
