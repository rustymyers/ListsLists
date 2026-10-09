from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Visibility(str, enum.Enum):
    private = "private"
    shared = "shared"
    unlisted = "unlisted"
    public = "public"


class ShareRole(str, enum.Enum):
    editor = "editor"
    viewer = "viewer"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    auth_source: Mapped[str] = mapped_column(String(20), default="local")
    list_view: Mapped[str] = mapped_column(String(10), default="cards")
    item_view: Mapped[str] = mapped_column(String(10), default="cards")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ListModel(Base):
    __tablename__ = "lists"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(200), index=True)
    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    visibility: Mapped[Visibility] = mapped_column(Enum(Visibility), default=Visibility.private)
    default_sort: Mapped[dict[str, Any]] = mapped_column(JSON, default=lambda: {"field": "position", "direction": "asc"})
    custom_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship()
    items: Mapped[list["ListItem"]] = relationship(
        back_populates="list",
        cascade="all, delete-orphan",
        order_by="ListItem.position",
        foreign_keys="ListItem.list_id",
    )
    shares: Mapped[list["ListShare"]] = relationship(back_populates="list", cascade="all, delete-orphan")


class CanonicalItem(Base):
    __tablename__ = "canonical_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(240), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(40), default="each")
    category: Mapped[str | None] = mapped_column(String(120), index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    storage_location: Mapped[str | None] = mapped_column(String(240))
    usage_context: Mapped[str | None] = mapped_column(String(240))
    notes: Mapped[str] = mapped_column(Text, default="")
    identity_key: Mapped[str | None] = mapped_column(String(160), index=True)
    conditional_requirements: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    custom_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship()


class ListItem(Base):
    __tablename__ = "list_items"
    __table_args__ = (Index("ix_items_list_position", "list_id", "position"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    list_id: Mapped[str] = mapped_column(ForeignKey("lists.id", ondelete="CASCADE"), index=True)
    canonical_item_id: Mapped[str | None] = mapped_column(ForeignKey("canonical_items.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    packing_spot: Mapped[str | None] = mapped_column(String(240))
    unit: Mapped[str] = mapped_column(String(40), default="each")
    category: Mapped[str | None] = mapped_column(String(120), index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    storage_location: Mapped[str | None] = mapped_column(String(240))
    usage_context: Mapped[str | None] = mapped_column(String(240))
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    referenced_list_id: Mapped[str | None] = mapped_column(ForeignKey("lists.id", ondelete="RESTRICT"), index=True)
    identity_key: Mapped[str | None] = mapped_column(String(160), index=True)
    conditional_requirements: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    custom_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    list: Mapped[ListModel] = relationship(back_populates="items", foreign_keys=[list_id])
    canonical_item: Mapped[CanonicalItem | None] = relationship(foreign_keys=[canonical_item_id])
    referenced_list: Mapped[ListModel | None] = relationship(foreign_keys=[referenced_list_id])
    dependencies = relationship(
        "ItemDependency",
        foreign_keys="ItemDependency.item_id",
        cascade="all, delete-orphan",
        uselist=True,
    )


class ItemDependency(Base):
    __tablename__ = "item_dependencies"
    __table_args__ = (UniqueConstraint("item_id", "depends_on_item_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    item_id: Mapped[str] = mapped_column(ForeignKey("list_items.id", ondelete="CASCADE"), index=True)
    depends_on_item_id: Mapped[str] = mapped_column(ForeignKey("list_items.id", ondelete="CASCADE"), index=True)
    condition: Mapped[str | None] = mapped_column(String(240))
    required: Mapped[bool] = mapped_column(Boolean, default=True)

    depends_on: Mapped[ListItem] = relationship(foreign_keys=[depends_on_item_id])


class ListShare(Base):
    __tablename__ = "list_shares"
    __table_args__ = (UniqueConstraint("list_id", "user_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    list_id: Mapped[str] = mapped_column(ForeignKey("lists.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[ShareRole] = mapped_column(Enum(ShareRole))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    list: Mapped[ListModel] = relationship(back_populates="shares")
    user: Mapped[User] = relationship()


class ExportProfile(Base):
    __tablename__ = "export_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    format: Mapped[str] = mapped_column(String(10), default="json")
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    target_type: Mapped[str] = mapped_column(String(50), index=True)
    target_id: Mapped[str | None] = mapped_column(String(36), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    actor: Mapped[User | None] = relationship()


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
