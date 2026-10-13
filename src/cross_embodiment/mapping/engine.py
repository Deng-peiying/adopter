"""Compile canonical commands to backend calls and decode backend observations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any

import yaml

from ..backend.protocol import TransportEvent, TransportRequest, TransportResult
from ..errors import CommandRejected
from ..hardware.manifest import EmbodimentManifest
from ..protocol.types import Command, JointState


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


def _convert_positions(values: list[float], source_unit: str, target_unit: str) -> list[float]:
    if source_unit == target_unit:
        return values
    if source_unit == "degree" and target_unit == "radian":
        return [math.radians(value) for value in values]
    if source_unit == "radian" and target_unit == "degree":
        return [math.degrees(value) for value in values]
    raise ValueError(f"Unsupported joint unit conversion: {source_unit} -> {target_unit}")


@dataclass(frozen=True)
class CompiledCommand:
    request: TransportRequest
    device_id: str
    joint_names: list[str]
    target_positions: list[float]
    result: dict[str, Any]
    completion: dict[str, Any]


@dataclass(frozen=True)
class DecodedTransportResult:
    transport: TransportResult
    backend_code: str | int | None
    description: str
    vendor_succeeded: bool


class InterfaceMappingEngine:
    """Pure mapping logic loaded from a Hardware Package."""

    SCHEMA_VERSION = "interface-mapping/v1"

    def __init__(self, mapping: dict[str, Any], manifest: EmbodimentManifest):
        self.mapping = mapping
        self.manifest = manifest
        self.bindings: dict[str, dict[str, Any]] = mapping["bindings"]
        self._validate()

    @classmethod
    def from_connection(
        cls, connection: dict[str, Any], manifest: EmbodimentManifest,
    ) -> "InterfaceMappingEngine":
        if "mapping" in connection:
            data = deepcopy(connection["mapping"])
        else:
            path = Path(connection["mapping_path"])
            if not path.is_absolute():
                path = Path(connection.get("package_root", ".")) / path
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError(f"Expected {cls.SCHEMA_VERSION} configuration")
        if not isinstance(data.get("bindings"), dict) or not data["bindings"]:
            raise ValueError("Interface mapping requires bindings")
        return cls(data, manifest)

    def _validate(self) -> None:
        states: dict[str, str] = {}
        actions: list[tuple[str, dict[str, Any]]] = []
        for binding_id, binding in self.bindings.items():
            semantic = binding.get("semantic")
            transport = binding.get("transport")
            if not isinstance(semantic, dict) or not isinstance(transport, dict):
                raise ValueError(f"Binding {binding_id} requires semantic and transport sections")
            for key in ("operation", "device", "joints", "unit"):
                if key not in semantic:
                    raise ValueError(f"Binding {binding_id} semantic requires {key}")
            if semantic["unit"] != "radian":
                raise ValueError(f"Binding {binding_id} canonical semantic unit must be radian")
            if not isinstance(semantic["joints"], list) or not semantic["joints"]:
                raise ValueError(f"Binding {binding_id} requires ordered joints")
            device = self.manifest.device(semantic["device"])
            manifest_joints = [] if device is None else [
                joint.get("canonical_name", joint.get("name")) for joint in device.get("joints", [])
            ]
            if manifest_joints != semantic["joints"]:
                raise ValueError(f"Mapping joint order does not match manifest for {semantic['device']}")
            for key in ("backend", "kind", "endpoint", "interface"):
                if not transport.get(key):
                    raise ValueError(f"Binding {binding_id} transport requires {key}")
            operation = semantic["operation"]
            if operation == "joint_state":
                if transport["kind"] != "subscription" or not isinstance(binding.get("decode"), dict):
                    raise ValueError(f"Joint state binding {binding_id} requires subscription decode")
                decode = binding["decode"]
                for key in ("positions", "stamp", "mode", "ready_values", "fault", "unit"):
                    if key not in decode:
                        raise ValueError(f"Binding {binding_id} decode requires {key}")
                if decode["unit"] not in ("radian", "degree"):
                    raise ValueError(f"Unsupported decode unit in {binding_id}")
                if not isinstance(decode["ready_values"], list):
                    raise ValueError(f"Binding {binding_id} ready_values must be a list")
                states[binding_id] = semantic["device"]
            elif operation == "joint_position":
                if transport["kind"] != "action" or "timeout_s" not in transport:
                    raise ValueError(f"Joint position binding {binding_id} requires timed action transport")
                for section in ("encode", "result", "completion"):
                    if not isinstance(binding.get(section), dict):
                        raise ValueError(f"Binding {binding_id} requires {section}")
                encode = binding["encode"]
                positions = encode.get("positions")
                if not isinstance(positions, dict):
                    raise ValueError(f"Binding {binding_id} requires positions encoder")
                for key in ("source", "field", "unit"):
                    if key not in positions:
                        raise ValueError(f"Binding {binding_id} positions encoder requires {key}")
                if positions["source"] != "positions":
                    raise ValueError(f"Binding {binding_id} positions source must be positions")
                if positions["unit"] not in ("radian", "degree"):
                    raise ValueError(f"Unsupported encode unit in {binding_id}")
                if "constants" in encode and not isinstance(encode["constants"], dict):
                    raise ValueError(f"Binding {binding_id} constants must be a mapping")
                for key in ("error_code", "description", "success_code"):
                    if key not in binding["result"]:
                        raise ValueError(f"Binding {binding_id} result requires {key}")
                for key in ("state_binding", "arrival_tolerance_rad", "settle_window_s"):
                    if key not in binding["completion"]:
                        raise ValueError(f"Binding {binding_id} completion requires {key}")
                float(transport["timeout_s"])
                float(binding["completion"]["arrival_tolerance_rad"])
                float(binding["completion"]["settle_window_s"])
                actions.append((binding_id, binding))
            else:
                raise ValueError(f"Unsupported mapped operation: {operation}")
        for binding_id, binding in actions:
            state_id = binding["completion"].get("state_binding")
            if state_id not in states:
                raise ValueError(f"Binding {binding_id} completion references unknown state binding")
            if states[state_id] != binding["semantic"]["device"]:
                raise ValueError(f"Binding {binding_id} completion uses a different device")

    def transport_bindings(self) -> list[TransportRequest]:
        return [self._request(binding_id, binding, {})
                for binding_id, binding in self.bindings.items()]

    def _request(
        self, binding_id: str, binding: dict[str, Any], payload: dict[str, Any],
    ) -> TransportRequest:
        transport = binding["transport"]
        return TransportRequest(
            binding_id=binding_id,
            backend=transport["backend"],
            kind=transport["kind"],
            endpoint=transport["endpoint"],
            interface=transport["interface"],
            payload=payload,
            timeout_s=float(transport["timeout_s"]) if "timeout_s" in transport else None,
        )

    def action_binding_ids(self) -> list[str]:
        return [binding_id for binding_id, binding in self.bindings.items()
                if binding["transport"]["kind"] == "action"]

    def backend_types(self) -> set[str]:
        return {binding["transport"]["backend"] for binding in self.bindings.values()}

    def device_ids(self) -> list[str]:
        return list(dict.fromkeys(binding["semantic"]["device"]
                                  for binding in self.bindings.values()))

    def supports(self, operation: str, device_id: str) -> bool:
        return any(binding["semantic"]["operation"] == operation
                   and binding["semantic"]["device"] == device_id
                   for binding in self.bindings.values())

    def compile_command(self, command: Command) -> CompiledCommand:
        matches = [(binding_id, binding) for binding_id, binding in self.bindings.items()
                   if binding["semantic"]["operation"] == command.mode
                   and binding["semantic"]["device"] == command.target]
        if len(matches) != 1:
            raise CommandRejected(f"No mapped command for {command.target}/{command.mode}")
        binding_id, binding = matches[0]
        semantic = binding["semantic"]
        names = semantic["joints"]
        positions = command.payload.get("positions")
        if not isinstance(positions, dict) or set(positions) != set(names):
            raise CommandRejected("Mapped joint move requires every canonical joint exactly once")
        target = [float(positions[name]) for name in names]
        if not all(math.isfinite(value) for value in target):
            raise CommandRejected("Mapped joint move requires finite positions")
        position_map = binding["encode"]["positions"]
        if position_map.get("source") != "positions" or not position_map.get("field"):
            raise ValueError(f"Binding {binding_id} has an invalid positions encoder")
        output = _convert_positions(target, semantic["unit"], position_map["unit"])
        payload = deepcopy(binding["encode"].get("constants", {}))
        payload[position_map["field"]] = output
        return CompiledCommand(
            request=self._request(binding_id, binding, payload),
            device_id=command.target,
            joint_names=list(names),
            target_positions=target,
            result=deepcopy(binding["result"]),
            completion=deepcopy(binding["completion"]),
        )

    def decode_event(self, event: TransportEvent) -> JointState | None:
        binding = self.bindings.get(event.binding_id)
        if binding is None or binding["semantic"]["operation"] != "joint_state":
            return None
        semantic, decode = binding["semantic"], binding["decode"]
        raw = _field(event.payload, decode["positions"], [])
        try:
            positions = [float(value) for value in raw]
            positions = _convert_positions(positions, decode["unit"], semantic["unit"])
        except (TypeError, ValueError):
            positions = []
        fault = _field(event.payload, decode["fault"], None)
        mode = _field(event.payload, decode["mode"], None)
        valid = len(positions) == len(semantic["joints"]) and all(
            math.isfinite(value) for value in positions
        )
        status = "fault" if fault not in (None, 0) else (
            "ready" if valid and mode in decode["ready_values"] else "not_ready"
        )
        return JointState(
            device_id=semantic["device"],
            positions=dict(zip(semantic["joints"], positions)) if valid else {},
            source_timestamp=_source_stamp(_field(event.payload, decode["stamp"])),
            received_at=event.received_at,
            status=status,
            details={"backend_mode": mode, "backend_fault_code": fault},
        )

    def decode_result(
        self, result: TransportResult, compiled: CompiledCommand,
    ) -> DecodedTransportResult:
        payload = result.payload
        code = _field(payload, compiled.result["error_code"]) if payload is not None else None
        description = _field(payload, compiled.result["description"], "") if payload is not None else ""
        return DecodedTransportResult(
            transport=result,
            backend_code=code,
            description=str(description or ""),
            vendor_succeeded=(result.status == "succeeded"
                              and code == compiled.result["success_code"]),
        )
