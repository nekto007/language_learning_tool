"""Unit tests for scripts/report_vocabulary_enrichment.py.

All tests use pure functions — no DB or Flask app required.
The --no-db guard in main() covers the DB skip path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from report_vocabulary_enrichment import (  # noqa: E402
    ENRICHMENT_FIELDS,
    EnrichmentReport,
    FieldCoverage,
    LevelRow,
    TierRow,
    assign_tier,
    build_report_from_words,
    compute_coverage_by_level,
    compute_coverage_by_tier,
    compute_overall_coverage,
    format_json,
    format_markdown,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _word(
    word_id: int = 1,
    level: str | None = "A1",
    ipa: bool = False,
    freq: bool = False,
    synonyms: bool = False,
    antonyms: bool = False,
    etymology: bool = False,
    collocations: bool = False,
    cultural_notes: bool = False,
    curriculum_lessons: int = 0,
    user_count: int = 0,
) -> dict:
    return {
        "word_id": word_id,
        "level": level,
        "ipa_transcription": ipa,
        "frequency_band": freq,
        "synonyms": synonyms,
        "antonyms": antonyms,
        "etymology": etymology,
        "collocations": collocations,
        "cultural_notes": cultural_notes,
        "curriculum_lessons": curriculum_lessons,
        "user_count": user_count,
    }


# ---------------------------------------------------------------------------
# assign_tier
# ---------------------------------------------------------------------------

class TestAssignTier:
    def test_a1_is_tier1(self):
        assert assign_tier("A1", 0, 0) == 1

    def test_a2_is_tier1(self):
        assert assign_tier("A2", 0, 0) == 1

    def test_b1_no_usage_is_tier2(self):
        assert assign_tier("B1", 0, 0) == 2

    def test_b2_no_usage_is_tier2(self):
        assert assign_tier("B2", 0, 0) == 2

    def test_c1_no_usage_is_tier3(self):
        assert assign_tier("C1", 0, 0) == 3

    def test_none_level_no_usage_is_tier3(self):
        assert assign_tier(None, 0, 0) == 3

    def test_high_curriculum_elevates_to_tier1(self):
        assert assign_tier("C2", 5, 0) == 1

    def test_many_users_elevates_to_tier1(self):
        assert assign_tier(None, 0, 4) == 1

    def test_one_curriculum_lesson_is_tier2(self):
        assert assign_tier(None, 1, 0) == 2

    def test_one_user_is_tier2(self):
        assert assign_tier(None, 0, 1) == 2


# ---------------------------------------------------------------------------
# FieldCoverage
# ---------------------------------------------------------------------------

class TestFieldCoverage:
    def test_pct_half_filled(self):
        fc = FieldCoverage(total=10, filled=5)
        assert fc.pct == 50.0

    def test_pct_zero_when_total_zero(self):
        fc = FieldCoverage(total=0, filled=0)
        assert fc.pct == 0.0

    def test_missing_is_complement(self):
        fc = FieldCoverage(total=10, filled=3)
        assert fc.missing == 7

    def test_to_dict_keys(self):
        fc = FieldCoverage(total=10, filled=4)
        d = fc.to_dict()
        assert set(d.keys()) == {"total", "filled", "missing", "pct"}


# ---------------------------------------------------------------------------
# compute_overall_coverage
# ---------------------------------------------------------------------------

class TestComputeOverallCoverage:
    def test_empty_words_gives_zero_coverage(self):
        cov = compute_overall_coverage([])
        for f in ENRICHMENT_FIELDS:
            assert cov[f].total == 0
            assert cov[f].filled == 0

    def test_all_fields_present_gives_100pct(self):
        words = [
            _word(1, ipa=True, freq=True, synonyms=True, antonyms=True,
                  etymology=True, collocations=True, cultural_notes=True)
        ]
        cov = compute_overall_coverage(words)
        for f in ENRICHMENT_FIELDS:
            assert cov[f].filled == 1
            assert cov[f].total == 1

    def test_no_fields_present_gives_zero(self):
        words = [_word(1), _word(2)]
        cov = compute_overall_coverage(words)
        for f in ENRICHMENT_FIELDS:
            assert cov[f].filled == 0
            assert cov[f].total == 2

    def test_partial_coverage_counted_correctly(self):
        words = [_word(1, ipa=True), _word(2, ipa=False), _word(3, ipa=True)]
        cov = compute_overall_coverage(words)
        assert cov["ipa_transcription"].filled == 2
        assert cov["ipa_transcription"].total == 3


# ---------------------------------------------------------------------------
# compute_coverage_by_level
# ---------------------------------------------------------------------------

class TestComputeCoverageByLevel:
    def test_groups_by_level(self):
        words = [_word(1, level="A1", ipa=True), _word(2, level="B1", ipa=False)]
        rows = compute_coverage_by_level(words)
        by_level = {r.level: r for r in rows}
        assert "A1" in by_level
        assert "B1" in by_level
        assert by_level["A1"].coverage["ipa_transcription"].filled == 1
        assert by_level["B1"].coverage["ipa_transcription"].filled == 0

    def test_none_level_grouped_as_none(self):
        words = [_word(1, level=None)]
        rows = compute_coverage_by_level(words)
        levels = [r.level for r in rows]
        assert "(none)" in levels

    def test_empty_cefr_levels_not_included(self):
        words = [_word(1, level="A1")]
        rows = compute_coverage_by_level(words)
        included_levels = [r.level for r in rows]
        # B1, B2, C1, C2 should be absent (no words)
        for absent in ("B1", "B2", "C1", "C2"):
            assert absent not in included_levels

    def test_total_words_per_level_correct(self):
        words = [_word(1, level="A2"), _word(2, level="A2"), _word(3, level="B1")]
        rows = compute_coverage_by_level(words)
        by_level = {r.level: r for r in rows}
        assert by_level["A2"].total_words == 2
        assert by_level["B1"].total_words == 1


# ---------------------------------------------------------------------------
# compute_coverage_by_tier
# ---------------------------------------------------------------------------

class TestComputeCoverageByTier:
    def test_always_returns_three_tiers(self):
        rows = compute_coverage_by_tier([])
        assert len(rows) == 3
        assert [r.tier for r in rows] == [1, 2, 3]

    def test_a1_word_goes_to_tier1(self):
        words = [_word(1, level="A1", ipa=True)]
        rows = compute_coverage_by_tier(words)
        tier1 = next(r for r in rows if r.tier == 1)
        assert tier1.total_words == 1
        assert tier1.coverage["ipa_transcription"].filled == 1

    def test_c1_no_usage_goes_to_tier3(self):
        words = [_word(1, level="C1")]
        rows = compute_coverage_by_tier(words)
        tier3 = next(r for r in rows if r.tier == 3)
        assert tier3.total_words == 1

    def test_mixed_tiers_distributed(self):
        words = [
            _word(1, level="A1"),  # tier 1
            _word(2, level="B1"),  # tier 2
            _word(3, level="C2"),  # tier 3
        ]
        rows = compute_coverage_by_tier(words)
        by_tier = {r.tier: r for r in rows}
        assert by_tier[1].total_words == 1
        assert by_tier[2].total_words == 1
        assert by_tier[3].total_words == 1


# ---------------------------------------------------------------------------
# build_report_from_words
# ---------------------------------------------------------------------------

class TestBuildReportFromWords:
    def test_total_words_correct(self):
        words = [_word(1), _word(2), _word(3)]
        report = build_report_from_words(words)
        assert report.total_words == 3

    def test_generated_at_is_set(self):
        report = build_report_from_words([])
        assert "T" in report.generated_at
        assert "Z" in report.generated_at

    def test_overall_contains_all_fields(self):
        report = build_report_from_words([_word(1)])
        assert set(report.overall.keys()) == set(ENRICHMENT_FIELDS)

    def test_by_level_is_list(self):
        report = build_report_from_words([_word(1, level="A1")])
        assert isinstance(report.by_level, list)
        assert report.by_level[0].level == "A1"

    def test_by_tier_has_three_entries(self):
        report = build_report_from_words([_word(1)])
        assert len(report.by_tier) == 3

    def test_to_dict_is_serialisable(self):
        report = build_report_from_words([_word(1, ipa=True)])
        d = report.to_dict()
        serialised = json.dumps(d)
        assert "ipa_transcription" in serialised


# ---------------------------------------------------------------------------
# format_markdown
# ---------------------------------------------------------------------------

class TestFormatMarkdown:
    def _simple_report(self) -> EnrichmentReport:
        return build_report_from_words([
            _word(1, level="A1", ipa=True, freq=True),
            _word(2, level="B1"),
        ])

    def test_contains_title(self):
        md = format_markdown(self._simple_report())
        assert "Vocabulary Enrichment Coverage Report" in md

    def test_contains_overall_section(self):
        md = format_markdown(self._simple_report())
        assert "Overall Coverage" in md

    def test_contains_cefr_level_section(self):
        md = format_markdown(self._simple_report())
        assert "A1" in md
        assert "B1" in md

    def test_contains_tier_section(self):
        md = format_markdown(self._simple_report())
        assert "Tier 1" in md
        assert "Tier 3" in md

    def test_all_enrichment_fields_present(self):
        md = format_markdown(self._simple_report())
        for f in ENRICHMENT_FIELDS:
            assert f in md

    def test_pct_bar_in_output(self):
        md = format_markdown(self._simple_report())
        assert "[" in md and "]" in md  # bar characters

    def test_db_error_surfaces_warning(self):
        report = self._simple_report()
        report.db_error = "connection refused"
        md = format_markdown(report)
        assert "WARNING" in md
        assert "connection refused" in md


# ---------------------------------------------------------------------------
# format_json
# ---------------------------------------------------------------------------

class TestFormatJson:
    def test_valid_json(self):
        report = build_report_from_words([_word(1)])
        text = format_json(report)
        parsed = json.loads(text)
        assert "total_words" in parsed
        assert "overall" in parsed
        assert "by_level" in parsed
        assert "by_tier" in parsed

    def test_total_words_in_json(self):
        report = build_report_from_words([_word(1), _word(2)])
        parsed = json.loads(format_json(report))
        assert parsed["total_words"] == 2

    def test_all_fields_in_overall(self):
        report = build_report_from_words([_word(1)])
        parsed = json.loads(format_json(report))
        assert set(parsed["overall"].keys()) == set(ENRICHMENT_FIELDS)


# ---------------------------------------------------------------------------
# main() --no-db guard
# ---------------------------------------------------------------------------

class TestMainNoDB:
    def test_no_db_exits_zero(self):
        assert main(["--no-db"]) == 0

    def test_no_db_writes_nothing(self, tmp_path: Path, capsys):
        out = tmp_path / "report.md"
        main(["--no-db", "--output", str(out)])
        assert not out.exists()
