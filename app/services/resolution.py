import csv
import io
import json
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import ItemDependency, ListItem, ListModel, User
from app.permissions import can_view
from app.schemas import ResolutionOptions


@dataclass
class ResolvedItem:
    identity: str
    name: str
    description: str
    quantity: float
    unit: str
    category: str | None
    tags: list[str]
    storage_location: str | None
    usage_context: str | None
    is_required: bool
    notes: str
    packing_spots: list[str] = field(default_factory=list)
    source_list_ids: list[str] = field(default_factory=list)
    source_item_ids: list[str] = field(default_factory=list)
    custom_metadata: dict[str, Any] = field(default_factory=dict)


class ListResolver:
    def __init__(self, db: Session, user: User | None, options: ResolutionOptions):
        self.db = db
        self.user = user
        self.options = options

    def resolve(self, root: ListModel) -> list[ResolvedItem]:
        raw = self._walk(root, path=[])
        if self.options.expand_dependencies:
            raw = self._expand_dependencies(raw)
        result = self._merge(raw) if self.options.merge_duplicates else raw
        for item in result:
            item.quantity *= self.options.quantity_multiplier
            if self.options.round_quantity is not None:
                item.quantity = round(item.quantity, self.options.round_quantity)
            if not self.options.preserve_source:
                item.source_list_ids = []
                item.source_item_ids = []
        reverse = self.options.sort_direction == "desc"
        sorters = {
            "position": lambda row: raw.index(row) if row in raw else 0,
            "name": lambda row: row.name.lower(),
            "category": lambda row: ((row.category or "").lower(), row.name.lower()),
            "location": lambda row: ((row.storage_location or "").lower(), row.name.lower()),
        }
        sort_name = "category" if self.options.group_by_category else self.options.sort_by
        result.sort(key=sorters[sort_name], reverse=reverse)
        return result

    def _list(self, list_id: str) -> ListModel:
        obj = self.db.scalar(
            select(ListModel)
            .where(ListModel.id == list_id)
            .options(selectinload(ListModel.items).selectinload(ListItem.dependencies))
        )
        if not obj or obj.deleted_at is not None:
            raise HTTPException(404, detail="Referenced list was not found")
        return obj

    def _walk(self, list_obj: ListModel, path: list[str], multiplier: float = 1.0) -> list[ResolvedItem]:
        if list_obj.id in path:
            raise HTTPException(409, detail="Circular list reference detected during resolution")
        # Nested lists never inherit the root's unlisted-link access.
        if path and not can_view(self.db, self.user, list_obj, allow_unlisted=False):
            raise HTTPException(403, detail="A nested list is not accessible to the current viewer")
        output: list[ResolvedItem] = []
        for item in sorted(list_obj.items, key=lambda value: value.position):
            if not item.is_required and not self.options.include_optional:
                continue
            if item.referenced_list_id:
                nested = self._list(item.referenced_list_id)
                output.extend(self._walk(nested, path + [list_obj.id], multiplier * item.quantity))
            else:
                output.append(self._from_item(item, list_obj.id, multiplier))
        return output

    @staticmethod
    def _from_item(item: ListItem, list_id: str, multiplier: float) -> ResolvedItem:
        return ResolvedItem(
            identity=item.identity_key or item.id,
            name=item.name,
            description=item.description,
            quantity=item.quantity * multiplier,
            unit=item.unit,
            category=item.category,
            tags=list(item.tags),
            storage_location=item.storage_location,
            usage_context=item.usage_context,
            is_required=item.is_required,
            notes=item.notes,
            packing_spots=[item.packing_spot] if item.packing_spot else [],
            source_list_ids=[list_id],
            source_item_ids=[item.id],
            custom_metadata=dict(item.custom_metadata),
        )

    def _merge(self, rows: list[ResolvedItem]) -> list[ResolvedItem]:
        merged: OrderedDict[str, ResolvedItem] = OrderedDict()
        compare_fields = ("name", "unit", "category", "storage_location", "usage_context")
        for row in rows:
            if row.identity not in merged:
                merged[row.identity] = row
                continue
            existing = merged[row.identity]
            conflicts = [name for name in compare_fields if getattr(existing, name) != getattr(row, name)]
            if conflicts and self.options.conflict_strategy == "error":
                raise HTTPException(409, detail=f"Conflicting duplicate attributes: {', '.join(conflicts)}")
            if conflicts and self.options.conflict_strategy == "last":
                for name in compare_fields:
                    setattr(existing, name, getattr(row, name))
                existing.description = row.description
                existing.notes = row.notes
                existing.custom_metadata = row.custom_metadata
            if self.options.combine_quantities:
                if existing.unit != row.unit:
                    raise HTTPException(409, detail="Cannot combine duplicate quantities with different units")
                existing.quantity += row.quantity
            existing.tags = list(dict.fromkeys(existing.tags + row.tags))
            existing.packing_spots = list(
                dict.fromkeys(existing.packing_spots + row.packing_spots)
            )
            existing.source_list_ids = list(dict.fromkeys(existing.source_list_ids + row.source_list_ids))
            existing.source_item_ids = list(dict.fromkeys(existing.source_item_ids + row.source_item_ids))
            existing.is_required = existing.is_required or row.is_required
        return list(merged.values())

    def _expand_dependencies(self, rows: list[ResolvedItem]) -> list[ResolvedItem]:
        seen = {source for row in rows for source in row.source_item_ids}
        frontier = set(seen)
        while frontier:
            dependencies = self.db.scalars(
                select(ItemDependency)
                .where(ItemDependency.item_id.in_(frontier))
                .options(selectinload(ItemDependency.depends_on))
            ).all()
            frontier = set()
            for dependency in dependencies:
                dep = dependency.depends_on
                if dep.id not in seen:
                    rows.append(self._from_item(dep, dep.list_id, 1.0))
                    seen.add(dep.id)
                    frontier.add(dep.id)
        return rows


def rows_as_dicts(rows: list[ResolvedItem]) -> list[dict[str, Any]]:
    return [asdict(row) for row in rows]


def export_json(rows: list[ResolvedItem], list_obj: ListModel) -> bytes:
    data = {"list": {"id": list_obj.id, "name": list_obj.name, "slug": list_obj.slug}, "items": rows_as_dicts(rows)}
    return json.dumps(data, indent=2).encode()


def export_csv(rows: list[ResolvedItem]) -> bytes:
    output = io.StringIO()
    fields = ["identity", "name", "description", "quantity", "unit", "category", "tags", "storage_location", "usage_context", "is_required", "notes", "packing_spots", "source_list_ids", "source_item_ids", "custom_metadata"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for data in rows_as_dicts(rows):
        data["tags"] = ";".join(data["tags"])
        data["packing_spots"] = ";".join(data["packing_spots"])
        data["source_list_ids"] = ";".join(data["source_list_ids"])
        data["source_item_ids"] = ";".join(data["source_item_ids"])
        data["custom_metadata"] = json.dumps(data["custom_metadata"], separators=(",", ":"))
        writer.writerow(data)
    return output.getvalue().encode("utf-8-sig")
