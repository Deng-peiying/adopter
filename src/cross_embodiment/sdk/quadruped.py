from __future__ import annotations

from ..protocol.types import Action, ActionSpec, BaseState, CommandResult, JointState
from .robot_base import RobotBase


class QuadrupedRobot(RobotBase):
    """Application facade for quadruped and explicitly declared wheel-leg bases."""

    @classmethod
    def profile_id(cls) -> str:
        return "quadruped"

    def stand(self, device_id: str = "base") -> CommandResult:
        """Request the embodiment's documented standing transition."""
        action = Action(ActionSpec("quadruped_stand", device_id), {})
        results = self.command(action)
        if len(results) != 1:
            raise RuntimeError("Single-device stand action must produce exactly one backend result")
        return results[0]

    def move_base_input(
        self,
        device_id: str,
        *,
        x: float,
        y: float,
        yaw: float,
        frequency_hz: float = 20.0,
    ) -> CommandResult:
        """Dispatch one normalized input sample without starting a sender loop.

        Repeated refresh calls and the zero-input/stop policy belong to the
        caller. ``frequency_hz`` is requested control-loop cadence metadata; it
        does not make this method send repeatedly.
        """
        action = Action(
            ActionSpec(
                "base_motion_input",
                device_id,
                frequency_hz=frequency_hz,
                dimension=3,
                units={"x": "ratio", "y": "ratio", "yaw": "ratio"},
                bounds={"x": [-1.0, 1.0], "y": [-1.0, 1.0], "yaw": [-1.0, 1.0]},
            ),
            {"x": x, "y": y, "yaw": yaw},
        )
        results = self.command(action)
        if len(results) != 1:
            raise RuntimeError("Single-device base motion must produce exactly one backend result")
        return results[0]

    def get_base_state(self, device_id: str) -> BaseState:
        if self.manifest.device(device_id) is None:
            raise ValueError(f"Unknown device: {device_id}")
        state = self.state().base_state
        if state is None or state.device_id != device_id:
            raise NotImplementedError(f"Backend has no measured base state for {device_id}")
        return state

    def get_joint_state(self, device_id: str) -> JointState:
        """Read named measured joints when the selected device declares them."""
        if not self.manifest.supports("joint_state", device_id):
            raise ValueError(f"Device {device_id!r} does not declare joint_state")
        getter = getattr(self.adapter, "get_joint_state", None)
        if getter is None:
            raise NotImplementedError(f"Backend has no joint-state mapping for {device_id}")
        state = getter(device_id)
        if not isinstance(state, JointState) or state.device_id != device_id:
            raise RuntimeError("Backend returned an invalid joint state")
        return state
