"""Provider-neutral model interface. The environment and runtime never import a provider SDK.

A *session* owns the provider-native conversation history, which lets an adapter keep provider
details (such as echoing thinking blocks back unchanged) out of the agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class ModelReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"


class ModelError(RuntimeError):
    """The model produced no usable turn (refusal, truncation, API failure). The turn may be retried."""


class ModelSession(Protocol):
    def send(self, tool_results: list[ToolResult], text: str) -> ModelReply: ...


class ModelClient(Protocol):
    name: str

    def start_session(self, system: str, tools: list[ToolSchema]) -> ModelSession: ...
