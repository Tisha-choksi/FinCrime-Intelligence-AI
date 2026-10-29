import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.alerts import AlertRepository
from app.repositories.transactions import TransactionRepository
from app.schemas.transaction import TransactionImportResult, TransactionIn
from app.services.audit import record_audit_event
from app.services.monitoring import evaluate_mon_011


async def import_transaction(
    session: AsyncSession, item: TransactionIn, correlation_id: uuid.UUID
) -> TransactionImportResult:
    tx_repo = TransactionRepository(session)
    alert_repo = AlertRepository(session)

    transaction, is_new = await tx_repo.insert_if_new(
        organization_id=item.organization_id,
        source_id=item.source_id,
        amount=item.amount,
        currency=item.currency,
        occurred_at=item.occurred_at,
        raw_payload=item.raw_payload,
    )

    if not is_new:
        await record_audit_event(
            session,
            organization_id=item.organization_id,
            event_type="transaction.duplicate_rejected",
            entity_type="transaction",
            entity_id=transaction.id,
            correlation_id=correlation_id,
            payload={"source_id": item.source_id},
        )
        return TransactionImportResult(
            source_id=item.source_id,
            status="duplicate",
            transaction_id=transaction.id,
            alert_created=False,
        )

    await record_audit_event(
        session,
        organization_id=item.organization_id,
        event_type="transaction.ingested",
        entity_type="transaction",
        entity_id=transaction.id,
        correlation_id=correlation_id,
        payload={"source_id": item.source_id, "amount": str(item.amount), "currency": item.currency},
    )

    result = await evaluate_mon_011(session, transaction)
    alert_created = False
    if result.triggered:
        alert = await alert_repo.create(
            organization_id=item.organization_id,
            transaction_id=transaction.id,
            rule_code="MON-011",
            rule_version=result.rule_version,
            correlation_id=correlation_id,
            details=result.details,
        )
        await record_audit_event(
            session,
            organization_id=item.organization_id,
            event_type="alert.created",
            entity_type="alert",
            entity_id=alert.id,
            correlation_id=correlation_id,
            payload=result.details,
        )
        alert_created = True

    return TransactionImportResult(
        source_id=item.source_id,
        status="imported",
        transaction_id=transaction.id,
        alert_created=alert_created,
    )
