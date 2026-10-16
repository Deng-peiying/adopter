from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from cross_embodiment import Robot, RuntimeInfo
from cross_embodiment.errors import PackageError, SafetyViolation
from cross_embodiment.package.artifact import build_package_artifact
from cross_embodiment.package.lifecycle import PackageLifecycle
from cross_embodiment.runtime.installed import (
    create_robot_from_instance,
    resolve_installed_runtime,
)


def _write_runtime_package(
    root: Path,
    *,
    mapping_value: str | None = "config/mapping.yaml",
) -> Path:
    root.mkdir(parents=True)
    (root / "config").mkdir()
    (root / "runtime_fixture_backend.py").write_text(
        """from datetime import datetime, timezone

from cross_embodiment.protocol.types import CommandResult, RobotState, SafetyState


class Adapter:
    def __init__(self, manifest, *, connection, control_enabled, dry_run, manage_process=False):
        self.manifest = manifest
        self.connection = connection
        self.control_enabled = control_enabled
        self.dry_run = dry_run
        self.manage_process = manage_process
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.sent = []

    def connect(self):
        self.connect_calls += 1

    def disconnect(self):
        self.disconnect_calls += 1

    def get_state(self):
        return RobotState(
            timestamp=datetime.now(timezone.utc),
            joint_positions={"arm.joint.0": 0.0, "arm.joint.1": 0.0},
            safety=SafetyState(enabled=True),
        )

    def send_command(self, command):
        self.sent.append(command)
        return CommandResult(True, status="succeeded", dispatched=True)
""",
        encoding="utf-8",
    )
    (root / "embodiment.yaml").write_text(
        """schema_version: embodiment/v0.2
embodiment: {type: arm, dof: 2}
devices:
  - id: arm
    type: arm
    capabilities: [joint_state, joint_position]
    joints:
      - {canonical_name: arm.joint.0, unit: radian, limits: [-1.0, 1.0]}
      - {canonical_name: arm.joint.1, unit: radian, limits: [-1.0, 1.0]}
control:
  supported_modes:
    - {type: joint_position, target: arm, dimension: 2}
safety: {requires_enable: true}
""",
        encoding="utf-8",
    )

    config_lines = ["secret_token: must-not-leak"]
    assets = ""
    if mapping_value is not None:
        mapping = root / "config" / "mapping.yaml"
        mapping.write_text("schema_version: interface-mapping/v1\nbindings: []\n", encoding="utf-8")
        digest = sha256(mapping.read_bytes()).hexdigest()
        config_lines.insert(0, f"mapping_path: {mapping_value}")
        assets = f"""assets:
  interface_mapping:
    - {{format: yaml, path: config/mapping.yaml, digest: sha256:{digest}}}
"""
    (root / "config" / "connection.yaml").write_text(
        "\n".join(config_lines) + "\n", encoding="utf-8"
    )
    (root / "package.yaml").write_text(
        f"""schema_version: hardware-package/v0.1
package: {{name: example/runtime-arm, version: 1.0.0, vendor: Example, model: arm, type: robot}}
embodiment_manifest: embodiment.yaml
{assets}backends:
  - id: fixture
    type: python
    entrypoint: runtime_fixture_backend:Adapter
defaults: {{backend: fixture, config: config/connection.yaml}}
""",
        encoding="utf-8",
    )
    return root


def _install_and_activate(
    tmp_path: Path,
    *,
    mapping_value: str | None = "config/mapping.yaml",
) -> tuple[Path, str, object]:
    source = _write_runtime_package(tmp_path / "source", mapping_value=mapping_value)
    artifact = tmp_path / "runtime.cepack"
    build_package_artifact(source, artifact)
    store = tmp_path / "store"
    lifecycle = PackageLifecycle(store)
    installed = lifecycle.install(artifact)
    instance_id = "lab/arm01"
    instance = tmp_path / "instance.yaml"
    instance.write_text(
        f"""schema_version: robot-instance/v0.1
instance: {{id: {instance_id}}}
robot: {{package: example/runtime-arm, version: 1.0.0}}
backend: {{preferred: fixture}}
connection: {{site: test-cell}}
""",
        encoding="utf-8",
    )
    lifecycle.activate("example/runtime-arm@1.0.0", instance)
    return store, instance_id, installed


def test_resolve_installed_runtime_preserves_store_and_mapping_provenance(tmp_path: Path) -> None:
    store, instance_id, installed = _install_and_activate(tmp_path)

    resolved = resolve_installed_runtime(instance_id, store)

    mapping = Path(installed.package_root) / "config" / "mapping.yaml"
    assert resolved.package_root == Path(installed.package_root)
    assert resolved.info.instance_id == instance_id
    assert resolved.info.package_name == "example/runtime-arm"
    assert resolved.info.package_version == "1.0.0"
    assert resolved.info.package_tree_digest == installed.package_tree_digest
    assert resolved.info.mapping_path == mapping
    assert resolved.info.mapping_sha256 == sha256(mapping.read_bytes()).hexdigest()
    assert resolved.info.allow_motion is False
    assert "secret_token" not in resolved.info.to_dict()
    assert "must-not-leak" not in repr(resolved.info.to_dict())


def test_create_robot_is_disconnected_and_uses_read_only_runtime_options(tmp_path: Path) -> None:
    store, instance_id, _ = _install_and_activate(tmp_path)

    robot = create_robot_from_instance(instance_id, store=store)

    assert robot.runtime_info.instance_id == instance_id
    assert robot.runtime_info.allow_motion is False
    assert robot.adapter.control_enabled is False
    assert robot.adapter.dry_run is False
    assert robot.adapter.manage_process is False
    assert robot.adapter.connect_calls == 0
    assert robot.adapter.disconnect_calls == 0
    assert robot.adapter.connection["require_ros"] is True
    assert robot.adapter.connection["package_root"] == str(robot.runtime_info.package_root)


def test_default_store_uses_environment_without_connecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, instance_id, _ = _install_and_activate(tmp_path)
    monkeypatch.setenv("CROSS_EMBODIMENT_STORE", str(store))

    robot = create_robot_from_instance(instance_id)

    assert robot.runtime_info.instance_id == instance_id
    assert robot.adapter.connect_calls == 0


@pytest.mark.parametrize("mapping_value", ["../outside.yaml", "/tmp/outside.yaml"])
def test_resolver_rejects_mapping_paths_outside_installed_package(
    tmp_path: Path, mapping_value: str,
) -> None:
    store, instance_id, _ = _install_and_activate(tmp_path, mapping_value=mapping_value)

    with pytest.raises(PackageError, match="mapping path"):
        resolve_installed_runtime(instance_id, store)


def test_resolver_rejects_installed_package_drift_without_fallback(tmp_path: Path) -> None:
    store, instance_id, installed = _install_and_activate(tmp_path)
    Path(installed.package_root, "drift.txt").write_text("changed", encoding="utf-8")

    with pytest.raises(PackageError, match="digest"):
        resolve_installed_runtime(instance_id, store)


def test_backend_without_mapping_has_none_mapping_provenance(tmp_path: Path) -> None:
    store, instance_id, _ = _install_and_activate(tmp_path, mapping_value=None)

    resolved = resolve_installed_runtime(instance_id, store)

    assert resolved.info.mapping_path is None
    assert resolved.info.mapping_sha256 is None


def test_public_factory_exports_runtime_info_and_stays_disconnected(tmp_path: Path) -> None:
    store, instance_id, _ = _install_and_activate(tmp_path)

    robot = Robot.from_instance(instance_id, store=store)

    assert isinstance(robot.runtime_info, RuntimeInfo)
    assert robot.runtime_info.instance_id == instance_id
    assert robot.adapter.connect_calls == 0


def test_public_factory_enforces_motion_permission_for_move_and_command(tmp_path: Path) -> None:
    store, instance_id, _ = _install_and_activate(tmp_path)
    target = {"arm.joint.0": 0.1, "arm.joint.1": -0.1}
    read_only = Robot.from_instance(instance_id, store=store)
    # The SDK permission is authoritative even if a Backend exposes or mutates
    # its own similarly named flag.
    read_only.adapter.control_enabled = True

    with pytest.raises(SafetyViolation, match="disabled"):
        read_only.move_joints("arm", target)
    with pytest.raises(SafetyViolation, match="disabled"):
        from cross_embodiment.protocol.types import Action, ActionSpec

        read_only.command(Action(ActionSpec("joint_position", "arm", dimension=2), {"positions": target}))
    assert read_only.adapter.sent == []

    writable = Robot.from_instance(instance_id, store=store, allow_motion=True)
    result = writable.move_joints("arm", target)
    assert result.status == "succeeded"
    assert writable.adapter.sent[0].payload["positions"] == target
