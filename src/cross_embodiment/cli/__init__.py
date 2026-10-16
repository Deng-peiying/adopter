from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
import runpy
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import yaml

from ..errors import CrossEmbodimentError, PackageError
from ..driver.backend import load_backend_entrypoint
from ..hardware.instance import RobotInstance
from ..package.lock import load_lock
from ..hardware.manifest import load_manifest
from ..package.project import ProjectSpec, load_project
from ..package.registry import LocalRegistry
from ..package.resolver import PackageResolver, Resolution
from ..sdk.robot import connect


def _registry_root(project_path: Path, configured: Path | None = None) -> Path:
    if configured is not None:
        return configured
    env_root = os.environ.get("CROSS_EMBODIMENT_REGISTRY")
    if env_root:
        return Path(env_root)
    for candidate in (project_path.parent, *project_path.parent.parents):
        if (candidate / "assets" / "catalog.yaml").is_file():
            return candidate
    return Path.home() / ".cross_embodiment" / "registry"


def _package_store(configured: Path | None = None) -> Path:
    if configured is not None:
        return configured
    return Path(os.environ.get("CROSS_EMBODIMENT_STORE", Path.home() / ".cross_embodiment"))


def _load(
    project_path: Path,
    *,
    registry_root: Path | None = None,
    install: bool = False,
    installed_only: bool = False,
) -> tuple[ProjectSpec, Resolution]:
    project = load_project(project_path)
    registry = LocalRegistry(_registry_root(project_path, registry_root))
    resolution = PackageResolver(registry).resolve(project, install=install, installed_only=installed_only)
    return project, resolution


def _manifest_and_instance(project: ProjectSpec, resolution: Resolution, name: str | None = None):
    robot_name = name or next(iter(project.robots), None)
    if robot_name is None:
        raise PackageError("Project declares no robots")
    spec = project.robots[robot_name]
    package = resolution.hardware[spec["package"]]
    if not package.embodiment_manifest:
        raise PackageError(f"Package {package.name} has no embodiment_manifest")
    manifest_path = package.root / package.embodiment_manifest
    if not manifest_path.is_file():
        raise PackageError(f"Embodiment manifest not found: {manifest_path}")
    return robot_name, package, load_manifest(manifest_path), resolution.instances.get(robot_name)


def _connection_defaults(package, instance) -> dict[str, Any]:
    connection: dict[str, Any] = {}
    config_path = package.defaults.get("config")
    if config_path:
        relative = Path(str(config_path))
        if relative.is_absolute() or ".." in relative.parts:
            raise PackageError(f"Package default config must stay inside package: {config_path}")
        path = (package.root / relative).resolve()
        if not path.is_relative_to(package.root.resolve()) or not path.is_file():
            raise PackageError(f"Package default config was not found: {config_path}")
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise PackageError(f"Package default config must be a mapping: {config_path}")
        connection.update(data)
    connection.update(dict(getattr(instance, "connection", {}) or {}))
    return connection


def _runtime_dir(project: ProjectSpec) -> Path:
    path = project.root / ".ce" / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _validate(project_path: Path, registry_root: Path | None = None) -> None:
    project, resolution = _load(project_path, registry_root=registry_root, installed_only=True)
    lock_path = project.root / "embodiment.lock"
    if not lock_path.is_file():
        raise PackageError(f"Project lock is missing; run ce install first: {lock_path}")
    lock = load_lock(lock_path)
    for name, spec in project.robots.items():
        package = resolution.hardware[spec["package"]]
        package.validate_assets(require_digests=bool(package.assets))
        if package.embodiment_manifest:
            manifest_path = package.root / package.embodiment_manifest
            load_manifest(manifest_path)
        instance = resolution.instances.get(name)
        if instance is not None and isinstance(instance, RobotInstance):
            if instance.package != package.name or instance.version != package.version:
                raise PackageError(f"Instance {name} does not match package {package.name}@{package.version}")
            lock.verify(package, instance)
            if instance.backend_preferred and instance.backend_preferred not in {backend.id for backend in package.backends}:
                raise PackageError(f"Unknown backend {instance.backend_preferred} for {package.name}")
            locked_backend = lock.hardware[package.name].get("backend")
            if locked_backend and locked_backend not in {backend.id for backend in package.backends}:
                raise PackageError(f"Locked backend {locked_backend} is unavailable for {package.name}")


def _install(project_path: Path, lock_path: Path | None = None, registry_root: Path | None = None) -> Path:
    project, resolution = _load(project_path, registry_root=registry_root, install=True)
    target = lock_path or (project.root / "embodiment.lock")
    resolution.write_lock(target)
    return target


def _up(project_path: Path, *, robot_name: str | None, dry_run: bool, control_enabled: bool, registry_root: Path | None = None) -> None:
    project, resolution = _load(project_path, registry_root=registry_root, installed_only=True)
    _validate(project_path, registry_root)
    lock = load_lock(project.root / "embodiment.lock")
    name, package, manifest, instance = _manifest_and_instance(project, resolution, robot_name)
    connection = _connection_defaults(package, instance)
    backend = resolution.selected_backends.get(package.name)
    if backend is None:
        raise PackageError(f"No Backend selected for {package.name}")
    locked_backend = lock.hardware[package.name].get("backend")
    if locked_backend:
        backend = next((candidate for candidate in package.backends if candidate.id == locked_backend), None)
        if backend is None:
            raise PackageError(f"Locked Backend {locked_backend} is missing from {package.name}")
    connection["package_root"] = str(package.root)
    if backend.launch:
        launch_path = Path(backend.launch)
        if launch_path.is_absolute() or ".." in launch_path.parts:
            raise PackageError(f"Backend launch path must stay inside the Hardware Package: {backend.launch}")
        connection.setdefault("launch_command", ["bash", backend.launch])
    connection["require_ros"] = not dry_run
    manage_process = bool(connection.get("manage_process", bool(backend.launch))) and not dry_run
    connection["manage_process"] = manage_process
    adapter = "mock" if backend.type == "mock" else load_backend_entrypoint(backend, package.root)
    robot = connect(
        adapter,
        manifest,
        control_enabled=control_enabled,
        dry_run=dry_run,
        connection=connection,
        manage_process=manage_process,
    )
    try:
        robot.lifecycle.connect()
        mode = "dry-run" if dry_run else "native"
        print(f"up: {name} ({package.name}@{package.version}) [{mode}]")
    finally:
        robot.lifecycle.stop()


def _start_host(project_path: Path, *, robot_name: str | None, control_enabled: bool, registry_root: Path | None) -> None:
    project = load_project(project_path)
    _validate(project_path, registry_root)
    runtime = _runtime_dir(project)
    active = runtime / "active.json"
    if active.is_file():
        try:
            current = json.loads(active.read_text(encoding="utf-8"))
            os.kill(int(current["pid"]), 0)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            active.unlink(missing_ok=True)
        else:
            raise PackageError(f"Project already has an active runtime (pid {current['pid']}); run ce down first")
    ready, failed = runtime / "ready.json", runtime / "failed.json"
    ready.unlink(missing_ok=True)
    failed.unlink(missing_ok=True)
    log = runtime / "host.log"
    project_file = project_path.resolve()
    command = [sys.executable, "-m", "cross_embodiment.cli", "_host", "--project", str(project_file)]
    if robot_name:
        command.extend(("--robot", robot_name))
    if control_enabled:
        command.append("--control-enabled")
    if registry_root:
        command.extend(("--registry", str(registry_root.resolve())))
    with log.open("ab") as stream:
        child = subprocess.Popen(command, cwd=project.root, stdin=subprocess.DEVNULL, stdout=stream,
                                 stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        if ready.is_file():
            print(f"up: Native runtime pid={child.pid}; log={log}")
            return
        if failed.is_file() or child.poll() is not None:
            reason = failed.read_text(encoding="utf-8") if failed.is_file() else f"host exited with {child.returncode}"
            raise PackageError(f"Native runtime failed to start: {reason.strip()}; see {log}")
        time.sleep(0.1)
    try:
        os.kill(child.pid, signal.SIGINT)
    except ProcessLookupError:
        pass
    raise PackageError(f"Timed out waiting for Native runtime; see {log}")


def _host(project_path: Path, *, robot_name: str | None, control_enabled: bool, registry_root: Path | None) -> None:
    project, resolution = _load(project_path, registry_root=registry_root, installed_only=True)
    _validate(project_path, registry_root)
    runtime = _runtime_dir(project)
    active, ready, failed = runtime / "active.json", runtime / "ready.json", runtime / "failed.json"
    stopping = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopping.set())
    robot = None
    try:
        name, package, manifest, instance = _manifest_and_instance(project, resolution, robot_name)
        connection = _connection_defaults(package, instance)
        lock = load_lock(project.root / "embodiment.lock")
        backend_id = lock.hardware[package.name].get("backend")
        backend = next((item for item in package.backends if item.id == backend_id), None)
        if backend is None:
            raise PackageError(f"Locked Backend {backend_id!r} is unavailable for {package.name}")
        connection["package_root"] = str(package.root)
        if backend.launch:
            launch = Path(backend.launch)
            if launch.is_absolute() or ".." in launch.parts:
                raise PackageError(f"Backend launch path must stay inside the Hardware Package: {backend.launch}")
            connection.setdefault("launch_command", ["bash", backend.launch])
        connection["require_ros"] = True
        manage_process = bool(connection.get("manage_process", bool(backend.launch)))
        connection["manage_process"] = manage_process
        adapter = "mock" if backend.type == "mock" else load_backend_entrypoint(backend, package.root)
        robot = connect(adapter, manifest, control_enabled=control_enabled, dry_run=False,
                        connection=connection, manage_process=manage_process)
        robot.lifecycle.connect()
        wait_ready = getattr(robot.adapter, "wait_ready", None)
        if wait_ready is not None and not wait_ready(float(connection.get("startup_timeout_sec", 15.0))):
            raise PackageError("Mapped backend has no fresh ready state or Action server")
        _write_json_atomic(active, {"pid": os.getpid(), "robot": name, "package": package.name, "version": package.version})
        _write_json_atomic(ready, {"pid": os.getpid(), "started_at": time.time()})
        while not stopping.wait(0.5):
            pass
    except Exception as exc:
        _write_json_atomic(failed, {"error": str(exc)})
        raise
    finally:
        if robot is not None:
            robot.lifecycle.stop()
        active.unlink(missing_ok=True)
        ready.unlink(missing_ok=True)


def _down(project_path: Path) -> None:
    project = load_project(project_path)
    active = _runtime_dir(project) / "active.json"
    if not active.is_file():
        print("down: no active runtime")
        return
    try:
        pid = int(json.loads(active.read_text(encoding="utf-8"))["pid"])
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        active.unlink(missing_ok=True)
        raise PackageError(f"Invalid active runtime state: {exc}") from exc
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        active.unlink(missing_ok=True)
        print("down: removed stale runtime state")
        return
    deadline = time.monotonic() + 10.0
    while active.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    if active.exists():
        raise PackageError(f"Runtime pid {pid} did not stop; inspect {active.parent / 'host.log'}")
    print("down: runtime stopped")


def _run_task(project_path: Path, registry_root: Path | None) -> None:
    project, _ = _load(project_path, registry_root=registry_root, installed_only=True)
    _validate(project_path, registry_root)
    entrypoint = project.task.get("entrypoint")
    if not entrypoint:
        raise PackageError("Project has no task.entrypoint")
    relative = Path(str(entrypoint))
    if relative.is_absolute() or ".." in relative.parts:
        raise PackageError(f"Task entrypoint must stay inside the project: {entrypoint}")
    task_path = (project.root / relative).resolve()
    if not task_path.is_relative_to(project.root.resolve()) or not task_path.is_file():
        raise PackageError(f"Project task entrypoint was not found: {entrypoint}")
    os.environ["CE_PROJECT_ROOT"] = str(project.root.resolve())
    runpy.run_path(str(task_path), run_name="__main__")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ce", description="Cross-Embodiment single-project runtime")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "status", "run", "down"):
        item = sub.add_parser(command)
        item.add_argument("--project", required=True, type=Path)
        item.add_argument("--registry", type=Path, help="registry root; defaults to CROSS_EMBODIMENT_REGISTRY")
    install = sub.add_parser("install")
    install.add_argument("--project", required=True, type=Path)
    install.add_argument("--lock", type=Path, help="override the generated lock-file path")
    install.add_argument("--registry", type=Path, help="registry root; defaults to CROSS_EMBODIMENT_REGISTRY")
    up = sub.add_parser("up")
    up.add_argument("--project", required=True, type=Path)
    up.add_argument("--robot")
    up.add_argument("--dry-run", action="store_true", help="never start the managed hardware backend or publish hardware commands")
    up.add_argument("--live", action="store_true", help="allow managed native startup")
    up.add_argument("--control-enabled", action="store_true")
    up.add_argument("--registry", type=Path, help="registry root; defaults to CROSS_EMBODIMENT_REGISTRY")
    host = sub.add_parser("_host", help=argparse.SUPPRESS)
    host.add_argument("--project", required=True, type=Path)
    host.add_argument("--robot")
    host.add_argument("--control-enabled", action="store_true")
    host.add_argument("--registry", type=Path)
    package = sub.add_parser("package", help="build and manage immutable Hardware Packages")
    package_commands = package.add_subparsers(dest="package_command", required=True)
    package_build = package_commands.add_parser("build")
    package_build.add_argument("--package-root", required=True, type=Path)
    package_build.add_argument("--output", required=True, type=Path)
    package_build.add_argument("--json", action="store_true")
    package_install = package_commands.add_parser("install")
    package_install.add_argument("--artifact", required=True, type=Path)
    package_install.add_argument("--store", type=Path)
    package_install.add_argument("--json", action="store_true")
    package_list = package_commands.add_parser("list")
    package_list.add_argument("--store", type=Path)
    package_list.add_argument("--json", action="store_true")
    package_inspect = package_commands.add_parser("inspect")
    package_inspect.add_argument("reference")
    package_inspect.add_argument("--store", type=Path)
    package_inspect.add_argument("--json", action="store_true")
    package_activate = package_commands.add_parser("activate")
    package_activate.add_argument("reference")
    package_activate.add_argument("--instance", required=True, type=Path)
    package_activate.add_argument("--store", type=Path)
    package_activate.add_argument("--json", action="store_true")
    package_use = package_commands.add_parser("use")
    package_use.add_argument("--instance", required=True)
    package_use.add_argument("--store", type=Path)
    package_use.add_argument("--json", action="store_true")
    package_deactivate = package_commands.add_parser("deactivate")
    package_deactivate.add_argument("--instance", required=True)
    package_deactivate.add_argument("--store", type=Path)
    package_deactivate.add_argument("--json", action="store_true")
    package_uninstall = package_commands.add_parser("uninstall")
    package_uninstall.add_argument("reference")
    package_uninstall.add_argument("--store", type=Path)
    package_uninstall.add_argument("--json", action="store_true")
    onboard = sub.add_parser("onboard", help="inspect vendor assets and generate a Hardware Package")
    phases = onboard.add_subparsers(dest="onboard_phase", required=True)
    inspect = phases.add_parser("inspect")
    inspect.add_argument("--vendor-root", type=Path, action="append", required=True)
    inspect.add_argument("--platform-root", type=Path, required=True)
    inspect.add_argument("--run-root", type=Path, required=True)
    inspect.add_argument("--denied-root", type=Path, action="append", default=[])
    inspect.add_argument("--json", action="store_true")
    assess = phases.add_parser("assess")
    assess.add_argument("--run-root", type=Path, required=True)
    assess.add_argument("--scope", type=Path, required=True)
    assess.add_argument("--candidates", type=Path, required=True)
    assess.add_argument("--json", action="store_true")
    derive = phases.add_parser("derive-candidates")
    derive.add_argument("--run-root", type=Path, required=True)
    derive.add_argument("--scope", type=Path, required=True)
    derive.add_argument("--json", action="store_true")
    generate = phases.add_parser("generate")
    generate.add_argument("--run-root", type=Path, required=True)
    generate.add_argument("--identity", type=Path, required=True)
    generate.add_argument("--json", action="store_true")
    generate_candidate = phases.add_parser("generate-candidate")
    generate_candidate.add_argument("--run-root", type=Path, required=True)
    generate_candidate.add_argument("--identity", type=Path, required=True)
    generate_candidate.add_argument("--json", action="store_true")
    for name in ("validate", "validate-candidate", "report"):
        phase = phases.add_parser(name)
        phase.add_argument("--run-root", type=Path, required=True)
        phase.add_argument("--json", action="store_true")
    agent = phases.add_parser(
        "agent",
        help="run evidence reasoning through the stateful typed-tool onboarding protocol",
    )
    agent.add_argument("--run-root", type=Path, required=True)
    agent.add_argument("--platform-root", type=Path, required=True)
    agent.add_argument("--identity", type=Path, required=True)
    agent.add_argument("--device", required=True)
    agent.add_argument("--capability", action="append", required=True)
    agent.add_argument("--joint", action="append", required=True)
    agent.add_argument("--provider", choices=("deepseek",), default="deepseek")
    agent.add_argument("--model", default="deepseek-chat")
    agent.add_argument("--thinking", action="store_true")
    agent.add_argument("--max-turns", type=int, default=32)
    agent.add_argument("--output", type=Path)
    agent.add_argument("--json", action="store_true")
    confirm_policy = phases.add_parser(
        "confirm-policy",
        help=(
            "confirm an explicit operator Runtime Completion Policy and build "
            "a runtime package without connecting to hardware"
        ),
    )
    confirm_policy.add_argument("--run-root", type=Path, required=True)
    confirm_policy.add_argument("--timeout-s", type=float, required=True)
    confirm_policy.add_argument(
        "--arrival-tolerance-rad", type=float, required=True,
    )
    confirm_policy.add_argument("--settle-window-s", type=float, required=True)
    confirm_policy.add_argument("--source", required=True)
    confirm_policy.add_argument("--operator", required=True)
    confirm_policy.add_argument("--reference", required=True)
    confirm_policy.add_argument("--confirmed-at")
    confirm_policy.add_argument("--json", action="store_true")
    preflight = phases.add_parser(
        "preflight",
        help="read state through an explicit directory or activated installed Hardware Package",
    )
    preflight_source = preflight.add_mutually_exclusive_group(required=True)
    preflight_source.add_argument("--package-root", type=Path)
    preflight_source.add_argument("--instance")
    preflight.add_argument("--store", type=Path)
    preflight.add_argument("--device", required=True)
    preflight.add_argument("--output", type=Path)
    preflight.add_argument("--json", action="store_true")
    accept_l3 = phases.add_parser(
        "accept-l3",
        help="operator-confirmed target and return through an explicit or activated package",
    )
    accept_source = accept_l3.add_mutually_exclusive_group(required=True)
    accept_source.add_argument("--package-root", type=Path)
    accept_source.add_argument("--instance")
    accept_l3.add_argument("--store", type=Path)
    accept_l3.add_argument("--device", required=True)
    accept_l3.add_argument("--target", type=Path, required=True)
    accept_l3.add_argument("--operator", required=True)
    accept_l3.add_argument("--output", type=Path)
    accept_l3.add_argument("--json", action="store_true")
    return parser


def _emit_package(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    else:
        print(yaml.safe_dump(value, sort_keys=False).rstrip())


def _package_command(args) -> int:
    from ..package.artifact import build_package_artifact
    from ..package.lifecycle import PackageLifecycle

    if args.package_command == "build":
        record = build_package_artifact(args.package_root, args.output)
        result = record.to_dict()
        result.update({"artifact": str(args.output.resolve()), "hardware_connected": False})
    else:
        lifecycle = PackageLifecycle(_package_store(args.store))
        if args.package_command == "install":
            result = lifecycle.install(args.artifact).to_dict()
            result["hardware_connected"] = False
        elif args.package_command == "list":
            result = [item.to_dict() for item in lifecycle.list()]
        elif args.package_command == "inspect":
            result = lifecycle.inspect(args.reference).to_dict()
        elif args.package_command == "activate":
            result = lifecycle.activate(args.reference, args.instance).to_dict()
            result["hardware_connected"] = False
        elif args.package_command == "use":
            result = lifecycle.resolve_use(args.instance).to_dict()
        elif args.package_command == "deactivate":
            lifecycle.deactivate(args.instance)
            result = {"deactivated": args.instance, "hardware_connected": False}
        elif args.package_command == "uninstall":
            removed = lifecycle.uninstall(args.reference)
            result = asdict(removed)
            result["hardware_connected"] = False
        else:  # pragma: no cover - argparse enforces the command set
            raise ValueError(f"Unknown package command: {args.package_command}")
    _emit_package(result, args.json)
    return 0


def _emit_onboarding(value: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, sort_keys=True))
    else:
        print(yaml.safe_dump(value, sort_keys=False).rstrip())


def _plain_onboarding_value(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _plain_onboarding_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_onboarding_value(item) for item in value]
    return value


def _write_provider_transcript(
    path: Path,
    provider,
    provider_name: str,
    model: str,
) -> None:
    document = {
        "schema_version": "onboarding-provider-transcript/v0.1",
        "provider": provider_name,
        "model": model,
        "messages": _plain_onboarding_value(provider.messages),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _onboard(args) -> int:
    if args.onboard_phase == "confirm-policy":
        from ..onboarding.workflow import OnboardingWorkflow

        result = OnboardingWorkflow(args.run_root).confirm_runtime_policy(
            timeout_s=args.timeout_s,
            arrival_tolerance_rad=args.arrival_tolerance_rad,
            settle_window_s=args.settle_window_s,
            source=args.source,
            operator=args.operator,
            reference=args.reference,
            confirmed_at=args.confirmed_at,
        )
        payload = _plain_onboarding_value(asdict(result))
        payload["phase"] = "confirm_policy"
        _emit_onboarding(payload, args.json)
        return 0 if result.conformance_passed else 14
    if args.onboard_phase == "preflight":
        from ..onboarding.l3 import (
            preflight_generated_package,
            preflight_installed_package,
        )

        if args.instance is not None:
            record = preflight_installed_package(
                _package_store(args.store), args.instance, args.device,
            )
        else:
            if args.store is not None:
                raise ValueError("--store requires --instance")
            record = preflight_generated_package(args.package_root, args.device)
        if args.output is not None:
            record.write_json(args.output)
        _emit_onboarding(record.to_dict(), args.json)
        return 0
    if args.onboard_phase == "accept-l3":
        from ..onboarding.l3 import (
            execute_generated_package_round_trip,
            execute_installed_package_round_trip,
            preflight_generated_package,
            preflight_installed_package,
        )

        target_document = yaml.safe_load(args.target.read_text(encoding="utf-8")) or {}
        positions = target_document.get("positions") if isinstance(target_document, dict) else None
        if not isinstance(positions, dict) or not positions:
            raise ValueError("L3 target file must contain a non-empty positions mapping")
        positions = {str(name): float(value) for name, value in positions.items()}
        if args.instance is not None:
            store = _package_store(args.store)
            preview = preflight_installed_package(store, args.instance, args.device)
        else:
            if args.store is not None:
                raise ValueError("--store requires --instance")
            store = None
            preview = preflight_generated_package(args.package_root, args.device)
        if preview.state_sample.get("status") != "ready":
            details = preview.state_sample.get("details") or {}
            raise ValueError(
                f"Device {args.device} is not ready "
                f"(mode={details.get('backend_mode')}, "
                f"fault_code={details.get('backend_fault_code')}); "
                "no authorization requested and no motion sent"
            )
        print("L3 acceptance preview:")
        print(yaml.safe_dump({
            "package_root": str(preview.package_root),
            "package_tree_sha256": preview.package_tree_sha256,
            "mapping_path": str(preview.mapping_path),
            "mapping_sha256": preview.mapping_sha256,
            "backend_id": preview.backend_id,
            "backend_entrypoint": preview.backend_entrypoint,
            "load_source": getattr(preview, "load_source", "explicit_package_root"),
            "instance_id": getattr(preview, "instance_id", None),
            "installed_package_digest": getattr(
                preview, "installed_package_digest", None,
            ),
            "device_id": args.device,
            "current_state": preview.state_sample,
            "probe_target": positions,
            "return_target": "fresh measured state captured immediately before the probe",
            "operations": 2,
        }, sort_keys=False).rstrip())
        confirmation = input("Type EXECUTE L3 to authorize this probe and return; anything else cancels: ")
        if confirmation.strip() != "EXECUTE L3":
            print("L3 acceptance cancelled; no motion command sent.")
            return 2
        if args.instance is not None:
            record = execute_installed_package_round_trip(
                store,
                args.instance,
                args.device,
                positions,
                operator=args.operator,
                authorized=True,
            )
        else:
            record = execute_generated_package_round_trip(
                args.package_root,
                args.device,
                positions,
                operator=args.operator,
                authorized=True,
            )
        if args.output is not None:
            record.write_json(args.output)
        _emit_onboarding(record.to_dict(), args.json)
        return 0 if record.classification == "passed" else 12

    if args.onboard_phase == "agent":
        from ..onboarding.agent import OnboardingAgent, OnboardingGoal
        from ..onboarding.providers import DeepSeekProvider
        from ..onboarding.workflow import OnboardingWorkflow

        required_capabilities = {"joint_position_state", "joint_position"}
        if (
            len(args.capability) != len(required_capabilities)
            or set(args.capability) != required_capabilities
        ):
            raise ValueError(
                "first-version onboarding requires exactly joint_position_state and joint_position"
            )
        workflow = OnboardingWorkflow(args.run_root, args.platform_root)
        provider = DeepSeekProvider(model=args.model, thinking=args.thinking)
        result = OnboardingAgent(provider, max_turns=args.max_turns).run(
            OnboardingGoal(
                device_id=args.device,
                capability_ids=tuple(args.capability),
                ordered_joints=tuple(args.joint),
                identity_path=args.identity,
            ),
            workflow,
        )

        payload = _plain_onboarding_value(asdict(result))
        payload.update({
            "phase": "agent",
            "provider": args.provider,
            "model": args.model,
            "motion_sent": False,
        })
        output = args.output or (args.run_root / "agent-run.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        transcript_path = args.run_root / "provider-transcript.json"
        _write_provider_transcript(
            transcript_path, provider, args.provider, args.model,
        )
        payload["provider_transcript"] = str(transcript_path)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _emit_onboarding(payload, args.json)
        return 0 if result.completed else 15

    from ..onboarding.workflow import AssetInsufficiency, ConformanceFailure, OnboardingWorkflow

    workflow = OnboardingWorkflow(
        args.run_root,
        getattr(args, "platform_root", None),
    )
    if args.onboard_phase == "inspect":
        result = workflow.inspect(tuple(args.vendor_root), tuple(args.denied_root))
    elif args.onboard_phase == "assess":
        coverage = workflow.assess(args.scope, args.candidates)
        complete = all(item.status in {"native", "derived"} and not item.conflicts for item in coverage.assessments)
        result = {"phase": "assess", "complete": complete, "assessments": [
            {"capability_id": item.capability_id, "status": item.status, "conflicts": list(item.conflicts)}
            for item in coverage.assessments
        ], "motion_sent": False}
        _emit_onboarding(result, args.json)
        return 0 if complete else AssetInsufficiency.exit_code
    elif args.onboard_phase == "derive-candidates":
        coverage = workflow.derive_candidates(args.scope)
        result = {
            "phase": "derive-candidates",
            "candidate_path": str(
                workflow.run_root / "deterministic-candidates.yaml"
            ),
            "assessments": [{
                "capability_id": item.capability_id,
                "status": item.status,
                "candidate_valid": item.candidate_valid,
                "interface_mapped": item.mapping_complete,
                "execution_policy_complete": item.execution_policy_complete,
                "missing_fields": [entry.field for entry in item.missing],
            } for item in coverage.assessments],
            "motion_sent": False,
        }
    elif args.onboard_phase == "generate":
        generated = workflow.generate(args.identity)
        result = {"phase": "generate", "package_root": str(generated.root), "motion_sent": False}
    elif args.onboard_phase == "generate-candidate":
        generated = workflow.generate_candidate(args.identity)
        result = {
            "phase": "generate-candidate",
            "package_root": str(generated.root),
            "package_status": generated.package_status,
            "live_execution_ready": False,
            "motion_sent": False,
        }
    elif args.onboard_phase == "validate":
        report = workflow.validate()
        result = {"phase": "validate", "passed": report.passed, "checks": list(report.checks), "failures": list(report.failures), "resolved_package_root": str(report.resolved_package_root), "resolved_mapping_path": str(report.resolved_mapping_path) if report.resolved_mapping_path else None, "motion_sent": False}
        _emit_onboarding(result, args.json)
        return 0 if report.passed else ConformanceFailure.exit_code
    elif args.onboard_phase == "validate-candidate":
        report = workflow.validate_candidate()
        result = {
            "phase": "validate-candidate",
            "passed": report.passed,
            "checks": list(report.checks),
            "failures": list(report.failures),
            "resolved_package_root": str(report.resolved_package_root),
            "resolved_mapping_path": (
                str(report.resolved_mapping_path)
                if report.resolved_mapping_path else None
            ),
            "candidate_only": True,
            "live_execution_ready": False,
            "motion_sent": False,
        }
        _emit_onboarding(result, args.json)
        return 0 if report.passed else ConformanceFailure.exit_code
    else:
        result = workflow.report()
    _emit_onboarding(result, args.json)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "package":
            return _package_command(args)
        if args.command == "onboard":
            return _onboard(args)
        if args.command == "validate":
            _validate(args.project, args.registry)
            print(f"valid: {args.project}")
        elif args.command == "install":
            print(f"installed and locked: {_install(args.project, args.lock, args.registry)}")
        elif args.command == "up":
            if args.live and not args.dry_run:
                _start_host(args.project, robot_name=args.robot, control_enabled=args.control_enabled, registry_root=args.registry)
            else:
                _up(args.project, robot_name=args.robot, dry_run=True, control_enabled=False, registry_root=args.registry)
        elif args.command == "status":
            _validate(args.project, args.registry)
            project = load_project(args.project)
            active = _runtime_dir(project) / "active.json"
            if active.is_file():
                try:
                    pid = int(json.loads(active.read_text(encoding="utf-8"))["pid"])
                    os.kill(pid, 0)
                    print(f"status: running (pid {pid})")
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    active.unlink(missing_ok=True)
                    print("status: configured (stale runtime state cleared)")
            else:
                print("status: configured (hardware startup not requested)")
        elif args.command == "run":
            _run_task(args.project, args.registry)
        elif args.command == "down":
            _down(args.project)
        elif args.command == "_host":
            _host(args.project, robot_name=args.robot, control_enabled=args.control_enabled, registry_root=args.registry)
        return 0
    except (CrossEmbodimentError, OSError, ValueError, KeyError) as exc:
        print(f"ce: error: {exc}", file=sys.stderr)
        try:
            from ..onboarding.workflow import OnboardingWorkflowError
            if isinstance(exc, OnboardingWorkflowError):
                return exc.exit_code
        except ImportError:
            pass
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
