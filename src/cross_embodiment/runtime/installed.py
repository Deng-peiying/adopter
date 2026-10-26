"""Resolve activated Hardware Packages into disconnected Robot runtimes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from ..errors import PackageError
from ..hardware.manifest import EmbodimentManifest, load_manifest
from ..package.lifecycle import PackageLifecycle
from ..package.manifest import BackendSpec, load_package_manifest

if TYPE_CHECKING:
    from ..sdk.robot_base import RobotBase


@dataclass(frozen=True)
class RuntimeInfo:
    instance_id: str
    package_name: str
    package_version: str
    package_tree_digest: str
    package_root: Path
    manifest_path: Path
    backend_id: str
    backend_entrypoint: str
    mapping_path: Path | None
    mapping_sha256: str | None
    allow_motion: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for name in ("package_root", "manifest_path", "mapping_path"):
            path = value[name]
            value[name] = str(path) if path is not None else None
        return value


@dataclass(frozen=True)
class ResolvedInstalledRuntime:
    package_root: Path
    manifest: EmbodimentManifest
    backend: BackendSpec
    connection: dict[str, Any]
    info: RuntimeInfo

    def create_robot(
        self,
        *,
        allow_motion: bool = False,
        connect_fn: Callable[..., RobotBase] | None = None,
        robot_class: type[RobotBase] | None = None,
    ) -> RobotBase:
        if connect_fn is None:
            from ..sdk.factory import connect as connect_fn

        runtime_connection = dict(self.connection)
        runtime_connection["package_root"] = str(self.package_root)
        robot = connect_fn(
            _load_backend(self.backend, self.package_root),
            self.manifest,
            control_enabled=allow_motion,
            dry_run=False,
            connection=runtime_connection,
            manage_process=bool(runtime_connection.get("manage_process", False)),
            robot_class=robot_class,
        )
        robot.runtime_info = replace(self.info, allow_motion=allow_motion)
        return robot


def _load_backend(backend: BackendSpec, package_root: Path) -> Any:
    from ..package.loader import load_backend_entrypoint

    return load_backend_entrypoint(backend, package_root)


def _store_root(store: str | Path | None) -> Path:
    if store is not None:
        return Path(store).expanduser().resolve()
    configured = os.environ.get("CROSS_EMBODIMENT_STORE")
    return Path(configured).expanduser().resolve() if configured else (
        Path.home() / ".cross_embodiment"
    ).resolve()


def _mapping_provenance(
    package: Any,
    root: Path,
    connection: dict[str, Any],
) -> tuple[Path | None, str | None]:
    value = connection.get("mapping_path")
    if value is None:
        return None, None
    relative = Path(str(value))
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise PackageError("activated mapping path must stay inside the installed package")
    mapping_path = (root / relative).resolve()
    if not mapping_path.is_relative_to(root):
        raise PackageError("activated mapping path must stay inside the installed package")
    try:
        declared = package.resolve_asset_path("interface_mapping", "yaml").resolve()
    except Exception as exc:
        raise PackageError("activated mapping path has no declared Mapping asset") from exc
    if mapping_path != declared:
        raise PackageError("activated mapping path differs from the declared Mapping asset")
    return mapping_path, sha256(mapping_path.read_bytes()).hexdigest()


def resolve_installed_runtime(
    instance_id: str,
    store: str | Path | None = None,
) -> ResolvedInstalledRuntime:
    use = PackageLifecycle(_store_root(store)).resolve_use(instance_id)
    root = use.package_root.resolve()
    package = load_package_manifest(root / "package.yaml")
    if package.root.resolve() != root:
        raise PackageError("activated package root differs from the verified SDK Store root")
    package.validate_assets(require_digests=bool(package.assets))

    manifest_path = use.manifest_path.resolve()
    declared_manifest = (root / str(package.embodiment_manifest)).resolve()
    if manifest_path != declared_manifest or not manifest_path.is_relative_to(root):
        raise PackageError("activated embodiment manifest differs from the installed package")
    manifest = load_manifest(manifest_path)

    backend = next((item for item in package.backends if item.id == use.backend_id), None)
    if backend is None or backend.entrypoint != use.backend_entrypoint:
        raise PackageError("activated Backend differs from the installed package selection")
    if not backend.entrypoint:
        raise PackageError(f"activated Backend has no entrypoint: {backend.id}")

    connection = dict(use.connection)
    if Path(str(connection.get("package_root", ""))).resolve() != root:
        raise PackageError("activated connection does not reference the installed package root")
    mapping_path, mapping_digest = _mapping_provenance(package, root, connection)
    info = RuntimeInfo(
        instance_id=instance_id,
        package_name=use.package_name,
        package_version=use.version,
        package_tree_digest=use.package_tree_digest,
        package_root=root,
        manifest_path=manifest_path,
        backend_id=backend.id,
        backend_entrypoint=backend.entrypoint,
        mapping_path=mapping_path,
        mapping_sha256=mapping_digest,
    )
    return ResolvedInstalledRuntime(root, manifest, backend, connection, info)


def create_robot_from_instance(
    instance_id: str,
    *,
    store: str | Path | None = None,
    allow_motion: bool = False,
    connect_fn: Callable[..., RobotBase] | None = None,
    robot_class: type[RobotBase] | None = None,
) -> RobotBase:
    return resolve_installed_runtime(instance_id, store).create_robot(
        allow_motion=allow_motion,
        connect_fn=connect_fn,
        robot_class=robot_class,
    )


__all__ = [
    "ResolvedInstalledRuntime",
    "RuntimeInfo",
    "create_robot_from_instance",
    "resolve_installed_runtime",
]
