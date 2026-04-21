"""Tests for ``app.daily_plan.linear.context``.

Covers:
- ``LinearSlotKind`` enum values (stable, used in query-param strings).
- ``build_slot_url`` appends ``from=linear_plan&slot=<kind>`` correctly.
- Existing query params survive the append.
- Fragment-only and empty URLs pass through unchanged.
- Duplicate ``from``/``slot`` params in the input are overwritten, not
  stacked.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from app.daily_plan.linear.context import (
    FROM_QUERY_KEY,
    PLAN_CONTEXT_SOURCE,
    SLOT_QUERY_KEY,
    LinearSlotKind,
    build_slot_url,
)


class TestLinearSlotKind:
    def test_all_four_kinds_present(self):
        # Stability: these strings are surfaced via query-params and read
        # by the frontend. Changing a value breaks saved sessionStorage
        # contexts, so these must remain stable.
        assert LinearSlotKind.CURRICULUM.value == 'curriculum'
        assert LinearSlotKind.SRS.value == 'srs'
        assert LinearSlotKind.BOOK.value == 'book'
        assert LinearSlotKind.ERROR_REVIEW.value == 'error_review'

    def test_kind_count_is_exactly_four(self):
        assert len(list(LinearSlotKind)) == 4

    def test_values_serialize_as_str(self):
        # LinearSlotKind is a str enum, so urlencode sees the raw value.
        assert str(LinearSlotKind.CURRICULUM.value) == 'curriculum'


class TestBuildSlotUrlBasics:
    def test_appends_context_to_plain_url(self):
        url = build_slot_url('/learn/42/', LinearSlotKind.CURRICULUM)

        parts = urlsplit(url)
        assert parts.path == '/learn/42/'
        params = parse_qs(parts.query)
        assert params[FROM_QUERY_KEY] == [PLAN_CONTEXT_SOURCE]
        assert params[SLOT_QUERY_KEY] == ['curriculum']

    @pytest.mark.parametrize(
        'kind, expected_slot',
        [
            (LinearSlotKind.CURRICULUM, 'curriculum'),
            (LinearSlotKind.SRS, 'srs'),
            (LinearSlotKind.BOOK, 'book'),
            (LinearSlotKind.ERROR_REVIEW, 'error_review'),
        ],
    )
    def test_slot_param_for_each_kind(self, kind, expected_slot):
        url = build_slot_url('/x', kind)

        params = parse_qs(urlsplit(url).query)
        assert params[SLOT_QUERY_KEY] == [expected_slot]
        assert params[FROM_QUERY_KEY] == [PLAN_CONTEXT_SOURCE]

    def test_preserves_existing_query_params(self):
        url = build_slot_url(
            '/learn/99/?source=linear_plan_card', LinearSlotKind.CURRICULUM
        )

        params = parse_qs(urlsplit(url).query)
        assert params['source'] == ['linear_plan_card']
        assert params[FROM_QUERY_KEY] == [PLAN_CONTEXT_SOURCE]
        assert params[SLOT_QUERY_KEY] == ['curriculum']

    def test_preserves_multiple_existing_params(self):
        url = build_slot_url('/study?a=1&b=2', LinearSlotKind.SRS)

        params = parse_qs(urlsplit(url).query)
        assert params['a'] == ['1']
        assert params['b'] == ['2']
        assert params[FROM_QUERY_KEY] == [PLAN_CONTEXT_SOURCE]
        assert params[SLOT_QUERY_KEY] == ['srs']

    def test_preserves_fragment(self):
        url = build_slot_url('/read/1#chapter-2', LinearSlotKind.BOOK)

        parts = urlsplit(url)
        assert parts.path == '/read/1'
        assert parts.fragment == 'chapter-2'
        params = parse_qs(parts.query)
        assert params[SLOT_QUERY_KEY] == ['book']


class TestBuildSlotUrlOverwriteExistingContext:
    def test_stale_from_param_is_overwritten(self):
        url = build_slot_url('/x?from=telegram', LinearSlotKind.CURRICULUM)

        params = parse_qs(urlsplit(url).query)
        assert params[FROM_QUERY_KEY] == [PLAN_CONTEXT_SOURCE]

    def test_stale_slot_param_is_overwritten(self):
        url = build_slot_url('/x?slot=srs', LinearSlotKind.CURRICULUM)

        params = parse_qs(urlsplit(url).query)
        assert params[SLOT_QUERY_KEY] == ['curriculum']

    def test_both_stale_context_params_overwritten(self):
        url = build_slot_url(
            '/x?from=oldsource&slot=oldkind&keep=me', LinearSlotKind.BOOK
        )

        params = parse_qs(urlsplit(url).query)
        assert params[FROM_QUERY_KEY] == [PLAN_CONTEXT_SOURCE]
        assert params[SLOT_QUERY_KEY] == ['book']
        assert params['keep'] == ['me']


class TestBuildSlotUrlEdgeCases:
    @pytest.mark.parametrize('empty', [None, ''])
    def test_empty_url_passed_through(self, empty):
        assert build_slot_url(empty, LinearSlotKind.CURRICULUM) == empty

    def test_fragment_only_url_passed_through(self):
        # ``#book-select-modal`` opens a dashboard modal and does not
        # navigate to a real page — appending query params would be a no-op
        # at best and potentially confusing, so leave it alone.
        assert (
            build_slot_url('#book-select-modal', LinearSlotKind.BOOK)
            == '#book-select-modal'
        )


class TestSlotBuildersUseContext:
    """Higher-level smoke: the 4 slot builders each produce a URL that
    carries ``from=linear_plan&slot=<kind>`` — no slot builder regresses
    back to the legacy naked ``?from=linear_plan`` format."""

    def test_curriculum_slot_uses_context(self):
        from app.daily_plan.linear.slots.curriculum_slot import _lesson_url

        class _FakeLesson:
            id = 7
            type = 'vocabulary'

        url = _lesson_url(_FakeLesson())
        params = parse_qs(urlsplit(url).query)
        assert params[FROM_QUERY_KEY] == [PLAN_CONTEXT_SOURCE]
        assert params[SLOT_QUERY_KEY] == ['curriculum']

    def test_curriculum_card_slot_preserves_source_and_adds_context(self):
        from app.daily_plan.linear.slots.curriculum_slot import _lesson_url

        class _FakeLesson:
            id = 11
            type = 'card'

        url = _lesson_url(_FakeLesson())
        params = parse_qs(urlsplit(url).query)
        assert params['source'] == ['linear_plan_card']
        assert params[FROM_QUERY_KEY] == [PLAN_CONTEXT_SOURCE]
        assert params[SLOT_QUERY_KEY] == ['curriculum']
