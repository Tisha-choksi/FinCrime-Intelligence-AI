import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent


class AuditEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        organization_id: uuid.UUID | None,
        event_type: str,
        entity_type: str,
        entity_id: uuid.UUID | None,
        correlation_id: uuid.UUID,
        payload: dict,
    ) -> AuditEvent:
        event = AuditEvent(
            id=uuid.uuid4(),
            organization_id=organization_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            correlation_id=correlation_id,
            payload=payload,
        )
        self._session.add(event)
        await self._session.flush()
        return event
