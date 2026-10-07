from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from ..errors import SafetyViolation
from ..hardware.manifest import EmbodimentManifest
from ..protocol.types import Action, RobotState


class SafetyGuard:
    def validate(self, action: Action, state: RobotState, manifest: EmbodimentManifest, *, control_enabled: bool, dry_run: bool) -> None:
        values = action.values
        self._check_finite(values)
        mode = next((item for item in manifest.control.get("supported_modes", []) if item.get("type") == action.spec.type and item.get("target") == action.spec.target), {})
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
        self._check_bounds(flat_values, mode.get("bounds"), mode.get("limits"))
        self._check_delta(flat_values, state, mode.get("max_delta"))
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
                    result.extend(float(value) for value in values[key])
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
    def _check_bounds(values: tuple[float, ...], bounds: Any, limits: Any) -> None:
        configured = bounds if bounds is not None else limits
        if configured is None:
            return
        if isinstance(configured, dict):
            configured = list(configured.values())
        for index, pair in enumerate(configured):
            if index >= len(values) or pair is None:
                continue
            low, high = float(pair[0]), float(pair[1])
            if not low <= values[index] <= high:
                raise SafetyViolation(f"Action value {index}={values[index]} outside [{low}, {high}]")

    @staticmethod
    def _check_delta(values: tuple[float, ...], state: RobotState, max_delta: Any) -> None:
        if not max_delta or not state.joint_positions:
            return
        current = tuple(float(value) for value in state.joint_positions.values())
        for index, limit in enumerate(max_delta):
            if index >= len(values) or index >= len(current):
                break
            if abs(values[index] - current[index]) > float(limit):
                raise SafetyViolation(f"Joint step {index} exceeds limit {limit}")
