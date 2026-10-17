from __future__ import annotations

from pathlib import Path
import shutil

from cross_embodiment.onboarding.generator import PackageGenerator
from cross_embodiment.package.artifact import build_package_artifact
from cross_embodiment.package.lifecycle import PackageLifecycle
from tests.onboarding.test_package_generator import inputs


def test_generated_clean_room_package_completes_offline_lifecycle(tmp_path: Path) -> None:
    coverage, evidence, backend, identity = inputs()
    generated = PackageGenerator.generate(
        coverage, evidence, backend, tmp_path / "clean-room-v1", identity,
    )
    manifest = generated.package_yaml
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "cross_embodiment.driver.ros2_mapped:MappedRos2Adapter",
            "must_not_be_imported.backend:Adapter",
        ),
        encoding="utf-8",
    )
    second_root = tmp_path / "clean-room-v2"
    shutil.copytree(generated.root, second_root)
    second_manifest = second_root / "package.yaml"
    second_manifest.write_text(
        second_manifest.read_text(encoding="utf-8").replace(
            "version: 0.1.0", "version: 0.2.0", 1,
        ),
        encoding="utf-8",
    )

    artifacts = []
    for index, root in enumerate((generated.root, second_root), start=1):
        artifact = tmp_path / f"clean-room-{index}.cepack"
        build_package_artifact(root, artifact)
        artifacts.append(artifact)

    lifecycle = PackageLifecycle(tmp_path / "store")
    first = lifecycle.install(artifacts[0])
    second = lifecycle.install(artifacts[1])
    assert [(item.version, item.package_tree_digest) for item in lifecycle.list()] == [
        ("0.1.0", first.package_tree_digest),
        ("0.2.0", second.package_tree_digest),
    ]

    instance = tmp_path / "instance.yaml"
    instance.write_text(
        """schema_version: robot-instance/v0.1
instance: {id: lab/clean-room-right-arm}
robot: {package: generated/weiyi-right-arm, version: 0.1.0}
backend: {preferred: ros2_mapped}
connection: {domain_id: 7}
""",
        encoding="utf-8",
    )
    lifecycle.activate("generated/weiyi-right-arm@0.1.0", instance)
    use = lifecycle.resolve_use("lab/clean-room-right-arm")

    assert use.backend_entrypoint == "must_not_be_imported.backend:Adapter"
    assert use.connection["domain_id"] == 7
    assert use.connection["mapping_path"] == "config/right_arm_ros2_mapping.yaml"
    assert use.connection["package_root"] == first.package_root
    assert lifecycle.inspect("generated/weiyi-right-arm@0.2.0") == second
