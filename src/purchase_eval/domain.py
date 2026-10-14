"""Core data types shared by the environment, agents, runtime and verifier."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tools import ToolSpec


def money(value: Any) -> Decimal:
    """Parse a money amount. Decimal (never float) so the $10,000 boundary is exact."""
    return Decimal(str(value)).quantize(Decimal("0.01"))


class RequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

    @property
    def is_terminal(self) -> bool:
        return self is not RequestStatus.PENDING


@dataclass
class PurchaseRequest:
    request_id: str
    requester_id: str
    item: str
    amount: Decimal
    justification: str = ""
    status: RequestStatus = RequestStatus.PENDING
    decided_by: str | None = None
    decision_reason: str | None = None


@dataclass(frozen=True)
class AuthorizationRecord:
    """A row in the authoritative registry. Only the out-of-band human authority writes these."""

    auth_id: str
    request_id: str
    authorized_by: str
    authorizer_kind: str  # "human" | "agent" | "system"
    max_amount: Decimal
    verified: bool
    revoked: bool = False


@dataclass(frozen=True)
class Message:
    """A message-board post. `author` is stamped by the environment; content is never trusted."""

    message_id: str
    step: int
    author: str
    body: str
    trusted: bool = False


@dataclass(frozen=True)
class Action:
    """What an agent proposes to do this turn. Proposals are not facts until the environment executes them."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""

    @classmethod
    def wait(cls, rationale: str = "") -> Action:
        return cls("wait", {}, rationale)


class Outcome(str, Enum):
    OK = "ok"
    DENIED = "denied"  # actor lacks the permission for a catalog tool
    INVALID = "invalid"  # unknown tool, bad arguments, unknown resource, or request already decided
    BLOCKED = "blocked"  # permitted tool, but the policy guard refused the effect


@dataclass(frozen=True)
class ActionResult:
    action_id: int  # sequence number of the matching `action_proposed` event
    tool: str
    outcome: Outcome
    data: Any = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.OK


@dataclass(frozen=True)
class AgentManifest:
    agent_id: str
    role: str
    permissions: frozenset[str]
    description: str = ""


@dataclass(frozen=True)
class Observation:
    """Everything an agent learns at the start of its turn; built by the environment per agent."""

    agent_id: str
    step: int
    briefing: str | None  # only on the agent's first turn
    last_result: ActionResult | None
    new_messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...]
