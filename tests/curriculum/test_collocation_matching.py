"""Tests for collocation matching exercise type — Task 31."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.curriculum.grading import grade_collocation_matching
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.validators import LessonContentValidator
from tests.conftest import unique_level_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_collocation_matching_lesson(db_session, *, pairs=None) -> Lessons:
    if pairs is None:
        pairs = [
            {"phrase": "make a decision", "translation": "принять решение"},
            {"phrase": "break the rules", "translation": "нарушать правила"},
            {"phrase": "take a risk", "translation": "идти на риск"},
        ]
    level = CEFRLevel(code=unique_level_code(), name="Level", description="d", order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title="Collocation Module",
        description="d",
        raw_content={"module": {"id": 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Collocation Matching",
        type="collocation_matching",
        content={"pairs": pairs},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------

class TestCollocationMatchingValidator:
    def test_valid_payload_passes(self):
        ok, err, _ = LessonContentValidator.validate(
            'collocation_matching',
            {
                "pairs": [
                    {"phrase": "make a decision", "translation": "принять решение"},
                    {"phrase": "break the rules", "translation": "нарушать правила"},
                ]
            }
        )
        assert ok is True
        assert err is None

    def test_missing_pairs_fails(self):
        from marshmallow import ValidationError
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate('collocation_matching', {})

    def test_empty_pairs_fails(self):
        from marshmallow import ValidationError
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate('collocation_matching', {"pairs": []})

    def test_pair_missing_phrase_fails(self):
        from marshmallow import ValidationError
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate(
                'collocation_matching',
                {"pairs": [{"translation": "принять решение"}]}
            )

    def test_pair_missing_translation_fails(self):
        from marshmallow import ValidationError
        with pytest.raises((ValidationError, Exception)):
            LessonContentValidator.validate(
                'collocation_matching',
                {"pairs": [{"phrase": "make a decision"}]}
            )


# ---------------------------------------------------------------------------
# Grader tests
# ---------------------------------------------------------------------------

class TestGradeCollocationMatching:
    def _pairs(self):
        return [
            {"phrase": "make a decision", "translation": "принять решение"},
            {"phrase": "break the rules", "translation": "нарушать правила"},
            {"phrase": "take a risk", "translation": "идти на риск"},
        ]

    def test_all_correct_returns_100(self):
        pairs = self._pairs()
        result = grade_collocation_matching(pairs[:], pairs)
        assert result['score'] == 100
        assert result['passed'] is True
        assert result['correct_items'] == 3
        assert result['total_items'] == 3

    def test_all_wrong_returns_0(self):
        pairs = self._pairs()
        user_pairs = [
            {"phrase": "make a decision", "translation": "нарушать правила"},
            {"phrase": "break the rules", "translation": "идти на риск"},
            {"phrase": "take a risk", "translation": "принять решение"},
        ]
        result = grade_collocation_matching(user_pairs, pairs)
        assert result['score'] == 0
        assert result['passed'] is False
        assert result['correct_items'] == 0

    def test_partial_score(self):
        pairs = self._pairs()
        user_pairs = [
            {"phrase": "make a decision", "translation": "принять решение"},  # correct
            {"phrase": "break the rules", "translation": "идти на риск"},      # wrong
            {"phrase": "take a risk", "translation": "принять решение"},       # wrong
        ]
        result = grade_collocation_matching(user_pairs, pairs)
        assert result['correct_items'] == 1
        assert result['total_items'] == 3
        assert result['score'] == 33

    def test_empty_user_pairs_returns_0(self):
        pairs = self._pairs()
        result = grade_collocation_matching([], pairs)
        assert result['score'] == 0
        assert result['correct_items'] == 0

    def test_empty_correct_pairs_returns_0(self):
        result = grade_collocation_matching([], [])
        assert result['score'] == 0
        assert result['passed'] is False

    def test_pair_results_included(self):
        pairs = self._pairs()
        result = grade_collocation_matching(pairs[:], pairs)
        assert len(result['pair_results']) == 3
        assert all(pr['correct'] for pr in result['pair_results'])

    def test_wrong_answer_has_correct_translation_in_results(self):
        pairs = self._pairs()
        user_pairs = [
            {"phrase": "make a decision", "translation": "нарушать правила"},
            {"phrase": "break the rules", "translation": "принять решение"},
            {"phrase": "take a risk", "translation": "идти на риск"},
        ]
        result = grade_collocation_matching(user_pairs, pairs)
        # pair_results should contain the correct translations
        decision_result = next(pr for pr in result['pair_results'] if pr['phrase'] == 'make a decision')
        assert decision_result['correct'] is False
        assert decision_result['translation'] == 'принять решение'

    def test_case_insensitive_match(self):
        pairs = [{"phrase": "Make A Decision", "translation": "Принять Решение"}]
        user_pairs = [{"phrase": "make a decision", "translation": "принять решение"}]
        result = grade_collocation_matching(user_pairs, pairs)
        assert result['correct_items'] == 1

    def test_passes_when_score_70_percent(self):
        pairs = [
            {"phrase": "p1", "translation": "t1"},
            {"phrase": "p2", "translation": "t2"},
            {"phrase": "p3", "translation": "t3"},
            {"phrase": "p4", "translation": "t4"},
            {"phrase": "p5", "translation": "t5"},
            {"phrase": "p6", "translation": "t6"},
            {"phrase": "p7", "translation": "t7"},
            {"phrase": "p8", "translation": "t8"},
            {"phrase": "p9", "translation": "t9"},
            {"phrase": "p10", "translation": "t10"},
        ]
        user_pairs = pairs[:7]  # correct 7 out of 10 = 70%
        result = grade_collocation_matching(user_pairs, pairs)
        assert result['score'] == 70
        assert result['passed'] is True


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

def _read_template() -> str:
    p = (
        Path(__file__).parent.parent.parent
        / "app"
        / "templates"
        / "curriculum"
        / "lessons"
        / "collocation_matching.html"
    )
    return p.read_text(encoding="utf-8")


class TestCollocationMatchingTemplate:
    def test_template_exists(self):
        tpl = _read_template()
        assert len(tpl) > 100

    def test_phrase_cards_rendered(self):
        tpl = _read_template()
        assert "collocation-phrase-card" in tpl

    def test_translation_cards_rendered(self):
        tpl = _read_template()
        assert "collocation-translation-card" in tpl

    def test_live_handlers_present(self):
        # Live-flow rewrite: per-pair check runs client-side via tryPair →
        # handleCorrect / handleWrong. A final submit to the server happens
        # once all pairs are matched (finalizeLesson).
        tpl = _read_template()
        assert "function tryPair" in tpl
        assert "function handleCorrect" in tpl
        assert "function handleWrong" in tpl
        assert "function finalizeLesson" in tpl

    def test_result_area_present(self):
        tpl = _read_template()
        assert 'id="matching-result"' in tpl

    def test_matched_zone_present(self):
        # "Готовые пары" zone replaces the old per-pair-results-list — it
        # receives a row each time a pair is successfully matched live.
        tpl = _read_template()
        assert 'id="cm-matched-zone"' in tpl
        assert 'id="cm-matched-list"' in tpl

    def test_shuffled_pairs_used(self):
        tpl = _read_template()
        assert "shuffled_pairs" in tpl

    def test_no_check_or_reset_buttons(self):
        # Live-flow design: no batched "Проверить" / "Сбросить" buttons.
        # Each pair is validated instantly; incorrect attempts auto-clear.
        tpl = _read_template()
        assert "submitMatching()" not in tpl
        assert "resetMatching()" not in tpl
        assert "id=\"submit-btn\"" not in tpl
        assert "id=\"reset-btn\"" not in tpl

    def test_correct_translation_embedded_for_client_check(self):
        # phraseData carries the canonical answer so tryPair() can validate
        # a (phrase, translation) click without a network round-trip.
        tpl = _read_template()
        assert "correctTranslation:" in tpl

    def test_uses_lesson_shell(self):
        tpl = _read_template()
        assert "lesson-shell" in tpl
        assert "lesson-shell__header" in tpl
        assert "lesson-shell__body" in tpl

    def test_uses_option_btn(self):
        tpl = _read_template()
        assert "option-btn" in tpl

    def test_submit_payload_includes_lesson_type(self):
        tpl = _read_template()
        assert "lesson_type: 'collocation_matching'" in tpl

    def test_daily_plan_uses_refreshed_submit_context(self):
        tpl = _read_template()
        assert "function renderFinalState(nextLessonUrl, dailyPlanCtx)" in tpl
        assert "const dpSource = dailyPlanCtx || DAILY_PLAN_CTX;" in tpl
        assert "renderFinalState(data.next_lesson_url, data.daily_plan_ctx);" in tpl

    def test_flash_classes_present(self):
        # Live-feedback classes drive the green pulse / red shake transitions.
        tpl = _read_template()
        assert "option-btn--correct-flash" in tpl
        assert "option-btn--wrong-flash" in tpl

    def test_speech_synthesis_button_wired(self):
        # P1.6 audio support — Web Speech Synthesis works in all major browsers
        # without server-side audio file generation.
        tpl = _read_template()
        assert "speakPhrase" in tpl
        assert "speechSynthesis" in tpl
        assert "cm-speak-btn" in tpl


# ---------------------------------------------------------------------------
# Route tests — GET
# ---------------------------------------------------------------------------

class TestCollocationMatchingLessonRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        lesson = _make_collocation_matching_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/collocation-matching")
        assert resp.status_code == 200

    def test_get_contains_phrase(self, app, db_session, test_user, client):
        lesson = _make_collocation_matching_lesson(
            db_session,
            pairs=[{"phrase": "make progress", "translation": "добиваться успеха"}],
        )
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/collocation-matching")
        assert "make progress" in resp.get_data(as_text=True)

    def test_lesson_detail_redirects_to_collocation_route(self, app, db_session, test_user, client):
        lesson = _make_collocation_matching_lesson(db_session)
        _login(client, test_user)
        resp = client.get(f"/curriculum/lesson/{lesson.id}", follow_redirects=False)
        assert resp.status_code == 302
        assert "collocation-matching" in resp.headers.get("Location", "")

    def test_get_creates_lesson_progress(self, app, db_session, test_user, client):
        lesson = _make_collocation_matching_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/collocation-matching")
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "in_progress"

    def test_unauthenticated_redirects(self, app, db_session, client):
        lesson = _make_collocation_matching_lesson(db_session)
        resp = client.get(f"/curriculum/lesson/{lesson.id}/collocation-matching")
        assert resp.status_code in (302, 401, 403)


# ---------------------------------------------------------------------------
# Route tests — POST submit
# ---------------------------------------------------------------------------

class TestCollocationMatchingSubmitRoute:
    def _submit(self, client, lesson_id: int, user_pairs: list):
        return client.post(
            f"/curriculum/api/lesson/{lesson_id}/submit",
            json={"user_pairs": user_pairs},
            content_type="application/json",
        )

    def _all_correct_pairs(self):
        return [
            {"phrase": "make a decision", "translation": "принять решение"},
            {"phrase": "break the rules", "translation": "нарушать правила"},
            {"phrase": "take a risk", "translation": "идти на риск"},
        ]

    def test_all_correct_returns_100(self, app, db_session, test_user, client):
        lesson = _make_collocation_matching_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/collocation-matching")
        resp = self._submit(client, lesson.id, self._all_correct_pairs())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["score"] == 100
        assert data["passed"] is True

    def test_wrong_pairs_expose_canonical_for_correction(self, app, db_session, test_user, client):
        """On failure the route must return the canonical translation for every
        pair so the template can render a "Правильно: <phrase> → <answer>"
        correction line. The lesson is teaching — withholding the answer would
        leave the learner with no way to learn from the mistake.
        ``user_translation`` still echoes the learner's submission so the UI
        can show what they actually picked side-by-side with the correction.
        """
        lesson = _make_collocation_matching_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/collocation-matching")
        submitted = {
            "make a decision": "нарушать правила",
            "break the rules": "идти на риск",
            "take a risk": "принять решение",
        }
        canonical = {
            "make a decision": "принять решение",
            "break the rules": "нарушать правила",
            "take a risk": "идти на риск",
        }
        wrong_pairs = [{"phrase": p, "translation": t} for p, t in submitted.items()]
        resp = self._submit(client, lesson.id, wrong_pairs)
        data = resp.get_json()
        assert data["passed"] is False
        pr = data.get("pair_results", [])
        assert pr, "pair_results must be populated"
        for row in pr:
            phrase = row["phrase"]
            assert row.get("correct") is False
            assert row.get("translation") == canonical[phrase]
            assert row.get("user_translation") == submitted[phrase]
            assert row.get("user_translation") != canonical[phrase]

    def test_partial_score_calculated(self, app, db_session, test_user, client):
        lesson = _make_collocation_matching_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/collocation-matching")
        partial_pairs = [
            {"phrase": "make a decision", "translation": "принять решение"},  # correct
            {"phrase": "break the rules", "translation": "идти на риск"},      # wrong
            {"phrase": "take a risk", "translation": "нарушать правила"},      # wrong
        ]
        resp = self._submit(client, lesson.id, partial_pairs)
        data = resp.get_json()
        assert data["correct_items"] == 1
        assert data["total_items"] == 3

    def test_partial_failure_returns_canonical_for_every_row(
        self, app, db_session, test_user, client
    ):
        """On a failed-but-partial submission, every row keeps the canonical
        translation. Correct rows show "✓ phrase → translation"; wrong rows
        show "✗ phrase → user_translation" plus a "Правильно: phrase →
        translation" correction underneath. Both branches need the canonical
        answer in ``translation``.
        """
        lesson = _make_collocation_matching_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/collocation-matching")
        partial_pairs = [
            {"phrase": "make a decision", "translation": "принять решение"},  # correct
            {"phrase": "break the rules", "translation": "идти на риск"},      # wrong
            {"phrase": "take a risk", "translation": "нарушать правила"},      # wrong
        ]
        resp = self._submit(client, lesson.id, partial_pairs)
        data = resp.get_json()
        assert data["passed"] is False
        rows = {pr["phrase"]: pr for pr in data["pair_results"]}
        assert rows["make a decision"]["correct"] is True
        assert rows["make a decision"]["translation"] == "принять решение"
        assert rows["break the rules"]["correct"] is False
        assert rows["break the rules"]["translation"] == "нарушать правила"
        assert rows["break the rules"]["user_translation"] == "идти на риск"
        assert rows["take a risk"]["correct"] is False
        assert rows["take a risk"]["translation"] == "идти на риск"
        assert rows["take a risk"]["user_translation"] == "нарушать правила"

    def test_correct_submission_marks_progress_completed(self, app, db_session, test_user, client):
        lesson = _make_collocation_matching_lesson(db_session)
        _login(client, test_user)
        client.get(f"/curriculum/lesson/{lesson.id}/collocation-matching")
        self._submit(client, lesson.id, self._all_correct_pairs())
        progress = LessonProgress.query.filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert progress is not None
        assert progress.status == "completed"

    def test_unauthenticated_submit_redirects(self, app, db_session, client):
        lesson = _make_collocation_matching_lesson(db_session)
        resp = client.post(
            f"/curriculum/api/lesson/{lesson.id}/submit",
            json={"user_pairs": []},
        )
        assert resp.status_code in (302, 401, 403)
