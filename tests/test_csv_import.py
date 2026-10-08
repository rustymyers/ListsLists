from sqlalchemy import select

from app.database import SessionLocal
from app.models import CanonicalItem, User
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
