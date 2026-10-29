import hashlib
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction


def compute_fingerprint(
    organization_id: uuid.UUID, source_id: str, amount: Decimal, currency: str, occurred_at: datetime
) -> str:
    raw = f"{organization_id}|{source_id}|{amount}|{currency}|{occurred_at.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_if_new(
        self,
        *,
        organization_id: uuid.UUID,
        source_id: str,
        amount: Decimal,
        currency: str,
        occurred_at: datetime,
        raw_payload: dict,
    ) -> tuple[Transaction, bool]:
        """Atomic idempotent insert. Returns (transaction, is_new).

        Uses INSERT ... ON CONFLICT DO NOTHING rather than check-then-insert
        so that concurrent/retried imports of the same transaction can never
        race into two rows.
        """
        fingerprint = compute_fingerprint(organization_id, source_id, amount, currency, occurred_at)
        stmt = (
            pg_insert(Transaction)
            .values(
                id=uuid.uuid4(),
                organization_id=organization_id,
                source_id=source_id,
                amount=amount,
                currency=currency,
                occurred_at=occurred_at,
                fingerprint=fingerprint,
                raw_payload=raw_payload,
            )
            .on_conflict_do_nothing(index_elements=["organization_id", "fingerprint"])
            .returning(Transaction)
        )
        result = await self._session.execute(stmt)
        inserted = result.scalar_one_or_none()
        if inserted is not None:
            return inserted, True

        existing = await self._session.execute(
            select(Transaction).where(
                Transaction.organization_id == organization_id,
                Transaction.fingerprint == fingerprint,
            )
        )
        return existing.scalar_one(), False
