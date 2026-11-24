import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_or_create_correlation_id
from app.core.db import get_session
from app.core.security import Actor, get_case_creation_actor, get_current_analyst
from app.schemas.case import (
    AuditEventResponse,
    CaseAssignRequest,
    CaseCreateRequest,
    CaseEvidenceCreateRequest,
    CaseEvidenceItemResponse,
    CaseEvidenceListResponse,
    CaseEvidenceResponse,
    CaseHistoryEntryResponse,
    CaseHistoryResponse,
    CaseResponse,
    CaseStatusChangeRequest,
    CaseTransactionLinkRequest,
    CaseTransactionLinkResponse,
)
from app.services.cases import (
    CaseAuthorizationError,
    CaseNotFoundError,
    CrossOrganizationReferenceError,
    InvalidAssigneeError,
    InvalidStatusTransitionError,
    add_evidence,
    assign_case,
    create_case_from_alert,
    get_case_history,
    link_transaction,
    list_evidence,
    transition_status,
)

router = APIRouter(prefix="/cases", tags=["cases"])


def _case_response(case, *, created: bool) -> CaseResponse:
    return CaseResponse(
        id=case.id,
        organization_id=case.organization_id,
        alert_id=case.alert_id,
        status=case.status,
        priority=case.priority,
        assigned_analyst_id=case.assigned_analyst_id,
        correlation_id=case.correlation_id,
        created_at=case.created_at,
        updated_at=case.updated_at,
        created=created,
    )


@router.post("", response_model=CaseResponse)
async def create_case(
    body: CaseCreateRequest,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(get_case_creation_actor),
    correlation_id: uuid.UUID = Depends(get_or_create_correlation_id),
) -> CaseResponse:
    """CAS-061. Callable by the n8n service actor (automatic case creation
    on a qualifying alert) or by an analyst. Idempotent per alert."""
    try:
        case, created = await create_case_from_alert(
            session,
            actor=actor,
            alert_id=body.alert_id,
            priority=body.priority,
            correlation_id=correlation_id,
        )
        await session.commit()
    except CaseNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="case creation failed, no changes were committed",
        ) from exc

    return _case_response(case, created=created)


@router.post("/{case_id}/assign", response_model=CaseResponse)
async def assign(
    case_id: uuid.UUID,
    body: CaseAssignRequest,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(get_current_analyst),
    correlation_id: uuid.UUID = Depends(get_or_create_correlation_id),
) -> CaseResponse:
    """CAS-062."""
    try:
        case = await assign_case(
            session,
            actor=actor,
            case_id=case_id,
            target_analyst_id=body.analyst_id,
            correlation_id=correlation_id,
        )
        await session.commit()
    except CaseNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CaseAuthorizationError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except InvalidAssigneeError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="assignment failed, no changes were committed",
        ) from exc

    return _case_response(case, created=False)


@router.post("/{case_id}/status", response_model=CaseResponse)
async def change_status(
    case_id: uuid.UUID,
    body: CaseStatusChangeRequest,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(get_current_analyst),
    correlation_id: uuid.UUID = Depends(get_or_create_correlation_id),
) -> CaseResponse:
    """CAS-063. Analyst-only -- the automated workflow may create a case
    but never transitions or closes one (plan.md §0/§6: no automated actor
    makes a consequential case decision)."""
    try:
        case = await transition_status(
            session,
            actor=actor,
            case_id=case_id,
            new_status=body.status,
            reason=body.reason,
            correlation_id=correlation_id,
        )
        await session.commit()
    except CaseNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidStatusTransitionError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="status change failed, no changes were committed",
        ) from exc

    return _case_response(case, created=False)


@router.post("/{case_id}/transactions", response_model=CaseTransactionLinkResponse)
async def link_case_transaction(
    case_id: uuid.UUID,
    body: CaseTransactionLinkRequest,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(get_current_analyst),
    correlation_id: uuid.UUID = Depends(get_or_create_correlation_id),
) -> CaseTransactionLinkResponse:
    """CAS-064 (transaction side)."""
    try:
        linked = await link_transaction(
            session,
            actor=actor,
            case_id=case_id,
            transaction_id=body.transaction_id,
            correlation_id=correlation_id,
        )
        await session.commit()
    except CaseNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CrossOrganizationReferenceError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="link failed, no changes were committed",
        ) from exc

    return CaseTransactionLinkResponse(transaction_id=body.transaction_id, linked=linked)


@router.post("/{case_id}/evidence", response_model=CaseEvidenceResponse)
async def add_case_evidence(
    case_id: uuid.UUID,
    body: CaseEvidenceCreateRequest,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(get_current_analyst),
    correlation_id: uuid.UUID = Depends(get_or_create_correlation_id),
) -> CaseEvidenceResponse:
    """CAS-064 (evidence-metadata side)."""
    try:
        evidence = await add_evidence(
            session,
            actor=actor,
            case_id=case_id,
            title=body.title,
            description=body.description,
            source_reference=body.source_reference,
            content=body.content,
            correlation_id=correlation_id,
        )
        await session.commit()
    except CaseNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="evidence creation failed, no changes were committed",
        ) from exc

    return CaseEvidenceResponse(
        id=evidence.id,
        title=evidence.title,
        description=evidence.description,
        source_reference=evidence.source_reference,
        content_hash=evidence.content_hash,
        added_by_analyst_id=evidence.added_by_analyst_id,
        created_at=evidence.created_at,
    )


@router.get("/{case_id}/evidence", response_model=CaseEvidenceListResponse)
async def read_case_evidence(
    case_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(get_current_analyst),
) -> CaseEvidenceListResponse:
    """CAS-064 (evidence read side). Every call is itself an audited
    `case.evidence_accessed` event, and each item's stored content_hash is
    re-verified against its current content (Sprint 4 access-logging +
    integrity requirements)."""
    try:
        case, verified_items = await list_evidence(session, actor=actor, case_id=case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return CaseEvidenceListResponse(
        case_id=case.id,
        items=[
            CaseEvidenceItemResponse(
                id=item.id,
                title=item.title,
                description=item.description,
                source_reference=item.source_reference,
                content=item.content,
                content_hash=item.content_hash,
                integrity_ok=integrity_ok,
                added_by_analyst_id=item.added_by_analyst_id,
                created_at=item.created_at,
            )
            for item, integrity_ok in verified_items
        ],
    )


@router.get("/{case_id}/history", response_model=CaseHistoryResponse)
async def read_case_history(
    case_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(get_current_analyst),
) -> CaseHistoryResponse:
    """CAS-065."""
    try:
        case, history, audit_events = await get_case_history(session, actor=actor, case_id=case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return CaseHistoryResponse(
        case_id=case.id,
        history=[
            CaseHistoryEntryResponse(
                id=h.id,
                event_type=h.event_type,
                actor_analyst_id=h.actor_analyst_id,
                correlation_id=h.correlation_id,
                details=h.details,
                created_at=h.created_at,
            )
            for h in history
        ],
        audit_events=[
            AuditEventResponse(
                id=a.id,
                event_type=a.event_type,
                correlation_id=a.correlation_id,
                payload=a.payload,
                created_at=a.created_at,
            )
            for a in audit_events
        ],
    )
