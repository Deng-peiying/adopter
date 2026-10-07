from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import PackageError
from ..hardware.instance import RobotInstance
from .manifest import HardwarePackage


@dataclass
class EmbodimentLock:
    lock_version: str
    hardware: dict[str, dict[str, Any]] = field(default_factory=dict)
    policy: dict[str, dict[str, Any]] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)

    def verify(self, package: HardwarePackage, instance: RobotInstance) -> None:
        from .manifest import _asset_digest
        from .registry import _directory_digest

        entry = self.hardware.get(package.name)
        if entry is None:
            raise PackageError(f"Lock has no entry for {package.name}")
        if str(entry.get("version")) != package.version or instance.version != package.version:
            raise PackageError(f"Locked version does not match {package.name}@{package.version}")
        expected_package_digest = entry.get("digest")
        if expected_package_digest and expected_package_digest != _directory_digest(package.root):
            raise PackageError(f"Locked package digest does not match {package.name}@{package.version}")
        locked_assets = entry.get("assets") or {}
        for slot, variants in package.assets.items():
            locked_variants = locked_assets.get(slot) or []
            for asset in variants:
                locked = next((item for item in locked_variants if item.get("format") == asset.format and item.get("path") == asset.path), None)
                if locked is None:
                    raise PackageError(f"Lock is missing asset {slot}:{asset.format} ({asset.path})")
                asset_path = package.resolve_asset_path(slot, asset.format)
                actual = f"sha256:{_asset_digest(asset_path)}"
                if locked.get("digest") != actual:
                    raise PackageError(f"Locked asset digest does not match {asset.path}")


def load_lock(path: str | Path) -> EmbodimentLock:
    path = Path(path)
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise PackageError("Lock YAML requires PyYAML") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("lock_version"):
        raise PackageError("Lock requires lock_version")
    return EmbodimentLock(
        lock_version=str(data["lock_version"]),
        hardware=dict(data.get("hardware") or {}),
        policy=dict(data.get("policy") or {}),
        runtime=dict(data.get("runtime") or {}),
    )
