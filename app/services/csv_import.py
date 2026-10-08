from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CanonicalItem, ListItem, ListModel, User, Visibility
from app.services.lists import unique_slug

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
    "list_name",
    "list_description",
    "list_visibility",
    "quantity",
    "packing_spot",
    "is_required",
)


@dataclass(frozen=True)
class ImportResult:
    created: int
    skipped: int
    lists_created: int
    placements_created: int
    placements_skipped: int


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


def _owned_list(session: Session, owner_id: str, name: str) -> ListModel | None:
    matches = session.scalars(
        select(ListModel).where(
            ListModel.owner_id == owner_id,
            ListModel.deleted_at.is_(None),
            func.lower(ListModel.name) == name.lower(),
        )
    ).all()
    if len(matches) > 1:
        raise ValueError(f'Multiple owned lists match "{name}"; use a unique list name')
    return matches[0] if matches else None


def _visibility(value: str) -> Visibility:
    try:
        return Visibility(value or Visibility.private.value)
    except ValueError as exc:
        values = ", ".join(member.value for member in Visibility)
        raise ValueError(f"list_visibility must be one of: {values}") from exc


def _quantity(value: str, line_number: int) -> float:
    try:
        quantity = float(value or 1)
    except ValueError as exc:
        raise ValueError(f"Row {line_number}: quantity must be a number") from exc
    if quantity < 0:
        raise ValueError(f"Row {line_number}: quantity cannot be negative")
    return quantity


def _is_required(value: str, line_number: int) -> bool:
    if not value:
        return True
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"Row {line_number}: is_required must be true or false")


def import_canonical_items(
    session: Session,
    owner: User,
    rows: Iterable[Mapping[str, str]],
    *,
    dry_run: bool = False,
) -> ImportResult:
    created = 0
    skipped = 0
    lists_created = 0
    placements_created = 0
    placements_skipped = 0
    canonical_by_key: dict[tuple[str, ...], CanonicalItem] = {}
    lists_by_name: dict[str, ListModel] = {}
    seen_placements: set[tuple[str, tuple[str, ...]]] = set()
    for line_number, row in enumerate(rows, start=2):
        name = _text(row, "name")
        unit = _text(row, "unit") or "each"
        identity_key = _text(row, "identity_key")
        list_name = _text(row, "list_name")
        if not name:
            raise ValueError(f"Row {line_number}: name is required")
        key = (
            ("identity", identity_key)
            if identity_key
            else ("name-unit", name.lower(), unit.lower())
        )
        canonical = canonical_by_key.get(key) or _existing_item(
            session, owner.id, name, unit, identity_key
        )
        if canonical:
            skipped += 1
        else:
            canonical = CanonicalItem(
                owner_id=owner.id,
                name=name,
                description=_text(row, "description"),
                unit=unit,
                category=_text(row, "category") or None,
                tags=[tag.strip() for tag in _text(row, "tags").split(",") if tag.strip()],
                storage_location=_text(row, "storage_location") or None,
                usage_context=_text(row, "usage_context") or None,
                notes=_text(row, "notes"),
                identity_key=identity_key or None,
            )
            canonical_by_key[key] = canonical
            created += 1
            if not dry_run:
                session.add(canonical)
                session.flush()
        if not list_name:
            continue
        list_key = list_name.lower()
        list_obj = lists_by_name.get(list_key) or _owned_list(session, owner.id, list_name)
        if not list_obj:
            list_obj = ListModel(
                name=list_name,
                slug=unique_slug(session, list_name),
                description=_text(row, "list_description"),
                visibility=_visibility(_text(row, "list_visibility")),
                owner_id=owner.id,
            )
            lists_created += 1
            if not dry_run:
                session.add(list_obj)
                session.flush()
        lists_by_name[list_key] = list_obj
        placement_key = (list_key, key)
        existing_placement = (
            not dry_run
            and session.scalar(
                select(ListItem.id).where(
                    ListItem.list_id == list_obj.id,
                    ListItem.canonical_item_id == canonical.id,
                )
            )
        )
        if placement_key in seen_placements or existing_placement:
            placements_skipped += 1
            continue
        seen_placements.add(placement_key)
        placements_created += 1
        if dry_run:
            continue
        position = session.scalar(
            select(func.max(ListItem.position)).where(ListItem.list_id == list_obj.id)
        )
        session.add(
            ListItem(
                list_id=list_obj.id,
                canonical_item_id=canonical.id,
                name=canonical.name,
                description=canonical.description,
                quantity=_quantity(_text(row, "quantity"), line_number),
                packing_spot=_text(row, "packing_spot") or None,
                unit=canonical.unit,
                category=canonical.category,
                tags=list(canonical.tags),
                storage_location=canonical.storage_location,
                usage_context=canonical.usage_context,
                is_required=_is_required(_text(row, "is_required"), line_number),
                notes=canonical.notes,
                position=(position if position is not None else -1) + 1,
                identity_key=canonical.identity_key,
                conditional_requirements=dict(canonical.conditional_requirements),
                custom_metadata=dict(canonical.custom_metadata),
            )
        )
        session.flush()
    return ImportResult(
        created=created,
        skipped=skipped,
        lists_created=lists_created,
        placements_created=placements_created,
        placements_skipped=placements_skipped,
    )
