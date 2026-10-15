from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Any

from ..errors import PackageError
from .artifact import extract_package_artifact, inspect_package_artifact
from .manifest import load_package_manifest
from .registry import _directory_digest


RECORD_SCHEMA = "installed-hardware-package/v0.1"


def _package_parts(name: str) -> tuple[str, ...]:
    value = PurePosixPath(name)
    if value.is_absolute() or len(value.parts) < 2 or any(
        part in ("", ".", "..") for part in value.parts
    ):
        raise PackageError(f"Invalid Hardware Package name: {name}")
    return value.parts


def _reference(value: str) -> tuple[str, str]:
    if "@" not in value:
        raise PackageError("Package reference must use NAME@VERSION")
    name, version = value.rsplit("@", 1)
    _package_parts(name)
    if not version or "/" in version or version in (".", ".."):
        raise PackageError(f"Invalid Hardware Package version: {version}")
    return name, version


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


@dataclass(frozen=True)
class InstalledPackageRecord:
    schema_version: str
    package_name: str
    version: str
    package_tree_digest: str
    artifact_digest: str
    package_root: str
    backends: tuple[dict[str, Any], ...]
    external_requirements: dict[str, dict[str, Any]]
    validation: dict[str, Any]
    installed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "package": {
                "name": self.package_name,
                "version": self.version,
                "tree_digest": self.package_tree_digest,
                "root": self.package_root,
            },
            "artifact_digest": self.artifact_digest,
            "backends": [dict(item) for item in self.backends],
            "external_requirements": self.external_requirements,
            "validation": self.validation,
            "installed_at": self.installed_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "InstalledPackageRecord":
        package = value.get("package") or {}
        if value.get("schema_version") != RECORD_SCHEMA or not isinstance(package, dict):
            raise PackageError("Invalid installed Hardware Package record")
        try:
            return cls(
                schema_version=RECORD_SCHEMA,
                package_name=str(package["name"]),
                version=str(package["version"]),
                package_tree_digest=str(package["tree_digest"]),
                artifact_digest=str(value["artifact_digest"]),
                package_root=str(package["root"]),
                backends=tuple(dict(item) for item in value.get("backends") or []),
                external_requirements={
                    str(key): dict(item)
                    for key, item in (value.get("external_requirements") or {}).items()
                },
                validation=dict(value.get("validation") or {}),
                installed_at=str(value["installed_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PackageError(f"Invalid installed Hardware Package record: {exc}") from exc


class PackageLifecycle:
    def __init__(self, store_root: str | Path):
        self.store_root = Path(store_root).resolve()

    def _package_root(self, name: str, version: str) -> Path:
        return self.store_root / "packages" / "hardware" / Path(*_package_parts(name)) / version

    def _record_path(self, name: str, version: str) -> Path:
        return self.store_root / "records" / "hardware" / Path(*_package_parts(name)) / f"{version}.json"

    def _read_record(self, name: str, version: str) -> InstalledPackageRecord:
        path = self._record_path(name, version)
        if not path.is_file():
            raise FileNotFoundError(f"Hardware Package {name}@{version} is not installed")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PackageError(f"Invalid install record {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise PackageError(f"Invalid install record: {path}")
        record = InstalledPackageRecord.from_dict(value)
        if record.package_name != name or record.version != version:
            raise PackageError(f"Install record identity mismatch: {path}")
        return record

    def _verified(self, record: InstalledPackageRecord) -> InstalledPackageRecord:
        expected_root = self._package_root(record.package_name, record.version).resolve()
        actual_root = Path(record.package_root).resolve()
        if actual_root != expected_root or not actual_root.is_relative_to(self.store_root):
            raise PackageError("Installed package record points outside its immutable store location")
        manifest = actual_root / "package.yaml"
        if not manifest.is_file():
            raise PackageError(f"Installed Hardware Package is missing: {manifest}")
        package = load_package_manifest(manifest)
        if package.name != record.package_name or package.version != record.version:
            raise PackageError("Installed package identity differs from its record")
        actual_digest = _directory_digest(actual_root)
        if actual_digest != record.package_tree_digest:
            raise PackageError(
                f"Installed package digest mismatch: expected {record.package_tree_digest}, got {actual_digest}"
            )
        package.validate_assets(require_digests=bool(package.assets))
        return record

    def install(self, artifact: Path) -> InstalledPackageRecord:
        artifact = artifact.resolve()
        metadata = inspect_package_artifact(artifact)
        destination = self._package_root(metadata.package_name, metadata.package_version)
        record_path = self._record_path(metadata.package_name, metadata.package_version)
        artifact_digest = f"sha256:{hashlib.sha256(artifact.read_bytes()).hexdigest()}"
        if destination.exists():
            if not record_path.is_file():
                raise PackageError(f"Installed package has no audit record: {destination}")
            installed = self._read_record(metadata.package_name, metadata.package_version)
            if installed.package_tree_digest != metadata.package_tree_digest:
                raise PackageError(
                    f"Installed package is immutable and differs from artifact: {destination}"
                )
            return self._verified(installed)

        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{metadata.package_version}-", dir=destination.parent))
        try:
            shutil.rmtree(staging)
            extract_package_artifact(artifact, staging)
            if _directory_digest(staging) != metadata.package_tree_digest:
                raise PackageError("Extracted package digest differs from artifact metadata")
            os.replace(staging, destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        package = load_package_manifest(destination / "package.yaml")
        record = InstalledPackageRecord(
            schema_version=RECORD_SCHEMA,
            package_name=package.name,
            version=package.version,
            package_tree_digest=metadata.package_tree_digest,
            artifact_digest=artifact_digest,
            package_root=str(destination),
            backends=metadata.backends,
            external_requirements=metadata.external_requirements,
            validation=dict(package.validation),
            installed_at=datetime.now(timezone.utc).isoformat(),
        )
        try:
            _atomic_json(record_path, record.to_dict())
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        return self._verified(record)

    def list(self) -> tuple[InstalledPackageRecord, ...]:
        root = self.store_root / "records" / "hardware"
        if not root.is_dir():
            return ()
        records = []
        for path in root.rglob("*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise PackageError(f"Invalid install record: {path}")
            records.append(self._verified(InstalledPackageRecord.from_dict(value)))
        return tuple(sorted(records, key=lambda item: (item.package_name, item.version)))

    def inspect(self, reference: str) -> InstalledPackageRecord:
        name, version = _reference(reference)
        return self._verified(self._read_record(name, version))
