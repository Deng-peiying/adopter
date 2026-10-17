from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AssetRef:
    slot: str
    format: str
    path: str
    source: bool = True
    digest: str | None = None
    metadata: dict[str, Any] | None = None
