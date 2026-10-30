import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class TransactionIn(BaseModel):
    organization_id: uuid.UUID
    source_id: str = Field(min_length=1, max_length=255)
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    occurred_at: datetime
    raw_payload: dict = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, value: str) -> str:
        return value.upper()


class TransactionImportRequest(BaseModel):
    transactions: list[TransactionIn] = Field(min_length=1, max_length=1000)


class TransactionImportResult(BaseModel):
    source_id: str
    status: str  # "imported" | "duplicate"
    transaction_id: uuid.UUID
    alert_created: bool


class TransactionImportResponse(BaseModel):
    correlation_id: uuid.UUID
    imported: int
    duplicates: int
    alerts_created: int
    results: list[TransactionImportResult]
