from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent, User


def record_event(
    db: Session,
    action: str,
    target_type: str,
    target_id: str | None,
    actor: User | None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        action=action,
        target_type=target_type,
        target_id=target_id,
        actor_id=actor.id if actor else None,
        details=details or {},
        ip_address=ip_address,
    )
    db.add(event)
    return event
