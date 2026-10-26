from __future__ import annotations

from ..protocol.types import Action, ActionSpec, CommandResult, JointState
from .robot_base import RobotBase


class ManipulatorRobot(RobotBase):
    """Application facade for manipulator-oriented convenience operations."""

    @classmethod
    def profile_id(cls) -> str:
        return "manipulator"

    def get_joint_state(self, device_id: str) -> JointState:
        if self.manifest.device(device_id) is None:
            raise ValueError(f"Unknown device: {device_id}")
        getter = getattr(self.adapter, "get_joint_state", None)
        if getter is None:
            raise NotImplementedError(f"Backend has no measured joint-state binding for {device_id}")
        return getter(device_id)

    def move_joints(self, device_id: str, positions: dict[str, float]) -> CommandResult:
        device = self.manifest.device(device_id)
        if device is None or not self.manifest.supports("joint_position", device_id):
            raise ValueError(f"Device {device_id!r} does not support joint_position")
        supports = getattr(self.adapter, "supports_action", None)
        if supports is not None and not supports("joint_position", device_id):
            raise ValueError(f"Device {device_id!r} has no active joint-position binding")
        expected = {joint.get("canonical_name", joint.get("name")) for joint in device.get("joints", [])}
        if not isinstance(positions, dict) or set(positions) != expected:
            raise ValueError(f"Absolute joint target must contain exactly {sorted(expected)}")
        results = self.command(Action(ActionSpec("joint_position", device_id, dimension=len(expected)),
                                      {"positions": positions}))
        if len(results) != 1:
            raise RuntimeError("Single-device joint move must produce exactly one backend result")
        return results[0]
