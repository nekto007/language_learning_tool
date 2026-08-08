"""Clear `["null"]` literals from collection_words synonyms/antonyms.

Audit CNT-019 (cross-zone audit 2026-08-08). A backfill wrote the *string*
"null" instead of an empty value: 1728 rows in `antonyms` and 180 in `synonyms`
hold the literal `["null"]`.

The lesson UI hides it — `_clean_word_list` in
`app/curriculum/routes/vocabulary_lessons.py` drops "null"/"none"/"n/a"/"-" —
but every other consumer sees a populated list. Two concrete consequences: any
new reader renders «Антонимы: null», and the metadata-coverage number the admin
dashboard reports (CNT-018) is inflated by roughly twice, because these rows
count as filled.

`NULL` is the established "no data" state for these columns (20146 rows already
use it), so that is what the literals become. Verified before writing: no other
junk form (`"-"`, `"n/a"`, `[]`) occurs in this table, so the sweep is exactly
these two shapes and nothing else.

Data-only and idempotent. Not reversible in a meaningful sense — downgrade is a
no-op on purpose: restoring a placeholder that never carried information would
re-introduce the defect.

Revision ID: 20260808_clear_null_literal_word_lists
Revises: 20260808_normalize_module_prerequisites
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op

revision = '20260808_clear_null_literal_word_lists'
down_revision = '20260808_normalize_module_prerequisites'
branch_labels = None
depends_on = None

NULL_LITERAL = '["null"]'


COLUMNS = ('synonyms', 'antonyms')


def clear_null_literals(conn) -> int:
    """Blank the literals. Returns the number of rows touched."""
    touched = 0
    for column in COLUMNS:
        result = conn.execute(
            sa.text(
                f'UPDATE collection_words SET {column} = NULL '  # noqa: S608 — fixed identifier list
                f'WHERE {column}::text = :literal'
            ),
            {'literal': NULL_LITERAL},
        )
        touched += result.rowcount or 0
    return touched


def upgrade():
    clear_null_literals(op.get_bind())


def downgrade():
    """No-op: the literal carried no information, so there is nothing to restore."""
