import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_or_create_correlation_id
from app.core.db import get_session
from app.core.security import require_service_token
from app.schemas.transaction import TransactionImportRequest, TransactionImportResponse
from app.services.ingestion import import_transaction

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post(
    "/import",
    response_model=TransactionImportResponse,
    dependencies=[Depends(require_service_token)],
)
async def import_transactions(
    body: TransactionImportRequest,
    session: AsyncSession = Depends(get_session),
    correlation_id: uuid.UUID = Depends(get_or_create_correlation_id),
) -> TransactionImportResponse:
    # Whole batch commits atomically: if anything fails mid-batch nothing is
    # persisted, so a client can safely resubmit the same batch -- already
    # committed rows from a *previous* successful call are caught by the
    # (organization_id, fingerprint) unique constraint and reported as
    # duplicates rather than re-imported.
    results = []
    try:
        for item in body.transactions:
            results.append(await import_transaction(session, item, correlation_id))
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="import failed, no changes were committed",
        ) from exc

    return TransactionImportResponse(
        correlation_id=correlation_id,
        imported=sum(1 for r in results if r.status == "imported"),
        duplicates=sum(1 for r in results if r.status == "duplicate"),
        alerts_created=sum(1 for r in results if r.alert_created),
        results=results,
    )
