from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import PackageError


@dataclass
class ProjectSpec:
    root: Path
    robots: dict[str, dict[str, Any]] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    task: dict[str, Any] = field(default_factory=dict)


def load_project(path: str | Path) -> ProjectSpec:
    path = Path(path)
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise PackageError("Project YAML requires PyYAML") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PackageError("Project root must be a mapping")
    return ProjectSpec(
        root=path.parent,
        robots=dict(data.get("robots") or {}),
        policy=dict(data.get("policy") or {}),
        runtime=dict(data.get("runtime") or {}),
        task=dict(data.get("task") or {}),
    )
