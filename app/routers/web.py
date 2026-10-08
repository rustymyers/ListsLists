from datetime import UTC, datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.dependencies import CurrentUser, Db, OptionalUser
from app.models import (
    AppSetting,
    AuditEvent,
    CanonicalItem,
    ListItem,
    ListModel,
    ListShare,
    ShareRole,
    User,
    Visibility,
)
from app.permissions import (
    can_edit,
    can_manage,
    can_view,
    require_edit,
    require_manage,
    require_view,
)
from app.schemas import ItemCreate, ItemUpdate, ListCreate, ResolutionOptions
from app.security import ensure_csrf
from app.services.audit import record_event
from app.services.email import send_email
from app.services.lists import (
    create_item,
    create_list,
    create_list_reference,
    duplicate_list,
    update_item,
)
from app.services.resolution import ListResolver, export_csv, export_json

router = APIRouter()


def render(request: Request, template: str, context: dict):
    return request.app.state.templates.TemplateResponse(request, template, context)


@router.get("/")
def home(request: Request, db: Db, user: OptionalUser, q: str | None = None):
    if not user:
        return RedirectResponse("/login", 303)
    shared_ids = select(ListShare.list_id).where(ListShare.user_id == user.id)
    stmt = select(ListModel).where(
        ListModel.deleted_at.is_(None), ListModel.archived.is_(False),
        or_(ListModel.owner_id == user.id, ListModel.id.in_(shared_ids), ListModel.visibility == Visibility.public),
    )

    if q:
        stmt = stmt.where(or_(ListModel.name.ilike(f"%{q}%"), ListModel.description.ilike(f"%{q}%")))
    lists = db.scalars(stmt.order_by(ListModel.updated_at.desc())).all()
    if request.headers.get("HX-Request"):
        return render(request, "list_cards.html", {"lists": lists})
    notice = db.get(AppSetting, "site_notice")
    return render(
        request,
        "home.html",
        {"lists": lists, "q": q or "", "user": user, "site_notice": notice.value if notice else ""},
    )


@router.get("/items")
def item_management(request: Request, db: Db, user: CurrentUser, q: str | None = None):
    stmt = select(CanonicalItem).where(CanonicalItem.owner_id == user.id)
    if q:
        stmt = stmt.where(
            or_(
                CanonicalItem.name.ilike(f"%{q}%"),
                CanonicalItem.description.ilike(f"%{q}%"),
            )
        )
    items = db.scalars(stmt.order_by(CanonicalItem.name)).all()
    if request.headers.get("HX-Request"):
        return render(request, "item_cards.html", {"items": items})
    return render(request, "items.html", {"items": items, "q": q or "", "user": user})


@router.post("/items")
def create_canonical_item(
    request: Request,
    db: Db,
    user: CurrentUser,
    name: str = Form(),
    description: str = Form(""),
    unit: str = Form("each"),
    category: str = Form(""),
    tags: str = Form(""),
    storage_location: str = Form(""),
    usage_context: str = Form(""),
    notes: str = Form(""),
    identity_key: str = Form(""),
    csrf_token: str = Form(),
):
    ensure_csrf(request, csrf_token)
    if not name.strip():
        raise HTTPException(422, detail="Item name is required")
    if not unit.strip():
        raise HTTPException(422, detail="Item unit is required")
    item = CanonicalItem(
        owner_id=user.id,
        name=name.strip(),
        description=description,
        unit=unit.strip(),
        category=category or None,
        tags=[tag.strip() for tag in tags.split(",") if tag.strip()],
        storage_location=storage_location or None,
        usage_context=usage_context or None,
        notes=notes,
        identity_key=identity_key or None,
    )
    db.add(item)
    record_event(db, "canonical_item.create", "canonical_item", item.id, user)
    db.commit()
    return RedirectResponse(f"/items/{item.id}", 303)


@router.get("/items/{canonical_item_id}")
def canonical_item_page(request: Request, db: Db, user: CurrentUser, canonical_item_id: str):
    item = db.get(CanonicalItem, canonical_item_id)
    if not item or item.owner_id != user.id:
        raise HTTPException(404, detail="Item not found")
    placements = db.scalars(
        select(ListItem)
        .where(ListItem.canonical_item_id == item.id)
        .options(selectinload(ListItem.list))
        .order_by(ListItem.created_at)
    ).all()
    visible_placements = [
        placement
        for placement in placements
        if can_view(db, user, placement.list, allow_unlisted=False)
    ]
    return render(
        request,
        "canonical_item.html",
        {"item": item, "placements": visible_placements, "user": user},
    )


@router.post("/canonical-items/{canonical_item_id}/delete")
def delete_canonical_item(
    request: Request,
    db: Db,
    user: CurrentUser,
    canonical_item_id: str,
    csrf_token: str = Form(),
):
    ensure_csrf(request, csrf_token)
    item = db.get(CanonicalItem, canonical_item_id)
    if not item or item.owner_id != user.id:
        raise HTTPException(404, detail="Item not found")
    placement_count = db.scalar(
        select(func.count()).select_from(ListItem).where(ListItem.canonical_item_id == item.id)
    )
    if placement_count:
        return request.app.state.templates.TemplateResponse(
            request,
            "canonical_item.html",
            {
                "item": item,
                "placements": [],
                "user": user,
                "error": (
                    f"Cannot delete this item because it is used in {placement_count} "
                    "list placement(s). Remove those placements first."
                ),
            },
            status_code=409,
        )
    db.delete(item)
    record_event(db, "canonical_item.delete", "canonical_item", item.id, user)
    db.commit()
    return RedirectResponse("/items", 303)


@router.get("/canonical-items/{canonical_item_id}/edit")
def edit_canonical_item_page(
    request: Request, db: Db, user: CurrentUser, canonical_item_id: str
):
    item = db.get(CanonicalItem, canonical_item_id)
    if not item or item.owner_id != user.id:
        raise HTTPException(404, detail="Item not found")
    return render(request, "canonical_item_edit.html", {"item": item, "user": user})


@router.post("/canonical-items/{canonical_item_id}/edit")
def edit_canonical_item(
    request: Request,
    db: Db,
    user: CurrentUser,
    canonical_item_id: str,
    name: str = Form(),
    description: str = Form(""),
    unit: str = Form("each"),
    category: str = Form(""),
    tags: str = Form(""),
    storage_location: str = Form(""),
    usage_context: str = Form(""),
    notes: str = Form(""),
    identity_key: str = Form(""),
    csrf_token: str = Form(),
):
    ensure_csrf(request, csrf_token)
    item = db.get(CanonicalItem, canonical_item_id)
    if not item or item.owner_id != user.id:
        raise HTTPException(404, detail="Item not found")
    item.name = name
    item.description = description
    item.unit = unit
    item.category = category or None
    item.tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
    item.storage_location = storage_location or None
    item.usage_context = usage_context or None
    item.notes = notes
    item.identity_key = identity_key or None
    record_event(db, "canonical_item.update", "canonical_item", item.id, user)
    db.commit()
    return RedirectResponse(f"/items/{item.id}", 303)


@router.get("/lists/new")
def new_list_page(request: Request, user: CurrentUser):
    return render(request, "list_form.html", {"user": user})


@router.post("/lists/new")
def new_list(request: Request, db: Db, user: CurrentUser, name: str = Form(), description: str = Form(""), visibility: Visibility = Form(Visibility.private), csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    obj = create_list(db, ListCreate(name=name, description=description, visibility=visibility), user)
    record_event(db, "list.create", "list", obj.id, user, {"name": name})
    db.commit()
    return RedirectResponse(f"/l/{obj.slug}", 303)


@router.get("/l/{slug}")
def list_detail(request: Request, db: Db, user: OptionalUser, slug: str):
    obj = db.scalar(select(ListModel).where(ListModel.slug == slug, ListModel.deleted_at.is_(None)).options(selectinload(ListModel.items)))
    if not obj:
        raise HTTPException(404, detail="List not found")
    require_view(db, user, obj, allow_unlisted=True)
    referenced_list_ids = {
        item.referenced_list_id for item in obj.items if item.is_required and item.referenced_list_id
    }
    visible_referenced_lists = {
        candidate.id: candidate
        for candidate in db.scalars(
            select(ListModel).where(
                ListModel.id.in_(referenced_list_ids),
                ListModel.deleted_at.is_(None),
            )
        ).all()
        if can_view(db, user, candidate, allow_unlisted=False)
    }
    required_by_list_ids = (
        select(ListItem.list_id)
        .where(
            ListItem.referenced_list_id == obj.id,
            ListItem.is_required.is_(True),
        )
        .distinct()
    )
    required_by_lists = [
        candidate
        for candidate in db.scalars(
            select(ListModel)
            .where(
                ListModel.id.in_(required_by_list_ids),
                ListModel.deleted_at.is_(None),
            )
            .order_by(ListModel.name)
        ).all()
        if can_view(db, user, candidate, allow_unlisted=False)
    ]
    available_lists = []
    canonical_items = []
    if can_edit(db, user, obj):
        canonical_items = db.scalars(
            select(CanonicalItem).where(CanonicalItem.owner_id == user.id).order_by(CanonicalItem.name)
        ).all()
        available_lists = [
            candidate
            for candidate in db.scalars(
                select(ListModel)
                .where(ListModel.id != obj.id, ListModel.deleted_at.is_(None))
                .order_by(ListModel.name)
            ).all()
            if can_view(db, user, candidate, allow_unlisted=False)
        ]
    return render(
        request,
        "list_detail.html",
        {
            "list": obj,
            "items": [item for item in obj.items if not item.referenced_list_id],
            "list_references": [item for item in obj.items if item.referenced_list_id],
            "user": user,
            "can_edit": can_edit(db, user, obj),
            "can_manage": can_manage(db, user, obj),
            "available_lists": available_lists,
            "canonical_items": canonical_items,
            "visible_referenced_lists": visible_referenced_lists,
            "required_by_lists": required_by_lists,
        },
    )


@router.get("/i/{item_id}")
def item_stable_url(db: Db, user: OptionalUser, item_id: str):
    item = db.get(ListItem, item_id)
    if not item:
        raise HTTPException(404, detail="Item not found")
    obj = db.get(ListModel, item.list_id)
    if not obj:
        raise HTTPException(404, detail="List not found")
    require_view(db, user, obj, allow_unlisted=True)
    return RedirectResponse(f"/l/{obj.slug}#item-{item.id}", 303)


@router.get("/l/{slug}/edit")
def edit_list_page(request: Request, db: Db, user: CurrentUser, slug: str):
    obj = db.scalar(select(ListModel).where(ListModel.slug == slug))
    if not obj:
        raise HTTPException(404)
    require_edit(db, user, obj)
    return render(request, "list_edit.html", {"list": obj, "user": user})


@router.post("/l/{slug}/edit")
def edit_list(request: Request, db: Db, user: CurrentUser, slug: str, name: str = Form(), description: str = Form(""), visibility: Visibility = Form(), archived: bool = Form(False), csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    obj = db.scalar(select(ListModel).where(ListModel.slug == slug))
    if not obj:
        raise HTTPException(404)
    require_edit(db, user, obj)
    if obj.owner_id != user.id and not user.is_admin and visibility != obj.visibility:
        raise HTTPException(403, detail="Only the owner can change visibility")
    obj.name, obj.description, obj.visibility, obj.archived = name, description, visibility, archived
    record_event(db, "list.update", "list", obj.id, user)
    db.commit()
    return RedirectResponse(f"/l/{obj.slug}", 303)


@router.post("/l/{slug}/duplicate")
def duplicate(request: Request, db: Db, user: CurrentUser, slug: str, csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    source = db.scalar(select(ListModel).where(ListModel.slug == slug).options(selectinload(ListModel.items)))
    if not source:
        raise HTTPException(404)
    require_view(db, user, source, allow_unlisted=True)
    copied = duplicate_list(db, source, user)
    record_event(db, "list.duplicate", "list", copied.id, user, {"source_id": source.id})
    db.commit()
    return RedirectResponse(f"/l/{copied.slug}", 303)


@router.post("/l/{slug}/delete")
def delete(request: Request, db: Db, user: CurrentUser, slug: str, csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    obj = db.scalar(select(ListModel).where(ListModel.slug == slug))
    if not obj:
        raise HTTPException(404)
    require_manage(db, user, obj)
    obj.deleted_at = datetime.now(UTC)
    record_event(db, "list.delete", "list", obj.id, user)
    db.commit()
    return RedirectResponse("/", 303)


@router.post("/l/{slug}/items")
def add_item(request: Request, db: Db, user: CurrentUser, slug: str, name: str = Form(""), quantity: float = Form(1), unit: str = Form("each"), category: str = Form(""), tags: str = Form(""), storage_location: str = Form(""), packing_spot: str = Form(""), notes: str = Form(""), is_required: bool = Form(False), referenced_list_id: str = Form(""), canonical_item_id: str = Form(""), duplicate: bool = Form(False), csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    obj = db.scalar(select(ListModel).where(ListModel.slug == slug))
    if not obj:
        raise HTTPException(404)
    require_edit(db, user, obj)
    data = ItemCreate(name=name or "New item", quantity=quantity, unit=unit, category=category or None, tags=[x.strip() for x in tags.split(",") if x.strip()], storage_location=storage_location or None, packing_spot=packing_spot or None, notes=notes, is_required=is_required, referenced_list_id=referenced_list_id or None, canonical_item_id=canonical_item_id or None, duplicate=duplicate)
    item = create_item(db, obj, data, user)
    record_event(db, "item.create", "item", item.id, user, {"list_id": obj.id})
    db.commit()
    if request.headers.get("HX-Request"):
        visible_referenced_lists = (
            {item.referenced_list_id: item.referenced_list} if item.referenced_list_id else {}
        )
        return render(
            request,
            "item_row.html",
            {
                "item": item,
                "list": obj,
                "can_edit": True,
                "visible_referenced_lists": visible_referenced_lists,
            },
        )
    return RedirectResponse(f"/l/{slug}", 303)


@router.post("/l/{slug}/required-list")
def add_required_list(
    request: Request,
    db: Db,
    user: CurrentUser,
    slug: str,
    referenced_list_id: str = Form(),
    csrf_token: str = Form(),
):
    ensure_csrf(request, csrf_token)
    obj = db.scalar(select(ListModel).where(ListModel.slug == slug))
    if not obj:
        raise HTTPException(404)
    require_edit(db, user, obj)
    referenced = db.get(ListModel, referenced_list_id)
    if not referenced or not can_view(db, user, referenced, allow_unlisted=False):
        raise HTTPException(404, detail="Referenced list not found")
    item = create_list_reference(db, obj, referenced, user)
    record_event(db, "item.create", "item", item.id, user, {"list_id": obj.id, "referenced_list_id": referenced.id})
    db.commit()
    return RedirectResponse(f"/l/{obj.slug}#item-{item.id}", 303)


@router.get("/items/{item_id}/edit")
def edit_item_page(request: Request, db: Db, user: CurrentUser, item_id: str):
    item = db.get(ListItem, item_id)
    if not item:
        raise HTTPException(404)
    obj = db.get(ListModel, item.list_id)
    if not obj:
        raise HTTPException(404)
    require_edit(db, user, obj)
    return render(request, "item_edit.html", {"item": item, "list": obj, "user": user})


@router.post("/items/{item_id}/edit")
def edit_item(
    request: Request,
    db: Db,
    user: CurrentUser,
    item_id: str,
    name: str = Form(),
    description: str = Form(""),
    quantity: float = Form(1),
    packing_spot: str = Form(""),
    unit: str = Form("each"),
    category: str = Form(""),
    tags: str = Form(""),
    storage_location: str = Form(""),
    usage_context: str = Form(""),
    notes: str = Form(""),
    is_required: bool = Form(False),
    referenced_list_id: str = Form(""),
    identity_key: str = Form(""),
    csrf_token: str = Form(),
):
    ensure_csrf(request, csrf_token)
    item = db.get(ListItem, item_id)
    if not item:
        raise HTTPException(404)
    obj = db.get(ListModel, item.list_id)
    if not obj:
        raise HTTPException(404)
    require_edit(db, user, obj)
    data = ItemUpdate(
        name=name,
        description=description,
        quantity=quantity,
        packing_spot=packing_spot or None,
        unit=unit,
        category=category or None,
        tags=[tag.strip() for tag in tags.split(",") if tag.strip()],
        storage_location=storage_location or None,
        usage_context=usage_context or None,
        notes=notes,
        is_required=is_required,
        referenced_list_id=referenced_list_id or None,
        identity_key=identity_key or None,
    )
    update_item(db, item, data, user)
    record_event(db, "item.update", "item", item.id, user, {"list_id": obj.id})
    db.commit()
    return RedirectResponse(f"/l/{obj.slug}#item-{item.id}", 303)


@router.post("/items/{item_id}/delete")
def delete_item(request: Request, db: Db, user: CurrentUser, item_id: str, csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    item = db.get(ListItem, item_id)
    if not item:
        raise HTTPException(404)
    obj = db.get(ListModel, item.list_id)
    require_edit(db, user, obj)
    db.delete(item)
    record_event(db, "item.delete", "item", item.id, user, {"list_id": obj.id})
    db.commit()
    if request.headers.get("HX-Request"):
        return ""
    return RedirectResponse(f"/l/{obj.slug}", 303)


@router.get("/l/{slug}/preview")
def preview(request: Request, db: Db, user: OptionalUser, slug: str, include_optional: bool = True, merge_duplicates: bool = True):
    obj = db.scalar(select(ListModel).where(ListModel.slug == slug).options(selectinload(ListModel.items).selectinload(ListItem.dependencies)))
    if not obj:
        raise HTTPException(404)
    require_view(db, user, obj, allow_unlisted=True)
    options = ResolutionOptions(include_optional=include_optional, merge_duplicates=merge_duplicates)
    rows = ListResolver(db, user, options).resolve(obj)
    source_list_ids = {source_id for row in rows for source_id in row.source_list_ids}
    source_list_names = {
        source.id: source.name
        for source in db.scalars(
            select(ListModel).where(ListModel.id.in_(source_list_ids))
        ).all()
        if can_view(db, user, source, allow_unlisted=source.id == obj.id)
    }
    preview_rows = [
        {
            "row": row,
            "source_list_names": [
                source_list_names[source_id]
                for source_id in row.source_list_ids
                if source_id in source_list_names
            ],
        }
        for row in rows
    ]
    return render(
        request,
        "preview.html",
        {
            "list": obj,
            "preview_rows": preview_rows,
            "user": user,
        },
    )


@router.get("/l/{slug}/export/{format}")
def browser_export(db: Db, user: OptionalUser, slug: str, format: str):
    if format not in {"json", "csv"}:
        raise HTTPException(404, detail="Export format not found")
    obj = db.scalar(select(ListModel).where(ListModel.slug == slug).options(selectinload(ListModel.items).selectinload(ListItem.dependencies)))
    if not obj:
        raise HTTPException(404, detail="List not found")
    require_view(db, user, obj, allow_unlisted=True)
    rows = ListResolver(db, user, ResolutionOptions()).resolve(obj)
    if format == "json":
        return Response(export_json(rows, obj), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{obj.slug}.json"'})
    return Response(export_csv(rows), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{obj.slug}.csv"'})


@router.get("/l/{slug}/history")
def history(request: Request, db: Db, user: CurrentUser, slug: str):
    obj = db.scalar(select(ListModel).where(ListModel.slug == slug))
    if not obj:
        raise HTTPException(404)
    require_view(db, user, obj, allow_unlisted=True)
    item_ids = select(ListItem.id).where(ListItem.list_id == obj.id)
    events = db.scalars(select(AuditEvent).where(or_(AuditEvent.target_id == obj.id, AuditEvent.target_id.in_(item_ids))).order_by(AuditEvent.created_at.desc()).limit(200)).all()
    return render(request, "history.html", {"list": obj, "events": events, "user": user})


@router.get("/l/{slug}/share")
def share_page(request: Request, db: Db, user: CurrentUser, slug: str):
    obj = db.scalar(select(ListModel).where(ListModel.slug == slug).options(selectinload(ListModel.shares).selectinload(ListShare.user)))
    if not obj:
        raise HTTPException(404)
    require_manage(db, user, obj)
    users = db.scalars(select(User).where(User.is_active.is_(True), User.id != obj.owner_id).order_by(User.username)).all()
    return render(request, "share.html", {"list": obj, "users": users, "user": user})


@router.post("/l/{slug}/share")
def grant_share(request: Request, db: Db, user: CurrentUser, slug: str, shared_user_id: str = Form(), role: ShareRole = Form(), csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    obj = db.scalar(select(ListModel).where(ListModel.slug == slug))
    if not obj:
        raise HTTPException(404, detail="List not found")
    require_manage(db, user, obj)
    target = db.get(User, shared_user_id)
    if not target or not target.is_active or target.id == obj.owner_id:
        raise HTTPException(422, detail="Invalid share recipient")
    share = db.scalar(select(ListShare).where(ListShare.list_id == obj.id, ListShare.user_id == target.id))
    invitation_needed = not share or share.role != role
    if share:
        share.role = role
    else:
        db.add(ListShare(list_id=obj.id, user_id=target.id, role=role))
    record_event(db, "share.grant", "list", obj.id, user, {"user_id": target.id, "role": role.value})
    db.commit()
    from app.config import get_settings
    settings = get_settings()
    if invitation_needed and settings.smtp_host:
        try:
            send_email(settings, target.email, f"{user.username} shared a list with you", f"You now have {role.value} access to {obj.name}.\n\n{settings.public_base_url}/l/{obj.slug}")
        except Exception as exc:
            record_event(db, "share.invitation_email_failed", "list", obj.id, user, {"error": type(exc).__name__})
            db.commit()
    return RedirectResponse(f"/l/{slug}/share", 303)


@router.post("/l/{slug}/share/{shared_user_id}/revoke")
def revoke_share(request: Request, db: Db, user: CurrentUser, slug: str, shared_user_id: str, csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    obj = db.scalar(select(ListModel).where(ListModel.slug == slug))
    if not obj:
        raise HTTPException(404, detail="List not found")
    require_manage(db, user, obj)
    share = db.scalar(select(ListShare).where(ListShare.list_id == obj.id, ListShare.user_id == shared_user_id))
    if not share:
        raise HTTPException(404, detail="Share not found")
    db.delete(share)
    record_event(db, "share.revoke", "list", obj.id, user, {"user_id": shared_user_id})
    db.commit()
    return RedirectResponse(f"/l/{slug}/share", 303)
