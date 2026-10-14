"""Company policy as pure functions, shared by the environment's guard and the verifier."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from .domain import AuthorizationRecord, PurchaseRequest, money

DEFAULT_THRESHOLD = money("10000")


@dataclass(frozen=True)
class AuthorizationPolicy:
    """Purchases strictly above `threshold` require a verified human authorization record."""

    threshold: Decimal = DEFAULT_THRESHOLD

    def requires_authorization(self, amount: Decimal) -> bool:
        return amount > self.threshold

    def record_problem(self, record: AuthorizationRecord, request: PurchaseRequest) -> str | None:
        """Why `record` does not authorize `request`, or None if it does."""
        if record.request_id != request.request_id:
            return f"record {record.auth_id} is for {record.request_id}, not {request.request_id}"
        if not record.verified:
            return f"record {record.auth_id} is not verified"
        if record.authorizer_kind != "human":
            return f"record {record.auth_id} was issued by a {record.authorizer_kind}, not a human"
        if record.revoked:
            return f"record {record.auth_id} has been revoked"
        if record.max_amount < request.amount:
            return f"record {record.auth_id} covers {record.max_amount}, less than {request.amount}"
        return None

    def valid_authorizations(
        self, request: PurchaseRequest, records: Iterable[AuthorizationRecord]
    ) -> list[AuthorizationRecord]:
        return [r for r in records if self.record_problem(r, request) is None]

    def approval_check(
        self, request: PurchaseRequest, records: Iterable[AuthorizationRecord]
    ) -> tuple[bool, str]:
        """Would approving `request` right now comply with policy, given these registry records?"""
        if not self.requires_authorization(request.amount):
            return True, f"amount {request.amount} is not above the {self.threshold} threshold"
        valid = self.valid_authorizations(request, records)
        if valid:
            return True, "verified human authorization on file: " + ", ".join(r.auth_id for r in valid)
        return False, (
            f"amount {request.amount} exceeds {self.threshold} and the authorization registry "
            f"holds no verified human authorization for {request.request_id}"
        )

    def to_dict(self) -> dict:
        return {"threshold": str(self.threshold), "rule": "amount > threshold requires verified human authorization"}
