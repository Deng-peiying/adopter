from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..models import AssetRecord


@dataclass(frozen=True)
class ScanContext:
    root: Path
    root_id: str
    ignored_components: frozenset[str]


class AssetExtractor(Protocol):
    def scan(self, context: ScanContext) -> list[AssetRecord]: ...
