"""Database utility helpers for common query patterns."""
from typing import Generator, List, TypeVar

T = TypeVar('T')


def chunk_ids(ids: list, chunk_size: int = 1000) -> Generator[list, None, None]:
    """Split a list of IDs into chunks to avoid large IN() clauses.

    Large IN() clauses can cause query plan degradation in PostgreSQL.
    This generator yields sub-lists of at most chunk_size elements.

    Args:
        ids: List of IDs to chunk.
        chunk_size: Maximum number of IDs per chunk (default 1000).

    Yields:
        Sub-lists of IDs, each at most chunk_size in length.
    """
    if not ids:
        return
    for i in range(0, len(ids), chunk_size):
        yield ids[i:i + chunk_size]


def query_by_ids(query_base, column, ids: list, chunk_size: int = 1000):
    """Execute a query filtering by a large list of IDs in chunks.

    Uses union_all under the hood when the list spans multiple chunks
    so a single result set is returned.

    Args:
        query_base: SQLAlchemy query object (e.g. Model.query).
        column: The column to filter on (e.g. Model.id).
        ids: List of ID values to include.
        chunk_size: Maximum IDs per IN() clause.

    Returns:
        List of model instances matching any of the given IDs.
    """
    if not ids:
        return []

    chunks = list(chunk_ids(ids, chunk_size))
    if len(chunks) == 1:
        return query_base.filter(column.in_(chunks[0])).all()

    queries = [query_base.filter(column.in_(chunk)) for chunk in chunks]
    combined = queries[0].union_all(*queries[1:])
    return combined.all()
