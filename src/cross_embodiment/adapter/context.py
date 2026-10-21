"""Package resource access shared by independently implemented Adapters."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class AdapterContext:
    package_root: Path

    @classmethod
    def from_connection(cls, connection: Mapping[str, Any]) -> AdapterContext:
        return cls(Path(connection.get("package_root", ".")).expanduser().resolve())

    def resource(self, relative: str | Path) -> Path:
        value = Path(relative)
        result = (self.package_root / value).resolve()
        if not result.is_relative_to(self.package_root):
            raise ValueError("Adapter resource must stay inside its package")
        return result
