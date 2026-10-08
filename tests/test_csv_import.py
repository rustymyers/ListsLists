from sqlalchemy import select

from app.database import SessionLocal
from app.models import CanonicalItem, ListItem, ListModel, User, Visibility
from app.services.csv_import import import_canonical_items


def test_csv_import_creates_new_items_and_skips_existing_identity_keys():
    rows = [
        {
            "name": "Tent",
            "unit": "each",
            "tags": "camping, lightweight",
            "identity_key": "tent-two-person",
        },
        {
            "name": "Tent copy",
            "unit": "each",
            "identity_key": "tent-two-person",
        },
    ]
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.username == "admin"))
        result = import_canonical_items(db, owner, rows)
        db.commit()

        items = db.scalars(select(CanonicalItem)).all()

    assert result.created == 1
    assert result.skipped == 1
    assert items[0].name == "Tent"
    assert items[0].tags == ["camping", "lightweight"]


def test_csv_import_dry_run_does_not_create_items():
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.username == "admin"))
        result = import_canonical_items(
            db,
            owner,
            [{"name": "Tent", "unit": "each"}],
            dry_run=True,
        )

        assert db.scalars(select(CanonicalItem)).all() == []

    assert result.created == 1
    assert result.skipped == 0


def test_csv_import_creates_lists_and_adds_items_to_existing_lists():
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.username == "admin"))
        existing = ListModel(
            name="Existing",
            slug="existing",
            owner_id=owner.id,
            visibility=Visibility.private,
        )
        db.add(existing)
        db.commit()
        result = import_canonical_items(
            db,
            owner,
            [
                {
                    "name": "Tent",
                    "unit": "each",
                    "identity_key": "tent",
                    "list_name": "New trip",
                    "list_description": "Packing list",
                    "list_visibility": "shared",
                    "quantity": "2",
                    "packing_spot": "Blue bin",
                    "is_required": "true",
                },
                {
                    "name": "Lantern",
                    "unit": "each",
                    "identity_key": "lantern",
                    "list_name": "New trip",
                },
                {
                    "name": "Tent",
                    "unit": "each",
                    "identity_key": "tent",
                    "list_name": "Existing",
                    "quantity": "1",
                },
            ],
        )
        db.commit()

        created_list = db.scalar(select(ListModel).where(ListModel.name == "New trip"))
        placements = db.scalars(
            select(ListItem).where(ListItem.list_id == created_list.id).order_by(ListItem.position)
        ).all()
        existing_placements = db.scalars(
            select(ListItem).where(ListItem.list_id == existing.id)
        ).all()

    assert result.lists_created == 1
    assert result.placements_created == 3
    assert created_list.visibility == Visibility.shared
    assert [placement.position for placement in placements] == [0, 1]
    assert placements[0].quantity == 2
    assert placements[0].packing_spot == "Blue bin"
    assert len(existing_placements) == 1
