from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from app.config import get_settings
from app.dependencies import Db, OptionalUser
from app.models import PasswordResetToken, User
from app.security import ensure_csrf, hash_password, new_reset_token, reset_token_hash, verify_password
from app.services.audit import record_event
from app.services.email import send_email

router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    return request.app.state.templates.TemplateResponse(request, "login.html", {})


@router.post("/login")
def login(request: Request, db: Db, username: str = Form(), password: str = Form(), csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    if get_settings().auth_mode == "proxy":
        raise HTTPException(403, detail="Local authentication is disabled")
    user = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        record_event(db, "auth.login_failed", "user", user.id if user else None, user, {"username": username}, request.client.host if request.client else None)
        db.commit()
        return request.app.state.templates.TemplateResponse(
            request,
            "login.html",
            {"username": username, "error": "Invalid credentials"},
            status_code=401,
        )
    request.session.clear()
    request.session["user_id"] = user.id
    record_event(db, "auth.login", "user", user.id, user, ip_address=request.client.host if request.client else None)
    db.commit()
    return RedirectResponse("/change-password" if user.must_change_password else "/", status_code=303)


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/change-password")
def change_password_page(request: Request, user: OptionalUser):
    if not user:
        return RedirectResponse("/login", status_code=303)
    return request.app.state.templates.TemplateResponse(request, "change_password.html", {"user": user})


@router.post("/change-password")
def change_password(request: Request, db: Db, user: OptionalUser, password: str = Form(), current_password: str = Form(""), csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    if not user:
        raise HTTPException(401, detail="Authentication required")
    if not user.must_change_password and not verify_password(current_password, user.password_hash):
        raise HTTPException(400, detail="Current password is incorrect")
    user.password_hash = hash_password(password)
    user.must_change_password = False
    record_event(db, "auth.password_change", "user", user.id, user)
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.get("/forgot-password")
def forgot_page(request: Request):
    return request.app.state.templates.TemplateResponse(request, "forgot.html", {})


@router.post("/forgot-password")
def forgot(request: Request, db: Db, email: str = Form(), csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    if get_settings().auth_mode == "proxy":
        raise HTTPException(403, detail="Local authentication is disabled")
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower(), User.auth_source == "local"))
    if user and user.is_active:
        raw, digest = new_reset_token()
        settings = get_settings()
        db.add(PasswordResetToken(user_id=user.id, token_hash=digest, expires_at=datetime.now(UTC) + timedelta(minutes=settings.password_reset_minutes)))
        db.commit()
        link = f"{settings.public_base_url}/reset-password/{raw}"
        send_email(settings, user.email, "ListsLists password reset", f"Use this single-use link before it expires:\n\n{link}")
    return request.app.state.templates.TemplateResponse(request, "message.html", {"message": "If that address is eligible, a reset link has been sent."})


@router.get("/reset-password/{raw_token}")
def reset_page(request: Request, raw_token: str):
    return request.app.state.templates.TemplateResponse(request, "reset.html", {"raw_token": raw_token})


@router.post("/reset-password/{raw_token}")
def reset_password(request: Request, db: Db, raw_token: str, password: str = Form(), csrf_token: str = Form()):
    ensure_csrf(request, csrf_token)
    token = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == reset_token_hash(raw_token)))
    now = datetime.now(UTC)
    if not token or token.used_at or token.expires_at.replace(tzinfo=UTC) <= now:
        raise HTTPException(400, detail="Reset token is invalid or expired")
    user = db.get(User, token.user_id)
    user.password_hash = hash_password(password)
    user.must_change_password = False
    token.used_at = now
    record_event(db, "auth.password_reset", "user", user.id, user)
    db.commit()
    return RedirectResponse("/login", status_code=303)
