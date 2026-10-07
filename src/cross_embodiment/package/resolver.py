from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..hardware.instance import load_robot_instance
from .lock import EmbodimentLock
from .manifest import BackendSpec, HardwarePackage, PlatformInfo, _asset_digest, load_package_manifest
from .project import ProjectSpec
from .registry import LocalRegistry, _directory_digest


@dataclass
class Resolution:
    hardware: dict[str, HardwarePackage] = field(default_factory=dict)
    instances: dict[str, object] = field(default_factory=dict)
    selected_backends: dict[str, BackendSpec] = field(default_factory=dict)

    def to_lock(self) -> EmbodimentLock:
        hardware = {}
        for name, package in sorted(self.hardware.items()):
            package_path = package.root / "package.yaml"
            backend = self.selected_backends.get(name)
            assets = {}
            for slot, variants in sorted(package.assets.items()):
                assets[slot] = []
                for asset in variants:
                    asset_path = package.resolve_asset_path(slot, asset.format)
                    assets[slot].append({
                        "format": asset.format,
                        "path": asset.path,
                        "digest": f"sha256:{_asset_digest(asset_path)}",
                        "source": asset.source,
                    })
            hardware[name] = {
                "version": package.version,
                "digest": _directory_digest(package.root),
                "manifest": package_path.name,
                "backend": backend.id if backend else None,
                "assets": assets,
            }
        return EmbodimentLock(lock_version="v0.1", hardware=hardware)

    def write_lock(self, path: str | Path) -> EmbodimentLock:
        lock = self.to_lock()
        import yaml  # type: ignore

        Path(path).write_text(yaml.safe_dump({"lock_version": lock.lock_version, "hardware": lock.hardware}, sort_keys=True), encoding="utf-8")
        return lock


class PackageResolver:
    def __init__(self, registry: LocalRegistry, platform: PlatformInfo | None = None):
        self.registry = registry
        self.platform = platform or PlatformInfo.current(os.environ.get("ROS_DISTRO"))

    def resolve(
        self,
        project: ProjectSpec,
        *,
        install: bool = False,
        installed_only: bool = False,
    ) -> Resolution:
        if install and installed_only:
            raise ValueError("resolve cannot install and require an installed package at once")
        resolution = Resolution()
        for instance_name, spec in project.robots.items():
            package_name = spec["package"]
            version = spec.get("version")
            if install:
                package_path = self.registry.install("hardware", package_name, version)
            elif installed_only:
                package_path = self.registry.find_installed("hardware", package_name, version)
            else:
                package_path = self.registry.find("hardware", package_name, version)
            package = load_package_manifest(package_path)
            resolution.hardware[package_name] = package
            instance = None
            if spec.get("instance"):
                relative_instance = Path(str(spec["instance"]))
                if relative_instance.is_absolute():
                    raise ValueError(f"Robot Instance path must be project-relative: {relative_instance}")
                instance_path = (project.root / relative_instance).resolve()
                if not instance_path.is_relative_to(project.root.resolve()):
                    raise ValueError(f"Robot Instance path escapes project root: {relative_instance}")
                instance = load_robot_instance(instance_path)
                resolution.instances[instance_name] = instance
            preferred = (
                getattr(instance, "backend_preferred", None)
                or spec.get("backend")
                or package.defaults.get("backend")
            )
            if preferred:
                resolution.selected_backends[package_name] = package.select_backend(str(preferred), self.platform)
        return resolution
