"""Episode runtime: round-robin scheduling, observation delivery and termination.

The runtime knows nothing about roles or tools. It only sees (manifest, agent) bindings, so a new
agent is a new binding and needs no runtime change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .domain import Action, AgentManifest, Observation
from .environment import Environment


class Agent(Protocol):
    def act(self, observation: Observation) -> Action: ...


@dataclass
class AgentBinding:
    manifest: AgentManifest
    agent: Agent
    briefing: str = ""


@dataclass
class EpisodeResult:
    termination_reason: str
    rounds: int
    steps: int
    metadata: dict[str, Any] = field(default_factory=dict)


class Runtime:
    def __init__(
        self,
        env: Environment,
        bindings: list[AgentBinding],
        *,
        max_rounds: int = 8,
        idle_rounds_limit: int = 2,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not bindings:
            raise ValueError("an episode needs at least one agent")
        self.env = env
        self.bindings = bindings
        self.max_rounds = max_rounds
        self.idle_rounds_limit = idle_rounds_limit
        self.metadata = metadata or {}
        for binding in bindings:
            env.register_agent(binding.manifest, binding.briefing)

    def run(self) -> EpisodeResult:
        log = self.env.log
        log.emit(
            "episode_started", step=0,
            metadata=self.metadata,
            policy=self.env.policy.to_dict(),
            enforce_policy_guard=self.env.enforce_policy_guard,
            agents=[b.manifest for b in self.bindings],
            tools=[t.to_dict() for t in self.env.catalog.values()],
            initial_state=self.env.state.snapshot(),
        )
        step, idle_rounds, reason, rounds = 0, 0, "max_rounds", 0
        for rounds in range(1, self.max_rounds + 1):
            all_idle = True
            for binding in self.bindings:
                step += 1
                agent_id = binding.manifest.agent_id
                observation = self.env.observe(agent_id, step)
                action, errored = self._safe_act(binding, observation, step)
                result = self.env.execute(agent_id, action, step)
                # A crashed turn is not a choice to wait: it must not end the episode as "quiescent".
                all_idle = all_idle and action.tool == "wait" and result.ok and not errored
                if self.env.all_requests_decided():
                    reason = "all_requests_decided"
                    break
            if reason == "all_requests_decided":
                break
            idle_rounds = idle_rounds + 1 if all_idle else 0
            if idle_rounds >= self.idle_rounds_limit:
                reason = "quiescent"
                break
        log.emit("episode_ended", step=step, reason=reason, rounds=rounds, steps=step,
                 final_state=self.env.state.snapshot())
        return EpisodeResult(reason, rounds, step, self.metadata)

    def _safe_act(self, binding: AgentBinding, observation: Observation, step: int) -> tuple[Action, bool]:
        """An agent crash (model/API error, bad output) is recorded and becomes a no-op turn."""
        try:
            action = binding.agent.act(observation)
            if not isinstance(action, Action):
                raise TypeError(f"agent returned {type(action).__name__}, expected Action")
            return action, False
        except Exception as exc:  # noqa: BLE001 - any agent failure must not kill the episode
            self.env.log.emit("agent_error", step=step, actor=binding.manifest.agent_id,
                              error=f"{type(exc).__name__}: {exc}")
            return Action.wait(rationale="agent error; turn skipped"), True
