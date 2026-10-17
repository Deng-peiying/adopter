from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Pose:
    position: tuple[float, float, float]
    quaternion_xyzw: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    frame: str = "base"


@dataclass(frozen=True)
class SafetyState:
    enabled: bool = False
    estop: bool = False
    fault: bool = False


@dataclass
class RobotState:
    timestamp: datetime = field(default_factory=now_utc)
    sequence_id: int = 0
    joint_positions: dict[str, float] | None = None
    joint_velocities: dict[str, float] | None = None
    joint_efforts: dict[str, float] | None = None
    ee_poses: dict[str, Pose] | None = None
    grippers: dict[str, float] | None = None
    safety: SafetyState = field(default_factory=SafetyState)
    device_status: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionSpec:
    type: str
    target: str
    frame: str | None = None
    frequency_hz: float = 20.0
    dimension: int | None = None
    units: dict[str, str] = field(default_factory=dict)
    bounds: dict[str, Any] = field(default_factory=dict)


@dataclass
class Action:
    spec: ActionSpec
    values: Any
    timestamp: datetime = field(default_factory=now_utc)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Observation:
    fields: dict[str, Any]
    timestamp: datetime = field(default_factory=now_utc)
    source_state_sequence: int = 0
    schema: str = "policy-observation/ee/v0.1"

    def __getitem__(self, key: str) -> Any:
        return self.fields[key]


@dataclass(frozen=True)
class Command:
    target: str
    mode: str
    payload: dict[str, Any]
    frame: str | None = None


@dataclass(frozen=True)
class CommandResult:
    accepted: bool
    message: str = ""
    sequence_id: int | None = None
