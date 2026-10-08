"""Add shared canonical items and list placement fields."""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0002_canonical_items"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "canonical_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("category", sa.String(120)),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("storage_location", sa.String(240)),
        sa.Column("usage_context", sa.String(240)),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("identity_key", sa.String(160)),
        sa.Column("conditional_requirements", sa.JSON(), nullable=False),
        sa.Column("custom_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_canonical_items_owner_id", "canonical_items", ["owner_id"])
    op.create_index("ix_canonical_items_name", "canonical_items", ["name"])
    op.create_index("ix_canonical_items_category", "canonical_items", ["category"])
    op.create_index("ix_canonical_items_identity_key", "canonical_items", ["identity_key"])
    op.add_column("list_items", sa.Column("canonical_item_id", sa.String(36), nullable=True))
    op.add_column("list_items", sa.Column("packing_spot", sa.String(240), nullable=True))
    op.create_foreign_key("fk_list_items_canonical_item_id", "list_items", "canonical_items", ["canonical_item_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_list_items_canonical_item_id", "list_items", ["canonical_item_id"])

    connection = op.get_bind()
    rows = connection.execute(sa.text(
        "SELECT id, list_id, name, description, unit, category, tags, storage_location, "
        "usage_context, notes, identity_key, conditional_requirements, custom_metadata, "
        "created_at, updated_at FROM list_items"
    )).mappings()
    lists = sa.table("lists", sa.column("id", sa.String), sa.column("owner_id", sa.String))
    canonical = sa.table(
        "canonical_items", *[sa.column(name) for name in (
            "id", "owner_id", "name", "description", "unit", "category", "tags",
            "storage_location", "usage_context", "notes", "identity_key",
            "conditional_requirements", "custom_metadata", "created_at", "updated_at",
        )],
    )
    for row in rows:
        owner_id = connection.execute(sa.select(lists.c.owner_id).where(lists.c.id == row["list_id"])).scalar_one()
        canonical_id = str(uuid4())
        values = dict(row)
        values["id"] = canonical_id
        values["owner_id"] = owner_id
        connection.execute(canonical.insert().values(**values))
        connection.execute(
            sa.text("UPDATE list_items SET canonical_item_id = :canonical_id WHERE id = :item_id"),
            {"canonical_id": canonical_id, "item_id": row["id"]},
        )


def downgrade():
    op.drop_index("ix_list_items_canonical_item_id", table_name="list_items")
    op.drop_constraint("fk_list_items_canonical_item_id", "list_items", type_="foreignkey")
    op.drop_column("list_items", "packing_spot")
    op.drop_column("list_items", "canonical_item_id")
    op.drop_index("ix_canonical_items_identity_key", table_name="canonical_items")
    op.drop_index("ix_canonical_items_category", table_name="canonical_items")
    op.drop_index("ix_canonical_items_name", table_name="canonical_items")
    op.drop_index("ix_canonical_items_owner_id", table_name="canonical_items")
    op.drop_table("canonical_items")
