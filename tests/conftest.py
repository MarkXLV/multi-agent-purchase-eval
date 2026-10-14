from __future__ import annotations

import pytest

from purchase_eval.domain import AgentManifest, AuthorizationRecord, PurchaseRequest, money
from purchase_eval.environment import Environment
from purchase_eval.events import EventLog
from purchase_eval.policy import AuthorizationPolicy
from purchase_eval.runner import APPROVER_PERMISSIONS, REQUESTER_PERMISSIONS
from purchase_eval.state import AuthorizationRegistry, EnvironmentState

REQUESTER = AgentManifest("requester", "requester", REQUESTER_PERMISSIONS)
APPROVER = AgentManifest("approver", "approver", APPROVER_PERMISSIONS)


def human_auth(rid: str, amount: str = "25000", **overrides) -> AuthorizationRecord:
    fields = dict(auth_id=f"AUTH-{rid}", request_id=rid, authorized_by="Dana (CFO)",
                  authorizer_kind="human", max_amount=money(amount), verified=True)
    fields.update(overrides)
    return AuthorizationRecord(**fields)


def make_env(amount: str = "25000", records=(), *, guard: bool = True, agents=(REQUESTER, APPROVER)) -> Environment:
    request = PurchaseRequest("PR-1", "requester", "Widget", money(amount), "needed")
    other = PurchaseRequest("PR-2", "someone_else", "Gadget", money("100"), "")
    state = EnvironmentState(requests={"PR-1": request, "PR-2": other},
                             registry=AuthorizationRegistry(list(records)))
    env = Environment(state, AuthorizationPolicy(), EventLog(), enforce_policy_guard=guard)
    for manifest in agents:
        env.register_agent(manifest, briefing=f"hello {manifest.agent_id}")
    return env


@pytest.fixture
def env() -> Environment:
    return make_env()
