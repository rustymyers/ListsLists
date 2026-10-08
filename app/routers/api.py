from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.dependencies import CurrentUser, Db, OptionalUser
from app.models import CanonicalItem, ExportProfile, ItemDependency, ListItem, ListModel, ListShare, User, Visibility
from app.permissions import can_view, require_edit, require_manage, require_view
from app.schemas import CanonicalItemOut, ExportProfileCreate, ItemCreate, ItemOut, ItemUpdate, ListCreate, ListOut, ListUpdate, ResolutionOptions, ShareCreate
from app.security import create_access_token, verify_password
from app.services.audit import record_event
from app.services.email import send_email
from app.services.lists import create_item, create_list, duplicate_list, unique_slug, update_item
from app.services.resolution import ListResolver, export_csv, export_json, rows_as_dicts

router = APIRouter(prefix="/api/v1", tags=["v1"])


def get_list_or_404(db: Db, list_id: str) -> ListModel:
    obj = db.scalar(select(ListModel).where(ListModel.id == list_id).options(selectinload(ListModel.items).selectinload(ListItem.dependencies)))
    if not obj or obj.deleted_at is not None:
        raise HTTPException(404, detail="List not found")
    return obj


def safe_item_out(db: Db, user: User | None, item: ListItem) -> ItemOut:
    source = item.canonical_item
    values = {field: getattr(source or item, field) for field in (
        "name", "description", "unit", "category", "tags", "storage_location",
        "usage_context", "notes", "identity_key", "conditional_requirements", "custom_metadata",
    )}
    values.update({
        "id": item.id, "list_id": item.list_id, "canonical_item_id": item.canonical_item_id,
        "quantity": item.quantity, "packing_spot": item.packing_spot, "is_required": item.is_required,
        "position": item.position, "referenced_list_id": item.referenced_list_id,
    })
    output = ItemOut.model_validate(values)
    if item.referenced_list_id:
        nested = db.get(ListModel, item.referenced_list_id)
        if not nested or not can_view(db, user, nested, allow_unlisted=False):
            output.referenced_list_id = None
    return output


@router.get("/canonical-items", response_model=list[CanonicalItemOut])
def canonical_items(db: Db, user: CurrentUser, q: str | None = None, offset: int = 0, limit: Annotated[int, Query(le=200)] = 100):
    stmt = select(CanonicalItem).where(CanonicalItem.owner_id == user.id)
    if q:
        stmt = stmt.where(or_(CanonicalItem.name.ilike(f"%{q}%"), CanonicalItem.description.ilike(f"%{q}%")))
    return db.scalars(stmt.order_by(CanonicalItem.name).offset(offset).limit(limit)).all()


@router.post("/canonical-items", response_model=CanonicalItemOut, status_code=201)
def add_canonical_item(request: Request, db: Db, user: CurrentUser, data: ItemCreate):
    item = CanonicalItem(owner_id=user.id, **data.model_dump(include=set((
        "name", "description", "unit", "category", "tags", "storage_location",
        "usage_context", "notes", "identity_key", "conditional_requirements", "custom_metadata",
    ))))
    db.add(item)
    record_event(db, "canonical_item.create", "canonical_item", item.id, user, request.client.host if request.client else None)
    db.commit()
    return item


@router.post("/auth/token")
def token(db: Db, form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    if get_settings().auth_mode == "proxy":
        raise HTTPException(403, detail="Local authentication is disabled")
    user = db.scalar(select(User).where(func.lower(User.username) == form.username.lower()))
    if not user or not user.is_active or not verify_password(form.password, user.password_hash):
        raise HTTPException(401, detail="Invalid credentials")
    if user.must_change_password:
        raise HTTPException(403, detail="Password change required in the browser before API access")
    return {"access_token": create_access_token(user.id, get_settings()), "token_type": "bearer"}


@router.get("/lists", response_model=list[ListOut])
def list_lists(db: Db, user: CurrentUser, q: str | None = None, archived: bool = False, offset: int = 0, limit: Annotated[int, Query(le=100)] = 50):
    share_ids = select(ListShare.list_id).where(ListShare.user_id == user.id)
    stmt = select(ListModel).where(
        ListModel.deleted_at.is_(None), ListModel.archived == archived,
        or_(ListModel.owner_id == user.id, ListModel.visibility == Visibility.public, ListModel.id.in_(share_ids)),
    )
    if q:
        stmt = stmt.where(or_(ListModel.name.ilike(f"%{q}%"), ListModel.description.ilike(f"%{q}%")))
    return db.scalars(stmt.order_by(ListModel.updated_at.desc()).offset(offset).limit(limit)).all()


@router.post("/lists", response_model=ListOut, status_code=201)
def add_list(request: Request, db: Db, user: CurrentUser, data: ListCreate):
    obj = create_list(db, data, user)
    record_event(db, "list.create", "list", obj.id, user, {"name": obj.name}, request.client.host if request.client else None)
    db.commit()
    return obj


@router.get("/lists/{list_id}", response_model=ListOut)
def get_list(db: Db, user: OptionalUser, list_id: str):
    obj = get_list_or_404(db, list_id)
    require_view(db, user, obj)
    return obj


@router.patch("/lists/{list_id}", response_model=ListOut)
def patch_list(request: Request, db: Db, user: CurrentUser, list_id: str, data: ListUpdate):
    obj = get_list_or_404(db, list_id)
    require_edit(db, user, obj)
    values = data.model_dump(exclude_unset=True)
    values = {key: value for key, value in values.items() if value is not None}
    if "slug" in values:
        values["slug"] = unique_slug(db, values["slug"], obj.id)
    if "visibility" in values and obj.owner_id != user.id and not user.is_admin:
        raise HTTPException(403, detail="Only the owner can change visibility")
    for key, value in values.items():
        setattr(obj, key, value)
    record_event(db, "list.update", "list", obj.id, user, {"fields": sorted(values)}, request.client.host if request.client else None)
    db.commit()
    return obj


@router.post("/lists/{list_id}/duplicate", response_model=ListOut, status_code=201)
def copy_list(request: Request, db: Db, user: CurrentUser, list_id: str):
    source = get_list_or_404(db, list_id)
    require_view(db, user, source)
    copied = duplicate_list(db, source, user)
    record_event(db, "list.duplicate", "list", copied.id, user, {"source_id": source.id}, request.client.host if request.client else None)
    db.commit()
    return copied


@router.delete("/lists/{list_id}", status_code=204)
def delete_list(request: Request, db: Db, user: CurrentUser, list_id: str):
    obj = get_list_or_404(db, list_id)
    require_manage(db, user, obj)
    obj.deleted_at = datetime.now(UTC)
    record_event(db, "list.delete", "list", obj.id, user, ip_address=request.client.host if request.client else None)
    db.commit()
    return Response(status_code=204)


@router.get("/lists/{list_id}/items", response_model=list[ItemOut])
def list_items(db: Db, user: OptionalUser, list_id: str, q: str | None = None, category: str | None = None, tag: str | None = None, offset: int = 0, limit: Annotated[int, Query(le=200)] = 100):
    obj = get_list_or_404(db, list_id)
    require_view(db, user, obj)
    stmt = select(ListItem).where(ListItem.list_id == obj.id)
    if q:
        stmt = stmt.where(or_(ListItem.name.ilike(f"%{q}%"), ListItem.description.ilike(f"%{q}%"), ListItem.notes.ilike(f"%{q}%")))
    if category:
        stmt = stmt.where(ListItem.category == category)
    rows = db.scalars(stmt.order_by(ListItem.position).offset(offset).limit(limit)).all()
    return [safe_item_out(db, user, row) for row in rows if not tag or tag in row.tags]


@router.get("/items/{item_id}", response_model=ItemOut)
def get_item(db: Db, user: OptionalUser, item_id: str):
    item = db.get(ListItem, item_id)
    if not item:
        raise HTTPException(404, detail="Item not found")
    obj = get_list_or_404(db, item.list_id)
    require_view(db, user, obj)
    return safe_item_out(db, user, item)


@router.post("/lists/{list_id}/items", response_model=ItemOut, status_code=201)
def add_item(request: Request, db: Db, user: CurrentUser, list_id: str, data: ItemCreate):
    obj = get_list_or_404(db, list_id)
    require_edit(db, user, obj)
    item = create_item(db, obj, data, user)
    record_event(db, "item.create", "item", item.id, user, {"list_id": obj.id}, request.client.host if request.client else None)
    db.commit()
    return item


@router.patch("/items/{item_id}", response_model=ItemOut)
def patch_item(request: Request, db: Db, user: CurrentUser, item_id: str, data: ItemUpdate):
    item = db.get(ListItem, item_id)
    if not item:
        raise HTTPException(404, detail="Item not found")
    obj = get_list_or_404(db, item.list_id)
    require_edit(db, user, obj)
    update_item(db, item, data, user)
    record_event(db, "item.update", "item", item.id, user, {"fields": sorted(data.model_fields_set)}, request.client.host if request.client else None)
    db.commit()
    return item


@router.post("/items/{item_id}/copy", response_model=ItemOut, status_code=201)
def copy_item(request: Request, db: Db, user: CurrentUser, item_id: str, target_list_id: Annotated[str | None, Body(embed=True)] = None):
    source = db.get(ListItem, item_id)
    if not source:
        raise HTTPException(404, detail="Item not found")
    source_list = get_list_or_404(db, source.list_id)
    require_view(db, user, source_list)
    target = get_list_or_404(db, target_list_id or source.list_id)
    require_edit(db, user, target)
    data = ItemCreate(
        name=source.name,
        description=source.description,
        quantity=source.quantity,
        packing_spot=source.packing_spot,
        unit=source.unit,
        category=source.category,
        tags=list(source.tags),
        storage_location=source.storage_location,
        usage_context=source.usage_context,
        is_required=source.is_required,
        notes=source.notes,
        referenced_list_id=source.referenced_list_id,
        identity_key=source.identity_key,
        conditional_requirements=dict(source.conditional_requirements),
        custom_metadata=dict(source.custom_metadata),
        duplicate=True,
    )
    copied = create_item(db, target, data, user)
    record_event(db, "item.copy", "item", copied.id, user, {"source_item_id": source.id, "target_list_id": target.id}, request.client.host if request.client else None)
    db.commit()
    return copied


@router.post("/items/{item_id}/move", response_model=ItemOut)
def move_item(request: Request, db: Db, user: CurrentUser, item_id: str, target_list_id: Annotated[str, Body(embed=True)]):
    item = db.get(ListItem, item_id)
    if not item:
        raise HTTPException(404, detail="Item not found")
    source = get_list_or_404(db, item.list_id)
    target = get_list_or_404(db, target_list_id)
    require_edit(db, user, source)
    require_edit(db, user, target)
    if source.id != target.id:
        has_dependencies = bool(item.dependencies) or bool(
            db.scalar(select(ItemDependency.id).where(ItemDependency.depends_on_item_id == item.id).limit(1))
        )
        if has_dependencies:
            raise HTTPException(409, detail="Remove item dependencies before moving between lists")
    if item.referenced_list_id:
        from app.services.lists import would_create_cycle
        nested = get_list_or_404(db, item.referenced_list_id)
        require_view(db, user, nested)
        if would_create_cycle(db, target.id, item.referenced_list_id):
            raise HTTPException(409, detail="Move would create a circular reference")
    item.list_id = target.id
    maximum = db.scalar(select(func.max(ListItem.position)).where(ListItem.list_id == target.id))
    item.position = (maximum if maximum is not None else -1) + 1
    record_event(db, "item.move", "item", item.id, user, {"from": source.id, "to": target.id}, request.client.host if request.client else None)
    db.commit()
    return item


@router.post("/lists/{list_id}/items/reorder", status_code=204)
def reorder_items(request: Request, db: Db, user: CurrentUser, list_id: str, item_ids: Annotated[list[str], Body(embed=True)]):
    obj = get_list_or_404(db, list_id)
    require_edit(db, user, obj)
    items = db.scalars(select(ListItem).where(ListItem.list_id == obj.id)).all()
    if len(item_ids) != len(items) or set(item_ids) != {item.id for item in items}:
        raise HTTPException(422, detail="item_ids must contain every item in the list exactly once")
    by_id = {item.id: item for item in items}
    for position, item_id in enumerate(item_ids):
        by_id[item_id].position = position
    record_event(db, "item.reorder", "list", obj.id, user, ip_address=request.client.host if request.client else None)
    db.commit()
    return Response(status_code=204)


@router.delete("/items/{item_id}", status_code=204)
def remove_item(request: Request, db: Db, user: CurrentUser, item_id: str):
    item = db.get(ListItem, item_id)
    if not item:
        raise HTTPException(404, detail="Item not found")
    obj = get_list_or_404(db, item.list_id)
    require_edit(db, user, obj)
    db.delete(item)
    record_event(db, "item.delete", "item", item.id, user, {"list_id": obj.id}, request.client.host if request.client else None)
    db.commit()
    return Response(status_code=204)


@router.put("/lists/{list_id}/shares", status_code=201)
def set_share(request: Request, db: Db, user: CurrentUser, list_id: str, data: ShareCreate):
    obj = get_list_or_404(db, list_id)
    require_manage(db, user, obj)
    target_user = db.get(User, data.user_id)
    if data.user_id == obj.owner_id or not target_user or not target_user.is_active:
        raise HTTPException(422, detail="Invalid share recipient")
    share = db.scalar(select(ListShare).where(ListShare.list_id == obj.id, ListShare.user_id == data.user_id))
    invitation_needed = not share or share.role != data.role
    if share:
        share.role = data.role
    else:
        share = ListShare(list_id=obj.id, user_id=data.user_id, role=data.role)
        db.add(share)
    record_event(db, "share.grant", "list", obj.id, user, {"user_id": data.user_id, "role": data.role.value}, request.client.host if request.client else None)
    db.commit()
    settings = get_settings()
    if invitation_needed and settings.smtp_host:
        try:
            send_email(
                settings,
                target_user.email,
                f"{user.username} shared a list with you",
                f"You now have {data.role.value} access to {obj.name}.\n\n{settings.public_base_url}/l/{obj.slug}",
            )
        except Exception as exc:
            record_event(db, "share.invitation_email_failed", "list", obj.id, user, {"error": type(exc).__name__})
            db.commit()
    return {"id": share.id, "user_id": share.user_id, "role": share.role}


@router.delete("/lists/{list_id}/shares/{shared_user_id}", status_code=204)
def revoke_share(request: Request, db: Db, user: CurrentUser, list_id: str, shared_user_id: str):
    obj = get_list_or_404(db, list_id)
    require_manage(db, user, obj)
    share = db.scalar(select(ListShare).where(ListShare.list_id == obj.id, ListShare.user_id == shared_user_id))
    if not share:
        raise HTTPException(404, detail="Share not found")
    db.delete(share)
    record_event(db, "share.revoke", "list", obj.id, user, {"user_id": shared_user_id}, request.client.host if request.client else None)
    db.commit()
    return Response(status_code=204)


@router.post("/lists/{list_id}/resolve")
def resolve_list(db: Db, user: OptionalUser, list_id: str, options: ResolutionOptions = ResolutionOptions()):
    obj = get_list_or_404(db, list_id)
    require_view(db, user, obj)
    return {"list_id": obj.id, "items": rows_as_dicts(ListResolver(db, user, options).resolve(obj))}


@router.post("/lists/{list_id}/export")
def export_list(
    db: Db,
    user: OptionalUser,
    list_id: str,
    format: Annotated[str | None, Query(pattern="^(json|csv)$")] = None,
    profile_id: str | None = None,
    options: ResolutionOptions = ResolutionOptions(),
):
    obj = get_list_or_404(db, list_id)
    require_view(db, user, obj)
    if profile_id:
        if not user:
            raise HTTPException(401, detail="Authentication required for export profiles")
        profile = db.get(ExportProfile, profile_id)
        if not profile or profile.owner_id != user.id:
            raise HTTPException(404, detail="Export profile not found")
        format = profile.format
        options = ResolutionOptions.model_validate(profile.options)
    format = format or "json"
    rows = ListResolver(db, user, options).resolve(obj)
    if format == "json":
        return Response(export_json(rows, obj), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{obj.slug}.json"'})
    return Response(export_csv(rows), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{obj.slug}.csv"'})


@router.post("/export-profiles", status_code=201)
def create_export_profile(db: Db, user: CurrentUser, data: ExportProfileCreate):
    profile = ExportProfile(owner_id=user.id, name=data.name, format=data.format, options=data.options.model_dump())
    db.add(profile)
    db.commit()
    return {"id": profile.id, "name": profile.name, "format": profile.format, "options": profile.options}


@router.get("/export-profiles")
def list_export_profiles(db: Db, user: CurrentUser, offset: int = 0, limit: Annotated[int, Query(le=100)] = 50):
    profiles = db.scalars(
        select(ExportProfile)
        .where(ExportProfile.owner_id == user.id)
        .order_by(ExportProfile.name)
        .offset(offset)
        .limit(limit)
    ).all()
    return [{"id": p.id, "name": p.name, "format": p.format, "options": p.options} for p in profiles]


@router.delete("/export-profiles/{profile_id}", status_code=204)
def delete_export_profile(db: Db, user: CurrentUser, profile_id: str):
    profile = db.get(ExportProfile, profile_id)
    if not profile or profile.owner_id != user.id:
        raise HTTPException(404, detail="Export profile not found")
    db.delete(profile)
    db.commit()
    return Response(status_code=204)


@router.get("/health")
def api_health():
    return {"status": "ok"}
