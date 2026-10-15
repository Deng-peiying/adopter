from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import zipfile
from typing import Any

from ..errors import PackageError
from .manifest import load_package_manifest
from .registry import _directory_digest


ARTIFACT_SCHEMA = "hardware-package-artifact/v0.1"
_IGNORED = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_ROOT_OUTPUTS = {"build", "install", "log", "logs"}


@dataclass(frozen=True)
class ArtifactRecord:
    schema_version: str
    package_name: str
    package_version: str
    package_tree_digest: str
    backends: tuple[dict[str, Any], ...]
    external_requirements: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "package": {
                "name": self.package_name,
                "version": self.package_version,
                "tree_digest": self.package_tree_digest,
            },
            "backends": [dict(item) for item in self.backends],
            "external_requirements": self.external_requirements,
            "format": "zip",
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ArtifactRecord":
        if value.get("schema_version") != ARTIFACT_SCHEMA:
            raise PackageError("Unsupported Hardware Package artifact schema")
        package = value.get("package")
        if not isinstance(package, dict):
            raise PackageError("Artifact metadata requires package identity")
        name = package.get("name")
        version = package.get("version")
        digest = package.get("tree_digest")
        if not all(isinstance(item, str) and item for item in (name, version, digest)):
            raise PackageError("Artifact metadata has invalid package identity or digest")
        if not str(digest).startswith("sha256:") or len(str(digest)) != 71:
            raise PackageError("Artifact metadata has invalid tree digest")
        backends = value.get("backends") or []
        requirements = value.get("external_requirements") or {}
        if not isinstance(backends, list) or not all(isinstance(item, dict) for item in backends):
            raise PackageError("Artifact backends must be a list of mappings")
        if not isinstance(requirements, dict) or not all(
            isinstance(key, str) and isinstance(item, dict)
            for key, item in requirements.items()
        ):
            raise PackageError("Artifact external requirements must be a mapping")
        return cls(
            schema_version=ARTIFACT_SCHEMA,
            package_name=str(name),
            package_version=str(version),
            package_tree_digest=str(digest),
            backends=tuple(dict(item) for item in backends),
            external_requirements={str(key): dict(item) for key, item in requirements.items()},
        )


def _files(root: Path) -> list[Path]:
    root = root.resolve()
    entries = list(root.rglob("*"))
    for item in entries:
        if item.is_symlink():
            raise PackageError(f"Package artifact cannot contain symlink: {item}")

    def included(path: Path) -> bool:
        relative = path.relative_to(root)
        return not (
            any(part in _IGNORED for part in relative.parts)
            or (relative.parts and relative.parts[0] in _ROOT_OUTPUTS)
            or path.suffix == ".pyc"
        )

    return sorted(
        (item for item in entries if item.is_file() and included(item)),
        key=lambda item: item.relative_to(root).as_posix(),
    )


def _zip_info(name: str, mode: int = 0o644) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    return info


def build_package_artifact(package_root: Path, output: Path) -> ArtifactRecord:
    root = package_root.resolve()
    manifest = root / "package.yaml"
    if not manifest.is_file():
        raise PackageError(f"Hardware Package manifest not found: {manifest}")
    package = load_package_manifest(manifest)
    package.validate_assets(require_digests=bool(package.assets))
    files = _files(root)
    tree_digest = _directory_digest(root)
    backends = tuple(
        {
            "id": backend.id,
            "type": backend.type,
            "entrypoint": backend.entrypoint,
            "requirements": dict(backend.requirements),
        }
        for backend in package.backends
    )
    record = ArtifactRecord(
        schema_version=ARTIFACT_SCHEMA,
        package_name=package.name,
        package_version=package.version,
        package_tree_digest=tree_digest,
        backends=backends,
        external_requirements={backend.id: dict(backend.requirements) for backend in package.backends},
    )
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}-", dir=output.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            metadata = json.dumps(
                record.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            archive.writestr(_zip_info("artifact.json"), metadata)
            for path in files:
                relative = path.relative_to(root).as_posix()
                mode = stat.S_IMODE(path.stat().st_mode)
                archive.writestr(_zip_info(f"package/{relative}", mode), path.read_bytes())
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return record


def _members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    seen: set[str] = set()
    members = archive.infolist()
    for member in members:
        path = PurePosixPath(member.filename)
        if (
            path.is_absolute()
            or any(part in ("", ".", "..") for part in path.parts)
            or member.filename in seen
            or not (member.filename == "artifact.json" or member.filename.startswith("package/"))
        ):
            raise PackageError(f"unsafe archive path: {member.filename}")
        seen.add(member.filename)
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise PackageError(f"Package artifact cannot contain symlink: {member.filename}")
        if member.is_dir():
            raise PackageError(f"Package artifact contains unexpected directory entry: {member.filename}")
    if "artifact.json" not in seen or "package/package.yaml" not in seen:
        raise PackageError("Package artifact is missing metadata or package manifest")
    return members


def inspect_package_artifact(path: Path) -> ArtifactRecord:
    try:
        with zipfile.ZipFile(path) as archive:
            _members(archive)
            value = json.loads(archive.read("artifact.json"))
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError) as exc:
        raise PackageError(f"Invalid Hardware Package artifact: {exc}") from exc
    if not isinstance(value, dict):
        raise PackageError("Artifact metadata must be an object")
    return ArtifactRecord.from_dict(value)


def extract_package_artifact(path: Path, destination: Path) -> ArtifactRecord:
    record = inspect_package_artifact(path)
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise PackageError(f"Artifact destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(path) as archive:
            members = _members(archive)
            for member in members:
                if not member.filename.startswith("package/"):
                    continue
                relative = PurePosixPath(member.filename).relative_to("package")
                target = destination.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member.filename))
                mode = stat.S_IMODE(member.external_attr >> 16)
                target.chmod(mode or 0o644)
        package = load_package_manifest(destination / "package.yaml")
        package.validate_assets(require_digests=bool(package.assets))
        if package.name != record.package_name or package.version != record.package_version:
            raise PackageError("Artifact package identity does not match metadata")
        actual = _directory_digest(destination)
        if actual != record.package_tree_digest:
            raise PackageError(
                f"Artifact package tree digest mismatch: expected {record.package_tree_digest}, got {actual}"
            )
    except Exception:
        import shutil

        shutil.rmtree(destination, ignore_errors=True)
        raise
    return record
