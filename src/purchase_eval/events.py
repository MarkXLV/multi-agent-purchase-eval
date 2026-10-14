"""Append-only event log. The JSONL trace is the single source of truth for the verifier."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


def jsonable(obj: Any) -> Any:
    """Convert domain objects to plain JSON values. Money stays a string so it round-trips exactly."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Decimal):
        return str(obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (frozenset, set)):
        return sorted(jsonable(v) for v in obj)
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    return obj


@dataclass(frozen=True)
class Event:
    seq: int
    step: int
    type: str
    actor: str | None
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "step": self.step, "type": self.type, "actor": self.actor, "data": self.data}


class EventLog:
    """Logical clock only (seq/step, no wall time), so identical runs produce identical traces."""

    def __init__(self) -> None:
        self._events: list[Event] = []

    def emit(self, type: str, *, step: int, actor: str | None = None, **data: Any) -> Event:
        event = Event(len(self._events) + 1, step, type, actor, jsonable(data))
        self._events.append(event)
        return event

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    def to_dicts(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._events]


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
