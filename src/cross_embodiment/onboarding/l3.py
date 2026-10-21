from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Callable

import yaml

from ..package.loader import load_backend_entrypoint
from ..hardware.manifest import load_manifest
from ..package.manifest import PlatformInfo, load_package_manifest
from ..runtime.installed import ResolvedInstalledRuntime, resolve_installed_runtime
from ..sdk.robot import connect


@dataclass(frozen=True)
class L3ExecutionRecord:
    schema_version: str
    package_root: Path
    package_tree_sha256: str
    mapping_path: Path
    mapping_sha256: str
    backend_id: str
    backend_entrypoint: str
    device_id: str
    state_sample: dict[str, Any]
    commands: tuple[dict[str, Any], ...]
    classification: str
    motion_sent: bool
    operator: str | None
    load_source: str = "explicit_package_root"
    instance_id: str | None = None
    installed_package_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["package_root"] = str(self.package_root)
        value["mapping_path"] = str(self.mapping_path)
        value["commands"] = list(self.commands)
        return value

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _tree_digest(root: Path) -> str:
    digest = sha256()
    ignored = {"__pycache__", ".pytest_cache"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in ignored for part in path.relative_to(root).parts) or path.suffix == ".pyc":
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _state_dict(state: Any) -> dict[str, Any]:
    return {
        "status": state.status,
        "positions": dict(state.positions),
        "source_timestamp": _timestamp(state.source_timestamp),
        "received_at": _timestamp(state.received_at),
        "details": dict(state.details),
    }


def _result_dict(result: Any) -> dict[str, Any]:
    backend_status = result.details.get("backend_status") if isinstance(result.details, dict) else None
    return {
        "accepted": result.accepted,
        "command_id": result.command_id,
        "status": result.status,
        "backend_code": result.backend_code,
        "backend_status": backend_status,
        "message": result.message,
        "dispatched": result.dispatched,
        "started_at": _timestamp(result.started_at),
        "completed_at": _timestamp(result.completed_at),
        "arrival_confirmed": result.arrival_confirmed,
        "max_joint_error_rad": result.max_joint_error_rad,
        "measured_state": _state_dict(result.final_joint_state) if result.final_joint_state is not None else None,
    }


def _load_generated_runtime(package_root: Path, device_id: str) -> tuple[Path, Any, Any, Path, dict[str, Any]]:
    """Resolve runtime inputs strictly within one explicit generated directory."""

    root = package_root.resolve()
    package_manifest = root / "package.yaml"
    if not package_manifest.is_file():
        raise ValueError(f"generated package manifest not found: {package_manifest}")
    package = load_package_manifest(package_manifest)
    if package.root.resolve() != root:
        raise ValueError("resolved package root differs from the explicit generated package")
    package.validate_assets(require_digests=True)

    if not package.embodiment_manifest:
        raise ValueError("generated package has no embodiment manifest")
    manifest_path = (root / package.embodiment_manifest).resolve()
    if not manifest_path.is_relative_to(root) or not manifest_path.is_file():
        raise ValueError("embodiment manifest must stay inside the generated package")
    manifest = load_manifest(manifest_path)
    if manifest.device(device_id) is None:
        raise ValueError(f"generated package does not expose device {device_id!r}")

    config_relative = Path(str(package.defaults.get("config", "")))
    if not config_relative.parts or config_relative.is_absolute() or ".." in config_relative.parts:
        raise ValueError("default connection config must stay inside the generated package")
    config_path = (root / config_relative).resolve()
    if not config_path.is_relative_to(root) or not config_path.is_file():
        raise ValueError("default connection config was not found inside the generated package")
    connection = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(connection, dict):
        raise ValueError("default connection config must be a mapping")
    mapping_relative = Path(str(connection.get("mapping_path", "")))
    if not mapping_relative.parts or mapping_relative.is_absolute() or ".." in mapping_relative.parts:
        raise ValueError("mapping path must stay inside the generated package")
    mapping_path = (root / mapping_relative).resolve()
    declared_mapping = package.resolve_asset_path("interface_mapping", "yaml").resolve()
    if not mapping_path.is_relative_to(root) or mapping_path != declared_mapping:
        raise ValueError("mapping path must resolve to the declared asset inside the generated package")

    platform = PlatformInfo.current(os.environ.get("ROS_DISTRO"))
    backend = package.select_backend(str(package.defaults.get("backend") or ""), platform)
    if not backend.entrypoint:
        raise ValueError("selected generated backend has no entrypoint")
    return root, manifest, backend, mapping_path, connection


def _connect_runtime(
    root: Path,
    manifest: Any,
    backend: Any,
    connection: dict[str, Any],
    *,
    control_enabled: bool,
    connect_fn: Callable[..., Any],
) -> Any:
    adapter = load_backend_entrypoint(backend, root)
    runtime_connection = dict(connection)
    runtime_connection.update({
        "package_root": str(root),
        "require_ros": True,
        "manage_process": False,
    })
    return connect_fn(
        adapter,
        manifest,
        control_enabled=control_enabled,
        dry_run=False,
        connection=runtime_connection,
        manage_process=False,
    )


def preflight_generated_package(
    package_root: Path,
    device_id: str,
    *,
    connect_fn: Callable[..., Any] = connect,
) -> L3ExecutionRecord:
    """Read one canonical joint state from one explicit generated package.

    This path never searches a registry, installs a package, or sends a command.
    The caller supplies the exact package directory that L2 produced.
    """

    root, manifest, backend, mapping_path, connection = _load_generated_runtime(package_root, device_id)
    return _preflight_runtime(
        root, manifest, backend, mapping_path, connection, device_id,
        connect_fn=connect_fn,
    )


def preflight_installed_package(
    store_root: Path,
    instance_id: str,
    device_id: str,
    *,
    connect_fn: Callable[..., Any] = connect,
) -> L3ExecutionRecord:
    """Read state only after resolving an activated immutable Store package."""

    resolved = _installed_l3_runtime(store_root, instance_id, device_id)
    robot = resolved.create_robot(allow_motion=False, connect_fn=connect_fn)
    return _preflight_robot(
        resolved.package_root,
        resolved.manifest,
        resolved.backend,
        resolved.info.mapping_path,
        device_id,
        robot,
        load_source="installed_activation",
        instance_id=instance_id,
        installed_package_digest=resolved.info.package_tree_digest,
    )


def _installed_l3_runtime(
    store_root: Path,
    instance_id: str,
    device_id: str,
) -> ResolvedInstalledRuntime:
    resolved = resolve_installed_runtime(instance_id, store_root)
    if resolved.manifest.device(device_id) is None:
        raise ValueError(f"installed package does not expose device {device_id!r}")
    if resolved.info.mapping_path is None:
        raise ValueError("installed L3 validation requires a declared interface Mapping")
    return resolved


def _preflight_runtime(
    root: Path,
    manifest: Any,
    backend: Any,
    mapping_path: Path,
    connection: dict[str, Any],
    device_id: str,
    *,
    connect_fn: Callable[..., Any],
    load_source: str = "explicit_package_root",
    instance_id: str | None = None,
    installed_package_digest: str | None = None,
) -> L3ExecutionRecord:
    robot = _connect_runtime(
        root, manifest, backend, connection, control_enabled=False, connect_fn=connect_fn,
    )
    return _preflight_robot(
        root,
        manifest,
        backend,
        mapping_path,
        device_id,
        robot,
        load_source=load_source,
        instance_id=instance_id,
        installed_package_digest=installed_package_digest,
    )


def _preflight_robot(
    root: Path,
    manifest: Any,
    backend: Any,
    mapping_path: Path,
    device_id: str,
    robot: Any,
    *,
    load_source: str = "explicit_package_root",
    instance_id: str | None = None,
    installed_package_digest: str | None = None,
) -> L3ExecutionRecord:
    try:
        robot.lifecycle.connect()
        state = robot.get_joint_state(device_id)
    finally:
        robot.lifecycle.stop()

    return L3ExecutionRecord(
        schema_version="l3-execution-record/v0.1",
        package_root=root,
        package_tree_sha256=_tree_digest(root),
        mapping_path=mapping_path,
        mapping_sha256=sha256(mapping_path.read_bytes()).hexdigest(),
        backend_id=backend.id,
        backend_entrypoint=backend.entrypoint,
        device_id=device_id,
        state_sample=_state_dict(state),
        commands=(),
        classification="preflight_read_only",
        motion_sent=False,
        operator=None,
        load_source=load_source,
        instance_id=instance_id,
        installed_package_digest=installed_package_digest,
    )


def execute_generated_package_round_trip(
    package_root: Path,
    device_id: str,
    target: dict[str, float],
    *,
    operator: str,
    authorized: bool,
    connect_fn: Callable[..., Any] = connect,
) -> L3ExecutionRecord:
    """Execute one explicit target and return to the measured starting state.

    This function is only the deterministic execution primitive. The CLI and
    runbook must show the complete target and obtain onsite confirmation before
    passing ``authorized=True``.
    """

    root, manifest, backend, mapping_path, connection = _load_generated_runtime(package_root, device_id)
    return _execute_runtime_round_trip(
        root, manifest, backend, mapping_path, connection, device_id, target,
        operator=operator,
        authorized=authorized,
        connect_fn=connect_fn,
    )


def execute_installed_package_round_trip(
    store_root: Path,
    instance_id: str,
    device_id: str,
    target: dict[str, float],
    *,
    operator: str,
    authorized: bool,
    connect_fn: Callable[..., Any] = connect,
) -> L3ExecutionRecord:
    """Run the existing SDK probe/return using one activated Store package."""

    resolved = _installed_l3_runtime(store_root, instance_id, device_id)
    joint_names, full_target = _validate_round_trip_request(
        resolved.manifest,
        device_id,
        target,
        operator=operator,
        authorized=authorized,
    )
    robot = resolved.create_robot(allow_motion=True, connect_fn=connect_fn)
    return _execute_robot_round_trip(
        resolved.package_root,
        resolved.manifest,
        resolved.backend,
        resolved.info.mapping_path,
        device_id,
        joint_names,
        full_target,
        robot,
        operator=operator,
        load_source="installed_activation",
        instance_id=instance_id,
        installed_package_digest=resolved.info.package_tree_digest,
    )


def _execute_runtime_round_trip(
    root: Path,
    manifest: Any,
    backend: Any,
    mapping_path: Path,
    connection: dict[str, Any],
    device_id: str,
    target: dict[str, float],
    *,
    operator: str,
    authorized: bool,
    connect_fn: Callable[..., Any],
    load_source: str = "explicit_package_root",
    instance_id: str | None = None,
    installed_package_digest: str | None = None,
) -> L3ExecutionRecord:
    joint_names, full_target = _validate_round_trip_request(
        manifest,
        device_id,
        target,
        operator=operator,
        authorized=authorized,
    )
    robot = _connect_runtime(
        root, manifest, backend, connection, control_enabled=True, connect_fn=connect_fn,
    )
    return _execute_robot_round_trip(
        root,
        manifest,
        backend,
        mapping_path,
        device_id,
        joint_names,
        full_target,
        robot,
        operator=operator,
        load_source=load_source,
        instance_id=instance_id,
        installed_package_digest=installed_package_digest,
    )


def _execute_robot_round_trip(
    root: Path,
    manifest: Any,
    backend: Any,
    mapping_path: Path,
    device_id: str,
    joint_names: tuple[str, ...],
    full_target: dict[str, float],
    robot: Any,
    *,
    operator: str,
    load_source: str = "explicit_package_root",
    instance_id: str | None = None,
    installed_package_digest: str | None = None,
) -> L3ExecutionRecord:
    commands: list[dict[str, Any]] = []
    motion_sent = False
    try:
        robot.lifecycle.connect()
        initial = robot.get_joint_state(device_id)
        return_target = {name: float(initial.positions[name]) for name in joint_names}
        probe_result = robot.move_joints(device_id, full_target)
        motion_sent = bool(probe_result.dispatched)
        commands.append({
            "operation": "probe",
            "target": full_target,
            "result": _result_dict(probe_result),
        })
        probe_ok = probe_result.status == "succeeded" and probe_result.arrival_confirmed is True
        if probe_ok:
            return_result = robot.move_joints(device_id, return_target)
            motion_sent = motion_sent or bool(return_result.dispatched)
            commands.append({
                "operation": "return",
                "target": return_target,
                "result": _result_dict(return_result),
            })
        passed = (
            len(commands) == 2
            and all(item["result"]["status"] == "succeeded" for item in commands)
            and all(item["result"]["arrival_confirmed"] is True for item in commands)
        )
    finally:
        robot.lifecycle.stop()

    return L3ExecutionRecord(
        schema_version="l3-execution-record/v0.1",
        package_root=root,
        package_tree_sha256=_tree_digest(root),
        mapping_path=mapping_path,
        mapping_sha256=sha256(mapping_path.read_bytes()).hexdigest(),
        backend_id=backend.id,
        backend_entrypoint=backend.entrypoint,
        device_id=device_id,
        state_sample=_state_dict(initial),
        commands=tuple(commands),
        classification="passed" if passed else "hardware_validation_failed",
        motion_sent=motion_sent,
        operator=operator,
        load_source=load_source,
        instance_id=instance_id,
        installed_package_digest=installed_package_digest,
    )


def _validate_round_trip_request(
    manifest: Any,
    device_id: str,
    target: dict[str, float],
    *,
    operator: str,
    authorized: bool,
) -> tuple[tuple[str, ...], dict[str, float]]:
    if not authorized:
        raise PermissionError("explicit onsite L3 authorization is required")
    if not operator.strip():
        raise ValueError("operator identity is required")
    device = manifest.device(device_id)
    joint_names = tuple(
        joint.get("canonical_name", joint.get("name"))
        for joint in device.get("joints", [])
    )
    if set(target) != set(joint_names):
        raise ValueError(f"L3 target must contain exactly {sorted(joint_names)}")
    return joint_names, {name: float(target[name]) for name in joint_names}
