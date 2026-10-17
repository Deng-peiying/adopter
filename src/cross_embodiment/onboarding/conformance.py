from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import importlib
from importlib.resources import files
import json
import math
from pathlib import Path
import threading
from typing import Any

import yaml

from ..backend.protocol import TransportEvent, TransportRequest, TransportResult
from ..driver.ros2_mapped import MappedRos2Adapter
from ..hardware.manifest import load_manifest
from ..mapping.engine import InterfaceMappingEngine
from ..package.manifest import load_package_manifest
from ..protocol.types import Command


@dataclass(frozen=True)
class ConformanceReport:
    passed: bool
    checks: tuple[str, ...]
    failures: tuple[str, ...]
    resolved_package_root: Path
    resolved_mapping_path: Path | None


@dataclass(frozen=True)
class SemanticDifference:
    field: str
    candidate: Any
    reference: Any


@dataclass(frozen=True)
class SemanticDiff:
    equivalent: bool
    differences: tuple[SemanticDifference, ...]


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    current = target
    parts = path.split(".")
    for name in parts[:-1]:
        current = current.setdefault(name, {})
    current[parts[-1]] = value


class _ReplayTransport:
    def __init__(self, engine: InterfaceMappingEngine, mode: str):
        self.engine = engine
        self.mode = mode
        self.callback = None
        self.state_binding = next(
            key for key, value in engine.bindings.items()
            if value["semantic"]["operation"] == "joint_state"
        )

    def _state_payload(self, positions: list[float]) -> dict[str, Any]:
        binding = self.engine.bindings[self.state_binding]
        decode = binding["decode"]
        payload: dict[str, Any] = {}
        now = datetime.now(timezone.utc)
        _set_path(payload, decode["positions"], positions)
        _set_path(payload, decode["stamp"], {"sec": int(now.timestamp()), "nanosec": now.microsecond * 1000})
        _set_path(payload, decode["mode"], decode["ready_values"][0])
        _set_path(payload, decode["fault"], 0)
        return payload

    def connect(self, bindings, on_event) -> None:
        self.callback = on_event
        count = len(self.engine.bindings[self.state_binding]["semantic"]["joints"])
        on_event(TransportEvent(self.state_binding, "state", self._state_payload([0.0] * count)))

    def execute(self, request: TransportRequest) -> TransportResult:
        if self.mode == "timeout":
            return TransportResult(request.binding_id, "timed_out", accepted=True, dispatched=True, cancel_requested=True, cancel_accepted=False)
        binding = self.engine.bindings[request.binding_id]
        target_field = binding["encode"]["positions"]["field"]
        target = list(request.payload[target_field])
        assert self.callback is not None
        threading.Timer(
            0.03,
            lambda: self.callback(TransportEvent(self.state_binding, "state", self._state_payload(target))),
        ).start()
        payload: dict[str, Any] = {}
        _set_path(payload, binding["result"]["error_code"], binding["result"]["success_code"])
        _set_path(payload, binding["result"]["description"], "")
        return TransportResult(request.binding_id, "succeeded", accepted=True, dispatched=True, payload=payload, backend_status=4)

    def ready(self, binding_ids) -> bool:
        return True

    def close(self) -> None:
        pass


class ConformanceRunner:
    def __init__(self, denied_markers: tuple[str, ...] = ()):
        self.denied_markers = denied_markers

    def validate_generated_package(self, package_root: Path) -> ConformanceReport:
        root = package_root.resolve()
        checks: list[str] = []
        failures: list[str] = []
        mapping_path: Path | None = None
        try:
            package = load_package_manifest(root / "package.yaml")
            if package.root.resolve() != root:
                raise ValueError("resolved package root selected another package")
            checks.extend(("package_schema", "resolved_package_identity"))
        except Exception as exc:
            return ConformanceReport(False, tuple(checks), (f"package schema: {exc}",), root, None)

        try:
            package.validate_assets(require_digests=True)
            checks.append("asset_digests")
        except Exception as exc:
            failures.append(f"asset digest validation: {exc}")

        try:
            config_relative = Path(str(package.defaults["config"]))
            if config_relative.is_absolute() or ".." in config_relative.parts:
                raise ValueError("default config path leaves generated package")
            config = yaml.safe_load((root / config_relative).read_text())
            mapping_relative = Path(str(config["mapping_path"]))
            if mapping_relative.is_absolute() or ".." in mapping_relative.parts:
                raise ValueError("mapping path leaves generated package")
            mapping_path = (root / mapping_relative).resolve()
            declared = package.resolve_asset_path("interface_mapping", "yaml").resolve()
            if mapping_path != declared or not mapping_path.is_relative_to(root):
                raise ValueError("mapping path does not resolve to declared generated asset")
        except Exception as exc:
            failures.append(f"mapping path resolution: {exc}")

        try:
            provenance = yaml.safe_load((root / "generation-provenance.yaml").read_text())
            for item in provenance.get("evidence", []):
                source = str(item.get("source_path", ""))
                if Path(source).is_absolute() or ".." in Path(source).parts or any(marker in source for marker in self.denied_markers):
                    raise ValueError(f"provenance contains denied reference: {source}")
            checks.append("provenance_isolation")
        except Exception as exc:
            failures.append(f"provenance isolation: {exc}")

        try:
            backend = package.select_backend(package.defaults.get("backend"), type("Platform", (), {"os": "linux", "arch": "x86_64", "ros_distro": "humble"})())
            module_name, symbol = str(backend.entrypoint).split(":", 1)
            getattr(importlib.import_module(module_name), symbol)
            checks.append("backend_entrypoint")
        except Exception as exc:
            failures.append(f"backend entrypoint: {exc}")

        if mapping_path is None or not mapping_path.is_file():
            return ConformanceReport(False, tuple(checks), tuple(failures), root, mapping_path)
        try:
            manifest = load_manifest(root / str(package.embodiment_manifest))
            engine = InterfaceMappingEngine.from_connection({"mapping_path": mapping_path}, manifest)
            state_id = next(key for key, value in engine.bindings.items() if value["semantic"]["operation"] == "joint_state")
            state_binding = engine.bindings[state_id]
            count = len(state_binding["semantic"]["joints"])
            replay = _ReplayTransport(engine, "success")
            decoded = engine.decode_event(TransportEvent(state_id, "state", replay._state_payload([0.1] * count)))
            if decoded is None or decoded.status != "ready" or len(decoded.positions) != count:
                raise AssertionError("state replay did not decode to ready canonical state")
            checks.append("state_decode")

            target = {name: 0.0 for name in state_binding["semantic"]["joints"]}
            compiled = engine.compile_command(Command(state_binding["semantic"]["device"], "joint_position", {"positions": target}))
            if len(compiled.target_positions) != count:
                raise AssertionError("goal did not retain every ordered joint")
            checks.append("goal_encode")

            failed_payload: dict[str, Any] = {}
            _set_path(failed_payload, compiled.result["error_code"], 9)
            _set_path(failed_payload, compiled.result["description"], "failure")
            failed = engine.decode_result(TransportResult(compiled.request.binding_id, "succeeded", True, True, failed_payload, 4), compiled)
            if failed.vendor_succeeded:
                raise AssertionError("non-success vendor code was accepted")
            checks.append("vendor_failure")

            timeout_adapter = MappedRos2Adapter(manifest, connection={"mapping_path": str(mapping_path)}, control_enabled=True, dry_run=False, transport_factory=lambda: _ReplayTransport(engine, "timeout"))
            timeout_adapter.connect()
            timed = timeout_adapter.send_command(Command(compiled.device_id, "joint_position", {"positions": target}))
            timeout_adapter.disconnect()
            if timed.status != "timed_out" or not timed.details.get("cancel_requested"):
                raise AssertionError("timeout/cancel uncertainty was not preserved")
            checks.append("timeout_uncertainty")

            success_adapter = MappedRos2Adapter(manifest, connection={"mapping_path": str(mapping_path), "arrival_timeout_s": 3.0}, control_enabled=True, dry_run=False, transport_factory=lambda: _ReplayTransport(engine, "success"))
            success_adapter.connect()
            succeeded = success_adapter.send_command(Command(compiled.device_id, "joint_position", {"positions": target}))
            success_adapter.disconnect()
            if succeeded.status != "succeeded" or not succeeded.arrival_confirmed:
                raise AssertionError("terminal success lacked measured arrival")
            checks.append("measured_arrival")
        except Exception as exc:
            failures.append(f"runtime conformance: {exc}")
        return ConformanceReport(not failures, tuple(checks), tuple(failures), root, mapping_path)

    def validate_candidate_package(self, package_root: Path) -> ConformanceReport:
        """Validate interface evidence without treating the package as executable."""
        root = package_root.resolve()
        checks: list[str] = []
        failures: list[str] = []
        mapping_path: Path | None = None
        try:
            package = load_package_manifest(root / "package.yaml")
            if package.root.resolve() != root:
                raise ValueError("resolved package root selected another package")
            if package.validation.get("candidate_only") is not True:
                raise ValueError("package is not marked candidate_only")
            if package.validation.get("live_execution_ready") is not False:
                raise ValueError("candidate package must block live execution")
            checks.append("package_schema")
        except Exception as exc:
            return ConformanceReport(
                False, tuple(checks), (f"candidate package schema: {exc}",),
                root, None,
            )

        try:
            package.validate_assets(require_digests=True)
            checks.append("asset_digests")
        except Exception as exc:
            failures.append(f"asset digest validation: {exc}")

        try:
            if "interface_mapping" in package.assets:
                raise ValueError("candidate package exposes a runtime mapping asset")
            mapping_path = package.resolve_asset_path(
                "interface_mapping_candidate", "yaml"
            ).resolve()
            mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
            schema_resource = files("cross_embodiment.onboarding").joinpath(
                "schemas/interface-mapping-candidate.schema.json"
            )
            schema = json.loads(schema_resource.read_text(encoding="utf-8"))
            try:
                import jsonschema  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "candidate schema validation requires the onboarding extra: "
                    "pip install 'cross-embodiment[onboarding]'"
                ) from exc
            jsonschema.validate(mapping, schema)
            checks.append("candidate_mapping_schema")
        except Exception as exc:
            failures.append(f"candidate mapping schema: {exc}")
            mapping = None

        try:
            if package.defaults:
                raise ValueError("candidate package declares runtime defaults")
            if any(
                backend.entrypoint or backend.launch or backend.executable
                for backend in package.backends
            ):
                raise ValueError("candidate package exposes an executable backend")
            if (root / "config/connection.yaml").exists():
                raise ValueError("candidate package contains a runtime connection")
            checks.append("runtime_execution_blocked")
        except Exception as exc:
            failures.append(f"runtime execution isolation: {exc}")

        if isinstance(mapping, dict):
            try:
                operations = {
                    binding["semantic"]["operation"]: binding
                    for binding in mapping["bindings"].values()
                }
                if set(operations) != {"joint_state", "joint_position"}:
                    raise ValueError("candidate requires state and position bindings")
                if not all(
                    binding.get("interface_mapped") is True
                    and binding.get("evidence")
                    for binding in operations.values()
                ):
                    raise ValueError("interface mapping lacks evidence")
                checks.append("interface_mapping_complete")
                policy = operations["joint_position"].get("completion_policy")
                if not isinstance(policy, dict) or policy.get("status") != "unresolved":
                    raise ValueError("completion policy gap is not explicit")
                if not policy.get("missing_fields"):
                    raise ValueError("completion policy has no unresolved fields")
                checks.append("execution_policy_gap_recorded")
            except Exception as exc:
                failures.append(f"candidate interface coverage: {exc}")

        try:
            provenance = yaml.safe_load(
                (root / "generation-provenance.yaml").read_text(encoding="utf-8")
            )
            for item in provenance.get("evidence", []):
                source = str(item.get("source_path", ""))
                if (
                    Path(source).is_absolute()
                    or ".." in Path(source).parts
                    or any(marker in source for marker in self.denied_markers)
                ):
                    raise ValueError(
                        f"provenance contains denied reference: {source}"
                    )
            checks.append("provenance_isolation")
        except Exception as exc:
            failures.append(f"provenance isolation: {exc}")

        return ConformanceReport(
            not failures, tuple(checks), tuple(failures), root, mapping_path,
        )


def _semantic_mapping(root: Path) -> dict[str, Any]:
    package = load_package_manifest(root / "package.yaml")
    mapping_path = package.resolve_asset_path("interface_mapping", "yaml", verify_digest=False)
    mapping = yaml.safe_load(mapping_path.read_text())
    manifest = load_manifest(root / str(package.embodiment_manifest))
    result: dict[str, Any] = {
        "devices": [device.get("id") for device in manifest.devices],
        "bindings": {},
    }
    for name, binding in sorted(mapping["bindings"].items()):
        result["bindings"][name] = {
            "semantic": binding.get("semantic"), "transport": binding.get("transport"),
            "decode": binding.get("decode"), "encode": binding.get("encode"),
            "result": binding.get("result"), "completion": binding.get("completion"),
        }
    return result


def _diff(prefix: str, left: Any, right: Any, output: list[SemanticDifference]) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            _diff(f"{prefix}.{key}" if prefix else key, left.get(key), right.get(key), output)
    elif left != right:
        output.append(SemanticDifference(prefix, left, right))


class IndependentEvaluator:
    @staticmethod
    def compare(candidate_root: Path, reference_root: Path) -> SemanticDiff:
        differences: list[SemanticDifference] = []
        _diff("", _semantic_mapping(candidate_root), _semantic_mapping(reference_root), differences)
        return SemanticDiff(not differences, tuple(differences))
