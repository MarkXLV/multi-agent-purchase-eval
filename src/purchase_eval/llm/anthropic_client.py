"""Claude adapter for the ModelClient seam (official `anthropic` SDK, manual tool loop).

The runtime owns the loop: one `send` is one model turn, and at most one tool call per turn
(`disable_parallel_tool_use`). History is append-only and assistant content is echoed back
unchanged, which keeps thinking blocks valid across turns.
"""

from __future__ import annotations

import json
from typing import Any

from .base import ModelError, ModelReply, ToolCall, ToolResult, ToolSchema

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicModelClient:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        effort: str = "medium",
        max_tokens: int = 16000,
        fallbacks: bool = True,
        client: Any = None,
    ) -> None:
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - exercised only without the extra installed
                raise RuntimeError("install the LLM extra: pip install -e '.[llm]'") from exc
            client = anthropic.Anthropic()  # credentials from ANTHROPIC_API_KEY / auth profile
        self._client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.fallbacks = fallbacks
        self.name = f"anthropic:{model}"

    def start_session(self, system: str, tools: list[ToolSchema]) -> AnthropicSession:
        return AnthropicSession(self, system, tools)


class AnthropicSession:
    def __init__(self, owner: AnthropicModelClient, system: str, tools: list[ToolSchema]) -> None:
        self._owner = owner
        self._system = system
        self._tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema, "strict": True}
            for t in tools
        ]
        self.history: list[dict[str, Any]] = []

    def build_request(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        o = self._owner
        request: dict[str, Any] = {
            "model": o.model,
            "max_tokens": o.max_tokens,
            "system": self._system,
            "tools": self._tools,
            "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
            "output_config": {"effort": o.effort},
            "messages": messages,
        }
        if o.fallbacks:
            # On a safety decline, the API re-runs the turn on Anthropic's recommended fallback model.
            # Sent via extra_body because the pinned SDK predates a typed `fallbacks` parameter.
            request["betas"] = [FALLBACK_BETA]
            request["extra_body"] = {"fallbacks": "default"}
        return request

    def send(self, tool_results: list[ToolResult], text: str) -> ModelReply:
        content: list[dict[str, Any]] = [
            {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content, "is_error": r.is_error}
            for r in tool_results
        ]
        if text:
            content.append({"type": "text", "text": text})
        messages = [*self.history, {"role": "user", "content": content}]
        request = self.build_request(messages)
        try:
            if "betas" in request:
                response = self._owner._client.beta.messages.create(**request)
            else:
                response = self._owner._client.messages.create(**request)
        except Exception as exc:  # SDK errors (rate limit, 5xx, network) -> retryable agent error
            raise ModelError(f"API call failed: {type(exc).__name__}: {exc}") from exc

        if response.stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise ModelError(f"model refused (category={category})")
        if response.stop_reason == "max_tokens":
            raise ModelError("response truncated at max_tokens")

        # Commit the turn only after success: append-only, assistant content echoed back verbatim.
        self.history = [*messages, {"role": "assistant", "content": response.content}]
        texts, calls = [], []
        for block in response.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(block.id, block.name, _as_dict(block.input)))
        return ModelReply("\n".join(texts).strip(), calls, response.stop_reason)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):  # defensive: some transports hand back serialized JSON
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}
