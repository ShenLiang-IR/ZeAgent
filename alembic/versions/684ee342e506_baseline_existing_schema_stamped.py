"""baseline: existing schema stamped

Revision ID: 684ee342e506
Revises:
Create Date: 2026-07-19 13:04:08.366109

Baseline migration: marks the existing schema (already created by
rebuild_tables.py / migrate_trigger_schema.py / migrate_audit_log_schema.py etc.)
as alembic baseline. Do NOT run `upgrade` on this migration (it's empty);
use `alembic stamp 684ee342e506` to mark current DB as baseline.

Future schema changes should autogenerate new revisions after this baseline:
  alembic revision --autogenerate -m "add tb_xxx"
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '684ee342e506'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Baseline upgrade: pass (schema already exists)."""
    pass


def downgrade() -> None:
    """Baseline downgrade: pass (cannot drop existing schema)."""
    pass
