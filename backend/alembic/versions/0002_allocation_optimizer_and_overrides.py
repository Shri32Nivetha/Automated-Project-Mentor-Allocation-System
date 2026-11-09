"""allocation optimiser metadata and administrator override audit

Adds nullable / defaulted columns only, so existing allocations and history rows are preserved unchanged.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18 09:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # allocations: how the match was classified, and whether an admin overrode domain compatibility
    op.add_column("allocations", sa.Column("match_tier", sa.String(length=12), nullable=True))
    op.add_column("allocations", sa.Column("matched_domains", sa.JSON(), nullable=True))
    op.add_column("allocations", sa.Column("is_override", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("allocations", sa.Column("override_reason", sa.Text(), nullable=True))
    op.add_column("allocations", sa.Column("auto_recommendation", sa.JSON(), nullable=True))
    # allocation_history: structured audit of overrides
    op.add_column("allocation_history", sa.Column("is_override", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("allocation_history", sa.Column("domain_violation", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("allocation_history", sa.Column("capacity_violation", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("allocation_history", sa.Column("projected_load", sa.Integer(), nullable=True))
    op.add_column("allocation_history", sa.Column("capacity_at_time", sa.Integer(), nullable=True))
    op.add_column("allocation_history", sa.Column("details", sa.JSON(), nullable=True))


def downgrade() -> None:
    for col in ("details", "capacity_at_time", "projected_load", "capacity_violation", "domain_violation", "is_override"):
        op.drop_column("allocation_history", col)
    for col in ("auto_recommendation", "override_reason", "is_override", "matched_domains", "match_tier"):
        op.drop_column("allocations", col)
