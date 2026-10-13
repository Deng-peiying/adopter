from __future__ import annotations

import hashlib
import os
import stat
import shutil
import tempfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from ..errors import PackageError
from .manifest import load_package_manifest


class LocalRegistry:
    """Index local package artifacts and install immutable versions locally."""

    def __init__(self, root: str | Path, store_root: str | Path | None = None):
        self.root = Path(root)
        self.catalog_path = self.root / "assets" / "catalog.yaml"
        self.store_root = Path(store_root) if store_root is not None else Path.home() / ".cross_embodiment"

    def _catalog(self) -> dict[str, Any]:
        if not self.catalog_path.is_file():
            raise FileNotFoundError(self.catalog_path)
        import yaml  # type: ignore

        data = yaml.safe_load(self.catalog_path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}

    def find(self, kind: str, name: str, version: str | None = None) -> Path:
        entry = ((self._catalog().get("packages") or {}).get(kind) or {}).get(name)
        if not isinstance(entry, dict):
            raise FileNotFoundError(f"{kind}/{name}")
        if version and not _version_satisfies(str(entry.get("version", "")), version):
            raise PackageError(f"No {kind}/{name} version satisfies {version}")
        relative = Path(str(entry["path"]))
        if relative.is_absolute():
            raise PackageError(f"Registry artifact path must be relative: {relative}")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise PackageError(f"Registry artifact path escapes registry root: {relative}")
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def find_installed(self, kind: str, name: str, version: str | None = None) -> Path:
        package_parts = PurePosixPath(name)
        if package_parts.is_absolute() or any(part in ("", ".", "..") for part in package_parts.parts):
            raise PackageError(f"Invalid package name: {name}")
        package_base = self.store_root / "packages" / kind / Path(*package_parts.parts)
        candidates = []
        if package_base.is_dir():
            for manifest in package_base.glob("*/package.yaml"):
                package = load_package_manifest(manifest)
                if package.name == name and (not version or _version_satisfies(package.version, version)):
                    candidates.append(( _version_key(package.version), manifest))
        if not candidates:
            raise FileNotFoundError(f"Package {kind}/{name}@{version or '*'} is not installed in {self.store_root}")
        return max(candidates, key=lambda item: item[0])[1]

    def install(self, kind: str, name: str, version: str | None = None) -> Path:
        """Copy a catalogued package into the SDK-managed immutable store.

        The catalog currently points at a local package artifact. Network
        registries can implement the same contract by materializing an
        artifact before this method is called.
        """
        manifest_path = self.find(kind, name, version)
        package = load_package_manifest(manifest_path)
        if package.name != name:
            raise PackageError(f"Catalog requested {name}, artifact declares {package.name}")
        if version and not _version_satisfies(package.version, version):
            raise PackageError(f"Installed artifact version {package.version} does not satisfy {version}")
        package.validate_assets(require_digests=bool(package.assets))
        package_root = manifest_path.parent.resolve()
        package_parts = PurePosixPath(package.name)
        if package_parts.is_absolute() or any(part in ("", ".", "..") for part in package_parts.parts):
            raise PackageError(f"Invalid package name for installation: {package.name}")
        destination = self.store_root / "packages" / kind / Path(*package_parts.parts) / package.version
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_digest = _directory_digest(package_root)
        if destination.exists():
            if _directory_digest(destination) != source_digest:
                raise PackageError(f"Installed package is immutable and differs from catalog artifact: {destination}")
            return destination / "package.yaml"

        staging = Path(tempfile.mkdtemp(prefix=f".{package.version}-", dir=destination.parent))
        try:
            shutil.rmtree(staging)
            shutil.copytree(package_root, staging, ignore=lambda directory, names: _copy_ignored(package_root, Path(directory), names))
            installed = load_package_manifest(staging / "package.yaml")
            if installed.name != package.name or installed.version != package.version:
                raise PackageError("Copied package identity changed during installation")
            installed.validate_assets()
            if _directory_digest(staging) != source_digest:
                raise PackageError("Package artifact changed while it was being installed")
            os.replace(staging, destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return destination / "package.yaml"


def _version_satisfies(actual: str, constraint: str) -> bool:
    if not constraint or constraint in ("*", "latest"):
        return True
    actual_parts = tuple(int(part) for part in actual.split(".")[:3])
    if constraint.startswith("^"):
        wanted = tuple(int(part) for part in constraint[1:].split(".") if part)
        return actual_parts[: len(wanted)] == wanted and actual_parts >= wanted + (0,) * (3 - len(wanted))
    return actual == constraint


def _version_key(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError as exc:
        raise PackageError(f"Invalid package version: {version}") from exc


def _directory_digest(root: Path) -> str:
    digest = hashlib.sha256()
    ignored = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    def included(path: Path) -> bool:
        relative = path.relative_to(root)
        root_build_output = relative.parts[0] in {"build", "install", "log", "logs"}
        return not (any(part in ignored for part in relative.parts)
                    or root_build_output or path.suffix == ".pyc")

    entries = [path for path in root.rglob("*") if included(path)]
    symlinks = [item for item in entries if item.is_symlink()]
    if symlinks:
        raise PackageError(f"Package artifact cannot contain symlinks: {symlinks[0]}")
    for path in sorted(item for item in entries if item.is_file()):
        relative = path.relative_to(root)
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(stat.S_IMODE(path.stat().st_mode).to_bytes(2, "big"))
        digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


def _copy_ignored(package_root: Path, directory: Path, names: list[str]) -> set[str]:
    relative = directory.relative_to(package_root)
    ignored = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    result = {name for name in names if name in ignored or name.endswith(".pyc")}
    if not relative.parts:
        result.update(name for name in names if name in {"build", "install", "log", "logs"})
    return result
