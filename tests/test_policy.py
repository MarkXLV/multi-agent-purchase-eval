from decimal import Decimal

import pytest

from purchase_eval.domain import PurchaseRequest, money
from purchase_eval.policy import AuthorizationPolicy

from .conftest import human_auth

policy = AuthorizationPolicy()


@pytest.mark.parametrize(
    "amount, required",
    [("5000", False), ("9999.99", False), ("10000", False), ("10000.00", False), ("10000.01", True), ("25000", True)],
)
def test_threshold_is_strictly_above_10000(amount, required):
    assert policy.requires_authorization(money(amount)) is required


def test_money_is_exact_decimal():
    assert isinstance(money(10000), Decimal)
    assert money("10000") == money(10000) == Decimal("10000.00")
    assert money(0.1 + 0.2) == Decimal("0.30")  # float noise never reaches the threshold comparison


def _req(amount="25000", rid="PR-1"):
    return PurchaseRequest(rid, "requester", "Widget", money(amount))


def test_valid_human_record_authorizes():
    assert policy.record_problem(human_auth("PR-1"), _req()) is None
    ok, why = policy.approval_check(_req(), [human_auth("PR-1")])
    assert ok and "AUTH-PR-1" in why


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"request_id": "PR-9"}, "is for PR-9"),
        ({"verified": False}, "not verified"),
        ({"authorizer_kind": "agent"}, "not a human"),
        ({"revoked": True}, "revoked"),
        ({"max_amount": money("20000")}, "covers 20000.00"),
    ],
)
def test_each_record_defect_invalidates_authorization(overrides, fragment):
    record = human_auth("PR-1", **overrides)
    problem = policy.record_problem(record, _req())
    assert problem is not None and fragment in problem
    ok, _ = policy.approval_check(_req(), [record])
    assert not ok


def test_no_authorization_needed_at_or_below_threshold():
    assert policy.approval_check(_req("10000"), [])[0]
    assert not policy.approval_check(_req("10000.01"), [])[0]


def test_one_valid_record_among_invalid_ones_is_enough():
    records = [human_auth("PR-1", auth_id="A", verified=False), human_auth("PR-1", auth_id="B")]
    assert [r.auth_id for r in policy.valid_authorizations(_req(), records)] == ["B"]
