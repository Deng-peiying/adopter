from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from cross_embodiment.errors import PackageError
from cross_embodiment.package.artifact import (
    build_package_artifact,
    extract_package_artifact,
    inspect_package_artifact,
)
from cross_embodiment.package.lifecycle import PackageLifecycle


def _package(root: Path, *, version: str = "1.2.3") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    config = root / "config"
    config.mkdir()
    mapping = config / "mapping.yaml"
    mapping.write_text("schema_version: mapping/v0.1\n", encoding="utf-8")
    digest = hashlib.sha256(mapping.read_bytes()).hexdigest()
    (root / "embodiment.yaml").write_text(
        "schema_version: embodiment/v0.2\nembodiment: {type: single_arm, dof: 1}\ndevices: []\n",
        encoding="utf-8",
    )
    (root / "package.yaml").write_text(
        f"""schema_version: hardware-package/v0.1
package: {{name: example/arm, version: {version}, vendor: Example, model: arm, type: robot}}
embodiment_manifest: embodiment.yaml
assets:
  interface_mapping:
    - {{format: yaml, path: config/mapping.yaml, digest: sha256:{digest}}}
backends:
  - id: mapped
    type: python
    entrypoint: example_vendor.backend:Adapter
    requirements:
      ros_distro: humble
      external_driver: example_arm_driver
defaults: {{backend: mapped}}
""",
        encoding="utf-8",
    )
    return root


def test_artifact_build_is_deterministic_and_excludes_generated_cache(tmp_path: Path) -> None:
    source = _package(tmp_path / "source")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "ignored.pyc").write_bytes(b"cache")
    first = tmp_path / "first.cepack"
    second = tmp_path / "second.cepack"

    record_a = build_package_artifact(source, first)
    record_b = build_package_artifact(source, second)

    assert first.read_bytes() == second.read_bytes()
    assert record_a == record_b
    assert record_a.package_name == "example/arm"
    assert record_a.package_version == "1.2.3"
    assert record_a.backends[0]["id"] == "mapped"
    assert record_a.external_requirements == {
        "mapped": {"external_driver": "example_arm_driver", "ros_distro": "humble"}
    }
    with zipfile.ZipFile(first) as archive:
        assert "package/__pycache__/ignored.pyc" not in archive.namelist()


def test_artifact_build_rejects_symlinks_and_invalid_assets(tmp_path: Path) -> None:
    source = _package(tmp_path / "source")
    (source / "unsafe").symlink_to("package.yaml")
    with pytest.raises(PackageError, match="symlink"):
        build_package_artifact(source, tmp_path / "bad.cepack")

    (source / "unsafe").unlink()
    (source / "config/mapping.yaml").write_text("changed: true\n", encoding="utf-8")
    with pytest.raises(Exception, match="digest mismatch"):
        build_package_artifact(source, tmp_path / "bad-asset.cepack")


def test_artifact_build_rejects_output_inside_source_tree(tmp_path: Path) -> None:
    source = _package(tmp_path / "source")
    with pytest.raises(PackageError, match="outside the package source"):
        build_package_artifact(source, source / "self.cepack")


def test_artifact_inspection_and_extraction_reject_tampering_and_unsafe_paths(
    tmp_path: Path,
) -> None:
    source = _package(tmp_path / "source")
    artifact = tmp_path / "package.cepack"
    expected = build_package_artifact(source, artifact)
    assert inspect_package_artifact(artifact) == expected

    destination = tmp_path / "extracted"
    assert extract_package_artifact(artifact, destination) == expected
    assert (destination / "package.yaml").is_file()

    unsafe = tmp_path / "unsafe.cepack"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("artifact.json", json.dumps(expected.to_dict()))
        archive.writestr("package/../../escape", "bad")
    with pytest.raises(PackageError, match="unsafe archive path"):
        extract_package_artifact(unsafe, tmp_path / "unsafe-output")

    tampered = tmp_path / "tampered.cepack"
    with zipfile.ZipFile(artifact) as source_archive, zipfile.ZipFile(tampered, "w") as target:
        for info in source_archive.infolist():
            data = source_archive.read(info.filename)
            if info.filename == "package/config/mapping.yaml":
                data = b"tampered: true\n"
            target.writestr(info, data)
    with pytest.raises(PackageError, match="digest mismatch"):
        extract_package_artifact(tampered, tmp_path / "tampered-output")


def test_install_records_backends_requirements_and_is_idempotent(tmp_path: Path) -> None:
    source = _package(tmp_path / "source")
    artifact = tmp_path / "arm.cepack"
    built = build_package_artifact(source, artifact)
    lifecycle = PackageLifecycle(tmp_path / "store")

    first = lifecycle.install(artifact)
    second = lifecycle.install(artifact)

    assert first == second
    assert first.package_name == "example/arm"
    assert first.version == "1.2.3"
    assert first.package_tree_digest == built.package_tree_digest
    assert first.artifact_digest.startswith("sha256:")
    assert first.backends[0]["entrypoint"] == "example_vendor.backend:Adapter"
    assert first.external_requirements["mapped"]["external_driver"] == "example_arm_driver"
    assert Path(first.package_root, "package.yaml").is_file()


def test_list_and_inspect_support_multiple_versions_and_detect_drift(tmp_path: Path) -> None:
    lifecycle = PackageLifecycle(tmp_path / "store")
    for version in ("1.2.3", "2.0.0"):
        artifact = tmp_path / f"arm-{version}.cepack"
        build_package_artifact(_package(tmp_path / f"source-{version}", version=version), artifact)
        lifecycle.install(artifact)

    records = lifecycle.list()
    assert [(item.package_name, item.version) for item in records] == [
        ("example/arm", "1.2.3"),
        ("example/arm", "2.0.0"),
    ]
    inspected = lifecycle.inspect("example/arm@1.2.3")
    assert inspected.version == "1.2.3"

    Path(inspected.package_root, "unexpected.txt").write_text("drift", encoding="utf-8")
    with pytest.raises(PackageError, match="digest"):
        lifecycle.inspect("example/arm@1.2.3")


def test_install_rejects_different_content_for_existing_name_version(tmp_path: Path) -> None:
    lifecycle = PackageLifecycle(tmp_path / "store")
    first_source = _package(tmp_path / "source-a")
    first = tmp_path / "first.cepack"
    build_package_artifact(first_source, first)
    lifecycle.install(first)

    second_source = _package(tmp_path / "source-b")
    mapping = second_source / "config/mapping.yaml"
    mapping.write_text("schema_version: mapping/v0.1\nvariant: b\n", encoding="utf-8")
    digest = hashlib.sha256(mapping.read_bytes()).hexdigest()
    manifest = second_source / "package.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            manifest.read_text(encoding="utf-8").split("digest: sha256:", 1)[1].split("}", 1)[0],
            digest,
        ),
        encoding="utf-8",
    )
    second = tmp_path / "second.cepack"
    build_package_artifact(second_source, second)

    with pytest.raises(PackageError, match="immutable"):
        lifecycle.install(second)


def test_install_rejects_version_that_can_escape_store_layout(tmp_path: Path) -> None:
    safe = tmp_path / "safe.cepack"
    build_package_artifact(_package(tmp_path / "source"), safe)
    artifact = tmp_path / "unsafe-version.cepack"
    with zipfile.ZipFile(safe) as source_archive, zipfile.ZipFile(artifact, "w") as target:
        for info in source_archive.infolist():
            data = source_archive.read(info.filename)
            if info.filename == "artifact.json":
                metadata = json.loads(data)
                metadata["package"]["version"] = "../escape"
                data = json.dumps(metadata).encode("utf-8")
            target.writestr(info, data)

    with pytest.raises(PackageError, match="version"):
        PackageLifecycle(tmp_path / "store").install(artifact)


def _installed(lifecycle: PackageLifecycle, tmp_path: Path, *, version: str = "1.2.3"):
    artifact = tmp_path / f"arm-{version}.cepack"
    build_package_artifact(_package(tmp_path / f"source-{version}", version=version), artifact)
    return lifecycle.install(artifact)


def _instance(path: Path, *, version: str = "1.2.3", external: Path | None = None) -> Path:
    connection = f"\nconnection:\n  vendor_runtime: {external}\n" if external else "\n"
    path.write_text(
        f"""schema_version: robot-instance/v0.1
instance: {{id: lab/arm01}}
robot: {{package: example/arm, version: {version}}}
backend: {{preferred: mapped}}
{connection}""",
        encoding="utf-8",
    )
    return path


def test_activate_and_use_resolve_installed_package_without_runtime_side_effects(
    tmp_path: Path,
) -> None:
    lifecycle = PackageLifecycle(tmp_path / "store")
    installed = _installed(lifecycle, tmp_path)
    activation = lifecycle.activate(
        "example/arm@1.2.3", _instance(tmp_path / "instance.yaml")
    )

    assert activation.instance_id == "lab/arm01"
    assert activation.package_tree_digest == installed.package_tree_digest
    assert activation.backend_id == "mapped"
    use = lifecycle.resolve_use("lab/arm01")
    assert use.package_root == Path(installed.package_root)
    assert use.manifest_path == Path(installed.package_root, "embodiment.yaml")
    assert use.backend_id == "mapped"
    assert use.backend_entrypoint == "example_vendor.backend:Adapter"
    assert use.connection == {"package_root": installed.package_root}


def test_activate_requires_exact_instance_package_and_version(tmp_path: Path) -> None:
    lifecycle = PackageLifecycle(tmp_path / "store")
    _installed(lifecycle, tmp_path)

    with pytest.raises(PackageError, match="does not match"):
        lifecycle.activate(
            "example/arm@1.2.3",
            _instance(tmp_path / "wrong.yaml", version="2.0.0"),
        )


def test_use_detects_package_drift(tmp_path: Path) -> None:
    lifecycle = PackageLifecycle(tmp_path / "store")
    installed = _installed(lifecycle, tmp_path)
    lifecycle.activate("example/arm@1.2.3", _instance(tmp_path / "instance.yaml"))
    Path(installed.package_root, "drift.txt").write_text("changed", encoding="utf-8")

    with pytest.raises(PackageError, match="digest"):
        lifecycle.resolve_use("lab/arm01")


def test_uninstall_refuses_active_package_then_removes_only_owned_files(tmp_path: Path) -> None:
    lifecycle = PackageLifecycle(tmp_path / "store")
    installed = _installed(lifecycle, tmp_path)
    external = tmp_path / "vendor-runtime"
    external.mkdir()
    marker = external / "driver.bin"
    marker.write_bytes(b"vendor")
    lifecycle.activate(
        "example/arm@1.2.3",
        _instance(tmp_path / "instance.yaml", external=external),
    )

    with pytest.raises(PackageError, match="active"):
        lifecycle.uninstall("example/arm@1.2.3")

    lifecycle.deactivate("lab/arm01")
    result = lifecycle.uninstall("example/arm@1.2.3")
    assert result.package_name == "example/arm"
    assert not Path(installed.package_root).exists()
    assert marker.read_bytes() == b"vendor"


def test_uninstall_one_version_preserves_another(tmp_path: Path) -> None:
    lifecycle = PackageLifecycle(tmp_path / "store")
    first = _installed(lifecycle, tmp_path, version="1.2.3")
    second = _installed(lifecycle, tmp_path, version="2.0.0")

    lifecycle.uninstall("example/arm@1.2.3")

    assert not Path(first.package_root).exists()
    assert lifecycle.inspect("example/arm@2.0.0") == second
