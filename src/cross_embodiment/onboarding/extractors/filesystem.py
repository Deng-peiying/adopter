from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path

from ..models import AssetRecord
from .base import ScanContext


_BINARY_SUFFIXES = {".so", ".a", ".o", ".bin", ".elf", ".exe"}
_SOURCE_SUFFIXES = {
    ".py", ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp",
    ".xml", ".yaml", ".yml", ".json", ".msg", ".srv", ".action",
    ".urdf", ".xacro", ".launch", ".cmake", ".md", ".txt",
}


def classify_asset(path: Path) -> str:
    name = path.name.lower()
    if path.suffix.lower() in _BINARY_SUFFIXES or ".so." in name:
        return "binary"
    if "build" in path.parts or "install" in path.parts:
        return "generated"
    if path.suffix.lower() in _SOURCE_SUFFIXES or name in {"package.xml", "cmakelists.txt"}:
        return "source"
    return "data"


class FilesystemExtractor:
    def scan(self, context: ScanContext) -> list[AssetRecord]:
        assets: list[AssetRecord] = []
        for directory, dirnames, filenames in os.walk(context.root, followlinks=False):
            current = Path(directory)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in context.ignored_components
                and not (current / name).is_symlink()
            )
            for name in sorted(filenames):
                path = current / name
                relative = path.relative_to(context.root)
                if any(part in context.ignored_components for part in relative.parts):
                    continue
                if path.is_symlink() or path.stat().st_mode & 0o444 == 0:
                    continue
                content = path.read_bytes()
                digest = sha256(content).hexdigest()
                assets.append(
                    AssetRecord(
                        asset_id=f"asset:{context.root_id}:{relative.as_posix()}:{digest[:12]}",
                        relative_path=relative,
                        sha256=digest,
                        kind=classify_asset(relative),
                        size_bytes=len(content),
                        source_root=context.root_id,
                    )
                )
        return sorted(assets, key=lambda record: (record.source_root, record.relative_path.as_posix()))
