from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HealthReport:
    ready: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
