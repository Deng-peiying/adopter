from __future__ import annotations

from dataclasses import asdict, is_dataclass
import math
from datetime import datetime, timezone
from typing import Any

from ..errors import SafetyViolation
from ..hardware.manifest import EmbodimentManifest
from ..protocol.types import Action, RobotState


class SafetyGuard:
    def validate(self, action: Action, state: RobotState, manifest: EmbodimentManifest, *, control_enabled: bool, dry_run: bool) -> None:
        values = action.values
        if is_dataclass(values):
            values = asdict(values)
        self._check_finite(values)
        mode = next((item for item in manifest.control.get("supported_modes", [])
                     if item.get("type") == action.spec.type
                     and (item.get("target") == action.spec.target
                          or action.spec.target in item.get("legacy_target_aliases", []))), {})
        dimension = action.spec.dimension or mode.get("dimension")
        flat_values = self._flat_values(values)
        if dimension is not None and len(flat_values) != int(dimension):
            raise SafetyViolation(f"Expected {dimension} action values, got {len(flat_values)}")
        if not dry_run and not control_enabled:
            raise SafetyViolation("Hardware control is disabled")
        if state.safety.estop:
            raise SafetyViolation("Emergency stop is active")
        if state.safety.fault:
            raise SafetyViolation("Robot reports a fault")
        if not dry_run and manifest.safety.get("requires_enable", False) and not state.safety.enabled:
            raise SafetyViolation("Robot is not enabled")
        max_age_ms = manifest.safety.get("max_state_age_ms")
        if max_age_ms is not None:
            age_ms = (datetime.now(timezone.utc) - state.timestamp).total_seconds() * 1000
            if age_ms > float(max_age_ms):
                raise SafetyViolation(f"Robot state is stale ({age_ms:.1f}ms)")
        configured_bounds = action.spec.bounds or mode.get("bounds", mode.get("limits"))
        device = manifest.device(action.spec.target)
        devices = [device] if device else manifest.devices
        if configured_bounds is None and devices:
            joints = [joint for item in devices for joint in item.get("joints", [])]
            joint_bounds = [joint.get("limits") for joint in joints]
            if any(bound is not None for bound in joint_bounds):
                configured_bounds = joint_bounds
        positions = values.get("positions") if isinstance(values, dict) else None
        if isinstance(positions, dict) and isinstance(configured_bounds, (list, tuple)) and devices:
            joint_names = [joint.get("canonical_name", joint.get("name"))
                           for item in devices for joint in item.get("joints", [])]
            configured_bounds = {name: bound for name, bound in zip(joint_names, configured_bounds) if name and bound is not None}
        self._check_bounds(values, flat_values, configured_bounds, None)
        if action.spec.type == "ee_delta":
            max_delta = mode.get("max_translation_delta")
            translation = tuple(float(x) for x in values["translation"])
            if max_delta and any(abs(value) > float(limit) for value, limit in zip(translation, max_delta)):
                raise SafetyViolation(f"EE translation exceeds limit: {translation}")

    @staticmethod
    def _flat_values(values: Any) -> tuple[float, ...]:
        if isinstance(values, dict):
            result = []
            for key in ("positions", "translation", "rotation"):
                if key in values:
                    data = values[key]
                    result.extend(float(value) for value in (data.values() if isinstance(data, dict) else data))
            if all(key in values for key in ("x", "y", "yaw")):
                result.extend(float(values[key]) for key in ("x", "y", "yaw"))
            if "pose" in values and isinstance(values["pose"], dict):
                pose = values["pose"]
                result.extend(float(value) for value in pose.get("position", ()))
                result.extend(float(value) for value in pose.get("quaternion_xyzw", ()))
            return tuple(result)
        if isinstance(values, (list, tuple)):
            return tuple(float(value) for value in values)
        return (float(values),)

    @classmethod
    def _check_finite(cls, value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                cls._check_finite(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                cls._check_finite(item)
        elif isinstance(value, (float, int)) and not math.isfinite(float(value)):
            raise SafetyViolation("Action contains non-finite values")

    @staticmethod
    def _check_bounds(action_values: Any, values: tuple[float, ...], bounds: Any, limits: Any) -> None:
        configured = bounds if bounds is not None else limits
        if configured is None:
            return
        if isinstance(configured, dict):
            positions = action_values.get("positions", {}) if isinstance(action_values, dict) else {}
            if isinstance(positions, dict) and positions:
                for name, value in positions.items():
                    pair = configured.get(name)
                    if pair is not None and not float(pair[0]) <= float(value) <= float(pair[1]):
                        raise SafetyViolation(f"Joint {name}={value} outside [{pair[0]}, {pair[1]}]")
                return
            if isinstance(action_values, dict):
                matched = False
                for name, value in action_values.items():
                    pair = configured.get(name)
                    if pair is None or not isinstance(value, (int, float)):
                        continue
                    matched = True
                    if not float(pair[0]) <= float(value) <= float(pair[1]):
                        raise SafetyViolation(f"Action {name}={value} outside [{pair[0]}, {pair[1]}]")
                if matched:
                    return
            configured = list(configured.values())
        for index, pair in enumerate(configured):
            if index >= len(values) or pair is None:
                continue
            low, high = float(pair[0]), float(pair[1])
            if not low <= values[index] <= high:
                raise SafetyViolation(f"Action value {index}={values[index]} outside [{low}, {high}]")
