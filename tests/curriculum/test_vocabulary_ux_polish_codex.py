"""Adversarial state-integrity guards for lesson-audit item 9."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.curriculum.models import LessonProgress
from app.curriculum.routes.vocabulary_lessons import (
    _autoplay_default,
    _vocabulary_resume_state,
)
from tests.curriculum.test_vocabulary_ux_polish import (
    _lesson,
    _login,
    _progress_url,
    _unique,
    _word_item,
)


class TestResumeSnapshotIntegrity:

    def test_only_in_progress_rows_can_resume(self):
        stale = SimpleNamespace(
            status='not_started',
            data={'card_index': 2, 'presented': [0, 1, 2], 'total_cards': 20},
        )
        assert _vocabulary_resume_state(stale, 20) is None

    def test_changed_deck_size_invalidates_snapshot(self):
        stale = SimpleNamespace(
            status='in_progress',
            data={'card_index': 18, 'presented': [0, 1, 18], 'total_cards': 19},
        )
        assert _vocabulary_resume_state(stale, 20) is None

    def test_current_index_must_have_been_presented(self):
        crafted = SimpleNamespace(
            status='in_progress',
            data={'card_index': 19, 'presented': [0, 1, 2], 'total_cards': 20},
        )
        assert _vocabulary_resume_state(crafted, 20) == {
            'index': 2,
            'presented': [0, 1, 2],
        }

    def test_flipped_cards_survive_resume_for_final_analytics(self):
        progress = SimpleNamespace(
            status='in_progress',
            data={
                'card_index': 4,
                'presented': [0, 1, 2, 3, 4],
                'flipped': [0, 2, 4],
                'total_cards': 5,
            },
        )
        assert _vocabulary_resume_state(progress, 5) == {
            'index': 4,
            'presented': [0, 1, 2, 3, 4],
            'flipped': [0, 2, 4],
        }
        source = Path('app/templates/curriculum/lessons/vocabulary.html').read_text(encoding='utf-8')
        assert 'flipped: Array.from(cardsState.flippedCards)' in source
        assert 'resume.flipped.forEach' in source


class TestCompletionRaceIntegrity:

    def test_late_snapshot_cannot_change_completed_score_or_data_even_if_crafted(
        self, app, db_session, test_user, client
    ):
        lesson = _lesson(
            db_session,
            'A2',
            [_word_item(_unique('race'), 'т') for _ in range(2)],
        )
        _login(client, test_user)
        url = _progress_url(app, lesson)
        final_data = {'cards_viewed': 2, 'total_cards': 2, 'flipped_count': 2}
        done = client.post(url, json={
            'status': 'completed', 'score': 100, 'data': final_data,
        })
        assert done.status_code == 200

        # The real client does not send score, but the server-side race guard
        # should discard the entire in-progress snapshot rather than letting a
        # crafted/old client alter last_score on a completed row.
        late = client.post(url, json={
            'status': 'in_progress',
            'score': 1,
            'data': {'card_index': 0, 'presented': [0], 'total_cards': 2},
        })
        assert late.status_code == 200
        progress = db_session.query(LessonProgress).filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).one()
        assert progress.status == 'completed'
        assert progress.score == 100 and progress.last_score == 100
        assert progress.data == final_data

    def test_data_only_snapshot_cannot_overwrite_completed_payload(
        self, app, db_session, test_user, client
    ):
        lesson = _lesson(
            db_session,
            'A2',
            [_word_item(_unique('data'), 'т') for _ in range(2)],
        )
        _login(client, test_user)
        url = _progress_url(app, lesson)
        final_data = {'cards_viewed': 2, 'total_cards': 2, 'flipped_count': 2}
        assert client.post(url, json={
            'status': 'completed', 'score': 100, 'data': final_data,
        }).status_code == 200

        # Status is optional in the generic schema; a snapshot-shaped payload
        # must not bypass the completed-row protection by omitting it.
        data_only = client.post(url, json={
            'data': {'card_index': 1, 'presented': [0, 1], 'total_cards': 2},
        })
        assert data_only.status_code == 200
        progress = db_session.query(LessonProgress).filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).one()
        assert progress.status == 'completed' and progress.data == final_data


class TestAutoplayPolicy:

    def test_a0_is_not_silently_added_to_the_a1_a2_owner_decision(self):
        assert _autoplay_default('A0') is False
        assert _autoplay_default('A1') is True
        assert _autoplay_default('A2') is True
