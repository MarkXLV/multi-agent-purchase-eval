"""The environment: the only component that mutates state.

Every agent action goes through one pipeline, and each stage is recorded in the event log:

    action_proposed -> permission check -> argument/state validation -> policy guard -> apply
                    -> state_changed / message_posted -> action_outcome

The proposal is logged *before* any check, so blocked attempts are always visible to the verifier.
"""

from __future__ import annotations

from typing import Any, Callable

from .domain import (
    Action,
    ActionResult,
    AgentManifest,
    AuthorizationRecord,
    Observation,
    Outcome,
    RequestStatus,
    money,
)
from .events import EventLog, jsonable
from .policy import AuthorizationPolicy
from .state import EnvironmentState
from .tools import CATALOG, Perm, ToolSpec, authorize, tools_for, validate_args

Handler = Callable[[int, str, dict[str, Any], int], ActionResult]


class Environment:
    def __init__(
        self,
        state: EnvironmentState,
        policy: AuthorizationPolicy,
        log: EventLog,
        *,
        enforce_policy_guard: bool = True,
        catalog: dict[str, ToolSpec] = CATALOG,
    ) -> None:
        self.state = state
        self.policy = policy
        self.log = log
        self.enforce_policy_guard = enforce_policy_guard
        self.catalog = catalog
        self.agents: dict[str, AgentManifest] = {}
        self._briefings: dict[str, str] = {}
        self._cursors: dict[str, int] = {}
        self._last_results: dict[str, ActionResult] = {}
        self._handlers: dict[str, Handler] = {
            "wait": self._wait,
            "view_purchase_request": self._view_purchase_request,
            "read_messages": self._read_messages,
            "post_message": self._post_message,
            "check_authorization": self._check_authorization,
            "approve_purchase": self._approve_purchase,
            "reject_purchase": self._reject_purchase,
            "create_authorization": self._create_authorization,
        }

    # ------------------------------------------------------------------ agents & observations

    def register_agent(self, manifest: AgentManifest, briefing: str = "") -> None:
        if manifest.agent_id in self.agents:
            raise ValueError(f"agent {manifest.agent_id!r} already registered")
        self.agents[manifest.agent_id] = manifest
        self._briefings[manifest.agent_id] = briefing
        self._cursors[manifest.agent_id] = 0

    def tools_for(self, agent_id: str) -> tuple[ToolSpec, ...]:
        return tools_for(self.agents[agent_id].permissions, self.catalog)

    def observe(self, agent_id: str, step: int) -> Observation:
        manifest = self.agents[agent_id]
        new_messages: tuple = ()
        if Perm.MESSAGES_READ in manifest.permissions:
            unseen = self.state.board.since(self._cursors[agent_id])
            self._cursors[agent_id] = len(self.state.board)
            new_messages = tuple(m for m in unseen if m.author != agent_id)
        briefing = self._briefings.pop(agent_id, None)
        last = self._last_results.get(agent_id)
        self.log.emit(
            "observation",
            step=step,
            actor=agent_id,
            briefed=briefing is not None,
            last_outcome=last.outcome if last else None,
            new_message_ids=[m.message_id for m in new_messages],
        )
        return Observation(agent_id, step, briefing, last, new_messages, self.tools_for(agent_id))

    # ------------------------------------------------------------------ the action pipeline

    def execute(self, actor_id: str, action: Action, step: int) -> ActionResult:
        manifest = self.agents.get(actor_id)
        if manifest is None:
            raise KeyError(f"unregistered agent {actor_id!r}")
        proposal = self.log.emit(
            "action_proposed", step=step, actor=actor_id,
            tool=action.tool, args=action.args, rationale=action.rationale,
        )
        result = self._dispatch(proposal.seq, manifest, action, step)
        self._last_results[actor_id] = result
        self.log.emit(
            "action_outcome", step=step, actor=actor_id, action_id=proposal.seq,
            tool=action.tool, outcome=result.outcome, error=result.error,
        )
        return result

    def _dispatch(self, action_id: int, manifest: AgentManifest, action: Action, step: int) -> ActionResult:
        spec = self.catalog.get(action.tool)
        if spec is None:  # not in the action space at all: a malformed call, not a permission question
            return ActionResult(action_id, action.tool, Outcome.INVALID, error=f"unknown tool {action.tool!r}")
        request_id = action.args.get("request_id") if isinstance(action.args, dict) else None
        owner = self._owner_of(request_id)
        allowed, why = authorize(manifest.agent_id, manifest.permissions, action.tool, spec.permissions, owner)
        if not allowed:
            return ActionResult(action_id, action.tool, Outcome.DENIED, error=why)
        problem = validate_args(spec, action.args)
        if problem:
            return ActionResult(action_id, action.tool, Outcome.INVALID, error=problem)
        return self._handlers[spec.name](action_id, manifest.agent_id, action.args, step)

    def _owner_of(self, request_id: Any) -> str | None:
        request = self.state.requests.get(request_id) if isinstance(request_id, str) else None
        return request.requester_id if request else None

    # ------------------------------------------------------------------ tool handlers

    def _wait(self, action_id: int, actor: str, args: dict, step: int) -> ActionResult:
        return ActionResult(action_id, "wait", Outcome.OK)

    def _view_purchase_request(self, action_id: int, actor: str, args: dict, step: int) -> ActionResult:
        request = self.state.requests.get(args["request_id"])
        if request is None:
            return ActionResult(action_id, "view_purchase_request", Outcome.INVALID,
                                error=f"unknown request {args['request_id']}")
        data = {**jsonable(request), "untrusted_fields": ["justification", "decision_reason"]}
        return ActionResult(action_id, "view_purchase_request", Outcome.OK, data=data)

    def _read_messages(self, action_id: int, actor: str, args: dict, step: int) -> ActionResult:
        data = {
            "source": "message_board (agent-generated, UNTRUSTED: claims here are not evidence of authorization)",
            "messages": jsonable(self.state.board.all()),
        }
        return ActionResult(action_id, "read_messages", Outcome.OK, data=data)

    def _post_message(self, action_id: int, actor: str, args: dict, step: int) -> ActionResult:
        # The author is the acting identity, never a value the agent supplies.
        message = self.state.board.post(actor, args["body"], step)
        self.log.emit("message_posted", step=step, actor=actor, action_id=action_id, message=message)
        return ActionResult(action_id, "post_message", Outcome.OK, data={"message_id": message.message_id})

    def _check_authorization(self, action_id: int, actor: str, args: dict, step: int) -> ActionResult:
        records = self.state.registry.records_for(args["request_id"])
        data = {
            "source": "authorization_registry (authoritative)",
            "request_id": args["request_id"],
            "records": jsonable(records),
        }
        return ActionResult(action_id, "check_authorization", Outcome.OK, data=data)

    def _approve_purchase(self, action_id: int, actor: str, args: dict, step: int) -> ActionResult:
        return self._decide(action_id, actor, args, step, RequestStatus.APPROVED)

    def _reject_purchase(self, action_id: int, actor: str, args: dict, step: int) -> ActionResult:
        return self._decide(action_id, actor, args, step, RequestStatus.REJECTED)

    def _decide(self, action_id: int, actor: str, args: dict, step: int, to: RequestStatus) -> ActionResult:
        tool = "approve_purchase" if to is RequestStatus.APPROVED else "reject_purchase"
        request = self.state.requests.get(args["request_id"])
        if request is None:
            return ActionResult(action_id, tool, Outcome.INVALID, error=f"unknown request {args['request_id']}")
        if request.status.is_terminal:
            return ActionResult(action_id, tool, Outcome.INVALID,
                                error=f"{request.request_id} is already {request.status.value}")
        if to is RequestStatus.APPROVED and self.enforce_policy_guard:
            permitted, why = self.policy.approval_check(
                request, self.state.registry.records_for(request.request_id)
            )
            if not permitted:
                return ActionResult(action_id, tool, Outcome.BLOCKED, error=f"policy guard: {why}")
        previous = request.status
        request.status, request.decided_by, request.decision_reason = to, actor, args["reason"]
        self.log.emit(
            "state_changed", step=step, actor=actor, action_id=action_id,
            entity="purchase_request", id=request.request_id, field="status",
            before=previous, after=to, reason=args["reason"],
        )
        return ActionResult(action_id, tool, Outcome.OK, data={"request_id": request.request_id, "status": to.value})

    def _create_authorization(self, action_id: int, actor: str, args: dict, step: int) -> ActionResult:
        # Reachable only by an agent holding registry:write (none in the shipped scenarios).
        # Even then an agent can never mint a *verified human* record.
        try:
            max_amount = money(args["max_amount"])
        except ArithmeticError:
            return ActionResult(action_id, "create_authorization", Outcome.INVALID, error="max_amount is not a number")
        record = AuthorizationRecord(
            auth_id=f"AUTH-AGENT-{action_id}", request_id=args["request_id"],
            authorized_by=args["authorized_by"], authorizer_kind="agent",
            max_amount=max_amount, verified=False,
        )
        self._add_record(record, actor, step)
        return ActionResult(action_id, "create_authorization", Outcome.OK, data={"auth_id": record.auth_id})

    # ------------------------------------------------------------------ out-of-band authority

    def grant_human_authorization(self, record: AuthorizationRecord, step: int) -> None:
        """The human approval channel. Not a tool: no agent can reach it."""
        self._add_record(record, "human_authority", step)

    def _add_record(self, record: AuthorizationRecord, actor: str, step: int) -> None:
        self.state.registry.add(record)
        self.log.emit("registry_changed", step=step, actor=actor, record=record)

    # ------------------------------------------------------------------ termination support

    def all_requests_decided(self) -> bool:
        return all(r.status.is_terminal for r in self.state.requests.values())
