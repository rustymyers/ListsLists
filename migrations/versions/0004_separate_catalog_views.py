"""Store independent list and item catalog display preferences."""

from alembic import op
import sqlalchemy as sa

revision = "0004_separate_catalog_views"
down_revision = "0003_user_catalog_view"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("list_view", sa.String(10), nullable=False, server_default="cards"),
    )
    op.add_column(
        "users",
        sa.Column("item_view", sa.String(10), nullable=False, server_default="cards"),
    )
    op.execute(
        "UPDATE users SET list_view = catalog_view, item_view = catalog_view"
    )


def downgrade():
    op.drop_column("users", "item_view")
    op.drop_column("users", "list_view")
