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


@dataclass(frozen=True)
class BaseState:
    """Measured planar and body state with explicit physical units."""

    device_id: str
    linear_x_mps: float | None = None
    linear_y_mps: float | None = None
    angular_z_radps: float | None = None
    roll_rad: float | None = None
    pitch_rad: float | None = None
    yaw_rad: float | None = None
    height_m: float | None = None
    source_timestamp: datetime | None = None
    received_at: datetime = field(default_factory=now_utc)
    status: str = "unknown"


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
    base_state: BaseState | None = None


@dataclass(frozen=True)
class JointState:
    """Measured named joints for one device, with source and receipt times."""

    device_id: str
    positions: dict[str, float]
    source_timestamp: datetime | None
    received_at: datetime
    status: str
    details: dict[str, Any] = field(default_factory=dict)


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


@dataclass(frozen=True)
class JointTarget:
    """Canonical named joint targets; revolute positions are radians."""

    device: str
    positions: dict[str, float]


@dataclass(frozen=True)
class CartesianTarget:
    """Absolute end-effector pose in metres and an xyzw quaternion."""

    device: str
    pose: Pose


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
    """Command submission status; never implies motion completion by itself.

    ``accepted`` preserves the v0.1 compatibility flag. ``status`` distinguishes
    simulation, local publication, and rejection; ``dispatched`` says whether
    the adapter attempted delivery to its configured backend.
    """

    accepted: bool
    message: str = ""
    sequence_id: int | None = None
    command_id: str | None = None
    status: str | None = None
    backend_code: str | int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    dispatched: bool = False
    started_at: datetime | None = None
    completed_at: datetime | None = None
    final_joint_state: JointState | None = None
    arrival_confirmed: bool | None = None
    max_joint_error_rad: float | None = None

    def __post_init__(self) -> None:
        if self.status is None:
            object.__setattr__(self, "status", "accepted" if self.accepted else "rejected")
