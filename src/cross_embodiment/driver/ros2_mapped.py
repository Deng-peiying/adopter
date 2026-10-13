"""Optional ROS 2 joint mapping runtime; SDK core never imports ROS."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import math
from pathlib import Path
import threading
import time
from typing import Any, Callable

import yaml

from ..driver.health import HealthReport
from ..errors import CommandRejected, DependencyError, LifecycleError
from ..hardware.manifest import EmbodimentManifest
from ..protocol.types import Command, CommandResult, JointState, RobotState, SafetyState


def _field(value: Any, path: str, default: Any = None) -> Any:
    for name in path.split("."):
        value = value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)
        if value is default:
            return default
    return value


def _source_stamp(value: Any) -> datetime | None:
    if value is None:
        return None
    sec, nanosec = _field(value, "sec"), _field(value, "nanosec")
    if sec is None or nanosec is None or (int(sec) == 0 and int(nanosec) == 0):
        return None
    return datetime.fromtimestamp(int(sec) + int(nanosec) / 1e9, timezone.utc)


def _load_mapping(connection: dict[str, Any]) -> dict[str, Any]:
    if "mapping" in connection:
        data = deepcopy(connection["mapping"])
    else:
        path = Path(connection["mapping_path"])
        if not path.is_absolute():
            path = Path(connection.get("package_root", ".")) / path
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "ros2-joint-mapping/v1":
        raise ValueError("Expected ros2-joint-mapping/v1 configuration")
    if not isinstance(data.get("devices"), dict) or not data["devices"]:
        raise ValueError("ROS joint mapping requires devices")
    for device_id, config in data["devices"].items():
        if not isinstance(config.get("joints"), list) or not config["joints"]:
            raise ValueError(f"Mapping {device_id} requires ordered joints")
        for section in ("state", "action"):
            if not isinstance(config.get(section), dict):
                raise ValueError(f"Mapping {device_id} requires {section}")
            if config[section].get("unit", "radian") not in ("radian", "degree"):
                raise ValueError(f"Unsupported {section} joint unit for {device_id}")
    return data


class NativeRos2JointTransport:
    """ROS mechanics for mapped state topics and point-to-point actions."""

    def __init__(self, mapping: dict[str, Any], on_state: Callable[[str, Any], None]):
        self.mapping = mapping
        self.on_state = on_state
        self.node = None
        self.executor = None
        self.thread = None
        self.clients: dict[str, Any] = {}
        self._owns_rclpy = False

    def connect(self) -> None:
        try:
            import rclpy
            from rclpy.action import ActionClient
            from rclpy.executors import MultiThreadedExecutor
            from rclpy.node import Node
            from rosidl_runtime_py.utilities import get_action, get_message
        except ImportError as exc:
            raise DependencyError("ROS 2 mapping runtime requires rclpy and rosidl_runtime_py") from exc
        if not rclpy.ok():
            rclpy.init(args=None)
            self._owns_rclpy = True
        self.node = Node("cross_embodiment_mapped_ros2")
        for device_id, config in self.mapping["devices"].items():
            state, action = config["state"], config["action"]
            message_type = get_message(state["type"])
            action_type = get_action(action["type"])
            self.node.create_subscription(
                message_type, state["topic"],
                lambda message, key=device_id: self.on_state(key, message), 10,
            )
            self.clients[device_id] = (ActionClient(self.node, action_type, action["name"]), action_type)
        self.executor = MultiThreadedExecutor()
        self.executor.add_node(self.node)
        self.thread = threading.Thread(target=self.executor.spin, daemon=True, name="mapped-ros2-executor")
        self.thread.start()

    @staticmethod
    def _wait(future: Any, timeout_s: float) -> Any:
        done = threading.Event()
        future.add_done_callback(lambda _: done.set())
        if not done.wait(timeout_s):
            raise TimeoutError("ROS Action response timed out; physical outcome is unknown")
        return future.result()

    def execute(self, device_id: str, goal_fields: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        client, action_type = self.clients[device_id]
        if not client.wait_for_server(timeout_sec=3.0):
            return {"accepted": False, "dispatched": False, "status": "unavailable", "result": None}
        goal = action_type.Goal()
        for field, value in goal_fields.items():
            setattr(goal, field, value)
        try:
            goal_future = client.send_goal_async(goal)
        except Exception as exc:
            return {"accepted": False, "dispatched": False, "status": "transport_error",
                    "result": None, "error": str(exc)}
        try:
            handle = self._wait(goal_future, 5.0)
        except TimeoutError:
            return {"accepted": False, "dispatched": True, "status": "timed_out", "result": None}
        except Exception as exc:
            return {"accepted": False, "dispatched": True, "status": "transport_error",
                    "result": None, "error": str(exc)}
        if not handle.accepted:
            return {"accepted": False, "dispatched": True, "status": "rejected", "result": None}
        try:
            terminal = self._wait(handle.get_result_async(), timeout_s)
        except TimeoutError:
            try:
                self._wait(handle.cancel_goal_async(), 3.0)
            except Exception:
                pass
            return {"accepted": True, "dispatched": True, "status": "timed_out", "result": None}
        except Exception as exc:
            return {"accepted": True, "dispatched": True, "status": "transport_error",
                    "result": None, "error": str(exc)}
        return {"accepted": True, "dispatched": True, "status": terminal.status, "result": terminal.result}

    def actions_ready(self) -> bool:
        return bool(self.clients) and all(
            client.wait_for_server(timeout_sec=0.0)
            for client, _ in self.clients.values())

    def close(self) -> None:
        if self.executor is not None:
            self.executor.shutdown()
        if self.thread is not None:
            self.thread.join(timeout=2.0)
        if self.node is not None:
            self.node.destroy_node()
        if self._owns_rclpy:
            import rclpy
            if rclpy.ok():
                rclpy.shutdown()


class MappedRos2Adapter:
    """Vendor-neutral Adapter driven by a Hardware Package ROS binding."""

    adapter_id = "ros2_mapped"
    version = "0.1.0"

    def __init__(self, manifest: EmbodimentManifest, *, connection: dict[str, Any] | None = None,
                 control_enabled: bool = False, dry_run: bool = True,
                 transport_factory: Callable[..., Any] | None = None, manage_process: bool = False):
        self.manifest = manifest
        self.connection = connection or {}
        if manage_process or self.connection.get("manage_process", False):
            raise ValueError("Mapped ROS runtime attaches to an existing driver; manage_process must be false")
        self.mapping = _load_mapping(self.connection)
        self.control_enabled = control_enabled
        self.dry_run = dry_run
        self.transport_factory = transport_factory or NativeRos2JointTransport
        self.transport = None
        self._condition = threading.Condition()
        self._states: dict[str, JointState] = {}
        self._state_versions: dict[str, int] = {}
        self._connected = False
        for device_id, config in self.mapping["devices"].items():
            device = self.manifest.device(device_id)
            if device is None or [joint.get("canonical_name", joint.get("name"))
                                  for joint in device.get("joints", [])] != config["joints"]:
                raise ValueError(f"Mapping joint order does not match manifest for {device_id}")

    def configure(self) -> None:
        pass

    def supports_action(self, action_type: str, device_id: str) -> bool:
        return action_type == "joint_position" and device_id in self.mapping["devices"]

    def capabilities(self) -> dict[str, Any]:
        view = self.manifest.capabilities()
        bound = self.mapping["devices"]
        view["devices"] = [device for device in view["devices"] if device["id"] in bound]
        for device in view["devices"]:
            device["capabilities"] = [name for name in device["capabilities"]
                                      if name in ("joint_state", "joint_position")]
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
        self.transport = self.transport_factory(self.mapping, self._on_state)
        self.transport.connect()
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
        ready = (self._connected and self.transport is not None
                 and self.transport.actions_ready() and self._all_mapped_states_ready())
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
        if ((now - state.received_at).total_seconds() > age_limit
                or (now - state.source_timestamp).total_seconds() > age_limit
                or (state.source_timestamp - now).total_seconds() > 1.0):
            return replace(state, status="stale")
        return state

    def _all_mapped_states_ready(self) -> bool:
        with self._condition:
            return all(device_id in self._states and
                       self._fresh_state(self._states[device_id]).status == "ready"
                       for device_id in self.mapping["devices"])

    def _on_state(self, device_id: str, message: Any) -> None:
        config = self.mapping["devices"][device_id]
        state_map = config["state"]
        raw = _field(message, state_map["positions"], [])
        unit = state_map.get("unit", "radian")
        positions = [math.radians(float(value)) if unit == "degree" else float(value) for value in raw]
        fault = _field(message, state_map["fault"], None)
        mode = _field(message, state_map["mode"], None)
        valid = len(positions) == len(config["joints"]) and all(math.isfinite(v) for v in positions)
        status = "fault" if fault not in (None, 0) else (
            "ready" if valid and mode in state_map["ready_modes"] else "not_ready")
        observation = JointState(
            device_id=device_id,
            positions=dict(zip(config["joints"], positions)) if valid else {},
            source_timestamp=_source_stamp(_field(message, state_map["stamp"])),
            received_at=datetime.now(timezone.utc),
            status=status,
            details={"backend_mode": mode, "backend_fault_code": fault},
        )
        with self._condition:
            self._states[device_id] = observation
            self._state_versions[device_id] = self._state_versions.get(device_id, 0) + 1
            self._condition.notify_all()

    def get_joint_state(self, device_id: str) -> JointState:
        if device_id not in self.mapping["devices"]:
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
        states = [self.get_joint_state(device_id) for device_id in self.mapping["devices"]]
        positions = {name: value for state in states for name, value in state.positions.items()}
        return RobotState(
            timestamp=max(state.received_at for state in states),
            joint_positions=positions,
            safety=SafetyState(enabled=all(state.status == "ready" for state in states),
                               fault=any(state.status == "fault" for state in states)),
            device_status={state.device_id: state.status for state in states},
        )

    def send_command(self, command: Command) -> CommandResult:
        if command.mode != "joint_position" or command.target not in self.mapping["devices"]:
            raise CommandRejected(f"No mapped joint move for {command.target}/{command.mode}")
        config = self.mapping["devices"][command.target]
        names = config["joints"]
        positions = command.payload.get("positions")
        if not isinstance(positions, dict) or set(positions) != set(names):
            raise CommandRejected("Mapped joint move requires every canonical joint exactly once")
        target = [float(positions[name]) for name in names]
        goal = dict(config["action"].get("goal_constants", {}))
        goal[config["action"]["goal_positions"]] = (
            [math.degrees(value) for value in target]
            if config["action"].get("unit", "radian") == "degree" else target)
        if self.dry_run:
            return CommandResult(True, "mapped locally; no Action goal sent", status="simulated")
        if not self.control_enabled:
            return CommandResult(False, "control disabled", status="not_dispatched")
        if not self._connected or self.transport is None:
            raise LifecycleError("ROS mapping runtime is disconnected")
        current = self.get_joint_state(command.target)
        if current.status != "ready":
            raise CommandRejected(f"Device {command.target} is {current.status}")
        started = datetime.now(timezone.utc)
        response = self.transport.execute(command.target, goal, float(config.get("action_timeout_s", 90.0)))
        accepted = bool(response.get("accepted"))
        backend_status = response.get("status")
        outcome = response.get("result")
        action_map = config["action"]
        code = _field(outcome, action_map["result_error"]) if outcome is not None else None
        description = _field(outcome, action_map["result_description"], "") if outcome is not None else ""
        details = {"backend_status": backend_status, "backend_description": description,
                   "transport_error": response.get("error"),
                   "goal": goal}
        common = dict(accepted=accepted, dispatched=bool(response.get("dispatched", accepted)), backend_code=code,
                      started_at=started, completed_at=None, details=details,
                      arrival_confirmed=False)
        if not accepted:
            status = ("timed_out" if backend_status == "timed_out" else
                      "outcome_unknown" if backend_status == "transport_error" and common["dispatched"] else
                      "not_dispatched" if backend_status in ("unavailable", "transport_error") else "rejected")
            return CommandResult(status=status, message=str(backend_status), **common)
        if backend_status == "timed_out":
            return CommandResult(status="timed_out", message="Action timed out; outcome unknown", **common)
        if backend_status == "transport_error":
            return CommandResult(status="outcome_unknown",
                                 message="Action result unavailable; physical outcome unknown", **common)
        if backend_status == 5:
            common["completed_at"] = datetime.now(timezone.utc)
            return CommandResult(status="cancelled", message="Action cancelled", **common)
        if backend_status != 4 or code != action_map.get("success_code", 0):
            common["completed_at"] = datetime.now(timezone.utc)
            return CommandResult(status="failed", message=str(description or backend_status), **common)
        terminal_at = datetime.now(timezone.utc)
        with self._condition:
            after_terminal = self._state_versions.get(command.target, 0)
        settled, error = self._wait_for_arrival(command.target, target, after_terminal,
                                               terminal_at, config)
        if settled is None:
            return CommandResult(status="timed_out", message="Action succeeded; measured arrival unconfirmed",
                                 max_joint_error_rad=error, **common)
        common["completed_at"] = datetime.now(timezone.utc)
        common["arrival_confirmed"] = True
        return CommandResult(status="succeeded", message="Action and measured arrival succeeded",
                             final_joint_state=settled, max_joint_error_rad=error, **common)

    def _wait_for_arrival(self, device_id: str, target: list[float], previous: int,
                          terminal_at: datetime,
                          config: dict[str, Any]) -> tuple[JointState | None, float | None]:
        deadline = time.monotonic() + float(self.connection.get("arrival_timeout_s", 20.0))
        tolerance = float(config.get("arrival_tolerance_rad", 0.015))
        settle_window = float(config.get("settle_window_s", 1.0))
        stable_since = None
        last_error = None
        last_version = previous
        with self._condition:
            while time.monotonic() < deadline:
                version = self._state_versions.get(device_id, 0)
                if version > last_version:
                    last_version = version
                    state = self._fresh_state(self._states[device_id])
                    actual = [state.positions.get(name) for name in config["joints"]]
                    if (state.status == "ready" and state.source_timestamp is not None
                            and state.source_timestamp >= terminal_at
                            and all(value is not None for value in actual)):
                        last_error = max(abs(value - desired) for value, desired in zip(actual, target))
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
