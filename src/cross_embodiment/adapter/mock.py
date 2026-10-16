from __future__ import annotations

from copy import deepcopy

from ..errors import CommandRejected, LifecycleError
from ..driver.health import HealthReport
from ..hardware.manifest import EmbodimentManifest
from ..protocol.types import Command, CommandResult, JointState, Pose, RobotState, SafetyState


class MockAdapter:
    adapter_id = "mock"
    version = "0.1.0"

    def __init__(self, manifest: EmbodimentManifest):
        self._manifest = manifest
        self._connected = False
        self._enabled = False
        self._sequence = 0
        self.commands: list[Command] = []
        joint_positions = {
            joint.get("canonical_name", joint.get("name")): 0.0
            for device in manifest.devices
            for joint in device.get("joints", [])
            if joint.get("canonical_name", joint.get("name"))
        }
        ee_poses = {
            str(device["id"]): Pose((0.4, 0.0, 0.4), frame="base")
            for device in manifest.devices
            if device.get("type") == "arm" and device.get("id")
        }
        grippers = {
            str(device["id"]): 0.5
            for device in manifest.devices
            if device.get("type") == "gripper" and device.get("id")
        }
        self._state = RobotState(
            joint_positions=joint_positions,
            ee_poses=ee_poses,
            grippers=grippers,
        )

    def load_manifest(self) -> EmbodimentManifest:
        return self._manifest

    def configure(self) -> None:
        return None

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._enabled = False
        self._connected = False

    def enable(self) -> None:
        if not self._connected:
            raise LifecycleError("Cannot enable a disconnected adapter")
        self._enabled = True
        self._state.safety = SafetyState(enabled=True)

    def disable(self) -> None:
        self._enabled = False
        self._state.safety = SafetyState(enabled=False)

    def capabilities(self):
        return self._manifest.capabilities()

    def supports_action(self, action_type: str, device_id: str) -> bool:
        return self._manifest.supports(action_type, device_id)

    def get_joint_state(self, device_id: str) -> JointState:
        device = self._manifest.device(device_id)
        if device is None:
            raise ValueError(f"Unknown device: {device_id}")
        state = self.get_state()
        names = [
            joint.get("canonical_name", joint.get("name"))
            for joint in device.get("joints", [])
        ]
        source = state.joint_positions or {}
        complete = all(name in source for name in names)
        return JointState(
            device_id=device_id,
            positions={name: float(source[name]) for name in names} if complete else {},
            source_timestamp=state.timestamp,
            received_at=state.timestamp,
            status="ready" if complete and state.safety.enabled else "not_ready",
        )

    def get_state(self) -> RobotState:
        if not self._connected:
            raise LifecycleError("Adapter is disconnected")
        self._sequence += 1
        state = deepcopy(self._state)
        state.sequence_id = self._sequence
        return state

    def send_command(self, command: Command) -> CommandResult:
        if not self._connected or not self._enabled:
            raise CommandRejected("Adapter is not enabled")
        if command.mode == "ee_delta":
            self._apply_ee_delta(command)
        elif command.mode == "gripper_position":
            value = float(command.payload["value"])
            if not 0.0 <= value <= 1.0:
                raise CommandRejected("Gripper value must be in [0, 1]")
            self._state.grippers[command.target] = value
        else:
            raise CommandRejected(f"Mock adapter does not implement {command.mode}")
        self.commands.append(command)
        return CommandResult(
            True, "applied by mock adapter; no physical robot involved", self._sequence,
            status="simulated", dispatched=False,
        )

    def health(self) -> HealthReport:
        return HealthReport(self._connected, "ready" if self._connected else "disconnected")

    def _apply_ee_delta(self, command: Command) -> None:
        pose = self._state.ee_poses.get(command.target)
        if pose is None:
            raise CommandRejected(f"Unknown EE target: {command.target}")
        delta = command.payload["translation"]
        self._state.ee_poses[command.target] = Pose(
            tuple(a + b for a, b in zip(pose.position, delta)),
            pose.quaternion_xyzw,
            pose.frame,
        )
