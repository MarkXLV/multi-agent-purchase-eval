"""Shared environment state: two authoritative stores and one untrusted store.

Agents never touch these objects directly; only `Environment` mutates them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .domain import AuthorizationRecord, Message, PurchaseRequest
from .events import jsonable


class AuthorizationRegistry:
    """Authoritative record of human authorizations. Agents can read it; none can write it."""

    def __init__(self, records: list[AuthorizationRecord] | None = None) -> None:
        self._records: dict[str, AuthorizationRecord] = {}
        for record in records or []:
            self.add(record)

    def add(self, record: AuthorizationRecord) -> None:
        if record.auth_id in self._records:
            raise ValueError(f"duplicate authorization id {record.auth_id}")
        self._records[record.auth_id] = record

    def records_for(self, request_id: str) -> list[AuthorizationRecord]:
        return [r for r in self._records.values() if r.request_id == request_id]

    def all(self) -> list[AuthorizationRecord]:
        return list(self._records.values())


class MessageBoard:
    """Append-only, agent-generated, untrusted."""

    def __init__(self) -> None:
        self._messages: list[Message] = []

    def post(self, author: str, body: str, step: int) -> Message:
        message = Message(f"MSG-{len(self._messages) + 1:04d}", step, author, body)
        self._messages.append(message)
        return message

    def since(self, cursor: int) -> list[Message]:
        return self._messages[cursor:]

    def all(self) -> list[Message]:
        return list(self._messages)

    def __len__(self) -> int:
        return len(self._messages)


@dataclass
class EnvironmentState:
    requests: dict[str, PurchaseRequest] = field(default_factory=dict)
    registry: AuthorizationRegistry = field(default_factory=AuthorizationRegistry)
    board: MessageBoard = field(default_factory=MessageBoard)

    def snapshot(self) -> dict:
        return {
            "purchase_requests": [jsonable(r) for r in self.requests.values()],
            "authorization_registry": [jsonable(r) for r in self.registry.all()],
            "message_board": [jsonable(m) for m in self.board.all()],
        }
