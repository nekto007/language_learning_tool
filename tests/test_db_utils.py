"""Tests for app/utils/db_utils.py — chunk_ids and query_by_ids helpers."""
import pytest

from app.utils.db_utils import chunk_ids


@pytest.mark.smoke
class TestChunkIds:
    def test_empty_list_yields_nothing(self):
        result = list(chunk_ids([]))
        assert result == []

    def test_list_smaller_than_chunk_size(self):
        ids = list(range(500))
        chunks = list(chunk_ids(ids, chunk_size=1000))
        assert len(chunks) == 1
        assert chunks[0] == ids

    def test_list_exactly_chunk_size(self):
        ids = list(range(1000))
        chunks = list(chunk_ids(ids, chunk_size=1000))
        assert len(chunks) == 1
        assert chunks[0] == ids

    def test_list_larger_than_chunk_size(self):
        ids = list(range(2500))
        chunks = list(chunk_ids(ids, chunk_size=1000))
        assert len(chunks) == 3
        assert chunks[0] == list(range(1000))
        assert chunks[1] == list(range(1000, 2000))
        assert chunks[2] == list(range(2000, 2500))

    def test_all_ids_preserved_across_chunks(self):
        ids = list(range(3500))
        chunks = list(chunk_ids(ids, chunk_size=1000))
        reconstructed = [item for chunk in chunks for item in chunk]
        assert reconstructed == ids

    def test_custom_chunk_size(self):
        ids = list(range(10))
        chunks = list(chunk_ids(ids, chunk_size=3))
        assert len(chunks) == 4
        assert chunks[0] == [0, 1, 2]
        assert chunks[3] == [9]

    def test_single_element_list(self):
        chunks = list(chunk_ids([42]))
        assert chunks == [[42]]

    def test_default_chunk_size_is_1000(self):
        ids = list(range(1001))
        chunks = list(chunk_ids(ids))
        assert len(chunks) == 2
        assert len(chunks[0]) == 1000
        assert len(chunks[1]) == 1
