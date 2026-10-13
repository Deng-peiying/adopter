from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..errors import PackageError
from ..protocol.types import JointState, Pose
from .kdl import forward_kinematics, solve_inverse_kinematics
from .types import IKResult, KinematicChain


def _pose_errors(actual: Pose, target: Pose) -> tuple[float, float]:
    position = math.sqrt(sum((a - b) ** 2 for a, b in zip(actual.position, target.position)))
    dot = abs(sum(a * b for a, b in zip(actual.quaternion_xyzw, target.quaternion_xyzw)))
    orientation = 2.0 * math.acos(max(-1.0, min(1.0, dot)))
    return position, orientation


@dataclass(frozen=True)
class JointGoalPlan:
    device_id: str
    source_state_timestamp: datetime
    model_digest: str
    goal_frame: str
    target_pose: Pose
    joint_target: dict[str, float]
    ik_result: IKResult
    position_tolerance_m: float
    orientation_tolerance_rad: float
    execution_semantics: str = "joint_space_move_to_ik_solution"
    endpoint_ik_validated: bool = True
    path_validated: bool = False
    collision_validated: bool = False
    cartesian_path_guaranteed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "source_state_timestamp": self.source_state_timestamp.isoformat(),
            "model_digest": self.model_digest,
            "goal_frame": self.goal_frame,
            "target_pose": {
                "position": list(self.target_pose.position),
                "quaternion_xyzw": list(self.target_pose.quaternion_xyzw),
            },
            "joint_target": dict(self.joint_target),
            "solver": {
                "code": self.ik_result.solver_code,
                "position_error_m": self.ik_result.position_error_m,
                "orientation_error_rad": self.ik_result.orientation_error_rad,
            },
            "tolerances": {
                "position_m": self.position_tolerance_m,
                "orientation_rad": self.orientation_tolerance_rad,
            },
            "execution_semantics": self.execution_semantics,
            "evidence": {
                "endpoint_ik_validated": self.endpoint_ik_validated,
                "path_validated": self.path_validated,
                "collision_validated": self.collision_validated,
                "cartesian_path_guaranteed": self.cartesian_path_guaranteed,
            },
        }


@dataclass(frozen=True)
class PlanVerification:
    achieved: bool
    measured_source_timestamp: datetime
    measured_pose: Pose
    position_error_m: float
    orientation_error_rad: float


class JointGoalPlanner:
    def __init__(self, chain: KinematicChain):
        self.chain = chain

    def plan(
        self,
        source: JointState,
        target_pose: Pose,
        *,
        position_tolerance_m: float,
        orientation_tolerance_rad: float,
    ) -> JointGoalPlan:
        if source.device_id != self.chain.device_id:
            raise PackageError(
                f"Joint state device {source.device_id} does not match {self.chain.device_id}"
            )
        if source.status != "ready":
            raise PackageError(f"Joint state is not ready: {source.status}")
        if source.source_timestamp is None:
            raise PackageError("Joint goal planning requires a source timestamp")
        if not target_pose.frame:
            raise PackageError("Joint goal planning requires an explicit target frame")
        if target_pose.frame != self.chain.base_link:
            raise PackageError(
                f"IK target frame must be {self.chain.base_link}, received {target_pose.frame}"
            )
        if position_tolerance_m <= 0 or orientation_tolerance_rad <= 0:
            raise PackageError("Position and orientation tolerance values must be positive")

        ik_result = solve_inverse_kinematics(self.chain, target_pose, source.positions)
        if not ik_result.success:
            raise PackageError(f"IK endpoint is unavailable: {ik_result.message}")
        if (
            ik_result.position_error_m > position_tolerance_m
            or ik_result.orientation_error_rad > orientation_tolerance_rad
        ):
            raise PackageError(
                "IK endpoint residual exceeds the requested tolerance: "
                f"position={ik_result.position_error_m}, "
                f"orientation={ik_result.orientation_error_rad}"
            )
        return JointGoalPlan(
            device_id=self.chain.device_id,
            source_state_timestamp=source.source_timestamp,
            model_digest=self.chain.model_digest,
            goal_frame=target_pose.frame,
            target_pose=target_pose,
            joint_target=dict(ik_result.positions),
            ik_result=ik_result,
            position_tolerance_m=float(position_tolerance_m),
            orientation_tolerance_rad=float(orientation_tolerance_rad),
        )

    def verify(self, plan: JointGoalPlan, measured: JointState) -> PlanVerification:
        if measured.device_id != plan.device_id:
            raise PackageError(
                f"Measured device {measured.device_id} does not match plan {plan.device_id}"
            )
        if measured.status != "ready" or measured.source_timestamp is None:
            raise PackageError("Plan verification requires a ready measured state with source timestamp")
        if measured.source_timestamp <= plan.source_state_timestamp:
            raise PackageError("Plan verification requires a newer measured source state")
        if plan.model_digest != self.chain.model_digest:
            raise PackageError("Plan model digest does not match the loaded kinematic model")
        pose = forward_kinematics(self.chain, measured.positions)
        position_error, orientation_error = _pose_errors(pose, plan.target_pose)
        return PlanVerification(
            achieved=(
                position_error <= plan.position_tolerance_m
                and orientation_error <= plan.orientation_tolerance_rad
            ),
            measured_source_timestamp=measured.source_timestamp,
            measured_pose=pose,
            position_error_m=position_error,
            orientation_error_rad=orientation_error,
        )
