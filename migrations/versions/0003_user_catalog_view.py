"""Persist each user's catalog display preference."""

from alembic import op
import sqlalchemy as sa

revision = "0003_user_catalog_view"
down_revision = "0002_canonical_items"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "catalog_view",
            sa.String(10),
            nullable=False,
            server_default="cards",
        ),
    )


def downgrade():
    op.drop_column("users", "catalog_view")
