from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CanonicalItem, User

CSV_HEADERS = (
    "name",
    "description",
    "unit",
    "category",
    "tags",
    "storage_location",
    "usage_context",
    "notes",
    "identity_key",
)


@dataclass(frozen=True)
class ImportResult:
    created: int
    skipped: int


def _text(row: Mapping[str, str], field: str) -> str:
    return (row.get(field) or "").strip()


def _existing_item(
    session: Session, owner_id: str, name: str, unit: str, identity_key: str
) -> CanonicalItem | None:
    stmt = select(CanonicalItem).where(CanonicalItem.owner_id == owner_id)
    if identity_key:
        return session.scalar(stmt.where(CanonicalItem.identity_key == identity_key))
    return session.scalar(
        stmt.where(
            func.lower(CanonicalItem.name) == name.lower(),
            func.lower(CanonicalItem.unit) == unit.lower(),
            CanonicalItem.identity_key.is_(None),
        )
    )


def import_canonical_items(
    session: Session,
    owner: User,
    rows: Iterable[Mapping[str, str]],
    *,
    dry_run: bool = False,
) -> ImportResult:
    created = 0
    skipped = 0
    seen: set[tuple[str, ...]] = set()
    for line_number, row in enumerate(rows, start=2):
        name = _text(row, "name")
        unit = _text(row, "unit") or "each"
        identity_key = _text(row, "identity_key")
        if not name:
            raise ValueError(f"Row {line_number}: name is required")
        key = (
            ("identity", identity_key)
            if identity_key
            else ("name-unit", name.lower(), unit.lower())
        )
        if key in seen or _existing_item(session, owner.id, name, unit, identity_key):
            skipped += 1
            seen.add(key)
            continue
        seen.add(key)
        created += 1
        if dry_run:
            continue
        session.add(
            CanonicalItem(
                owner_id=owner.id,
                name=name,
                description=_text(row, "description"),
                unit=unit,
                category=_text(row, "category") or None,
                tags=[
                    tag.strip()
                    for tag in _text(row, "tags").split(",")
                    if tag.strip()
                ],
                storage_location=_text(row, "storage_location") or None,
                usage_context=_text(row, "usage_context") or None,
                notes=_text(row, "notes"),
                identity_key=identity_key or None,
            )
        )
    return ImportResult(created=created, skipped=skipped)
