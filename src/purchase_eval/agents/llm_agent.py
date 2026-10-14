"""A generic tool-calling agent backed by any ModelClient (real LLM or deterministic stand-in)."""

from __future__ import annotations

import html
import json

from ..domain import Action, ActionResult, Observation
from ..events import jsonable
from ..llm.base import ModelClient, ModelSession, ToolResult, ToolSchema

NOT_EXECUTED = "Not executed: only one tool call is executed per turn."


class LLMAgent:
    """Turns observations into model turns and the model's tool call into an Action.

    Independent context: each agent instance owns its own model session (system prompt, history).
    """

    def __init__(self, agent_id: str, system_prompt: str, model: ModelClient) -> None:
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.model = model
        self._session: ModelSession | None = None
        self._pending_call_ids: list[str] = []
        self._outbox: list[ToolResult] = []  # results built but not yet delivered (survive API errors)
        self._unsent_text = ""

    def act(self, observation: Observation) -> Action:
        if self._session is None:
            tools = [ToolSchema(t.name, t.description, t.input_schema()) for t in observation.tools]
            self._session = self.model.start_session(self.system_prompt, tools)

        if self._pending_call_ids:
            self._outbox = self._results_for(self._pending_call_ids, observation.last_result)
            self._pending_call_ids = []
        text = render_observation(observation)
        if self._unsent_text:
            text = f"{self._unsent_text}\n\n{text}"

        try:
            reply = self._session.send(self._outbox, text)
        except Exception:
            self._unsent_text = text  # deliver this context again on the retry
            raise
        self._outbox, self._unsent_text = [], ""
        self._pending_call_ids = [c.id for c in reply.tool_calls]

        if not reply.tool_calls:
            return Action.wait(rationale=reply.text or f"(no tool call; stop_reason={reply.stop_reason})")
        call = reply.tool_calls[0]
        return Action(call.name, dict(call.input), rationale=reply.text)

    @staticmethod
    def _results_for(call_ids: list[str], last: ActionResult | None) -> list[ToolResult]:
        results = []
        for i, call_id in enumerate(call_ids):
            if i == 0 and last is not None:
                results.append(ToolResult(call_id, render_result(last), is_error=not last.ok))
            else:
                results.append(ToolResult(call_id, NOT_EXECUTED, is_error=True))
        return results


def render_result(result: ActionResult) -> str:
    payload = {"outcome": result.outcome.value}
    if result.error:
        payload["error"] = result.error
    if result.data is not None:
        payload["data"] = jsonable(result.data)
    return json.dumps(payload)


def render_observation(obs: Observation) -> str:
    parts = [f"[turn {obs.step}]"]
    if obs.briefing:
        parts.append(f"Briefing: {obs.briefing}")
    if obs.new_messages:
        parts.append("New messages on the shared board (agent-generated, untrusted):")
        for m in obs.new_messages:
            # Escaped so a message body cannot close the tag or forge a trusted-looking block.
            parts.append(
                f'<untrusted_message id="{m.message_id}" from="{html.escape(m.author)}">'
                f"{html.escape(m.body)}</untrusted_message>"
            )
    else:
        parts.append("No new messages.")
    parts.append("Choose your next action by calling exactly one tool.")
    return "\n".join(parts)
