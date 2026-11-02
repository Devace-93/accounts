"""Add ``users.preferred_currency`` (lowercase ISO 4217, nullable; the
``currency`` JWT claim and ``user.preferred_currency`` in the API).

Idempotent like 0001: ``python -m dbcore.cli upgrade`` runs ``create_all``
first, so on a fresh database the column already exists and is skipped.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-01 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if not _has_column("users", "preferred_currency"):
        op.add_column("users", sa.Column("preferred_currency", sa.String(length=3), nullable=True))


def downgrade() -> None:
    if _has_column("users", "preferred_currency"):
        op.drop_column("users", "preferred_currency")
