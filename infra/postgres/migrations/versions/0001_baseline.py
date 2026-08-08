"""baseline — empty starting point for the migration chain

Revision ID: 0001_baseline
Revises:
Create Date: Sprint 0 Task 0.3

Deliberately creates nothing. Applying it only establishes the
``alembic_version`` table, giving Sprint 1 Task 1.6's ``0002_full_schema`` a
parent revision to chain onto.

Every table, enum type, foreign key, and index in
``ZIP_13_ENGINEERING_CONTRACTS/DATABASE_SCHEMA.md`` §1-§18 belongs to that later
revision, whose Definition of Done is a line-by-line DDL diff against the
contract. Adding any schema object here would split that diff across two files
and break it.
"""

from __future__ import annotations

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: see module docstring."""


def downgrade() -> None:
    """No-op: nothing was created."""
