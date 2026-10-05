import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, text

from app.config import get_settings
from app.dependencies import AdminUser, Db
from app.models import AppSetting, AuditEvent, PasswordResetToken, User
from app.security import ensure_csrf, hash_password, new_reset_token
from app.services.audit import record_event
from app.services.email import send_email

router = APIRouter(prefix="/admin")


@router.get("")
def dashboard(request: Request, db: Db, user: AdminUser):
    users = db.scalars(select(User).order_by(User.created_at.desc())).all()
    events = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100)).all()
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False
    notice = db.get(AppSetting, "site_notice")
    return request.app.state.templates.TemplateResponse(request, "admin.html", {"user": user, "users": users, "events": events, "database_ok": database_ok, "smtp_configured": bool(get_settings().smtp_host), "site_notice": notice.value if notice else ""})


@router.post("/settings")
def update_settings(request: Request, db: Db, user: AdminUser, site_notice: str = Form(""), csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    setting = db.get(AppSetting, "site_notice")
    if setting:
        setting.value = site_notice[:500]
    else:
        db.add(AppSetting(key="site_notice", value=site_notice[:500]))
    record_event(db, "admin.settings_update", "setting", None, user, {"keys": ["site_notice"]})
    db.commit()
    return RedirectResponse("/admin", 303)


@router.post("/users")
def create_user(request: Request, db: Db, user: AdminUser, username: str = Form(), email: str = Form(), is_admin: bool = Form(False), csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    temporary = secrets.token_urlsafe(18)
    created = User(username=username, email=email, password_hash=hash_password(temporary), is_admin=is_admin, must_change_password=True)
    db.add(created)
    record_event(db, "admin.user_create", "user", created.id, user, {"username": username})
    db.commit()
    return request.app.state.templates.TemplateResponse(request, "message.html", {"message": f"User created. Temporary password (show once): {temporary}", "user": user})


@router.post("/users/{user_id}/toggle")
def toggle_user(request: Request, db: Db, user: AdminUser, user_id: str, csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    target = db.get(User, user_id)
    if not target or target.id == user.id:
        raise HTTPException(422, detail="Cannot change this user")
    target.is_active = not target.is_active
    record_event(db, "admin.user_toggle", "user", target.id, user, {"active": target.is_active})
    db.commit()
    return RedirectResponse("/admin", 303)


@router.post("/users/{user_id}/admin")
def toggle_admin(request: Request, db: Db, user: AdminUser, user_id: str, csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    target = db.get(User, user_id)
    if not target or target.id == user.id:
        raise HTTPException(422, detail="Cannot change this user")
    target.is_admin = not target.is_admin
    record_event(db, "admin.role_change", "user", target.id, user, {"is_admin": target.is_admin})
    db.commit()
    return RedirectResponse("/admin", 303)


@router.post("/users/{user_id}/reset")
def admin_reset(request: Request, db: Db, user: AdminUser, user_id: str, csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    target = db.get(User, user_id)
    if not target or target.auth_source != "local":
        raise HTTPException(422, detail="Local user required")
    settings = get_settings()
    if settings.smtp_host:
        raw, digest = new_reset_token()
        db.add(PasswordResetToken(user_id=target.id, token_hash=digest, expires_at=datetime.now(UTC) + timedelta(minutes=settings.password_reset_minutes)))
        record_event(db, "admin.password_reset_link", "user", target.id, user)
        db.commit()
        link = f"{settings.public_base_url}/reset-password/{raw}"
        send_email(settings, target.email, "ListsLists password reset", f"An administrator issued this single-use reset link:\n\n{link}")
        return RedirectResponse("/admin", 303)
    temporary = secrets.token_urlsafe(18)
    target.password_hash = hash_password(temporary)
    target.must_change_password = True
    record_event(db, "admin.temporary_password", "user", target.id, user)
    db.commit()
    return request.app.state.templates.TemplateResponse(request, "message.html", {"message": f"Temporary password (show once): {temporary}", "user": user})


@router.post("/email-test")
def test_email(request: Request, user: AdminUser, to: str = Form(), csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    send_email(get_settings(), to, "ListsLists SMTP test", "Email delivery is working.")
    return RedirectResponse("/admin", 303)
