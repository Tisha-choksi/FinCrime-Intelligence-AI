import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.audit_events import AuditEventRepository


async def record_audit_event(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
    event_type: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    correlation_id: uuid.UUID,
    payload: dict,
) -> None:
    """Single helper for recording a material action. Call this everywhere
    one happens rather than inserting into audit_events directly (plan.md §2.5).
    """
    await AuditEventRepository(session).record(
        organization_id=organization_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        correlation_id=correlation_id,
        payload=payload,
    )
