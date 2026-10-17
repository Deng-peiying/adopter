from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Sequence

from .extractors.base import ScanContext
from .extractors.filesystem import FilesystemExtractor
from .models import AssetRecord


DEFAULT_IGNORED_COMPONENTS = frozenset(
    {".git", ".cache", ".pytest_cache", "__pycache__", "logs", "log"}
)


@dataclass(frozen=True)
class InventoryIssue:
    code: str
    relative_path: str
    detail: str


@dataclass(frozen=True)
class DuplicateDigest:
    sha256: str
    relative_paths: tuple[str, ...]


@dataclass(frozen=True)
class AssetInventory:
    assets: tuple[AssetRecord, ...]
    issues: tuple[InventoryIssue, ...]
    duplicate_digests: tuple[DuplicateDigest, ...]
    schema_version: str = "asset-inventory/v0.1"

    def write_json(self, path: Path) -> None:
        def asset(item: AssetRecord) -> dict[str, object]:
            value = asdict(item)
            value["relative_path"] = item.relative_path.as_posix()
            return value

        payload = {
            "schema_version": self.schema_version,
            "assets": [asset(item) for item in self.assets],
            "issues": [asdict(item) for item in self.issues],
            "duplicate_digests": [asdict(item) for item in self.duplicate_digests],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class InventoryBuilder:
    def __init__(self, ignored_components: frozenset[str] = DEFAULT_IGNORED_COMPONENTS):
        self._ignored_components = ignored_components
        self._extractor = FilesystemExtractor()

    def build(self, roots: Sequence[Path]) -> AssetInventory:
        assets: list[AssetRecord] = []
        issues: list[InventoryIssue] = []
        root_ids: set[str] = set()
        for root_value in roots:
            root = root_value.resolve()
            if not root.is_dir():
                raise ValueError(f"vendor root is not a directory: {root_value}")
            root_id = root.name
            if root_id in root_ids:
                raise ValueError(f"duplicate vendor root id: {root_id}")
            root_ids.add(root_id)
            for directory, dirnames, filenames in os.walk(root, followlinks=False):
                current = Path(directory)
                for name in sorted((*dirnames, *filenames)):
                    path = current / name
                    relative = path.relative_to(root).as_posix()
                    if path.is_symlink():
                        issues.append(InventoryIssue("symlink_skipped", relative, "symlinks are not followed"))
                    elif path.is_file() and path.stat().st_mode & 0o444 == 0:
                        issues.append(InventoryIssue("unreadable", relative, "file has no read bits"))
            context = ScanContext(root, root_id, self._ignored_components)
            assets.extend(self._extractor.scan(context))

        assets.sort(key=lambda item: (item.source_root, item.relative_path.as_posix()))
        by_digest: dict[str, list[str]] = {}
        for item in assets:
            by_digest.setdefault(item.sha256, []).append(item.relative_path.as_posix())
        duplicates = tuple(
            DuplicateDigest(digest, tuple(sorted(paths)))
            for digest, paths in sorted(by_digest.items())
            if len(paths) > 1
        )
        return AssetInventory(tuple(assets), tuple(sorted(issues, key=lambda x: x.relative_path)), duplicates)
