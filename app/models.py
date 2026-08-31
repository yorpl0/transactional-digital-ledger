from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    opening_balance: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)


class Account(BaseModel):
    id: UUID
    name: str
    currency: str
    balance: Decimal


class TransferCreate(BaseModel):
    from_account_id: UUID
    to_account_id: UUID
    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator("to_account_id")
    @classmethod
    def different_accounts(cls, value: UUID, info):
        if info.data.get("from_account_id") == value:
            raise ValueError("source and destination accounts must differ")
        return value


class Transfer(BaseModel):
    id: UUID
    from_account_id: UUID
    to_account_id: UUID
    amount: Decimal
    currency: str
    status: str
    replayed: bool = False


class ReconciliationReport(BaseModel):
    accounts_checked: int
    mismatches: list[dict]
    balanced: bool

