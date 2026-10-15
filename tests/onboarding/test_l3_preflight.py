from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cross_embodiment.onboarding.generator import PackageGenerator
from cross_embodiment.onboarding.l3 import execute_generated_package_round_trip, preflight_generated_package
from cross_embodiment.protocol.types import CommandResult, JointState
from tests.onboarding.test_package_generator import inputs


class _Lifecycle:
    def __init__(self) -> None:
        self.connected = False
        self.stopped = False

    def connect(self) -> None:
        self.connected = True

    def stop(self) -> None:
        self.stopped = True


class _Robot:
    def __init__(self) -> None:
        self.lifecycle = _Lifecycle()
        self.reads = []

    def get_joint_state(self, device_id: str) -> JointState:
        self.reads.append(device_id)
        now = datetime(2026, 10, 15, tzinfo=timezone.utc)
        return JointState(
            device_id=device_id,
            positions={f"arm.right.joint.{index}": float(index) for index in range(7)},
            source_timestamp=now,
            received_at=now,
            status="ready",
            details={"backend_mode": 104, "backend_fault_code": 0},
        )

    def move_joints(self, device_id: str, positions: dict[str, float]) -> CommandResult:
        self.reads.append((device_id, dict(positions)))
        now = datetime(2026, 10, 15, tzinfo=timezone.utc)
        measured = JointState(
            device_id=device_id,
            positions=dict(positions),
            source_timestamp=now,
            received_at=now,
            status="ready",
        )
        return CommandResult(
            accepted=True,
            command_id=f"command-{len(self.reads)}",
            status="succeeded",
            backend_code=0,
            details={"backend_status": 4},
            dispatched=True,
            started_at=now,
            completed_at=now,
            final_joint_state=measured,
            arrival_confirmed=True,
            max_joint_error_rad=0.0001,
        )


def test_preflight_loads_only_explicit_generated_package_and_reads_state(tmp_path: Path) -> None:
    coverage, evidence, backend_fit, identity = inputs()
    root = tmp_path / "generated"
    generated = PackageGenerator.generate(coverage, evidence, backend_fit, root, identity)
    robot = _Robot()
    calls = []

    def connect_fn(adapter, manifest, **kwargs):
        calls.append((adapter, manifest, kwargs))
        return robot

    record = preflight_generated_package(root, "right_arm", connect_fn=connect_fn)

    assert record.package_root == root.resolve()
    assert record.mapping_path == generated.mapping_yaml.resolve()
    assert len(record.package_tree_sha256) == 64
    assert len(record.mapping_sha256) == 64
    assert record.backend_entrypoint == "cross_embodiment.driver.ros2_mapped:MappedRos2Adapter"
    assert record.state_sample["status"] == "ready"
    assert record.state_sample["positions"]["arm.right.joint.6"] == 6.0
    assert record.commands == ()
    assert record.motion_sent is False
    assert record.classification == "preflight_read_only"
    assert robot.reads == ["right_arm"]
    assert robot.lifecycle.connected and robot.lifecycle.stopped
    assert calls[0][2]["control_enabled"] is False
    assert calls[0][2]["dry_run"] is False
    assert calls[0][2]["connection"]["package_root"] == str(root.resolve())


def test_preflight_rejects_mapping_outside_explicit_package(tmp_path: Path) -> None:
    coverage, evidence, backend_fit, identity = inputs()
    root = tmp_path / "generated"
    PackageGenerator.generate(coverage, evidence, backend_fit, root, identity)
    (root / "config" / "connection.yaml").write_text("mapping_path: /tmp/old-package/mapping.yaml\n")
    try:
        preflight_generated_package(root, "right_arm", connect_fn=lambda *args, **kwargs: _Robot())
    except ValueError as exc:
        assert "inside the generated package" in str(exc)
    else:
        raise AssertionError("absolute/fallback mapping path was accepted")


def test_l3_round_trip_requires_authorization_and_records_both_sdk_moves(tmp_path: Path) -> None:
    coverage, evidence, backend_fit, identity = inputs()
    root = tmp_path / "generated"
    PackageGenerator.generate(coverage, evidence, backend_fit, root, identity)
    target = {f"arm.right.joint.{index}": float(index) + 0.1 for index in range(7)}

    try:
        execute_generated_package_round_trip(
            root, "right_arm", target, operator="robot", authorized=False,
            connect_fn=lambda *args, **kwargs: _Robot(),
        )
    except PermissionError as exc:
        assert "authorization" in str(exc).lower()
    else:
        raise AssertionError("L3 motion ran without explicit authorization")

    robot = _Robot()
    record = execute_generated_package_round_trip(
        root, "right_arm", target, operator="robot", authorized=True,
        connect_fn=lambda *args, **kwargs: robot,
    )

    assert record.classification == "passed"
    assert record.motion_sent is True
    assert len(record.commands) == 2
    assert record.commands[0]["operation"] == "probe"
    assert record.commands[0]["result"]["arrival_confirmed"] is True
    assert record.commands[1]["operation"] == "return"
    assert record.commands[1]["target"] == {
        f"arm.right.joint.{index}": float(index) for index in range(7)
    }
    assert record.commands[1]["result"]["backend_status"] == 4
    assert record.operator == "robot"
