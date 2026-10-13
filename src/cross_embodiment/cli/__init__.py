from __future__ import annotations

import argparse
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
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
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
