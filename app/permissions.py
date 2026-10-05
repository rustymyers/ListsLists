from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ListModel, ListShare, ShareRole, User, Visibility


def share_role(db: Session, user: User | None, list_obj: ListModel) -> ShareRole | None:
    if not user:
        return None
    return db.scalar(
        select(ListShare.role).where(ListShare.list_id == list_obj.id, ListShare.user_id == user.id)
    )


def can_view(db: Session, user: User | None, list_obj: ListModel, *, allow_unlisted: bool = False) -> bool:
    if list_obj.deleted_at is not None:
        return False
    if user and (user.is_admin or list_obj.owner_id == user.id):
        return True
    if list_obj.visibility == Visibility.public:
        return True
    if allow_unlisted and list_obj.visibility == Visibility.unlisted:
        return True
    return share_role(db, user, list_obj) in {ShareRole.viewer, ShareRole.editor}


def can_edit(db: Session, user: User | None, list_obj: ListModel) -> bool:
    if not user or list_obj.deleted_at is not None:
        return False
    if user.is_admin or list_obj.owner_id == user.id:
        return True
    return share_role(db, user, list_obj) == ShareRole.editor


def can_manage(db: Session, user: User | None, list_obj: ListModel) -> bool:
    return bool(user and (user.is_admin or list_obj.owner_id == user.id) and list_obj.deleted_at is None)


def require_view(db: Session, user: User | None, list_obj: ListModel, *, allow_unlisted: bool = False) -> None:
    if not can_view(db, user, list_obj, allow_unlisted=allow_unlisted):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="List not found")


def require_edit(db: Session, user: User | None, list_obj: ListModel) -> None:
    if not can_edit(db, user, list_obj):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Editor access required")


def require_manage(db: Session, user: User | None, list_obj: ListModel) -> None:
    if not can_manage(db, user, list_obj):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner access required")
