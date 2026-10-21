from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from cross_embodiment.hardware.manifest import load_manifest
from cross_embodiment.package.manifest import load_package_manifest
from cross_embodiment.onboarding.backend_fit import BackendCapabilityFit, BackendFitReport
from cross_embodiment.onboarding.capability import CapabilityCoverage
from cross_embodiment.onboarding.generator import PackageGenerator, PackageIdentity
from cross_embodiment.onboarding.evidence import EvidenceMatrix
from cross_embodiment.onboarding.inventory import AssetInventory
from cross_embodiment.onboarding.models import (
    CapabilityAssessment, CapabilityCandidate, EvidenceLevel, EvidenceRecord,
    IntegrationStage, MissingRequirement,
)


JOINTS = tuple(f"arm.right.joint.{i}" for i in range(7))
LIMITS = tuple((-2.0, 2.0) for _ in JOINTS)


def inputs(conflict: bool = False):
    state_semantics = {
        "binding_operation": "joint_state", "transport_kind": "ros2_subscription",
        "endpoint": "/wy/right_arm_state", "interface_type": "arm/msg/ArmState",
        "positions_field": "joint_angles", "stamp_field": "header.stamp",
        "mode_field": "arm_mode", "ready_values": [104], "fault_field": "arm_fault.fault_code",
        "unit": "radian", "ordered_joints": JOINTS, "joint_limits": LIMITS,
    }
    move_semantics = {
        "binding_operation": "joint_position", "transport_kind": "ros2_action",
        "endpoint": "/wy/right_arm_move_action", "interface_type": "arm/action/ArmMove",
        "timeout_s": 90.0, "target_field": "joint_angles", "target_unit": "radian",
        "constants": {"move_type": "MoveJ", "cart_pose": [0.0] * 6},
        "result_code_field": "error_code.value", "result_description_field": "error_description",
        "success_code": 0, "ordered_joints": JOINTS, "unit": "radian",
        "state_binding": "right_arm_joint_state", "arrival_tolerance_rad": 0.015,
        "settle_window_s": 1.0, "completion": ["terminal_result", "measured_arrival"],
    }
    candidates = (
        CapabilityCandidate("joint_position_state", ("state-evidence",), state_semantics),
        CapabilityCandidate("joint_position", ("move-evidence",), move_semantics),
    )
    assessments = (
        CapabilityAssessment(
            "joint_position_state", "native", ("state-evidence",),
            IntegrationStage(discovered=True),
            conflicts=("unit",) if conflict else (),
            candidate_valid=True, mapping_complete=True,
            execution_policy_complete=True,
        ),
        CapabilityAssessment(
            "joint_position", "native", ("move-evidence",),
            IntegrationStage(discovered=True),
            candidate_valid=True, mapping_complete=True,
            execution_policy_complete=True,
        ),
    )
    coverage = CapabilityCoverage(assessments, candidates, ("unmapped-left-arm",))
    backend = BackendFitReport((
        BackendCapabilityFit("joint_position_state", "ros2", "ros2_subscription", "joint_state"),
        BackendCapabilityFit("joint_position", "ros2", "ros2_action", "joint_position"),
    ), ())
    identity = PackageIdentity(
        package_name="generated/weiyi-right-arm", version="0.1.0", vendor="Weiyi",
        model="dual_o6_right_arm", device_id="right_arm", embodiment_type="single_arm",
        backend_id="ros2", backend_entrypoint="adapters.ros2.adapter:GeneratedAdapter",
        ros_distro="humble", os="linux", arch="x86_64",
    )
    records = tuple(EvidenceRecord(
        evidence_id=identifier, source_asset_ids=(), source_path=Path(f"raw/{identifier}.yaml"),
        claim_type="fixture", claims={}, provenance={"extractor": "fixture"},
        confidence_boundary="fixture", level=EvidenceLevel.DECLARED,
    ) for identifier in ("state-evidence", "move-evidence", "unmapped-left-arm"))
    evidence = EvidenceMatrix.build(AssetInventory((), (), ()), records)
    return coverage, evidence, backend, identity


def partial_policy_inputs():
    coverage, evidence, backend, identity = inputs()
    move = coverage.candidates[1]
    policy_fields = {
        "timeout_s", "arrival_tolerance_rad", "settle_window_s",
    }
    partial_move = CapabilityCandidate(
        move.capability_id,
        move.evidence_ids,
        {
            key: value for key, value in move.proposed_semantics.items()
            if key not in policy_fields
        },
    )
    partial_assessment = replace(
        coverage.assessments[1],
        status="unknown",
        missing=tuple(
            MissingRequirement(field, "runtime completion policy unresolved")
            for field in sorted(policy_fields)
        ),
        candidate_valid=True,
        mapping_complete=True,
        execution_policy_complete=False,
    )
    return (
        CapabilityCoverage(
            (coverage.assessments[0], partial_assessment),
            (coverage.candidates[0], partial_move),
            coverage.discovered_unmapped_evidence_ids,
        ),
        evidence,
        backend,
        identity,
    )


def test_generates_runtime_compatible_scoped_package(tmp_path: Path) -> None:
    coverage, evidence, backend, identity = inputs()
    generated = PackageGenerator.generate(coverage, evidence, backend, tmp_path / "out", identity)
    package = load_package_manifest(generated.package_yaml)
    manifest = load_manifest(generated.embodiment_yaml)
    mapping = yaml.safe_load(generated.mapping_yaml.read_text())

    assert package.name == "generated/weiyi-right-arm"
    assert [device["id"] for device in manifest.devices] == ["right_arm"]
    assert [joint["canonical_name"] for joint in manifest.devices[0]["joints"]] == list(JOINTS)
    assert package.backends[0].entrypoint == "adapters.ros2.adapter:GeneratedAdapter"
    assert (generated.root / "adapters/ros2/adapter.py").is_file()
    state = mapping["bindings"]["right_arm_joint_state"]
    move = mapping["bindings"]["right_arm_joint_position"]
    assert state["semantic"]["unit"] == "radian"
    assert state["decode"]["positions"] == "joint_angles"
    assert move["encode"]["constants"]["move_type"] == "MoveJ"
    assert move["encode"]["positions"]["field"] == "joint_angles"
    assert move["result"]["error_code"] == "error_code.value"
    assert move["completion"]["arrival_tolerance_rad"] == 0.015


def test_generation_is_deterministic_and_contains_no_absolute_vendor_paths(tmp_path: Path) -> None:
    coverage, evidence, backend, identity = inputs()
    first = PackageGenerator.generate(coverage, evidence, backend, tmp_path / "one", identity)
    second = PackageGenerator.generate(coverage, evidence, backend, tmp_path / "two", identity)
    files = ["package.yaml", "embodiment.yaml", "config/right_arm_ros2_mapping.yaml", "generation-provenance.yaml"]
    for relative in files:
        one = (first.root / relative).read_text()
        two = (second.root / relative).read_text()
        assert one == two
        assert str(tmp_path) not in one
    assert "state-evidence" in (first.root / "generation-provenance.yaml").read_text()


def test_refuses_conflicts_or_unknown_required_capabilities(tmp_path: Path) -> None:
    coverage, evidence, backend, identity = inputs(conflict=True)
    with pytest.raises(ValueError, match="conflict"):
        PackageGenerator.generate(coverage, evidence, backend, tmp_path / "conflict", identity)
    coverage, evidence, backend, identity = inputs()
    bad = CapabilityCoverage((replace(coverage.assessments[0], status="unknown"), coverage.assessments[1]), coverage.candidates, ())
    with pytest.raises(ValueError, match="not native"):
        PackageGenerator.generate(bad, evidence, backend, tmp_path / "unknown", identity)


def test_generates_non_executable_candidate_package_when_only_policy_is_unresolved(
    tmp_path: Path,
) -> None:
    partial, evidence, backend, identity = partial_policy_inputs()
    policy_fields = {
        "timeout_s", "arrival_tolerance_rad", "settle_window_s",
    }

    generated = PackageGenerator.generate_candidate(
        partial, evidence, backend, tmp_path / "candidate", identity,
    )
    package = load_package_manifest(generated.package_yaml)
    candidate = yaml.safe_load(generated.mapping_yaml.read_text())

    assert generated.package_status == "candidate"
    assert package.validation["candidate_only"] is True
    assert package.validation["live_execution_ready"] is False
    assert package.defaults == {}
    assert package.backends[0].entrypoint is None
    assert "interface_mapping" not in package.assets
    assert "interface_mapping_candidate" in package.assets
    assert candidate["schema_version"] == "interface-mapping-candidate/v0.1"
    move_binding = candidate["bindings"]["right_arm_joint_position"]
    assert move_binding["interface_mapped"] is True
    assert move_binding["completion_policy"]["status"] == "unresolved"
    assert set(move_binding["completion_policy"]["missing_fields"]) == policy_fields
    assert "timeout_s" not in move_binding["transport"]
    assert not (generated.root / "config/connection.yaml").exists()


def test_candidate_mapping_filename_is_derived_from_device_identity(
    tmp_path: Path,
) -> None:
    partial, evidence, backend, identity = partial_policy_inputs()
    generic_identity = replace(identity, device_id="primary_arm")
    move = partial.candidates[1]
    generic_move = replace(
        move,
        proposed_semantics={
            **move.proposed_semantics,
            "state_binding": "primary_arm_joint_state",
        },
    )
    generic_partial = CapabilityCoverage(
        partial.assessments,
        (partial.candidates[0], generic_move),
        partial.discovered_unmapped_evidence_ids,
    )

    generated = PackageGenerator.generate_candidate(
        generic_partial, evidence, backend, tmp_path / "candidate", generic_identity,
    )
    package = load_package_manifest(generated.package_yaml)

    assert generated.mapping_yaml.name == "primary_arm_ros2_mapping.candidate.yaml"
    assert package.assets["interface_mapping_candidate"][0].path == (
        "config/primary_arm_ros2_mapping.candidate.yaml"
    )


def test_generation_rejects_package_identity_device_relabeling(
    tmp_path: Path,
) -> None:
    partial, evidence, backend, identity = partial_policy_inputs()
    mismatched = replace(identity, device_id="primary_arm")

    with pytest.raises(ValueError, match="identity device"):
        PackageGenerator.generate_candidate(
            partial, evidence, backend, tmp_path / "candidate", mismatched,
        )

    complete, evidence, backend, identity = inputs()
    with pytest.raises(ValueError, match="identity device"):
        PackageGenerator.generate(
            complete,
            evidence,
            backend,
            tmp_path / "runtime",
            replace(identity, device_id="primary_arm"),
        )
