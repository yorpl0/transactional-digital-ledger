from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models import TransferCreate
from app.service import request_fingerprint


def test_fingerprint_is_deterministic() -> None:
    source, destination = uuid4(), uuid4()
    request = TransferCreate(
        from_account_id=source,
        to_account_id=destination,
        amount=Decimal("10.00"),
        currency="USD",
        idempotency_key="request-123",
    )
    assert request_fingerprint(request) == request_fingerprint(request)
    assert len(request_fingerprint(request)) == 64


def test_rejects_self_transfer() -> None:
    account_id = uuid4()
    with pytest.raises(ValidationError):
        TransferCreate(
            from_account_id=account_id,
            to_account_id=account_id,
            amount=Decimal("1.00"),
            currency="USD",
            idempotency_key="request-123",
        )

