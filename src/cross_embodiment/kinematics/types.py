from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class KinematicSemantics:
    device_id: str
    base_link: str
    tip_link: str
    canonical_joints: tuple[str, ...]
    model_joints: tuple[str, ...]
    length_unit: str
    angle_unit: str


@dataclass(frozen=True)
class KinematicChain:
    semantics: KinematicSemantics
    model_digest: str
    joint_limits: tuple[tuple[float, float], ...]
    backend: Any = field(repr=False, compare=False)

    @property
    def device_id(self) -> str:
        return self.semantics.device_id

    @property
    def base_link(self) -> str:
        return self.semantics.base_link

    @property
    def tip_link(self) -> str:
        return self.semantics.tip_link

    @property
    def canonical_joints(self) -> tuple[str, ...]:
        return self.semantics.canonical_joints

    @property
    def model_joints(self) -> tuple[str, ...]:
        return self.semantics.model_joints

    @property
    def joint_count(self) -> int:
        return len(self.canonical_joints)


@dataclass(frozen=True)
class IKResult:
    success: bool
    positions: dict[str, float]
    position_error_m: float
    orientation_error_rad: float
    solver_code: int
    message: str
