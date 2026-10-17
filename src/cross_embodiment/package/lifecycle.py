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
from ..hardware.instance import load_robot_instance
from .manifest import PlatformInfo
from .artifact import extract_package_artifact, inspect_package_artifact
from .manifest import load_package_manifest
from .registry import _directory_digest


RECORD_SCHEMA = "installed-hardware-package/v0.1"
ACTIVATION_SCHEMA = "hardware-package-activation/v0.1"


def _package_parts(name: str) -> tuple[str, ...]:
    value = PurePosixPath(name)
    if value.is_absolute() or not value.parts or any(
        part in ("", ".", "..") for part in value.parts
    ):
        raise PackageError(f"Invalid Hardware Package name: {name}")
    return value.parts


def _instance_parts(instance_id: str) -> tuple[str, ...]:
    value = PurePosixPath(instance_id)
    if value.is_absolute() or not value.parts or any(
        part in ("", ".", "..") for part in value.parts
    ):
        raise PackageError(f"Invalid Robot Instance id: {instance_id}")
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


@dataclass(frozen=True)
class ActivationRecord:
    schema_version: str
    instance_id: str
    package_name: str
    version: str
    package_tree_digest: str
    backend_id: str
    instance_path: str
    activated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "instance_id": self.instance_id,
            "package": {
                "name": self.package_name,
                "version": self.version,
                "tree_digest": self.package_tree_digest,
            },
            "backend_id": self.backend_id,
            "instance_path": self.instance_path,
            "activated_at": self.activated_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActivationRecord":
        package = value.get("package") or {}
        if value.get("schema_version") != ACTIVATION_SCHEMA or not isinstance(package, dict):
            raise PackageError("Invalid Hardware Package activation record")
        try:
            return cls(
                schema_version=ACTIVATION_SCHEMA,
                instance_id=str(value["instance_id"]),
                package_name=str(package["name"]),
                version=str(package["version"]),
                package_tree_digest=str(package["tree_digest"]),
                backend_id=str(value["backend_id"]),
                instance_path=str(value["instance_path"]),
                activated_at=str(value["activated_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PackageError(f"Invalid Hardware Package activation record: {exc}") from exc


@dataclass(frozen=True)
class PackageUse:
    instance_id: str
    package_name: str
    version: str
    package_tree_digest: str
    package_root: Path
    manifest_path: Path
    backend_id: str
    backend_entrypoint: str | None
    connection: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "package": {
                "name": self.package_name,
                "version": self.version,
                "tree_digest": self.package_tree_digest,
                "root": str(self.package_root),
            },
            "manifest_path": str(self.manifest_path),
            "backend_id": self.backend_id,
            "backend_entrypoint": self.backend_entrypoint,
            "connection": self.connection,
            "hardware_connected": False,
        }


@dataclass(frozen=True)
class UninstallResult:
    package_name: str
    version: str
    package_tree_digest: str


class PackageLifecycle:
    def __init__(self, store_root: str | Path):
        self.store_root = Path(store_root).resolve()

    def _package_root(self, name: str, version: str) -> Path:
        return self.store_root / "packages" / "hardware" / Path(*_package_parts(name)) / version

    def _record_path(self, name: str, version: str) -> Path:
        return self.store_root / "records" / "hardware" / Path(*_package_parts(name)) / f"{version}.json"

    def _activation_root(self, instance_id: str) -> Path:
        return self.store_root / "activations" / Path(*_instance_parts(instance_id))

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

    def activate(self, reference: str, instance_path: Path) -> ActivationRecord:
        installed = self.inspect(reference)
        source = instance_path.resolve()
        instance = load_robot_instance(source)
        if instance.package != installed.package_name or instance.version != installed.version:
            raise PackageError(
                f"Robot Instance {instance.instance_id} does not match "
                f"{installed.package_name}@{installed.version}"
            )
        package = load_package_manifest(Path(installed.package_root) / "package.yaml")
        preferred = instance.backend_preferred or package.defaults.get("backend")
        backend = package.select_backend(
            str(preferred) if preferred else None,
            PlatformInfo.current(os.environ.get("ROS_DISTRO")),
        )
        activation_root = self._activation_root(instance.instance_id)
        activation_root.mkdir(parents=True, exist_ok=True)
        stored_instance = activation_root / "instance.yaml"
        fd, temporary_name = tempfile.mkstemp(prefix=".instance-", dir=activation_root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(source.read_bytes())
            os.replace(temporary_name, stored_instance)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise
        record = ActivationRecord(
            schema_version=ACTIVATION_SCHEMA,
            instance_id=instance.instance_id,
            package_name=installed.package_name,
            version=installed.version,
            package_tree_digest=installed.package_tree_digest,
            backend_id=backend.id,
            instance_path=str(stored_instance),
            activated_at=datetime.now(timezone.utc).isoformat(),
        )
        _atomic_json(activation_root / "activation.json", record.to_dict())
        return record

    def _activation(self, instance_id: str) -> ActivationRecord:
        path = self._activation_root(instance_id) / "activation.json"
        if not path.is_file():
            raise FileNotFoundError(f"Robot Instance is not activated: {instance_id}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise PackageError(f"Invalid activation record: {path}")
        record = ActivationRecord.from_dict(value)
        if record.instance_id != instance_id:
            raise PackageError(f"Activation identity mismatch: {path}")
        instance_path = Path(record.instance_path).resolve()
        if not instance_path.is_relative_to(self._activation_root(instance_id).resolve()):
            raise PackageError("Activation instance path escapes the SDK store")
        return record

    def resolve_use(self, instance_id: str) -> PackageUse:
        activation = self._activation(instance_id)
        installed = self.inspect(f"{activation.package_name}@{activation.version}")
        if installed.package_tree_digest != activation.package_tree_digest:
            raise PackageError("Activated package digest differs from installed package")
        package = load_package_manifest(Path(installed.package_root) / "package.yaml")
        instance = load_robot_instance(activation.instance_path)
        if instance.package != package.name or instance.version != package.version:
            raise PackageError("Activated Robot Instance no longer matches its package")
        backend = next(
            (item for item in package.backends if item.id == activation.backend_id), None,
        )
        if backend is None:
            raise PackageError(f"Activated Backend is no longer declared: {activation.backend_id}")
        if not package.embodiment_manifest:
            raise PackageError(f"Package {package.name} has no embodiment manifest")
        manifest_path = (package.root / package.embodiment_manifest).resolve()
        if not manifest_path.is_relative_to(package.root.resolve()) or not manifest_path.is_file():
            raise PackageError("Package embodiment manifest is missing or outside the package")
        connection: dict[str, Any] = {}
        config = package.defaults.get("config")
        if config:
            relative = Path(str(config))
            if relative.is_absolute() or ".." in relative.parts:
                raise PackageError("Package default config must stay inside the package")
            config_path = (package.root / relative).resolve()
            if not config_path.is_relative_to(package.root.resolve()) or not config_path.is_file():
                raise PackageError(f"Package default config was not found: {config}")
            import yaml  # type: ignore

            value = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            if not isinstance(value, dict):
                raise PackageError("Package default config must be a mapping")
            connection.update(value)
        connection.update(instance.connection)
        connection["package_root"] = str(package.root)
        return PackageUse(
            instance_id=instance_id,
            package_name=package.name,
            version=package.version,
            package_tree_digest=installed.package_tree_digest,
            package_root=package.root,
            manifest_path=manifest_path,
            backend_id=backend.id,
            backend_entrypoint=backend.entrypoint,
            connection=connection,
        )

    def deactivate(self, instance_id: str) -> None:
        root = self._activation_root(instance_id)
        if not root.exists():
            raise FileNotFoundError(f"Robot Instance is not activated: {instance_id}")
        if not root.is_relative_to((self.store_root / "activations").resolve()):
            raise PackageError("Activation path escapes the SDK store")
        shutil.rmtree(root)
        self._prune_empty(root.parent, self.store_root / "activations")

    def uninstall(self, reference: str) -> UninstallResult:
        name, version = _reference(reference)
        installed = self.inspect(reference)
        activations = self.store_root / "activations"
        if activations.is_dir():
            for path in activations.rglob("activation.json"):
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    active = ActivationRecord.from_dict(value)
                    if active.package_name == name and active.version == version:
                        raise PackageError(
                            f"Hardware Package {reference} is active for {active.instance_id}"
                        )
        package_root = self._package_root(name, version).resolve()
        record_path = self._record_path(name, version).resolve()
        if not package_root.is_relative_to(self.store_root) or not record_path.is_relative_to(self.store_root):
            raise PackageError("Uninstall target escapes the SDK store")
        shutil.rmtree(package_root)
        record_path.unlink()
        self._prune_empty(package_root.parent, self.store_root / "packages" / "hardware")
        self._prune_empty(record_path.parent, self.store_root / "records" / "hardware")
        return UninstallResult(name, version, installed.package_tree_digest)

    @staticmethod
    def _prune_empty(path: Path, boundary: Path) -> None:
        boundary = boundary.resolve()
        current = path.resolve()
        while current != boundary and current.is_relative_to(boundary):
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
