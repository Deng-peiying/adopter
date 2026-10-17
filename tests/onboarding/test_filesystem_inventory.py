from __future__ import annotations

import json
import os
from pathlib import Path

from cross_embodiment.onboarding.inventory import InventoryBuilder


def test_inventory_is_stable_classifies_assets_and_excludes_noise(tmp_path: Path) -> None:
    root = tmp_path / "vendor"
    (root / "src").mkdir(parents=True)
    (root / "install" / "lib").mkdir(parents=True)
    (root / ".cache").mkdir()
    (root / "logs").mkdir()
    (root / "src" / "node.py").write_text("print('never import me')\n")
    (root / "install" / "lib" / "libdriver.so").write_bytes(b"\x7fELFdemo")
    (root / "package.xml").write_text("<package/>")
    (root / ".cache" / "ignored.bin").write_bytes(b"ignored")
    (root / "logs" / "run.log").write_text("ignored")

    first = InventoryBuilder().build((root,))
    second = InventoryBuilder().build((root,))

    assert first == second
    assert [str(record.relative_path) for record in first.assets] == sorted(
        str(record.relative_path) for record in first.assets
    )
    by_path = {str(item.relative_path): item for item in first.assets}
    assert by_path["src/node.py"].kind == "source"
    assert by_path["install/lib/libdriver.so"].kind == "binary"
    assert by_path["package.xml"].kind == "source"
    assert not any("ignored" in path for path in by_path)
    assert by_path["src/node.py"].sha256 == "d2f9ef6debf54b21055eb2ceb03f45ccfcbdbf0a95d0a13abad19f138221f55b"


def test_inventory_reports_symlinks_unreadable_and_duplicate_content(tmp_path: Path) -> None:
    root = tmp_path / "vendor"
    root.mkdir()
    (root / "a.txt").write_text("same")
    (root / "b.txt").write_text("same")
    unreadable = root / "private.txt"
    unreadable.write_text("private")
    unreadable.chmod(0)
    (root / "link.txt").symlink_to(root / "a.txt")
    try:
        inventory = InventoryBuilder().build((root,))
    finally:
        unreadable.chmod(0o600)

    assert any(issue.code == "symlink_skipped" for issue in inventory.issues)
    assert any(issue.code == "unreadable" for issue in inventory.issues)
    assert inventory.duplicate_digests
    duplicate_paths = set(inventory.duplicate_digests[0].relative_paths)
    assert duplicate_paths == {"a.txt", "b.txt"}


def test_inventory_serializes_schema_shaped_json(tmp_path: Path) -> None:
    root = tmp_path / "vendor"
    root.mkdir()
    (root / "README.md").write_text("vendor")
    inventory = InventoryBuilder().build((root,))
    target = tmp_path / "asset-inventory.json"
    inventory.write_json(target)
    data = json.loads(target.read_text())

    assert data["schema_version"] == "asset-inventory/v0.1"
    assert data["assets"][0]["relative_path"] == "README.md"
    assert data["assets"][0]["source_root"] == "vendor"
