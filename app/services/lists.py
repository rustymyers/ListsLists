import re
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ItemDependency, ListItem, ListModel, User
from app.permissions import can_view
from app.schemas import ItemCreate, ItemUpdate, ListCreate


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "list"
    return slug[:200]


def unique_slug(db: Session, wanted: str, exclude_id: str | None = None) -> str:
    root = slugify(wanted)
    slug = root
    counter = 2
    while db.scalar(select(ListModel.id).where(ListModel.slug == slug, ListModel.id != exclude_id)):
        slug = f"{root[:190]}-{counter}"
        counter += 1
    return slug


def create_list(db: Session, data: ListCreate, owner: User) -> ListModel:
    obj = ListModel(
        name=data.name,
        slug=unique_slug(db, data.slug or data.name),
        description=data.description,
        visibility=data.visibility,
        custom_metadata=data.custom_metadata,
        owner_id=owner.id,
    )
    db.add(obj)
    db.flush()
    return obj


def would_create_cycle(db: Session, parent_list_id: str, referenced_list_id: str) -> bool:
    if parent_list_id == referenced_list_id:
        return True
    seen: set[str] = set()
    stack = [referenced_list_id]
    while stack:
        current = stack.pop()
        if current == parent_list_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(
            db.scalars(
                select(ListItem.referenced_list_id).where(
                    ListItem.list_id == current, ListItem.referenced_list_id.is_not(None)
                )
            ).all()
        )
    return False


def _set_dependencies(db: Session, item: ListItem, dependency_ids: list[str]) -> None:
    item.dependencies.clear()
    for dep_id in dict.fromkeys(dependency_ids):
        target = db.get(ListItem, dep_id)
        if not target or target.list_id != item.list_id or target.id == item.id:
            raise HTTPException(422, detail=f"Invalid dependency: {dep_id}")
        item.dependencies.append(ItemDependency(depends_on_item_id=dep_id))


def create_item(db: Session, list_obj: ListModel, data: ItemCreate, actor: User) -> ListItem:
    if data.referenced_list_id:
        ref = db.get(ListModel, data.referenced_list_id)
        if not ref or ref.deleted_at is not None:
            raise HTTPException(422, detail="Referenced list does not exist")
        if not can_view(db, actor, ref, allow_unlisted=False):
            raise HTTPException(403, detail="The referenced list is not accessible")
        if would_create_cycle(db, list_obj.id, ref.id):
            raise HTTPException(409, detail="This reference would create a circular list graph")
    position = data.position
    if position is None:
        maximum = db.scalar(select(func.max(ListItem.position)).where(ListItem.list_id == list_obj.id))
        position = (maximum if maximum is not None else -1) + 1
    values = data.model_dump(exclude={"dependency_ids", "position"})
    item = ListItem(list_id=list_obj.id, position=position, **values)
    db.add(item)
    db.flush()
    _set_dependencies(db, item, data.dependency_ids)
    return item


def update_item(db: Session, item: ListItem, data: ItemUpdate, actor: User) -> ListItem:
    values = data.model_dump(exclude_unset=True)
    for required_field in {"name", "quantity", "unit", "is_required", "position"}:
        if required_field in values and values[required_field] is None:
            raise HTTPException(422, detail=f"{required_field} cannot be null")
    dependency_ids = values.pop("dependency_ids", None)
    referenced = values.get("referenced_list_id")
    if referenced and referenced != item.referenced_list_id:
        ref = db.get(ListModel, referenced)
        if not ref or ref.deleted_at is not None:
            raise HTTPException(422, detail="Referenced list does not exist")
        if not can_view(db, actor, ref, allow_unlisted=False):
            raise HTTPException(403, detail="The referenced list is not accessible")
        if would_create_cycle(db, item.list_id, referenced):
            raise HTTPException(409, detail="This reference would create a circular list graph")
    for key, value in values.items():
        setattr(item, key, value)
    if dependency_ids is not None:
        _set_dependencies(db, item, dependency_ids)
    return item


def duplicate_list(db: Session, source: ListModel, owner: User) -> ListModel:
    copy_list = ListModel(
        name=f"{source.name} (copy)",
        slug=unique_slug(db, f"{source.slug}-copy"),
        description=source.description,
        visibility=source.visibility,
        default_sort=deepcopy(source.default_sort),
        custom_metadata=deepcopy(source.custom_metadata),
        owner_id=owner.id,
    )
    db.add(copy_list)
    db.flush()
    id_map: dict[str, ListItem] = {}
    for item in source.items:
        copied = ListItem(
            list_id=copy_list.id,
            name=item.name,
            description=item.description,
            quantity=item.quantity,
            unit=item.unit,
            category=item.category,
            tags=deepcopy(item.tags),
            storage_location=item.storage_location,
            usage_context=item.usage_context,
            is_required=item.is_required,
            notes=item.notes,
            position=item.position,
            referenced_list_id=item.referenced_list_id,
            identity_key=item.identity_key,
            conditional_requirements=deepcopy(item.conditional_requirements),
            custom_metadata=deepcopy(item.custom_metadata),
        )
        db.add(copied)
        db.flush()
        id_map[item.id] = copied
    for original in source.items:
        for dep in original.dependencies:
            if dep.depends_on_item_id in id_map:
                db.add(ItemDependency(item_id=id_map[original.id].id, depends_on_item_id=id_map[dep.depends_on_item_id].id, condition=dep.condition, required=dep.required))
    return copy_list
