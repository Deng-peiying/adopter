"""Communication-level contract shared by backend transports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class TransportRequest:
    """A compiled backend call with no canonical robot semantics left to resolve."""

    binding_id: str
    backend: str
    kind: str
    endpoint: str
    interface: str
    payload: dict[str, Any] = field(default_factory=dict)
    timeout_s: float | None = None


@dataclass(frozen=True)
class TransportEvent:
    """An asynchronous backend state or action feedback event."""

    binding_id: str
    kind: str
    payload: dict[str, Any]
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class TransportResult:
    """Transport lifecycle result, separate from vendor payload semantics."""

    binding_id: str
    status: str
    accepted: bool = False
    dispatched: bool = False
    payload: dict[str, Any] | None = None
    backend_status: str | int | None = None
    error: str | None = None
    cancel_requested: bool = False
    cancel_accepted: bool | None = None


@runtime_checkable
class BackendTransport(Protocol):
    """Mechanism-only transport used by an adapter runtime."""

    def connect(
        self,
        bindings: Sequence[TransportRequest],
        on_event: Callable[[TransportEvent], None],
    ) -> None: ...

    def execute(self, request: TransportRequest) -> TransportResult: ...

    def ready(self, binding_ids: Sequence[str]) -> bool: ...

    def close(self) -> None: ...
