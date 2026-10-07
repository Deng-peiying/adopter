from __future__ import annotations

import os
import platform as host_platform
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .assets import AssetRef
from ..errors import AssetError, DependencyError, PackageError


@dataclass(frozen=True)
class PlatformInfo:
    os: str
    arch: str
    ros_distro: str | None = None

    @classmethod
    def current(cls, ros_distro: str | None = None) -> "PlatformInfo":
        return cls(os=sys_platform(), arch=host_platform.machine(), ros_distro=ros_distro)


def sys_platform() -> str:
    return os.uname().sysname.lower() if hasattr(os, "uname") else host_platform.system().lower()


@dataclass(frozen=True)
class BackendSpec:
    id: str
    type: str
    entrypoint: str | None = None
    package: str | None = None
    launch: str | None = None
    executable: str | None = None
    platforms: tuple[dict[str, Any], ...] = ()
    requirements: dict[str, Any] = field(default_factory=dict)

    def supports(self, platform: PlatformInfo) -> bool:
        if platform.ros_distro and self.requirements.get("ros_distro") and self.requirements["ros_distro"] != platform.ros_distro:
            return False
        if not self.platforms:
            return True
        return any(
            item.get("os") in (None, platform.os)
            and item.get("arch") in (None, platform.arch)
            for item in self.platforms
        )


@dataclass
class HardwarePackage:
    name: str
    version: str
    vendor: str
    model: str
    type: str
    root: Path
    embodiment_manifest: str | None = None
    assets: dict[str, list[AssetRef]] = field(default_factory=dict)
    backends: list[BackendSpec] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)

    def resolve_asset(self, slot: str, format: str | None = None) -> AssetRef:
        variants = self.assets.get(slot, [])
        if format is not None:
            variants = [asset for asset in variants if asset.format == format]
        if not variants:
            requested = f"{slot}:{format}" if format else slot
            raise AssetError(f"No asset variant available for {requested} in {self.name}")
        return variants[0]

    def resolve_asset_path(
        self,
        slot: str,
        format: str | None = None,
        *,
        verify_digest: bool = True,
    ) -> Path:
        asset = self.resolve_asset(slot, format)
        relative = Path(asset.path)
        if relative.is_absolute():
            raise AssetError(f"Asset path must be package-relative: {asset.path}")
        root = self.root.resolve()
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root):
            raise AssetError(f"Asset path escapes package root: {asset.path}")
        if not resolved.exists():
            raise AssetError(f"Asset does not exist: {asset.path}")
        if verify_digest and asset.digest:
            expected = asset.digest.removeprefix("sha256:")
            if not asset.digest.startswith("sha256:") or len(expected) != 64:
                raise AssetError(f"Unsupported asset digest for {asset.path}: {asset.digest}")
            actual = _asset_digest(resolved)
            if actual != expected:
                raise AssetError(f"Asset digest mismatch for {asset.path}: expected sha256:{expected}, got sha256:{actual}")
        return resolved

    def validate_assets(self, *, require_digests: bool = False) -> dict[str, list[Path]]:
        validated: dict[str, list[Path]] = {}
        for slot, variants in self.assets.items():
            validated[slot] = []
            for asset in variants:
                if require_digests and not asset.digest:
                    raise AssetError(f"Asset is missing a SHA-256 digest: {asset.path}")
                validated[slot].append(self.resolve_asset_path(slot, asset.format))
        return validated

    def select_backend(self, preferred: str | None, platform: PlatformInfo) -> BackendSpec:
        candidates = self.backends
        if preferred:
            candidates = [backend for backend in candidates if backend.id == preferred]
        if not candidates:
            raise DependencyError(f"Backend '{preferred}' is not declared by {self.name}")
        compatible = [backend for backend in candidates if backend.supports(platform)]
        if not compatible:
            raise DependencyError(
                f"No backend for {self.name} supports {platform.os}/{platform.arch}"
                f" ros={platform.ros_distro or 'none'}"
            )
        return compatible[0]


def _yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise PackageError("Package YAML requires PyYAML") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PackageError(f"Package root must be a mapping: {path}")
    return data


def load_package_manifest(path: str | Path) -> HardwarePackage:
    path = Path(path)
    data = _yaml(path)
    package = data.get("package") or {}
    required = [key for key in ("name", "version", "vendor", "model", "type") if key not in package]
    if required:
        raise PackageError(f"Package missing fields: {', '.join(required)}")
    assets: dict[str, list[AssetRef]] = {}
    for slot, entries in (data.get("assets") or {}).items():
        if not isinstance(entries, list):
            raise AssetError(f"Asset slot '{slot}' must contain a list")
        assets[slot] = [
            AssetRef(
                slot=slot,
                format=str(item["format"]),
                path=str(item["path"]),
                source=bool(item.get("source", True)),
                digest=str(item["digest"]) if item.get("digest") is not None else None,
                metadata=item.get("metadata"),
            )
            for item in entries
        ]
    backends = []
    for item in data.get("backends") or []:
        if "id" not in item or "type" not in item:
            raise PackageError("Backend requires id and type")
        backends.append(
            BackendSpec(
                id=str(item["id"]),
                type=str(item["type"]),
                entrypoint=item.get("entrypoint"),
                package=item.get("package"),
                launch=item.get("launch"),
                executable=item.get("executable"),
                platforms=tuple(item.get("platforms") or ()),
                requirements=dict(item.get("requirements") or {}),
            )
        )
    return HardwarePackage(
        name=str(package["name"]),
        version=str(package["version"]),
        vendor=str(package["vendor"]),
        model=str(package["model"]),
        type=str(package["type"]),
        root=path.parent,
        embodiment_manifest=data.get("embodiment_manifest"),
        assets=assets,
        backends=backends,
        defaults=dict(data.get("defaults") or {}),
        validation=dict(data.get("validation") or {}),
    )


def _asset_digest(path: Path) -> str:
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())
    for item in files:
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
    return digest.hexdigest()
