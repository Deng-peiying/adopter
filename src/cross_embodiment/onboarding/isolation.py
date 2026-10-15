from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import platform
from pathlib import Path
import subprocess
import sys
from typing import Sequence

import yaml


def _inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


@dataclass(frozen=True)
class IsolationPolicy:
    vendor_roots: tuple[Path, ...]
    platform_roots: tuple[Path, ...]
    output_root: Path
    denied_roots: tuple[Path, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "vendor_roots", tuple(p.resolve() for p in self.vendor_roots))
        object.__setattr__(self, "platform_roots", tuple(p.resolve() for p in self.platform_roots))
        object.__setattr__(self, "output_root", self.output_root.resolve())
        object.__setattr__(self, "denied_roots", tuple(p.resolve() for p in self.denied_roots))

    def authorize_read(self, path: Path) -> Path:
        resolved = path.resolve()
        if any(_inside(resolved, root) for root in self.denied_roots):
            raise PermissionError(f"read path is under a denied root: {path}")
        allowed = self.vendor_roots + self.platform_roots
        if not any(_inside(resolved, root) for root in allowed):
            raise PermissionError(f"read path is outside allowed roots: {path}")
        return resolved

    def authorize_write(self, path: Path) -> Path:
        resolved = path.resolve()
        if not _inside(resolved, self.output_root):
            raise PermissionError(f"write path is outside staging output: {path}")
        return resolved

    def validate_generated_tree(self) -> None:
        for path in self.output_root.rglob("*"):
            if path.is_symlink():
                raise PermissionError(f"generated tree contains symlink: {path}")
            self.authorize_write(path)


@dataclass(frozen=True)
class PlatformLock:
    schema_version: str
    sdk_commit: str
    asset_digests: dict[str, str]
    python_version: str
    os_name: str
    architecture: str

    @classmethod
    def capture(cls, repo_root: Path, schema_paths: Sequence[Path]) -> "PlatformLock":
        root = repo_root.resolve()
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        digests: dict[str, str] = {}
        for path in sorted((item.resolve() for item in schema_paths), key=str):
            if not _inside(path, root):
                raise ValueError(f"platform asset is outside repository: {path}")
            digests[str(path.relative_to(root))] = sha256(path.read_bytes()).hexdigest()
        return cls(
            schema_version="platform-lock/v0.1",
            sdk_commit=commit,
            asset_digests=digests,
            python_version=platform.python_version(),
            os_name=platform.platform(),
            architecture=platform.machine(),
        )

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(asdict(self), sort_keys=False), encoding="utf-8")
