from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import PackageError


@dataclass
class RobotInstance:
    instance_id: str
    package: str
    version: str
    backend_preferred: str | None = None
    connection: dict[str, Any] = field(default_factory=dict)
    components: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    tool: dict[str, Any] = field(default_factory=dict)
    overrides: dict[str, Any] = field(default_factory=dict)
    root: Path | None = None


def load_robot_instance(path: str | Path) -> RobotInstance:
    path = Path(path)
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise PackageError("Robot Instance YAML requires PyYAML") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("instance"), dict):
        raise PackageError("Robot Instance requires an instance mapping")
    instance = data["instance"]
    robot = data.get("robot") or {}
    if not instance.get("id") or not robot.get("package") or not robot.get("version"):
        raise PackageError("Robot Instance requires id, robot.package, and robot.version")
    return RobotInstance(
        instance_id=str(instance["id"]),
        package=str(robot["package"]),
        version=str(robot["version"]),
        backend_preferred=(data.get("backend") or {}).get("preferred"),
        connection=dict(data.get("connection") or {}),
        components=dict(data.get("components") or {}),
        calibration=dict(data.get("calibration") or {}),
        tool=dict(data.get("tool") or {}),
        overrides=dict(data.get("overrides") or {}),
        root=path.parent,
    )
