from __future__ import annotations

import time
from dataclasses import dataclass

from ..errors import CompatibilityError, LifecycleError, SafetyViolation
from .mapping import ActionMapper
from .safety import SafetyGuard
from ..protocol.types import Action, ActionSpec, Command, Observation


@dataclass
class CompatibilityReport:
    status: str
    checks: list[str]
    blocking_issues: list[str]
    warnings: list[str]

    @property
    def has_blocking_issues(self) -> bool:
        return bool(self.blocking_issues)

    def summary(self) -> str:
        return "; ".join(self.blocking_issues or self.warnings or [self.status])

    def raise_if_incompatible(self) -> None:
        if self.has_blocking_issues:
            raise CompatibilityError(self.summary())


class Runtime:
    def __init__(self, robot, policy, control_frequency_hz: float | None = None, safety_profile: str = "default"):
        self.robot = robot
        self.policy = policy
        self.safety_profile = safety_profile
        self.frequency_hz = control_frequency_hz or policy.action_spec().frequency_hz
        self.running = False
        self._validated = False
        self.safety = SafetyGuard()
        self.mapper = ActionMapper()

    def validate(self) -> CompatibilityReport:
        spec: ActionSpec = self.policy.action_spec()
        checks: list[str] = []
        issues: list[str] = []
        warnings: list[str] = []
        if not spec.type:
            issues.append("action type is missing")
        if not self.robot.manifest.supports(spec.type, spec.target):
            issues.append(f"target '{spec.target}' does not support action '{spec.type}'")
        else:
            checks.append(f"action {spec.type} supported by {spec.target}")
        if spec.frequency_hz <= 0:
            issues.append("policy frequency must be positive")
        if spec.type == "ee_delta" and spec.frame is None:
            issues.append("ee_delta requires an explicit frame")
        if spec.type == "ee_delta" and self.robot.manifest.frames.get("default_action_frame") != spec.frame:
            warnings.append("action frame differs from manifest default action frame")
        self._validated = not issues
        status = "incompatible" if issues else ("compatible_with_mapping" if warnings else "compatible")
        return CompatibilityReport(status, checks, issues, warnings)

    def start(self) -> None:
        if not self._validated:
            report = self.validate()
            report.raise_if_incompatible()
        self.robot.lifecycle.connect()
        self.robot.lifecycle.enable()
        self.policy.reset()
        self.running = True

    def observe(self) -> Observation:
        if not self.running:
            raise LifecycleError("Runtime is not running")
        state = self.robot.state()
        fields = {}
        if state.ee_poses:
            fields.update({f"robot.ee_pose.{name}": pose for name, pose in state.ee_poses.items()})
        if state.grippers:
            fields.update({f"robot.gripper.{name}": value for name, value in state.grippers.items()})
        if state.joint_positions:
            fields["robot.joint_position"] = state.joint_positions
        return Observation(fields=fields, source_state_sequence=state.sequence_id)

    def apply(self, action: Action):
        self._validate_action(action)
        state = self.robot.state()
        adapter = self.robot.adapter
        self.safety.validate(
            action,
            state,
            self.robot.manifest,
            control_enabled=getattr(adapter, "control_enabled", True),
            dry_run=getattr(adapter, "dry_run", False),
        )
        commands = self.mapper.map(action, self.robot.manifest)
        return [self.robot.command(command) for command in commands]

    def step(self):
        observation = self.observe()
        return self.apply(self.policy.step(observation))

    def run(self, steps: int = 1, sleep: bool = False):
        for _ in range(steps):
            if not self.running:
                break
            self.step()
            if sleep:
                time.sleep(1.0 / self.frequency_hz)

    def stop(self, reason: str = "user") -> None:
        self.running = False
        try:
            self.robot.lifecycle.stop()
        finally:
            self.robot.close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop(reason="context_exit")

    def _validate_action(self, action: Action) -> None:
        if action.spec != self.policy.action_spec():
            raise SafetyViolation("ActionSpec does not match policy ActionSpec")
        return None

    def _map_action(self, action: Action) -> list[Command]:
        return self.mapper.map(action, self.robot.manifest)
