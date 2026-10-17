"""Adapter runtime combining the interface mapping engine and ROS 2 transport."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import threading
import time
from typing import Any, Callable

from ..backend.protocol import BackendTransport, TransportEvent
from ..driver.health import HealthReport
from ..errors import CommandRejected, LifecycleError
from ..hardware.manifest import EmbodimentManifest
from ..mapping.engine import CompiledCommand, InterfaceMappingEngine
from ..protocol.types import Command, CommandResult, JointState, RobotState, SafetyState
from .ros2_transport import Ros2Transport


class MappedRos2Adapter:
    """Thin Adapter Runtime for a mapped ROS 2 Hardware Package."""

    adapter_id = "ros2_mapped"
    version = "0.1.0"

    def __init__(
        self,
        manifest: EmbodimentManifest,
        *,
        connection: dict[str, Any] | None = None,
        control_enabled: bool = False,
        dry_run: bool = True,
        transport_factory: Callable[[], BackendTransport] | None = None,
        manage_process: bool = False,
    ):
        self.manifest = manifest
        self.connection = connection or {}
        if manage_process or self.connection.get("manage_process", False):
            raise ValueError("Mapped ROS runtime attaches to an existing driver; manage_process must be false")
        self.mapping_engine = InterfaceMappingEngine.from_connection(self.connection, manifest)
        if self.mapping_engine.backend_types() != {"ros2"}:
            raise ValueError("MappedRos2Adapter requires every binding to use the ROS2 backend")
        self.mapping = self.mapping_engine.mapping
        self.control_enabled = control_enabled
        self.dry_run = dry_run
        self.transport_factory = transport_factory or Ros2Transport
        self.transport: BackendTransport | None = None
        self._condition = threading.Condition()
        self._states: dict[str, JointState] = {}
        self._state_versions: dict[str, int] = {}
        self._connected = False

    def configure(self) -> None:
        pass

    def load_manifest(self) -> EmbodimentManifest:
        return self.manifest

    def supports_action(self, action_type: str, device_id: str) -> bool:
        return self.mapping_engine.supports(action_type, device_id)

    def capabilities(self) -> dict[str, Any]:
        view = self.manifest.capabilities()
        bound = set(self.mapping_engine.device_ids())
        view["devices"] = [device for device in view["devices"] if device["id"] in bound]
        for device in view["devices"]:
            device["capabilities"] = [
                name for name in device["capabilities"]
                if self.mapping_engine.supports(name, device["id"])
            ]
        view["actions"] = [
            {key: value for key, value in action.items() if key != "frequency_hz"}
            for action in view["actions"]
            if self.supports_action(action["type"], action["target"])
        ]
        view["safety"]["supports_estop"] = False
        return view

    def connect(self) -> None:
        if self.dry_run:
            self._connected = True
            return
        self.transport = self.transport_factory()
        self.transport.connect(self.mapping_engine.transport_bindings(), self._on_transport_event)
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False
        if self.transport is not None:
            self.transport.close()
            self.transport = None

    def enable(self) -> None:
        if not self._connected:
            raise LifecycleError("ROS mapping runtime is disconnected")
        if not self._all_mapped_states_ready():
            raise LifecycleError("Mapped device has not reported a ready state")

    def disable(self) -> None:
        pass

    def health(self) -> HealthReport:
        ready = (
            self._connected
            and self.transport is not None
            and self.transport.ready(self.mapping_engine.action_binding_ids())
            and self._all_mapped_states_ready()
        )
        return HealthReport(ready, "ready" if ready else "not ready")

    def wait_ready(self, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.health().ready:
                return True
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        return self.health().ready

    def _fresh_state(self, state: JointState) -> JointState:
        max_age_ms = self.manifest.safety.get("max_state_age_ms")
        if max_age_ms is None:
            return state
        if state.source_timestamp is None:
            return replace(state, status="timestamp_unconfirmed")
        now = datetime.now(timezone.utc)
        age_limit = float(max_age_ms) / 1000
        if (
            (now - state.received_at).total_seconds() > age_limit
            or (now - state.source_timestamp).total_seconds() > age_limit
            or (state.source_timestamp - now).total_seconds() > 1.0
        ):
            return replace(state, status="stale")
        return state

    def _all_mapped_states_ready(self) -> bool:
        with self._condition:
            return all(
                device_id in self._states
                and self._fresh_state(self._states[device_id]).status == "ready"
                for device_id in self.mapping_engine.device_ids()
            )

    def _on_transport_event(self, event: TransportEvent) -> None:
        observation = self.mapping_engine.decode_event(event)
        if observation is None:
            return
        with self._condition:
            device_id = observation.device_id
            self._states[device_id] = observation
            self._state_versions[device_id] = self._state_versions.get(device_id, 0) + 1
            self._condition.notify_all()

    def get_joint_state(self, device_id: str) -> JointState:
        if not self.mapping_engine.supports("joint_state", device_id):
            raise ValueError(f"No joint state mapping for {device_id}")
        deadline = time.monotonic() + float(self.connection.get("state_timeout_s", 5.0))
        with self._condition:
            while device_id not in self._states:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"No joint state received for {device_id}")
                self._condition.wait(remaining)
            state = deepcopy(self._states[device_id])
        return self._fresh_state(state)

    def get_state(self) -> RobotState:
        states = [self.get_joint_state(device_id)
                  for device_id in self.mapping_engine.device_ids()]
        positions = {name: value for state in states for name, value in state.positions.items()}
        return RobotState(
            timestamp=max(state.received_at for state in states),
            joint_positions=positions,
            safety=SafetyState(
                enabled=all(state.status == "ready" for state in states),
                fault=any(state.status == "fault" for state in states),
            ),
            device_status={state.device_id: state.status for state in states},
        )

    def send_command(self, command: Command) -> CommandResult:
        compiled = self.mapping_engine.compile_command(command)
        if self.dry_run:
            return CommandResult(True, "mapped locally; no backend request sent", status="simulated")
        if not self.control_enabled:
            return CommandResult(False, "control disabled", status="not_dispatched")
        if not self._connected or self.transport is None:
            raise LifecycleError("ROS mapping runtime is disconnected")
        current = self.get_joint_state(compiled.device_id)
        if current.status != "ready":
            raise CommandRejected(f"Device {compiled.device_id} is {current.status}")

        started = datetime.now(timezone.utc)
        transport_result = self.transport.execute(compiled.request)
        decoded = self.mapping_engine.decode_result(transport_result, compiled)
        details = {
            "backend_status": transport_result.backend_status,
            "transport_status": transport_result.status,
            "backend_description": decoded.description,
            "transport_error": transport_result.error,
            "cancel_requested": transport_result.cancel_requested,
            "cancel_accepted": transport_result.cancel_accepted,
            "goal": deepcopy(compiled.request.payload),
        }
        common = dict(
            accepted=transport_result.accepted,
            dispatched=transport_result.dispatched,
            backend_code=decoded.backend_code,
            started_at=started,
            completed_at=None,
            details=details,
            arrival_confirmed=False,
        )
        if not transport_result.accepted:
            if transport_result.status == "timed_out":
                status = "timed_out"
            elif transport_result.status == "transport_error" and transport_result.dispatched:
                status = "outcome_unknown"
            elif transport_result.status in ("unavailable", "transport_error"):
                status = "not_dispatched"
            else:
                status = "rejected"
            return CommandResult(status=status, message=transport_result.status, **common)
        if transport_result.status == "timed_out":
            return CommandResult(
                status="timed_out", message="Action timed out; outcome unknown", **common,
            )
        if transport_result.status == "transport_error":
            return CommandResult(
                status="outcome_unknown",
                message="Action result unavailable; physical outcome unknown",
                **common,
            )
        if transport_result.status == "cancelled":
            common["completed_at"] = datetime.now(timezone.utc)
            return CommandResult(status="cancelled", message="Action cancelled", **common)
        if not decoded.vendor_succeeded:
            common["completed_at"] = datetime.now(timezone.utc)
            return CommandResult(
                status="failed",
                message=decoded.description or transport_result.status,
                **common,
            )

        terminal_at = datetime.now(timezone.utc)
        with self._condition:
            after_terminal = self._state_versions.get(compiled.device_id, 0)
        settled, error = self._wait_for_arrival(
            compiled, after_terminal, terminal_at,
        )
        if settled is None:
            return CommandResult(
                status="timed_out",
                message="Action succeeded; measured arrival unconfirmed",
                max_joint_error_rad=error,
                **common,
            )
        common["completed_at"] = datetime.now(timezone.utc)
        common["arrival_confirmed"] = True
        return CommandResult(
            status="succeeded",
            message="Action and measured arrival succeeded",
            final_joint_state=settled,
            max_joint_error_rad=error,
            **common,
        )

    def _wait_for_arrival(
        self,
        compiled: CompiledCommand,
        previous: int,
        terminal_at: datetime,
    ) -> tuple[JointState | None, float | None]:
        deadline = time.monotonic() + float(self.connection.get("arrival_timeout_s", 20.0))
        tolerance = float(compiled.completion["arrival_tolerance_rad"])
        settle_window = float(compiled.completion["settle_window_s"])
        stable_since = None
        last_error = None
        last_version = previous
        device_id = compiled.device_id
        with self._condition:
            while time.monotonic() < deadline:
                version = self._state_versions.get(device_id, 0)
                if version > last_version:
                    last_version = version
                    state = self._fresh_state(self._states[device_id])
                    actual = [state.positions.get(name) for name in compiled.joint_names]
                    if (
                        state.status == "ready"
                        and state.source_timestamp is not None
                        and state.source_timestamp >= terminal_at
                        and all(value is not None for value in actual)
                    ):
                        last_error = max(
                            abs(value - desired)
                            for value, desired in zip(actual, compiled.target_positions)
                        )
                        if last_error <= tolerance:
                            stable_since = stable_since or time.monotonic()
                            if settle_window == 0:
                                return deepcopy(state), last_error
                        else:
                            stable_since = None
                    else:
                        stable_since = None
                if stable_since is not None and time.monotonic() - stable_since >= settle_window:
                    state = self._fresh_state(self._states[device_id])
                    if state.status == "ready":
                        return deepcopy(state), last_error
                self._condition.wait(min(0.05, max(0.0, deadline - time.monotonic())))
        return None, last_error
