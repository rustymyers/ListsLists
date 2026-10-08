import json
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    CanonicalItem,
    ExportProfile,
    ItemDependency,
    ListItem,
    ListModel,
    ListShare,
    PasswordResetToken,
    ShareRole,
    User,
    Visibility,
)

BACKUP_FORMAT = "listslists-backup"
BACKUP_VERSION = 1


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_timestamp(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _rows(session: Session, model: type, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            field: _timestamp(value)
            if isinstance(value := getattr(row, field), datetime)
            else value
            for field in fields
        }
        for row in session.scalars(select(model)).all()
    ]


def export_backup(session: Session) -> bytes:
    users = [
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_admin": user.is_admin,
            "is_active": user.is_active,
            "auth_source": user.auth_source,
            "created_at": _timestamp(user.created_at),
            "updated_at": _timestamp(user.updated_at),
        }
        for user in session.scalars(select(User)).all()
    ]
    return json.dumps(
        {
            "format": BACKUP_FORMAT,
            "version": BACKUP_VERSION,
            "users": users,
            "lists": _rows(
                session,
                ListModel,
                (
                    "id", "name", "slug", "description", "owner_id", "visibility",
                    "default_sort", "custom_metadata", "archived", "deleted_at",
                    "created_at", "updated_at",
                ),
            ),
            "canonical_items": _rows(
                session,
                CanonicalItem,
                (
                    "id", "owner_id", "name", "description", "unit", "category", "tags",
                    "storage_location", "usage_context", "notes", "identity_key",
                    "conditional_requirements", "custom_metadata", "created_at", "updated_at",
                ),
            ),
            "list_items": _rows(
                session,
                ListItem,
                (
                    "id", "list_id", "canonical_item_id", "name", "description", "quantity",
                    "packing_spot", "unit", "category", "tags", "storage_location",
                    "usage_context", "is_required", "notes", "position", "referenced_list_id",
                    "identity_key", "conditional_requirements", "custom_metadata", "created_at",
                    "updated_at",
                ),
            ),
            "item_dependencies": _rows(
                session,
                ItemDependency,
                ("id", "item_id", "depends_on_item_id", "condition", "required"),
            ),
            "list_shares": _rows(
                session, ListShare, ("id", "list_id", "user_id", "role", "created_at")
            ),
            "export_profiles": _rows(
                session,
                ExportProfile,
                ("id", "owner_id", "name", "format", "options", "created_at", "updated_at"),
            ),
        },
        default=lambda value: value.value if isinstance(value, (Visibility, ShareRole)) else value,
        indent=2,
    ).encode()


def _require_backup(payload: Any, current_user_id: str) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ValueError("Import file must contain a JSON object")
    if payload.get("format") != BACKUP_FORMAT or payload.get("version") != BACKUP_VERSION:
        raise ValueError("Import file is not a supported ListsLists backup")
    sections = (
        "users", "lists", "canonical_items", "list_items", "item_dependencies",
        "list_shares", "export_profiles",
    )
    if any(not isinstance(payload.get(section), list) for section in sections):
        raise ValueError("Import file is missing one or more required data sections")
    users = payload["users"]
    if not any(
        row.get("id") == current_user_id and row.get("is_admin") and row.get("is_active")
        for row in users
        if isinstance(row, dict)
    ):
        raise ValueError("Import must retain the current active administrator account")
    if not any(
        row.get("is_admin") and row.get("is_active")
        for row in users
        if isinstance(row, dict)
    ):
        raise ValueError("Import must contain at least one active administrator")
    if any(not isinstance(row, dict) for section in sections for row in payload[section]):
        raise ValueError("Every import record must be a JSON object")
    return {section: payload[section] for section in sections}


def import_backup(session: Session, payload: Any, current_user_id: str) -> None:
    data = _require_backup(payload, current_user_id)
    session.execute(delete(ItemDependency))
    session.execute(delete(ListShare))
    session.execute(delete(ListItem))
    session.execute(delete(CanonicalItem))
    session.execute(delete(ExportProfile))
    session.execute(delete(PasswordResetToken))
    session.execute(delete(ListModel))
    session.execute(delete(User))

    for row in data["users"]:
        session.add(
            User(
                id=row["id"],
                username=row["username"],
                email=row["email"],
                password_hash=None,
                is_admin=row["is_admin"],
                is_active=row["is_active"],
                must_change_password=row.get("auth_source", "local") == "local",
                auth_source=row.get("auth_source", "local"),
                created_at=_parse_timestamp(row.get("created_at")),
                updated_at=_parse_timestamp(row.get("updated_at")),
            )
        )
    for row in data["lists"]:
        session.add(
            ListModel(
                **{
                    **row,
                    "visibility": Visibility(row["visibility"]),
                    "deleted_at": _parse_timestamp(row.get("deleted_at")),
                    "created_at": _parse_timestamp(row.get("created_at")),
                    "updated_at": _parse_timestamp(row.get("updated_at")),
                }
            )
        )
    for row in data["canonical_items"]:
        session.add(
            CanonicalItem(
                **{
                    **row,
                    "created_at": _parse_timestamp(row.get("created_at")),
                    "updated_at": _parse_timestamp(row.get("updated_at")),
                }
            )
        )
    for row in data["list_items"]:
        session.add(
            ListItem(
                **{
                    **row,
                    "created_at": _parse_timestamp(row.get("created_at")),
                    "updated_at": _parse_timestamp(row.get("updated_at")),
                }
            )
        )
    for row in data["item_dependencies"]:
        session.add(ItemDependency(**row))
    for row in data["list_shares"]:
        session.add(
            ListShare(
                **{
                    **row,
                    "role": ShareRole(row["role"]),
                    "created_at": _parse_timestamp(row.get("created_at")),
                }
            )
        )
    for row in data["export_profiles"]:
        session.add(
            ExportProfile(
                **{
                    **row,
                    "created_at": _parse_timestamp(row.get("created_at")),
                    "updated_at": _parse_timestamp(row.get("updated_at")),
                }
            )
        )
    session.flush()
