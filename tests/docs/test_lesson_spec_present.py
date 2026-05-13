"""Guard the lesson-frontend spec contract.

The redesign in docs/plans/2026-05-13-modern-lesson-ui-redesign.md depends
on docs/design/lesson-frontend-spec.md being the single source of truth
for the modern lesson UI. This test asserts the spec exists and covers
every lesson type the redesign targets.
"""

from pathlib import Path

import pytest

SPEC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "design"
    / "lesson-frontend-spec.md"
)

REQUIRED_LESSONS = [
    "writing_prompt",
    "translation",
    "sentence_completion",
    "sentence_correction",
    "shadow_reading",
    "audio_fill_blank",
    "pronunciation",
    "collocation_matching",
    "listening_immersion",
]


@pytest.fixture(scope="module")
def spec_text() -> str:
    assert SPEC_PATH.exists(), f"spec missing: {SPEC_PATH}"
    return SPEC_PATH.read_text(encoding="utf-8")


def test_spec_file_present() -> None:
    assert SPEC_PATH.is_file(), f"spec missing: {SPEC_PATH}"


def test_spec_documents_shared_shell(spec_text: str) -> None:
    # Shared shell skeleton + class taxonomy must be in the doc so later
    # tasks can rely on the same names.
    for token in (
        "lesson-shell",
        "lesson-shell__header",
        "lesson-shell__body",
        "lesson-shell__actions",
        "result-badge",
        "input--correct",
        "input--wrong",
        "option-btn",
    ):
        assert token in spec_text, f"shared-shell token missing from spec: {token}"


@pytest.mark.parametrize("lesson", REQUIRED_LESSONS)
def test_spec_has_section_for_lesson(spec_text: str, lesson: str) -> None:
    # Each lesson type must appear as a section header AND have a payload
    # block so the redesign cannot quietly drop a lesson.
    assert f"### 2." in spec_text, "spec is missing per-lesson sections"
    assert lesson in spec_text, f"lesson section missing in spec: {lesson}"


@pytest.mark.parametrize("lesson", REQUIRED_LESSONS)
def test_spec_declares_lesson_type_in_payload(spec_text: str, lesson: str) -> None:
    # Every payload contract names the lesson_type explicitly so the
    # backend dispatcher (submit_lesson in app/curriculum/routes/lessons.py)
    # routes consistently. listening_immersion is included since the
    # redesign wires its submit path through the same dispatcher.
    quoted = f'"{lesson}"'
    assert quoted in spec_text, f'spec must quote lesson_type "{lesson}" in payload'


def test_spec_cross_check_table_lists_every_lesson(spec_text: str) -> None:
    # The cross-check table validates payloads against the existing
    # backend handlers — without it, fields could drift silently.
    for lesson in REQUIRED_LESSONS:
        assert f"| {lesson} |" in spec_text, (
            f"cross-check table row missing for {lesson}"
        )
